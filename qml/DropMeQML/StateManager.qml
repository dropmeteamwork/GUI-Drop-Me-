import QML
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import DropMe

import "."

Item {
    id: sm
    anchors.fill: parent

    required property Image captureImage
    required property Item bottomView
    required property CaptureSession captureSession
    required property var cameraCapture

    property bool transitionedFromStart: false
    property var _pendingPopupPayload: ({})
    property var _pendingRoutePayload: ({})

    property var routeComponents: ({})
    property var popupComponents: ({})
    property string _lastAppliedRoute: ""    UiCoordinator {
        id: uiCoordinator
        appState: AppState
        serial: Global.serial
    }

    function _initComponentMaps() {
        routeComponents = {
            "start": startView,
            "select_language": selectLanguageView,
            "maintenance": maintenanceView,
            "enter_credentials": enterCredentialsView,
            "recycle_qr": recycleView,
            "recycle_phone": recycleView
        }

        popupComponents = {
            "hands": popupHandsView,
            "hands_and_close": popupHandsAndCloseView,
            "non_recyclable": popupNonRecyclableView,
            "timeout": popupTimeoutView,
            "invalid_phone": invalidPhoneNumberView,
            "finished_qr": popupFinishedQrCodeRecycleView,
            "finished_phone": popupFinishedPhoneNumberRecycleView,
            "out_of_service": popupOutOfServiceView
        }
    }

    function goToStart() {
        view.clear()
        view.push(startView)
        transitionedFromStart = false
    }

    function _normalizeImageSource(path) {
        var p = String(path || "")
        if (p === "")
            return ""
        if (p.startsWith("file:///") || p.startsWith("qrc:/") || p.startsWith("image://") || p.startsWith("data:"))
            return p
        if (/^[A-Za-z]:[\\/]/.test(p))
            return "file:///" + p.replace(/\\/g, "/")
        return p
    }

    function _routeProps(target, payload) {
        var p = payload || {}
        var out = {}

        if (target === "recycle_qr") {
            out.userType = Global.UserType.QrCode
            out.captureSource = sm.cameraCapture
        } else if (target === "recycle_phone") {
            out.userType = Global.UserType.PhoneNumber
            out.phoneNumber = p.phoneNumber || ""
            out.captureSource = sm.cameraCapture
        }

        return out
    }

    function _executeRoute(route, payload) {
        var action = uiCoordinator.routeAction(route, payload)
        if (!action || action.op === "none") {
            console.log("[StateManager] Unknown route:", route)
            return
        }

        if (action.background !== undefined && action.background !== null && action.background !== "")
            view.background.name = action.background

        var target = action.target || ""
        var comp = routeComponents[target]
        if (!comp) {
            console.log("[StateManager] Missing route component for:", target)
            return
        }

        var props = _routeProps(target, action.props || {})

        if (action.op === "reset") {
            view.clear()
            view.push(comp, props)
            transitionedFromStart = false
            return
        }

        if (action.op === "push") {
            view.push(comp, props)
            return
        }

        console.log("[StateManager] Unknown route action:", action.op)
    }

    StackView {
        id: view
        anchors.fill: parent
        initialItem: startView
        background: Resource { name: "background" }
        onEmptyChanged: background.name = "background"
        enabled: AppState.activePopup === ""

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
            sm._pendingRoutePayload = payload || {}
            uiCoordinator.handleNavigate(route, payload)
        }

        function onShowPopup(popupName, payload) {
            sm._pendingPopupPayload = payload || {}
            uiCoordinator.handleShowPopup(popupName, payload)
        }

        function onResetToStart() { uiCoordinator.handleResetToStart() }
        function onHwHandInGate() { uiCoordinator.handleHwHandInGate() }
        function onHwGateCleared() { uiCoordinator.handleHwGateCleared() }
        function onHwBinFull(binName) { uiCoordinator.handleHwBinFull(binName) }
        function onHwBasketState(binName, isFull) { uiCoordinator.handleHwBasketState(binName, isFull) }
        function onHwError(errorName, errorId) { uiCoordinator.handleHwError(errorName, errorId) }
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
        name: view.background.name
    }

    Item {
        id: popupLayer
        anchors.fill: parent
        z: 9999
        visible: AppState.activePopup !== ""
        property var popupItem: null
    }

    property bool _popupRenderScheduled: false
    function _renderPopup() {
        const activeName = AppState.activePopup
        const key = uiCoordinator.popupKey(activeName)

        if (popupLayer.popupItem) {
            popupLayer.popupItem.destroy()
            popupLayer.popupItem = null
        }

        if (!key) {
            popupLayer.visible = false
            return
        }

        const comp = popupComponents[key]
        if (!comp) {
            console.log("[StateManager] Missing popup component for:", key)
            popupLayer.visible = false
            return
        }

        var payload = sm._pendingPopupPayload
        if (!payload || typeof payload !== "object")
            payload = AppState.popupPayload || {}
        sm._pendingPopupPayload = ({})

        const obj = comp.createObject(popupLayer, payload)
        if (!obj) {
            console.log("[StateManager] Failed to create popup:", key)
            popupLayer.visible = false
            return
        }

        popupLayer.popupItem = obj
        popupLayer.visible = true
    }

    Connections {
        target: uiCoordinator
        function onBackRequested() { view.pop() }
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

        function onCurrentRouteChanged() {
            console.log("[StateManager] routeChanged ->", AppState.currentRoute)
            var payload = sm._pendingRoutePayload
            if (!payload || typeof payload !== "object")
                payload = AppState.routePayload || {}
            sm._pendingRoutePayload = ({})

            var route = AppState.currentRoute
            var isRecycle = (route === "recycle_qr" || route === "recycle_phone")
            if (isRecycle && route === sm._lastAppliedRoute) {
                console.log("[StateManager] duplicate recycle route ignored:", route)
                return
            }

            sm._executeRoute(route, payload)
            sm._lastAppliedRoute = route
            if (isRecycle) {
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
                console.log("[StateManager] bottom -> Camera by route", route)
            } else {
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.Slides
                console.log("[StateManager] bottom -> Slides by route", route)
            }
        }
    }

    Component {
        id: selectLanguageView
        SelectLanguageView {
            onSelectLanguage: language => {
                AppState.language = language
                EventBus.navigate("enter_credentials", {"language": language})
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
            onNewUserFailed: uiCoordinator.handleNewUserFailed(SystemInfo.dev)

            onHandsInserted: EventBus.showPopup("hands", {})
            onOtherInserted: EventBus.showPopup("non_recyclable", {})
            onFinishedWithNoPoints: EventBus.showPopup("timeout", {})
            onFinishedWithQrCode: EventBus.showPopup("finished_qr", {"points": AppState.recyclePoints})
            onFinishedWithPhoneNumber: EventBus.showPopup("finished_phone", {"points": AppState.recyclePoints, "isPending": false})
            onFinishedWithPhoneNumberOffline: EventBus.showPopup("finished_phone", {"points": AppState.recyclePoints, "isPending": true})

            onShowCamera: {
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.CameraVideoOutput
                console.log("[StateManager] bottom -> Camera by RecycleView.showCamera")
            }
            onShowCapture: imagePath => {
                sm.captureImage.source = sm._normalizeImageSource(imagePath)
                sm.bottomView.currentIndex = MainWindow.BottomViewItem.CaptureImage
                console.log("[StateManager] bottom -> Capture by RecycleView.showCapture")
            }
            Component.onCompleted: {
                console.log("[StateManager] RecycleView component completed")
                sm.captureSession.camera.start()
            }

            Component.onDestruction: {
                console.log("[StateManager] RecycleView component destroyed")
                sm.captureSession.camera.stop()
            }
        }
    }

    Component {
        id: popupHandsView
        PopupHandsView {
            interval: 2000
            autoClose: true
            onFinished: {
                if (!AppState.handInGate)
                    AppState.clearPopup()
            }
        }
    }

    Component {
        id: popupHandsAndCloseView
        PopupHandsView {
            autoClose: false
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
                uiCoordinator.requestReturnToStart()
            }
        }
    }

    Component {
        id: popupFinishedPhoneNumberRecycleView
        PopupFinishedPhoneNumberRecycleView {
            onFinished: {
                AppState.clearPopup()
                uiCoordinator.requestReturnToStart()
            }
        }
    }

    Component {
        id: popupTimeoutView
        PopupTimeoutView {
            onFinished: {
                AppState.clearPopup()
                uiCoordinator.requestReturnToStart()
            }
        }
    }

    Component {
        id: popupOutOfServiceView
        PopupOutOfServiceView {
            onFinished: {
                AppState.clearPopup()
                uiCoordinator.requestReturnToStart()
            }
        }
    }

    Component {
        id: invalidPhoneNumberView
        PopupInvalidPhoneNumberView { onFinished: AppState.clearPopup() }
    }

    Component.onCompleted: {
        _initComponentMaps()
    }
}










