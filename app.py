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

def get_realtime_taiex():
    """從 Yahoo Finance 抓取即時大盤 (UTC+8)"""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        if 'chart' in data and 'result' in data['chart']:
            meta = data['chart']['result'][0]['meta']
            current = meta.get('regularMarketPrice')
            prev = meta.get('chartPreviousClose')
            timestamp = meta.get('regularMarketTime')
            
            if timestamp:
                time_str = datetime.fromtimestamp(timestamp, tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')

            if current and prev:
                return current, current - prev, (current - prev)/prev * 100, time_str
    except:
        pass
    return None, None, None, datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')

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
    # 預設開啟自動刷新，頻率 60 秒
    auto_refresh = st.checkbox('開啟 60秒 自動刷新', value=True)
    if st.button("🔄 手動刷新", type="primary"):
        st.cache_data.clear()
        st.rerun()

# 核心邏輯：如果勾選自動刷新，後端每 60 秒重跑一次
@st.fragment(run_every=60 if auto_refresh else None)
def dashboard_content():
    # 1. 抓資料
    df, data_date = get_option_data()
    taiex_now, taiex_diff, taiex_pct, taiex_time = get_realtime_taiex()

    # 2. 顯示指標
    if taiex_now is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("加權指數 (TAIEX)", f"{taiex_now:,.2f}", f"{taiex_diff:+.2f} ({taiex_pct:+.2f}%)")
        with c2:
            st.caption(f"即時報價：{taiex_time} (TW)")
        with c3:
            st.caption(f"盤後籌碼：{data_date}")
            
            # === 加入 JavaScript 動態倒數計時 ===
            if auto_refresh:
                # 這段 JS 會在瀏覽器端執行，不消耗後端資源
                # 每次 Python 重跑這個 fragment 時，HTML 會重繪，JS 計時器也會重置為 60
                countdown_html = """
                <div id="countdown-timer" style="font-size: 0.8em; color: rgba(49, 51, 63, 0.6); margin-top: -10px;">
                    ⚡ 刷新倒數: <span id="time-left">60</span>s
                </div>
                <script>
                    // 清除可能存在的舊 interval (避免 fragment 重複執行時疊加)
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
        if s_date <= data_date: continue # 過濾已結算
        
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
    
    # 字體設定
    font_path = 'msjh.ttc'
    prop = fm.FontProperties(fname=font_path) if os.path.exists(font_path) else None
    if prop:
        plt.rcParams['font.family'] = prop.get_name()
    else:
        plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft JhengHei UI', 'SimHei']
        plt.rcParams['axes.unicode_minus'] = False 

    # 標題
    title_str = f"TXO 籌碼分佈 vs 大盤：{int(taiex_now)}" if taiex_now else "TXO 籌碼分佈"
    time_info = f"[更新：{taiex_time} (TW)]" if taiex_now else f"[日期：{data_date}]"
    
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
        
        # 大盤虛線
        if taiex_now:
            ax.axvline(x=taiex_now, color='#ff9900', linestyle='--', linewidth=2, label=f'大盤 ({int(taiex_now)})')

        # 子標題
        t_text = f"合約：{m_code}  [預估結算：{s_date}]"
        ax.set_title(t_text, fontsize=14, fontweight='bold', loc='left', pad=12, color='#003366', fontproperties=prop if prop else None)
        
        if i == 0: 
            ax.legend(loc='upper right', frameon=True, fontsize=12, prop=prop if prop else None)

        ax.grid(axis='y', linestyle='--', alpha=0.3)
        for s in ['top', 'right', 'left']: ax.spines[s].set_visible(False)
        ax.tick_params(axis='y', length=0)

        # 標註最大量
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
