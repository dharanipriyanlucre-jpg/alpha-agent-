import requests
import pandas as pd
import time
import logging
from datetime import datetime

# ─── CONFIGURATION ───
# Get your URL from https://ntfy.sh/ (Click 'Get URL')
NTFY_URL = "https://ntfy.sh/YOUR_UNIQUE_TOPIC_HERE" 
SYMBOL = "BTCUSDT"  # Change to ETHUSDT, SOLUSDT, etc.
CHECK_INTERVAL = 300 # Check every 5 minutes (in seconds)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# ─── PURE PANDAS INDICATORS (No external TA libraries needed) ───
def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_adx(high, low, close, period=14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = (plus_dm > minus_dm) & (plus_dm > 0) * plus_dm
    minus_dm = (minus_dm > plus_dm) & (minus_dm > 0) * minus_dm
    
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    adx = dx.rolling(window=period).mean()
    return adx

# ─── DATA FETCHER (Binance Public API - Free, No Auth) ───
def fetch_candles(interval, limit):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": interval, "limit": limit}
    res = requests.get(url, params=params).json()
    df = pd.DataFrame(res, columns=["time","open","high","low","close","volume","close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    for col in ["open","high","low","close","volume"]: df[col] = df[col].astype(float)
    df.set_index("time", inplace=True)
    return df

# ─── THE AGENT LOGIC ───
def run_agent():
    logging.info(f"🚀 ALPHA AGENT STARTED | Monitoring {SYMBOL}")
    
    # Fetch Multi-Timeframe Data
    df_1h = fetch_candles("1h", 100)
    df_15m = fetch_candles("15m", 100)
    df_5m = fetch_candles("5m", 100)

    # Calculate Indicators for 1H (Trend)
    df_1h['ema50'] = calc_ema(df_1h['close'], 50)
    df_1h['ema200'] = calc_ema(df_1h['close'], 200)
    df_1h['adx'] = calc_adx(df_1h['high'], df_1h['low'], df_1h['close'])
    
    # Calculate Indicators for 15M (Pullback)
    df_15m['ema50'] = calc_ema(df_15m['close'], 50)
    df_15m['ema21'] = calc_ema(df_15m['close'], 21)

    # Calculate Indicators for 5M (Trigger)
    df_5m['ema21'] = calc_ema(df_5m['close'], 21)
    df_5m['rsi'] = calc_rsi(df_5m['close'])
    df_5m['vol_sma'] = df_5m['volume'].rolling(20).mean()

    # Get latest values
    h = df_1h.iloc[-1]
    l15 = df_15m.iloc[-1]
    m5 = df_5m.iloc[-1]

    # ─── STRATEGY CONDITIONS ───
    trend_ok = (m5['close'] > h['ema50']) and (m5['close'] > h['ema200']) and (h['adx'] > 20)
    pullback_ok = (m5['close'] < l15['ema50']) and (m5['close'] > l15['ema21'])
    trigger_rsi = m5['rsi'] > 50
    trigger_vol = m5['volume'] > (m5['vol_sma'] * 1.2)
    bullish_candle = (m5['close'] > m5['open']) and (m5['close'] > m5['low'] * 1.005)

    # ─── ALERT GENERATION ───
    if trend_ok and pullback_ok and trigger_rsi and trigger_vol and bullish_candle:
        entry = m5['close']
        sl = m5['low'] * 0.985
        tp = entry + (entry - sl) * 2.0
        
        msg = (
            f"🟢 **ALPHA AGENT: LONG ENTRY**\n"
            f"💰 Price: `{entry:.2f}`\n"
            f"🛑 Stop Loss: `{sl:.2f}`\n"
            f"🎯 Take Profit: `{tp:.2f}` (2R)\n"
            f"📈 ADX (1H): `{h['adx']:.1f}`\n"
            f"⏱️ Execute within 3 mins"
        )
        logging.info("🚨 SIGNAL TRIGGERED! Pushing to ntfy...")
        
        # Push to ntfy
        try:
            requests.post(NTFY_URL, data=msg.encode('utf-8'), 
                         headers={"X-Priority": "3", "Title": "🚨 ALPHA ENTRY", "Tags": "chart-increasing,pushpin"})
            logging.info("✅ Alert sent to ntfy!")
        except Exception as e:
            logging.error(f"ntfy failed: {e}")
            
    else:
        if trend_ok and pullback_ok:
            logging.info("Conditions partially met. Waiting for trigger...")

    # Loop forever
    time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    try:
        while True:
            run_agent()
    except KeyboardInterrupt:
        logging.info("Agent stopped by user.")
