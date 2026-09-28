# -*- coding: utf-8 -*-
"""向量数据库（services/vectordb.py）离线测试：含与 rag.py 的集成。

不联网、不动真实向量库：临时目录 + 临时知识库。
跑法（在 app/ 目录下）：python eval/_test_vectordb.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

TMP_ROOT = Path(tempfile.mkdtemp(prefix="vdb-test-"))
TMP_KB = TMP_ROOT / "knowledge"
TMP_VDB = TMP_ROOT / "vector.sqlite3"
os.environ["VECTOR_DB_PATH"] = str(TMP_VDB)      # 务必隔离：别碰 app/data/vector.sqlite3

import numpy as np

from services.knowledge import vectordb
from services.knowledge.rag import RagService, _rag_chunk_ref

FAILED = 0


def check(name: str, got, want) -> None:
    global FAILED
    ok = got == want
    if not ok:
        FAILED += 1
        print(f"  [NG] {name}  期望={want!r} 实际={got!r}")
    else:
        print(f"  [OK] {name}")


def truthy(name: str, got) -> None:
    check(name, bool(got), True)


# --------------------------------------------------------------------------- #
print("A. 向量化后端")
# --------------------------------------------------------------------------- #
embedder = vectordb.LocalEmbedder(dim=256)
vec1 = embedder(["员工出差报销流程"])[0]
vec2 = embedder(["员工出差报销流程"])[0]
check("维度正确", int(vec1.shape[0]), 256)
check("同一文本两次结果一致（可落盘的前提）", bool(np.allclose(vec1, vec2)), True)
check("已 L2 归一化", round(float(np.linalg.norm(vec1)), 5), 1.0)
empty = embedder([""])[0]
check("空文本的模为 0（不会 NaN）", float(np.linalg.norm(empty)), 0.0)
check("中文无需分词也能有重叠", bool(np.allclose(
    embedder(["报销"])[0].dot(embedder(["报销的单"])[0]) > 0.5, True)), True)

check("未配 EMBEDDING_BASE_URL 时自动选 local", vectordb.backend_name(), "local")
os.environ["EMBEDDING_BASE_URL"] = "https://example.invalid/v1"
os.environ["EMBEDDING_API_KEY"] = "sk-test"
check("配了 embedding 地址则自动选 api", vectordb.backend_name(), "api")
os.environ.pop("EMBEDDING_BASE_URL")
os.environ.pop("EMBEDDING_API_KEY")

# --------------------------------------------------------------------------- #
print("\nB. 存储与检索")
# --------------------------------------------------------------------------- #
corpus = {
    "policy.md#1": "员工出差报销需要在返回公司后三十天内提交报销单和发票。",
    "policy.md#2": "差旅标准：交通为飞机经济舱，住宿为一线城市每晚六百元。",
    "faq.md#1": "咖啡机除垢：每月使用专用除垢剂清洗一次水箱。",
    "faq.md#2": "数据库连接失败先检查网络与主机端口配置是否正确。",
}
store = vectordb.get_store(refresh=True)
check("写入条数", store.upsert_many(
    [(ref, text, {"source": ref.split("#")[0]}) for ref, text in corpus.items()]), 4)
check("落盘计数", store.count(), 4)
check("Top1 命中报销策略", store.search("报销流程是什么", 1)[0]["ref"], "policy.md#1")
check("Top1 命中差旅标准", store.search("飞机经济舱住宿多少钱", 1)[0]["ref"], "policy.md#2")
check("Top1 命中咖啡机", store.search("咖啡机怎么清洗水箱", 1)[0]["ref"], "faq.md#1")
check("分数在 0~1", 0.0 < store.search("报销", 1)[0]["score"] <= 1.0, True)
check("元数据过滤", bool(store.search("报销流程", 5, where={"source": "policy.md"})), True)
check("过滤后被滤空", store.search("报销流程", 5, where={"source": "nosuch.md"}), [])
check("谓词式过滤", [h["ref"] for h in store.search(
    "标准", 5, where=lambda m: m.get("source") == "policy.md")][0] in ("policy.md#2", "policy.md#1"), True)

print("\nC. 持久化 / 增量 / 删除")
check("换实例重开仍可读", vectordb.VectorDB(TMP_VDB, backend="local").count(), 4)
check("删除一条", store.delete("faq.md#1"), True)
check("删除后计数", store.count(), 3)

report = store.sync([
    ("policy.md#1", corpus["policy.md#1"], {"source": "policy.md"}),
    ("policy.md#2", corpus["policy.md#2"], {"source": "policy.md"}),
], prune=True)
check("内容未变不重写", (report["unchanged"], report["written"]), (2, 0))
check("prune 清掉不在名单里的旧向量", report["removed"], 1)
report2 = store.sync([
    ("policy.md#1", "这条内容改过了需要重新算向量", {"source": "policy.md"}),
    ("policy.md#2", corpus["policy.md#2"], {"source": "policy.md"}),
], prune=True)
check("只重算改动的那条", (report2["unchanged"], report2["written"]), (1, 1))

print("\nD. 索引与一致性")
os.environ["VECTOR_IVF_MIN"] = "0"
os.environ["VECTOR_NPROBE"] = "2"
small_path = TMP_ROOT / "ivf.sqlite3"
small = vectordb.VectorDB(small_path, backend="local")
small.upsert_many([(f"d{i}", f"第{i}份文档介绍{i % 3}号设备的维护流程与注意事项", {"i": i})
                   for i in range(150)])
small._load()
truthy("IVF 已构建", small._ivf is not None)
exact_refs = [h["ref"] for h in small.search("设备维护注意事项", 5, exact=True)]
check("IVF 与精确解 Top5 一致", [h["ref"] for h in small.search("设备维护注意事项", 5)], exact_refs)
small.close()
os.environ.pop("VECTOR_IVF_MIN")
os.environ.pop("VECTOR_NPROBE")

snap = store.stats()
check("统计含条数", snap["vectors"], 2)
check("统计含后端", snap["backend"], "local")
check("统计含维度", snap["dim"], store.dim)

mismatch = vectordb.VectorDB(TMP_VDB, backend="local",
                             embedder=vectordb.LocalEmbedder(dim=128))
try:
    mismatch.search("报销", 1)
    check("换维度会被拦下", False, True)
except vectordb.VectorDBError as exc:
    check("换维度会被拦下", "维度不一致" in str(exc), True)
mismatch.close()

# --------------------------------------------------------------------------- #
print("\nE. 与 rag.py 的集成（临时知识库）")
# --------------------------------------------------------------------------- #
TMP_KB.mkdir(parents=True, exist_ok=True)
(TMP_KB / "policy.md").write_text(
    "# 报销制度\n\n员工出差报销需在返回后三十天内提交单据。\n\n"
    "差旅住宿标准为一线城市每晚六百元，交通为经济舱。\n", encoding="utf-8")
(TMP_KB / "faq.md").write_text(
    "# 常见问题\n\n咖啡机每月需用除垢剂清洗水箱一次。\n", encoding="utf-8")

service = RagService(directory=TMP_KB)
service.rebuild()
engines = service.engines()
truthy("RAG 已挂上向量库", engines.get("vectordb_enabled"))
check("没有降级错误", engines.get("vectordb_error"), None)
check("向量条数 == 分块数", engines["vectordb"]["vectors"], service._chunk_count)
check("引擎标签显示双路", service.backend_label(), "智能（关键词+语义 双路融合）")

fused, note = service._rank_fused("报销要多久之内提交", 3, 6, "smart")
check("融合备注含语义通道", "语义" in note, True)
truthy("融合结果非空", fused)
truthy("至少有一条被向量通道命中", any("vector" in hits for _score, _idx, hits in fused))

hits = service.search("咖啡机怎么清洗", k=2)
truthy("检索结果包含知识库原文", "除垢" in hits or "清洗" in hits)

# 删掉一个文档后重建：旧向量必须跟着消失（不然会召回已删除的内容）
(TMP_KB / "faq.md").unlink()
service.rebuild()
after = vectordb.get_store().count()
check("删文档后向量跟着 prune", after, service._chunk_count)
truthy("旧内容的 ref 已不在库里", vectordb.get_store().search("咖啡机除垢", 3) == []
       or all(not h["ref"].startswith("faq.md") for h in vectordb.get_store().search("咖啡机除垢", 3)))

check("ref 生成带页码", _rag_chunk_ref(type("D", (), {"metadata": {"source": "a.pdf", "chunk_index": 2, "page": 7}})()), "a.pdf#2@p7")
check("无页码时不带 @", _rag_chunk_ref(type("D", (), {"metadata": {"source": "a.md", "chunk_index": 1}})()), "a.md#1")

try:
    vectordb.get_store().close()
except Exception:
    pass

print()
if FAILED:
    print(f"失败 {FAILED} 项")
    sys.exit(1)
print("全部测试通过 [OK]")
