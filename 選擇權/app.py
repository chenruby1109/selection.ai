import streamlit as st
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import requests
import time
from datetime import datetime, timedelta

# ==========================================
# 1. 使用者設定區
# ==========================================
# 請填入你的 Telegram Token (必填，否則收不到通知)
TG_TOKEN = "你的_TELEGRAM_TOKEN" 
TG_CHAT_ID = "你的_CHAT_ID"

# 策略參數
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MA_PERIOD = 60 # 60分K的季線，或是1分K的60MA，作為趨勢線

# ==========================================
# 2. 爬蟲與數據獲取模組 (免費來源)
# ==========================================

def get_free_market_data():
    """
    獲取台股加權指數 (^TWII) 即時數據 (延遲約 0-15分鐘)
    以此作為台指期 (TXF) 的替代分析標的
    """
    try:
        # 下載當日 1分K 資料
        df = yf.download(tickers="^TWII", period="1d", interval="1m", progress=False)
        
        if df.empty:
            return None, "No Data"

        # 重整資料格式
        df.reset_index(inplace=True)
        df.columns = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
        df.set_index('Datetime', inplace=True)
        
        return df, "Success"
    except Exception as e:
        return None, str(e)

def analyze_chips_proxy(df):
    """
    因為沒有付費籌碼源，我們用 '價量關係' 模擬籌碼強度
    """
    # 計算成交量變化 (Volume Delta)
    vol_ma = df['Volume'].rolling(5).mean()
    current_vol = df['Volume'].iloc[-1]
    
    # 簡單的籌碼假設：出量上漲=主力買，出量下跌=主力賣
    if current_vol > vol_ma.iloc[-1] * 1.5:
        return "🔥 爆量 (主力進場)"
    elif current_vol < vol_ma.iloc[-1] * 0.5:
        return "❄️ 量縮 (觀望)"
    else:
        return "☁️ 正常量"

# ==========================================
# 3. 訊號發送模組
# ==========================================

def send_telegram(message):
    if "你的" in TG_TOKEN:
        st.toast("⚠️ 未設定 Telegram Token，無法發送")
        return
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=3)
    except Exception as e:
        st.error(f"TG 發送錯誤: {e}")

# ==========================================
# 4. 策略核心 (高勝率邏輯)
# ==========================================

def strategy_engine(df, manual_pcr=100):
    """
    df: 價格數據
    manual_pcr: 手動輸入的 Put/Call Ratio (因為這很難爬，建議手動參考)
    """
    if len(df) < MA_PERIOD:
        return "WAIT", 0.0

    # 計算指標
    df.ta.rsi(length=RSI_PERIOD, append=True)
    df.ta.sma(length=MA_PERIOD, append=True)
    
    # 取得最新數據
    last = df.iloc[-1]
    rsi = last[f'RSI_{RSI_PERIOD}']
    ma = last[f'SMA_{MA_PERIOD}']
    close = last['Close']
    
    signal = "WAIT"
    
    # === 高勝率邏輯：順大勢 (MA + PCR) + 逆小勢 (RSI) ===
    
    # 狀況 A: 趨勢向上 (價在MA上) + 籌碼偏多 (PCR > 100) + 短線拉回 (RSI超賣)
    # 這是勝率最高的 Buy Call 點 (拉回買進)
    if close > ma and manual_pcr > 100 and rsi < RSI_OVERSOLD:
        signal = "BUY_CALL"
        
    # 狀況 B: 趨勢向下 (價在MA下) + 籌碼偏空 (PCR < 100) + 短線反彈 (RSI超買)
    # 這是勝率最高的 Buy Put 點 (反彈空)
    elif close < ma and manual_pcr < 100 and rsi > RSI_OVERBOUGHT:
        signal = "BUY_PUT"
        
    return signal, rsi, close

# ==========================================
# 5. Streamlit 主程式
# ==========================================

st.set_page_config(page_title="免費籌碼即時掃描", layout="wide", page_icon="🕵️")

st.title("🕵️ 選擇權籌碼狙擊手 (免費版)")
st.markdown("---")

# 側邊欄：輸入籌碼濾網
with st.sidebar:
    st.header("1. 籌碼濾網 (必填)")
    st.info("由於 PCR 數據無法免費即時爬取，請參考期交所網頁後手動調整，以增加勝率。")
    pcr_input = st.slider("目前市場 Put/Call Ratio (%)", 50, 150, 100)
    
    st.header("2. 控制中心")
    run_bot = st.checkbox("啟動即時監控", value=False)
    refresh_rate = st.number_input("刷新頻率 (秒)", 30, 300, 60)

# 主面板
col1, col2 = st.columns(2)
with col1:
    st.subheader("📊 加權指數走勢 (模擬台指期)")
    chart_spot = st.empty()
with col2:
    st.subheader("🔔 即時訊號日誌")
    log_spot = st.empty()

if "logs" not in st.session_state:
    st.session_state.logs = []

# 執行迴圈
if run_bot:
    while True:
        with st.spinner("正在分析市場數據..."):
            # 1. 抓取資料
            df, status = get_free_market_data()
            
            if df is not None:
                # 2. 畫圖
                chart_spot.line_chart(df['Close'])
                
                # 3. 分析籌碼與訊號
                chip_status = analyze_chips_proxy(df)
                signal, rsi_val, current_price = strategy_engine(df, manual_pcr=pcr_input)
                
                # 顯示資訊
                now_time = datetime.now().strftime("%H:%M:%S")
                st.metric(label=f"更新時間 {now_time}", value=f"{current_price:.2f}", delta=chip_status)
                
                # 4. 觸發警報
                if signal != "WAIT":
                    msg = f"🚀 {signal} 訊號觸發！\n⏰ 時間: {now_time}\n💰 價格: {current_price}\n📊 RSI: {rsi_val:.2f}\n⚖️ PCR設定: {pcr_input}%"
                    
                    # 避免重複發送 (簡單濾網: 如果最後一條log跟現在一樣就不發)
                    if not st.session_state.logs or st.session_state.logs[0] != msg:
                        st.session_state.logs.insert(0, msg)
                        send_telegram(msg)
                        st.toast(f"已發送 Telegram: {signal}")
                
                # 更新 Log 顯示
                log_spot.table(pd.DataFrame(st.session_state.logs, columns=["訊號紀錄"]))
                
            else:
                st.error("獲取資料失敗，可能是盤後或網路問題。")
            
            time.sleep(refresh_rate)
            st.experimental_rerun()
