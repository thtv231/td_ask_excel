import { getIndex } from "@/lib/pinecone";

export const runtime = "nodejs";

const DATA_TYPES = [
  "transaction","company_profile","consignee_profile",
  "contact","macro_trade","trade_summary","ecommerce_seller",
];

export async function GET() {
  try {
    const index = getIndex();
    const stats = await index.describeIndexStats();
    const total = stats.totalRecordCount ?? 0;

    // Ước tính phân phối dựa trên ChromaDB gốc (tỷ lệ cố định, hiển thị thông tin)
    const knownDist: Record<string, number> = {
      transaction:       36825,
      company_profile:   11024,
      consignee_profile:  5486,
      contact:            4439,
      macro_trade:          520,
      trade_summary:        884,
      ecommerce_seller:     141,
    };
    const knownTotal = Object.values(knownDist).reduce((a, b) => a + b, 0);

    const per_type: Record<string, number> = {};
    for (const dt of DATA_TYPES) {
      per_type[dt] = total > 0
        ? Math.round((knownDist[dt] / knownTotal) * total)
        : 0;
    }

    return Response.json({ total, per_type, model: "paraphrase-multilingual-mpnet-base-v2" });
  } catch (e) {
    return Response.json({ error: String(e) }, { status: 503 });
  }
}
