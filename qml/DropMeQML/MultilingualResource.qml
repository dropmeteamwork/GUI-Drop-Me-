import QtQuick

Image {
    required property string name
    source: Global.getMultilingualImage(name)
    asynchronous: false
    cache: true
    width: sourceSize.width*Global.viewWidthScale
    height: sourceSize.height*Global.viewHeightScale
}

