"""RAG 知识库模块 —— 为 LangChain Agent 提供「检索增强」能力。

使用方式
--------
把 `.md / .markdown / .txt / .pdf` 文档放进项目根目录的 `knowledge/` 文件夹
（可放子目录），Agent（agent.py）启动时即自动挂载 `search_knowledge` 检索工具。
PDF 会逐页抽取文字，命中片段会标注页码；无文字层的扫描件会给出提示（需先 OCR）。

检索引擎（可多路并存，构成“智能检索 = 多路召回 + RRF 融合”）：
- **keyword（恒可用）**：自实现的 TF-IDF 余弦检索器（继承 langchain BaseRetriever），
  零第三方依赖、零网络请求，放入文档即可离线演示；中文按「字 + 双字词」索引。
- **vector（语义，可选）**：配置 EMBEDDING_*（任意 OpenAI 兼容的 embedding 服务）
  后自动加入语义向量引擎，与 keyword 一起做双路召回融合；初始化失败自动降级为
  keyword-only，不影响使用。DeepSeek 官方不提供 embedding，可配硅基流动等渠道：
      EMBEDDING_PROVIDER=openai
      EMBEDDING_API_KEY=sk-xxx       # 留空则复用 OPENAI_API_KEY
      EMBEDDING_BASE_URL=...         # OpenAI 官方可留空
      EMBEDDING_MODEL=...            # 如 text-embedding-3-small / BAAI/bge-m3
- 将来配置好后无需改代码：检索自动从“关键词单路”升级为“关键词+语义”双路混合。

对外检索模式：
- **smart（默认，智能）**：对所有可用引擎（keyword [+ vector]）做多路召回，用
  RRF（Reciprocal Rank Fusion）融合重排后输出 Top-K；只存在一路时自动退化为该路。
- **keyword / vector**：只走指定的一路（vector 未构建时会提示并退回 keyword）。
- 深度搜索（Deep Research 式、拆子问题多轮检索后综合回答）由 agent.py / web 提供，
  内部逐个子查询都调用这里的 smart 检索。

命令行自测（不调用 LLM，不消耗 API）::

    python rag.py "咖啡机怎么除垢"
    python rag.py --list
    python rag.py --list --backend smart
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import Field

try:                                    # 包式运行：python -m services.rag
    from services import vectordb
except ModuleNotFoundError:             # 直接运行：python services/rag.py
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services import vectordb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --------------------------------------------------------------------------- #
# 配置（环境变量可覆盖默认值）
# --------------------------------------------------------------------------- #
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}
MAX_FILE_SIZE = 20 * 1024 * 1024         # 单个文档上限 20MB

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

CHUNK_SIZE = _env_int("RAG_CHUNK_SIZE", 500)          # 分块目标长度（字符）
CHUNK_OVERLAP = _env_int("RAG_CHUNK_OVERLAP", 60)     # 相邻块重叠（字符）
TOP_K = _env_int("RAG_TOP_K", 3)                      # 每次检索最终返回片段数
PER_LIST = _env_int("RAG_PER_LIST", 8)                # 每路引擎先召回的数量（多路融合前的池）
RRF_K = _env_float("RAG_RRF_K", 60.0)                 # RRF 融合常数：score=Σ 1/(k+rank)

# 分词：连续中文（含少量兼容字）或连续 [a-z0-9_] 串
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9_]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


# --------------------------------------------------------------------------- #
# 中文友好的轻量分词：拉丁词整体保留；中文段拆成「单字 + 相邻双字」
# --------------------------------------------------------------------------- #
def tokenize(text: str) -> list[str]:
    """把文本切成可匹配的 token 列表（重复保留，用于词频统计）。"""
    tokens: list[str] = []
    for segment in _TOKEN_RE.findall(text.lower()):
        if _CJK_RE.match(segment):
            tokens.extend(segment)  # 单字
            if len(segment) >= 2:
                tokens.extend(segment[i:i + 2] for i in range(len(segment) - 1))
        else:
            tokens.append(segment)
    return tokens


# --------------------------------------------------------------------------- #
# PDF 文本抽取（按页返回，懒加载 pypdf 依赖）
# --------------------------------------------------------------------------- #
def _extract_pdf_pages(path: Path) -> list[tuple[int, str]]:
    """逐页抽取 PDF 文本，返回 ``[(页号, 该页文本), ...]``（自动跳过无文字页）。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("缺少 PDF 解析依赖 pypdf，请先执行：pip install pypdf") from exc

    reader = PdfReader(str(path))
    pages: list[tuple[int, str]] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if text:
            pages.append((number, text))
    return pages


