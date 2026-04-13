# -*- coding: utf-8 -*-
import asyncio
import functools
import itertools
import logging
import math
import os
import random
import time
import discord
from discord.ext import commands
import shutil
import subprocess
import sys
from async_timeout import timeout
import json

logger = logging.getLogger(__name__)

# Find yt-dlp: prefer the one next to the running Python (venv/Scripts/)
_venv_ytdlp = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
YTDLP = _venv_ytdlp if shutil.which(_venv_ytdlp) else "yt-dlp"
logger.info("Using yt-dlp at: %s", shutil.which(YTDLP) or YTDLP)

# Find ffmpeg: check project root first, then PATH
_project_ffmpeg = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffmpeg.exe")
FFMPEG = _project_ffmpeg if os.path.isfile(_project_ffmpeg) else "ffmpeg"
logger.info("Using ffmpeg at: %s", FFMPEG)

time_json = "json/time.json"

try:
    with open(time_json, "rb") as f:
        pass
except FileNotFoundError:
    logger.info("time.json does not exist, creating")
    os.makedirs("json", exist_ok=True)
    with open(time_json, "w") as f:
        json.dump({}, f)


class VoiceError(Exception):
    pass


class YTDLError(Exception):
    pass


class YTDLSource(discord.PCMVolumeTransformer):
    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
        'executable': FFMPEG,
    }

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader', '未知')
        self.uploader_url = data.get('uploader_url', '')
        self.title = data.get('title', '未知標題')
        self.thumbnail = data.get('thumbnail', '')
        self.description = data.get('description', '')
        self.duration = self.parse_duration(int(data.get('duration', 0)))
        self.duration_raw = int(data.get('duration', 0))
        self.tags = data.get('tags', [])
        self.url = data.get('webpage_url', '')
        self.views = data.get('view_count', 0)
        self.likes = data.get('like_count', 0)
        self.dislikes = data.get('dislike_count', 0)
        self.stream_url = data.get('url', '')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()
        
        partial = functools.partial(cls.get_info_and_url, search)
        
        try:
            data = await loop.run_in_executor(None, partial)
        except Exception as e:
            # 嘗試簡化的方法
            try:
                partial_simple = functools.partial(cls.get_simple_url, search)
                data = await loop.run_in_executor(None, partial_simple)
            except Exception as e2:
                raise YTDLError(f'無法處理請求: {str(e)} / {str(e2)}')
            
        if not data:
            raise YTDLError('找不到符合條件的內容 `{}`'.format(search))

        return cls(ctx, discord.FFmpegPCMAudio(data['url'], **cls.FFMPEG_OPTIONS), data=data)

    @staticmethod
    def get_simple_url(search):
        """簡化的獲取方法，只取得基本URL和標題"""
        try:
            # 如果是搜尋關鍵字，加上 ytsearch: 前綴
            if not search.startswith('http'):
                search = f"ytsearch:{search}"
            
            # 只獲取URL和標題
            cmd = [
                YTDLP,
                '--format', 'bestaudio',
                '--get-url',
                '--get-title',
                '--no-playlist',
                '--quiet',
                '--no-warnings',
                search
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    return {
                        'title': lines[0],
                        'url': lines[1],
                        'duration': 0,
                        'thumbnail': '',
                        'description': '',
                        'uploader': '未知',
                        'webpage_url': search if search.startswith('http') else '',
                        'view_count': 0,
                        'like_count': 0,
                        'uploader_url': '',
                        'tags': [],
                        'dislike_count': 0
                    }
            else:
                logger.warning("簡化方法錯誤: %s", result.stderr)
            
            return None
            
        except Exception as e:
            logger.warning("簡化方法異常: %s", e)
            return None

    @staticmethod
    def get_info_and_url(search):
        """使用命令行 yt-dlp 獲取音訊資訊和 URL"""
        try:
            # 如果是搜尋關鍵字，加上 ytsearch: 前綴
            if not search.startswith('http'):
                search = f"ytsearch:{search}"
            
            # 先獲取基本資訊（標題和串流URL）
            cmd = [
                YTDLP,
                '--format', 'bestaudio',
                '--get-url',
                '--get-title',
                '--no-playlist',
                '--quiet',
                search
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    title = lines[0]
                    url = lines[1]
                    
                    # 獲取額外資訊
                    try:
                        info_cmd = [
                            YTDLP,
                            '--dump-json',
                            '--no-playlist',
                            '--quiet',
                            search
                        ]
                        
                        info_result = subprocess.run(info_cmd, capture_output=True, text=True, timeout=30)
                        
                        if info_result.returncode == 0:
                            import json
                            info_data = json.loads(info_result.stdout)
                            
                            return {
                                'title': title,
                                'url': url,
                                'duration': info_data.get('duration', 0),
                                'thumbnail': info_data.get('thumbnail', ''),
                                'description': info_data.get('description', '')[:500] + '...' if info_data.get('description') else '',
                                'uploader': info_data.get('uploader', '未知'),
                                'webpage_url': info_data.get('webpage_url', ''),
                                'view_count': info_data.get('view_count', 0),
                                'like_count': info_data.get('like_count', 0),
                                'uploader_url': info_data.get('uploader_url', ''),
                                'tags': info_data.get('tags', []),
                                'dislike_count': 0
                            }
                    except Exception as e:
                        logger.warning("獲取詳細資訊失敗，使用基本資訊: %s", e)
                    
                    # 返回基本資訊
                    return {
                        'title': title,
                        'url': url,
                        'duration': 0,
                        'thumbnail': '',
                        'description': '',
                        'uploader': '未知',
                        'webpage_url': search if search.startswith('http') else '',
                        'view_count': 0,
                        'like_count': 0,
                        'uploader_url': '',
                        'tags': [],
                        'dislike_count': 0
                    }
            else:
                logger.warning("yt-dlp 錯誤: %s", result.stderr)
            
            return None
            
        except Exception as e:
            logger.warning("獲取音訊資訊錯誤: %s", e)
            return None

    @staticmethod
    def duration_to_seconds(duration_str):
        """將時長字符串轉換為秒數"""
        try:
            if ':' in duration_str:
                parts = duration_str.split(':')
                if len(parts) == 2:  # MM:SS
                    return int(parts[0]) * 60 + int(parts[1])
                elif len(parts) == 3:  # HH:MM:SS
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            return 0
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def parse_duration(duration):
        if duration <= 0:
            return "0:00"
            
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration_parts = []
        if days > 0:
            duration_parts.append('{}'.format(days))
        if hours >= 10:
            duration_parts.append('{}'.format(hours))
        elif days > 0:
            duration_parts.append('0{}'.format(hours))
        elif hours > 0:
            duration_parts.append('{}'.format(hours))
        if minutes >= 10:
            duration_parts.append('{}'.format(minutes))
        elif hours > 0 or days > 0:
            duration_parts.append('0{}'.format(minutes))
        elif minutes > 0:
            duration_parts.append('{}'.format(minutes))

        if seconds >= 10:
            duration_parts.append('{}'.format(seconds))
        else:
            duration_parts.append('0{}'.format(seconds))

        return ':'.join(duration_parts)


class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self, begin):
        progress = time.time()
        begin = int(begin)
        progress = int(progress)
        p = int(progress - begin)
        dd = int(self.source.duration_raw)
        ppp = self.parse_duration(p, self.source.duration_raw)
        if dd < 60:
            ppp = "0:" + ppp
        duration = self.source.duration
        if dd < 60:
            duration = "0:" + duration

        if dd - p < 0:
            logger.warning("進度條計算錯誤: 已播放時間超過總時長")
            return None
        if p != 0 and dd > 0:
            pp = int(p / dd * 15)
        else:
            pp = 0
        
        embed = (discord.Embed(title='正在播放',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=discord.Color.blurple())
                 .add_field(name='進度條', value=str('<' + '-' * pp + '●' + '-' * (15 - pp) + '>' + ppp + '/' + duration), inline=False)
                 .add_field(name='請求者', value=self.requester.mention)
                 .add_field(name='上傳者', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self) if self.source.uploader_url else self.source.uploader)
                 .add_field(name='連結', value='[點擊]({0.source.url})'.format(self) if self.source.url else '無連結')
                 .add_field(name='下載', value='[點擊]({0.source.url})'.format(self).replace("youtube", "backupmp3") if self.source.url else '無下載'))

        if self.source.thumbnail:
            embed.set_thumbnail(url=self.source.thumbnail)

        return embed

    def parse_duration(self, p, raw):
        if p <= 0:
            return "0:00"
            
        minutes, seconds = divmod(p, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration_parts = []
        if raw >= 86400:
            duration_parts.append('{}'.format(days))
        if raw >= 3600 and days == 0:
            duration_parts.append('{}'.format(hours))
        elif raw >= 3600:
            duration_parts.append('0{}'.format(hours))
        if raw >= 60 and hours == 0 and days == 0:
            duration_parts.append('{}'.format(minutes))
        elif raw >= 60:
            duration_parts.append('0{}'.format(minutes))
        if seconds >= 10:
            duration_parts.append('{}'.format(seconds))
        else:
            duration_parts.append('0{}'.format(seconds))
        return ':'.join(duration_parts)


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
        self.exists = True
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

    async def disconnect(self, ctx: commands.Context):
        """清理並斷開語音連接"""
        try:
            music_cog = self.bot.get_cog('Music')
            if music_cog and ctx.guild.id in music_cog.voice_states:
                del music_cog.voice_states[ctx.guild.id]
        except Exception as e:
            logger.warning("disconnect cleanup error: %s", e)
        logger.info("disconnect!")
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
            self.now = None

            if not self.loop:
                try:
                    # 增加超時時間到5分鐘，並且只在佇列真正空閒時觸發
                    async with timeout(300):  # 5 minutes
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    # 確認真的沒有正在播放的音樂
                    if not (self.voice and self.voice.is_playing()):
                        logger.info("播放序列空閒超過5分鐘，斷開連接")
                        self.bot.loop.create_task(self.stop())
                        self.exists = False
                        # 通知頻道即將斷線
                        if self._ctx and self._ctx.channel:
                            try:
                                await self._ctx.channel.send("⚠️ 播放序列空閒超過5分鐘，機器人將自動離開語音頻道。")
                            except Exception as e:
                                logger.warning("無法發送斷線通知: %s", e)
                        return
                    else:
                        # 如果還在播放，繼續等待
                        continue

                # 設定音量並開始播放
                self.current.source.volume = self._volume
                self.voice.play(self.current.source, after=self.play_next_song)
                begin = time.time()
                
                # 記錄播放時間
                try:
                    with open(time_json, "r") as f:
                        a = json.load(f)
                    a["begin"] = begin
                    with open(time_json, "w") as r:
                        json.dump(a, r)
                except Exception as e:
                    logger.warning("JSON 檔案錯誤: %s", e)
                
                # 發送播放資訊
                embed = self.current.create_embed(begin)
                if embed:
                    await self.current.source.channel.send(embed=embed)
            
            else:
                # 循環播放模式
                if self.current:
                    self.now = discord.FFmpegPCMAudio(self.current.source.stream_url, **YTDLSource.FFMPEG_OPTIONS)
                    self.voice.play(self.now, after=self.play_next_song)
                    begin = time.time()
                    
                    try:
                        with open(time_json, "r") as f:
                            a = json.load(f)
                        a["begin"] = begin
                        with open(time_json, "w") as r:
                            json.dump(a, r)
                    except Exception as e:
                        logger.warning("JSON 檔案錯誤: %s", e)

            await self.next.wait()

    def play_next_song(self, error=None):
        if error:
            logger.error("播放器錯誤: %s", error)
        
        # 檢查是否還有人在語音頻道
        if self.voice and self.voice.channel:
            # 計算非機器人成員數量
            human_members = [member for member in self.voice.channel.members if not member.bot]
            if len(human_members) == 0:
                logger.info("語音頻道沒有人類成員，準備自動離開")
                self.bot.loop.create_task(self.auto_leave_empty_channel())
                return
        
        self.next.set()

    async def auto_leave_empty_channel(self):
        """當語音頻道沒有人時自動離開"""
        try:
            # 等待10秒，看看是否有人重新加入
            await asyncio.sleep(10)
            
            # 再次檢查
            if self.voice and self.voice.channel:
                human_members = [member for member in self.voice.channel.members if not member.bot]
                if len(human_members) == 0:
                    if self._ctx and self._ctx.channel:
                        try:
                            await self._ctx.channel.send("👤 語音頻道已無人，機器人自動離開。")
                        except Exception:
                            pass
                    await self.stop()
                    self.exists = False
        except Exception as e:
            logger.warning("自動離開檢查錯誤: %s", e)

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        """停止播放並斷開連接"""
        self.songs.clear()
        if self.voice:
            try:
                await self.voice.disconnect()
                logger.info("已斷開語音連接")
            except Exception as e:
                logger.warning("斷開連接時發生錯誤: %s", e)
            self.voice = None


class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state or not state.exists:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state
        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('此指令無法在私人訊息中使用。')
        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('發生錯誤: {}'.format(str(error)))

    async def ensure_voice_state(self, ctx: commands.Context):
        """確保使用者在語音頻道中且機器人可以連接"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError('您未連接到任何語音頻道。')

        if ctx.author.id == ctx.guild.owner.id:
            return

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError('機器人已在其他語音頻道中。')

    @commands.command(name='join', invoke_without_subcommand=True)
    async def _join(self, ctx: commands.Context):
        """讓機器人進來指令者的語音頻道"""
        await self.ensure_voice_state(ctx)
        
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
            raise VoiceError('您既未連接到語音頻道，也未指定要加入的頻道。')

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'])
    async def _leave(self, ctx: commands.Context):
        """清空序列及讓機器人離開語音頻道"""
        if not ctx.voice_state.voice:
            return await ctx.send('未連接到任何語音頻道。')

        await ctx.voice_state.stop()
        # 確保清理狀態
        if ctx.guild.id in self.voice_states:
            del self.voice_states[ctx.guild.id]
        await ctx.send("👋 已離開語音頻道！")

    @commands.command(name='volume')                      
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """設定機器人的音量"""
        if not ctx.voice_state.is_playing:
            return await ctx.send('目前沒有播放任何音樂。')

        if volume < 0 or volume > 100:
            return await ctx.send('音量必須在 0 到 100 之間')

        ctx.voice_state.current.source.volume = volume / 100
        await ctx.send('播放器音量設定為 {}%'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing'])
    async def _now(self, ctx: commands.Context):
        """現正播放"""
        if not ctx.voice_state.current:
            return await ctx.send('目前沒有播放任何音樂。')
            
        try:
            with open(time_json, "r") as f:
                a = json.load(f)
            embed = ctx.voice_state.current.create_embed(a.get("begin", time.time()))
            if embed:
                await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send('無法顯示當前播放資訊。')

    @commands.command(name='pause')          
    @commands.has_permissions(manage_guild=True)
    async def _pause(self, ctx: commands.Context):
        """暫停歌曲"""
        if ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='resume')          
    async def _resume(self, ctx: commands.Context):
        """恢復播放"""
        if ctx.voice_state.voice and ctx.voice_state.voice.is_paused():
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('⏯')

    @commands.command(name='stop')             
    async def _stop(self, ctx: commands.Context):
        """停止歌曲和清空序列"""
        ctx.voice_state.songs.clear()
        if ctx.voice_state.loop:
            ctx.voice_state.loop = False
        
        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('⏹')

    @commands.command(name='fskip')
    @commands.has_permissions(manage_guild=True)
    async def _force_skip(self, ctx: commands.Context):
        """強制跳到下一首（需要管理員權限）"""
        if not ctx.voice_state.is_playing:
            await ctx.send('目前沒有播放任何音樂...')
        else:
            await ctx.message.add_reaction('⏭')
            if ctx.voice_state.loop:
                ctx.voice_state.loop = False
            ctx.voice_state.skip()

    @commands.command(name='skip')
    async def _skip(self, ctx: commands.Context):
        """需要3個人投票才能跳到下一首（播音樂的人可以直接強制跳過）"""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send('您必須在語音頻道中才能使用此指令。')
            
        channel = ctx.author.voice.channel
        user_count = sum(1 for member in channel.members if not member.bot)

        if not ctx.voice_state.is_playing:
            return await ctx.send('目前沒有播放任何音樂...')

        voter = ctx.message.author
        if voter == ctx.voice_state.current.requester:
            await ctx.message.add_reaction('⏭')
            loop_state = ctx.voice_state.loop
            if ctx.voice_state.loop:
                ctx.voice_state.loop = False
            ctx.voice_state.skip()
            if loop_state:
                ctx.voice_state.loop = True

        elif voter.id not in ctx.voice_state.skip_votes:
            ctx.voice_state.skip_votes.add(voter.id)
            total_votes = len(ctx.voice_state.skip_votes)
            
            if total_votes >= 3 or user_count < 3:
                await ctx.message.add_reaction('⏭')
                loop_state = ctx.voice_state.loop
                if ctx.voice_state.loop:
                    ctx.voice_state.loop = False
                ctx.voice_state.skip()
                if loop_state:
                    ctx.voice_state.loop = True
            else:
                await ctx.send('跳過投票已新增，目前 **{}/3**，或使用 "fskip" 來強制跳過歌曲。'.format(total_votes))
        else:
            await ctx.send('您已經投票跳過這首歌曲了。')

    @commands.command(name='queue')
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """歌曲序列，可以在後面加頁數"""
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('播放序列是空的。')

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        queue = ''
        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)

        embed = (discord.Embed(description='**{} 首歌曲:**\n\n{}'.format(len(ctx.voice_state.songs), queue))
                 .set_footer(text='第 {}/{} 頁'.format(page, pages)))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """打亂序列"""
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('播放序列是空的。')

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """從序列中移除歌曲"""
        if len(ctx.voice_state.songs) == 0:
            return await ctx.send('播放序列是空的。')

        if index < 1 or index > len(ctx.voice_state.songs):
            return await ctx.send('無效的歌曲編號。')

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """重複播放（第二次打指令解除重複）"""
        if not ctx.voice_state.is_playing:
            return await ctx.send('目前沒有播放任何音樂。')

        ctx.voice_state.loop = not ctx.voice_state.loop
        if ctx.voice_state.loop:
            await ctx.send("已開啟循環播放！")
        else:
            await ctx.send("已關閉循環播放！")

    @commands.command(name='play', aliases=['p', 'Play', 'PLAY'])
    async def _play(self, ctx: commands.Context, *, search: str = None):
        """播音樂，可以使用URL也可以用關鍵字"""
        await self.ensure_voice_state(ctx)
        
        if search is None:
            if ctx.voice_state.voice and ctx.voice_state.voice.is_paused():
                ctx.voice_state.voice.resume()
                return await ctx.message.add_reaction('⏯')
            else:
                return await ctx.send("請輸入關鍵字或網址")

        # 處理播放清單
        if 'playlist?' in search:
            await ctx.send("正在處理播放清單，請稍候...")
            try:
                # 使用命令行獲取播放清單
                cmd = [YTDLP, '--flat-playlist', '--get-id', search]
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, lambda: subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                )
                
                if result.returncode == 0:
                    video_ids = result.stdout.strip().split('\n')
                    count = 0
                    for video_id in video_ids[:20]:  # 限制最多20首
                        if video_id:
                            url = f"https://www.youtube.com/watch?v={video_id}"
                            try:
                                await self._add_song_to_queue(ctx, url, silent=True)
                                count += 1
                                await asyncio.sleep(0.5)
                            except Exception as e:
                                logger.warning("無法新增歌曲 %s: %s", url, e)
                                continue
                    
                    return await ctx.send(f'成功新增播放清單！共新增 {count} 首歌曲。')
                else:
                    return await ctx.send('無法處理播放清單。')
                    
            except Exception as e:
                return await ctx.send(f'無法處理播放清單: {str(e)}')

        # 處理單首歌曲
        await self._add_song_to_queue(ctx, search)

    async def _add_song_to_queue(self, ctx: commands.Context, search: str, silent: bool = False):
        """新增歌曲到播放佇列的輔助方法"""
        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        if not silent:
            async with ctx.typing():
                try:
                    source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
                    song = Song(source)
                    
                    if 'insert' in search:
                        # 插入到佇列前面（如果有這個功能需求）
                        await ctx.voice_state.songs.put(song)
                        await ctx.send('已插入 {}'.format(str(source)))
                    else:
                        await ctx.voice_state.songs.put(song)
                        await ctx.send('已加入播放序列 {}'.format(str(source)))
                        
                except YTDLError as e:
                    await ctx.send('處理請求時發生錯誤: {}'.format(str(e)))
                except Exception as e:
                    await ctx.send(f'發生未預期的錯誤: {str(e)}')
        else:
            try:
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
                song = Song(source)
                await ctx.voice_state.songs.put(song)
            except Exception as e:
                logger.warning("靜默新增歌曲失敗: %s", e)
                raise

    @commands.command(name='testt')
    async def test_ytdlp(self, ctx, *, url: str = None):
        """測試 yt-dlp 是否正常工作"""
        try:
            # 測試版本
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: subprocess.run([YTDLP, '--version'], capture_output=True, text=True)
            )
            if result.returncode == 0:
                await ctx.send(f"✅ yt-dlp 正常工作，版本: {result.stdout.strip()}")
            else:
                return await ctx.send("❌ yt-dlp 無法正常工作")
            
            # 如果提供了URL，測試特定URL
            if url:
                await ctx.send(f"🔍 正在測試URL: {url}")
                
                test_cmd = [
                    YTDLP,
                    '--format', 'bestaudio',
                    '--get-url',
                    '--get-title',
                    '--no-playlist',
                    '--quiet',
                    url
                ]
                
                test_result = await loop.run_in_executor(
                    None, lambda: subprocess.run(test_cmd, capture_output=True, text=True, timeout=30)
                )
                
                if test_result.returncode == 0:
                    lines = test_result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        await ctx.send(f"✅ **測試成功!**\n標題: {lines[0]}\n音訊URL: 已獲取")
                    else:
                        await ctx.send(f"⚠️ 部分成功，但輸出格式異常: {test_result.stdout}")
                else:
                    await ctx.send(f"❌ **測試失敗!**\n錯誤: {test_result.stderr}")
                    
        except FileNotFoundError:
            await ctx.send("❌ 找不到 yt-dlp，請確保已正確安裝")
        except Exception as e:
            await ctx.send(f"❌ 測試失敗: {e}")

    @commands.command(name='checkk')
    async def _check_status(self, ctx: commands.Context):
        """檢查機器人狀態"""
        if not ctx.voice_state.voice:
            return await ctx.send("❌ 機器人未連接到語音頻道")
        
        channel = ctx.voice_state.voice.channel
        human_members = [member for member in channel.members if not member.bot]
        
        status = f"🔊 **語音頻道狀態:**\n"
        status += f"頻道: {channel.name}\n"
        status += f"總成員: {len(channel.members)}\n"
        status += f"人類成員: {len(human_members)}\n"
        status += f"機器人成員: {len(channel.members) - len(human_members)}\n"
        status += f"播放狀態: {'🎵 播放中' if ctx.voice_state.is_playing else '⏸️ 待機中'}\n"
        status += f"佇列歌曲: {len(ctx.voice_state.songs)} 首\n"
        status += f"循環模式: {'🔁 開啟' if ctx.voice_state.loop else '❌ 關閉'}"
        
        await ctx.send(status)

    @commands.command(hidden=True)
    @commands.is_owner()
    async def check(self, ctx: commands.Context):
        logger.info("voice_client type: %s", type(ctx.voice_client))
        if ctx.voice_client is None:
            logger.info("no voice client")

async def setup(bot):
    await bot.add_cog(Music(bot))