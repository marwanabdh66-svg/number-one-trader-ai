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

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"

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
    rs = gain / loss.replace(0, float("nan"))
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

def get_market_assets(markets: list[str], selected_assets: list[str] | None = None):
    found = []
    for market in markets:
        for asset, symbol in ASSETS.get(market, {}).items():
            if not selected_assets or asset in selected_assets:
                found.append((asset, symbol, market))
    return found
