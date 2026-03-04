import QML
import QtQuick
import QtQuick.Controls
import QtMultimedia

import DropMe

Item {
    required property int userType
    required property ImageCapture imageCapture
    property string phoneNumber: ""

    signal finishedWithNoPoints
    signal finishedWithQrCode
    signal finishedWithPhoneNumber
    signal finishedWithPhoneNumberOffline
    signal newUserFailed
    signal otherInserted
    signal handsInserted
    signal showCapture(string path)
    signal showCamera

    id: view

    // Add this timer here (at component level, not inside function)
    Timer {
        id: cameraRestoreTimer
        interval: 1500  // Adjust duration as needed
        repeat: false
        onTriggered: view.showCamera()
    }

    function onPrediction(pred, predImage = '') {
        console.log("ON PREDICTION", pred, Date.now())
        if (pred == 'hand') {
            view.handsInserted()
            clock.reset()
            clock.start()
        } else if (pred == 'aluminum') {
            Global.serial.sendCan()
            AppState.incrementRecycleCans()
            if (view.userType == Global.UserType.QrCode) {
                Global.server.sendAluminumCan()
            }
            clock.reset()
            clock.start()

            if (predImage) {
                view.showCapture(predImage)
                // Switch back to camera after showing the image
                cameraRestoreTimer.restart()
            }
        } else if (pred == 'plastic') {
            Global.serial.sendPlastic()
            AppState.incrementRecyclePlastic()
            if (view.userType == Global.UserType.QrCode) {
                Global.server.sendPlasticBottle()
            }
            clock.reset()
            clock.start()
            
            if (predImage) {
                view.showCapture(predImage)
                cameraRestoreTimer.restart()  // Just call restart on the timer
}
        } else if (pred == 'other') {
            Global.serial.sendOther()
            view.otherInserted()
            clock.reset()
            clock.start()
        }
    }



    Connections {
        target: view.imageCapture

        function onImageSaved(requestId, capturePath) {
            //var pred = Global.server.getCapturePrediction(capturePath)
            //view.onPrediction(pred[0], pred[1])
            Global.server.getCapturePrediction(capturePath, view.phoneNumber)
        }
    }

    Connections {
        target: Global.serial

        function onReady() {
            clock.start()
            view.showCamera()            
        }

        function onNewUserFailed() {
            view.newUserFailed()
        }
    }

    Connections {
        target: Global.server

        function onFinishedPhoneNumberRecycle(isPending: bool) {
            isPending ? view.finishedWithPhoneNumberOffline() : view.finishedWithPhoneNumber()
        }
    }


    Timer {
                id: deferralTimer 
                interval: 150
                repeat: false
                running: false


                onTriggered: {
                    running = false;
                    view.onPrediction(deferralTimer.pred, deferralTimer.predImage);
                    
                    // Switch back to camera after a short delay
                    // cameraRestoreTimer.start();
                    
                    if (deferralTimer.cleanupPath) {
                        cleanupDelayTimer.start();
                    }
                }

                property var pred: ""
                property var predImage: ""
                property var cleanupPath: ""
            }

    
	// NEW: Release processing lock after crusher has time to act
	Timer {
	    id: processingReleaseTimer
	    interval: 3000  // 3 seconds for crusher to complete
	    repeat: false
	    onTriggered: view.processingItem = false
	}

    Timer {
                id: cleanupDelayTimer
                interval: 2000  // 2s delay; adjust if needed (long enough for Image load)
                repeat: false
                onTriggered: {
                    if (deferralTimer.cleanupPath) {
                        Global.server.cleanupFile(deferralTimer.cleanupPath);
                        deferralTimer.cleanupPath = "";
                    }
                }
            }
  
    Connections {
            target: Global.server

            // <<< EDITED: Added systemPathToDelete to the function arguments >>>
            function onPredictionReady(results, capturePath, systemPathToDelete) { 
                
                // The structure of 'results' is now [item, qml_uri] from Python server.py:
                var item = results[0];        // e.g., "plastic", "aluminum", "other", "hand"
                var imagePath = results[1];   // The 'file:///' URI

                // 1. Display the image immediately
                // view.showCapture(imagePath); 

                // 2. Set timer variables
                deferralTimer.pred = item; 
                deferralTimer.predImage = imagePath;
                deferralTimer.cleanupPath = systemPathToDelete; // <--- Store path for cleanup
                deferralTimer.running = true;
                // ----------------------------------
            }
        }

    Component.onDestruction: {
        Global.serial.sendSignOut()
        AppState.endRecycleSession()
    }
    Component.onCompleted: {
        AppState.startRecycleSession()
        view.showCamera()
    }

    Timer {
        interval: 2_000
        running: true
        onTriggered: Global.serial.sendNewUser()
    }



    MultilingualResource {
        name: "background-recycle"
        anchors.fill: parent

        component ViewText : Text {
            required property string viewText
            text: viewText
            color: "#243B6A"
            font.family: Global.fontBold.font.family
            font.weight: Global.fontBold.font.weight
            font.styleName: Global.fontBold.font.styleName
            font.pointSize: 48*Global.viewWidthScale
        }

        Column {
            visible: SystemInfo.dev
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            Button {
                text: "start"
                onPressed: {
                    clock.start()
                    view.showCamera()
                }
            }
            Button {
                text: "end"
                onPressed: clock.finish()
            }
            Button {
                text: "hand"
                onPressed: {
                        // Generate a new capture path
                        var p = SystemInfo.getNextCapturePath()
                        // Take a snapshot from the camera
                        view.imageCapture.captureToFile(p)
                        // Update the UI counters and animations
                        view.onPrediction(text)
                        // Send the actual image path to the dev-mode uploader
                        Global.server.sendDevPrediction(text, p)
                    }

            }
            Button {
                text: "aluminum"
                onPressed: {
                        var p = SystemInfo.getNextCapturePath()
                        view.imageCapture.captureToFile(p)
                        view.onPrediction(text)
                        Global.server.sendDevPrediction(text, p)
                    }

            }
            Button {
                text: "plastic"
                onPressed: {
                        var p = SystemInfo.getNextCapturePath()
                        view.imageCapture.captureToFile(p)
                        view.onPrediction(text)
                        Global.server.sendDevPrediction(text, p)
                    }

            }
            Button {
                text: "other"
                onPressed: {
                        var p = SystemInfo.getNextCapturePath()
                        view.imageCapture.captureToFile(p)
                        view.onPrediction(text)
                        Global.server.sendDevPrediction(text, p)
                    }

            }
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recyclePlasticBottles.toString())
            x: Global.ifArabic(370, 363)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recycleCans.toString())
            x: Global.ifArabic(600, 592)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        ViewText {
            viewText: Global.convertToLanguageNumerals(AppState.recyclePoints.toString())
            x: Global.ifArabic(775, 750)*Global.viewWidthScale
            y: 330*Global.viewHeightScale
        }

        MultilingualResourceButton {
            resource: "button-end"
            x: 380*Global.viewWidthScale
            y: 535*Global.viewHeightScale
            onPressed: clock.finish()
        }

        Clock {
            id: clock
            interval: 3_000
            onTriggered: {
                console.log("CLOCK TRIGGER", Date.now())
                var capturePath = SystemInfo.getNextCapturePath()
                view.imageCapture.captureToFile(capturePath)
            }
            onFinished: {
                if (AppState.recycleHasFinished) return
                AppState.markRecycleFinished()

                if (AppState.recyclePoints === 0) {
                    view.finishedWithNoPoints()
                } else if (view.userType === Global.UserType.QrCode) {
                    view.finishedWithQrCode()
                } else if (view.userType === Global.UserType.PhoneNumber) {
                    Global.server.finishRecyclePhoneNumber(view.phoneNumber, AppState.recyclePlasticBottles, AppState.recycleCans)
                }
                if (view.userType === Global.UserType.QrCode) {
                    Global.server.finishRecycleQrCode(view.phoneNumber, AppState.recyclePlasticBottles, AppState.recycleCans)
                }
            }
        }
    }
}