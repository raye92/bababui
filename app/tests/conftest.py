"""Keep all diagnostic storage outside real app data."""
import pytest


@pytest.fixture(autouse=True)
def temporary_save_locks(tmp_path, monkeypatch):
    from app.src import documents, jobs
    monkeypatch.setattr(jobs, 'APP_DIR', tmp_path)
    monkeypatch.setattr(documents, 'NATIVE_ASSET_DIR', tmp_path / 'casecat')
    monkeypatch.setattr(documents, 'SAVE_LOCK_DIR', tmp_path/'save-locks')
