"""Free manual trading journal, risk calculator and performance reports."""
from __future__ import annotations

import os
import math
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")


def _db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con


def init_trading_tools():
    con = _db()
    con.execute("""CREATE TABLE IF NOT EXISTS manual_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        asset TEXT NOT NULL,
        side TEXT NOT NULL,
        entry REAL NOT NULL,
        exit REAL NOT NULL,
        pnl REAL NOT NULL,
        created_at TEXT NOT NULL
    )""")
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_manual_trades_user ON manual_trades(chat_id, id)"
    )
    con.commit()
    con.close()


def add_trade(chat_id: int, asset: str, side: str, entry: float,
              exit_price: float, pnl: float) -> int:
    asset = str(asset).strip()[:32]
    if not asset:
        raise ValueError("اكتب اسم الأصل أو الزوج.")
    if side not in ("شراء", "بيع"):
        raise ValueError("اتجاه الصفقة غير صحيح.")
    if not all(math.isfinite(float(x)) for x in (entry, exit_price, pnl)):
        raise ValueError("أدخل أرقاماً صحيحة ومحدودة.")
    if entry <= 0 or exit_price <= 0:
        raise ValueError("سعر الدخول والخروج يجب أن يكونا أكبر من صفر.")
    con = _db()
    cur = con.execute(
        """INSERT INTO manual_trades(chat_id,asset,side,entry,exit,pnl,created_at)
        VALUES(?,?,?,?,?,?,?)""",
        (chat_id, asset, side, float(entry), float(exit_price), float(pnl),
         datetime.now(timezone.utc).isoformat(timespec="seconds")),
    )
    trade_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return trade_id


def get_trades(chat_id: int, limit: int = 10):
    con = _db()
    rows = con.execute(
        "SELECT * FROM manual_trades WHERE chat_id=? ORDER BY id DESC LIMIT ?",
        (chat_id, max(1, min(int(limit), 50))),
    ).fetchall()
    con.close()
    return rows


def get_performance(chat_id: int) -> dict:
    con = _db()
    row = con.execute(
        """SELECT COUNT(*) AS total,
        SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
        SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) AS losses,
        SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) AS breakeven,
        COALESCE(SUM(pnl), 0) AS net,
        COALESCE(AVG(pnl), 0) AS average,
        COALESCE(MAX(pnl), 0) AS best,
        COALESCE(MIN(pnl), 0) AS worst
        FROM manual_trades WHERE chat_id=?""",
        (chat_id,),
    ).fetchone()
    con.close()
    total = int(row["total"] or 0)
    wins = int(row["wins"] or 0)
    return {
        "total": total,
        "wins": wins,
        "losses": int(row["losses"] or 0),
        "breakeven": int(row["breakeven"] or 0),
        "net": float(row["net"] or 0),
        "average": float(row["average"] or 0),
        "best": float(row["best"] or 0),
        "worst": float(row["worst"] or 0),
        "win_rate": (wins / total * 100) if total else 0.0,
    }


def calculate_risk(capital: float, risk_percent: float, stop_percent: float) -> dict:
    capital = float(capital)
    risk_percent = float(risk_percent)
    stop_percent = float(stop_percent)
    if not all(math.isfinite(x) for x in (capital, risk_percent, stop_percent)):
        raise ValueError("تأكد من إدخال أرقام صحيحة.")
    if capital <= 0:
        raise ValueError("رأس المال يجب أن يكون أكبر من صفر.")
    if not 0 < risk_percent <= 10:
        raise ValueError("نسبة المخاطرة يجب أن تكون أكبر من صفر وحتى 10%.")
    if not 0 < stop_percent <= 100:
        raise ValueError("مسافة وقف الخسارة يجب أن تكون أكبر من صفر وحتى 100%.")
    risk_amount = capital * risk_percent / 100
    position_size = risk_amount / (stop_percent / 100)
    return {
        "risk_amount": risk_amount,
        "position_size": position_size,
        "capital": capital,
        "risk_percent": risk_percent,
        "stop_percent": stop_percent,
    }


def calculate_payout_edge(payout_percent: float, win_rate_percent: float,
                          drawdown_percent: float = 0.0) -> dict:
    """Calculate binary-payout break-even and equal-stake expectancy."""
    payout = float(payout_percent)
    win_rate = float(win_rate_percent)
    drawdown = float(drawdown_percent)
    if not all(math.isfinite(x) for x in (payout, win_rate, drawdown)):
        raise ValueError("أدخل أرقاماً صحيحة.")
    if not 1 <= payout <= 500:
        raise ValueError("نسبة العائد يجب أن تكون بين 1% و500%.")
    if not 0 <= win_rate <= 100:
        raise ValueError("نسبة الفوز يجب أن تكون بين 0% و100%.")
    if not 0 <= drawdown < 100:
        raise ValueError("نسبة التراجع يجب أن تكون من 0% إلى أقل من 100%.")
    breakeven = 100.0 / (1.0 + payout / 100.0)
    expected_per_100 = 100.0 * ((win_rate / 100.0 * payout) - (1.0 - win_rate / 100.0))
    recovery = (drawdown / (100.0 - drawdown) * 100.0) if drawdown else 0.0
    return {
        "payout_percent": payout,
        "win_rate_percent": win_rate,
        "draw_even_win_rate": breakeven,
        "expected_per_100_stakes": expected_per_100,
        "drawdown_percent": drawdown,
        "recovery_percent": recovery,
        "edge_positive": win_rate > breakeven,
    }
