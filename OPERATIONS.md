# 正式環境部署

本專案正式環境使用 Alembic 管理 SQL Server schema。production 預設 `AUTO_SCHEMA_MANAGEMENT=0`，應用啟動時不自動建表或補欄位。

## 部署流程

1. 確認 `.env` 至少包含 `DATABASE_URL`、必要 OpenAI/Azure/LDAP 設定。
   若使用內建 SQL Server schema/migration，請設定 `DATABASE_SCHEMA=translation`。
2. 第一次導入既有資料庫時，如果 schema 已存在且完整，先執行 `alembic stamp head`。空資料庫或要由 migration 建表時，執行 `alembic upgrade head`。
3. 執行 `flask --app app.py schema-preflight` 確認必要 tables/columns 完整。
4. 執行 `flask --app app.py seed-bootstrap` 初始化 auth roles 與 bootstrap admins。
5. 使用 `bash deploy.sh` 同步套件、執行 migration/preflight/seed，並在 systemd 可用時安裝與重啟服務。

常用環境變數：

```bash
APP_ENV=production
AUTO_SCHEMA_MANAGEMENT=0
APP_DIR=/path/to/pdf_ocr_translate
ENV_FILE=/path/to/pdf_ocr_translate/.env
RUN_GIT_PULL=0
INSTALL_SYSTEMD_UNITS=1
MANAGE_SYSTEMD_SERVICES=auto
UV_SYNC_ARGS=--frozen
WEB_WORKERS=4
WEB_BIND=unix:/path/to/pdf_ocr_translate/uo_regulations_translate.sock
ENABLE_NGINX=0
NGINX_LISTEN_PORT=81
```

`MANAGE_SYSTEMD_SERVICES=auto` 會在偵測到 systemd 時才安裝 unit 與重啟服務；容器或非 systemd 環境會略過服務啟停。

## systemd

只產生 unit files：

```bash
bash scripts/install_systemd_units.sh --output-dir /tmp/translate-systemd
```

安裝 unit files：

```bash
sudo bash scripts/install_systemd_units.sh --install
sudo systemctl enable uo_regulations_translate uo_regulations_translate_worker
sudo systemctl start uo_regulations_translate uo_regulations_translate_worker
```

## Nginx

此 VM 會與 UO_MDR 使用同一個 domain、不同 listen port。建議 UO_MDR 維持 `listen 80`，本系統使用 `listen 81`，並分別安裝為不同 site config。

只產生站台設定：

```bash
bash scripts/install_nginx_site.sh --listen-port 81 --output-file /tmp/uo_regulations_translate
```

部署時同步 Nginx 站台設定：

```bash
ENABLE_NGINX=1 NGINX_LISTEN_PORT=81 bash deploy.sh
```
