import sys
import random
import subprocess
from urllib.parse import urlparse

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
    QMessageBox,
)
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkRequest,
    QNetworkReply,
)

from PyQt6.QtCore import QTimer
from PyQt6.QtWebEngineWidgets import QWebEngineView

from audio_streamer import AudioStreamer


class BarGraphWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.value = 0.0
        self.audio_status = ""
        self.setMinimumWidth(200)
        self.setMinimumHeight(150)
        
    def set_value(self, value: float):
        self.value = max(0.0, min(100.0, value))
        self.update()

    def set_audio_status(self, status: str):
        self.audio_status = status
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

        fill_height = int((self.value / 100.0) * bar_height)

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

        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            self.audio_status
        )


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
        self.load_urls_from_file()
        if (self.control_url == "") or (self.camera_url == ""):
            QMessageBox.critical(
                self,
                "Error",
                "Please provide camera and control URLs in url.txt"
            )
            sys.exit(1)
        self.host = urlparse(self.control_url).hostname

        
        # --------------------
        # Left side
        # --------------------

        self.bar_graph = BarGraphWidget()

        self.audio_button = QPushButton()
        self.video_button = QPushButton()
        self.shutdown_button = QPushButton()

        self.update_audio_button()
        self.update_video_button()

        self.shutdown_button.setText("Shutdown")
        
        self.audio_button.clicked.connect(self.toggle_audio)
        self.video_button.clicked.connect(self.toggle_video)
        self.shutdown_button.clicked.connect(self.shutdown_requested)

        self.audio_button.setMinimumHeight(80)
        self.video_button.setMinimumHeight(80)
        self.shutdown_button.setMinimumHeight(80)

        self.audio_button.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )

        self.video_button.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
        )
        self.shutdown_button.setStyleSheet("""
            QPushButton {
            background-color: #b00000;
            color: white;
            font-size: 20px;
            font-weight: bold;
}        """)
        
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.bar_graph, stretch=1)
        left_layout.addWidget(self.audio_button)
        left_layout.addWidget(self.video_button)
        left_layout.addWidget(self.shutdown_button)
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

        # --------------------
        # Update timer (100 ms)
        # --------------------

        self.network_manager = QNetworkAccessManager()
        
        self.camera_watchdog = QTimer(self)
        self.camera_watchdog.timeout.connect(
            self.check_camera
        )
        self.camera_watchdog.start(2000)
        
        self.audio_streamer = AudioStreamer(
            self.audio_url,
            gain=3.0
        )

        self.audio_streamer.volume_changed.connect(
            self.audio_level_changed
        )

        self.audio_streamer.status_changed.connect(
            self.audio_status_changed
        )        

        self.audio_streamer.start_stream()

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
        # First check camera host is reachable via ping 
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "2", self.host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3
            )

            if result.returncode == 0:
                # Host is up - check camera is running
                try:
                    request = QNetworkRequest(
                        QUrl(self.control_url)
                    )

                    self.reply = self.network_manager.get(request)

                    # Set camera up / down when connect finished 
                    self.reply.finished.connect(
                        self.on_camera_check_finished
                    )        
                    # result = subprocess.run(
                    #     [
                    #         "wget",
                    #         "--spider",
                    #         "--timeout=2",
                    #         "--tries=1",
                    #         self.control_url
                    #     ],
                    #     stdout=subprocess.DEVNULL,
                    #     stderr=subprocess.DEVNULL,
                    #     timeout=5
                    # )

                except Exception:
                    self.camera_up = False
            else:
                print(f"Ping failed for host {self.host}, returncode={result.returncode}")
                self.video_stack.setCurrentWidget(
                    self.video_error_label
                )
                self.camera_up = False
                    
        except Exception:
            self.camera_up = False

    def camera_available(self, error):

        down_errors = {
            QNetworkReply.NetworkError.ConnectionRefusedError,
            QNetworkReply.NetworkError.HostNotFoundError,
            QNetworkReply.NetworkError.TimeoutError,
        }

        return error not in down_errors
    
    def on_camera_check_finished(self):
        print(f"Camera check finished, error={self.reply.error()} camera_up={self.camera_up}")
        if self.camera_available(self.reply.error()):
            if self.camera_up == False:
                print("Camera is back up, reloading video feed")
                self.web_view.setUrl(QUrl(self.camera_url))
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

    def audio_level_changed(self, level):
        # print(f"Audio level changed: {level:.2f}, current value: {self.audio_streamer.volume_level():.2f}")
        value = int(level * 100)
        self.bar_graph.set_value(value)

    def audio_status_changed(self, status):
        print(f"Audio status changed: {status}")
        if not self.audio_streamer.is_streaming():
            self.bar_graph.set_audio_status(status)
        else:
            self.bar_graph.set_audio_status("")
            
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
        if self.audio_streamer.is_streaming():
            self.audio_streamer.stop_stream()
            self.audio_toggle_button.setText("Start")

        else:
            self.audio_streamer.start_stream()
            self.audio_toggle_button.setText("Stop")

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

    def shutdown_requested(self):

        reply = QMessageBox.question(
            self,
            "Shutdown",
            "Shutdown Monitor?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.shutdown_pi()

    def shutdown_pi(self):

        print("Shutting down Raspberry Pi")

        subprocess.Popen(
            ["sudo", "shutdown", "-h", "now"]
        )

    def load_urls_from_file(self):

        self.camera_url = ""
        self.control_url = ""
        self.audio_url = ""
        try:
            with open("url.txt", "r", encoding="utf-8") as f:

                for line in f:
                    line = line.strip()

                    if not line:
                        continue

                    parts = line.split(",", 1)

                    if len(parts) != 2:
                        continue

                    label = parts[0].strip().lower()
                    url = parts[1].strip()

                    if label == "camera":
                        self.camera_url = url
                    elif label == "control":
                        self.control_url = url
                    elif label == "audio":
                        self.audio_url = url

            print(f"Camera URL : {self.camera_url}")
            print(f"Control URL: {self.control_url}")
            print(f"Audio URL: {self.audio_url}")

        except Exception as e:
            print(f"Error reading url.txt: {e}")

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