# --------------------------------------------------------------------------- #
# 文档分块
# --------------------------------------------------------------------------- #
_BREAK_CHARS = "。！？；!?;\n，,、.… "


def _split_long(text: str, size: int, overlap: int) -> list[str]:
    """把超长文本切成带重叠的窗口，切点优先落在句末标点 / 空白处。"""
    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            window = text[start:end]
            cut = -1
            for i in range(len(window) - 1, -1, -1):
                if window[i] in _BREAK_CHARS:
                    cut = i
                    break
            if cut > 0:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_text(text: str, size: int = None, overlap: int = None) -> list[str]:
    """按空行分段，优先保持段落完整；单段过长时按窗口切分。"""
    size = size or CHUNK_SIZE
    overlap = CHUNK_OVERLAP if overlap is None else overlap
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        # Markdown 标题处强制断块：让“### 题目 + 参考 SQL”等条目自包含成块，
        # 避免检索召回“只含题目、不含答案/SQL”的残块
        if re.match(r"^#{1,6}\s", paragraph) and buffer:
            chunks.append(buffer)
            buffer = ""
        pieces = [paragraph] if len(paragraph) <= size else _split_long(paragraph, size, overlap)
        for piece in pieces:
            if not buffer:
                buffer = piece
            elif len(buffer) + 1 + len(piece) <= size:
                buffer = f"{buffer}\n{piece}"
            else:
                chunks.append(buffer)
                buffer = piece
    if buffer:
        chunks.append(buffer)
    return chunks


# --------------------------------------------------------------------------- #
# 检索引擎 1：零依赖 TF-IDF 余弦检索（keyword，恒可用）
# --------------------------------------------------------------------------- #
class _KeywordRetriever(BaseRetriever):
    """基于 TF-IDF 向量 + 余弦相似度的轻量检索器（BaseRetriever 子类）。

    语料规模较小时足够准确，且不依赖任何第三方向量库 / embedding 服务。
    ``rank()`` 会返回全部候选的余弦分数，供上层做多路融合（RRF）。
    """

    documents: list[Document] = Field(default_factory=list)
    k: int = Field(default=TOP_K)
    doc_counts: list[dict[str, int]] = Field(default_factory=list, exclude=True)
    doc_norms: list[float] = Field(default_factory=list, exclude=True)
    idf_map: dict[str, float] = Field(default_factory=dict, exclude=True)
    n_docs: int = Field(default=0, exclude=True)

    def __init__(self, documents: list[Document], k: int = TOP_K) -> None:
        super().__init__(documents=documents, k=k)
        n_docs = len(documents)

        df: dict[str, int] = {}
        for doc in documents:
            for tok in set(tokenize(doc.page_content)):
                df[tok] = df.get(tok, 0) + 1
        # 平滑 IDF：log((N+1)/(df+1)) + 1，避免除零并保证未见词也有权重
        self.idf_map = {tok: math.log((n_docs + 1) / (freq + 1)) + 1.0 for tok, freq in df.items()}

        self.n_docs = n_docs
        self.doc_counts = []
        self.doc_norms = []
        for doc in documents:
            counts: dict[str, int] = {}
            for tok in tokenize(doc.page_content):
                counts[tok] = counts.get(tok, 0) + 1
            norm = math.sqrt(sum((freq * self._idf(tok)) ** 2 for tok, freq in counts.items()))
            self.doc_counts.append(counts)
            self.doc_norms.append(norm)

    def _idf(self, tok: str) -> float:
        return self.idf_map.get(tok, math.log(self.n_docs + 1) + 1.0)

    def rank(self, query: str) -> list[tuple[float, int]]:
        """对 query 算全部片段余弦相似度，按分数从高到低返回 ``[(sim, doc_idx)]``。

        只保留有实际词命中的片段（sim > 0）。
        """
        query = (query or "").strip()
        if not query:
            return []

        q_counts: dict[str, int] = {}
        for tok in tokenize(query):
            q_counts[tok] = q_counts.get(tok, 0) + 1
        q_vec = {tok: freq * self._idf(tok) for tok, freq in q_counts.items()}
        q_norm = math.sqrt(sum(w * w for w in q_vec.values())) or 1.0

        scored: list[tuple[float, int]] = []
        for idx, counts in enumerate(self.doc_counts):
            total = 0.0
            for tok, w_query in q_vec.items():
                freq = counts.get(tok)
                if freq:
                    total += w_query * freq * self._idf(tok)  # 等价于查询向量 · 文档向量
            norm = self.doc_norms[idx]
            if norm > 0 and total > 0:
                scored.append((total / (q_norm * norm), idx))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        ranked = self.rank(query)
        hits: list[Document] = []
        for sim, idx in ranked[: self.k]:
            src = self.documents[idx]
            hits.append(Document(
                page_content=src.page_content,
                metadata={**src.metadata, "score": round(max(0.0, sim), 4)},
            ))
        return hits


