"""Plan or apply additive versioned MySQL migrations."""
import argparse
from pathlib import Path

from .config import Settings
from .db import conn, init_db


MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def _statements(text: str):
    """Split our migration files while ignoring full-line SQL comments."""
    sql = "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("--"))
    return [statement.strip() for statement in sql.split(";")
            if statement.strip()]


def migrate(settings: Settings) -> list[str]:
    # CREATE IF NOT EXISTS only: establishes missing MCP tables without altering
    # upstream-owned source tables or replacing any existing production table.
    # Existing test databases may contain partial tables. Create only missing
    # tables first, then add missing fields before inserting the manual sentinel.
    init_db(settings, seed_manual=False)
    applied_now = []
    with conn(settings) as c, c.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""")
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row["version"] for row in cur.fetchall()}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in applied:
                continue
            for statement in _statements(path.read_text(encoding="utf-8")):
                cur.execute(statement)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
            applied_now.append(path.name)
        cur.execute("""INSERT IGNORE INTO recordings
            (recording_id, uploaded_at, has_audio, has_transcript, has_summary, ingestion_status)
            VALUES ('__manual__', NOW(), 0, 0, 0, 'n/a')""")
    return applied_now


def pending(settings: Settings) -> list[str]:
    with conn(settings) as c, c.cursor() as cur:
        cur.execute("""SELECT COUNT(*) AS present
            FROM information_schema.tables
            WHERE table_schema=DATABASE() AND table_name='schema_migrations'""")
        if cur.fetchone()["present"]:
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row["version"] for row in cur.fetchall()}
        else:
            applied = set()
    return [path.name for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
            if path.name not in applied]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true",
                        help="list pending versions without changing derived tables")
    args = parser.parse_args()
    settings = Settings.load()
    versions = pending(settings) if args.plan else migrate(settings)
    print("pending:" if args.plan else "applied:", versions or "(none)")
