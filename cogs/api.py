# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import asyncio
import requests
import random
import datetime
from bs4 import BeautifulSoup
import os
import re
import json
from dateutil import parser
import base64



weapons={'匕首':'Dagger','黑刀':'Black Knife','格擋匕首':'Parrying Dagger','慈悲短劍':'Misericorde','逆刺':'Reduvia','結晶小刀':'Crystal Knife','慶典小鐮刀':'Celebrant-s Sickle','輝石克力士':'Glintstone Kris','蠍尾針':'Scorpion-s Stinger','單刃小刀':'Great Knife','脇差':'Wakizashi','五指劍':'Cinquedea','象牙小鐮刀':'Ivory Sickle','染血短刀':'Bloodstained Dagger','黃銅短刀':'Erdsteel Dagger','使命短刀':'Blade of Calling','長劍':'Longsword','短劍':'Short Sword','闊劍':'Broadsword','君王軍直劍':'Lordsworn-s Straight Sword','拉茲利輝石劍':'Lazuli Glintstone Sword','結晶劍':'Crystal Sword','卡利亞騎士劍':'Carian Knight-s Sword','夜與火之劍':'Sword of Night and Flame','托莉娜劍':'Sword of St Trina','黃金墓碑':'Golden Epitaph','手杖劍':'Cane Sword','儀式直劍':'Ornamental Straight Sword','老舊直劍':'Weathered Straight Sword','戰鷹爪形劍':'Warhawk-s Talon','權貴細身劍':'Noble-s Slender Sword','歐赫寶劍':'Regalia of Eochaid','米凱拉騎士劍':'Miquellan Knight-s Sword','秘文劍':'Coded Sword','腐敗結晶劍':'Rotten Crystal Sword','失鄉騎士大劍':'Banished Knight-s Greatsword','混種大劍':'Bastard Sword','大劍':'Claymore','焰形大劍':'Flamberge','石像鬼黑劍':'Gargoyle-s Blackblade','石像鬼大劍':'Gargoyle-s Greatsword','騎士大劍':'Knight-s Greatsword','君王軍大劍':'Lordsworn-s Greatsword','瑪雷家行刑劍':'Marais Executioner-s Sword','滅洛斯劍':'Sword of Milos','暗月大劍':'Dark Moon Greatsword','褻瀆聖劍':'Blasphemous Blade','白王劍':'Alabaster Lord-s Sword','奧陶琵斯大劍':'Ordovis-s Greatsword','黃金律法大劍':'Golden Order Greatsword','神軀化劍':'Sacred Relic Sword','分岔大劍':'Forked Greatsword','赫芬尖塔劍':'Helphen-s Steeple','死亡鉤棒':'Death-s Poker','鐵制大劍':'Iron Greatsword','緊密孿生劍':'Inseparable Sword','巨劍':'Greatsword',
'看門犬大劍':'Watchdog-s Greatsword','瑪利喀斯的黑劍':'Maliketh-s Black Blade','山妖黃金劍':'Troll-s Golden Sword','雙手巨劍':'Zweihander','碎星大劍':'Starscourge Greatsword','王室巨劍':'Royal Greatsword','狩獵神祇大劍':'Godslayer-s Greatsword','遺跡大劍':'Ruins Greatsword','劍骸大劍':'Grafted Blade Greatsword','山妖騎士劍':'Troll Knight-s Sword','蟻刺細劍':'Antspur Rapier','刺劍':'Estoc','結冰針':'Frozen Needle','權貴刺劍':'Noble-s Estoc','細劍':'Rapier','尊腐騎士劍':'Cleanrot Knight-s Sword','羅傑爾刺劍':'Rogier-s Rapier','鮮血旋流':'Bloody Helice','神皮縫針':'Godskin Stitcher','大重劍':'Great Epee','龍王岩劍':'Dragon King-s Cragblade','彎刃大刀':'Falchion','短彎刀':'Scimitar','巨型刀':'Grossmesser','螳臂刀':'Mantis Blade','剝屍曲劍':'Scavenger-s Curved Sword','鉤劍':'Shotel','日蝕鉤劍':'Eclipse Shotel','艾絲緹薄翼':'Wing of Astel','諾克斯流體劍':'Nox Flowing Sword','蛇神彎刀':'Serpent-God-s Curved Sword','賽施爾長刀':'Shamshir','山賊彎刀':'Bandit-s Curved Sword','流水曲劍':'Flowing Curved Sword','熔岩刀':'Magma Blade','獸人彎刀':'Beastman-s Curved Sword','黑王大劍':'Onyx Lord-s Greatsword','騎兵馬刀':'Dismounter','獵犬長牙':'Bloodhound-s Fang','土龍鱗劍':'Magma Wyrm-s Scalesword','薩米爾彎刀':'Zamor Curved Sword','惡兆之子大刀':'Omen Cleaver','習武修士火紋刀':'Monk-s Flameblade','獸人大彎刀':'Beastman-s Cleaver','蒙葛特咒劍':'Morgott-s Cursed Sword','打刀':'Uchigatana','長牙':'Nagakiba','瑪蓮妮亞的義手刀':'Hand of Malenia','鐵隕石刀':'Meteoric Ore Blade','屍山血海':'Rivers of Blood','名刀月隱':'Moonveil','龍鱗刀':'Dragonscale Blade','蛇骨刀':'Serpentbone Blade','雙頭劍':'Twinblade','神皮剝制劍':'Godskin Peeler','騎士雙頭劍':'Twinned Knight Swords','艾琉諾拉雙頭刀':'Eleonora-s Poleblade','石像鬼雙頭劍':'Gargoyle-s Twinblade',
'石像鬼黑雙頭劍':'Gargoyle-s Black Blades','錘矛':'Mace','棍棒':'Club','彎曲棍棒':'Curved Club','戰鎬':'Warpick','晨星錘':'Morning Star','梵雷的花束':'Varre-s Bouquet','獸牙棒':'Spiked Club','石槌':'Hammer','習武修士火紋錘':'Monk-s Flamemace','眾使者的笛子':'Envoy-s Horn','百智權杖':'Scepter of the All-Knowing','諾克斯流體錘':'Nox Flowing Hammer','戒指指頭':'Ringed Finger','石棍棒':'Stone Club','瑪莉卡的石槌':'Marika-s Hammer','大棍棒':'Large Club','大角槌':'Greathorn Hammer','鬥技錘':'Battle Hammer','巨型錘矛':'Great Mace','彎曲大棍棒':'Curved Great Club','慶典大頭蓋骨':'Celebrant-s Skull','十字鎬':'Pickaxe','獸爪大錘':'Beastclaw Greathammer','眾使者的長笛子':'Envoy-s Long Horn','尊容燭臺':'Cranial Vessel Candlestand','巨星錘':'Great Stars','砌石槌':'Brick Hammer','吞世權杖':'Devourer-s Scepter','腐敗鬥技錘':'Rotten Battle Hammer','連枷':'Flail','鐵塊連枷':'Chainlink Flail','黑夜騎兵連枷':'Nightrider Flail','棄子的繁星':'Bastard-s Stars','家人頭連枷':'Family Heads','戰斧':'Battle Axe','分岔手斧':'Forked Hatchet','手斧':'Hand Axe','顎齒斧':'Jawbone Axe','鐵柴刀':'Iron Cleaver','波紋劍':'Ripple Blade','慶典柴刀':'Celebrant-s Cleaver','凍殼斧':'Icerind Hatchet','高地斧':'Highland Axe','活祭品斧':'Sacrificial Axe','羅澤司的斧':'Rosus- Axe','風暴鷹斧':'Stormhawk Axe','歪柄斧':'Warped Axe','巨斧':'Greataxe','惡兆獵人大柴刀':'Great Omenkiller Cleaver','葛瑞克的王斧':'Axe of Godrick','肢解菜刀':'Butchering Knife','展翼大角':'Winged Greathorn','斬身大柴刀':'Executioner-s Greataxe','銹蝕船錨':'Rusted Anchor','弦月斧':'Crescent Moon Axe','石像鬼黑斧':'Gargoyle-s Black Axe','石像鬼大斧':'Gargoyle-s Great Axe','長柄柴刀':'Longhaft Axe','短矛':'Short Spear','矛':'Spear','結晶矛':'Crystal Spear','泥人魚叉':'Clayman-s Harpoon','尊腐騎士矛':'Cleanrot Spear',
'闊頭槍':'Partisan','慶典肋骨釘耙':'Celebrant-s Rib-Rake','長矛':'Pike','燭臺棒':'Torchpole','古蘭桑克斯的雷電':'Bolt of Gransax','十字薙刀':'Cross-Naginata','死亡儀式矛':'Death Ritual Spear','拷問燭臺':'Inquisitor-s Girandole','棘刺棍':'Spiked Spear','鐵制矛':'Iron Spear','腐敗結晶矛':'Rotten Crystal Spear','蒙格溫聖矛':'Mohgwyn-s Sacred Spear','志留亞的樹矛':'Siluria-s Tree','大蛇狩獵矛':'Serpent-Hunter','維克的戰矛':'Vyke-s War Spear','騎兵長矛':'Lance','大樹矛':'Treespear','戟':'Halberd','昆蟲劍刃戟':'Pest-s Glaive','琉森戟':'Lucerne','失鄉騎士戟':'Banished Knight-s Halberd','老將的軍旗':'Commander-s Standard','黑夜騎兵劍刃戟':'Nightrider Glaive','殘缺波紋戟':'Ripple Crescent Halberd','惡兵鋸齒刀':'Vulgar Militia Saw','黃金戟':'Golden Halberd','劍刃戟':'Glaive','羅蕾塔的戰鐮':'Loretta-s War Sickle','守衛劍槍':'Guardian-s Swordspear','惡兵鉤劍':'Vulgar Militia Shotel','龍戟':'Dragon Halberd','石像鬼戟':'Gargoyle-s Halberd','石像鬼黑戟':'Gargoyle-s Black Halberd','大鐮刀':'Scythe','墓地大鐮刀':'Grave Scythe','光環鐮刀':'Halo Scythe','展翼鐮刀':'Winged Scythe','軟鞭':'Whip','荊棘鞭':'Thorned Whip','熔岩燭臺鞭':'Magma Whip Candlestick','霍斯勞花瓣鞭':'Hoslow-s Petal Whip','巨人紅發鞭':'Giant-s Red Braid','軟鞭劍':'Urumi','搏擊手套':'Caestus','棘刺搏擊手套':'Spiked Caestus','接肢飛龍':'Grafted Dragon','鐵球拳套':'Iron Ball','晨星拳套':'Star Fist','拳劍':'Katar','攀附手骨':'Clinging Bone','老將的義足':'Veteran-s Prosthesis','秘文帕塔劍':'Cipher Pata','鉤爪':'Hookclaws','毒蛇牙':'Venomous Fang','獵犬彎爪':'Bloodhound Claws','猛禽鉤爪':'Raptor Talons','主教大火槌':'Prelate-s Inferno Crozier','看門犬錫杖':'Watchdog-s Staff','巨型棍棒':'Great Club','眾使者的扇形笛子':'Envoy-s Greathorn','鬥士大斧':'Duelist Greataxe','葛孚雷的王斧':'Axe of Godfrey',
'大龍爪':'Dragon Greatclaw','化身儀式杖':'Staff of the Avatar','星獸半顎':'Fallingstar Beast Jaw','基薩的刺輪':'Ghiza-s Wheel','粉碎巨人槌':'Giant-Crusher','魔像戟':'Golem-s Halberd','山妖大槌':'Troll-s Hammer','腐敗儀式杖':'Rotten Staff','腐敗大斧':'Rotten Greataxe','火把':'Torch','鋼絲火把':'Steel-Wire Torch','托莉娜燭火':'St Trina-s Torch','靈火火把':'Ghostflame Torch','驅獸火把':'Beast-Repellent Torch','哨兵火把':'Sentry-s Torch','觀星杖':'Astrologer-s Staff','輝石杖':'Glintstone Staff','學院輝石杖':'Academy Glintstone Staff','卡利亞權杖':'Carian Regal Scepter','亞人女王杖':'Demi-Human Queen-s Staff','挖石杖':'Digger-s Staff','亞茲勒的輝石杖':'Azur-s Glintstone Staff','卡利亞輝石杖':'Carian Glintstone Staff','喪失杖':'Staff of Loss','隕石杖':'Meteorite Staff','盧瑟特的輝石杖':'Lusat-s Glintstone Staff','結晶杖':'Crystal Staff','罪人杖':'Staff of the Guilty','死王子杖':'Prince of Death-s Staff','卡利亞輝劍杖':'Carian Glintblade Staff','腐敗結晶杖':'Rotten Crystal Staff','格密爾輝石杖':'Gelmir Glintstone Staff','白金杖':'Albinauric Staff','雙指聖印記':'Finger Seal','狩獵神祇聖印記':'Godslayer-s Seal','巨人聖印記':'Giant-s Seal','碎石聖印記':'Gravel Stone Seal','爪痕聖印記':'Clawmark Seal','黃金律法聖印記':'Golden Order Seal','黃金樹聖印記':'Erdtree Seal','龍饗印記':'Dragon Communion Seal','癲火聖印記':'Frenzied Flame Seal','短弓':'Shortbow','混種小弓':'Misbegotten Shortbow','紅木短弓':'Red Branch Shortbow','豎琴弓':'Harp Bow','複合弓':'Composite Bow','長弓':'Longbow','白金弓':'Albinauric Bow','角弓':'Horn Bow','黃金樹弓':'Erdtree Bow','蛇弓':'Serpent Bow','滑輪弓':'Pulley Bow','黑弓':'Black Bow','獅子大弓':'Lion Greatbow','魔像大弓':'Golem Greatbow','黃金樹大弓':'Erdtree Greatbow','大弓':'Greatbow','士兵弩':'Soldier-s Crossbow',
'輕弩':'Light Crossbow','重弩':'Heavy Crossbow','滑輪弩':'Pulley Crossbow','圓月弩':'Full Moon Crossbow','鋼弩':'Arbalest','克雷普的黑鍵':'Crepus-s Black-Key Crossbow','攜帶型弩炮':'Hand Ballista','壺大炮':'Jar Cannon'}

