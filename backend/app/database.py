"""
PostgreSQL (Supabase) ulanishi va schema yaratish.

Ulanish quyidagi environment variable orqali beriladi (Render Environment'ga
qo'yiladi). Supabase loyihangizning Settings > Database > Connection string
("URI" formati, Session yoki Transaction pooler) qismidan olinadi:

  DATABASE_URL = "postgresql://postgres.xxxx:PAROL@aws-0-xxxx.pooler.supabase.com:5432/postgres"

  yoki alohida-alohida:
  PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

get_cursor() — context manager, eski MySQL kodini deyarli o'zgartirmasdan
ishlatish uchun mo'ljallangan:
    with get_cursor(commit=True) as cur:
        cur.execute("INSERT INTO ...", (...))
        cur.lastrowid

Placeholder sifatida butun kod bazasida SQLite/MySQL uslubidagi '?' ishlatilgan
— bu _adapt_query orqali avtomatik '%s' (psycopg2 formati) ga aylantiriladi.
Shuningdek MySQL'ga xos bo'lgan bir nechta sintaksis farqlari (backtick,
AUTO_INCREMENT, ON DUPLICATE KEY UPDATE, NOW()/UTC_TIMESTAMP(), INSERT IGNORE,
ENGINE=InnoDB) ham shu joyda PostgreSQL ekvivalentlariga avtomatik
o'giriladi — shu bilan boshqa modullardagi (routers/services) so'rovlarni
qayta yozmasdan ishlatish mumkin.
"""
import os
import re
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from psycopg2 import pool as pg_pool

_pool: "pg_pool.SimpleConnectionPool" = None


def _get_connection_params() -> dict:
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("MYSQL_URL")  # eski nom bilan qoldirilgan bo'lsa ham ishlaydi
    )
    if url:
        parsed = urlparse(url)
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "user": parsed.username or "postgres",
            "password": parsed.password or "",
            "dbname": (parsed.path or "/postgres").lstrip("/"),
        }
    return {
        "host": os.environ.get("PGHOST", "localhost"),
        "port": int(os.environ.get("PGPORT", "5432")),
        "user": os.environ.get("PGUSER", "postgres"),
        "password": os.environ.get("PGPASSWORD", ""),
        "dbname": os.environ.get("PGDATABASE", "postgres"),
    }


def _get_pool():
    global _pool
    if _pool is None:
        params = _get_connection_params()
        _pool = pg_pool.SimpleConnectionPool(1, 10, **params, sslmode="require")
    return _pool


# ==================== MySQL -> PostgreSQL so'rov moslashtiruvi ====================

def _adapt_query(query: str) -> str:
    q = query

    # Backtick'lar (MySQL identifier quoting) -> double quote (Postgres)
    q = q.replace("`", '"')

    # ENGINE=InnoDB; kabi MySQL'ga xos qatorlarni olib tashlash
    q = re.sub(r"\)\s*ENGINE=InnoDB\s*;?", ");", q)

    # AUTO_INCREMENT -> Postgres'da SERIAL orqali qo'llaniladi (schema'da alohida hal qilinadi)
    q = q.replace("AUTO_INCREMENT", "")

    # TINYINT(1) -> SMALLINT
    q = re.sub(r"TINYINT\(1\)", "SMALLINT", q)
    q = re.sub(r"\bTINYINT\b", "SMALLINT", q)

    # MEDIUMTEXT -> TEXT
    q = q.replace("MEDIUMTEXT", "TEXT")

    # DATETIME -> TIMESTAMP
    q = re.sub(r"\bDATETIME\b", "TIMESTAMP", q)

    # ON UPDATE CURRENT_TIMESTAMP MySQL'da bor, Postgres'da yo'q — bu qismni olib tashlaymiz
    q = re.sub(r"\s*ON UPDATE CURRENT_TIMESTAMP", "", q)

    # UTC_TIMESTAMP() -> Postgres ekvivalenti
    q = q.replace("UTC_TIMESTAMP()", "(NOW() AT TIME ZONE 'UTC')")

    # INSERT IGNORE INTO -> INSERT INTO ... ON CONFLICT DO NOTHING
    if q.strip().upper().startswith("INSERT IGNORE"):
        q = re.sub(r"^\s*INSERT IGNORE", "INSERT", q, flags=re.IGNORECASE)
        q = q.rstrip().rstrip(";")
        q += " ON CONFLICT DO NOTHING"

    # ON DUPLICATE KEY UPDATE col = VALUES(col) -> ON CONFLICT (...) DO UPDATE SET col = EXCLUDED.col
    if "ON DUPLICATE KEY UPDATE" in q.upper():
        q = _rewrite_upsert(q)

    # '?' placeholder'larni psycopg2 uslubidagi '%s' ga aylantirish (oxirida)
    q = q.replace("?", "%s")

    return q


