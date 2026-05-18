from __future__ import annotations

import json
import re
import threading
import zipfile
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree as ET

from . import state

try:
    import xlsxwriter
except Exception:  # pragma: no cover - optional dependency in runtime env
    xlsxwriter = None

_PROTECTED_TERM_PREFIX = "[[[GLOSSARY_TERM_"
_PROTECTED_TERM_PATTERN = re.compile(r"\[\[\[GLOSSARY_TERM_\d+::(.*?)\]\]\]")
_SPREADSHEET_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_GLOSSARY_CACHE_LOCK = threading.Lock()
_GLOBAL_GLOSSARY_CACHE: tuple[Path, float | None, list[dict[str, str]]] | None = None
_COMBINED_GLOSSARY_CACHE: tuple[
    tuple[tuple[str, float | None], ...],
    list[tuple[str, str]],
] | None = None
_SYSTEM_GLOSSARY_CACHE: tuple[
    tuple[tuple[str, float | None], ...],
    list[dict[str, str]],
] | None = None


def global_glossary_path() -> Path:
    return Path(state.GLOBAL_GLOSSARY_PATH)


def system_glossary_path() -> Path:
    return Path(state.SYSTEM_GLOSSARY_PATH)


def _resolve_glossary_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = state.BASE_DIR / path
    return path


def _path_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def invalidate_glossary_cache() -> None:
    global _GLOBAL_GLOSSARY_CACHE, _COMBINED_GLOSSARY_CACHE, _SYSTEM_GLOSSARY_CACHE
    with _GLOSSARY_CACHE_LOCK:
        _GLOBAL_GLOSSARY_CACHE = None
        _COMBINED_GLOSSARY_CACHE = None
        _SYSTEM_GLOSSARY_CACHE = None


def _clean_glossary_items(data: object) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        cleaned.append({"cn": cn, "en": en})
    return cleaned


def load_global_glossary() -> list[dict[str, str]]:
    global _GLOBAL_GLOSSARY_CACHE
    path = global_glossary_path()
    current_mtime = _path_mtime(path)
    with _GLOSSARY_CACHE_LOCK:
        cached = _GLOBAL_GLOSSARY_CACHE
        if cached and cached[0] == path and cached[1] == current_mtime:
            return list(cached[2])

    if current_mtime is None:
        cleaned: list[dict[str, str]] = []
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cleaned = []
        else:
            cleaned = _clean_glossary_items(data)

    with _GLOSSARY_CACHE_LOCK:
        _GLOBAL_GLOSSARY_CACHE = (path, current_mtime, cleaned)
    return list(cleaned)


def write_global_glossary(items: list[dict[str, str]]) -> None:
    payload: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        key = (cn, en)
        if key in seen:
            continue
        payload.append({"cn": cn, "en": en})
        seen.add(key)
    path = global_glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    invalidate_glossary_cache()


def write_system_glossary(items: list[dict[str, str]]) -> None:
    payload: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en or cn in seen:
            continue
        payload.append({"cn": cn, "en": en})
        seen.add(cn)
    path = system_glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    invalidate_glossary_cache()


def _system_glossary_paths() -> tuple[Path, ...]:
    if not state.SYSTEM_GLOSSARY_PATH:
        return tuple()
    return (_resolve_glossary_path(state.SYSTEM_GLOSSARY_PATH),)


def load_system_glossary() -> list[dict[str, str]]:
    global _SYSTEM_GLOSSARY_CACHE
    paths = _system_glossary_paths()
    cache_key = tuple((str(path), _path_mtime(path)) for path in paths)
    with _GLOSSARY_CACHE_LOCK:
        cached = _SYSTEM_GLOSSARY_CACHE
        if cached and cached[0] == cache_key:
            return [dict(item) for item in cached[1]]

    entries_by_cn: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in _clean_glossary_items(data):
            entries_by_cn[item["cn"]] = item["en"]

    cleaned = [
        {"cn": cn, "en": en}
        for cn, en in sorted(entries_by_cn.items(), key=lambda pair: pair[0])
    ]
    with _GLOSSARY_CACHE_LOCK:
        _SYSTEM_GLOSSARY_CACHE = (cache_key, cleaned)
    return [dict(item) for item in cleaned]


def load_glossary_entries() -> list[tuple[str, str]]:
    global _COMBINED_GLOSSARY_CACHE
    paths = _system_glossary_paths()
    if state.GLOBAL_GLOSSARY_PATH:
        paths = paths + (_resolve_glossary_path(state.GLOBAL_GLOSSARY_PATH),)
    cache_key = tuple((str(path), _path_mtime(path)) for path in paths)
    with _GLOSSARY_CACHE_LOCK:
        cached = _COMBINED_GLOSSARY_CACHE
        if cached and cached[0] == cache_key:
            return list(cached[1])

    entries_by_cn: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in _clean_glossary_items(data):
            entries_by_cn[item["cn"]] = item["en"]
    entries = list(entries_by_cn.items())
    entries.sort(key=lambda pair: len(pair[0]), reverse=True)
    with _GLOSSARY_CACHE_LOCK:
        _COMBINED_GLOSSARY_CACHE = (cache_key, entries)
    return list(entries)


