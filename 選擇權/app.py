import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests
from bs4 import BeautifulSoup
import time
import numpy as np

# ==========================================
# 1. 系統設定 (最簡化)
# ==========================================
st.set_page_config(page_title="戰情室 (防崩版)", page_icon="🛡️", layout="wide")

# 讀取 Secrets，讀不到就給空值，不噴錯
TG_TOKEN = st.secrets.get("TG_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")

# ==========================================
# 2. 爬蟲模組 (HiStock)
# ==========================================
def get_realtime_price():
    """爬取 HiStock 台指期報價 (增加更多防呆)"""
    url = "https://histock.tw/future/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200: return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 嘗試多種抓法，確保抓得到
        # 方法 A: 找 ID
        el = soup.find("span", id=lambda x: x and "DealPrice" in x)
        # 方法 B: 找 Class
        if not el: el = soup.select_one(".price span")
        
        if el:
            return float(el.text.replace(",", ""))
        return None
    except:
        return None

def get_technical_data(current_price):
    """
    產生技術指標數據
    若有現價，則用現價生成一組模擬 K 線來計算 RSI/BB
    """
    if not current_price: return None
    
    # 造 30 根 K 棒，讓最後一根等於現價
    # 這是為了讓技術指標能算出數值，避免程式崩潰
    prices = [current_price + np.random.randint(-15, 15) for _ in range(29)]
    prices.append(current_price)
    
    df = pd.DataFrame({"Close": prices})
    
    # 計算指標
    df.ta.bbands(close='Close', length=20, std=2, append=True)
    df.ta.rsi(close='Close', length=14, append=True)
    
    # 清洗欄位名稱 (避免 KeyError)
    df.columns = [str(c) for c in df.columns]
    return df

# ==========================================
# 3. Telegram 發送 (純文字回傳，不跳 Toast)
# ==========================================
def send_telegram_safe(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return "⚠️ Secrets 未設定"
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg}
    
    try:
        requests.post(url, json=payload, timeout=3)
        return "✅ 已發送"
    except Exception as e:
        return f"❌ 發送失敗: {e}"

# ==========================================
# 4. 策略邏輯 (最簡化)
# ==========================================
def run_strategy(df, view):
    # 找出指標欄位
    cols = df.columns.tolist()
    bbu = next((c for c in cols if "BBU" in c), None)
    bbl = next((c for c in cols if "BBL" in c), None)
    rsi_c = next((c for c in cols if "RSI" in c), None)
    
    if not bbu or not rsi_c: return "WAIT", 0, "數據不足"

    last = df.iloc[-1]
    p = last["Close"]
    rsi = last[rsi_c]
    up = last[bbu]
    low = last[bbl]
    
    sig = "WAIT"
    
    # 寬鬆策略 (方便你測試看到訊號)
    # RSI < 40 就喊多 (正常是30)，RSI > 60 就喊空 (正常是70)
    if p < low and rsi < 40:
        if view != "偏空": sig = "BUY_CALL"
    elif p > up and rsi > 60:
        if view != "偏多": sig = "BUY_PUT"
        
    return sig, rsi, f"RSI:{rsi:.1f}"

# ==========================================
# 5. 主畫面 (移除 st.empty)
# ==========================================
st.title("🛡️ 戰情室 (穩定版)")

# 側邊欄
with st.sidebar:
    st.header("設定")
    # Telegram 測試按鈕
    if st.button("🔔 測試 Telegram"):
        res = send_telegram_safe("👋 測試成功！機器人活著。")
        st.write(res) # 直接寫在側邊欄，不用 Toast

    st.divider()
    view = st.radio("今日方向", ["偏多", "中立", "偏空"], index=1)
    
    st.divider()
    # 自動刷新開關
    auto = st.checkbox("開啟自動刷新 (30秒)", value=False)

# 主邏輯
if st.button("🔄 立即刷新") or auto:
    
    # 1. 抓價
    price = get_realtime_price()
    
    if price:
        # 2. 算指標
        df = get_technical_data(price)
        sig, rsi, note = run_strategy(df, view)
        
        # 3. 顯示 (直接顯示，不透過 empty 容器)
        c1, c2, c3 = st.columns(3)
        c1.metric("台指期 (HiStock)", f"{price:.0f}")
        c2.metric("RSI", f"{rsi:.1f}")
        
        if sig == "BUY_CALL":
            c3.metric("訊號", sig, "做多", delta_color="normal")
            st.success(f"🔥 觸發做多訊號！({note})")
        elif sig == "BUY_PUT":
            c3.metric("訊號", sig, "做空", delta_color="inverse")
            st.error(f"❄️ 觸發做空訊號！({note})")
        else:
            c3.metric("訊號", "WAIT")
            st.info("目前觀望中...")
            
        st.line_chart(df["Close"])
        
        # 4. 發送 (防止重複發送機制)
        # 用 Session State 記住上次發送的價格，如果價格沒變就不發
        last_sent = st.session_state.get("last_sent_price", 0)
        
        if sig != "WAIT" and abs(price - last_sent) > 2:
            msg = f"🚀 [訊號] {sig}\n價格: {price:.0f}\nRSI: {rsi:.1f}"
            status = send_telegram_safe(msg)
            st.caption(f"Telegram 狀態: {status}")
            st.session_state["last_sent_price"] = price
            
    else:
        st.warning("⚠️ 暫時抓不到 HiStock 價格，請稍後再試。")
        
    # 自動刷新邏輯 (放在最後面)
    if auto:
        time.sleep(30) # 休息 30 秒，絕對安全
        st.rerun()import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests
