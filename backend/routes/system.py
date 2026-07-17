import os
import tempfile
import threading

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.maintenance import (
    backup_path,
    create_backup,
    list_backups,
    pending_restore,
    queue_restore,
    run_data_check,
    validate_and_store_backup,
)
from core.tasks import create_task, register_retry_handler, update_task


router = APIRouter()


def _start_backup(label: str = "manual") -> str:
    task_id = create_task("data_backup", "备份 JiaYuan 数据", payload={"label": label}, retryable=True)

    def run():
        update_task(task_id, status="running", progress=10, message="正在创建一致性数据库快照")
        try:
            result = create_backup(label)
            update_task(task_id, status="completed", progress=100, message=f"备份完成：{result['name']}")
        except Exception as exc:
            update_task(task_id, status="failed", message=str(exc))

    threading.Thread(target=run, name=f"backup-task-{task_id[:8]}", daemon=True).start()
    return task_id


register_retry_handler("data_backup", lambda payload: _start_backup(str(payload.get("label") or "retry")))


@router.get("/diagnostics")
def diagnostics(deep: bool = False):
    return run_data_check(deep)


@router.get("/backups")
def backups():
    return {"backups": list_backups(), "pending_restore": pending_restore()}


@router.post("/backups", status_code=202)
def start_backup():
    return {"task_id": _start_backup()}


@router.get("/backups/{filename}")
def download_backup(filename: str):
    try:
        path = backup_path(filename)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="备份不存在") from exc
    return FileResponse(path, media_type="application/zip", filename=os.path.basename(path))


@router.post("/backups/import")
def import_backup(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="只能导入 JiaYuan ZIP 备份")
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="jiayuan-upload-", suffix=".zip", delete=False) as target:
            temp_path = target.name
            while chunk := file.file.read(1024 * 1024):
                target.write(chunk)
        return validate_and_store_backup(temp_path, os.path.basename(file.filename))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if temp_path and os.path.isfile(temp_path):
            os.remove(temp_path)


@router.post("/backups/{filename}/restore", status_code=202)
def restore_backup(filename: str):
    try:
        queued = queue_restore(filename)
    except (ValueError, FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "恢复已排队，完全退出并重新打开 App 后生效", "restore": queued}
