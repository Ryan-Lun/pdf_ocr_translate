import os
import json
import argparse
import time
import base64
import requests

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}


def infer_folder(folder_path, url="localhost:8001"):

    if not os.path.isdir(folder_path):
        raise ValueError(f"{folder_path} 不是合法的資料夾路徑")

    files = []
    for root, _, filenames in os.walk(folder_path):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in IMG_EXTS:
                files.append(os.path.join(root, fn))

    print(f"找到 {len(files)} 張圖片")

    out_dir = os.path.join(folder_path, "results")
    os.makedirs(out_dir, exist_ok=True)

    start = time.time()
    for idx, img_path in enumerate(files):
        print(f"[{idx+1}/{len(files)}] 辨識：{img_path}")

        with open(img_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("ascii")
        payload = {
            "file": image_data,
            "fileType": 1,  # 0 = image
        }
        response = requests.post(url, json=payload, timeout=120)
        if response.status_code != 200:
            print("識別失敗: HTTP", response.status_code)
            continue
        output = response.json()

        if output.get("errorCode", -1) != 0:
            print("識別失敗:", output.get("errorMsg"))
            continue

        pruned = output["result"]["layoutParsingResults"][0]["prunedResult"]

        base = os.path.splitext(os.path.basename(img_path))[0]
        json_file = os.path.join(out_dir, f"{base}.json")
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(pruned, f, indent=2, ensure_ascii=False)

        print("儲存結果到", json_file)
    finsh = time.time()
    spend_time = finsh-start
    print(f"time:{spend_time:.2f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", "-f", type=str, required=True)
    parser.add_argument("--url", type=str, default="localhost:8001")
    args = parser.parse_args()

    infer_folder(args.folder, args.url)
