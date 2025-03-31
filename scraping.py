from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time

# Basic setup
options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1920,1080')

# Uncomment if you need proxy
# options.add_argument('--proxy-server=your_proxy:port')

driver = webdriver.Chrome(options=options)

try:
    # Load page
    driver.get("https://www.boerse-frankfurt.de/equity/sappi")
    print("Page loading...")
    
    # Simple cookie handling (if exists)
    try:
        time.sleep(2)  # Brief pause for cookie dialog
        driver.find_element(By.ID, "onetrust-accept-btn-handler").click()
        print("Cookies accepted")
    except:
        print("No cookie popup found")
    
    # Wait for target div - with multiple possible class combinations
    wait = WebDriverWait(driver, 20)
    target_div = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt, " +
                          "div.col-12.ar-col-lg-1-3, " +
                          "div[class*='ar-col-lg-1-3']")
    ))
    
    # Scroll to make sure it's fully loaded
    driver.execute_script("arguments[0].scrollIntoView(true);", target_div)
    time.sleep(1)
    
    # Get the content
    print("Found target div. Content:")
    print(target_div.text)
    
    # Save proof
    target_div.screenshot("target_element.png")
    print("Saved screenshot of element as 'target_element.png'")

except Exception as e:
    print(f"Error: {e}")
    driver.save_screenshot("error.png")
    print("Saved screenshot of error as 'error.png'")

finally:
    driver.quit()
    print("Browser closed")