# --------------------------------------------------------------------------- #
# 检索引擎 2：语义向量检索（vector，需 OpenAI 兼容 embedding 服务，可选）
# --------------------------------------------------------------------------- #
def embedding_config() -> dict | None:
    """返回语义检索配置；未显式开启时返回 None（保持离线关键词检索）。

    规则：
    - EMBEDDING_PROVIDER=openai / openai-compatible：使用 EMBEDDING_API_KEY
      （留空则复用 OPENAI_API_KEY）与 EMBEDDING_BASE_URL / EMBEDDING_MODEL。
    - EMBEDDING_API_KEY 单独填了也会自动启用语义检索。
    - 显式设为 offline（或不满足上面条件）=> 只用零依赖关键词检索。
    """
    provider = (os.getenv("EMBEDDING_PROVIDER") or "").strip().lower()
    if provider == "offline":
        return None
    if provider not in ("openai", "openai-compatible", ""):
        return None

    api_key = (os.getenv("EMBEDDING_API_KEY") or "").strip()
    if not api_key and provider == "openai":
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None

    base_url = (os.getenv("EMBEDDING_BASE_URL") or "").strip()
    model = (os.getenv("EMBEDDING_MODEL") or "").strip() or "text-embedding-3-small"
    config: dict = {"api_key": api_key, "model": model}
    if base_url:
        config["base_url"] = base_url
    return config


class _VectorIndex:
    """极简的内存语义向量索引：embedding 一次全量算好，查询时余弦相似度取 Top。

    不依赖 chroma / faiss，用纯 Python 列表运算即可覆盖小型知识库。
    """

    def __init__(self, embeddings, texts: list[str]) -> None:
        self._embeddings = embeddings
        self._texts = texts
        vectors = embeddings.embed_documents(texts) if texts else []
        self._vecs = [[float(x) for x in vec] for vec in vectors]
        self._norms = [math.sqrt(sum(v * v for v in vec)) for vec in self._vecs]

    def search(self, query: str, k: int) -> list[tuple[float, int]]:
        qv = self._embeddings.embed_query(query)
        q_norm = math.sqrt(sum(x * x for x in qv)) or 1.0
        scored: list[tuple[float, int]] = []
        for idx, vec in enumerate(self._vecs):
            dot = sum(a * b for a, b in zip(qv, vec))
            sim = dot / (q_norm * self._norms[idx]) if self._norms[idx] else 0.0
            if sim > 0:
                scored.append((sim, idx))
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[:k]


def _rag_chunk_ref(doc: Document) -> str:
    """分块在向量库里的稳定主键："相对路径#分块序号[@p页码]"。

    稳定很重要：知识库没改时 ref 不变 → 向量库判定"内容相同" → 不重复向量化。
    """
    meta = doc.metadata or {}
    ref = f"{meta.get('source', 'unknown')}#{meta.get('chunk_index', 0)}"
    page = meta.get("page")
    return f"{ref}@p{page}" if page is not None else ref


