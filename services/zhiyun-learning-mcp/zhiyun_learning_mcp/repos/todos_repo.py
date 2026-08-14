# meeting_assistant/repos/todos_repo.py
from datetime import timedelta
from ..db import aconn


class TodosRepo:
    def __init__(self, settings): self.s = settings

    async def delete_for(self, rid):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("DELETE FROM todos WHERE recording_id=%s", (rid,))

    async def insert_many(self, rid, phone, todos: list[dict]):
        rows = [(rid, phone, t["task"], t.get("owner"), t.get("due")) for t in todos]
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.executemany("INSERT INTO todos (recording_id, phone, task, owner, due) "
                                  "VALUES (%s,%s,%s,%s,%s)", rows)

    async def query(self, phone, status="open", due_before=None, owner=None):
        q = "SELECT * FROM todos WHERE phone=%s"; params = [phone]
        if status:
            q += " AND status=%s"; params.append(status)
        if due_before:
            q += " AND due <= %s"; params.append(due_before)
        if owner:
            q += " AND owner=%s"; params.append(owner)
        q += " ORDER BY due IS NULL, due"
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute(q, params)
            return await cur.fetchall()

    async def due_within(self, phone, days, now):
        async with aconn(self.s) as c, c.cursor() as cur:
            await cur.execute("SELECT * FROM todos WHERE phone=%s AND status='open' "
                              "AND due IS NOT NULL AND due <= %s ORDER BY due",
                              (phone, now + timedelta(days=days)))
            return await cur.fetchall()
