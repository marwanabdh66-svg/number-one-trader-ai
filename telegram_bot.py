"""بوت Telegram لمشروع NUMBER ONE TRADER AI.
شغّله بعد وضع TELEGRAM_BOT_TOKEN في متغيرات البيئة.
"""
import os
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from engine import ASSETS, TIMEFRAMES, analyze_asset

TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
HELP="""أوامر البوت:
/start بدء الاستخدام
/markets عرض الأسواق
/analyze BTCUSDT 5m تحليل أصل
/signals آخر الإشارات
/history سجل التحليل
/demo التداول التجريبي
/settings الإعدادات
/help المساعدة

هذه إشارات تحليلية وليست توصية مالية."""
def find_asset(q):
    for market,items in ASSETS.items():
        for name,symbol in items.items():
            if q.upper() in (name.upper(),symbol.upper()): return name,symbol,market
    return None
async def start(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("مرحبًا بك في NUMBER ONE TRADER AI 📈\n\n"+HELP)
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
    result=await asyncio.to_thread(analyze_asset,name,symbol,market,tf,"جميع الإشارات")
    if not result:
        await update.message.reply_text("لا توجد إشارة واضحة أو البيانات غير متاحة الآن.");return
    arrow="🟢 صعود" if result["direction"]=="صعود" else "🔴 هبوط"
    await update.message.reply_text(f"الأصل: {name} ({symbol})\nالاتجاه: {arrow}\nالفاصل: {tf}\nالقوة: {result['confidence']}%\nالدخول: {result['entry']:.6f}\nوقف الخسارة: {result['stop_loss']:.6f}\nالهدف: {result['take_profit']:.6f}\nRSI: {result['rsi']}\nالمصدر: {result['source']}\n\nتحليل فني تجريبي، وليس ضمانًا للربح.")
async def signals(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("استخدم /analyze متبوعًا برمز الأصل والفاصل للحصول على تحليل جديد.")
async def history(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سجل الإشارات الكامل موجود في صفحة سجل الإشارات بالموقع.")
async def demo(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("التداول التجريبي متاح من محاكي التداول في الموقع. لا ينفذ البوت صفقات حقيقية.")
async def settings(update:Update,context:ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("الفواصل: 1m، 5m، 15m، 30m، 1h، 4h.\nيمكن تغيير بقية الإعدادات من الموقع.")
def main():
    if not TOKEN: raise RuntimeError("يجب ضبط TELEGRAM_BOT_TOKEN كمتغير سري.")
    app=Application.builder().token(TOKEN).build()
    for command,fn in [("start",start),("markets",markets),("analyze",analyze),("signals",signals),("history",history),("demo",demo),("settings",settings),("help",start)]:
        app.add_handler(CommandHandler(command,fn))
    print("NUMBER ONE TRADER AI Telegram bot is running.")
    app.run_polling()
if __name__=="__main__": main()
