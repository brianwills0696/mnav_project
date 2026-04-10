import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime
import re

# =========================
# 0. Streamlit 設定 + Cache
# =========================
st.set_page_config(page_title="BTC & MSTR mNAV Dashboard", layout="wide")

@st.cache_data(ttl=3600)
def get_btc_data():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90"
    response = requests.get(url, timeout=10)
    data = response.json()

    prices = data["prices"]
    volumes = data["total_volumes"]

    df = pd.DataFrame(prices, columns=["timestamp", "price"])
    df["volume"] = [v[1] for v in volumes]

    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("date", inplace=True)

    df.index = df.index.tz_localize(None)

    return df

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
def get_effective_diluted_shares():
    url = "https://saylortracker.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        # 使用正則表達式直接從網頁原始碼中找尋數據
        # 尋找 "Effective Diluted Shares" 後方的數字
        match = re.search(r'Effective Diluted Shares.*?([\d,]+)', response.text, re.DOTALL)
        
        if match:
            shares_str = match.group(1).replace(",", "")
            return int(shares_str)
        else:
            print("無法在頁面上找到 Effective Diluted Shares，使用預設值")
            return 257000000  # 預設參考值
    except Exception as e:
        print(f"爬蟲發生錯誤: {e}")
        return 257000000

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
# Sidebar
# =========================
st.sidebar.header("📌 財務參數微調")

adj_shares = st.sidebar.number_input("發行股數", value=shares_dynamic, step=1000000)
DEBT = st.sidebar.number_input("總負債", value=8254 * 1e6)
PREF = st.sidebar.number_input("優先股", value=10006 * 1e6)
CASH = st.sidebar.number_input("現金", value=2250 * 1e6)

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
# 6. BTC Price
# =========================
st.subheader("BTC Price Trend")
st.line_chart(df["price"])

# =========================
# 7. BTC Raw Data
# =========================
st.subheader("BTC Raw Data")

def format_volume(x):
    return f"{x / 1e9:.1f}B"

def format_price(x):
    return f"{x:,.2f}"

df_display = df.sort_index(ascending=False).copy()
df_display = df_display.reset_index()
df_display = df_display.drop(columns=["timestamp"])

df_display["price"] = df_display["price"].apply(format_price)
df_display["volume"] = df_display["volume"].apply(format_volume)

st.dataframe(df_display.head(50))

# =========================
# 8. K線圖（12H + 日期格式）
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
# 10. BTC vs MSTR (雙 Y 軸)
# =========================
st.subheader("BTC vs MSTR Price (Dual Y-Axis)")

df_compare = df_combined[["BTC_price", "MSTR_price"]].dropna()

# 建立一個帶有次座標軸的圖表
from plotly.subplots import make_subplots

fig_dual = make_subplots(specs=[[{"secondary_y": True}]])

# 加入 BTC 曲線 (左軸)
fig_dual.add_trace(
    go.Scatter(x=df_compare.index, y=df_compare["BTC_price"], name="BTC Price ($)", line=dict(color="orange")),
    secondary_y=False,
)

# 加入 MSTR 曲線 (右軸)
fig_dual.add_trace(
    go.Scatter(x=df_compare.index, y=df_compare["MSTR_price"], name="MSTR Price ($)", line=dict(color="blue")),
    secondary_y=True,
)

# 設定圖表標題與軸標籤
fig_dual.update_layout(
    title_text="BTC and MSTR Price Comparison",
    hovermode="x unified"
)

fig_dual.update_yaxes(title_text="<b>BTC</b> Price (USD)", secondary_y=False)
fig_dual.update_yaxes(title_text="<b>MSTR</b> Price (USD)", secondary_y=True)

st.plotly_chart(fig_dual, use_container_width=True)

# =========================
# 11. 最新狀態
# =========================
latest = df_combined.iloc[-1]

col1, col2, col3 = st.columns(3)

col1.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
col2.metric("mNAV", f"{latest['mNAV']:.2f}x")
col3.metric("Premium", f"{latest['Premium_%']:.2f}%")

# =========================
# 12. 表格（降序 + 12H）
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