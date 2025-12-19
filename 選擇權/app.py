import streamlit as st
import pandas as pd
import pandas_ta as ta
import requests
from bs4 import BeautifulSoup # 用來爬嗨投資
import time
from datetime import datetime

# ==========================================
# 1. 系統與 Telegram 設定
# ==========================================
st.set_page_config(page_title="AI 戰情室 (HiStock版)", page_icon="⚡", layout="wide")

# 嘗試讀取 Secrets
TG_TOKEN = st.secrets.get("TG_TOKEN", "")
TG_CHAT_ID = st.secrets.get("TG_CHAT_ID", "")

# 側邊欄：顯示 Telegram 狀態
with st.sidebar:
    st.header("🤖 Telegram 設定檢查")
    if not TG_TOKEN or not TG_CHAT_ID:
        st.error("❌ 未偵測到 Token 或 ID")
        st.info("請在 Streamlit Cloud -> Settings -> Secrets 貼上設定")
    else:
        st.success("✅ 已讀取 Token 設定")

    st.divider()

# ==========================================
# 2. 爬蟲模組 (HiStock 嗨投資)
# ==========================================
def get_histock_price():
    """
    直接爬取嗨投資期貨頁面，避開 API 封鎖
    """
    url = "https://histock.tw/future/"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 嗨投資的台指期報價通常在這個 ID 或是結構下
        # 這裡針對台指期近月 (TX) 抓取
        # 注意：網頁結構可能會變，這是爬蟲的風險
        
        # 嘗試抓取大字報價
        price_element = soup.select_one("span[id*='DealPrice']") 
        # 如果上面抓不到，試試看列表中的第一個 (通常是台指期)
        if not price_element:
            price_element = soup.select_one(".price span")
            
        if price_element:
            price_text = price_element.text.replace(",", "")
            price = float(price_text)
            return price
        else:
            return None
    except Exception as e:
        print(f"HiStock 爬取失敗: {e}")
        return None

