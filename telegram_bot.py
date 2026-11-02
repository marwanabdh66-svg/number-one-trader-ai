"""NUMBER ONE TRADER AI — واجهة تيليجرام عربية احترافية."""
import os
import asyncio
import sqlite3
from datetime import datetime, timezone

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # The bot can still run without the optional AI assistant.
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from engine import ASSETS, TIMEFRAMES, analyze_asset, analyze_otc_poc, resolve_otc_symbol
from auto_trader import init_auto_db, start_session, stop_session, format_status, run_cycle, get_trade_history
from signal_monitor import init_signal_monitor, set_signal_watch, signal_watch_enabled, scan_signal_watchers
from subscriptions import (
    OWNER_ID, activate_pro, access_status, consume_trial_use, create_pro_request,
    ensure_user, init_subscriptions, pro_offer_text, subscription_message,
)
from trading_tools import (
    add_trade, get_trades, get_performance, calculate_risk, init_trading_tools,
)


TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")
client = OpenAI(api_key=OPENAI_API_KEY, timeout=45.0) if OPENAI_API_KEY and OpenAI is not None else None

SYSTEM_PROMPT = """أنت المساعد الذكي الرسمي في NUMBER ONE TRADER AI.
أجب بالعربية الواضحة. اشرح التداول والمؤشرات للمبتدئين.
لا تخترع أسعارًا أو بيانات لحظية أو نتائج. لا تدّع ضمان الأرباح.
التحليل تعليمي وليس نصيحة مالية. لا تنفذ صفقات حقيقية ولا تطلب كلمات مرور أو مفاتيح سرية.
"""

GOLD = "◆"
HELP_TEXT = (
    "╔════════════════════╗\n"
    "     ◆ NUMBER ONE ◆\n"
    "       TRADER AI\n"
    "╚════════════════════╝\n\n"
    "مرحباً بك في مركز NUMBER ONE TRADER AI.\n"
    "الدليل الإرشادي الذكي لـ Pocket Option OTC: قريباً.\n"
    "يمكنك حالياً استخدام المحاكاة التعليمية والمساعد الذكي وسجلّك الشخصي.\n\n"
    "اختر الخدمة من لوحة التحكم أدناه.\n"
    "🛡️ التداول الآلي المتاح حالياً محاكاة فقط؛ لا يستخدم أموالاً حقيقية."
)

def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
        asset TEXT, symbol TEXT, market TEXT, timeframe TEXT, direction TEXT,
        confidence INTEGER, entry REAL, stop_loss REAL, take_profit REAL,
        source TEXT, created_at TEXT
    )""")
    con.commit()
    con.close()

def save_signal(chat_id, result):
    con = db()
    con.execute(
        """INSERT INTO signals(chat_id,asset,symbol,market,timeframe,direction,
        confidence,entry,stop_loss,take_profit,source,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (chat_id, result["asset"], result["symbol"], result["market"],
         result["timeframe"], result["direction"], result["confidence"],
         result["entry"], result["stop_loss"], result["take_profit"],
         result["source"], result["created_at"])
    )
    con.commit()
    con.close()

def main_keyboard():
    rows = [
        [InlineKeyboardButton("🤖 محاكاة تداول تجريبية فقط", callback_data="auto"),
         InlineKeyboardButton("📈 حالة المحاكاة", callback_data="auto_status")],
        [InlineKeyboardButton("📒 دفتر التداول", callback_data="journal"),
         InlineKeyboardButton("🧮 حاسبة المخاطر", callback_data="risk_calc")],
        [InlineKeyboardButton("📊 تحليل أدائي", callback_data="performance"),
         InlineKeyboardButton("🕘 سجل تحليلاتي", callback_data="history")],
        [InlineKeyboardButton("🛡️ حارس الانضباط", callback_data="discipline"),
         InlineKeyboardButton("🎓 أكاديمية التداول", callback_data="learn")],
        [InlineKeyboardButton("👤 حسابي الشخصي", callback_data="my_account")],
        [InlineKeyboardButton("⚙️ إعداداتي", callback_data="settings")],
        [InlineKeyboardButton("🧭 الدليل الإرشادي الذكي OTC — قريباً", callback_data="guide")],
        [InlineKeyboardButton("💎 اشتراك PRO", callback_data="pro"),
         InlineKeyboardButton("📋 حالة اشتراكي", callback_data="substatus")],
        [InlineKeyboardButton("🤖 المساعد الذكي", callback_data="assistant"),
         InlineKeyboardButton("❔ المساعدة", callback_data="help")],
    ]
    return InlineKeyboardMarkup(rows)

