from __future__ import annotations

import argparse
import json
from pathlib import Path

from ocr_pipeline.table_merge import add_merged_cells_field


def main() -> None:
    parser = argparse.ArgumentParser(description="Run table merge against one PP-Structure JSON file.")
    parser.add_argument("input_json", type=Path)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("table_merged.json"),
        help="Output JSON path. Defaults to table_merged.json.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    data = json.loads(args.input_json.read_text(encoding="utf-8"))
    merged = add_merged_cells_field(data, verbose=args.verbose)
    args.output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done -> {args.output}")


if __name__ == "__main__":
    main()
