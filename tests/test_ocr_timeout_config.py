from __future__ import annotations

import importlib
from pathlib import Path
from types import SimpleNamespace

from app.services import jobs, ocr, pp_structure, state
from ocr_pipeline import pipeline


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {
            "errorCode": 0,
            "result": {
                "tableRecResults": [
                    {
                        "prunedResult": {
                            "parsing_res_list": [],
                            "overall_ocr_res": {
                                "rec_polys": [],
                                "rec_texts": [],
                                "rec_scores": [],
                            },
                        }
                    }
                ]
            },
        }

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_state_reads_table_recogntion_v2_env(monkeypatch):
    monkeypatch.setenv("TABLE_RECOGNTION_V2_URL", "https://example.test/table")
    monkeypatch.setenv("TABLE_RECOGNTION_V2TIMEOUT_SECONDS", "33.5")

    reloaded = importlib.reload(state)

    try:
        assert reloaded.TABLE_RECOGNTION_V2_URL == "https://example.test/table"
        assert reloaded.TRITON_URL == "https://example.test/table"
        assert reloaded.TABLE_RECOGNTION_V2TIMEOUT_SECONDS == 33.5
        assert reloaded.OCR_API_TIMEOUT_SECONDS == 33.5
        assert reloaded.REGION_OCR_API_TIMEOUT_SECONDS == 33.5
    finally:
        importlib.reload(state)


def test_ocr_pipeline_allows_subsecond_table_recogntion_v2_timeout(monkeypatch):
    monkeypatch.setenv("TABLE_RECOGNTION_V2TIMEOUT_SECONDS", "0.1")

    reloaded = importlib.reload(pipeline)

    try:
        assert reloaded.DEFAULT_TABLE_RECOGNTION_V2TIMEOUT_SECONDS == 0.1
    finally:
        importlib.reload(pipeline)