def markets_keyboard():
    keys = list(ASSETS.keys())
    rows = []
    for i in range(0, len(keys), 2):
        rows.append([InlineKeyboardButton("🌐 " + keys[j], callback_data=f"market:{j}") for j in range(i, min(i+2, len(keys)))])
    rows.append([InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def assets_keyboard(market_index):
    market = list(ASSETS.keys())[market_index]
    assets = list(ASSETS[market].items())
    rows = []
    for i in range(0, len(assets), 2):
        rows.append([
            InlineKeyboardButton(assets[j][0], callback_data=f"asset:{market_index}:{j}")
            for j in range(i, min(i+2, len(assets)))
        ])
    rows.append([InlineKeyboardButton("⬅️ الأسواق", callback_data="markets"),
                 InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def timeframe_keyboard():
    labels = list(TIMEFRAMES.keys())
    rows = []
    for i in range(0, len(labels), 3):
        rows.append([InlineKeyboardButton(labels[j], callback_data=f"tf:{j}") for j in range(i, min(i+3, len(labels)))])
    rows.append([InlineKeyboardButton("⬅️ تغيير الأصل", callback_data="markets"),
                 InlineKeyboardButton("🏠 الرئيسية", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def fmt(value):
    return f"{value:,.6f}" if abs(float(value)) < 100 else f"{value:,.2f}"

def signal_text(s):
    arrow = "🟢 صعود" if s["direction"] == "صعود" else "🔴 هبوط"
    return (
        "╔═══════ ◈ ═══════╗\n"
        "      NUMBER ONE TRADER AI\n"
        "╚═══════ ◈ ═══════╝\n\n"
        f"💠 الأصل: {s['asset']} ({s['symbol']})\n"
        f"🌐 السوق: {s['market']}\n"
        f"⏱️ الفاصل: {s['timeframe']}\n"
        f"📍 الاتجاه: {arrow}\n"
        f"🎯 توافق المؤشرات: {s['confidence']}%\n\n"
        f"💰 الدخول المرجعي: {fmt(s['entry'])}\n"
        f"🛑 وقف الخسارة الحسابي: {fmt(s['stop_loss'])}\n"
        f"🏁 الهدف الحسابي: {fmt(s['take_profit'])}\n"
        f"📈 RSI: {s['rsi']}\n"
        f"🧩 مصدر البيانات: {s['source']}\n"
        f"🕒 التوقيت: {s['created_at']}\n\n"
        f"📝 الأسباب: {s['reasons']}\n\n"
        "⚠️ تحليل فني تجريبي، وليس توصية مالية أو ضماناً للربح."
    )

async def send_long(message, text):
    for start in range(0, len(text), 3900):
        await message.reply_text(text[start:start+3900])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.setdefault("timeframe", "5 دقائق")
    ensure_user(update.effective_chat.id)
    await update.message.reply_text(HELP_TEXT + "\n\n" + subscription_message(update.effective_chat.id), reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 دليل NUMBER ONE TRADER AI\n\n"
        "الدليل الإرشادي الذكي: قريباً — متوقف مؤقتاً حتى حل مشكلة مصدر بيانات OTC.\n\n"
        "الأوامر: /start /journal /performance /risk /discipline /learn /markets /analyze /history /reset /help\n"
        "يمكنك إرسال سؤالك مباشرة للمساعد الذكي.",
        reply_markup=main_keyboard()
    )

async def show_my_account(user, message):
    chat_id = user.id
    ensure_user(chat_id)
    status = access_status(chat_id)
    performance = get_performance(chat_id)
    tier_names = {
        "owner": "مالك البوت",
        "pro": "PRO فعال",
        "trial": "تجربة مجانية",
        "expired": "انتهت التجربة"
    }
    username = f"@{user.username}" if user.username else "غير محدد"
    if status["tier"] == "owner":
        plan_detail = "صلاحيات المالك كاملة"
    elif status["tier"] == "pro":
        plan_detail = f"متبقي {status['days_left']} يوم/أيام"
    elif status["tier"] == "trial":
        plan_detail = f"متبقي {status['days_left']} يوم/أيام، واستخدامات اليوم: {status['remaining']}"
    else:
        plan_detail = "يمكنك طلب الاشتراك من القائمة"
    text = (
        "👤 حسابك في NUMBER ONE TRADER AI\\n\\n"
        f"الاسم: {user.full_name}\\n"
        f"اسم المستخدم: {username}\\n"
        f"رقم تيليجرام: {chat_id}\\n\\n"
        f"💎 الخطة: {tier_names.get(status['tier'], status['tier'])}\\n"
        f"{plan_detail}\\n\\n"
        "📒 ملخص دفتر التداول الخاص بك\\n"
        f"عدد الصفقات المسجلة: {performance['total']}\\n"
        f"صافي النتائج المدخلة: {performance['net']:+.2f}\\n"
        f"نسبة الصفقات الرابحة: {performance['win_rate']:.1f}%\\n\\n"
        "🔐 حساب Pocket Option: غير مربوط. لم نطلب كلمة المرور أو رمز التحقق، "
        "ولن نخزن بيانات دخول الوسيط في البوت."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📒 دفتر التداول", callback_data="journal"),
         InlineKeyboardButton("📊 تقرير الأداء", callback_data="performance")],
        [InlineKeyboardButton("💎 حالة الاشتراك", callback_data="substatus")],
        [InlineKeyboardButton("🌐 فتح موقع Pocket Option", url="https://pocketoption.com/")],
        [InlineKeyboardButton("ℹ️ معلومات الربط الآمن", callback_data="broker_link_info")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
    ])
    await message.reply_text(text, reply_markup=keyboard)


async def show_journal(chat_id, message):
    rows = get_trades(chat_id, 10)
    if not rows:
        await message.reply_text(
            "📒 دفتر التداول فارغ حالياً. اضغط «إضافة صفقة» لتسجيل أول صفقة يدوياً.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ إضافة صفقة", callback_data="journal_add")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
        return
    lines = ["📒 دفتر تداولك — آخر 10 صفقات", ""]
    for row in rows:
        sign = "+" if row["pnl"] > 0 else ""
        emoji = "🟢" if row["pnl"] > 0 else ("🔴" if row["pnl"] < 0 else "⚪")
        lines.append(
            f"{emoji} {row['asset']} | {row['side']}\n"
            f"الدخول: {row['entry']:g} | الخروج: {row['exit']:g}\n"
            f"النتيجة المسجلة: {sign}{row['pnl']:.2f}"
        )
    await message.reply_text(
        "\n\n".join(lines),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ إضافة صفقة", callback_data="journal_add"),
             InlineKeyboardButton("📊 تحليل أدائي", callback_data="performance")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
        ])
    )


async def show_performance(chat_id, message):
    p = get_performance(chat_id)
    if not p["total"]:
        text = "📊 لا توجد صفقات مسجلة بعد. أضف صفقاتك إلى دفتر التداول ليظهر تقرير أدائك."
    else:
        text = (
            "📊 تقرير أدائك المسجل\n\n"
            f"عدد الصفقات: {p['total']}\n"
            f"الرابحة: {p['wins']} | الخاسرة: {p['losses']} | المتعادلة: {p['breakeven']}\n"
            f"نسبة الصفقات الرابحة: {p['win_rate']:.1f}%\n"
            f"صافي النتائج المسجلة: {p['net']:+.2f}\n"
            f"متوسط نتيجة الصفقة: {p['average']:+.2f}\n"
            f"أفضل نتيجة: {p['best']:+.2f} | أسوأ نتيجة: {p['worst']:+.2f}\n\n"
            "هذه الإحصاءات محسوبة من النتائج التي أدخلتها يدوياً، وليست تحققاً مستقلاً من حساب الوسيط."
        )
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📒 دفتر التداول", callback_data="journal")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
    ]))



LESSONS = {
    "risk": {
        "title": "إدارة المخاطر",
        "body": "حدّد مقداراً صغيراً تخاطر به قبل الدخول، ولا ترفع النسبة لتعويض خسارة سابقة. لا توجد نسبة تضمن الربح.",
        "question": "إذا كان رأس مالك 500 دولار واخترت مخاطرة 1%، فما المبلغ المعرض للخسارة؟",
        "choices": [("5 دولارات", "5"), ("10 دولارات", "10"), ("50 دولاراً", "50")],
        "correct": "5",
        "explain": "1% من 500 = 5 دولارات. هذا حساب للمخاطرة وليس ضماناً لحد الخسارة."
    },
    "discipline": {
        "title": "الانضباط النفسي",
        "body": "تجنب التداول الانتقامي والإفراط في الصفقات. بعد خسارة مؤثرة خذ استراحة وراجع سبب الدخول.",
        "question": "بعد خسارتين متتاليتين، ما التصرف الأكثر انضباطاً؟",
        "choices": [("زيادة حجم الصفقة", "increase"), ("التوقف مؤقتاً ومراجعة الأسباب", "pause"), ("الدخول فوراً", "rush")],
        "correct": "pause",
        "explain": "الاستراحة ومراجعة السجل تساعد على منع قرارات التعويض المتسرعة."
    },
    "trend": {
        "title": "الاتجاه والدعم والمقاومة",
        "body": "الاتجاه الصاعد غالباً ما يظهر في قمم وقيعان أعلى، والهابط في قمم وقيعان أدنى. الدعم والمقاومة مناطق وليست ضماناً للارتداد.",
        "question": "ما الوصف الأقرب للاتجاه الصاعد؟",
        "choices": [("قمم وقيعان أعلى", "up"), ("قمم وقيعان أدنى", "down"), ("حركة بلا اتجاه", "flat")],
        "correct": "up",
        "explain": "تتابع القمم والقيعان الأعلى علامة شائعة على اتجاه صاعد، لكنه لا يضمن استمراره."
    }
}


async def show_learning(chat_id, message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧮 إدارة المخاطر", callback_data="lesson:risk")],
        [InlineKeyboardButton("🧠 الانضباط النفسي", callback_data="lesson:discipline")],
        [InlineKeyboardButton("📈 الاتجاه والدعم والمقاومة", callback_data="lesson:trend")],
        [InlineKeyboardButton("🛡️ فحص انضباطي", callback_data="discipline")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
    ])
    await message.reply_text(
        "🎓 أكاديمية NUMBER ONE\n\nدروس قصيرة واختبارات تفاعلية في مهارات التداول. المحتوى تعليمي وليس توصية دخول.",
        reply_markup=keyboard
    )


async def show_discipline(chat_id, message):
    rows = get_trades(chat_id, 5)
    if not rows:
        text = "🛡️ حارس الانضباط\n\nلا توجد صفقات كافية في دفتر التداول لفحص سلوكك. سجّل نتائجك يدوياً ليظهر لك التنبيه."
    else:
        losses = sum(1 for row in rows if float(row["pnl"]) < 0)
        streak = 0
        for row in rows:
            if float(row["pnl"]) < 0:
                streak += 1
            else:
                break
        text = (
            "🛡️ حارس الانضباط — آخر خمس صفقات\n\n"
            f"الخسائر ضمن آخر {len(rows)} صفقات: {losses}\n"
            f"الخسائر المتتالية من أحدث صفقة: {streak}\n\n"
        )
        if streak >= 2:
            text += "⚠️ لديك خسارتان متتاليتان أو أكثر. خذ استراحة ولا ترفع حجم الصفقة للتعويض. راجع أسباب الدخول وحدود المخاطرة."
        elif losses >= 3:
            text += "⚠️ تكررت الخسائر في سجلك الأخير. راجع استراتيجيتك وفكّر في التوقف مؤقتاً."
        else:
            text += "لا يظهر نمط خسائر متتالية في السجل الحالي. واصل الالتزام بخطة المخاطرة."
        text += "\n\nهذا الفحص تعليمي ويعتمد على النتائج التي أدخلتها يدوياً."
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("📒 دفتر التداول", callback_data="journal"),
         InlineKeyboardButton("🎓 الأكاديمية", callback_data="learn")],
        [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
    ]))