def _build_vector_index(documents: list[Document], config: dict) -> _VectorIndex:
    """用 OpenAI 兼容的 embedding 服务给全部分块向量化，构建内存索引。"""
    from langchain_openai import OpenAIEmbeddings

    embeddings = OpenAIEmbeddings(
        model=config["model"],
        api_key=config["api_key"],
        base_url=config.get("base_url"),
        timeout=float(os.getenv("REQUEST_TIMEOUT", "60")),
    )
    texts = [doc.page_content for doc in documents]
    return _VectorIndex(embeddings, texts)


def engine_display_name(config: dict | None, built: bool = False) -> str:
    """语义向量引擎的展示名（配置了但还没构建/构建失败时也能说明）。"""
    if not config:
        return ""
    host = ""
    base = config.get("base_url")
    if base:
        host = base.rstrip("/").rsplit("/", 1)[-1] or base
    host = f"@{host}" if host else ""
    state = "" if built else "（未启用）"
    return f"vector[{config['model']}{host}]{state}"


# --------------------------------------------------------------------------- #
# 知识库服务（线程安全、懒构建索引）
# --------------------------------------------------------------------------- #
class RagService:
    """在 knowledge/ 目录之上提供 加载 -> 分块 -> 多路索引 -> 智能检索 的封装。

    智能检索（mode="smart"）= 对全部可用引擎（keyword [+ vector]）各自召回
    ``per_list`` 个候选，再用 RRF（Reciprocal Rank Fusion）融合重排取 Top-K；
    当前只有一路引擎可用时自动退化为该路，接口不变。
    """

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory else KNOWLEDGE_DIR
        self._lock = threading.RLock()
        self._documents: list[Document] = []      # 规范分块（fusion 统一用其下标）
        self._kw: _KeywordRetriever | None = None  # keyword 引擎（恒可用）
        self._vector: _VectorIndex | None = None   # vector 引擎（可选）
        self._vector_config: dict | None = None
        self._built_files = 0
        self._chunk_count = 0
        self._error: str | None = None
        # 持久化向量库（services/vectordb.py）：重启不丢索引，增量更新；不可用时自动降级
        self._vdb = None
        self._vdb_map: dict[str, int] = {}    # 向量库 ref → self._documents 下标
        self._vdb_error: str | None = None

    # ------------------------- 文件枚举 ------------------------- #
    def _iter_source_files(self):
        if not self.directory.is_dir():
            return
        for path in sorted(self.directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.directory)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if path.stat().st_size > MAX_FILE_SIZE:
                continue
            yield path

    def files(self) -> list[str]:
        return [str(p.relative_to(self.directory)).replace("\\", "/") for p in self._iter_source_files()]

    # ------------------------- 索引构建 ------------------------- #
    def _load_documents(self) -> tuple[list[Document], int, list[str]]:
        """读取知识库：文本类整篇分块；PDF 逐页抽取再分块。

        返回 (documents, built_files, warnings)，单个文件失败不会中断整个索引。
        """
        documents: list[Document] = []
        built_files = 0
        warnings: list[str] = []
        for path in self._iter_source_files():
            relative = str(path.relative_to(self.directory)).replace("\\", "/")
            try:
                if path.suffix.lower() == ".pdf":
                    page_texts = _extract_pdf_pages(path)
                    if not page_texts:
                        warnings.append(f"{relative}：未提取到文字（可能是扫描件，请先转成可检索的文本 PDF）")
                    pieces: list[tuple[str, int | None]] = [
                        (piece, number)
                        for number, page_text in page_texts
                        for piece in chunk_text(page_text)
                    ]
                else:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    pieces = [(piece, None) for piece in chunk_text(text)]

                if pieces:
                    built_files += 1
                # 更新时间：让模型（和用户）能判断这条资料是否过期（上下文工程的"来源标注"要求）
                try:
                    updated = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
                except Exception:
                    updated = ""
                for index, (piece, page_number) in enumerate(pieces, start=1):
                    metadata: dict = {"source": relative, "chunk_index": index}
                    if page_number is not None:
                        metadata["page"] = page_number
                    if updated:
                        metadata["updated"] = updated
                    documents.append(Document(page_content=piece, metadata=metadata))
            except Exception as exc:
                warnings.append(f"{relative}：加载失败（{exc}）")
        return documents, built_files, warnings

    def rebuild(self) -> None:
        """重新扫描 knowledge/ 并重建全部引擎索引（新文档 / 修改文档后调用）。"""
        with self._lock:
            documents, built_files, warnings = self._load_documents()
            self._documents = documents
            self._kw = None
            self._vector = None
            self._vector_config = embedding_config()
            self._built_files = built_files
            self._chunk_count = len(documents)
            self._error = None

            # 持久化向量库：把分块同步进 VectorDB
            self._vdb, self._vdb_map, self._vdb_error = None, {}, None
            if documents:
                self._kw = _KeywordRetriever(documents=documents, k=TOP_K)
                if self._vector_config:
                    try:
                        self._vector = _build_vector_index(documents, self._vector_config)
                    except Exception as exc:  # embedding 服务不可用时自动降级，不中断
                        warnings.append(f"语义向量引擎初始化失败，已降级为关键词单路检索：{exc}")
                self._sync_vectordb(documents, warnings)

            self._error = "；".join(warnings) if warnings else None

    def _sync_vectordb(self, documents: list[Document], warnings: list[str]) -> None:
        """将分块同步进持久化向量库（增量：内容未变的分块不重新向量化）。

        任何失败都只是降级（回落到关键词 / 内存 embedding 路径），不影响知识库可用。
        """
        try:
            if not vectordb.enabled():
                return
            store = vectordb.get_store()
            items: list[tuple[str, str, dict]] = []
            mapping: dict[str, int] = {}
            for index, doc in enumerate(documents):
                ref = _rag_chunk_ref(doc)
                mapping[ref] = index
                items.append((ref, doc.page_content or "", dict(doc.metadata or {})))
            store.sync(items, prune=True)      # prune：删掉已从 knowledge/ 移除的旧向量
            self._vdb = store
            self._vdb_map = mapping
        except Exception as exc:
            self._vdb, self._vdb_map = None, {}
            self._vdb_error = str(exc)
            warnings.append(f"向量数据库同步失败，已降级为关键词/Embedding 检索：{exc}")

    def _ensure(self) -> None:
        if self._kw is None and self.files():
            self.rebuild()

    # ------------------------- 引擎状态 ------------------------- #
    def engines(self) -> dict:
        """当前已构建/可用的引擎详情（不触发 embedding 网络调用）。"""
        planned_vector = bool(embedding_config())
        info = {
            "keyword": self._kw is not None,
            "vector": self._vector is not None,
            "vector_planned": planned_vector,
            "vector_config": self._vector_config,
            "mode": "smart",
            "vectordb_enabled": bool(self._vdb is not None),
            "vectordb_error": self._vdb_error,
        }
        if self._vdb is not None:
            try:
                stats = self._vdb.stats()
                info["vectordb"] = {
                    "path": stats.get("path"),
                    "backend": stats.get("backend"),
                    "vectors": stats.get("vectors"),
                    "dim": stats.get("dim"),
                    "ivf": stats.get("ivf"),
                    "size_mb": stats.get("size_mb"),
                }
            except Exception:
                pass
        return info

    def summary(self) -> dict:
        """知识库状态（不会触发 embedding 网络调用）。"""
        file_list = self.files()
        return {
            "enabled": bool(file_list),
            "file_count": len(file_list),
            "files": file_list,
            "chunk_count": self._chunk_count if self._kw is not None else None,
            "built": self._kw is not None,
            "backend": self.backend_label(),
            "engines": self.engines(),
            "error": self._error,
        }

    def backend_label(self) -> str:
        """给界面/命令行展示用的引擎名称。"""
        kw_on = self._kw is not None
        # 持久化向量库同样是"语义那一路"（和不落盘的 _VectorIndex 二选一）
        vec_on = self._vector is not None or bool(self._vdb is not None and self._vdb_map)
        if vec_on and kw_on:
            return "智能（关键词+语义 双路融合）"
        if vec_on:
            return "vector（语义检索）"
        if kw_on:
            return "keyword（零依赖 TF-IDF）"
        if self.files():
            return "keyword（零依赖 TF-IDF）"
        return "（知识库为空）"

    # ------------------------- 多路融合检索 ------------------------- #
    def _rank_fused(
        self,
        query: str,
        k: int | None,
        per_list: int | None,
        mode: str,
    ) -> tuple[list[tuple[float, int, list[str]]], str]:
        """多路召回 + RRF 融合。返回 ([(融合分, doc_idx, 命中引擎)], 引擎说明)。

        只支持 smart / hybrid / keyword / vector 四种模式。
        """
        mode = (mode or "smart").lower()
        k = k or TOP_K
        per_list = max(per_list or PER_LIST, 1)

        kw_ranked: list[tuple[float, int]] = []
        vec_ranked: list[tuple[float, int]] = []
        engine_hits: dict[int, list[str]] = {}

        if self._kw is not None and mode in ("smart", "hybrid", "keyword"):
            kw_ranked = self._kw.rank(query)[:per_list]

        vector_allowed = mode in ("smart", "hybrid", "vector")
        vec_error: str | None = None
        if vector_allowed:
            if self._vdb is not None and self._vdb_map:
                try:                            # 持久化向量库优先（重启不丢、增量更新）
                    for hit in self._vdb.search(query, per_list):
                        index = self._vdb_map.get(hit["ref"])
                        if index is not None:
                            vec_ranked.append((float(hit["score"]), index))
                except Exception as exc:
                    vec_error = f"向量数据库检索失败：{exc}"
            elif self._vector is None:
                if mode == "vector":
                    vec_error = "语义向量引擎未构建（请确认已配置可用的 EMBEDDING_* 或 VECTOR_DB=1）"
            else:
                try:
                    vec_ranked = self._vector.search(query, per_list)
                except Exception as exc:
                    vec_error = f"语义向量检索失败：{exc}"

        if vec_error and not kw_ranked:
            raise RuntimeError(vec_error)

        for sim, idx in kw_ranked:
            engine_hits.setdefault(idx, []).append("keyword")
        for sim, idx in vec_ranked:
            engine_hits.setdefault(idx, []).append("vector")

        if mode == "vector":
            ranked = [(sim, idx) for sim, idx in vec_ranked]
            engines_label = "语义向量" + (f"（{vec_error}）" if vec_error and not kw_ranked else "")
        elif mode == "keyword" or not vec_ranked:
            ranked = kw_ranked
            engines_label = "关键词(TF-IDF)"
        else:
            # RRF 融合：对每路排名的位置求 1/(k+rank)，跨路累加后重排
            rrf: dict[int, float] = {}
            for position, (_sim, idx) in enumerate(kw_ranked, start=1):
                rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + position)
            for position, (_sim, idx) in enumerate(vec_ranked, start=1):
                rrf[idx] = rrf.get(idx, 0.0) + 1.0 / (RRF_K + position)
            fused_order = sorted(rrf.items(), key=lambda item: item[1], reverse=True)
            ranked = [(rrf[idx], idx) for idx, _ in fused_order]
            engines_label = "关键词+语义（RRF 融合）"

        # 对命中的片段给出可读的相关度：取所命中引擎归一化相似度的均值
        kw_score = {idx: max(0.0, sim) for sim, idx in kw_ranked}
        vec_score = {idx: max(0.0, (sim + 1.0) / 2.0) for sim, idx in vec_ranked}
        fused: list[tuple[float, int, list[str]]] = []
        for _raw, idx in ranked[:k]:
            parts = [kw_score.get(idx), vec_score.get(idx)]
            values = [v for v in parts if v is not None]
            score = sum(values) / len(values) if values else 0.0
            engines = engine_hits.get(idx, [])
            fused.append((score, idx, engines))

        if vec_error and kw_ranked:
            engines_label += f"（语义通道暂不可用：{vec_error}）"
        return fused, engines_label

    def retrieve(
        self,
        query: str,
        k: int | None = None,
        *,
        mode: str = "smart",
        per_list: int | None = None,
    ) -> tuple[list[Document], str]:
        """智能检索：多路召回 + RRF 融合，返回 Top-K 片段（含融合相关度）。

        返回 (documents, engines_label)。每个片段的 metadata 里带：
        ``source`` 来源文件、``chunk_index`` 段落号、``page``（PDF 页码，如有）、
        ``score`` 0~1 相关度、``engines`` 命中的引擎列表。
        当知识库为空 / 检索失败时返回 ([], engines_label) 并在 label 里说明。
        """
        query = (query or "").strip()
        self._ensure()
        if not query:
            return [], "空查询"
        if not self._kw:
            return [], "知识库为空（请先把 .md/.txt/.pdf 文档放入 knowledge/ 目录）"

        try:
            fused, engines_label = self._rank_fused(query, k, per_list, mode)
        except Exception as exc:
            return [], f"检索失败：{exc}"

        docs: list[Document] = []
        for score, idx, engines in fused:
            src = self._documents[idx]
            docs.append(Document(
                page_content=src.page_content,
                metadata={**src.metadata, "score": round(score, 4), "engines": engines},
            ))
        if not docs:
            engines_label = f"{engines_label}（无命中片段）"
        return docs, engines_label

    def search(self, query: str, k: int = None, mode: str = "smart") -> str:
        """检索知识库并把命中的片段拼成给 Agent 的文本（带来源标注）。兼容旧接口。

        mode 取值：smart（默认智能融合）/ keyword / vector。
        """
        docs, engines_label = self.retrieve(query, k, mode=mode)
        if not docs:
            if "知识库为空" in engines_label or "检索失败" in engines_label:
                return f"（{engines_label}。请如实告知用户，不要编造知识库中的信息。）"
            if "空查询" in engines_label:
                return "（检索内容不能为空。）"
            return "（知识库中没有检索到与问题相关的内容，请如实告知用户，不要编造。）"

        parts = [f"（检索引擎：{engines_label}）"]
        for index, doc in enumerate(docs, start=1):
            source = doc.metadata.get("source", "未知文档")
            chunk_index = doc.metadata.get("chunk_index", "?")
            page = doc.metadata.get("page")
            score = doc.metadata.get("score")
            head = f"片段{index}（来源：{source} · 第{chunk_index}段"
            if page is not None:
                head += f" · PDF 第{page}页"
            if score is not None:
                head += f" · 相关度{score:.3f}"
            parts.append(f"{head}）：\n{doc.page_content.strip()}")
        return "\n\n---\n\n".join(parts)


