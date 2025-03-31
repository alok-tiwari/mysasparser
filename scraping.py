from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time

# Configure Chrome options
options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--headless')  # Remove this if you want to see the browser
options.add_argument('--disable-gpu')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--window-size=1920,1080')
options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Path to chromedriver
chromedriver_path = '/mnt/chrome/chromedriver-linux64/chromedriver'
service = Service(executable_path=chromedriver_path)

try:
    # Initialize driver
    driver = webdriver.Chrome(service=service, options=options)
    
    # Load the page
    url = "https://www.boerse-frankfurt.de/equity/sappi"
    print(f"Navigating to {url}")
    driver.get(url)
    
    # Wait for page to load
    WebDriverWait(driver, 30).until(
        EC.presence_of_element_located((By.TAG_NAME, 'body'))
    print("Page loaded successfully")
    
    # Handle cookie consent with more robust waiting
    try:
        # First wait for the cookie dialog frame to be present
        WebDriverWait(driver, 10).until(
            EC.frame_to_be_available_and_switch_to_it((By.ID, "sp_message_iframe_764281"))
        )
        
        # Then wait for the accept button
        accept_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Accept all')]"))
        )
        accept_button.click()
        print("Cookies accepted")
        
        # Switch back to main content
        driver.switch_to.default_content()
    except Exception as e:
        print(f"Cookie handling skipped: {str(e)[:100]}...")
    
    # Wait for dynamic content to load
    print("Waiting for dynamic content...")
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.quotation-box"))
    )
    
    # Scroll to ensure content loads
    print("Scrolling to load content...")
    driver.execute_script("window.scrollTo(0, 500)")
    time.sleep(2)
    
    # Find the specific div you're targeting
    print("Looking for target div...")
    target_div = WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt"))
    )
    
    # Get all matching divs (in case there are multiple)
    all_target_divs = driver.find_elements(By.CSS_SELECTOR, "div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt")
    print(f"Found {len(all_target_divs)} matching div elements")
    
    # Print content of each found div
    for i, div in enumerate(all_target_divs, 1):
        print(f"\nDiv {i} content:")
        print(div.text)
        print("-" * 50)
    
    # Alternative: If you need specific data points, you can find child elements
    if all_target_divs:
        first_div = all_target_divs[0]
        # Example: Find all spans within the div
        spans = first_div.find_elements(By.TAG_NAME, "span")
        print(f"\nFound {len(spans)} span elements in first div")
        for span in spans[:5]:  # Print first 5 spans
            print(span.text)
    
except Exception as e:
    print(f"Error occurred: {str(e)[:200]}")
    # Save screenshot for debugging
    driver.save_screenshot('error_screenshot.png')
    print("Saved screenshot to error_screenshot.png")
finally:
    if 'driver' in locals():
        driver.quit()
        print("WebDriver closed")

print("Script completed")
