import os
import sqlite3

# 获取绝对路径，避免权限和找不到路径的问题
current_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(current_dir, 'campus_assistant.db')

print(f"正在创建/连接数据库，文件路径: {db_path}")

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 严格检查了每句结尾英文分号 (;) 的 SQLite 脚本
sql_script = """
CREATE TABLE IF NOT EXISTS `courses` (
    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
    `course_name` TEXT NOT NULL,
    `teacher` TEXT DEFAULT '',
    `classroom` TEXT DEFAULT '',
    `semester` TEXT NOT NULL,
    `schedule_json` TEXT
);

CREATE TABLE IF NOT EXISTS `deadlines` (
    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
    `course_id` INTEGER DEFAULT NULL,
    `title` TEXT NOT NULL,
    `description` TEXT,
    `due_time` TEXT NOT NULL,
    `priority` INTEGER DEFAULT 2,
    `is_completed` INTEGER DEFAULT 0,
    FOREIGN KEY (`course_id`) REFERENCES `courses`(`id`) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS `wrong_questions` (
    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
    `course_id` INTEGER DEFAULT NULL,
    `title` TEXT NOT NULL,
    `content_md` TEXT NOT NULL,
    `analysis_md` TEXT,
    `tags` TEXT DEFAULT '',
    `created_at` TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (`course_id`) REFERENCES `courses`(`id`) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS `knowledge_files` (
    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
    `course_id` INTEGER DEFAULT NULL,
    `file_name` TEXT NOT NULL,
    `file_path` TEXT NOT NULL,
    `vector_collection` TEXT NOT NULL,
    `status` TEXT DEFAULT 'processing',
    `created_at` TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (`course_id`) REFERENCES `courses`(`id`) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS `script_configs` (
    `id` INTEGER PRIMARY KEY AUTOINCREMENT,
    `script_name` TEXT NOT NULL UNIQUE,
    `account` TEXT NOT NULL,
    `encrypted_secret` TEXT NOT NULL,
    `is_enabled` INTEGER DEFAULT 1,
    `last_run_at` TEXT,
    `last_result` TEXT
);
"""

try:
    # 执行清爽无误的脚本
    cursor.executescript(sql_script)
    conn.commit()
    print("🎉 恭喜！本地数据地基已经完美建立完毕！")
except sqlite3.Error as e:
    print(f"❌ 依然建表失败，错误原因: {e}")
finally:
    conn.close()