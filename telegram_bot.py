"""بوت NUMBER ONE TRADER AI مع مساعد محادثة يعمل عبر OpenAI Responses API.
المفاتيح السرية تُقرأ من متغيرات البيئة ولا تحفظ في ملفات المشروع.
"""
import os
import asyncio
from openai import OpenAI
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from engine import ASSETS, TIMEFRAMES, analyze_asset

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-4.1-mini")
client=OpenAI(api_key=OPENAI_API_KEY,timeout=45.0) if OPENAI_API_KEY else None

SYSTEM_PROMPT="""أنت المساعد الذكي الرسمي داخل NUMBER ONE TRADER AI.
تحدث باللغة العربية الواضحة وبأسلوب مختصر ومفيد، ويمكنك شرح المصطلحات للمبتدئين.
ساعد المستخدم في فهم الأسواق والتحليل الفني والمؤشرات وإدارة المخاطر واستخدام المنصة.
لا تدّعِ أنك تملك أسعارًا مباشرة أو بيانات لحظية ما لم تُرسل لك بيانات فعلية في سياق الرسالة.
إذا طلب المستخدم تحليلًا حيًا لأصل، اطلب منه استخدام الأمر /analyze BTCUSDT 5m أو إرسال الرمز والفاصل للأمر.
لا تخترع أسعارًا أو إشارات أو نتائج تداول. وضّح أن التحليل تعليمي وليس نصيحة مالية ولا ضمانًا للربح.
لا تنفذ أو توحي بتنفيذ صفقات حقيقية أو عمليات مالية. لا تطلب كلمات مرور أو مفاتيح API أو رموز البوت.
إذا كان السؤال خارج التداول، أجب عنه بشكل طبيعي وآمن.
"""

HELP="""مرحبًا بك في NUMBER ONE TRADER AI 📈

يمكنك الآن كتابة سؤالك بالعربية مباشرة لمحادثة المساعد الذكي.

الأوامر:
/start بدء الاستخدام
/markets عرض الأسواق
/analyze BTCUSDT 5m تحليل أصل
/signals طلب طريقة عرض الإشارات
/history سجل التحليل
/demo التداول التجريبي
/settings الإعدادات
/reset مسح ذاكرة المحادثة الحالية
/ask اطرح سؤالًا على ChatGPT\n/reset بدء محادثة جديدة\n/help المساعدة

ملاحظة: التحليل تعليمي ولا يضمن الأرباح."""

def find_asset(q):
    for market,items in ASSETS.items():
        for name,symbol in items.items():
            if q.upper() in (name.upper(),symbol.upper()): return name,symbol,market
    return None

async def send_long(message,text):
    text=text or "لم أتمكن من تكوين رد."
    for start in range(0,len(text),3900):
        await message.reply_text(text[start:start+3900])

async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)

