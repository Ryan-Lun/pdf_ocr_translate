from __future__ import annotations

import os
import re
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
OUT_ROOT = BASE_DIR / "out"
JOB_ROOT = OUT_ROOT / "jobs"
UPLOAD_ROOT = OUT_ROOT / "uploads"

TRITON_URL = os.getenv("TRITON_URL", "https://racks-editing-norm-timber.trycloudflare.com/table-recognition")
AZURE_BASE_URL = os.getenv("AZURE_OPENAI_BASE_URL", "https://uocp-azure-openai.openai.azure.com/openai/v1/")
AZURE_API_KEY_ENV = os.getenv("AZURE_OPENAI_API_KEY_ENV", "UO_AZURE_OPENAI_API_KEY")
AZURE_BATCH_MODEL = os.getenv("AZURE_BATCH_MODEL", "batch-o3-mini")
AZURE_BATCH_POLL_SECONDS = float(os.getenv("AZURE_BATCH_POLL_SECONDS", "60"))
AZURE_BATCH_COMPLETION_WINDOW = os.getenv("AZURE_BATCH_COMPLETION_WINDOW", "24h")
GLOSSARY_INSPECTION_PATH = os.getenv(
    "GLOSSARY_INSPECTION_PATH",
    str((BASE_DIR / "glossary" / "inspection_terminology.json")),
)
GLOSSARY_PROCESS_PATH = os.getenv(
    "GLOSSARY_PROCESS_PATH",
    str((BASE_DIR / "glossary" / "process_terminology.json")),
)
GLOBAL_GLOSSARY_PATH = os.getenv(
    "GLOBAL_GLOSSARY_PATH",
    str((BASE_DIR / "glossary" / "global_glossary.json")),
)
AZURE_BATCH_SYSTEM_PROMPT = os.getenv(
    "AZURE_BATCH_SYSTEM_PROMPT",
    "\n".join(
        [
            "You are a professional medical device regulatory translator.",
            "Translate the text from Chinese to English accurately and literally.",
            "Do NOT summarize, paraphrase, explain, or add content.",
            "Preserve all numbers, codes, references, and formatting.",
            "CRITICAL FORMATTING RULE 1: You MUST insert a line break strictly before every numbered item (e.g., '2.', '3.', '4.').",
            "CRITICAL FORMATTING RULE 2: You MUST keep all text within the same numbered item as ONE continuous paragraph. Do NOT add line breaks inside a step.",
            "Strictly prohibit duplicate words or expressions with identical meanings; if they appear, you must remove the redundancy and keep only one.",
            "Output only the translated text."
        ]
    ),
).strip()

BATCH_INPUT_NAME = "azure_batch_input.jsonl"
BATCH_OUTPUT_NAME = "azure_batch_output.jsonl"
BATCH_STATUS_NAME = "batch_status.json"
BATCH_ALIAS_NAME = "batch_alias_map.json"
BATCH_PREFILL_NAME = "batch_prefill_map.json"

ALLOWED_EXTENSIONS = {".pdf"}

FONT_CANDIDATES = [
    r"C:\\Windows\\Fonts\\msjh.ttf",
    r"C:\\Windows\\Fonts\\msjhbd.ttf",
    r"C:\\Windows\\Fonts\\msjhl.ttf",
    r"C:\\Windows\\Fonts\\msjh.ttc",
    r"C:\\Windows\\Fonts\\msjhbd.ttc",
    r"C:\\Windows\\Fonts\\msjhl.ttc",
    r"C:\\Windows\\Fonts\\mingliu.ttc",
    r"C:\\Windows\\Fonts\\simsun.ttc",
]

DEFAULT_TEXT_COLOR = "#0000ff"
DEFAULT_FONT_SIZE_PX = 25.0

TRANSLATION_MEMORY_PATH = Path(
    os.getenv("TRANSLATION_MEMORY_PATH", str(OUT_ROOT / "translation_memory.json"))
)
TRANSLATION_MEMORY_LOCK = threading.Lock()
TRANSLATION_MEMORY_TTL_DAYS = int(os.getenv("TRANSLATION_MEMORY_TTL_DAYS", "7"))
TRANSLATION_MEMORY_TTL_SECONDS = max(0, TRANSLATION_MEMORY_TTL_DAYS) * 86400

NUMERIC_ONLY_RE = re.compile(r"^[0-9]+([,./:-][0-9]+)*%?$")

ACTIVE_UPLOAD: dict[str, object] | None = None
ACTIVE_UPLOAD_LOCK = threading.Lock()
JOBS_EVENT = threading.Condition()
JOBS_VERSION = 0
