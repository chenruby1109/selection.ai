import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import time

# ==========================================
# 1. 系統設定
# ==========================================
st.set_page_config(page_title="AI 趨勢訊號站", page_icon="📶", layout="wide")

# 從 Streamlit Secrets 讀取 Token
# 如果你在本機執行，因為沒有 Secrets，這裡會給空值，但程式不會崩潰
try:
    TG_TOKEN = st.secrets.get("TG_TOKEN", "")
    TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")
except FileNotFoundError:
    TG_TOKEN = ""
    TG_CHAT_ID = ""

# ==========================================
# 2. 核心功能 (已修復錯誤)
# ==========================================

def get_data():
    """抓取加權指數數據 (已針對新版 yfinance 修復)"""
    try:
        # 抓取 5天 的 5分K
        df = yf.download(tickers="^TWII", period="5d", interval="5m", progress=False)
        
        if df.empty:
            return None
        
        # --- 關鍵修復區塊 ---
        # 1. 重設索引，讓時間變成一般欄位
        df.reset_index(inplace=True)
        
        # 2. 處理多層欄位 (MultiIndex) 問題
        # 如果欄位長得像 ('Close', '^TWII')，我們只留 'Close'
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
            
        # 3. 確保欄位名稱是乾淨的字串
        df.columns = [str(c) for c in df.columns]
        
        # 4. 統一時間欄位名稱
        if "Datetime" in df.columns:
            df.rename(columns={"Datetime": "ts"}, inplace=True)
        elif "Date" in df.columns:
            df.rename(columns={"Date": "ts"}, inplace=True)
        
        # 設回索引
        if "ts" in df.columns:
            df.set_index("ts", inplace=True)
        
        # 移除空值
        df.dropna(inplace=True)
        
        return df
    except Exception as e:
        st.error(f"數據抓取失敗: {e}")
        return None

def send_telegram(msg):
    """發送 TG 通知"""
    if not TG_TOKEN or not TG_CHAT_ID:
        # 如果沒有設定 Token，只在網頁顯示，不報錯
        return
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"TG 發送失敗: {e}")

def strategy(df, pcr_view):
    """
    高勝率策略 (已修復欄位讀取錯誤)
    """
    # 檢查必要欄位
    if "Close" not in df.columns:
        return "WAIT", 0, 0, "資料格式錯誤 (缺少 Close)"

    # 計算指標
    try:
        # 計算布林通道和 RSI
        df.ta.bbands(close='Close', length=20, std=2, append=True)
        df.ta.rsi(close='Close', length=14, append=True)
    except Exception:
        return "WAIT", 0, 0, "指標計算錯誤"
    
    # --- 動態抓取欄位名稱 (避免 KeyError) ---
    cols = df.columns.tolist()
    
    # 自動尋找包含 BBU, BBL, RSI 的欄位名稱
    bbu_col = next((c for c in cols if "BBU" in c), None)
    bbl_col = next((c for c in cols if "BBL" in c), None)
    rsi_col = next((c for c in cols if "RSI" in c), None)

    if not bbu_col or not rsi_col:
        return "WAIT", 0, 0, "找不到指標欄位"

    # 取得最新一筆數據
    last = df.iloc[-1]
    close = last["Close"]
    rsi = last[rsi_col]
    upper = last[bbu_col]
    lower = last[bbl_col]
    
    signal = "WAIT"
    reason = ""
    
    # === 訊號邏輯 ===
    # 買 CALL: 跌破下軌 + RSI超賣 + 籌碼偏多
    if close < lower and rsi < 30:
        if pcr_view == "偏多":
            signal = "BUY_CALL"
            reason = "📉 跌破下軌 + RSI超賣 + 籌碼支撐"
        else:
            reason = "⚠️ 技術面落底，但籌碼不佳"
            
    # 買 PUT: 突破上軌 + RSI超買 + 籌碼偏空
    elif close > upper and rsi > 70:
        if pcr_view == "偏空":
            signal = "BUY_PUT"
            reason = "📈 突破上軌 + RSI超買 + 籌碼壓力"
        else:
            reason = "⚠️ 技術面過熱，但籌碼強勢"

    return signal, close, rsi, reason

# ==========================================
# 3. 前端介面
# ==========================================
st.title("📶 選擇權訊號戰情室 (雲端穩定版)")
st.markdown("---")

# 初始化 Session State
if "last_sig" not in st.session_state:
    st.session_state.last_sig = ""

# 側邊欄設定
with st.sidebar:
    st.header("🕵️ 人工籌碼濾網")
    st.info("由於免費源沒有即時籌碼，請根據盤前資訊設定今日方向，以提高勝率。")
    pcr_option = st.radio("今日大戶籌碼/PCR看法:", ["偏多 (看漲)", "中立 (盤整)", "偏空 (看跌)"], index=1)
    
    pcr_map = {"偏多 (看漲)": "偏多", "中立 (盤整)": "中立", "偏空 (看跌)": "偏空"}
    user_view = pcr_map[pcr_option]
    
    st.divider()
    auto_refresh = st.checkbox("開啟自動刷新 (每60秒)", value=True)

# 主畫面按鈕區
if st.button("🔄 立即分析市場") or auto_refresh:
    
    with st.spinner("正在連線 Yahoo Finance 分析中..."):
        df = get_data()
        
        if df is not None:
            sig, price, rsi_val, note = strategy(df, user_view)
            
            # 顯示大字報
            col1, col2, col3 = st.columns(3)
            col1.metric("加權指數", f"{price:.0f}")
            col2.metric("RSI 強度", f"{rsi_val:.1f}")
            if sig == "BUY_CALL":
                col3.metric("目前訊號", sig, delta="強力買進", delta_color="normal")
            elif sig == "BUY_PUT":
                col3.metric("目前訊號", sig, delta="強力放空", delta_color="inverse")
            else:
                col3.metric("目前訊號", sig)
            
            # 走勢圖
            st.line_chart(df["Close"])
            st.info(f"💡 策略狀態: {note}")
            
            # 訊號處理與發送
            # 為了防止一直重複發送，我們檢查目前的價格是否跟上一次發送時一樣
            current_sig_id = f"{sig}_{price:.0f}"
            
            if sig in ["BUY_CALL", "BUY_PUT"]:
                if st.session_state.last_sig != current_sig_id:
                    # 準備訊息內容
                    icon = "🚀" if sig == "BUY_CALL" else "🔻"
                    direction = "買進 CALL" if sig == "BUY_CALL" else "買進 PUT"
                    
                    msg = (
                        f"{icon} **進場通知** {icon}\n"
                        f"建議: {direction}\n"
                        f"指數: {price:.0f}\n"
                        f"RSI: {rsi_val:.1f}\n"
                        f"理由: {note}"
                    )
                    
                    # 發送
                    send_telegram(msg)
                    st.toast(f"已發送通知: {direction}")
                    
                    # 更新狀態，避免下次重複發
                    st.session_state.last_sig = current_sig_id
                
        else:
            st.warning("⚠️ 暫時無法取得數據，可能是盤後或 Yahoo API 忙碌中，請稍後重試。")

    if auto_refresh:
        time.sleep(60)
        st.rerun()
