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
st.set_page_config(page_title="MSTR & BTC Real-time Dashboard", layout="wide")
st_autorefresh(interval=60000, key="global_update") # 每分鐘自動整理

# OpenAI 初始化 (請確保已設定環境變數或在 Secrets 中配置)
client = OpenAI()

# =========================
# 1. 資料抓取函數 (防禦性設計)
# =========================
@st.cache_data(ttl=60)
def fetch_btc_klines(interval="1h", limit=500):
    """從 Binance 抓取 K 線數據，增加長度檢查"""
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        # 關鍵防護：檢查回傳的 JSON 是否為空列表
        if not data or len(data) == 0:
            st.warning(f"Binance 未回傳 {interval} 的數據。")
            return pd.DataFrame()
            
        df = pd.DataFrame(data, columns=["ot", "open", "high", "low", "close", "vol", "ct", "qv", "n", "tbb", "tbq", "i"])
        df["date"] = pd.to_datetime(df["ot"], unit="ms")
        df[["open", "high", "low", "close"]] = df[["open", "high", "low", "close"]].astype(float)
        return df
    except Exception as e:
        st.error(f"BTC 數據抓取失敗 ({interval}): {e}")
        return pd.DataFrame()
    
@st.cache_data(ttl=3600)
def fetch_mstr_stock():
    """從 Yahoo Finance 抓取 MSTR 數據，附帶頻率限制處理"""
    try:
        ticker = yf.Ticker("MSTR")
        df = ticker.history(period="2y", interval="1d")
        if df.empty:
            return pd.DataFrame()
        df.index = df.index.tz_localize(None)
        df = df.reset_index().rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
        return df
    except Exception as e:
        st.warning(f"MSTR 數據受限 (yfinance limit): {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_live_stats():
    """抓取 SaylorTracker 與 Bitbo 的即時參數"""
    stats = {"shares": 380000000, "btc_holdings": 252220}
    try:
        # 爬取持幣量
        res_bitbo = requests.get("https://bitbo.io/treasuries/microstrategy/", timeout=10)
        match_btc = re.search(r"([\d,]+)\s+bitcoins", res_bitbo.text, re.IGNORECASE)
        if match_btc:
            stats["btc_holdings"] = int(match_btc.group(1).replace(",", ""))
            
        # 爬取稀釋股數
        headers = {"User-Agent": "Mozilla/5.0"}
        res_saylor = requests.get("https://saylortracker.com/", headers=headers, timeout=10)
        match_shares = re.search(r'Effective Diluted Shares.*?([\d,]+)', res_saylor.text, re.DOTALL)
        if match_shares:
            stats["shares"] = int(match_shares.group(1).replace(",", ""))
    except:
        pass
    return stats

# =========================
# 2. 側邊欄與參數調整
# =========================
st.title("🚀 MSTR Diluted mNAV Dashboard")

live_stats = get_live_stats()

with st.expander("🛠️ 核心計算參數調整", expanded=False):
    c1, c2, c3 = st.columns(3)
    adj_shares = c1.number_input("稀釋後總股數", value=live_stats["shares"], step=100000)
    adj_btc = c2.number_input("BTC 總持量", value=live_stats["btc_holdings"], step=100)
    adj_net_debt = c3.number_input("淨債務 (USD)", value=6000000000, step=100000000) # 預估值

# =========================
# 3. 數據處理中心 (關鍵：防止 IndexError)
# =========================
# 獲取 BTC 數據 (預設日線用於計算)
btc_daily = fetch_btc_klines(interval="1d", limit=500)
mstr_daily = fetch_mstr_stock()

# 資料對齊檢查
if btc_daily.empty or mstr_daily.empty:
    st.error("❌ 無法取得市場數據。請稍後再試，或檢查 API 限制。")
    st.info("提示：Yahoo Finance 經常對 Streamlit Cloud 的 IP 進行頻率限制。")
    st.stop() # 強制停止，防止 iloc[-1] 崩潰

# 合併數據
df_combined = pd.merge(
    btc_daily[['date', 'close']].rename(columns={'close': 'BTC_price'}),
    mstr_daily[['date', 'close']].rename(columns={'close': 'MSTR_price'}),
    on='date', how='inner'
).set_index('date')

# 計算指標
df_combined["market_cap"] = adj_shares * df_combined["MSTR_price"]
df_combined["btc_value"] = adj_btc * df_combined["BTC_price"]
df_combined["diluted_mNAV"] = (df_combined["market_cap"] + adj_net_debt) / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["diluted_mNAV"] - 1) * 100

