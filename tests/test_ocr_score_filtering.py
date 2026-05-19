from pathlib import Path

from app.services import ocr, state


def test_load_page_data_skips_low_score_entries(monkeypatch):
    monkeypatch.setattr(state, "OCR_MIN_LINE_SCORE", 0.5)
    payload = {
        "page_index_0based": 0,
        "input_path": "page.png",
        "coord_transform": {"image_size_px": [100, 100]},
        "rec_polys": [
            [[0, 0], [10, 0], [10, 10], [0, 10]],
            [[20, 0], [30, 0], [30, 10], [20, 10]],
        ],
        "rec_texts": ["keep", "drop"],
        "edit_texts": ["keep edit", "drop edit"],
        "rec_scores": [0.9, 0.2],
    }

    page = ocr.load_page_data(Path("dummy.json"), data=payload)

    assert page["rec_texts"] == ["keep"]
    assert page["edit_texts"] == ["keep edit"]
    assert page["rec_scores"] == [0.9]


def test_load_ocr_pages_skips_low_score_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "OCR_MIN_LINE_SCORE", 0.5)
    job_dir = tmp_path / "job"
    json_dir = job_dir / "ocr_json"
    json_dir.mkdir(parents=True)
    (json_dir / "0001_res_with_pdf_coords.json").write_text(
        """
        {
          "page_index_0based": 0,
          "input_path": "page.png",
          "rec_polys": [
            [[0, 0], [10, 0], [10, 10], [0, 10]],
            [[20, 0], [30, 0], [30, 10], [20, 10]]
          ],
          "rec_texts": ["keep", "drop"],
          "edit_texts": ["keep edit", "drop edit"],
          "rec_scores": [0.9, 0.2]
        }
        """,
        encoding="utf-8",
    )

    pages = ocr.load_ocr_pages(job_dir)

    assert len(pages) == 1
    assert pages[0]["rec_texts"] == ["keep"]
    assert pages[0]["edit_texts"] == ["keep edit"]
    assert pages[0]["rec_scores"] == [0.9]
