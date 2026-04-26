# """
# B2B Lead Research Pipeline
# Tavily (company info) + Apollo (people/contacts)

# Cài đặt:
#     pip install tavily-python requests

# Cách dùng:
#     python b2b_pipeline.py
# """

# import json
# import csv
# import time
# import re
# import os
# from datetime import datetime
# from urllib.parse import urlparse

# import requests

# # ─── CẤU HÌNH ────────────────────────────────────────────────────────────────

# TAVILY_API_KEY = "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"
# APOLLO_API_KEY = "gw8O2SfnLMNEMVzsx_8Qaw"

# COMPANY_NAME   = "VPrint"          # Tên công ty cần nghiên cứu
# TITLE_FILTER   = []                # VD: ["CEO", "Director", "Sales"] — để [] để lấy tất cả
# MAX_PEOPLE     = 25                # Số nhân sự tối đa lấy từ Apollo
# ENRICH_PEOPLE  = False             # True = gọi enrich lấy email (tốn credit Apollo)

# OUTPUT_DIR     = "output"          # Thư mục lưu kết quả

# # ─── TAVILY ──────────────────────────────────────────────────────────────────

# def tavily_search(query: str, max_results: int = 5, depth: str = "basic") -> dict:
#     """Tìm kiếm web qua Tavily API."""
#     resp = requests.post(
#         "https://api.tavily.com/search",
#         json={
#             "api_key": TAVILY_API_KEY,
#             "query": query,
#             "max_results": max_results,
#             "search_depth": depth,
#             "include_answer": True,
#         },
#         timeout=30,
#     )
#     resp.raise_for_status()
#     return resp.json()


# def tavily_extract(urls: list[str]) -> dict:
#     """Extract full content từ danh sách URL."""
#     resp = requests.post(
#         "https://api.tavily.com/extract",
#         json={"api_key": TAVILY_API_KEY, "urls": urls},
#         timeout=60,
#     )
#     resp.raise_for_status()
#     return resp.json()


# # ─── APOLLO ──────────────────────────────────────────────────────────────────

# def apollo_search_people(
#     company_name: str,
#     domain: str | None = None,
#     title_filters: list[str] | None = None,
#     per_page: int = 25,
# ) -> dict:
#     """
#     Tìm nhân sự theo tên công ty + domain.
#     Endpoint này KHÔNG tốn credit Apollo.
#     """
#     params = {"per_page": per_page}

#     if company_name:
#         params["q_organization_name"] = company_name
#     if domain:
#         params["organization_domains[]"] = domain
#     for title in (title_filters or []):
#         params.setdefault("person_titles[]", [])
#         if isinstance(params["person_titles[]"], list):
#             params["person_titles[]"].append(title)
#         else:
#             params["person_titles[]"] = [params["person_titles[]"], title]

#     resp = requests.post(
#         "https://api.apollo.io/api/v1/mixed_people/api_search",
#         params=params,
#         headers={
#             "x-api-key": APOLLO_API_KEY,
#             "Content-Type": "application/json",
#             "Cache-Control": "no-cache",
#         },
#         timeout=30,
#     )
#     if resp.status_code == 401:
#         raise ValueError("Apollo API key không hợp lệ")
#     resp.raise_for_status()
#     return resp.json()


# def apollo_enrich_person(person_id: str) -> dict:
#     """
#     Enrich chi tiết 1 người (email, phone, LinkedIn...).
#     CẢNH BÁO: Tốn credit Apollo tùy plan.
#     """
#     resp = requests.post(
#         "https://api.apollo.io/api/v1/people/match",
#         json={
#             "id": person_id,
#             "reveal_personal_emails": False,
#             "reveal_phone_number": False,
#         },
#         headers={
#             "x-api-key": APOLLO_API_KEY,
#             "Content-Type": "application/json",
#             "Cache-Control": "no-cache",
#         },
#         timeout=30,
#     )
#     resp.raise_for_status()
#     return resp.json()


# # ─── HELPERS ─────────────────────────────────────────────────────────────────

# def extract_field(texts: list[str], patterns: list[str]) -> str | None:
#     """Trích xuất field đầu tiên khớp pattern từ danh sách texts."""
#     for text in texts:
#         for pattern in patterns:
#             m = re.search(pattern, text, re.IGNORECASE)
#             if m:
#                 return (m.group(1) if m.lastindex else m.group(0)).strip()
#     return None