async def markets(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("\n".join("• "+m+": "+", ".join(a.keys()) for m,a in ASSETS.items()))

async def analyze(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("مثال: /analyze BTCUSDT 5m");return
    found=find_asset(context.args[0])
    if not found:
        await update.message.reply_text("الأصل غير معروف. استخدم /markets.");return
    name,symbol,market=found; code=context.args[1] if len(context.args)>1 else "5m"
    tf=next((label for label,(c,y) in TIMEFRAMES.items() if c==code),None)
    if not tf:
        await update.message.reply_text("الفواصل: 1m، 5m، 15m، 30m، 1h، 4h");return
    await update.message.reply_text("جارٍ تحليل الأصل...")
    try:
        result=await asyncio.to_thread(analyze_asset,name,symbol,market,tf,"جميع الإشارات")
    except Exception:
        result=None
    if not result:
        await update.message.reply_text("لا توجد إشارة واضحة أو البيانات غير متاحة الآن.");return
    arrow="🟢 صعود" if result["direction"]=="صعود" else "🔴 هبوط"
    await update.message.reply_text(f"الأصل: {name} ({symbol})\nالاتجاه: {arrow}\nالفاصل: {tf}\nقوة توافق المؤشرات: {result['confidence']}%\nالدخول المرجعي: {result['entry']:.6f}\nوقف الخسارة الحسابي: {result['stop_loss']:.6f}\nالهدف الحسابي: {result['take_profit']:.6f}\nRSI: {result['rsi']}\nالمصدر: {result['source']}\n\nهذه قراءة فنية تجريبية وليست ضمانًا للربح.")

async def signals(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لتحليل إشارة محدثة استخدم مثلًا:\n/analyze BTCUSDT 5m")

async def history(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سجل الإشارات الكامل موجود في صفحة سجل الإشارات بالموقع.")

async def demo(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("التداول التجريبي متاح من محاكي التداول في الموقع. لا ينفذ البوت صفقات حقيقية.")

async def settings(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("الفواصل المتاحة: 1m، 5m، 15m، 30m، 1h، 4h.\nيمكن تغيير بقية الإعدادات من الموقع.")

async def reset_chat(update:Update,context:ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("ai_history",None)
    await update.message.reply_text("تم مسح سياق المحادثة الحالية. ابدأ سؤالًا جديدًا.")

def ask_openai(history):
    response=client.responses.create(
        model=OPENAI_MODEL,
        instructions=SYSTEM_PROMPT,
        input=history,
        max_output_tokens=700,
        store=False,
    )
    return response.output_text

async def chat_with_ai(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    if client is None:
        await update.message.reply_text(
            "ميزة المحادثة الذكية غير مفعّلة بعد.\n"
            "يلزم إضافة مفتاح OPENAI_API_KEY إلى أسرار تشغيل البوت.\n"
            "يمكنك استخدام أوامر تحليل السوق الحالية مثل /analyze BTCUSDT 5m."
        )
        return
    history=context.user_data.setdefault("ai_history",[])
    history.append({"role":"user","content":update.message.text[:4000]})
    # نحتفظ بآخر 12 رسالة فقط لتقليل التكلفة وحجم الطلب.
    history=history[-12:]
    await update.message.chat.send_action("typing")
    try:
        answer=await asyncio.to_thread(ask_openai,history)
        if not answer:
            answer="لم يصلني رد نصي. حاول صياغة السؤال بطريقة أخرى."
        history.append({"role":"assistant","content":answer})
        context.user_data["ai_history"]=history[-12:]
        await send_long(update.message,answer)
    except Exception as exc:
        # لا نرسل تفاصيل الخطأ أو بيانات الاعتماد للمستخدم.
        print(f"OpenAI request failed: {type(exc).__name__}")
        await update.message.reply_text("تعذر الاتصال بالمساعد الذكي الآن. تحقق من إعداد المفتاح ورصيد واجهة API ثم حاول مجددًا.")


async def ask_command(update:Update,context:ContextTypes.DEFAULT_TYPE):
    question=" ".join(context.args).strip()
    if not question:
        await update.message.reply_text("اكتب سؤالك بعد الأمر، مثال:\\n/ask ما معنى مؤشر RSI؟")
        return
    update.message.text=question
    await chat_with_ai(update,context)

def main():
    if not TOKEN: raise RuntimeError("يجب ضبط TELEGRAM_BOT_TOKEN كمتغير سري.")
    app=Application.builder().token(TOKEN).build()
    for command,fn in [
        ("start",start),("markets",markets),("analyze",analyze),
        ("signals",signals),("history",history),("demo",demo),
        ("settings",settings),("ask",ask_command),("reset",reset_chat),("help",start)
    ]:
        app.add_handler(CommandHandler(command,fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,chat_with_ai))
    print("NUMBER ONE TRADER AI Telegram bot is running.")
    print("OpenAI chat enabled." if client else "OpenAI chat disabled: OPENAI_API_KEY is missing.")
    app.run_polling()

if __name__=="__main__": main()
