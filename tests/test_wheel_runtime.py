"""MIG-001: installed wheels use the explicit service working directory for migrations."""

from pathlib import Path

import pytest

import whatsapp_chat_system.standalone_api as api_module


def test_installed_package_finds_migrations_in_service_working_directory(
    tmp_path, monkeypatch
):
    expected = api_module._current_alembic_head()
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setattr(
        api_module,
        "__file__",
        str(tmp_path / "site-packages" / "whatsapp_chat_system" / "standalone_api.py"),
    )
    monkeypatch.chdir(project_root)
    assert api_module._current_alembic_head() == expected


def test_installed_package_without_migration_assets_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        api_module,
        "__file__",
        str(tmp_path / "site-packages" / "whatsapp_chat_system" / "standalone_api.py"),
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="migration assets"):
        api_module._current_alembic_head()
