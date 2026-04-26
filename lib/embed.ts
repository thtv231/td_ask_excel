import { pipeline, env } from "@huggingface/transformers";
import { tmpdir } from "os";
import { join } from "path";

env.cacheDir = join(tmpdir(), "hf_cache");
env.allowLocalModels = false;

type FeaturePipeline = (
  text: string | string[],
  opts: { pooling: string; normalize: boolean }
) => Promise<{ data: Float32Array; dims: number[] }>;

let _pipe: FeaturePipeline | null = null;

async function getPipe(): Promise<FeaturePipeline> {
  if (!_pipe) {
    _pipe = (await pipeline(
      "feature-extraction",
      "Xenova/paraphrase-multilingual-mpnet-base-v2"
    )) as unknown as FeaturePipeline;
  }
  return _pipe;
}

export async function embedText(text: string): Promise<number[]> {
  const pipe = await getPipe();
  const out = await pipe(text, { pooling: "mean", normalize: true });
  return Array.from(out.data);
}

export async function embedBatch(texts: string[]): Promise<number[][]> {
  const results: number[][] = [];
  for (const t of texts) {
    results.push(await embedText(t));
  }
  return results;
}
