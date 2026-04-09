import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime

# =========================
# 0. Streamlit 設定 + Cache
# =========================
st.set_page_config(page_title="BTC & MSTR mNAV Dashboard", layout="wide")

@st.cache_data(ttl=3600)
def get_btc_data():
    # Binance API: 獲取 BTCUSDT 數據
    symbol = "BTCUSDT"
    interval = "1h"  # 如果你想要像圖片中顯示每小時的數據，用 1h；如果是日線用 1d
    limit = 90
    
    klines_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    
    try:
        response = requests.get(klines_url, timeout=10)
        data = response.json()
        
        # 1. 建立原始 DataFrame
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
        ])
        
        # 2. 轉換數值格式
        df["price"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)
        
        # 3. 處理時間
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        
        # ✨ 關鍵修改：只保留你需要的欄位
        # 我們保留 date 是為了設為索引，保留 price 和 volume 是為了顯示與計算
        df = df[["date", "price", "volume"]]
        
        # 4. 設定索引並移除時區
        df.set_index("date", inplace=True)
        df.index = df.index.tz_localize(None)
        
        return df
    except Exception as e:
        st.error(f"Binance API 擷取失敗: {e}")
        return None
    
@st.cache_data(ttl=3600)
def get_mstr_data():
    ticker = yf.Ticker("MSTR")
    shares = ticker.info.get("sharesOutstanding", 345000000)

    hist = ticker.history(period="90d")["Close"]
    hist.index = hist.index.tz_localize(None)

    return shares, hist

@st.cache_data(ttl=3600)
def get_mstr_btc_holdings():
    url = "https://bitbo.io/treasuries/microstrategy/"
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        import re
        text = soup.get_text()
        match = re.search(r"([\d,]+)\s+bitcoins", text, re.IGNORECASE)

        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass

    return 252220


# =========================
# 1. 標題
# =========================
st.title("BTC & MSTR mNAV Dashboard")

# =========================
# 2. 抓資料
# =========================
df = get_btc_data()
shares_dynamic, mstr_hist = get_mstr_data()
BTC_HOLDINGS = get_mstr_btc_holdings()

# =========================
# 3. BTC → 12H K
# =========================
btc_12h = df["price"].resample("12h").ohlc()

btc_12h["BTC_price"] = btc_12h["close"]

# =========================
# 4. MSTR → 12H 對齊
# =========================
mstr_12h = mstr_hist.resample("12h").ffill()

df_combined = pd.DataFrame({
    "BTC_price": btc_12h["BTC_price"],
    "MSTR_price": mstr_12h
}).ffill()
# =========================
# 6. BTC Price
# =========================
st.subheader("BTC Price Trend")
st.line_chart(btc_12h["BTC_price"])
# =========================
# 6. BTC 原始資料 (修正版)
# =========================
st.subheader("BTC Raw Data")

# 1. 先複製一份資料，避免影響到後續計算
df_display = df.copy()

# 2. 如果 date 現在是索引 (Index)，把它轉回欄位才能顯示
if df_display.index.name == "date":
    df_display = df_display.reset_index()

# 3. 排序：最新的日期排在最上面
df_display = df_display.sort_values(by="date", ascending=False)

# 4. 格式化數值（讓它好看一點，加上千分位）
df_display["price"] = df_display["price"].map(lambda x: f"${x:,.2f}")
df_display["volume"] = df_display["volume"].map(lambda x: f"{x:,.2f}")

# 5. 確保只顯示這三欄 (防止其他隱藏欄位干擾)
df_display = df_display[["date", "price", "volume"]]

# 6. 正式繪製表格
st.dataframe(df_display.head(50), use_container_width=True)
# =========================
# 8. K線圖
# =========================
st.subheader("BTC Candlestick")

fig = go.Figure(data=[go.Candlestick(
    x=btc_12h.index.strftime("%-m/%-d"),  # ⭐ 改成 1/1 格式
    open=btc_12h['open'],
    high=btc_12h['high'],
    low=btc_12h['low'],
    close=btc_12h['close']
)])

st.plotly_chart(fig)

# =========================
# Sidebar
# =========================
st.subheader("📌 MSTR Financial Controls")

col1, col2, col3, col4 = st.columns(4)

adj_shares = col1.number_input("Shares Outstanding", value=shares_dynamic, step=1000000)
DEBT = col2.number_input("Total Debt", value=8254 * 1e6)
PREF = col3.number_input("Preferred Equity", value=10006 * 1e6)
CASH = col4.number_input("Cash", value=2250 * 1e6)

# =========================
# 5. mNAV 計算
# =========================
df_combined["market_cap"] = df_combined["MSTR_price"] * adj_shares
df_combined["btc_value"] = df_combined["BTC_price"] * BTC_HOLDINGS

df_combined["EV"] = (
    df_combined["market_cap"]
    + DEBT
    + PREF
    - CASH
)

df_combined["mNAV"] = df_combined["EV"] / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["mNAV"] - 1) * 100

# =========================
# 9. mNAV
# =========================
st.subheader("mNAV")
st.line_chart(df_combined["mNAV"])

st.subheader("Premium / Discount (%)")
st.line_chart(df_combined["Premium_%"])

# =========================
# 10. BTC vs MSTR normalized
# =========================
df_compare = df_combined[["BTC_price", "MSTR_price"]].dropna()

df_compare["BTC_norm"] = df_compare["BTC_price"] / df_compare["BTC_price"].iloc[0] * 100
df_compare["MSTR_norm"] = df_compare["MSTR_price"] / df_compare["MSTR_price"].iloc[0] * 100

st.subheader("BTC vs MSTR (Normalized)")
st.line_chart(df_compare[["BTC_norm", "MSTR_norm"]])

# =========================
# 11. 最新狀態
# =========================
latest = df_combined.iloc[-1]

col1, col2, col3 = st.columns(3)

col1.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
col2.metric("mNAV", f"{latest['mNAV']:.2f}x")
col3.metric("Premium", f"{latest['Premium_%']:.2f}%")

# =========================
# 12. 表格
# =========================
df_display = df_combined[[
    "BTC_price",
    "MSTR_price",
    "market_cap",
    "btc_value",
    "EV",
    "mNAV",
    "Premium_%"
]].copy()

df_display = df_display.sort_index(ascending=False)

df_display["BTC_price"] = df_display["BTC_price"].map(lambda x: f"${x:,.0f}")
df_display["MSTR_price"] = df_display["MSTR_price"].map(lambda x: f"${x:,.2f}")
df_display["market_cap"] = df_display["market_cap"].map(lambda x: f"${x/1e9:.2f}B")
df_display["btc_value"] = df_display["btc_value"].map(lambda x: f"${x/1e9:.2f}B")
df_display["EV"] = df_display["EV"].map(lambda x: f"${x/1e9:.2f}B")
df_display["mNAV"] = df_display["mNAV"].map(lambda x: f"{x:.2f}")
df_display["Premium_%"] = df_display["Premium_%"].map(lambda x: f"{x:.2f}%")

st.subheader("Detailed Data")
st.dataframe(df_display.head(20))