def load_combined_glossary() -> list[tuple[str, str]]:
    return load_glossary_entries()


def build_glossary_management_payload() -> dict[str, list[dict[str, str | bool | None]]]:
    system_items = load_system_glossary()
    user_items = load_global_glossary()
    system_by_cn = {item["cn"]: item["en"] for item in system_items}
    user_by_cn = {item["cn"]: item["en"] for item in user_items}

    effective_items: list[dict[str, str | bool | None]] = []
    for cn in sorted(set(system_by_cn) | set(user_by_cn)):
        system_en = system_by_cn.get(cn)
        user_en = user_by_cn.get(cn)
        has_user = user_en is not None
        effective_items.append(
            {
                "cn": cn,
                "en": user_en if has_user else system_en or "",
                "source": "user" if has_user else "system",
                "overridden": bool(has_user and system_en is not None),
                "system_en": system_en,
                "user_en": user_en,
            }
        )

    return {
        "system_glossary": system_items,
        "user_glossary": user_items,
        "effective_glossary": effective_items,
    }


def _excel_column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return max(0, index - 1)


def _load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for node in root.findall("x:si", _SPREADSHEET_NS):
        parts = [
            text_node.text or ""
            for text_node in node.findall(".//x:t", _SPREADSHEET_NS)
        ]
        values.append("".join(parts))
    return values


def _resolve_first_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    first_sheet = workbook.find("x:sheets/x:sheet", _SPREADSHEET_NS)
    if first_sheet is None:
        raise ValueError("Excel 檔案沒有工作表。")
    rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if not rel_id:
        raise ValueError("找不到工作表關聯。")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        if rel.attrib.get("Id") != rel_id:
            continue
        target = rel.attrib.get("Target") or ""
        normalized = target.lstrip("/")
        if normalized.startswith("xl/"):
            return normalized
        return f"xl/{normalized}"
    raise ValueError("找不到第一張工作表。")


def _read_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall("x:sheetData/x:row", _SPREADSHEET_NS):
        row_values: list[str] = []
        for cell in row.findall("x:c", _SPREADSHEET_NS):
            col_index = _excel_column_index(cell.attrib.get("r", ""))
            while len(row_values) <= col_index:
                row_values.append("")
            cell_type = cell.attrib.get("t")
            value_node = cell.find("x:v", _SPREADSHEET_NS)
            inline_node = cell.find("x:is/x:t", _SPREADSHEET_NS)
            if inline_node is not None:
                value = inline_node.text or ""
            elif value_node is None or value_node.text is None:
                value = ""
            elif cell_type == "s":
                try:
                    value = shared_strings[int(value_node.text)]
                except Exception:
                    value = ""
            else:
                value = value_node.text
            row_values[col_index] = str(value or "")
        rows.append(row_values)
    return rows


