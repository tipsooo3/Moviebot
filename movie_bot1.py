import os
import re
import requests
import threading
from urllib.parse import urlparse
from flask import Flask
from telegram import Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ===== Configuration =====
TOKEN = "8164504221:AAG8VFdDtvGlDUNO19DioCFdxaT8-3bLHhg"
CHANNEL_ID = "@moviex24"
MAX_SIZE = 2000 * 1024 * 1024  # 2GB Telegram limit
PORT = os.getenv('PORT', 8080)  # For Render health checks

# ===== Torrent Support (Comment out if not needed) =====
try:
    import libtorrent as lt
    TORRENT_SUPPORT = True
    ses = lt.session()
    ses.listen_on(6881, 6891)
    ses.start_dht()
except ImportError:
    TORRENT_SUPPORT = False

# ===== Flask Server for Render Health Checks =====
app = Flask(__name__)
@app.route('/')
def home():
    return "🎬 Movie Bot is Running"
def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# ===== Core Functions =====
def sanitize_filename(name):
    """Remove special chars from filenames"""
    return re.sub(r'[^\w\-_. ]', '', name)

def download_http(url):
    """Download HTTP files with progress"""
    filename = sanitize_filename(os.path.basename(urlparse(url).path) or "movie.mp4")
    
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        if total_size > MAX_SIZE:
            raise ValueError(f"File too large ({total_size//(1024*1024)}MB > {MAX_SIZE//(1024*1024)}MB limit)")
            
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
    return filename

def download_torrent(magnet_link):
    """Download torrents using libtorrent"""
    if not TORRENT_SUPPORT:
        raise ImportError("libtorrent not available")
    
    params = {'save_path': '.', 'storage_mode': lt.storage_mode_t(2)}
    handle = lt.add_magnet_uri(ses, magnet_link, params)
    
    print("⏳ Downloading metadata...")
    while not handle.has_metadata():
        pass
    
    handle.set_sequential_download(True)
    torrent_info = handle.get_torrent_info()
    filename = torrent_info.name()
    
    print(f"📥 Downloading: {filename}")
    while handle.status().progress != 1.0:
        pass
        
    return filename

# ===== Telegram Handlers =====
def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🎬 *Movie Upload Bot*\n\n"
        "Send me:\n"
        "- Direct HTTP links (MP4/MKV)\n"
        "- Magnet links (torrents)\n"
        "- /rename NewName.mp4 to rename files\n\n"
        f"📦 Torrent support: {'✅ Enabled' if TORRENT_SUPPORT else '❌ Disabled'}",
        parse_mode="Markdown"
    )

last_download = None

def handle_download(update: Update, context: CallbackContext):
    global last_download
    url = update.message.text.strip()
    
    try:
        msg = update.message.reply_text("⏳ Processing your request...")
        
        if url.startswith(('http://', 'https://')):
            filename = download_http(url)
        elif url.startswith('magnet:') and TORRENT_SUPPORT:
            filename = download_torrent(url)
        else:
            update.message.reply_text("❌ Unsupported link type")
            return
            
        last_download = filename
        with open(filename, 'rb') as f:
            context.bot.send_video(
                chat_id=CHANNEL_ID,
                video=InputFile(f),
                supports_streaming=True,
                timeout=300,
                caption=f"📤 Uploaded by @{update.message.from_user.username}"
            )
        msg.edit_text(f"✅ Success! Saved as: {filename}")
        
    except Exception as e:
        update.message.reply_text(f"❌ Error: {str(e)}")
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

def rename_file(update: Update, context: CallbackContext):
    global last_download
    if not last_download:
        update.message.reply_text("⚠️ No recent download to rename")
        return
        
    new_name = ' '.join(context.args)
    if not new_name:
        update.message.reply_text("Usage: /rename New Movie Name.mp4")
        return
        
    try:
        os.rename(last_download, sanitize_filename(new_name))
        last_download = new_name
        update.message.reply_text(f"✅ Renamed to: {new_name}")
    except Exception as e:
        update.message.reply_text(f"❌ Rename failed: {str(e)}")

# ===== Main Execution =====
def main():
    # Start Flask server in background
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Telegram bot
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("rename", rename_file))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_download))
    
    print("🤖 Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()