# def extract_domain(results: list[dict]) -> str | None:
#     """Lấy domain chính của công ty từ kết quả search."""
#     skip = {"masothue.com", "tracuunhanh.vn", "google.com", "vcci.com.vn"}
#     for r in results:
#         try:
#             host = urlparse(r["url"]).hostname.replace("www.", "")
#             if not any(s in host for s in skip):
#                 return host
#         except Exception:
#             continue
#     return None


# def extract_markets(text: str) -> list[str]:
#     """Tìm thị trường xuất khẩu được đề cập."""
#     keywords = [
#         "Mỹ", "USA", "Châu Âu", "EU", "Nhật", "Japan", "Hàn Quốc", "Korea",
#         "Trung Quốc", "China", "ASEAN", "Đông Nam Á", "Đài Loan", "Taiwan",
#         "Australia", "Singapore", "Thailand", "Malaysia",
#     ]
#     return [k for k in keywords if k.lower() in text.lower()]


# def step(label: str):
#     print(f"\n{'─'*50}\n  {label}\n{'─'*50}")


# def log(msg: str):
#     print(f"  › {msg}")


# # ─── PIPELINE ────────────────────────────────────────────────────────────────

# def run_pipeline(company: str) -> dict:
#     """Chạy toàn bộ pipeline cho 1 công ty."""

#     result = {
#         "company": company,
#         "timestamp": datetime.now().isoformat(),
#         "company_info": {},
#         "people": [],
#     }

#     # ── BƯỚC 1: Thông tin cơ bản ──────────────────────────────────────────
#     step("Bước 1 — Tìm kiếm thông tin cơ bản (Tavily)")

#     s1 = tavily_search(
#         f"thông tin chi tiết công ty {company} địa chỉ sản phẩm dịch vụ thành lập",
#         max_results=5,
#         depth="advanced",
#     )
#     log(f"Tìm thấy {len(s1['results'])} kết quả")

#     # ── BƯỚC 2: MST & pháp lý ────────────────────────────────────────────
#     step("Bước 2 — Tra cứu MST & pháp lý (Tavily)")

#     s2 = tavily_search(
#         f'"{company}" mã số thuế thành lập người đại diện site:masothue.com OR site:tracuunhanh.vn',
#         max_results=3,
#     )
#     log(f"Tìm thấy {len(s2['results'])} kết quả pháp lý")

#     # ── BƯỚC 3: Xuất nhập khẩu ───────────────────────────────────────────
#     step("Bước 3 — Tra cứu xuất nhập khẩu & thị trường (Tavily)")

#     s3 = tavily_search(
#         f'"{company}" xuất khẩu nhập khẩu khách hàng đối tác thị trường nước ngoài',
#         max_results=5,
#         depth="advanced",
#     )
#     s3b = tavily_search(
#         f'"{company}" site:importyeti.com OR site:volza.com OR site:panjiva.com',
#         max_results=3,
#     )
#     log(f"Tìm thấy {len(s3['results'])} kết quả thương mại")

#     # ── BƯỚC 4: Extract website ───────────────────────────────────────────
#     step("Bước 4 — Extract nội dung website (Tavily)")

#     domain = extract_domain(s1["results"])
#     log(f"Domain phát hiện: {domain or '(không rõ)'}")

#     top_urls = [r["url"] for r in s1["results"][:2]]
#     extracted_texts = []
#     try:
#         extracted = tavily_extract(top_urls)
#         for item in extracted.get("results", []):
#             extracted_texts.append(item.get("raw_content", ""))
#         log(f"Extract thành công {len(extracted_texts)} trang")
#     except Exception as e:
#         log(f"Extract warning: {e}")

#     # ── Tổng hợp thông tin công ty ────────────────────────────────────────
#     all_texts = []
#     for s in [s1, s2, s3, s3b]:
#         for r in s.get("results", []):
#             all_texts.append((r.get("content", "") + " " + r.get("title", "")).strip())
#     all_texts.extend(extracted_texts)
#     full_text = " ".join(all_texts)

#     company_info = {
#         "name": company,
#         "domain": domain,
#         "mst": extract_field(all_texts, [
#             r"(?:mã số thuế|MST)[:\s]+([0-9]{10,13})",
#             r"\b(0[0-9]{9,12})\b",
#         ]),
#         "founded": extract_field(all_texts, [
#             r"(?:thành lập|ngày hoạt động)[:\s]+(\d{4}[-\/]\d{2}[-\/]\d{2}|\d{4})",
#         ]),
#         "representative": extract_field(all_texts, [
#             r"(?:người đại diện)[:\s]+([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠ][^\n|]{5,35})",
#         ]),
#         "address": extract_field(all_texts, [
#             r"(?:địa chỉ|address)[:\s]+([^\n|]{10,80})",
#         ]),
#         "phone": extract_field(all_texts, [
#             r"(?:hotline|điện thoại|phone|tel)[:\s]+([\+0-9\s\(\)]{9,15})",
#             r"\b(0[0-9]{9})\b",
#         ]),
#         "email": extract_field(all_texts, [
#             r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
#         ]),
#         "markets": extract_markets(full_text),
#         "tavily_answer": s1.get("answer") or s3.get("answer"),
#         "top_sources": [
#             {"title": r["title"], "url": r["url"], "score": round(r["score"], 3)}
#             for r in s1["results"][:3]
#         ],
#     }

#     result["company_info"] = company_info

#     print()
#     print("  Kết quả công ty:")
#     for k, v in company_info.items():
#         if v and k not in ("top_sources", "tavily_answer"):
#             print(f"    {k:<18} {v}")

#     # ── BƯỚC 5: Apollo — tìm nhân sự ────────────────────────────────────
#     step("Bước 5 — Tìm nhân sự (Apollo)")

#     try:
#         ap_data = apollo_search_people(
#             company_name=company,
#             domain=domain,
#             title_filters=TITLE_FILTER or None,
#             per_page=MAX_PEOPLE,
#         )
#         people_raw = ap_data.get("people", [])
#         total = ap_data.get("pagination", {}).get("total_entries", len(people_raw))
#         log(f"Apollo: {total} người tổng cộng, hiển thị {len(people_raw)}")

#         for p in people_raw:
#             person = {
#                 "id": p.get("id"),
#                 "name": p.get("name"),
#                 "title": p.get("title"),
#                 "linkedin_url": p.get("linkedin_url"),
#                 "email": p.get("email"),
#                 "city": p.get("city"),
#                 "country": p.get("country"),
#                 "seniority": p.get("seniority"),
#                 "organization": p.get("organization", {}).get("name"),
#             }

#             # Enrich nếu bật (tốn credit)
#             if ENRICH_PEOPLE and p.get("id"):
#                 try:
#                     enriched = apollo_enrich_person(p["id"])
#                     ep = enriched.get("person", {})
#                     person["email"] = ep.get("email") or person["email"]
#                     person["phone"] = (ep.get("phone_numbers") or [{}])[0].get("raw_number")
#                     log(f"  Enriched: {person['name']} → {person['email'] or 'no email'}")
#                     time.sleep(0.5)  # tránh rate limit
#                 except Exception as e:
#                     log(f"  Enrich warning ({person['name']}): {e}")

#             result["people"].append(person)

#         print()
#         print(f"  {'Tên':<30} {'Chức danh':<30} {'LinkedIn'}")
#         print(f"  {'─'*30} {'─'*30} {'─'*30}")
#         for p in result["people"]:
#             name = (p["name"] or "")[:28]
#             title = (p["title"] or "")[:28]
#             li = "có" if p["linkedin_url"] else "—"
#             print(f"  {name:<30} {title:<30} {li}")

#     except Exception as e:
#         log(f"Apollo lỗi: {e}")
#         log("Bỏ qua bước Apollo — vẫn lưu thông tin công ty")

#     return result


# # ─── XUẤT KẾT QUẢ ────────────────────────────────────────────────────────────

# def save_results(data: dict):
#     os.makedirs(OUTPUT_DIR, exist_ok=True)
#     slug = re.sub(r"[^\w]", "_", data["company"].lower())
#     ts = datetime.now().strftime("%Y%m%d_%H%M%S")

