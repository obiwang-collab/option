import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import calendar
from datetime import datetime, timedelta, timezone 
from io import StringIO
import matplotlib.font_manager as fm
import os
import time

# --- 1. 網頁設定 ---
st.set_page_config(
    page_title="台指期選擇權戰情室",
    page_icon="📊",
    layout="wide" 
)

# 定義台灣時區
TW_TZ = timezone(timedelta(hours=8))

# --- 2. 工具函數區 ---

MANUAL_SETTLEMENT_FIX = {
    '202501W1': '2025/01/02', 
}

def get_settlement_date(contract_code):
    code = str(contract_code).strip()
    for key, fix_date in MANUAL_SETTLEMENT_FIX.items():
        if key in code: return fix_date

    try:
        if len(code) < 6: return "9999/99/99"
        year = int(code[:4])
        month = int(code[4:6])
        c = calendar.monthcalendar(year, month)
        wednesdays = [week[calendar.WEDNESDAY] for week in c if week[calendar.WEDNESDAY] != 0]
        fridays = [week[calendar.FRIDAY] for week in c if week[calendar.FRIDAY] != 0]
        
        day = None
        if 'F1' in code: day = fridays[0] if len(fridays) >= 1 else None
        elif 'F2' in code: day = fridays[1] if len(fridays) >= 2 else None
        elif 'F3' in code: day = fridays[2] if len(fridays) >= 3 else None
        elif 'F4' in code: day = fridays[3] if len(fridays) >= 4 else None
        elif 'F5' in code: day = fridays[4] if len(fridays) >= 5 else None
        elif 'W1' in code: day = wednesdays[0]
        elif 'W2' in code: day = wednesdays[1]
        elif 'W4' in code: 
             if len(wednesdays) >= 4: day = wednesdays[3]
        elif 'W5' in code:
             if len(wednesdays) >= 5: day = wednesdays[4]
        else:
             if len(wednesdays) >= 3: day = wednesdays[2]
        return f"{year}/{month:02d}/{day:02d}" if day else "9999/99/99"
    except:
        return "9999/99/99"

# --- 建立 Session (模擬瀏覽器行為) ---
def get_session():
    s = requests.Session()
    s.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://invest.cnyes.com/'
    })
    return s

# --- [大盤] 多重來源抓取 ---
def fetch_twse_index(session):
    """來源1: 證交所 (最快，但雲端易擋)"""
    ts = int(time.time() * 1000)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0&_={ts}"
    try:
        res = session.get(url, timeout=3)
        # 如果沒拿到 Cookie 導致失敗，嘗試訪問首頁拿票
        if res.status_code != 200:
            session.get('https://mis.twse.com.tw/stock/fibest.jsp?lang=zh_tw', timeout=3)
            res = session.get(url, timeout=3)
            
        data = res.json()
        if 'msgArray' in data and len(data['msgArray']) > 0:
            info = data['msgArray'][0]
            current = info.get('z', '-')
            if current == '-' or current == '': current = info.get('o', '-')
            
            if current != '-':
                # 組合時間
                t_str = info.get('t', '')
                full_time = f"{datetime.now(tz=TW_TZ).strftime('%Y-%m-%d')} {t_str}"
                
                # 計算漲跌
                y_close = float(info.get('y', current))
                cur_val = float(current)
                diff = cur_val - y_close
                pct = (diff / y_close) * 100
                
                return cur_val, diff, pct, full_time, "TWSE"
    except:
        pass
    return None

