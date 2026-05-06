from __future__ import annotations

import glob
import json
import os
import re
from typing import Any

_model = None


def get_model():
    global _model
    if _model is None:
        print("Loading BGE-M3 model on CPU...")
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer("BAAI/bge-m3", device="cpu")
        print("Model loaded.")
    return _model


def is_chinese(text: Any):
    return re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", text)

def is_english(text: Any):
    return re.search(r"[A-Za-z]", str(text))


def bbox_vertical_match(box_zh, box_en):
    zh_x1, zh_y1, zh_x2, zh_y2 = box_zh
    en_x1, en_y1, en_x2, en_y2 = box_en
    if en_y1 < zh_y2:
        return False
    overlap = min(zh_x2, en_x2) - max(zh_x1, en_x1)
    zh_width = zh_x2 - zh_x1
    if zh_width <= 0:
        return False
    if overlap / zh_width < 0.5:
        return False
    if en_y1 - zh_y2 > 400:
        return False
    return True


# ------------------------------
# Align bilingual paragraphs and set should_translate
# ------------------------------

def align_and_update_json(data: dict) -> dict:
    blocks = data.get("parsing_res_list", [])
    if not blocks:
        return data

    zh_list = []
    en_list = []

    exclude_labels = ["table", "paragraph_title"]

    for i, block in enumerate(blocks):
        label = block.get("block_label", "")
        if label in exclude_labels:
            continue

        text = block.get("block_content", "")
        bbox = block.get("block_bbox", [])

        if is_chinese(text):
            zh_list.append({"index": i, "text": text, "box": bbox})
        elif is_english(text):
            en_list.append({"index": i, "text": text, "box": bbox})

    matched_indices = set()
    pairs = []

    if zh_list and en_list:
        zh_texts = [item["text"] for item in zh_list]
        en_texts = [item["text"] for item in en_list]

        model = get_model()
        from sentence_transformers import util

        zh_emb = model.encode(zh_texts, convert_to_tensor=True)
        en_emb = model.encode(en_texts, convert_to_tensor=True)
        cos_matrix = util.cos_sim(zh_emb, en_emb).numpy()

        for i, zh_item in enumerate(zh_list):
            best_score = 0
            best_en_idx = -1

            for j, en_item in enumerate(en_list):
                if not bbox_vertical_match(zh_item["box"], en_item["box"]):
                    continue

                score = cos_matrix[i][j]
                if score > best_score:
                    best_score = score
                    best_en_idx = j

            if best_score > 0.6:
                pairs.append(
                    {
                        "zh": zh_item["text"],
                        "en": en_list[best_en_idx]["text"],
                        "similarity": float(round(best_score, 4)),
                    }
                )
                matched_indices.add(zh_item["index"])
                matched_indices.add(en_list[best_en_idx]["index"])

    for idx, block in enumerate(blocks):
        label = block.get("block_label", "")
        if label in exclude_labels or idx in matched_indices:
            block["should_translate"] = False
        else:
            block["should_translate"] = True

    data["bilingual_pairs"] = pairs
    return data


# ------------------------------
# CLI
# ------------------------------

def main() -> None:
    input_dir = "pp_json"
    json_files = glob.glob(os.path.join(input_dir, "**/*.json"), recursive=True)

    print(f"Found {len(json_files)} JSON files...")

    for path in json_files:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            updated_data = align_and_update_json(data)

            with open(path, "w", encoding="utf-8") as f:
                json.dump(updated_data, f, ensure_ascii=False, indent=4)

            print(f"Updated: {path}")

        except Exception as exc:
            print(f"Failed: {path}: {exc}")


if __name__ == "__main__":
    main()
