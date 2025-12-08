def get_realtime_taiex():
    """
    修改版：從 Yahoo Finance 抓取即時大盤 (UTC+8)
    修正：加入 timestamp 參數以防止 API 快取導致資料延遲
    """
    # 取得當下時間戳記 (整數秒)
    ts = int(time.time())
    
    # 關鍵修改：在網址後面加上 &_={ts} 讓每次網址都不一樣，強制 Yahoo 給最新資料
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII?interval=1d&_={ts}"
    
    headers = {
        # 偽裝成一般瀏覽器，避免被擋
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # 設定較短的 timeout，避免卡住
        res = requests.get(url, headers=headers, timeout=3)
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
    except Exception as e:
        # print(f"Yahoo API Error: {e}") # 本地除錯用
        pass
        
    return None, None, None, datetime.now(tz=TW_TZ).strftime('%Y-%m-%d %H:%M:%S')
