import os
import json
import asyncio
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pytgcalls import PyTgCalls
from pytgcalls.types import InputStream, AudioPiped
from pytgcalls.exceptions import GroupCallNotFoundError
from yt_dlp import YoutubeDL
from youtubesearchpython import VideosSearch
from googleapiclient.discovery import build

from config import API_ID, API_HASH, BOT_TOKEN, OWNER_ID, COOKIES_PATH, DOWNLOADS_DIR, YOUTUBE_API_KEY

# Ensure downloads dir exists
Path(DOWNLOADS_DIR).mkdir(parents=True, exist_ok=True)

app = Client("musicbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
call_py = PyTgCalls(app)

# Queues and persistent data
queues = {}  # chat_id -> list of (file, title)
vc_users = {}  # chat_id -> set(user_ids)
GROUPS_FILE = "groups.json"
GBAN_FILE = "gbanned.json"

def load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

groups = load_json(GROUPS_FILE, [])
GBANNED = load_json(GBAN_FILE, [])

def save_gbans():
    save_json(GBAN_FILE, GBANNED)

def save_groups():
    save_json(GROUPS_FILE, groups)

# ---------------- YouTube Search ----------------

def search_youtube_api(query):
    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        part="snippet",
        maxResults=1,
        q=query,
        type="video"
    )
    response = request.execute()
    items = response.get("items")
    if not items:
        raise Exception("No results found via API")
    video_id = items[0]["id"]["videoId"]
    title = items[0]["snippet"]["title"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    return url, title

# ---------------- YT-DLP Fallback ----------------
YDL_OPTS = {
    "format": "bestaudio/best",
    "outtmpl": f"{DOWNLOADS_DIR}/%(title)s.%(ext)s",
    "cookiefile": COOKIES_PATH,
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}

def download_audio(query):
    search = VideosSearch(query, limit=1).result()
    if not search.get("result"):
        raise Exception("No results found.")
    url = search["result"][0]["link"]
    with YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        title = info.get("title", "Unknown")
    return filename, title

# ---------------- Helper ----------------
def is_gbanned(user_id):
    return user_id in GBANNED

async def play_next(chat_id):
    q = queues.get(str(chat_id), [])
    if q:
        file, title = q.pop(0)
        queues[str(chat_id)] = q
        await call_py.join_group_call(chat_id, InputStream(AudioPiped(file)))
        return title
    return None

# ---------------- Commands ----------------

@app.on_message(filters.command("start") & filters.private)
async def start(_, message):
    buttons = [
        [InlineKeyboardButton("👤 Owner", url="https://t.me/YourOwnerUsername")],
        [InlineKeyboardButton("💬 Support Chat", url="https://t.me/YourSupportChat")],
    ]
    text = "🎵 TELEGRAM MOST POWERFUL MUSIC BOT - NEW VERSION 🎵\n\nWelcome! Use /play in your groups to start music."
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

@app.on_message(filters.new_chat_members)
async def new_member(_, message):
    chat_id = message.chat.id
    # bot join log
    if app.me.id in [u.id for u in message.new_chat_members]:
        await message.reply("🤖 Hello! Main ready hoon music play karne ke liye. Use /play <song> to start!")
    if chat_id not in groups:
        groups.append(chat_id)
        save_groups()

@app.on_message(filters.command("play") & filters.group)
async def play(_, message):
    user = message.from_user
    if not user:
        return
    if is_gbanned(user.id):
        return await message.reply("🚫 Aap Globally Banned ho! Contact owner.")

    if len(message.command) < 2:
        return await message.reply("❌ Use: /play <song name or url>")

    query = " ".join(message.command[1:])
    m = await message.reply(f"🔎 Searching `{query}`...")

    try:
        # Try API first
        try:
            url, title = search_youtube_api(query)
        except:
            # fallback: cookies + yt-dlp
            url, title = download_audio(query)

        file = None
        if url.endswith(".mp3") or url.endswith(".m4a"):
            file = url
        else:
            file, title = download_audio(url)

    except Exception as e:
        return await m.edit(f"❌ Download/Search failed: {e}")

    chat_id = message.chat.id
    q = queues.get(str(chat_id), [])

    if q:
        q.append((file, title))
        queues[str(chat_id)] = q
        await m.edit(f"➕ Added to queue: **{title}**")
    else:
        queues[str(chat_id)] = []
        try:
            await call_py.join_group_call(chat_id, InputStream(AudioPiped(file)))
            chat = await app.get_chat(chat_id)
            await m.edit(f"▶️ Now Playing: **{title}**\n📍 Voice Chat: **{chat.title}**\n🎤 Requested by: {user.mention}")
        except Exception as e:
            queues.pop(str(chat_id), None)
            await m.edit(f"❌ Could not join group call: {e}")

# Skip / Stop / Pause / Resume commands
@app.on_message(filters.command("skip") & filters.group)
async def skip(_, message):
    if not message.from_user or is_gbanned(message.from_user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.leave_group_call(chat_id)
    except GroupCallNotFoundError:
        return await message.reply("❌ Abhi koi music nahi chal raha!")
    next_title = await play_next(chat_id)
    if next_title:
        await message.reply(f"⏭ Skipped! Now playing: **{next_title}**")
    else:
        await message.reply("⏹ Queue khali hai, music stopped.")

@app.on_message(filters.command("stop") & filters.group)
async def stop(_, message):
    if not message.from_user or is_gbanned(message.from_user.id):
        return
    chat_id = message.chat.id
    queues.pop(str(chat_id), None)
    try:
        await call_py.leave_group_call(chat_id)
    except GroupCallNotFoundError:
        pass
    await message.reply("⏹ Music stopped aur queue clear ho gayi!")

@app.on_message(filters.command("pause") & filters.group)
async def pause(_, message):
    if not message.from_user or is_gbanned(message.from_user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.pause_stream(chat_id)
        await message.reply("⏸ Music paused!")
    except:
        await message.reply("❌ Abhi koi music nahi chal raha!")

@app.on_message(filters.command("resume") & filters.group)
async def resume(_, message):
    if not message.from_user or is_gbanned(message.from_user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.resume_stream(chat_id)
        await message.reply("▶️ Music resumed!")
    except:
        await message.reply("❌ Abhi koi paused music nahi hai!")

# ---------------- Commands ----------------

@app.on_message(filters.command("start") & filters.private)
async def start(_, message):
    buttons = [
        [InlineKeyboardButton("👤 Owner", url="https://t.me/YourOwnerUsername")],
        [InlineKeyboardButton("💬 Support Chat", url="https://t.me/YourSupportChat")],
    ]
    text = "🎵 TELEGRAM MOST POWERFUL MUSIC BOT - NEW VERSION 🎵\n\nWelcome! Use /play in your groups to start music."
    await message.reply(text, reply_markup=InlineKeyboardMarkup(buttons), disable_web_page_preview=True)

@app.on_message(filters.new_chat_members)
async def new_member(_, message):
    chat_id = message.chat.id
    # bot join log
    if app.me.id in [u.id for u in message.new_chat_members]:
        await message.reply("🤖 Hello! Main ready hoon music play karne ke liye. Use /play <song> to start!")
    if chat_id not in groups:
        groups.append(chat_id)
        save_groups()

@app.on_message(filters.command("play") & filters.group)
async def play(_, message):
    user = message.from_user
    if not user:
        return
    if is_gbanned(user.id):
        return await message.reply("🚫 Aap Globally Banned ho! Contact owner.")

    if len(message.command) < 2:
        return await message.reply("❌ Use: /play <song name or url>")

    query = " ".join(message.command[1:])
    m = await message.reply(f"🔎 Searching `{query}`...")

    try:
        file, title = await asyncio.get_event_loop().run_in_executor(None, download_audio, query)
    except Exception as e:
        return await m.edit(f"❌ Download/Search failed: {e}")

    chat_id = message.chat.id
    q = queues.get(str(chat_id), [])

    if q:
        q.append((file, title))
        queues[str(chat_id)] = q
        await m.edit(f"➕ Added to queue: **{title}**")
    else:
        queues[str(chat_id)] = []
        try:
            await call_py.join_group_call(chat_id, InputStream(AudioPiped(file)))
            chat = await app.get_chat(chat_id)
            await m.edit(f"▶️ Now Playing: **{title}**\n📍 Voice Chat: **{chat.title}**\n🎤 Requested by: {user.mention}")
        except Exception as e:
            queues.pop(str(chat_id), None)
            await m.edit(f"❌ Could not join group call: {e}")

# /skip
@app.on_message(filters.command("skip") & filters.group)
async def skip(_, message):
    user = message.from_user
    if not user or is_gbanned(user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.leave_group_call(chat_id)
    except GroupCallNotFoundError:
        return await message.reply("❌ Abhi koi music nahi chal raha!")
    next_title = await play_next(chat_id)
    if next_title:
        await message.reply(f"⏭ Skipped! Now playing: **{next_title}**")
    else:
        await message.reply("⏹ Queue khali hai, music stopped.")

# /stop
@app.on_message(filters.command("stop") & filters.group)
async def stop(_, message):
    user = message.from_user
    if not user or is_gbanned(user.id):
        return
    chat_id = message.chat.id
    queues.pop(str(chat_id), None)
    try:
        await call_py.leave_group_call(chat_id)
    except GroupCallNotFoundError:
        pass
    await message.reply("⏹ Music stopped aur queue clear ho gayi!")

# /pause
@app.on_message(filters.command("pause") & filters.group)
async def pause(_, message):
    user = message.from_user
    if not user or is_gbanned(user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.pause_stream(chat_id)
        await message.reply("⏸ Music paused!")
    except:
        await message.reply("❌ Abhi koi music nahi chal raha!")

# /resume
@app.on_message(filters.command("resume") & filters.group)
async def resume(_, message):
    user = message.from_user
    if not user or is_gbanned(user.id):
        return
    chat_id = message.chat.id
    try:
        await call_py.resume_stream(chat_id)
        await message.reply("▶️ Music resumed!")
    except:
        await message.reply("❌ Abhi koi paused music nahi hai!")

# ---------------- Owner Commands ----------------

@app.on_message(filters.command("gban"))
async def gban_cmd(_, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return
    if len(message.command) < 2:
        return
    try:
        user_id = int(message.command[1])
    except:
        return
    if user_id not in GBANNED:
        GBANNED.append(user_id)
        save_gbans()
        await message.reply(f"🚫 User `{user_id}` Globally Banned!")

@app.on_message(filters.command("ungban"))
async def ungban_cmd(_, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return
    if len(message.command) < 2:
        return
    try:
        user_id = int(message.command[1])
    except:
        return
    if user_id in GBANNED:
        GBANNED.remove(user_id)
        save_gbans()
        await message.reply(f"✅ User `{user_id}` Unbanned!")

@app.on_message(filters.command("broadcast"))
async def broadcast_cmd(_, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return
    success = fail = 0
    if message.reply_to_message:
        for chat_id in list(groups):
            try:
                await app.copy_message(chat_id, message.chat.id, message.reply_to_message.message_id)
                success += 1
            except:
                fail += 1
        await message.reply(f"✅ Broadcast done!\nSuccess: {success} | Failed: {fail}")
    else:
        if len(message.command) < 2:
            return
        text = " ".join(message.command[1:])
        for chat_id in list(groups):
            try:
                await app.send_message(chat_id, f"📢 Broadcast:\n\n{text}")
                success += 1
            except:
                fail += 1
        await message.reply(f"✅ Broadcast done!\nSuccess: {success} | Failed: {fail}")

@app.on_message(filters.command("active") & filters.private)
async def active_vc(_, message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return await message.reply("❌ Owner Only")
    active_text = "🎵 Active Voice Chats:\n\n"
    has_active = False
    for chat_id, q in queues.items():
        if q:
            try:
                chat = await app.get_chat(int(chat_id))
                active_text += f"📍 {chat.title} (ID: {chat_id}) - 🎶 {len(q)+1} song(s) in queue\n"
                has_active = True
            except:
                continue
    if not has_active:
        active_text = "⚠️ Abhi koi VC me music play nahi ho raha."
    await message.reply(active_text)

# ---------------- Live VC Join Monitor ----------------

async def monitor_vc(chat_id):
    if chat_id not in vc_users:
        vc_users[chat_id] = set()

    while True:
        try:
            participants = await call_py.get_participants(chat_id)
            current_users = set(p.user_id for p in participants)
            new_users = current_users - vc_users[chat_id]

            for user_id in new_users:
                user = await app.get_users(user_id)
                msg = await app.send_message(chat_id, f"🎤 {user.first_name} (ID: {user.id}) ne VC join kiya!")
                await asyncio.sleep(5)
                await msg.delete()

            vc_users[chat_id] = current_users
            await asyncio.sleep(1)
        except:
            await asyncio.sleep(5)

# Start monitoring VC for all groups
async def start_monitor_all_groups():
    for chat_id in groups:
        asyncio.create_task(monitor_vc(chat_id))

# ---------------- Startup ----------------

async def main():
    await app.start()
    await call_py.start()
    global groups
    groups = load_json(GROUPS_FILE, [])
    await start_monitor_all_groups()
    print("🎶 Music Bot Started!")
    await asyncio.get_event_loop().create_future()  # idle

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
