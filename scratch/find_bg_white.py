import io

with io.open('stocks/templates/stocks/portfolio.html', encoding='utf-8', errors='ignore') as f:
    for i, line in enumerate(f):
        if 'background:' in line or 'background-color:' in line:
            if any(x in line for x in ['#fff', 'white', '#ffffff', '255,255,255', '255, 255, 255']):
                print(f"{i+1}: {line.strip()}")