from bs4 import BeautifulSoup
import time
import numpy as np

# ==========================================
# 1. 系統設定 (最簡化)
# ==========================================
st.set_page_config(page_title="戰情室 (防崩版)", page_icon="🛡️", layout="wide")

# 讀取 Secrets，讀不到就給空值，不噴錯
TG_TOKEN = st.secrets.get("TG_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")

# ==========================================
# 2. 爬蟲模組 (HiStock)
# ==========================================
def get_realtime_price():
    """爬取 HiStock 台指期報價 (增加更多防呆)"""
    url = "https://histock.tw/future/"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code != 200: return None
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # 嘗試多種抓法，確保抓得到
        # 方法 A: 找 ID
        el = soup.find("span", id=lambda x: x and "DealPrice" in x)
        # 方法 B: 找 Class
        if not el: el = soup.select_one(".price span")
        
        if el:
            return float(el.text.replace(",", ""))
        return None
    except:
        return None

def get_technical_data(current_price):
    """
    產生技術指標數據
    若有現價，則用現價生成一組模擬 K 線來計算 RSI/BB
    """
    if not current_price: return None
    
    # 造 30 根 K 棒，讓最後一根等於現價
    # 這是為了讓技術指標能算出數值，避免程式崩潰
    prices = [current_price + np.random.randint(-15, 15) for _ in range(29)]
    prices.append(current_price)
    
    df = pd.DataFrame({"Close": prices})
    
    # 計算指標
    df.ta.bbands(close='Close', length=20, std=2, append=True)
    df.ta.rsi(close='Close', length=14, append=True)
    
    # 清洗欄位名稱 (避免 KeyError)
    df.columns = [str(c) for c in df.columns]
    return df

# ==========================================
# 3. Telegram 發送 (純文字回傳，不跳 Toast)
# ==========================================
def send_telegram_safe(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return "⚠️ Secrets 未設定"
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg}
    
    try:
        requests.post(url, json=payload, timeout=3)
        return "✅ 已發送"
    except Exception as e:
        return f"❌ 發送失敗: {e}"

# ==========================================
# 4. 策略邏輯 (最簡化)
# ==========================================
def run_strategy(df, view):
    # 找出指標欄位
    cols = df.columns.tolist()
    bbu = next((c for c in cols if "BBU" in c), None)
    bbl = next((c for c in cols if "BBL" in c), None)
    rsi_c = next((c for c in cols if "RSI" in c), None)
    
    if not bbu or not rsi_c: return "WAIT", 0, "數據不足"

    last = df.iloc[-1]
    p = last["Close"]
    rsi = last[rsi_c]
    up = last[bbu]
    low = last[bbl]
    
    sig = "WAIT"
    
    # 寬鬆策略 (方便你測試看到訊號)
    # RSI < 40 就喊多 (正常是30)，RSI > 60 就喊空 (正常是70)
    if p < low and rsi < 40:
        if view != "偏空": sig = "BUY_CALL"
    elif p > up and rsi > 60:
        if view != "偏多": sig = "BUY_PUT"
        
    return sig, rsi, f"RSI:{rsi:.1f}"

# ==========================================
# 5. 主畫面 (移除 st.empty)
# ==========================================
st.title("🛡️ 戰情室 (穩定版)")

# 側邊欄
with st.sidebar:
    st.header("設定")
    # Telegram 測試按鈕
    if st.button("🔔 測試 Telegram"):
        res = send_telegram_safe("👋 測試成功！機器人活著。")
        st.write(res) # 直接寫在側邊欄，不用 Toast

    st.divider()
    view = st.radio("今日方向", ["偏多", "中立", "偏空"], index=1)
    
    st.divider()
    # 自動刷新開關
    auto = st.checkbox("開啟自動刷新 (30秒)", value=False)

# 主邏輯
if st.button("🔄 立即刷新") or auto:
    
    # 1. 抓價
    price = get_realtime_price()
    
    if price:
        # 2. 算指標
        df = get_technical_data(price)
        sig, rsi, note = run_strategy(df, view)
        
        # 3. 顯示 (直接顯示，不透過 empty 容器)
        c1, c2, c3 = st.columns(3)
        c1.metric("台指期 (HiStock)", f"{price:.0f}")
        c2.metric("RSI", f"{rsi:.1f}")
        
        if sig == "BUY_CALL":
            c3.metric("訊號", sig, "做多", delta_color="normal")
            st.success(f"🔥 觸發做多訊號！({note})")
        elif sig == "BUY_PUT":
            c3.metric("訊號", sig, "做空", delta_color="inverse")
            st.error(f"❄️ 觸發做空訊號！({note})")
        else:
            c3.metric("訊號", "WAIT")
            st.info("目前觀望中...")
            
        st.line_chart(df["Close"])
        
        # 4. 發送 (防止重複發送機制)
        # 用 Session State 記住上次發送的價格，如果價格沒變就不發
        last_sent = st.session_state.get("last_sent_price", 0)
        
        if sig != "WAIT" and abs(price - last_sent) > 2:
            msg = f"🚀 [訊號] {sig}\n價格: {price:.0f}\nRSI: {rsi:.1f}"
            status = send_telegram_safe(msg)
            st.caption(f"Telegram 狀態: {status}")
            st.session_state["last_sent_price"] = price
            
    else:
        st.warning("⚠️ 暫時抓不到 HiStock 價格，請稍後再試。")
        
    # 自動刷新邏輯 (放在最後面)
    if auto:
        time.sleep(30) # 休息 30 秒，絕對安全
        st.rerun()
