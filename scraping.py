from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import os
import time
import traceback

# Set environment variables if needed
os.environ['CURL_CA_BUNDLE'] = ''

# Configure Chrome options
options = Options()
options.add_argument('--no-sandbox')
options.add_argument('--remote-debugging-port=9222')
options.add_argument('--headless')
options.add_argument('--disable-gpu')
options.add_argument('--ignore-certificate-errors')
options.add_argument('--disable-dev-shm-usage')  # Add this to help with memory issues in containers
options.add_argument('--window-size=1920,1080')  # Set a larger window size

# Chrome might be blocking the site through the proxy - let's make it optional
# If you need the proxy, uncomment these lines
# proxy = {
#     'http': f'http://<redacted>:24',
#     'https': f'http://<redacted>:24'
# }
# options.add_argument(f'--proxy-server={proxy["http"]}')

# Path to your chromedriver executable
chromedriver_path = '/mnt/chrome/chromedriver-linux64/chromedriver'

# Set up the ChromeDriver service
service = Service(executable_path=chromedriver_path)

try:
    # Set up the Selenium WebDriver
    driver = webdriver.Chrome(service=service, options=options)
    
    # Define the website URL
    url = "https://www.boerse-frankfurt.de/equity/sappi"
    
    print(f"Navigating to {url}")
    # Open the website using Selenium
    driver.get(url)
    
    # Wait for the page to load completely
    print("Waiting for page to load...")
    WebDriverWait(driver, 30).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    print("Page loaded successfully")
    
    # Save the page source to debug
    with open("page_source.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print("Saved page source to page_source.html for debugging")
    
    # Print the title to verify we're on the right page
    print(f"Page title: {driver.title}")
    
    # Try to handle cookies if they appear
    try:
        print("Looking for cookie consent dialog...")
        cookie_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.ID, "onetrust-accept-btn-handler"))
        )
        print("Cookie button found, clicking...")
        cookie_button.click()
        time.sleep(2)
        print("Cookies accepted")
    except Exception as e:
        print(f"No cookie banner found or couldn't be accepted: {e}")
    
    # Ensure JavaScript has fully loaded by waiting for a key element
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".quotation-box, .market-data, .stockdata"))
        )
        print("Key page elements detected")
    except Exception as e:
        print(f"Key page elements not found: {e}")
    
    # Scroll slowly down the page to ensure all content loads
    print("Scrolling page to load dynamic content...")
    for i in range(3):
        driver.execute_script(f"window.scrollTo(0, {i * 500});")
        time.sleep(1)
    
    # Wait a bit longer for all dynamic content to load
    time.sleep(5)
    
    # Execute JavaScript to check if there are any loading spinners active
    loading_spinners = driver.execute_script("""
        return document.querySelectorAll('.app-loading-spinner-parent').length;
    """)
    print(f"Found {loading_spinners} loading spinners on the page")
    
    # Try different selectors for the target element
    print("Searching for target element...")
    selectors = [
        "div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt",
        ".col-12.ar-col-lg-1-3",
        ".quotation-box",
        ".widget.quotation-box",
        ".market-data",
        ".stockdata"
    ]
    
    element_found = False
    for selector in selectors:
        try:
            print(f"Trying selector: {selector}")
            element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
            )
            print(f"Found element with selector: {selector}")
            element_text = element.text[:100] + "..." if len(element.text) > 100 else element.text
            print(f"Element text: {element_text}")
            element_found = True
            break
        except Exception as e:
            print(f"Selector {selector} failed: {e}")
    
    if not element_found:
        print("Could not find target element with any selector")
        
        # Try to find any table on the page
        tables = driver.find_elements(By.TAG_NAME, "table")
        print(f"Found {len(tables)} tables on the page")
        
        if tables:
            print("Analyzing first table found:")
            first_table = tables[0]
            rows = first_table.find_elements(By.TAG_NAME, "tr")
            print(f"Found {len(rows)} rows in first table")
            
            for idx, row in enumerate(rows[:3]):  # First 3 rows
                cells = row.find_elements(By.TAG_NAME, "td")
                cell_texts = [cell.text for cell in cells]
                print(f"Row {idx+1}: {cell_texts}")
    
    # Parse with BeautifulSoup for analysis
    print("Parsing page with BeautifulSoup...")
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    # Get all widgets on the page
    widgets = soup.select(".widget")
    print(f"Found {len(widgets)} widgets on the page")
    
    # Look for any table in the page
    tables = soup.find_all("table")
    print(f"Found {len(tables)} tables with BeautifulSoup")
    
    # If tables exist, analyze the first one
    if tables:
        print("Analyzing first table:")
        first_table = tables[0]
        rows = first_table.find_all("tr")
        print(f"Table has {len(rows)} rows")
        
        for idx, row in enumerate(rows[:3]):  # First 3 rows
            cells = row.find_all("td")
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            print(f"Row {idx+1}: {cell_texts}")
            
    # Check if there's a div with class containing both "col-12" and "ar-col-lg-1-3"
    target_divs = [div for div in soup.find_all("div") 
                  if div.get("class") and "col-12" in div.get("class") and "ar-col-lg-1-3" in div.get("class")]
    
    print(f"Found {len(target_divs)} divs with both 'col-12' and 'ar-col-lg-1-3' classes")
    
    # Get the actual class names of some key divs to see what's available
    print("\nExamining div class names:")
    for idx, div in enumerate(soup.find_all("div", class_=True)[:20]):  # First 20 divs with classes
        class_names = div.get("class")
        if any(c for c in class_names if "col-" in c or "widget" in c):
            print(f"Div {idx+1}: classes={class_names}")

except Exception as e:
    print(f"Main exception occurred: {e}")
    print("Traceback:")
    traceback.print_exc()
finally:
    # Close the WebDriver
    try:
        if 'driver' in locals():
            driver.quit()
            print("WebDriver closed successfully")
    except Exception as e:
        print(f"Error closing WebDriver: {e}")

print("Script completed")
