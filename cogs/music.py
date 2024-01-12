# -*- coding: utf-8 -*- 
import asyncio
import functools
import itertools
import math
import os
import random
import time
import discord
from discord.ext.commands.core import command
import yt_dlp
from async_timeout import timeout
from discord.ext import commands
from discord.ext.commands.core import has_guild_permissions
import json

time_json="json/time.json"

try:
    with open(time_json,"rb") as f:
        print("time.json exists")
    f.close()
except:
    print("time.json does not exist,so created")
    with open(time_json,"w+") as f:
        a={"useless":""}
        json.dump(a,f)
    f.close()

# Silence useless bug reports messages
yt_dlp.utils.bug_reports_message = lambda: ''


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
    ytdl.cache.remove()

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = self.parse_duration(int(data.get('duration')))
        self.duration_raw=int(data.get('duration'))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if days > 0:
            duration.append('{}'.format(days))
        if hours >=10:
            duration.append('{}'.format(hours))
        elif(days>0):
            duration.append('0{}'.format(hours))
        elif(hours>0):
            duration.append('{}'.format(hours))
        if(minutes>=10) :
            duration.append('{}'.format(minutes))
        elif(hours>0 or days>0):
            duration.append('0{}'.format(minutes))
        elif(minutes>0):
            duration.append('{}'.format(minutes))

        if seconds >=10 :
            duration.append('{}'.format(seconds))
        else:
            duration.append('0{}'.format(seconds))

        return ':'.join(duration)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    


    def create_embed(self,begin):
        
        progress=time.time()
        begin=int(begin)
        progress=int(progress)
        p=int(progress-begin)
        dd=int(self.source.duration_raw)
        ppp=self.parse_duration(p,self.source.duration_raw)
        if(dd<60):
            ppp="0:"+ppp
        duration=self.source.duration
        if(dd<60):
            duration="0:"+duration

        if(dd-p<0):
            print('error!')
            return 
        if(p!=0):
            pp=int(p/dd*15)
        else:
            pp=0
        
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='Progressbar',value=str('<'+'-'*pp+'●'+'-'*(15-pp)+'>'+ppp+'/'+duration),inline=False)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .add_field(name='URL', value='[Click]({0.source.url})'.format(self))
                 .add_field(name='Download', value='[Click]({0.source.url})'.format(self).replace("youtube","backupmp3"))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed

    
    def parse_duration(self,p,raw):
        minutes, seconds = divmod(p, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration = []
        if(raw>=86400):
            duration.append('{}'.format(days))
        if(raw>=3600 and days==0):
            duration.append('{}'.format(hours))
        elif(raw>=3600):
            duration.append('0{}'.format(hours))
        if(raw>=60 and hours==0 and days==0):
            duration.append('{}'.format(minutes))
        elif(raw>=60):
            duration.append('0{}'.format(minutes))
        if(seconds >= 10):
            duration.append('{}'.format(seconds))
        else:
            duration.append('0{}'.format(seconds))
        return ':'.join(duration)





class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]


class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx
        self.exists=True
        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()
        self._loop = False
        self._volume = 0.5
        self.skip_votes = set()

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    async def disconnect(self,ctx:commands.Context):
        del self.voice_states[ctx.guild.id]
        print('disconnect!')
        return
        

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self):
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()
            self.now=None

            if(self.loop==False):
                # Try to get the next song within 1 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(60):  # 1 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    print('disconnect')
                    self.bot.loop.create_task(self.stop())
                    self.exists=False
                    self.disconnect
                    return

                self.current.source.volume = self._volume
                self.voice.play(self.current.source, after=self.play_next_song)
                begin=time.time()
                with open(time_json,"rb") as f:
                    a = json.load(f)
                    a["begin"] = begin
                    dict=a
                f.close()
                with open(time_json,"w") as r:
                    json.dump(dict,r)
                r.close()
                print(self.current.create_embed(begin))

                await self.current.source.channel.send(embed=self.current.create_embed(begin))
            
            elif(self.loop==True):
                self.now=discord.FFmpegPCMAudio(self.current.source.stream_url,**YTDLSource.FFMPEG_OPTIONS)
                self.voice.play(self.now,after=self.play_next_song)
                begin=time.time()
                with open(time_json,"rb") as f:
                    a = json.load(f)
                    a["begin"] = begin
                    dict=a
                f.close()
                with open(time_json,"w") as r:
                    json.dump(dict,r)
                r.close()
                


            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        self.skip_votes.clear()

        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None

 
