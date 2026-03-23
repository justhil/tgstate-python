import asyncio
import json
from typing import Any

# 为每个 SSE 客户端维护独立队列，避免单消费者队列导致事件丢失。
_subscribers: set[asyncio.Queue[str]] = set()
_subscribers_lock = asyncio.Lock()


async def subscribe_file_updates() -> asyncio.Queue[str]:
    """注册一个文件更新订阅者，并返回其专属事件队列。"""
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
    async with _subscribers_lock:
        _subscribers.add(queue)
    return queue


async def unsubscribe_file_updates(queue: asyncio.Queue[str]) -> None:
    """取消文件更新订阅。"""
    async with _subscribers_lock:
        _subscribers.discard(queue)


async def publish_file_update(payload: dict[str, Any] | str) -> None:
    """向所有已连接客户端广播文件更新事件。"""
    message = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)

    async with _subscribers_lock:
        subscribers = tuple(_subscribers)

    for queue in subscribers:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # 队列仍然满时直接丢弃最新事件，避免广播被单个慢连接阻塞。
            print("警告: 文件更新事件队列已满，已跳过一个客户端事件。")
