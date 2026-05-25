from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_uses_env_and_persistent_data_volume():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "smsverify-web" in compose
    assert "${APP_PORT:-8000}:8000" in compose
    assert "SMSVERIFY_TOKEN: ${SMSVERIFY_TOKEN:?请配置 SMSVERIFY_TOKEN}" in compose
    assert "ADMIN_PASSWORD: ${ADMIN_PASSWORD:?请配置 ADMIN_PASSWORD}" in compose
    assert "SESSION_SECRET: ${SESSION_SECRET:?请配置 SESSION_SECRET}" in compose
    assert "SMSVERIFY_BASE_URL: ${SMSVERIFY_BASE_URL:?请配置 SMSVERIFY_BASE_URL}" in compose
    assert "SMSVERIFY_DATABASE: /app/data/smsverify.db" in compose
    assert "smsverify-data:/app/data" in compose
    assert "smsverify-data:" in compose
    assert "./data:/app/data" not in compose
    assert "dev-token" not in compose
    assert "dev-secret" not in compose


def test_dockerfile_runs_with_uv_without_copying_local_runtime_state():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "ghcr.io/astral-sh/uv:python3.13" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert 'CMD ["uv", "run", "--frozen", "--no-dev", "uvicorn"' in dockerfile
    assert "buy_sms.py" not in dockerfile
    assert ".venv" in dockerignore
    assert "data/" in dockerignore
    assert "__pycache__/" in dockerignore
    assert "buy_sms.py" in gitignore


def test_public_repo_files_do_not_expose_real_provider_host():
    scanned_paths = [
        ROOT / "app",
        ROOT / "README.md",
        ROOT / "Dockerfile",
        ROOT / "docker-compose.yml",
        ROOT / ".env.example",
    ]

    for path in scanned_paths:
        files = path.rglob("*") if path.is_dir() else [path]
        for file_path in files:
            if file_path.is_file() and "__pycache__" not in file_path.parts:
                assert "smsverify.online" not in file_path.read_text(encoding="utf-8")
