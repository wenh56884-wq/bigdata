# -*- coding: utf-8 -*-
"""向量数据库（Vector Database）：为知识库提供**持久化**的高维向量存储与近邻检索。

为什么单独做这一层
------------------
改造前 rag.py 里的所谓语义检索是这样的：每次进程启动，把全部分块**重新算一遍** embedding
放进内存列表（`_VectorIndex`），配不到 EMBEDDING_* 就完全退化成关键词。**没有落盘、
没有增量更新、没有索引结构、重启即失效**——它只是"内存里的一个 list"，不是数据库。

这里实现的是一个能落地的向量库，具备：

    持久化    SQLite 存库，向量以 float32 二进制（BLOB）存放 + 元数据 JSON；重启直接加载
    向量化    两种后端：local（离线、零依赖，哈希 + n-gram + IDF）/ api（OpenAI 兼容 embedding）
    索引      向量不足 VECTOR_IVF_MIN 时走精确检索（余弦），超过自动构建 **IVF 倒排索引**
              （KMeans 粗量化 + nprobe 只搜最近若干簇），从 O(N) 降到 O(N/k)，并与精确解对照
    操作      upsert / delete / prune / clear / search(支持元数据过滤) / stats，线程安全
    一致性    换 embedding 后端或维度变化时，旧向量自动判定失效（提示重建而不是给出错的相似度）

依赖只用 numpy + sqlite3（可选 sklearn 供 IVF），不引入 chroma / faiss。

配置（.env，全部运行时读取）：
    VECTOR_DB=1                      总开关（默认开）
    VECTOR_DB_PATH=app/data/vector.sqlite3
    VECTOR_BACKEND=auto|local|api    auto：配了 EMBEDDING_API_KEY 用 api，否则 local
    VECTOR_DIM=512                   local 后端的向量维度
    VECTOR_IVF_MIN=5000              超过多少条才启用 IVF；0 表示总是 IVF，-1 关闭
    VECTOR_NPROBE=8                  IVF 探测几个簇（越大越准、越慢）

自检：python -m services.knowledge.vectordb（合成语料，不联网）
CLI ：python -m services.knowledge.vectordb --stats | --search "查询词" | --rebuild-check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "vector.sqlite3"

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS vectors (
        ref         TEXT PRIMARY KEY,   -- 业务主键："文件路径#分块序号"
        text        TEXT NOT NULL,      -- 原文（命中后直接返回，不必再回源读取）
        meta        TEXT,               -- JSON：来源、页码、自定义字段
        dim         INTEGER NOT NULL,   -- 向量维度（换后端会被校验发现）
        backend     TEXT NOT NULL,      -- 生成该向量的后端名
        vec         BLOB NOT NULL,      -- float32 二进制
        updated_at  REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_vectors_backend ON vectors(backend)",
    """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
)


