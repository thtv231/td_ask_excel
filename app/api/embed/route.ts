import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  const formData = await req.formData();

  const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
  const upstream = await fetch(`${BACKEND}/embed`, {
    method: "POST",
    body: formData,
  });

  const data = await upstream.json();
  return Response.json(data, { status: upstream.status });
}
