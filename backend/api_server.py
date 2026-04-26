#!/usr/bin/env python3
"""
api_server.py — FastAPI backend cho Trade Intelligence Chatbot.

Endpoints:
  GET  /stats          → thống kê ChromaDB collection
  POST /chat           → RAG chat với Groq (SSE streaming)
  POST /embed          → nhúng file Excel mới vào ChromaDB
  POST /research       → nghiên cứu sâu công ty qua Tavily

Chạy:
  pip install fastapi uvicorn groq python-multipart python-dotenv
  python api_server.py
"""

import contextlib
import io
import json
import logging
import os
import sys
import tempfile

# Fix Windows console encoding — demo_tavily prints Vietnamese via print()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from typing import Any, Optional

import chromadb
import pandas as pd
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

load_dotenv()

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Nhập các hàm xử lý từ embed_db.py
from embed_db import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    process_sheet,
    get_sheet_names,
    read_sheet,
)

# ─── Config ───────────────────────────────────────────────────────────────────
CHROMA_DIR     = ROOT / "chroma_db"
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
USE_E5_PREFIX  = EMBEDDING_MODEL.startswith("intfloat/multilingual-e5")
GROQ_MODEL     = "llama-3.3-70b-versatile"
BATCH_UPSERT   = 100
PORT           = int(os.getenv("PORT", 8000))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(stream=sys.stdout)],
)
log = logging.getLogger("api")

# ─── Groq client ──────────────────────────────────────────────────────────────
try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None
    log.warning("Groq library not installed — `pip install groq`")

# ─── ChromaDB + model (lazy init) ─────────────────────────────────────────────
_db_client: Optional[chromadb.PersistentClient] = None
_embed_model: Optional[SentenceTransformer] = None


def get_db() -> chromadb.Collection:
    global _db_client
    if _db_client is None:
        _db_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # get_or_create — an toàn khi collection chưa tồn tại (Railway lần đầu)
    return _db_client.get_or_create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def get_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        log.info(f"Loading embedding model: {EMBEDDING_MODEL}")
        _embed_model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    return _embed_model


def encode_query(text: str) -> list:
    t = ("query: " + text) if USE_E5_PREFIX else text
    return get_model().encode([t], normalize_embeddings=True).tolist()


def encode_passage(text: str) -> list:
    t = ("passage: " + text) if USE_E5_PREFIX else text
    return get_model().encode([t], normalize_embeddings=True).tolist()


# ─── RAG helpers ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Bạn là trợ lý nghiên cứu B2B chuyên về thương mại xuất nhập khẩu Việt Nam, hỗ trợ tìm kiếm đối tác, khách hàng và nhân sự cho đội sales.

## Dữ liệu bạn có quyền truy cập
- **Hồ sơ công ty xuất khẩu** (company_profile): tên, địa chỉ, điện thoại, email, sản phẩm, giá trị xuất khẩu, thị trường
- **Hồ sơ người nhập khẩu** (consignee_profile): tên buyer nước ngoài, quốc gia, số lô hàng, giá trị nhập
- **Giao dịch xuất khẩu** (transaction): vận đơn cụ thể, hàng hóa, cảng đến, ngày vận chuyển, địa chỉ shipper
- **Nhân sự / liên hệ** (contact): tên người, chức danh, email, điện thoại, LinkedIn URL — trích từ Panjiva và LinkedIn
- **Thống kê vĩ mô** (macro_trade): kim ngạch theo HS code, quốc gia, năm 2017–2021
- **Tóm tắt thương mại** (trade_summary): tổng hợp theo mã HS 6 chữ số
- **Người bán TMĐT** (ecommerce_seller): seller trên các sàn thương mại điện tử VN

## Quy tắc trả lời

**Ngôn ngữ:** Trả lời TIẾNG VIỆT trừ khi user hỏi tiếng Anh.

**Độ trung thực:** CHỈ dùng thông tin trong ngữ cảnh được cung cấp. Không bịa đặt tên công ty, số điện thoại, email.

**Khi liệt kê công ty:** Luôn kèm địa chỉ, email, điện thoại nếu có. Nếu thiếu thì ghi "—".

