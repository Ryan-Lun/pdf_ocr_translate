from __future__ import annotations

from .shared import (
    Response,
    _can_view_active_editors,
    _current_access_scope,
    _document_template_source_jobs,
    api_bp,
    jobs,
    json,
    stream_with_context,
    time,
)


def _jobs_stream_response(job_type: str):
    owner_work_id, include_all = _current_access_scope()
    can_view_active_editors = _can_view_active_editors()
    @stream_with_context
    def generate():
        last_payload = None
        while True:
            payload = {
                "can_view_active_editors": can_view_active_editors,
                "jobs": jobs.build_jobs_list(
                    job_type=job_type,
                    owner_work_id=owner_work_id,
                    include_all=include_all,
                    include_active_editors=can_view_active_editors,
                )
            }
            data = json.dumps(payload, ensure_ascii=False)
            if data != last_payload:
                last_payload = data
                yield f"event: jobs\ndata: {data}\n\n"
            else:
                yield ": ping\n\n"
            time.sleep(3)

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


def _document_template_source_jobs_stream_response():
    @stream_with_context
    def generate():
        last_payload = None
        while True:
            payload = {"jobs": _document_template_source_jobs()}
            data = json.dumps(payload, ensure_ascii=False)
            if data != last_payload:
                last_payload = data
                yield f"event: jobs\ndata: {data}\n\n"
            else:
                yield ": ping\n\n"
            time.sleep(3)

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@api_bp.route("/jobs/stream", methods=["GET"], endpoint="jobs_stream")
def jobs_stream():
    return _jobs_stream_response("ocr_overlay")


@api_bp.route("/doc-jobs/stream", methods=["GET"], endpoint="doc_jobs_stream")
def doc_jobs_stream():
    return _jobs_stream_response("doc_workspace")


@api_bp.route("/word-jobs/stream", methods=["GET"], endpoint="word_jobs_stream")
def word_jobs_stream():
    return _jobs_stream_response("word_translate")


@api_bp.route("/template-jobs/stream", methods=["GET"], endpoint="template_jobs_stream")
def template_jobs_stream():
    return _jobs_stream_response("template_source")


@api_bp.route(
    "/document-templates/source-jobs/stream",
    methods=["GET"],
    endpoint="document_template_source_jobs_stream",
)
def document_template_source_jobs_stream():
    return _document_template_source_jobs_stream_response()
