import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

# --- FLASK SERVER (Render ke liye zaroori hai) ---
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is Running!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
MONETAG_LINK = os.getenv("MONETAG_DIRECT_LINK") # Env mein apna Monetag link daalein

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Jab user link se aaye (e.g., t.me/bot?start=123)
    if context.args:
        file_id = context.args[0]
        
        if not CHANNEL_ID or not MONETAG_LINK:
            await update.message.reply_text("❌ Env Vars (CHANNEL_ID ya MONETAG_LINK) missing hain.")
            return

        # Monetag Button setup
        keyboard = [
            [InlineKeyboardButton("📺 Watch Ad (Fast Server)", url=MONETAG_LINK)],
            [InlineKeyboardButton("📥 Direct Download", url=MONETAG_LINK)] # Dono par ads laga sakte hain
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Bot file bhejega aur niche Monetag ka ad button hoga
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=int(CHANNEL_ID),
                message_id=int(file_id),
                reply_markup=reply_markup
            )
        except Exception as e:
            await update.message.reply_text("❌ File link invalid hai ya bot channel mein admin nahi hai.")
    
    else:
        # Normal /start par sirf welcome message (Description aap BotFather se set karenge)
        await update.message.reply_text("👋 Welcome! File lene ke liye link par click karein.")

if __name__ == '__main__':
    # Flask thread start karein
    Thread(target=run_flask).start()

    if not TOKEN:
        print("❌ BOT_TOKEN missing!")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    print("🚀 Bot started without database load...")
    app.run_polling()
