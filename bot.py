import logging
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

# --- FAKE SERVER FOR RENDER ---
# Ye Render ke "Port Timeout" error ko fix karega
app_flask = Flask('')

@app_flask.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    # Render automatically PORT environment variable deta hai
    port = int(os.environ.get("PORT", 10000))
    app_flask.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        file_id = context.args[0]
        if not CHANNEL_ID:
            await update.message.reply_text("❌ CHANNEL_ID missing in Env vars.")
            return
        try:
            await context.bot.copy_message(
                chat_id=update.effective_chat.id,
                from_chat_id=int(CHANNEL_ID),
                message_id=int(file_id)
            )
        except Exception as e:
            await update.message.reply_text("❌ File download link invalid ya bot admin nahi hai.")
    else:
        await update.message.reply_text("👋 Welcome! Send me a valid link to get files.")

if __name__ == '__main__':
    # 1. Start Flask in a separate thread
    Thread(target=run_flask).start()

    # 2. Start Telegram Bot
    if not TOKEN:
        print("❌ BOT_TOKEN missing!")
        exit(1)

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    print("🚀 Bot and Flask server started...")
    app.run_polling()