def test_ocr_pipeline_uses_table_recogntion_v2_timeout(tmp_path, monkeypatch):
    captured: dict[str, float] = {}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(pipeline, "DEFAULT_TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 12.5)
    monkeypatch.setattr(pipeline.cv2, "imread", lambda path: SimpleNamespace(shape=(10, 20, 3)))

    def fake_post(url, *, json, timeout):
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(pipeline.requests, "post", fake_post)

    pipeline.run_layout_parsing_predict([image_path], tmp_path / "json", triton_url="http://ocr")

    assert captured["timeout"] == 12.5


def test_ocr_pipeline_retries_table_recogntion_v2_request(tmp_path, monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr(pipeline, "DEFAULT_TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 12.5)
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("Request timed out.")
        return _Response()

    monkeypatch.setattr(pipeline.requests, "post", fake_post)

    output = pipeline._post_table_recogntion_v2(
        url="http://ocr",
        payload={"file": "x"},
        image_path=tmp_path / "page.png",
    )

    assert output["errorCode"] == 0
    assert attempts["count"] == 3


def test_ocr_pipeline_fails_after_three_table_recogntion_v2_attempts(tmp_path, monkeypatch):
    attempts = {"count": 0}
    warnings: list[str] = []
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pipeline, "DEFAULT_TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 1.0)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        raise pipeline.requests.exceptions.ReadTimeout(
            "HTTPConnectionPool(host='192.168.12.66', port=8080): Read timed out. (read timeout=1.0)"
        )

    monkeypatch.setattr(pipeline.requests, "post", fake_post)

    try:
        pipeline._post_table_recogntion_v2(
            url="http://ocr",
            payload={"file": "x"},
            image_path=tmp_path / "page.png",
            progress_cb=lambda *_args: warnings.append(_args[-1]),
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "TABLE RECOGNTION V2 API 請求連續失敗 3 次" in message
        assert "Request timed out. (read timeout=1s)" in message
        assert "192.168.12.66" not in message
        assert "port=8080" not in message
    else:
        raise AssertionError("expected RuntimeError")

    assert attempts["count"] == 3
    assert warnings
    assert all("192.168.12.66" not in warning for warning in warnings)
    assert all("port=8080" not in warning for warning in warnings)


def test_ocr_pipeline_stops_after_three_total_table_recogntion_v2_failures(tmp_path, monkeypatch):
    attempts = {"count": 0}
    warnings: list[str] = []
    image_paths = [tmp_path / "page1.png", tmp_path / "page2.png"]
    for path in image_paths:
        path.write_bytes(b"fake image")
    monkeypatch.setattr(pipeline, "DEFAULT_TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pipeline.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pipeline.cv2, "imread", lambda path: SimpleNamespace(shape=(10, 20, 3)))

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] in {1, 2, 4}:
            raise TimeoutError("Request timed out.")
        return _Response()

    monkeypatch.setattr(pipeline.requests, "post", fake_post)

    try:
        pipeline.run_layout_parsing_predict(
            image_paths,
            tmp_path / "json",
            triton_url="http://ocr",
            progress_cb=lambda *_args: warnings.append(_args[-1]),
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "TABLE RECOGNTION V2 API 請求累計失敗 3 次" in message
        assert "Request timed out. (read timeout=0.1s)" in message
    else:
        raise AssertionError("expected RuntimeError")

    failure_warnings = [warning for warning in warnings if "請求失敗" in warning]
    assert failure_warnings == [
        "第 1 頁第 1 次 TABLE RECOGNTION V2 API 請求失敗（累計 1/3）：Request timed out. (read timeout=0.1s)",
        "第 1 頁第 2 次 TABLE RECOGNTION V2 API 請求失敗（累計 2/3）：Request timed out. (read timeout=0.1s)",
        "第 2 頁第 1 次 TABLE RECOGNTION V2 API 請求失敗（累計 3/3）：Request timed out. (read timeout=0.1s)",
    ]


def test_region_ocr_uses_table_recogntion_v2_timeout(tmp_path, monkeypatch):
    captured: dict[str, float] = {}
    image_path = tmp_path / "page.png"

    class _Image:
        shape = (100, 200, 3)

        def __getitem__(self, key):
            return SimpleNamespace(size=100)

    class _Encoded:
        def tobytes(self):
            return b"encoded"

    monkeypatch.setattr(state, "TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 3.5)
    monkeypatch.setattr(ocr, "load_page_json_data", lambda job_dir, page_idx: {})
    monkeypatch.setattr(ocr, "resolve_page_image_path", lambda job_dir, page_data: image_path)
    monkeypatch.setattr(ocr.cv2, "imread", lambda path: _Image())
    monkeypatch.setattr(ocr.cv2, "imencode", lambda ext, crop: (True, _Encoded()))

    def fake_post(url, *, json, timeout):
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(ocr.requests, "post", fake_post)

    result = ocr.run_region_ocr(tmp_path, 0, {"x": 0, "y": 0, "w": 10, "h": 10})

    assert captured["timeout"] == 3.5
    assert result["page_index_0based"] == 0


def test_region_ocr_retries_table_recogntion_v2_request(monkeypatch):
    attempts = {"count": 0}
    monkeypatch.setattr(state, "TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 3.5)
    monkeypatch.setattr(ocr.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("Request timed out.")
        return _Response()

    monkeypatch.setattr(ocr.requests, "post", fake_post)

    output = ocr._post_table_recogntion_v2({"file": "x"})

    assert output["errorCode"] == 0
    assert attempts["count"] == 3


def test_region_ocr_timeout_error_hides_connection_details(monkeypatch):
    monkeypatch.setattr(state, "TABLE_RECOGNTION_V2TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(ocr.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        raise ocr.requests.exceptions.ReadTimeout(
            "HTTPConnectionPool(host='192.168.12.66', port=8080): Read timed out. (read timeout=1.0)"
        )

    monkeypatch.setattr(ocr.requests, "post", fake_post)

    try:
        ocr._post_table_recogntion_v2({"file": "x"})
    except RuntimeError as exc:
        message = str(exc)
        assert "TABLE RECOGNTION V2 API 請求連續失敗 3 次" in message
        assert "Request timed out. (read timeout=1s)" in message
        assert "192.168.12.66" not in message
        assert "port=8080" not in message
    else:
        raise AssertionError("expected RuntimeError")


def test_job_message_sanitizer_hides_connection_pool_endpoint():
    message = (
        "錯誤原因：TABLE RECOGNTION V2 API 請求連續失敗 3 次，已中斷任務："
        "HTTPConnectionPool(host='192.168.12.66', port=8080): Read timed out. "
        "(read timeout=1.0) 請向系統管理員回報此問題。"
    )

    sanitized = jobs.sanitize_job_message(message)

    assert sanitized is not None
    assert "Read timed out. (read timeout=1.0)" in sanitized
    assert "192.168.12.66" not in sanitized
    assert "port=8080" not in sanitized


def test_pp_structure_uses_configured_timeout(tmp_path, monkeypatch):
    captured: dict[str, float] = {}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")

    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 45.5)

    def fake_post(url, *, json, timeout):
        captured["timeout"] = timeout
        return _Response({"ok": True})

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    assert pp_structure._request_layout_parsing(image_path) == {"ok": True}
    assert captured["timeout"] == 45.5


def test_pp_structure_retries_request(tmp_path, monkeypatch):
    attempts = {"count": 0}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("Request timed out.")
        return _Response({"ok": True})

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    assert pp_structure._request_layout_parsing(image_path) == {"ok": True}
    assert attempts["count"] == 3


def test_pp_structure_reports_retry_warning(tmp_path, monkeypatch):
    attempts = {"count": 0}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")
    warnings: list[str] = []
    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("Request timed out.")
        return _Response({"ok": True})

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    assert pp_structure._request_layout_parsing(
        image_path,
        warning_callback=warnings.append,
    ) == {"ok": True}
    assert warnings == [
        "第 1 次 PDF 重建結構 API 請求失敗：Request timed out. (read timeout=0.1s)",
        "第 2 次 PDF 重建結構 API 請求失敗：Request timed out. (read timeout=0.1s)",
    ]


def test_pp_structure_retry_warning_includes_page_number(tmp_path, monkeypatch):
    attempts = {"count": 0}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")
    warnings: list[str] = []
    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise TimeoutError("Request timed out.")
        return _Response({"ok": True})

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    assert pp_structure._request_layout_parsing(
        image_path,
        page_number=2,
        warning_callback=warnings.append,
    ) == {"ok": True}
    assert warnings == [
        "第 2 頁第 1 次 PDF 重建結構 API 請求失敗：Request timed out. (read timeout=0.1s)",
    ]


def test_pp_structure_stops_after_three_total_failures_across_pages(tmp_path, monkeypatch):
    attempts = {"count": 0}
    page_paths = [tmp_path / "page1.png", tmp_path / "page2.png"]
    for path in page_paths:
        path.write_bytes(b"fake image")
    warnings: list[str] = []
    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pp_structure, "render_pdf_pages", lambda pdf_path, out_dir, dpi=150: page_paths)
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        if attempts["count"] in {1, 2, 4}:
            raise TimeoutError("Request timed out.")
        return _Response({"result": {"layoutParsingResults": []}})

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    try:
        pp_structure.extract_pdf_to_markdown(
            tmp_path / "source.pdf",
            tmp_path / "out",
            warning_callback=warnings.append,
        )
    except RuntimeError as exc:
        message = str(exc)
        assert "PDF 重建結構 API 請求累計失敗 3 次" in message
        assert "Request timed out. (read timeout=0.1s)" in message
    else:
        raise AssertionError("expected RuntimeError")

    assert warnings == [
        "第 1 頁第 1 次 PDF 重建結構 API 請求失敗（累計 1/3）：Request timed out. (read timeout=0.1s)",
        "第 1 頁第 2 次 PDF 重建結構 API 請求失敗（累計 2/3）：Request timed out. (read timeout=0.1s)",
        "第 2 頁第 1 次 PDF 重建結構 API 請求失敗（累計 3/3）：Request timed out. (read timeout=0.1s)",
    ]


def test_pp_structure_fails_after_three_attempts(tmp_path, monkeypatch):
    attempts = {"count": 0}
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")
    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        attempts["count"] += 1
        raise TimeoutError("Request timed out.")

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    try:
        pp_structure._request_layout_parsing(image_path)
    except RuntimeError as exc:
        message = str(exc)
        assert "PDF 重建結構 API 請求連續失敗 3 次" in message
        assert "Request timed out. (read timeout=0.1s)" in message
    else:
        raise AssertionError("expected RuntimeError")

    assert attempts["count"] == 3


def test_pp_structure_timeout_error_hides_connection_details(tmp_path, monkeypatch):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"fake image")
    monkeypatch.setattr(state, "PP_STRUCTURE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pp_structure.time, "sleep", lambda seconds: None)

    def fake_post(url, *, json, timeout):
        raise pp_structure.requests.exceptions.ReadTimeout(
            "HTTPConnectionPool(host='192.168.12.66', port=8080): Read timed out. (read timeout=0.1)"
        )

    monkeypatch.setattr(pp_structure.requests, "post", fake_post)

    try:
        pp_structure._request_layout_parsing(image_path)
    except RuntimeError as exc:
        message = str(exc)
        assert "PDF 重建結構 API 請求連續失敗 3 次" in message
        assert "Request timed out. (read timeout=0.1s)" in message
        assert "192.168.12.66" not in message
        assert "port=8080" not in message
    else:
        raise AssertionError("expected RuntimeError")
