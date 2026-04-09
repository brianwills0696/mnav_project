import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# =========================
# 0. Streamlit 設定
# =========================
st.set_page_config(page_title="BTC & MSTR Pro Terminal", layout="wide")

# --- 資料抓取函式 ---

@st.cache_data(ttl=600)
def fetch_btc_binance(interval="1h", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=10).json()
    df = pd.DataFrame(data, columns=["ot", "open", "high", "low", "close", "vol", "ct", "qv", "n", "tbb", "tbq", "i"])
    df["date"] = pd.to_datetime(df["ot"], unit="ms")
    df[["open", "high", "low", "close", "vol"]] = df[["open", "high", "low", "close", "vol"]].astype(float)
    return df

@st.cache_data(ttl=600)
def fetch_mstr_yf(period="2y", interval="1h"):
    ticker = yf.Ticker("MSTR")
    df = ticker.history(period=period, interval=interval)
    shares = ticker.info.get("sharesOutstanding", 345000000)
    df = df.reset_index()
    df.rename(columns={df.columns[0]: "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "vol"}, inplace=True)
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    return df, shares

@st.cache_data(ttl=3600)
def get_mstr_btc_holdings():
    url = "https://bitbo.io/treasuries/microstrategy/"
    try:
        response = requests.get(url, timeout=10); soup = BeautifulSoup(response.text, "html.parser")
        import re; match = re.search(r"([\d,]+)\s+bitcoins", soup.get_text(), re.IGNORECASE)
        if match: return int(match.group(1).replace(",", ""))
    except: pass
    return 252220 

# =========================
# 1. 執行數據抓取
# =========================
btc_h = fetch_btc_binance("1h", 1000)
btc_d = fetch_btc_binance("1d", 400)
btc_w = fetch_btc_binance("1w", 100)

mstr_data_h, shares_dynamic = fetch_mstr_yf("2y", "1h")
mstr_data_d, _ = fetch_mstr_yf("2y", "1d")
mstr_data_w, _ = fetch_mstr_yf("5y", "1wk")
BTC_HOLDINGS = get_mstr_btc_holdings()

# 側邊欄參數
st.sidebar.header("📌 財務參數調整")
adj_shares = st.sidebar.number_input("發行股數", value=shares_dynamic)
DEBT = st.sidebar.number_input("總負債 (USD)", value=8254 * 1e6)
PREF = st.sidebar.number_input("優先股 (USD)", value=10006 * 1e6)
CASH = st.sidebar.number_input("現金 (USD)", value=2250 * 1e6)

# mNAV 計算 (週末保留 BTC 變動，MSTR 沿用週五價)
btc_hourly_idx = btc_h.set_index("date")["close"]
mstr_hourly_idx = mstr_data_h.set_index("date")["close"]
df_combined = pd.DataFrame({"BTC_price": btc_hourly_idx, "MSTR_price": mstr_hourly_idx}).ffill().bfill()

df_combined["market_cap"] = df_combined["MSTR_price"] * adj_shares
df_combined["btc_value"] = df_combined["BTC_price"] * BTC_HOLDINGS
df_combined["EV"] = (df_combined["market_cap"] + DEBT + PREF - CASH)
df_combined["mNAV"] = df_combined["EV"] / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["mNAV"] - 1) * 100

update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# --- 圖表生成邏輯 ---
def create_interactive_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()
    h_start, d_start, w_start = now-timedelta(days=3), now-timedelta(days=60), now-timedelta(days=365)

    fig.add_trace(go.Candlestick(x=df_h['date'], open=df_h['open'], high=df_h['high'], low=df_h['low'], close=df_h['close'], name=label))
    
    fig.update_layout(
        updatemenus=[dict(type="buttons", direction="right", active=0, x=0, y=1.15,
            buttons=[
                dict(label="Hourly (3D)", method="update", args=[{"x":[df_h.date],"open":[df_h.open],"high":[df_h.high],"low":[df_h.low],"close":[df_h.close]},{"xaxis":{"range":[h_start,now],"rangeslider":{"visible":False}}}]),
                dict(label="Daily (60D)", method="update", args=[{"x":[df_d.date],"open":[df_d.open],"high":[df_d.high],"low":[df_d.low],"close":[df_d.close]},{"xaxis":{"range":[d_start,now],"rangeslider":{"visible":False}}}]),
                dict(label="Weekly (1Y)", method="update", args=[{"x":[df_w.date],"open":[df_w.open],"high":[df_w.high],"low":[df_w.low],"close":[df_w.close]},{"xaxis":{"range":[w_start,now],"rangeslider":{"visible":False}}}]),
            ])],
        xaxis=dict(range=[h_start, now], rangeslider_visible=False, constrain="domain"),
        height=500, margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified"
    )
    if is_stock:
        fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=[16, 9.5], pattern="hour")])
    return fig

# =========================
# 2. 介面排版
# =========================

st.title("₿ BTC & MSTR Professional Analytics")

# --- 1. BTC K線圖 ---
st.subheader("1. BTC Candlestick")
st.plotly_chart(create_interactive_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

# BTC 指標
bt_c1, bt_c2, bt_c3 = st.columns(3)
latest_btc = btc_h.iloc[-1]
bt_c1.metric("Current Price", f"${latest_btc['close']:,.2f}")
bt_c2.metric("24h High", f"${btc_h.iloc[-24:]['high'].max():,.2f}")
bt_c3.metric("24h Volume", f"{btc_h.iloc[-24:]['vol'].sum():,.0f} BTC")
st.caption(f"🕒 **Last update:** {update_time} | **Source:** Binance API")

# --- 2. BTC 表格 ---
st.subheader("2. BTC Hourly Data (Latest)")
st.dataframe(btc_h.sort_values("date", ascending=False).head(10)[["date", "close", "vol"]], use_container_width=True)

# --- 3. MSTR K線圖 ---
st.markdown("---")
st.subheader("3. MSTR Stock Price")
st.plotly_chart(create_interactive_chart(mstr_data_h, mstr_data_d, mstr_data_w, "MSTR", is_stock=True), use_container_width=True)
st.caption(f"🕒 **Last update:** {update_time} | **Source:** Yahoo Finance")

# --- 4. mNAV 走勢圖 ---
st.markdown("---")
st.subheader("4. MSTR mNAV Hourly Trend")
fig_mnav = go.Figure()
fig_mnav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["mNAV"], line=dict(color='orange', width=2), name="mNAV"))
fig_mnav.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(rangeslider_visible=False, constrain="domain"))
st.plotly_chart(fig_mnav, use_container_width=True)

# mNAV 指標
mn_c1, mn_c2, mn_c3, mn_c4 = st.columns(4)
latest_nav = df_combined.iloc[-1]
mn_c1.metric("MSTR Stock Price", f"${latest_nav['MSTR_price']:.2f}")
mn_c2.metric("Market Cap", f"${latest_nav['market_cap']/1e9:.2f}B")
mn_c3.metric("mNAV Ratio", f"{latest_nav['mNAV']:.2f}x")
mn_c4.metric("NAV Premium", f"{latest_nav['Premium_%']:.2f}%")
st.caption(f"🕒 **Last update:** {update_time} | **Source:** Combined Binance & YF Data")

# --- 5. MSTR 詳細資訊 ---
st.subheader("5. Detailed mNAV Analytics")
st.dataframe(df_combined.sort_index(ascending=False).head(20), use_container_width=True)