import logging
import os
import json
import signal
import re
import requests
from telethon import TelegramClient, events
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# Muat variabel dari file .env
load_dotenv()

# Konfigurasi logging
logging.basicConfig(
    filename='telegram_forwarder.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ambil konfigurasi dari .env
API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
PHONE = os.getenv('TELEGRAM_PHONE')
ADMINS = os.getenv('ADMINS').split(',')  # Daftar admin, pisahkan dengan koma jika lebih dari satu
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DISCORD_CHANNEL_ID = os.getenv('DISCORD_CHANNEL_ID')

# File untuk menyimpan daftar channel dan keywords
CHANNELS_FILE = 'channels.json'
KEYWORDS_FILE = 'keywords.json'

# Muat daftar channel dan keywords dari file JSON
def load_config():
    global FILTERED_CHANNELS, UNFILTERED_CHANNELS, KEYWORDS
    try:
        with open(CHANNELS_FILE, 'r') as f:
            channels_data = json.load(f)
            FILTERED_CHANNELS = channels_data.get('FILTERED_CHANNELS', [])
            UNFILTERED_CHANNELS = channels_data.get('UNFILTERED_CHANNELS', [])
        with open(KEYWORDS_FILE, 'r') as f:
            keywords_data = json.load(f)
            KEYWORDS = keywords_data.get('KEYWORDS', [])
    except FileNotFoundError:
        FILTERED_CHANNELS = []
        UNFILTERED_CHANNELS = []
        KEYWORDS = []
        logger.warning("File konfigurasi tidak ditemukan. Menggunakan daftar kosong.")
        with open(CHANNELS_FILE, 'w') as f:
            json.dump({'FILTERED_CHANNELS': [], 'UNFILTERED_CHANNELS': []}, f)
        with open(KEYWORDS_FILE, 'w') as f:
            json.dump({'KEYWORDS': []}, f)

load_config()

# Inisialisasi client Telegram
client = TelegramClient('telegram_session', API_ID, API_HASH)

# Fungsi untuk mengekstrak username dari link atau username langsung
def extract_username(input_str):
    if input_str.startswith('@'):
        return input_str[1:]  # Hilangkan "@" dari awal
    url_pattern = r'https?://t\.me/(\w+)'
    match = re.search(url_pattern, input_str)
    if match:
        return match.group(1)
    return input_str

# Fungsi untuk memeriksa kata kunci dalam pesan
def contains_keyword(text, keywords):
    text_lower = text.lower()
    return any(keyword.lower() in text_lower for keyword in keywords)

# Fungsi untuk mengirim pesan ke Discord
def send_to_discord(message_content):
    url = f"https://discord.com/api/v9/channels/{DISCORD_CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "content": message_content[:2000]  # Discord memiliki batas 2000 karakter
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            logger.info("Pesan berhasil dikirim ke Discord.")
        else:
            logger.error(f"Gagal mengirim ke Discord: {response.status_code}, {response.text}")
    except Exception as e:
        logger.error(f"Error saat mengirim ke Discord: {str(e)}")

# Fungsi untuk login
async def login():
    try:
        await client.start(phone=PHONE)
        if not await client.is_user_authorized():
            logger.info("Memulai proses login...")
            code = input("Masukkan kode verifikasi yang diterima: ")
            try:
                await client.sign_in(PHONE, code)
            except SessionPasswordNeededError:
                password = input("Masukkan kata sandi 2FA Anda: ")
                await client.sign_in(password=password)
        logger.info("Login berhasil!")
    except Exception as e:
        logger.error(f"Gagal login: {str(e)}")
        raise

# Event handler untuk pesan baru
@client.on(events.NewMessage(chats=FILTERED_CHANNELS + UNFILTERED_CHANNELS))
async def forward_message(event):
    try:
        message = event.message
        chat_id = event.chat.username or event.chat.id
        logger.info(f"Pesan baru diterima dari {chat_id}: {message.id} - Teks: {message.text}")

        if chat_id in FILTERED_CHANNELS:
            if message.text and contains_keyword(message.text, KEYWORDS):
                send_to_discord(f"From Telegram ({chat_id}): {message.text}")
                logger.info(f"Pesan {message.id} dari {chat_id} diteruskan ke Discord")
            else:
                logger.info(f"Pesan dari {chat_id} tidak mengandung keyword: {message.text}")
        elif chat_id in UNFILTERED_CHANNELS:
            send_to_discord(f"From Telegram ({chat_id}): {message.text}")
            logger.info(f"Pesan {message.id} dari {chat_id} diteruskan ke Discord")
    except Exception as e:
        logger.error(f"Gagal memproses pesan {message.id}: {str(e)}")

# Event handler untuk perintah /add_filter_channel
@client.on(events.NewMessage(pattern='/add_filter_channel (.+)'))
async def add_filter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    input_str = event.pattern_match.group(1)
    channel_name = extract_username(input_str)
    if channel_name not in FILTERED_CHANNELS:
        FILTERED_CHANNELS.append(channel_name)
        with open(CHANNELS_FILE, 'w') as f:
            json.dump({'FILTERED_CHANNELS': FILTERED_CHANNELS, 'UNFILTERED_CHANNELS': UNFILTERED_CHANNELS}, f)
        await event.reply(f"Channel {channel_name} ditambahkan ke FILTERED_CHANNELS.")
        logger.info(f"Channel {channel_name} ditambahkan ke FILTERED_CHANNELS: {FILTERED_CHANNELS}")
    else:
        await event.reply(f"Channel {channel_name} sudah ada di FILTERED_CHANNELS.")

# Event handler untuk perintah /add_unfilter_channel
@client.on(events.NewMessage(pattern='/add_unfilter_channel (.+)'))
async def add_unfilter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    input_str = event.pattern_match.group(1)
    channel_name = extract_username(input_str)
    if channel_name not in UNFILTERED_CHANNELS:
        UNFILTERED_CHANNELS.append(channel_name)
        with open(CHANNELS_FILE, 'w') as f:
            json.dump({'FILTERED_CHANNELS': FILTERED_CHANNELS, 'UNFILTERED_CHANNELS': UNFILTERED_CHANNELS}, f)
        await event.reply(f"Channel {channel_name} ditambahkan ke UNFILTERED_CHANNELS.")
        logger.info(f"Channel {channel_name} ditambahkan ke UNFILTERED_CHANNELS: {UNFILTERED_CHANNELS}")
    else:
        await event.reply(f"Channel {channel_name} sudah ada di UNFILTERED_CHANNELS.")

# Event handler untuk perintah /add_keyword
@client.on(events.NewMessage(pattern='/add_keyword (.+)'))
async def add_keyword(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    keyword = event.pattern_match.group(1)
    if keyword not in KEYWORDS:
        KEYWORDS.append(keyword)
        with open(KEYWORDS_FILE, 'w') as f:
            json.dump({'KEYWORDS': KEYWORDS}, f)
        await event.reply(f"Keyword {keyword} ditambahkan.")
        logger.info(f"Keyword {keyword} ditambahkan: {KEYWORDS}")
    else:
        await event.reply(f"Keyword {keyword} sudah ada.")

# Event handler untuk perintah /remove_filter_channel
@client.on(events.NewMessage(pattern='/remove_filter_channel (.+)'))
async def remove_filter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    input_str = event.pattern_match.group(1)
    channel_name = extract_username(input_str)
    if channel_name in FILTERED_CHANNELS:
        FILTERED_CHANNELS.remove(channel_name)
        with open(CHANNELS_FILE, 'w') as f:
            json.dump({'FILTERED_CHANNELS': FILTERED_CHANNELS, 'UNFILTERED_CHANNELS': UNFILTERED_CHANNELS}, f)
        await event.reply(f"Channel {channel_name} dihapus dari FILTERED_CHANNELS.")
        logger.info(f"Channel {channel_name} dihapus dari FILTERED_CHANNELS: {FILTERED_CHANNELS}")
    else:
        await event.reply(f"Channel {channel_name} tidak ditemukan di FILTERED_CHANNELS.")

# Event handler untuk perintah /remove_unfilter_channel
@client.on(events.NewMessage(pattern='/remove_unfilter_channel (.+)'))
async def remove_unfilter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    input_str = event.pattern_match.group(1)
    channel_name = extract_username(input_str)
    if channel_name in UNFILTERED_CHANNELS:
        UNFILTERED_CHANNELS.remove(channel_name)
        with open(CHANNELS_FILE, 'w') as f:
            json.dump({'FILTERED_CHANNELS': FILTERED_CHANNELS, 'UNFILTERED_CHANNELS': UNFILTERED_CHANNELS}, f)
        await event.reply(f"Channel {channel_name} dihapus dari UNFILTERED_CHANNELS.")
        logger.info(f"Channel {channel_name} dihapus dari UNFILTERED_CHANNELS: {UNFILTERED_CHANNELS}")
    else:
        await event.reply(f"Channel {channel_name} tidak ditemukan di UNFILTERED_CHANNELS.")

# Event handler untuk perintah /remove_keyword
@client.on(events.NewMessage(pattern='/remove_keyword (.+)'))
async def remove_keyword(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    keyword = event.pattern_match.group(1)
    if keyword in KEYWORDS:
        KEYWORDS.remove(keyword)
        with open(KEYWORDS_FILE, 'w') as f:
            json.dump({'KEYWORDS': KEYWORDS}, f)
        await event.reply(f"Keyword {keyword} dihapus.")
        logger.info(f"Keyword {keyword} dihapus: {KEYWORDS}")
    else:
        await event.reply(f"Keyword {keyword} tidak ditemukan.")

# Event handler untuk perintah /list_filter
@client.on(events.NewMessage(pattern='/list_filter'))
async def list_filter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    if FILTERED_CHANNELS:
        list_str = "Filter Channel:\n"
        list_str += "\n".join([f"{i+1}. {channel}" for i, channel in enumerate(FILTERED_CHANNELS)])
        await event.reply(f"```\n{list_str}\n```")
    else:
        await event.reply("Tidak ada channel di FILTERED_CHANNELS.")

# Event handler untuk perintah /list_unfilter
@client.on(events.NewMessage(pattern='/list_unfilter'))
async def list_unfilter_channel(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    if UNFILTERED_CHANNELS:
        list_str = "Unfilter Channel:\n"
        list_str += "\n".join([f"{i+1}. {channel}" for i, channel in enumerate(UNFILTERED_CHANNELS)])
        await event.reply(f"```\n{list_str}\n```")
    else:
        await event.reply("Tidak ada channel di UNFILTERED_CHANNELS.")

# Event handler untuk perintah /list_keyword
@client.on(events.NewMessage(pattern='/list_keyword'))
async def list_keyword(event):
    if str(event.sender_id) not in ADMINS:
        await event.reply("Anda tidak diizinkan untuk menjalankan perintah ini.")
        return
    if KEYWORDS:
        list_str = "Keywords:\n"
        list_str += "\n".join([f"{i+1}. {keyword}" for i, channel in enumerate(KEYWORDS)])
        await event.reply(f"```\n{list_str}\n```")
    else:
        await event.reply("Tidak ada keyword yang ditambahkan.")

# Fungsi untuk menutup client dengan benar
async def shutdown_client():
    logger.info("Menghentikan client...")
    await client.disconnect()
    logger.info("Client berhasil dihentikan.")

# Fungsi utama
async def main():
    try:
        await login()
        logger.info("Client berjalan, memantau channel...")
        print(f"Skrip berjalan pada {datetime.now()}. Cek telegram_forwarder.log untuk detail.")
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Error di fungsi utama: {str(e)}")
        print(f"Terjadi error, cek log untuk detail: {str(e)}")

# Jalankan skrip
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    task = loop.create_task(main())

    def handle_interrupt():
        logger.info("Menerima sinyal penghentian, menutup client...")
        loop.create_task(shutdown_client())

    signal.signal(signal.SIGINT, lambda s, f: handle_interrupt())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(asyncio.sleep(1))
        loop.close()
        logger.info("Script selesai.")
