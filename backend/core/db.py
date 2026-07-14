# backend/core/db.py
import sqlite3
import os
import hashlib

from core.paths import DATABASE_PATH, DATA_DIR, resolve_data_path

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = DATA_DIR
DB_PATH = DATABASE_PATH

INGESTION_STATUSES = {"uploaded", "parsing", "indexing", "ready", "failed"}
INGESTION_TRANSITIONS = {
    "uploaded": {"parsing", "failed"},
    "parsing": {"indexing", "failed"},
    "indexing": {"ready", "failed"},
    "ready": {"uploaded", "failed"},
    "failed": {"uploaded"},
}

KNOWLEDGE_FILE_COLUMNS = {
    "status": "TEXT NOT NULL DEFAULT 'uploaded'",
    "page_count": "INTEGER NOT NULL DEFAULT 0",
    "engine": "TEXT DEFAULT NULL",
    "elapsed_ms": "INTEGER NOT NULL DEFAULT 0",
    "chunk_count": "INTEGER NOT NULL DEFAULT 0",
    "error_message": "TEXT DEFAULT NULL",
    "file_sha256": "TEXT DEFAULT NULL",
    "started_at": "TEXT DEFAULT NULL",
    "completed_at": "TEXT DEFAULT NULL",
    "updated_at": "TEXT DEFAULT NULL",
    "document_type": "TEXT NOT NULL DEFAULT 'pdf'",
    "mime_type": "TEXT DEFAULT 'application/pdf'",
    "source_kind": "TEXT NOT NULL DEFAULT 'upload'",
    "source_url": "TEXT DEFAULT NULL",
    "unit_type": "TEXT NOT NULL DEFAULT 'page'",
    "unit_count": "INTEGER NOT NULL DEFAULT 0",
}


def _table_columns(conn, table_name):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _ensure_column(conn, table_name, column_name, definition):
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _resolve_stored_path(file_path):
    return resolve_data_path(file_path)


