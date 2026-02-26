import sys
import os

# mock django settings
sys.path.append('d:\DjangoProjects\contracts')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

from stocks.utils import get_stock_data, analyze_with_ai

data = get_stock_data("AIT.BK")
history = data['history']
sma_200 = history['Close'].rolling(window=200).mean().iloc[-1] if len(history) >= 200 else 0
print("SMA 200:", sma_200)
print("Data len:", len(history))

