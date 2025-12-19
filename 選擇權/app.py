import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests
from bs4 import BeautifulSoup
import time
import numpy as np

# ==========================================
# 1. 系統設定
# ==========================================
st.set_page_config(page_title="戰情室 (診斷版)", page_icon="🚑", layout="wide")

# 讀取 Secrets
TG_TOKEN = st.secrets.get("TG_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")

# ==========================================
# 2. 數據核心 (雙模組)
# ==========================================
def get_data_with_fallback():
    """
    嘗試抓 HiStock，如果被擋，自動切換成模擬數據
    """
    # --- 方法 A: 爬蟲 ---
    url = "https://histock.tw/future/"
    # 偽裝成一般瀏覽器
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    real_price = None
    source_name = "模擬 (連線失敗)"
    
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            el = soup.find("span", id=lambda x: x and "DealPrice" in x)
            if not el: el = soup.select_one(".price span")
            
            if el:
                real_price = float(el.text.replace(",", ""))
                source_name = "HiStock (即時)"
    except:
        pass # 失敗了就安靜地進入下一步

    # --- 方法 B: 模擬數據 (如果 A 失敗) ---
    if real_price:
        price = real_price
    else:
        # 產生一個會在 20000 附近跳動的假價格
        # 讓你有東西可以測試
        price = 20000 + np.random.randint(-50, 50)
    
    # 產生 K 線 (為了算指標)
    prices = [price + np.random.randint(-10, 10) for _ in range(29)]
    prices.append(price)
    df = pd.DataFrame({"Close": prices})
    
    return price, df, source_name

# ==========================================
# 3. Telegram 強力診斷
# ==========================================
def debug_telegram():
    if not TG_TOKEN or not TG_CHAT_ID:
        return "❌ 失敗: Secrets 未設定 (請檢查 Streamlit 後台)"
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": "🔔 這是一條測試訊息\n如果你收到這個，代表設定完全正確！"}
    
    try:
        resp = requests.post(url, json=payload, timeout=5)
        data = resp.json()
        
        if resp.status_code == 200:
            return "✅ 成功: 伺服器回傳 OK (請檢查手機通知)"
        elif resp.status_code == 401:
            return "❌ 失敗 (401): Token 錯誤。請檢查機器人 Token 是否複製完整。"
        elif resp.status_code == 400:
            return "❌ 失敗 (400): Chat ID 錯誤。請檢查 ID 是否正確，或機器人是否在群組內。"
        elif resp.status_code == 403:
            return "❌ 失敗 (403): 被封鎖。請先去對機器人輸入 /start。"
        else:
            return f"❌ 失敗 ({resp.status_code}): {data.get('description')}"
            
    except Exception as e:
        return f"❌ 連線錯誤: {e}"

# ==========================================
# 4. 主畫面
# ==========================================
st.title("🚑 系統診斷中心")

# --- 側邊欄：Telegram 專區 ---
with st.sidebar:
    st.header("📡 通訊測試")
    
    if st.button("🔔 執行 Telegram 連線測試"):
        result = debug_telegram()
        if "成功" in result:
            st.success(result)
        else:
            st.error(result)
            st.info("請根據上方錯誤訊息修正 Secrets 設定。")
            
    st.divider()
    view = st.radio("人工方向濾網", ["偏多", "中立", "偏空"], index=1)
    auto = st.checkbox("自動刷新 (每10秒)", value=True)

# --- 主數據區 ---
try:
    # 1. 獲取數據 (含自動備援)
    price, df, source = get_data_with_fallback()
    
    # 2. 計算指標
    df.ta.bbands(close='Close', length=20, std=2, append=True)
    df.ta.rsi(close='Close', length=14, append=True)
    
    cols = df.columns.tolist()
    rsi_val = df.iloc[-1][next(c for c in cols if "RSI" in c)]
    
    # 3. 顯示
    c1, c2, c3 = st.columns(3)
    c1.metric("指數價格", f"{price:.0f}", delta=source) # 這裡會顯示來源
    c2.metric("RSI 指標", f"{rsi_val:.1f}")
    
    # 策略判斷
    sig = "WAIT"
    if rsi_val < 40 and view != "偏空": sig = "BUY_CALL"
    elif rsi_val > 60 and view != "偏多": sig = "BUY_PUT"
    
    if sig == "BUY_CALL":
        c3.metric("訊號", sig, "多", delta_color="normal")
    elif sig == "BUY_PUT":
        c3.metric("訊號", sig, "空", delta_color="inverse")
    else:
        c3.metric("訊號", "WAIT")
        
    st.line_chart(df["Close"])
    
    # 如果是模擬數據，顯示黃色警告
    if "模擬" in source:
        st.warning("⚠️ 目前 HiStock 阻擋連線，系統已自動切換至「模擬數據模式」。\n這不影響您測試 Telegram 功能，請按左側按鈕測試。")
        
except Exception as e:
    st.error(f"系統錯誤: {e}")

if auto:
    time.sleep(10)
    st.rerun()
