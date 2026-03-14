import os
import subprocess
import sys
from functools import wraps

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import settings


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != settings.admin_user_id:
            return
        return await func(update, context)

    return wrapper


@admin_only
async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("⏳ Pulling latest code...")
    try:
        subprocess.run(["git", "pull"], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        await update.message.reply_text(f"❌ git pull failed:\n{e.stderr.decode()}")
        return
    await update.message.reply_text("✅ Done. Restarting...")
    os.execv(sys.executable, [sys.executable] + sys.argv)
