# -*- coding: utf-8 -*-
import re
import string
import discord
from discord.ext import commands
import random
import json
import utils

badword_json="json/badword.json"

class Event(commands.Cog):
    
    def __init__(self,bot:commands.Bot):
        self.bot=bot


    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        separators = string.punctuation+string.digits+string.whitespace
        excluded = string.ascii_letters
        
        if message.author.id != self.bot.user.id:
            try:
                with open(badword_json,'rb') as file:
                    words=json.load(file)
                file.close()
            except:
                print("badword.json does not exist,so created")
                with open(badword_json,'w+') as file:
                    words={"useless":[""]}
                    json.dump(words,file)
                file.close()
            if(not('!unbanwords' in message.content or '!banwords' in message.content)and (str(message.guild.id) in words) ):
                for word in words[str(message.guild.id)]:
                    print(word)
                    formatted_word = f"[{separators}]*".join(list(word))
                    regex_true = re.compile(fr"{formatted_word}", re.IGNORECASE)
                    regex_false = re.compile(fr"([{excluded}]+{word})|({word}[{excluded}]+)", re.IGNORECASE)
                    profane = False
                    if ((regex_true.search(message.content) is not None\
                        and regex_false.search(message.content) is None)or word in message.content):
                        profane = True
                    print(profane)
                    if(profane==True):
                        await message.delete()
                        await message.channel.send("哦?你說了不該說的話了喔!")

            print(f"{message.guild}/{message.channel}/{message.author.name}>{message.content}")
            if message.embeds:
                print(message.embeds[0].to_dict())
            

        word1='笑死'
        word='笑鼠'
        word11='哈哈'
        url1=['https://imgur.dcard.tw/Fr6zOj0.png','https://memeprod.ap-south-1.linodeobjects.com/user-template/8033ffd8b66053cc9ab07c53d7652654.png']
        if word1 in message.content or word in message.content or word11 in message.content : 
            x = random.randint(0,len(url1)-1)
            await message.channel.send(f"{url1[x]}")
            return
    
        word2='窩不知道'
        url2=['https://truth.bahamut.com.tw/s01/201911/4e3eb1c83a9c6204fd1cdcff2206e831.JPG','https://truth.bahamut.com.tw/s01/201907/edaa624f6882cdc725a9bca58659803b.JPG','https://truth.bahamut.com.tw/s01/202004/1cecf7904f5ac8408c555f4ffad83d68.JPG','https://truth.bahamut.com.tw/s01/201902/df15787a89f2db08eaca4d30bda6d707.JPG']
        if word2 in message.content:
            x = random.randint(0,len(url2)-1)
            await message.channel.send(f"{url2[x]}")
            return
    
        word3='並沒有'
        url3=['https://memeprod.sgp1.digitaloceanspaces.com/user-resource/a31207a4daab475e4d64655ea6577364.png','https://i.imgur.com/LTMTlj8.jpg']
        if word3 in message.content:
            x = random.randint(0,len(url3)-1)
            await message.channel.send(f"{url3[x]}")
            return

        word4='騙人的吧'
        url4=['https://truth.bahamut.com.tw/s01/202105/c4e636d6e6084526102507e29fd3dd27.JPG','https://i.imgur.com/WvUzIEC.jpg']
        if word4 in message.content:
            x = random.randint(0,len(url4)-1)
            await message.channel.send(f"{url4[x]}")
            return

        word5='=U='
        url5=['https://www.u-acg.com/wp-content/uploads/2018/03/yurucam.jpg','https://i.ytimg.com/vi/yG-uaVgKNVM/maxresdefault.jpg','https://i.imgur.com/vt43dre.jpg']
        if word5 in message.content:
            x = random.randint(0,len(url5)-1)
            await message.channel.send(f"{url5[x]}")
            return

        word6='你好棒'
        url6=['https://memeprod.sgp1.digitaloceanspaces.com/user-wtf/1633946494585.jpg','https://memeprod.sgp1.digitaloceanspaces.com/user-wtf/1611827428231.jpg','https://megapx-assets.dcard.tw/images/0401c23d-cfce-41a5-8f3c-eaddee3276d9/640.jpeg','https://i.imgur.com/c1K37Br.jpg','http://memenow.cc/wp-content/uploads/2020/04/20200409_5e8e8809efa5d.jpg','https://memeprod.sgp1.digitaloceanspaces.com/user-wtf/1618457624593.jpg']
        if(word6 in message.content):
            x = random.randint(0,len(url6)-1)
            await message.channel.send(f"{url6[x]}")
            return

        word7='挖堀挖堀'
        word71='挖苦挖苦'
        if(word7 in message.content or word71 in message.content):
            await message.channel.send(f"https://i.ytimg.com/vi/RJA3sLMJ_5M/maxresdefault.jpg")
            return

        word8='安妮亞'
        word81='安妮雅'
        url8=["https://i.ytimg.com/vi/RJA3sLMJ_5M/maxresdefault.jpg","https://truth.bahamut.com.tw/s01/202204/9b47c1e3c795e7ca9143d038548f1039.JPG","https://media.gq.com.tw/photos/628b2ec34824d010bb0b3cd4/master/pass/165306325038.jpeg"
        ,"https://i.imgur.com/wFTt4U3.jpg","https://cdn.hk01.com/di/media/images/dw/20220523/605374591732289536956820.jpeg/OyZWi9Te_rGFnyJrBdp7si7C17c13FhsMqHQvzKh0L8?v=w1920","https://cdn2.ettoday.net/images/6356/d6356349.jpg","https://www.mirrormedia.com.tw/assets/images/20220523134712-fdfb0d0e4e92b7fd3ba4f9df1137c297-mobile.png"
        ,"https://fpimgs.s3-ap-southeast-1.amazonaws.com/uul/202204/220421/626138f1c3b0d4.37571922.png","https://p26.toutiaoimg.com/origin/tos-cn-i-qvj2lq49k0/81ee7a5948ce4544a5f622e84524e27a?from=pc","https://c.tenor.com/ZvMZoQy5hkMAAAAC/fbi-fbi-open-the-door.gif"]
        if(word8 in message.content or word81 in message.content):
            x=random.randint(0,len(url8)-1)
            await message.channel.send(f"{url8[x]}")
            return
        word9='不可以瑟瑟'
        word91='不可以色色'
        url9=["https://static.wikia.nocookie.net/evchk/images/d/d0/%E4%B8%8D%E5%8F%AF%E4%BB%A5%E8%89%B2%E8%89%B2.jpg/revision/latest?cb=20211013194012","https://dvblobcdnjp.azureedge.net//Content/Upload/Popular/Images/2021-09/637c0cfc-3736-4b76-81ce-9dad2226aab9_m.jpg","https://static.wikia.nocookie.net/evchk/images/0/07/%E4%B8%8D%E5%8F%AF%E4%BB%A5%E8%89%B2%E8%89%B24.jpg/revision/latest/scale-to-width-down/250?cb=20211016193637","https://dvblobcdnjp.azureedge.net//Content/ueditor/net/upload1/2021-09/e967dedb-5683-493d-a5c2-dfb30f55bbe1.png"
        ,"https://s.yimg.com/ny/api/res/1.2/F2Yrc22rf21lhMVKhlEZfQ--/YXBwaWQ9aGlnaGxhbmRlcjt3PTY0MA--/https://s.yimg.com/os/creatr-uploaded-images/2021-09/4fd33520-1c3c-11ec-a2fd-631153bc4385"]
        if(word9 in message.content or word91 in message.content):
            x=random.randint(0,len(url9)-1)
            await message.channel.send(f"{url9[x]}")
            return

        word10='傻眼'
        url10=["https://memeprod.sgp1.digitaloceanspaces.com/user-wtf/1588907260330.jpg","https://memeprod.sgp1.digitaloceanspaces.com/user-wtf/1649160772882.jpg","https://memeprod.ap-south-1.linodeobjects.com/user-template/4d21d4175ce3cf317d1a532d7cde1550.png"]
        if(word10 in message.content):
            x=random.randint(0,len(url10)-1)
            await message.channel.send(f"{url10[x]}")
            return

        word48763='星爆'
        url48763=['http://i.imgur.com/eH9zKS0.jpg','https://c.tenor.com/4Wmrjus9r0MAAAAC/%E6%98%9F%E7%88%86%E6%B0%A3%E6%B5%81%E6%96%AC.gif','https://x.nctu.app/img/g7Fx.jpg','http://i.imgur.com/EaIXyCA.jpg']
        if word48763 in message.content:
            x = random.randint(0,len(url48763)-1)
            await message.channel.send(f"{url48763[x]}")
            return


async def setup(bot):
    await bot.add_cog(Event(bot))