class Api(commands.Cog):
    @commands.command(name='meme')
    async def _meme(self,ctx:commands.Context):
        """今日熱門迷因"""
        target=requests.get("https://memes.tw/wtf/api").json()
        rand=random.randint(1,len(target)-1)
        embed = discord.Embed()
        embed.set_image(url=target[rand]['src'])
        embed.title=f"{target[rand]['title']}"
        embed.description=f"[連結]({target[rand]['url']})"
        await ctx.send(embed=embed)

    @commands.command(name='weather')
    async def _weather(self,ctx:commands.Context,region=None):
        """各縣市36小時天氣預報"""
        if(region==None):
            await ctx.send("請輸入地區(縣市)")
            return

        target=requests.get("https://opendata.cwb.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization=CWB-1461ABE2-E884-48EC-BBDE-F082E02B2D30&format=JSON").json()
        for i in range(len(target['records']['location'])):
            if(target['records']['location'][i]['locationName']==region):
                dd=target['records']['location'][i]['weatherElement']
                break
        print(len(dd))
        for j in range(len(dd)):
            a=dd[j]
            print(a)
        await ctx.send(region+"未來36小時天氣預報")
        for k in range(len(dd[0]['time'])):
            embed=discord.Embed()
            embed.title=dd[0]['time'][k]['startTime']+'~'+dd[j]['time'][k]['endTime']
            embed.description=f"{dd[0]['time'][k]['parameter']['parameterName']}\n降雨機率:{dd[1]['time'][k]['parameter']['parameterName']}%\n最低溫度:{dd[2]['time'][k]['parameter']['parameterName']}°C\n最高溫度:{dd[4]['time'][k]['parameter']['parameterName']}°C\n舒適度:{dd[3]['time'][k]['parameter']['parameterName']}"
            await ctx.send(embed=embed)

    @commands.command(name='elden')
    async def elden(self,ctx:commands.Context,name1):
        """展示艾爾登法環的武器數值"""
        embed = discord.Embed()
        c2=weapons[f'{name1}']
        c2=c2.replace('-',"'")
        c1=c2.replace(' ','+')
        r = requests.get(f"https://eldenring.wiki.fextralife.com/{c1}") 
        soup = BeautifulSoup(r.text,"html.parser") 
        sel = soup.select("div.lineleft") #數值
        str4 =str(sel) 
        s = [int(s) for s in re.findall(r'-?\d\.?\d*', str4)]
        k=[1,3,4,5,7,8,9,11,12,14,15,17]
        for j in range(18,46):
            k.append(j)
        s1=[]
        for i in range(45):
            if i in k:
                pass
            else:
                s1.append(s[i])

        sel2 = soup.select("tbody td") #圖片
        a1=str(sel2[0])
        word1='/'
        word2='"'
        b1=a1.find(word1)
        lst = []
        for pos,char in enumerate(a1):
            if(char == word2):
                lst.append(pos)
        b2=lst[9]
        a2=a1[b1:b2]
        embed.set_image(url=f"https://eldenring.wiki.fextralife.com/{a2}")
        embed.description = f"{name1}\n攻擊力:\n物理:{s1[0]}\n魔力:{s1[1]}\n火:{s1[2]}\n雷:{s1[3]}\n聖:{s1[4]}\n致命一擊:{s1[5]}\n[詳細資料](https://eldenring.wiki.fextralife.com/{c1})."
        await ctx.send(embed=embed)

    @commands.command(name='picture')
    async def picture(self,ctx:commands.Context,query:str=None):
        """隨機找圖片素材用"""
        if(query==None):
            await ctx.send("請輸入要搜尋的東西")
            return
        
        access_key=os.environ.get('picture_access_key')
        if(access_key==None):
            try:
                with open('api_key/access_key.txt','r') as r:
                    access_key=r.read()
            except:
                await ctx.send("no picture_access_key")
                return

        url = 'https://api.unsplash.com/search/photos'
        querystring = {'query': query, 'client_id': access_key}
        response = requests.get(url, params=querystring, allow_redirects=True).json()
        print(response)

    @commands.command(hidden=True)
    async def ccu_csie_camp(self,ctx:commands.Context,req:str=None):
        if(req==None):
            await ctx.send("type things to search")
            return
        url='https://www.google.com/search?q='+req+'&tbm=isch&sa=X&ved=2ahUKEwioipTwptP_AhVIEIgKHUkYBtQQ0pQJegQICxAB&biw=1608&bih=950&dpr=1'
        res=requests.get(url).text
        soup=BeautifulSoup(res,'html5lib')
        title=soup.find_all('img')
        for i in title:
            await ctx.send(i['src'])
        

    @commands.command(name='hololive')
    async def hololive(self,ctx:commands.Context,category:str=None):
        """看各位holomember的開台狀況(百鬼是要不要開台阿)"""
        if(category==None):
            await ctx.send("請輸入類別(live,upcoming)")
            return
        if(category=='live' or category=='upcoming'):
            api_key=os.environ.get('holodex_api_key')

            if(api_key==None):
                try:
                    with open('api_key/api.txt','r') as r:
                        api_key=r.read()
                except:
                    await ctx.send("no holodex_api_key")
                    return
            url = "https://holodex.net/api/v2/live"
            querystring = {"org":"Hololive","status":category}
            headers = {
                "Accept": "application/json",
                "X-APIKEY": api_key
            }
            response = requests.get(url, headers=headers, params=querystring).json()
            
            # print(response)
            
            for i in range(len(response)):
                print(response[i]['status'])
                if(response[i]['status']=='live'):
                    livestart=response[i]['start_actual']
                elif(response[i]['status']=='upcoming'):
                    livestart=response[i]['start_scheduled']
                print(livestart)
                if(livestart==None):
                    livestart='結束'
                else:
                    livestart=parser.parse(livestart)
                    livestart=livestart.strftime("%Y/%m/%d %H:%M")

                embed=discord.Embed()
                embed.title=response[i]['title']
                embed.url='https://www.youtube.com/watch?v='+response[i]['id']
                embed.set_image(url=response[i]['channel']['photo'])
                a='https://www.youtube.com/channel/'+response[i]['channel']['id']
                if(response[i]['status']=='upcoming'):
                    embed.description=f"開始時間:{livestart}\n{response[i]['channel']['name']}的頻道[url]({a})"
                elif(response[i]['status']=='live'):
                    embed.description=f"觀看人數:{response[i]['live_viewers']}\n{response[i]['channel']['name']}的頻道[url]({a})"
                t=response[i]['title']
                t=t.lower()
                if((not 'free' in t) and (not 'chat' in t) and (not 'schedule' in t)):
                    await ctx.send(embed=embed)
            print("list over")
            return
        
        await ctx.send("類別輸入錯誤，請重新輸入(live,upcoming)")
    
            

async def setup(bot):
    await bot.add_cog(Api(bot))



