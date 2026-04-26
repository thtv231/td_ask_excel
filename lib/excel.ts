import * as XLSX from "xlsx";
import { createHash } from "crypto";

function s(val: unknown): string {
  if (val === null || val === undefined) return "";
  if (typeof val === "number" && isNaN(val)) return "";
  return String(val).trim();
}

function makeId(...parts: string[]): string {
  return createHash("md5").update(parts.join("|")).digest("hex");
}

function detectCategory(filename: string): string {
  const f = filename.toLowerCase();
  if (f.includes("hs_code_61") || f.includes("apparel"))   return "dệt may (HS 61)";
  if (f.includes("hs_code_64") || f.includes("footwear"))  return "giày dép (HS 64)";
  if (f.includes("hs_code_85") || f.includes("electric"))  return "điện tử / điện máy (HS 85)";
  if (f.includes("hs_code_94") || f.includes("furniture")) return "nội thất (HS 94)";
  if (f.includes("848180") || f.includes("faucet"))        return "vòi nước / phụ kiện";
  if (f.includes("led_bulb") || f.includes("853952"))      return "đèn LED Bulbs";
  if (f.includes("led_strip") || f.includes("940542"))     return "đèn LED Strip";
  return "";
}

interface Doc { id: string; text: string; metadata: Record<string, string> }
type Row = Record<string, unknown>;

const SKIP_SHEETS = new Set([
  "Info","About","Sheet1","Sheet2","Technology","Dell","Amazon",
  "Transport Method","Shipment Origin","Shipment Destination",
  "Shipment Month","Shipment Year","Port of Lading Name",
  "Port of Unlading Name","Origin and Destination Country",
]);

const SHEET_DISPATCH: Record<string, string> = {
  "Consolidated View Shipments":        "shipment",
  "All Exports Shipments":              "shipment",
  "Consignee and Shipper":              "shipment",
  "Consolidated View Shipper Shipments":"shipper_profile",
  "Shipper":                            "shipper_profile",
  "Consignee":                          "consignee_profile",
  "Contact Info":                       "contact",
  "HS Codes":                           "macro_trade",
  "Exporters":                          "macro_trade",
  "Importers":                          "macro_trade",
  "Trade Relationships":                "macro_trade",
  "HS Code (6-digit)":                  "hs_summary",
  "List of Ecommerce Sellers in VN":    "ecommerce",
};

function buildShipment(row: Row, file: string, sheet: string): Doc | null {
  const shipper   = s(row["Shipper"] ?? row["Shipper Name"]);
  const consignee = s(row["Consignee"]);
  if (!shipper && !consignee) return null;

  const date   = s(row["Date"]);
  const goods  = s(row["Goods Shipped"]);
  const hs     = s(row["HS Code"]);
  const val    = s(row["Value (USD)"]);
  const addr   = s(row["Shipper Full Address"]);
  const email  = s(row["Shipper Email 1"]);
  const phone  = s(row["Shipper Phone 1"]);
  const dest   = s(row["Shipment Destination"]);
  const portU  = s(row["Port of Unlading"]);
  const cat    = detectCategory(file);

  const parts: string[] = [];
  if (date)      parts.push(`Ngày giao dịch: ${date}.`);
  if (shipper)   parts.push(`Nhà xuất khẩu: ${shipper}.`);
  if (addr)      parts.push(`Địa chỉ: ${addr}.`);
  if (email)     parts.push(`Email: ${email}.`);
  if (phone)     parts.push(`SĐT: ${phone}.`);
  if (consignee) parts.push(`Nhà nhập khẩu: ${consignee}.`);
  if (goods)     parts.push(`Hàng hóa: ${goods}.`);
  if (cat)       parts.push(`Danh mục: ${cat}.`);
  if (hs)        parts.push(`HS Code: ${hs}.`);
  if (val)       parts.push(`Giá trị: ${val} USD.`);
  if (dest)      parts.push(`Điểm đến: ${dest}.`);
  if (portU)     parts.push(`Cảng dỡ hàng: ${portU}.`);

  return {
    id:   makeId(file, sheet, shipper, consignee, date, goods),
    text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "transaction",
      shipper_name: shipper.slice(0,200), consignee_name: consignee.slice(0,200),
      hs_code: hs.slice(0,20), product_category: cat.slice(0,100) },
  };
}

