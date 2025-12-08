import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
import calendar

# --- 設定區 ---
st.set_page_config(layout="wide", page_title="台指期籌碼戰情室")
TW_TZ = timezone(timedelta(hours=8)) 

# 手動修正結算日 (2025範例)
MANUAL_SETTLEMENT_FIX = {
    '202501W1': '2025/01/02', 
}

# --- 輔助函式 ---
def get_settlement_date(contract_code):
    """推算結算日"""
    code = str(contract_code).strip()
    for key, fix_date in MANUAL_SETTLEMENT_FIX.items():
        if key in code: return fix_date
    try:
        if len(code) < 5: return "9999/99/99"
        year = int(code[:4])
        month = int(code[4:6])
        c = calendar.monthcalendar(year, month)
        wednesdays = [week[calendar.WEDNESDAY] for week in c if week[calendar.WEDNESDAY] != 0]
        fridays = [week[calendar.FRIDAY] for week in c if week[calendar.FRIDAY] != 0]
        day = None
        
        if 'F1' in code: day = fridays[0] if len(fridays) >= 1 else None
        elif 'F2' in code: day = fridays[1] if len(fridays) >= 2 else None
        elif 'F3' in code: day = fridays[2] if len(fridays) >= 3 else None
        elif 'W1' in code: day = wednesdays[0]
        elif 'W2' in code: day = wednesdays[1]
        elif 'W4' in code: day = wednesdays[3] if len(wednesdays) >= 4 else wednesdays[-1]
        elif 'W5' in code: day = wednesdays[4] if len(wednesdays) >= 5 else None
        else: # 月選
            if len(wednesdays) >= 3: day = wednesdays[2]
            
        return f"{year}/{month:02d}/{day:02d}" if day else "9999/99/99"
    except:
        return "9999/99/99"

@st.cache_data(ttl=60) # 60秒快取，避免頻繁請求
def get_realtime_data():
    """取得大盤與期貨報價"""
    taiex, fut = None, None
    ts = int(time.time())
    
    # 1. 大盤
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0&_={ts}000"
        res = requests.get(url, timeout=2)
        data = res.json()
        if 'msgArray' in data and len(data['msgArray']) > 0:
            val = data['msgArray'][0].get('z', '-')
            if val == '-': val = data['msgArray'][0].get('o', '-')
            if val != '-': taiex = float(val)
    except: pass

    # 2. 期貨 (Yahoo)
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/WTX=F?interval=1m&range=1d&_={ts}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=3)
        data = res.json()
        price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        if price: fut = float(price)
    except: pass
    
    return taiex, fut

@st.cache_data(ttl=300) # 籌碼資料 5 分鐘快取一次即可 (期交所盤中不更新OI)
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    # 往回找 5 天
    for i in range(5):
        query_date = (datetime.now(tz=TW_TZ) - timedelta(days=i)).strftime('%Y/%m/%d')
        payload = {
            'queryType': '2', 'marketCode': '0', 'dateaddcnt': '',
            'commodity_id': 'TXO', 'commodity_id2': '', 
            'queryDate': query_date, 'MarketCode': '0', 'commodity_idt': 'TXO'
        }
        try:
            res = requests.post(url, data=payload, headers=headers, timeout=5)
            if "查無資料" in res.text or len(res.text) < 500: continue 
            
            dfs = pd.read_html(StringIO(res.text))
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
        except: continue 
    return None, None

