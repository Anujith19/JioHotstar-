import logging
import os
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

# ലോഗിങ് സെറ്റ് ചെയ്യുക
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# /start കമാൻഡ്
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to JioHotstar Bot!\n\n"
        "• Send any JioHotstar video link to download.\n"
        "• Type /login to set up your account authentication."
    )

# /login കമാൻഡ് (OTP & Token ഓപ്ഷനുകൾ)
async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📱 OTP ലോഗിൻ (Phone Number)", callback_data="login_otp")],
        [InlineKeyboardButton("🔑 ഹോസ്റ്റാർ ടോക്കൺ നൽകുക", callback_data="login_token")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "**ജിയോ ഹോസ്റ്റാർ ലോഗിൻ രീതി തിരഞ്ഞെടുക്കുക:**\n\n"
        "താഴെയുള്ള ഓപ്ഷനുകളിൽ ഏതെങ്കിലും ഒന്ന് തിരഞ്ഞെടുക്കുക:",
        reply_markup=reply_markup
    )

# ലോഗിൻ ബട്ടണുകൾ ഹാൻഡ്ഡിൽ ചെയ്യുന്നത്
async def login_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "login_otp":
        context.user_data['waiting_for'] = 'phone_number'
        await query.message.edit_text(
            "📱 **OTP ലോഗിൻ:**\n\n"
            "ദയവായി നിങ്ങളുടെ ജിയോ ഹോസ്റ്റാറുമായി ബന്ധിപ്പിച്ചിരിക്കുന്ന ഫോൺ നമ്പർ അയക്കുക (ഉദാഹരണത്തിന്: `+919876543210`)."
        )
    elif query.data == "login_token":
        context.user_data['waiting_for'] = 'hotstar_token'
        await query.message.edit_text(
            "🔑 **ടോക്കൺ ലോഗിൻ:**\n\n"
            "ദയവായി നിങ്ങളുടെ ഹോസ്റ്റാർ അക്കൗണ്ടിന്റെ ടോക്കൺ അല്ലെങ്കിൽ കുക്കി ടെക്സ്റ്റ് ആയി ഇവിടെ അയക്കുക."
        )

# JioHotstar ലിങ്കും മറ്റ് ടെക്സ്റ്റുകളും ഹാൻഡ്ഡിൽ ചെയ്യുന്ന ഹാൻഡ്‌ലർ
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    waiting_for = context.user_data.get('waiting_for')
    
    # യൂസർ ഫോൺ നമ്പറാണ് അയച്ചതെങ്കിൽ
    if waiting_for == 'phone_number':
        context.user_data['waiting_for'] = None
        await update.message.reply_text(f"✅ ഫോൺ നമ്പർ സ്വീകരിച്ചു: {text}\nOTP അയക്കാനുള്ള പ്രക്രിയ പുരോഗമിക്കുന്നു...")
        return

    # യൂസർ ടോക്കൺ ആണ് അയച്ചതെങ്കിൽ
    elif waiting_for == 'hotstar_token':
        context.user_data['waiting_for'] = None
        # റെൻഡറിലെ എൻവയോൺമെന്റ് വേരിയബിൾ പോലെ താൽക്കാലികമായി സേവ് ചെയ്യുന്നു
        context.user_data['custom_token'] = text
        await update.message.reply_text("✅ ഹോസ്റ്റാർ ടോക്കൺ വിജയകരമായി സേവ് ചെയ്യപ്പെട്ടു!")
        return

    # സാധാരണ ഹോസ്റ്റാർ ലിങ്ക് ആണെങ്കിൽ ഡൗൺലോഡ് പ്രോസസ്സ് തുടങ്ങുക
    if "hotstar.com" in text:
        context.user_data['hotstar_url'] = text
        
        keyboard = [
            [InlineKeyboardButton("1080p (Full HD)", callback_data="q_1080p")],
            [InlineKeyboardButton("720p (HD)", callback_data="q_720p")],
            [InlineKeyboardButton("480p", callback_data="q_480p")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📥 Select video quality for download:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Please send a valid JioHotstar link containing 'hotstar.com' or use /login.")

# ഡൗൺലോഡും ക്വാളിറ്റിയും ഹാൻഡ്ഡിൽ ചെയ്യുന്ന ബട്ടൺ കോഡ്
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
        
        # യൂസർ നൽകിയ ടോക്കൺ അല്ലെങ്കിൽ എൻവയോൺമെന്റ് ടോക്കൺ എടുക്കുന്നു
        hotstar_token = context.user_data.get('custom_token') or os.getenv("HOTSTAR_TOKEN")
        
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
            
            with open(filename, 'rb') as video_file:
                await context.bot.send_video(chat_id=query.message.chat_id, video=video_file)
            
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
    app.add_handler(CommandHandler("login", login_command))
    
    # ലോഗിൻ ഇൻലൈൻ ബട്ടണുകൾക്കായി ഫിൽട്ടർ ചെയ്യുന്നു
    app.add_handler(CallbackQueryHandler(login_callback_handler, pattern="^login_"))
    
    # ഡൗൺലോഡ് ക്വാളിറ്റി ബട്ടണുകൾക്കായി ഫിൽട്ടർ ചെയ്യുന്നു
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^q_|^start_download$"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("JioHotstar All-in-One Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
