import platform

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait,Select
from selenium.webdriver.support import expected_conditions as EC

import datetime

import time



def init():
	options = Options()
	options.add_argument("--headless")
	options.add_argument("--disable-dev-shm-usage"); # overcome limited resource problems
	options.add_argument('--window-size=1920,1080')
	options.add_argument("--no-sandbox")
	options.add_argument("--disable-gpu")
	options.add_experimental_option("excludeSwitches", ["enable-automation"])
	options.add_experimental_option('useAutomationExtension', False)
	
	options.add_experimental_option("prefs", {"profile.password_manager_enabled": False, "credentials_enable_service": False})
	if(platform.system()=='Windows'):
		options.binary_location = "chrome-win64/chrome.exe"
	elif(platform.system()=='Linux'):
		options.binary_location = "chrome-linux64/chrome"

 
	


	if(platform.system()=='Windows'):
		driver = webdriver.Chrome(options=options, executable_path="driver/chromedriver.exe",)
	elif(platform.system()=='Linux'):
		driver = webdriver.Chrome(options=options, executable_path="chromedriver-linux64/chromedriver",)
	
 
	driver.delete_all_cookies() #清cookie
 
 
	return driver


weekdays={'0':'Mon','1':'Tue','2':'Wed','3':'Thu','4':'Fri','5':'Sat','6':'Sun'}

months={'1':'Jan','2':'Feb','3':'Mar','4':'Apr','5':'May','6':'Jun','7':'Jul','8':'Aug','9':'Sep','10':'Oct','11':'Nov','12':'Dec'}




def main():
    now=datetime.datetime.now()


    result=init()
 
 
    driver=result


    
    driver.get("https://leetcode.com/problemset/")
    
    with open('aaa.html','w+',encoding='UTF-8') as o:
        o.write(driver.find_element(By.TAG_NAME, 'body').get_attribute('innerHTML'))
    
    print("get to leetcode complete")

    time.sleep(0.5)

    
    
    question=driver.find_element(By.XPATH,f"//a[@data-value='{weekdays[str(now.weekday())]} {months[str(now.month)]} {str(now.day).zfill(2)} {str(now.year)} 00:00:00 GMT+0000 (Coordinated Universal Time)']")
    #question=driver.find_element(By.XPATH,f"//a[@data-value='{weekdays[str(now.weekday())]} {months[str(now.month)]} {str(now.day).zfill(2)} {str(now.year)} 00:00:00 GMT+0800 (台北標準時間)']") #windows
    
    
    print(question.get_attribute('href'))
    
    driver.get(question.get_attribute('href'))

    time.sleep(0.5)
    
    with open('bbb.html','w+',encoding='UTF-8') as o:
    	o.write(driver.page_source)
    
    title=driver.title
    print(title[0:title.find('-')])
    return str(now.month)+"/"+str(now.day)+" "+title


#main()