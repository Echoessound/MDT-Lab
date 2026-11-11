"""Bounded downloads from the built-in public dataset catalog only."""
import time
from urllib.parse import urljoin, urlsplit

import httpx

from ..api_schemas import APIError
from .datasets import CATALOG, MAX_UPLOAD_BYTES

ALLOWED_HOSTS = {
    "synthetichealth.github.io", "wiki.cancerimagingarchive.net",
    "www.cancerimagingarchive.net", "cancerimagingarchive.net",
}


def download_dataset(source: str, *, transport=None) -> bytes:
    url = CATALOG.get(source, {}).get("download_url")
    if not url:
        raise APIError(422, "DATASET_DOWNLOAD_UNAVAILABLE", "此格式请通过本地文件导入。")
    started = time.monotonic()
    try:
        with httpx.Client(timeout=30, follow_redirects=False, trust_env=True, transport=transport) as client:
            for _ in range(4):
                parsed = urlsplit(url)
                if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
                        or parsed.username or parsed.password or parsed.port not in (None, 443)):
                    raise APIError(502, "DATASET_REDIRECT_BLOCKED", "数据源跳转到未支持的地址；请从官方页面下载后上传。")
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    raw = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        raw.extend(chunk)
                        if len(raw) > MAX_UPLOAD_BYTES:
                            raise APIError(413, "DATASET_SIZE_LIMIT", "数据源超过20MB限制，请上传筛选后的文件。")
                        if time.monotonic() - started > 60:
                            raise httpx.TimeoutException("download deadline")
                    if not raw:
                        raise APIError(502, "DATASET_DOWNLOAD_EMPTY", "数据源返回空文件。")
                    return bytes(raw)
            raise APIError(502, "DATASET_REDIRECT_LIMIT", "数据源跳转次数超限，请使用文件上传。")
    except httpx.HTTPError:
        raise APIError(502, "DATASET_DOWNLOAD_FAILED", "无法获取官方数据源；请稍后重试或从官方页面下载后上传。") from None
