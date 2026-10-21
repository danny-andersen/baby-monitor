import sys
import subprocess
import json
from urllib.parse import urlparse

from PyQt6.QtCore import Qt, QTimer, QUrl, QPointF, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QPolygonF, QBrush
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
from battery_status import BatteryIcon, BatteryStatusWorker


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
        if "playing" in status:
            self.audio_status = ""
        else:
            self.audio_status = status
        self.update()


    def paintEvent(self, event):
        painter = QPainter(self)

        # painter.fillRect(self.rect(), Qt.GlobalColor.gray)

        margin = 10

        bar_width = self.width() - (2 * margin)
        bar_height = self.height() - (2 * margin)

        x = margin
        y = margin

        # Outer border
        painter.setPen(QPen(Qt.GlobalColor.gray, 2))
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


class SpeakerButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.audio_on = True
        self.setFixedSize(200, 60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "font-size: 20px; font-weight: bold;"
            "background-color: Gray;"
            "border: 4px solid #cccccc;"
            "border-radius: 16px;"
        )

    def set_audio(self, enabled):
        self.audio_on = bool(enabled)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        # Centre the 48 x 40 speaker drawing in the button
        painter.translate(
            (self.width() - 48) / 2,
            (self.height() - 40) / 2
        )

        painter.setPen(QPen(QColor("#222222"), 2.5))
        painter.setBrush(QBrush(QColor("#222222")))

        # Speaker body
        painter.drawPolygon(QPolygonF([
            QPointF(9, 19),
            QPointF(16, 19),
            QPointF(25, 12),
            QPointF(25, 36),
            QPointF(16, 29),
            QPointF(9, 29),
        ]))

        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self.audio_on:
            # Sound waves
            painter.drawArc(
                QRectF(19, 14, 18, 20), -55 * 16, 110 * 16
            )
            painter.drawArc(
                QRectF(19, 8, 29, 32), -55 * 16, 110 * 16
            )
        else:
            # Cross through speaker when muted
            painter.setPen(QPen(QColor("#d32f2f"), 3))
            painter.drawLine(29, 17, 42, 31)
            painter.drawLine(42, 17, 29, 31)

        painter.end()



class PowerButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 60)
        self.setMinimumHeight(60)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
            background-color: #b00000;
            color: white;
            font-size: 20px;
            font-weight: bold;
            border: 4px solid #cccccc;
            border-radius: 16px;
}        """)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        # Centre a 32 x 32 power icon in the button
        painter.translate(
            (self.width() - 32) / 2,
            (self.height() - 32) / 2
        )

        painter.setPen(QPen(
            QColor("#222222"),
            3,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap
        ))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Complete circular ring
        painter.drawEllipse(QRectF(3, 3, 26, 26))

        # Cover the top-centre section to create the gap
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b00000"))
        painter.drawRect(QRectF(10, 0, 12, 12))

        # Draw the vertical power line
        painter.setPen(QPen(
            QColor("#222222"),
            3,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap
        ))
        painter.drawLine(QPointF(16, 1), QPointF(16, 17))        # Vertical power line

        painter.end()


class MainWindow(QWidget):

    def __init__(self):
        super().__init__()

        self.audio_enabled = True
        self.video_enabled = True
        self.camera_up = False
        self.camera_status = ""

        self.setStyleSheet("background-color: LightGray;")
        
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
        if (self.camera_health == "") or (self.camera_url == ""):
            QMessageBox.critical(
                self,
                "Error",
                "Please provide camera and control URLs in url.txt"
            )
            sys.exit(1)
        self.host = urlparse(self.camera_health).hostname

        
        # --------------------
        # Left side
        # --------------------

        self.bar_graph = BarGraphWidget()

        self.audio_button = SpeakerButton()
        self.audio_button.set_audio(self.audio_enabled)
        self.audio_button.clicked.connect(self.toggle_audio)

        self.icon = BatteryIcon()

        self.shutdown_button = PowerButton()
        self.shutdown_button.clicked.connect(self.shutdown_requested)
        
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.bar_graph, stretch=1)
        left_layout.addWidget(self.icon)
        left_layout.addWidget(self.audio_button)
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

        self.video_error_label = QLabel(f"Loading Video feed\n\nPlease wait..")
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
        self.video_container = QWidget()
        self.video_container.setLayout(self.video_stack)
        self.video_stack.setCurrentWidget(self.video_error_label)

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

        self.start_battery_polling()

    def on_load_started(self):
        print("Video stream started")

        self.video_stack.setCurrentWidget(
            self.web_view
        )
        self.camera_up = True

    # def on_load_finished(self):
    #     print("Video stream stopped")

    #     self.video_stack.setCurrentWidget(
    #         self.video_loading_label
    #     )
    #     self.camera_up = False


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
                        QUrl(self.camera_health)
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
                # print(f"Ping failed for host {self.host}, returncode={result.returncode}")
                if self.camera_up:
                    self.update_camera_status("failed")
                    self.video_stack.setCurrentWidget(
                        self.video_error_label
                    )
                    self.camera_up = False
                    
        except Exception:
            if self.camera_up:
                self.update_camera_status("host unreachable")
                self.video_stack.setCurrentWidget(
                    self.video_error_label
                )
                self.camera_up = False

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
            try: 
                data = json.loads(bytes(self.reply.readAll()).decode())
                if data.get("camera_ok"):
                    if self.camera_up == False:
                        print("Camera is back up, reloading video feed")
                        self.web_view.setUrl(QUrl(self.camera_url))
                        self.camera_up = True
                    self.video_stack.setCurrentWidget(self.web_view)
            except Exception as e:
                print(f"Error parsing camera health response: {e}")
                self.update_camera_status("garbled")
                self.video_stack.setCurrentWidget(
                    self.video_error_label
                )
    
        else:
            # print("Camera not available, showing error label")
            if self.camera_up:
                self.update_camera_status("unavailable")
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
        self.bar_graph.set_audio_status(status)
            
    # ==================================================
    # Audio
    # ==================================================


    def toggle_audio(self):
        self.audio_enabled = not self.audio_enabled
        self.audio_streamer.audio_output_enabled = self.audio_enabled
        self.audio_button.set_audio(self.audio_enabled)

    # ==================================================
    # Shutdown
    # ==================================================

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
 
    # ==================================================
    # Remote Battery status
    # ==================================================
        
    def start_battery_polling(self):
        # Fetch immediately, then once every minute
        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(
            self.fetch_battery_status
        )
        self.fetch_battery_status()
        self.battery_timer.start(5000)


    def fetch_battery_status(self):
        # Avoid overlapping requests
        if hasattr(self, "battery_worker"):
            if self.battery_worker.isRunning():
                return

        self.battery_worker = BatteryStatusWorker(
            self.status_url, self
        )
        self.battery_worker.battery_updated.connect(
            self.update_battery
        )
        self.battery_worker.camera_status_updated.connect(
            self.update_camera_status
        )
        self.battery_worker.status_error.connect(
            self.battery_status_error
        )
        self.battery_worker.charging_status_updated.connect(
            self.icon.set_charging
        )

        self.battery_worker.start()


    def update_battery(self, percentage):
        self.icon.set_percentage(percentage)

    def battery_status_error(self, message):
        self.icon.set_percentage(0)
        self.update_camera_status("unavailable")
        # print(f"Battery status request failed: {message}")
        
    def update_camera_status(self, status):
        self.camera_status = status
        retry = "Retrying..." if "available" in self.camera_status else ""
        retry = "Waiting..." if "starting" in self.camera_status else retry
        
        self.video_error_label.setText(
            f"Video feed {self.camera_status}\n\n{retry}"
        )

    # ==================================================
    # URL loader
    # ==================================================


    def load_urls_from_file(self):

        self.camera_url = ""
        self.camera_health = ""
        self.audio_url = ""
        self.status_url = ""
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
                    elif label == "camera_health":
                        self.camera_health = url
                    elif label == "audio":
                        self.audio_url = url
                    elif label == "status":
                        self.status_url = url
            print(f"Camera URL : {self.camera_url}")
            print(f"Camera Health URL: {self.camera_health}")
            print(f"Audio URL: {self.audio_url}")
            print(f"Status URL: {self.status_url}")

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
