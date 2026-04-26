import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function GET(_req: NextRequest) {
  const results: Record<string, unknown> = {
    env: {
      PINECONE_API_KEY: process.env.PINECONE_API_KEY ? "set" : "MISSING",
      GROQ_API_KEY:     process.env.GROQ_API_KEY     ? "set" : "MISSING",
      HF_API_KEY:       process.env.HF_API_KEY        ? "set" : "MISSING",
    },
    node: process.version,
    platform: process.platform,
  };

  // Test Pinecone
  try {
    const { getIndex } = await import("@/lib/pinecone");
    const idx = getIndex();
    const stats = await idx.describeIndexStats();
    results.pinecone = { ok: true, total: stats.totalRecordCount };
  } catch (e) {
    results.pinecone = { ok: false, error: String(e) };
  }

  // Test embed (with timeout)
  try {
    const { embedText } = await import("@/lib/embed");
    const vec = await Promise.race([
      embedText("test"),
      new Promise<never>((_, rej) => setTimeout(() => rej(new Error("embed timeout 60s")), 60_000)),
    ]);
    results.embed = { ok: true, dims: (vec as number[]).length, sample: (vec as number[]).slice(0, 3) };
  } catch (e) {
    results.embed = { ok: false, error: String(e) };
  }

  return Response.json(results, { status: 200 });
}