def calculate_file_sha256(file_path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with open(file_path, "rb") as file:
        while chunk := file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _backfill_legacy_file_hashes(conn):
    rows = conn.execute(
        "SELECT id, file_path FROM knowledge_files WHERE file_sha256 IS NULL OR file_sha256 = ''"
    ).fetchall()
    for file_id, stored_path in rows:
        resolved_path = _resolve_stored_path(stored_path)
        if not resolved_path or not os.path.isfile(resolved_path):
            continue
        try:
            file_sha256 = calculate_file_sha256(resolved_path)
            conn.execute(
                "UPDATE knowledge_files SET file_sha256 = ? WHERE id = ?",
                (file_sha256, file_id),
            )
        except OSError:
            continue

def init_db():
    """初始化数据库表结构"""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS `courses` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `course_name` TEXT NOT NULL,
                `created_at` TEXT DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS `knowledge_files` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `course_id` INTEGER DEFAULT NULL,
                `file_name` TEXT NOT NULL,
                `file_path` TEXT NOT NULL,
                `status` TEXT NOT NULL DEFAULT 'uploaded'
                    CHECK (`status` IN ('uploaded', 'parsing', 'indexing', 'ready', 'failed')),
                `page_count` INTEGER NOT NULL DEFAULT 0,
                `engine` TEXT DEFAULT NULL,
                `elapsed_ms` INTEGER NOT NULL DEFAULT 0,
                `chunk_count` INTEGER NOT NULL DEFAULT 0,
                `error_message` TEXT DEFAULT NULL,
                `file_sha256` TEXT DEFAULT NULL,
                `started_at` TEXT DEFAULT NULL,
                `completed_at` TEXT DEFAULT NULL,
                `updated_at` TEXT DEFAULT (datetime('now', 'localtime')),
                `document_type` TEXT NOT NULL DEFAULT 'pdf',
                `mime_type` TEXT DEFAULT 'application/pdf',
                `source_kind` TEXT NOT NULL DEFAULT 'upload',
                `source_url` TEXT DEFAULT NULL,
                `unit_type` TEXT NOT NULL DEFAULT 'page',
                `unit_count` INTEGER NOT NULL DEFAULT 0,
                `created_at` TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (`course_id`) REFERENCES `courses`(`id`) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS `deadlines` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `student_id` TEXT,
                `course_name` TEXT,
                `task_name` TEXT,
                `task_type` TEXT,
                `deadline` DATETIME,
                `is_submitted` BOOLEAN,
                `url` TEXT
            );
        """)

        _ensure_column(conn, "courses", "parent_id", "INTEGER DEFAULT NULL")

        existing_file_columns = _table_columns(conn, "knowledge_files")
        is_legacy_table = "status" not in existing_file_columns
        for column_name, definition in KNOWLEDGE_FILE_COLUMNS.items():
            _ensure_column(conn, "knowledge_files", column_name, definition)

        # 旧数据全部来自历史 PDF 上传；新格式则根据扩展名修正默认迁移值。
        conn.execute(
            """
            UPDATE knowledge_files
            SET document_type = CASE
                    WHEN lower(file_name) LIKE '%.docx' THEN 'docx'
                    WHEN lower(file_name) LIKE '%.pptx' THEN 'pptx'
                    WHEN lower(file_name) LIKE '%.md' OR lower(file_name) LIKE '%.markdown' THEN 'markdown'
                    WHEN lower(file_name) LIKE '%.html' OR lower(file_name) LIKE '%.htm' THEN 'html'
                    ELSE 'pdf'
                END,
                mime_type = CASE
                    WHEN lower(file_name) LIKE '%.docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    WHEN lower(file_name) LIKE '%.pptx' THEN 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    WHEN lower(file_name) LIKE '%.md' OR lower(file_name) LIKE '%.markdown' THEN 'text/markdown'
                    WHEN lower(file_name) LIKE '%.html' OR lower(file_name) LIKE '%.htm' THEN 'text/html'
                    ELSE 'application/pdf'
                END,
                unit_type = CASE
                    WHEN lower(file_name) LIKE '%.pptx' THEN 'slide'
                    WHEN lower(file_name) LIKE '%.docx' OR lower(file_name) LIKE '%.md'
                         OR lower(file_name) LIKE '%.markdown' THEN 'heading'
                    WHEN lower(file_name) LIKE '%.html' OR lower(file_name) LIKE '%.htm' THEN 'web_section'
                    ELSE 'page'
                END,
                unit_count = CASE
                    WHEN unit_count = 0 AND page_count > 0 THEN page_count
                    ELSE unit_count
                END
            WHERE document_type IS NULL OR document_type = '' OR document_type = 'pdf'
            """
        )

        if is_legacy_table:
            # 旧记录已经完成过历史入库流程，迁移时应视为可检索状态。
            conn.execute(
                """
                UPDATE knowledge_files
                SET status = 'ready',
                    updated_at = COALESCE(updated_at, created_at, datetime('now', 'localtime'))
                """
            )

        _backfill_legacy_file_hashes(conn)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_files_sha256_status "
            "ON knowledge_files(file_sha256, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_knowledge_files_source_url "
            "ON knowledge_files(source_url)"
        )
        conn.commit()
    finally:
        conn.close()


def update_file_ingestion(file_id, status=None, **fields):
    """原子更新单个文件的入库状态和指标。"""
    allowed_fields = {
        "page_count", "engine", "elapsed_ms", "chunk_count", "error_message",
        "file_sha256", "file_name", "file_path", "started_at", "completed_at",
        "document_type", "mime_type", "source_kind", "source_url",
        "unit_type", "unit_count",
    }
    unknown_fields = set(fields) - allowed_fields
    if unknown_fields:
        raise ValueError(f"不允许更新的入库字段: {sorted(unknown_fields)}")
    if status is not None and status not in INGESTION_STATUSES:
        raise ValueError(f"非法入库状态: {status}")

    assignments = []
    values = []
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    for field_name, value in fields.items():
        assignments.append(f"{field_name} = ?")
        values.append(value)
    assignments.append("updated_at = datetime('now', 'localtime')")
    values.append(file_id)

    conn = get_db_connection()
    try:
        current_record = conn.execute(
            "SELECT status FROM knowledge_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        if not current_record:
            raise LookupError(f"文件记录不存在: {file_id}")
        current_status = current_record["status"]
        if (
            status is not None
            and status != current_status
            and status not in INGESTION_TRANSITIONS.get(current_status, set())
        ):
            raise ValueError(f"非法入库状态流转: {current_status} → {status}")

        cursor = conn.execute(
            f"UPDATE knowledge_files SET {', '.join(assignments)} WHERE id = ?",
            values,
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"文件状态更新失败: {file_id}")
        conn.commit()
    finally:
        conn.close()

def get_db_connection():
    """获取数据库连接（带字典形式返回结果的 Row 工厂）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.row_factory = sqlite3.Row
    return conn
# ---------------------------------------------------------
# 新增：为 Deadline 看板提供的数据读写接口
# ---------------------------------------------------------

def get_account_info(student_id: str):
    """从 campus_config 表获取学号和密码，如果表结构不一样请调整表名"""
    conn = get_db_connection()
    # 注意：这里查的是 campus_config 表，这与你的 campus.py 里的建表逻辑保持一致
    row = conn.execute("SELECT student_id, password, real_name FROM campus_config WHERE student_id = ?", (student_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_deadlines(student_id: str):
    """从 deadlines 表读取某个学号的缓存数据"""
    conn = get_db_connection()
    rows = conn.execute("SELECT * FROM deadlines WHERE student_id = ? ORDER BY deadline ASC", (student_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_deadlines(student_id: str, deadlines_list: list):
    """
    保存最新抓取的 Deadline 数据。
    采用先清空该学号旧数据，再批量插入新数据的简单策略。
    """
    conn = get_db_connection()
    try:
        # 清理旧数据，保证不冗余
        conn.execute("DELETE FROM deadlines WHERE student_id = ?", (student_id,))
        
        # 批量插入新数据
        for item in deadlines_list:
            conn.execute('''
                INSERT INTO deadlines (student_id, course_name, task_name, task_type, deadline, is_submitted, url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                student_id, 
                item.get('course_name'), 
                item.get('title'), 
                item.get('type', 'assignment'), # 这里建议存原类型以区分考试和作业
                item.get('deadline'), 
                item.get('is_submitted', False),
                item.get('source', '') # 这里临时把 source 存在 url 字段，或者你也可以扩充 DB 字段
            ))
        conn.commit()
    except Exception as e:
        print(f"Database save error: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

# 模块导入时自动建表
init_db()
