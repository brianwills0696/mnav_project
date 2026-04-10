import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import yfinance as yf
import re
from datetime import datetime, timedelta
from streamlit_autorefresh import st_autorefresh

# =========================
# 0. Streamlit Configuration
# =========================
st.set_page_config(page_title="MSTR & BTC Dashboard (CoinGecko)", layout="wide")
st_autorefresh(interval=60000, key="global_update") 

# =========================
# 1. Data Fetching Functions
# =========================
@st.cache_data(ttl=300)
def fetch_btc_coingecko_ohlc(days="1"):
    """Fetch OHLC data from CoinGecko"""
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days={days}"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 429:
            st.error("CoinGecko API Rate Limit reached. Please wait a moment.")
            return pd.DataFrame()
        res.raise_for_status()
        data = res.json()
        
        if not data:
            return pd.DataFrame()
            
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        st.error(f"Failed to fetch BTC data: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_mstr_stock():
    """Fetch MSTR stock data from Yahoo Finance"""
    try:
        ticker = yf.Ticker("MSTR")
        df = ticker.history(period="2y", interval="1d")
        if df.empty: return pd.DataFrame()
        df.index = df.index.tz_localize(None)
        df = df.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
        return df
    except Exception as e:
        st.warning(f"MSTR data restricted (yfinance limit): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_live_stats():
    """Scrape live stats from SaylorTracker and Bitbo"""
    stats = {"shares": 380000000, "btc_holdings": 252220}
    try:
        # BTC Holdings from Bitbo
        res_bitbo = requests.get("https://bitbo.io/treasuries/microstrategy/", timeout=10)
        match_btc = re.search(r"([\d,]+)\s+bitcoins", res_bitbo.text, re.IGNORECASE)
        if match_btc: stats["btc_holdings"] = int(match_btc.group(1).replace(",", ""))
        
        # Diluted Shares from SaylorTracker
        headers = {"User-Agent": "Mozilla/5.0"}
        res_saylor = requests.get("https://saylortracker.com/", headers=headers, timeout=10)
        match_shares = re.search(r'Effective Diluted Shares.*?([\d,]+)', res_saylor.text, re.DOTALL)
        if match_shares: stats["shares"] = int(match_shares.group(1).replace(",", ""))
    except: pass
    return stats

# =========================
# 2. UI & Parameter Adjustment
# =========================
st.title("MSTR Diluted mNAV Dashboard")
live_stats = get_live_stats()

with st.expander("Core Calculation Parameters", expanded=False):
    c1, c2, c3 = st.columns(3)
    adj_shares = c1.number_input("Effective Diluted Shares", value=live_stats["shares"], step=100000)
    adj_btc = c2.number_input("Total BTC Holdings", value=live_stats["btc_holdings"], step=100)
    adj_net_debt = c3.number_input("Estimated Net Debt (USD)", value=6000000000, step=100000000)

# =========================
# 3. Data Processing (mNAV Calculation)
# =========================
btc_base = fetch_btc_coingecko_ohlc(days="90")
mstr_daily = fetch_mstr_stock()

if btc_base.empty or mstr_daily.empty:
    st.error("❌ Data Unavailable. Check API status or rate limits.")
    st.stop()

# Align BTC to Daily Close for MSTR
btc_daily = btc_base.copy()
btc_daily['date'] = btc_daily['date'].dt.normalize()
btc_daily = btc_daily.groupby('date').last().reset_index()

# Merge Data
df_combined = pd.merge(
    btc_daily[['date', 'close']].rename(columns={'close': 'BTC_price'}),
    mstr_daily[['date', 'close']].rename(columns={'close': 'MSTR_price'}),
    on='date', how='inner'
).set_index('date')

# Formula: (Market Cap + Net Debt) / Total BTC Value
df_combined["market_cap"] = adj_shares * df_combined["MSTR_price"]
df_combined["btc_value"] = adj_btc * df_combined["BTC_price"]
df_combined["diluted_mNAV"] = (df_combined["market_cap"] + adj_net_debt) / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["diluted_mNAV"] - 1) * 100

latest = df_combined.iloc[-1]

# =========================
# 4. Main Dashboard UI
# =========================

# --- Metrics Summary ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("BTC Price (CoinGecko)", f"${latest['BTC_price']:,.0f}")
m2.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
m3.metric("Diluted mNAV", f"{latest['diluted_mNAV']:.2f}x")
m4.metric("Premium %", f"{latest['Premium_%']:.2f}%")

st.divider()

# --- BTC Candlestick Chart ---
st.subheader("Bitcoin Price Action")
# Fixed segmented_control with label and options
selected_tf = st.segmented_control(
    label="Time Interval", 
    options=["Hour (3D)", "Day (3M)", "Week (1Y)"], 
    default="Day (3M)"
)

if selected_tf == "Hour (3D)":
    k_df = fetch_btc_coingecko_ohlc(days="7") 
elif selected_tf == "Day (3M)":
    k_df = fetch_btc_coingecko_ohlc(days="90")
else:
    k_df = fetch_btc_coingecko_ohlc(days="365")

if not k_df.empty:
    fig_k = go.Figure(data=[go.Candlestick(
        x=k_df['date'], open=k_df['open'], high=k_df['high'], low=k_df['low'], close=k_df['close']
    )])
    fig_k.update_layout(
        height=500, 
        margin=dict(t=0, b=0), 
        xaxis_rangeslider_visible=False, 
        template="plotly_dark"
    )
    st.plotly_chart(fig_k, use_container_width=True)

# --- mNAV Historical Trend ---
st.subheader("mNAV Premium/Discount Trend")
fig_nav = make_subplots(specs=[[{"secondary_y": True}]])
fig_nav.add_trace(go.Scatter(
    x=df_combined.index, y=df_combined["diluted_mNAV"], 
    name="mNAV Ratio", line=dict(color="gold", width=3)
), secondary_y=False)
fig_nav.add_trace(go.Scatter(
    x=df_combined.index, y=df_combined["BTC_price"], 
    name="BTC Price", line=dict(color="#9ac9EF")
), secondary_y=True)

fig_nav.update_layout(height=450, template="plotly_dark", hovermode="x unified")
fig_nav.update_yaxes(title_text="mNAV Multiple", secondary_y=False)
fig_nav.update_yaxes(title_text="BTC Price (USD)", secondary_y=True)
st.plotly_chart(fig_nav, use_container_width=True)

# --- Historical Database ---
st.subheader("Historical Data Logs")
df_display = df_combined.copy().sort_index(ascending=False)
df_display["BTC_price"] = df_display["BTC_price"].map("${:,.0f}".format)
df_display["MSTR_price"] = df_display["MSTR_price"].map("${:,.2f}".format)
df_display["diluted_mNAV"] = df_display["diluted_mNAV"].map("{:.2f}x".format)
df_display["Premium_%"] = df_display["Premium_%"].map("{:.2f}%".format)

# Rename columns for display
df_display = df_display.rename(columns={
    "BTC_price": "BTC Price",
    "MSTR_price": "MSTR Price",
    "diluted_mNAV": "mNAV Ratio",
    "Premium_%": "Premium %"
})

st.dataframe(
    df_display[['BTC Price', 'MSTR Price', 'mNAV Ratio', 'Premium %']].head(50), 
    use_container_width=True
)

st.caption(f"Last sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ")