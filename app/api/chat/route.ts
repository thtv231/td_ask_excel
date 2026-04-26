import { NextRequest } from "next/server";
import { buildRagContext } from "@/lib/rag";
import Groq from "groq-sdk";

export const runtime = "nodejs";
export const maxDuration = 90;

const SYSTEM_PROMPT = `Bạn là trợ lý nghiên cứu B2B chuyên về thương mại xuất nhập khẩu Việt Nam, hỗ trợ tìm kiếm đối tác, khách hàng và nhân sự cho đội sales.

## Dữ liệu bạn có quyền truy cập
- **Hồ sơ công ty xuất khẩu** (company_profile): tên, địa chỉ, điện thoại, email, sản phẩm, giá trị xuất khẩu, thị trường
- **Hồ sơ người nhập khẩu** (consignee_profile): tên buyer nước ngoài, quốc gia, số lô hàng, giá trị nhập
- **Giao dịch xuất khẩu** (transaction): vận đơn cụ thể, hàng hóa, cảng đến, ngày vận chuyển
- **Nhân sự / liên hệ** (contact): tên người, chức danh, email, điện thoại, LinkedIn URL
- **Thống kê vĩ mô** (macro_trade): kim ngạch theo HS code, quốc gia, năm 2017–2021
- **Tóm tắt thương mại** (trade_summary): tổng hợp theo mã HS 6 chữ số
- **Người bán TMĐT** (ecommerce_seller): seller trên các sàn thương mại điện tử VN

## Quy tắc trả lời
**Ngôn ngữ:** Trả lời TIẾNG VIỆT trừ khi user hỏi tiếng Anh.
**Độ trung thực:** CHỈ dùng thông tin trong ngữ cảnh được cung cấp. Không bịa đặt tên công ty, số điện thoại, email.
**Khi liệt kê công ty:** Luôn kèm địa chỉ, email, điện thoại nếu có. Nếu thiếu thì ghi "—".
**Khi hỏi về nhân sự:** Ưu tiên dữ liệu loại contact. Hiển thị: Tên | Chức danh | Email | LinkedIn.
**Khi hỏi về khu công nghiệp:** Trích tất cả công ty có địa chỉ khớp. Nói rõ "kết quả có thể chưa đầy đủ".
**Khi user hỏi công ty Việt Nam:** Lọc kết quả theo địa chỉ có "Vietnam" hoặc "Việt Nam".
**Format:** Dùng bảng markdown khi có nhiều công ty/người. Tránh trả lời quá ngắn khi user hỏi "liệt kê".
**Giới hạn:** Nếu không có dữ liệu → gợi ý dùng tab "Nghiên cứu sâu".`;

const groq = new Groq({ apiKey: process.env.GROQ_API_KEY });

export async function POST(req: NextRequest) {
  try {
    const { messages } = await req.json();
    const lastUser = [...messages].reverse().find((m: { role: string }) => m.role === "user")?.content ?? "";

    // RAG — nếu embed/pinecone lỗi thì vẫn trả lời không có context
    let context = "";
    let sources: unknown[] = [];
    try {
      const rag = await buildRagContext(lastUser);
      context = rag.context;
      sources  = rag.sources;
    } catch (ragErr) {
      console.error("RAG error (non-fatal):", ragErr);
    }

    const groqMsgs: { role: string; content: string }[] = [
      { role: "system", content: SYSTEM_PROMPT },
    ];
    if (context) {
      groqMsgs.push({
        role: "system",
        content: `=== NGỮ CẢNH TỪ CƠ SỞ DỮ LIỆU ===\n${context}\n=====================================`,
      });
    }
    groqMsgs.push(...messages);

    const stream = await groq.chat.completions.create({
      model: "llama-3.3-70b-versatile",
      messages: groqMsgs as Parameters<typeof groq.chat.completions.create>[0]["messages"],
      stream: true,
      max_tokens: 2048,
      temperature: 0.3,
    });

    const sourcesJson = JSON.stringify({ sources });

    return new Response(
      new ReadableStream({
        async start(controller) {
          const enc = new TextEncoder();
          try {
            controller.enqueue(enc.encode(`data: ${sourcesJson}\n\n`));
            for await (const chunk of stream) {
              const text = chunk.choices[0]?.delta?.content ?? "";
              if (text) controller.enqueue(enc.encode(`data: ${JSON.stringify({ text })}\n\n`));
            }
            controller.enqueue(enc.encode("data: [DONE]\n\n"));
          } catch (streamErr) {
            controller.enqueue(enc.encode(`data: ${JSON.stringify({ text: `\n\n⚠️ Lỗi: ${String(streamErr)}` })}\n\ndata: [DONE]\n\n`));
          } finally {
            controller.close();
          }
        },
      }),
      { headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform" } }
    );
  } catch (err) {
    console.error("Chat route error:", err);
    return Response.json({ detail: String(err) }, { status: 500 });
  }
}