_CONFLICT_TARGETS = {
    "settings": "(user_id, \"key\")",
    "api_keys": "(user_id, provider)",
    "users": "(name)",
}


def _rewrite_upsert(q: str) -> str:
    """
    'INSERT INTO tbl (...) VALUES (...) ON DUPLICATE KEY UPDATE col = VALUES(col), ...'
    ni Postgres'ning 'INSERT ... ON CONFLICT (target) DO UPDATE SET col = EXCLUDED.col, ...'
    ko'rinishiga o'giradi.
    """
    m = re.search(r"INSERT INTO\s+([a-zA-Z_\"]+)", q, re.IGNORECASE)
    table = m.group(1).strip('"') if m else None
    conflict_target = _CONFLICT_TARGETS.get(table, "")

    idx = q.upper().index("ON DUPLICATE KEY UPDATE")
    head = q[:idx].rstrip().rstrip(";")
    tail = q[idx + len("ON DUPLICATE KEY UPDATE"):].strip().rstrip(";")

    tail = re.sub(r"VALUES\(([a-zA-Z_\"]+)\)", r"EXCLUDED.\1", tail)

    if not conflict_target:
        return f"{head} ON CONFLICT DO NOTHING"

    return f"{head} ON CONFLICT {conflict_target} DO UPDATE SET {tail}"


class _CursorWrapper:
    """psycopg2 cursor'ni SQLite '?' placeholder va dict-row xulq-atvoriga moslaydi."""

    def __init__(self, raw_cursor, conn):
        self._cur = raw_cursor
        self._conn = conn
        self._last_insert_id = None

    def execute(self, query, params=None):
        adapted = _adapt_query(query)

        is_insert = adapted.strip().upper().startswith("INSERT")
        has_returning = "RETURNING" in adapted.upper()
        if is_insert and not has_returning and not adapted.rstrip().upper().endswith("DO NOTHING"):
            adapted = adapted.rstrip().rstrip(";") + " RETURNING id"

        # Har bir buyruqdan oldin SAVEPOINT qo'yamiz — shu bilan ichkarida xato
        # yuz bersa, faqat shu buyruqqa qadar rollback qilamiz, butun
        # tranzaksiyadagi oldingi (masalan CREATE TABLE) ishlarni saqlab qolamiz.
        self._cur.execute("SAVEPOINT vss_before_stmt")
        try:
            self._cur.execute(adapted, params or ())
        except psycopg2.errors.UndefinedColumn:
            # 'id' ustuni bo'lmagan jadvalga (composite-PK jadvallar) RETURNING id
            # qo'shilgan bo'lishi mumkin — shuni olib tashlab qayta urinamiz.
            self._cur.execute("ROLLBACK TO SAVEPOINT vss_before_stmt")
            fallback = re.sub(r"\s*RETURNING id\s*$", "", adapted)
            self._cur.execute(fallback, params or ())

        if is_insert:
            try:
                row = self._cur.fetchone()
                self._last_insert_id = row["id"] if row else None
            except (psycopg2.ProgrammingError, KeyError, TypeError):
                self._last_insert_id = None
        return self

    def executemany(self, query, seq_of_params):
        adapted = _adapt_query(query)
        self._cur.executemany(adapted, seq_of_params)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def lastrowid(self):
        return self._last_insert_id

    @property
    def rowcount(self):
        return self._cur.rowcount

    def try_execute(self, query, params=None):
        """execute() ni xatoni yutgan holda bajaradi va, agar xato bo'lsa,
        faqat shu buyruqni SAVEPOINT orqali bekor qiladi (butun tranzaksiyani
        emas) — shu bilan oldin bajarilgan CREATE TABLE va boshqa ishlar
        saqlanib qoladi. True/False qaytaradi (muvaffaqiyatli bo'ldimi)."""
        try:
            self.execute(query, params)
            return True
        except Exception:
            self._cur.execute("ROLLBACK TO SAVEPOINT vss_before_stmt")
            return False


