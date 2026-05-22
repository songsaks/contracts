import django, os, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from django.test import RequestFactory
from stocks.views import stock_chart_data

req = RequestFactory().get('/stocks/chart/PLTR/data/?market=US&period=1y&interval=1d')
resp = stock_chart_data.__wrapped__(req, 'PLTR')
data = json.loads(resp.content)

signals = data.get('signals', [])
candles = data.get('candles', [])

signalMap = {}
for s in signals:
    if s['time'] not in signalMap or s['type'] == 'sys1_exit':
        signalMap[s['time']] = s['type']
    elif s['type'] in ('sys1_buy', 'sys2_buy'):
        signalMap[s['time']] = s['type']

currentTrend = None
blueCount = 0
pinkCount = 0
for c in candles:
    sig = signalMap.get(c['time'])
    if sig in ('sys1_buy', 'sig2_buy', 'sys2_buy'):
        currentTrend = 'buy'
    elif sig == 'sys1_exit':
        currentTrend = 'exit'
    
    if currentTrend == 'buy':
        blueCount += 1
    elif currentTrend == 'exit':
        pinkCount += 1

print(f"Candles: {len(candles)}, Blue: {blueCount}, Pink: {pinkCount}")
