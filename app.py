import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from streamlit_autorefresh import st_autorefresh

# =========================
# 0. 自動更新設定
# =========================
st_autorefresh(interval=5000, key="btc_update")
st.set_page_config(page_title="BTC & MSTR Real-time Terminal", layout="wide")

# =========================
# ⭐ 工具：動態Y軸（核心）
# =========================
def get_y_range(df, start, end, padding=0.02):
    df_filtered = df[(df['date'] >= start) & (df['date'] <= end)]
    low = df_filtered['low'].min()
    high = df_filtered['high'].max()
    margin = (high - low) * padding
    return [low - margin, high + margin]

# =========================
# 資料抓取
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

# =========================
# 即時價格狀態
# =========================
if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=["time", "price"])

if 'price_max' not in st.session_state:
    st.session_state.price_max = None
if 'price_min' not in st.session_state:
    st.session_state.price_min = None

current_p = fetch_btc_realtime_price()

if current_p:
    new_entry = pd.DataFrame({"time": [datetime.now()], "price": [current_p]})
    st.session_state.price_history = pd.concat(
        [st.session_state.price_history, new_entry],
        ignore_index=True
    ).tail(50)

    if st.session_state.price_max is None:
        st.session_state.price_max = current_p
        st.session_state.price_min = current_p
    else:
        st.session_state.price_max = max(st.session_state.price_max, current_p)
        st.session_state.price_min = min(st.session_state.price_min, current_p)

# =========================
# 歷史數據
# =========================
btc_h = fetch_btc_binance("1h", 1000)
btc_d = fetch_btc_binance("1d", 400)
btc_w = fetch_btc_binance("1w", 100)

# =========================
# ⭐ BTC K線（已升級動態Y軸）
# =========================
def create_interactive_chart(df_h, df_d, df_w, label):
    fig = go.Figure()
    now = df_h['date'].max()

    h_start = now - timedelta(days=3)
    d_start = now - timedelta(days=60)
    w_start = now - timedelta(days=365)

    fig.add_trace(go.Candlestick(
        x=df_h['date'],
        open=df_h['open'],
        high=df_h['high'],
        low=df_h['low'],
        close=df_h['close'],
        name=label
    ))

    fig.update_layout(
        updatemenus=[dict(
            type="buttons",
            direction="right",
            x=0,
            y=1.15,
            buttons=[
                dict(
                    label="Hourly",
                    method="update",
                    args=[
                        {"x":[df_h.date],"open":[df_h.open],"high":[df_h.high],"low":[df_h.low],"close":[df_h.close]},
                        {
                            "xaxis":{"range":[h_start,now]},
                            "yaxis":{"range": get_y_range(df_h, h_start, now)}
                        }
                    ]
                ),
                dict(
                    label="Daily",
                    method="update",
                    args=[
                        {"x":[df_d.date],"open":[df_d.open],"high":[df_d.high],"low":[df_d.low],"close":[df_d.close]},
                        {
                            "xaxis":{"range":[d_start,now]},
                            "yaxis":{"range": get_y_range(df_d, d_start, now)}
                        }
                    ]
                ),
                dict(
                    label="Weekly",
                    method="update",
                    args=[
                        {"x":[df_w.date],"open":[df_w.open],"high":[df_w.high],"low":[df_w.low],"close":[df_w.close]},
                        {
                            "xaxis":{"range":[w_start,now]},
                            "yaxis":{"range": get_y_range(df_w, w_start, now)}
                        }
                    ]
                ),
            ]
        )],
        xaxis=dict(range=[h_start, now], rangeslider_visible=False),
        yaxis=dict(fixedrange=False),
        height=450,
        margin=dict(t=30, b=10)
    )

    return fig

# =========================
# UI
# =========================
st.title("₿ BTC Real-time Dashboard (Auto-refresh 5s)")

# --- BTC K線 ---
st.subheader("1. BTC Candlestick")
st.plotly_chart(create_interactive_chart(btc_h, btc_d, btc_w, "BTC"), use_container_width=True)

# =========================
# 即時折線圖
# =========================
st.subheader("📈 BTC Real-time Spot Trend")

if not st.session_state.price_history.empty:
    fig_spot = go.Figure()

    fig_spot.add_trace(go.Scatter(
        x=st.session_state.price_history["time"],
        y=st.session_state.price_history["price"],
        mode='lines+markers',
        line=dict(width=3),
        fill='tozeroy'
    ))

    buffer = (st.session_state.price_max - st.session_state.price_min) * 0.05

    fig_spot.update_layout(
        yaxis=dict(
            range=[
                st.session_state.price_min - buffer,
                st.session_state.price_max + buffer
            ],
            tickformat=",.2f",
            side="right"
        ),
        xaxis=dict(rangeslider_visible=False),
        height=350
    )

    st.plotly_chart(fig_spot, use_container_width=True)

    st.write(
        f"📊 Max: {st.session_state.price_max:,.2f} | "
        f"Min: {st.session_state.price_min:,.2f}"
    )

# =========================
# 指標
# =========================
c1, c2, c3 = st.columns(3)

c1.metric("Current Price", f"${current_p:,.2f}" if current_p else "Loading...")
c2.metric("24h High", f"${btc_h.iloc[-24:]['high'].max():,.2f}")
c3.metric("Status", "Live", delta="5s")

st.caption(f"🕒 Last Update: {datetime.now().strftime('%H:%M:%S')}")