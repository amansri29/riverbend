from app.config import Settings


def test_database_url_template_expands_from_environment(monkeypatch):
    monkeypatch.setenv("DB_APP_PASSWORD", "s3cr3t")
    s = Settings(
        _env_file=None,
        database_url_template="postgresql://riverbend_app:${DB_APP_PASSWORD}@/riverbend?host=/cloudsql/p:r:i",
    )
    assert s.database_url == "postgresql://riverbend_app:s3cr3t@/riverbend?host=/cloudsql/p:r:i"


def test_plain_database_url_still_wins_when_no_template():
    s = Settings(_env_file=None, database_url="postgresql://u:p@h/db")
    assert s.database_url == "postgresql://u:p@h/db"
