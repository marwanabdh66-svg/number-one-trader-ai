"""Paper-only autonomous trading simulator for NUMBER ONE TRADER AI.

This module NEVER sends orders to a broker or exchange. It simulates trades using
public market data and persists sessions/trades in SQLite.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from engine import ASSETS, analyze_asset, fetch_market_data

DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")
FEE_RATE = 0.0005  # estimated simulated fee per side; not a live broker quote
MIN_CONFIDENCE = 80
SCAN_INTERVAL_SECONDS = 300
CRYPTO_MARKET = "العملات الرقمية"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@contextmanager
def _db():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_auto_db() -> None:
    with _db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS auto_sessions (
            chat_id INTEGER PRIMARY KEY,
            initial_capital REAL NOT NULL,
            balance REAL NOT NULL,
            duration_hours INTEGER NOT NULL,
            risk_pct REAL NOT NULL,
            max_daily_loss_pct REAL NOT NULL DEFAULT 3.0,
            started_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            status TEXT NOT NULL,
            last_scan TEXT,
            day_key TEXT NOT NULL,
            day_start_balance REAL NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS auto_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            asset TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            quantity REAL NOT NULL,
            notional REAL NOT NULL,
            status TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            pnl REAL,
            close_reason TEXT
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_auto_trades_open ON auto_trades(chat_id,status)")


def start_session(chat_id: int, capital: float, duration_hours: int, risk_pct: float, max_daily_loss_pct: float = 3.0) -> None:
    if capital <= 0 or duration_hours not in (1, 3, 6, 12, 24) or risk_pct not in (0.5, 1.0) or max_daily_loss_pct not in (2.0, 3.0, 5.0):
        raise ValueError("إعدادات تشغيل غير صالحة")
    now = _now()
    day_key = now.date().isoformat()
    with _db() as con:
        existing = con.execute("SELECT status FROM auto_sessions WHERE chat_id=?", (chat_id,)).fetchone()
        if existing and existing["status"] == "running":
            raise ValueError("لديك جلسة تداول تجريبية تعمل بالفعل")
        con.execute("""INSERT INTO auto_sessions
            (chat_id,initial_capital,balance,duration_hours,risk_pct,max_daily_loss_pct,
             started_at,ends_at,status,last_scan,day_key,day_start_balance,updated_at)
            VALUES(?,?,?,?,?,?,?,?,'running',NULL,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET
            initial_capital=excluded.initial_capital,balance=excluded.balance,
            duration_hours=excluded.duration_hours,risk_pct=excluded.risk_pct,
            max_daily_loss_pct=excluded.max_daily_loss_pct,started_at=excluded.started_at,
            ends_at=excluded.ends_at,status='running',last_scan=NULL,day_key=excluded.day_key,
            day_start_balance=excluded.day_start_balance,updated_at=excluded.updated_at""",
            (chat_id, capital, capital, duration_hours, risk_pct, max_daily_loss_pct, _iso(now),
             _iso(now + timedelta(hours=duration_hours)), day_key, capital, _iso(now)))
        

def _close_open_positions(chat_id: int, reason: str) -> list[str]:
    messages = []
    with _db() as con:
        trades = con.execute("SELECT * FROM auto_trades WHERE chat_id=? AND status='open'", (chat_id,)).fetchall()
    for trade in trades:
        price = float(trade["entry"])
        try:
            frame, _ = fetch_market_data(trade["symbol"], "1 دقيقة")
            if not frame.empty:
                price = float(frame.iloc[-1]["close"])
        except Exception:
            pass
        with _db() as con:
            messages.append(_close_trade(con, trade, price, reason))
    return messages


def stop_session(chat_id: int) -> bool:
    with _db() as con:
        row = con.execute("SELECT status FROM auto_sessions WHERE chat_id=?", (chat_id,)).fetchone()
    if not row or row["status"] != "running":
        return False
    _close_open_positions(chat_id, "إغلاق عند إيقاف الجلسة")
    with _db() as con:
        con.execute("UPDATE auto_sessions SET status='stopped',updated_at=? WHERE chat_id=? AND status='running'",
                    (_iso(_now()), chat_id))
    return True


def get_session(chat_id: int) -> dict[str, Any] | None:
    with _db() as con:
        row = con.execute("SELECT * FROM auto_sessions WHERE chat_id=?", (chat_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["open_trades"] = con.execute(
            "SELECT COUNT(*) FROM auto_trades WHERE chat_id=? AND status='open'", (chat_id,)
        ).fetchone()[0]
        result["closed_trades"] = con.execute(
            "SELECT COUNT(*) FROM auto_trades WHERE chat_id=? AND status='closed'", (chat_id,)
        ).fetchone()[0]
        result["realized_pnl"] = con.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM auto_trades WHERE chat_id=? AND status='closed'", (chat_id,)
        ).fetchone()[0]
        utc_day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        result["daily_realized_pnl"] = con.execute(
            "SELECT COALESCE(SUM(pnl),0) FROM auto_trades "
            "WHERE chat_id=? AND status='closed' AND closed_at>=?",
            (chat_id, utc_day_start)
        ).fetchone()[0]
        return result


def _close_trade(con, trade, price: float, reason: str) -> str:
    direction = trade["direction"]
    gross = (price - trade["entry"]) * trade["quantity"]
    if direction == "هبوط":
        gross = -gross
    fees = (trade["notional"] + abs(price * trade["quantity"])) * FEE_RATE
    pnl = gross - fees
    con.execute("""UPDATE auto_trades SET status='closed',closed_at=?,exit_price=?,pnl=?,close_reason=?
                   WHERE id=? AND status='open'""",
                (_iso(_now()), price, pnl, reason, trade["id"]))
    con.execute("UPDATE auto_sessions SET balance=balance+?,updated_at=? WHERE chat_id=?",
                (pnl, _iso(_now()), trade["chat_id"]))
    return f"إغلاق تجريبي: {trade['asset']} | {reason} | النتيجة {pnl:+.2f}"


def run_cycle() -> list[tuple[int, str]]:
    """Run one bounded scan cycle; returns Telegram notifications."""
    init_auto_db()
    notices: list[tuple[int, str]] = []
    now = _now()
    with _db() as con:
        sessions = con.execute("SELECT * FROM auto_sessions WHERE status='running'").fetchall()

    for session in sessions:
        chat_id = session["chat_id"]
        ends_at = datetime.fromisoformat(session["ends_at"])
        if now >= ends_at:
            _close_open_positions(chat_id, "إغلاق عند انتهاء المدة")
            with _db() as con:
                con.execute("UPDATE auto_sessions SET status='stopped',updated_at=? WHERE chat_id=?",
                            (_iso(now), chat_id))
            notices.append((chat_id, "⏱️ انتهت مدة التداول التجريبي. أُغلقت الصفقات الافتراضية المتبقية وفق آخر سعر متاح، وتوقف النظام. راجع حالة التداول لمعرفة النتيجة."))
            continue

        day_key = now.date().isoformat()
        if session["day_key"] != day_key:
            with _db() as con:
                con.execute("UPDATE auto_sessions SET day_key=?,day_start_balance=balance WHERE chat_id=?",
                            (day_key, chat_id))

        # Check existing simulated positions using the latest available candle.
        with _db() as con:
            open_trades = con.execute(
                "SELECT * FROM auto_trades WHERE chat_id=? AND status='open'", (chat_id,)
            ).fetchall()
        unrealized_pnl = 0.0
        for trade in open_trades:
            try:
                frame, _ = fetch_market_data(trade["symbol"], "1 دقيقة")
                if frame.empty:
                    continue
                candle = frame.iloc[-1]
                high, low, close = float(candle["high"]), float(candle["low"]), float(candle["close"])
                exit_price = None
                reason = ""
                if trade["direction"] == "صعود":
                    if low <= trade["stop_loss"]:
                        exit_price, reason = trade["stop_loss"], "وقف الخسارة"
                    elif high >= trade["take_profit"]:
                        exit_price, reason = trade["take_profit"], "جني الهدف"
                else:
                    if high >= trade["stop_loss"]:
                        exit_price, reason = trade["stop_loss"], "وقف الخسارة"
                    elif low <= trade["take_profit"]:
                        exit_price, reason = trade["take_profit"], "جني الهدف"
                if exit_price is not None:
                    with _db() as con:
                        msg = _close_trade(con, trade, exit_price, reason)
                    notices.append((chat_id, msg))
                else:
                    floating = (close - float(trade["entry"])) * float(trade["quantity"])
                    if trade["direction"] == "هبوط":
                        floating = -floating
                    unrealized_pnl += floating - (
                        float(trade["notional"]) + abs(close * float(trade["quantity"]))
                    ) * FEE_RATE
            except Exception:
                continue

        # Daily loss circuit breaker includes realized and floating losses.
        current = get_session(chat_id)
        if not current or current["status"] != "running":
            continue
        daily_floor = current["day_start_balance"] * (1 - current["max_daily_loss_pct"] / 100)
        daily_equity = float(current["balance"]) + unrealized_pnl
        if daily_equity <= daily_floor:
            _close_open_positions(chat_id, "إغلاق حماية عند حد الخسارة اليومية")
            with _db() as con:
                con.execute("UPDATE auto_sessions SET status='stopped',updated_at=? WHERE chat_id=? AND status='running'",
                            (_iso(_now()), chat_id))
            notices.append((chat_id,
                f"🛑 أوقف حارس رأس المال المحاكاة تلقائياً بعد بلوغ حد الخسارة اليومية "
                f"({current['max_daily_loss_pct']}%). لن تُفتح صفقات جديدة في هذه الجلسة."))
            continue

        last_scan = current.get("last_scan")
        if last_scan:
            try:
                if (now - datetime.fromisoformat(last_scan)).total_seconds() < SCAN_INTERVAL_SECONDS:
                    continue
            except ValueError:
                pass
        with _db() as con:
            con.execute("UPDATE auto_sessions SET last_scan=?,updated_at=? WHERE chat_id=?",
                        (_iso(now), _iso(now), chat_id))

        # Conservative MVP: one open simulated position maximum; crypto assets only.
        with _db() as con:
            count = con.execute("SELECT COUNT(*) FROM auto_trades WHERE chat_id=? AND status='open'",
                                (chat_id,)).fetchone()[0]
        if count:
            continue
        if current["balance"] <= 0:
            stop_session(chat_id)
            notices.append((chat_id, "🛑 توقف الحساب التجريبي لأن الرصيد المحاكى لم يعد كافياً."))
            continue

        candidates = []
        for asset, symbol in ASSETS.get(CRYPTO_MARKET, {}).items():
            try:
                signal = analyze_asset(asset, symbol, CRYPTO_MARKET, "5 دقائق", "الإشارات القوية فقط")
                if signal and signal["confidence"] >= MIN_CONFIDENCE:
                    candidates.append(signal)
            except Exception:
                continue
        if not candidates:
            continue
        signal = max(candidates, key=lambda item: item["confidence"])
        entry = float(signal["entry"])
        stop = float(signal["stop_loss"])
        target = float(signal["take_profit"])
        risk_distance = abs(entry - stop)
        if risk_distance <= 0 or entry <= 0:
            continue
        risk_cash = current["balance"] * (current["risk_pct"] / 100)
        quantity = risk_cash / risk_distance
        notional = quantity * entry
        # No leverage in the simulator: never allocate more than available balance.
        if notional > current["balance"]:
            quantity = current["balance"] / entry
            notional = current["balance"]
        if quantity <= 0:
            continue
        with _db() as con:
            con.execute("""INSERT INTO auto_trades
                (chat_id,asset,symbol,direction,entry,stop_loss,take_profit,quantity,notional,
                 status,opened_at) VALUES(?,?,?,?,?,?,?,?,?,'open',?)""",
                (chat_id, signal["asset"], signal["symbol"], signal["direction"], entry,
                 stop, target, quantity, notional, _iso(now)))
        notices.append((chat_id,
            f"🧪 فتح صفقة تجريبية: {signal['asset']} ({signal['symbol']})\n"
            f"الاتجاه: {signal['direction']} | تقييم المؤشرات: {signal['confidence']}%\n"
            f"دخول افتراضي: {entry:.6g}\nوقف افتراضي: {stop:.6g}\nهدف افتراضي: {target:.6g}\n"
            f"المخاطرة المستهدفة: {current['risk_pct']}% من الرصيد المحاكى."))
    return notices


def format_status(chat_id: int) -> str:
    data = get_session(chat_id)
    if not data:
        return "لا توجد جلسة تداول آلي محفوظة."
    remaining = max(0, (datetime.fromisoformat(data["ends_at"]) - _now()).total_seconds())
    hours, rem = divmod(int(remaining), 3600)
    minutes = rem // 60
    state = "🟢 يعمل تجريبياً" if data["status"] == "running" else "⚪ متوقف"
    return (f"🤖 حالة NUMBER ONE TRADER AI: {state}\n"
            f"الرصيد التجريبي: {data['balance']:.2f}\n"
            f"النتيجة المحققة: {data['realized_pnl']:+.2f}\n"
            f"صفقات مفتوحة: {data['open_trades']} | مغلقة: {data['closed_trades']}\n"
            f"المخاطرة لكل صفقة: {data['risk_pct']}%\n"
            f"حد الخسارة اليومية: {data['max_daily_loss_pct']}%\n"
            f"نتيجة اليوم المحققة: {data['daily_realized_pnl']:+.2f}\n"
            f"الوقت المتبقي: {hours} ساعة و{minutes} دقيقة\n"
            "🛡️ الحماية تراقب الخسائر المحققة والعائمة عند توفر بيانات السعر.\n"
            "⚠️ محاكاة فقط؛ لا توجد أموال حقيقية أو أوامر إلى وسيط تداول.")



def get_trade_history(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    """Return the latest simulated trades for one Telegram chat."""
    safe_limit = max(1, min(int(limit), 25))
    with _db() as con:
        rows = con.execute(
            "SELECT * FROM auto_trades WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]
