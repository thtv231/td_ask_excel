"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

type Role = "user" | "assistant";

interface Source {
  type: string;
  score: number;
  file: string;
  preview: string;
  meta: Record<string, string>;
}

interface Message {
  role: Role;
  content: string;
  sources?: Source[];
  streaming?: boolean;
}

interface Stats {
  total: number;
  per_type: Record<string, number>;
  model: string;
}

interface ResearchResult {
  company: string;
  company_info: Record<string, unknown>;
  people: Array<{
    name: string;
    title?: string;
    email?: string;
    linkedin_url?: string;
    source?: string;
  }>;
}

type Tab = "chat" | "upload" | "research";

// ─── Markdown renderer ────────────────────────────────────────────────────────

function renderMarkdown(raw: string): string {
  const lines = raw.split("\n");
  const out: string[] = [];
  let i = 0;

  const inlineFormat = (s: string) =>
    s
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*(.+?)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");

  while (i < lines.length) {
    const line = lines[i];

    // ── Table ──────────────────────────────────────────────────────────────────
    if (line.trim().startsWith("|") && i + 1 < lines.length && /^\|[\s\-|:]+\|/.test(lines[i + 1])) {
      const headers = line
        .trim()
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((c) => `<th class="px-3 py-2 text-left font-semibold text-slate-700 border border-slate-200 bg-slate-50 whitespace-nowrap">${inlineFormat(c.trim())}</th>`)
        .join("");
      i += 2; // skip separator row
      const bodyRows: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i]
          .trim()
          .replace(/^\||\|$/g, "")
          .split("|")
          .map((c) => `<td class="px-3 py-2 text-slate-700 border border-slate-200 align-top">${inlineFormat(c.trim()) || "—"}</td>`)
          .join("");
        bodyRows.push(`<tr class="even:bg-slate-50/60 hover:bg-blue-50/40 transition-colors">${cells}</tr>`);
        i++;
      }
      out.push(
        `<div class="overflow-x-auto my-2 rounded-lg border border-slate-200 shadow-sm">` +
        `<table class="min-w-full text-xs border-collapse">` +
        `<thead><tr>${headers}</tr></thead>` +
        `<tbody>${bodyRows.join("")}</tbody>` +
        `</table></div>`
      );
      continue;
    }

    // ── Headers ────────────────────────────────────────────────────────────────
    if (/^###\s/.test(line)) {
      out.push(`<h3 class="font-semibold text-sm mt-3 mb-1 text-slate-800">${inlineFormat(line.slice(4))}</h3>`);
      i++; continue;
    }
    if (/^##\s/.test(line)) {
      out.push(`<h2 class="font-semibold text-sm mt-4 mb-1.5 text-slate-800 border-b border-slate-100 pb-1">${inlineFormat(line.slice(3))}</h2>`);
      i++; continue;
    }

    // ── Unordered list ─────────────────────────────────────────────────────────
    if (/^[-*]\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s/.test(lines[i])) {
        items.push(`<li class="ml-4 leading-relaxed">${inlineFormat(lines[i].slice(2))}</li>`);
        i++;
      }
      out.push(`<ul class="list-disc my-1 space-y-0.5">${items.join("")}</ul>`);
      continue;
    }

    // ── Ordered list ───────────────────────────────────────────────────────────
    if (/^\d+\.\s/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
        items.push(`<li class="ml-4 leading-relaxed">${inlineFormat(lines[i].replace(/^\d+\.\s/, ""))}</li>`);
        i++;
      }
      out.push(`<ol class="list-decimal my-1 space-y-0.5">${items.join("")}</ol>`);
      continue;
    }

    // ── Blank line ─────────────────────────────────────────────────────────────
    if (!line.trim()) { out.push("<br/>"); i++; continue; }

    // ── Paragraph ─────────────────────────────────────────────────────────────
    out.push(`<p class="leading-relaxed">${inlineFormat(line)}</p>`);
    i++;
  }

  return out.join("\n");
}

// ─── Copy button ──────────────────────────────────────────────────────────────

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return (
    <button
      onClick={copy}
      title="Copy"
      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
    >
      {copied ? (
        <>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={2} className="w-3 h-3 text-green-500">
            <path d="M3 8l3 3 7-7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="text-green-600">Đã copy</span>
        </>
      ) : (
        <>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-3 h-3">
            <rect x="5" y="5" width="9" height="9" rx="1.5" />
            <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
          </svg>
          Copy
        </>
      )}
    </button>
  );
}

