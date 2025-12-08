import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import time
from datetime import datetime, timedelta, timezone
from io import StringIO
import calendar

# --- 設定區 ---
st.set_page_config(layout="wide", page_title="台指期籌碼戰情室 (APP最終版)")
TW_TZ = timezone(timedelta(hours=8)) 

# 手動修正結算日
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

@st.cache_data(ttl=60)
def get_realtime_data():
    """取得大盤與期貨報價"""
    taiex, fut = None, None
    ts = int(time.time())
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0&_={ts}000"
        res = requests.get(url, timeout=2)
        data = res.json()
        if 'msgArray' in data and len(data['msgArray']) > 0:
            val = data['msgArray'][0].get('z', '-')
            if val == '-': val = data['msgArray'][0].get('o', '-')
            if val != '-': taiex = float(val)
    except: pass

    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/WTX=F?interval=1m&range=1d&_={ts}"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=3)
        data = res.json()
        price = data['chart']['result'][0]['meta'].get('regularMarketPrice')
        if price: fut = float(price)
    except: pass
    
    return taiex, fut

@st.cache_data(ttl=300)
def get_option_data():
    url = "https://www.taifex.com.tw/cht/3/optDailyMarketReport"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
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
            
            required_cols = ['到期月份(週別)', '履約價', '買賣權', '未沖銷契約量', '結算價']
            if not all(col in df.columns for col in required_cols): continue
            
            df = df[required_cols].copy()
            df.columns = ['Month', 'Strike', 'Type', 'OI', 'Price'] 
            
            # --- 強力資料清洗 (解決抓不到 Call 的問題) ---
            df = df.dropna(subset=['Type'])
            df['Type'] = df['Type'].astype(str).str.strip() # 去除空白
            
            # 數值轉換
            df['Strike'] = pd.to_numeric(df['Strike'].astype(str).str.replace(',', ''), errors='coerce')
            df['OI'] = pd.to_numeric(df['OI'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            df['Price'] = pd.to_numeric(df['Price'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            # 計算金額
            df['Amount'] = df['OI'] * df['Price'] * 50
            
            if df['OI'].sum() == 0: continue 
            return df, query_date
        except: continue 
    return None, None

# --- 繪圖元件: 龍捲風圖 (Plotly版) ---
def plot_tornado_chart(df_target, title, spot_price, fut_price):
    # 寬鬆判斷 Call
    is_call = df_target['Type'].str.contains('買|Call', case=False, na=False)
    
    df_call = df_target[is_call][['Strike', 'OI', 'Amount']].rename(columns={'OI': 'Call_OI', 'Amount': 'Call_Amt'})
    df_put = df_target[~is_call][['Strike', 'OI', 'Amount']].rename(columns={'OI': 'Put_OI', 'Amount': 'Put_Amt'})
    
    data = pd.merge(df_call, df_put, on='Strike', how='outer').fillna(0).sort_values('Strike')
    
    # 計算總金額
    total_put_money = data['Put_Amt'].sum()
    total_call_money = data['Call_Amt'].sum()
    
    # 篩選顯示範圍 (只顯示大量區)
    valid = data[(data['Call_OI'] > 300) | (data['Put_OI'] > 300)]
    if not valid.empty:
        min_s = valid['Strike'].min() - 100
        max_s = valid['Strike'].max() + 100
        data = data[(data['Strike'] >= min_s) & (data['Strike'] <= max_s)]
    
    # --- 優化文字標籤：只顯示 > 400 的數字 ---
    data['Put_Text'] = data['Put_OI'].apply(lambda x: str(int(x)) if x > 400 else "")
    data['Call_Text'] = data['Call_OI'].apply(lambda x: str(int(x)) if x > 400 else "")

    # --- 強制對稱 X 軸 ---
    max_oi = max(data['Put_OI'].max(), data['Call_OI'].max())
    x_limit = max_oi * 1.3 # 留空間給文字

    fig = go.Figure()

    # Put (左, 綠色)
    fig.add_trace(go.Bar(
        y=data['Strike'], x=-data['Put_OI'], orientation='h', name='Put (支撐)',
        marker_color='#2ca02c',
        text=data['Put_Text'], textposition='outside', # 使用過濾後的文字
        customdata=data['Put_Amt'] / 100000000, 
        hovertemplate='<b>履約價: %{y}</b><br>Put OI: %{x}<br>Put 市值: %{customdata:.2f}億<extra></extra>'
    ))

    # Call (右, 紅色)
    fig.add_trace(go.Bar(
        y=data['Strike'], x=data['Call_OI'], orientation='h', name='Call (壓力)',
        marker_color='#d62728',
        text=data['Call_Text'], textposition='outside',
        customdata=data['Call_Amt'] / 100000000,
        hovertemplate='<b>履約價: %{y}</b><br>Call OI: %{x}<br>Call 市值: %{customdata:.2f}億<extra></extra>'
    ))

    # 價格線
    if spot_price:
        fig.add_hline(y=spot_price, line_dash="dash", line_color="#ff7f0e", annotation_text=f"現貨 {int(spot_price)}", annotation_position="top right")
    if fut_price:
        fig.add_hline(y=fut_price, line_dash="dashdot", line_color="blue", annotation_text=f"期貨 {int(fut_price)}", annotation_position="bottom right")

    fig.update_layout(
        title=dict(text=title, x=0.5),
        xaxis=dict(
            title='未平倉量 (OI)',
            range=[-x_limit, x_limit], # 強制對稱
            showgrid=True,
            zeroline=True, zerolinewidth=2, zerolinecolor='black',
            # 自定義刻度顯示 (把負號拿掉)
            tickmode='array',
            tickvals=[-x_limit*0.75, -x_limit*0.5, -x_limit*0.25, 0, x_limit*0.25, x_limit*0.5, x_limit*0.75],
            ticktext=[f"{int(x_limit*0.75)}", f"{int(x_limit*0.5)}", f"{int(x_limit*0.25)}", "0", 
                      f"{int(x_limit*0.25)}", f"{int(x_limit*0.5)}", f"{int(x_limit*0.75)}"]
        ),
        yaxis=dict(
            title='履約價', 
            tickmode='linear', 
            dtick=200 # 強制每隔 200 點顯示一個刻度，避免擁擠
        ),
        barmode='overlay',
        legend=dict(orientation="h", y=1.05, x=0.3),
        height=700, # 拉高圖表
        margin=dict(l=40, r=40, t=80, b=40),
        
        # --- 顯示總金額的框框 (Annotations) ---
        annotations=[
            # 左上角 Put 金額
            dict(
                x=0.02, y=1.02, xref="paper", yref="paper",
                text=f"<b>Put 總金額</b><br>{total_put_money/100000000:.1f} 億",
                showarrow=False, align="left",
                bgcolor="white", bordercolor="#2ca02c", borderwidth=2,
                font=dict(size=14, color="#2ca02c")
            ),
            # 右上角 Call 金額
            dict(
                x=0.98, y=1.02, xref="paper", yref="paper",
                text=f"<b>Call 總金額</b><br>{total_call_money/100000000:.1f} 億",
                showarrow=False, align="right",
                bgcolor="white", bordercolor="#d62728", borderwidth=2,
                font=dict(size=14, color="#d62728")
            )
        ]
    )
    return fig

# --- 主程式 ---
def main():
    st.title("📊 台指期選擇權籌碼戰情室 (APP最終版)")

    if st.sidebar.button("🔄 重新整理"):
        st.cache_data.clear()
        st.rerun()

    with st.spinner('計算籌碼金額中...'):
        df, data_date = get_option_data()
        taiex_now, fut_now = get_realtime_data()

    if df is None:
        st.error("查無資料，請稍後再試")
        return

    # 計算全市場數據
    total_call_amt = df[df['Type'].str.contains('買|Call', case=False, na=False)]['Amount'].sum()
    total_put_amt = df[df['Type'].str.contains('賣|Put', case=False, na=False)]['Amount'].sum()
    pc_ratio_amt = (total_put_amt / total_call_amt) * 100 if total_call_amt > 0 else 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("資料日期", data_date)
    c2.metric("現貨 / 期貨", f"{int(taiex_now) if taiex_now else 'N/A'} / {int(fut_now) if fut_now else 'N/A'}")
    
    trend = "偏多" if pc_ratio_amt > 100 else "偏空"
    trend_color = "normal" if pc_ratio_amt > 100 else "inverse"
    c3.metric("P/C 金額比 (市值)", f"{pc_ratio_amt:.1f}%", f"{trend}格局", delta_color=trend_color)
    c4.metric("全市場總市值", f"{(total_call_amt+total_put_amt)/100000000:.1f} 億")
    
    st.markdown("---")

    unique_months = df['Month'].unique()
    contracts = []
    for m in unique_months:
        s_date = get_settlement_date(m)
        if s_date > data_date:
            contracts.append({'code': m, 'date': s_date})
    contracts.sort(key=lambda x: x['date'])
    
    targets = []
    if contracts:
        targets.append({'type': '🔥 本週結算', 'info': contracts[0]})
        monthly = next((c for c in contracts if len(c['code']) == 6), None)
        if monthly and monthly['code'] != contracts[0]['code']:
            targets.append({'type': '📅 當月結算', 'info': monthly})
        elif monthly:
             next_monthly = next((c for c in contracts if len(c['code']) == 6 and c['code'] != monthly['code']), None)
             if next_monthly:
                 targets.append({'type': '📅 次月結算', 'info': next_monthly})

    if not targets:
        st.warning("無合約資料")
        return

    # 左右並排顯示
    cols = st.columns(len(targets))
    for i, target in enumerate(targets):
        with cols[i]:
            m_code = target['info']['code']
            s_date = target['info']['date']
            
            # 取得該合約的 P/C Ratio
            df_target = df[df['Month'] == m_code]
            sub_call = df_target[df_target['Type'].str.contains('Call|買', case=False, na=False)]['Amount'].sum()
            sub_put = df_target[df_target['Type'].str.contains('Put|賣', case=False, na=False)]['Amount'].sum()
            sub_ratio = (sub_put / sub_call * 100) if sub_call > 0 else 0
            
            title = f"{target['type']} ({m_code}) - P/C金額比: {sub_ratio:.1f}%"
            
            fig = plot_tornado_chart(df_target, title, taiex_now, fut_now)
            st.plotly_chart(fig, use_container_width=True)

if __name__ == "__main__":
    main()
