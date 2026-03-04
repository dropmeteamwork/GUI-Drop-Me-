import QML
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import DropMe

import "."   // ✅ ensures EnterCredentialsView, StartView, etc are visible

Item {
    id: sm
    anchors.fill: parent

    required property Image captureImage
    required property Item bottomView
    required property CaptureSession captureSession

    // ✅ Centralized UI-flow flags belong here (not implicit globals)
    property bool transitionedFromStart: false
    // Popup payload kept in QML to avoid lossy Python QVariantMap round-trip
    property var _pendingPopupPayload: ({})
    property var _pendingRoutePayload: ({})

    function goToStart() {
        view.clear()
        view.push(startView)
        AppState.shouldSignOut = false
        sm.transitionedFromStart = false
    }

    function goToStartOrDefer() {
        if (AppState.handInGate) {
            AppState.shouldSignOut = true
            return
        }
        goToStart()
    }

    function _executeRoute(route, payload) {
        // Called only by onCurrentRouteChanged. "back" is handled
        // directly in EventBus.onNavigate and never reaches here.
        payload = payload || {}

        switch (route) {
        case "start":
            goToStart()
            return

        case "select_language":
            view.push(selectLanguageView)
            return

        case "maintenance":
            if (payload.language !== undefined)
                AppState.language = payload.language
            view.push(maintenanceView)
            return

        case "enter_credentials":
            view.background.name = "background-with-logo"
            sm.transitionedFromStart = false
            view.push(enterCredentialsView)
            return

        case "recycle_qr":
            view.push(recycleView, {
                          "userType": Global.UserType.QrCode,
                          "imageCapture": sm.captureSession.imageCapture
                      })
            return

        case "recycle_phone":
            view.push(recycleView, {
                          "userType": Global.UserType.PhoneNumber,
                          "phoneNumber": payload.phoneNumber,
                          "imageCapture": sm.captureSession.imageCapture
                      })
            return

        default:
            console.log("[StateManager] Unknown route:", route)
            return
        }
    }

    function popupComponentFor(name) {
        switch (name) {
        case "hands": return popupHandsView
        case "hands_and_close": return popupHandsAndCloseView
        case "non_recyclable": return popupNonRecyclableView
        case "timeout": return popupTimeoutView
        case "invalid_phone": return invalidPhoneNumberView
        case "finished_qr": return popupFinishedQrCodeRecycleView
        case "finished_phone": return popupFinishedPhoneNumberRecycleView
        case "out_of_service": return popupOutOfServiceView
        default: return null
        }
    }

    StackView {
        id: view
        anchors.fill: parent
        initialItem: startView
        background: Resource { name: "background" }
        onEmptyChanged: background.name = "background"

        // ✅ match old repo: when popup is shown, underlying screen is NOT visible/clickable
        enabled: AppState.activePopup === ""

        // instant swap
        pushEnter: null
        pushExit: null
        popEnter: null
        popExit: null
        replaceEnter: null
        replaceExit: null
    }


    Connections {
        target: EventBus

        function onNavigate(route, payload) {
            // "back" is a UI-gesture pop — does not update AppState.currentRoute
            if (route === "back") {
                view.pop()
                return
            }
            // Cache payload in QML before the Python round-trip (same pattern as popup payload).
            // AppState.navigateTo() sets currentRoute → fires onCurrentRouteChanged below.
            sm._pendingRoutePayload = payload || {}
            AppState.navigateTo(route, payload)
        }

        function onShowPopup(popupName, payload) {
            // Cache payload in QML BEFORE handing off to Python.
            // Python's Property(object) → QVariantMap round-trip can drop keys,
            // causing createObject to fail with "required property not initialized".
            sm._pendingPopupPayload = payload || {}
            AppState.showPopup(popupName, payload)
        }
        function onResetToStart() { sm.goToStart() }

        function onHwHandInGate() {
            if (AppState.handInGate) return
            AppState.handInGate = true
            AppState.showPopup("hands_and_close", {})
        }

        function onHwBinFull(binName) {
            AppState.showPopup("out_of_service", {})
        }

        function onHwError(errorName, errorId) {
            console.log("MCU Error:", errorName, errorId)
            AppState.showPopup("out_of_service", {})
        }
    }

    Component {
        id: startView
        StartView {
            onStart: EventBus.navigate("select_language", {})
            onPattern: language => EventBus.navigate("maintenance", {"language": language})
        }
    }

    Resource {
        id: popupBackdropImg
        anchors.fill: parent
        z: 9000
        visible: AppState.activePopup !== ""
        name: view.background.name  // or "background-with-logo" depending on which area you mean
    }

    Item {
        id: popupLayer
        anchors.fill: parent
        z: 9999
        visible: AppState.activePopup !== ""

        // the actual popup object instance (created/destroyed centrally)
        property var popupItem: null
    }

    property bool _popupRenderScheduled: false
    function _renderPopup() {
        const name = AppState.activePopup

        // 1) Clear current popup instance
        if (popupLayer.popupItem) {
            popupLayer.popupItem.destroy()
            popupLayer.popupItem = null
        }

        // 2) No popup requested
        if (!name) {
            popupLayer.visible = false
            return
        }

        // 3) Resolve popup component
        const comp = popupComponentFor(name)
        if (!comp) {
            console.log("[StateManager] Unknown popup:", name)
            popupLayer.visible = false
            return
        }

        // 4) Use the QML-cached payload (avoids lossy Python → QVariantMap → JS round-trip).
        //    Falls back to AppState.popupPayload for popups triggered outside EventBus.
        var payload = sm._pendingPopupPayload
        if (!payload || typeof payload !== "object") {
            payload = AppState.popupPayload || {}
        }
        // ✅ prevent stale payload reuse
        sm._pendingPopupPayload = ({})


        // 5) Create popup with construction props (fixes required properties)
        const obj = comp.createObject(popupLayer, payload)
        if (!obj) {
            console.log("[StateManager] Failed to create popup:", name)
            popupLayer.visible = false
            return
        }

        popupLayer.popupItem = obj
        popupLayer.visible = true
    }

    Connections {
        target: AppState

        function _schedule() {
            if (sm._popupRenderScheduled) return
            sm._popupRenderScheduled = true
            Qt.callLater(function() {
                sm._popupRenderScheduled = false
                sm._renderPopup()
            })
        }

        function onActivePopupChanged() { _schedule() }
        function onPopupPayloadChanged() { _schedule() }

        // Route-driven navigation: AppState is source of truth, StateManager is the renderer.
        // Satisfies PDF Phase 2 — "Decouple View Logic".
        function onCurrentRouteChanged() {
            var payload = sm._pendingRoutePayload
            if (!payload || typeof payload !== "object") {
                payload = AppState.routePayload || {}
            }
            sm._pendingRoutePayload = ({})   // consume — prevent stale reuse
            sm._executeRoute(AppState.currentRoute, payload)
        }
    }
    

    Component {
        id: selectLanguageView
        SelectLanguageView {
            onSelectLanguage: language => {
                AppState.language = language
                EventBus.navigate("enter_credentials", {})
            }
        }
    }

    Component {
        id: enterCredentialsView
        EnterCredentialsView {
            Resource {
                name: "button-back"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 20*Global.viewWidthScale
                anchors.topMargin: 20*Global.viewHeightScale
                MouseArea { anchors.fill: parent; onPressed: EventBus.navigate("back", {}) }
            }

            onEnterWithQrCode: EventBus.navigate("recycle_qr", {})
            onEnterWithPhoneNumber: phoneNumber => EventBus.navigate("recycle_phone", {"phoneNumber": phoneNumber})
            onInvalidPhoneNumber: EventBus.showPopup("invalid_phone", {})
        }
    }

    Component {
        id: maintenanceView
        MaintenanceView {
            Resource {
                name: "button-back"
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.leftMargin: 20*Global.viewWidthScale
                anchors.topMargin: 20*Global.viewHeightScale
                MouseArea { anchors.fill: parent; onPressed: EventBus.navigate("back", {}) }
            }
        }
    }

    Component {
        id: recycleView
        RecycleView {
            onNewUserFailed: {
                if (!SystemInfo.dev)
                    EventBus.showPopup("out_of_service", {})
            }

            onHandsInserted: EventBus.showPopup("hands", {})
            onOtherInserted: EventBus.showPopup("non_recyclable", {})
            onFinishedWithNoPoints: EventBus.showPopup("timeout", {})
            onFinishedWithQrCode: EventBus.showPopup("finished_qr", {"points": AppState.recyclePoints})
            onFinishedWithPhoneNumber: EventBus.showPopup("finished_phone", {"points": AppState.recyclePoints, "isPending": false})
            onFinishedWithPhoneNumberOffline: EventBus.showPopup("finished_phone", {"points": AppState.recyclePoints, "isPending": true})

            onShowCamera: sm.bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
            onShowCapture: imagePath => {
                sm.captureImage.source = imagePath
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.CaptureImage
            }

            Component.onCompleted: {
                sm.captureSession.camera.start()
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
            }

            Component.onDestruction: {
                sm.captureSession.camera.stop()
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.Slides
            }
        }
    }

    Component {
        id: popupHandsView
        PopupHandsView { interval: 2000; onFinished: AppState.clearPopup() }
    }

    Component {
        id: popupHandsAndCloseView
        PopupHandsView {
            interval: 5000
            onFinished: {
                AppState.handInGate = false
                Global.serial.closeDoor()
                AppState.clearPopup()
                if (AppState.shouldSignOut) sm.goToStart()
            }
        }
    }

    Component {
        id: popupNonRecyclableView
        PopupNonRecyclableView { interval: 2000; onFinished: AppState.clearPopup() }
    }

    Component {
        id: popupFinishedQrCodeRecycleView
        PopupFinishedQrCodeRecycleView {
            onFinished: {
                AppState.clearPopup()
                sm.goToStartOrDefer()
            }
        }
    }

    Component {
        id: popupFinishedPhoneNumberRecycleView
        PopupFinishedPhoneNumberRecycleView { 
            onFinished: {
                AppState.clearPopup()
                sm.goToStartOrDefer() 
            }
        }
    }

    Component {
        id: popupTimeoutView
        PopupTimeoutView { 
            onFinished: {
                AppState.clearPopup()
                sm.goToStartOrDefer() 
            }
        }
    }

    Component {
        id: popupOutOfServiceView
        PopupOutOfServiceView { 
            onFinished: {
                AppState.clearPopup()
                sm.goToStartOrDefer() 
            }
        }
    }

    Component {
        id: invalidPhoneNumberView
        PopupInvalidPhoneNumberView { onFinished: AppState.clearPopup() }
    }

}