async def show_history(chat_id, message):
    con = db()
    rows = con.execute(
        "SELECT * FROM signals WHERE chat_id=? ORDER BY id DESC LIMIT 10", (chat_id,)
    ).fetchall()
    con.close()
    if not rows:
        await message.reply_text("لا يوجد سجل تحليلات محفوظ حتى الآن.", reply_markup=main_keyboard())
        return
    lines = ["🕘 آخر تحليلاتك في NUMBER ONE TRADER AI", ""]
    for row in rows:
        arrow = "🟢" if row["direction"] == "صعود" else "🔴"
        lines.append(f"{arrow} {row['asset']} | {row['timeframe']} | {row['confidence']}% | {row['created_at']}")
    await message.reply_text("\n".join(lines), reply_markup=main_keyboard())

async def analyze_selected(update, context, query=None):
    asset = context.user_data.get("asset")
    if not asset:
        await query.edit_message_text("اختر السوق أولاً.", reply_markup=markets_keyboard())
        return
    name, symbol, market = asset
    timeframe = context.user_data.get("timeframe", "5 دقائق")
    await query.edit_message_text(f"⏳ جارٍ تحليل {name} على فاصل {timeframe}...")
    try:
        result = await asyncio.to_thread(analyze_asset, name, symbol, market, timeframe, "جميع الإشارات")
    except Exception:
        result = None
    if not result:
        await query.message.reply_text(
            "لم تتوفر بيانات كافية أو لا توجد إشارة واضحة الآن. حاول لاحقاً أو اختر فاصلاً آخر.",
            reply_markup=main_keyboard()
        )
        return
    save_signal(query.message.chat_id, result)
    await query.message.reply_text(
        signal_text(result),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 إعادة التحليل", callback_data="reanalyze"),
             InlineKeyboardButton("📊 تحليل أصل آخر", callback_data="markets")],
            [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]
        ])
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "auto":
        context.user_data["auto_setup"] = {}
        await q.edit_message_text(
            "🤖 إعداد المحاكاة التعليمية\n\nهذه محاكاة افتراضية منفصلة تستخدم بيانات العملات الرقمية العامة، وليست Pocket Option OTC ولا تتصل بحسابك ولا ترسل أوامر بأموال حقيقية. اختر مدة تشغيل المحاكاة.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("ساعة", callback_data="auto_duration:1"),
                 InlineKeyboardButton("3 ساعات", callback_data="auto_duration:3")],
                [InlineKeyboardButton("6 ساعات", callback_data="auto_duration:6"),
                 InlineKeyboardButton("12 ساعة", callback_data="auto_duration:12")],
                [InlineKeyboardButton("24 ساعة", callback_data="auto_duration:24")],
                [InlineKeyboardButton("⬅️ الرئيسية", callback_data="home")]
            ])
        )
    elif data.startswith("auto_duration:"):
        duration = int(data.split(":")[1])
        context.user_data.setdefault("auto_setup", {})["duration"] = duration
        await q.edit_message_text(
            "اختر مستوى المخاطرة الافتراضي لكل صفقة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("محافظ 0.5%", callback_data="auto_risk:0.5"),
                 InlineKeyboardButton("متوازن 1%", callback_data="auto_risk:1.0")]
            ])
        )
    elif data.startswith("auto_risk:"):
        risk = float(data.split(":")[1])
        context.user_data.setdefault("auto_setup", {})["risk"] = risk
        await q.edit_message_text(
            "اختر الحد الأقصى للخسارة اليومية في المحاكاة:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("2%", callback_data="auto_daily:2"),
                 InlineKeyboardButton("3%", callback_data="auto_daily:3"),
                 InlineKeyboardButton("5%", callback_data="auto_daily:5")]
            ])
        )
    elif data.startswith("auto_daily:"):
        daily = float(data.split(":")[1])
        context.user_data.setdefault("auto_setup", {})["daily"] = daily
        context.user_data["awaiting_auto_capital"] = True
        await q.edit_message_text(
            f"إعداداتك: مدة {context.user_data['auto_setup']['duration']} ساعة، مخاطرة {context.user_data['auto_setup']['risk']}%، حد خسارة يومية {daily}%.\n\nأرسل الآن مبلغ رأس المال الافتراضي بالأرقام فقط، مثلاً 100."
        )
    elif data == "auto_status":
        await q.edit_message_text(format_status(q.message.chat_id), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 سجل الصفقات", callback_data="auto_trades")],
            [InlineKeyboardButton("⏹️ إيقاف التداول الآلي", callback_data="auto_stop")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
        ]))
    elif data == "auto_trades":
        rows = get_trade_history(q.message.chat_id, 10)
        if not rows:
            await q.edit_message_text("لا توجد صفقات تجريبية مسجلة بعد.", reply_markup=main_keyboard())
        else:
            lines = ["📜 سجل آخر الصفقات التجريبية", ""]
            for row in rows:
                status = "مفتوحة" if row["status"] == "open" else "مغلقة"
                pnl = "قيد المتابعة" if row["pnl"] is None else f"{row['pnl']:+.2f}"
                lines.append(f"{row['asset']} | {row['direction']} | {status}\nالدخول: {row['entry']:.6g} | النتيجة: {pnl}")
            await q.edit_message_text("\n\n".join(lines), reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 تحديث الحالة", callback_data="auto_status")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ]))
    elif data == "auto_stop":
        stopped = stop_session(q.message.chat_id)
        await q.edit_message_text(
            "تم إيقاف فتح صفقات جديدة في المحاكاة." if stopped else "لا توجد جلسة نشطة لإيقافها.",
            reply_markup=main_keyboard()
        )
    elif data == "my_account":
        await show_my_account(q.from_user, q.message)
    elif data == "broker_link_info":
        await q.edit_message_text(
            "🔐 ربط حساب Pocket Option\\n\\n"
            "حسابك الشخصي داخل NUMBER ONE يعمل الآن عبر هويتك في تيليجرام، "
            "ويحفظ دفتر صفقاتك واشتراكك بصورة منفصلة عن بقية المستخدمين.\\n\\n"
            "أما جلب رصيد Pocket Option والصفقات الحقيقية أو تنفيذها، فيحتاج إلى واجهة رسمية وموافقة مكتوبة من الوسيط. "
            "لا يظهر في المصادر الرسمية العامة التي تحققنا منها مسار API عام موثق لهذا الربط، كما تحذر شروط المنصة من برامج التداول غير المصرح بها.\\n\\n"
            "لا ترسل كلمة مرورك أو رمز التحقق أو ملفات الجلسة إلى البوت أو لأي شخص. "
            "لن نستخدم أدوات غير رسمية قد تعرض حسابك أو أموالك للخطر.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🌐 موقع Pocket Option الرسمي", url="https://pocketoption.com/")],
                [InlineKeyboardButton("👤 العودة إلى حسابي", callback_data="my_account")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "home":
        await q.edit_message_text(HELP_TEXT, reply_markup=main_keyboard())
    elif data == "markets" or data.startswith(("market:", "asset:", "tf:")):
        await q.edit_message_text(
            "الدليل الإرشادي الذكي متوقف مؤقتاً — قريباً. لن يتم تحليل أزواج OTC أو إصدار إشارات حتى حل مشكلة مصدر البيانات.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]])
        )
    elif data == "change_tf":
        await q.edit_message_text("الدليل الإرشادي الذكي متوقف مؤقتاً — قريباً.", reply_markup=main_keyboard())
    elif data in ("analyze", "reanalyze"):
        await q.edit_message_text("الدليل الإرشادي الذكي متوقف مؤقتاً — قريباً. لن تصدر إشارات حتى إعادة تفعيل مصدر بيانات OTC.", reply_markup=main_keyboard())
    elif data in ("signals", "signals_toggle", "quickscan"):
        await q.edit_message_text(
            "الدليل الإرشادي الذكي ومركز إشارات OTC: قريباً. الخدمة متوقفة مؤقتاً حتى حل مشكلة مصدر البيانات.",
            reply_markup=main_keyboard()
        )
    elif data == "learn":
        await show_learning(q.message.chat_id, q.message)
    elif data.startswith("lesson:"):
        lesson_id = data.split(":", 1)[1]
        lesson = LESSONS.get(lesson_id)
        if not lesson:
            await q.edit_message_text("الدرس غير متاح.", reply_markup=main_keyboard())
        else:
            buttons = [[InlineKeyboardButton(label, callback_data=f"quiz:{lesson_id}:{answer}")]
                       for label, answer in lesson["choices"]]
            buttons.append([InlineKeyboardButton("⬅️ الأكاديمية", callback_data="learn")])
            await q.edit_message_text(
                f"🎓 {lesson['title']}\n\n{lesson['body']}\n\n❓ {lesson['question']}",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    elif data.startswith("quiz:"):
        parts = data.split(":")
        lesson = LESSONS.get(parts[1]) if len(parts) == 3 else None
        if not lesson:
            await q.edit_message_text("تعذر تحميل السؤال.", reply_markup=main_keyboard())
        else:
            correct = parts[2] == lesson["correct"]
            result = "✅ إجابة صحيحة!" if correct else "❌ إجابة غير صحيحة."
            await q.edit_message_text(
                f"{result}\n\n{lesson['explain']}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📚 درس آخر", callback_data="learn")],
                    [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
                ])
            )
    elif data == "discipline":
        await show_discipline(q.message.chat_id, q.message)
    elif data == "journal":
        await show_journal(q.message.chat_id, q.message)
    elif data == "journal_add":
        context.user_data["journal_flow"] = {"step": "asset"}
        await q.edit_message_text("➕ تسجيل صفقة جديدة\n\nاكتب اسم الأصل أو الزوج، مثال: EUR/USD أو الذهب.")
    elif data.startswith("journal_side:"):
        flow = context.user_data.get("journal_flow")
        if not flow:
            await q.edit_message_text("انتهت جلسة التسجيل. افتح دفتر التداول وابدأ من جديد.", reply_markup=main_keyboard())
        else:
            flow["side"] = "شراء" if data.endswith("buy") else "بيع"
            flow["step"] = "entry"
            await q.edit_message_text("أرسل سعر الدخول بالأرقام فقط، مثال: 1.0850")
    elif data == "performance":
        await show_performance(q.message.chat_id, q.message)
    elif data == "risk_calc":
        context.user_data["awaiting_risk_input"] = True
        await q.edit_message_text(
            "🧮 حاسبة المخاطر المجانية\n\n"
            "أرسل ثلاثة أرقام بهذا الترتيب: رأس المال نسبة المخاطرة% مسافة وقف الخسارة%\n"
            "مثال: 1000 1 2\n\n"
            "أي أن رأس المال 1000، والمخاطرة 1%، ووقف الخسارة يبعد 2% عن سعر الدخول."
        )
    elif data == "history":
        await show_history(q.message.chat_id, q.message)
    elif data == "settings":
        await q.edit_message_text(
            "⚙️ الإعدادات\nاكتب الفاصل الزمني مباشرة مع زوج OTC، مثال: AED/CNY OTC 1m أو AED/CNY OTC 5m.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]])
        )
    elif data == "guide":
        await q.edit_message_text(
            "🧭 الدليل الإرشادي الذكي — قريباً\n\n"
            "الخدمة متوقفة مؤقتاً حتى حل مشكلة مصدر بيانات Pocket Option OTC.\n"
            "لن يتم تحليل الأزواج أو إصدار إشارات خلال فترة التوقف.\n"
            "لن نستخدم بيانات أسواق أخرى أو إشارات تقديرية بديلاً عن بيانات OTC.\n\n"
            + subscription_message(q.message.chat_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 اشتراك PRO", callback_data="pro")],
                [InlineKeyboardButton("📋 حالة الاشتراك", callback_data="substatus")],
                [InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]
            ])
        )
    elif data == "pro":
        request_id = create_pro_request(q.message.chat_id)
        await q.edit_message_text(
            pro_offer_text(request_id),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]])
        )
        if OWNER_ID:
            try:
                await context.bot.send_message(
                    chat_id=int(OWNER_ID),
                    text=f"طلب اشتراك PRO جديد #{request_id} من المستخدم {q.message.chat_id}. للتفعيل: /activate {q.message.chat_id} 30"
                )
            except Exception as exc:
                print(f"PRO admin notification failed: {type(exc).__name__}")
    elif data == "substatus":
        await q.edit_message_text(
            subscription_message(q.message.chat_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 طلب PRO", callback_data="pro")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "assistant":
        await q.edit_message_text(
            "🤖 المساعد الذكي جاهز للمحادثة. أرسل سؤالك برسالة نصية هنا.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 القائمة الرئيسية", callback_data="home")]])
        )
    elif data == "help":
        await q.edit_message_text(
            "📘 اختر السوق ثم الأصل ثم الفاصل الزمني، وبعدها اضغط ابدأ التحليل. "
            "يمكنك أيضاً إرسال أسئلتك نصياً للمساعد الذكي.",
            reply_markup=main_keyboard()
        )

