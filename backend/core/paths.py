"""项目资源目录与可写运行数据目录。

开发模式默认把数据放在 backend 目录，保持现有启动方式兼容；桌面版通过
JIAYUAN_DATA_DIR / JIAYUAN_MODEL_DIR 把可变数据放到用户 LocalAppData，避免
向只读的安装目录写数据库、上传文件或模型。
"""

from __future__ import annotations

import os
import sys


SOURCE_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCE_BACKEND_DIR = os.path.abspath(getattr(sys, "_MEIPASS", SOURCE_BACKEND_DIR))


def _default_data_dir() -> str:
    configured = os.getenv("JIAYUAN_DATA_DIR", "").strip()
    if configured:
        return os.path.abspath(os.path.expanduser(configured))

    if getattr(sys, "frozen", False):
        local_app_data = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
        if local_app_data:
            return os.path.join(local_app_data, "JiaYuan")
        return os.path.join(os.path.expanduser("~"), ".jiayuan")

    return SOURCE_BACKEND_DIR


DATA_DIR = _default_data_dir()
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
VECTOR_DB_DIR = os.path.join(DATA_DIR, "vector_db")
ENGINE_FLAG_DIR = os.path.join(DATA_DIR, "engine_flags")
ENGINE_CONFIG_DIR = os.path.join(DATA_DIR, "engine_config")
DATABASE_PATH = os.path.join(DATA_DIR, "campus_assistant.db")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
MODEL_DIR = os.path.abspath(
    os.path.expanduser(os.getenv("JIAYUAN_MODEL_DIR", os.path.join(DATA_DIR, "models")))
)
MINERU_CONFIG_PATH = os.path.join(ENGINE_CONFIG_DIR, "mineru.json")


def ensure_runtime_dirs() -> None:
    for directory in (
        DATA_DIR,
        UPLOAD_DIR,
        VECTOR_DB_DIR,
        ENGINE_FLAG_DIR,
        ENGINE_CONFIG_DIR,
        MODEL_DIR,
        BACKUP_DIR,
    ):
        os.makedirs(directory, exist_ok=True)


def resolve_data_path(path: str | None) -> str | None:
    """解析数据库中的相对路径；绝对路径原样返回。"""
    if not path or os.path.isabs(path):
        return path
    return os.path.join(DATA_DIR, path)


def resource_path(*parts: str) -> str:
    return os.path.join(RESOURCE_BACKEND_DIR, *parts)


ensure_runtime_dirs()
