import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import time
from datetime import datetime

# ==========================================
# 1. 系統設定
# ==========================================
st.set_page_config(page_title="AI 趨勢訊號站", page_icon="📶", layout="wide")

# 從 Streamlit Secrets 讀取 Token (稍後教你設定，這樣最安全)
try:
    TG_TOKEN = st.secrets["TG_TOKEN"]
    TG_CHAT_ID = st.secrets["TG_CHAT_ID"]
except:
    st.error("⚠️ 請在 Streamlit Cloud 設定 Secrets，否則無法發送通知")
    TG_TOKEN = ""
    TG_CHAT_ID = ""

# ==========================================
# 2. 核心功能
# ==========================================

def get_data():
    """抓取加權指數數據"""
    try:
        # 抓取 5天 的 5分K
        df = yf.download(tickers="^TWII", period="5d", interval="5m", progress=False)
        if df.empty: return None
        
        # 格式整理
        df.reset_index(inplace=True)
        # yfinance 欄位有時會是多層索引，這裡做簡單處理
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
            
        df.rename(columns={"Datetime": "ts", "Date": "ts"}, inplace=True)
        df.set_index("ts", inplace=True)
        return df
    except Exception as e:
        st.error(f"數據抓取失敗: {e}")
        return None

def send_telegram(msg):
    """發送 TG 通知"""
    if not TG_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def strategy(df, pcr_view):
    """
    高勝率策略:
    1. 布林通道 (逆勢)
    2. RSI (動能)
    3. PCR 濾網 (手動輸入的籌碼觀點)
    """
    # 計算指標
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.rsi(length=14, append=True)
    
    last = df.iloc[-1]
    close = last["Close"]
    rsi = last["RSI_14"]
    upper = last["BBU_20_2.0"]
    lower = last["BBL_20_2.0"]
    
    signal = "WAIT"
    reason = ""
    
    # === 訊號邏輯 ===
    # 買 CALL 條件: 跌破下軌 + RSI超賣 + 籌碼偏多
    if close < lower and rsi < 30:
        if pcr_view == "偏多":
            signal = "BUY_CALL"
            reason = "📉 跌破下軌 + RSI超賣 + 籌碼支撐"
        else:
            reason = "⚠️ 技術面落底，但籌碼不佳，建議觀望"
            
    # 買 PUT 條件: 突破上軌 + RSI超買 + 籌碼偏空
    elif close > upper and rsi > 70:
        if pcr_view == "偏空":
            signal = "BUY_PUT"
            reason = "📈 突破上軌 + RSI超買 + 籌碼壓力"
        else:
            reason = "⚠️ 技術面過熱，但籌碼強勢，建議觀望"

    return signal, close, rsi, reason

# ==========================================
# 3. 前端介面
# ==========================================
st.title("📶 選擇權訊號戰情室 (雲端版)")
st.markdown("---")

# 側邊欄設定
with st.sidebar:
    st.header("🕵️ 人工籌碼濾網")
    st.info("由於免費源沒有即時籌碼，請根據盤前資訊設定今日方向，以提高勝率。")
    pcr_option = st.radio("今日大戶籌碼/PCR看法:", ["偏多 (看漲)", "中立 (盤整)", "偏空 (看跌)"])
    
    pcr_map = {"偏多 (看漲)": "偏多", "中立 (盤整)": "中立", "偏空 (看跌)": "偏空"}
    user_view = pcr_map[pcr_option]
    
    st.divider()
    auto_refresh = st.checkbox("開啟自動刷新 (每60秒)", value=True)

# 主畫面
if st.button("🔄 立即分析市場") or auto_refresh:
    
    with st.spinner("正在連線 Yahoo Finance 分析中..."):
        df = get_data()
        
        if df is not None:
            sig, price, rsi_val, note = strategy(df, user_view)
            
            # 顯示大字報
            col1, col2, col3 = st.columns(3)
            col1.metric("加權指數", f"{price:.0f}")
            col2.metric("RSI 強度", f"{rsi_val:.1f}")
            col3.metric("目前訊號", sig, delta_color="inverse")
            
            # 走勢圖
            st.line_chart(df["Close"])
            
            # 訊號處理
            if sig == "BUY_CALL":
                st.success(f"🔥 強力訊號: {note}")
                # 只有當最後一筆是新訊號時才發送 (簡單防重複機制可再優化)
                if "last_sig" not in st.session_state or st.session_state.last_sig != str(price):
                    send_telegram(f"🚀 **進場通知** 🚀\n建議: 買進 CALL\n價格: {price:.0f}\nRSI: {rsi_val:.1f}\n理由: {note}")
                    st.session_state.last_sig = str(price)
                    
            elif sig == "BUY_PUT":
                st.error(f"❄️ 強力訊號: {note}")
                if "last_sig" not in st.session_state or st.session_state.last_sig != str(price):
                    send_telegram(f"🔻 **進場通知** 🔻\n建議: 買進 PUT\n價格: {price:.0f}\nRSI: {rsi_val:.1f}\n理由: {note}")
                    st.session_state.last_sig = str(price)
            else:
                st.info(f"👀 目前觀望: {note}")
                
        else:
            st.warning("暫時無法取得數據，請稍後重試")

    if auto_refresh:
        time.sleep(60)
        st.rerun()