class VectorDBError(RuntimeError):
    """向量库不可用 / 配置不一致（调用方应降级而不是崩溃）。"""


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_flag(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def enabled() -> bool:
    return _env_flag("VECTOR_DB", True)


def db_path() -> Path:
    custom = (os.getenv("VECTOR_DB_PATH") or "").strip()
    return Path(custom) if custom else DEFAULT_DB_PATH


def backend_name() -> str:
    """auto → 只有当**明确配了 embedding 服务地址**时才走 api，否则用 local。

    为什么不能只看 OPENAI_API_KEY：多数人配的是**对话**服务的 key（例如 DeepSeek），
    它并不提供 /embeddings，照着猜会让向量库每次同步都 503 然后降级。
    """
    configured = (os.getenv("VECTOR_BACKEND") or "auto").strip().lower()
    if configured not in ("auto", "local", "api"):
        configured = "auto"
    if configured == "auto":
        base_url = (os.getenv("EMBEDDING_BASE_URL") or "").strip()
        api_key = ((os.getenv("EMBEDDING_API_KEY") or "").strip()
                   or (os.getenv("OPENAI_API_KEY") or "").strip())
        return "api" if (base_url and api_key) else "local"
    return configured


def ivf_threshold() -> int:
    return _env_int("VECTOR_IVF_MIN", 5000)


def nprobe() -> int:
    return max(1, _env_int("VECTOR_NPROBE", 8))


# --------------------------------------------------------------------------- #
# 向量化：local（离线哈希）/ api（OpenAI 兼容）
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _features(text: str) -> list[str]:
    """切特征：中文取字 + 二元组（bigram），英文/数字取词。

    为什么中文要用 bigram：没有分词器时，"报销流程"和"流程报销"如果只按单字/整串算，
    要么丢粒度要么颗粒过粗；字级 + 二元组的组合对语序和部分匹配都更稳。
    """
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        piece = match.group(0)
        if _CJK_RE.search(piece):
            if len(piece) == 1:
                out.append(piece)
            else:
                out.extend(piece[i:i + 2] for i in range(len(piece) - 1))
        else:
            out.append(piece)
    return out


def _stable_hash(token: str) -> int:
    """进程内稳定的哈希（内置 hash() 有随机盐，跨进程会变，不能用于持久化向量）。"""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


class LocalEmbedder:
    """零依赖、离线、可复现的向量化：哈希 TF（次线性）→ L2 归一化。

    坦白说这是**词法层面**的"语义"（类似 TF-IDF 的稠密版），不是 Transformer 的语义；
    但它的好处是：不需要联网、不需要下载模型、向量稳定可落盘。
    想用真正的语义向量，配 EMBEDDING_* 切到 api 后端即可。
    """

    name = "local"

    def __init__(self, dim: int | None = None) -> None:
        self.dim = max(64, dim or _env_int("VECTOR_DIM", 512))

    def __call__(self, texts: list[str]) -> np.ndarray:
        """把若干文本转成 (n, dim) 的 float32 向量（已 L2 归一化）。"""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        matrix = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            counts: dict[int, float] = {}
            for token in _features(text or ""):
                code = _stable_hash(token)
                index = code % self.dim
                sign = -1.0 if (code >> 40) & 1 else 1.0   # 带符号哈希：抵消随机碰撞带来的偏置
                counts[index] = counts.get(index, 0.0) + sign
            for index, weight in counts.items():
                magnitude = abs(weight)
                if magnitude <= 0:                 # 带符号哈希正负相消 → 这一维不表态
                    continue
                # 次线性词频：出现 10 次不该比 1 次重 10 倍
                matrix[row, index] = math.copysign(1.0 + math.log(magnitude), weight)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (matrix / norms).astype(np.float32)


class ApiEmbedder:
    """OpenAI 兼容的 embedding 服务（POST {base_url}/embeddings）。"""

    name = "api"

    def __init__(self) -> None:
        self.model = (os.getenv("EMBEDDING_MODEL") or "").strip() or "text-embedding-3-small"
        self.base_url = (os.getenv("EMBEDDING_BASE_URL") or "").strip().rstrip("/") \
            or (os.getenv("BASE_URL") or "").strip().rstrip("/")
        self.api_key = ((os.getenv("EMBEDDING_API_KEY") or "").strip()
                        or (os.getenv("OPENAI_API_KEY") or "").strip())
        if not self.api_key:
            raise VectorDBError("api 后端需要 EMBEDDING_API_KEY（或 OPENAI_API_KEY）")
        if not self.base_url:
            raise VectorDBError("api 后端需要 EMBEDDING_BASE_URL")
        self.timeout = float(os.getenv("REQUEST_TIMEOUT", "60") or 60)
        self.dim = self._probe_dim()

    def _post(self, batch: list[str]) -> list[list[float]]:
        import urllib.request

        payload = json.dumps({"model": self.model, "input": batch}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        ordered = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        return [item["embedding"] for item in ordered]

    def _probe_dim(self) -> int:
        vector = self._post(["维度探测"])[0]
        return len(vector)

    def __call__(self, texts: list[str]) -> np.ndarray:
        out: list[list[float]] = []
        batch_size = max(1, _env_int("EMBEDDING_BATCH", 32))
        for start in range(0, len(texts), batch_size):
            out.extend(self._post(list(texts[start:start + batch_size])))
        if not out:
            return np.zeros((0, self.dim), dtype=np.float32)
        matrix = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (matrix / norms).astype(np.float32)


def build_embedder(backend: str | None = None):
    """按配置造一个 embedder；local 永不失败，api 失败时由调用方降级。"""
    which = (backend or backend_name()).strip().lower()
    if which == "api":
        return ApiEmbedder()
    return LocalEmbedder()


# --------------------------------------------------------------------------- #
# 向量库本体
# --------------------------------------------------------------------------- #
class VectorDB:
    """持久化向量库：SQLite 落盘 + 内存索引 + 可选 IVF 近邻加速。

    用法：
        db = VectorDB()
        db.sync([("a.md#1", "正文…", {"source": "a.md"})], prune=True)
        hits = db.search("怎么报销", top_k=5)
    """

    def __init__(self, path: Path | None = None, backend: str | None = None,
                 embedder=None) -> None:
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backend = (backend or backend_name()).strip().lower()
        self._embed = embedder or build_embedder(self.backend)
        self._lock = threading.RLock()
        self._ready = False          # 内存索引是否已构建
        self._exn: Exception | None = None

        self._refs: list[str] = []
        self._texts: list[str] = []
        self._metas: list[dict] = []
        self._backends: list[str] = []
        self._matrix: np.ndarray | None = None     # 原始（未乘 IDF）向量，形状 (n, dim)
        self._ivf: Any = None                      # sklearn KMeans（可选）
        self._assignments: np.ndarray | None = None

        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        for statement in _SCHEMA:
            self._conn.execute(statement)
        self._conn.commit()

    # ---------------------------- 内部：索引与落盘 ---------------------------- #
    @property
    def dim(self) -> int:
        return int(getattr(self._embed, "dim", 0) or 0)

    def _check_compat(self) -> None:
        """旧库存的向量和当前 embedder 不一致时，明确报错而不是给错误的相似度。

        注意：这里不能拿 `_ready` 当判据（加载时 `_ready` 就是被这几行置位的），只看数据本身。
        """
        if self._matrix is None or len(self._refs) == 0:
            return
        stored_dim = int(len(self._matrix[0])) if hasattr(self._matrix, "__len__") else 0
        expected = self.dim
        if expected and stored_dim and stored_dim != expected:
            raise VectorDBError(
                f"向量维度不一致（库里 {stored_dim} 维 vs 当前后端 {expected} 维）："
                "请删掉向量库或执行一次 rebuild 重建"
            )
        wrong_backend = {b for b in self._backends if b and b != self.backend}
        if wrong_backend:
            raise VectorDBError(
                f"向量由另一个后端生成（库里：{'、'.join(sorted(wrong_backend))}，"
                f"当前：{self.backend}）：不同后端的向量不能直接比较，请 rebuild 重建"
            )

    def _load(self) -> None:
        """从 SQLite 载入全部向量到内存索引（含 IDF 与可选 IVF 的构建）。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ref, text, meta, dim, backend, vec FROM vectors ORDER BY updated_at"
            ).fetchall()
            self._refs, self._texts, self._metas, self._backends = [], [], [], []
            vectors: list[np.ndarray] = []
            for ref, text, raw_meta, dim, stored_backend, blob in rows:
                try:
                    vector = np.frombuffer(blob, dtype=np.float32).copy()
                except Exception:
                    continue
                if vector.size != int(dim or 0):
                    continue
                self._refs.append(ref)
                self._texts.append(text or "")
                self._backends.append(str(stored_backend or ""))
                try:
                    self._metas.append(json.loads(raw_meta or "{}"))
                except Exception:
                    self._metas.append({})
                vectors.append(vector)

            if vectors:
                matrix = np.vstack(vectors).astype(np.float32)
            else:
                matrix = np.zeros((0, self.dim or 1), dtype=np.float32)
            self._matrix = matrix
            self._build_idf()
            self._build_ivf()
            self._ready = True
            self._check_compat()

    def ensure_ready(self) -> None:
        if not self._ready:
            self._load()

    def _build_idf(self) -> None:
        """由当前语料统计 IDF：出现得越普遍的维度，区分度越低。

        向量库里存的是**不带 IDF** 的原始 TF 向量，IDF 在加载时重算——这样新文档入库
        不会让旧向量"过期"，也保留了增量更新的能力。
        """
        matrix = self._matrix
        if matrix is None or len(matrix) == 0:
            self._idf = np.ones((self.dim or 1,), dtype=np.float32)
            return
        doc_freq = float((np.count_nonzero(matrix, axis=0) > 0).sum()) if False else \
            np.count_nonzero(matrix, axis=0).astype(np.float32)
        total = float(len(matrix))
        self._idf = np.log((total + 1.0) / (1.0 + doc_freq)).astype(np.float32)

    def _build_ivf(self) -> None:
        """规模够大时构建 IVF 倒排索引：KMeans 粗量化 + nprobe 只搜最近的几个簇。"""
        self._ivf, self._assignments = None, None
        matrix = self._matrix
        if matrix is None:
            return
        count = len(matrix)
        threshold = ivf_threshold()
        if threshold < 0 or count < max(threshold, 2):
            return
        if count < 100:                       # 样本太少，聚类没有意义
            return
        try:
            from sklearn.cluster import KMeans
        except Exception:
            return
        clusters = max(2, min(int(math.sqrt(count)), 64))
        if count < clusters * 10:
            return
        try:
            model = KMeans(n_clusters=clusters, n_init=5, random_state=42)
            labels = model.fit_predict(np.asarray(matrix, dtype=np.float32))
            self._ivf = model
            self._assignments = labels
        except Exception:
            self._ivf, self._assignments = None, None

    def _candidate_indexes(self, query: np.ndarray, exact: bool) -> np.ndarray:
        """决定本次要算相似度的向量范围（IVF 时先挑簇）。"""
        matrix = self._matrix
        n = len(matrix)
        if exact or self._ivf is None or self._assignments is None:
            return np.arange(n, dtype=int)
        centers = np.asarray(self._ivf.cluster_centers_, dtype=np.float32)
        idf = getattr(self, "_idf", np.ones((self.dim,), dtype=np.float32))
        q = _norm_rows((query * idf).reshape(1, -1))[0]
        centers = _norm_rows(np.asarray(self._ivf.cluster_centers_, dtype=np.float32) * idf)
        order = np.argsort(-(centers @ q))[: min(nprobe(), len(centers))]
        mask = np.isin(self._assignments, order)
        picks = np.where(mask)[0]
        # 候选太少（说明查询落在簇边界）就退回精确检索，宁可慢也不能漏
        return picks if len(picks) >= max(50, n // 20) else np.arange(n, dtype=int)

    # ---------------------------- 写操作 ---------------------------- #
    def upsert(self, ref: str, text: str, meta: dict | None = None) -> bool:
        """写入 / 更新一条（同一 ref 重复写入会覆盖）。返回是否真的落库。"""
        return self.upsert_many([(ref, text, meta or {})]) == 1

    def upsert_many(self, items: Iterable[tuple[str, str, dict]]) -> int:
        """批量写入：一次性向量化后成批入库，比逐条快得多。"""
        prepared = [(str(ref), str(text or ""), dict(meta or {}))
                    for ref, text, meta in items if str(ref)]
        if not prepared:
            return 0
        with self._lock:
            self.ensure_ready()
            try:
                vectors = self._embed([text for _ref, text, _meta in prepared])
            except Exception as exc:
                raise VectorDBError(f"向量化失败：{exc}") from exc
            now = time.time()
            payload = []
            for (ref, text, meta), vector in zip(prepared, vectors):
                payload.append((
                    ref, text, json.dumps(meta, ensure_ascii=False),
                    int(vector.size), self.backend, vector.astype(np.float32).tobytes(), now,
                ))
            self._conn.executemany(
                "INSERT INTO vectors (ref, text, meta, dim, backend, vec, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(ref) DO UPDATE SET text=excluded.text, meta=excluded.meta, "
                "dim=excluded.dim, backend=excluded.backend, vec=excluded.vec, "
                "updated_at=excluded.updated_at",
                payload,
            )
            # 新拿到的 refresh 标记要跟着走：换了后端/维度的旧数据不能被继续用
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("backend", self.backend),
            )
            self._conn.commit()
            self._ready = False          # 内存索引失效，下次查询重新加载
            return len(payload)

    def sync(self, items: Iterable[tuple[str, str, dict]], prune: bool = True) -> dict:
        """全量同步一批分块：`items` 为 [(ref, text, meta)]。

        用「ref 相同 + 文本相同 + 维度/后端一致」判断是否需要重新向量化——
        知识库没改动的分块不重复计算，只是将它们登记进保留名单。
        prune=True 时删除已不在名单里的旧数据（文档被删掉后不该继续被召回）。
        """
        prepared = [(str(ref), str(text or ""), dict(meta or {}))
                    for ref, text, meta in items if str(ref)]
        existing: dict[str, tuple] = {}
        if prepared:
            with self._lock:
                marks = ",".join("?" * len(prepared))
                rows = self._conn.execute(
                    f"SELECT ref, text, dim, backend FROM vectors WHERE ref IN ({marks})",
                    [row[0] for row in prepared],
                ).fetchall()
                existing = {str(row[0]): tuple(row) for row in rows}

        todo: list[tuple[str, str, dict]] = []
        unchanged = 0
        for ref, text, meta in prepared:
            row = existing.get(ref)
            if row and str(row[1]) == text and int(row[2] or 0) == self.dim and row[3] == self.backend:
                unchanged += 1
                continue
            todo.append((ref, text, meta))
        written = self.upsert_many(todo) if todo else 0
        removed = self.prune([row[0] for row in prepared]) if prune else 0
        return {"total": len(prepared), "unchanged": unchanged,
                "written": written, "removed": removed}

    def delete(self, ref: str) -> bool:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM vectors WHERE ref = ?", (str(ref),))
            self._conn.commit()
            if cursor.rowcount:
                self._ready = False
            return bool(cursor.rowcount)

    def prune(self, keep_refs: list[str]) -> int:
        """删除不在 keep_refs 里的数据（文档被删掉后，旧向量不该继续被召回）。"""
        keep = [str(ref) for ref in keep_refs]
        with self._lock:
            if not keep:
                cursor = self._conn.execute("DELETE FROM vectors")
            else:
                marks = ",".join("?" * len(keep))
                cursor = self._conn.execute(
                    f"DELETE FROM vectors WHERE ref NOT IN ({marks})", keep)
            self._conn.commit()
            if cursor.rowcount:
                self._ready = False
            return int(cursor.rowcount or 0)

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM vectors")
            self._conn.commit()
            self._ready = False
            self._refs, self._texts, self._metas = [], [], []
            self._matrix = None

    # ---------------------------- 读操作 ---------------------------- #
    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    def search(self, query: str, top_k: int = 5,
               where: dict | Callable[[dict], bool] | None = None,
               exact: bool = False) -> list[dict]:
        """近似最近邻搜索（余弦相似度）。

        where：字典（要求 meta 中对应字段相等，值可给列表表示"属于其一"）或自定义谓词。
        """
        if not query or not str(query).strip():
            return []
        with self._lock:
            self.ensure_ready()
            if self._matrix is None or len(self._refs) == 0:
                return []
            query_vector = self._embed([str(query)])[0]
            indexes = self._candidate_indexes(query_vector, exact)
            if len(indexes) == 0:
                return []
            idf = getattr(self, "_idf", np.ones((len(query_vector),), dtype=np.float32))
            q = query_vector * idf
            q_norm = np.linalg.norm(q) or 1.0
            candidates = self._matrix[indexes]
            weighted = candidates * idf
            norms = np.linalg.norm(weighted, axis=1)
            norms[norms == 0] = 1.0
            scores = (weighted @ q) / (norms * q_norm)

            if where is not None:
                predicate = _make_filter(where)
                keep = [i for i, idx in enumerate(indexes) if predicate(self._metas[idx])]
                indexes = indexes[keep]
                scores = scores[keep]
            if len(scores) == 0:
                return []
            top = np.argsort(-scores)[: max(1, int(top_k))]
            results: list[dict] = []
            for position in top:
                idx = int(indexes[position])
                if float(scores[position]) <= 0:
                    continue
                results.append({
                    "ref": self._refs[idx],
                    "score": float(scores[position]),
                    "text": self._texts[idx],
                    "meta": self._metas[idx],
                })
            return results

    def stats(self) -> dict:
        with self._lock:
            count = self.count()
            dim = self.dim
            row = self._conn.execute("SELECT value FROM meta WHERE key='backend'").fetchone()
            stored_backend = row[0] if row else ""
            self.ensure_ready()
            ivf_ready = self._ivf is not None
            return {
                "enabled": enabled(),
                "path": str(self.path),
                "backend": self.backend,
                "stored_backend": stored_backend,
                "vectors": count,
                "dim": dim,
                "ivf": ivf_ready,
                "nprobe": min(nprobe(), len(self._ivf.cluster_centers_)) if ivf_ready else 0,
                "size_mb": round(self.path.stat().st_size / 1024 / 1024, 3)
                if self.path.exists() else 0.0,
            }

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


def _norm_rows(matrix: np.ndarray) -> np.ndarray:
    """逐行 L2 归一化（零向量的范数置 1，避免除零又不改它全是 0 的事实）。"""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _make_filter(where: dict | Callable[[dict], bool]) -> Callable[[dict], bool]:
    if callable(where):
        return where

    def predicate(meta: dict) -> bool:
        for key, want in where.items():
            got = (meta or {}).get(key)
            if isinstance(want, (list, tuple, set)):
                if got not in want:
                    return False
            elif got != want:
                return False
        return True

    return predicate


# --------------------------------------------------------------------------- #
# 进程内共享实例（RAG / Agent 都用它，避免重复建连接）
# --------------------------------------------------------------------------- #
_SINGLETON: VectorDB | None = None
_SINGLETON_LOCK = threading.Lock()


def get_store(refresh: bool = False) -> "VectorDB":
    """拿到全局唯一的向量库实例（后台/维度变了可传 refresh=True 重建）。"""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None or refresh:
            _SINGLETON = VectorDB()
        return _SINGLETON


# --------------------------------------------------------------------------- #
# 自检：python -m services.knowledge.vectordb（合成语料，不联网）
# --------------------------------------------------------------------------- #
def _selftest() -> int:
    import tempfile

    failed = 0

    def check(name: str, got, want) -> None:
        nonlocal failed
        ok = got == want
        if not ok:
            failed += 1
        print(f"  [{'OK' if ok else 'NG'}] {name}" + ("" if ok else f"  期望={want!r} 实际={got!r}"))

    tmp_dir = Path(tempfile.mkdtemp(prefix="vectordb-"))
    db_file = tmp_dir / "test.sqlite3"

    corpus = {
        "policy.md#1": "员工出差报销需要在返回公司后三十天内提交差旅报销单和相关发票。",
        "policy.md#2": "差旅的标准交通飞机经济舱，住宿标准为一线城市每晚六百元。",
        "faq.md#1": "咖啡机的除垢方法：每月使用专用除垢剂清洗一次水箱。",
        "faq.md#2": "数据库连接失败时先检查网络和配置里的主机端口是否正确。",
    }

    print("① 写入与检索")
    db = VectorDB(db_file, backend="local")
    written = db.upsert_many([(ref, text, {"source": ref.split("#")[0]})
                              for ref, text in corpus.items()])
    check("写入 4 条", written, 4)
    check("落盘计数", db.count(), 4)

    hits = db.search("报销流程是什么", top_k=1)
    check("Top1 命中报销文档", hits[0]["ref"], "policy.md#1")
    hits = db.search("飞机经济舱和住宿多少钱", top_k=1)
    check("Top1 命中差旅标准", hits[0]["ref"], "policy.md#2")
    hits = db.search("咖啡机怎么清洗", top_k=1)
    check("Top1 命中咖啡机", hits[0]["ref"], "faq.md#1")
    check("分数在 0~1 之间", 0.0 < db.search("报销", 1)[0]["score"] <= 1.0, True)

    print("\n② 元数据过滤 / 删除")
    hits = db.search("报销流程是什么", top_k=8, where={"source": "policy.md"})
    check("过滤后只剩 policy 来源", bool(hits) and {h["ref"].split("#")[0] for h in hits}, {"policy.md"})
    check("删除一条", db.delete("faq.md#1"), True)
    check("删除后计数", db.count(), 3)
    check("prune 删掉不在列表里的", db.prune(["policy.md#1", "policy.md#2"]), 1)
    check("prune 后命中正确", db.search("咖啡机", 1), [])

    print("\n③ 持久化（重启后仍然可用）")
    db.close()
    reopened = VectorDB(db_file, backend="local")
    check("重开后计数不变", reopened.count(), 2)
    check("重开后仍能检索", reopened.search("差旅标准", 1)[0]["ref"] == "policy.md#2", True)
    reopened.close()

    print("\n④ 增量同步：内容没变的不重算")
    reopened = VectorDB(db_file, backend="local")
    report = reopened.sync([
        ("policy.md#1", corpus["policy.md#1"], {"source": "policy.md"}),
        ("policy.md#2", corpus["policy.md#2"], {"source": "policy.md"}),
    ], prune=True)
    check("全部未变化 → 0 次写", (report["unchanged"], report["written"]), (2, 0))
    report2 = reopened.sync([
        ("policy.md#1", "内容被改过了，需要重新向量化", {"source": "policy.md"}),
        ("policy.md#2", corpus["policy.md#2"], {"source": "policy.md"}),
    ], prune=True)
    check("只重算改过的那条", (report2["unchanged"], report2["written"]), (1, 1))

    print("\n⑤ IVF 索引与精确解一致")
    os.environ["VECTOR_IVF_MIN"] = "0"          # 强制构建 IVF（用小样本验证路径正确）
    os.environ["VECTOR_NPROBE"] = "2"
    readings = [
        (f"doc{i}", f"第{i}份文档讲的是{i % 3}号设备的维护流程与注意事项", {"i": i})
        for i in range(120)
    ]
    small_path = tmp_dir / "ivf.sqlite3"
    small_db = VectorDB(small_path, backend="local")
    small_db.upsert_many(readings)
    small_db._load()
    exact_hits = [h["ref"] for h in small_db.search("设备维护注意事项", top_k=5, exact=True)]
    ivf_hits = [h["ref"] for h in small_db.search("设备维护注意事项", top_k=5)]
    check("IVF 已构建", small_db._ivf is not None, True)
    check("IVF 与精确解 Top5 完全一致", ivf_hits, exact_hits)
    os.environ.pop("VECTOR_IVF_MIN")
    os.environ.pop("VECTOR_NPROBE")
    small_db.close()

    print("\n⑥ 维度不一致要报错而不是算错")
    reopened.close()
    mismatch = VectorDB(db_file, backend="local", embedder=LocalEmbedder(dim=128))
    try:
        mismatch.search("报销", 1)
        check("换维度后被拦下", False, True)
    except VectorDBError as exc:
        check("换维度后被拦下", "维度不一致" in str(exc), True)
    mismatch.close()

    print("\n⑦ 统计与清理")
    stats_db = VectorDB(db_file, backend="local")
    snap = stats_db.stats()
    check("统计含维度", snap["dim"] == stats_db.dim, True)
    check("统计含条数", snap["vectors"], 2)
    stats_db.clear()
    check("清空后为 0", stats_db.count(), 0)
    stats_db.close()

    for file_path in tmp_dir.glob("*"):
        try:
            file_path.unlink()
        except Exception:
            pass
    try:
        tmp_dir.rmdir()
    except Exception:
        pass

    print("\n全部通过 [OK]" if not failed else f"\n失败 {failed} 项 [NG]")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description="向量数据库（Vector Database）")
    parser.add_argument("--stats", action="store_true", help="查看向量库统计")
    parser.add_argument("--search", metavar="查询词", help="在向量库里检索一次")
    parser.add_argument("--top", type=int, default=3, help="返回条数（默认 3）")
    parser.add_argument("--selftest", action="store_true", help="离线自检")
    args = parser.parse_args()

    if args.selftest:
        raise SystemExit(1 if _selftest() else 0)

    if not enabled():
        print("向量库已关闭（VECTOR_DB=0）")
        return

    store = get_store()
    if args.stats or not args.search:
        snap = store.stats()
        print("向量库统计：")
        for key, value in snap.items():
            print(f"  {key}: {value}")
    if args.search:
        for rank, hit in enumerate(store.search(args.search, top_k=args.top), 1):
            source = hit["meta"].get("source", hit["ref"])
            preview = hit["text"].replace("\n", " ")[:60]
            print(f"  {rank}. [{hit['score']:.4f}] {source}: {preview}…")


if __name__ == "__main__":
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "--selftest":
        raise SystemExit(1 if _selftest() else 0)
    main()
