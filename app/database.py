import sqlite3
import threading
from typing import Any

DATABASE_URL = "file_metadata.db"

# 使用线程锁来确保多线程环境下的数据库访问安全
_db_lock = threading.Lock()


def get_db_connection():
    """获取数据库连接。"""
    conn = sqlite3.connect(DATABASE_URL, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库，创建表。"""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_id TEXT NOT NULL UNIQUE,
                    filesize INTEGER NOT NULL,
                    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()
            print("数据库已成功初始化。")
        finally:
            conn.close()


def add_file_metadata(filename: str, file_id: str, filesize: int) -> bool:
    """
    向数据库中添加一个新的文件元数据记录。
    返回值表示本次调用是否真正插入了新记录。
    """
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO files (filename, file_id, filesize) VALUES (?, ?, ?)",
                (filename, file_id, filesize)
            )
            conn.commit()
            inserted = cursor.rowcount > 0
            print(f"已添加或忽略文件元数据: {filename}")
            return inserted
        finally:
            conn.close()


def get_all_files() -> list[dict[str, Any]]:
    """从数据库中获取所有文件的元数据。"""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT filename, file_id, filesize, upload_date FROM files ORDER BY upload_date DESC"
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


def get_file_info(file_id: str) -> dict[str, Any] | None:
    """通过 file_id 获取单个文件的完整元数据。"""
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT filename, file_id, filesize, upload_date FROM files WHERE file_id = ?",
                (file_id,)
            )
            result = cursor.fetchone()
            return dict(result) if result else None
        finally:
            conn.close()


def get_file_by_id(file_id: str) -> dict[str, Any] | None:
    """兼容旧调用，返回文件名和大小。"""
    result = get_file_info(file_id)
    if not result:
        return None
    return {
        "filename": result["filename"],
        "filesize": result["filesize"]
    }


def delete_file_metadata(file_id: str) -> bool:
    """
    根据 file_id 从数据库中删除文件元数据。
    返回: 如果成功删除了一行，则为 True，否则为 False。
    """
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def delete_file_by_message_id(message_id: int) -> str | None:
    """
    根据 message_id 从数据库中删除文件元数据，并返回其 file_id。
    因为一个主消息 ID 只对应一个文件，所以可以直接删除。
    """
    file_id_to_delete = None
    with _db_lock:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT file_id FROM files WHERE file_id LIKE ?",
                (f"{message_id}:%",)
            )
            result = cursor.fetchone()
            if result:
                file_id_to_delete = result[0]
                cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id_to_delete,))
                conn.commit()
                print(
                    f"已从数据库中删除与消息 ID {message_id} 关联的文件: {file_id_to_delete}"
                )
            return file_id_to_delete
        finally:
            conn.close()
