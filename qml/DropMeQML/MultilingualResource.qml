import QtQuick

Image {
    required property string name
    source: Global.getMultilingualImage(name)
    width: sourceSize.width*Global.viewWidthScale
    height: sourceSize.height*Global.viewHeightScale
}
