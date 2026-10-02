import sys
from PyQt5.QtWidgets import QApplication, QGraphicsView, QGraphicsScene
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt5.QtCore import QUrl, QSizeF

class VideoWindow(QGraphicsView):
    def __init__(self, path):
        super().__init__()
        self.setWindowTitle("Video Test with QGraphicsVideoItem")
        self.setGeometry(100, 100, 800, 600)

        # Scene + video item
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.videoItem = QGraphicsVideoItem()
        self.videoItem.setSize(QSizeF(self.scene.sceneRect().size()))
        self.scene.addItem(self.videoItem)

        # Media player
        self.player = QMediaPlayer(None, QMediaPlayer.VideoSurface)
        self.player.setVideoOutput(self.videoItem)

        url = QUrl.fromLocalFile(path)
        self.player.setMedia(QMediaContent(url))
        self.player.play()

    def resizeEvent(self, event):
        self.videoItem.setSize(QSizeF(self.size()))
        super().resizeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VideoWindow("/home/danny/Dropbox/Apps/Home_Lan_Status/motion_images/2025-08-01/20250801T015438-frontdoor.mp4")  # replace with a real file
    win.showFullScreen()  # fullscreen playback
    sys.exit(app.exec_())
