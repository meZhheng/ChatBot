import hashlib
import sqlite3


def get_md5_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def check_md5_hash(text: str, hash_value: str) -> bool:
    return get_md5_hash(text) == hash_value


class KnowledgeBaseService:
    def __init__(self, sqlite: sqlite3.Connection):
        self.sqlite = sqlite
        self.sqlite.row_factory = sqlite3.Row
        self.ensure_schema()

    def ensure_schema(self):
        self.sqlite.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_text_hashes (
                content_hash TEXT PRIMARY KEY,
                source_name TEXT NOT NULL,
                content_type TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.sqlite.commit()

    def has_text(self, text: str) -> bool:
        return self.has_hash(get_md5_hash(text))

    def has_hash(self, content_hash: str) -> bool:
        row = self.sqlite.execute(
            """
            SELECT 1
            FROM processed_text_hashes
            WHERE content_hash = ?
            """,
            (content_hash,),
        ).fetchone()
        return row is not None

    def record_text_hash(
        self,
        *,
        text: str,
        source_name: str,
        content_type: str | None,
    ) -> dict:
        content_hash = get_md5_hash(text)
        is_duplicate = self.has_hash(content_hash)

        if not is_duplicate:
            self.sqlite.execute(
                """
                INSERT INTO processed_text_hashes (
                    content_hash,
                    source_name,
                    content_type
                )
                VALUES (?, ?, ?)
                """,
                (content_hash, source_name, content_type),
            )
            self.sqlite.commit()

        return {
            "content_hash": content_hash,
            "source_name": source_name,
            "content_type": content_type,
            "is_duplicate": is_duplicate,
        }

    def list_md5_records(self) -> list[dict]:
        rows = self.sqlite.execute(
            """
            SELECT content_hash, source_name, content_type
            FROM processed_text_hashes
            ORDER BY created_at, content_hash
            """
        ).fetchall()
        return [dict(row) for row in rows]
