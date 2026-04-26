#!/usr/bin/env python3
"""
embed_db.py — Embed Excel trade data into ChromaDB for RAG chatbot.

Usage:
    pip install chromadb sentence-transformers pandas openpyxl
    python embed_db.py            # embed tất cả dữ liệu
    python embed_db.py --reset    # xóa collection cũ rồi embed lại

ChromaDB sẽ được lưu tại ./chroma_db/
"""

import argparse
import hashlib
import logging
import sys
from pathlib import Path
from typing import Generator, Optional

import chromadb
import pandas as pd
from chromadb.utils import embedding_functions

# ─── Cấu hình ─────────────────────────────────────────────────────────────────
DB_DIR = Path("db")
CHROMA_DIR = Path("chroma_db")
COLLECTION_NAME = "trade_data"

# Mô hình đa ngôn ngữ (Tiếng Việt + Tiếng Anh), không cần prefix
# Thay bằng "intfloat/multilingual-e5-base" nếu muốn độ chính xác cao hơn
# (e5 yêu cầu prefix "passage: " khi embed và "query: " khi tìm kiếm)
EMBEDDING_MODEL = "paraphrase-multilingual-mpnet-base-v2"

BATCH_SIZE = 100  # số document upsert mỗi lần
DEVICE = "cpu"    # đổi thành "cuda" nếu có GPU

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ─── Tiện ích ─────────────────────────────────────────────────────────────────

def s(val) -> str:
    """Trả về str, chuỗi rỗng nếu là NaN / None."""
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    return str(val).strip()


def make_id(*parts: str) -> str:
    """Tạo ID duy nhất từ các thành phần."""
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def get_sheet_names(filepath: Path) -> list:
    try:
        xl = pd.ExcelFile(filepath, engine="openpyxl")
        return xl.sheet_names
    except Exception as e:
        log.warning(f"Không mở được {filepath.name}: {e}")
        return []


def read_sheet(filepath: Path, sheet_name: str) -> Optional[pd.DataFrame]:
    try:
        df = pd.read_excel(filepath, sheet_name=sheet_name, engine="openpyxl")
        df = df.dropna(how="all")
        return df if not df.empty else None
    except Exception as e:
        log.warning(f"Lỗi đọc {filepath.name}::{sheet_name}: {e}")
        return None


def detect_product_category(source_file: str) -> str:
    """Suy ra danh mục sản phẩm từ tên file."""
    f = source_file.lower()
    if "hs_code_61" in f or "apparel" in f:
        return "dệt may (HS 61)"
    if "hs_code_64" in f or "footware" in f or "footwear" in f:
        return "giày dép (HS 64)"
    if "hs_code_85" in f or "electric" in f:
        return "điện tử / điện máy (HS 85)"
    if "hs_code_94" in f or "furniture" in f:
        return "nội thất (HS 94)"
    if "848180" in f or "faucet" in f or "touch_on" in f:
        return "vòi nước / phụ kiện"
    if "led_bulb" in f or "853952" in f:
        return "đèn LED Bulbs"
    if "led_strip" in f or "940542" in f:
        return "đèn LED Strip"
    if "481420" in f:
        return "hàng xuất khẩu VN"
    return ""


# ─── Builders — mỗi hàm trả về dict {"id", "text", "metadata"} hoặc None ────

def build_shipment_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Dữ liệu giao dịch xuất nhập khẩu.
    Sheet: Consolidated View Shipments (48 cột), All Exports Shipments (23 cột),
           Consignee and Shipper (33 cột).
    """
    shipper   = s(row.get("Shipper", row.get("Shipper Name", "")))
    consignee = s(row.get("Consignee", ""))
    if not shipper and not consignee:
        return None

    date          = s(row.get("Date", ""))
    goods         = s(row.get("Goods Shipped", ""))
    hs_code       = s(row.get("HS Code", ""))
    value         = s(row.get("Value (USD)", ""))
    weight        = s(row.get("Weight (KG)", ""))
    teu           = s(row.get("Volume (TEU)", ""))
    transport     = s(row.get("Transport Method", ""))
    origin        = s(row.get("Shipment Origin", ""))
    destination   = s(row.get("Shipment Destination", ""))
    port_lading   = s(row.get("Port of Lading", ""))
    port_unlading = s(row.get("Port of Unlading", ""))
    shipper_addr  = s(row.get("Shipper Full Address", ""))
    shipper_email = s(row.get("Shipper Email 1", ""))
    shipper_phone = s(row.get("Shipper Phone 1", ""))
    shipper_web   = s(row.get("Shipper Website 1", ""))
    consignee_addr  = s(row.get("Consignee Full Address", ""))
    consignee_email = s(row.get("Consignee Email 1", ""))

    product = detect_product_category(source_file)

    parts = []
    if date:
        parts.append(f"Ngày giao dịch: {date}.")
    if shipper:
        parts.append(f"Nhà xuất khẩu (Shipper): {shipper}.")
    if shipper_addr:
        parts.append(f"Địa chỉ shipper: {shipper_addr}.")
    if shipper_email:
        parts.append(f"Email shipper: {shipper_email}.")
    if shipper_phone:
        parts.append(f"SĐT shipper: {shipper_phone}.")
    if shipper_web:
        parts.append(f"Website shipper: {shipper_web}.")
    if consignee:
        parts.append(f"Nhà nhập khẩu (Consignee): {consignee}.")
    if consignee_addr:
        parts.append(f"Địa chỉ consignee: {consignee_addr}.")
    if consignee_email:
        parts.append(f"Email consignee: {consignee_email}.")
    if goods:
        parts.append(f"Hàng hóa: {goods}.")
    if product:
        parts.append(f"Danh mục: {product}.")
    if hs_code:
        parts.append(f"HS Code: {hs_code}.")
    if value:
        parts.append(f"Giá trị: {value} USD.")
    if weight:
        parts.append(f"Trọng lượng: {weight} KG.")
    if teu:
        parts.append(f"Thể tích: {teu} TEU.")
    if transport:
        parts.append(f"Phương thức vận chuyển: {transport}.")
    if origin:
        parts.append(f"Xuất xứ: {origin}.")
    if destination:
        parts.append(f"Điểm đến: {destination}.")
    if port_lading:
        parts.append(f"Cảng xếp hàng: {port_lading}.")
    if port_unlading:
        parts.append(f"Cảng dỡ hàng: {port_unlading}.")

    text = " ".join(parts)
    row_id = make_id(source_file, sheet_name, shipper, consignee, date, goods)

    return {
        "id": row_id,
        "text": text,
        "metadata": {
            "source_file":    source_file,
            "sheet_name":     sheet_name,
            "data_type":      "transaction",
            "shipper_name":   shipper[:200],
            "consignee_name": consignee[:200],
            "hs_code":        hs_code[:20],
            "shipment_date":  date[:30],
            "value_usd":      value[:30],
            "goods":          goods[:200],
            "product_category": product[:100],
        },
    }


def build_shipper_profile_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Hồ sơ công ty xuất khẩu (aggregate).
    Sheet: Consolidated View Shipper Shipments (21 cột), Shipper (VN2US, 20 cột).
    """
    name = s(row.get("Shipper Name", ""))
    if not name:
        return None

    addr       = s(row.get("Shipper Full Address", ""))
    email      = s(row.get("Shipper Email 1", ""))
    email_upd  = s(row.get("UPDATE", ""))       # cột đặc biệt trong file Furniture
    phone      = s(row.get("Shipper Phone 1", ""))
    website    = s(row.get("Shipper Website 1", ""))
    profile    = s(row.get("Shipper Profile", ""))
    trade_roles= s(row.get("Shipper Trade Roles", ""))
    hq_global  = s(row.get("Shipper Global HQ Name", ""))
    hq_dom     = s(row.get("Shipper Domestic HQ Name", ""))
    parent     = s(row.get("Shipper Ultimate Parent Name", ""))
    parent_web = s(row.get("Shipper Ultimate Parent Website", ""))
    shipments  = s(row.get("Shipments", ""))
    kg         = s(row.get("KG", ""))
    value      = s(row.get("VALUE (usd)", ""))
    teu        = s(row.get("TEU", ""))
    matching   = s(row.get("Matching Fields", ""))
    product    = detect_product_category(source_file)

    parts = [f"Hồ sơ nhà xuất khẩu: {name}."]
    if product:
        parts.append(f"Danh mục sản phẩm: {product}.")
    if addr:
        parts.append(f"Địa chỉ: {addr}.")
    if email:
        parts.append(f"Email: {email}.")
    if email_upd:
        parts.append(f"Email (cập nhật): {email_upd}.")
    if phone:
        parts.append(f"Điện thoại: {phone}.")
    if website:
        parts.append(f"Website: {website}.")
    if trade_roles:
        parts.append(f"Vai trò thương mại: {trade_roles}.")
    if profile:
        parts.append(f"Mô tả: {profile}.")
    if hq_global:
        parts.append(f"HQ toàn cầu: {hq_global}.")
    if hq_dom:
        parts.append(f"HQ trong nước: {hq_dom}.")
    if parent:
        parts.append(f"Công ty mẹ: {parent}.")
    if parent_web:
        parts.append(f"Website công ty mẹ: {parent_web}.")
    if shipments:
        parts.append(f"Tổng số lô hàng: {shipments}.")
    if value:
        parts.append(f"Tổng giá trị xuất khẩu: {value} USD.")
    if kg:
        parts.append(f"Tổng trọng lượng: {kg} KG.")
    if teu:
        parts.append(f"Tổng thể tích: {teu} TEU.")
    if matching:
        parts.append(f"Sản phẩm chính: {matching}.")

    text = " ".join(parts)
    row_id = make_id(source_file, sheet_name, name)

    return {
        "id": row_id,
        "text": text,
        "metadata": {
            "source_file":      source_file,
            "sheet_name":       sheet_name,
            "data_type":        "company_profile",
            "shipper_name":     name[:200],
            "email":            (email_upd or email)[:100],
            "phone":            phone[:50],
            "website":          website[:200],
            "total_shipments":  shipments[:20],
            "total_value_usd":  value[:30],
            "product_category": product[:100],
        },
    }


def build_consignee_profile_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Hồ sơ nhà nhập khẩu Mỹ (aggregate).
    Sheet: Consignee (VN2US, 20 cột).
    """
    name = s(row.get("Consignee", row.get("Consignee Name", "")))
    if not name:
        return None

    addr    = s(row.get("Consignee Full Address", ""))
    email   = s(row.get("Consignee Email 1", ""))
    phone   = s(row.get("Consignee Phone 1", ""))
    website = s(row.get("Consignee Website 1", ""))
    profile = s(row.get("Consignee Profile", ""))
    roles   = s(row.get("Consignee Trade Roles", ""))
    country = s(row.get("Consignee Country", ""))
    industry= s(row.get("Consignee Industry", ""))
    revenue = s(row.get("Consignee Revenue", ""))
    employees = s(row.get("Consignee Employees", ""))
    shipments = s(row.get("Shipments", ""))
    value   = s(row.get("VALUE (usd)", ""))
    matching= s(row.get("Matching Fields", ""))
    product = detect_product_category(source_file)

    parts = [f"Hồ sơ nhà nhập khẩu: {name}."]
    if country:
        parts.append(f"Quốc gia: {country}.")
    if product:
        parts.append(f"Danh mục sản phẩm nhập: {product}.")
    if addr:
        parts.append(f"Địa chỉ: {addr}.")
    if email:
        parts.append(f"Email: {email}.")
    if phone:
        parts.append(f"Điện thoại: {phone}.")
    if website:
        parts.append(f"Website: {website}.")
    if industry:
        parts.append(f"Ngành: {industry}.")
    if revenue:
        parts.append(f"Doanh thu: {revenue}.")
    if employees:
        parts.append(f"Số nhân viên: {employees}.")
    if roles:
        parts.append(f"Vai trò thương mại: {roles}.")
    if profile:
        parts.append(f"Mô tả: {profile}.")
    if shipments:
        parts.append(f"Tổng số lô hàng nhập từ VN: {shipments}.")
    if value:
        parts.append(f"Tổng giá trị nhập: {value} USD.")
    if matching:
        parts.append(f"Sản phẩm chính: {matching}.")

    text = " ".join(parts)
    row_id = make_id(source_file, sheet_name, name)

    return {
        "id": row_id,
        "text": text,
        "metadata": {
            "source_file":      source_file,
            "sheet_name":       sheet_name,
            "data_type":        "consignee_profile",
            "consignee_name":   name[:200],
            "country":          country[:100],
            "email":            email[:100],
            "website":          website[:200],
            "product_category": product[:100],
        },
    }


def build_contact_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Thông tin liên hệ cá nhân.
    Sheet: Contact Info (8 cột).
    """
    company = s(row.get("Company", ""))
    name    = s(row.get("Contact Name", ""))
    if not company and not name:
        return None

    position     = s(row.get("Position", ""))
    email        = s(row.get("Email", ""))
    phone        = s(row.get("Phone", ""))
    contact_type = s(row.get("Contact Type", ""))
    profile_url  = s(row.get("Profile URL", ""))
    company_url  = s(row.get("Company URL", ""))

    parts = []
    if name:
        parts.append(f"Người liên hệ: {name}.")
    if position:
        parts.append(f"Chức vụ: {position}.")
    if company:
        parts.append(f"Công ty: {company}.")
    if contact_type:
        parts.append(f"Loại liên hệ: {contact_type}.")
    if email:
        parts.append(f"Email: {email}.")
    if phone:
        parts.append(f"Điện thoại: {phone}.")
    if profile_url:
        parts.append(f"LinkedIn: {profile_url}.")
    if company_url:
        parts.append(f"Website công ty: {company_url}.")

    text = " ".join(parts)
    row_id = make_id(source_file, sheet_name, company, name, email)

    return {
        "id": row_id,
        "text": text,
        "metadata": {
            "source_file":  source_file,
            "sheet_name":   sheet_name,
            "data_type":    "contact",
            "company_name": company[:200],
            "contact_name": name[:100],
            "position":     position[:100],
            "email":        email[:100],
        },
    }