class Music(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}
        self.members=discord.VoiceChannel.members

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state or not state.exists :
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """讓機器人進來指令者的語音頻道"""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    @commands.has_permissions(manage_guild=True)
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """讓機器人去指定的頻道，如果沒有指定，就讓機器人進來指令者的語音頻道"""
        if not channel and not ctx.author.voice:
            raise VoiceError('You are neither connected to a voice channel nor specified a channel to join.')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    # @commands.has_permissions(manage_guild=True)
    async def _leave(self, ctx: commands.Context):
        """清空序列及讓機器人離開語音頻道"""

        if not ctx.voice_state.voice:
            return await ctx.send('Not connected to any voice channel.')

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')                      
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """設定機器人的音量"""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        if 0 >= volume >= 100:
            return await ctx.send('Volume must be between 0 and 100')

        ctx.voice_state.current.source.volume = volume / 100
        await ctx.send('Volume of the player set to {}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """現正播放"""
        with open(time_json,"rb") as f:
            a = json.load(f)
        f.close()
        print(dir(ctx.voice_state))
        await ctx.send(embed=ctx.voice_state.current.create_embed(a["begin"]))

    @commands.command(name='pause')          
    @commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        """暫停歌曲"""

        if  ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')             
    # @commands.has_permissions(manage_guild=True)
    async def _stop(self, ctx: commands.Context):
        """停止歌曲和清空序列"""

        ctx.voice_state.songs.clear()
        if(ctx.voice_state.loop):
            ctx.voice_state.loop=False
        
        if  ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')


    @commands.command(name='fskip')
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self,ctx:commands.Context):
        """強制跳到下一首(需要管理員權限)"""
        if not ctx.voice_state.is_playing:
            await ctx.send('Not playing any music right now...')
        else:
            await ctx.message.add_reaction('⏭')
            
            if(ctx.voice_state.loop):
                ctx.voice_state.loop=False
                
            ctx.voice_state.skip()
            

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context,*,channel:discord.VoiceChannel =None):
        """需要3個人投票才能跳到下一首(播音樂的人可以直接強制跳過)"""
        channel=ctx.author.voice.channel

        sum=0
        for i in range(len(channel.members)):
            if(not channel.members[i].bot):
                sum+=1
        print(sum)

        if not ctx.voice_state.is_playing:
            return await ctx.send('Not playing any music right now...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            s=0
            if(ctx.voice_state.loop):
                ctx.voice_state.loop=False
                s=1
            ctx.voice_state.skip()
            if(s==1):
                ctx.voice_state.loop=True

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)
            print(channel.members)
            if total_votes >= 3 or sum<3:
                await ctx.message.add_reaction('⏭')
                s=0
                if(ctx.voice_state.loop):
                    ctx.voice_state.loop=False
                    s=1
                ctx.voice_state.skip()
                if(s==1):
                    ctx.voice_state.loop=True
            else:
                await ctx.send('Skip vote added, currently at **{}/3**, or use "fskip" to skip song without vote. '.format(total_votes))

        else:
            await ctx.send('You have already voted to skip this song.')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """歌曲序列，可以在後面加頁數"""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} tracks:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='Viewing page {}/{}'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """打亂序列"""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """從序列中移除歌曲"""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('Empty queue.')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """重複播放(第二次打指令解除重複)"""

        if not ctx.voice_state.is_playing:
            return await ctx.send('Nothing being played at the moment.')

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        if(ctx.voice_state.loop==True):
            await ctx.send("loop!")
        else:
            await ctx.send("unloop!")

    
    @commands.command(name='play',pass_context = True , aliases=['Play', 'PLAY'])
    async def _play(self, ctx: commands.Context,*,search='-1'):
        """播音樂，可以使用URL也可以用關鍵字"""
        
        if(search=='-1'):
            if  ctx.voice_state.voice.is_paused():
                ctx.voice_state.voice.resume()
                return await ctx.message.add_reaction('⏯')
            else:
                await ctx.send("請輸入關鍵字或網址")
                return
        
        if('playlist?' in search):
            option={
                'extract_flat':True,
                'verbose':True
            }
            with yt_dlp.YoutubeDL(option) as ydl:
                info=ydl.extract_info(search,download=False)
                info=info.get('entries')
                for i in range(len(info)): 
                    print(info[i]['url'])
                    a="https://www.youtube.com/watch?v="+info[i]['url']
                    await self._play(ctx,search=a)
                    await asyncio.sleep(2)
            return await ctx.send('成功')

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as e:
                await ctx.send('An error occurred while processing this request: {}'.format(str(e)))
            else:
                song = Song(source)
                if('insert' in search):
                    print('insert')
                    await ctx.voice_state.songs.insert(song,0)
                    await ctx.send('Inserted {}'.format(str(source)))
                else:
                    await ctx.voice_state.songs.put(song)
                    await ctx.send('Enqueued {}'.format(str(source)))

    @commands.command(hidden=True)
    @commands.is_owner()
    async def check(self, ctx: commands.Context):
        print(type(ctx.voice_client))
        if type(ctx.voice_client) is NoneType:
            print('yes')
        
        
        
        
    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('You are not connected to any voice channel.')

        if ctx.author.id==ctx.guild.owner.id:
            return

        
        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('Bot is already in a voice channel.')

async def setup(bot):
    await bot.add_cog(Music(bot))