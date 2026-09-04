import logging
import os
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

# ലോഗിങ് സെറ്റ് ചെയ്യുക
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(name)

# /start കമാൻഡ്
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Welcome to JioHotstar Downloader Bot!\nSend any JioHotstar video link to download.")

# JioHotstar ലിങ്ക് പരിശോധിക്കുന്ന ഹാൻഡ്‌ലർ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if "hotstar.com" in text:
        context.user_data['hotstar_url'] = text
        
        # ക്വാളിറ്റി സെലക്ട് ചെയ്യാനുള്ള ബട്ടണുകൾ
        keyboard = [
            [InlineKeyboardButton("1080p (Full HD)", callback_data="q_1080p")],
            [InlineKeyboardButton("720p (HD)", callback_data="q_720p")],
            [InlineKeyboardButton("480p", callback_data="q_480p")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📥 Select video quality for download:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please send a valid JioHotstar link containing 'hotstar.com'.")

# ബട്ടൺ ക്ലിക്ക് ചെയ്യുമ്പോൾ ഡൗൺലോഡിങ് പ്രോസസ്സ് ആരംഭിക്കുന്നത്
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("q_"):
        quality = query.data.split("_")[1]
        context.user_data['quality'] = quality
        
        keyboard = [
            [InlineKeyboardButton("Submit / Download 🚀", callback_data="start_download")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=f"Selected Quality: {quality}\nClick Submit to start downloading:", reply_markup=reply_markup)
        
    elif query.data == "start_download":
        await query.edit_message_text(text="⏳ Downloading video from JioHotstar... Please wait.")
        
        url = context.user_data.get('hotstar_url')
        quality = context.user_data.get('quality', '720p')
        height = quality.replace('p', '')
        
        # Environment Variable-ൽ നിന്ന് ഹോസ്റ്റാർ ടോക്കൺ എടുക്കുന്നു
        hotstar_token = os.getenv("HOTSTAR_TOKEN")
        
        # yt-dlp സെറ്റിങ്സ്
        ydl_opts = {
            'format': f'best[height<={height}]',
            'outtmpl': 'downloads/%(title)s.%(ext)s',
        }
        
        if hotstar_token:
            ydl_opts['http_headers'] = {'Authorization': f'Bearer {hotstar_token}'}

        try:
            os.makedirs('downloads', exist_ok=True)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
            
            await context.bot.send_message(chat_id=query.message.chat_id, text="✅ Download completed! Uploading to Telegram...")
            
            # ടെലിഗ്രാമിലേക്ക് വീഡിയോ അയക്കുന്നു
            with open(filename, 'rb') as video_file:
                await context.bot.send_video(chat_id=query.message.chat_id, video=video_file)
            
            # ഫയൽ ഡിലീറ്റ് ചെയ്ത് സ്റ്റോറേജ് ക്ലീൻ ചെയ്യുന്നു
            os.remove(filename)
            
        except Exception as e:
            logger.error(f"Error: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=f"❌ Download failed: {str(e)}")

def main():
    # ബോട്ട് ടോക്കൺ പൂർണ്ണമായും Environment Variable വഴി മാത്രം എടുക്കുന്നു (നേരിട്ട് ടോക്കൺ ഇല്ല)
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    
    if not TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN is missing in Environment Variables!")
    
    app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("JioHotstar Downloader Bot is running...")
    app.run_polling()

if name == "main":
    main()
