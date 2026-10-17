
import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication, QMainWindow
from PyQt6.QtWebEngineWidgets import QWebEngineView


class CameraWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Camera Viewer")
        self.resize(1000, 700)

        self.web_view = QWebEngineView(self)
        self.setCentralWidget(self.web_view)

        # Connect signals BEFORE calling load()
        self.web_view.loadStarted.connect(self.on_load_started)
        self.web_view.loadFinished.connect(self.on_load_finished)
        self.web_view.urlChanged.connect(self.on_url_changed)

        self.web_view.load(
            QUrl("http://baby-cam:8081/")
        )

    def on_load_started(self):
        print("Web page load started")

    def on_load_finished(self, ok):
        print(f"Web page load finished: {ok}")

    def on_url_changed(self, url):
        print(f"URL changed: {url.toString()}")


app = QApplication(sys.argv)
window = CameraWindow()
window.show()
sys.exit(app.exec())
