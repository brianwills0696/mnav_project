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
from openai import OpenAI

# =========================
# 0. Streamlit 基本設定
# =========================
st.set_page_config(page_title="MSTR & BTC Dashboard (CoinGecko)", layout="wide")
st_autorefresh(interval=60000, key="global_update") 

client = OpenAI()

# =========================
# 1. 資料抓取函數 (切換至 CoinGecko)
# =========================
@st.cache_data(ttl=300) # CoinGecko 免費版建議 TTL 設長一點
def fetch_btc_coingecko_ohlc(days="1"):
    """
    從 CoinGecko 抓取 OHLC 數據
    days: 1, 7, 14, 30, 90, 180, 365, max
    """
    # CoinGecko OHLC API
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/ohlc?vs_currency=usd&days={days}"
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 429:
            st.error("CoinGecko API 達到頻率限制 (Rate Limit)，請稍候再試。")
            return pd.DataFrame()
        res.raise_for_status()
        data = res.json()
        
        if not data:
            return pd.DataFrame()
            
        # CoinGecko 回傳格式: [timestamp, open, high, low, close]
        df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        st.error(f"CoinGecko 數據抓取失敗: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_mstr_stock():
    try:
        ticker = yf.Ticker("MSTR")
        df = ticker.history(period="2y", interval="1d")
        if df.empty: return pd.DataFrame()
        df.index = df.index.tz_localize(None)
        df = df.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
        return df
    except Exception as e:
        st.warning(f"MSTR 數據受限: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_live_stats():
    stats = {"shares": 380000000, "btc_holdings": 252220}
    try:
        # 爬取持幣量
        res_bitbo = requests.get("https://bitbo.io/treasuries/microstrategy/", timeout=10)
        match_btc = re.search(r"([\d,]+)\s+bitcoins", res_bitbo.text, re.IGNORECASE)
        if match_btc: stats["btc_holdings"] = int(match_btc.group(1).replace(",", ""))
        # 爬取稀釋股數
        headers = {"User-Agent": "Mozilla/5.0"}
        res_saylor = requests.get("https://saylortracker.com/", headers=headers, timeout=10)
        match_shares = re.search(r'Effective Diluted Shares.*?([\d,]+)', res_saylor.text, re.DOTALL)
        if match_shares: stats["shares"] = int(match_shares.group(1).replace(",", ""))
    except: pass
    return stats

# =========================
# 2. UI 介面與參數
# =========================
st.title("🚀 MSTR Diluted mNAV Dashboard")
live_stats = get_live_stats()

with st.expander("🛠️ 核心計算參數調整", expanded=False):
    c1, c2, c3 = st.columns(3)
    adj_shares = c1.number_input("稀釋後總股數", value=live_stats["shares"], step=100000)
    adj_btc = c2.number_input("BTC 總持量", value=live_stats["btc_holdings"], step=100)
    adj_net_debt = c3.number_input("淨債務 (USD)", value=6000000000, step=100000000)

# =========================
# 3. 數據處理 (計算 mNAV)
# =========================
# 使用 CoinGecko 90 天資料作為基準對齊 MSTR
btc_base = fetch_btc_coingecko_ohlc(days="90")
mstr_daily = fetch_mstr_stock()

if btc_base.empty or mstr_daily.empty:
    st.error("❌ 無法取得數據。請檢查 CoinGecko API 狀態或 yfinance 限制。")
    st.stop()

# 為了計算最新 mNAV，將 BTC 轉為日線對齊
btc_daily = btc_base.copy()
btc_daily['date'] = btc_daily['date'].dt.normalize()
btc_daily = btc_daily.groupby('date').last().reset_index()

df_combined = pd.merge(
    btc_daily[['date', 'close']].rename(columns={'close': 'BTC_price'}),
    mstr_daily[['date', 'close']].rename(columns={'close': 'MSTR_price'}),
    on='date', how='inner'
).set_index('date')

df_combined["market_cap"] = adj_shares * df_combined["MSTR_price"]
df_combined["btc_value"] = adj_btc * df_combined["BTC_price"]
df_combined["diluted_mNAV"] = (df_combined["market_cap"] + adj_net_debt) / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["diluted_mNAV"] - 1) * 100

latest = df_combined.iloc[-1]

# =========================
# 4. 主要 UI 配置
# =========================
m1, m2, m3, m4 = st.columns(4)
m1.metric("BTC Price (CG)", f"${latest['BTC_price']:,.0f}")
m2.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
m3.metric("Diluted mNAV", f"{latest['diluted_mNAV']:.2f}x")
m4.metric("Premium %", f"{latest['Premium_%']:.2f}%")

# --- BTC K線圖 ---
st.subheader("📊 Bitcoin 價格走勢 (CoinGecko)")
selected_tf = st.segmented_control("時間尺度", ["小時 (3天)", "日 (3個月)", "週 (1年)"], default="日 (3個月)")

# CoinGecko 的 days 參數映射
if selected_tf == "小時 (3天)":
    k_df = fetch_btc_coingecko_ohlc(days="7") # 7天內會提供較細的顆粒度
elif selected_tf == "日 (3個月)":
    k_df = fetch_btc_coingecko_ohlc(days="90")
else:
    k_df = fetch_btc_coingecko_ohlc(days="365")

if not k_df.empty:
    fig_k = go.Figure(data=[go.Candlestick(
        x=k_df['date'], open=k_df['open'], high=k_df['high'], low=k_df['low'], close=k_df['close']
    )])
    fig_k.update_layout(height=450, margin=dict(t=0, b=0), xaxis_rangeslider_visible=False, template="plotly_dark")
    st.plotly_chart(fig_k, use_container_width=True)

# --- mNAV 圖表 ---
st.subheader("📈 mNAV 溢價歷史趨勢")
fig_nav = make_subplots(specs=[[{"secondary_y": True}]])
fig_nav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["diluted_mNAV"], name="mNAV Ratio", line=dict(color="gold", width=2)), secondary_y=False)
fig_nav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["BTC_price"], name="BTC Price", line=dict(color="rgba(255,255,255,0.1)")), secondary_y=True)
fig_nav.update_layout(height=400, template="plotly_dark", hovermode="x unified")
st.plotly_chart(fig_nav, use_container_width=True)

# --- AI 與 表格 ---
col_ai, col_data = st.columns([1, 1])
with col_ai:
    st.subheader("🤖 AI 策略分析")
    if st.button("啟動 AI 市場診斷"):
        with st.spinner("Analyzing..."):
            prompt = f"BTC: {latest['BTC_price']}, mNAV: {latest['diluted_mNAV']:.2f}. 分析溢價狀況。"
            try:
                response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.info(response.choices[0].message.content)
            except Exception as e: st.error(f"AI 呼叫失敗: {e}")

with col_data:
    st.subheader("📋 歷史數據摘要")
    st.dataframe(df_combined.sort_index(ascending=False).head(20), use_container_width=True)