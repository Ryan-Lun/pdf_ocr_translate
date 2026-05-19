from __future__ import annotations
import logging
import os
import threading
import time

import requests

from . import openai_config, state

logger = logging.getLogger(__name__)

_WARMUP_LOCK = threading.Lock()
_WARMUP_STARTED = False
_ONE_BY_ONE_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9l9e0AAAAASUVORK5CYII="
)


def init_startup_warmup() -> None:
    global _WARMUP_STARTED
    if not state.STARTUP_WARMUP_ENABLED:
        return
    if _is_werkzeug_reloader_parent():
        logger.info("Skipping startup warmup in Werkzeug reloader parent process.")
        return
    with _WARMUP_LOCK:
        if _WARMUP_STARTED:
            return
        _WARMUP_STARTED = True
    if state.STARTUP_WARMUP_BLOCKING:
        _run_startup_warmup()
        return
    thread = threading.Thread(target=_run_startup_warmup, name="startup-warmup", daemon=True)
    thread.start()


def _is_werkzeug_reloader_parent() -> bool:
    run_main = os.getenv("WERKZEUG_RUN_MAIN")
    if run_main is None:
        return False
    return run_main.lower() != "true"


def _run_startup_warmup() -> None:
    started_at = time.time()
    logger.info("Startup warmup started.")
    if state.STARTUP_WARMUP_OPENAI_CLIENTS:
        _warm_openai_clients()
    if _should_warm_bge():
        _warm_bge_model()
    if state.STARTUP_WARMUP_TRITON:
        _warm_triton_service()
    logger.info("Startup warmup finished in %.2fs.", time.time() - started_at)


def _runtime_role() -> str:
    return str(os.getenv("APP_RUNTIME_ROLE") or "web").strip().lower()


def _should_warm_bge() -> bool:
    if not state.STARTUP_WARMUP_BGE:
        return False
    return _runtime_role() == "worker"


def _warm_openai_clients() -> None:
    try:
        openai_config.create_sync_client()
        openai_config.create_async_client()
        logger.info("Startup warmup: OpenAI clients initialized.")
    except Exception as exc:
        logger.warning("Startup warmup: failed to initialize OpenAI clients: %s", exc)


def _warm_bge_model() -> None:
    try:
        from ocr_pipeline.paragraph_align import get_model

        model = get_model()
        if model is None:
            logger.warning("Startup warmup: BGE-M3 model unavailable.")
            return
        logger.info("Startup warmup: BGE-M3 model loaded.")
    except Exception as exc:
        logger.warning("Startup warmup: failed to load BGE-M3 model: %s", exc)


def _warm_triton_service() -> None:
    payload = {
        "file": _ONE_BY_ONE_PNG_BASE64,
        "fileType": 1,
        "useDocOrientationClassify": False,
        "useTableOrientationClassify": False,
    }
    try:
        response = requests.post(
            state.TRITON_URL,
            json=payload,
            timeout=state.STARTUP_WARMUP_TIMEOUT_SECONDS,
        )
        logger.info(
            "Startup warmup: Triton warmup status_code=%s",
            response.status_code,
        )
    except Exception as exc:
        logger.warning("Startup warmup: Triton warmup request failed: %s", exc)
