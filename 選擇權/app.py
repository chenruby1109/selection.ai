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
st.set_page_config(page_title="AI 選擇權戰情室 (日夜全時段)", page_icon="⚡", layout="wide")

# 讀取 Telegram 設定 (從 Secrets 讀取，若無則留空)
try:
    TG_TOKEN = st.secrets.get("TG_TOKEN", "")
    TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")
except FileNotFoundError:
    TG_TOKEN = ""
    TG_CHAT_ID = ""

# ==========================================
# 2. 數據抓取與清洗模組
# ==========================================
def get_futures_data():
    """
    抓取 TX=F (台指期)，包含日盤與夜盤
    """
    try:
        # 抓取 5天 的 5分K
        df = yf.download(tickers="TX=F", period="5d", interval="5m", progress=False)
        
        if df.empty: return None
        
        # --- 標準化清洗流程 ---
        df.reset_index(inplace=True)
        
        # 處理 MultiIndex (Yahoo 改版問題)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        
        # 強制轉字串避免格式錯誤
        df.columns = [str(c) for c in df.columns]
        
        # 統一時間欄位
        if "Datetime" in df.columns: df.rename(columns={"Datetime": "ts"}, inplace=True)
        elif "Date" in df.columns: df.rename(columns={"Date": "ts"}, inplace=True)
        
        # 設定索引與時區轉換 (轉為台灣時間)
        if "ts" in df.columns:
            # Yahoo 抓下來通常是 UTC，轉為 UTC+8
            if df["ts"].dt.tz is None:
                df["ts"] = df["ts"].dt.tz_localize("UTC").dt.tz_convert("Asia/Taipei")
            else:
                df["ts"] = df["ts"].dt.tz_convert("Asia/Taipei")
            
            df.set_index("ts", inplace=True)
        
        # 移除空值
        df.dropna(inplace=True)
        
        return df
    except Exception as e:
        return None

# ==========================================
# 3. 即時籌碼分析模組 (取代付費 PCR)
# ==========================================
def analyze_volume_chips(df):
    """
    透過「價量關係」模擬即時籌碼強度
    回傳: 籌碼狀態 (字串), 強度分數 (0-10)
    """
    if "Volume" not in df.columns:
        return "無法分析量能", 5

    # 計算 5根K棒 的平均成交量 (MV5)
    df["Vol_MA5"] = df["Volume"].rolling(5).mean()
    
    last = df.iloc[-1]
    vol = last["Volume"]
    vol_ma = last["Vol_MA5"]
    close = last["Close"]
    open_p = last["Open"]
    
    # 量能爆發判定 (大於均量 1.5 倍)
    is_explosion = vol > (vol_ma * 1.5)
    
    chip_msg = "量能平穩"
    score = 5 # 5分中立
    
    if is_explosion:
        if close > open_p: # 爆量上漲 -> 大戶做多
            chip_msg = "🔥 主力進場 (爆量長紅)"
            score = 9
        else: # 爆量下跌 -> 大戶倒貨
            chip_msg = "🤮 主力倒貨 (爆量長黑)"
            score = 1
    elif vol < (vol_ma * 0.6):
        chip_msg = "❄️ 人氣退潮 (量縮盤整)"
        score = 5
        
    return chip_msg, score

# ==========================================
# 4. 策略核心 (高勝率: BB + RSI + 籌碼濾網)
# ==========================================
def strategy(df, manual_pcr_view):
    """
    回傳: 訊號類型, 價格, RSI, 理由
    """
    # 確保有 Close
    if "Close" not in df.columns: return "WAIT", 0, 0, "No Close Data"

    # 計算指標
    try:
        df.ta.bbands(close='Close', length=20, std=2, append=True)
        df.ta.rsi(close='Close', length=14, append=True)
    except: return "WAIT", 0, 0, "Indicator Error"
    
    # 動態抓取欄位
    cols = df.columns.tolist()
    bbu = next((c for c in cols if "BBU" in c), None)
    bbl = next((c for c in cols if "BBL" in c), None)
    rsi_c = next((c for c in cols if "RSI" in c), None)

    if not bbu or not rsi_c: return "WAIT", 0, 0, "Column Error"

    # 取得當下數據
    last = df.iloc[-1]
    close = last["Close"]
    rsi = last[rsi_c]
    upper = last[bbu]
    lower = last[bbl]
    
    # 執行量能籌碼分析
    chip_msg, chip_score = analyze_volume_chips(df)
    
    signal = "WAIT"
    reason = ""
    
    # === 策略邏輯 ===
    
    # 【多方訊號】條件：
    # 1. 技術面：跌破下軌 (超跌) + RSI < 30 (超賣)
    # 2. 籌碼面：人工濾網不能是「偏空」 OR 當下出現「主力進場」訊號
    if close < lower and rsi < 30:
        if manual_pcr_view != "偏空" or chip_score >= 8:
            signal = "BULL"
            reason = f"📉 技術超跌反彈 + {chip_msg}"
        else:
            reason = "⚠️ 技術超賣，但大趨勢偏空，放棄逆勢單"

    # 【空方訊號】條件：
    # 1. 技術面：突破上軌 (超漲) + RSI > 70 (超買)
    # 2. 籌碼面：人工濾網不能是「偏多」 OR 當下出現「主力倒貨」訊號
    elif close > upper and rsi > 70:
        if manual_pcr_view != "偏多" or chip_score <= 2:
            signal = "BEAR"
            reason = f"📈 技術超買過熱 + {chip_msg}"
        else:
            reason = "⚠️ 技術超買，但大趨勢偏多，放棄逆勢單"
            
    return signal, close, rsi, reason, chip_msg

