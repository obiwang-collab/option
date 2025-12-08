import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import calendar
from datetime import datetime, timedelta, timezone # 修改: 引入 timezone
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

# --- 2. 工具函數區 ---

# 定義台灣時區 (UTC+8)
TW_TZ = timezone(timedelta(hours=8))

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
    """
    修改版：從 Yahoo Finance 抓取即時大盤，並強制轉換為台灣時間 (UTC+8)
    """
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        
        if 'chart' in data and 'result' in data['chart']:
            meta = data['chart']['result'][0]['meta']
            
            current_price = meta.get('regularMarketPrice')
            previous_close = meta.get('chartPreviousClose')
            timestamp = meta.get('regularMarketTime')
            
            # 關鍵修改：將 Unix Timestamp 轉為【台灣時間】
            if timestamp:
                # 這裡指定 tz=TW_TZ，確保轉出來是台灣時間
                time_str = datetime.fromtimestamp(timestamp, tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')

            if current_price and previous_close:
                diff = current_price - previous_close
                percent = (diff / previous_close) * 100
                return current_price, diff, percent, time_str
                
    except Exception as e:
        pass
    
    # 失敗時回傳系統當前時間 (也要轉成台灣時間)
    return None, None, None, datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')

@st.cache_data(ttl=300) 
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 嘗試往回找 5 天
    for i in range(5):
        # 這裡也改用台灣時間來計算日期，避免跨日時差導致日期錯誤
        query_date = (datetime.now(tz=TW_TZ) - timedelta(days=i)).strftime('%Y/%m/%d')
        
        payload = {
            'queryType': '2', 'marketCode': '0', 'dateaddcnt': '',
            'commodity_id': 'TXO', 'commodity_id2': '', 
            'queryDate': query_date, 
            'MarketCode': '0', 'commodity_idt': 'TXO'
        }

        try:
            res = requests.post(url, data=payload, headers=headers, timeout=10)
            
            if len(res.text) < 500 or "查無資料" in res.text:
                continue 

            dfs = pd.read_html(StringIO(res.text))
            if not dfs: continue
            
            df = dfs[0]
            
            df.columns = [str(c).replace(' ', '').replace('*', '') for c in df.columns]
            required_cols = ['到期月份(週別)', '履約價', '買賣權', '未沖銷契約量']
            
            if not all(col in df.columns for col in required_cols): continue

            # --- 處理千分位逗號 ---
            df = df[required_cols].copy()
            df.columns = ['Month', 'Strike', 'Type', 'OI']
            
            df['Strike'] = df['Strike'].astype(str).str.replace(',', '') 
            df['OI'] = df['OI'].astype(str).str.replace(',', '')
            
            df['Strike'] = pd.to_numeric(df['Strike'], errors='coerce')
            df['OI'] = pd.to_numeric(df['OI'], errors='coerce').fillna(0)
            
            if df['OI'].sum() == 0:
                continue 

            return df, query_date
            
        except Exception as e:
            continue 

    return None, None

# --- 3. 主程式邏輯 ---

st.title("📊 台指期選擇權(TXO) 支撐壓力戰情室")

with st.sidebar:
    st.write("### 功能選單")
    if st.button("🔄 刷新即時數據", type="primary"):
        st.cache_data.clear()
        st.session_state['refresh'] = True

if True:
    with st.spinner('連線資料源中...'):
        # 1. 抓盤後籌碼
        df, data_date = get_option_data()
        # 2. 抓 Yahoo 即時大盤 (包含時間)
        taiex_now, taiex_diff, taiex_pct, taiex_time = get_realtime_taiex()

    # --- 顯示大盤指數區塊 ---
    if taiex_now is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("加權指數 (TAIEX)", f"{taiex_now:,.2f}", f"{taiex_diff:+.2f} ({taiex_pct:+.2f}%)")
        with c2:
            st.caption(f"即時報價時間：{taiex_time} (TW)")
        with c3:
            st.caption(f"盤後籌碼日期：{data_date}")
        st.divider() 
    else:
        st.warning("⚠️ 無法獲取即時大盤 (Yahoo Finance 連線失敗)，僅顯示盤後籌碼。")

    if df is None or df.empty:
        st.warning("⚠️ 最近 5 天查無有效合約資料。")
    else:
        all_months = df['Month'].unique()
        dataset_list = []
        
        for month in all_months:
            s_date = get_settlement_date(month)
            
            # 過濾已結算合約
            if s_date <= data_date:
                continue
            
            df_m = df[df['Month'] == month]
            is_call = df_m['Type'].astype(str).str.upper().str.contains('買權|CALL')
            
            df_call = df_m[is_call][['Strike', 'OI']].rename(columns={'OI': 'Call_OI'})
            df_put = df_m[~is_call][['Strike', 'OI']].rename(columns={'OI': 'Put_OI'})
            
            df_merge = pd.merge(df_call, df_put, on='Strike', how='outer').fillna(0).sort_values('Strike')
            df_show = df_merge[(df_merge['Call_OI'] > 200) | (df_merge['Put_OI'] > 200)]
            
            if not df_show.empty and (df_show['Call_OI'].max() >= 500 or df_show['Put_OI'].max() >= 500):
                dataset_list.append({'month': month, 'data': df_show, 'settle_date': s_date})
        
        if not dataset_list:
            st.info("無有效合約資料 (所有合約皆已結算或無量)。")
        else:
            valid_datasets = sorted(dataset_list, key=lambda x: x['settle_date'])

            num = len(valid_datasets)
            fig, axes = plt.subplots(num, 1, figsize=(18, 6 * num)) 
            if num == 1: axes = [axes]

            plt.style.use('seaborn-v0_8-white')
            
            font_path = 'msjh.ttc'
            prop = None
            if os.path.exists(font_path):
                try:
                    prop = fm.FontProperties(fname=font_path)
                    plt.rcParams['font.family'] = prop.get_name()
                except:
                    pass
            
            if prop is None:
                plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft JhengHei UI', 'SimHei']
                plt.rcParams['axes.unicode_minus'] = False 

            if taiex_now:
                # 標題加上 (TW) 提示
                full_title = f"TXO 籌碼分佈 vs 大盤：{int(taiex_now)}  [更新時間：{taiex_time} (TW)]"
            else:
                full_title = f"TXO 籌碼分佈    [盤後數據日期：{data_date}]"
            
            if prop:
                fig.suptitle(full_title, fontsize=20, fontweight='bold', y=0.96, color='#333333', fontproperties=prop)
            else:
                fig.suptitle(full_title, fontsize=20, fontweight='bold', y=0.96, color='#333333')

            for i, item in enumerate(valid_datasets):
                ax = axes[i]
                m_code = item['month']
                data = item['data']
                s_date = item['settle_date']
                
                strikes = data['Strike'].values
                c_oi = data['Call_OI'].values
                p_oi = data['Put_OI'].values
                
                bw = np.min(np.diff(strikes)) * 0.4 if len(strikes) > 1 else 20
                call_color = '#d62728' 
                put_color = '#2ca02c'  

                ax.bar(strikes + bw/2, c_oi, width=bw, color=call_color, alpha=0.85, label='Call (壓力)')
                ax.bar(strikes - bw/2, p_oi, width=bw, color=put_color, alpha=0.85, label='Put (支撐)')
                
                # --- 畫出大盤目前位置的虛線 ---
                if taiex_now:
                    ax.axvline(x=taiex_now, color='#ff9900', linestyle='--', linewidth=2, label=f'大盤 ({int(taiex_now)})')

                title_text = f"合約：{m_code}  [預估結算：{s_date}]"
                if prop:
                    ax.set_title(title_text, fontsize=14, fontweight='bold', loc='left', pad=12, color='#003366', fontproperties=prop)
                    if i == 0: ax.legend(loc='upper right', frameon=True, fontsize=12, prop=prop)
                else:
                    ax.set_title(title_text, fontsize=14, fontweight='bold', loc='left', pad=12, color='#003366')
                    if i == 0: ax.legend(loc='upper right', frameon=True, fontsize=12)

                ax.grid(axis='y', linestyle='--', alpha=0.3)
                ax.spines['top'].set_visible(False)
                ax.spines['right'].set_visible(False)
                ax.spines['left'].set_visible(False)
                ax.tick_params(axis='y', length=0)

                ax.text(strikes[np.argmax(c_oi)] + bw/2, np.max(c_oi) + 50, f'{int(np.max(c_oi))}', 
                        ha='center', va='bottom', color=call_color, fontweight='bold', fontsize=11)
                ax.text(strikes[np.argmax(p_oi)] - bw/2, np.max(p_oi) + 50, f'{int(np.max(p_oi))}', 
                        ha='center', va='bottom', color=put_color, fontweight='bold', fontsize=11)

                ax.set_xticks(strikes)
                
                if len(strikes) > 40: step = 2 
                else: step = 1 

                labels = [str(int(s)) if idx % step == 0 else '' for idx, s in enumerate(strikes)]
                ax.set_xticklabels(labels, rotation=45, fontsize=12)

            plt.subplots_adjust(top=0.92, bottom=0.08, hspace=0.5)
            st.pyplot(fig, use_container_width=True)
