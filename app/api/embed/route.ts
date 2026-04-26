import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const maxDuration = 120;

export async function POST(req: NextRequest) {
  const formData = await req.formData();

  const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND}/embed`, { method: "POST", body: formData });
  } catch (e) {
    return Response.json({ detail: `Không thể kết nối backend: ${e}` }, { status: 503 });
  }

  const text = await upstream.text();
  try {
    const data = JSON.parse(text);
    return Response.json(data, { status: upstream.status });
  } catch {
    return Response.json(
      { detail: `Backend trả lỗi (${upstream.status}): ${text.slice(0, 200)}` },
      { status: 502 }
    );
  }
}