def get_data_hybrid():
    """
    混合數據源：
    1. 價格：從 HiStock 爬蟲抓 (即時不擋IP)
    2. K線：用 Yahoo 抓歷史數據來算指標 (RSI/BB)，只抓收盤價
    """
    # 1. 先抓現在的價格 (Real-time)
    current_price = get_histock_price()
    
    # 2. 抓歷史數據算指標 (Yahoo 的歷史數據 API 比較少擋，即時才會擋)
    try:
        import yfinance as yf
        df = yf.download(tickers="TX=F", period="5d", interval="15m", progress=False)
        
        if df.empty:
            # 如果 Yahoo 完全掛了，我們手動造一個只有現價的 DataFrame
            if current_price:
                df = pd.DataFrame({"Close": [current_price]*30})
            else:
                return None, "數據源全滅"
        
        # 清洗資料
        df.reset_index(inplace=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df.columns = [str(c) for c in df.columns]
        
        # 如果我們有抓到嗨投資的最新價，把最後一根 K 棒換成最新價
        # 這樣指標才會準
        if current_price and "Close" in df.columns:
            # 使用 pandas 的 iloc 修改最後一筆收盤價
            df.iloc[-1, df.columns.get_loc("Close")] = current_price
            
        # 移除空值
        df.dropna(inplace=True)
        
        return df, current_price
        
    except Exception as e:
        return None, str(e)

# ==========================================
# 3. 策略與發送模組 (含除錯功能)
# ==========================================

def send_telegram_debug(msg):
    """
    發送 Telegram 並回傳伺服器回應 (除錯用)
    """
    if not TG_TOKEN or not TG_CHAT_ID:
        return False, "❌ 未設定 Token 或 Chat ID"
        
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": msg}
    
    try:
        resp = requests.post(url, json=payload, timeout=5)
        result = resp.json()
        
        if resp.status_code == 200 and result.get("ok"):
            return True, "✅ 發送成功！請檢查手機。"
        else:
            # 回傳錯誤代碼 (例如 400, 401)
            error_desc = result.get("description", "未知錯誤")
            return False, f"❌ 發送失敗 (代碼 {resp.status_code}): {error_desc}"
            
    except Exception as e:
        return False, f"❌ 連線錯誤: {e}"

def strategy(df, manual_view):
    # 確保有 Close
    if "Close" not in df.columns: return "WAIT", 0, 0, "No Data"

    # 計算指標
    try:
        df.ta.bbands(close='Close', length=20, std=2, append=True)
        df.ta.rsi(close='Close', length=14, append=True)
    except: return "WAIT", 0, 0, "Error"
    
    # 找欄位
    cols = df.columns.tolist()
    bbu = next((c for c in cols if "BBU" in c), None)
    bbl = next((c for c in cols if "BBL" in c), None)
    rsi_c = next((c for c in cols if "RSI" in c), None)

    if not bbu or not rsi_c: return "WAIT", 0, 0, "Col Error"

    last = df.iloc[-1]
    close = last["Close"]
    rsi = last[rsi_c]
    upper = last[bbu]
    lower = last[bbl]
    
    signal = "WAIT"
    note = ""

    # 策略邏輯
    if close < lower and rsi < 35: # 放寬一點讓你好測試
        if manual_view != "偏空":
            signal = "BUY_CALL"
            note = "📉 跌破下軌+RSI低檔 (嗨投資源)"
            
    elif close > upper and rsi > 65:
        if manual_view != "偏多":
            signal = "BUY_PUT"
            note = "📈 突破上軌+RSI高檔 (嗨投資源)"
            
    return signal, close, rsi, note

# ==========================================
# 4. 前端介面
# ==========================================
st.title("⚡ AI 選擇權戰情室 (嗨投資訊號源)")
st.markdown("---")

# 初始化
if "last_sig" not in st.session_state: st.session_state.last_sig = ""

with st.sidebar:
    st.subheader("🕵️ 人工濾網")
    pcr_option = st.radio("今日方向:", ["偏多", "中立", "偏空"], index=1)
    
    st.divider()
    st.subheader("🛠️ Telegram 測試區")
    
    # === 測試按鈕 (除錯版) ===
    if st.button("🔔 發送測試訊息"):
        if not TG_TOKEN:
            st.error("無法發送：請先設定 Secrets")
        else:
            with st.spinner("正在連線 Telegram..."):
                success, log = send_telegram_debug("✅ 這是來自嗨投資戰情室的測試訊息！\n如果你看到這條，代表連線成功。")
                if success:
                    st.success(log)
                    st.balloons()
                else:
                    st.error(log) # 這裡會直接顯示錯誤原因！
                    st.markdown("**常見錯誤解法：**\n1. **400 Bad Request**: Chat ID 填錯。\n2. **401 Unauthorized**: Token 填錯。\n3. **Chat not found**: 機器人沒加你好友，請對機器人按 `/start`。")

    auto_refresh = st.checkbox("自動刷新 (60s)", value=True)

# 主畫面
if st.button("🔄 立即分析") or auto_refresh:
    
    with st.spinner("正在從 HiStock 爬取即時報價..."):
        df, current_price = get_data_hybrid()
        
        if df is not None and current_price:
            sig, price, rsi, note = strategy(df, pcr_option)
            
            # 顯示
            col1, col2, col3 = st.columns(3)
            col1.metric("台指期 (HiStock)", f"{price:.0f}")
            col2.metric("RSI 指標", f"{rsi:.1f}")
            
            if sig == "BUY_CALL":
                col3.metric("訊號", sig, "做多 Buy Call", delta_color="normal")
            elif sig == "BUY_PUT":
                col3.metric("訊號", sig, "做空 Buy Put", delta_color="inverse")
            else:
                col3.metric("訊號", "WAIT", "觀望")
            
            st.line_chart(df["Close"])
            st.caption(f"數據來源：HiStock (現價) + Yahoo (歷史K棒) | 狀態: {note}")
            
            # 發送訊號
            sig_id = f"{sig}_{price:.0f}"
            if sig != "WAIT" and st.session_state.last_sig != sig_id:
                msg = f"🚀 [訊號觸發] {sig}\n價格: {price:.0f}\nRSI: {rsi:.1f}\n來源: HiStock"
                success, log = send_telegram_debug(msg)
                if success:
                    st.toast("已發送訊號至 Telegram")
                st.session_state.last_sig = sig_id
                
        else:
            st.error("⚠️ 無法取得數據。可能是 HiStock 改版或網路問題。")
            if current_price: # 如果有錯誤訊息
                st.write(f"錯誤詳情: {current_price}")

    if auto_refresh:
        time.sleep(60)
        st.rerun()
