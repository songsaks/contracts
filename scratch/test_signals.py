import requests

def test_api():
    try:
        import sys
        import os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        url = "http://127.0.0.1:8000/stocks/chart/PLTR/data/?market=US&period=1y&interval=1d"
        # We need a logged in session or maybe not if @login_required is enabled?
        # Oh, stock_chart_data view has @login_required decorator!
        # Line 10539: @login_required
        # So requests without login will get a redirect to login page.
        # Let's inspect the Django settings to see if we can log in or bypass.
        # Or we can just import stock_chart_data or run Django code directly!
        import django
        import os
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
        django.setup()
        
        from django.test import RequestFactory
        from django.contrib.auth.models import User
        from stocks.views import stock_chart_data
        
        factory = RequestFactory()
        request = factory.get('/stocks/chart/PLTR/data/?market=US&period=1y&interval=1d')
        
        # Get or create a dummy user
        user = User.objects.first()
        if not user:
            user = User.objects.create_user(username='temp_user', password='password')
        request.user = user
        
        response = stock_chart_data(request, 'PLTR')
        import json
        data = json.loads(response.content)
        if 'error' in data:
            print("Error in response:", data['error'])
            return
            
        print("Symbol:", data['symbol'])
        print("Number of candles:", len(data['candles']))
        print("Number of signals:", len(data['signals']))
        print("First 5 signals:", data['signals'][:5])
        print("Last 5 signals:", data['signals'][-5:])
        
        # Test how the JS logic behaves
        signal_map = {}
        for s in data['signals']:
            t = s['time']
            stype = s['type']
            if t not in signal_map or stype == 'sys1_exit':
                signal_map[t] = stype
            elif stype in ('sys1_buy', 'sys2_buy'):
                signal_map[t] = stype
                
        trend = None
        trend_counts = {'buy': 0, 'exit': 0, 'none': 0}
        for c in data['candles']:
            t = c['time']
            sig = signal_map.get(t)
            if sig in ('sys1_buy', 'sys2_buy'):
                trend = 'buy'
            elif sig == 'sys1_exit':
                trend = 'exit'
            
            if trend == 'buy':
                trend_counts['buy'] += 1
            elif trend == 'exit':
                trend_counts['exit'] += 1
            else:
                trend_counts['none'] += 1
                
        print("Trend counts in candles:", trend_counts)
        
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_api()
