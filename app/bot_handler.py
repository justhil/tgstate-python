import asyncio
import json
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from .core.config import get_settings
from .services.telegram_service import get_telegram_service
from . import database
from .events import file_update_queue

async def handle_new_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理新增的文件或照片，将其元数据存入数据库，并通过队列发送通知。
    在函数内部检查消息来源是否为授权的聊天（私聊、群组或频道）。
    """
    settings = get_settings()
    message = update.message or update.channel_post

    # 1. 确保有消息
    if not message:
        return

    # 2. 检查消息来源是否为指定的频道/群组
    channel_identifier = settings.CHANNEL_NAME
    if not channel_identifier:
        print("错误: CHANNEL_NAME 未在 .env 中设置，无法处理文件。")
        return

    chat = message.chat
    is_allowed = False
    # 检查是公开频道 (e.g., "@username") 还是私密频道 (e.g., "-100123456789")
    if channel_identifier.startswith('@'):
        if chat.username and chat.username == channel_identifier.lstrip('@'):
            is_allowed = True
    else:
        if str(chat.id) == channel_identifier:
            is_allowed = True

    if not is_allowed:
        return

    # 3. 确定文件/照片信息
    file_obj = None
    file_name = None
    
    if message.document:
        file_obj = message.document
        file_name = file_obj.file_name
    elif message.photo:
        # 选择分辨率最高的照片
        file_obj = message.photo[-1]
        # 为照片创建一个默认文件名
        file_name = f"photo_{message.message_id}.jpg"

    # 4. 如果成功获取到文件或照片对象，则处理它
    if file_obj and file_name:
        # 我们只关心小于20MB的、非清单文件
        if file_obj.file_size < (20 * 1024 * 1024) and not file_name.endswith('.manifest'):
            # 使用复合ID "message_id:file_id"
            composite_id = f"{message.message_id}:{file_obj.file_id}"
            
            database.add_file_metadata(
                filename=file_name,
                file_id=composite_id,
                filesize=file_obj.file_size
            )
            
            # 将新文件信息放入队列，以便 SSE 端点可以推送给前端
            file_info = {
                "action": "add",
                "filename": file_name,
                "file_id": composite_id,
                "filesize": file_obj.file_size,
                "upload_date": message.date.isoformat()
            }
            await file_update_queue.put(json.dumps(file_info))

async def handle_get_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理对文件消息回复 "get" 的情况。
    """
    if not (update.message and update.message.reply_to_message and (update.message.reply_to_message.document or update.message.reply_to_message.photo)):
        return

    # 检查回复的文本是否完全是 "get"
    if update.message.text.lower().strip() != 'get':
        return

    document = update.message.reply_to_message.document or update.message.reply_to_message.photo[-1]
    file_id = document.file_id
    file_name = getattr(document, 'file_name', f"photo_{update.message.reply_to_message.message_id}.jpg")
    settings = get_settings()
    
    final_file_id = file_id
    final_file_name = file_name

    # 如果是清单文件，我们需要解析它以获取原始文件名
    if file_name.endswith('.manifest'):
        telegram_service = get_telegram_service()
        download_url = await telegram_service.get_download_url(file_id)
        if download_url:
            # 在实际应用中，我们应该流式处理而不是一次性下载
            # 但为了简化，我们先下载清单内容
            import httpx
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.get(download_url)
                    resp.raise_for_status()
                    content = resp.content
                    if content.startswith(b'tgstate-blob\n'):
                        lines = content.decode('utf-8').strip().split('\n')
                        final_file_name = lines[1] # 获取原始文件名
                        # file_id 保持为清单文件的 ID，下载路由会处理它
                except httpx.RequestError as e:
                    print(f"下载清单文件时出错: {e}")
                    await update.message.reply_text("错误：无法获取清单文件内容。")
                    return

    file_path = f"/d/{final_file_id}"
    
    if settings.BASE_URL:
        download_link = f"{settings.BASE_URL.strip('/')}{file_path}"
        reply_text = f"这是 '{final_file_name}' 的下载链接:\n{download_link}"
    else:
        reply_text = f"这是 '{final_file_name}' 的下载路径 (请自行拼接域名):\n`{file_path}`"

    await update.message.reply_text(reply_text)

async def handle_deleted_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    处理消息删除事件，同步删除数据库中的文件记录。
    """
    # 在 `python-telegram-bot` v20+ 中，删除事件是通过 `update.edited_message` 捕获的，
    # 当消息被删除时，它会变成一个内容为空的 `edited_message`。
    # 我们通过检查 `update.edited_message` 是否存在来判断消息是否被删除。
    if update.edited_message and not update.edited_message.text:
        message_id = update.edited_message.message_id
        deleted_file_id = database.delete_file_by_message_id(message_id)
        if deleted_file_id:
            # 如果成功删除了数据库记录，就通知前端
            delete_info = {
                "action": "delete",
                "file_id": deleted_file_id
            }
            await file_update_queue.put(json.dumps(delete_info))

def create_bot_app() -> Application:
    """
    创建并配置 Telegram Bot 应用实例。
    """
    settings = get_settings()
    if not settings.BOT_TOKEN:
        print("错误: .env 文件中未设置 BOT_TOKEN。机器人无法创建。")
        raise ValueError("BOT_TOKEN not configured.")

    application = Application.builder().token(settings.BOT_TOKEN).build()

    # --- 添加处理器 ---
    
    # 1. 处理对文件消息回复 "get" 的情况 (在任何地方)
    get_handler = MessageHandler(
        filters.TEXT & (~filters.COMMAND) & filters.REPLY,
        handle_get_reply
    )
    application.add_handler(get_handler)

    # 2. 处理所有文件和照片消息
    new_file_handler = MessageHandler(filters.ALL, handle_new_file)
    application.add_handler(new_file_handler, group=0)

    # 3. 处理消息删除事件
    # 注意：机器人需要有管理员权限才能接收到此事件
    delete_handler = MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_deleted_message)
    application.add_handler(delete_handler, group=1)
    
    return application
