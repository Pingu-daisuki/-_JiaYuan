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
    
    # 复用你优秀的表结构设计
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
            `task_type` TEXT, -- 'exam' 或 'assignment'
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

def get_db_connection():
    """获取数据库连接（带字典形式返回结果的 Row 工厂）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 模块导入时自动建表
init_db()