"""Regresión de la publicación de ZIP de Les Enfants en Google Drive."""

from types import SimpleNamespace

from tests._streamlit_stub import install as _install_streamlit_stub

_install_streamlit_stub()

import modules.les_enfants_terribles as m  # noqa: E402


class _Request:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _Files:
    def __init__(self, response):
        self.response = response
        self.get_calls = []
        self.create_calls = []

    def get(self, **kwargs):
        self.get_calls.append(kwargs)
        return _Request({"id": kwargs["fileId"], "name": "Planeación", "driveId": "shared"})

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return _Request(self.response)


class _Service:
    def __init__(self, response):
        self.files_api = _Files(response)

    def files(self):
        return self.files_api


def test_planning_drive_uses_configurable_folder_and_returns_real_link(tmp_path, monkeypatch):
    zip_path = tmp_path / "Planeacion_03-11-2026.zip"
    zip_path.write_bytes(b"zip")
    monkeypatch.setattr(m, "configured_planning_drive_folder_id", lambda: "configured-folder")
    service = _Service({"id": "drive-file-id"})

    result = m.upload_planning_zip_to_drive(
        {"zip": str(zip_path), "origins": [444], "run_date": "2026-11-03"},
        service=service,
        media_upload_factory=lambda *_args, **_kwargs: "media",
    )

    assert result == "https://drive.google.com/open?id=drive-file-id"
    assert service.files_api.get_calls[0]["fileId"] == "configured-folder"
    assert service.files_api.create_calls[0]["body"]["parents"] == ["configured-folder"]


def test_planning_drive_connection_checks_folder_without_creating_files(monkeypatch):
    monkeypatch.setattr(m, "configured_planning_drive_folder_id", lambda: "folder")
    service = _Service({"id": "unused"})

    result = m.test_planning_drive_connection(service=service)

    assert "Planeación" in result
    assert not service.files_api.create_calls


def test_oauth_values_accept_existing_mother_base_secret_names(monkeypatch):
    values = {
        "DATA_DASHBOARD_OAUTH_CLIENT_ID": "client",
        "DATA_DASHBOARD_OAUTH_CLIENT_SECRET": "secret",
        "MAIL_OAUTH_REFRESH_TOKEN": "token",
    }
    monkeypatch.setattr(m, "_planning_drive_secret", lambda key: values.get(key, ""))
    assert m._planning_drive_oauth_values() == ("client", "secret", "token")
