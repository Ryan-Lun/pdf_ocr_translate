from __future__ import annotations

import json
import re
from pathlib import Path
import pdfplumber

def is_chinese(text):
    return re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", text)

def is_english(text):
    return re.search(r"[A-Za-z]", text)

def is_mixed(text):
    return is_chinese(text) and is_english(text)

def is_code_like(text):
    return re.fullmatch(r"[A-Za-z0-9\-_/\. %]+", text)

def should_translate(text):
    text = text.strip()
    if not text:
        return False
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", text))

def box_center(box):
    x1, y1, x2, y2 = box
    return ((x1 + x2) / 2, (y1 + y2) / 2)

def intersection_area(a, b):
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])

    if x2 < x1 or y2 < y1:
        return 0
    return (x2 - x1) * (y2 - y1)

def box_area(box):
    return (box[2] - box[0]) * (box[3] - box[1])

def overlap_ratio(cell_box, rec_box):
    inter = intersection_area(cell_box, rec_box)
    area = box_area(rec_box)
    if area == 0:
        return 0
    return inter / area

def sort_by_reading_order(texts_with_box):
    def get_stats(box):
        x1, y1, x2, y2 = box
        return (x1 + x2) / 2, (y1 + y2) / 2, (y2 - y1) 
    
    if not texts_with_box:
        return []
    
    avg_h = sum((item[1][3] - item[1][1]) for item in texts_with_box) / len(texts_with_box)
    return sorted(texts_with_box, key=lambda x: (round(get_stats(x[1])[1] / (avg_h * 0.5)), get_stats(x[1])[0]))

def group_texts_by_proximity(texts_with_box, x_thresh=3.0, y_thresh=1.2):
    if not texts_with_box:
        return []
        
    groups = []
    current_group = [texts_with_box[0]]
    
    for i in range(1, len(texts_with_box)):
        curr = texts_with_box[i]
        prev = current_group[-1]
        
        p_box, c_box = prev[1], curr[1]
        h_prev, h_curr = p_box[3] - p_box[1], c_box[3] - c_box[1]
        avg_h = (h_prev + h_curr) / 2.0
        x_dist = max(0, max(p_box[0], c_box[0]) - min(p_box[2], c_box[2]))
        y_dist = max(0, max(p_box[1], c_box[1]) - min(p_box[3], c_box[3]))
        p_cy = (p_box[1] + p_box[3]) / 2
        c_cy = (c_box[1] + c_box[3]) / 2
        is_same_line = abs(p_cy - c_cy) < (avg_h * 0.6)

        should_merge = False
        if is_same_line:
            if x_dist <= avg_h * x_thresh:
                should_merge = True
        else:
            if y_dist <= avg_h * y_thresh:
                x_overlap = min(p_box[2], c_box[2]) - max(p_box[0], c_box[0])
                if x_overlap > -avg_h:
                    should_merge = True
        
        if should_merge:
            current_group.append(curr)
        else:
            groups.append(current_group)
            current_group = [curr]
            
    if current_group:
        groups.append(current_group)
    return groups

def normalize_box_to_bbox(box):
    if not box: return [0, 0, 0, 0]
    if isinstance(box[0], (list, tuple)):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        return [min(xs), min(ys), max(xs), max(ys)]
    return [float(v) for v in box]