#     # JSON đầy đủ
#     json_path = os.path.join(OUTPUT_DIR, f"{slug}_{ts}.json")
#     with open(json_path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)
#     print(f"\n  JSON đã lưu: {json_path}")

#     # CSV nhân sự
#     if data["people"]:
#         csv_path = os.path.join(OUTPUT_DIR, f"{slug}_{ts}_people.csv")
#         fields = ["name", "title", "email", "phone", "linkedin_url",
#                   "city", "country", "seniority", "organization"]
#         with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
#             writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
#             writer.writeheader()
#             writer.writerows(data["people"])
#         print(f"  CSV nhân sự đã lưu: {csv_path}")

#     # CSV công ty (1 dòng)
#     info = data["company_info"]
#     co_csv = os.path.join(OUTPUT_DIR, f"{slug}_{ts}_company.csv")
#     with open(co_csv, "w", newline="", encoding="utf-8-sig") as f:
#         writer = csv.DictWriter(f, fieldnames=info.keys(), extrasaction="ignore")
#         writer.writeheader()
#         writer.writerow(info)
#     print(f"  CSV công ty đã lưu: {co_csv}")


# # ─── CHẠY NHIỀU CÔNG TY (batch) ──────────────────────────────────────────────

# def run_batch(companies: list[str], delay: float = 2.0):
#     """
#     Chạy pipeline cho danh sách công ty.
#     delay: giây chờ giữa mỗi công ty (tránh rate limit).
#     """
#     all_results = []
#     for i, company in enumerate(companies, 1):
#         print(f"\n{'='*55}")
#         print(f"  [{i}/{len(companies)}] {company}")
#         print(f"{'='*55}")
#         try:
#             result = run_pipeline(company)
#             save_results(result)
#             all_results.append(result)
#         except Exception as e:
#             print(f"  LỖI khi xử lý {company}: {e}")
#         if i < len(companies):
#             print(f"\n  Chờ {delay}s trước công ty tiếp theo...")
#             time.sleep(delay)
#     return all_results


# # ─── MAIN ────────────────────────────────────────────────────────────────────

# if __name__ == "__main__":
#     print("=" * 55)
#     print("  B2B Lead Research Pipeline")
#     print("  Tavily + Apollo")
#     print("=" * 55)

#     # ── Chạy 1 công ty ──
#     result = run_pipeline(COMPANY_NAME)
#     save_results(result)

#     # ── Hoặc chạy batch nhiều công ty ──
#     # companies = ["VPrint", "Vinamilk", "TMA Solutions"]
#     # run_batch(companies, delay=3.0)

#     print("\n  Pipeline hoàn tất.")


"""
B2B Lead Research Pipeline
Tavily (company info) + LinkedIn via Tavily (people) + Hunter.io (email)

Lý do bỏ Apollo: free plan bị 403 trên mixed_people/api_search.
Cần plan Basic $59/tháng. Pipeline này dùng các nguồn MIỄN PHÍ thay thế:
  - Bước 1-4 : Tavily   → thông tin công ty, MST, XNK, website
  - Bước 5   : Tavily   → tìm nhân sự qua LinkedIn public profile search
  - Bước 6   : Hunter.io (free 25 req/tháng) → email theo domain

Cài đặt:
    pip install requests

Cách dùng:
    python b2b_pipeline.py
"""

import json
import csv
import time
import re
import os
from datetime import datetime
from urllib.parse import urlparse

import requests

# ─── CẤU HÌNH ────────────────────────────────────────────────────────────────

TAVILY_API_KEY = "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"  # app.tavily.com — free 1000 req/tháng
HUNTER_API_KEY = ""                    # hunter.io — free 25 req/tháng (để "" để bỏ qua)

COMPANY_NAME  = "CÔNG TY TNHH VINA SOLAR TECHNOLOGY"         # Tên công ty cần nghiên cứu
# Lọc chức danh khi tìm LinkedIn — để [] để lấy tất cả
TITLE_FILTER  = ["CEO", "Giám đốc", "Director", "Sales", "Manager", "Trưởng phòng"]

OUTPUT_DIR    = "output"

# ─── TAVILY ──────────────────────────────────────────────────────────────────

