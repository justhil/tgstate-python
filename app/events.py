import asyncio

# 创建一个全局的、线程安全的异步队列作为事件总线
# Bot handler 将向此队列中放入新文件通知
# SSE 端点将从此队列中读取通知并发送给前端
file_update_queue = asyncio.Queue()