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
        if (logText.length > 10000)
            logText = logText.substring(0, 10000)
    }

    Rectangle {
        anchors.fill: parent
        color: "#15202b"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8

        RowLayout {
            Layout.fillWidth: true

            Button {
                text: "< Back"
                onClicked: root.back()
            }

            Label {
                Layout.fillWidth: true
                text: "Protocol Test"
                color: "white"
                font.pixelSize: 20
                font.bold: true
            }
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: "#d6e3f0"
            text: "This panel sends the same commands used in operating mode. For parity testing, inject hardware events from the MCU simulator terminal. Local sensor overrides stay disabled unless DROPME_DEV_LOCAL_SENSOR_OVERRIDE=1."
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true

            TextArea {
                readOnly: true
                text: logText
                font.family: "Consolas"
                font.pixelSize: 12
                color: "#e8f0f7"
                wrapMode: TextArea.NoWrap
                background: Rectangle {
                    color: "#0b1118"
                    radius: 6
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 4
            rowSpacing: 6
            columnSpacing: 6

            Label { text: "System"; color: "#7fd1b9"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "PING"; onClicked: Global.serial.pingSystem() }
            Button { text: "GET STATUS"; onClicked: Global.serial.getMcuStatus() }
            Button { text: "RESET"; onClicked: Global.serial.resetSystem() }
            Button { text: "REQ STATUS"; onClicked: Global.serial.requestSequenceStatus() }

            Label { text: "Read"; color: "#7fd1b9"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "POLL WEIGHT"; onClicked: Global.serial.pollWeight() }
            Button { text: "GATE CLOSED"; onClicked: Global.serial.readSensorByName("gate_closed") }
            Button { text: "GATE OPENED"; onClicked: Global.serial.readSensorByName("gate_opened") }
            Button { text: "EXIT GATE"; onClicked: Global.serial.readSensorByName("exit_gate") }
            Button { text: "GATE ALARM"; onClicked: Global.serial.readSensorByName("gate_alarm") }
            Button { text: "DROP SENSOR"; onClicked: Global.serial.readSensorByName("drop_sensor") }
            Button { text: "BASKET 1"; onClicked: Global.serial.readSensorByName("basket_1") }
            Button { text: "BASKET 2"; onClicked: Global.serial.readSensorByName("basket_2") }
            Button { text: "BASKET 3"; onClicked: Global.serial.readSensorByName("basket_3") }

            Label { text: "Indicators"; color: "#7fd1b9"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "LIGHT RED"; onClicked: Global.serial.setRingLightRed() }
            Button { text: "LIGHT GREEN"; onClicked: Global.serial.setRingLightGreen() }
            Button { text: "LIGHT BLUE"; onClicked: Global.serial.setRingLightBlue() }
            Button { text: "LIGHT YELLOW"; onClicked: Global.serial.setRingLightYellow() }
            Button { text: "BEEP 1"; onClicked: Global.serial.buzzerSingle() }
            Button { text: "BEEP 2"; onClicked: Global.serial.buzzerDouble() }
            Button { text: "BEEP LONG"; onClicked: Global.serial.buzzerLong() }

            Label { text: "Session"; color: "#7fd1b9"; font.bold: true; Layout.columnSpan: 4 }
            Button { text: "START FLOW"; onClicked: Global.serial.startOperation() }
            Button { text: "OPEN / START"; onClicked: Global.serial.openGate() }
            Button { text: "ACCEPT PLASTIC"; onClicked: Global.serial.sendPlastic() }
            Button { text: "ACCEPT AL"; onClicked: Global.serial.sendCan() }
            Button { text: "REJECT"; onClicked: Global.serial.sendOther() }
            Button { text: "END"; onClicked: Global.serial.endOperation() }
            Button { text: "CLOSE / END"; onClicked: Global.serial.closeDoor() }
        }
    }

    Connections {
        target: Global.serial

        function onCommandSent(cmdName, payload) {
            var payloadLabel = payload === 0 ? "0x00" : "0x" + payload.toString(16)
            root.log("TX " + cmdName + " " + payloadLabel)
        }

        function onConnectionEstablished(portName) { root.log("STATE connected " + portName) }
        function onConnectionLost() { root.log("STATE disconnected") }
        function onSystemReady() { root.log("RX STATUS_OK") }
        function onGateOpened() { root.log("RX gate opened") }
        function onGateClosed() { root.log("RX gate closed") }
        function onGateBlocked() { root.log("RX gate alarm / blocked") }
        function onConveyorDone() { root.log("RX ITEM_DROPPED") }
        function onPlasticAccepted() { root.log("FLOW plastic accepted") }
        function onCanAccepted() { root.log("FLOW aluminum accepted") }
        function onItemRejected() { root.log("FLOW rejected") }
        function onWeightReceived(grams) { root.log("RX weight " + grams + " g") }
        function onBinFull(binName) { root.log("RX bin full " + binName) }
        function onDoorStatusReceived(status) { root.log("RX MCU status 0x" + status.toString(16)) }
        function onErrorOccurred(name, id) { root.log("RX error " + name + " " + id) }
    }

    Component.onCompleted: {
        root.log("Protocol test ready. Use the MCU simulator for STATUS_OK, ITEM_DROPPED, BASKET_STATUS, CRC errors, and sensor edge cases.")
    }
}