@contextmanager
def get_cursor(commit: bool = False):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        raw_cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor = _CursorWrapper(raw_cursor, conn)
        yield cursor
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        raw_cursor.close()
        pool.putconn(conn)


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS shorts (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL DEFAULT 1,
        file_path VARCHAR(1000),
        thumbnail_path VARCHAR(1000),
        start_time FLOAT DEFAULT 0,
        end_time FLOAT DEFAULT 0,
        duration FLOAT DEFAULT 0,
        score FLOAT DEFAULT 0,
        title VARCHAR(500),
        description TEXT,
        hashtags VARCHAR(1000),
        keywords VARCHAR(1000),
        transcript TEXT,
        ai_topic VARCHAR(500),
        ai_language VARCHAR(50),
        ai_category VARCHAR(255),
        ai_keywords VARCHAR(1000),
        ai_viral_tips TEXT,
        ai_analyzed_at TIMESTAMP NULL,
        subtitle_text TEXT,
        subtitle_enabled SMALLINT DEFAULT 0,
        watermark_enabled SMALLINT DEFAULT 0,
        watermark_path VARCHAR(1000),
        crop_mode VARCHAR(50) DEFAULT 'none',
        status VARCHAR(50) DEFAULT 'draft',
        youtube_video_id VARCHAR(100),
        youtube_url VARCHAR(500),
        playlist_id VARCHAR(100),
        category_id VARCHAR(20) DEFAULT '22',
        visibility VARCHAR(20) DEFAULT 'public',
        made_for_kids SMALLINT DEFAULT 0,
        manual_upload SMALLINT DEFAULT 1,
        scheduled_at TIMESTAMP NULL,
        uploaded_at TIMESTAMP NULL,
        error_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_shorts_status ON shorts (status);",
    "CREATE INDEX IF NOT EXISTS idx_shorts_scheduled_at ON shorts (scheduled_at);",
    "CREATE INDEX IF NOT EXISTS idx_shorts_user_id ON shorts (user_id);",
    """
    CREATE TABLE IF NOT EXISTS settings (
        user_id INT NOT NULL DEFAULT 1,
        "key" VARCHAR(100) NOT NULL,
        value TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, "key")
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        user_id INT NOT NULL DEFAULT 1,
        provider VARCHAR(50) NOT NULL,
        encrypted_key TEXT,
        enabled SMALLINT DEFAULT 1,
        last_checked_at TIMESTAMP NULL,
        last_check_status VARCHAR(20),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, provider)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS youtube_account (
        user_id INT PRIMARY KEY,
        client_secret_path VARCHAR(1000),
        encrypted_token_json TEXT,
        channel_id VARCHAR(100),
        channel_title VARCHAR(255),
        channel_thumbnail VARCHAR(500),
        connected_at TIMESTAMP NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS prompt_templates (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL DEFAULT 1,
        name VARCHAR(255) NOT NULL,
        is_active SMALLINT DEFAULT 0,
        audience VARCHAR(500),
        language VARCHAR(20) DEFAULT 'uz',
        tone VARCHAR(255),
        seo_focus VARCHAR(500),
        cta_text VARCHAR(500),
        use_emoji SMALLINT DEFAULT 1,
        keywords VARCHAR(1000),
        banned_words VARCHAR(1000),
        title_max_length INT DEFAULT 100,
        description_template TEXT,
        custom_instructions TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_prompt_templates_user_id ON prompt_templates (user_id);",
    """
    CREATE TABLE IF NOT EXISTS schedule_slots (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL DEFAULT 1,
        hour INT NOT NULL,
        minute INT NOT NULL,
        enabled SMALLINT DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_schedule_slots_user_id ON schedule_slots (user_id);",
    """
    CREATE TABLE IF NOT EXISTS task_queue (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL DEFAULT 1,
        task_type VARCHAR(100),
        ref_id INT NULL,
        status VARCHAR(20) DEFAULT 'queued',
        progress INT DEFAULT 0,
        message VARCHAR(500),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue (status);",
    "CREATE INDEX IF NOT EXISTS idx_task_queue_user_id ON task_queue (user_id);",
    """
    CREATE TABLE IF NOT EXISTS logs (
        id SERIAL PRIMARY KEY,
        user_id INT NOT NULL DEFAULT 1,
        level VARCHAR(20),
        source VARCHAR(100),
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_logs_created_at ON logs (created_at);",
    "CREATE INDEX IF NOT EXISTS idx_logs_user_id ON logs (user_id);",
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token VARCHAR(64) PRIMARY KEY,
        user_id INT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """,
]

DEFAULT_SETTINGS = {
    "daily_upload_count": "4",
    "timezone": "Asia/Tashkent",
    "auto_schedule_mode": "calendar",
    "output_width": "1080",
    "output_height": "1920",
    "default_title_template": "Video #{index}",
    "default_description_template": "Yangi qiziqarli video! #shorts",
    "default_hashtags": "#shorts #viral",
}

# Eski (oldingi versiyadagi) bazalarni yangi ustunlar bilan moslashtirish uchun
# best-effort migratsiya buyruqlari — ustun allaqachon mavjud bo'lsa xato jim yutiladi.
MIGRATION_STATEMENTS = [
    "ALTER TABLE shorts ADD COLUMN transcript TEXT",
    "ALTER TABLE shorts ADD COLUMN ai_topic VARCHAR(500)",
    "ALTER TABLE shorts ADD COLUMN ai_language VARCHAR(50)",
    "ALTER TABLE shorts ADD COLUMN ai_category VARCHAR(255)",
    "ALTER TABLE shorts ADD COLUMN ai_keywords VARCHAR(1000)",
    "ALTER TABLE shorts ADD COLUMN ai_viral_tips TEXT",
    "ALTER TABLE shorts ADD COLUMN ai_analyzed_at TIMESTAMP NULL",
    "ALTER TABLE shorts ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE prompt_templates ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE schedule_slots ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE task_queue ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE logs ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE settings ADD COLUMN user_id INT NOT NULL DEFAULT 1",
    "ALTER TABLE api_keys ADD COLUMN user_id INT NOT NULL DEFAULT 1",
]

# settings/api_keys/youtube_account uchun PRIMARY KEY ni composite (user_id, ...) ga
# o'zgartirish — eski bazalarda kerak bo'lishi mumkin, xatoni yutuvchi bosqichda.
PK_MIGRATION_STATEMENTS = [
    'ALTER TABLE settings DROP CONSTRAINT IF EXISTS settings_pkey, ADD PRIMARY KEY (user_id, "key")',
    "ALTER TABLE api_keys DROP CONSTRAINT IF EXISTS api_keys_pkey, ADD PRIMARY KEY (user_id, provider)",
    "ALTER TABLE youtube_account DROP CONSTRAINT IF EXISTS youtube_account_pkey, ADD PRIMARY KEY (user_id)",
]

DEFAULT_USERS = ["Foydalanuvchi 1", "Foydalanuvchi 2", "Foydalanuvchi 3"]


def _ensure_default_users(cur) -> list:
    """3 ta boshlang'ich foydalanuvchini yaratadi (agar hali mavjud bo'lmasa) va ID ro'yxatini qaytaradi."""
    for name in DEFAULT_USERS:
        cur.execute("INSERT IGNORE INTO users (name) VALUES (?)", (name,))
    cur.execute("SELECT id FROM users ORDER BY id ASC")
    return [r["id"] for r in cur.fetchall()]


def _ensure_user_defaults(cur, user_id: int):
    """Har bir foydalanuvchi uchun boshlang'ich settings/schedule_slots/prompt_templates yaratadi."""
    for key, value in DEFAULT_SETTINGS.items():
        cur.execute(
            "INSERT IGNORE INTO settings (user_id, `key`, value) VALUES (?, ?, ?)",
            (user_id, key, value),
        )

    cur.execute("SELECT COUNT(*) AS cnt FROM schedule_slots WHERE user_id = ?", (user_id,))
    if cur.fetchone()["cnt"] == 0:
        for hour, minute in [(9, 0), (13, 0), (18, 0), (21, 0)]:
            cur.execute(
                "INSERT INTO schedule_slots (user_id, hour, minute, enabled) VALUES (?, ?, ?, 1)",
                (user_id, hour, minute),
            )

    cur.execute("SELECT COUNT(*) AS cnt FROM prompt_templates WHERE user_id = ?", (user_id,))
    if cur.fetchone()["cnt"] == 0:
        cur.execute(
            """INSERT INTO prompt_templates
               (user_id, name, is_active, audience, language, tone, seo_focus, cta_text, use_emoji,
                keywords, banned_words, title_max_length, description_template, custom_instructions)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (
                user_id, "Standart shablon",
                "Umumiy YouTube auditoriyasi, 16-35 yosh", "uz", "energetic, qiziqarli",
                "trend hashtag va kalit so'zlarga urg'u berish",
                "Obuna bo'lishni va like bosishni unutmang!",
                "shorts, viral, trend", "",
                100, "{title}\n\n{summary}\n\n{hashtags}",
                "Sarlavha diqqat tortuvchi va qisqa bo'lsin.",
            ),
        )


def init_db():
    """Jadvallarni yaratadi (agar mavjud bo'lmasa) va boshlang'ich ma'lumotlarni joylaydi."""
    with get_cursor(commit=True) as cur:
        for statement in SCHEMA_STATEMENTS:
            cur.execute(statement)

        for statement in MIGRATION_STATEMENTS:
            # Xato yutilsa ham, rollback() shart — aks holda Postgres
            # tranzaksiyani "aborted" holatda qoldirib, keyingi barcha
            # buyruqlarni InFailedSqlTransaction bilan rad etadi.
            cur.try_execute(statement)

        for statement in PK_MIGRATION_STATEMENTS:
            cur.try_execute(statement)

        user_ids = _ensure_default_users(cur)
        for uid in user_ids:
            _ensure_user_defaults(cur, uid)
