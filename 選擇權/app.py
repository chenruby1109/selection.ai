import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime
from scipy.stats import norm

# --- 自動刷新模組 (讓它變成機器人的關鍵) ---
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st.error("請在 requirements.txt 中加入 'streamlit-autorefresh'")
    def st_autorefresh(interval, key): return None

# --- 網頁設定 ---
st.set_page_config(page_title="Miniko 雲端哨兵", page_icon="🤖", layout="wide")

st.markdown("""
<style>
    .big-font { font-size:24px !important; font-weight: bold; }
    .status-box { padding: 10px; border-radius: 5px; text-align: center; font-weight: bold; color: white;}
    .status-run { background-color: #28a745; }
    .status-stop { background-color: #dc3545; }
    .log-box { font-family: monospace; background-color: #f0f0f0; padding: 10px; border-radius: 5px; height: 150px; overflow-y: scroll; }
</style>
""", unsafe_allow_html=True)

st.title("🤖 Miniko AI 雲端自動哨兵 (V61.0)")

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ 機器人設定")
    line_token = st.text_input("Line Notify Token", type="password", placeholder="貼上您的權杖")
    refresh_rate = st.slider("監控頻率 (秒)", 30, 300, 60)
    
    st.markdown("---")
    st.header("🎯 策略參數")
    ma_period = st.number_input("趨勢均線 (MA)", value=20)
    vix_threshold = st.number_input("VIX 警戒值", value=22.0)
    
    # 機器人開關
    run_bot = st.toggle("啟動自動監控", value=False)

# --- 1. Line 通知函式 ---
def send_line_msg(token, msg):
    if not token: return
    url = "https://notify-api.line.me/api/notify"
    headers = {"Authorization": "Bearer " + token}
    payload = {"message": msg}
    try:
        requests.post(url, headers=headers, data=payload)
    except:
        pass

# --- 2. 獲取即時數據 (yfinance) ---
def get_live_data():
    try:
        ticker = yf.Ticker("^TWII") # 加權指數
        df = ticker.history(period="1d", interval="1m")
        if df.empty:
            df = ticker.history(period="5d", interval="1d")
        current_price = df['Close'].iloc[-1]
        
        df_d = ticker.history(period="1mo", interval="1d")
        ma_val = df_d['Close'].rolling(ma_period).mean().iloc[-1]
        
        df_d['Log_Ret'] = np.log(df_d['Close'] / df_d['Close'].shift(1))
        sigma = df_d['Log_Ret'].std() * np.sqrt(252) * 100
        
        return current_price, ma_val, sigma, df.index[-1]
    except:
        return 0, 0, 0, datetime.now()

# --- 3. 策略邏輯與通知 ---
def check_strategy(price, ma, vix, last_time):
    signal = "中性"
    msg = ""
    if price > ma * 1.002:
        signal = "多方 (Bullish)"
    elif price < ma * 0.998:
        signal = "空方 (Bearish)"
    if vix > vix_threshold:
        signal += " + 🔥高波動警報"
        
    current_time = last_time.strftime("%H:%M")
    log_msg = f"[{current_time}] 指數:{int(price)} | MA{ma_period}:{int(ma)} | 訊號:{signal}"
    return signal, log_msg

# --- 主程式邏輯 ---
if run_bot:
    count = st_autorefresh(interval=refresh_rate * 1000, key="data_refresh")
    st.markdown(f"<div class='status-box status-run'>🟢 機器人監控中 (每 {refresh_rate} 秒掃描) - 掃描次數: {count}</div>", unsafe_allow_html=True)
else:
    st.markdown("<div class='status-box status-stop'>🔴 機器人已暫停</div>", unsafe_allow_html=True)

price, ma, vix, time_point = get_live_data()

col1, col2, col3 = st.columns(3)
col1.metric("加權指數", f"{int(price)}")
col2.metric(f"MA{ma_period}", f"{int(ma)}", delta=int(price-ma))
col3.metric("波動率 (VIX)", f"{vix:.2f}%")

signal, log_msg = check_strategy(price, ma, vix, time_point)

st.subheader("📡 即時戰略訊號")
if "多方" in signal:
    st.success(f"🚀 {signal}")
elif "空方" in signal:
    st.error(f"📉 {signal}")
else:
    st.info(f"⚖️ {signal}")

if 'log_history' not in st.session_state:
    st.session_state.log_history = []

if run_bot:
    if not st.session_state.log_history or log_msg != st.session_state.log_history[0]:
        st.session_state.log_history.insert(0, log_msg)
        # 實戰中解開下面這行就會發送 Line
        if line_token and (vix > 20 or abs(price - ma) < 20):
             full_msg = f"\n📊 Miniko 戰報\n時間: {time_point.strftime('%H:%M')}\n指數: {int(price)}\n狀態: {signal}"
             send_line_msg(line_token, full_msg)
             st.toast("已發送 Line 通知!", icon="📨")

st.text_area("監控日誌 (Log)", value="\n".join(st.session_state.log_history), height=200)
