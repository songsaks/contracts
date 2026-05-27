import sys
sys.stdout.reconfigure(encoding='utf-8')
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

print("Starting chrome...")
driver = webdriver.Chrome(options=options)

try:
    print("Navigating to stocks/crypto-trading/...")
    driver.get("http://127.0.0.1:8000/stocks/crypto-trading/")
    
    # Inject localStorage configuration and reload
    print("Injecting configuration...")
    driver.execute_script("localStorage.setItem('crypto_fib_on', '1');")
    driver.execute_script("localStorage.setItem('crypto_smc_on', '1');")
    driver.refresh()

    # Wait for the page and charts to render
    print("Waiting 5 seconds...")
    time.sleep(5)

    print("Title of page:", driver.title)
    
    # Check console logs
    print("--- CONSOLE LOGS ---")
    logs = driver.get_log('browser')
    for log in logs:
        print(f"[{log['level']}] {log['message']}")
    print("--------------------")
    
finally:
    driver.quit()
