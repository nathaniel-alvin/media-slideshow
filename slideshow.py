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

Or double-click release/MediaSlideshow.exe after building with build_exe.py.

Usage
-----
1. Click "Select Media Folder" and choose a folder containing images and/or videos.
2. Optionally enable "Randomize/Shuffle Media".
3. Set "Image Duration" (seconds) for how long each image is shown.
4. Click "Start Slideshow" for borderless fullscreen playback.
5. Press Esc at any time to stop and return to the setup window.

Slideshow controls
------------------
- Space       Play / Pause
- Left/Right  Previous / Next media
- R           Toggle repeat (loop video or hold image)
- Up/Down     Increase / Decrease volume
- M           Toggle mute
- I           Toggle filename and position overlay
- Esc         Exit slideshow
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, QEvent
from PyQt6.QtGui import QKeyEvent, QMouseEvent, QPixmap
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

OVERLAY_STYLE = """
    QLabel {
        background-color: rgba(0, 0, 0, 160);
        color: white;
        padding: 8px 14px;
        font-size: 15px;
        border-radius: 6px;
    }
"""


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

    CURSOR_HIDE_MS = 2000
    OSD_HIDE_MS = 2000
    VOLUME_STEP = 0.05

    def __init__(
        self,
        media_files: list[Path],
        image_duration_sec: float,
        randomize: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_media = media_files
        self._base_image_duration_ms = max(1, int(image_duration_sec * 1000))
        self._paused_remaining_ms = 0
        self._randomize = randomize

        self._playlist: list[Path] = []
        self._index = 0
        self._current_pixmap: QPixmap | None = None

        self._paused = False
        self._repeat_mode = False
        self._muted = False
        self._volume = 1.0
        self._show_info = False
        self._cursor_hidden = False

        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        )
        self.setStyleSheet("background-color: black;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

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

        for widget in (self._stack, self._image_label, self._video_widget):
            widget.setMouseTracking(True)
            widget.installEventFilter(self)

        self._player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.setVideoOutput(self._video_widget)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)
        self._audio_output.setVolume(self._volume)

        self._image_timer = QTimer(self)
        self._image_timer.setSingleShot(True)
        self._image_timer.timeout.connect(self._advance)

        self._info_label = QLabel(self)
        self._info_label.setStyleSheet(OVERLAY_STYLE)
        self._info_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._info_label.hide()

        self._osd_label = QLabel(self)
        self._osd_label.setStyleSheet(OVERLAY_STYLE)
        self._osd_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._osd_label.hide()

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setSingleShot(True)
        self._cursor_timer.timeout.connect(self._hide_cursor)

        self._osd_timer = QTimer(self)
        self._osd_timer.setSingleShot(True)
        self._osd_timer.timeout.connect(self._osd_label.hide)

        self._reset_playlist()
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        self.setFocus()
        self._start_cursor_hide_timer()
        QTimer.singleShot(0, self._show_current)

    def _reset_playlist(self) -> None:
        self._playlist = list(self._all_media)
        if self._randomize:
            random.shuffle(self._playlist)
        self._index = 0

    def _current_path(self) -> Path | None:
        if not self._playlist or self._index >= len(self._playlist):
            return None
        return self._playlist[self._index]

    def _is_showing_video(self) -> bool:
        path = self._current_path()
        return path is not None and is_video(path)

    def _is_showing_image(self) -> bool:
        path = self._current_path()
        return path is not None and not is_video(path)

    def _show_current(self) -> None:
        if not self._playlist:
            self.stop_and_close()
            return

        if self._index >= len(self._playlist):
            self._reset_playlist()

        path = self._playlist[self._index]
        self._paused_remaining_ms = 0
        self._image_timer.stop()
        self._player.stop()

        if is_video(path):
            self._stack.setCurrentWidget(self._video_widget)
            self._image_label.clear()
            self._current_pixmap = None
            self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
            self._player.play()
            if self._paused:
                self._player.pause()
        else:
            self._stack.setCurrentWidget(self._image_label)
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                self._advance()
                return
            self._current_pixmap = pixmap
            self._update_image_display()
            self._start_image_timer_if_needed()

        self._update_info_overlay()
        self._position_overlays()
        self._info_label.raise_()
        self._osd_label.raise_()

    def _start_image_timer_if_needed(self) -> None:
        if self._repeat_mode or self._paused:
            return
        duration = self._paused_remaining_ms or self._base_image_duration_ms
        self._image_timer.start(max(1, duration))
        self._paused_remaining_ms = 0

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
        if self._paused:
            return
        self._index += 1
        self._show_current()

    def _go_next(self) -> None:
        if not self._playlist:
            return
        self._paused = False
        self._paused_remaining_ms = 0
        self._index = (self._index + 1) % len(self._playlist)
        self._show_current()

    def _go_previous(self) -> None:
        if not self._playlist:
            return
        self._paused = False
        self._paused_remaining_ms = 0
        self._index = (self._index - 1) % len(self._playlist)
        self._show_current()

    def _on_media_status(self, status: QMediaPlayer.MediaStatus) -> None:
        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return
        if self._repeat_mode and self._is_showing_video():
            self._player.setPosition(0)
            if not self._paused:
                self._player.play()
            return
        if not self._paused:
            self._advance()

    def _on_player_error(self, _error: QMediaPlayer.Error, _message: str) -> None:
        if not self._paused:
            self._advance()

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._is_showing_video():
            if self._paused:
                self._player.pause()
            else:
                self._player.play()
        elif self._is_showing_image():
            if self._paused:
                remaining = self._image_timer.remainingTime()
                self._image_timer.stop()
                if remaining > 0:
                    self._paused_remaining_ms = remaining
            elif not self._repeat_mode:
                self._start_image_timer_if_needed()
        self._show_osd("Paused" if self._paused else "Playing")

    def _toggle_repeat(self) -> None:
        self._repeat_mode = not self._repeat_mode
        if self._is_showing_image():
            if self._repeat_mode:
                remaining = self._image_timer.remainingTime()
                self._image_timer.stop()
                if remaining > 0:
                    self._paused_remaining_ms = remaining
            elif not self._paused:
                self._start_image_timer_if_needed()
        self._show_osd(f"Repeat: {'ON' if self._repeat_mode else 'OFF'}")

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self._audio_output.setMuted(self._muted)
        self._show_osd("Muted" if self._muted else "Unmuted")

    def _adjust_volume(self, delta: float) -> None:
        self._volume = max(0.0, min(1.0, self._volume + delta))
        self._audio_output.setVolume(self._volume)
        if self._volume > 0.0 and self._muted:
            self._muted = False
            self._audio_output.setMuted(False)
        percent = int(round(self._volume * 100))
        self._show_osd(f"Volume: {percent}%")

    def _toggle_info(self) -> None:
        self._show_info = not self._show_info
        self._update_info_overlay()

    def _update_info_overlay(self) -> None:
        if not self._show_info or not self._playlist:
            self._info_label.hide()
            return
        path = self._current_path()
        filename = path.name if path else "Unknown"
        position = f"{self._index + 1} / {len(self._playlist)}"
        self._info_label.setText(f"{filename}\n{position}")
        self._info_label.adjustSize()
        self._info_label.show()
        self._position_overlays()

    def _show_osd(self, message: str) -> None:
        self._osd_label.setText(message)
        self._osd_label.adjustSize()
        self._osd_label.show()
        self._position_overlays()
        self._osd_timer.start(self.OSD_HIDE_MS)

    def _position_overlays(self) -> None:
        margin = 20
        if self._info_label.isVisible():
            self._info_label.move(margin, margin)
        if self._osd_label.isVisible():
            x = self.width() - self._osd_label.width() - margin
            y = self.height() - self._osd_label.height() - margin
            self._osd_label.move(max(margin, x), max(margin, y))

    def _start_cursor_hide_timer(self) -> None:
        self._cursor_timer.start(self.CURSOR_HIDE_MS)

    def _reveal_cursor(self) -> None:
        if self._cursor_hidden:
            self.unsetCursor()
            self._cursor_hidden = False
        self._start_cursor_hide_timer()

    def _hide_cursor(self) -> None:
        self.setCursor(Qt.CursorShape.BlankCursor)
        self._cursor_hidden = True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._stack.currentWidget() is self._image_label:
            self._update_image_display()
        self._position_overlays()
        self._info_label.raise_()
        self._osd_label.raise_()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._reveal_cursor()
        super().mouseMoveEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            self._reveal_cursor()
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        if key == Qt.Key.Key_Escape:
            self.stop_and_close()
            return
        if key == Qt.Key.Key_Space:
            self._toggle_pause()
            return
        if key == Qt.Key.Key_Right:
            self._go_next()
            return
        if key == Qt.Key.Key_Left:
            self._go_previous()
            return
        if key in (Qt.Key.Key_R,):
            self._toggle_repeat()
            return
        if key == Qt.Key.Key_Up:
            self._adjust_volume(self.VOLUME_STEP)
            return
        if key == Qt.Key.Key_Down:
            self._adjust_volume(-self.VOLUME_STEP)
            return
        if key == Qt.Key.Key_M:
            self._toggle_mute()
            return
        if key == Qt.Key.Key_I:
            self._toggle_info()
            return

        super().keyPressEvent(event)

    def stop_and_close(self) -> None:
        self._image_timer.stop()
        self._cursor_timer.stop()
        self._osd_timer.stop()
        self._player.stop()
        self._player.setSource(QUrl())
        self.unsetCursor()
        self.hide()
        self.deleteLater()


class SetupWindow(QMainWindow):
    """Main setup window for choosing media and slideshow options."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Media Slideshow")
        self.setMinimumSize(420, 300)

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

        hint = QLabel(
            "Esc: exit slideshow\n"
            "Space: pause/play | ←/→: prev/next | R: repeat\n"
            "↑/↓: volume | M: mute | I: info overlay"
        )
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
