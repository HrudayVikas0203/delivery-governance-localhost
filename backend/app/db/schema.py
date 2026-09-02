from sqlalchemy import inspect, text

from app.db.session import engine


MYSQL_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {
        "tags": "JSON NULL",
        "checklist": "JSON NULL",
        "rejection_reason": "TEXT NULL",
        "submitted_for_review_at": "DATETIME NULL",
        "approved_at": "DATETIME NULL",
    },
    "resource_allocations": {
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "updated_at": "DATETIME NULL",
    },
    "brd_documents": {
        "storage_path": "VARCHAR(512) NULL",
        "error_message": "TEXT NULL",
    },
    "report_templates": {
        "filename": "VARCHAR(255) NULL",
        "content_type": "VARCHAR(120) NULL",
        "size_bytes": "INTEGER NULL",
        "content_bytes": "MEDIUMBLOB NULL",
        "content_sha256": "VARCHAR(64) NULL",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "updated_at": "DATETIME NULL",
        "account_id": "VARCHAR(36) NULL",
        "project_id": "VARCHAR(36) NULL",
    },
    "scheduled_emails": {
        "html_body": "TEXT NULL",
    },
    "generated_reports": {
        "llm_provider": "VARCHAR(40) NULL",
        "llm_model": "VARCHAR(120) NULL",
        "filename": "VARCHAR(255) NULL",
        "content_type": "VARCHAR(120) NULL",
        "size_bytes": "INTEGER NULL",
        "content_bytes": "LONGBLOB NULL",
    },
}

SQLITE_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {
        "tags": "JSON NOT NULL DEFAULT '[]'",
        "checklist": "JSON NOT NULL DEFAULT '[]'",
        "rejection_reason": "TEXT NULL",
        "submitted_for_review_at": "DATETIME NULL",
        "approved_at": "DATETIME NULL",
    },
    "resource_allocations": {
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "updated_at": "DATETIME NULL",
    },
    "brd_documents": {
        "storage_path": "VARCHAR(512) NULL",
        "error_message": "TEXT NULL",
    },
    "report_templates": {
        "filename": "VARCHAR(255) NULL",
        "content_type": "VARCHAR(120) NULL",
        "size_bytes": "INTEGER NULL",
        "content_bytes": "BLOB NULL",
        "content_sha256": "VARCHAR(64) NULL",
        "is_active": "BOOLEAN NOT NULL DEFAULT 1",
        "updated_at": "DATETIME NULL",
        "account_id": "VARCHAR(36) NULL",
        "project_id": "VARCHAR(36) NULL",
    },
    "scheduled_emails": {
        "html_body": "TEXT NULL",
    },
    "generated_reports": {
        "llm_provider": "VARCHAR(40) NULL",
        "llm_model": "VARCHAR(120) NULL",
        "filename": "VARCHAR(255) NULL",
        "content_type": "VARCHAR(120) NULL",
        "size_bytes": "INTEGER NULL",
        "content_bytes": "BLOB NULL",
    },
}


def ensure_schema_upgrades() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name
    column_specs = SQLITE_COLUMNS if dialect == "sqlite" else MYSQL_COLUMNS

    with engine.begin() as conn:
        for table_name, columns in column_specs.items():
            if table_name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))

        # SQLAlchemy persists Python Enum member names in MySQL. Expand the
        # existing enums additively so deployments created before these roles
        # continue to accept the complete organization hierarchy.
        if dialect == "mysql" and "employees" in existing_tables:
            role_column = next(column for column in inspector.get_columns("employees") if column["name"] == "role")
            existing_roles = set(getattr(role_column["type"], "enums", []) or [])
            employee_roles = [
                "INTERN", "DEVELOPER", "TEAM_LEAD", "PROJECT_MANAGER",
                "PROGRAM_MANAGER", "PROGRAM_DIRECTOR", "DELIVERY_HEAD", "STUDIO_HEAD",
            ]
            if not set(employee_roles).issubset(existing_roles):
                values = ",".join(f"'{value}'" for value in employee_roles)
                conn.execute(text(f"ALTER TABLE employees MODIFY COLUMN role ENUM({values}) NOT NULL"))

        if dialect == "mysql" and "resource_allocations" in existing_tables:
            allocation_column = next(column for column in inspector.get_columns("resource_allocations") if column["name"] == "allocation_role")
            existing_allocation_roles = set(getattr(allocation_column["type"], "enums", []) or [])
            allocation_roles = [
                "STUDIO_HEAD", "INTERN", "DEVELOPER", "TEAM_LEAD",
                "PROJECT_MANAGER", "PROGRAM_MANAGER", "ARCHITECT",
                "TECHNICAL_ARCHITECT", "SOLUTION_ARCHITECT", "DATABASE_ENGINEER",
                "BACKEND_ENGINEER", "FRONTEND_ENGINEER", "FULL_STACK_ENGINEER",
                "MOBILE_DEVELOPER", "QA", "QA_ANALYST", "TESTING_ENGINEER", "DEVOPS", "DEVOPS_ENGINEER",
                "CLOUD_ENGINEER", "UI_UX_DESIGNER", "BUSINESS_ANALYST", "DATA_ENGINEER",
                "AI_ML_ENGINEER", "SECURITY_ENGINEER",
            ]
            if not set(allocation_roles).issubset(existing_allocation_roles):
                values = ",".join(f"'{value}'" for value in allocation_roles)
                conn.execute(text(f"ALTER TABLE resource_allocations MODIFY COLUMN allocation_role ENUM({values}) NOT NULL"))