latest = df_combined.iloc[-1]

# =========================
# 4. 主要 UI 配置
# =========================

# --- 指標區 ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("BTC Price", f"${latest['BTC_price']:,.0f}")
m2.metric("MSTR Price", f"${latest['MSTR_price']:.2f}")
m3.metric("Diluted mNAV", f"{latest['diluted_mNAV']:.2f}x")
m4.metric("Premium %", f"{latest['Premium_%']:.2f}%")

# --- BTC K線圖 (動態尺度) ---
st.subheader("📊 Bitcoin 價格走勢")

# 建議將 segmented_control 放在一個變數中
selected_tf = st.segmented_control("時間尺度", ["小時 (3天)", "日 (3個月)", "週 (1年)"], default="日 (3個月)")

# 根據選擇抓取資料
if selected_tf == "小時 (3天)":
    k_df = fetch_btc_klines("1h", 72)
elif selected_tf == "日 (3個月)":
    k_df = fetch_btc_klines("1d", 90)
else:
    k_df = fetch_btc_klines("1w", 52)

# --- 關鍵修正：檢查 k_df 是否為空 ---
if k_df is not None and not k_df.empty:
    try:
        fig_k = go.Figure(data=[go.Candlestick(
            x=k_df['date'], 
            open=k_df['open'], 
            high=k_df['high'], 
            low=k_df['low'], 
            close=k_df['close']
        )])
        fig_k.update_layout(
            height=450, 
            margin=dict(t=0, b=0), 
            xaxis_rangeslider_visible=False, 
            template="plotly_dark"
        )
        st.plotly_chart(fig_k, use_container_width=True)
    except Exception as chart_err:
        st.error(f"繪圖時發生錯誤: {chart_err}")
else:
    st.info(f"暫時無法顯示 {selected_tf} 的 K 線數據，請切換其他尺度或稍後再試。")

# --- mNAV 歷史圖表 ---
st.subheader("📈 mNAV 溢價/折價歷史趨勢")
fig_nav = make_subplots(specs=[[{"secondary_y": True}]])
fig_nav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["diluted_mNAV"], name="mNAV Ratio", line=dict(color="gold", width=2)), secondary_y=False)
fig_nav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["BTC_price"], name="BTC Price (背景)", line=dict(color="rgba(255,255,255,0.1)")), secondary_y=True)
fig_nav.update_layout(height=400, template="plotly_dark", hovermode="x unified")
st.plotly_chart(fig_nav, use_container_width=True)

# --- AI 與 資料表格 ---
col_ai, col_data = st.columns([1, 1])

with col_ai:
    st.subheader("🤖 AI 策略分析")
    if st.button("啟動 AI 市場診斷"):
        with st.spinner("AI 正在分析數據..."):
            prompt = f"BTC: {latest['BTC_price']}, MSTR: {latest['MSTR_price']}, mNAV: {latest['diluted_mNAV']:.2f}. 分析當前 MSTR 相對於 BTC 的溢價狀況與投資情緒。"
            try:
                response = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": prompt}])
                st.info(response.choices[0].message.content)
            except Exception as e:
                st.error(f"AI 呼叫失敗: {e}")

with col_data:
    st.subheader("📋 歷史數據摘要")
    st.dataframe(
        df_combined[['BTC_price', 'MSTR_price', 'diluted_mNAV', 'Premium_%']]
        .sort_index(ascending=False).head(20), 
        use_container_width=True
    )