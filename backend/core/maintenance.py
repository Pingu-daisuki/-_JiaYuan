"""运行时数据自检、备份及下次启动恢复。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime

from core.paths import (
    BACKUP_DIR,
    DATA_DIR,
    DATABASE_PATH,
    ENGINE_CONFIG_DIR,
    ENGINE_FLAG_DIR,
    UPLOAD_DIR,
    VECTOR_DB_DIR,
    ensure_runtime_dirs,
    resolve_data_path,
)


BACKUP_FORMAT = 1
MAX_BACKUP_ENTRIES = 100_000
MAX_BACKUP_UNPACKED_BYTES = 100 * 1024 * 1024 * 1024
PENDING_RESTORE_PATH = os.path.join(BACKUP_DIR, "pending-restore.json")
RESTORE_RESULT_PATH = os.path.join(BACKUP_DIR, "restore-result.json")
BACKUP_PARTS = {
    "uploads": UPLOAD_DIR,
    "vector_db": VECTOR_DB_DIR,
    "engine_config": ENGINE_CONFIG_DIR,
    "engine_flags": ENGINE_FLAG_DIR,
}


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")[:19]


def _safe_backup_name(name: str) -> str:
    basename = os.path.basename(name or "")
    if basename != name or not basename.lower().endswith(".zip"):
        raise ValueError("备份文件名无效")
    return basename


def _validate_zip_members(archive: zipfile.ZipFile) -> None:
    allowed_roots = {"manifest.json", "campus_assistant.db", *BACKUP_PARTS.keys()}
    if len(archive.infolist()) > MAX_BACKUP_ENTRIES:
        raise ValueError("备份包文件数量过多")
    unpacked_size = 0
    for info in archive.infolist():
        unpacked_size += max(0, info.file_size)
        if unpacked_size > MAX_BACKUP_UNPACKED_BYTES:
            raise ValueError("备份包展开后超过 100 GB 限制")
        normalized = info.filename.replace("\\", "/").lstrip("/")
        parts = [part for part in normalized.split("/") if part]
        if not parts or parts[0] not in allowed_roots or ".." in parts:
            raise ValueError(f"备份包包含非法路径: {info.filename}")
        if info.is_dir():
            continue
        mode = info.external_attr >> 16
        if mode and (mode & 0o170000) == 0o120000:
            raise ValueError("备份包不能包含符号链接")


def _validate_extracted_backup(root: str) -> dict:
    manifest_path = os.path.join(root, "manifest.json")
    database_path = os.path.join(root, "campus_assistant.db")
    if not os.path.isfile(manifest_path) or not os.path.isfile(database_path):
        raise ValueError("备份包缺少清单或数据库")
    with open(manifest_path, "r", encoding="utf-8") as file:
        manifest = json.load(file)
    if manifest.get("format") != BACKUP_FORMAT or manifest.get("app") != "jiayuan":
        raise ValueError("备份格式或应用标识不兼容")
    with closing(sqlite3.connect(database_path)) as conn:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise ValueError(f"备份数据库完整性校验失败: {integrity}")
    return manifest


def create_backup(label: str = "manual") -> dict:
    ensure_runtime_dirs()
    filename = f"JiaYuan-{_timestamp()}-{label}.zip"
    destination = os.path.join(BACKUP_DIR, filename)
    from core.processor import VECTOR_WRITE_LOCK

    with VECTOR_WRITE_LOCK:
        with tempfile.TemporaryDirectory(prefix="jiayuan-backup-", dir=BACKUP_DIR) as staging:
            database_copy = os.path.join(staging, "campus_assistant.db")
            with closing(sqlite3.connect(DATABASE_PATH, timeout=30)) as source:
                with closing(sqlite3.connect(database_copy)) as target:
                    source.backup(target)
            included = ["campus_assistant.db"]
            for archive_name, source_path in BACKUP_PARTS.items():
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, os.path.join(staging, archive_name))
                    included.append(archive_name)
            manifest = {
                "app": "jiayuan",
                "format": BACKUP_FORMAT,
                "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "label": label,
                "included": included,
            }
            with open(os.path.join(staging, "manifest.json"), "w", encoding="utf-8") as file:
                json.dump(manifest, file, ensure_ascii=False, indent=2)
            with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for root, _, files in os.walk(staging):
                    for item in files:
                        source_path = os.path.join(root, item)
                        archive.write(source_path, os.path.relpath(source_path, staging))
    return backup_info(filename)


def backup_info(filename: str) -> dict:
    safe_name = _safe_backup_name(filename)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(path):
        raise FileNotFoundError(safe_name)
    stat = os.stat(path)
    return {
        "name": safe_name,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    }


def list_backups() -> list[dict]:
    ensure_runtime_dirs()
    items = []
    for name in os.listdir(BACKUP_DIR):
        if name.lower().endswith(".zip"):
            try:
                items.append(backup_info(name))
            except OSError:
                pass
    return sorted(items, key=lambda item: item["modified_at"], reverse=True)


def backup_path(filename: str) -> str:
    safe_name = _safe_backup_name(filename)
    path = os.path.realpath(os.path.join(BACKUP_DIR, safe_name))
    if os.path.dirname(path) != os.path.realpath(BACKUP_DIR) or not os.path.isfile(path):
        raise FileNotFoundError(safe_name)
    return path


def validate_and_store_backup(source_path: str, original_name: str) -> dict:
    safe_name = _safe_backup_name(original_name)
    with zipfile.ZipFile(source_path) as archive:
        _validate_zip_members(archive)
        with tempfile.TemporaryDirectory(prefix="jiayuan-validate-") as extracted:
            archive.extractall(extracted)
            manifest = _validate_extracted_backup(extracted)
    destination = os.path.join(BACKUP_DIR, safe_name)
    if os.path.realpath(source_path) != os.path.realpath(destination):
        shutil.copy2(source_path, destination)
    return {**backup_info(safe_name), "manifest": manifest}


def queue_restore(filename: str) -> dict:
    path = backup_path(filename)
    with zipfile.ZipFile(path) as archive:
        _validate_zip_members(archive)
        with tempfile.TemporaryDirectory(prefix="jiayuan-validate-") as extracted:
            archive.extractall(extracted)
            manifest = _validate_extracted_backup(extracted)
    payload = {
        "filename": os.path.basename(path),
        "queued_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "manifest": manifest,
    }
    with open(PENDING_RESTORE_PATH, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
    return payload


def pending_restore() -> dict | None:
    try:
        with open(PENDING_RESTORE_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def apply_pending_restore() -> dict | None:
    pending = pending_restore()
    if not pending:
        return None
    ensure_runtime_dirs()
    archive_path = backup_path(pending["filename"])
    result = {"filename": pending["filename"], "applied_at": None, "error": None}
    try:
        with tempfile.TemporaryDirectory(prefix="jiayuan-restore-", dir=BACKUP_DIR) as extracted:
            with zipfile.ZipFile(archive_path) as archive:
                _validate_zip_members(archive)
                archive.extractall(extracted)
            manifest = _validate_extracted_backup(extracted)
            database_source = os.path.join(extracted, "campus_assistant.db")
            os.replace(database_source, DATABASE_PATH)
            for archive_name, destination in BACKUP_PARTS.items():
                source = os.path.join(extracted, archive_name)
                if archive_name not in manifest.get("included", []):
                    continue
                if os.path.isdir(destination):
                    shutil.rmtree(destination)
                if os.path.exists(source):
                    shutil.move(source, destination)
                else:
                    os.makedirs(destination, exist_ok=True)
        result["applied_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        os.remove(PENDING_RESTORE_PATH)
    except Exception as exc:
        result["error"] = str(exc)
    with open(RESTORE_RESULT_PATH, "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)
    return result


def run_data_check(deep: bool = False) -> dict:
    ensure_runtime_dirs()
    issues: list[dict] = []
    stats: dict[str, object] = {}
    with closing(sqlite3.connect(DATABASE_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        stats["database_integrity"] = integrity
        if integrity != "ok":
            issues.append({"level": "error", "code": "database_integrity", "message": integrity})
        files = conn.execute(
            "SELECT id, file_name, file_path, status, chunk_count FROM knowledge_files"
        ).fetchall()
        stats["file_records"] = len(files)
        missing = [
            {"id": row["id"], "name": row["file_name"]}
            for row in files
            if not os.path.isfile(resolve_data_path(row["file_path"]) or "")
        ]
        if missing:
            issues.append({"level": "error", "code": "missing_files", "message": f"{len(missing)} 个源文件缺失", "items": missing[:50]})
        orphan_folders = conn.execute(
            "SELECT id, course_name FROM courses WHERE parent_id IS NOT NULL "
            "AND parent_id NOT IN (SELECT id FROM courses)"
        ).fetchall()
        if orphan_folders:
            issues.append({"level": "warning", "code": "orphan_folders", "message": f"{len(orphan_folders)} 个目录失去父目录"})
        ready = [row for row in files if row["status"] == "ready"]
        stats["ready_files"] = len(ready)

    usage = shutil.disk_usage(DATA_DIR)
    stats["disk_free_bytes"] = usage.free
    stats["data_size_bytes"] = sum(
        os.path.getsize(os.path.join(root, name))
        for root, _, names in os.walk(DATA_DIR)
        if os.path.realpath(root).startswith(os.path.realpath(DATA_DIR))
        for name in names
        if os.path.isfile(os.path.join(root, name))
    )

    if deep:
        try:
            from core.processor import VECTOR_WRITE_LOCK, get_vector_collection

            with VECTOR_WRITE_LOCK:
                stored = get_vector_collection().get(include=["metadatas"])
            vector_counts: dict[int, int] = {}
            for metadata in stored.get("metadatas") or []:
                file_id = int(metadata.get("file_id", 0))
                vector_counts[file_id] = vector_counts.get(file_id, 0) + 1
            stats["vector_chunks"] = sum(vector_counts.values())
            ready_ids = {int(row["id"]) for row in ready}
            missing_vectors = [row["file_name"] for row in ready if vector_counts.get(int(row["id"]), 0) == 0]
            orphan_vector_ids = sorted(set(vector_counts) - ready_ids)
            if missing_vectors:
                issues.append({"level": "error", "code": "missing_vectors", "message": f"{len(missing_vectors)} 个就绪文件没有向量", "items": missing_vectors[:50]})
            if orphan_vector_ids:
                issues.append({"level": "warning", "code": "orphan_vectors", "message": f"发现 {len(orphan_vector_ids)} 组孤立向量", "items": orphan_vector_ids[:50]})
        except Exception as exc:
            issues.append({"level": "warning", "code": "vector_check_failed", "message": f"向量自检失败: {exc}"})

    return {
        "healthy": not any(issue["level"] == "error" for issue in issues),
        "deep": deep,
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "stats": stats,
        "issues": issues,
        "pending_restore": pending_restore(),
    }
