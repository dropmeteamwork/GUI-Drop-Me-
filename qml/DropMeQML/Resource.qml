import QtQuick

import DropMe

Image {
    required property string name

    source: SystemInfo.getImagePath(name)
    width: sourceSize.width*Global.viewWidthScale
    height: sourceSize.height*Global.viewHeightScale
}
