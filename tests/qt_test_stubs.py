from __future__ import annotations

import importlib
import sys
import types


def import_with_fake_pyside(module_name: str):
    try:
        importlib.import_module("PySide6")
    except ModuleNotFoundError:
        inserted = _install_fake_pyside()
        try:
            return importlib.import_module(module_name)
        finally:
            _remove_fake_modules(inserted)
    else:
        return importlib.import_module(module_name)


def _install_fake_pyside() -> list[str]:
    qtcore = types.ModuleType("PySide6.QtCore")
    qtqml = types.ModuleType("PySide6.QtQml")
    pyside6 = types.ModuleType("PySide6")
    inserted: list[str] = []

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._events = []
            self._callbacks = []

        def connect(self, callback):
            self._callbacks.append(callback)

        def emit(self, *args, **kwargs):
            self._events.append((args, kwargs))
            for callback in list(self._callbacks):
                callback(*args, **kwargs)

    class _QObject:
        def __init__(self, *args, **kwargs):
            pass

        def property(self, name):
            return getattr(self, name)

        def setProperty(self, name, value):
            setattr(self, name, value)

    class _QLoggingCategory:
        def __init__(self, name=""):
            self.name = name

    class _QTimer:
        def __init__(self, parent=None):
            self.parent = parent
            self.timeout = _Signal()
            self._active = False

        def setSingleShot(self, value):
            self._single_shot = bool(value)

        def setInterval(self, value):
            self._interval = int(value)

        def start(self):
            self._active = True

        def stop(self):
            self._active = False

        def isActive(self):
            return self._active

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
    qtcore.QTimer = _QTimer
    qtcore.QLoggingCategory = _QLoggingCategory
    qtcore.qCCritical = _noop
    qtcore.qCDebug = _noop
    qtcore.qCInfo = _noop
    qtcore.qCWarning = _noop
    qtqml.QmlElement = _qml_element
    qtqml.QmlSingleton = _qml_singleton

    pyside6.QtCore = qtcore
    pyside6.QtQml = qtqml

    for name, module in (
        ("PySide6", pyside6),
        ("PySide6.QtCore", qtcore),
        ("PySide6.QtQml", qtqml),
    ):
        if name not in sys.modules:
            sys.modules[name] = module
            inserted.append(name)

    return inserted


def _remove_fake_modules(module_names: list[str]) -> None:
    for name in module_names:
        sys.modules.pop(name, None)
