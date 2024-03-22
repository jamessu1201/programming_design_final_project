# -*- coding:utf-8 -*-
import json
from twocaptcha import TwoCaptcha

import platform

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait,Select
from selenium.webdriver.support import expected_conditions as EC

import time

def solve(key,solver,driver):
  try:
    result = solver.recaptcha(
      sitekey=key,
      url=driver.current_url,
      version="v2",
    )
  except Exception as e:
    return "fail"
    
  return result




def init():
	options = Options()
	options.add_argument("--headless")
	options.add_argument("--disable-dev-shm-usage") # overcome limited resource problems
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

 
	try:
		with open("private/two_captcha.txt",'r') as key_file:
			key=key_file.read()
	except:
		return "請去https://2captcha.com/建立api金鑰"

	try:
		with open("private/json/account.json","r") as js:
			data=json.load(js)
	except:
		return "請建立帳號密碼"
	


	solver=TwoCaptcha(apiKey=key)

	if(platform.system()=='Windows'):
		s=Service("driver/chromedriver.exe")
	elif(platform.system()=='Linux'):
		s=Service("chromedriver-linux64/chromedriver")
 
	driver = webdriver.Chrome(options=options,service=s,)
	
 
	driver.delete_all_cookies() #清cookie
	
	print("initiate complete.")
 
	return driver,solver,data



def login(driver,solver,data):
    
	username=driver.find_element(By.XPATH,"//input[@id='username']")
	password=driver.find_element(By.XPATH,"//input[@id='password']")

	username.send_keys(data['accounts'][0])
	password.send_keys(data['passwords'][0])					#input username and password


	captcha=driver.find_element(By.XPATH,"//div[@class='g-recaptcha']")

	site_key=captcha.get_attribute("data-sitekey")

	result= solve(site_key,solver,driver)

	if(result=="fail"):
		return "fail to solve recaptcha"

	response=driver.find_element(By.XPATH,"//textarea[@class='g-recaptcha-response']")

	driver.execute_script("arguments[0].style.display = 'inline-block';", response)

	response.send_keys(result['code'])

	submit=driver.find_element(By.XPATH,"//button[@name='submit']")

	submit.click()
 
	if("Authentication Succeeded with Warnings" in driver.page_source):
	    driver.find_element(By.XPATH,"//button[@name='continue']").click()
     
     
	print('login complete.')





def attend(driver,attend_pwd=None):
	

	if(attend_pwd!=None):
		try:
			attend_site=driver.find_element(By.XPATH,"//table[@class='generaltable attwidth boxaligncenter']//tr[@class='lastrow']").find_element(By.XPATH,"//a[contains(text(), '登記出缺席')]")
		except:
			driver.quit()
			return "已點名或此課程尚未開啟點名"

		attend_link=attend_site.get_attribute("href")

		driver.get(attend_link)
     
		password=driver.find_element(By.XPATH,"//input[@id='id_studentpassword']")
		password.send_keys(attend_pwd)

	driver.find_element(By.XPATH,"//input[contains(@id, 'id_status_')]").click()
 
	driver.find_element(By.XPATH,"//input[@name='submitbutton']").click()

	try:
		table=driver.find_element(By.XPATH,"//table[@class='generaltable attwidth boxaligncenter']//tr[@class='lastrow']")
	except:
		return "密碼錯誤，未點名"

	return "點名成功"



 

def attend_main(course_name,attend_pwd):
 
	result=init()
	if(type(result)==tuple()):
		print('yes')
	print(type(result))
 
	driver=result[0]
	solver=result[1]
	data=result[2]

#----------------------------   init complete
	print("ready to get driver.")
 



	driver.get("https://ecourse2.ccu.edu.tw/")

	
	print("driver get complete.")

	login_site=driver.find_element(By.XPATH,"//a[contains(text(), 'CCU單一登入')]")

	link=login_site.get_attribute("href")

	driver.get(link)	#to login site


	login(driver,solver,data)	#do login


	
	
	try:																#check whether id is correct
		page=driver.find_element(By.XPATH,"//div[@id='page']")
	except:
		driver.quit()
		return "帳號或密碼錯誤"
	
	

	try:																				#check whether course name is exist
		course=page.find_element(By.XPATH,f"//a[contains(text(), '{course_name}')]")
	except:
		driver.quit()
		return "未知課程，請重新輸入"



	link=course.get_attribute("href")

	id=link[link.find('=')+1:]

	driver.get("https://ecourse2.ccu.edu.tw/local/courseutility/attendance.php?id="+id) #get into attend site
 
	#-------------------------------------------- 
	# found course


	return attend(driver,attend_pwd)  #do attend
	





def attend_with_link(link):
    
	result=init()

	print(result)
 
	driver=result[0]
	solver=result[1]
	data=result[2]

#----------------------------   init complete
	
	driver.get(link)
 
	login_site=driver.find_element(By.XPATH,"//a[contains(text(), 'CCU單一登入')]")

	link=login_site.get_attribute("href")

	driver.get(link)	#to login site
 
	login(driver,solver,data)
 
	if("這個點名時段現在不能自己點名。" in driver.page_source):
		return "這個點名時段現在不能自己點名。"
	else:
		return attend(driver)


attend_main('aaa','aaa')
