import sys
import random

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QStackedLayout,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkRequest,
    QNetworkReply,
)

from PyQt6.QtCore import QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView


class BarGraphWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.value = 0.0
        self.setMinimumWidth(200)
        self.setMinimumHeight(150)

    def set_value(self, value: float):
        self.value = max(0.0, min(5.0, value))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.fillRect(self.rect(), Qt.GlobalColor.white)

        margin = 20

        bar_width = self.width() - (2 * margin)
        bar_height = self.height() - (2 * margin)

        x = margin
        y = margin

        # Outer border
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawRect(x, y, bar_width, bar_height)

        fill_height = int((self.value / 5.0) * bar_height)

        colours = [
            QColor(0, 180, 0),      # green
            QColor(180, 220, 0),    # yellow-green
            QColor(255, 220, 0),    # yellow
            QColor(255, 140, 0),    # orange
            QColor(220, 0, 0)       # red
        ]

        segment_height = bar_height / 5

        for i, colour in enumerate(colours):

            seg_y = y + bar_height - int((i + 1) * segment_height)
            seg_h = int(segment_height)

            visible_height = min(
                max(fill_height - (i * seg_h), 0),
                seg_h
            )

            if visible_height > 0:
                painter.fillRect(
                    x,
                    seg_y + seg_h - visible_height,
                    bar_width,
                    visible_height,
                    colour
                )

        # painter.drawText(
        #     self.rect(),
        #     Qt.AlignmentFlag.AlignCenter,
        #     f"{self.value:.2f}"
        # )


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.audio_enabled = True
        self.video_enabled = True
        self.camera_up = False

        # self.setWindowTitle("Baby Monitor")
        # No title bar, border, minimize/maximize buttons
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )

        # Always stay on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.video_url = self.load_url_from_file()
        
        # --------------------
        # Left side
        # --------------------

        self.bar_graph = BarGraphWidget()

        self.audio_button = QPushButton()
        self.video_button = QPushButton()

        self.update_audio_button()
        self.update_video_button()

        self.audio_button.clicked.connect(self.toggle_audio)
        self.video_button.clicked.connect(self.toggle_video)

        self.audio_button.setMinimumHeight(80)
        self.video_button.setMinimumHeight(80)

        self.audio_button.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )

        self.video_button.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )

        left_layout = QVBoxLayout()
        # left_layout.addWidget(QLabel("Status"))
        left_layout.addWidget(self.bar_graph, stretch=1)
        left_layout.addWidget(self.audio_button)
        left_layout.addWidget(self.video_button)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # --------------------
        # Right side Web View
        # --------------------
        self.web_view = QWebEngineView()
        self.web_view.setFixedSize(832, 600)
        self.web_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.NoContextMenu
        )
        self.web_view.page().runJavaScript("""
        document.body.style.overflow = 'hidden';
        """)
        self.web_view.loadStarted.connect(self.on_load_started)
        self.web_view.loadFinished.connect(self.on_load_finished)

        # self.web_view.page().renderProcessTerminated.connect(
        #     lambda *args: print("render terminated")
        # )

        self.video_loading_label = QLabel("Loading Video feed\n\nPlease wait..")
        self.video_loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_loading_label.setStyleSheet("""
        QLabel {
        font-size: 24px;
        font-weight: bold;
        color: white;
        background-color: black;
        }
        """)

        self.video_error_label = QLabel("Video feed currently not available.\n\nRetrying...")
        self.video_error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_error_label.setStyleSheet("""
        QLabel {
        font-size: 24px;
        font-weight: bold;
        color: white;
        background-color: black;
        }
        """)
        self.video_stack = QStackedLayout()
        self.video_stack.addWidget(self.web_view)
        self.video_stack.addWidget(self.video_error_label)
        self.video_stack.addWidget(self.video_loading_label)
        self.video_container = QWidget()
        self.video_container.setLayout(self.video_stack)
        self.video_stack.setCurrentWidget(self.video_loading_label)

        # --------------------
        # Main Layout
        # --------------------

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(left_layout)
        layout.addWidget(self.video_container)

        # self.web_view.load(QUrl(self.video_url))
        # self.web_view.setUrl(QUrl(self.video_url))

        # --------------------
        # Update timer (100 ms)
        # --------------------

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_bar_graph)
        self.timer.start(100)

        self.network_manager = QNetworkAccessManager()
        
        self.camera_watchdog = QTimer(self)
        self.camera_watchdog.timeout.connect(
            self.check_camera
        )
        self.camera_watchdog.start(2000)

    def on_load_started(self):
        print("Video stream started")

        self.video_stack.setCurrentWidget(
            self.web_view
        )
        self.camera_up = True

    def on_load_finished(self):
        print("Video stream stopped")

        self.video_stack.setCurrentWidget(
            self.video_loading_label
        )
        self.camera_up = False


    def check_camera(self):

        request = QNetworkRequest(
            QUrl(self.video_url)
        )

        self.reply = self.network_manager.head(request)

        self.reply.finished.connect(
            self.on_camera_check_finished
        )        

    def camera_available(self, error):

        down_errors = {
            QNetworkReply.NetworkError.ConnectionRefusedError,
            QNetworkReply.NetworkError.HostNotFoundError,
            QNetworkReply.NetworkError.TimeoutError,
        }

        return error not in down_errors
    
    def on_camera_check_finished(self):
        # print(f"Camera check finished, error={self.reply.error()} camera_up={self.camera_up}")
        if self.camera_available(self.reply.error()):
            if self.camera_up == False:
                print("Camera is back up, reloading video feed")
                self.web_view.setUrl(QUrl(self.video_url))
                self.camera_up = True
            self.video_stack.setCurrentWidget(self.web_view)
    
        else:
            # print("Camera not available, showing error label")
            self.video_stack.setCurrentWidget(
                self.video_error_label
            )
            self.camera_up = False


    # ==================================================
    # Bar Graph Update
    # ==================================================


    def update_bar_graph(self):
        """
        Replace this with your real float source.
        Expected range: 0.0 -> 5.0
        """
        value = random.uniform(0.0, 5.0)
        self.bar_graph.set_value(value)

    # ==================================================
    # Audio
    # ==================================================

    def update_audio_button(self):
        state = "ON" if self.audio_enabled else "OFF"
        self.audio_button.setText(f"Audio {state}")

    def toggle_audio(self):
        self.audio_enabled = not self.audio_enabled
        self.update_audio_button()

        self.on_audio_changed(self.audio_enabled)

    def on_audio_changed(self, enabled: bool):
        """
        Extend this function with whatever action
        you want to happen when Audio changes.
        """
        print(f"Audio enabled = {enabled}")

    # ==================================================
    # Video
    # ==================================================

    def update_video_button(self):
        state = "ON" if self.video_enabled else "OFF"
        self.video_button.setText(f"Video {state}")

    def toggle_video(self):
        self.video_enabled = not self.video_enabled
        self.update_video_button()

        self.on_video_changed(self.video_enabled)

    def on_video_changed(self, enabled: bool):
        """
        Extend this function with whatever action
        you want to happen when Video changes.
        """
        print(f"Video enabled = {enabled}")


    def load_url_from_file(self) -> str:
        """
        Reads the first line from url.txt and returns it.
        """

        try:
            with open("url.txt", "r", encoding="utf-8") as f:
                url = f.readline().strip()

            print(f"Loaded URL: {url}")
            return url

        except FileNotFoundError:
            print("url.txt not found")
            return ""

        except Exception as e:
            print(f"Failed to load URL: {e}")
            return ""

def main():
    app = QApplication(sys.argv)

    window = MainWindow()
    window.setGeometry(0, 0, 1024, 600)
    window.showFullScreen() 
    # window.resize(950, 540)
    # window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
