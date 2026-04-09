import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh
from openai import OpenAI

client = OpenAI()

# =========================
# AI 分析
# =========================
def generate_ai_summary(df_combined):
    latest = df_combined.iloc[-1]

    prompt = f"""
You are a professional macro and crypto equity analyst.

BTC Price: {latest['BTC_price']:.2f}
MSTR Price: {latest['MSTR_price']:.2f}
mNAV: {latest['mNAV']:.2f}

Recent Trend:
- BTC change (24h): {(df_combined['BTC_price'].iloc[-1] / df_combined['BTC_price'].iloc[-24] - 1)*100:.2f}%
- MSTR change (24h): {(df_combined['MSTR_price'].iloc[-1] / df_combined['MSTR_price'].iloc[-24] - 1)*100:.2f}%

1. Trend
2. mNAV valuation
3. Short insight
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content


# =========================
# 設定
# =========================
st_autorefresh(interval=5000, key="global_update")
st.set_page_config(page_title="BTC & MSTR Dashboard", layout="wide")


# =========================
# 工具函式
# =========================
def get_y_range(df, start, end, padding=0.05):
    mask = (df['date'] >= start) & (df['date'] <= end)
    df_filtered = df.loc[mask]
    if df_filtered.empty:
        return [None, None]

    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]


# =========================
# 資料抓取
# =========================
@st.cache_data(ttl=5)
def fetch_btc_realtime_price():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        res = requests.get(url, timeout=5)
        return res.json()["bitcoin"]["usd"]
    except:
        return None


@st.cache_data(ttl=600)
def fetch_btc_binance(interval="1h", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=10).json()

    df = pd.DataFrame(data, columns=["ot", "open", "high", "low", "close", "vol", "ct", "qv", "n", "tbb", "tbq", "i"])
    df["date"] = pd.to_datetime(df["ot"], unit="ms")
    df[["open", "high", "low", "close", "vol"]] = df[["open", "high", "low", "close", "vol"]].astype(float)

    return df


@st.cache_data(ttl=600)
def fetch_mstr_yf(period="2y", interval="1d"):
    ticker = yf.Ticker("MSTR")
    df = ticker.history(period=period, interval=interval)

    shares = ticker.info.get("sharesOutstanding", 345000000)

    df = df.reset_index()
    df.rename(columns={
        df.columns[0]: "date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "vol"
    }, inplace=True)

    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)

    return df, shares


@st.cache_data(ttl=3600)
def get_mstr_btc_holdings():
    try:
        url = "https://bitbo.io/treasuries/microstrategy/"
        soup = BeautifulSoup(requests.get(url, timeout=10).text, "html.parser")

        import re
        match = re.search(r"([\d,]+)\s+bitcoins", soup.get_text(), re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass

    return 252220


# =========================
# 資料
# =========================
btc_h = fetch_btc_binance("1h", 1000)
btc_d = fetch_btc_binance("1d", 400)
btc_w = fetch_btc_binance("1w", 100)

mstr_data_h, shares = fetch_mstr_yf("2y", "1d")
mstr_data_d, _ = fetch_mstr_yf("2y", "1d")
mstr_data_w, _ = fetch_mstr_yf("5y", "1wk")

BTC_HOLDINGS = get_mstr_btc_holdings()

DEBT = 8254 * 1e6
PREF = 10006 * 1e6
CASH = 2250 * 1e6


btc_idx = btc_h.set_index("date")["close"]
mstr_idx = mstr_data_h.set_index("date")["close"]

df_combined = pd.DataFrame({
    "BTC_price": btc_idx,
    "MSTR_price": mstr_idx
}).ffill().bfill()

df_combined["market_cap"] = df_combined["MSTR_price"] * shares
df_combined["btc_value"] = df_combined["BTC_price"] * BTC_HOLDINGS
df_combined["EV"] = df_combined["market_cap"] + DEBT + PREF - CASH
df_combined["mNAV"] = df_combined["EV"] / df_combined["btc_value"]


# =========================
# 圖表
# =========================
def create_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()

    h_s = now - timedelta(days=3)
    d_s = now - timedelta(days=60)
    w_s = now - timedelta(days=365)

    fig.add_trace(go.Candlestick(
        x=df_h['date'],
        open=df_h['open'],
        high=df_h['high'],
        low=df_h['low'],
        close=df_h['close']
    ))

    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            buttons=[
                dict(label="H", method="update", args=[
                    {"x": [df_h.date]},
                    {"xaxis": {"range": [h_s, now]}}
                ]),
                dict(label="D", method="update", args=[
                    {"x": [df_d.date]},
                    {"xaxis": {"range": [d_s, now]}}
                ]),
                dict(label="W", method="update", args=[
                    {"x": [df_w.date]},
                    {"xaxis": {"range": [w_s, now]}}
                ]),
            ]
        )],
        xaxis=dict(type="date"),
        height=500
    )

    return fig


# =========================
# UI
# =========================
st.title("BTC & MSTR Dashboard")

st.subheader("BTC Price")
st.plotly_chart(create_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

price = fetch_btc_realtime_price()
st.metric("BTC Price", f"${price:,.2f}" if price else "Loading...")

st.subheader("MSTR")
st.plotly_chart(create_chart(mstr_data_h, mstr_data_d, mstr_data_w, "MSTR", True), use_container_width=True)

st.subheader("mNAV")
fig = go.Figure()
fig.add_trace(go.Scatter(x=df_combined.index, y=df_combined["mNAV"]))
st.plotly_chart(fig, use_container_width=True)

if st.button("AI Analysis"):
    st.write(generate_ai_summary(df_combined))