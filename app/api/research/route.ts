import { NextRequest } from "next/server";
import { getIndex } from "@/lib/pinecone";
import { embedText } from "@/lib/embed";
import { createHash } from "crypto";

export const runtime = "nodejs";
export const maxDuration = 120;

async function tavilySearch(query: string, opts: { depth?: string; maxResults?: number } = {}) {
  const res = await fetch("https://api.tavily.com/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      api_key:      process.env.TAVILY_API_KEY,
      query,
      search_depth: opts.depth ?? "advanced",
      max_results:  opts.maxResults ?? 8,
      include_answer: true,
    }),
  });
  if (!res.ok) throw new Error(`Tavily ${res.status}`);
  return res.json();
}

function extractField(texts: string[], ...keywords: string[]): string {
  for (const text of texts) {
    for (const kw of keywords) {
      const re = new RegExp(`${kw}[:\\s]+([^\\n.]{5,80})`, "i");
      const m  = text.match(re);
      if (m) return m[1].trim();
    }
  }
  return "";
}

export async function POST(req: NextRequest) {
  const { company_name, save_to_db } = await req.json();
  if (!company_name?.trim()) return Response.json({ detail: "Thiếu tên công ty" }, { status: 400 });

  const name = company_name.trim();

  try {
    // ── 1. Tìm thông tin công ty ─────────────────────────────────────────────
    const [infoRes, liRes] = await Promise.all([
      tavilySearch(`${name} Vietnam export company website email phone address`),
      tavilySearch(`${name} Vietnam CEO director sales manager LinkedIn`, { depth: "basic", maxResults: 6 }),
    ]);

    const infoTexts: string[] = [
      infoRes.answer ?? "",
      ...(infoRes.results ?? []).map((r: { content: string }) => r.content),
    ];

    const topSources = (infoRes.results ?? []).slice(0, 3).map((r: { title: string; url: string }) => ({
      title: r.title,
      url:   r.url,
    }));

    const company_info = {
      tavily_answer: (infoRes.answer ?? "").slice(0, 500),
      domain:  extractField(infoTexts, "website", "web", "domain"),
      email:   extractField(infoTexts, "email"),
      phone:   extractField(infoTexts, "phone", "tel", "điện thoại"),
      address: extractField(infoTexts, "address", "địa chỉ", "headquarters"),
      markets: extractMarkets(infoTexts),
      top_sources: topSources,
    };

    // ── 2. Tìm người ─────────────────────────────────────────────────────────
    const people = extractPeople(liRes.results ?? [], name);

    const result = { company: name, company_info, people };

    // ── 3. Lưu vào Pinecone (nếu yêu cầu) ───────────────────────────────────
    if (save_to_db) {
      await saveResearchToPinecone(result);
    }

    return Response.json(result);
  } catch (e) {
    return Response.json({ detail: String(e) }, { status: 500 });
  }
}

function extractMarkets(texts: string[]): string[] {
  const COUNTRIES = ["USA","US","United States","Mỹ","Japan","Nhật","EU","Europe","Germany","France",
    "UK","Australia","Canada","South Korea","Hàn Quốc","China","Singapore","Taiwan"];
  const found = new Set<string>();
  for (const t of texts) {
    for (const c of COUNTRIES) {
      if (t.includes(c)) found.add(c);
    }
  }
  return Array.from(found).slice(0, 8);
}

function extractPeople(results: Array<{ title: string; url: string; content: string }>, company: string) {
  const people: Array<{ name: string; title?: string; linkedin_url?: string; source?: string }> = [];
  const seen = new Set<string>();

  for (const r of results) {
    const isLinkedIn = r.url?.includes("linkedin.com");
    if (!isLinkedIn && !r.content?.toLowerCase().includes(company.toLowerCase().slice(0, 8))) continue;

    const nameRe = /^([A-Z][a-z]+ [A-Z][a-z]+(?:\s[A-Z][a-z]+)?)/m;
    const titleRe = /(?:CEO|Director|Manager|President|Head|VP|Officer|Sales|Marketing|Export|Import)[^\n]{0,60}/i;

    const nameM  = r.title?.match(nameRe) ?? r.content?.match(nameRe);
    const titleM = r.content?.match(titleRe);
    const name   = nameM?.[1];

    if (!name || seen.has(name)) continue;
    seen.add(name);

    people.push({
      name,
      title:        titleM?.[0]?.trim(),
      linkedin_url: isLinkedIn ? r.url : undefined,
      source:       "tavily",
    });
    if (people.length >= 8) break;
  }
  return people;
}

async function saveResearchToPinecone(result: {
  company: string;
  company_info: Record<string, unknown>;
  people: Array<{ name: string; title?: string; linkedin_url?: string }>;
}) {
  try {
    const index   = getIndex();
    const { company, company_info, people } = result;

    const docs: { id: string; text: string; metadata: Record<string, string> }[] = [];

    // Công ty
    const companyText = [
      `Hồ sơ nghiên cứu: ${company}.`,
      company_info.address  ? `Địa chỉ: ${company_info.address}.` : "",
      company_info.email    ? `Email: ${company_info.email}.`     : "",
      company_info.phone    ? `SĐT: ${company_info.phone}.`       : "",
      company_info.domain   ? `Website: ${company_info.domain}.`  : "",
      Array.isArray(company_info.markets) && company_info.markets.length
        ? `Thị trường: ${company_info.markets.join(", ")}.`        : "",
      company_info.tavily_answer ? String(company_info.tavily_answer).slice(0, 300) : "",
    ].filter(Boolean).join(" ");

    docs.push({
      id:   `research__${createHash("md5").update(company).digest("hex")}`,
      text: companyText,
      metadata: { source_file: "tavily_research", sheet_name: "live",
        data_type: "company_profile", shipper_name: company.slice(0,200) },
    });

    // Nhân sự
    for (const p of people) {
      if (!p.name) continue;
      const text = `Người liên hệ: ${p.name}. Chức vụ: ${p.title ?? "—"}. Công ty: ${company}.${p.linkedin_url ? ` LinkedIn: ${p.linkedin_url}.` : ""}`;
      docs.push({
        id:   `research_contact__${createHash("md5").update(company + p.name).digest("hex")}`,
        text,
        metadata: { source_file: "tavily_research", sheet_name: "live",
          data_type: "contact", company_name: company.slice(0,200),
          contact_name: p.name.slice(0,100), position: (p.title ?? "").slice(0,100) },
      });
    }

    const vecs = await Promise.all(docs.map((d) => embedText(d.text)));
    await index.upsert(docs.map((d, i) => ({
      id: d.id, values: vecs[i],
      metadata: { text: d.text.slice(0, 400), ...d.metadata },
    })));
  } catch (e) {
    console.warn("saveResearchToPinecone failed:", e);
  }
}
