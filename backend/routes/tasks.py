from fastapi import APIRouter, HTTPException, Query

from core.tasks import get_task, list_tasks, request_cancel, retry_task


router = APIRouter()


@router.get("")
def get_tasks(limit: int = Query(default=100, ge=1, le=500)):
    return {"tasks": list_tasks(limit)}


@router.get("/{task_id}")
def get_task_detail(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/{task_id}/cancel")
def cancel_task(task_id: str):
    task = request_cancel(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.post("/{task_id}/retry", status_code=202)
def retry_background_task(task_id: str):
    try:
        new_task_id = retry_task(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"task_id": new_task_id}
