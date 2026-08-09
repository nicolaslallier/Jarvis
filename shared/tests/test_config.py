from jarvis_shared.config import SharedSettings


def test_defaults():
    settings = SharedSettings(database_url="postgresql://user:pass@localhost/db")
    assert settings.app_env == "development"
    assert settings.otel_exporter_otlp_endpoint == ""
    assert settings.minio_endpoint == "http://minio:9000"
    assert settings.minio_bucket == "jarvis"


def test_sqlalchemy_url_normalizes_postgres_scheme():
    settings = SharedSettings(database_url="postgres://user:pass@host:5432/db")
    assert settings.sqlalchemy_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_sqlalchemy_url_normalizes_postgresql_scheme():
    settings = SharedSettings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.sqlalchemy_url == "postgresql+asyncpg://user:pass@host:5432/db"


def test_sqlalchemy_url_passthrough_when_already_asyncpg():
    settings = SharedSettings(database_url="postgresql+asyncpg://user:pass@host:5432/db")
    assert settings.sqlalchemy_url == "postgresql+asyncpg://user:pass@host:5432/db"
