from __future__ import annotations

from flask import Blueprint, abort, render_template, url_for

from ...services import jobs

editor_bp = Blueprint(
    "editor",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/editor",
)


@editor_bp.route("/job/<job_id>", methods=["GET"], endpoint="editor")
def editor(job_id: str) -> str:
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    return render_template(
        "editor/editor.html",
        job_id=job_id,
        debug_pdf_url=url_for("jobs.job_file", job_id=job_id, filename="overlay_debug.pdf"),
    )
