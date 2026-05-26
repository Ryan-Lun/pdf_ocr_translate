# Repository Guidelines

## Project Structure & Module Organization
`app/` contains the Flask application: `blueprints/` for routes, `services/` for OCR, translation, DOCX export, and job orchestration, plus shared templates in `app/templates/`. `ocr_pipeline/` holds lower-level OCR merge and paragraph alignment logic. `tests/` contains pytest coverage for routes and service behavior. Runtime inputs and generated artifacts live in `assets/`, `pdf/`, `out/`, and `output/`; treat these as working data, not core source.

## Build, Test, and Development Commands
Use the repository virtualenv at `.venv` for local development and tests.

```powershell
.venv\Scripts\Activate.ps1
uv sync --python .venv\Scripts\python.exe
python app.py
pytest
pytest tests\test_app.py -k upload
```

`uv sync` installs dependencies from `pyproject.toml` and `uv.lock`. `python app.py` starts the local Flask server on port `5001`. `pytest` runs the full suite; use `-k` to target a workflow while iterating.

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, type-aware code where useful, and small service functions grouped by domain. Use `snake_case` for modules, functions, and variables; use descriptive names like `document_templates.py` or `test_submit_quota.py`. Keep route handlers thin and move OCR, translation, and persistence logic into `app/services/` or `ocr_pipeline/`.

## Testing Guidelines
The project uses `pytest` with Flask test clients and temporary-path fixtures. Add tests in `tests/` with names starting `test_*.py`, and keep test functions behavior-focused, for example `test_upload_missing_pdf`. Cover both happy paths and regression cases for upload flows, editor actions, and template persistence. If a change touches SQL-backed template storage, make sure the related fixture setup in `tests/conftest.py` still passes cleanly.

## Commit & Pull Request Guidelines
Recent history uses short, task-focused commit messages in Traditional Chinese, for example `修復補翻選區後畫面上移問題`. Keep commits narrowly scoped and written in imperative form. Pull requests should include a concise summary, affected user flow, test evidence (`pytest` command used), and screenshots for editor or layout changes.

## Security & Configuration Tips
Keep secrets in `.env` and avoid committing real credentials or generated job data. Database schema helpers live in `scripts/`, including `scripts/init_sqlserver_schema.sql`; review schema changes alongside application code before merging.
