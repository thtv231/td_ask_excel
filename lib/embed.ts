const HF_URL =
  "https://api-inference.huggingface.co/models/sentence-transformers/paraphrase-multilingual-mpnet-base-v2";

function l2Normalize(vec: number[]): number[] {
  const norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0));
  return norm === 0 ? vec : vec.map((v) => v / norm);
}

export async function embedText(text: string): Promise<number[]> {
  for (let attempt = 0; attempt < 4; attempt++) {
    const res = await fetch(HF_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.HF_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ inputs: text }),
    });

    const data = await res.json();

    // Model đang load — đợi rồi retry
    if (data?.error?.includes("loading") || data?.estimated_time) {
      const wait = Math.min((data.estimated_time ?? 20) * 1000, 20000);
      await new Promise((r) => setTimeout(r, wait));
      continue;
    }

    if (!res.ok) throw new Error(`HF API error ${res.status}: ${JSON.stringify(data)}`);

    // Kết quả có thể là [[v1,...]] hoặc [v1,...]
    const raw: number[] = Array.isArray(data[0]) ? data[0] : data;
    return l2Normalize(raw);
  }
  throw new Error("HF API không phản hồi sau 4 lần thử");
}

export async function embedBatch(texts: string[]): Promise<number[][]> {
  // HF Inference API free tier: gọi tuần tự để tránh rate limit
  const results: number[][] = [];
  for (const t of texts) {
    results.push(await embedText(t));
  }
  return results;
}