function buildShipperProfile(row: Row, file: string, sheet: string): Doc | null {
  const name = s(row["Shipper Name"]);
  if (!name) return null;
  const addr  = s(row["Shipper Full Address"]);
  const email = s(row["Shipper Email 1"] ?? row["UPDATE"]);
  const phone = s(row["Shipper Phone 1"]);
  const web   = s(row["Shipper Website 1"]);
  const ship  = s(row["Shipments"]);
  const val   = s(row["VALUE (usd)"]);
  const cat   = detectCategory(file);

  const parts = [`Hồ sơ nhà xuất khẩu: ${name}.`];
  if (cat)   parts.push(`Danh mục: ${cat}.`);
  if (addr)  parts.push(`Địa chỉ: ${addr}.`);
  if (email) parts.push(`Email: ${email}.`);
  if (phone) parts.push(`SĐT: ${phone}.`);
  if (web)   parts.push(`Website: ${web}.`);
  if (ship)  parts.push(`Số lô hàng: ${ship}.`);
  if (val)   parts.push(`Tổng giá trị: ${val} USD.`);

  return {
    id:   makeId(file, sheet, name),
    text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "company_profile",
      shipper_name: name.slice(0,200), email: email.slice(0,100),
      phone: phone.slice(0,50), website: web.slice(0,200), product_category: cat.slice(0,100) },
  };
}

function buildConsignee(row: Row, file: string, sheet: string): Doc | null {
  const name = s(row["Consignee"] ?? row["Consignee Name"]);
  if (!name) return null;
  const country = s(row["Consignee Country"]);
  const addr    = s(row["Consignee Full Address"]);
  const email   = s(row["Consignee Email 1"]);
  const val     = s(row["VALUE (usd)"]);
  const cat     = detectCategory(file);

  const parts = [`Hồ sơ nhà nhập khẩu: ${name}.`];
  if (country) parts.push(`Quốc gia: ${country}.`);
  if (cat)     parts.push(`Danh mục: ${cat}.`);
  if (addr)    parts.push(`Địa chỉ: ${addr}.`);
  if (email)   parts.push(`Email: ${email}.`);
  if (val)     parts.push(`Tổng giá trị nhập: ${val} USD.`);

  return {
    id:   makeId(file, sheet, name),
    text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "consignee_profile",
      consignee_name: name.slice(0,200), country: country.slice(0,100), email: email.slice(0,100) },
  };
}

function buildContact(row: Row, file: string, sheet: string): Doc | null {
  const company = s(row["Company"]);
  const name    = s(row["Contact Name"]);
  if (!company && !name) return null;
  const pos   = s(row["Position"]);
  const email = s(row["Email"]);
  const phone = s(row["Phone"]);
  const li    = s(row["Profile URL"]);

  const parts: string[] = [];
  if (name)    parts.push(`Người liên hệ: ${name}.`);
  if (pos)     parts.push(`Chức vụ: ${pos}.`);
  if (company) parts.push(`Công ty: ${company}.`);
  if (email)   parts.push(`Email: ${email}.`);
  if (phone)   parts.push(`SĐT: ${phone}.`);
  if (li)      parts.push(`LinkedIn: ${li}.`);

  return {
    id:   makeId(file, sheet, company, name, email),
    text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "contact",
      company_name: company.slice(0,200), contact_name: name.slice(0,100),
      position: pos.slice(0,100), email: email.slice(0,100) },
  };
}

