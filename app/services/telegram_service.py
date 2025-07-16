import telegram
import os
import io
from functools import lru_cache
from typing import BinaryIO
import telegram
from telegram import Update
from telegram.ext import CallbackContext
from telegram.request import HTTPXRequest
from ..core.config import Settings, get_settings
from .. import database

# Telegram Bot API 对通过 getFile 方法下载的文件有 20MB 的限制。
# 我们将分块大小设置为 19.5MB 以确保上传和下载都能成功。
CHUNK_SIZE_BYTES = int(19.5 * 1024 * 1024)

class TelegramService:
    """
    用于与 Telegram Bot API 交互的服务。
    """
    def __init__(self, settings: Settings):
        # 为大文件上传设置更长的超时时间 (例如 5 分钟)
        request = HTTPXRequest(
            connect_timeout=300.0,
            read_timeout=300.0,
            write_timeout=300.0
        )
        self.bot = telegram.Bot(token=settings.BOT_TOKEN, request=request)
        self.channel_name = settings.CHANNEL_NAME

    async def _upload_chunk(self, chunk_data: bytes, chunk_name: str) -> str | None:
        """一个上传单个数据块的辅助函数。"""
        try:
            with io.BytesIO(chunk_data) as document_chunk:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=document_chunk,
                    filename=chunk_name
                )
            if message.document:
                return message.document.file_id
        except Exception as e:
            print(f"上传分块 {chunk_name} 到 Telegram 时出错: {e}")
        return None

    async def _upload_as_chunks(self, file_path: str, original_filename: str) -> str | None:
        """
        将大文件分割成块，并通过回复链将所有部分聚合起来。
        """
        chunk_file_ids = []
        first_message_id = None
        
        try:
            with open(file_path, 'rb') as f:
                chunk_number = 1
                while True:
                    chunk = f.read(CHUNK_SIZE_BYTES)
                    if not chunk:
                        break
                    
                    chunk_name = f"{original_filename}.part{chunk_number}"
                    print(f"正在上传分块: {chunk_name}")
                    
                    with io.BytesIO(chunk) as chunk_io:
                        # 如果是第一个块，正常发送。否则，作为对第一个块的回复发送。
                        reply_to_id = first_message_id if first_message_id else None
                        message = await self.bot.send_document(
                            chat_id=self.channel_name,
                            document=chunk_io,
                            filename=chunk_name,
                            reply_to_message_id=reply_to_id
                        )
                    
                    # 如果是第一个块，保存其 message_id
                    if not first_message_id:
                        first_message_id = message.message_id
                    
                    # 关键变更：存储复合ID (message_id:file_id) 而不是只有 file_id
                    chunk_file_ids.append(f"{message.message_id}:{message.document.file_id}")
                    chunk_number += 1
        except IOError as e:
            print(f"读取或上传文件块时出错: {e}")
            return None
        except Exception as e:
            print(f"发送文件块时出错: {e}")
            return None

        # 生成并上传清单文件，同样作为对第一个块的回复
        manifest_content = f"tgstate-blob\n{original_filename}\n" + "\n".join(chunk_file_ids)
        manifest_name = f"{original_filename}.manifest"
        
        print("所有分块上传完毕。正在上传清单文件...")
        try:
            with io.BytesIO(manifest_content.encode('utf-8')) as manifest_file:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=manifest_file,
                    filename=manifest_name,
                    reply_to_message_id=first_message_id
                )
            if message.document:
                print("清单文件上传成功。")
                # 将大文件的元数据存入数据库
                total_size = os.path.getsize(file_path)
                # 创建复合ID，格式为 "message_id:file_id"
                composite_id = f"{message.message_id}:{message.document.file_id}"
                database.add_file_metadata(
                    filename=original_filename,
                    file_id=composite_id, # 我们存储复合ID
                    filesize=total_size
                )
                return composite_id # 返回复合ID
        except Exception as e:
            print(f"上传清单文件时出错: {e}")
        
        return None

    async def upload_file(self, file_path: str, file_name: str) -> str | None:
        """
        将文件上传到指定的 Telegram 频道。
        如果文件大于 200MB，则分块上传。
        
        参数:
            file_path: 文件的本地路径。
            file_name: 文件名。

        返回:
            如果成功，则返回文件的 file_id，否则返回 None。
        """
        if not self.channel_name:
            print("错误：环境变量中未设置 CHANNEL_NAME。")
            return None
        
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            print(f"无法获取文件大小: {e}")
            return None

        if file_size >= CHUNK_SIZE_BYTES:
            print(f"文件大小 ({file_size / 1024 / 1024:.2f} MB) 超过或等于 {CHUNK_SIZE_BYTES / 1024 / 1024:.2f}MB。正在启动分块上传...")
            return await self._upload_as_chunks(file_path, file_name)
        
        print(f"文件大小 ({file_size / 1024 / 1024:.2f} MB) 小于 {CHUNK_SIZE_BYTES / 1024 / 1024:.2f}MB。正在直接上传...")
        try:
            with open(file_path, 'rb') as document_file:
                message = await self.bot.send_document(
                    chat_id=self.channel_name,
                    document=document_file,
                    filename=file_name
                )
            if message.document:
                # 将小文件的元数据存入数据库
                # 创建复合ID，格式为 "message_id:file_id"
                composite_id = f"{message.message_id}:{message.document.file_id}"
                database.add_file_metadata(
                    filename=file_name,
                    file_id=composite_id, # 存储复合ID
                    filesize=file_size
                )
                return composite_id # 返回复合ID
        except Exception as e:
            print(f"上传文件到 Telegram 时出错: {e}")
        
        return None

    async def get_download_url(self, file_id: str) -> str | None:
        """
        为给定的 file_id 获取临时下载链接。

        参数:
            file_id: 来自 Telegram 的文件 ID。

        返回:
            如果成功，则返回临时下载链接，否则返回 None。
        """
        try:
            file = await self.bot.get_file(file_id)
            return file.file_path
        except Exception as e:
            print(f"从 Telegram 获取下载链接时出错: {e}")
            return None

    async def delete_message(self, message_id: int) -> bool:
        """
        从频道中删除指定 ID 的消息。

        参数:
            message_id: 要删除的消息的 ID。

        返回:
            如果成功，则返回 True，否则返回 False。
        """
        try:
            # bot.delete_message 返回 True 表示成功
            success = await self.bot.delete_message(
                chat_id=self.channel_name,
                message_id=message_id
            )
            return success
        except telegram.error.BadRequest as e:
            # 处理消息找不到或无权删除等情况
            print(f"删除消息 {message_id} 失败: {e}")
            return False
        except Exception as e:
            print(f"删除消息 {message_id} 时发生未知错误: {e}")
            return False

    async def delete_file_with_chunks(self, file_id: str) -> dict:
        """
        完全删除一个文件，包括其所有可能的分块。
        该函数会处理清单文件，并删除所有引用的分块。

        参数:
            file_id: 要删除的文件的复合 ID ("message_id:actual_file_id")。

        返回:
            一个包含删除操作结果的字典。
        """
        results = {
            "status": "pending",
            "main_file_id": file_id,
            "deleted_chunks": [],
            "failed_chunks": [],
            "main_message_deleted": False,
            "is_manifest": False,
            "reason": ""
        }

        try:
            main_message_id_str, main_actual_file_id = file_id.split(':', 1)
            main_message_id = int(main_message_id_str)
        except (ValueError, IndexError):
            results["status"] = "error"
            results["reason"] = "Invalid composite file_id format."
            return results

        # 步骤 1: 检查文件是否为清单
        download_url = await self.get_download_url(main_actual_file_id)
        if not download_url:
            print(f"警告: 无法为文件 {main_actual_file_id} 获取下载链接。将只尝试删除主消息。")
            results["reason"] = f"Could not get download URL for {main_actual_file_id}."
        else:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(download_url)
                    if response.status_code == 200 and response.content.startswith(b'tgstate-blob\n'):
                        results["is_manifest"] = True
                        print(f"文件 {file_id} 是一个清单文件。正在处理分块删除...")
                        
                        manifest_content = response.content.decode('utf-8')
                        lines = manifest_content.strip().split('\n')
                        chunk_composite_ids = lines[2:]

                        for chunk_id in chunk_composite_ids:
                            try:
                                chunk_message_id_str, _ = chunk_id.split(':', 1)
                                chunk_message_id = int(chunk_message_id_str)
                                if await self.delete_message(chunk_message_id):
                                    results["deleted_chunks"].append(chunk_id)
                                else:
                                    results["failed_chunks"].append(chunk_id)
                            except Exception as e:
                                print(f"处理或删除分块 {chunk_id} 时出错: {e}")
                                results["failed_chunks"].append(chunk_id)
            except Exception as e:
                error_message = f"下载或解析清单文件 {file_id} 时出错: {e}"
                print(error_message)
                results["reason"] += " " + error_message
                # 即使清单处理失败，我们也要继续尝试删除主消息

        # 步骤 2: 删除主消息 (清单文件本身或单个文件)
        if await self.delete_message(main_message_id):
            results["main_message_deleted"] = True
            print(f"主消息 {main_message_id} 已成功删除。")
        else:
            print(f"删除主消息 {main_message_id} 失败。")

        if results["main_message_deleted"] and (not results["is_manifest"] or not results["failed_chunks"]):
             results["status"] = "success"
        else:
             results["status"] = "partial_failure"
             if not results["main_message_deleted"]:
                 results["reason"] += " Failed to delete main message."
             if results["failed_chunks"]:
                 results["reason"] += f" Failed to delete {len(results['failed_chunks'])} chunks."


        return results


    async def list_files_in_channel(self) -> list[dict]:
        """
        遍历频道历史记录，智能地列出所有文件。
        - 小于20MB的文件直接显示。
        - 大于20MB但通过清单管理的文件，显示原始文件名。
        """
        files = []
        # Telegram API 限制 get_chat_history 一次最多返回 100 条
        # 我们需要循环获取，直到没有更多消息
        last_message_id = None
        
        # 为了避免无限循环，我们设置一个最大迭代次数
        MAX_ITERATIONS = 100
        
        print("开始从频道获取历史消息...")
        
        for i in range(MAX_ITERATIONS):
            try:
                # 获取一批消息
                messages = await self.bot.get_chat_history(
                    chat_id=self.channel_name,
                    limit=100,
                    offset_id=last_message_id if last_message_id else 0
                )
            except Exception as e:
                print(f"获取聊天历史时出错: {e}")
                break

            if not messages:
                print("没有更多历史消息了。")
                break

            for message in messages:
                if message.document:
                    doc = message.document
                    # 小于20MB的普通文件
                    if doc.file_size < 20 * 1024 * 1024 and not doc.file_name.endswith('.manifest'):
                        files.append({
                            "name": doc.file_name,
                            "file_id": doc.file_id,
                            "size": doc.file_size
                        })
                    # 清单文件
                    elif doc.file_name.endswith('.manifest'):
                        # 下载并解析清单文件以获取原始文件名和大小
                        manifest_url = await self.get_download_url(doc.file_id)
                        if not manifest_url: continue
                        
                        import httpx
                        async with httpx.AsyncClient() as client:
                            try:
                                resp = await client.get(manifest_url)
                                if resp.status_code == 200 and resp.content.startswith(b'tgstate-blob\n'):
                                    lines = resp.content.decode('utf-8').strip().split('\n')
                                    original_filename = lines[1]
                                    # 注意：这里我们无法轻易获得原始总大小，暂时留空
                                    files.append({
                                        "name": original_filename,
                                        "file_id": doc.file_id, # 关键：使用清单文件的ID
                                        "size": None # 标记为未知大小
                                    })
                            except httpx.RequestError:
                                continue
            
            # 设置下一次迭代的偏移量
            last_message_id = messages[-1].message_id
            print(f"已处理批次 {i+1}，最后的消息 ID: {last_message_id}")

        print(f"文件列表获取完毕，共找到 {len(files)} 个有效文件。")
        return files

@lru_cache()
def get_telegram_service() -> TelegramService:
    """
    TelegramService 的缓存工厂函数。
    """
    return TelegramService(settings=get_settings())