def parse_system_glossary_excel(file_bytes: bytes) -> dict[str, object]:
    try:
        workbook = zipfile.ZipFile(BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("無法解析 Excel 檔案，請上傳 .xlsx 格式。") from exc

    with workbook as zf:
        shared_strings = _load_shared_strings(zf)
        sheet_path = _resolve_first_sheet_path(zf)
        rows = _read_sheet_rows(zf, sheet_path, shared_strings)

    if not rows:
        raise ValueError("Excel 檔案沒有資料。")

    header = [str(value or "").strip().lower() for value in rows[0]]
    if "cn" not in header or "en" not in header:
        raise ValueError("Excel 第一列必須包含 cn 與 en 欄位。")
    cn_index = header.index("cn")
    en_index = header.index("en")

    entries: list[dict[str, str]] = []
    duplicates: list[dict[str, str | int]] = []
    invalid_rows: list[dict[str, str | int]] = []
    seen: dict[str, str] = {}

    for row_number, row in enumerate(rows[1:], start=2):
        cn = str(row[cn_index] if cn_index < len(row) else "").strip()
        en = str(row[en_index] if en_index < len(row) else "").strip()
        if not cn and not en:
            continue
        if not cn or not en:
            invalid_rows.append({"row": row_number, "cn": cn, "en": en, "reason": "cn 欄位缺少中文詞彙或 en 欄位缺少英文詞彙"})
            continue
        if cn in seen:
            duplicates.append({"row": row_number, "cn": cn, "previous_en": seen[cn], "en": en})
        seen[cn] = en

    for cn, en in seen.items():
        entries.append({"cn": cn, "en": en})
    entries.sort(key=lambda item: item["cn"])
    return {
        "items": entries,
        "duplicates": duplicates,
        "invalid_rows": invalid_rows,
        "total_rows": max(0, len(rows) - 1),
    }


def build_system_glossary_import_preview(items: list[dict[str, str]]) -> dict[str, object]:
    current_items = load_system_glossary()
    current_by_cn = {item["cn"]: item["en"] for item in current_items}
    additions = 0
    updates = 0
    unchanged = 0
    preview_rows: list[dict[str, str | None]] = []

    for item in items:
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        current_en = current_by_cn.get(cn)
        if current_en is None:
            status = "add"
            additions += 1
        elif current_en != en:
            status = "update"
            updates += 1
        else:
            status = "unchanged"
            unchanged += 1
        preview_rows.append(
            {
                "cn": cn,
                "current_en": current_en,
                "next_en": en,
                "status": status,
            }
        )

    preview_rows.sort(key=lambda item: (str(item["status"]), str(item["cn"])))
    return {
        "items": items,
        "preview_rows": preview_rows,
        "summary": {
            "incoming": len(items),
            "additions": additions,
            "updates": updates,
            "unchanged": unchanged,
        },
    }


def apply_system_glossary_import(items: list[dict[str, str]]) -> list[dict[str, str]]:
    merged_by_cn = {item["cn"]: item["en"] for item in load_system_glossary()}
    for item in items:
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        merged_by_cn[cn] = en
    merged_items = [
        {"cn": cn, "en": en}
        for cn, en in sorted(merged_by_cn.items(), key=lambda pair: pair[0])
    ]
    write_system_glossary(merged_items)
    return merged_items


def _escape_xml_text(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _build_xlsx_bytes(rows: list[list[str]], sheet_name: str = "Sheet1") -> bytes:
    shared_strings: list[str] = []
    shared_index: dict[str, int] = {}
    sheet_rows: list[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_idx, value in enumerate(row, start=1):
            text = str(value or "")
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            col_name = ""
            current = col_idx
            while current > 0:
                current, remainder = divmod(current - 1, 26)
                col_name = chr(65 + remainder) + col_name
            cell_ref = f"{col_name}{row_idx}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{shared_index[text]}</v></c>')
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    shared_xml = "".join(f"<si><t>{_escape_xml_text(text)}</t></si>" for text in shared_strings)
    sheet_xml = "".join(sheet_rows)
    sheet_name_xml = _escape_xml_text(sheet_name)
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{sheet_name_xml}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">
  {shared_xml}
</sst>""",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {sheet_xml}
  </sheetData>
</worksheet>""",
        )
    return output.getvalue()


def export_system_glossary_excel() -> bytes:
    items = load_system_glossary()
    if xlsxwriter is None:
        rows = [["cn", "en"]]
        rows.extend([[item["cn"], item["en"]] for item in items])
        return _build_xlsx_bytes(rows, sheet_name="SystemGlossary")

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("SystemGlossary")
    header_format = workbook.add_format({"bold": True})
    worksheet.write(0, 0, "cn", header_format)
    worksheet.write(0, 1, "en", header_format)
    for row_index, item in enumerate(items, start=1):
        worksheet.write(row_index, 0, item["cn"])
        worksheet.write(row_index, 1, item["en"])
    worksheet.set_column(0, 0, 36)
    worksheet.set_column(1, 1, 54)
    workbook.close()
    return output.getvalue()


def apply_glossary(text: str, entries: list[tuple[str, str]] | None = None) -> str:
    if not text:
        return text
    entries = entries or load_glossary_entries()
    if not entries:
        return text
    out = text
    hits: list[tuple[str, str]] = []
    for cn, en in entries:
        if cn in out:
            out = out.replace(cn, en)
            hits.append((cn, en))
    if hits:
        preview = ", ".join([f"{cn}->{en}" for cn, en in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] hits={len(hits)} {preview}{more}")
    return out


def apply_glossary_with_protection(
    text: str,
    entries: list[tuple[str, str]] | None = None,
) -> str:
    if not text:
        return text
    entries = entries or load_glossary_entries()
    if not entries:
        return text

    out_parts: list[str] = []
    hits: list[tuple[str, str]] = []
    i = 0
    term_index = 1
    while i < len(text):
        matched = False
        for cn, en in entries:
            if not cn or not en:
                continue
            if text.startswith(cn, i):
                protected = f"{_PROTECTED_TERM_PREFIX}{term_index:04d}::{en}]]]"
                out_parts.append(protected)
                hits.append((cn, en))
                i += len(cn)
                term_index += 1
                matched = True
                break
        if matched:
            continue
        out_parts.append(text[i])
        i += 1

    if hits:
        preview = ", ".join([f"{cn}->{en}" for cn, en in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] protected_hits={len(hits)} {preview}{more}")
    return "".join(out_parts)


def restore_protected_glossary_terms(text: str) -> str:
    if not text or _PROTECTED_TERM_PREFIX not in text:
        return text
    return _PROTECTED_TERM_PATTERN.sub(lambda match: match.group(1), text)
