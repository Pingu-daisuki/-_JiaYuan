# backend/core/db.py
import sqlite3
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
DB_PATH = os.path.join(parent_dir, 'campus_assistant.db')

def init_db():
    """初始化数据库表结构"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 执行建表 SQL
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
    conn.commit()
    conn.close()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("ALTER TABLE courses ADD COLUMN parent_id INTEGER DEFAULT NULL")
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        pass # 列如果已存在就会忽略报错，极其安全
    conn.commit()
    conn.close()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("ALTER TABLE courses ADD COLUMN parent_id INTEGER DEFAULT NULL")
        conn.commit()
        conn.close()
    except sqlite3.OperationalError:
        pass # 列如果已存在就会忽略报错，极其安全

def get_db_connection():
    """获取数据库连接（带字典形式返回结果的 Row 工厂）"""
    conn = sqlite3.connect(DB_PATH)
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