# --------------------------------------------------------------------------- #
# 命令行自测入口（不消耗 LLM）
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 知识库检索自测（不调用 LLM）")
    parser.add_argument("query", nargs="*", help="要检索的问题；省略则只打印知识库状态")
    parser.add_argument("--list", action="store_true", help="列出知识库文档")
    parser.add_argument("--rebuild", action="store_true", help="强制重建索引（读取最新文档）")
    parser.add_argument(
        "--backend", choices=["smart", "keyword", "vector"], default="smart",
        help="检索模式：smart=多路融合（默认）；keyword=仅关键词；vector=仅语义向量",
    )
    args = parser.parse_args()

    service = RagService()
    if args.rebuild:
        service.rebuild()

    info = service.summary()
    print(f"知识库目录：{service.directory}")
    print(f"文档数：{info['file_count']}   后端：{info['backend']}   已建索引：{info['built']}")
    engines = info["engines"]
    if engines.get("vector_planned") and not engines.get("vector"):
        print("提示：检测到 EMBEDDING_* 配置但语义向量引擎未构建（可能初始化失败），当前为关键词单路。")
    elif not engines.get("vector_planned"):
        print("提示：未配置 EMBEDDING_*，当前为关键词单路；配好后自动升级为关键词+语义双路混合。")
    if info["error"]:
        print(f"注意：{info['error']}")
    if args.list:
        for name in info["files"]:
            print(f"  - {name}")
    query = " ".join(args.query).strip()
    if query:
        print("\n" + "=" * 20 + f" 检索({args.backend})：{query} " + "=" * 20)
        print(service.search(query, mode=args.backend))


if __name__ == "__main__":
    main()
