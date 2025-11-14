# tktst.py
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel
import sys

app = QApplication(sys.argv)

w = QWidget()
w.setWindowTitle("Mini GUI")

layout = QVBoxLayout(w)

input_box = QLineEdit()
button = QPushButton("Press")
label = QLabel("Waiting...")

def on_click():
    label.setText(f"Hi, {input_box.text()}")

button.clicked.connect(on_click)

layout.addWidget(input_box)
layout.addWidget(button)
layout.addWidget(label)

w.show()
sys.exit(app.exec())
