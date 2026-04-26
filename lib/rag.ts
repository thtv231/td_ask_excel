import { getIndex } from "./pinecone";
import { embedText } from "./embed";

// ── Query type detection ────────────────────────────────────────────────────────
const PEOPLE_TOKENS = new Set(["ceo","director","manager","sales","linkedin","contact"]);
const PEOPLE_PHRASES = ["giám đốc","giam doc","nhân sự","nhan su","liên hệ","lien he",
  "người phụ trách","nguoi phu trach","chức danh","trưởng phòng",
  "truong phong","phó giám đốc","điều hành","chuc danh","phụ trách"];

const KCN_TOKENS = new Set(["kcn","industrial"]);
const KCN_PHRASES = ["khu công nghiệp","khu cong nghiep","industrial park","industrial zone",
  "bình dương","binh duong","đồng nai","dong nai","long an","bắc ninh",
  "bac ninh","hưng yên","hung yen","vĩnh phúc","vinh phuc"];

const MARKET_TOKENS = new Set(["macro","trade"]);
const MARKET_PHRASES = ["thị trường","kim ngạch","thống kê","hs code","tổng kim ngạch","xuất khẩu đi"];

export type QueryType = "people" | "kcn" | "market" | "general";

export function detectQueryType(query: string): QueryType {
  const q = query.toLowerCase();
  const tokens = new Set(q.split(/\s+/));
  if (Array.from(PEOPLE_TOKENS).some((t) => tokens.has(t)) || PEOPLE_PHRASES.some((p) => q.includes(p))) return "people";
  if (Array.from(KCN_TOKENS).some((t) => tokens.has(t))    || KCN_PHRASES.some((p) => q.includes(p)))    return "kcn";
  if (Array.from(MARKET_TOKENS).some((t) => tokens.has(t)) || MARKET_PHRASES.some((p) => q.includes(p))) return "market";
  return "general";
}

// ── RAG retrieval ───────────────────────────────────────────────────────────────
export interface Source {
  type: string;
  score: number;
  file: string;
  preview: string;
  meta: Record<string, string>;
}

type Plan = Array<[string | null, number]>;

export async function buildRagContext(
  query: string
): Promise<{ context: string; sources: Source[] }> {
  const qtype  = detectQueryType(query);
  const vec    = await embedText(query);
  const index  = getIndex();

  let plan: Plan;
  if (qtype === "people") {
    plan = [["contact", 6], [null, 5], ["company_profile", 3]];
  } else if (qtype === "kcn") {
    plan = [["company_profile", 7], ["transaction", 5], [null, 4]];
  } else if (qtype === "market") {
    plan = [["macro_trade", 5], ["trade_summary", 3], [null, 4], ["transaction", 3]];
  } else {
    plan = [[null, 6], ["company_profile", 3], ["contact", 2], ["transaction", 2], ["macro_trade", 2], ["trade_summary", 1]];
  }

  // Parallel query Pinecone
  const queries = plan.map(([dtype, topK]) =>
    index.query({
      vector: vec,
      topK,
      filter: dtype ? { data_type: { $eq: dtype } } : undefined,
      includeMetadata: true,
    }).catch(() => ({ matches: [] }))
  );
  const results = await Promise.all(queries);

  const seen = new Set<string>();
  const sources: Source[] = [];
  const blocks: string[]  = [];
  const maxBlocks = qtype === "people" || qtype === "kcn" ? 18 : 14;

  for (const res of results) {
    for (const match of res.matches ?? []) {
      if (blocks.length >= maxBlocks) break;
      const score = match.score ?? 0;
      if (score < 0.28) continue;

      const meta = (match.metadata ?? {}) as Record<string, string>;
      const text  = meta.text ?? "";
      const uid   = text.slice(0, 60);
      if (seen.has(uid)) continue;
      seen.add(uid);

      const dtype = meta.data_type ?? "unknown";
      blocks.push(`[${dtype.toUpperCase()} | score=${score.toFixed(3)}]\n${text}`);
      sources.push({
        type:    dtype,
        score:   Math.round(score * 10000) / 10000,
        file:    meta.source_file ?? "",
        preview: text.slice(0, 100),
        meta:    Object.fromEntries(
          Object.entries(meta).filter(([k]) => !["text","source_file","sheet_name"].includes(k))
        ),
      });
    }
  }

  return { context: blocks.join("\n\n"), sources };
}
