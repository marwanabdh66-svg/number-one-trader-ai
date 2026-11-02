"""دليل اتجاهي تجريبي قائم على بيانات الشموع المتاحة، وليس تنفيذ صفقات."""
from __future__ import annotations

from engine import ASSETS, TIMEFRAMES, fetch_market_data, calculate_indicators


def find_asset(request: str):
    normalized = request.strip().upper().replace(" ", "")
    for market, items in ASSETS.items():
        for name, symbol in items.items():
            if normalized in (name.upper().replace(" ", ""), symbol.upper().replace(" ", "")):
                return name, symbol, market
    return None


def smart_guide(request: str, timeframe: str = "5 دقائق") -> str:
    """Return a transparent direction guide. OTC symbols require broker-native data."""
    raw = request.strip()
    if "OTC" in raw.upper():
        return (
            "🧭 الدليل الإرشادي الذكي — Pocket Option OTC\n\n"
            f"الأصل المطلوب: {raw}\n"
            "⏸️ لا توجد إشارة مؤكدة حالياً.\n"
            "سبب التوقف: لا يتوفر داخل المشروع حتى الآن مصدر بيانات شموع مباشر وموثوق "
            "خاص بـ Pocket Option OTC لهذا الزوج. بيانات Binance أو Yahoo لا تطابق بالضرورة "
            "سعر OTC لدى الوسيط، لذلك لن أختلق اتجاه صعود أو هبوط ولا قيمة POC.\n\n"
            "الحالة: موصل بيانات Pocket Option OTC قيد التطوير. "
            "لن يتم تنفيذ أي صفقة حقيقية."
        )

    found = find_asset(raw)
    if not found:
        supported = ", ".join(list(ASSETS.get("العملات الرقمية", {}).keys())[:6])
        return (
            "لم أتعرف على الأصل المطلوب أو لم أجد له مصدر بيانات مدعوماً.\n"
            f"جرّب أحد هذه الأصول: {supported}\n"
            "أما أزواج OTC في Pocket Option فتحتاج إلى مصدر بيانات الوسيط."
        )

    name, symbol, market = found
    frame, source = fetch_market_data(symbol, timeframe)
    data = calculate_indicators(frame)
    if data.empty or len(data) < 20:
        return (
            f"🧭 الدليل الإرشادي: {name}\n"
            "⏸️ لا توجد إشارة واضحة — بيانات الشموع غير كافية أو المصدر غير متاح."
        )

    last = data.iloc[-1]
    close = float(last["close"])
    votes_up = 0
    votes_down = 0
    reasons = []

    if last["ema9"] > last["ema21"] > last["ema50"]:
        votes_up += 2
        reasons.append("ترتيب المتوسطات EMA صاعد")
    elif last["ema9"] < last["ema21"] < last["ema50"]:
        votes_down += 2
        reasons.append("ترتيب المتوسطات EMA هابط")

    if last["macd"] > last["macd_signal"]:
        votes_up += 1
        reasons.append("MACD فوق خط الإشارة")
    else:
        votes_down += 1
        reasons.append("MACD تحت خط الإشارة")

    rsi = float(last["rsi"])
    if 52 <= rsi <= 68:
        votes_up += 1
        reasons.append(f"RSI يدعم الزخم الصاعد ({rsi:.1f})")
    elif 32 <= rsi <= 48:
        votes_down += 1
        reasons.append(f"RSI يدعم الزخم الهابط ({rsi:.1f})")

    # Approximate volume-profile POC from available candle volume and price bins.
    profile = data.tail(120).copy()
    low = float(profile["low"].min())
    high = float(profile["high"].max())
    poc = None
    if high > low:
        bins =  thirty = 30
        width = (high - low) / bins
        volumes = [0.0] * bins
        for _, candle in profile.iterrows():
            typical = (float(candle["high"]) + float(candle["low"]) + float(candle["close"])) / 3
            idx = max(0, min(bins - 1, int((typical - low) / width)))
            volumes[idx] += max(0.0, float(candle.get("volume", 0) or 0))
        if max(volumes, default=0) > 0:
            poc = low + (volumes.index(max(volumes)) + 0.5) * width

    if poc is not None:
        if close > poc:
            votes_up += 1
            reasons.append("السعر أعلى من POC التقريبي")
        elif close < poc:
            votes_down += 1
            reasons.append("السعر أسفل من POC التقريبي")

    candle = data.iloc[-1]
    body = abs(float(candle["close"]) - float(candle["open"]))
    upper_wick = float(candle["high"]) - max(float(candle["close"]), float(candle["open"]))
    lower_wick = min(float(candle["close"]), float(candle["open"])) - float(candle["low"])
    if lower_wick > body * 1.5 and float(candle["close"]) > float(candle["open"]):
        votes_up += 1
        reasons.append("شمعة رفض هبوط بذيل سفلي")
    elif upper_wick > body * 1.5 and float(candle["close"]) < float(candle["open"]):
        votes_down += 1
        reasons.append("شمعة رفض صعود بذيل علوي")

    difference = votes_up - votes_down
    if difference >= 3:
        direction = "⬆️ احتمال صعود"
    elif difference <= -3:
        direction = "⬇️ احتمال هبوط"
    else:
        direction = "⏸️ لا توجد إشارة واضحة"

    strength = min(90, 50 + abs(difference) * 8)
    poc_line = f"{poc:.6g}" if poc is not None else "غير متاح (حجم تداول مفقود)"
    return (
        "🧭 NUMBER ONE — الدليل الإرشادي الذكي\n\n"
        f"الأصل: {name} ({symbol})\n"
        f"السوق: {market}\n"
        f"الفاصل: {timeframe}\n"
        f"الاتجاه: {direction}\n"
        f"قوة توافق القواعد: {strength}% (ليست احتمال ربح إحصائياً)\n"
        f"السعر المرجعي: {close:.6g}\n"
        f"POC تقريبي: {poc_line}\n"
        f"مصدر البيانات: {source}\n\n"
        "أسباب التحليل:\n- " + "\n- ".join(reasons) + "\n\n"
        "⚠️ تحليل تجريبي فقط؛ قد يتأخر المصدر أو تختلف الأسعار عن الوسيط. "
        "لا يضمن النتيجة ولا ينفذ صفقات."
    )