def build_macro_trade_doc(
    row: pd.Series, source_file: str, sheet_name: str, row_idx: int
) -> Optional[dict]:
    """
    Dữ liệu thương mại vĩ mô (2017-2021).
    Sheet: HS Codes, Exporters, Importers, Trade Relationships.
    """
    year_cols = [c for c in row.index if str(c).startswith("201") or str(c).startswith("202")]

    if sheet_name == "HS Codes":
        hs = s(row.get("HS Code", ""))
        hs_section = s(row.get("HS Section", ""))
        if not hs:
            return None

        total      = s(row.get("Total", ""))
        pct_change = s(row.get("% Change", ""))

        parts = [f"Thống kê nhập khẩu Mỹ theo HS Code: {hs}."]
        if hs_section:
            parts.append(f"Ngành hàng: {hs_section}.")
        for c in year_cols:
            val = s(row.get(c, ""))
            if val:
                parts.append(f"Năm {str(c)[:4]}: {val} USD.")
        if total:
            parts.append(f"Tổng 2017–2021: {total} USD.")
        if pct_change:
            parts.append(f"Tăng trưởng: {pct_change}%.")

        row_id = make_id(source_file, sheet_name, hs)
        return {
            "id": row_id,
            "text": " ".join(parts),
            "metadata": {
                "source_file": source_file,
                "sheet_name":  sheet_name,
                "data_type":   "macro_trade",
                "sub_type":    "hs_code",
                "hs_code":     hs[:20],
                "hs_section":  hs_section[:200],
            },
        }

    if sheet_name in ("Exporters", "Importers"):
        country = s(row.get("Partner Country/Region", row.get("Reporting Country/Region", "")))
        region  = s(row.get("Partner World Region",  row.get("Reporting World Region",  "")))
        if not country:
            return None

        total = s(row.get("Total", ""))
        role  = "xuất khẩu sang Mỹ" if sheet_name == "Exporters" else "nhập khẩu"

        parts = [f"Thống kê {role}: {country} ({region})."]
        for c in year_cols:
            val = s(row.get(c, ""))
            if val:
                parts.append(f"Năm {str(c)[:4]}: {val} USD.")
        if total:
            parts.append(f"Tổng: {total} USD.")

        row_id = make_id(source_file, sheet_name, country)
        return {
            "id": row_id,
            "text": " ".join(parts),
            "metadata": {
                "source_file": source_file,
                "sheet_name":  sheet_name,
                "data_type":   "macro_trade",
                "sub_type":    sheet_name.lower(),
                "country":     country[:100],
                "region":      region[:100],
            },
        }

    if sheet_name == "Trade Relationships":
        reporting = s(row.get("Reporting Country/Region", ""))
        partner   = s(row.get("Partner Country/Region", ""))
        if not reporting or not partner:
            return None

        total = s(row.get("Total", ""))

        parts = [f"Quan hệ thương mại: {reporting} nhập khẩu từ {partner}."]
        for c in year_cols:
            val = s(row.get(c, ""))
            if val:
                parts.append(f"Năm {str(c)[:4]}: {val} USD.")
        if total:
            parts.append(f"Tổng: {total} USD.")

        row_id = make_id(source_file, sheet_name, reporting, partner)
        return {
            "id": row_id,
            "text": " ".join(parts),
            "metadata": {
                "source_file":       source_file,
                "sheet_name":        sheet_name,
                "data_type":         "macro_trade",
                "sub_type":          "trade_relationship",
                "reporting_country": reporting[:100],
                "partner_country":   partner[:100],
            },
        }

    return None


