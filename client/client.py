#!/usr/bin/env python

# Copyright (c) 2025 PaddlePaddle Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import argparse
import sys
import base64
import json
from pathlib import Path

import requests

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, required=True)
    parser.add_argument("--file-type", type=int, choices=[0, 1])
    parser.add_argument("--no-visualization", action="store_true")
    parser.add_argument("--url", type=str, default="https://reproduced-dating-tamil-edited.trycloudflare.com/layout-parsing")

    args = parser.parse_args()

    with open(args.file, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("ascii")
    payload = {"file": image_data}
    if args.file_type is not None:
        payload["fileType"] = args.file_type
    if args.no_visualization:
        payload["visualize"] = False
    response = requests.post(args.url, json=payload, timeout=120)
    if response.status_code != 200:
        print(f"Error code: HTTP {response.status_code}", file=sys.stderr)
        sys.exit(1)
    output = response.json()
    if output.get("errorCode", -1) != 0:
        print(f"Error code: {output['errorCode']}", file=sys.stderr)
        print(f"Error message: {output['errorMsg']}", file=sys.stderr)
        sys.exit(1)
    result = output["result"]
    md_dir = Path(f"paddle_api")
    md_dir.mkdir(exist_ok=True)
    for i, res in enumerate(result["layoutParsingResults"]):
        print(res["prunedResult"])
        # md_dir = Path(f"markdown_{i}")
        # md_dir.mkdir(exist_ok=True)
        pruned = res["prunedResult"]
        filename = f"{md_dir}/pruned_result_page_{i}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=2, ensure_ascii=False)
        print(f"已將第 {i} 頁寫入 {filename}")
        (md_dir / "doc.md").write_text(res["markdown"]["text"], encoding="utf-8")

        for img_path, img in res["markdown"]["images"].items():
            img_path = md_dir / img_path
            img_path.parent.mkdir(parents=True, exist_ok=True)
            img_path.write_bytes(base64.b64decode(img))
        print(f"Markdown document saved at {md_dir / 'doc.md'}")

        for img_name, img in res["outputImages"].items():
            img_path = f"{md_dir}/{img_name}_{i}.jpg"
            Path(img_path).write_bytes(base64.b64decode(img))
            print(f"Output image saved at {img_path}")


if __name__ == "__main__":
    main()
