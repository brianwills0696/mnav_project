import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

# =========================
# 標題
# =========================
st.title("BTC & MSTR mNAV Dashboard")

# =========================
# 1. 抓 BTC 資料（CoinGecko）
# =========================
url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90"
response = requests.get(url)
data = response.json()

prices = data["prices"]
volumes = data["total_volumes"]

# 建 dataframe
df = pd.DataFrame(prices, columns=["timestamp", "price"])
df["volume"] = [v[1] for v in volumes]

# 時間轉換
df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
df.set_index("date", inplace=True)

# =========================
# 2. 轉成日K（OHLC）
# =========================
ohlc = df["price"].resample("1D").ohlc()

# =========================
# 3. 美化顯示
# =========================
def format_volume(x):
    return f"{x / 1e9:.1f}B"

def format_price(x):
    return f"{x:,.2f}"

df_display = df.sort_index(ascending=False).copy()
df_display["price"] = df_display["price"].apply(format_price)
df_display["volume"] = df_display["volume"].apply(format_volume)

st.subheader("BTC Raw Data")
st.dataframe(df_display.head(50))

# =========================
# 4. BTC 價格圖
# =========================
st.subheader("BTC Price Trend")
st.line_chart(df["price"])

# =========================
# 5. K線圖（Plotly）
# =========================
st.subheader("BTC Candlestick")

fig = go.Figure(data=[go.Candlestick(
    x=ohlc.index,
    open=ohlc['open'],
    high=ohlc['high'],
    low=ohlc['low'],
    close=ohlc['close']
)])

fig.update_layout(
    xaxis=dict(tickformat="%m/%d"),
    yaxis=dict(side="left")
)

st.plotly_chart(fig)

# =========================
# 6. 抓 MSTR 股價
# =========================
mstr = yf.download("MSTR", period="90d", interval="1d")

# 修正 MultiIndex
mstr.columns = mstr.columns.droplevel(1)

# 只留收盤價
mstr = mstr[['Close']]
mstr.rename(columns={"Close": "MSTR_price"}, inplace=True)

# =========================
# 7. BTC 日資料
# =========================
btc_daily = ohlc.copy()
btc_daily["BTC_price"] = btc_daily["close"]

# 合併
df_merged = btc_daily.join(mstr, how="inner")

# =========================
# 8. 抓 BTC Holdings（Bitbo）
# =========================
def get_mstr_btc_holdings():
    url = "https://bitbo.io/treasuries/microstrategy/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    import re
    text = soup.get_text()

    match = re.search(r"([\d,]+)\s+bitcoins", text, re.IGNORECASE)

    if match:
        return int(match.group(1).replace(",", ""))
    else:
        return None

BTC_HOLDINGS = get_mstr_btc_holdings()
st.write("BTC Holdings:", BTC_HOLDINGS)

# =========================
# 9. 固定 shares（重要！）
# =========================
# 這是用 Bitbo 反推的「經濟股數」
SHARES_OUTSTANDING = 345_000_000

# =========================
# 10. 計算 Market Cap
# =========================
df_merged["market_cap"] = df_merged["MSTR_price"] * SHARES_OUTSTANDING

# =========================
# 11. BTC 資產價值
# =========================
df_merged["btc_value"] = df_merged["BTC_price"] * BTC_HOLDINGS

# =========================
# 12. Enterprise Value（關鍵）
# =========================
# 來源：Bitbo snapshot
DEBT = 8254 * 1e6
PREF = 10006 * 1e6
CASH = 2250 * 1e6

df_merged["EV"] = (
    df_merged["market_cap"]
    + DEBT
    + PREF
    - CASH
)

# =========================
# 13. mNAV（正確版本）
# =========================
df_merged["mNAV"] = df_merged["EV"] / df_merged["btc_value"]

# =========================
# 14. Premium / Discount
# =========================
df_merged["Premium_%"] = (df_merged["mNAV"] - 1) * 100

# =========================
# 15. 圖表
# =========================
st.subheader("mNAV")
st.line_chart(df_merged["mNAV"])

st.subheader("Premium / Discount (%)")
st.line_chart(df_merged["Premium_%"])

st.subheader("BTC vs MSTR")
st.line_chart(df_merged[["BTC_price", "MSTR_price"]])

# =========================
# 16. 最新狀態
# =========================
latest_premium = df_merged["Premium_%"].iloc[-1]

if latest_premium > 0:
    st.success(f"Currently trading at PREMIUM: {latest_premium:.2f}%")
else:
    st.error(f"Currently trading at DISCOUNT: {latest_premium:.2f}%")

# =========================
# 17. 數據表
# =========================
df_display = df_merged[[
    "BTC_price",
    "MSTR_price",
    "market_cap",
    "btc_value",
    "EV",
    "mNAV",
    "Premium_%"
]].copy()

# 美化
df_display["BTC_price"] = df_display["BTC_price"].map(lambda x: f"${x:,.0f}")
df_display["MSTR_price"] = df_display["MSTR_price"].map(lambda x: f"${x:,.2f}")
df_display["market_cap"] = df_display["market_cap"].map(lambda x: f"${x/1e9:.2f}B")
df_display["btc_value"] = df_display["btc_value"].map(lambda x: f"${x/1e9:.2f}B")
df_display["EV"] = df_display["EV"].map(lambda x: f"${x/1e9:.2f}B")
df_display["mNAV"] = df_display["mNAV"].map(lambda x: f"{x:.2f}")
df_display["Premium_%"] = df_display["Premium_%"].map(lambda x: f"{x:.2f}%")

st.subheader("Detailed Data")
st.dataframe(df_display.tail(20))