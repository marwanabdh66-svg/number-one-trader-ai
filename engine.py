"""محرك تحليل فني تجريبي لـ NUMBER ONE TRADER AI.
البيانات تأتي من Binance للعملات الرقمية وYahoo Finance لبقية الأسواق.
لا يرسل أوامر تداول حقيقية ولا يضمن النتائج.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math
import time

import pandas as pd
import requests
import yfinance as yf

BINANCE_KLINES = "https://data-api.binance.vision/api/v3/klines"
OTCHARTS_BASE = "https://otcharts.com/v1"
OTCHARTS_API_KEY = __import__("os").getenv("OTCHARTS_API_KEY", "").strip()
OTC_TIMEFRAMES = {"1 دقيقة": 60, "5 دقائق": 300, "15 دقيقة": 900, "30 دقيقة": 1800, "ساعة": 3600, "4 ساعات": 14400}
_OTC_SYMBOL_CACHE: dict[str, tuple[float, str]] = {}
_OTC_SYMBOL_CACHE_TTL = 300


TIMEFRAMES = {
    "1 دقيقة": ("1m", "1m"),
    "5 دقائق": ("5m", "5m"),
    "15 دقيقة": ("15m", "15m"),
    "30 دقيقة": ("30m", "30m"),
    "ساعة": ("1h", "60m"),
    "4 ساعات": ("4h", "60m"),
}

ASSETS = {
    "العملات الرقمية": {
        "BTC/USDT": "BTCUSDT", "ETH/USDT": "ETHUSDT",
        "BNB/USDT": "BNBUSDT", "SOL/USDT": "SOLUSDT",
        "XRP/USDT": "XRPUSDT", "ADA/USDT": "ADAUSDT",
        "DOGE/USDT": "DOGEUSDT", "AVAX/USDT": "AVAXUSDT",
        "LINK/USDT": "LINKUSDT", "TRX/USDT": "TRXUSDT",
    },
    "الفوركس": {
        "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X",
        "USD/JPY": "USDJPY=X", "USD/CHF": "USDCHF=X",
        "AUD/USD": "AUDUSD=X", "USD/CAD": "USDCAD=X",
        "NZD/USD": "NZDUSD=X",
    },
    "الذهب والسلع": {
        "الذهب": "GC=F", "الفضة": "SI=F",
        "النفط الأمريكي": "CL=F", "الغاز الطبيعي": "NG=F",
    },
    "الأسهم الأمريكية": {
        "Apple": "AAPL", "Microsoft": "MSFT", "NVIDIA": "NVDA",
        "Amazon": "AMZN", "Tesla": "TSLA", "Google": "GOOGL",
        "Meta": "META", "Netflix": "NFLX",
    },
    "المؤشرات": {
        "S&P 500": "^GSPC", "Nasdaq 100": "^NDX",
        "Dow Jones": "^DJI",
    },
}

def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.columns = [str(c).lower().replace(" ", "_") for c in frame.columns]
    required = ["open", "high", "low", "close"]
    if not all(c in frame.columns for c in required):
        return pd.DataFrame()
    if "volume" not in frame.columns:
        frame["volume"] = 0
    frame = frame[["open", "high", "low", "close", "volume"]].copy()
    for col in frame.columns:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])

def fetch_market_data(symbol: str, timeframe_label: str, period: str = "5d") -> tuple[pd.DataFrame, str]:
    """Fetch candles. Return (OHLCV, source label)."""
    # Pocket Option OTC feed through a third-party read-only API.
    if symbol.endswith("_otc"):
        if not OTCHARTS_API_KEY:
            return pd.DataFrame(), "OTCharts (مفتاح API غير مضبوط)"
        try:
            tf_seconds = OTC_TIMEFRAMES.get(timeframe_label, 300)
            response = requests.get(
                f"{OTCHARTS_BASE}/candles",
                params={"venue": "otc", "symbol": symbol, "tf": tf_seconds, "limit": 300},
                headers={"Authorization": f"Bearer {OTCHARTS_API_KEY}", "User-Agent": "NUMBER-ONE-TRADER-AI/1.0"},
                timeout=15,
            )
            response.raise_for_status()
            candles = response.json().get("candles", [])
            if not candles:
                return pd.DataFrame(), "OTCharts (لا توجد شموع)"
            frame = pd.DataFrame(candles).rename(columns={"time": "timestamp"})
            if "timestamp" in frame.columns:
                frame.index = pd.to_datetime(frame["timestamp"], unit="s", utc=True)
            return _normalize(frame), "OTCharts Pocket Option OTC"
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            detail = (exc.response.text[:240].replace("\n", " ") if exc.response is not None else "")
            print(f"OTCharts OTC request failed: HTTP {status}; {detail}")
            return pd.DataFrame(), f"OTCharts (HTTP {status})"
        except Exception as exc:
            print(f"OTCharts OTC request failed: {type(exc).__name__}")
            return pd.DataFrame(), "OTCharts (غير متاح)"

    interval, yahoo_interval = TIMEFRAMES[timeframe_label]
    if symbol.endswith("USDT") and "/" not in symbol:
        try:
            response = requests.get(
                BINANCE_KLINES,
                params={"symbol": symbol, "interval": interval, "limit": 500},
                timeout=12,
                headers={"User-Agent": "NUMBER-ONE-TRADER-AI/1.0"},
            )
            response.raise_for_status()
            raw = response.json()
            frame = pd.DataFrame(raw, columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades", "taker_buy_base",
                "taker_buy_quote", "ignore",
            ])
            frame.index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
            frame = _normalize(frame)
            return frame, "Binance"
        except Exception:
            pass

    try:
        ticker = yf.Ticker(symbol)
        use_interval = yahoo_interval
        use_period = "5d" if use_interval in ("1m", "5m", "15m", "30m") else "60d"
        frame = ticker.history(period=use_period, interval=use_interval, auto_adjust=False)
        frame = _normalize(frame)
        if timeframe_label == "4 ساعات" and not frame.empty:
            frame = frame.resample("4h").agg({
                "open": "first", "high": "max", "low": "min",
                "close": "last", "volume": "sum",
            }).dropna()
        return frame, "Yahoo Finance"
    except Exception:
        return pd.DataFrame(), "غير متاح"

def resolve_otc_symbol(pair: str) -> str | None:
    """Resolve a pair only from the API's Pocket Option OTC catalogue; never guess ids."""
    if not OTCHARTS_API_KEY:
        return None
    normalized = pair.upper().replace("/", "").replace("-", "").replace(" ", "")
    cached = _OTC_SYMBOL_CACHE.get(normalized)
    if cached and time.time() - cached[0] < _OTC_SYMBOL_CACHE_TTL:
        return cached[1]
    try:
        response = requests.get(
            f"{OTCHARTS_BASE}/symbols",
            params={"venue": "otc"},
            headers={"Authorization": f"Bearer {OTCHARTS_API_KEY}", "User-Agent": "NUMBER-ONE-TRADER-AI/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        for item in response.json().get("symbols", []):
            symbol = str(item.get("symbol", ""))
            name = str(item.get("name", "")).upper().replace("/", "").replace(" ", "").replace("OTC", "")
            symbol_normalized = symbol.upper().replace("_OTC", "").replace("/", "").replace("-", "")
            if normalized == name or normalized == symbol_normalized:
                if item.get("open") is False:
                    print(f"Pocket Option OTC instrument is currently closed: {symbol}")
                    return None
                _OTC_SYMBOL_CACHE[normalized] = (time.time(), symbol)
                return symbol
    except requests.HTTPError as exc:
        response = exc.response
        status = response.status_code if response is not None else "?"
        detail = (response.text[:240].replace("\\n", " ") if response is not None else "")
        print(f"OTCharts symbol catalogue failed: HTTP {status}; {detail}")
    except requests.RequestException as exc:
        print(f"OTCharts symbol catalogue request failed: {type(exc).__name__}")
    except Exception as exc:
        print(f"OTCharts symbol catalogue failed: {type(exc).__name__}")
    return None


def calculate_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    data = _normalize(frame)
    if len(data) < 55:
        return pd.DataFrame()
    close = data["close"]
    high, low = data["high"], data["low"]
    data["ema9"] = close.ewm(span=9, adjust=False).mean()
    data["ema21"] = close.ewm(span=21, adjust=False).mean()
    data["ema50"] = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    data["rsi"] = 100 - (100 / (1 + rs))
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    data["macd"] = fast - slow
    data["macd_signal"] = data["macd"].ewm(span=9, adjust=False).mean()
    data["bb_mid"] = close.rolling(20).mean()
    std = close.rolling(20).std()
    data["bb_upper"] = data["bb_mid"] + 2 * std
    data["bb_lower"] = data["bb_mid"] - 2 * std
    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    data["stoch"] = 100 * (close - lowest) / (highest - lowest).replace(0, float("nan"))
    previous = close.shift(1)
    tr = pd.concat([
        high - low, (high - previous).abs(), (low - previous).abs()
    ], axis=1).max(axis=1)
    data["atr"] = tr.rolling(14).mean()
    return data.dropna()


def detect_poc_retest(frame: pd.DataFrame) -> tuple[str | None, str | None]:
    """Return a single arrow only after a volume POC retest and candle confirmation."""
    data = _normalize(frame).tail(120).copy()
    if len(data) < 20 or float(data["volume"].fillna(0).sum()) <= 0:
        return None, None
    typical = (data["high"] + data["low"] + data["close"]) / 3
    low_edge = float(data["low"].min())
    high_edge = float(data["high"].max())
    if not math.isfinite(low_edge + high_edge) or high_edge <= low_edge:
        return None, None
    bins = 40
    bucket = ((typical - low_edge) / (high_edge - low_edge) * bins).clip(0, bins - 1).astype(int)
    volume_by_bucket = data["volume"].fillna(0).groupby(bucket).sum()
    if volume_by_bucket.empty or float(volume_by_bucket.max()) <= 0:
        return None, None
    poc_bucket = int(volume_by_bucket.idxmax())
    poc = low_edge + (poc_bucket + 0.5) * (high_edge - low_edge) / bins
    prev, last = data.iloc[-2], data.iloc[-1]
    candle_key = str(data.index[-1]) if data.index is not None else str(len(data))
    tolerance = max((high_edge - low_edge) / bins * 0.35, abs(poc) * 0.00005)
    touched = float(last["low"]) <= poc + tolerance and float(last["high"]) >= poc - tolerance
    if not touched:
        return None, candle_key
    # Retest from above followed by a bullish close, or from below followed by a bearish close.
    if float(prev["close"]) > poc + tolerance and float(last["close"]) > poc + tolerance and float(last["close"]) > float(last["open"]):
        return "⬆️", candle_key
    if float(prev["close"]) < poc - tolerance and float(last["close"]) < poc - tolerance and float(last["close"]) < float(last["open"]):
        return "⬇️", candle_key
    return None, candle_key


@dataclass
class Signal:
    asset: str
    symbol: str
    market: str
    timeframe: str
    direction: str
    signal_type: str
    confidence: int
    entry: float
    stop_loss: float
    take_profit: float
    rsi: float
    macd: str
    trend: str
    source: str
    created_at: str
    reasons: str

def analyze_asset(asset: str, symbol: str, market: str, timeframe: str,
                  signal_filter: str = "جميع الإشارات") -> dict | None:
    frame, source = fetch_market_data(symbol, timeframe)
    data = calculate_indicators(frame)
    if data.empty:
        return None
    last = data.iloc[-1]
    prev = data.iloc[-2]
    close = float(last["close"])
    atr = float(last["atr"])
    if not all(math.isfinite(x) for x in (close, atr)) or close <= 0 or atr <= 0:
        return None

    bullish, bearish, reasons = 0, 0, []
    if last["ema9"] > last["ema21"] > last["ema50"]:
        bullish += 2; reasons.append("اتجاه المتوسطات صاعد")
    elif last["ema9"] < last["ema21"] < last["ema50"]:
        bearish += 2; reasons.append("اتجاه المتوسطات هابط")
    if last["macd"] > last["macd_signal"] and prev["macd"] <= prev["macd_signal"]:
        bullish += 2; reasons.append("تقاطع MACD صاعد")
    elif last["macd"] < last["macd_signal"] and prev["macd"] >= prev["macd_signal"]:
        bearish += 2; reasons.append("تقاطع MACD هابط")
    elif last["macd"] > last["macd_signal"]:
        bullish += 1; reasons.append("MACD إيجابي")
    else:
        bearish += 1; reasons.append("MACD سلبي")
    if 50 < last["rsi"] < 70:
        bullish += 1; reasons.append("RSI يدعم الصعود")
    elif 30 < last["rsi"] < 50:
        bearish += 1; reasons.append("RSI يدعم الهبوط")
    elif last["rsi"] <= 30:
        bullish += 1; reasons.append("RSI في منطقة تشبع بيع")
    elif last["rsi"] >= 70:
        bearish += 1; reasons.append("RSI في منطقة تشبع شراء")
    if close > last["bb_mid"]:
        bullish += 1
    else:
        bearish += 1
    if last["stoch"] > 55:
        bullish += 1
    elif last["stoch"] < 45:
        bearish += 1

    difference = bullish - bearish
    if abs(difference) < 3:
        return None
    direction = "صعود" if difference > 0 else "هبوط"
    votes = max(bullish, bearish)
    confidence = min(94, 52 + votes * 5 + min(abs(difference), 4) * 2)
    signal_type = "قوي" if confidence >= 78 else "متوسط"
    if signal_filter == "الإشارات القوية فقط" and signal_type != "قوي":
        return None
    if signal_filter == "إشارات الاتجاه" and not (
        (direction == "صعود" and last["ema9"] > last["ema21"]) or
        (direction == "هبوط" and last["ema9"] < last["ema21"])
    ):
        return None
    if signal_filter == "إشارات الانعكاس" and not (
        (direction == "صعود" and last["rsi"] < 38) or
        (direction == "هبوط" and last["rsi"] > 62)
    ):
        return None

    risk = atr * 1.5
    reward = atr * 2.25
    if direction == "صعود":
        stop, target = close - risk, close + reward
    else:
        stop, target = close + risk, close - reward
    return asdict(Signal(
        asset=asset, symbol=symbol, market=market, timeframe=timeframe,
        direction=direction, signal_type=signal_type, confidence=int(confidence),
        entry=close, stop_loss=stop, take_profit=target,
        rsi=round(float(last["rsi"]), 2),
        macd="إيجابي" if last["macd"] > last["macd_signal"] else "سلبي",
        trend="صاعد" if last["ema9"] > last["ema21"] else "هابط",
        source=source,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        reasons="، ".join(reasons),
    ))

def analyze_otc_poc(asset: str, symbol: str, timeframe: str) -> dict | None:
    """Pocket Option OTC-only setup: POC retest + candle confirmation + trend filters.

    If the provider omits candle volume, use a candle-count/TPO proxy and disclose that
    limitation; never label the proxy as a true volume POC.
    """
    if not symbol.lower().endswith("_otc"):
        return None
    frame, source = fetch_market_data(symbol, timeframe)
    if frame.empty or not source.startswith("OTCharts Pocket Option OTC"):
        return None
    # Ignore the newest bar: it may still be forming at the provider.
    confirmed = _normalize(frame).iloc[:-1].copy()
    data = calculate_indicators(confirmed)
    if len(data) < 55:
        return None

    # Reject broken candle sequences rather than interpreting a data outage as a price move.
    expected_seconds = OTC_TIMEFRAMES.get(timeframe, 300)
    if isinstance(confirmed.index, pd.DatetimeIndex):
        gaps = confirmed.index.to_series().diff().dt.total_seconds().dropna().tail(60)
        if not gaps.empty and (gaps > expected_seconds * 1.5).any():
            print("OTC POC analysis skipped: candle history contains gaps")
            return None
    profile = confirmed.tail(120).copy()
    if len(profile) < 20:
        return None
    typical = (profile["high"] + profile["low"] + profile["close"]) / 3
    low_edge, high_edge = float(profile["low"].min()), float(profile["high"].max())
    if not math.isfinite(low_edge + high_edge) or high_edge <= low_edge:
        return None
    bins = 48
    bucket = ((typical - low_edge) / (high_edge - low_edge) * bins).clip(0, bins - 1).astype(int)
    volume = profile["volume"].fillna(0)
    has_real_volume = float(volume.sum()) > 0
    weights = volume if has_real_volume else pd.Series(1.0, index=profile.index)
    distribution = weights.groupby(bucket).sum()
    if distribution.empty or float(distribution.max()) <= 0:
        return None
    poc_bucket = int(distribution.idxmax())
    poc = low_edge + (poc_bucket + 0.5) * (high_edge - low_edge) / bins

    last, prev = data.iloc[-1], data.iloc[-2]
    candle = profile.iloc[-1]
    touched = float(candle["low"]) <= poc + max((high_edge-low_edge)/bins*0.4, abs(poc)*0.00003) and float(candle["high"]) >= poc - max((high_edge-low_edge)/bins*0.4, abs(poc)*0.00003)
    if not touched:
        return None

    direction = None
    tolerance = max((high_edge-low_edge)/bins*0.4, abs(poc)*0.00003)
    if float(prev["close"]) > poc+tolerance and float(last["close"]) > poc+tolerance and float(candle["close"]) > float(candle["open"]):
        direction = "صعود"
    elif float(prev["close"]) < poc-tolerance and float(last["close"]) < poc-tolerance and float(candle["close"]) < float(candle["open"]):
        direction = "هبوط"
    if direction is None:
        return None

    bullish_trend = float(last["ema9"]) > float(last["ema21"]) > float(last["ema50"])
    bearish_trend = float(last["ema9"]) < float(last["ema21"]) < float(last["ema50"])
    if direction == "صعود" and not bullish_trend:
        return None
    if direction == "هبوط" and not bearish_trend:
        return None
    if direction == "صعود" and not (45 <= float(last["rsi"]) <= 72):
        return None
    if direction == "هبوط" and not (28 <= float(last["rsi"]) <= 55):
        return None

    close, atr = float(last["close"]), float(last["atr"])
    if not math.isfinite(close+atr) or close <= 0 or atr <= 0:
        return None
    stop, target = (close-atr*1.2, close+atr*1.8) if direction == "صعود" else (close+atr*1.2, close-atr*1.8)
    profile_label = "POC تقريبي موزون بحجم الشموع" if has_real_volume else "POC سعري تقريبي (حجم التداول غير متاح من المزود)"
    reasons = f"إعادة اختبار {profile_label}، شمعة تأكيد، توافق EMA9/21/50، RSI={float(last['rsi']):.1f}"
    return asdict(Signal(
        asset=asset, symbol=symbol, market="Pocket Option OTC", timeframe=timeframe,
        direction=direction, signal_type="تأكيد POC",
        confidence=78 if has_real_volume else 68,
        entry=close, stop_loss=stop, take_profit=target,
        rsi=round(float(last["rsi"]), 2),
        macd="إيجابي" if last["macd"] > last["macd_signal"] else "سلبي",
        trend="صاعد" if bullish_trend else "هابط", source=source,
        created_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        reasons=reasons,
    ))

def get_market_assets(markets: list[str], selected_assets: list[str] | None = None):
    found = []
    for market in markets:
        for asset, symbol in ASSETS.get(market, {}).items():
            if not selected_assets or asset in selected_assets:
                found.append((asset, symbol, market))
    return found
