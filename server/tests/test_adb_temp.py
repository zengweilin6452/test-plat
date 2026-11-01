from types import SimpleNamespace

from app.integrations import devices


def test_windows_adb_uses_writable_project_temp(tmp_path, monkeypatch):
    adb = tmp_path / "adb.exe"
    adb.touch()
    monkeypatch.setattr(devices.sys, "platform", "win32")
    monkeypatch.setattr(devices, "settings", SimpleNamespace(repo_root=tmp_path))
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="List of devices attached\n", stderr="")

    monkeypatch.setattr(devices.subprocess, "run", run)
    assert devices.list_devices(adb) == []
    env = calls[0][1]["env"]
    assert env["TEMP"] == env["TMP"] == str(tmp_path / ".runtime" / "adb-tmp")
    assert (tmp_path / ".runtime" / "adb-tmp").is_dir()
