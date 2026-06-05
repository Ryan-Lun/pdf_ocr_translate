IF SCHEMA_ID(N'translation') IS NULL
    EXEC(N'CREATE SCHEMA [translation]');
GO

IF OBJECT_ID(N'translation.document_templates', N'U') IS NOT NULL
    DROP TABLE translation.document_templates;
IF OBJECT_ID(N'translation.job_events', N'U') IS NOT NULL
    DROP TABLE translation.job_events;
IF OBJECT_ID(N'translation.job_artifacts', N'U') IS NOT NULL
    DROP TABLE translation.job_artifacts;
IF OBJECT_ID(N'translation.jobs', N'U') IS NOT NULL
    DROP TABLE translation.jobs;
GO

IF OBJECT_ID(N'translation.users', N'U') IS NULL
BEGIN
    CREATE TABLE translation.users (
        id int IDENTITY(1,1) NOT NULL,
        work_id nvarchar(100) NOT NULL,
        display_name nvarchar(200) NULL,
        email nvarchar(200) NULL,
        is_active bit NOT NULL CONSTRAINT DF_translation_users_is_active DEFAULT (1),
        created_at datetime2(6) NOT NULL CONSTRAINT DF_translation_users_created_at DEFAULT (SYSUTCDATETIME()),
        last_login_at datetime2(6) NULL,
        CONSTRAINT PK_translation_users PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_translation_users_work_id UNIQUE (work_id)
    );
END;
GO

IF OBJECT_ID(N'translation.roles', N'U') IS NULL
BEGIN
    CREATE TABLE translation.roles (
        id int IDENTITY(1,1) NOT NULL,
        name nvarchar(50) NOT NULL,
        CONSTRAINT PK_translation_roles PRIMARY KEY CLUSTERED (id),
        CONSTRAINT UQ_translation_roles_name UNIQUE (name)
    );
END;
GO

IF OBJECT_ID(N'translation.user_roles', N'U') IS NULL
BEGIN
    CREATE TABLE translation.user_roles (
        user_id int NOT NULL,
        role_id int NOT NULL,
        CONSTRAINT PK_translation_user_roles PRIMARY KEY CLUSTERED (user_id, role_id),
        CONSTRAINT UQ_translation_user_roles_user_id UNIQUE (user_id),
        CONSTRAINT FK_translation_user_roles_users FOREIGN KEY (user_id) REFERENCES translation.users(id) ON DELETE CASCADE,
        CONSTRAINT FK_translation_user_roles_roles FOREIGN KEY (role_id) REFERENCES translation.roles(id) ON DELETE CASCADE
    );
END;
GO

CREATE TABLE translation.jobs (
    job_id char(32) NOT NULL,
    job_type varchar(50) NOT NULL,
    status varchar(30) NOT NULL,
    stage varchar(50) NULL,
    progress float NOT NULL CONSTRAINT DF_translation_jobs_progress DEFAULT (0),
    job_name nvarchar(255) NULL,
    owner_work_id nvarchar(100) NULL,
    target_lang varchar(20) NULL,
    document_mode varchar(20) NULL,
    payload_json nvarchar(max) NULL,
    error_message nvarchar(max) NULL,
    cancel_requested bit NOT NULL CONSTRAINT DF_translation_jobs_cancel_requested DEFAULT (0),
    retry_count int NOT NULL CONSTRAINT DF_translation_jobs_retry_count DEFAULT (0),
    worker_id varchar(100) NULL,
    started_at datetime2(6) NULL,
    completed_at datetime2(6) NULL,
    created_at datetime2(6) NOT NULL CONSTRAINT DF_translation_jobs_created_at DEFAULT (SYSUTCDATETIME()),
    updated_at datetime2(6) NOT NULL CONSTRAINT DF_translation_jobs_updated_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_translation_jobs PRIMARY KEY CLUSTERED (job_id)
);
GO

CREATE TABLE translation.job_artifacts (
    id bigint IDENTITY(1,1) NOT NULL,
    job_id char(32) NOT NULL,
    artifact_type varchar(50) NOT NULL,
    file_path nvarchar(1000) NOT NULL,
    created_at datetime2(6) NOT NULL CONSTRAINT DF_translation_job_artifacts_created_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_translation_job_artifacts PRIMARY KEY CLUSTERED (id),
    CONSTRAINT FK_translation_job_artifacts_jobs FOREIGN KEY (job_id) REFERENCES translation.jobs(job_id)
);
GO

CREATE TABLE translation.job_events (
    id bigint IDENTITY(1,1) NOT NULL,
    job_id char(32) NOT NULL,
    event_type varchar(50) NOT NULL,
    stage varchar(50) NULL,
    message nvarchar(max) NULL,
    created_at datetime2(6) NOT NULL CONSTRAINT DF_translation_job_events_created_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_translation_job_events PRIMARY KEY CLUSTERED (id),
    CONSTRAINT FK_translation_job_events_jobs FOREIGN KEY (job_id) REFERENCES translation.jobs(job_id)
);
GO

CREATE TABLE translation.document_templates (
    template_id char(32) NOT NULL,
    name nvarchar(255) NOT NULL CONSTRAINT DF_translation_document_templates_name DEFAULT (N''),
    display_name nvarchar(255) NULL,
    owner_work_id nvarchar(100) NULL,
    source_job_id char(32) NULL,
    status varchar(20) NOT NULL CONSTRAINT DF_translation_document_templates_status DEFAULT ('saved'),
    payload_json nvarchar(max) NULL,
    created_at datetime2(6) NOT NULL CONSTRAINT DF_translation_document_templates_created_at DEFAULT (SYSUTCDATETIME()),
    updated_at datetime2(6) NOT NULL CONSTRAINT DF_translation_document_templates_updated_at DEFAULT (SYSUTCDATETIME()),
    CONSTRAINT PK_translation_document_templates PRIMARY KEY CLUSTERED (template_id)
);
GO

CREATE INDEX IX_translation_jobs_status_created_at
ON translation.jobs (status, created_at);
GO

CREATE INDEX IX_translation_jobs_job_type_updated_at
ON translation.jobs (job_type, updated_at DESC);
GO

CREATE INDEX IX_translation_jobs_owner_work_id
ON translation.jobs (owner_work_id);
GO

CREATE INDEX IX_translation_jobs_cancel_requested_status
ON translation.jobs (cancel_requested, status);
GO

CREATE INDEX IX_translation_job_artifacts_job_id
ON translation.job_artifacts (job_id);
GO

CREATE INDEX IX_translation_job_events_job_id_created_at
ON translation.job_events (job_id, created_at DESC);
GO

CREATE INDEX IX_translation_document_templates_source_job_id
ON translation.document_templates (source_job_id);
GO

CREATE INDEX IX_translation_document_templates_owner_work_id
ON translation.document_templates (owner_work_id);
GO

CREATE INDEX IX_translation_document_templates_updated_at
ON translation.document_templates (updated_at DESC);
GO
