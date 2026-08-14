"""Explicitly enqueue all existing upstream meetings for a new Milvus prefix."""
import argparse
import asyncio
import json

from . import db
from .config import Settings


async def main(enqueue: bool):
    settings = Settings.load()
    await db.init_pool(settings)
    try:
        async with db.aconn(settings) as connection, connection.cursor() as cursor:
            await cursor.execute("""SELECT id, phone
                FROM user_meeting_info
                WHERE phone IS NOT NULL AND phone<>''
                  AND (del_flag='0' OR del_flag IS NULL)
                  AND (COALESCE(content, '')<>'' OR COALESCE(abstract_content, '')<>''
                       OR COALESCE(abstract_text, '')<>'')
                ORDER BY id""")
            rows = await cursor.fetchall()
        if not enqueue:
            print(json.dumps({"eligible_meetings": len(rows), "enqueued": 0,
                              "dry_run": True}, ensure_ascii=False))
            return
        async with db.aconn(settings) as connection, connection.cursor() as cursor:
            await cursor.executemany("""INSERT INTO ingest_jobs
                (recording_id, phone, transcript_status, summary_status, payload)
                VALUES (%s,%s,'updated','updated',%s)""", [
                (str(row["id"]), row["phone"], json.dumps({
                    "phone": row["phone"], "meeting_id": str(row["id"]),
                    "operation": "upsert", "transcript_status": "updated",
                    "summary_status": "updated", "force_rebuild": True,
                }, ensure_ascii=False)) for row in rows
            ])
        print(json.dumps({"eligible_meetings": len(rows), "enqueued": len(rows),
                          "dry_run": False}, ensure_ascii=False))
    finally:
        await db.close_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--enqueue", action="store_true",
                        help="actually create rebuild jobs; default is dry-run")
    args = parser.parse_args()
    asyncio.run(main(args.enqueue))