def tavily_search(query: str, max_results: int = 5, depth: str = "basic") -> dict:
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": TAVILY_API_KEY,
            "query": query,
            "max_results": max_results,
            "search_depth": depth,
            "include_answer": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def tavily_extract(urls: list) -> dict:
    resp = requests.post(
        "https://api.tavily.com/extract",
        json={"api_key": TAVILY_API_KEY, "urls": urls},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


# ─── HUNTER.IO ───────────────────────────────────────────────────────────────

def hunter_domain_search(domain: str, limit: int = 10) -> list:
    """
    Tìm email theo domain qua Hunter.io.
    Free plan: 25 requests/tháng.
    Trả về list dict: {first_name, last_name, email, position, linkedin_url}
    """
    if not HUNTER_API_KEY:
        return []
    resp = requests.get(
        "https://api.hunter.io/v2/domain-search",
        params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": limit},
        timeout=20,
    )
    if not resp.ok:
        return []
    data = resp.json().get("data", {})
    return data.get("emails", [])


# ─── LINKEDIN via TAVILY ──────────────────────────────────────────────────────

def search_linkedin_people(company: str, domain: str = None, titles: list = None) -> list:
    """
    Tìm nhân sự công ty qua LinkedIn public profiles bằng Tavily.
    Không cần API LinkedIn — dùng Google-indexed profiles.
    """
    people = []
    queries = []

    # Query 1: tìm theo tên công ty + chức danh
    title_str = " OR ".join(f'"{t}"' for t in (titles or [])[:4]) if titles else ""
    q1 = f'site:linkedin.com/in "{company}" {title_str}'.strip()
    queries.append(q1)

    # Query 2: tìm theo domain nếu có
    if domain:
        q2 = f'site:linkedin.com/in "{domain.split(".")[0]}" {title_str}'.strip()
        queries.append(q2)

    seen_urls = set()
    for q in queries:
        try:
            result = tavily_search(q, max_results=10, depth="basic")
            for r in result.get("results", []):
                url = r.get("url", "")
                if "linkedin.com/in/" not in url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse tên + chức danh từ title/content
                raw_title = r.get("title", "")
                raw_content = r.get("content", "")

                # LinkedIn title format: "Tên - Chức danh - Công ty | LinkedIn"
                name, title, org = parse_linkedin_title(raw_title)
                if not name:
                    continue

                people.append({
                    "name": name,
                    "title": title,
                    "organization": org or company,
                    "linkedin_url": url,
                    "email": None,
                    "source": "LinkedIn via Tavily",
                    "snippet": raw_content[:200],
                })
            time.sleep(0.5)
        except Exception as e:
            log(f"  LinkedIn search warning: {e}")

    return people


def parse_linkedin_title(raw: str) -> tuple:
    """
    Parse LinkedIn page title.
    Format phổ biến: "Nguyen Van A - CEO - VPrint | LinkedIn"
    Trả về (name, title, organization)
    """
    # Bỏ " | LinkedIn" ở cuối
    raw = re.sub(r"\s*\|\s*LinkedIn.*$", "", raw, flags=re.IGNORECASE).strip()

    parts = [p.strip() for p in raw.split(" - ") if p.strip()]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        return parts[0], parts[1], None
    elif len(parts) == 1 and parts[0]:
        return parts[0], None, None
    return None, None, None


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def extract_field(texts: list, patterns: list):
    for text in texts:
        for pattern in patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                return (m.group(1) if m.lastindex else m.group(0)).strip()
    return None


def extract_domain(results: list):
    skip = {"masothue.com", "tracuunhanh.vn", "google.com", "vcci.com.vn",
            "linkedin.com", "facebook.com", "youtube.com"}
    for r in results:
        try:
            host = urlparse(r["url"]).hostname.replace("www.", "")
            if not any(s in host for s in skip):
                return host
        except Exception:
            continue
    return None


def extract_markets(text: str) -> list:
    keywords = [
        "Mỹ", "USA", "Châu Âu", "EU", "Nhật", "Japan",
        "Hàn Quốc", "Korea", "Trung Quốc", "China", "ASEAN",
        "Đông Nam Á", "Đài Loan", "Taiwan", "Australia",
        "Singapore", "Thailand", "Malaysia",
    ]
    return [k for k in keywords if k.lower() in text.lower()]


def step(label: str):
    print(f"\n{'─'*55}\n  {label}\n{'─'*55}")


def log(msg: str):
    print(f"  › {msg}")


# ─── PIPELINE ────────────────────────────────────────────────────────────────

def run_pipeline(company: str) -> dict:
    result = {
        "company": company,
        "timestamp": datetime.now().isoformat(),
        "company_info": {},
        "people": [],
    }

    # ── Bước 1: Thông tin cơ bản ──────────────────────────────────────────
    step("Bước 1 — Thông tin cơ bản (Tavily)")
    s1 = tavily_search(
        f"thông tin chi tiết công ty {company} địa chỉ sản phẩm dịch vụ thành lập",
        max_results=5, depth="advanced",
    )
    log(f"Tìm thấy {len(s1['results'])} kết quả")

    # ── Bước 2: MST & pháp lý ─────────────────────────────────────────────
    step("Bước 2 — MST & pháp lý (Tavily)")
    s2 = tavily_search(
        f'"{company}" mã số thuế thành lập người đại diện site:masothue.com OR site:tracuunhanh.vn',
        max_results=3,
    )
    log(f"Tìm thấy {len(s2['results'])} kết quả pháp lý")

    # ── Bước 3: Xuất nhập khẩu ────────────────────────────────────────────
    step("Bước 3 — Xuất nhập khẩu & thị trường (Tavily)")
    s3, s3b = (
        tavily_search(f'"{company}" xuất khẩu nhập khẩu khách hàng đối tác thị trường', max_results=5, depth="advanced"),
        tavily_search(f'"{company}" site:importyeti.com OR site:volza.com', max_results=3),
    )
    log(f"Tìm thấy {len(s3['results'])} kết quả thương mại")

    # ── Bước 4: Extract website ───────────────────────────────────────────
    step("Bước 4 — Extract website (Tavily)")
    domain = extract_domain(s1["results"])
    log(f"Domain phát hiện: {domain or '(không rõ)'}")

    extracted_texts = []
    try:
        top_urls = [r["url"] for r in s1["results"][:2]]
        ext = tavily_extract(top_urls)
        for item in ext.get("results", []):
            extracted_texts.append(item.get("raw_content", ""))
        log(f"Extract thành công {len(extracted_texts)} trang")
    except Exception as e:
        log(f"Extract warning: {e}")

    # ── Tổng hợp thông tin công ty ────────────────────────────────────────
    all_texts = []
    for s in [s1, s2, s3, s3b]:
        for r in s.get("results", []):
            all_texts.append(r.get("content", "") + " " + r.get("title", ""))
    all_texts.extend(extracted_texts)
    full_text = " ".join(all_texts)

    company_info = {
        "name": company,
        "domain": domain,
        "mst": extract_field(all_texts, [
            r"(?:mã số thuế|MST)[:\s]+([0-9]{10,13})",
            r"\b(0[0-9]{9,12})\b",
        ]),
        "founded": extract_field(all_texts, [
            r"(?:thành lập|ngày hoạt động)[:\s]+(\d{4}[-\/]\d{2}[-\/]\d{2}|\d{4})",
        ]),
        "representative": extract_field(all_texts, [
            r"(?:người đại diện)[:\s]+([A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚĂĐĨŨƠƯẠ][^\n|]{5,35})",
        ]),
        "address": extract_field(all_texts, [
            r"(?:địa chỉ|address)[:\s]+([^\n|]{10,80})",
        ]),
        "phone": extract_field(all_texts, [
            r"(?:hotline|điện thoại|phone|tel)[:\s]+([\+0-9\s\(\)]{9,15})",
        ]),
        "email": extract_field(all_texts, [
            r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        ]),
        "markets": extract_markets(full_text),
        "tavily_answer": s1.get("answer") or s3.get("answer"),
        "top_sources": [
            {"title": r["title"], "url": r["url"], "score": round(r["score"], 3)}
            for r in s1["results"][:3]
        ],
    }
    result["company_info"] = company_info

    print()
    for k, v in company_info.items():
        if v and k not in ("top_sources", "tavily_answer", "markets"):
            print(f"    {k:<18} {v}")
    if company_info["markets"]:
        print(f"    {'markets':<18} {', '.join(company_info['markets'])}")

    # ── Bước 5: LinkedIn via Tavily ───────────────────────────────────────
    step("Bước 5 — Tìm nhân sự qua LinkedIn (Tavily)")
    people = search_linkedin_people(
        company=company,
        domain=domain,
        titles=TITLE_FILTER or None,
    )
    log(f"Tìm thấy {len(people)} hồ sơ LinkedIn")

    # ── Bước 6: Hunter.io — email theo domain ─────────────────────────────
    if domain and HUNTER_API_KEY:
        step("Bước 6 — Tìm email qua Hunter.io")
        emails = hunter_domain_search(domain, limit=20)
        log(f"Hunter.io tìm thấy {len(emails)} email")

        # Map email vào người đã tìm được, hoặc thêm mới
        existing_names = {p["name"].lower(): p for p in people}
        for e in emails:
            full_name = f"{e.get('first_name','')} {e.get('last_name','')}".strip()
            key = full_name.lower()
            if key in existing_names:
                existing_names[key]["email"] = e.get("email")
                if e.get("linkedin") and not existing_names[key]["linkedin_url"]:
                    existing_names[key]["linkedin_url"] = e["linkedin"]
            else:
                people.append({
                    "name": full_name,
                    "title": e.get("position"),
                    "organization": company,
                    "linkedin_url": e.get("linkedin"),
                    "email": e.get("email"),
                    "source": "Hunter.io",
                    "snippet": "",
                })
    else:
        if not HUNTER_API_KEY:
            log("Bỏ qua Hunter.io (chưa có API key — đăng ký miễn phí tại hunter.io)")

    result["people"] = people

    # In bảng nhân sự
    if people:
        print()
        print(f"  {'Tên':<28} {'Chức danh':<28} {'Email':<25} {'Nguồn'}")
        print(f"  {'─'*28} {'─'*28} {'─'*25} {'─'*15}")
        for p in people:
            name  = (p["name"] or "")[:26]
            title = (p["title"] or "—")[:26]
            email = (p["email"] or "—")[:23]
            src   = p.get("source", "")[:14]
            print(f"  {name:<28} {title:<28} {email:<25} {src}")

    return result


# ─── XUẤT KẾT QUẢ ────────────────────────────────────────────────────────────

def save_results(data: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = re.sub(r"[^\w]", "_", data["company"].lower())
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON đầy đủ
    json_path = os.path.join(OUTPUT_DIR, f"{slug}_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"JSON đã lưu: {json_path}")

    # CSV nhân sự
    if data["people"]:
        csv_path = os.path.join(OUTPUT_DIR, f"{slug}_{ts}_people.csv")
        fields = ["name", "title", "email", "linkedin_url", "organization", "source", "snippet"]
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data["people"])
        log(f"CSV nhân sự đã lưu: {csv_path}")

    # CSV công ty
    info = {k: v for k, v in data["company_info"].items()
            if k not in ("top_sources", "tavily_answer")}
    info["markets"] = ", ".join(info.get("markets") or [])
    co_csv = os.path.join(OUTPUT_DIR, f"{slug}_{ts}_company.csv")
    with open(co_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=info.keys())
        writer.writeheader()
        writer.writerow(info)
    log(f"CSV công ty đã lưu: {co_csv}")


# ─── BATCH: NHIỀU CÔNG TY ────────────────────────────────────────────────────

def run_batch(companies: list, delay: float = 3.0):
    """Chạy pipeline lần lượt cho danh sách công ty."""
    for i, company in enumerate(companies, 1):
        print(f"\n{'='*55}")
        print(f"  [{i}/{len(companies)}] {company}")
        print(f"{'='*55}")
        try:
            result = run_pipeline(company)
            save_results(result)
        except Exception as e:
            print(f"  LỖI: {e}")
        if i < len(companies):
            print(f"\n  Chờ {delay}s...")
            time.sleep(delay)


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  B2B Lead Research Pipeline v2")
    print("  Tavily + LinkedIn (free) + Hunter.io (free)")
    print("=" * 55)

    # ── Chạy 1 công ty ──
    result = run_pipeline(COMPANY_NAME)
    save_results(result)

    # ── Hoặc chạy batch ──
    # run_batch(["VPrint", "Vinamilk", "TMA Solutions"], delay=3.0)

    print("\n  Pipeline hoàn tất.")
