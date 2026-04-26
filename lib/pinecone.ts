import { Pinecone } from "@pinecone-database/pinecone";

let _pc: Pinecone | null = null;

export function getPinecone() {
  if (!_pc) _pc = new Pinecone({ apiKey: process.env.PINECONE_API_KEY! });
  return _pc;
}

export const INDEX_NAME = "trade-data";

export function getIndex() {
  return getPinecone().index(INDEX_NAME);
}
