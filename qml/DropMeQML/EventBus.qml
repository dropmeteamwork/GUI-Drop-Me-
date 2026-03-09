pragma Singleton
import QtQuick

QtObject {
    // UI-level events (navigation + popups)
    signal showPopup(string popupName, var payload)
    signal navigate(string route, var payload)
    signal resetToStart()

    // Hardware-derived events (abstracted from Serial/AutoSerial)
    signal hwHandInGate()
    signal hwGateCleared()
    signal hwBinFull(string binName)
    signal hwError(string errorName, int errorId)

    // Optional: simple publish helper (nice for consistency)
    function emitPopup(name, payload) { showPopup(name, payload ?? ({})) }
    function emitNav(route, payload) { navigate(route, payload ?? ({})) }
}
