"""Content-addressed storage and honest binary metadata extraction for real medical attachments.

Supports raster medical slices (PNG/JPEG/WebP), DICOM Part 10 (.dcm) with PII group 0x0010
stripping, and clinical PDF reports. Never fabricates measurements or synthetic pixels.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
from tempfile import NamedTemporaryFile
from threading import RLock
from uuid import uuid4

from ..api_schemas import APIError

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MiB per attachment

ALLOWED_FORMATS: dict[str, tuple[str, str]] = {
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".webp": ("image/webp", "image"),
    ".dcm": ("application/dicom", "dicom"),
    ".pdf": ("application/pdf", "pdf"),
}

# Explicit-VR long-length value representations in DICOM Part 10
_DICOM_LONG_VRS = {b"OB", b"OD", b"OF", b"OL", b"OW", b"SQ", b"UC", b"UN", b"UR", b"UT"}
_DICOM_TEXT_VRS = {b"AE", b"AS", b"CS", b"DA", b"DS", b"DT", b"IS", b"LO", b"LT", b"PN", b"SH", b"ST", b"TM", b"UI"}

# Technical non-PII DICOM tags safe to expose in the research workbench
_DICOM_SAFE_TAGS: dict[tuple[int, int], str] = {
    (0x0008, 0x0020): "study_date",
    (0x0008, 0x0060): "modality",
    (0x0008, 0x103E): "series_description",
    (0x0018, 0x0015): "body_part_examined",
    (0x0018, 0x0050): "slice_thickness_mm",
    (0x0028, 0x0004): "photometric_interpretation",
    (0x0028, 0x0010): "rows",
    (0x0028, 0x0011): "columns",
    (0x0028, 0x0030): "pixel_spacing",
    (0x0028, 0x1050): "window_center",
    (0x0028, 0x1051): "window_width",
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_filename(name: str) -> tuple[str, str]:
    clean = Path(name.strip().replace("\\", "/")).name
    if not clean or len(clean) > 160:
        raise APIError(422, "INVALID_ATTACHMENT_NAME", "附件文件名无效或超出长度限制。")
    ext = Path(clean).suffix.lower()
    if ext not in ALLOWED_FORMATS:
        supported = "、".join(sorted(ALLOWED_FORMATS))
        raise APIError(422, "UNSUPPORTED_ATTACHMENT_TYPE", f"仅支持以下真实附件格式：{supported}。")
    safe_base = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", Path(clean).stem).strip("._") or "attachment"
    return f"{safe_base[:100]}{ext}", ext


def _parse_png(raw: bytes) -> dict:
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise APIError(422, "INVALID_IMAGE_HEADER", "文件不是合法的 PNG 图像。")
    width, height, bit_depth, color_type = struct.unpack(">IIBB", raw[16:26])
    color_names = {0: "灰度", 2: "RGB 真彩", 3: "索引色", 4: "灰度+透明", 6: "RGBA 真彩"}
    return {
        "format": "PNG",
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_mode": color_names.get(color_type, f"类型 {color_type}"),
        "previewable": True,
    }


def _parse_jpeg(raw: bytes) -> dict:
    if len(raw) < 4 or raw[:2] != b"\xff\xd8":
        raise APIError(422, "INVALID_IMAGE_HEADER", "文件不是合法的 JPEG 图像。")
    pos = 2
    width = height = components = None
    while pos + 4 <= len(raw):
        if raw[pos] != 0xFF:
            break
        while pos < len(raw) and raw[pos] == 0xFF:
            pos += 1
        if pos >= len(raw):
            break
        marker = raw[pos]
        pos += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(raw):
            break
        seg_len = struct.unpack(">H", raw[pos:pos + 2])[0]
        if seg_len < 2 or pos + seg_len > len(raw):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3} and seg_len >= 8:
            height, width, components = struct.unpack(">HHB", raw[pos + 3:pos + 8])
            break
        pos += seg_len
    return {
        "format": "JPEG",
        "width": width,
        "height": height,
        "channels": components,
        "previewable": True,
    }


def _parse_webp(raw: bytes) -> dict:
    if len(raw) < 30 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise APIError(422, "INVALID_IMAGE_HEADER", "文件不是合法的 WebP 图像。")
    chunk = raw[12:16]
    width = height = None
    if chunk == b"VP8X" and len(raw) >= 30:
        width = 1 + int.from_bytes(raw[24:27], "little")
        height = 1 + int.from_bytes(raw[27:30], "little")
    elif chunk == b"VP8 " and len(raw) >= 30:
        w, h = struct.unpack("<HH", raw[26:30])
        width, height = w & 0x3FFF, h & 0x3FFF
    elif chunk == b"VP8L" and len(raw) >= 25:
        bits = struct.unpack("<I", raw[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
    return {"format": "WebP", "width": width, "height": height, "previewable": True}


def _parse_pdf(raw: bytes) -> dict:
    if not raw.startswith(b"%PDF-"):
        raise APIError(422, "INVALID_PDF_HEADER", "文件不是合法的 PDF 文档。")
    version_match = re.match(rb"%PDF-(\d+\.\d+)", raw[:16])
    version = version_match.group(1).decode("ascii") if version_match else "unknown"
    pages = len(re.findall(rb"/Type\s*/Page\b", raw))
    return {
        "format": "PDF",
        "pdf_version": version,
        "estimated_pages": pages if pages > 0 else None,
        "previewable": False,
    }


def _parse_dicom(raw: bytes) -> dict:
    """Parse non-PII technical tags from a DICOM Part 10 binary without third-party dependencies."""
    if len(raw) < 132 or raw[128:132] != b"DICM":
        raise APIError(422, "INVALID_DICOM_HEADER", "文件缺少 DICOM Part 10 魔数标识（偏移 128 处应为 DICM）。")

    pos = 132
    extracted: dict[str, str | int | float] = {}
    pii_tags_skipped = 0
    total_tags_scanned = 0
    max_scan = min(len(raw), 256 * 1024)

    while pos + 8 <= max_scan and total_tags_scanned < 400:
        group, element = struct.unpack("<HH", raw[pos:pos + 4])
        pos += 4
        # Stop at PixelData (7FE0,0010)
        if (group, element) == (0x7FE0, 0x0010):
            break
        vr = raw[pos:pos + 2]
        explicit = len(vr) == 2 and all(65 <= b <= 90 for b in vr)
        if explicit:
            pos += 2
            if vr in _DICOM_LONG_VRS:
                if pos + 6 > len(raw):
                    break
                length = struct.unpack("<I", raw[pos + 2:pos + 6])[0]
                pos += 6
            else:
                if pos + 2 > len(raw):
                    break
                length = struct.unpack("<H", raw[pos:pos + 2])[0]
                pos += 2
        else:
            length = struct.unpack("<I", raw[pos:pos + 4])[0]
            pos += 4
            vr = b""

        if length == 0xFFFFFFFF or pos + length > len(raw):
            break
        value_bytes = raw[pos:pos + length]
        pos += length
        total_tags_scanned += 1

        # Strictly strip / never record patient identity tags in group 0x0010
        if group == 0x0010:
            pii_tags_skipped += 1
            continue

        field_name = _DICOM_SAFE_TAGS.get((group, element))
        if not field_name:
            continue

        if (group, element) in {(0x0028, 0x0010), (0x0028, 0x0011)} and len(value_bytes) >= 2:
            extracted[field_name] = struct.unpack("<H", value_bytes[:2])[0]
        elif not explicit or vr in _DICOM_TEXT_VRS:
            decoded = value_bytes.decode("utf-8", errors="ignore").strip("\x00 ").strip()
            if decoded:
                if field_name in {"slice_thickness_mm", "window_center", "window_width"}:
                    first = decoded.split("\\")[0]
                    try:
                        extracted[field_name] = round(float(first), 3)
                    except ValueError:
                        extracted[field_name] = decoded
                else:
                    extracted[field_name] = decoded

    return {
        "format": "DICOM Part 10",
        "previewable": False,
        "pii_group_0010_skipped": pii_tags_skipped,
        "tags_scanned": total_tags_scanned,
        "dicom_tags": extracted,
        "width": extracted.get("columns"),
        "height": extracted.get("rows"),
    }


def inspect_attachment_bytes(raw: bytes, ext: str) -> dict:
    if ext == ".png":
        return _parse_png(raw)
    if ext in {".jpg", ".jpeg"}:
        return _parse_jpeg(raw)
    if ext == ".webp":
        return _parse_webp(raw)
    if ext == ".dcm":
        return _parse_dicom(raw)
    if ext == ".pdf":
        return _parse_pdf(raw)
    raise APIError(422, "UNSUPPORTED_ATTACHMENT_TYPE", "不支持的附件格式。")


class MediaAttachmentStore:
    """Thread-safe content-addressed local store for real case/event attachments."""

    def __init__(self, media_dir: Path) -> None:
        self.media_dir = media_dir
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.media_dir / "index.json"
        self._lock = RLock()
        self._records: list[dict] = self._load_index()

    def _load_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_index(self) -> None:
        tmp = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.media_dir, delete=False) as fp:
                tmp = Path(fp.name)
                json.dump(self._records, fp, ensure_ascii=False, indent=2)
            os.replace(tmp, self.index_path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def add(self, case_id: str, event_id: str, filename: str, raw: bytes) -> dict:
        if not raw or len(raw) > MAX_ATTACHMENT_BYTES:
            raise APIError(413, "ATTACHMENT_SIZE_LIMIT", "附件为空或超过 10MB 大小限制。")
        safe_name, ext = _sanitize_filename(filename)
        mime_type, kind = ALLOWED_FORMATS[ext]
        metadata = inspect_attachment_bytes(raw, ext)
        sha256 = hashlib.sha256(raw).hexdigest()
        blob_name = f"{sha256}{ext}"
        blob_path = self.media_dir / blob_name

        with self._lock:
            if not blob_path.exists():
                blob_path.write_bytes(raw)
            record = {
                "attachment_id": f"att_{uuid4().hex[:16]}",
                "case_id": case_id,
                "event_id": event_id,
                "filename": safe_name,
                "mime_type": mime_type,
                "kind": kind,
                "byte_count": len(raw),
                "sha256": sha256,
                "blob_name": blob_name,
                "uploaded_at": _utcnow(),
                "metadata": metadata,
            }
            self._records.append(record)
            self._save_index()
            return self._public(record)

    @staticmethod
    def _public(record: dict) -> dict:
        return {k: v for k, v in record.items() if k != "blob_name"}

    def list_for_case(self, case_id: str, event_id: str | None = None) -> list[dict]:
        with self._lock:
            return [
                self._public(item)
                for item in self._records
                if item["case_id"] == case_id and (event_id is None or item["event_id"] == event_id)
            ]

    def get_content(self, case_id: str, attachment_id: str) -> tuple[bytes, str, str]:
        with self._lock:
            record = next(
                (item for item in self._records if item["case_id"] == case_id and item["attachment_id"] == attachment_id),
                None,
            )
            if record is None:
                raise APIError(404, "ATTACHMENT_NOT_FOUND", "未找到该病例附件。")
            blob_path = self.media_dir / record["blob_name"]
            if not blob_path.exists():
                raise APIError(404, "ATTACHMENT_BLOB_MISSING", "附件存储文件已缺失。")
            return blob_path.read_bytes(), record["mime_type"], record["filename"]

    def delete(self, case_id: str, attachment_id: str) -> dict:
        with self._lock:
            idx = next(
                (i for i, item in enumerate(self._records) if item["case_id"] == case_id and item["attachment_id"] == attachment_id),
                None,
            )
            if idx is None:
                raise APIError(404, "ATTACHMENT_NOT_FOUND", "未找到该病例附件。")
            removed = self._records.pop(idx)
            self._save_index()
            return {"deleted": True, "attachment_id": removed["attachment_id"]}
