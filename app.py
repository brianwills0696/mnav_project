
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

def generate_ai_summary(df_combined):
    latest = df_combined.iloc[-1]

    prompt = f"""
You are a professional macro and crypto equity analyst.

Here is the latest data:

BTC Price: {latest['BTC_price']:.2f}
MSTR Price: {latest['MSTR_price']:.2f}
mNAV: {latest['mNAV']:.2f}

Recent Trend:
- BTC change (last 24h): {(df_combined['BTC_price'].iloc[-1] / df_combined['BTC_price'].iloc[-24] - 1)*100:.2f}%
- MSTR change (last 24h): {(df_combined['MSTR_price'].iloc[-1] / df_combined['MSTR_price'].iloc[-24] - 1)*100:.2f}%

Tasks:
1. Identify trend (bullish / bearish / neutral)
2. Evaluate if mNAV is overvalued or undervalued
3. Provide a short investment interpretation

Keep it concise and professional.
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content

# =========================
# 0. 自動更新與頁面設定
# =========================
st_autorefresh(interval=5000, key="global_update")
st.set_page_config(page_title="BTC & MSTR Pro Terminal", layout="wide")

# =========================
# 1. 工具函式：動態 Y 軸計算
# =========================
def get_y_range(df, start, end, padding=0.05):
    """計算指定時間區間內的最高與最低價，並回傳 Y 軸範圍"""
    mask = (df['date'] >= start) & (df['date'] <= end)
    df_filtered = df.loc[mask]
    if df_filtered.empty:
        return [None, None]
    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]

# =========================
# 2. 資料抓取函式
# =========================
@st.cache_data(ttl=2)
def fetch_btc_realtime_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        res = requests.get(url, timeout=2)
        return float(res.json()['price'])
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
# 3. 狀態管理 (即時數據與 Max/Min)
# =========================
if "ai_summary" not in st.session_state:
    st.session_state.ai_summary = None
    st.session_state.ai_generated = False

if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=["time", "price"])
if 'price_max' not in st.session_state:
    st.session_state.price_max = None
if 'price_min' not in st.session_state:
    st.session_state.price_min = None

current_p = fetch_btc_realtime_price()

if current_p:
    # 更新歷史紀錄
    new_entry = pd.DataFrame({"time": [datetime.now()], "price": [current_p]})
    st.session_state.price_history = pd.concat([st.session_state.price_history, new_entry], ignore_index=True).tail(50)
    
    # 更新 Max / Min
    if st.session_state.price_max is None:
        st.session_state.price_max = current_p
        st.session_state.price_min = current_p
    else:
        st.session_state.price_max = max(st.session_state.price_max, current_p)
        st.session_state.price_min = min(st.session_state.price_min, current_p)

# =========================
# 4. 執行數據分析
# =========================
btc_h = fetch_btc_binance("1h", 1000)
btc_d = fetch_btc_binance("1d", 400)
btc_w = fetch_btc_binance("1w", 100)

mstr_data_h, shares_dynamic = fetch_mstr_yf("2y", "1h")
mstr_data_d, _ = fetch_mstr_yf("2y", "1d")
mstr_data_w, _ = fetch_mstr_yf("5y", "1wk")
BTC_HOLDINGS = get_mstr_btc_holdings()
# ✅ 財務參數調整區 (原 sidebar 內容)
# st.write("### ⚙️ 財務參數調整")
# p_col1, p_col2, p_col3, p_col4 = st.columns(4)
# st.write("### ⚙️ 財務參數調整")
# p_col1, p_col2, p_col3, p_col4 = st.columns(4)
# adj_shares = p_col1.number_input("發行股數", value=shares_dynamic)
# DEBT = p_col2.number_input("總負債 (USD)", value=8254 * 1e6, step=1e8)
# PREF = p_col3.number_input("優先股 (USD)", value=10006 * 1e6, step=1e8)
# CASH = p_col4.number_input("現金 (USD)", value=2250 * 1e6, step=1e8)
adj_shares = shares_dynamic
DEBT = 8254 * 1e6
PREF = 10006 * 1e6
CASH = 2250 * 1e6
# mNAV 計算 (週末自動填充)
btc_hourly_idx = btc_h.set_index("date")["close"]
mstr_hourly_idx = mstr_data_h.set_index("date")["close"]
df_combined = pd.DataFrame({"BTC_price": btc_hourly_idx, "MSTR_price": mstr_hourly_idx}).ffill().bfill()
df_combined["market_cap"] = df_combined["MSTR_price"] * adj_shares
df_combined["btc_value"] = df_combined["BTC_price"] * BTC_HOLDINGS
df_combined["EV"] = (df_combined["market_cap"] + DEBT + PREF - CASH)
df_combined["mNAV"] = df_combined["EV"] / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["mNAV"] - 1) * 100

update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =========================
# 5. 圖表生成邏輯 (升級動態 Y 軸)
# =========================
def get_y_range(df, start, end, padding=0.05):
    mask = (df['date'] >= start) & (df['date'] <= end)
    df_filtered = df.loc[mask]
    if df_filtered.empty: return [None, None]
    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]

def create_interactive_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()
    h_s, d_s, w_s = now-timedelta(days=3), now-timedelta(days=60), now-timedelta(days=365)

    fig.add_trace(go.Candlestick(x=df_h['date'], open=df_h['open'], high=df_h['high'], low=df_h['low'], close=df_h['close'], name=label))
    
    fig.update_layout(
        updatemenus=[dict(type="buttons", direction="right", active=0, x=0, y=1.15,
            buttons=[
                dict(label="Hourly", method="update", args=[
                    {"x":[df_h.date], "open":[df_h.open], "high":[df_h.high], "low":[df_h.low], "close":[df_h.close]},
                    {"xaxis":{"range":[h_s, now]}, "yaxis":{"range": get_y_range(df_h, h_s, now)}}
                ]),
                dict(label="Daily", method="update", args=[
                    {"x":[df_d.date], "open":[df_d.open], "high":[df_d.high], "low":[df_d.low], "close":[df_d.close]},
                    {"xaxis":{"range":[d_s, now]}, "yaxis":{"range": get_y_range(df_d, d_s, now)}}
                ]),
                dict(label="Weekly", method="update", args=[
                    {"x":[df_w.date], "open":[df_w.open], "high":[df_w.high], "low":[df_w.low], "close":[df_w.close]},
                    {"xaxis":{"range":[w_s, now]}, "yaxis":{"range": get_y_range(df_w, w_s, now)}}
                ]),
            ]
        )],
        xaxis=dict(range=[h_s, now], rangeslider_visible=False, constrain="domain"),
        yaxis=dict(fixedrange=False, tickformat=",.0f"),
        height=500, margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified"
    )
    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            active=0,
            x=0,
            y=1.15,
            buttons=[
                dict(label="Hourly", method="update", args=[
                    {"x": [df_h['date']], "open": [df_h['open']], "high": [df_h['high']], "low": [df_h['low']], "close": [df_h['close']]},
                    {"xaxis": {"type": "category"}} # 強制轉為類別軸
                ]),
                dict(label="Daily", method="update", args=[
                    {"x": [df_d['date']], "open": [df_d['open']], "high": [df_d['high']], "low": [df_d['low']], "close": [df_d['close']]},
                    {"xaxis": {"type": "category"}}
                ]),
                dict(label="Weekly", method="update", args=[
                    {"x": [df_w['date']], "open": [df_w['open']], "high": [df_w['high']], "low": [df_w['low']], "close": [df_w['close']]},
                    {"xaxis": {"type": "category"}}
                ]),
            ]
        )],
        xaxis=dict(
            type="category",        # ✅ 關鍵：設定為類別軸
            categoryorder="category ascending", # 依照日期排序
            rangeslider_visible=False,
            showticklabels=True,
            nticks=10               # 限制標籤數量，避免字擠在一起
        ),
        yaxis=dict(
            autorange=True,         # ✅ 在類別軸模式下，建議讓 Y 軸自動縮放
            fixedrange=False,
            tickformat=",.0f"
        ),
        height=600,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified"
    )

    return fig

def create_interactive_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()

    # 定義三個時間尺度的起始點
    h_s = now - timedelta(days=3)
    d_s = now - timedelta(days=60)
    w_s = now - timedelta(days=365)

    # 1. 初始資料與軌跡 (預設顯示 Hourly)
    fig.add_trace(go.Candlestick(
        x=df_h['date'], 
        open=df_h['open'], high=df_h['high'], 
        low=df_h['low'], close=df_h['close'], 
        name=label
    ))

    # 2. 設定按鈕：關鍵在於同時更新 xaxis 和 yaxis
    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            active=0,
            x=0,
            y=1.15,
            buttons=[
                # --- Hourly 按鈕 ---
                dict(label="Hourly", method="update", args=[
                    # 更新數據內容
                    {"x": [df_h.date], "open": [df_h.open], "high": [df_h.high], "low": [df_h.low], "close": [df_h.close]},
                    # 更新座標軸範圍：重點在 yaxis 的 range 呼叫了 get_y_range
                    {
                        "xaxis": {"range": [h_s, now], "rangeslider": {"visible": False}},
                        "yaxis": {"range": get_y_range(df_h, h_s, now), "fixedrange": False}
                    }
                ]),
                # --- Daily 按鈕 ---
                dict(label="Daily", method="update", args=[
                    {"x": [df_d.date], "open": [df_d.open], "high": [df_d.high], "low": [df_d.low], "close": [df_d.close]},
                    {
                        "xaxis": {"range": [d_s, now], "rangeslider": {"visible": False}}, # 這裡的 d_start 建議改用外部傳入或統一變數名
                        "yaxis": {"range": get_y_range(df_d, d_s, now), "fixedrange": False}
                    }
                ]),
                # --- Weekly 按鈕 ---
                dict(label="Weekly", method="update", args=[
                    {"x": [df_w.date], "open": [df_w.open], "high": [df_w.high], "low": [df_w.low], "close": [df_w.close]},
                    {
                        "xaxis": {"range": [w_s, now], "rangeslider": {"visible": False}},
                        "yaxis": {"range": get_y_range(df_w, w_s, now), "fixedrange": False}
                    }
                ]),
            ]
        )],
        # 初始佈局設定
        xaxis=dict(range=[h_s, now], rangeslider_visible=False, constrain="domain"),
        yaxis=dict(
            range=get_y_range(df_h, h_s, now), # 初始 Y 軸也必須設定，否則第一眼會很扁
            fixedrange=False, 
            tickformat=",.0f",
            zeroline=False
        ),
        height=600,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified"
    )

    # 針對 MSTR 排除非交易時段
    if is_stock:
        fig.update_xaxes(rangebreaks=[
            dict(bounds=["sat", "sun"]), 
            dict(bounds=[16, 9.5], pattern="hour")
        ])

    return fig

# =========================
# 6. UI 排版
# =========================
st.title("₿ BTC & MSTR Dashboard")

# --- 1. BTC K線 ---
st.subheader("1. BTC Price")
st.plotly_chart(create_interactive_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

# --- 2. BTC 即時折線圖 ---
st.subheader("BTC Real-time Trend")
if not st.session_state.price_history.empty:
    fig_spot = go.Figure()
    fig_spot.add_trace(go.Scatter(
        x=st.session_state.price_history["time"], 
        y=st.session_state.price_history["price"],
        mode='lines+markers', 
        line=dict(color='#02d495', width=3),  # 這裡補上逗號
        fill='tozeroy',                      # 移除重複的 fill
        fillcolor='rgba(2, 212, 149, 0.2)'    # 將顏色改為透明度 0.2 的綠色，視覺效果更好
    ))
    # 使用緩衝追蹤 Max/Min
    buffer = (st.session_state.price_max - st.session_state.price_min) * 0.1
    fig_spot.update_layout(
        yaxis=dict(range=[st.session_state.price_min - buffer, st.session_state.price_max + buffer], tickformat=",.2f", side="right"),
        xaxis=dict(rangeslider_visible=False), height=350, margin=dict(t=10, b=10)
    )
    st.plotly_chart(fig_spot, use_container_width=True)
    st.write(f"**Session High:** {st.session_state.price_max:,.2f} | **Session Low:** {st.session_state.price_min:,.2f}")

# 指標
bt_c1, bt_c2, bt_c3 = st.columns(3)
bt_c1.metric("Current Price", f"${current_p:,.2f}" if current_p else "Loading...")
bt_c2.metric("24h High", f"${btc_h.iloc[-24:]['high'].max():,.2f}")
bt_c3.metric("24h Volume", f"{btc_h.iloc[-24:]['vol'].sum():,.0f} BTC")

# --- 3. BTC 表格 ---
# st.subheader("2. BTC Hourly Data")
# st.dataframe(btc_h.sort_values("date", ascending=False).head(10)[["date", "close", "vol"]], use_container_width=True)

# --- 4. MSTR K線 ---
st.markdown("---")
st.subheader("3. MSTR Stock Price")
st.plotly_chart(create_interactive_chart(mstr_data_h, mstr_data_d, mstr_data_w, "MSTR", is_stock=True), use_container_width=True)

# --- 5. mNAV 走勢圖 ---
st.markdown("---")
st.subheader("4. MSTR mNAV")


fig_mnav = go.Figure()
fig_mnav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["mNAV"], line=dict(color='orange', width=2)))
fig_mnav.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(rangeslider_visible=False, constrain="domain"))
st.plotly_chart(fig_mnav, use_container_width=True)

st.markdown("---")
st.subheader("🤖 AI Market Insight")

if st.button("Generate AI Analysis", key="ai_btn"):
    if not st.session_state.ai_generated:
        with st.spinner("Analyzing market..."):
            st.session_state.ai_summary = generate_ai_summary(df_combined)
            st.session_state.ai_generated = True

if st.session_state.ai_summary:
    st.info(st.session_state.ai_summary)

# --- 6. 詳細資料 ---
# st.subheader("5. Detailed Analysis")
# st.dataframe(df_combined.sort_index(ascending=False).head(20), use_container_width=True)

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

def generate_ai_summary(df_combined):
    latest = df_combined.iloc[-1]

    prompt = f"""
