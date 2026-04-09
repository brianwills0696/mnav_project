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
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90"
    response = requests.get(url, timeout=10)
    data = response.json()

    prices = data["prices"]
    volumes = data["total_volumes"]

    df = pd.DataFrame(prices, columns=["timestamp", "price"])
    df["volume"] = [v[1] for v in volumes]

    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("date", inplace=True)

    # ✅ 關鍵修正：移除時區
    df.index = df.index.tz_localize(None)

    return df

@st.cache_data(ttl=3600)
def get_mstr_data():
    ticker = yf.Ticker("MSTR")

    # 股數（動態）
    shares = ticker.info.get("sharesOutstanding", 345000000)

    # 歷史價格
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

    return 252220  # fallback

def apply_date_format(fig):
    fig.update_layout(
        xaxis=dict(tickformat="%-m/%-d")
    )
    return fig
# =========================
# 1. 標題
# =========================
st.title(" BTC & MSTR mNAV Dashboard")

# =========================
# 2. 抓資料
# =========================
df = get_btc_data()
shares_dynamic, mstr_hist = get_mstr_data()
BTC_HOLDINGS = get_mstr_btc_holdings()

# =========================
# Sidebar（可調整參數）
# =========================
st.sidebar.header("📌 財務參數微調")

adj_shares = st.sidebar.number_input("發行股數", value=shares_dynamic, step=1000000)
DEBT = st.sidebar.number_input("總負債", value=8254 * 1e6)
PREF = st.sidebar.number_input("優先股", value=10006 * 1e6)
CASH = st.sidebar.number_input("現金", value=2250 * 1e6)

# =========================
# 3. BTC 日K
# =========================
ohlc = df["price"].resample("1D").ohlc()
btc_daily = ohlc.copy()
btc_daily["BTC_price"] = btc_daily["close"]

# =========================
# 4. MSTR（補齊週末）
# =========================
df_combined = pd.DataFrame({
    "BTC_price": btc_daily["BTC_price"],
    "MSTR_price": mstr_hist
}).ffill()

# =========================
# 5. mNAV 計算（修正版）
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
# 6. BTC 價格圖
# =========================
st.subheader("BTC Price Trend")
st.line_chart(df["price"])

# 7. BTC 原始資料
# =========================
st.subheader("BTC Raw Data")

def format_volume(x):
    return f"{x / 1e9:.1f}B"

def format_price(x):
    return f"{x:,.2f}"

df_display = df.sort_index(ascending=False).copy()

# 把 index（date）變回欄位
df_display = df_display.reset_index()

# 刪掉 timestamp
df_display = df_display.drop(columns=["timestamp"])

# 格式化
df_display["price"] = df_display["price"].apply(format_price)
df_display["volume"] = df_display["volume"].apply(format_volume)

st.dataframe(df_display.head(50))
# =========================
# =========================
# 8. K線圖
# =========================
st.subheader("BTC Candlestick")

fig = go.Figure(data=[go.Candlestick(
    x=ohlc.index,
    open=ohlc['open'],
    high=ohlc['high'],
    low=ohlc['low'],
    close=ohlc['close']
)])

st.plotly_chart(fig)

# =========================
# 9. mNAV 圖
# =========================
st.subheader("mNAV")
st.line_chart(df_combined["mNAV"])

st.subheader("Premium / Discount (%)")
st.line_chart(df_combined["Premium_%"])

# =========================
# 10. BTC vs MSTR
# =========================
df_compare = df_combined[["BTC_price", "MSTR_price"]].dropna()

df_compare["BTC_norm"] = df_compare["BTC_price"] / df_compare["BTC_price"].iloc[0] * 100
df_compare["MSTR_norm"] = df_compare["MSTR_price"] / df_compare["MSTR_price"].iloc[0] * 100

st.subheader("BTC vs MSTR (Normalized)")
st.line_chart(df_compare[["BTC_norm", "MSTR_norm"]])

# st.subheader("BTC vs MSTR")
# st.line_chart(df_combined[["BTC_price", "MSTR_price"]])

# 雙軸
#fig = go.Figure()
# 
# fig.add_trace(go.Scatter(
    # x=df_combined.index,
    # y=df_combined["BTC_price"],
    # name="BTC",
    # yaxis="y1"
# ))

# fig.add_trace(go.Scatter(
    # x=df_combined.index,
    # y=df_combined["MSTR_price"],
    # name="MSTR",
    # yaxis="y2"
# ))

# fig.update_layout(
    # title="BTC vs MSTR (Dual Axis)",
    # yaxis=dict(title="BTC Price"),
    # yaxis2=dict(title="MSTR Price", overlaying="y", side="right")
# )

#st.plotly_chart(fig)

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




