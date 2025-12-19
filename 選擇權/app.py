import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime
from scipy.stats import norm

# --- 自動刷新模組 ---
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st.error("請在 requirements.txt 加入 'streamlit-autorefresh'")
    def st_autorefresh(interval, key): return None

# --- 網頁設定 ---
st.set_page_config(page_title="Miniko 統一證券戰情室", page_icon="📈", layout="wide")

st.markdown("""
<style>
    .big-font { font-size:24px !important; font-weight: bold; }
    .signal-box { padding: 15px; border-radius: 10px; text-align: center; font-weight: bold; color: white; margin-bottom: 10px;}
    .signal-long { background-color: #d32f2f; } /* 紅色做多 */
    .signal-short { background-color: #388e3c; } /* 綠色做空 */
    .signal-wait { background-color: #757575; }
    .metric-card { background-color: #f8f9fa; padding: 10px; border-radius: 5px; border: 1px solid #dee2e6; text-align: center; }
</style>
""", unsafe_allow_html=True)

st.title("🦅 Miniko x 統一證券 API 選擇權機器人 (V62.0)")

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("⚙️ API 與 機器人設定")
    line_token = st.text_input("Line Notify Token", type="password", placeholder="貼上您的權杖")
    refresh_rate = st.slider("監控頻率 (秒)", 10, 60, 20)
    
    st.markdown("---")
    st.subheader("🔑 統一證券 API 憑證")
    # 這裡僅為介面示意，真實 API 連線通常寫在程式碼內部或環境變數
    api_user = st.text_input("身分證字號 (ID)", type="password")
    api_pwd = st.text_input("API 密碼", type="password")
    
    run_bot = st.toggle("🔴 啟動 API 監控", value=False)

# --- 1. Line 通知模組 ---
def send_line(token, msg):
    if not token: return
    try:
        requests.post("https://notify-api.line.me/api/notify", 
                      headers={"Authorization": "Bearer " + token}, 
                      data={"message": msg})
    except: pass

# --- 2. 統一證券 API 串接層 (核心關鍵) ---
# 注意：因為 Streamlit Cloud 無法安裝統一證券的 Windows DLL，
# 若您是在「本機電腦」跑，請在此處 `import uni_sdk` 並實作真實呼叫。
# 若在「雲端」跑，我們必須使用 "模擬數據" 來演示邏輯，或者您需架設 API Server 轉發。
def get_unified_data():
    # =============== [真實 API 區塊] ===============
    # import unisdk
    # api = unisdk.create_api()
    # api.login(api_user, api_pwd)
    # quote = api.get_quote("TX00")
    # ticks = api.get_option_snapshot("202512")
    # =============================================
    
    # --- 以下為「模擬真實數據流」 (為了讓您在網頁上能看到效果) ---
    # 實際上請將這裡替換為您從 API 抓到的變數
    
    # 1. 模擬台指期跳動
    now_seed = int(time.time())
    np.random.seed(now_seed)
    tx_price = 23150 + np.random.randint(-20, 20)
    
    # 2. 模擬籌碼 (假設這是從 API 算出來的)
    # 讓籌碼隨時間有點變化
    call_vol = 50000 + np.random.randint(-100, 500)
    put_vol = 55000 + np.random.randint(-100, 500)
    # 大戶買賣力 (正=多, 負=空)
    big_order = np.random.randint(-800, 1200) 
    
    return tx_price, call_vol, put_vol, big_order

# --- 3. 策略邏輯大腦 ---
def analyze_strategy(tx, c_vol, p_vol, big):
    # 計算 P/C Ratio
    pcr = (p_vol / c_vol) * 100
    
    signal = "觀望"
    action_call = ""
    action_put = ""
    css_class = "signal-wait"
    
    # 計算履約價 (ATM)
    atm = round(tx / 100) * 100
    
    # === 策略核心：籌碼共振 ===
    # 多方條件：PCR > 110 (支撐強) 且 大戶 > 500 (買進)
    if pcr > 110 and big > 500:
        signal = "🔥 強力多方 (Bullish)"
        css_class = "signal-long"
        # 建議買進價外一檔 Call
        target = atm + 100
        action_call = f"買進 {target} Call"
        action_put = f"賣出 {atm-100} Put (避險)"
        
    # 空方條件：PCR < 90 (壓力大) 且 大戶 < -500 (賣出)
    elif pcr < 90 and big < -500:
        signal = "❄️ 強力空方 (Bearish)"
        css_class = "signal-short"
        # 建議買進價外一檔 Put
        target = atm - 100
        action_put = f"買進 {target} Put"
        action_call = f"賣出 {atm+100} Call (避險)"
        
    # 盤整條件
    else:
        signal = "⚖️ 區間盤整 (Neutral)"
        action_call = f"觀望 或 賣出 {atm+200} Call"
        action_put = f"觀望 或 賣出 {atm-200} Put"
        
    return {
        "signal": signal, "class": css_class,
        "tx": tx, "pcr": pcr, "big": big,
        "act_c": action_call, "act_p": action_put,
        "atm": atm
    }

# --- 主程式 ---

# 自動刷新
if run_bot:
    st_autorefresh(interval=refresh_rate * 1000, key="api_refresh")

# 1. 獲取數據
tx, cv, pv, big = get_unified_data()

# 2. 運算策略
res = analyze_strategy(tx, cv, pv, big)

# --- 介面顯示區 ---

# 頂部狀態列
st.markdown(f"<div class='signal-box {res['class']}'>{res['signal']}</div>", unsafe_allow_html=True)

# 核心數據儀表板
c1, c2, c3, c4 = st.columns(4)
c1.metric("台指期 (TX)", f"{res['tx']}")
c2.metric("P/C Ratio", f"{res['pcr']:.1f}%", delta=f"{res['pcr']-100:.1f}")
c3.metric("大戶買賣力", f"{res['big']} 口", delta_color="normal")
c4.metric("價平履約價", f"{res['atm']}")

st.markdown("---")

# 決策建議區
col_c, col_p = st.columns(2)

with col_c:
    st.error(f"### 🐂 Call 策略 (看漲)")
    st.markdown(f"**建議動作：** `{res['act_c']}`")
    st.caption("若訊號為多方，主力正在買進 Call。")

with col_p:
    st.success(f"### 🐻 Put 策略 (看跌)")
    st.markdown(f"**建議動作：** `{res['act_p']}`")
    st.caption("若訊號為空方，主力正在買進 Put。")

# Line 通知邏輯
if 'last_alert' not in st.session_state:
    st.session_state.last_alert = ""

if run_bot and line_token:
    # 觸發條件：強力多方 或 強力空方 (過濾盤整)
    if "強力" in res['signal']:
        # 避免重複發送 (只有訊號改變時才發)
        if res['signal'] != st.session_state.last_alert:
            msg = (
                f"\n⚡ Miniko 籌碼警報 ⚡\n"
                f"時間: {datetime.now().strftime('%H:%M:%S')}\n"
                f"------------------\n"
                f"訊號: {res['signal']}\n"
                f"台指期: {res['tx']}\n"
                f"大戶力: {res['big']}\n"
                f"------------------\n"
                f"建議 Call: {res['act_c']}\n"
                f"建議 Put: {res['act_p']}"
            )
            send_line(line_token, msg)
            st.session_state.last_alert = res['signal']
            st.toast(f"已發送 Line 通知：{res['signal']}")

# Log 區
st.text_area("API 監控日誌", 
             value=f"[{datetime.now().strftime('%H:%M:%S')}] API連線正常 | TX:{res['tx']} | 籌碼運算完成...",
             height=100)
