from __future__ import annotations

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtQml import QmlElement, QmlSingleton

QML_IMPORT_NAME = "DropMe"
QML_IMPORT_MAJOR_VERSION = 1
QML_IMPORT_MINOR_VERSION = 0


@QmlElement
@QmlSingleton
class AppState(QObject):
    """Central application/workflow state.

    Milestone 1 goal:
    - Move workflow flags out of QML (Global.qml / ad-hoc properties)
    - Keep UI layout + flow unchanged; QML binds to these reactive properties.
    """

    handInGateChanged = Signal()
    shouldSignOutChanged = Signal()
    languageChanged = Signal()
    languageCodeChanged = Signal()
    activePopupChanged = Signal()
    popupPayloadChanged = Signal()
    # Route-driven navigation (Milestone 1 — Decouple View Logic)
    currentRouteChanged = Signal()
    routePayloadChanged = Signal()
    # Recycle session state
    recyclePlasticBottlesChanged = Signal()
    recycleCansChanged = Signal()
    recyclePointsChanged = Signal()
    recycleHasFinishedChanged = Signal()
    recycleSessionActiveChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._hand_in_gate: bool = False
        self._should_sign_out: bool = False
        self._language: int = 1  # 0=Arabic, 1=English (matches Global.Language order)
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
        """Convenience reset used when the app returns to Start."""
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
        # 0 -> ar, 1 -> en
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
        v = value if value is not None else {}
        self._popup_payload = v
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
        v = str(value or "")
        # Always emit even if same route (allows re-navigating to same screen)
        self._current_route = v
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
        """Set the current route; StateManager reacts via onCurrentRouteChanged.
        Satisfies PDF Phase 2 — Decouple View Logic:
        AppState becomes source of truth for current screen.
        StateManager is a pure renderer that reacts to state.
        """
        self.set_route_payload(payload if payload is not None else {})
        self.set_current_route(route)

# ─── Recycle Session ────────────────────────────────────────────────────

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

    # recyclePoints is derived — notified whenever plastic or cans change
    recyclePoints = Property(int, get_recycle_points, notify=recyclePointsChanged)

    def get_recycle_has_finished(self) -> bool:
        return self._recycle_has_finished

    def set_recycle_has_finished(self, v: bool) -> None:
        self._recycle_has_finished = bool(v)
        self.recycleHasFinishedChanged.emit()

    recycleHasFinished = Property(bool, get_recycle_has_finished, set_recycle_has_finished, notify=recycleHasFinishedChanged)

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
        """Reset all session counters. Call from RecycleView.Component.onCompleted."""
        self._recycle_plastic = 0
        self._recycle_cans = 0
        self._recycle_has_finished = False
        self._recycle_session_active = True
        self.recyclePlasticBottlesChanged.emit()
        self.recycleCansChanged.emit()
        self.recyclePointsChanged.emit()
        self.recycleHasFinishedChanged.emit()
        self.recycleSessionActiveChanged.emit()

    @Slot()
    def endRecycleSession(self) -> None:
        """Clean up session. Call from RecycleView.Component.onDestruction."""
        self._recycle_session_active = False
        self.recycleSessionActiveChanged.emit()