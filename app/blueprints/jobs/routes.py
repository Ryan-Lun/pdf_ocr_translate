from __future__ import annotations

from flask import Blueprint, abort, request, send_file, send_from_directory

from ...services import jobs

jobs_bp = Blueprint(
    "jobs",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/jobs",
    url_prefix="",
)


@jobs_bp.route("/jobs/<job_id>/<path:filename>", methods=["GET"], endpoint="job_file")
def job_file(job_id: str, filename: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    file_path = job_dir / filename
    if not file_path.exists():
        abort(404)
    download_flag = str(request.args.get("download", "")).lower()
    if download_flag in {"1", "true", "yes"}:
        job_name = jobs.get_job_name(job_dir)
        if filename == "edited.pdf":
            download_name = jobs.build_download_name(job_id, job_name)
        elif filename == "structure/doc.md":
            download_name = jobs.build_doc_markdown_name(job_id, job_name, translated=False)
        elif filename == "translated/doc.translated.md":
            download_name = jobs.build_doc_markdown_name(job_id, job_name, translated=True)
        elif filename == "output/output.docx":
            download_name = jobs.build_docx_name(job_id, job_name)
        else:
            download_name = filename
        return send_file(file_path, as_attachment=True, download_name=download_name)
    return send_from_directory(job_dir, filename)
