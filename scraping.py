from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import os
import time

# Set environment variables if needed
os.environ['CURL_CA_BUNDLE'] = ''

# Configure Chrome options
options = webdriver.ChromeOptions()
options.add_argument('--no-sandbox')
options.add_argument('--remote-debugging-port=9222')
options.add_argument('--headless')  # Run in headless mode
options.add_argument('--disable-gpu')
options.add_argument('--ignore-certificate-errors')

# If you need to use a proxy
proxy = {
    'http': f'http://<redacted>:24',
    'https': f'http://<redacted>:24'
}
options.add_argument(f'--proxy-server={proxy["http"]}')

# Path to your chromedriver executable
chromedriver_path = '/mnt/chrome/chromedriver-linux64/chromedriver'  # Update with your path

# Set up the ChromeDriver service
service = Service(executable_path=chromedriver_path)

# Set up the Selenium WebDriver
driver = webdriver.Chrome(service=service, options=options)

# Define the website URL
url = "https://www.boerse-frankfurt.de/equity/sappi"

try:
    # Open the website using Selenium
    driver.get(url)
    
    # Wait for the page to load completely
    WebDriverWait(driver, 20).until(
        lambda driver: driver.execute_script("return document.readyState") == "complete"
    )
    
    # Wait for cookie banner to appear and accept it if it exists
    try:
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.ID, "onetrust-accept-btn-handler"))
        )
        accept_button = driver.find_element(By.ID, "onetrust-accept-btn-handler")
        accept_button.click()
        time.sleep(1)
    except:
        print("No cookie banner found or couldn't be accepted")
    
    # Key fix: Wait explicitly for the target element to be visible
    # The class names in your original script had spaces, which is incorrect syntax for class selection
    WebDriverWait(driver, 20).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt"))
    )
    
    # Scroll to ensure all dynamic content loads
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight/3);")
    time.sleep(2)
    
    # Parse the page source with BeautifulSoup
    soup = BeautifulSoup(driver.page_source, "html.parser")
    
    # Extract information using BeautifulSoup with correct class names (spaces replaced with dots for CSS selector)
    class1 = soup.select_one("div.col-12.ar-col-lg-1-3.ar-mr-lg.ar-mt")
    
    if class1:
        print("Found the target element!")
        class2 = class1.select_one("div.widget.app-loading-spinner-parent.ar-p")
        if class2:
            print("Found inner widget element!")
            rows = class2.find_all('tr')
            if rows:
                print(f"Found {len(rows)} rows of data")
                for idx, row in enumerate(rows, start=1):
                    columns = row.find_all('td')
                    column_text = [col.get_text(strip=True) for col in columns]
                    print(f"Row {idx}: {column_text}")
            else:
                print("No table rows found within the widget")
        else:
            print("Could not find the inner widget element. Page structure might have changed.")
            
            # Debug: Print the HTML of the found element to understand its structure
            print("HTML of target element:")
            print(class1.prettify())
    else:
        print("Could not find the specified element on the page.")
        
        # Debug: Print selectors that did match
        all_col12 = soup.select("div[class*='col-12']")
        print(f"Found {len(all_col12)} elements with 'col-12' in their class.")
        
except Exception as e:
    print("Entered in Exception ::>> Not found Instrument")
    print(f"Exception >>>>>>>>>>>>>>>>>{e}")
finally:
    # Close the WebDriver
    driver.quit()
    
print("Done")
