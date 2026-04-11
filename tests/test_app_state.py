import json
import sys
import types
from pathlib import Path


def _install_fake_pyside():
    qtcore = types.ModuleType("PySide6.QtCore")
    qtqml = types.ModuleType("PySide6.QtQml")
    pyside6 = types.ModuleType("PySide6")

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._events = []

        def emit(self, *args, **kwargs):
            self._events.append((args, kwargs))

    class _QObject:
        pass

    class _QLoggingCategory:
        def __init__(self, name=""):
            self.name = name

    def _slot(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def _property(_type, fget, fset=None, notify=None):
        return property(fget, fset)

    def _qml_element(cls):
        return cls

    def _qml_singleton(cls):
        return cls

    def _noop(*args, **kwargs):
        return None

    qtcore.QObject = _QObject
    qtcore.Signal = _Signal
    qtcore.Slot = _slot
    qtcore.Property = _property
    qtcore.QLoggingCategory = _QLoggingCategory
    qtcore.qCCritical = _noop
    qtcore.qCDebug = _noop
    qtcore.qCInfo = _noop
    qtcore.qCWarning = _noop
    qtqml.QmlElement = _qml_element
    qtqml.QmlSingleton = _qml_singleton

    pyside6.QtCore = qtcore
    pyside6.QtQml = qtqml

    sys.modules.setdefault("PySide6", pyside6)
    sys.modules.setdefault("PySide6.QtCore", qtcore)
    sys.modules.setdefault("PySide6.QtQml", qtqml)


_install_fake_pyside()

import gui.app_state as app_state_module


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
