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

# 修改重點：加入日期回溯 + 去除逗號邏輯 + 回傳日期字串
@st.cache_data(ttl=300) 
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # 嘗試往回找 5 天
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
            
            # 檢查內容是否有效
            if len(res.text) < 500 or "查無資料" in res.text:
                continue 

            dfs = pd.read_html(StringIO(res.text))
            if not dfs: continue
            
            df = dfs[0]
            
            df.columns = [str(c).replace(' ', '').replace('*', '') for c in df.columns]
            required_cols = ['到期月份(週別)', '履約價', '買賣權', '未沖銷契約量']
            
            if not all(col in df.columns for col in required_cols): continue

            # --- 關鍵修正區：處理千分位逗號 ---
            df = df[required_cols].copy()
            df.columns = ['Month', 'Strike', 'Type', 'OI']
            
            # 先轉成字串，把逗號拿掉，再轉數字 (這是之前缺少的步驟)
            df['Strike'] = df['Strike'].astype(str).str.replace(',', '') 
            df['OI'] = df['OI'].astype(str).str.replace(',', '')
            
            df['Strike'] = pd.to_numeric(df['Strike'], errors='coerce')
            df['OI'] = pd.to_numeric(df['OI'], errors='coerce').fillna(0)
            
            # 確保有抓到有效數據 (避免全0的情況)
            if df['OI'].sum() == 0:
                continue 

            # 回傳 DataFrame 以及 抓到的日期
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
    with st.spinner('連線期交所中...'):
        # 這裡會接收兩個回傳值：資料表 和 資料日期
        df, data_date = get_option_data()

    if df is None or df.empty:
        st.warning("⚠️ 最近 5 天查無有效合約資料，請稍後再試。")
    else:
        # 顯示資料日期
        st.success(f"✅ 已載入數據，資料日期：{data_date}")

        all_months = df['Month'].unique()
        dataset_list = []
        
        for month in all_months:
            s_date = get_settlement_date(month)
            df_m = df[df['Month'] == month]
            is_call = df_m['Type'].astype(str).str.upper().str.contains('買權|CALL')
            
            df_call = df_m[is_call][['Strike', 'OI']].rename(columns={'OI': 'Call_OI'})
            df_put = df_m[~is_call][['Strike', 'OI']].rename(columns={'OI': 'Put_OI'})
            
            df_merge = pd.merge(df_call, df_put, on='Strike', how='outer