def build_hs_summary_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Tóm tắt xuất khẩu VN→Mỹ theo HS Code (6 chữ số).
    Sheet: HS Code (6-digit).
    """
    hs   = s(row.get("HS Code", ""))
    desc = s(row.get("HS Code Description", ""))
    if not hs:
        return None

    shipments = s(row.get("Shipments", ""))
    value     = s(row.get("VALUE (usd)", ""))
    kg        = s(row.get("KG", ""))
    teu       = s(row.get("TEU", ""))
    product   = detect_product_category(source_file)

    parts = [f"Xuất khẩu Việt Nam → Mỹ theo HS Code {hs}."]
    if desc:
        parts.append(f"Mô tả hàng hóa: {desc}.")
    if product:
        parts.append(f"Danh mục: {product}.")
    if shipments:
        parts.append(f"Số lô hàng: {shipments}.")
    if value:
        parts.append(f"Tổng giá trị: {value} USD.")
    if kg:
        parts.append(f"Tổng trọng lượng: {kg} KG.")
    if teu:
        parts.append(f"Tổng thể tích: {teu} TEU.")

    row_id = make_id(source_file, sheet_name, hs)
    return {
        "id": row_id,
        "text": " ".join(parts),
        "metadata": {
            "source_file":    source_file,
            "sheet_name":     sheet_name,
            "data_type":      "trade_summary",
            "sub_type":       "hs_code_summary",
            "hs_code":        hs[:20],
            "hs_description": desc[:200],
            "product_category": product[:100],
        },
    }


def build_ecommerce_seller_doc(row: pd.Series, source_file: str, sheet_name: str) -> Optional[dict]:
    """
    Người bán thương mại điện tử Việt Nam.
    Sheet: List of Ecommerce Sellers in VN.
    """
    name = s(row.get("Customer Name", ""))
    if not name:
        return None

    phone      = s(row.get("Contact number", ""))
    address    = s(row.get("Address", ""))
    city       = s(row.get("City", ""))
    status     = s(row.get("Trading status", ""))
    biz_type   = s(row.get("Type of business note", ""))
    product    = s(row.get("Product", ""))
    categories = s(row.get("Categories", ""))
    website    = s(row.get("Customer own Website", ""))
    marketplace= s(row.get("Selling on market place", ""))
    platform   = s(row.get("Sell on Ecommerce Platform", ""))
    social     = s(row.get("Sell on Social Media", ""))

    parts = [f"Người bán TMĐT Việt Nam: {name}."]
    if product:
        parts.append(f"Sản phẩm: {product}.")
    if categories:
        parts.append(f"Danh mục: {categories}.")
    if city:
        parts.append(f"Thành phố: {city}.")
    if address:
        parts.append(f"Địa chỉ: {address}.")
    if phone:
        parts.append(f"Điện thoại: {phone}.")
    if status:
        parts.append(f"Trạng thái kinh doanh: {status}.")
    if biz_type:
        parts.append(f"Loại hình: {biz_type}.")
    if website:
        parts.append(f"Website: {website}.")
    if marketplace:
        parts.append(f"Sàn TMĐT: {marketplace}.")
    if platform:
        parts.append(f"Nền tảng: {platform}.")
    if social:
        parts.append(f"Mạng xã hội: {social}.")

    row_id = make_id(source_file, sheet_name, name)
    return {
        "id": row_id,
        "text": " ".join(parts),
        "metadata": {
            "source_file":  source_file,
            "sheet_name":   sheet_name,
            "data_type":    "ecommerce_seller",
            "company_name": name[:200],
            "product":      product[:200],
            "categories":   categories[:200],
            "city":         city[:100],
        },
    }


# ─── Bảng phân loại sheet → builder ──────────────────────────────────────────

# Tên sheet → hàm xử lý
_SHEET_DISPATCH = {
    # Giao dịch
    "Consolidated View Shipments":   "shipment",
    "All Exports Shipments":         "shipment",
    "Consignee and Shipper":         "shipment",
    # Hồ sơ công ty
    "Consolidated View Shipper Shipments": "shipper_profile",
    "Shipper":                       "shipper_profile",
    # Hồ sơ nhà nhập khẩu
    "Consignee":                     "consignee_profile",
    # Liên hệ
    "Contact Info":                  "contact",
    # MacroTrade
    "HS Codes":                      "macro_trade",
    "Exporters":                     "macro_trade",
    "Importers":                     "macro_trade",
    "Trade Relationships":           "macro_trade",
    # Tóm tắt HS Code
    "HS Code (6-digit)":             "hs_summary",
    # TMĐT
    "List of Ecommerce Sellers in VN": "ecommerce",
}

_SKIP_SHEETS = {
    "Info", "About", "Sheet1", "Sheet2", "Technology", "Dell",
    "Amazon",                         # chỉ có 5 cột địa chỉ, ít giá trị
    "Transport Method",               # pivot đơn giản, ít ngữ nghĩa
    "Shipment Origin", "Shipment Destination",
    "Shipment Month",  "Shipment Year",
    "Port of Lading Name", "Port of Unlading Name",
    "Origin and Destination Country",
}


def process_sheet(df: pd.DataFrame, source_file: str, sheet_name: str) -> list:
    if sheet_name in _SKIP_SHEETS:
        return []

    dispatch = _SHEET_DISPATCH.get(sheet_name)

    # Heuristic nếu tên sheet không khớp bảng trên
    if dispatch is None:
        cols = set(df.columns.astype(str))
        if "Shipper Name" in cols and "Shipments" in cols:
            dispatch = "shipper_profile"
        elif "Shipper" in cols and "Goods Shipped" in cols:
            dispatch = "shipment"
        elif "Contact Name" in cols:
            dispatch = "contact"
        else:
            log.debug(f"Bỏ qua sheet không nhận dạng được: {source_file}::{sheet_name}")
            return []

    docs = []
    for _, row in df.iterrows():
        if dispatch == "shipment":
            doc = build_shipment_doc(row, source_file, sheet_name)
        elif dispatch == "shipper_profile":
            doc = build_shipper_profile_doc(row, source_file, sheet_name)
        elif dispatch == "consignee_profile":
            doc = build_consignee_profile_doc(row, source_file, sheet_name)
        elif dispatch == "contact":
            doc = build_contact_doc(row, source_file, sheet_name)
        elif dispatch == "macro_trade":
            doc = build_macro_trade_doc(row, source_file, sheet_name, _)
        elif dispatch == "hs_summary":
            doc = build_hs_summary_doc(row, source_file, sheet_name)
        elif dispatch == "ecommerce":
            doc = build_ecommerce_seller_doc(row, source_file, sheet_name)
        else:
            doc = None

        if doc:
            docs.append(doc)

    return docs


# ─── Pipeline chính ───────────────────────────────────────────────────────────

def collect_documents() -> Generator[tuple, None, None]:
    """Yield (source_file, sheet_name, docs) từ toàn bộ file Excel trong DB_DIR."""
    excel_files = sorted(DB_DIR.glob("*.xlsx")) + sorted(DB_DIR.glob("*.xls"))

    if not excel_files:
        log.error(f"Không tìm thấy file Excel trong {DB_DIR.resolve()}")
        return

    for filepath in excel_files:
        log.info(f"Đang xử lý: {filepath.name}")
        for sheet_name in get_sheet_names(filepath):
            df = read_sheet(filepath, sheet_name)
            if df is None:
                continue
            docs = process_sheet(df, filepath.name, sheet_name)
            if docs:
                yield filepath.name, sheet_name, docs


def upsert_batch(collection: chromadb.Collection, docs: list) -> None:
    """Upsert một batch, khử trùng lặp theo ID."""
    deduped = {d["id"]: d for d in docs}
    unique  = list(deduped.values())

    for i in range(0, len(unique), BATCH_SIZE):
        chunk = unique[i : i + BATCH_SIZE]
        collection.upsert(
            ids       =[d["id"]       for d in chunk],
            documents =[d["text"]     for d in chunk],
            metadatas =[d["metadata"] for d in chunk],
        )


def main():
    parser = argparse.ArgumentParser(description="Embed trade data vào ChromaDB")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Xóa collection cũ và embed lại từ đầu",
    )
    args = parser.parse_args()

    log.info(f"Mô hình embedding : {EMBEDDING_MODEL}")
    log.info(f"ChromaDB          : {CHROMA_DIR.resolve()}")
    log.info(f"Dữ liệu nguồn     : {DB_DIR.resolve()}")

    CHROMA_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))

    if args.reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            log.info(f"Đã xóa collection '{COLLECTION_NAME}'.")
        except Exception:
            pass

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL,
        device=DEVICE,
    )

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    total = 0
    data_type_counts: dict = {}

    for source_file, sheet_name, docs in collect_documents():
        upsert_batch(collection, docs)
        total += len(docs)

        for d in docs:
            dt = d["metadata"].get("data_type", "unknown")
            data_type_counts[dt] = data_type_counts.get(dt, 0) + 1

        log.info(f"  [{sheet_name}] → {len(docs)} docs (tổng: {total})")

    log.info("\n─── Tổng kết ───────────────────────────────────────────")
    for dt, cnt in sorted(data_type_counts.items()):
        log.info(f"  {dt:<25} : {cnt:>6} vectors")
    log.info(f"  {'TỔNG':<25} : {collection.count():>6} vectors trong ChromaDB")
    log.info(f"\nChromaDB đã lưu tại: {CHROMA_DIR.resolve()}")
    log.info("Sẵn sàng sử dụng cho chatbot RAG.")


if __name__ == "__main__":
    main()
