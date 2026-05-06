from __future__ import annotations

import json
import time
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

from ocr_pipeline.merge_logic import merge_keep_original_json

app = FastAPI(title="Merge Service")


@app.post("/merge-and-save")
async def merge_and_save(file: UploadFile = File(...)):
    t1 = time.time()

    content = await file.read()
    data = json.loads(content.decode("utf-8"))

    merged = merge_keep_original_json(data)

    return JSONResponse(
        {
            "status": "success",
            "merged": merged,
            "time_cost": round(time.time() - t1, 3),
        }
    )


@app.get("/")
def root():
    return {"status": "merge service running"}


__all__ = ["app", "merge_keep_original_json"]