function buildMacroTrade(row: Row, file: string, sheet: string): Doc | null {
  const yearCols = Object.keys(row).filter((k) => /^20(1|2)\d/.test(k));

  if (sheet === "HS Codes") {
    const hs = s(row["HS Code"]); if (!hs) return null;
    const sect = s(row["HS Section"]);
    const parts = [`Thống kê nhập khẩu Mỹ theo HS Code: ${hs}.`];
    if (sect) parts.push(`Ngành hàng: ${sect}.`);
    for (const y of yearCols) { const v = s(row[y]); if (v) parts.push(`Năm ${y.slice(0,4)}: ${v} USD.`); }
    return { id: makeId(file, sheet, hs), text: parts.join(" "),
      metadata: { source_file: file, sheet_name: sheet, data_type: "macro_trade", sub_type: "hs_code", hs_code: hs.slice(0,20) } };
  }

  if (sheet === "Exporters" || sheet === "Importers") {
    const country = s(row["Partner Country/Region"] ?? row["Reporting Country/Region"]); if (!country) return null;
    const role    = sheet === "Exporters" ? "xuất khẩu sang Mỹ" : "nhập khẩu";
    const parts   = [`Thống kê ${role}: ${country}.`];
    for (const y of yearCols) { const v = s(row[y]); if (v) parts.push(`Năm ${y.slice(0,4)}: ${v} USD.`); }
    return { id: makeId(file, sheet, country), text: parts.join(" "),
      metadata: { source_file: file, sheet_name: sheet, data_type: "macro_trade", sub_type: sheet.toLowerCase(), country: country.slice(0,100) } };
  }

  if (sheet === "Trade Relationships") {
    const rep  = s(row["Reporting Country/Region"]); if (!rep) return null;
    const part = s(row["Partner Country/Region"]);
    const parts = [`Quan hệ thương mại: ${rep} nhập khẩu từ ${part}.`];
    for (const y of yearCols) { const v = s(row[y]); if (v) parts.push(`Năm ${y.slice(0,4)}: ${v} USD.`); }
    return { id: makeId(file, sheet, rep, part), text: parts.join(" "),
      metadata: { source_file: file, sheet_name: sheet, data_type: "macro_trade", sub_type: "trade_relationship" } };
  }
  return null;
}

function buildHsSummary(row: Row, file: string, sheet: string): Doc | null {
  const hs = s(row["HS Code"]); if (!hs) return null;
  const desc = s(row["HS Code Description"]);
  const val  = s(row["VALUE (usd)"]);
  const cat  = detectCategory(file);
  const parts = [`Xuất khẩu Việt Nam theo HS Code ${hs}.`];
  if (desc) parts.push(`Mô tả: ${desc}.`);
  if (cat)  parts.push(`Danh mục: ${cat}.`);
  if (val)  parts.push(`Tổng giá trị: ${val} USD.`);
  return { id: makeId(file, sheet, hs), text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "trade_summary", hs_code: hs.slice(0,20) } };
}

function buildEcommerce(row: Row, file: string, sheet: string): Doc | null {
  const name = s(row["Customer Name"]); if (!name) return null;
  const product = s(row["Product"]);
  const city    = s(row["City"]);
  const phone   = s(row["Contact number"]);
  const parts = [`Người bán TMĐT Việt Nam: ${name}.`];
  if (product) parts.push(`Sản phẩm: ${product}.`);
  if (city)    parts.push(`Thành phố: ${city}.`);
  if (phone)   parts.push(`SĐT: ${phone}.`);
  return { id: makeId(file, sheet, name), text: parts.join(" "),
    metadata: { source_file: file, sheet_name: sheet, data_type: "ecommerce_seller",
      company_name: name.slice(0,200), product: product.slice(0,200) } };
}

export function processExcelBuffer(buffer: ArrayBuffer, filename: string): Doc[] {
  const wb    = XLSX.read(buffer, { type: "array" });
  const docs: Doc[] = [];

  for (const sheetName of wb.SheetNames) {
    if (SKIP_SHEETS.has(sheetName)) continue;

    const ws   = wb.Sheets[sheetName];
    const rows = XLSX.utils.sheet_to_json(ws, { defval: "" }) as Row[];
    if (!rows.length) continue;

    let dispatch = SHEET_DISPATCH[sheetName];
    if (!dispatch) {
      const cols = new Set(Object.keys(rows[0]));
      if (cols.has("Shipper Name") && cols.has("Shipments")) dispatch = "shipper_profile";
      else if (cols.has("Shipper") && cols.has("Goods Shipped")) dispatch = "shipment";
      else if (cols.has("Contact Name")) dispatch = "contact";
      else continue;
    }

    for (const row of rows) {
      let doc: Doc | null = null;
      if (dispatch === "shipment")        doc = buildShipment(row, filename, sheetName);
      else if (dispatch === "shipper_profile") doc = buildShipperProfile(row, filename, sheetName);
      else if (dispatch === "consignee_profile") doc = buildConsignee(row, filename, sheetName);
      else if (dispatch === "contact")    doc = buildContact(row, filename, sheetName);
      else if (dispatch === "macro_trade") doc = buildMacroTrade(row, filename, sheetName);
      else if (dispatch === "hs_summary") doc = buildHsSummary(row, filename, sheetName);
      else if (dispatch === "ecommerce")  doc = buildEcommerce(row, filename, sheetName);
      if (doc) docs.push(doc);
    }
  }

  return docs;
}
