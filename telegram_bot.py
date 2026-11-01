"""NUMBER ONE TRADER AI — واجهة تيليجرام عربية احترافية."""
import os
import asyncio
import sqlite3
from datetime import datetime, timezone

from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from engine import ASSETS, TIMEFRAMES, analyze_asset
from auto_trader import init_auto_db, start_session, stop_session, format_status, run_cycle

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
DB_PATH = os.getenv("BOT_DB_PATH", "number_one_bot.sqlite3")
client = OpenAI(api_key=OPENAI_API_KEY, timeout=45.0) if OPENAI_API_KEY else None

SYSTEM_PROMPT = """أنت المساعد الذكي الرسمي في NUMBER ONE TRADER AI.
أجب بالعربية الواضحة. اشرح التداول والمؤشرات للمبتدئين.
لا تخترع أسعارًا أو بيانات لحظية أو نتائج. لا تدّع ضمان الأرباح.
التحليل تعليمي وليس نصيحة مالية. لا تنفذ صفقات حقيقية ولا تطلب كلمات مرور أو مفاتيح سرية.
"""

GOLD = "◆"
HELP_TEXT = (
    "مرحباً بك في NUMBER ONE TRADER AI\n"
    "مساعدك الذكي لتحليل الأسواق ومتابعة الإشارات.\n\n"
    "اختر من القائمة بالأسفل للبدء. يمكنك أيضاً إرسال سؤالك مباشرة للمساعد الذكي."
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
        [InlineKeyboardButton("🤖 التداول الآلي التجريبي", callback_data="auto"),
         InlineKeyboardButton("📊 تحليل الأسواق", callback_data="markets")],
        [InlineKeyboardButton("📡 الإشارات", callback_data="signals"),
         InlineKeyboardButton("🧭 الفحص السريع", callback_data="quickscan")],
        [InlineKeyboardButton("🔎 تحليل أصل محدد", callback_data="markets"),
         InlineKeyboardButton("📈 حالة التداول الآلي", callback_data="auto_status")],
        [InlineKeyboardButton("🕘 سجل تحليلاتي", callback_data="history"),
         InlineKeyboardButton("⚙️ إعداداتي", callback_data="settings")],
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
    await update.message.reply_text(HELP_TEXT, reply_markup=main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📘 دليل NUMBER ONE TRADER AI\n\n"
        "1) اختر السوق.\n2) اختر الأصل.\n3) اختر الفاصل الزمني.\n"
        "4) اطلب التحليل لعرض الاتجاه ومستويات الدخول والوقف والهدف.\n\n"
        "الأوامر: /start /markets /analyze /history /reset /help\n"
        "يمكنك إرسال سؤالك مباشرة للمساعد الذكي.",
        reply_markup=main_keyboard()
    )

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
            "🤖 إعداد التداول الآلي التجريبي\\n\\nاختر مدة تشغيل النظام. سيعمل على الخادم حتى لو أغلقت شاشة هاتفك. هذه نسخة محاكاة ولا ترسل أوامر بأموال حقيقية.",
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
            f"إعداداتك: مدة {context.user_data['auto_setup']['duration']} ساعة، مخاطرة {context.user_data['auto_setup']['risk']}%، حد خسارة يومية {daily}%.\\n\\nأرسل الآن مبلغ رأس المال الافتراضي بالأرقام فقط، مثلاً 100."
        )
    elif data == "auto_status":
        await q.edit_message_text(format_status(q.message.chat_id), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏹️ إيقاف التداول الآلي", callback_data="auto_stop")],
            [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
        ]))
    elif data == "auto_stop":
        stopped = stop_session(q.message.chat_id)
        await q.edit_message_text(
            "تم إيقاف فتح صفقات جديدة في المحاكاة." if stopped else "لا توجد جلسة نشطة لإيقافها.",
            reply_markup=main_keyboard()
        )
    elif data == "home":
        await q.edit_message_text(HELP_TEXT, reply_markup=main_keyboard())
    elif data == "markets":
        await q.edit_message_text("🌐 اختر السوق الذي تريد تحليله:", reply_markup=markets_keyboard())
    elif data.startswith("market:"):
        mi = int(data.split(":")[1])
        context.user_data["market_index"] = mi
        market = list(ASSETS.keys())[mi]
        await q.edit_message_text(f"اختر الأصل من سوق {market}:", reply_markup=assets_keyboard(mi))
    elif data.startswith("asset:"):
        _, mi, ai = data.split(":")
        market = list(ASSETS.keys())[int(mi)]
        name, symbol = list(ASSETS[market].items())[int(ai)]
        context.user_data["asset"] = (name, symbol, market)
        await q.edit_message_text(
            f"تم اختيار {name} ({symbol}).\nاختر الفاصل الزمني:",
            reply_markup=timeframe_keyboard()
        )
    elif data.startswith("tf:"):
        idx = int(data.split(":")[1])
        label = list(TIMEFRAMES.keys())[idx]
        context.user_data["timeframe"] = label
        await q.edit_message_text(
            f"تم اختيار الفاصل: {label}\nهل تريد بدء التحليل؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 ابدأ التحليل الآن", callback_data="analyze")],
                [InlineKeyboardButton("⏱️ تغيير الفاصل", callback_data="change_tf"),
                 InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "change_tf":
        await q.edit_message_text("اختر الفاصل الزمني:", reply_markup=timeframe_keyboard())
    elif data in ("analyze", "reanalyze"):
        await analyze_selected(update, context, q)
    elif data == "signals":
        await q.edit_message_text(
            "📡 مركز الإشارات\n\nاختر أصلاً وفاصلاً زمنياً للحصول على قراءة فنية محدثة. "
            "لا يتم إرسال إشارات تلقائية في الخلفية حالياً.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔎 اختر أصلاً للتحليل", callback_data="markets")],
                [InlineKeyboardButton("🏠 الرئيسية", callback_data="home")]
            ])
        )
    elif data == "quickscan":
        await q.edit_message_text(
            "🧭 الفحص السريع\nاختر السوق أولاً، ثم الأصل والفاصل الزمني. "
            "الفحص الشامل المجدول سيضاف بعد تجهيز خدمة التشغيل المستمر.",
            reply_markup=markets_keyboard()
        )
    elif data == "history":
        await show_history(q.message.chat_id, q.message)
    elif data == "settings":
        current = context.user_data.get("timeframe", "5 دقائق")
        await q.edit_message_text(
            f"⚙️ إعداداتك الحالية\nالفاصل الافتراضي: {current}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏱️ تغيير الفاصل الافتراضي", callback_data="change_tf")],
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
    if context.user_data.get("awaiting_auto_capital"):
        raw = update.message.text.strip().replace(",", "")
        try:
            capital = float(raw)
            setup = context.user_data.get("auto_setup", {})
            start_session(update.effective_chat.id, capital, setup["duration"], setup["risk"], setup["daily"])
            context.user_data["awaiting_auto_capital"] = False
            context.user_data.pop("auto_setup", None)
            await update.message.reply_text(
                "🟢 بدأ التداول الآلي التجريبي على الخادم. يمكنك إغلاق شاشة الهاتف.\\n"
                f"الرصيد الافتراضي: {capital:.2f}\\n"
                "الأسواق الحالية: العملات الرقمية فقط\\n"
                "النظام يفتح صفقة تجريبية واحدة كحد أقصى، ويوقف الجلسة عند بلوغ حد الخسارة اليومية.\\n"
                "استخدم زر حالة التداول لمتابعة النتائج أو إيقاف الجلسة. لا توجد أموال حقيقية مستخدمة.",
                reply_markup=main_keyboard()
            )
        except (ValueError, KeyError):
            await update.message.reply_text("أرسل مبلغاً رقمياً أكبر من صفر، مثل 100.")
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

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("مثال: /analyze BTCUSDT 5m")
        return
    requested = context.args[0].upper()
    found = None
    for market, items in ASSETS.items():
        for name, symbol in items.items():
            if requested in (name.upper(), symbol.upper()):
                found = (name, symbol, market)
                break
        if found:
            break
    if not found:
        await update.message.reply_text("الأصل غير معروف. استخدم /markets.")
        return
    timeframe_code = context.args[1] if len(context.args) > 1 else "5m"
    label = next((k for k, (code, _) in TIMEFRAMES.items() if code == timeframe_code), None)
    if not label:
        await update.message.reply_text("الفواصل: 1m، 5m، 15m، 30m، 1h، 4h")
        return
    context.user_data["asset"] = found
    context.user_data["timeframe"] = label
    await update.message.reply_text("⏳ جارٍ التحليل...")
    try:
        result = await asyncio.to_thread(analyze_asset, *found, label, "جميع الإشارات")
    except Exception:
        result = None
    if not result:
        await update.message.reply_text("لا توجد إشارة واضحة أو البيانات غير متاحة الآن.")
        return
    save_signal(update.effective_chat.id, result)
    await update.message.reply_text(signal_text(result), reply_markup=main_keyboard())

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_history(update.effective_chat.id, update.message)

async def reset_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ai_history", None)
    await update.message.reply_text("تم مسح سياق المحادثة.", reply_markup=main_keyboard())

async def auto_trading_worker(app):
    init_auto_db()
    while True:
        try:
            notices = await asyncio.to_thread(run_cycle)
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
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("markets", lambda u, c: u.message.reply_text("اختر السوق:", reply_markup=markets_keyboard())))
    app.add_handler(CommandHandler("analyze", analyze_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("reset", reset_chat))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("NUMBER ONE TRADER AI Telegram bot is running.")
    print("AI assistant enabled." if client else "AI assistant disabled: OPENAI_API_KEY missing.")
    app.run_polling()

if __name__ == "__main__":
    main()