async def ask_openai(history):
    response = await asyncio.to_thread(
        client.responses.create,
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=history,
        max_output_tokens=700,
        store=False,
    )
    return response.output_text

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    # خطوات تسجيل الصفقة اليدوية وحاسبة المخاطر — متاحة مجاناً.
    flow = context.user_data.get("journal_flow")
    if flow:
        raw_value = update.message.text.strip()
        step = flow.get("step")
        if step == "asset":
            if not raw_value or len(raw_value) > 32:
                await update.message.reply_text("اكتب اسم أصل أو زوجاً صحيحاً لا يتجاوز 32 حرفاً.")
                return
            flow["asset"] = raw_value
            flow["step"] = "side"
            await update.message.reply_text(
                f"الأصل: {raw_value}\nاختر اتجاه الصفقة:",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("شراء", callback_data="journal_side:buy"),
                    InlineKeyboardButton("بيع", callback_data="journal_side:sell")
                ]])
            )
            return
        if step in ("entry", "exit", "pnl"):
            try:
                number = float(raw_value.replace(",", ""))
                if not __import__("math").isfinite(number):
                    raise ValueError
            except ValueError:
                await update.message.reply_text("أرسل رقماً صحيحاً فقط، ويمكنك استخدام الكسور العشرية.")
                return
            if step in ("entry", "exit") and number <= 0:
                await update.message.reply_text("يجب أن يكون السعر أكبر من صفر. أعد إدخاله.")
                return
            if step == "entry":
                flow["entry"] = number
                flow["step"] = "exit"
                await update.message.reply_text("أرسل سعر الخروج من الصفقة.")
            elif step == "exit":
                flow["exit"] = number
                flow["step"] = "pnl"
                await update.message.reply_text(
                    "أرسل صافي نتيجة الصفقة كما ظهرت لك: ربح موجب أو خسارة سالبة. مثال: 5.50 أو -3.25"
                )
            else:
                try:
                    trade_id = add_trade(
                        update.effective_chat.id, flow["asset"], flow["side"],
                        flow["entry"], flow["exit"], number
                    )
                except (ValueError, KeyError) as exc:
                    await update.message.reply_text(str(exc))
                    return
                context.user_data.pop("journal_flow", None)
                await update.message.reply_text(
                    f"✅ تم حفظ الصفقة رقم #{trade_id} في دفتر التداول.\n"
                    f"النتيجة المسجلة: {number:+.2f}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📒 دفتر التداول", callback_data="journal"),
                         InlineKeyboardButton("📊 تحليل أدائي", callback_data="performance")],
                        [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
                    ])
                )
            return

    if context.user_data.get("awaiting_risk_input"):
        try:
            parts = update.message.text.replace(",", ".").split()
            if len(parts) != 3:
                raise ValueError
            result = calculate_risk(float(parts[0]), float(parts[1]), float(parts[2]))
        except ValueError as exc:
            await update.message.reply_text(
                (str(exc) if str(exc) else "صيغة الإدخال غير صحيحة.")
                + "\nأرسلها بهذا الشكل: 1000 1 2"
            )
            return
        context.user_data["awaiting_risk_input"] = False
        await update.message.reply_text(
            "🧮 نتيجة حاسبة المخاطر\n\n"
            f"رأس المال: {result['capital']:.2f}\n"
            f"نسبة المخاطرة: {result['risk_percent']:.2f}%\n"
            f"المبلغ المعرض للمخاطرة: {result['risk_amount']:.2f}\n"
            f"مسافة وقف الخسارة: {result['stop_percent']:.2f}%\n"
            f"حجم المركز الحسابي التقريبي: {result['position_size']:.2f}\n\n"
            "الحساب تعليمي فقط. تحقق من متطلبات الوسيط والرافعة والرسوم، ولا يعني حجم المركز أنه مبلغ مضمون أو مناسب لك.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🧮 حساب جديد", callback_data="risk_calc")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
        return

    # الدليل الإرشادي متوقف مؤقتاً؛ امنع جميع طلبات OTC حتى إعادة تفعيله.
    if not context.user_data.get("awaiting_auto_capital"):
        raw_text = update.message.text.strip().upper()
        if "OTC" in raw_text:
            await update.message.reply_text("🧭 الدليل الإرشادي الذكي — قريباً. الخدمة متوقفة مؤقتاً حتى حل مشكلة بيانات Pocket Option OTC. لن تصدر أي إشارات خلال فترة التوقف.", reply_markup=main_keyboard())
            return
        import re
        pair_match = re.fullmatch(r"([A-Z0-9]{2,10})\s*[/\-]\s*([A-Z0-9]{2,10})\s+OTC(?:\s+(1M|5M|15M|30M|1H))?", raw_text)
        if pair_match:
            base, quote, requested_tf = pair_match.groups()
            pair = f"{base}/{quote}"
            status = access_status(update.effective_chat.id)
            if not status["allowed"]:
                await update.message.reply_text(
                    subscription_message(update.effective_chat.id) + "\n\nاكتب /pro لطلب الاشتراك. "
                    "لن يتم استخدام أي مصدر سوق عادي بدلاً من بيانات OTC.",
                    reply_markup=main_keyboard()
                )
                return
            otc_symbol = await asyncio.to_thread(resolve_otc_symbol, pair)
            if not otc_symbol:
                await update.message.reply_text(
                    f"⚠️ لم أتمكن من جلب رمز {pair} من كتالوج Pocket Option OTC.\n"
                    "قد يكون الرمز غير مدعوم في باقة OTCharts أو أن المفتاح/الحصة غير متاحين. "
                    "لن أستخدم أسعار Forex أو Binance كبديل ولن أخمّن رمزاً.",
                    reply_markup=main_keyboard()
                )
                return
            if not consume_trial_use(update.effective_chat.id):
                await update.message.reply_text(subscription_message(update.effective_chat.id) + "\nاكتب /pro لتفعيل الاشتراك.")
                return
            timeframe_code = requested_tf.lower() if requested_tf else "5m"
            label = next((k for k, (code, _) in TIMEFRAMES.items() if code == timeframe_code), "5 دقائق")
            await update.message.reply_text(f"⏳ جارٍ فحص شموع Pocket Option OTC للزوج {pair} على {label}...")
            try:
                result = await asyncio.to_thread(analyze_otc_poc, f"{pair} OTC", otc_symbol, label)
            except Exception as exc:
                print(f"OTC POC analysis failed: {type(exc).__name__}")
                result = None
            if not result:
                await update.message.reply_text(
                    "لم تتكوّن إشارة OTC مؤكدة الآن: نحتاج شموعاً كافية، وإعادة اختبار POC، "
                    "وشمعة تأكيد، وتوافق الاتجاه. عدم ظهور سهم أفضل من تخمين اتجاه.",
                    reply_markup=main_keyboard()
                )
                return
            save_signal(update.effective_chat.id, result)
            await update.message.reply_text(signal_text(result), reply_markup=main_keyboard())
            return
        if re.fullmatch(r"[A-Z0-9]{2,10}\s*[/\-]\s*[A-Z0-9]{2,10}(?:\s+(?:1M|5M|15M|30M|1H))?", raw_text):
            await update.message.reply_text(
                "للدليل الإرشادي أرسل الزوج مع OTC صراحةً، مثال: AED/CNY OTC 5m. "
                "لن أحلل الزوج من سوق عادي.",
                reply_markup=main_keyboard()
            )
            return
    if context.user_data.get("awaiting_auto_capital"):
        raw = update.message.text.strip().replace(",", "")
        try:
            capital = float(raw)
            setup = context.user_data.get("auto_setup", {})
            start_session(update.effective_chat.id, capital, setup["duration"], setup["risk"], setup["daily"])
            context.user_data["awaiting_auto_capital"] = False
            context.user_data.pop("auto_setup", None)
            await update.message.reply_text(
                "🟢 بدأ التداول الآلي التجريبي على الخادم. يمكنك إغلاق شاشة الهاتف.\n"
                f"الرصيد الافتراضي: {capital:.2f}\n"
                "الأسواق الحالية: العملات الرقمية فقط\n"
                "النظام يفتح صفقة تجريبية واحدة كحد أقصى، ويوقف الجلسة عند بلوغ حد الخسارة اليومية.\n"
                "استخدم زر حالة التداول لمتابعة النتائج أو إيقاف الجلسة. لا توجد أموال حقيقية مستخدمة.",
                reply_markup=main_keyboard()
            )
        except ValueError as exc:
            context.user_data["awaiting_auto_capital"] = False
            context.user_data.pop("auto_setup", None)
            await update.message.reply_text(str(exc) if "جلسة تداول" in str(exc) else "أرسل مبلغاً رقمياً أكبر من صفر، مثل 100.")
        except KeyError:
            context.user_data["awaiting_auto_capital"] = False
            await update.message.reply_text("تعذر قراءة الإعدادات. ابدأ إعداد التداول الآلي من القائمة الرئيسية.")
        return
    await chat_with_ai(update, context)


