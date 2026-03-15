from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes


async def _orphaned_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Answer callback queries not handled by any ConversationHandler.

    With per_message=False, clicking buttons on stale inline keyboards (from a
    previous or abandoned flow) does not match the current ConversationHandler
    state, so query.answer() is never called — leaving Telegram in an infinite
    loading state.  This catch-all silently dismisses those orphaned callbacks.
    """
    query = update.callback_query
    if query:
        await query.answer()


orphaned_callback_handler = CallbackQueryHandler(_orphaned_callback)
