"""Automatic technical-signal watchlist for NUMBER ONE TRADER AI.
Signals are informational only; this module never places orders.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from engine import ASSETS, analyze_asset

DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")
MARKET = "العملات الرقمية"
TIMEFRAME = "5 دقائق"
SCAN_SECONDS = 300
ALERT_COOLDOWN_HOURS = 4
MIN_CONFIDENCE = 80


def _connect():
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def init_signal_monitor():
    with _connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS signal_watchers (
                chat_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_scan TEXT
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS signal_alert_state (
                chat_id INTEGER NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                last_alert TEXT NOT NULL,
                PRIMARY KEY(chat_id, symbol)
            )
        """)


def set_signal_watch(chat_id: int, enabled: bool):
    init_signal_monitor()
    with _connect() as con:
        con.execute("""
            INSERT INTO signal_watchers(chat_id, enabled, last_scan)
            VALUES(?,?,NULL)
            ON CONFLICT(chat_id) DO UPDATE SET enabled=excluded.enabled
        """, (chat_id, int(enabled)))


def signal_watch_enabled(chat_id: int) -> bool:
    init_signal_monitor()
    with _connect() as con:
        row = con.execute(
            "SELECT enabled FROM signal_watchers WHERE chat_id=?", (chat_id,)
        ).fetchone()
    return bool(row and row["enabled"])


def scan_signal_watchers():
    """Scan opted-in chats and return (chat_id, message) notifications."""
    init_signal_monitor()
    now = datetime.now(timezone.utc)
    with _connect() as con:
        watchers = con.execute(
            "SELECT chat_id,last_scan FROM signal_watchers WHERE enabled=1"
        ).fetchall()

    notices = []
    assets = list(ASSETS.get(MARKET, {}).items())
    for watcher in watchers:
        chat_id = watcher["chat_id"]
        if watcher["last_scan"]:
            try:
                previous = datetime.fromisoformat(watcher["last_scan"])
                if (now - previous).total_seconds() < SCAN_SECONDS:
                    continue
            except ValueError:
                pass

        with _connect() as con:
            con.execute(
                "UPDATE signal_watchers SET last_scan=? WHERE chat_id=?",
                (now.isoformat(), chat_id),
            )

        for asset, symbol in assets:
            try:
                signal = analyze_asset(
                    asset, symbol, MARKET, TIMEFRAME, "الإشارات القوية فقط"
                )
                if not signal or signal["confidence"] < MIN_CONFIDENCE:
                    continue
                with _connect() as con:
                    old = con.execute(
                        "SELECT direction,last_alert FROM signal_alert_state "
                        "WHERE chat_id=? AND symbol=?",
                        (chat_id, symbol),
                    ).fetchone()

                    should_alert = old is None
                    if old:
                        try:
                            last_alert = datetime.fromisoformat(old["last_alert"])
                            cooldown_done = now - last_alert >= timedelta(hours=ALERT_COOLDOWN_HOURS)
                        except ValueError:
                            cooldown_done = True
                        should_alert = old["direction"] != signal["direction"] or cooldown_done

                    if not should_alert:
                        continue

                    con.execute("""
                        INSERT INTO signal_alert_state(chat_id,symbol,direction,last_alert)
                        VALUES(?,?,?,?)
                        ON CONFLICT(chat_id,symbol) DO UPDATE SET
                            direction=excluded.direction,last_alert=excluded.last_alert
                    """, (chat_id, symbol, signal["direction"], now.isoformat()))

                arrow = "🟢 صعود" if signal["direction"] == "صعود" else "🔴 هبوط"
                notices.append((chat_id,
                    "📡 إشارة سوق تلقائية جديدة — محاكاة/معلومات فقط\n"
                    f"الأصل: {asset} ({symbol})\n"
                    f"الاتجاه: {arrow}\n"
                    f"توافق المؤشرات: {signal['confidence']}%\n"
                    f"السعر المرجعي: {signal['entry']:.6g}\n"
                    f"وقف حسابي: {signal['stop_loss']:.6g}\n"
                    f"هدف حسابي: {signal['take_profit']:.6g}\n"
                    f"الفاصل: {TIMEFRAME} | المصدر: {signal['source']}\n"
                    f"الأسباب: {signal['reasons']}\n"
                    "هذه قراءة مؤشرات وليست احتمال ربح أو توصية مالية."))
            except Exception as exc:
                print(f"Signal scan failed for {symbol}: {type(exc).__name__}")
    return notices
