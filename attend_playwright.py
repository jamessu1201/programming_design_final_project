# -*- coding:utf-8 -*-
import asyncio
import logging
from playwright.async_api import async_playwright

import json
from twocaptcha import TwoCaptcha
import concurrent.futures

logger = logging.getLogger(__name__)

async def solve(key,solver,url):
    loop=asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        result=await loop.run_in_executor(pool,lambda:solver.recaptcha(sitekey=key,url=url,version="v2",))
        return result

async def init():
    try:
        with open("private/two_captcha.txt",'r') as key_file:
            key=key_file.read()
    except FileNotFoundError:
        return "請去https://2captcha.com 建立api金鑰"

    try:
        with open("private/json/account.json","r") as js:
            data=json.load(js)
    except (FileNotFoundError, json.JSONDecodeError):
        return "請建立帳號密碼"

    solver=TwoCaptcha(apiKey=key)

    logger.info("initiate complete.")

    return solver,data


async def login(result,page):
    
    solver,data=result

    await page.locator("xpath=//input[@id='username']").fill(data['accounts'][0])
    await page.locator("xpath=//input[@id='password']").fill(data['passwords'][0])
    
    key=await page.locator("xpath=//div[@class='g-recaptcha']").get_attribute("data-sitekey")
        
    result=await solve(key,solver,page.url)
        
    if(result=="fail"):
        return "fail to solve recaptcha"

    logger.info("captcha solved")
        
        
        
    await page.evaluate("""(code) => {
            var selector = document.querySelector('.g-recaptcha-response');
            selector.style.display='inline-block';
            selector.innerHTML=code;
        }""",result['code']) 
        
        
    await page.locator("xpath=//button[@name='submit']").click()
        
    if("Authentication Succeeded with Warnings" in await page.content()):
        await page.locator("xpath=//button[@name='continue']").click()
        
    if("帳號或密碼有誤" in await page.content()):
        return "帳號或密碼有誤"
    
    logger.info("login complete")
    return "sus"
    
    

async def attend(page,attend_pwd=None):
    
    if(attend_pwd!=None):
        locate=page.locator("xpath=//table[@class='generaltable attwidth boxaligncenter']//tr[@class='lastrow']")
        if(await locate.locator("xpath=//a[contains(text(), '登記出缺席')]").is_visible()):
            attend_site=await locate.locator("xpath=//a[contains(text(), '登記出缺席')]").get_attribute("href")
        else:
            return "已點名或此課程尚未開啟點名"

        await page.goto(attend_site)
        
        await page.locator("xpath=//input[@id='id_studentpassword']").fill(attend_pwd)
        
    await page.get_by_label("出席Present").click()
    await page.locator("xpath=//input[@name='submitbutton']").click()
    
    logger.info("attend complete")
    return "點名成功"


async def attend_main(course_name,attend_pwd):
    
        p=await async_playwright().start()
        result=await init()

        if(type(result)==str):
            return result

        browser=await p.chromium.launch()
        page=await browser.new_page()
        logger.info("ready go to site")
        await page.goto("https://ecourse2.ccu.edu.tw/")

        await asyncio.sleep(1)

        login_site=await page.get_by_role("link", name="CCU單一登入").get_attribute("href")
        await page.goto(login_site)

        await asyncio.sleep(1)

        check=await login(result,page)

        if(check!="sus"):
            await page.close()
            return check

        try:
            course = await page.locator("a", has_text=course_name).get_attribute("href")
        except Exception as e:
            logger.warning("找不到課程: %s", e)
            await page.close()
            return "未知課程或有複數個與此關鍵字相同的課程，請重新輸入"

        await page.goto("https://ecourse2.ccu.edu.tw/local/courseutility/attendance.php?id="+course[course.find('=')+1:])

        result=await attend(page,attend_pwd)
        await p.stop()

        return result