**Khi hỏi về nhân sự (CEO, Giám đốc, Sales Manager, Director...):**
- Ưu tiên dữ liệu loại `contact` — chứa tên người, chức danh, LinkedIn URL
- Hiển thị: Tên | Chức danh | Email | Điện thoại | LinkedIn (nếu có)
- Nếu không có trong ngữ cảnh → nói rõ và gợi ý dùng tab "Nghiên cứu sâu" để tìm qua LinkedIn/Tavily

**Khi hỏi về khu công nghiệp (KCN):**
- Địa chỉ công ty được lưu trong trường địa chỉ của `company_profile` và `transaction`
- Trích tất cả công ty có địa chỉ khớp tỉnh/KCN được hỏi
- Lưu ý: kết quả RAG chỉ trả về các công ty gần nhất theo ngữ nghĩa, không phải toàn bộ — nên nói rõ "Đây là một số công ty tìm được, có thể chưa đầy đủ"

**Khi user hỏi công ty Việt Nam:** Lọc kết quả theo địa chỉ có "Vietnam" hoặc "Việt Nam". Bỏ qua công ty Trung Quốc, Hàn Quốc... trừ khi user hỏi rõ về nước đó.

**Khi hỏi "xuất khẩu đi đâu" / "thị trường":** Dùng dữ liệu transaction (cảng đến, quốc gia nhận) và macro_trade.

**Khi hỏi "khách hàng là ai":** Dùng consignee_profile — đây là danh sách người nhập khẩu (buyer) từ VN.

**Format:** Dùng bảng markdown khi có nhiều công ty/người. Dùng bullet list khi liệt kê thuộc tính. Tránh trả lời quá ngắn khi user hỏi "liệt kê" hoặc "tất cả".

**Giới hạn dữ liệu:** Nếu câu hỏi cần dữ liệu thời gian thực hoặc thông tin công ty chưa có trong DB → gợi ý dùng tab **"Nghiên cứu sâu"** (Tavily search) để tra cứu trực tiếp."""


_PEOPLE_TOKENS = {"ceo","director","manager","sales","linkedin","contact"}
_PEOPLE_PHRASES = [
    "giám đốc","giam doc","nhân sự","nhan su","liên hệ","lien he",
    "người phụ trách","nguoi phu trach","chức danh","trưởng phòng",
    "truong phong","phó giám đốc","điều hành","chuc danh","phụ trách",
]
_KCN_TOKENS  = {"kcn","industrial"}
_KCN_PHRASES = [
    "khu công nghiệp","khu cong nghiep","industrial park","industrial zone",
    "bình dương","binh duong","đồng nai","dong nai","long an","bắc ninh",
    "bac ninh","hưng yên","hung yen","vĩnh phúc","vinh phuc",
]
_MARKET_TOKENS  = {"macro","trade"}
_MARKET_PHRASES = [
    "thị trường","kim ngạch","thống kê","hs code","tổng kim ngạch","xuất khẩu đi",
]


def _detect_query_type(query: str) -> str:
    q = query.lower()
    tokens = set(q.split())
    if (_PEOPLE_TOKENS & tokens) or any(p in q for p in _PEOPLE_PHRASES):
        return "people"
    if (_KCN_TOKENS & tokens) or any(p in q for p in _KCN_PHRASES):
        return "kcn"
    if (_MARKET_TOKENS & tokens) or any(p in q for p in _MARKET_PHRASES):
        return "market"
    return "general"


def build_rag_context(query: str) -> tuple[str, list[dict]]:
    """Truy vấn ChromaDB, trả về (context_string, sources_list)."""
    vec = encode_query(query)
    col = get_db()

    qtype = _detect_query_type(query)

    if qtype == "people":
        plan = [
            ("contact",          6),
            (None,               5),
            ("company_profile",  3),
        ]
    elif qtype == "kcn":
        plan = [
            ("company_profile",  7),
            ("transaction",      5),
            (None,               4),
        ]
    elif qtype == "market":
        plan = [
            ("macro_trade",      5),
            ("trade_summary",    3),
            (None,               4),
            ("transaction",      3),
        ]
    else:
        # general
        plan = [
            (None,               6),
            ("company_profile",  3),
            ("contact",          2),
            ("transaction",      2),
            ("macro_trade",      2),
            ("trade_summary",    1),
        ]

    seen_ids: set[str] = set()
    sources: list[dict] = []
    context_blocks: list[str] = []

    for dtype, n in plan:
        try:
            kwargs: dict[str, Any] = dict(
                query_embeddings=vec,
                n_results=n,
                include=["documents", "metadatas", "distances"],
            )
            if dtype:
                kwargs["where"] = {"data_type": dtype}
            res = col.query(**kwargs)
        except Exception:
            continue

        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            score = round(1 - dist, 4)
            if score < 0.28:
                continue
            uid = doc[:60]
            if uid in seen_ids:
                continue
            seen_ids.add(uid)

            dt_label = meta.get("data_type", "unknown").upper()
            context_blocks.append(f"[{dt_label} | score={score}]\n{doc}")
            sources.append({
                "type":    meta.get("data_type", ""),
                "score":   score,
                "file":    meta.get("source_file", ""),
                "preview": doc[:100],
                "meta":    {k: v for k, v in meta.items() if k not in ("source_file", "sheet_name")},
            })

    max_blocks = 18 if qtype in ("people", "kcn") else 14
    context = "\n\n".join(context_blocks[:max_blocks])
    return context, sources[:max_blocks]


# ─── FastAPI app ──────────────────────────────────────────────────────────────

app = FastAPI(title="Trade Intelligence API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _warmup():
    """Pre-load embedding model so first request doesn't timeout."""
    import threading
    def _load():
        try:
            log.info("Warming up embedding model...")
            get_model()
            log.info("Embedding model ready.")
        except Exception as e:
            log.warning(f"Warmup failed: {e}")
    threading.Thread(target=_load, daemon=True).start()


