import QML
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import DropMe

Item {
    id: root
    signal back()

    property string logText: ""
    function log(line) {
        var ts = new Date().toLocaleTimeString("en-US", { hour12: false })
        logText = "[" + ts + "] " + line + "\n" + logText
        if (logText.length > 8000) logText = logText.substring(0, 8000)
    }

    Rectangle {
        anchors.fill: parent
        color: "#1a1a2e"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true
            Button {
                text: "← Back"
                onClicked: root.back()
            }
            Text {
                text: "Protocol Test (all commands)"
                font.pixelSize: 20
                color: "white"
                Layout.fillWidth: true
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            clip: true
            ScrollBar.vertical.policy: ScrollBar.AlwaysOn
            TextArea {
                readOnly: true
                text: logText
                font.family: "Consolas"
                font.pixelSize: 12
                color: "#e0e0e0"
                wrapMode: TextArea.NoWrap
                background: Rectangle { color: "#0d0d1a" }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 4
            rowSpacing: 6
            columnSpacing: 6

            // ---- System ----
            Text { text: "System"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "SYS_INIT";     onClicked: Global.serial.initSystem() }
            Button { text: "SYS_RESET";    onClicked: Global.serial.resetSystem() }
            Button { text: "SYS_PING";    onClicked: Global.serial.pingSystem() }
            Button { text: "SYS_STOP_ALL"; onClicked: Global.serial.stopAll() }

            Text { text: "Operation"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "OP_NEW";    onClicked: Global.serial.startOperation() }
            Button { text: "OP_CANCEL"; onClicked: Global.serial.cancelOperation() }
            Button { text: "OP_END";    onClicked: Global.serial.endOperation() }

            Text { text: "Gate"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "GATE_OPEN";  onClicked: Global.serial.openGate() }
            Button { text: "GATE_CLOSE"; onClicked: Global.serial.closeGate() }

            Text { text: "Conveyor"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button {
                text: "CONVEYOR_RUN(10)"
                onClicked: Global.serial.runConveyor(10)
            }
            Button { text: "CONVEYOR_STOP"; onClicked: Global.serial.stopConveyor() }

            Text { text: "Reject"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "REJECT_ACTIVATE"; onClicked: Global.serial.activateReject() }
            Button { text: "REJECT_HOME";   onClicked: Global.serial.homeReject() }

            Text { text: "Sort"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "SORT_SET(plastic)"; onClicked: Global.serial.setSort("plastic") }
            Button { text: "SORT_SET(can)";     onClicked: Global.serial.setSort("can") }

            Text { text: "Classification"; color: "#59b280"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "ITEM_ACCEPT(plastic)"; onClicked: Global.serial.acceptItem("plastic") }
            Button { text: "ITEM_ACCEPT(can)";     onClicked: Global.serial.acceptItem("can") }
            Button { text: "ITEM_REJECT";          onClicked: Global.serial.rejectItem() }
        }
    }

    Connections {
        target: Global.serial
        function onCommandSent(cmdName, payload) {
            root.log("TX: " + cmdName + " PL:" + (payload === 0 ? "0" : "0x" + payload.toString(16)))
        }
        function onSystemReady()    { root.log("RX: SYS_READY") }
        function onSystemBusy()     { root.log("RX: SYS_BUSY") }
        function onSystemIdle()     { root.log("RX: SYS_IDLE") }
        function onGateOpened()     { root.log("RX: GATE_OPENED") }
        function onGateClosed()     { root.log("RX: GATE_CLOSED") }
        function onGateBlocked()    { root.log("RX: GATE_BLOCKED") }
        function onConveyorDone()   { root.log("RX: CONVEYOR_DONE") }
        function onSortDone()       { root.log("RX: SORT_DONE") }
        function onRejectDone()     { root.log("RX: REJECT_DONE") }
        function onRejectHomeOk()   { root.log("RX: REJECT_HOME_OK") }
        function onWeightReceived(grams) { root.log("RX: WEIGHT_DATA " + grams + "g") }
        function onBinFull(binName) { root.log("RX: BIN_FULL " + binName) }
        function onErrorOccurred(name, id) { root.log("RX: ERROR " + name + " ID:" + id) }
    }

    Component.onCompleted: log("Protocol Test ready. Use simulator keys: h w p c r i for MCU→PC events.")
}
