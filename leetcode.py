import platform

import requests

import datetime

import time

import json


weekdays={'0':'Mon','1':'Tue','2':'Wed','3':'Thu','4':'Fri','5':'Sat','6':'Sun'}

months={'1':'Jan','2':'Feb','3':'Mar','4':'Apr','5':'May','6':'Jun','7':'Jul','8':'Aug','9':'Sep','10':'Oct','11':'Nov','12':'Dec'}

link=''

with open('private/scrapingbee.txt') as read:
    api_key=read.read()



def get_result():
    
    url="https://app.scrapingbee.com/api/v1/"
    params={"api_key":api_key,"url":"https://leetcode.com/graphql/?query=%0A+query+questionOfToday+%7B%0A+activeDailyCodingChallengeQuestion+%7B%0A+date%0A+userStatus%0A+link+%0A+question+%7B+%0A+acRate+%0A+difficulty+%0A+freqBar+%0A+frontendQuestionId%3A+questionFrontendId+%0A+isFavor+%0A+paidOnly%3A+isPaidOnly+%0A+status+%0A+title+%0A+titleSlug+%0A+hasVideoSolution+%0A+hasSolution+%0A+topicTags+%7B+%0A+name++%0A+id+%0A+slug++%0A+%7D+%0A+%7D+%0A+%7D+%0A+%7D%0A+++","render_js":"true"}
    return requests.get(url,params=params)


def get_link():
    print("link:",link)
    return link



def main():
    
    global link
    
    now=datetime.datetime.now()
    
    result=get_result()
    
    print(result.request.url)
    print(result)

    j=result.json()

    try:
        question=j['data']['activeDailyCodingChallengeQuestion']['question']
    except:
        return "出現錯誤QQ"
    
    print(question)

    title=question['title']
    
    link="https://leetcode.com"+j['data']['activeDailyCodingChallengeQuestion']['link']+"?envType=daily-question&envId="+f"{now.year}-{now.month}-{now.day}"
    print(link)

    id=question['frontendQuestionId']

    print(id+'. '+title)
    
    title=id+'. '+title
    
    return str(now.month)+"/"+str(now.day)+" "+title,question['difficulty']

print(main())
print(get_link())