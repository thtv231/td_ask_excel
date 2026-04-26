import { NextRequest } from "next/server";
import { getIndex } from "@/lib/pinecone";
import { embedBatch } from "@/lib/embed";
import { processExcelBuffer } from "@/lib/excel";

export const runtime = "nodejs";
export const maxDuration = 120;

const BATCH = 50;

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const files    = formData.getAll("files") as File[];
    if (!files.length) return Response.json({ detail: "Không có file" }, { status: 400 });

    const index   = getIndex();
    const results: { file: string; status: string; docs: number }[] = [];

    for (const file of files) {
      try {
        const buffer = await file.arrayBuffer();
        const docs   = processExcelBuffer(buffer, file.name);

        if (!docs.length) {
          results.push({ file: file.name, status: "skip", docs: 0 });
          continue;
        }

        // Deduplicate by id
        const unique = Object.values(Object.fromEntries(docs.map((d) => [d.id, d])));

        for (let i = 0; i < unique.length; i += BATCH) {
          const chunk  = unique.slice(i, i + BATCH);
          const texts  = chunk.map((d) => d.text);
          const vecs   = await embedBatch(texts);

          await index.upsert(
            chunk.map((d, j) => ({
              id:       d.id,
              values:   vecs[j],
              metadata: { text: d.text.slice(0, 400), ...d.metadata },
            }))
          );
        }

        results.push({ file: file.name, status: "ok", docs: unique.length });
      } catch (e) {
        results.push({ file: file.name, status: `error: ${e}`, docs: 0 });
      }
    }

    const stats = await index.describeIndexStats();
    return Response.json({ results, total_collection: stats.totalRecordCount ?? 0 });
  } catch (e) {
    return Response.json({ detail: String(e) }, { status: 500 });
  }
}
