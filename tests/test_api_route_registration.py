from __future__ import annotations


def test_api_route_split_preserves_existing_urls_and_endpoint_names(app):
    expected = {
        ("api.apply_consistency", "/api/job/<job_id>/consistency/apply", "POST"),
        ("api.apply_document_template", "/api/document-templates/<template_id>/apply", "POST"),
        ("api.apply_paragraph_term", "/api/job/<job_id>/paragraph-term/apply", "POST"),
        ("api.batch_restore", "/api/job/<job_id>/batch-restore", "POST"),
        ("api.batch_status", "/api/job/<job_id>/batch-status", "GET"),
        ("api.batch_translate", "/api/job/<job_id>/batch-translate", "POST"),
        ("api.cancel_job", "/api/job/<job_id>/cancel", "POST"),
        ("api.cancel_upload", "/api/upload-cancel", "POST"),
        ("api.cancel_word_job", "/api/job/<job_id>/cancel-word", "POST"),
        ("api.delete_document_template", "/api/document-templates/<template_id>", "DELETE"),
        ("api.delete_job", "/api/job/<job_id>", "DELETE"),
        ("api.doc_job_data", "/api/doc-job/<job_id>", "GET"),
        ("api.doc_jobs_stream", "/api/doc-jobs/stream", "GET"),
        ("api.document_template_source_jobs", "/api/document-templates/source-jobs", "GET"),
        ("api.document_template_source_jobs_stream", "/api/document-templates/source-jobs/stream", "GET"),
        ("api.document_templates", "/api/document-templates", "GET"),
        ("api.document_templates", "/api/document-templates", "POST"),
        ("api.download_doc_jobs_docx", "/api/doc-jobs/download-docx", "POST"),
        ("api.download_translated_batch", "/api/jobs/download-translated", "GET"),
        ("api.download_translated_batch", "/api/jobs/download-translated", "POST"),
        ("api.download_word_jobs_docx", "/api/word-jobs/download-docx", "POST"),
        ("api.editor_presence", "/api/job/<job_id>/editor-presence", "POST"),
        ("api.editor_presence_index", "/api/editor-presence", "GET"),
        ("api.global_glossary", "/api/glossary", "GET"),
        ("api.global_glossary", "/api/glossary", "POST"),
        ("api.glossary_library", "/api/glossary/library", "GET"),
        ("api.glossary_retranslate", "/api/job/<job_id>/glossary-retranslate", "POST"),
        ("api.glossary_system_export", "/api/glossary/system-export", "GET"),
        ("api.glossary_system_import_apply", "/api/glossary/system-import-apply", "POST"),
        ("api.glossary_system_import_preview", "/api/glossary/system-import-preview", "POST"),
        ("api.job_data", "/api/job/<job_id>", "GET"),
        ("api.jobs_stream", "/api/jobs/stream", "GET"),
        ("api.list_doc_jobs", "/api/doc-jobs", "GET"),
        ("api.list_jobs", "/api/jobs", "GET"),
        ("api.list_template_jobs", "/api/template-jobs", "GET"),
        ("api.list_word_jobs", "/api/word-jobs", "GET"),
        ("api.region_ocr_preview", "/api/job/<job_id>/region-ocr-preview", "POST"),
        ("api.rename_document_template", "/api/document-templates/<template_id>/name", "PATCH"),
        ("api.retranslate_box", "/api/job/<job_id>/retranslate-box", "POST"),
        ("api.retranslate_boxes", "/api/job/<job_id>/retranslate-boxes", "POST"),
        ("api.retranslate_document", "/api/job/<job_id>/retranslate-document", "POST"),
        ("api.retranslate_region", "/api/job/<job_id>/retranslate-region", "POST"),
        ("api.retry_job", "/api/job/<job_id>/retry", "POST"),
        ("api.save_job", "/api/job/<job_id>/save", "POST"),
        ("api.save_system_prompt", "/api/job/<job_id>/system-prompt", "POST"),
        ("api.template_jobs_stream", "/api/template-jobs/stream", "GET"),
        ("api.update_merge_notice", "/api/job/<job_id>/merge-notices/<notice_id>", "POST"),
        ("api.word_jobs_stream", "/api/word-jobs/stream", "GET"),
    }
    actual = set()
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith("api.") or rule.endpoint == "api.static":
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            actual.add((rule.endpoint, rule.rule, method))

    assert actual == expected
