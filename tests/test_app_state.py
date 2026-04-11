import json
from pathlib import Path

from tests.qt_test_stubs import import_with_fake_pyside

app_state_module = import_with_fake_pyside("gui.app_state")


def _workspace_sandbox_dir(name: str) -> Path:
    root = Path.cwd() / "tests" / "_tmp_app_state"
    target = root / name
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_start_recycle_session_preserves_known_full_bins(monkeypatch):
    project_dir = _workspace_sandbox_dir("preserve_bins")
    monkeypatch.setattr(app_state_module, "PROJECT_DIR", project_dir)
    state = app_state_module.AppState()
    state.setRecycleBinState("plastic", True)
    state.setRecycleBinState("can", False)

    state.startRecycleSession()

    assert state.recyclePlasticBinFull is True
    assert state.recycleCanBinFull is False
    assert state.recycleActiveFullBin == "plastic"


def test_app_state_restores_persisted_basket_state(monkeypatch):
    project_dir = _workspace_sandbox_dir("restore_bins")
    snapshot_path = project_dir / "src" / "dropme_protocol_logs"
    snapshot_path.mkdir(parents=True, exist_ok=True)
    (snapshot_path / "sensor_snapshot.json").write_text(
        json.dumps(
            {
                "bins": {
                    "plastic_full": True,
                    "can_full": False,
                    "reject_full": False,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(app_state_module, "PROJECT_DIR", project_dir)

    state = app_state_module.AppState()

    assert state.recyclePlasticBinFull is True
    assert state.recycleCanBinFull is False
    assert state.recycleActiveFullBin == "plastic"