async def chat_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if client is None:
        await update.message.reply_text(
            "المساعد الذكي غير مفعّل بعد. يلزم إضافة OPENAI_API_KEY إلى أسرار تشغيل البوت. "
            "يمكنك استخدام أزرار تحليل الأسواق حالياً."
        )
        return
    history = context.user_data.setdefault("ai_history", [])
    history.append({"role": "user", "content": update.message.text[:4000]})
    history = history[-12:]
    await update.message.chat.send_action("typing")
    try:
        answer = await ask_openai(history)
        if not answer:
            answer = "لم يصلني رد نصي. حاول مرة أخرى."
        history.append({"role": "assistant", "content": answer})
        context.user_data["ai_history"] = history[-12:]
        await send_long(update.message, answer)
    except Exception as exc:
        print(f"OpenAI request failed: {type(exc).__name__}")
        await update.message.reply_text(
            "تعذر الاتصال بالمساعد الذكي الآن. تحقق من إعداد مفتاح الخدمة ورصيد واجهة API."
        )

async def journal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_journal(update.effective_chat.id, update.message)


async def performance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_performance(update.effective_chat.id, update.message)


async def risk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        context.user_data["awaiting_risk_input"] = True
        await update.message.reply_text(
            "🧮 أرسل: رأس المال نسبة المخاطرة% مسافة وقف الخسارة%\nمثال: /risk 1000 1 2"
        )
        return
    try:
        result = calculate_risk(*(float(x) for x in context.args))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return
    await update.message.reply_text(
        "🧮 نتيجة حاسبة المخاطر\n\n"
        f"المبلغ المعرض للمخاطرة: {result['risk_amount']:.2f}\n"
        f"حجم المركز الحسابي التقريبي: {result['position_size']:.2f}\n"
        "حساب تعليمي وليس توصية مالية."
    )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧭 الدليل الإرشادي الذكي — قريباً. الخدمة متوقفة مؤقتاً حتى حل مشكلة بيانات Pocket Option OTC.")
    return
    raw = " ".join(context.args).upper().strip()
    import re
    match = re.fullmatch(r"([A-Z0-9]{2,10})\s*[/\-]\s*([A-Z0-9]{2,10})\s+OTC(?:\s+(1M|5M|15M|30M|1H))?", raw)
    if not match:
        await update.message.reply_text("الاستخدام: /analyze AED/CNY OTC 5m — يقبل الدليل أزواج Pocket Option OTC فقط.")
        return
    base, quote, requested_tf = match.groups()
    status = access_status(update.effective_chat.id)
    if not status["allowed"]:
        await update.message.reply_text(subscription_message(update.effective_chat.id) + "\nاكتب /pro لطلب PRO.")
        return
    pair = f"{base}/{quote}"
    symbol = await asyncio.to_thread(resolve_otc_symbol, pair)
    if not symbol:
        await update.message.reply_text("تعذر العثور على الزوج في كتالوج Pocket Option OTC. لم يتم استخدام مصدر بديل.")
        return
    if not consume_trial_use(update.effective_chat.id):
        await update.message.reply_text(subscription_message(update.effective_chat.id) + "\nاكتب /pro لطلب PRO.")
        return
    tf = requested_tf.lower() if requested_tf else "5m"
    label = next((k for k, (code, _) in TIMEFRAMES.items() if code == tf), "5 دقائق")
    await update.message.reply_text(f"جارٍ تحليل Pocket Option OTC: {pair} على {label}...")
    result = await asyncio.to_thread(analyze_otc_poc, f"{pair} OTC", symbol, label)
    if not result:
        await update.message.reply_text("لا توجد إشارة مؤكدة الآن؛ لم يتحقق شرط POC وإغلاق شمعة التأكيد.")
        return
    save_signal(update.effective_chat.id, result)
    await update.message.reply_text(signal_text(result), reply_markup=main_keyboard())


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_history(update.effective_chat.id, update.message)


