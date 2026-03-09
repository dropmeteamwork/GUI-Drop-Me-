import QtQuick

import DropMe

Image {
    required property string name

    source: SystemInfo.getImagePath(name)
    asynchronous: false
    cache: true
    width: sourceSize.width*Global.viewWidthScale
    height: sourceSize.height*Global.viewHeightScale
}