def add_merged_cells_field(data, pdf_path: str = None, page_index: int = 0, scale_factor: float = 1.0, verbose: bool = False):
    table_res_list = data.get("table_res_list")
    if not isinstance(table_res_list, list) or not table_res_list:
        return data
    
    # 1. Global comparison: collect all text fragments recognized by table OCR across all tables
    all_table_ocr_texts = set()
    for table in table_res_list:
        t_ocr = table.get("table_ocr_pred") or {}
        for txt in (t_ocr.get("rec_texts") or []):
            clean_txt = txt.strip().replace(" ", "")
            if clean_txt:
                all_table_ocr_texts.add(clean_txt)

    # 2. Identify missing OCR items from overall_ocr_res that are NOT covered by any table OCR
    overall_ocr = data.get("overall_ocr_res") or {}
    o_texts = overall_ocr.get("rec_texts") or []
    o_raw_boxes = overall_ocr.get("rec_boxes") or []
    o_boxes = [normalize_box_to_bbox(b) for b in o_raw_boxes]

    missing_ocr_items = []
    for o_txt, o_box in zip(o_texts, o_boxes):
        clean_o = o_txt.strip().replace(" ", "")
        if not clean_o:
            continue
        if clean_o not in all_table_ocr_texts:
            missing_ocr_items.append({"text": o_txt, "box": o_box})

    # 3. Determine unique cells and landscape orientation
    all_pdf_cells = []
    is_landscape = False 

    if pdf_path and Path(pdf_path).exists():
        with pdfplumber.open(pdf_path) as pdf:
            if page_index < len(pdf.pages):
                page = pdf.pages[page_index]
                if page.width > page.height:
                    is_landscape = True

                for table_plumb in page.find_tables():
                    for cell in table_plumb.cells:
                        if cell is None:
                            continue
                        x0, top, x1, bottom = cell
                        all_pdf_cells.append([
                            x0 * scale_factor, 
                            top * scale_factor, 
                            x1 * scale_factor, 
                            bottom * scale_factor
                        ])

    if not all_pdf_cells:
        # Fallback to OCR-detected cells from table_res_list
        for t in table_res_list:
            ocr_cells = t.get("cell_box_list") or []
            for box in ocr_cells:
                if isinstance(box, (list, tuple)) and len(box) == 4:
                    all_pdf_cells.append([float(v) for v in box])

        max_x = max([normalize_box_to_bbox(b)[2] for t in table_res_list for b in t.get("table_ocr_pred", {}).get("rec_boxes", [])] + [0])
        max_y = max([normalize_box_to_bbox(b)[3] for t in table_res_list for b in t.get("table_ocr_pred", {}).get("rec_boxes", [])] + [0])
        is_landscape = (max_x > max_y)

    dynamic_y_thresh = 4 if is_landscape else 0.7

    unique_cells = []
    seen = set()
    for c in all_pdf_cells:
        tup = (round(c[0], 1), round(c[1], 1), round(c[2], 1), round(c[3], 1))
        if tup not in seen:
            seen.add(tup)
            unique_cells.append(c)

    # 4. Process each table
    for table_idx, table in enumerate(table_res_list):
        table_ocr_pred = table.get("table_ocr_pred") or {}
        rec_texts = table_ocr_pred.get("rec_texts") or []
        raw_rec_boxes = table_ocr_pred.get("rec_boxes") or []
        rec_boxes = [normalize_box_to_bbox(b) for b in raw_rec_boxes]
        
        merged_cells = []
        if rec_texts and rec_boxes:
            cell_buckets = {i: [] for i in range(len(unique_cells))}
            matched_ocr_indices = set()
            for ocr_idx, (txt, box) in enumerate(zip(rec_texts, rec_boxes)):
                best_cell_idx = -1
                min_cell_area = float('inf')
                for i, cell_box in enumerate(unique_cells):
                    overlap = overlap_ratio(cell_box, box)
                    if overlap >= 0.5:
                        area = box_area(cell_box)
                        if area < min_cell_area:
                            min_cell_area = area
                            best_cell_idx = i
                if best_cell_idx != -1:
                    cell_buckets[best_cell_idx].append((txt, box))
                    matched_ocr_indices.add(ocr_idx)

            # Group and merge only table-recognized text
            for cell_idx, items in cell_buckets.items():
                if not items:
                    continue
                cell_box = unique_cells[cell_idx]
                items = sort_by_reading_order(items)
                grouped_texts = group_texts_by_proximity(items, x_thresh=3.0, y_thresh=dynamic_y_thresh)
                for group in grouped_texts:
                    merged_text = " ".join([t[0].strip() for t in group])
                    if not merged_text:
                        continue
                    translate_flag = should_translate(merged_text)
                    if not translate_flag:
                        continue
                    if len(group) == 1:
                        target_box = group[0][1]
                    else:
                        xs = [item[1][0] for item in group] + [item[1][2] for item in group]
                        ys = [item[1][1] for item in group] + [item[1][3] for item in group]
                        target_box = [min(xs), min(ys), max(xs), max(ys)]

                    merged_cells.append({
                        "cell_box": target_box,
                        "merged_text": merged_text,
                        "should_translate": translate_flag,
                        "original_table_cell": cell_box,
                        "original_ocr_components": [{"text": item[0], "box": item[1]} for item in group]
                    })

            # Handle orphaned table OCR items
            orphaned_items = []
            for ocr_idx, (txt, box) in enumerate(zip(rec_texts, rec_boxes)):
                if ocr_idx not in matched_ocr_indices:
                    orphaned_items.append((txt, box))

            if orphaned_items:
                orphaned_items = sort_by_reading_order(orphaned_items)
                grouped_orphans = group_texts_by_proximity(orphaned_items, x_thresh=3.0, y_thresh=dynamic_y_thresh)
                for group in grouped_orphans:
                    merged_text = " ".join([t[0].strip() for t in group])
                    if not merged_text:
                        continue
                    translate_flag = should_translate(merged_text)
                    if not translate_flag:
                        continue
                    if len(group) == 1:
                        target_box = group[0][1]
                    else:
                        xs = [item[1][0] for item in group] + [item[1][2] for item in group]
                        ys = [item[1][1] for item in group] + [item[1][3] for item in group]
                        target_box = [min(xs), min(ys), max(xs), max(ys)]

                    merged_cells.append({
                        "cell_box": target_box,
                        "merged_text": merged_text,
                        "should_translate": translate_flag,
                        "original_table_cell": target_box, 
                        "original_ocr_components": [{"text": item[0], "box": item[1]} for item in group]
                    })

        # 5. Add Missing OCR items from overall_ocr_res individually (only if inside table boundaries)
        if unique_cells and missing_ocr_items:
            table_x0 = min(c[0] for c in unique_cells)
            table_y0 = min(c[1] for c in unique_cells)
            table_x1 = max(c[2] for c in unique_cells)
            table_y1 = max(c[3] for c in unique_cells)

            for item in missing_ocr_items:
                m_txt, m_box = item["text"], item["box"]
                cx, cy = (m_box[0] + m_box[2]) / 2, (m_box[1] + m_box[3]) / 2
                
                if table_x0 <= cx <= table_x1 and table_y0 <= cy <= table_y1:
                    translate_flag = should_translate(m_txt)
                    if translate_flag:
                        best_patch_idx = -1
                        min_patch_area = float('inf')
                        for i, cell_box in enumerate(unique_cells):
                            if cell_box[0] <= cx <= cell_box[2] and cell_box[1] <= cy <= cell_box[3]:
                                area = box_area(cell_box)
                                if area < min_patch_area:
                                    min_patch_area = area
                                    best_patch_idx = i
                                    
                        patch_cell = unique_cells[best_patch_idx] if best_patch_idx != -1 else m_box
                        merged_cells.append({
                            "cell_box": m_box,
                            "merged_text": m_txt.strip(),
                            "should_translate": translate_flag,
                            "original_table_cell": patch_cell,
                            "original_ocr_components": [{"text": m_txt, "box": m_box}]
                        })
                        if verbose:
                            print(f"[Missing Text Added Individually]: {m_txt}")

        merged_cells.sort(key=lambda x: (round(x["cell_box"][1], 1), round(x["cell_box"][0], 1)))
        table["merged_cells"] = merged_cells
    return data


if __name__ == "__main__":
    input_path = Path(
        "out/jobs/f8663368c9b7476683c44ac7cb399ea3/pp_json/f8663368c9b7476683c44ac7cb399ea3_p0002.json"
    )
    output_path = Path("table_merged.json")

    data = json.loads(input_path.read_text(encoding="utf-8"))
    new_data = add_merged_cells_field(data, verbose=True)

    output_path.write_text(
        json.dumps(new_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\nDone -> table_merged.json")