# --- 繪圖函式 (使用 Plotly 繪製龍捲風圖) ---
def plot_tornado_chart(df_target, title, spot_price, fut_price):
    # 資料處理
    is_call = df_target['Type'].astype(str).str.upper().str.contains('買權|CALL')
    df_call = df_target[is_call][['Strike', 'OI']].rename(columns={'OI': 'Call_OI'})
    df_put = df_target[~is_call][['Strike', 'OI']].rename(columns={'OI': 'Put_OI'})
    
    # 合併
    data = pd.merge(df_call, df_put, on='Strike', how='outer').fillna(0).sort_values('Strike')
    
    # 智慧篩選範圍 (只顯示大量區)
    valid = data[(data['Call_OI'] > 300) | (data['Put_OI'] > 300)]
    if not valid.empty:
        min_s = valid['Strike'].min() - 100
        max_s = valid['Strike'].max() + 100
        data = data[(data['Strike'] >= min_s) & (data['Strike'] <= max_s)]
    
    # 開始繪圖
    fig = go.Figure()

    # 1. Put (左邊，綠色) - 數值轉負才能畫在左邊
    fig.add_trace(go.Bar(
        y=data['Strike'],
        x=-data['Put_OI'], # 負值
        orientation='h',
        name='Put (支撐)',
        marker_color='#2ca02c',
        text=data['Put_OI'], # 顯示正值文字
        textposition='outside',
        hovertemplate='履約價: %{y}<br>Put OI: %{text}<extra></extra>'
    ))

    # 2. Call (右邊，紅色)
    fig.add_trace(go.Bar(
        y=data['Strike'],
        x=data['Call_OI'],
        orientation='h',
        name='Call (壓力)',
        marker_color='#d62728',
        text=data['Call_OI'],
        textposition='outside',
        hovertemplate='履約價: %{y}<br>Call OI: %{x}<extra></extra>'
    ))

    # 3. 價格線
    if spot_price:
        fig.add_hline(y=spot_price, line_dash="dash", line_color="#ff7f0e", annotation_text=f"現貨 {int(spot_price)}", annotation_position="top right")
    if fut_price:
        fig.add_hline(y=fut_price, line_dash="dashdot", line_color="blue", annotation_text=f"期貨 {int(fut_price)}", annotation_position="bottom right")

    # 4. 版面設定
    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis=dict(
            title='未平倉量 (OI)',
            showgrid=True,
            zeroline=True,
            zerolinewidth=2,
            zerolinecolor='black',
            # 隱藏負號的 X 軸刻度
            tickmode='array',
            tickvals=[-3000, -2000, -1000, 0, 1000, 2000, 3000], # 範例刻度
            ticktext=['3k', '2k', '1k', '0', '1k', '2k', '3k']
        ),
        yaxis=dict(
            title='履約價',
            tickmode='linear',
            dtick=100 if len(data) < 20 else 200 # 根據資料量調整刻度密度
        ),
        barmode='overlay', # 其實分開畫更好，但 overlay 配合正負值會自動變 butterfly
        showlegend=True,
        legend=dict(orientation="h", y=1.02, x=0.3),
        height=600, # 高度
        margin=dict(l=20, r=20, t=50, b=20)
    )
    
    return fig

# --- 主程式 ---
def main():
    st.title("📊 台指期選擇權籌碼監控 (龍捲風圖版)")

    # 側邊欄重新整理
    if st.sidebar.button("🔄 重新整理數據"):
        st.cache_data.clear()
        st.rerun()

    # 1. 取得資料
    with st.spinner('正在從期交所抓取資料...'):
        df, data_date = get_option_data()
        taiex_now, fut_now = get_realtime_data()

    if df is None:
        st.error("無法取得期交所資料，請稍後再試。")
        return

    # 顯示即時報價
    col1, col2, col3 = st.columns(3)
    col1.metric("資料日期", data_date)
    col2.metric("加權指數 (現貨)", f"{int(taiex_now)}" if taiex_now else "N/A")
    col3.metric("台指期 (期貨)", f"{int(fut_now)}" if fut_now else "N/A", 
                delta=f"{int(fut_now - taiex_now)}" if (fut_now and taiex_now) else None)

    st.markdown("---")

    # 2. 篩選合約
    unique_months = df['Month'].unique()
    contracts = []
    for m in unique_months:
        s_date = get_settlement_date(m)
        if s_date > data_date:
            contracts.append({'code': m, 'date': s_date})
    contracts.sort(key=lambda x: x['date'])
    
    targets = []
    if contracts:
        targets.append({'type': '🔥 本週結算', 'info': contracts[0]}) # 週選
        
        monthly = next((c for c in contracts if len(c['code']) == 6), None)
        if monthly and monthly['code'] != contracts[0]['code']:
            targets.append({'type': '📅 當月結算', 'info': monthly}) # 月選
        elif monthly:
             next_monthly = next((c for c in contracts if len(c['code']) == 6 and c['code'] != monthly['code']), None)
             if next_monthly:
                 targets.append({'type': '📅 次月結算', 'info': next_monthly})

    # 3. 左右並排顯示
    if not targets:
        st.warning("目前無可顯示的合約數據。")
        return

    # 建立左右兩欄
    cols = st.columns(len(targets))
    
    for i, target in enumerate(targets):
        with cols[i]:
            m_code = target['info']['code']
            s_date = target['info']['date']
            title = f"{target['type']} ({m_code}) - 結算: {s_date}"
            
            # 過濾該合約資料
            df_target = df[df['Month'] == m_code]
            
            # 繪圖
            fig = plot_tornado_chart(df_target, title, taiex_now, fut_now)
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
