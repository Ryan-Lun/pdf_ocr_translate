from __future__ import annotations

import json
import zipfile
from io import BytesIO

from app.services import glossary, state


def _write_glossary(path, items):
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_xlsx(rows):
    shared_strings = []
    shared_index = {}
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            text = str(value)
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            cell_ref = f"{chr(64 + col_idx)}{row_idx}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{shared_index[text]}</v></c>')
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    shared_xml = "".join(f"<si><t>{text}</t></si>" for text in shared_strings)
    sheet_xml = "".join(sheet_rows)
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as zf:
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
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
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
    return stream.getvalue()


def test_glossary_page_ok(client):
    resp = client.get("/workspace/glossary")
    assert resp.status_code == 200
    assert "詞彙庫管理" in resp.get_data(as_text=True)


def test_glossary_library_payload_and_user_override(client, tmp_path, monkeypatch):
    system_path = tmp_path / "system.json"
    global_path = tmp_path / "global.json"
    _write_glossary(system_path, [{"cn": "批號", "en": "Lot No."}, {"cn": "製造日期", "en": "Manufacturing Date"}])
    _write_glossary(global_path, [{"cn": "批號", "en": "Batch No."}])

    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    glossary.invalidate_glossary_cache()

    resp = client.get("/api/glossary/library")
    assert resp.status_code == 200
    payload = resp.get_json()

    assert payload["ok"] is True
    assert payload["system_glossary"] == [
        {"cn": "批號", "en": "Lot No."},
        {"cn": "製造日期", "en": "Manufacturing Date"},
    ]
    assert payload["user_glossary"] == [{"cn": "批號", "en": "Batch No."}]
    assert payload["effective_glossary"] == [
        {
            "cn": "批號",
            "en": "Batch No.",
            "source": "user",
            "overridden": True,
            "system_en": "Lot No.",
            "user_en": "Batch No.",
        },
        {
            "cn": "製造日期",
            "en": "Manufacturing Date",
            "source": "system",
            "overridden": False,
            "system_en": "Manufacturing Date",
            "user_en": None,
        },
    ]
    assert glossary.load_combined_glossary() == [
        ("製造日期", "Manufacturing Date"),
        ("批號", "Batch No."),
    ]


def test_glossary_post_updates_effective_override(client, tmp_path, monkeypatch):
    system_path = tmp_path / "system.json"
    global_path = tmp_path / "global.json"
    _write_glossary(system_path, [{"cn": "批號", "en": "Lot No."}])
    _write_glossary(global_path, [])

    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    glossary.invalidate_glossary_cache()

    save_resp = client.post(
        "/api/glossary",
        json={"glossary": [{"cn": "批號", "en": "Batch No."}]},
    )
    assert save_resp.status_code == 200

    payload = client.get("/api/glossary/library").get_json()
    effective = payload["effective_glossary"]
    assert effective[0]["cn"] == "批號"
    assert effective[0]["source"] == "user"
    assert effective[0]["overridden"] is True
    assert effective[0]["en"] == "Batch No."


def test_system_glossary_excel_preview_and_apply(client, tmp_path, monkeypatch):
    global_path = tmp_path / "global.json"
    system_path = tmp_path / "system.json"
    _write_glossary(system_path, [{"cn": "批號", "en": "Lot No."}, {"cn": "製造日期", "en": "Manufacturing Date"}])
    _write_glossary(global_path, [])
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    glossary.invalidate_glossary_cache()

    workbook = _build_xlsx(
        [
            ["cn", "en"],
            ["批號", "Batch No."],
            ["新詞", "New Term"],
            ["新詞", "New Term 2"],
            ["缺英文", ""],
        ]
    )
    preview_resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "system.xlsx")},
        content_type="multipart/form-data",
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.get_json()
    assert preview["ok"] is True
    assert preview["summary"] == {
        "incoming": 2,
        "additions": 1,
        "updates": 1,
        "unchanged": 0,
    }
    assert len(preview["duplicates"]) == 1
    assert len(preview["invalid_rows"]) == 1

    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "items": preview["items"],
            "duplicates": preview["duplicates"],
            "invalid_rows": preview["invalid_rows"],
        },
    )
    assert apply_resp.status_code == 400
    payload = apply_resp.get_json()
    assert payload["ok"] is False
    assert "重複詞彙列" in payload["error"]


def test_system_glossary_excel_apply_succeeds_without_blocking_issues(client, tmp_path, monkeypatch):
    global_path = tmp_path / "global.json"
    system_path = tmp_path / "system.json"
    _write_glossary(system_path, [{"cn": "批號", "en": "Lot No."}])
    _write_glossary(global_path, [])
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    glossary.invalidate_glossary_cache()

    workbook = _build_xlsx(
        [
            ["cn", "en"],
            ["批號", "Batch No."],
            ["新詞", "New Term"],
        ]
    )
    preview_resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "system.xlsx")},
        content_type="multipart/form-data",
    )
    preview = preview_resp.get_json()
    assert preview["duplicates"] == []
    assert preview["invalid_rows"] == []

    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "items": preview["items"],
            "duplicates": preview["duplicates"],
            "invalid_rows": preview["invalid_rows"],
        },
    )
    assert apply_resp.status_code == 200
    payload = apply_resp.get_json()
    assert payload["ok"] is True
    assert payload["system_glossary"] == [
        {"cn": "批號", "en": "Batch No."},
        {"cn": "新詞", "en": "New Term"},
    ]


def test_system_glossary_excel_preview_requires_cn_en_header(client):
    workbook = _build_xlsx(
        [
            ["source", "target"],
            ["批號", "Batch No."],
        ]
    )
    resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "bad.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "cn" in payload["error"]


def test_system_glossary_export_returns_xlsx(client, tmp_path, monkeypatch):
    system_path = tmp_path / "system.json"
    global_path = tmp_path / "global.json"
    _write_glossary(system_path, [{"cn": "批號", "en": "Lot No."}])
    _write_glossary(global_path, [])
    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    glossary.invalidate_glossary_cache()

    resp = client.get("/api/glossary/system-export")
    assert resp.status_code == 200
    assert resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "system_glossary.xlsx" in resp.headers.get("Content-Disposition", "")
    parsed = glossary.parse_system_glossary_excel(resp.data)
    assert parsed["items"] == [{"cn": "批號", "en": "Lot No."}]