You are a professional macro and crypto equity analyst.

Here is the latest data:

BTC Price: {latest['BTC_price']:.2f}
MSTR Price: {latest['MSTR_price']:.2f}
mNAV: {latest['mNAV']:.2f}

Recent Trend:
- BTC change (last 24h): {(df_combined['BTC_price'].iloc[-1] / df_combined['BTC_price'].iloc[-24] - 1)*100:.2f}%
- MSTR change (last 24h): {(df_combined['MSTR_price'].iloc[-1] / df_combined['MSTR_price'].iloc[-24] - 1)*100:.2f}%

Tasks:
1. Identify trend (bullish / bearish / neutral)
2. Evaluate if mNAV is overvalued or undervalued
3. Provide a short investment interpretation

Keep it concise and professional.
"""

    response = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.choices[0].message.content

# =========================
# 0. 自動更新與頁面設定
# =========================
st_autorefresh(interval=5000, key="global_update")
st.set_page_config(page_title="BTC & MSTR Pro Terminal", layout="wide")

# =========================
# 1. 工具函式：動態 Y 軸計算
# =========================
def get_y_range(df, start, end, padding=0.05):
    """計算指定時間區間內的最高與最低價，並回傳 Y 軸範圍"""
    mask = (df['date'] >= start) & (df['date'] <= end)
    df_filtered = df.loc[mask]
    if df_filtered.empty:
        return [None, None]
    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]

# =========================
# 2. 資料抓取函式
# =========================
@st.cache_data(ttl=2)
def fetch_btc_realtime_price():
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        res = requests.get(url, timeout=2)
        return float(res.json()['price'])
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
# 3. 狀態管理 (即時數據與 Max/Min)
# =========================
if "ai_summary" not in st.session_state:
    st.session_state.ai_summary = None
    st.session_state.ai_generated = False

if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=["time", "price"])
if 'price_max' not in st.session_state:
    st.session_state.price_max = None
if 'price_min' not in st.session_state:
    st.session_state.price_min = None

current_p = fetch_btc_realtime_price()

if current_p:
    # 更新歷史紀錄
    new_entry = pd.DataFrame({"time": [datetime.now()], "price": [current_p]})
    st.session_state.price_history = pd.concat([st.session_state.price_history, new_entry], ignore_index=True).tail(50)
    
    # 更新 Max / Min
    if st.session_state.price_max is None:
        st.session_state.price_max = current_p
        st.session_state.price_min = current_p
    else:
        st.session_state.price_max = max(st.session_state.price_max, current_p)
        st.session_state.price_min = min(st.session_state.price_min, current_p)

# =========================
# 4. 執行數據分析
# =========================
btc_h = fetch_btc_binance("1h", 1000)
btc_d = fetch_btc_binance("1d", 400)
btc_w = fetch_btc_binance("1w", 100)

mstr_data_h, shares_dynamic = fetch_mstr_yf("2y", "1h")
mstr_data_d, _ = fetch_mstr_yf("2y", "1d")
mstr_data_w, _ = fetch_mstr_yf("5y", "1wk")
BTC_HOLDINGS = get_mstr_btc_holdings()
# ✅ 財務參數調整區 (原 sidebar 內容)
# st.write("### ⚙️ 財務參數調整")
# p_col1, p_col2, p_col3, p_col4 = st.columns(4)
# st.write("### ⚙️ 財務參數調整")
# p_col1, p_col2, p_col3, p_col4 = st.columns(4)
# adj_shares = p_col1.number_input("發行股數", value=shares_dynamic)
# DEBT = p_col2.number_input("總負債 (USD)", value=8254 * 1e6, step=1e8)
# PREF = p_col3.number_input("優先股 (USD)", value=10006 * 1e6, step=1e8)
# CASH = p_col4.number_input("現金 (USD)", value=2250 * 1e6, step=1e8)
adj_shares = shares_dynamic
DEBT = 8254 * 1e6
PREF = 10006 * 1e6
CASH = 2250 * 1e6
# mNAV 計算 (週末自動填充)
btc_hourly_idx = btc_h.set_index("date")["close"]
mstr_hourly_idx = mstr_data_h.set_index("date")["close"]
df_combined = pd.DataFrame({"BTC_price": btc_hourly_idx, "MSTR_price": mstr_hourly_idx}).ffill().bfill()
df_combined["market_cap"] = df_combined["MSTR_price"] * adj_shares
df_combined["btc_value"] = df_combined["BTC_price"] * BTC_HOLDINGS
df_combined["EV"] = (df_combined["market_cap"] + DEBT + PREF - CASH)
df_combined["mNAV"] = df_combined["EV"] / df_combined["btc_value"]
df_combined["Premium_%"] = (df_combined["mNAV"] - 1) * 100

update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# =========================
# 5. 圖表生成邏輯 (升級動態 Y 軸)
# =========================
def get_y_range(df, start, end, padding=0.05):
    mask = (df['date'] >= start) & (df['date'] <= end)
    df_filtered = df.loc[mask]
    if df_filtered.empty: return [None, None]
    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]

def create_interactive_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()
    h_s, d_s, w_s = now-timedelta(days=3), now-timedelta(days=60), now-timedelta(days=365)

    fig.add_trace(go.Candlestick(x=df_h['date'], open=df_h['open'], high=df_h['high'], low=df_h['low'], close=df_h['close'], name=label))
    
    fig.update_layout(
        updatemenus=[dict(type="buttons", direction="right", active=0, x=0, y=1.15,
            buttons=[
                dict(label="Hourly", method="update", args=[
                    {"x":[df_h.date], "open":[df_h.open], "high":[df_h.high], "low":[df_h.low], "close":[df_h.close]},
                    {"xaxis":{"range":[h_s, now]}, "yaxis":{"range": get_y_range(df_h, h_s, now)}}
                ]),
                dict(label="Daily", method="update", args=[
                    {"x":[df_d.date], "open":[df_d.open], "high":[df_d.high], "low":[df_d.low], "close":[df_d.close]},
                    {"xaxis":{"range":[d_s, now]}, "yaxis":{"range": get_y_range(df_d, d_s, now)}}
                ]),
                dict(label="Weekly", method="update", args=[
                    {"x":[df_w.date], "open":[df_w.open], "high":[df_w.high], "low":[df_w.low], "close":[df_w.close]},
                    {"xaxis":{"range":[w_s, now]}, "yaxis":{"range": get_y_range(df_w, w_s, now)}}
                ]),
            ]
        )],
        xaxis=dict(range=[h_s, now], rangeslider_visible=False, constrain="domain"),
        yaxis=dict(fixedrange=False, tickformat=",.0f"),
        height=500, margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified"
    )
    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            active=0,
            x=0,
            y=1.15,
            buttons=[
                dict(label="Hourly", method="update", args=[
                    {"x": [df_h['date']], "open": [df_h['open']], "high": [df_h['high']], "low": [df_h['low']], "close": [df_h['close']]},
                    {"xaxis": {"type": "category"}} # 強制轉為類別軸
                ]),
                dict(label="Daily", method="update", args=[
                    {"x": [df_d['date']], "open": [df_d['open']], "high": [df_d['high']], "low": [df_d['low']], "close": [df_d['close']]},
                    {"xaxis": {"type": "category"}}
                ]),
                dict(label="Weekly", method="update", args=[
                    {"x": [df_w['date']], "open": [df_w['open']], "high": [df_w['high']], "low": [df_w['low']], "close": [df_w['close']]},
                    {"xaxis": {"type": "category"}}
                ]),
            ]
        )],
        xaxis=dict(
            type="category",        # ✅ 關鍵：設定為類別軸
            categoryorder="category ascending", # 依照日期排序
            rangeslider_visible=False,
            showticklabels=True,
            nticks=10               # 限制標籤數量，避免字擠在一起
        ),
        yaxis=dict(
            autorange=True,         # ✅ 在類別軸模式下，建議讓 Y 軸自動縮放
            fixedrange=False,
            tickformat=",.0f"
        ),
        height=600,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified"
    )

    return fig

def create_interactive_chart(df_h, df_d, df_w, label, is_stock=False):
    fig = go.Figure()
    now = df_h['date'].max()

    # 定義三個時間尺度的起始點
    h_s = now - timedelta(days=3)
    d_s = now - timedelta(days=60)
    w_s = now - timedelta(days=365)

    # 1. 初始資料與軌跡 (預設顯示 Hourly)
    fig.add_trace(go.Candlestick(
        x=df_h['date'], 
        open=df_h['open'], high=df_h['high'], 
        low=df_h['low'], close=df_h['close'], 
        name=label
    ))

    # 2. 設定按鈕：關鍵在於同時更新 xaxis 和 yaxis
    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            active=0,
            x=0,
            y=1.15,
            buttons=[
                # --- Hourly 按鈕 ---
                dict(label="Hourly", method="update", args=[
                    # 更新數據內容
                    {"x": [df_h.date], "open": [df_h.open], "high": [df_h.high], "low": [df_h.low], "close": [df_h.close]},
                    # 更新座標軸範圍：重點在 yaxis 的 range 呼叫了 get_y_range
                    {
                        "xaxis": {"range": [h_s, now], "rangeslider": {"visible": False}},
                        "yaxis": {"range": get_y_range(df_h, h_s, now), "fixedrange": False}
                    }
                ]),
                # --- Daily 按鈕 ---
                dict(label="Daily", method="update", args=[
                    {"x": [df_d.date], "open": [df_d.open], "high": [df_d.high], "low": [df_d.low], "close": [df_d.close]},
                    {
                        "xaxis": {"range": [d_s, now], "rangeslider": {"visible": False}}, # 這裡的 d_start 建議改用外部傳入或統一變數名
                        "yaxis": {"range": get_y_range(df_d, d_s, now), "fixedrange": False}
                    }
                ]),
                # --- Weekly 按鈕 ---
                dict(label="Weekly", method="update", args=[
                    {"x": [df_w.date], "open": [df_w.open], "high": [df_w.high], "low": [df_w.low], "close": [df_w.close]},
                    {
                        "xaxis": {"range": [w_s, now], "rangeslider": {"visible": False}},
                        "yaxis": {"range": get_y_range(df_w, w_s, now), "fixedrange": False}
                    }
                ]),
            ]
        )],
        # 初始佈局設定
        xaxis=dict(range=[h_s, now], rangeslider_visible=False, constrain="domain"),
        yaxis=dict(
            range=get_y_range(df_h, h_s, now), # 初始 Y 軸也必須設定，否則第一眼會很扁
            fixedrange=False, 
            tickformat=",.0f",
            zeroline=False
        ),
        height=600,
        margin=dict(l=10, r=10, t=50, b=10),
        hovermode="x unified"
    )

    # 針對 MSTR 排除非交易時段
    if is_stock:
        fig.update_xaxes(rangebreaks=[
            dict(bounds=["sat", "sun"]), 
            dict(bounds=[16, 9.5], pattern="hour")
        ])

    return fig

# =========================
# 6. UI 排版
# =========================
st.title("₿ BTC & MSTR Dashboard")

# --- 1. BTC K線 ---
st.subheader("1. BTC Price")
st.plotly_chart(create_interactive_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

# --- 2. BTC 即時折線圖 ---
st.subheader("BTC Real-time Trend")
if not st.session_state.price_history.empty:
    fig_spot = go.Figure()
    fig_spot.add_trace(go.Scatter(
        x=st.session_state.price_history["time"], 
        y=st.session_state.price_history["price"],
        mode='lines+markers', 
        line=dict(color='#02d495', width=3),  # 這裡補上逗號
        fill='tozeroy',                      # 移除重複的 fill
        fillcolor='rgba(2, 212, 149, 0.2)'    # 將顏色改為透明度 0.2 的綠色，視覺效果更好
    ))
    # 使用緩衝追蹤 Max/Min
    buffer = (st.session_state.price_max - st.session_state.price_min) * 0.1
    fig_spot.update_layout(
        yaxis=dict(range=[st.session_state.price_min - buffer, st.session_state.price_max + buffer], tickformat=",.2f", side="right"),
        xaxis=dict(rangeslider_visible=False), height=350, margin=dict(t=10, b=10)
    )
    st.plotly_chart(fig_spot, use_container_width=True)
    st.write(f"**Session High:** {st.session_state.price_max:,.2f} | **Session Low:** {st.session_state.price_min:,.2f}")

# 指標
bt_c1, bt_c2, bt_c3 = st.columns(3)
bt_c1.metric("Current Price", f"${current_p:,.2f}" if current_p else "Loading...")
bt_c2.metric("24h High", f"${btc_h.iloc[-24:]['high'].max():,.2f}")
bt_c3.metric("24h Volume", f"{btc_h.iloc[-24:]['vol'].sum():,.0f} BTC")

# --- 3. BTC 表格 ---
# st.subheader("2. BTC Hourly Data")
# st.dataframe(btc_h.sort_values("date", ascending=False).head(10)[["date", "close", "vol"]], use_container_width=True)

# --- 4. MSTR K線 ---
st.markdown("---")
st.subheader("3. MSTR Stock Price")
st.plotly_chart(create_interactive_chart(mstr_data_h, mstr_data_d, mstr_data_w, "MSTR", is_stock=True), use_container_width=True)

# --- 5. mNAV 走勢圖 ---
st.markdown("---")
st.subheader("4. MSTR mNAV")


fig_mnav = go.Figure()
fig_mnav.add_trace(go.Scatter(x=df_combined.index, y=df_combined["mNAV"], line=dict(color='orange', width=2)))
fig_mnav.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=10), xaxis=dict(rangeslider_visible=False, constrain="domain"))
st.plotly_chart(fig_mnav, use_container_width=True)

st.markdown("---")
st.subheader("🤖 AI Market Insight")

if st.button("Generate AI Analysis", key="ai_btn"):
    if not st.session_state.ai_generated:
        with st.spinner("Analyzing market..."):
            st.session_state.ai_summary = generate_ai_summary(df_combined)
            st.session_state.ai_generated = True

if st.session_state.ai_summary:
    st.info(st.session_state.ai_summary)

# --- 6. 詳細資料 ---
# st.subheader("5. Detailed Analysis")
# st.dataframe(df_combined.sort_index(ascending=False).head(20), use_container_width=True)
st.caption(f"🕒 Last Update: {update_time} | Refresh: 5s")
