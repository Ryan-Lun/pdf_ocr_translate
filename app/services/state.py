from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from . import openai_config

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional import guard
    load_dotenv = None

if callable(load_dotenv):
    load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[2]
OUT_ROOT = BASE_DIR / "out"
JOB_ROOT = OUT_ROOT / "jobs"
TEMPLATE_ROOT = OUT_ROOT / "templates"
TEMPLATE_JOB_ROOT = TEMPLATE_ROOT / "jobs"
UPLOAD_ROOT = OUT_ROOT / "uploads"
DOC_WORKSPACE_ROOT = OUT_ROOT / "doc_workspace"

TRITON_URL = os.getenv("TRITON_URL", "https://racks-editing-norm-timber.trycloudflare.com/table-recognition")
PP_STRUCTURE_URL = os.getenv(
    "PP_STRUCTURE_URL",
    os.getenv(
        "TRITON_LAYOUT_URL",
        "https://writing-coordination-farm-approximately.trycloudflare.com/layout-parsing",
    ),
)
OPENAI_BASE_URL = openai_config.get_openai_base_url()
AZURE_BASE_URL = OPENAI_BASE_URL
OPENAI_API_KEY = openai_config.get_openai_api_key()
AZURE_API_KEY_ENV = os.getenv("AZURE_OPENAI_API_KEY_ENV", "OPENAI_API_KEY")
AZURE_BATCH_MODEL = openai_config.get_batch_translate_deployment()
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
SYSTEM_GLOSSARY_PATH = os.getenv(
    "SYSTEM_GLOSSARY_PATH",
    str((BASE_DIR / "glossary" / "system_glossary.json")),
)
DOCUMENT_TEMPLATES_PATH = Path(
    os.getenv("DOCUMENT_TEMPLATES_PATH", str(TEMPLATE_ROOT / "document_templates.json"))
)
AZURE_BATCH_SYSTEM_PROMPT = os.getenv(
    "AZURE_BATCH_SYSTEM_PROMPT",
    "\n".join(
        [
            "You are a professional medical device regulatory translator.",
            "Translate the text from Chinese to English accurately and literally.",
            "Do NOT summarize, paraphrase, explain, or add content.",
            "Preserve all numbers, codes, references, and formatting.",
            "If the input is a standalone year, number, code, table number, figure number, symbol, unit, abbreviation, or non-sentence fragment, do not explain it. Return only the translated or preserved text. Examples: 2017年 -> 2017、2018年 -> 2018、N/A -> N/A",
            "CRITICAL FORMATTING RULE 1: You MUST insert a line break strictly before every numbered item (e.g., '2.', '3.', '4.').",
            "CRITICAL FORMATTING RULE 2: You MUST keep all text within the same numbered item as ONE continuous paragraph. Do NOT add line breaks inside a step.",
            "Strictly prohibit duplicate words or expressions with identical meanings; if they appear, you must remove the redundancy and keep only one.",
            "Output only the translated text."
        ]
    ),
).strip()

