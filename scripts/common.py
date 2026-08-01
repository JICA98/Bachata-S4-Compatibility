from __future__ import annotations

import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CUSA_RE = re.compile(r"^CUSA[0-9]{5}$")
STATUS_ORDER = {"playable": 0, "ingame": 1, "menus": 2, "boots": 3, "nothing": 4}
STATUS_LABELS = tuple(STATUS_ORDER)
DATA_REPOSITORY = "JICA98/Bachata-S4-Compatibility"
RAW_BASE = f"https://raw.githubusercontent.com/{DATA_REPOSITORY}/main/"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return parsed.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "unknown"


def display_driver(driver: dict[str, Any]) -> str:
    name = str(driver.get("name") or driver.get("type") or "Unknown")
    version = str(driver.get("version") or "").strip()
    build = str(driver.get("build") or "").strip()
    details = " ".join(part for part in (version, build) if part)
    return f"{name} {details}".strip()


def gzip_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, destination.open("wb") as raw_dst:
        with gzip.GzipFile(fileobj=raw_dst, mode="wb", compresslevel=9, mtime=0) as dst:
            while True:
                block = src.read(1024 * 1024)
                if not block:
                    break
                dst.write(block)