# ── GET /stats ─────────────────────────────────────────────────────────────────
DATA_TYPES = [
    "transaction", "company_profile", "consignee_profile",
    "contact", "macro_trade", "trade_summary", "ecommerce_seller",
]


@app.get("/stats")
def stats():
    try:
        col = get_db()
        total = col.count()
        per_type: dict[str, int] = {}
        for dt in DATA_TYPES:
            try:
                r = col.get(where={"data_type": dt}, include=[], limit=200_000)
                per_type[dt] = len(r["ids"])
            except Exception:
                per_type[dt] = 0
        return {"total": total, "per_type": per_type, "model": EMBEDDING_MODEL}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── POST /chat ─────────────────────────────────────────────────────────────────

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


@app.post("/chat")
async def chat(req: ChatRequest):
    if not groq_client:
        raise HTTPException(status_code=503, detail="Groq client chưa được cấu hình. Set GROQ_API_KEY trong .env")

    msgs = req.messages
    last_user = next((m.content for m in reversed(msgs) if m.role == "user"), "")

    # RAG retrieval
    context, sources = build_rag_context(last_user)

    # Build Groq messages
    groq_msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        groq_msgs.append({
            "role": "system",
            "content": f"=== NGỮ CẢNH TỪ CƠ SỞ DỮ LIỆU ===\n{context}\n=====================================",
        })
    groq_msgs += [{"role": m.role, "content": m.content} for m in msgs]

    async def generate():
        # Gửi sources trước (metadata không stream)
        yield f"data: {json.dumps({'sources': sources}, ensure_ascii=False)}\n\n"

        stream = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=groq_msgs,
            stream=True,
            max_tokens=2048,
            temperature=0.3,
        )
        for chunk in stream:
            text = chunk.choices[0].delta.content or ""
            if text:
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── POST /embed ────────────────────────────────────────────────────────────────

@app.post("/embed")
async def embed(files: list[UploadFile] = File(...)):
    """Nhận file Excel, xử lý và upsert vào ChromaDB."""
    col = get_db()
    model = get_model()

    results: list[dict] = []

    with tempfile.TemporaryDirectory() as tmp:
        for upload in files:
            tmp_path = Path(tmp) / upload.filename
            tmp_path.write_bytes(await upload.read())

            file_docs: list[dict] = []
            sheets = get_sheet_names(tmp_path)

            for sheet in sheets:
                df = read_sheet(tmp_path, sheet)
                if df is None:
                    continue
                docs = process_sheet(df, upload.filename, sheet)
                file_docs.extend(docs)

            if not file_docs:
                results.append({"file": upload.filename, "status": "skip", "docs": 0})
                continue

            # Embed và upsert
            deduped = {d["id"]: d for d in file_docs}
            unique = list(deduped.values())

            for i in range(0, len(unique), BATCH_UPSERT):
                chunk = unique[i : i + BATCH_UPSERT]
                # Tính embedding
                texts = [d["text"] for d in chunk]
                if USE_E5_PREFIX:
                    texts = ["passage: " + t for t in texts]
                vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()

                col.upsert(
                    ids       =[d["id"]       for d in chunk],
                    embeddings=vecs,
                    documents =[d["text"]     for d in chunk],
                    metadatas =[d["metadata"] for d in chunk],
                )

            results.append({"file": upload.filename, "status": "ok", "docs": len(unique)})
            log.info(f"Embedded {len(unique)} docs from {upload.filename}")

    return {"results": results, "total_collection": col.count()}


