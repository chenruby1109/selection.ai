import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests
from bs4 import BeautifulSoup
import time

# ==========================================
# 1. 系統設定 (由 Secrets 讀取)
# ==========================================
st.set_page_config(page_title="AI 戰情室 (穩定版)", page_icon="📈", layout="wide")

try:
    TG_TOKEN = st.secrets["TG_TOKEN"]
    TG_CHAT_ID = st.secrets["TG_CHAT_ID"]
except:
    TG_TOKEN = ""
    TG_CHAT_ID = ""

# ==========================================
# 2. 爬蟲模組 (HiStock 嗨投資)
# ==========================================
def get_histock_price():
    """
    爬取嗨投資台指期報價
    """
    url = "https://histock.tw/future/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 針對嗨投資網頁結構抓取價格
        # 嘗試抓取 ID 為 DealPrice 的元素
        price_span = soup.find("span", id=lambda x: x and "DealPrice" in x)
        
        if price_span:
            price = float(price_span.text.replace(",", ""))
            return price
        else:
            return None
    except Exception as e:
        return None

def get_fake_history(current_price):
    """
    因為沒有 API Key，我們用現價生成一組假 K 線
    目的是為了讓指標 (RSI/BB) 能夠計算出數值
    """
    # 產生 30 筆數據，讓最後一筆等於現價
    # 這裡的技術指標僅供參考 (因為是用現價回推的)
    if not current_price:
        return None
        
    # 模擬一個小波動
    import numpy as np
    prices = [current_price + np.random.randint(-10, 10) for _ in range(29)]
    prices.append(current_price) # 確保最後一筆是準的
    
    df = pd.DataFrame({"Close": prices})
    return df

# ==========================================
# 3. Telegram 發送與除錯
# ==========================================
def send_telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return False, "未設定 Secrets"
    
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg}
    
    try:
        resp = requests.post(url, json=payload, timeout=5)
        result = resp.json()
        
        if resp.status_code == 200 and result.get("ok"):
            return True, "發送成功"
        else:
            return False, f"錯誤代碼 {resp.status_code}: {result.get('description')}"
    except Exception as e:
        return False, f"連線失敗: {e}"

# ==========================================
# 4. 策略邏輯
# ==========================================
def strategy(price, df, view):
    # 計算指標
    df.ta.bbands(close='Close', length=20, std=2, append=True)
    df.ta.rsi(close='Close', length=14, append=True)
    
    # 確保欄位產生成功
    cols = df.columns.tolist()
    if not any("BBU" in c for c in cols):
        return "WAIT", 0, "計算中"

    # 抓取數值
    last = df.iloc[-1]
    rsi = last[next(c for c in cols if "RSI" in c)]
    upper = last[next(c for c in cols if "BBU" in c)]
    lower = last[next(c for c in cols if "BBL" in c)]
    
    signal = "WAIT"
    
    # 策略判斷
    if price < lower and rsi < 35:
        if view != "偏空": signal = "BUY_CALL"
    elif price > upper and rsi > 65:
        if view != "偏多": signal = "BUY_PUT"
        
    return signal, rsi, f"RSI:{rsi:.1f}"

# ==========================================
# 5. 主畫面 UI
# ==========================================
st.title("🛡️ 選擇權戰情室 (除錯穩定版)")
st.caption("數據來源：HiStock 網頁爬蟲 | Telegram：即時推送")

# 側邊欄設定
with st.sidebar:
    st.header("🔧 設定")
    
    # Telegram 狀態檢查
    if TG_TOKEN and TG_CHAT_ID:
        st.success("Secrets 設定已讀取")
        if st.button("🔔 點我測試 Telegram"):
            with st.spinner("發送中..."):
                ok, log = send_telegram("👋 哈囉！這是一條測試訊息。\n如果你看到這個，代表機器人設定成功！")
                if ok:
                    st.success("✅ 測試成功！手機應該會響。")
                else:
                    st.error(f"❌ 測試失敗：{log}")
                    st.markdown("**常見原因：**\n1. **Chat ID 錯誤**: 請檢查數字。\n2. **未啟動機器人**: 請去 Telegram 對機器人輸入 `/start`。")
    else:
        st.error("⚠️ 未偵測到 Secrets")
        st.info("請到 Streamlit Cloud 設定 TG_TOKEN 和 TG_CHAT_ID")

    st.divider()
    manual_view = st.radio("今日盤勢看法", ["偏多", "中立", "偏空"], index=1)
    
    st.divider()
    auto_run = st.checkbox("開啟自動監控", value=False)

# 主邏輯區
col1, col2, col3 = st.columns(3)
chart_place = st.empty()
log_place = st.empty()

# 執行按鈕
if st.button("🔄 手動刷新一次") or auto_run:
    
    # 1. 抓取價格
    price = get_histock_price()
    
    if price:
        # 2. 產生數據並計算
        df = get_fake_history(price)
        sig, rsi, note = strategy(price, df, manual_view)
        
        # 3. 更新畫面
        col1.metric("台指期 (HiStock)", f"{price:.0f}")
        col2.metric("RSI 強度", f"{rsi:.1f}")
        
        if sig == "BUY_CALL":
            col3.metric("訊號", sig, "做多", delta_color="normal")
        elif sig == "BUY_PUT":
            col3.metric("訊號", sig, "做空", delta_color="inverse")
        else:
            col3.metric("訊號", "WAIT")
            
        # 畫簡單的圖
        chart_place.line_chart(df["Close"])
        
        # 4. 發送訊號
        if sig != "WAIT":
            # 為了防止洗版，使用 Session State 紀錄上次發送的價格
            last_sent = st.session_state.get("last_sent_price", 0)
            
            if abs(price - last_sent) > 5: # 價格變動超過 5 點才重發
                msg = f"🚀 [訊號觸發] {sig}\n價格: {price:.0f}\nRSI: {rsi:.1f}\n建議: 依照策略進場"
                send_telegram(msg)
                st.session_state["last_sent_price"] = price
                log_place.success(f"已發送通知: {sig}")
            else:
                log_place.info("訊號持續中 (已發送過)")
                
    else:
        st.warning("⚠️ 無法連線 HiStock，請稍後重試。")

    # 自動刷新的延遲 (避免過快導致 removeChild 錯誤)
    if auto_run:
        time.sleep(10) # 10秒刷新一次就好，太快會當機
        st.rerun()
