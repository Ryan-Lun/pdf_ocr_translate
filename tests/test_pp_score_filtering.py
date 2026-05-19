from app.services import ocr, state
from ocr_pipeline.pipeline import filter_ppstructure_data_by_score


def test_filter_ppstructure_data_by_score_keeps_blocks_and_sets_block_score():
    payload = {
        "parsing_res_list": [
            {"block_content": "keep", "block_score": 0.9},
            {"block_content": "drop", "block_score": 0.2},
        ]
    }

    filtered = filter_ppstructure_data_by_score(payload, 0.5)

    assert len(filtered["parsing_res_list"]) == 2
    assert filtered["parsing_res_list"][0]["block_score"] == 0.9
    assert filtered["parsing_res_list"][1]["block_score"] == 0.2


def test_load_pp_pages_keeps_blocks_and_sets_block_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "OCR_MIN_LINE_SCORE", 0.5)
    job_dir = tmp_path / "job"
    pp_dir = job_dir / "pp_json"
    pp_dir.mkdir(parents=True)
    (pp_dir / "page_p0001.json").write_text(
        """
        {
          "parsing_res_list": [
            {
              "block_content": "keep",
              "block_bbox": [0, 0, 10, 10],
              "block_label": "text",
              "block_score": 0.9,
              "should_translate": true
            },
            {
              "block_content": "drop",
              "block_bbox": [0, 20, 10, 30],
              "block_label": "text",
              "block_score": 0.2,
              "should_translate": true
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    pages = ocr.load_pp_pages(job_dir)

    assert len(pages[0]["parsing_res_list"]) == 2
    assert pages[0]["parsing_res_list"][0]["block_content"] == "keep"
    assert pages[0]["parsing_res_list"][0]["block_score"] == 0.9
    assert pages[0]["parsing_res_list"][1]["block_content"] == "drop"
    assert pages[0]["parsing_res_list"][1]["block_score"] == 0.2


def test_filter_ppstructure_data_derives_score_from_overall_ocr():
    payload = {
        "parsing_res_list": [
            {
                "block_content": "drop",
                "block_bbox": [0, 0, 20, 20],
                "block_label": "text",
            },
            {
                "block_content": "keep",
                "block_bbox": [0, 30, 20, 50],
                "block_label": "text",
            },
        ],
        "overall_ocr_res": {
            "rec_polys": [
                [[0, 0], [20, 0], [20, 20], [0, 20]],
                [[0, 30], [20, 30], [20, 50], [0, 50]],
            ],
            "rec_scores": [0.2, 0.9],
        },
    }

    filtered = filter_ppstructure_data_by_score(payload, 0.5)

    assert len(filtered["parsing_res_list"]) == 2
    assert filtered["parsing_res_list"][0]["block_content"] == "drop"
    assert filtered["parsing_res_list"][0]["block_score"] == 0.2
    assert filtered["parsing_res_list"][1]["block_content"] == "keep"
    assert filtered["parsing_res_list"][1]["block_score"] == 0.9
