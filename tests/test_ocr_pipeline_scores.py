from ocr_pipeline.pipeline import extract_rec_entries_from_ppstructure


def test_extract_rec_entries_filters_low_score_lines_only():
    data = {
        "parsing_res_list": [
            {
                "block_label": "text",
                "block_bbox": [0, 0, 100, 20],
                "block_content": "keep paragraph",
                "block_score": 0.9,
            },
            {
                "block_label": "text",
                "block_bbox": [0, 30, 100, 50],
                "block_content": "drop paragraph",
                "block_score": 0.2,
            },
        ],
        "overall_ocr_res": {
            "rec_polys": [
                [[0, 60], [100, 60], [100, 80], [0, 80]],
                [[0, 90], [100, 90], [100, 110], [0, 110]],
            ],
            "rec_texts": ["keep line", "drop line"],
            "rec_scores": [0.8, 0.1],
        },
    }

    rec_polys, rec_texts, rec_scores = extract_rec_entries_from_ppstructure(
        data,
        skip_text_inside_table=False,
        min_line_score=0.5,
        table_fallback_layout=False,
    )

    assert len(rec_polys) == 3
    assert rec_texts == ["keep paragraph", "drop paragraph", "keep line"]
    assert rec_scores == [0.9, 0.2, 0.8]
