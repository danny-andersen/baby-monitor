
import sys
import requests

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, 
)
from PyQt6.QtCore import QThread, pyqtSignal

class BatteryStatus:
    battery_level = 0
    charging = 0
    camera_status = ""
    video_addr = ""
    video_on = 0
    microphone_on = 0
    

class BatteryStatusWorker(QThread):
    status_updated = pyqtSignal(BatteryStatus)
    status_error = pyqtSignal(str)

    def __init__(self, status_url, parent=None):
        super().__init__(parent)
        self.status_url = status_url

    def run(self):
        try:
            response = requests.get(
                self.status_url, timeout=10
            )
            response.raise_for_status()
            status = BatteryStatus()
            data = response.json()
            percentage = int(data["battery_perc"])
            status.battery_level = max(0, min(100, percentage))
            status.camera_status = data.get("camera_status", "unknown")
            status.video_addr = data.get("video_addr", "0.0.0.0")
            status.charging = data.get("charging", 0)
            status.video_on = data.get("video", 0)
            status.microphone_on = data.get("microphone", 0)
            self.status_updated.emit(status)

        except (requests.RequestException, ValueError, KeyError) as exc:
            self.status_error.emit(str(exc))
            

class BatteryIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.percentage = 0
        self.charging = 0
        self.setMinimumSize(180, 60)

    def set_status(self, status: BatteryStatus):
        self.percentage = status.battery_level
        self.charging = bool(status.charging)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing
        )

        painter.translate(
            (self.width() - 150) / 2,
            (self.height() - 60) / 2
        )

        # Battery outline
        painter.setPen(QPen(QColor("#404040"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(5, 5, 130, 50), 6, 6
        )

        # Battery terminal
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#404040"))
        painter.drawRoundedRect(
            QRectF(137, 19, 8, 22), 2, 2
        )

        # Charge colour
        if self.percentage <= 20:
            colour = QColor("#e53935")
        elif self.percentage <= 40:
            colour = QColor("#ffb300")
        else:
            colour = QColor("#43a047")

        # Fill level
        fill_width = 122 * self.percentage / 100
        painter.setBrush(QBrush(colour))
        painter.drawRoundedRect(
            QRectF(9, 9, fill_width, 42), 3, 3
        )

        # Percentage centred inside the battery
        painter.setPen(QColor("#202020"))
        font = painter.font()
        font.setBold(True)
        font.setPointSize(15)
        painter.setFont(font)

        if self.charging:
            # Position percentage towards the left
            painter.drawText(
                QRectF(7, 5, 83, 50),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.percentage}%"
            )

            # Draw a lightning bolt on the right
            bolt = [
                (108, 10),
                (94, 31),
                (104, 31),
                (98, 49),
                (119, 24),
                (108, 24),
            ]

            from PyQt6.QtGui import QPolygonF
            from PyQt6.QtCore import QPointF

            cx, cy = 106.5, 29.5
            scale = 0.8

            scaled_bolt = [
                QPointF(
                    cx + (x - cx) * scale,
                    cy + (y - cy) * scale
                )
                for x, y in bolt
            ]

            painter.setPen(QPen(QColor("#202020"), 1))
            painter.setBrush(QColor("#202020"))
            painter.drawPolygon(QPolygonF(scaled_bolt))
        else:
            # Centre percentage when not charging
            painter.drawText(
                QRectF(5, 5, 130, 50),
                Qt.AlignmentFlag.AlignCenter,
                f"{self.percentage}%"
            )
            
        painter.end()

class BatteryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Battery Status")
        self.resize(260, 180)

        layout = QVBoxLayout(self)

        self.icon = BatteryIcon()
        layout.addWidget(self.icon)

        # self.label = QLabel("75%")
        # self.label.setAlignment(
        #     Qt.AlignmentFlag.AlignCenter
        # )
        # self.label.setStyleSheet(
        #     "font-size: 24px; font-weight: bold;"
        # )
        # layout.addWidget(self.label)

        # Demo slider: remove this when using real data

    def update_battery(self, percentage):
        self.icon.set_percentage(percentage)
        # self.label.setText(f"{percentage}%")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BatteryWindow()
    window.show()
    sys.exit(app.exec())