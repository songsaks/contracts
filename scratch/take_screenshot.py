import sys
sys.stdout.reconfigure(encoding='utf-8')
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1200,800')

print("Starting chrome...")
driver = webdriver.Chrome(options=options)

try:
    print("Navigating to page...")
    driver.get("http://127.0.0.1:8000/stocks/crypto-trading/")
    
    # Inject localStorage configuration and reload
    print("Injecting configuration...")
    driver.execute_script("localStorage.setItem('crypto_fib_on', '1');")
    driver.execute_script("localStorage.setItem('crypto_smc_on', '1');")
    driver.refresh()
    
    # Wait for the page and charts to render
    print("Waiting 8 seconds...")
    time.sleep(8)
    
    # Take screenshot
    screenshot_path = 'scratch/rendered_chart.png'
    driver.save_screenshot(screenshot_path)
    print("Screenshot saved to:", screenshot_path)
    
finally:
    driver.quit()
