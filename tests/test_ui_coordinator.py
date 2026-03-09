import sys
import types


def _install_fake_pyside():
    qtcore = types.ModuleType("PySide6.QtCore")
    qtqml = types.ModuleType("PySide6.QtQml")
    pyside6 = types.ModuleType("PySide6")

    class _Signal:
        def __init__(self, *args, **kwargs):
            self._events = []
        def emit(self, *args, **kwargs):
            self._events.append((args, kwargs))

    class _QLoggingCategory:
        def __init__(self, name=""):
            self.name = name

    class _QObject:
        def property(self, name):
            return getattr(self, name)
        def setProperty(self, name, value):
            setattr(self, name, value)

    def _slot(*args, **kwargs):
        def deco(fn):
            return fn
        return deco

    def _property(_type, fget, fset=None, notify=None):
        return property(fget, fset)

    def _qml_element(cls):
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

    pyside6.QtCore = qtcore
    pyside6.QtQml = qtqml

    sys.modules.setdefault("PySide6", pyside6)
    sys.modules.setdefault("PySide6.QtCore", qtcore)
    sys.modules.setdefault("PySide6.QtQml", qtqml)


_install_fake_pyside()

from gui.ui_coordinator import UiCoordinator


class FakeAppState:
    def __init__(self):
        self.handInGate = False
        self.shouldSignOut = False
        self.activePopup = ""
        self.language = 1
        self.calls = []

    def property(self, name):
        return getattr(self, name)

    def setProperty(self, name, value):
        setattr(self, name, value)

    def navigateTo(self, route, payload):
        self.calls.append(("navigateTo", route, payload))

    def showPopup(self, name, payload):
        self.activePopup = name
        self.calls.append(("showPopup", name, payload))

    def clearPopup(self):
        self.activePopup = ""
        self.calls.append(("clearPopup",))

    def startRecycleSession(self):
        self.calls.append(("startRecycleSession",))

    def markRecycleBinFull(self, name):
        self.calls.append(("markRecycleBinFull", name))


class FakeSerial:
    def __init__(self):
        self.calls = []

    def closeDoor(self):
        self.calls.append(("closeDoor",))


def test_navigate_start_sets_flag_and_routes():
    app = FakeAppState()
    ui = UiCoordinator()
    ui.appState = app

    app.shouldSignOut = True
    ui.handleNavigate("start", {})

    assert app.shouldSignOut is False
    assert ("navigateTo", "start", {}) in app.calls


def test_navigate_recycle_starts_session():
    app = FakeAppState()
    ui = UiCoordinator()
    ui.appState = app

    ui.handleNavigate("recycle_qr", {})

    assert ("startRecycleSession",) in app.calls
    assert ("navigateTo", "recycle_qr", {}) in app.calls


def test_show_popup_validates_key():
    app = FakeAppState()
    ui = UiCoordinator()
    ui.appState = app

    ui.handleShowPopup("timeout", {"x": 1})
    assert ("showPopup", "timeout", {"x": 1}) in app.calls

    before = len(app.calls)
    ui.handleShowPopup("unknown_popup", {})
    assert len(app.calls) == before


def test_hw_gate_cleared_with_deferred_signout():
    app = FakeAppState()
    serial = FakeSerial()

    ui = UiCoordinator()
    ui.appState = app
    ui.serial = serial

    app.handInGate = True
    app.shouldSignOut = True
    app.activePopup = "hands"

    ui.handleHwGateCleared()

    assert app.handInGate is False
    assert app.shouldSignOut is False
    assert ("clearPopup",) in app.calls
    assert ("closeDoor",) in serial.calls
    assert ("navigateTo", "start", {}) in app.calls