async def auto_status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        format_status(update.effective_chat.id),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹️ إيقاف المحاكاة", callback_data="auto_stop")],
            [InlineKeyboardButton("📜 سجل الصفقات", callback_data="auto_trades")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")],
        ]),
    )


async def auto_trades_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_trade_history(update.effective_chat.id, 10)
    if not rows:
        await update.message.reply_text("لا توجد صفقات تجريبية مسجلة بعد.", reply_markup=main_keyboard())
        return
    lines = ["📜 سجل آخر الصفقات التجريبية", ""]
    for row in rows:
        status = "مفتوحة" if row["status"] == "open" else "مغلقة"
        pnl = "قيد المتابعة" if row["pnl"] is None else f"{row['pnl']:+.2f}"
        lines.append(
            f"{'🟡' if row['status'] == 'open' else '⚪'} {row['asset']} | {row['direction']} | {status}\n"
            f"الدخول: {row['entry']:.6g} | الوقف: {row['stop_loss']:.6g} | الهدف: {row['take_profit']:.6g}\n"
            f"النتيجة: {pnl}"
        )
    await send_long(update.message, "\n\n".join(lines))


async def stop_auto_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stopped = stop_session(update.effective_chat.id)
    await update.message.reply_text(
        "تم إيقاف جلسة المحاكاة وإغلاق الصفقة الافتراضية المفتوحة إن وجدت."
        if stopped else "لا توجد جلسة محاكاة نشطة حالياً.",
        reply_markup=main_keyboard(),
    )


