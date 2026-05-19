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


def _render_editor(job_id: str, *, template_mode: bool = False) -> str:
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    job_name = jobs.get_job_name(job_dir)
    return render_template(
        "editor/editor.html",
        job_id=job_id,
        job_name=job_name,
        debug_pdf_url=url_for("jobs.job_file", job_id=job_id, filename="overlay_debug.pdf"),
        template_mode=template_mode,
    )


@editor_bp.route("/job/<job_id>", methods=["GET"], endpoint="editor")
def editor(job_id: str) -> str:
    return _render_editor(job_id)


@editor_bp.route("/template/job/<job_id>", methods=["GET"], endpoint="template_editor")
def template_editor(job_id: str) -> str:
    return _render_editor(job_id, template_mode=True)