// ─── Source badge ──────────────────────────────────────────────────────────────

const DATA_TYPE_COLORS: Record<string, string> = {
  company_profile:   "bg-blue-50 text-blue-700 border-blue-100",
  consignee_profile: "bg-indigo-50 text-indigo-700 border-indigo-100",
  transaction:       "bg-green-50 text-green-700 border-green-100",
  contact:           "bg-purple-50 text-purple-700 border-purple-100",
  macro_trade:       "bg-orange-50 text-orange-700 border-orange-100",
  trade_summary:     "bg-yellow-50 text-yellow-700 border-yellow-100",
  ecommerce_seller:  "bg-pink-50 text-pink-700 border-pink-100",
};

function SourceBadge({ src }: { src: Source }) {
  const color = DATA_TYPE_COLORS[src.type] ?? "bg-slate-50 text-slate-600 border-slate-100";
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${color}`}
      title={src.preview}
    >
      {src.type.replace(/_/g, " ")}
      <span className="opacity-40">{src.score.toFixed(2)}</span>
    </span>
  );
}

// ─── Message bubble ───────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const [showSources, setShowSources] = useState(false);
  const isUser = msg.role === "user";

  return (
    <div className={`group flex gap-2.5 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold flex-shrink-0 mt-0.5 ${
          isUser ? "bg-blue-600 text-white" : "bg-slate-200 text-slate-600"
        }`}
      >
        {isUser ? "U" : "AI"}
      </div>

      <div className={`max-w-[80%] flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`px-3.5 py-2.5 rounded-2xl text-sm ${
            isUser
              ? "bg-blue-600 text-white rounded-tr-sm"
              : "bg-white border border-slate-200 text-slate-800 rounded-tl-sm shadow-sm"
          }`}
        >
          {isUser ? (
            <span className="whitespace-pre-wrap leading-relaxed">{msg.content}</span>
          ) : (
            <div
              className={`prose-chat min-w-0 ${msg.streaming ? "cursor" : ""}`}
              dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
            />
          )}
        </div>

        {!isUser && !msg.streaming && msg.content && (
          <div className="flex items-center gap-2 px-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
            <CopyButton text={msg.content} />
            {msg.sources && msg.sources.length > 0 && (
              <>
                <span className="text-slate-200">|</span>
                <button
                  onClick={() => setShowSources((s) => !s)}
                  className="text-xs text-slate-400 hover:text-slate-600 flex items-center gap-1 transition-colors"
                >
                  <span>{showSources ? "▾" : "▸"}</span>
                  {msg.sources.length} nguồn
                </button>
              </>
            )}
          </div>
        )}
        {showSources && msg.sources && (
          <div className="px-1 flex flex-wrap gap-1 max-w-md">
            {msg.sources.map((src, i) => <SourceBadge key={i} src={src} />)}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Chat panel ───────────────────────────────────────────────────────────────

function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Xin chào! Tôi là trợ lý nghiên cứu B2B thương mại Việt Nam. Tôi có thể giúp bạn tìm:\n\n- **Nhà xuất khẩu** theo ngành (nội thất, dệt may, giày dép, LED, điện tử...)\n- **Thông tin liên hệ** (CEO, Sales Manager, LinkedIn...)\n- **Khách hàng nhập khẩu** tại Mỹ và các thị trường\n- **Thống kê thương mại** VN theo ngành và năm\n\nHãy đặt câu hỏi!",
    },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;

    const userMsg: Message = { role: "user", content: text };
    const aiMsg: Message = { role: "assistant", content: "", streaming: true };

    setMessages((prev) => [...prev, userMsg, aiMsg]);
    setInput("");
    setLoading(true);

    try {
      const history = [...messages, userMsg].map((m) => ({ role: m.role, content: m.content }));

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: history }),
      });

      if (!res.ok) throw new Error(await res.text());

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";
      let sources: Source[] = [];
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";

        for (const part of parts) {
          if (!part.startsWith("data: ")) continue;
          const raw = part.slice(6);
          if (raw === "[DONE]") break;
          try {
            const d = JSON.parse(raw);
            if (d.sources) sources = d.sources;
            else if (d.text) accumulated += d.text;
          } catch {}
        }

        setMessages((prev) => {
          const updated = [...prev];
          updated[updated.length - 1] = { ...updated[updated.length - 1], content: accumulated, sources, streaming: true };
          return updated;
        });
      }

      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          content: accumulated || "(Không có phản hồi)",
          sources,
          streaming: false,
        };
        return updated;
      });
    } catch (err) {
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: "assistant",
          content: `❌ Lỗi: ${err instanceof Error ? err.message : "Không thể kết nối API server"}`,
          streaming: false,
        };
        return updated;
      });
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [input, loading, messages]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };

  const QUICK = [
    "Liệt kê 5 nhà xuất khẩu đồ gỗ nội thất lớn nhất VN",
    "Khách hàng Mỹ nhập đèn LED từ Việt Nam là ai?",
    "Tìm CEO / Sales Manager công ty xuất khẩu dệt may",
    "Các công ty nội thất ở KCN Bình Dương",
  ];

  const sessionCount = messages.filter((m) => m.role === "assistant").length - 1;

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 min-h-0">
        {messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)}

        {loading && messages[messages.length - 1]?.content === "" && (
          <div className="flex gap-2.5">
            <div className="w-7 h-7 rounded-full bg-slate-200 flex items-center justify-center text-xs font-bold text-slate-600">AI</div>
            <div className="px-3.5 py-3 bg-white border border-slate-200 rounded-2xl rounded-tl-sm shadow-sm">
              <span className="flex gap-1 items-center">
                {[0, 1, 2].map((j) => (
                  <span key={j} className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: `${j * 0.15}s` }} />
                ))}
              </span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick prompts — only on first load */}
      {messages.length <= 1 && (
        <div className="px-5 pb-2 grid grid-cols-2 gap-2">
          {QUICK.map((q) => (
            <button
              key={q}
              onClick={() => { setInput(q); inputRef.current?.focus(); }}
              className="text-xs px-3 py-2 rounded-xl border border-slate-200 bg-white hover:border-blue-400 hover:text-blue-600 text-slate-600 transition-colors text-left leading-snug"
            >
              {q}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="px-5 pb-4 pt-2.5 border-t border-slate-100">
        <div className="flex gap-2.5 items-end bg-white border border-slate-200 rounded-xl px-3.5 py-2.5 shadow-sm focus-within:border-blue-400 transition-colors">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Hỏi về công ty, sản phẩm, nhân sự, thị trường... (Enter để gửi)"
            rows={1}
            className="flex-1 resize-none outline-none text-sm leading-relaxed bg-transparent text-slate-800 placeholder:text-slate-400 max-h-28"
            style={{ height: "auto" }}
            onInput={(e) => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = "auto";
              t.style.height = Math.min(t.scrollHeight, 112) + "px";
            }}
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 text-white flex items-center justify-center transition-colors"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="w-3.5 h-3.5">
              <path d="M22 2L11 13M22 2L15 22l-4-9-9-4 20-7z" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        {sessionCount > 0 && (
          <p className="text-center text-xs text-slate-400 mt-1.5">{sessionCount} tin nhắn trong phiên</p>
        )}
      </div>
    </div>
  );
}

// ─── Upload panel ────────────────────────────────────────────────────────────

function UploadPanel() {
  const [files, setFiles] = useState<File[]>([]);
  const [status, setStatus] = useState<string>("");
  const [results, setResults] = useState<Array<{ file: string; status: string; docs: number }>>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const zoneRef = useRef<HTMLDivElement>(null);

  const addFiles = (incoming: FileList | null) => {
    if (!incoming) return;
    const xlsx = Array.from(incoming).filter((f) => f.name.endsWith(".xlsx") || f.name.endsWith(".xls"));
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      return [...prev, ...xlsx.filter((f) => !names.has(f.name))];
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    zoneRef.current?.classList.remove("drag-over");
    addFiles(e.dataTransfer.files);
  };

  const embed = async () => {
    if (!files.length || busy) return;
    setBusy(true);
    setStatus("Đang nhúng dữ liệu vào ChromaDB...");
    setResults([]);

    const form = new FormData();
    files.forEach((f) => form.append("files", f));

    try {
      const res = await fetch("/api/embed", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Lỗi không rõ");
      setResults(data.results || []);
      const total = (data.results as typeof results).reduce((s, r) => s + r.docs, 0);
      setStatus(`✅ Hoàn tất! Đã embed ${total} docs. Collection: ${data.total_collection.toLocaleString()} vectors.`);
      setFiles([]);
    } catch (e) {
      setStatus(`❌ Lỗi: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-5 space-y-4 max-w-xl">
      <div>
        <h2 className="text-base font-semibold text-slate-800">Upload dữ liệu Excel</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Thêm file .xlsx/.xls — dữ liệu được embed vào ChromaDB, chatbot tìm kiếm được ngay.
        </p>
      </div>

      {/* Drop zone */}
      <div
        ref={zoneRef}
        onDragOver={(e) => { e.preventDefault(); zoneRef.current?.classList.add("drag-over"); }}
        onDragLeave={() => zoneRef.current?.classList.remove("drag-over")}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className="border-2 border-dashed border-slate-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/50 transition-all"
      >
        <div className="text-3xl mb-2">📂</div>
        <p className="text-sm font-medium text-slate-700">Kéo thả hoặc click để chọn file</p>
        <p className="text-xs text-slate-400 mt-1">.xlsx, .xls — có thể chọn nhiều file cùng lúc</p>
        <input ref={inputRef} type="file" multiple accept=".xlsx,.xls" className="hidden" onChange={(e) => addFiles(e.target.files)} />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-3.5 py-2 border-b border-slate-100 flex items-center justify-between">
            <span className="text-xs font-medium text-slate-700">{files.length} file đã chọn</span>
            <button onClick={() => setFiles([])} className="text-xs text-red-500 hover:text-red-700">Xóa tất cả</button>
          </div>
          <ul className="divide-y divide-slate-100 max-h-44 overflow-y-auto">
            {files.map((f) => (
              <li key={f.name} className="flex items-center justify-between px-3.5 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-green-500 text-sm">📄</span>
                  <span className="text-xs text-slate-700 truncate">{f.name}</span>
                  <span className="text-xs text-slate-400 flex-shrink-0">{(f.size / 1024).toFixed(0)} KB</span>
                </div>
                <button onClick={() => setFiles((p) => p.filter((x) => x.name !== f.name))} className="text-slate-300 hover:text-red-400 ml-2 text-xs leading-none">✕</button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Embed button */}
      <button
        onClick={embed}
        disabled={!files.length || busy}
        className="w-full py-2.5 rounded-xl bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 text-white font-medium text-sm transition-colors flex items-center justify-center gap-2"
      >
        {busy
          ? <><span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Đang xử lý...</>
          : "🔗 Embed vào ChromaDB"}
      </button>

      {/* Status */}
      {status && (
        <div className={`text-xs px-3.5 py-2.5 rounded-xl ${
          status.startsWith("✅") ? "bg-green-50 text-green-700 border border-green-100" :
          status.startsWith("❌") ? "bg-red-50 text-red-700 border border-red-100" :
          "bg-blue-50 text-blue-700 border border-blue-100"
        }`}>
          {status}
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
          <div className="px-3.5 py-2 border-b border-slate-100 text-xs font-medium text-slate-700">Kết quả embed</div>
          <ul className="divide-y divide-slate-100">
            {results.map((r) => (
              <li key={r.file} className="flex items-center justify-between px-3.5 py-2">
                <span className="text-xs text-slate-700 truncate max-w-xs">{r.file}</span>
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                  r.status === "ok" ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-500"
                }`}>
                  {r.status === "ok" ? `✓ ${r.docs} docs` : "bỏ qua"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ─── Research panel ───────────────────────────────────────────────────────────

function ResearchPanel() {
  const [company, setCompany] = useState("");
  const [saveToDb, setSaveToDb] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const run = async () => {
    if (!company.trim() || loading) return;
    setLoading(true); setError(""); setResult(null); setSaved(false);
    try {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ company_name: company.trim(), save_to_db: saveToDb }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Lỗi không rõ");
      setResult(data);
      if (saveToDb) setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const INFO_LABELS: Record<string, string> = {
    domain: "Domain", mst: "Mã số thuế", founded: "Năm thành lập",
    representative: "Người đại diện", address: "Địa chỉ",
    phone: "Điện thoại", email: "Email", tavily_answer: "Tóm tắt",
  };

  return (
    <div className="p-5 space-y-4 max-w-2xl">
      <div>
        <h2 className="text-base font-semibold text-slate-800">Nghiên cứu sâu công ty</h2>
        <p className="text-xs text-slate-500 mt-0.5">
          Dùng Tavily thu thập thông tin thực tế: website, nhân sự LinkedIn, thị trường xuất khẩu.
        </p>
      </div>

      <div className="flex gap-2.5">
        <input
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Dán tên công ty từ chat vào đây, vd: VINA SOLAR TECHNOLOGY"
          className="flex-1 px-3.5 py-2.5 border border-slate-200 rounded-xl text-sm outline-none focus:border-blue-400 bg-white"
        />
        <button
          onClick={run}
          disabled={loading || !company.trim()}
          className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 text-white rounded-xl text-sm font-medium transition-colors flex items-center gap-1.5"
        >
          {loading ? <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : "🔍"}
          {loading ? "Đang nghiên cứu..." : "Bắt đầu"}
        </button>
      </div>

      <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
        <input type="checkbox" checked={saveToDb} onChange={(e) => setSaveToDb(e.target.checked)} className="w-3.5 h-3.5 accent-blue-600" />
        Tự động lưu kết quả vào ChromaDB (chatbot tìm thấy ngay sau đó)
      </label>

      {loading && (
        <div className="flex items-center gap-2.5 px-3.5 py-3 bg-blue-50 border border-blue-100 rounded-xl">
          <span className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin flex-shrink-0" />
          <span className="text-sm text-blue-700">Đang chạy pipeline Tavily (thường mất 30–60 giây)...</span>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-xl px-3.5 py-3 text-sm text-red-700">❌ {error}</div>
      )}

      {result && (
        <div className="space-y-3">
          {saved && (
            <div className="bg-green-50 border border-green-100 rounded-xl px-3.5 py-2.5 text-xs text-green-700">
              ✅ Đã lưu vào ChromaDB — chatbot có thể tìm thấy ngay.
            </div>
          )}

          {/* Company info */}
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <div className="px-4 py-2.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
              <span>🏢</span>
              <span className="font-semibold text-slate-800 text-sm">{result.company}</span>
              <div className="ml-auto"><CopyButton text={result.company} /></div>
            </div>
            <div className="divide-y divide-slate-100">
              {Object.entries(result.company_info)
                .filter(([k, v]) => INFO_LABELS[k] && v)
                .map(([k, v]) => (
                  <div key={k} className="flex gap-3 px-4 py-2">
                    <span className="text-xs text-slate-400 w-28 flex-shrink-0 pt-0.5">{INFO_LABELS[k]}</span>
                    <span className="text-xs text-slate-700 flex-1">{String(v)}</span>
                  </div>
                ))}
              {(result.company_info.markets as string[] | undefined)?.length ? (
                <div className="flex gap-3 px-4 py-2">
                  <span className="text-xs text-slate-400 w-28 flex-shrink-0 pt-0.5">Thị trường</span>
                  <div className="flex flex-wrap gap-1">
                    {(result.company_info.markets as string[]).map((m) => (
                      <span key={m} className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full text-xs">{m}</span>
                    ))}
                  </div>
                </div>
              ) : null}
              {(result.company_info.top_sources as Array<{ title: string; url: string }> | undefined)?.length ? (
                <div className="flex gap-3 px-4 py-2">
                  <span className="text-xs text-slate-400 w-28 flex-shrink-0 pt-0.5">Nguồn</span>
                  <div className="space-y-0.5">
                    {(result.company_info.top_sources as Array<{ title: string; url: string }>).map((s, i) => (
                      <a key={i} href={s.url} target="_blank" rel="noreferrer"
                        className="block text-xs text-blue-600 hover:underline truncate max-w-sm">{s.title}</a>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {/* People table */}
          {result.people.length > 0 && (
            <div className="bg-white border border-slate-200 rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
                <span>👥</span>
                <span className="font-semibold text-slate-800 text-xs">Nhân sự ({result.people.length} người)</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-slate-100 text-slate-500 bg-slate-50">
                      {["Tên", "Chức danh", "Email", "LinkedIn", "Nguồn"].map((h) => (
                        <th key={h} className="text-left px-4 py-2 font-medium border border-slate-100">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {result.people.map((p, i) => (
                      <tr key={i} className="hover:bg-slate-50 even:bg-slate-50/40">
                        <td className="px-4 py-2 font-medium text-slate-800 border border-slate-100">{p.name}</td>
                        <td className="px-4 py-2 text-slate-600 border border-slate-100">{p.title || "—"}</td>
                        <td className="px-4 py-2 border border-slate-100">
                          {p.email ? <a href={`mailto:${p.email}`} className="text-blue-600 hover:underline">{p.email}</a> : "—"}
                        </td>
                        <td className="px-4 py-2 border border-slate-100">
                          {p.linkedin_url ? <a href={p.linkedin_url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">Profile ↗</a> : "—"}
                        </td>
                        <td className="px-4 py-2 text-slate-400 border border-slate-100">{p.source || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Stats sidebar ────────────────────────────────────────────────────────────

function StatsSidebar({ active, onTabChange }: { active: Tab; onTabChange: (t: Tab) => void }) {
  const NAV: { id: Tab; icon: string; label: string }[] = [
    { id: "chat",     icon: "💬", label: "Chat" },
    { id: "upload",   icon: "📂", label: "Upload Excel" },
    { id: "research", icon: "🔍", label: "Nghiên cứu sâu" },
  ];
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetch("/api/stats").then((r) => r.json()).then(setStats).catch(() => {});
  }, []);

  const TYPE_ICONS: Record<string, string> = {
    company_profile:   "🏭",
    consignee_profile: "🏪",
    transaction:       "🚢",
    contact:           "👤",
    macro_trade:       "📊",
    trade_summary:     "📋",
    ecommerce_seller:  "🛒",
  };

  const TYPE_LABELS: Record<string, string> = {
    company_profile:   "Công ty",
    consignee_profile: "Người nhập",
    transaction:       "Giao dịch",
    contact:           "Nhân sự",
    macro_trade:       "Vĩ mô",
    trade_summary:     "Tóm tắt",
    ecommerce_seller:  "TMĐT",
  };

  return (
    <aside className="w-44 flex-shrink-0 bg-white border-r border-slate-200 flex flex-col">
      {/* Logo */}
      <div className="px-4 py-3.5 border-b border-slate-100">
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 bg-blue-600 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0">S</div>
          <div>
            <p className="text-sm font-semibold text-slate-800 leading-tight">Striker14</p>
            <p className="text-xs text-slate-400 leading-tight">B2B Vietnam</p>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="p-2.5 space-y-0.5 border-b border-slate-100">
        {NAV.map((n) => (
          <button
            key={n.id}
            onClick={() => onTabChange(n.id)}
            className={`w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-sm font-medium transition-colors ${
              active === n.id ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"
            }`}
          >
            <span className="text-base leading-none">{n.icon}</span>
            <span>{n.label}</span>
          </button>
        ))}
      </nav>

      {/* Database stats */}
      <div className="p-3 flex-1 overflow-y-auto">
        <p className="text-xs font-medium text-slate-400 mb-2 uppercase tracking-wide">Cơ sở dữ liệu</p>
        {stats ? (
          <div className="space-y-1.5">
            <div className="bg-blue-50 rounded-lg px-2.5 py-2 mb-3">
              <p className="text-xs text-blue-500">Tổng vectors</p>
              <p className="text-xl font-bold text-blue-700 leading-tight">{stats.total.toLocaleString()}</p>
            </div>
            {Object.entries(stats.per_type)
              .filter(([, v]) => v > 0)
              .sort(([, a], [, b]) => b - a)
              .map(([type, count]) => (
                <div key={type} className="flex items-center justify-between gap-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-xs leading-none">{TYPE_ICONS[type] ?? "•"}</span>
                    <span className="text-xs text-slate-500 truncate">{TYPE_LABELS[type] ?? type}</span>
                  </div>
                  <span className="text-xs font-semibold text-slate-700 flex-shrink-0">{count.toLocaleString()}</span>
                </div>
              ))}
          </div>
        ) : (
          <div className="space-y-2 animate-pulse">
            {[55, 75, 45, 65, 50, 60, 40].map((w, i) => (
              <div key={i} className="h-2.5 bg-slate-100 rounded" style={{ width: `${w}%` }} />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [tab, setTab] = useState<Tab>("chat");

  return (
    <div className="h-screen flex overflow-hidden">
      <StatsSidebar active={tab} onTabChange={setTab} />
      <main className="flex-1 overflow-hidden flex flex-col bg-slate-50">
        <div className={`flex-1 overflow-hidden flex-col min-h-0 ${tab === "chat" ? "flex" : "hidden"}`}>
          <ChatPanel />
        </div>
        <div className={`flex-1 overflow-y-auto ${tab === "upload" ? "block" : "hidden"}`}>
          <UploadPanel />
        </div>
        <div className={`flex-1 overflow-y-auto ${tab === "research" ? "block" : "hidden"}`}>
          <ResearchPanel />
        </div>
      </main>
    </div>
  );
}