async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ai_history", None)
    await update.message.reply_text("تم مسح سياق المحادثة.", reply_markup=main_keyboard())


async def pro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request_id = create_pro_request(update.effective_chat.id)
    await update.message.reply_text(pro_offer_text(request_id), reply_markup=main_keyboard())
    if OWNER_ID:
        try:
            await context.bot.send_message(
                chat_id=int(OWNER_ID),
                text=f"طلب اشتراك PRO جديد #{request_id} من المستخدم {update.effective_chat.id}. للتفعيل: /activate {update.effective_chat.id} 30"
            )
        except Exception as exc:
            print(f"PRO admin notification failed: {type(exc).__name__}")

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Telegram ID الخاص بحسابك: {update.effective_user.id}\n"
        "إذا كنت مالك البوت، ضع هذا الرقم في متغير الاستضافة OWNER_TELEGRAM_ID."
    )

async def substatus_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(subscription_message(update.effective_chat.id), reply_markup=main_keyboard())

async def activate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != OWNER_ID:
        await update.message.reply_text("هذا الأمر مخصص لمالك البوت فقط.")
        return
    if not context.args or len(context.args) not in (1, 2):
        await update.message.reply_text("الاستخدام: /activate TELEGRAM_ID [DAYS] — مثال /activate 123456789 30")
        return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1]) if len(context.args) == 2 else 30
        until = activate_pro(target_id, days)
    except (ValueError, TypeError) as exc:
        await update.message.reply_text(f"تعذر التفعيل: {exc}")
        return
    await update.message.reply_text(f"تم تفعيل PRO للمستخدم {target_id} حتى {until.strftime('%Y-%m-%d %H:%M UTC')}.")
    try:
        await context.bot.send_message(chat_id=target_id, text=f"💎 تم تفعيل اشتراك NUMBER ONE PRO لمدة {days} يوماً.\nينتهي في {until.strftime('%Y-%m-%d %H:%M UTC')}.")
    except Exception as exc:
        print(f"PRO activation notice failed: {type(exc).__name__}")

