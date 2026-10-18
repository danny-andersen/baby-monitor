
import sys
import requests

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QBrush
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, 
)
from PyQt6.QtCore import QThread, pyqtSignal


class BatteryStatusWorker(QThread):
    battery_updated = pyqtSignal(int)
    camera_status_updated = pyqtSignal(str)
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

            data = response.json()
            percentage = int(data["battery_perc"])
            percentage = max(0, min(100, percentage))
            self.battery_updated.emit(percentage)

            camera_status = data.get("camera_status", "Unknown")
            self.camera_status_updated.emit(camera_status)

        except (requests.RequestException, ValueError, KeyError) as exc:
            self.status_error.emit(str(exc))
            

class BatteryIcon(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.percentage = 0
        self.setMinimumSize(180, 60)

    def set_percentage(self, value):
        self.percentage = max(0, min(100, int(value)))
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
        painter.setPen(QPen(QColor("#dddddd"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(
            QRectF(5, 5, 130, 50), 6, 6
        )

        # Battery terminal
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dddddd"))
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