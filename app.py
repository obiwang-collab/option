import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import calendar
from datetime import datetime, timedelta 
from io import StringIO
import matplotlib.font_manager as fm
import os
import time # 新增 time 模組

# --- 1. 網頁設定 ---
st.set_page_config(
    page_title="台指期選擇權戰情室",
    page_icon="📊",
    layout="wide" 
)

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
    """
    從證交所 MIS 抓取即時大盤指數
    """
    ts = int(time.time() * 1000)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0&_={ts}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=5)
        data = res.json()
        
        if 'msgArray' in data and len(data['msgArray']) > 0:
            info = data['msgArray'][0]
            
            # z = 當盤成交價, y = 昨日收盤價
            current_price = info.get('z', '-')
            yesterday_close = info.get('y', '-')
            
            if current_price == '-' or current_price == '':
                current_price = info.get('o', yesterday_close)

            try:
                cur_val = float(current_price)
                y_val = float(yesterday_close)
                diff = cur_val - y_val
                percent = (diff / y_val) * 100
                return cur_val, diff, percent
            except:
                return None, None, None
    except:
        pass
    
    return None, None, None

@st.cache_data(ttl=300) 
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for i in range(5):
        query_date = (datetime.now() - timedelta(days=i)).strftime('%Y/%m/%d')
        
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
    # 這裡的刷新按鈕現在也會刷新大盤指數
    if st.button("🔄 刷新即時數據", type="primary"):
        st.cache_data.clear()
        st.session_state['refresh'] = True

if True:
    # 1. 先抓盤後籌碼 (有快取)
    with st.spinner('讀取資料中...'):
        df, data_date = get_option_data()
        
        # 2. 抓取即時大盤 (不使用快取，或者快取極短，這裡直接呼叫)
        taiex_now, taiex_diff, taiex_pct = get_realtime_taiex()

    # --- 顯示大盤指數區塊 ---
    if taiex_now is not None:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("加權指數 (TAIEX)", f"{taiex_now:,.2f}", f"{taiex_diff:+.2f} ({taiex_pct:+.2f}%)")
        with c2:
            st.caption(f"盤後籌碼日期：{data_date}")
        with c3:
            st.caption("指數來源：TWSE MIS (即時)")
        st.divider() # 畫一條分隔線
    else:
        st.warning("⚠️ 無法連線至證交所獲取即時大盤，僅顯示盤後籌碼。")

    if df is None or df.empty:
        st.warning("⚠️ 最近 5 天查無有效選擇權合約資料。")
    else:
        all_months = df['Month'].unique()
        dataset_list = []
        
        for month in all_months:
            s_date = get_settlement_date(month)
            
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
            st.info("無有效合約資料。")
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

            # 在標題中也顯示大盤
            if taiex_now:
                full_title = f"TXO 籌碼分佈 vs 大盤：{int(taiex_now)}  [數據日期：{data_date}]"
            else:
                full_title = f"TXO 籌碼分佈    [數據日期：{data_date}]"
            
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
                
                # --- 新增功能：畫出大盤目前位置的虛線 ---
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
