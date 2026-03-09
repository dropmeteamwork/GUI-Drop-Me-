import QML
import QtQuick
import Qt.labs.folderlistmodel

Item {
    id: slides
    required property url folder
    property int interval: 5000
    clip: true

    property list<url> queue: []
    property int activeImageIndex: 0
    property int currentQueuePosition: 0
    property int nextQueuePosition: 0
    property bool pendingSwap: false

    function _activeImage() {
        return activeImageIndex === 0 ? slideA : slideB
    }

    function _inactiveImage() {
        return activeImageIndex === 0 ? slideB : slideA
    }

    function _resetQueue(items) {
        queue = items
        pendingSwap = false
        currentQueuePosition = 0
        nextQueuePosition = 0
        activeImageIndex = 0

        slideA.source = queue.length > 0 ? queue[0] : ""
        slideB.source = ""
    }

    function _preloadNext() {
        if (queue.length <= 1)
            return

        nextQueuePosition = (currentQueuePosition + 1) % queue.length
        pendingSwap = true
        _inactiveImage().source = queue[nextQueuePosition]
    }

    function _tryCommitSwap() {
        if (!pendingSwap)
            return

        var nextImg = _inactiveImage()
        if (nextImg.status !== Image.Ready)
            return

        activeImageIndex = activeImageIndex === 0 ? 1 : 0
        currentQueuePosition = nextQueuePosition
        pendingSwap = false
    }

    Image {
        id: slideA
        visible: slides.activeImageIndex === 0
        asynchronous: true
        cache: true
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        onStatusChanged: slides._tryCommitSwap()
    }

    Image {
        id: slideB
        visible: slides.activeImageIndex === 1
        asynchronous: true
        cache: true
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        horizontalAlignment: Image.AlignHCenter
        verticalAlignment: Image.AlignVCenter
        onStatusChanged: slides._tryCommitSwap()
    }

    Timer {
        interval: slides.interval
        running: true
        repeat: true
        onTriggered: slides._preloadNext()
    }

    FolderListModel {
        id: folderModel
        folder: slides.folder
        showDirs: false
        showOnlyReadable: true
        nameFilters: ["*.png", "*.jpg", "*.jpeg", "*.PNG", "*.JPG", "*.JPEG"]
        onStatusChanged: if (folderModel.status === FolderListModel.Ready) {
            var files = []
            for (var i = 0; i < folderModel.count; i++)
                files.push(folderModel.get(i, "fileUrl"))
            slides._resetQueue(files)
        }
    }
}
