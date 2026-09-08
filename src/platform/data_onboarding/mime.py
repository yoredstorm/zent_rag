# =============================================================================
# Data Onboarding — detección MIME por magic bytes
# =============================================================================
from __future__ import annotations

_ALLOWED_EXT = {
    "pdf": "file",
    "csv": "csv",
    "xlsx": "excel",
    "xls": "excel",
    "txt": "file",
    "md": "file",
    "markdown": "file",
    "docx": "file",
}


class MimeRejected(ValueError):
    """Archivo no permitido para onboarding."""


def detect_source_type(filename: str, data: bytes) -> str:
    """Devuelve file|csv|excel o lanza MimeRejected."""
    if not data:
        raise MimeRejected("Empty file")
    if data[:2] == b"MZ":
        raise MimeRejected("Executable files are not allowed")
    name = (filename or "upload.bin").rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if data.startswith(b"%PDF-"):
        return "file"
    if data[:4] == b"PK\x03\x04":
        if ext == "xlsx":
            return "excel"
        if ext == "docx":
            return "file"
        raise MimeRejected("ZIP archives are not allowed unless xlsx/docx")
    if ext == "csv" or (ext in ("", "txt") and _looks_csv(data) and ext != "txt"):
        return "csv"
    if ext == "csv":
        return "csv"
    if ext in _ALLOWED_EXT:
        return _ALLOWED_EXT[ext]
    if _looks_csv(data) and ext in ("", "txt", "csv"):
        return "csv"
    raise MimeRejected(f"Unsupported file type: .{ext or 'unknown'}")


def _looks_csv(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = sample.decode("latin-1")
        except UnicodeDecodeError:
            return False
    first = text.splitlines()[0] if text.splitlines() else ""
    return "," in first or ";" in first
