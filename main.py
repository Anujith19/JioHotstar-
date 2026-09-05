import logging
import os
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

# ലോഗിങ് സെറ്റ് ചെയ്യുക
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ⚠️ Render/Heroku-ൽ Environment Variable ആയി PROXY കൊടുത്തിട്ടില്ലെങ്കിൽ താഴെ പറയുന്ന ഡിഫോൾട്ട് പ്രോക്സി ഉപയോഗിക്കും.
# ആവശ്യമെങ്കിൽ 'http://139.59.59.122:8012' എന്ന ഭാഗത്ത് പുതിയ പ്രോക്സി മാറ്റാം.
DEFAULT_PROXY = "http://139.59.59.122:8012"

# /start കമാൻഡ്
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to JioHotstar Downloader Bot!\nSend any JioHotstar video link to download.")

# JioHotstar ലിങ്ക് പരിശോധിക്കുന്ന ഹാൻഡ്‌ലർ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if "hotstar.com" in text:
        context.user_data['hotstar_url'] = text
        
        # ക്വാളിറ്റികളും ഓഡിയോ സെലക്ഷനും ഉൾപ്പെടുത്തിയ ബട്ടണുകൾ
        keyboard = [
            [
                InlineKeyboardButton("🎬 Best Quality", callback_data="q_best"),
                InlineKeyboardButton("📺 1080p", callback_data="q_1080p")
            ],
            [
                InlineKeyboardButton("📱 720p", callback_data="q_720p"),
                InlineKeyboardButton("📱 480p", callback_data="q_480p")
            ],
            [
                InlineKeyboardButton("⚡ 360p (Data Saver)", callback_data="q_360p"),
                InlineKeyboardButton("🎵 Audio Only (MP3/M4A)", callback_data="q_audio")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📥 Select Quality or Audio Option:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please send a valid JioHotstar link containing 'hotstar.com'.")

# ബട്ടൺ ക്ലിക്ക് ചെയ്യുമ്പോൾ ഡൗൺലോഡിങ് പ്രോസസ്സ്
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("q_"):
        selected_option = query.data.split("_")[1]
        context.user_data['selected_option'] = selected_option
        
        display_text = "Audio Only" if selected_option == "audio" else f"{selected_option}"
        
        keyboard = [
            [InlineKeyboardButton("🚀 Start Download", callback_data="start_download")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"Selected Option: {display_text}\nClick below to start downloading:", reply_markup=reply_markup)
        
    elif query.data == "start_download":
        await query.edit_message_text(text="⏳ Processing & Downloading from JioHotstar... Please wait.")
        
        url = context.user_data.get('hotstar_url')
        selected_option = context.user_data.get('selected_option', 'best')
        
        # Format Selection (വീഡിയോ/ഓഡിയോ അനുസരിച്ച് മാറ്റം വരുത്തുന്നു)
        if selected_option == "audio":
            format_spec = 'bestaudio/best'
            out_extension = 'downloads/%(title)s.%(ext)s'
        elif selected_option == "best":
            format_spec = 'bestvideo+bestaudio/best'
            out_extension = 'downloads/%(title)s.%(ext)s'
        else:
            height = selected_option.replace('p', '')
            format_spec = f'bestvideo[height<={height}]+bestaudio/best[height<={height}]/best'
            out_extension = 'downloads/%(title)s.%(ext)s'
        
        # PROXY വേരിയബിൾ പരിശോധിക്കുന്നു (Render/Heroku Env Variable അല്ലെങ്കിൽ ഡിഫോൾട്ട് പ്രോക്സി)
        proxy_address = os.getenv("PROXY", DEFAULT_PROXY)
        
        ydl_opts = {
            'format': format_spec,
            'outtmpl': out_extension,
            'geo_bypass': True,
            'geo_bypass_country': 'IN',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }
        
        # പ്രോക്സി ചേർക്കുന്നു
        if proxy_address:
            ydl_opts['proxy'] = proxy_address
        
        # Cookies പരിശോധന (Environment Variable അല്ലെങ്കിൽ cookies.txt ഫയൽ)
        hotstar_cookies = os.getenv("HOTSTAR_COOKIES")
        if hotstar_cookies:
            cookie_file_path = "cookies.txt"
            with open(cookie_file_path, "w", encoding="utf-8") as f:
                f.write(hotstar_cookies)
            ydl_opts['cookiefile'] = cookie_file_path
        elif os.path.exists("cookies.txt"):
            ydl_opts['cookiefile'] = "cookies.txt"

        try:
            os.makedirs('downloads', exist_ok=True)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
            
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Download completed! Uploading to Telegram...")
            
            # ഓഡിയോ ആണെങ്കിൽ Audio ആയും, വീഡിയോ ആണെങ്കിൽ Video ആയും അയക്കുന്നു
            with open(filename, 'rb') as file_data:
                if selected_option == "audio":
                    await context.bot.send_audio(chat_id=query.message.chat_id, audio=file_data)
                else:
                    await context.bot.send_video(chat_id=query.message.chat_id, video=file_data)
            
            # ഫയൽ ഡിലീറ്റ് ചെയ്ത് ഫ്രീ ആക്കുന്നു
            if os.path.exists(filename):
                os.remove(filename)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Download failed: {str(e)}")

def main():
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing in Environment Variables!")
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("JioHotstar Downloader Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
