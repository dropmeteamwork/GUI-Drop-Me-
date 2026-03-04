pragma Singleton

import QML
import QtQuick
import QtQuick.Window

import DropMe

Item {
    property MainWindow window: null
    property real screenWidth: window == null ? 1080 : Math.min(window.width, 9*window.height/16)
    property real screenHeight: window == null ? 1920 : Math.min(16*window.width/9, window.height)
    property real viewWidth: screenWidth
    property real viewHeight: 2*screenHeight/5
    property real viewRefWidth: 1080.0
    property real viewRefHeight: 768.0
    property real viewWidthScale: viewWidth/viewRefWidth
    property real viewHeightScale: viewHeight/viewRefHeight

    property FontLoader fontMedium: tajawalMediumFontLoader
    property FontLoader fontBold: tajawalBoldFontLoader

    property Server server: globalServer
    property AutoSerial serial: globalSerial


    enum Language {
        Arabic,
        English
    }

    enum UserType {
        PhoneNumber,
        QrCode
    }

    Server {
        id: globalServer
    }

    // Serial {
    //     id: globalSerial
    // }

    AutoSerial {
        id: globalSerial
    }

    FontLoader {
        id: tajawalMediumFontLoader
        source: SystemInfo.getFontPath("Tajawal-Medium.ttf")
    }

    FontLoader {
        id: tajawalBoldFontLoader
        source: SystemInfo.getFontPath("Tajawal-Bold.ttf")
    }

    function getMultilingualImage(resource) {
        return SystemInfo.getImagePath(AppState.languageCode + "-" + resource)
    }

    function convertToArabicNumerals(inputString) {
        var arabicNumerals = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];
        var result = "";

        for (var i = 0; i < inputString.length; i++) {
            var digit = inputString.charAt(i);
            if (digit >= '0' && digit <= '9') {
                result += arabicNumerals[digit.charCodeAt(0) - '0'.charCodeAt(0)];
            } else {
                result += digit;
            }
        }

        return result;
    }

    function convertToLanguageNumerals(inputString) {
        return ifArabic(convertToArabicNumerals(inputString), inputString)
    }

    function ifArabic(ifExpr, elseExpr) {
        // language state is now owned by AppState (Python singleton)
        return AppState.languageCode === "ar" ? ifExpr : elseExpr
    }
}
