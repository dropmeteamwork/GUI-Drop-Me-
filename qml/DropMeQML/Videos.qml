import QML
import QtQuick
import QtMultimedia
import Qt.labs.folderlistmodel

Item {
    id: videos
    required property url folder
    required property VideoOutput videoOutput
    readonly property alias playing: mediaPlayer.playing
    property bool suspend: false

    Connections {
        target: Global.server
        function onSuspendVideos() {
            videos.suspend = true
            mediaPlayer.stop()
            mediaPlayer.queuePosition = 0
        }
        function onContinueVideos() {
            videos.updateQueue()    
            videos.suspend = false
            mediaPlayer.play()
        }
    }

    function updateQueue() {
        mediaPlayer.queuePosition = 0
        mediaPlayer.queue = []
        for (var i = 0; i < folderModel.count; i++) {
            mediaPlayer.queue.push(folderModel.get(i, "fileUrl"))
        }
    }

    MediaPlayer {
        id: mediaPlayer
        property list<url> queue
        property int queuePosition: 0
        source: queue[queuePosition] || ""
        videoOutput: videos.videoOutput
        autoPlay: true
        onPlayingChanged: {
            if (mediaPlayer.playing || videos.suspend) return
            mediaPlayer.queuePosition = (mediaPlayer.queuePosition + 1) % mediaPlayer.queue.length
            mediaPlayer.play()
        }
    }

    FolderListModel {
        id: folderModel
        folder: videos.folder
        showDirs: false
        showOnlyReadable: true
        onStatusChanged: if (folderModel.status == FolderListModel.Ready) {
            videos.updateQueue()
        }
    }
}
