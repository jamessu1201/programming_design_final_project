import platform

import requests

import datetime

import time

import json


weekdays={'0':'Mon','1':'Tue','2':'Wed','3':'Thu','4':'Fri','5':'Sat','6':'Sun'}

months={'1':'Jan','2':'Feb','3':'Mar','4':'Apr','5':'May','6':'Jun','7':'Jul','8':'Aug','9':'Sep','10':'Oct','11':'Nov','12':'Dec'}


link=''



def get_result():
    
    url="https://leetcode.com/graphql/"
    headers = {'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'}

    params={"query":"\n query questionOfToday {\n activeDailyCodingChallengeQuestion {\n date\n userStatus\n link \n question { \n acRate \n difficulty \n freqBar \n frontendQuestionId: questionFrontendId \n isFavor \n paidOnly: isPaidOnly \n status \n title \n titleSlug \n hasVideoSolution \n hasSolution \n topicTags { \n name  \n id \n slug  \n } \n } \n } \n }\n   "}
    return requests.get(url,params=params,headers=headers)


def get_link():
    print("link:",link)
    return link



def main():
    
    global link
    
    now=datetime.datetime.now()
    
    result=get_result()
    
    print(result.request.url)

    j=result.json()

    question=j['data']['activeDailyCodingChallengeQuestion']['question']
    
    print(question)

    title=question['title']
    
    link="https://leetcode.com"+j['data']['activeDailyCodingChallengeQuestion']['link']+"?envType=daily-question&envId="+f"{now.year}-{now.month}-{now.day}"
    print(link)

    id=question['frontendQuestionId']

    print(id+'. '+title)
    
    title=id+'. '+title
    
    return str(now.month)+"/"+str(now.day)+" "+title,question['difficulty']

print(main())
# print(get_link())