"""Куда бот пишет базу и таблицу. На сервере это постоянный диск /data."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    custom = os.environ.get("DATA_DIR", "").strip()
    if custom:
        path = Path(custom)
        path.mkdir(parents=True, exist_ok=True)
        return path
    mounted = Path("/data")
    local = ROOT / "data"
    if mounted.is_dir() and os.access(mounted, os.W_OK):
        mounted.mkdir(parents=True, exist_ok=True)
        target = mounted / "zhar.sqlite"
        source = local / "zhar.sqlite"
        if source.exists() and not target.exists():
            shutil.copy(source, target)
        return mounted
    local.mkdir(parents=True, exist_ok=True)
    return local
