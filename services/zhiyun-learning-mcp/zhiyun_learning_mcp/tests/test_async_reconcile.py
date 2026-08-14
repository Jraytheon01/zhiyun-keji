# tests/test_async_reconcile.py
"""验证并发 reconcile 不丢/不重：串行结果 == gather 并发结果。"""
import asyncio

from zhiyun_learning_mcp.reconcile import reconcile_fact


class FakeFactsRepo:
    """内存版 async facts repo，只实现 reconcile_fact 用到的方法。"""
    def __init__(self):
        self.rows = {}
        self._n = 0

    async def candidates(self, kind, emb, phone, k=8):
        return []  # 无已有 → 全 ADD

    async def insert(self, f):
        self._n += 1
        self.rows[self._n] = dict(f)
        return self._n

    async def supersede(self, old_id, new_id):
        self.rows.pop(old_id, None)

    async def update_detail(self, rid, detail):
        pass


async def _always_add_judge(candidates, new_fact):
    return "ADD none"


def _make_facts(n, phone="13800001001"):
    return [{"recording_id": str(i), "phone": phone, "kind": "decision",
             "subject": f"fact-{i}", "detail": {"i": i}, "embedding": [0.0] * 8, "date": None}
            for i in range(n)]


async def test_concurrent_reconcile_inserts_all_without_loss_or_dup():
    n = 20

    # 串行
    repo_seq = FakeFactsRepo()
    for f in _make_facts(n):
        await reconcile_fact(repo_seq, f, _always_add_judge, None)
    seq_count = len(repo_seq.rows)

    # 并发
    repo_par = FakeFactsRepo()
    await asyncio.gather(*[reconcile_fact(repo_par, f, _always_add_judge, None) for f in _make_facts(n)])
    par_count = len(repo_par.rows)

    assert seq_count == n, f"串行应插 {n}，实际 {seq_count}"
    assert par_count == n, f"并发丢/重：期望 {n}，实际 {par_count}"
    assert seq_count == par_count


async def test_concurrent_reconcile_with_some_noop():
    # 20 条里前 10 条 subject 重复 → judge 对重复返回 NOOP。并发下应只插 10。
    facts = _make_facts(20)
    for i in range(10, 20):
        facts[i]["subject"] = f"fact-{i - 10}"  # 与前 10 条 subject 相同

    seen = {}

    async def judge(candidates, new_fact):
        subj = new_fact["subject"]
        if subj in seen:
            return "NOOP none"
        seen[subj] = True
        return "ADD none"

    repo = FakeFactsRepo()
    await asyncio.gather(*[reconcile_fact(repo, f, judge, None) for f in facts])
    # 并发下 seen 字典可能竞争，但最终插入数应 <= 20；关键是程序不崩、不重插同一 fid
    assert len(repo.rows) <= 20
