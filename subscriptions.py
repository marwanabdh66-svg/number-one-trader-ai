"""Trial and manual PRO subscription management for NUMBER ONE TRADER AI."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")
OWNER_ID = os.getenv("OWNER_TELEGRAM_ID", "").strip()
TRIAL_DAYS = int(os.getenv("PRO_TRIAL_DAYS", "1"))
TRIAL_DAILY_LIMIT = int(os.getenv("PRO_TRIAL_DAILY_LIMIT", "10000"))
PRO_PAYMENT_INSTRUCTIONS = os.getenv("PRO_PAYMENT_INSTRUCTIONS", "").strip()
PRO_PRICE_TEXT = os.getenv("PRO_PRICE_TEXT", "تواصل مع إدارة NUMBER ONE لمعرفة السعر ووسيلة الدفع.")

def _db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def _now():
    return datetime.now(timezone.utc)

def _parse(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None

def init_subscriptions():
    con = _db()
    con.execute("""CREATE TABLE IF NOT EXISTS subscription_users (
        chat_id INTEGER PRIMARY KEY,
        trial_started TEXT NOT NULL,
        pro_until TEXT,
        daily_date TEXT,
        daily_count INTEGER NOT NULL DEFAULT 0
    )""")
    con.execute("""CREATE TABLE IF NOT EXISTS pro_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        payment_method TEXT
    )""")
    columns = {row["name"] for row in con.execute("PRAGMA table_info(pro_requests)").fetchall()}
    if "payment_method" not in columns:
        con.execute("ALTER TABLE pro_requests ADD COLUMN payment_method TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS subscription_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    migrated = con.execute("SELECT value FROM subscription_settings WHERE key='full_24h_trial_v1'").fetchone()
    if migrated is None:
        # Grant existing non-PRO users one clean 24-hour trial under the new policy.
        con.execute("UPDATE subscription_users SET trial_started=? WHERE pro_until IS NULL OR pro_until<=?",
                    (_now().isoformat(), _now().isoformat()))
        con.execute("INSERT INTO subscription_settings(key,value) VALUES('full_24h_trial_v1','done')")
    con.commit()
    con.close()

def ensure_user(chat_id: int):
    con = _db()
    row = con.execute("SELECT chat_id FROM subscription_users WHERE chat_id=?", (chat_id,)).fetchone()
    if row is None:
        con.execute("INSERT INTO subscription_users(chat_id, trial_started) VALUES(?,?)",
                    (chat_id, _now().isoformat()))
        con.commit()
    con.close()

def access_status(chat_id: int) -> dict:
    if OWNER_ID and str(chat_id) == OWNER_ID:
        return {"tier": "owner", "allowed": True, "remaining": None, "days_left": None}
    ensure_user(chat_id)
    con = _db()
    row = con.execute("SELECT * FROM subscription_users WHERE chat_id=?", (chat_id,)).fetchone()
    con.close()
    now = _now()
    pro_until = _parse(row["pro_until"])
    if pro_until and pro_until > now:
        return {"tier": "pro", "allowed": True, "remaining": None,
                "days_left": max(1, (pro_until.date() - now.date()).days)}
    trial_started = _parse(row["trial_started"])
    trial_end = trial_started + timedelta(days=TRIAL_DAYS)
    if now < trial_end:
        # The one-day trial unlocks every bot feature without a daily usage cap.
        return {"tier": "trial", "allowed": True, "remaining": None,
                "days_left": 1}
    return {"tier": "expired", "allowed": False, "remaining": 0, "days_left": 0}

def consume_trial_use(chat_id: int) -> bool:
    status = access_status(chat_id)
    if not status["allowed"]:
        return False
    if status["tier"] in ("owner", "pro", "trial"):
        return True
    day = _now().date().isoformat()
    con = _db()
    row = con.execute("SELECT daily_date,daily_count FROM subscription_users WHERE chat_id=?", (chat_id,)).fetchone()
    count = row["daily_count"] if row["daily_date"] == day else 0
    if count >= TRIAL_DAILY_LIMIT:
        con.close()
        return False
    con.execute("UPDATE subscription_users SET daily_date=?, daily_count=? WHERE chat_id=?",
                (day, count + 1, chat_id))
    con.commit()
    con.close()
    return True

def create_pro_request(chat_id: int, payment_method: str = "manual") -> int:
    if payment_method not in {"jawali", "jaib"}:
        payment_method = "manual"
    con = _db()
    cur = con.execute("INSERT INTO pro_requests(chat_id,created_at,status,payment_method) VALUES(?,?, 'pending',?)",
                      (chat_id, _now().isoformat(), payment_method))
    request_id = int(cur.lastrowid)
    con.commit()
    con.close()
    return request_id

def activate_pro(chat_id: int, days: int = 30) -> datetime:
    if days < 1 or days > 365:
        raise ValueError("مدة الاشتراك يجب أن تكون بين يوم و365 يوماً.")
    ensure_user(chat_id)
    con = _db()
    row = con.execute("SELECT pro_until FROM subscription_users WHERE chat_id=?", (chat_id,)).fetchone()
    current = _parse(row["pro_until"])
    start = current if current and current > _now() else _now()
    until = start + timedelta(days=days)
    con.execute("UPDATE subscription_users SET pro_until=? WHERE chat_id=?", (until.isoformat(), chat_id))
    con.execute("UPDATE pro_requests SET status='approved' WHERE chat_id=? AND status='pending'", (chat_id,))
    con.commit()
    con.close()
    return until

def subscription_message(chat_id: int) -> str:
    status = access_status(chat_id)
    if status["tier"] == "owner":
        return "👑 حساب المالك: وصول كامل إلى الدليل الإرشادي."
    if status["tier"] == "pro":
        return f"💎 اشتراك PRO فعال حتى {status['days_left']} يوم/أيام متبقية."
    if status["tier"] == "trial":
        return (f"🎁 تجربتك المجانية فعالة. المتبقي: {status['days_left']} يوم/أيام، "
                f"وحتى {status['remaining']} تحليلات اليوم.")
    return "⛔ انتهت التجربة المجانية. اطلب اشتراك PRO لتفعيل الدليل الإرشادي."

def pro_offer_text(request_id: int) -> str:
    payment = PRO_PAYMENT_INSTRUCTIONS or "لم تُضف الإدارة تعليمات الدفع بعد. أرسل رقم طلبك إلى إدارة البوت لتأكيد السعر ووسيلة الدفع."
    return (f"💎 طلب اشتراك NUMBER ONE PRO\nرقم الطلب: #{request_id}\n\n"
            f"{PRO_PRICE_TEXT}\n\n{payment}\n\n"
            "بعد الدفع أرسل إثبات التحويل إلى إدارة البوت. لا ترسل كلمة مرور حسابك أو مفاتيحك السرية.")


AI_FREE_DAILY_CREDITS = int(os.getenv("AI_FREE_DAILY_CREDITS", "5"))

def ai_credit_status(chat_id: int) -> dict:
    """Daily AI chat allowance: free users get configured credits; PRO and owner are unlimited."""
    tier = access_status(chat_id)["tier"]
    if tier in ("owner", "pro", "trial"):
        return {"tier": tier, "remaining": None, "limit": None, "unlimited": True}
    ensure_user(chat_id)
    day = _now().date().isoformat()
    con = _db()
    con.execute("""CREATE TABLE IF NOT EXISTS ai_daily_credits (
        chat_id INTEGER NOT NULL,
        credit_date TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(chat_id, credit_date)
    )""")
    row = con.execute(
        "SELECT used FROM ai_daily_credits WHERE chat_id=? AND credit_date=?",
        (chat_id, day)
    ).fetchone()
    used = int(row["used"]) if row else 0
    con.close()
    return {"tier": tier, "remaining": max(0, AI_FREE_DAILY_CREDITS - used),
            "limit": AI_FREE_DAILY_CREDITS, "unlimited": False}

def consume_ai_credit(chat_id: int) -> bool:
    """Consume one daily AI message credit, or allow unlimited PRO/owner access."""
    status = ai_credit_status(chat_id)
    if status["unlimited"]:
        return True
    if status["remaining"] <= 0:
        return False
    day = _now().date().isoformat()
    con = _db()
    con.execute("""CREATE TABLE IF NOT EXISTS ai_daily_credits (
        chat_id INTEGER NOT NULL,
        credit_date TEXT NOT NULL,
        used INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(chat_id, credit_date)
    )""")
    con.execute("""INSERT INTO ai_daily_credits(chat_id,credit_date,used) VALUES(?,?,1)
        ON CONFLICT(chat_id,credit_date) DO UPDATE SET used=used+1""", (chat_id, day))
    con.commit()
    con.close()
    return True
