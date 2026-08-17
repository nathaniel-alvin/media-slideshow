#!/usr/bin/env python3
"""
Offline Fullscreen Media Slideshow for Windows
==============================================

Requirements
------------
- Python 3.9 or newer
- Windows 10/11

Install dependencies
--------------------
Open PowerShell or Command Prompt and run:

    pip install PyQt6

Run the application
-------------------
From this folder:

    python slideshow.py

Usage
-----
1. Click "Select Media Folder" and choose a folder containing images and/or videos.
2. Optionally enable "Randomize/Shuffle Media".
3. Set "Image Duration" (seconds) for how long each image is shown.
4. Click "Start Slideshow" for borderless fullscreen playback.
5. Press Esc at any time to stop and return to the setup window.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QKeyEvent, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".webm", ".m4v", ".mpeg", ".mpg"}


def scan_media_folder(folder: Path) -> list[Path]:
    """Return supported image and video files from a folder (non-recursive)."""
    if not folder.is_dir():
        return []

    files: list[Path] = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if suffix in IMAGE_EXTENSIONS or suffix in VIDEO_EXTENSIONS:
            files.append(entry)
    return files


def is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


class SlideshowWindow(QWidget):
    """Borderless fullscreen slideshow with image and video support."""

    def __init__(
        self,
        media_files: list[Path],
        image_duration_sec: float,
        randomize: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_media = media_files
        self._image_duration_ms = max(1, int(image_duration_sec * 1000))
        self._randomize = randomize

        self._playlist: list[Path] = []
        self._index = 0
        self._current_pixmap: QPixmap | None = None

        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet("background-color: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget(self)
        root_layout.addWidget(self._stack)

        self._image_label = QLabel(self)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("background-color: black;")
        self._stack.addWidget(self._image_label)

        self._video_widget = QVideoWidget(self)
        self._video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._video_widget.setStyleSheet("background-color: black;")
        self._stack.addWidget(self._video_widget)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

        self._image_timer = QTimer(self)
        self._image_timer.setSingleShot(True)
        self._image_timer.timeout.connect(self._advance)

        self._reset_playlist()
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        QTimer.singleShot(0, self._show_current)

    def _reset_playlist(self) -> None:
        self._playlist = list(self._all_media)
        if self._randomize:
            random.shuffle(self._playlist)
        self._index = 0

    def _show_current(self) -> None:
        if not self._playlist:
            self.stop_and_close()
            return

        if self._index >= len(self._playlist):
            self._reset_playlist()

        path = self._playlist[self._index]
        self._image_timer.stop()
        self._player.stop()

        if is_video(path):
            self._stack.setCurrentWidget(self._video_widget)
            self._image_label.clear()
            self._current_pixmap = None
            self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self._player.play()
        else:
            self._stack.setCurrentWidget(self._image_label)
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self._advance()
                return
            self._current_pixmap = pixmap
            self._update_image_display()
            self._image_timer.start(self._image_duration_ms)

    def _update_image_display(self) -> None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        scaled = self._current_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def _advance(self) -> None:
        self._index += 1
        self._show_current()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._advance()

    def _on_player_error(self, _error: QMediaPlayer.Error, _message: str) -> None:
        self._advance()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._stack.currentWidget() is self._image_label:
            self._update_image_display()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.stop_and_close()
            return
        super().keyPressEvent(event)

    def stop_and_close(self) -> None:
        self._image_timer.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        self.hide()
        self.deleteLater()


class SetupWindow(QMainWindow):
    """Main setup window for choosing media and slideshow options."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Media Slideshow")
        self.setMinimumSize(420, 260)

        self._media_folder: Path | None = None
        self._slideshow: SlideshowWindow | None = None

        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(12)

        title = QLabel("Offline Fullscreen Media Slideshow")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        self._folder_label = QLabel("No folder selected")
        self._folder_label.setWordWrap(True)
        layout.addWidget(self._folder_label)

        select_btn = QPushButton("Select Media Folder")
        select_btn.clicked.connect(self._select_folder)
        layout.addWidget(select_btn)

        self._randomize_checkbox = QCheckBox("Randomize/Shuffle Media")
        layout.addWidget(self._randomize_checkbox)

        duration_row = QHBoxLayout()
        duration_row.addWidget(QLabel("Image Duration (seconds):"))
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(0.5, 3600.0)
        self._duration_spin.setSingleStep(0.5)
        self._duration_spin.setValue(5.0)
        self._duration_spin.setDecimals(1)
        duration_row.addWidget(self._duration_spin)
        layout.addLayout(duration_row)

        self._start_btn = QPushButton("Start Slideshow")
        self._start_btn.clicked.connect(self._start_slideshow)
        layout.addWidget(self._start_btn)

        hint = QLabel("Press Esc during the slideshow to return here.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Media Folder",
            str(self._media_folder or Path.home()),
        )
        if not folder:
            return

        self._media_folder = Path(folder)
        media_count = len(scan_media_folder(self._media_folder))
        self._folder_label.setText(
            f"{self._media_folder}\n({media_count} supported media file(s) found)"
        )

    def _start_slideshow(self) -> None:
        if self._media_folder is None:
            QMessageBox.warning(self, "No Folder", "Please select a media folder first.")
            return

        media_files = scan_media_folder(self._media_folder)
        if not media_files:
            QMessageBox.warning(
                self,
                "No Media Found",
                "The selected folder does not contain supported image or video files.",
            )
            return

        if self._slideshow is not None:
            self._slideshow.stop_and_close()
            self._slideshow = None

        self._slideshow = SlideshowWindow(
            media_files=media_files,
            image_duration_sec=self._duration_spin.value(),
            randomize=self._randomize_checkbox.isChecked(),
        )
        self._slideshow.destroyed.connect(self._on_slideshow_closed)
        self.hide()

    def _on_slideshow_closed(self) -> None:
        self._slideshow = None
        self.show()
        self.raise_()
        self.activateWindow()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Media Slideshow")

    window = SetupWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
