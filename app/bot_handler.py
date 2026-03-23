import httpx
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from . import database
from .core.config import get_settings
from .events import publish_file_update
from .services.telegram_service import get_telegram_service
from .utils.file_paths import build_file_path


async def handle_new_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理新增的文件或照片，并在真正写入数据库后通知前端刷新。
    """
    settings = get_settings()
    message = update.message or update.channel_post
    if not message:
        return

    channel_identifier = settings.CHANNEL_NAME
    if not channel_identifier:
        print("错误: CHANNEL_NAME 未在 .env 中设置，无法处理文件。")
        return

    chat = message.chat
    is_allowed = False
    if channel_identifier.startswith('@'):
        if chat.username and chat.username == channel_identifier.lstrip('@'):
            is_allowed = True
    else:
        if str(chat.id) == channel_identifier:
            is_allowed = True

    if not is_allowed:
        return

    file_obj = None
    file_name = None
    if message.document:
        file_obj = message.document
        file_name = file_obj.file_name
    elif message.photo:
        file_obj = message.photo[-1]
        file_name = f"photo_{message.message_id}.jpg"

    if not (file_obj and file_name):
        return

    if file_obj.file_size >= 20 * 1024 * 1024 or file_name.endswith('.manifest'):
        return

    composite_id = f"{message.message_id}:{file_obj.file_id}"
    inserted = database.add_file_metadata(
        filename=file_name,
        file_id=composite_id,
        filesize=file_obj.file_size
    )
    if not inserted:
        return

    await publish_file_update(
        {
            "action": "add",
            "filename": file_name,
            "file_id": composite_id,
            "filesize": file_obj.file_size,
            "upload_date": message.date.isoformat()
        }
    )


async def handle_get_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理对文件消息回复 `get` 的情况。
    """
    if not (
        update.message
        and update.message.reply_to_message
        and (
            update.message.reply_to_message.document
            or update.message.reply_to_message.photo
        )
    ):
        return

    if update.message.text.lower().strip() != 'get':
        return

    document = update.message.reply_to_message.document or update.message.reply_to_message.photo[-1]
    file_id = document.file_id
    file_name = getattr(document, 'file_name', f"photo_{update.message.reply_to_message.message_id}.jpg")
    settings = get_settings()

    final_file_id = file_id
    final_file_name = file_name

    if file_name.endswith('.manifest'):
        telegram_service = get_telegram_service()
        download_url = await telegram_service.get_download_url(file_id)
        if download_url:
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.get(download_url)
                    resp.raise_for_status()
                    content = resp.content
                    if content.startswith(b'tgstate-blob\n'):
                        lines = content.decode('utf-8').strip().split('\n')
                        final_file_name = lines[1]
                except httpx.RequestError as exc:
                    print(f"下载清单文件时出错: {exc}")
                    await update.message.reply_text("错误：无法获取清单文件内容。")
                    return

    file_path = build_file_path(final_file_id, final_file_name, settings.FILE_ROUTE)
    if settings.BASE_URL:
        download_link = f"{settings.BASE_URL.strip('/')}{file_path}"
        reply_text = f"这是 '{final_file_name}' 的下载链接:\n{download_link}"
    else:
        reply_text = f"这是 '{final_file_name}' 的下载路径:\n`{file_path}`"

    await update.message.reply_text(reply_text)


def create_bot_app() -> Application:
    """创建并配置 Telegram Bot 应用实例。"""
    settings = get_settings()
    if not settings.BOT_TOKEN:
        print("错误: .env 文件中未设置 BOT_TOKEN。机器人无法创建。")
        raise ValueError("BOT_TOKEN not configured.")

    application = Application.builder().token(settings.BOT_TOKEN).build()

    get_handler = MessageHandler(
        filters.TEXT & (~filters.COMMAND) & filters.REPLY,
        handle_get_reply
    )
    application.add_handler(get_handler)

    new_file_handler = MessageHandler(filters.ALL, handle_new_file)
    application.add_handler(new_file_handler, group=0)

    return application