async def payment_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo:
        return
    if not OWNER_ID:
        await update.message.reply_text("استلام إثبات الدفع غير مهيأ بعد. يرجى التواصل مع إدارة البوت.")
        return
    user = update.effective_user
    caption = (
        "📥 إثبات دفع اشتراك PRO\n"
        f"المستخدم: {user.full_name}\n"
        f"Telegram ID: {update.effective_chat.id}\n"
        f"Username: @{user.username or 'غير متاح'}\n"
        "راجع التحويل ثم فعّل الاشتراك بالأمر: /activate TELEGRAM_ID 30"
    )
    try:
        await context.bot.send_message(chat_id=int(OWNER_ID), text=caption)
        await context.bot.forward_message(
            chat_id=int(OWNER_ID), from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id
        )
        await update.message.reply_text("تم إرسال إثبات الدفع إلى إدارة البوت للمراجعة. لن يتفعل الاشتراك إلا بعد التحقق اليدوي.")
    except Exception as exc:
        print(f"Payment proof forwarding failed: {type(exc).__name__}")
        await update.message.reply_text("تعذر إرسال الإثبات للإدارة الآن. حاول لاحقاً.")

async def auto_trading_worker(app):
    init_auto_db()
    while True:
        try:
            notices = await asyncio.to_thread(run_cycle)
            # The legacy crypto signal watcher is intentionally not scanned here:
            # the primary signal product is Pocket Option OTC only.
            for chat_id, message in notices:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=message)
                except Exception as exc:
                    print(f"Auto-trader notification failed: {type(exc).__name__}")
        except Exception as exc:
            print(f"Auto-trader cycle failed: {type(exc).__name__}")
        await asyncio.sleep(60)


async def post_init(app):
    app.create_task(auto_trading_worker(app), name="auto-trading-worker")


def main():
    if not TOKEN:
        raise RuntimeError("يجب ضبط TELEGRAM_BOT_TOKEN كمتغير سري في خدمة الاستضافة.")
    init_db()
    init_auto_db()
    init_signal_monitor()
    init_subscriptions()
    init_trading_tools()
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("account", lambda u, c: show_my_account(u.effective_user, u.message)))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("markets", lambda u, c: u.message.reply_text("الدليل الإرشادي الذكي — قريباً. الخدمة متوقفة مؤقتاً حتى حل مشكلة مصدر بيانات Pocket Option OTC.")))
    app.add_handler(CommandHandler("pro", pro_command))
    app.add_handler(CommandHandler("substatus", substatus_command))
    app.add_handler(CommandHandler("id", id_command))
    app.add_handler(CommandHandler("activate", activate_command))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("journal", journal_command))
    app.add_handler(CommandHandler("performance", performance_command))
    app.add_handler(CommandHandler("learn", lambda u, c: show_learning(u.effective_chat.id, u.message)))
    app.add_handler(CommandHandler("discipline", lambda u, c: show_discipline(u.effective_chat.id, u.message)))
    app.add_handler(CommandHandler("risk", lambda u, c: risk_command(u, c)))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("auto", lambda u, c: u.message.reply_text("افتح زر التداول الآلي من القائمة الرئيسية.", reply_markup=main_keyboard())))
    app.add_handler(CommandHandler("status", auto_status_command))
    app.add_handler(CommandHandler("trades", auto_trades_command))
    app.add_handler(CommandHandler("stop", stop_auto_command))
    app.add_handler(CommandHandler("reset", reset_chat))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, payment_photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("NUMBER ONE TRADER AI Telegram bot is running.")
    print("AI assistant enabled." if client else "AI assistant disabled: OPENAI_API_KEY missing.")
    app.run_polling()

if __name__ == "__main__":
    main()