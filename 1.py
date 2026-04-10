import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import re
from datetime import datetime, timedelta

# =========================
# 0. Streamlit 設定
# =========================
st.set_page_config(page_title="MSTR Diluted mNAV Dashboard", layout="wide")

# =========================
# 1. 資料抓取函數 (含爬蟲)
# =========================

@st.cache_data(ttl=3600)
def get_btc_data():
    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=90"
    response = requests.get(url, timeout=10)
    data = response.json()
    df = pd.DataFrame(data["prices"], columns=["timestamp", "price"])
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("date", inplace=True)
    df.index = df.index.tz_localize(None)
    return df

@st.cache_data(ttl=3600)
def get_mstr_data():
    ticker = yf.Ticker("MSTR")
    hist = ticker.history(period="90d")["Close"]
    hist.index = hist.index.tz_localize(None)
    return hist

@st.cache_data(ttl=3600)
def get_effective_diluted_shares():
    url = "https://saylortracker.com/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        match = re.search(r'Effective Diluted Shares.*?([\d,]+)', response.text, re.DOTALL)
        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass
    return 380000000

@st.cache_data(ttl=3600)
def get_mstr_btc_holdings():
    url = "https://bitbo.io/treasuries/microstrategy/"
    try:
        response = requests.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()
        match = re.search(r"([\d,]+)\s+bitcoins", text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass
    return 252220

# =========================
# 2. 頁面頂端：參數調整區 (原 Sidebar)
# =========================
st.title("MSTR Diluted mNAV Dashboard")

# 預抓數據作為預設值
default_shares = get_effective_diluted_shares()
default_btc = get_mstr_btc_holdings()

st.markdown("### 核心計算參數調整")
col_input1, col_input2 = st.columns(2)

with col_input1:
    adj_diluted_shares = st.number_input(
        "Effective Diluted Shares (稀釋後總股數)", 
        value=default_shares, 
        step=100000,
        format="%d"
    )

with col_input2:
    adj_btc_holdings = st.number_input(
        "BTC Holdings (MSTR 總持幣量)", 
        value=default_btc, 
        step=100,
        format="%d"
    )

st.divider()

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
# 3. 執行計算
# =========================
df_btc = get_btc_data()
mstr_hist = get_mstr_data()

# 資料對齊 (12H)
btc_12h = df_btc["price"].resample("12h").ohlc()
mstr_12h = mstr_hist.resample("12h").ffill()

df_combined = pd.DataFrame({
    "BTC_price": btc_12h["close"],
    "MSTR_price": mstr_12h
}).ffill().dropna()

# 使用調整後的參數計算 Diluted mNAV
df_combined["diluted_mNAV"] = (adj_diluted_shares * df_combined["MSTR_price"]) / (adj_btc_holdings * df_combined["BTC_price"])
df_combined["Premium_%"] = (df_combined["diluted_mNAV"] - 1) * 100

# =========================
# 4. 數據清單與指標
# =========================
latest = df_combined.iloc[-1]


st.subheader("BTC Price")
st.plotly_chart(create_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

st.subheader("Current indicator")
m1, m2, m3, m4 = st.columns(4)
m1.metric("BTC Price", f"${latest['BTC_price']:,.0f}")
m2.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
m3.metric("Diluted mNAV", f"{latest['diluted_mNAV']:.2f}x")
m4.metric("Premium %", f"{latest['Premium_%']:.2f}%")

m5, m6, m7, m8 = st.columns(4)
m5.metric("Effective Diluted Shares", f"{adj_diluted_shares:,.0f}")
m6.metric("BTC Holdings", f"{adj_btc_holdings:,.0f} BTC")
m7.metric("BTC per Share", f"{(adj_btc_holdings / adj_diluted_shares):.6f}")
m8.metric("Total BTC Value", f"${(adj_btc_holdings * latest['BTC_price'])/1e9:.2f}B")

st.subheader("https://saylortracker.com/?tab=charts")

# =========================
# 5. 視覺化圖表 (雙 Y 軸)
# =========================
st.subheader("BTC vs MSTR Price Correlation")
fig_dual = make_subplots(specs=[[{"secondary_y": True}]])
fig_dual.add_trace(go.Scatter(x=df_combined.index, y=df_combined["BTC_price"], name="BTC (Left)", line=dict(color="orange")), secondary_y=False)
fig_dual.add_trace(go.Scatter(x=df_combined.index, y=df_combined["MSTR_price"], name="MSTR (Right)", line=dict(color="dodgerblue")), secondary_y=True)
fig_dual.update_layout(hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
fig_dual.update_yaxes(title_text="BTC Price (USD)", secondary_y=False)
fig_dual.update_yaxes(title_text="MSTR Price (USD)", secondary_y=True)
st.plotly_chart(fig_dual, use_container_width=True)

# =========================
# 6. 詳細資料表格
# =========================
st.subheader("Historical Database")
df_display = df_combined.sort_index(ascending=False).copy()
df_display["BTC_price"] = df_display["BTC_price"].map(lambda x: f"${x:,.0f}")
df_display["MSTR_price"] = df_display["MSTR_price"].map(lambda x: f"${x:,.2f}")
df_display["diluted_mNAV"] = df_display["diluted_mNAV"].map(lambda x: f"{x:.3f}x")
df_display["Premium_%"] = df_display["Premium_%"].map(lambda x: f"{x:.2f}%")

# 顯示關鍵欄位
st.dataframe(df_display[["BTC_price", "MSTR_price", "diluted_mNAV", "Premium_%"]].head(20), use_container_width=True)