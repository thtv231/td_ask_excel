export const runtime = "nodejs";

export async function GET() {
  try {
    const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";
    const upstream = await fetch(`${BACKEND}/stats`);
    const data = await upstream.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "API server offline" }, { status: 503 });
  }
}