# ==========================================
# 5. Telegram 發送模組
# ==========================================
def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg} # 移除 markdown 避免格式錯誤
    try:
        requests.post(url, json=payload, timeout=5)
    except: pass

# ==========================================
# 6. 前端介面 (UI)
# ==========================================
st.title("⚡ AI 選擇權戰情室 (日夜盤 Live)")
st.markdown("---")

if "last_sig" not in st.session_state: st.session_state.last_sig = ""

# 側邊欄：人工濾網 + 設定
with st.sidebar:
    st.header("⚙️ 戰情中心設定")
    
    # 顯示目前時段
    hour = datetime.now().hour
    is_night = hour >= 15 or hour < 8
    st.info(f"目前時段: {'🌙 夜盤交易中' if is_night else '☀️ 日盤交易中'}")
    
    st.divider()
    st.subheader("🕵️ 大趨勢濾網 (人工設定)")
    st.caption("因免費源無即時PCR，請依開盤資訊設定今日基調，可大幅提高勝率。")
    pcr_option = st.radio("今日主力方向:", ["偏多 (只做多)", "中立 (雙向)", "偏空 (只做空)"], index=1)
    
    pcr_map = {"偏多 (只做多)": "偏多", "中立 (雙向)": "中立", "偏空 (只做空)": "偏空"}
    user_view = pcr_map[pcr_option]
    
    st.divider()
    auto_refresh = st.checkbox("開啟自動監控 (每60秒)", value=True)
    
    # 測試按鈕
    if st.button("🔔 測試 Telegram"):
        send_telegram("✅ 測試成功！您的機器人已準備好接收高勝率訊號。")
        st.toast("測試訊息已發送")

# 主邏輯
if st.button("🔄 立即掃描市場") or auto_refresh:
    
    with st.spinner("正在連線期貨市場 (TX=F)..."):
        df = get_futures_data()
        
        if df is not None:
            sig_type, price, rsi, note, chip_now = strategy(df, user_view)
            
            # 取得最後更新時間
            last_time = df.index[-1].strftime('%H:%M')
            
            # 儀表板顯示
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("台指期 (TX)", f"{price:.0f}", f"更新: {last_time}")
            col2.metric("RSI 動能", f"{rsi:.1f}")
            col3.metric("即時量能", chip_now)
            
            # 訊號顯示與處理
            if sig_type == "BULL":
                col4.metric("AI 訊號", "做多訊號", "強力買進", delta_color="normal")
                st.success(f"🔥 觸發多方策略！\n建議操作：\n1. **買方**: Buy Call (買權)\n2. **賣方**: Sell Put (賣權)\n\n理由: {note}")
                
                # 發送 TG
                sig_id = f"BULL_{last_time}_{price:.0f}"
                if st.session_state.last_sig != sig_id:
                    msg = (f"🚀 [多方訊號觸發] 🚀\n"
                           f"時間: {last_time}\n"
                           f"價格: {price:.0f}\n"
                           f"建議: Buy Call 或 Sell Put\n"
                           f"RSI: {rsi:.1f}\n"
                           f"理由: {note}")
                    send_telegram(msg)
                    st.session_state.last_sig = sig_id
                    st.toast("已發送多方訊號")
                    
            elif sig_type == "BEAR":
                col4.metric("AI 訊號", "做空訊號", "強力放空", delta_color="inverse")
                st.error(f"❄️ 觸發空方策略！\n建議操作：\n1. **買方**: Buy Put (賣權)\n2. **賣方**: Sell Call (買權)\n\n理由: {note}")
                
                # 發送 TG
                sig_id = f"BEAR_{last_time}_{price:.0f}"
                if st.session_state.last_sig != sig_id:
                    msg = (f"🔻 [空方訊號觸發] 🔻\n"
                           f"時間: {last_time}\n"
                           f"價格: {price:.0f}\n"
                           f"建議: Buy Put 或 Sell Call\n"
                           f"RSI: {rsi:.1f}\n"
                           f"理由: {note}")
                    send_telegram(msg)
                    st.session_state.last_sig = sig_id
                    st.toast("已發送空方訊號")
            else:
                col4.metric("AI 訊號", "觀望 (WAIT)", "無訊號", delta_color="off")
                st.info(f"目前市場平穩，等待機會。\n籌碼狀態: {chip_now}")
                
            # 畫圖
            st.line_chart(df["Close"])
            
        else:
            st.warning("⚠️ 暫時無法取得數據 (Yahoo API 可能延遲)，請稍後自動重試。")

    if auto_refresh:
        time.sleep(60)
        st.rerun()
