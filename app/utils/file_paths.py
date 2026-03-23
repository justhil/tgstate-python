from urllib.parse import quote, unquote, urlparse

DEFAULT_FILE_ROUTE = "/d"


def normalize_file_route(file_route: str | None = None) -> str:
    """标准化文件访问路由，统一成 `/path` 形式。"""
    route = (file_route or DEFAULT_FILE_ROUTE).strip()
    if not route:
        return DEFAULT_FILE_ROUTE
    return "/" + route.strip("/")


def build_file_path(file_id: str, filename: str, file_route: str | None = None) -> str:
    """构建带文件名的下载路径。"""
    route = normalize_file_route(file_route)
    encoded_file_id = quote(str(file_id), safe="")
    encoded_filename = quote(str(filename), safe="")
    return f"{route}/{encoded_file_id}/{encoded_filename}"


def extract_file_id_from_value(value: str | None, file_route: str | None = None) -> str | None:
    """从文件 URL、相对路径或复合 file_id 中解析 file_id。"""
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if "://" in text:
        text = urlparse(text).path or ""

    route = normalize_file_route(file_route)
    prefix = f"{route}/"
    if text.startswith(prefix):
        remainder = text[len(prefix):]
        file_id = remainder.split("/", 1)[0]
        return unquote(file_id) or None

    if text.startswith("/"):
        return None

    # 兜底兼容直接传入复合 ID 的情况。
    return text if ":" in text else None