DOC_TRANSLATE_MODEL = openai_config.get_doc_translate_deployment()
PDF_REALTIME_TRANSLATE_MODEL = openai_config.get_pdf_realtime_translate_deployment()
WORD_TRANSLATE_MODEL = openai_config.get_word_translate_deployment()
WORD_QUALITY_MODEL = openai_config.get_word_quality_deployment()
DOC_TRANSLATE_MAX_CHARS = int(os.getenv("DOC_TRANSLATE_MAX_CHARS", "4000"))
DOC_TRANSLATE_USE_AZURE = os.getenv("DOC_TRANSLATE_USE_AZURE", "0").strip() == "1"
DOC_TRANSLATE_SYSTEM_PROMPT = os.getenv(
    "DOC_TRANSLATE_SYSTEM_PROMPT",
    "\n".join(
        [
            "You are a professional document translator.",
            "Translate the provided HTML content accurately and literally.",
            "Preserve the original HTML structure, headings, lists, tables, links, image references, and attributes needed for rendering.",
            "Do NOT remove placeholders, file paths, URLs, tag structure, or embedded resource references.",
            "Return only the translated HTML.",
        ]
    ),
).strip()

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "3"))
WORKER_ID = os.getenv("WORKER_ID", f"{os.getenv('COMPUTERNAME', 'worker')}-{os.getpid()}")
WORKER_OCR_MAX_RUNNING = int(os.getenv("WORKER_OCR_MAX_RUNNING", "1"))
WORKER_PDF_TRANSLATE_MAX_RUNNING = int(os.getenv("WORKER_PDF_TRANSLATE_MAX_RUNNING", "1"))
WORKER_DOC_MAX_RUNNING = int(os.getenv("WORKER_DOC_MAX_RUNNING", "1"))
WORKER_WORD_MAX_RUNNING = int(os.getenv("WORKER_WORD_MAX_RUNNING", "1"))
PDF_REALTIME_JOB_CONCURRENCY = max(1, int(os.getenv("PDF_REALTIME_JOB_CONCURRENCY", "4")))
PDF_REALTIME_GLOBAL_CONCURRENCY = max(1, int(os.getenv("PDF_REALTIME_GLOBAL_CONCURRENCY", "8")))
PDF_REALTIME_RPM_LIMIT = max(1, int(os.getenv("PDF_REALTIME_RPM_LIMIT", "300")))
PDF_REALTIME_MAX_SEGMENTS_PER_REQUEST = max(1, int(os.getenv("PDF_REALTIME_MAX_SEGMENTS_PER_REQUEST", "30")))
PDF_REALTIME_MAX_CHARS_PER_REQUEST = max(500, int(os.getenv("PDF_REALTIME_MAX_CHARS_PER_REQUEST", "8000")))
PDF_REALTIME_RATE_LIMIT_RPM = max(1, int(os.getenv("PDF_REALTIME_RATE_LIMIT_RPM", "2500")))
PDF_REALTIME_RATE_LIMIT_TPM = max(1, int(os.getenv("PDF_REALTIME_RATE_LIMIT_TPM", "250000")))
PDF_REALTIME_RATE_LIMIT_HEADROOM = min(
    1.0,
    max(0.1, float(os.getenv("PDF_REALTIME_RATE_LIMIT_HEADROOM", "0.8"))),
)
DEFAULT_OPENAI_RATE_LIMIT_RPM = max(1, int(os.getenv("DEFAULT_OPENAI_RATE_LIMIT_RPM", "300")))
DEFAULT_OPENAI_RATE_LIMIT_TPM = max(1, int(os.getenv("DEFAULT_OPENAI_RATE_LIMIT_TPM", "120000")))
DEFAULT_OPENAI_RATE_LIMIT_HEADROOM = min(
    1.0,
    max(0.1, float(os.getenv("DEFAULT_OPENAI_RATE_LIMIT_HEADROOM", "0.8"))),
)
USER_SUBMISSIONS_PER_MINUTE = max(1, int(os.getenv("USER_SUBMISSIONS_PER_MINUTE", "10")))
REALTIME_COMPLETION_TOKEN_BUDGET = max(1, int(os.getenv("REALTIME_COMPLETION_TOKEN_BUDGET", "4000")))
STARTUP_WARMUP_ENABLED = os.getenv("STARTUP_WARMUP_ENABLED", "1").strip() == "1"
STARTUP_WARMUP_BLOCKING = os.getenv("STARTUP_WARMUP_BLOCKING", "1").strip() == "1"
STARTUP_WARMUP_BGE = os.getenv("STARTUP_WARMUP_BGE", "1").strip() == "1"
STARTUP_WARMUP_TRITON = os.getenv("STARTUP_WARMUP_TRITON", "0").strip() == "1"
STARTUP_WARMUP_OPENAI_CLIENTS = os.getenv("STARTUP_WARMUP_OPENAI_CLIENTS", "1").strip() == "1"
STARTUP_WARMUP_TIMEOUT_SECONDS = float(os.getenv("STARTUP_WARMUP_TIMEOUT_SECONDS", "30"))

BATCH_INPUT_NAME = "azure_batch_input.jsonl"
BATCH_OUTPUT_NAME = "azure_batch_output.jsonl"
BATCH_STATUS_NAME = "batch_status.json"
BATCH_ALIAS_NAME = "batch_alias_map.json"
BATCH_PREFILL_NAME = "batch_prefill_map.json"
DOC_STATUS_NAME = "document_status.json"

ALLOWED_EXTENSIONS = {".pdf"}

FONT_CANDIDATES = [
    str(BASE_DIR / "assets" / "fonts" / "NotoSansTC-Regular.ttf"),
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

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}

PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY = _env_bool(
    "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY",
    True,
)

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
