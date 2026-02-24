import QML
import QtQuick
import Qt.labs.folderlistmodel

Item {
    id: slides
    required property url folder
    property int interval: 5000

    Image {
        id: slide
        property list<url> queue
        property int queuePosition: 0
        source: queue[queuePosition] || ""
        width: sourceSize.width*Global.viewWidthScale
        height: sourceSize.height*Global.viewHeightScale
    }
    
    Timer {
        interval: slides.interval
        running: true
        repeat: true
        onTriggered: slide.queuePosition = (slide.queuePosition + 1) %  slide.queue.length
    }

    FolderListModel {
        id: folderModel
        folder: slides.folder
        showDirs: false
        showOnlyReadable: true
        onStatusChanged: if (folderModel.status == FolderListModel.Ready) {
            for (var i = 0; i < folderModel.count; i++) {
                slide.queue.push(folderModel.get(i, "fileUrl"))
            }
        }
    }
}