def fetch_yahoo_index():
    """來源2: Yahoo Finance (穩定備援)"""
    ts = int(time.time())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1m&range=1d&includePrePost=false&_={ts}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        data = res.json()
        result = data['chart']['result'][0]
        meta = result['meta']
        
        # 嘗試拿最後一根 K 棒
        if 'timestamp' in result and 'indicators' in result:
            quotes = result['indicators']['quote'][0]['close']
            timestamps = result['timestamp']
            
            # 找最後一個非 None 的值
            for i in range(len(quotes)-1, -1, -1):
                if quotes[i] is not None:
                    price = quotes[i]
                    last_ts = timestamps[i]
                    prev = meta.get('chartPreviousClose', price)
                    
                    diff = price - prev
                    pct = (diff / prev) * 100
                    t_str = datetime.fromtimestamp(last_ts, tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
                    
                    return price, diff, pct, t_str, "Yahoo"
    except:
        pass
    return None

def get_realtime_taiex():
    s = get_session()
    # 優先嘗試 TWSE
    res = fetch_twse_index(s)
    if res: return res
    # 失敗轉 Yahoo
    res = fetch_yahoo_index()
    if res: return res
    
    return None, None, None, datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S'), "N/A"

# --- [期貨] 多重來源抓取 ---
def fetch_futures_cnyes(session):
    """來源1: 鉅亨網 (最快)"""
    url = "https://ws.api.cnyes.com/ws/api/v1/quote/quotes/TWS:TXF:FUT"
    try:
        res = session.get(url, timeout=4)
        data = res.json()
        if 'data' in data and data['data']:
            quote = data['data'][0]
            price = quote.get('6')
            name = quote.get('0', '台指期')
            timestamp = quote.get('13') # Unix timestamp
            
            if price:
                t_str = datetime.fromtimestamp(timestamp, tz=TW_TZ).strftime('%H:%M:%S') if timestamp else ""
                return float(price), name, t_str, "Anue"
    except:
        pass
    return None

def fetch_futures_yahoo():
    """來源2: Yahoo Finance (WTX=F)"""
    ts = int(time.time())
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/WTX=F?interval=1m&range=1d&includePrePost=false&_={ts}"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        data = res.json()
        if 'chart' in data and 'result' in data['chart']:
            result = data['chart']['result'][0]
            
            # 嘗試拿最後一根 K 棒
            if 'timestamp' in result and 'indicators' in result:
                quotes = result['indicators']['quote'][0]['close']
                timestamps = result['timestamp']
                
                for i in range(len(quotes)-1, -1, -1):
                    if quotes[i] is not None:
                        price = quotes[i]
                        last_ts = timestamps[i]
                        t_str = datetime.fromtimestamp(last_ts, tz=TW_TZ).strftime('%H:%M:%S')
                        return float(price), "TX(Yahoo)", t_str, "Yahoo"
    except:
        pass
    return None

def get_realtime_futures():
    s = get_session()
    # 1. 鉅亨網
    res = fetch_futures_cnyes(s)
    if res: return res
    # 2. Yahoo
    res = fetch_futures_yahoo()
    if res: return res
    
    return None, None, None, None

@st.cache_data(ttl=300) 
def get_option_data():
    """抓取期交所盤後籌碼 (有快取)"""
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {'User-Agent': 'Mozilla/5.0'}

    for i in range(5):
        query_date = (datetime.now(tz=TW_TZ) - timedelta(days=i)).strftime('%Y/%m/%d')
        payload = {
            'queryType': '2', 'marketCode': '0', 'dateaddcnt': '',
            'commodity_id': 'TXO', 'commodity_id2': '', 
            'queryDate': query_date, 
            'MarketCode': '0', 'commodity_idt': 'TXO'
        }

        try:
            res = requests.post(url, data=payload, headers=headers, timeout=10)
            if len(res.text) < 500 or "查無資料" in res.text: continue 

            dfs = pd.read_html(StringIO(res.text))
            if not dfs: continue
            df = dfs[0]
            
            df.columns = [str(c).replace(' ', '').replace('*', '') for c in df.columns]
            required_cols = ['到期月份(週別)', '履約價', '買賣權', '未沖銷契約量']
            if not all(col in df.columns for col in required_cols): continue

            df = df[required_cols].copy()
            df.columns = ['Month', 'Strike', 'Type', 'OI']
            
            df['Strike'] = pd.to_numeric(df['Strike'].astype(str).str.replace(',', ''), errors='coerce')
            df['OI'] = pd.to_numeric(df['OI'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            if df['OI'].sum() == 0: continue 
            return df, query_date
        except:
            continue 
    return None, None

# --- 3. 主程式邏輯 (使用 st.fragment + JS 倒數) ---

st.title("📊 台指期選擇權(TXO) 支撐壓力戰情室")

with st.sidebar:
    st.write("### 設定")
    auto_refresh = st.checkbox('開啟 60秒 自動刷新', value=True)
    if st.button("🔄 手動刷新", type="primary"):
        st.cache_data.clear()
        st.rerun()

# 核心邏輯：如果勾選自動刷新，後端每 60 秒重跑一次
@st.fragment(run_every=60 if auto_refresh else None)
def dashboard_content():
    # 1. 抓資料
    df, data_date = get_option_data()
    
    # 抓大盤
    taiex_now, taiex_diff, taiex_pct, taiex_time, t_src = get_realtime_taiex()
    
    # 抓期貨
    fut_now, fut_name, fut_time, f_src = get_realtime_futures()

    # 2. 顯示指標
    if taiex_now is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("加權指數 (Spot)", f"{taiex_now:,.0f}", f"{taiex_diff:+.0f} ({taiex_pct:+.2f}%)")
        with c2:
            if fut_now:
                # 計算價差
                gap = fut_now - taiex_now
                st.metric(f"台指期 ({fut_name})", f"{fut_now:,.0f}", f"價差: {gap:+.0f}")
            else:
                st.metric("台指期 (Futures)", "N/A", "等待數據...")
        with c3:
            # 顯示資料來源與時間
            st.caption(f"現貨源: {t_src} | 期貨源: {f_src}")
            st.caption(f"更新: {taiex_time}")
            
            if auto_refresh:
                countdown_html = """
                <div id="countdown-timer" style="font-size: 0.8em; color: rgba(49, 51, 63, 0.6); margin-top: -5px;">
                    ⚡ 刷新倒數: <span id="time-left">60</span>s
                </div>
                <script>
                    if (window.countdownInterval) clearInterval(window.countdownInterval);
                    var timeLeft = 60;
                    var elem = document.getElementById('time-left');
                    window.countdownInterval = setInterval(function() {
                        if (timeLeft <= 1) {
                            elem.innerHTML = "更新中...";
                            clearInterval(window.countdownInterval);
                        } else {
                            timeLeft--;
                            elem.innerHTML = timeLeft;
                        }
                    }, 1000);
                </script>
                """
                st.components.v1.html(countdown_html, height=30)
            else:
                st.caption("⏸️ 自動刷新已暫停")

        st.divider() 
    else:
        st.warning("⚠️ 無法獲取即時大盤，僅顯示盤後籌碼。")

    # 3. 繪圖邏輯
    if df is None or df.empty:
        st.warning("⚠️ 最近 5 天查無有效合約資料。")
        return

    all_months = df['Month'].unique()
    dataset_list = []
    
    for month in all_months:
        s_date = get_settlement_date(month)
        if s_date <= data_date: continue 
        
        df_m = df[df['Month'] == month]
        is_call = df_m['Type'].astype(str).str.upper().str.contains('買權|CALL')
        
        df_call = df_m[is_call][['Strike', 'OI']].rename(columns={'OI': 'Call_OI'})
        df_put = df_m[~is_call][['Strike', 'OI']].rename(columns={'OI': 'Put_OI'})
        
        df_merge = pd.merge(df_call, df_put, on='Strike', how='outer').fillna(0).sort_values('Strike')
        df_show = df_merge[(df_merge['Call_OI'] > 200) | (df_merge['Put_OI'] > 200)]
        
        if not df_show.empty and (df_show['Call_OI'].max() >= 500 or df_show['Put_OI'].max() >= 500):
            dataset_list.append({'month': month, 'data': df_show, 'settle_date': s_date})
    
    if not dataset_list:
        st.info("無有效合約資料。")
        return

    valid_datasets = sorted(dataset_list, key=lambda x: x['settle_date'])
    num = len(valid_datasets)
    fig, axes = plt.subplots(num, 1, figsize=(18, 6 * num)) 
    if num == 1: axes = [axes]

    plt.style.use('seaborn-v0_8-white')
    
    font_path = 'msjh.ttc'
    prop = fm.FontProperties(fname=font_path) if os.path.exists(font_path) else None
    if prop:
        plt.rcParams['font.family'] = prop.get_name()
    else:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft JhengHei UI', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False 

    # 標題
    t_price = int(taiex_now) if taiex_now else "N/A"
    f_price = int(fut_now) if fut_now else "N/A"
    gap_info = ""
    if taiex_now and fut_now:
        gap = int(fut_now - taiex_now)
        gap_info = f" (價差 {gap:+})"
    
    title_str = f"現貨: {t_price} vs 期貨: {f_price}{gap_info}"
    time_info = f"[更新: {taiex_time}]" if taiex_time else f"[日期: {data_date}]"
    
    fig.suptitle(f"{title_str}    {time_info}", fontsize=20, fontweight='bold', y=0.96, color='#333333', fontproperties=prop if prop else None)

    for i, item in enumerate(valid_datasets):
        ax = axes[i]
        m_code = item['month']
        data = item['data']
        s_date = item['settle_date']
        
        strikes = data['Strike'].values
        c_oi = data['Call_OI'].values
        p_oi = data['Put_OI'].values
        
        bw = np.min(np.diff(strikes)) * 0.4 if len(strikes) > 1 else 20
        
        ax.bar(strikes + bw/2, c_oi, width=bw, color='#d62728', alpha=0.85, label='Call (壓力)')
        ax.bar(strikes - bw/2, p_oi, width=bw, color='#2ca02c', alpha=0.85, label='Put (支撐)')
        
        # 畫虛線：現貨(橘)、期貨(藍)
        if taiex_now:
            ax.axvline(x=taiex_now, color='#ff9900', linestyle='--', linewidth=2, label=f'現貨 ({int(taiex_now)})')
        if fut_now:
            ax.axvline(x=fut_now, color='blue', linestyle='-.', linewidth=2, label=f'期貨 ({int(fut_now)})')

        t_text = f"合約：{m_code}  [預估結算：{s_date}]"
        ax.set_title(t_text, fontsize=14, fontweight='bold', loc='left', pad=12, color='#003366', fontproperties=prop if prop else None)
        
        if i == 0: 
            ax.legend(loc='upper right', frameon=True, fontsize=12, prop=prop if prop else None)

        ax.grid(axis='y', linestyle='--', alpha=0.3)
        for s in ['top', 'right', 'left']: ax.spines[s].set_visible(False)
        ax.tick_params(axis='y', length=0)

        ax.text(strikes[np.argmax(c_oi)] + bw/2, np.max(c_oi) + 50, f'{int(np.max(c_oi))}', 
                ha='center', va='bottom', color='#d62728', fontweight='bold', fontsize=11)
        ax.text(strikes[np.argmax(p_oi)] - bw/2, np.max(p_oi) + 50, f'{int(np.max(p_oi))}', 
                ha='center', va='bottom', color='#2ca02c', fontweight='bold', fontsize=11)

        ax.set_xticks(strikes)
        step = 2 if len(strikes) > 40 else 1
        labels = [str(int(s)) if idx % step == 0 else '' for idx, s in enumerate(strikes)]
        ax.set_xticklabels(labels, rotation=45, fontsize=12)

    plt.subplots_adjust(top=0.92, bottom=0.08, hspace=0.5)
    st.pyplot(fig, use_container_width=True)

# --- 執行主要區塊 ---
dashboard_content()
