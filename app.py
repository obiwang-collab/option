import streamlit as st
import requests
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import calendar
from datetime import datetime, timedelta  # 修改1: 增加 timedelta 模組
from io import StringIO
import matplotlib.font_manager as fm
import os

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

@st.cache_data(ttl=60) 
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    
    # 修改2: 增加 User-Agent 避免被擋，並加入回溯迴圈
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 嘗試往回找 5 天 (涵蓋週末與國定假日)
    for i in range(5):
        query_date = (datetime.now() - timedelta(days=i)).strftime('%Y/%m/%d')
        
        payload = {
            'queryType': '2', 'marketCode': '0', 'dateaddcnt': '',
            'commodity_id': 'TXO', 'commodity_id2': '', 
            'queryDate': query_date, # 使用動態日期
            'MarketCode': '0', 'commodity_idt': 'TXO'
        }

        try:
            res = requests.post(url, data=payload, headers=headers, timeout=10)
            
            # 如果回傳內容太短或包含查無資料，就跳過，找前一天
            if len(res.text) < 500 or "查無資料" in res.text:
                continue

            dfs = pd.read_html(StringIO(res.text))
            if not dfs: continue # 沒表格，找前一天
            
            df = dfs[0]
            
            df.columns = [str(c).replace(' ', '').replace('*', '') for c in df.columns]
            required_cols = ['到期月份(週別)', '履約價', '買賣權', '未沖銷契約量']
            
            # 欄位不對，找前一天
            if not all(col in df.columns for col in required_cols): continue

            # --- 成功抓到資料 ---
            st.toast(f"已載入 {query_date} 的盤後資料", icon="📅") # 提示使用者目前顯示的日期
            
            df = df[required_cols].copy()
            df.columns = ['Month', 'Strike', 'Type', 'OI']
            df = df[pd.to_numeric(df['Strike'], errors='coerce').notnull()]
            df['Strike'] = df['Strike'].astype(float)
            df['OI'] = pd.to_numeric(df['OI'], errors='coerce').fillna(0)
            return df
            
        except Exception as e:
            continue # 發生錯誤，找前一天

    st.error("最近 5 天皆無法獲取期交所資料，請檢查連線。")
    return None

# --- 3. 主程式邏輯 (以下完全未改動) ---

st.title("📊 台指期選擇權(TXO) 支撐壓力戰情室")

with st.sidebar:
    st.write("### 功能選單")
    if st.button("🔄 刷新即時數據", type="primary"):
        st.cache_data.clear()
        st.session_state['refresh'] = True

if True:
    with st.spinner('連線期交所中...'):
        df = get_option_data()

    if df is None or df.empty:
        st.warning("⚠️ 暫無資料，請稍後再試。")
    else:
        all_months = df['Month'].unique()
        dataset_list = []
        
        for month in all_months:
            s_date = get_settlement_date(month)
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

            # ==========================================
            # 關鍵修正：雲端字體載入邏輯
            # ==========================================
            plt.style.use('seaborn-v0_8-white')
            
            # 1. 優先尋找同目錄下的 msjh.ttc (這是給雲端用的)
            font_path = 'msjh.ttc'
            prop = None
            if os.path.exists(font_path):
                try:
                    prop = fm.FontProperties(fname=font_path)
                    # 設定全域字體為該檔案
                    plt.rcParams['font.family'] = prop.get_name()
                except:
                    pass
            
            # 2. 如果找不到檔案，退回使用系統字體 (這是給你電腦用的)
            if prop is None:
                plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'Microsoft JhengHei UI', 'SimHei']
                plt.rcParams['axes.unicode_minus'] = False 

            today_str = datetime.now().strftime('%Y-%m-%d')
            now_str = datetime.now().strftime('%H:%M')
            
            full_title = f"台指期選擇權(TXO) 籌碼分佈    [資料日期：{today_str} {now_str}]"
            
            # 如果有找到字體檔，就套用 fontproperties
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

                title_text = f"合約：{m_code}  [預估結算：{s_date}]"
                if prop:
                    ax.set_title(title_text, fontsize=14, fontweight='bold', loc='left', pad=12, color='#003366', fontproperties=prop)
                    # 圖例
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
