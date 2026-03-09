from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtQml import QmlElement, QmlSingleton

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
@QmlSingleton
class AppState(QObject):
    """Central application/workflow state."""

    handInGateChanged = Signal()
    shouldSignOutChanged = Signal()
    languageChanged = Signal()
    languageCodeChanged = Signal()
    activePopupChanged = Signal()
    popupPayloadChanged = Signal()

    # Route-driven navigation
    currentRouteChanged = Signal()
    routePayloadChanged = Signal()

    # Recycle session state
    recyclePlasticBottlesChanged = Signal()
    recycleCansChanged = Signal()
    recyclePointsChanged = Signal()
    recycleHasFinishedChanged = Signal()
    recycleSessionActiveChanged = Signal()

    # Bin status state (driven by MCU events)
    recyclePlasticBinFullChanged = Signal()
    recycleCanBinFullChanged = Signal()
    recycleActiveFullBinChanged = Signal()

    # Recycle view -> requests executed in QML
    recycleRequestHardwareAction = Signal(str)  # action: 'can' | 'plastic' | 'other'
    recycleRequestServerAction = Signal(str)    # action: 'send_aluminum' | 'send_plastic'
    recycleRequestFinishPhoneNumber = Signal(str, int, int)  # phoneNumber, plastic, cans
    recycleRequestFinishQrCode = Signal(str, int, int)       # token/phoneNumber, plastic, cans

    # Recycle UI events
    recycleUiClockRestart = Signal()
    recycleUiShowCapture = Signal(str)
    recycleUiHandsInserted = Signal()
    recycleUiOtherInserted = Signal()
    recycleUiFinishedNoPoints = Signal()
    recycleUiFinishedQrCode = Signal()
    recycleUiBinFull = Signal(str)  # 'plastic' | 'can'

    def __init__(self) -> None:
        super().__init__()
        self._hand_in_gate: bool = False
        self._should_sign_out: bool = False
        self._language: int = 1  # 0=Arabic, 1=English
        self._active_popup: str = ""
        self._popup_payload: object = {}

        # Route-driven navigation
        self._current_route: str = ""
        self._route_payload: object = {}

        # Recycle session
        self._recycle_plastic: int = 0
        self._recycle_cans: int = 0
        self._recycle_has_finished: bool = False
        self._recycle_session_active: bool = False

        # Bin status (sticky until cleared in maintenance / restart)
        self._recycle_plastic_bin_full: bool = False
        self._recycle_can_bin_full: bool = False
        self._recycle_active_full_bin: str = ""

    # --- handInGate ---
    def get_hand_in_gate(self) -> bool:
        return self._hand_in_gate

    def set_hand_in_gate(self, value: bool) -> None:
        v = bool(value)
        if self._hand_in_gate == v:
            return
        self._hand_in_gate = v
        self.handInGateChanged.emit()

    handInGate = Property(bool, get_hand_in_gate, set_hand_in_gate, notify=handInGateChanged)

    # --- shouldSignOut ---
    def get_should_sign_out(self) -> bool:
        return self._should_sign_out

    def set_should_sign_out(self, value: bool) -> None:
        v = bool(value)
        if self._should_sign_out == v:
            return
        self._should_sign_out = v
        self.shouldSignOutChanged.emit()

    shouldSignOut = Property(bool, get_should_sign_out, set_should_sign_out, notify=shouldSignOutChanged)

    @Slot()
    def resetWorkflowFlags(self) -> None:
        self.set_hand_in_gate(False)
        self.set_should_sign_out(False)
        self.set_language(1)  # English

    # --- language ---
    def get_language(self) -> int:
        return int(self._language)

    def set_language(self, value: int) -> None:
        v = int(value)
        if self._language == v:
            return
        self._language = v
        self.languageChanged.emit()
        self.languageCodeChanged.emit()

    language = Property(int, get_language, set_language, notify=languageChanged)

    # --- languageCode (derived) ---
    def get_language_code(self) -> str:
        return "ar" if int(self._language) == 0 else "en"

    languageCode = Property(str, get_language_code, notify=languageCodeChanged)

    # --- activePopup ---
    def get_active_popup(self) -> str:
        return self._active_popup

    def set_active_popup(self, value: str) -> None:
        v = str(value or "")
        if self._active_popup == v:
            return
        self._active_popup = v
        self.activePopupChanged.emit()

    activePopup = Property(str, get_active_popup, set_active_popup, notify=activePopupChanged)

    # --- popupPayload ---
    def get_popup_payload(self) -> object:
        return self._popup_payload

    def set_popup_payload(self, value: object) -> None:
        self._popup_payload = value if value is not None else {}
        self.popupPayloadChanged.emit()

    popupPayload = Property(object, get_popup_payload, set_popup_payload, notify=popupPayloadChanged)

    @Slot(str, "QVariant")
    def showPopup(self, name: str, payload=None) -> None:
        self.set_popup_payload(payload if payload is not None else {})
        self.set_active_popup(name)

    @Slot()
    def clearPopup(self) -> None:
        self.set_active_popup("")
        self.set_popup_payload({})

    # --- currentRoute ---
    def get_current_route(self) -> str:
        return self._current_route

    def set_current_route(self, value: str) -> None:
        self._current_route = str(value or "")
        # Always emit even if same route (allows re-navigating to same screen)
        self.currentRouteChanged.emit()

    currentRoute = Property(str, get_current_route, set_current_route, notify=currentRouteChanged)

    # --- routePayload ---
    def get_route_payload(self) -> object:
        return self._route_payload

    def set_route_payload(self, value: object) -> None:
        self._route_payload = value if value is not None else {}
        self.routePayloadChanged.emit()

    routePayload = Property(object, get_route_payload, set_route_payload, notify=routePayloadChanged)

    @Slot(str, "QVariant")
    def navigateTo(self, route: str, payload=None) -> None:
        self.set_route_payload(payload if payload is not None else {})
        self.set_current_route(route)

    # --- Recycle counters ---
    def get_recycle_plastic(self) -> int:
        return self._recycle_plastic

    def set_recycle_plastic(self, v: int) -> None:
        self._recycle_plastic = int(v)
        self.recyclePlasticBottlesChanged.emit()

    recyclePlasticBottles = Property(int, get_recycle_plastic, set_recycle_plastic, notify=recyclePlasticBottlesChanged)

    def get_recycle_cans(self) -> int:
        return self._recycle_cans

    def set_recycle_cans(self, v: int) -> None:
        self._recycle_cans = int(v)
        self.recycleCansChanged.emit()

    recycleCans = Property(int, get_recycle_cans, set_recycle_cans, notify=recycleCansChanged)

    def get_recycle_points(self) -> int:
        return 2 * self._recycle_plastic + 4 * self._recycle_cans

    recyclePoints = Property(int, get_recycle_points, notify=recyclePointsChanged)

    def get_recycle_has_finished(self) -> bool:
        return self._recycle_has_finished

    def set_recycle_has_finished(self, v: bool) -> None:
        self._recycle_has_finished = bool(v)
        self.recycleHasFinishedChanged.emit()

    recycleHasFinished = Property(bool, get_recycle_has_finished, set_recycle_has_finished, notify=recycleHasFinishedChanged)

    # --- Recycle bin full flags ---
    def get_recycle_plastic_bin_full(self) -> bool:
        return self._recycle_plastic_bin_full

    def set_recycle_plastic_bin_full(self, v: bool) -> None:
        b = bool(v)
        if self._recycle_plastic_bin_full == b:
            return
        self._recycle_plastic_bin_full = b
        self.recyclePlasticBinFullChanged.emit()

    recyclePlasticBinFull = Property(bool, get_recycle_plastic_bin_full, set_recycle_plastic_bin_full, notify=recyclePlasticBinFullChanged)

    def get_recycle_can_bin_full(self) -> bool:
        return self._recycle_can_bin_full

    def set_recycle_can_bin_full(self, v: bool) -> None:
        b = bool(v)
        if self._recycle_can_bin_full == b:
            return
        self._recycle_can_bin_full = b
        self.recycleCanBinFullChanged.emit()

    recycleCanBinFull = Property(bool, get_recycle_can_bin_full, set_recycle_can_bin_full, notify=recycleCanBinFullChanged)

    def get_recycle_active_full_bin(self) -> str:
        return self._recycle_active_full_bin

    def set_recycle_active_full_bin(self, binName: str) -> None:
        b = str(binName or "").strip().lower()
        if b not in ("", "plastic", "can"):
            b = ""
        if self._recycle_active_full_bin == b:
            return
        self._recycle_active_full_bin = b
        self.recycleActiveFullBinChanged.emit()

    recycleActiveFullBin = Property(str, get_recycle_active_full_bin, set_recycle_active_full_bin, notify=recycleActiveFullBinChanged)

    @Slot(str)
    def markRecycleBinFull(self, binName: str) -> None:
        # Full-bin overlays are session-scoped in UI.
        if not self._recycle_session_active:
            return
        b = str(binName or "").strip().lower()
        if "plastic" in b:
            self.set_recycle_plastic_bin_full(True)
            self.set_recycle_active_full_bin("plastic")
        elif "can" in b:
            self.set_recycle_can_bin_full(True)
            self.set_recycle_active_full_bin("can")

    @Slot(str)
    def clearRecycleBinFull(self, binName: str = "") -> None:
        b = str(binName or "").strip().lower()
        if b == "":
            self.set_recycle_plastic_bin_full(False)
            self.set_recycle_can_bin_full(False)
            self.set_recycle_active_full_bin("")
            return
        if "plastic" in b:
            self.set_recycle_plastic_bin_full(False)
            if not self._recycle_can_bin_full:
                self.set_recycle_active_full_bin("")
            else:
                self.set_recycle_active_full_bin("can")
        elif "can" in b:
            self.set_recycle_can_bin_full(False)
            if not self._recycle_plastic_bin_full:
                self.set_recycle_active_full_bin("")
            else:
                self.set_recycle_active_full_bin("plastic")

    @Slot()
    def incrementRecyclePlastic(self) -> None:
        self.set_recycle_plastic(self._recycle_plastic + 1)
        self.recyclePointsChanged.emit()

    @Slot()
    def incrementRecycleCans(self) -> None:
        self.set_recycle_cans(self._recycle_cans + 1)
        self.recyclePointsChanged.emit()

    @Slot()
    def markRecycleFinished(self) -> None:
        self.set_recycle_has_finished(True)

    @Slot()
    def startRecycleSession(self) -> None:
        self._recycle_plastic = 0
        self._recycle_cans = 0
        self._recycle_has_finished = False
        self._recycle_session_active = True

        # Dev/prod parity requirement for UI testing:
        # each new recycle session starts from a clean visual state,
        # then MCU full-bin events rebuild state.
        self.set_recycle_plastic_bin_full(False)
        self.set_recycle_can_bin_full(False)
        self.set_recycle_active_full_bin("")

        self.recyclePlasticBottlesChanged.emit()
        self.recycleCansChanged.emit()
        self.recyclePointsChanged.emit()
        self.recycleHasFinishedChanged.emit()
        self.recycleSessionActiveChanged.emit()

    @Slot()
    def endRecycleSession(self) -> None:
        self._recycle_session_active = False
        self.recycleSessionActiveChanged.emit()

    # --- Recycle Prediction / Finish Logic ---
    @Slot(str, int, str, str)
    def onPredictionResult(self, pred: str, userType: int, phoneNumber: str, predImage: str = "") -> None:
        p = str(pred or "")
        u = int(userType)

        if p == "hand":
            self.recycleUiHandsInserted.emit()
            self.recycleUiClockRestart.emit()
            return

        if p == "aluminum":
            if self._recycle_can_bin_full:
                self.recycleUiBinFull.emit("can")
                self.recycleUiClockRestart.emit()
                return
            self.incrementRecycleCans()
            self.recycleRequestHardwareAction.emit("can")
            if u == 1:  # QrCode
                self.recycleRequestServerAction.emit("send_aluminum")
            self.recycleUiClockRestart.emit()
            if predImage:
                self.recycleUiShowCapture.emit(str(predImage))
            return

        if p == "plastic":
            if self._recycle_plastic_bin_full:
                self.recycleUiBinFull.emit("plastic")
                self.recycleUiClockRestart.emit()
                return
            self.incrementRecyclePlastic()
            self.recycleRequestHardwareAction.emit("plastic")
            if u == 1:  # QrCode
                self.recycleRequestServerAction.emit("send_plastic")
            self.recycleUiClockRestart.emit()
            if predImage:
                self.recycleUiShowCapture.emit(str(predImage))
            return

        if p == "other":
            self.recycleRequestHardwareAction.emit("other")
            self.recycleUiOtherInserted.emit()
            self.recycleUiClockRestart.emit()
            return

    @Slot(int, str)
    def onRecycleClockFinished(self, userType: int, phoneNumber: str) -> None:
        if self._recycle_has_finished:
            return
        self.markRecycleFinished()

        points = self.get_recycle_points()
        u = int(userType)
        pn = str(phoneNumber or "")

        if points == 0:
            self.recycleUiFinishedNoPoints.emit()
            return

        if u == 1:  # QrCode
            self.recycleUiFinishedQrCode.emit()
            self.recycleRequestFinishQrCode.emit(pn, int(self._recycle_plastic), int(self._recycle_cans))
            return

        self.recycleRequestFinishPhoneNumber.emit(pn, int(self._recycle_plastic), int(self._recycle_cans))







