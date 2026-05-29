# 正式環境部署與資料庫維運

本專案正式環境使用 Alembic 管理 SQL Server schema。production 預設 `AUTO_SCHEMA_MANAGEMENT=0`，應用啟動時不自動建表或補欄位。

## 部署流程

1. 確認 `.env` 至少包含 `DATABASE_URL`、必要 OpenAI/Azure/LDAP 設定。
2. 第一次導入既有資料庫時，如果 schema 已存在且完整，先執行 `alembic stamp head`。空資料庫或要由 migration 建表時，執行 `alembic upgrade head`。
3. 執行 `flask --app app.py schema-preflight` 確認必要 tables/columns 完整。
4. 執行 `flask --app app.py seed-bootstrap` 初始化 auth roles 與 bootstrap admins。
5. 使用 `bash deploy.sh` 部署並重啟 systemd services。

常用環境變數：

```bash
APP_ENV=production
AUTO_SCHEMA_MANAGEMENT=0
RUN_GIT_PULL=0
RUN_DB_BACKUP=1
INSTALL_SYSTEMD_UNITS=1
WEB_WORKERS=4
WEB_BIND=unix:uo_regulations_translate.sock
```

## 資料庫備份與還原

部署前備份：

```bash
SQLCMD_SERVER=... SQLCMD_USER=... SQLCMD_PASSWORD=... MSSQL_DATABASE=... MSSQL_BACKUP_DIR=... \
  bash scripts/backup_mssql_full.sh
```

原地還原會覆蓋目標資料庫，必須明確加上 `--yes`：

```bash
SQLCMD_SERVER=... SQLCMD_USER=... SQLCMD_PASSWORD=... MSSQL_DATABASE=... MSSQL_BACKUP_FILE=... \
  bash scripts/restore_mssql_replace.sh --yes
```

## systemd

只產生 unit files：

```bash
bash scripts/install_systemd_units.sh --output-dir /tmp/translate-systemd
```

安裝 unit files：

```bash
sudo bash scripts/install_systemd_units.sh --install
sudo systemctl enable uo_regulations_translate_worker
sudo systemctl start uo_regulations_translate uo_regulations_translate_worker
```
