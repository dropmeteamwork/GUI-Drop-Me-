from tests.qt_test_stubs import import_with_fake_pyside

UiCoordinator = import_with_fake_pyside("gui.ui_coordinator").UiCoordinator


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
        self.gate_blocked = False

    def closeDoor(self):
        self.calls.append(("closeDoor",))

    def isGateBlocked(self):
        return self.gate_blocked


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


def test_gate_alarm_shows_remove_hand_popup():
    app = FakeAppState()
    ui = UiCoordinator()
    ui.appState = app

    ui.handleHwHandInGate()

    assert app.handInGate is True
    assert ("showPopup", "hands", {}) in app.calls


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


def test_hw_gate_cleared_ignored_while_alarm_still_active():
    app = FakeAppState()
    serial = FakeSerial()
    serial.gate_blocked = True

    ui = UiCoordinator()
    ui.appState = app
    ui.serial = serial

    app.handInGate = True
    app.activePopup = "hands"

    ui.handleHwGateCleared()

    assert app.handInGate is True
    assert ("clearPopup",) not in app.calls
