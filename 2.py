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
# 0. Streamlit 設定與自動整理
# =========================
st.set_page_config(page_title="MSTR Diluted mNAV Dashboard Pro", layout="wide")
# 每 60 秒自動重新整理一次介面 (副函式功能)
st_autorefresh(interval=60000, key="global_update")

# 初始化 OpenAI (若有 API Key 請確保環境變數已設定)
client = OpenAI()

# =========================
# 1. 資料抓取函數 (整合爬蟲與 yfinance)
# =========================

@st.cache_data(ttl=3600)
def get_btc_data():
    # 使用 Binance API 獲取更精細的數據 (副函式優點)
    url = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000"
    try:
        data = requests.get(url, timeout=10).json()
        df = pd.DataFrame(data, columns=["ot", "open", "high", "low", "close", "vol", "ct", "qv", "n", "tbb", "tbq", "i"])
        df["date"] = pd.to_datetime(df["ot"], unit="ms")
        df[["open", "high", "low", "close", "vol"]] = df[["open", "high", "low", "close", "vol"]].astype(float)
        return df
    except:
        # 備援機制
        return pd.DataFrame()

@st.cache_data(ttl=86400)
def get_mstr_data():
    ticker = yf.Ticker("MSTR")
    hist = ticker.history(period="2y", interval="1d")
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
        match = re.search(r"([\d,]+)\s+bitcoins", soup.get_text(), re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    except:
        pass
    return 252220

# AI 分析函數 (整合自副函式)
def generate_ai_summary(df):
    latest = df.iloc[-1]
    prompt = f"""
    You are a professional macro and crypto equity analyst.
    Current BTC Price: ${latest['BTC_price']:,.2f}
    MSTR Price: ${latest['MSTR_price']:,.2f}
    Current Diluted mNAV: {latest['diluted_mNAV']:.2f}x
    Premium/Discount: {latest['Premium_%']:.2f}%

    Please provide:
    1. Trend analysis
    2. mNAV valuation perspective
    3. Short-term market insight
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o", # 修正為可用模型
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI Analysis currently unavailable: {str(e)}"

# =========================
# 2. 頁面頂端：參數調整區
# =========================
st.title("🚀 MSTR Diluted mNAV Dashboard")

# 預抓數據作為預設值
default_shares = get_effective_diluted_shares()
default_btc = get_mstr_btc_holdings()

with st.expander("🛠️ 核心計算參數調整 (點擊展開)", expanded=True):
    col_input1, col_input2, col_input3 = st.columns(3)
    with col_input1:
        adj_diluted_shares = st.number_input("Diluted Shares (稀釋後總股數)", value=default_shares, step=100000)
    with col_input2:
        adj_btc_holdings = st.number_input("BTC Holdings (MSTR 總持幣量)", value=default_btc, step=100)
    with col_input3:
        # 整合副函式的財務負擔概念
        net_debt = st.number_input("Net Debt (債務-現金, USD)", value=8254000000 - 2250000000, step=100000000)

st.divider()

# =========================
# 3. 數據計算
# =========================
btc_raw = get_btc_data()
mstr_raw = get_mstr_data()

# 資料對齊
btc_close = btc_raw.set_index("date")["close"]
df_combined = pd.DataFrame({
    "BTC_price": btc_close,
    "MSTR_price": mstr_raw["Close"]
}).ffill().dropna()

# 計算 Diluted mNAV (整合主函式的公式與副函式的財務結構)
# 公式：(市值 + 淨債務) / (比特幣持倉 * 比特幣價格)
df_combined["market_cap"] = adj_diluted_shares * df_combined["MSTR_price"]
df_combined["btc_value"] = adj_btc_holdings * df_combined["BTC_price"]
df_combined["diluted_mNAV"] = (df_combined["market_cap"] + net_debt) / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["diluted_mNAV"] - 1) * 100

latest = df_combined.iloc[-1]

# =========================
# 4. 關鍵指標看板
# =========================
m1, m2, m3, m4 = st.columns(4)
m1.metric("BTC Price", f"${latest['BTC_price']:,.0f}")
m2.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
m3.metric("Diluted mNAV", f"{latest['diluted_mNAV']:.2f}x")
m4.metric("Premium %", f"{latest['Premium_%']:.2f}%")

m5, m6, m7, m8 = st.columns(4)
m5.metric("Net Debt Applied", f"${net_debt/1e9:.2f}B")
m6.metric("BTC Holdings", f"{adj_btc_holdings:,.0f}")
m7.metric("BTC per Share", f"{(adj_btc_holdings / adj_diluted_shares):.6f}")
m8.metric("MSTR Market Cap", f"${(df_combined['market_cap'].iloc[-1])/1e9:.2f}B")

# =========================
# 5. 視覺化圖表
# =========================
# 圖表 A: BTC K線圖 (整合副函式繪圖邏輯)
st.subheader("📊 Bitcoin Price Action (1H)")
fig_btc = go.Figure(data=[go.Candlestick(
    x=btc_raw['date'], open=btc_raw['open'], high=btc_raw['high'], low=btc_raw['low'], close=btc_raw['close']
)])
fig_btc.update_layout(height=400, margin=dict(t=0, b=0), xaxis_rangeslider_visible=False)
st.plotly_chart(fig_btc, use_container_width=True)

# 圖表 B: mNAV 趨勢與價格相關性
st.subheader("📈 mNAV Valuation & Correlation")
fig_dual = make_subplots(specs=[[{"secondary_y": True}]])
fig_dual.add_trace(go.Scatter(x=df_combined.index, y=df_combined["diluted_mNAV"], name="mNAV Ratio", line=dict(color="gold", width=3)), secondary_y=False)
fig_dual.add_trace(go.Scatter(x=df_combined.index, y=df_combined["BTC_price"], name="BTC Price", line=dict(color="blue")), secondary_y=True)
fig_dual.update_layout(hovermode="x unified", height=400)
st.plotly_chart(fig_dual, use_container_width=True)

# =========================
# 6. AI 分析與歷史資料
# =========================
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("🤖 AI Market Insight")
    if st.button("Generate AI Analysis"):
        with st.spinner("Analyzing market data..."):
            insight = generate_ai_summary(df_combined)
            st.info(insight)

with col_right:
    st.subheader("📜 Recent History")
    df_display = df_combined.sort_index(ascending=False).head(10).copy()
    st.dataframe(df_display[["BTC_price", "MSTR_price", "diluted_mNAV", "Premium_%"]], use_container_width=True)

st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | Data source: Binance, Yahoo Finance, Bitbo")