# ── POST /research ─────────────────────────────────────────────────────────────

class ResearchRequest(BaseModel):
    company_name: str
    save_to_db: bool = False


@app.post("/research")
async def research(req: ResearchRequest):
    """Chạy demo_tavily.run_pipeline trong subprocess riêng để tránh encoding conflict với uvicorn."""
    import subprocess, json as _json
    script = (
        "from demo_tavily import run_pipeline\n"
        "import sys, json, io, contextlib\n"
        "_buf = io.StringIO()\n"
        "with contextlib.redirect_stdout(_buf):\n"
        "    result = run_pipeline(sys.argv[1])\n"
        "sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\\n')\n"
        "sys.stdout.flush()\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script, req.company_name],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            timeout=120,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            err = proc.stderr.strip() or "no output"
            log.error("Subprocess stderr:\n%s", err)
            raise RuntimeError(err)
        result = _json.loads(proc.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Tavily pipeline timeout (120s)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi Tavily pipeline: {e}")

    if req.save_to_db and result:
        _embed_research_result(result)

    return result


def _embed_research_result(result: dict):
    """Lưu kết quả research vào ChromaDB."""
    try:
        col  = get_db()
        model = get_model()
        company = result.get("company", "")
        info    = result.get("company_info", {})
        people  = result.get("people", [])

        docs = []

        # Embed thông tin công ty
        parts = [f"Hồ sơ nghiên cứu: {company}."]
        for k, v in info.items():
            if v and k not in ("top_sources", "tavily_answer", "markets"):
                parts.append(f"{k}: {v}.")
        if info.get("markets"):
            parts.append(f"Thị trường: {', '.join(info['markets'])}.")
        if info.get("tavily_answer"):
            parts.append(f"Tóm tắt: {info['tavily_answer']}")

        docs.append({
            "id": f"research__{company.lower().replace(' ', '_')}",
            "text": " ".join(parts),
            "metadata": {
                "source_file": "tavily_research",
                "sheet_name":  "live",
                "data_type":   "company_profile",
                "shipper_name": company[:200],
                "email":        (info.get("email") or "")[:100],
                "website":      (info.get("domain") or "")[:200],
                "total_shipments": "",
                "total_value_usd": "",
                "product_category": "",
            },
        })

        # Embed nhân sự
        for p in people:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            text = f"Người liên hệ: {name}. Chức vụ: {p.get('title','—')}. Công ty: {company}."
            if p.get("email"):
                text += f" Email: {p['email']}."
            if p.get("linkedin_url"):
                text += f" LinkedIn: {p['linkedin_url']}."
            docs.append({
                "id": f"research_contact__{company.lower().replace(' ', '_')}__{name.lower().replace(' ', '_')}",
                "text": text,
                "metadata": {
                    "source_file":  "tavily_research",
                    "sheet_name":   "live",
                    "data_type":    "contact",
                    "company_name": company[:200],
                    "contact_name": name[:100],
                    "position":     (p.get("title") or "")[:100],
                    "email":        (p.get("email") or "")[:100],
                },
            })

        if docs:
            texts = [d["text"] for d in docs]
            if USE_E5_PREFIX:
                texts = ["passage: " + t for t in texts]
            vecs = model.encode(texts, normalize_embeddings=True).tolist()
            col.upsert(
                ids       =[d["id"]       for d in docs],
                embeddings=vecs,
                documents =[d["text"]     for d in docs],
                metadatas =[d["metadata"] for d in docs],
            )
            log.info(f"Saved {len(docs)} research docs for {company}")
    except Exception as e:
        log.warning(f"Could not save research to DB: {e}")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info(f"Starting API server on port {PORT}")
    log.info(f"ChromaDB: {CHROMA_DIR}")
    log.info(f"Model   : {EMBEDDING_MODEL}")
    log.info(f"Groq    : {'OK' if groq_client else 'NOT CONFIGURED'}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
