#!/usr/bin/env python3
"""A local desktop app for quickly sorting photos and videos into folders."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from html import escape
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QFile, QObject, QEasingCurve, QPropertyAnimation, QRunnable, QSettings, QSize, QThreadPool, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QImage, QImageReader, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:
    pass


APP_NAME = "frameSorter"
LOGO_PATH = Path(__file__).parent / "assets" / "framesorter-logo.png"
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".heic", ".heif", ".avif",
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mpg", ".mpeg",
    ".wmv", ".3gp", ".mts", ".m2ts",
}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
THUMBNAIL_SIZE = QSize(188, 122)
PAGE_SIZE = 120


@dataclass(frozen=True)
class MediaItem:
    path: Path
    category: str | None
    size: int
    modified: float

    @property
    def is_video(self) -> bool:
        return self.path.suffix.lower() in VIDEO_EXTENSIONS


class ThumbnailSignals(QObject):
    ready = Signal(str, QImage)


class ThumbnailTask(QRunnable):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.signals = ThumbnailSignals()

    def run(self) -> None:
        image = QImage()
        try:
            if self.path.suffix.lower() in VIDEO_EXTENSIONS:
                image = self._video_frame()
            else:
                with Image.open(self.path) as source:
                    source = ImageOps.exif_transpose(source).convert("RGB")
                    source.thumbnail((460, 300), Image.Resampling.LANCZOS)
                    raw = source.tobytes("raw", "RGB")
                    image = QImage(
                        raw, source.width, source.height, source.width * 3,
                        QImage.Format.Format_RGB888,
                    ).copy()
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, subprocess.SubprocessError):
            if self.path.suffix.lower() not in VIDEO_EXTENSIONS:
                reader = QImageReader(str(self.path))
                reader.setAutoTransform(True)
                image = reader.read()
                if not image.isNull():
                    image = image.scaled(
                        QSize(460, 300), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        self.signals.ready.emit(str(self.path), image)

    def _video_frame(self) -> QImage:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return QImage()
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-ss", "00:00:01", "-i", str(self.path),
             "-frames:v", "1", "-vf", "scale=460:-1", "-f", "image2pipe",
             "-vcodec", "mjpeg", "pipe:1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return QImage.fromData(result.stdout) if result.returncode == 0 else QImage()


class PreviewImage(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setStyleSheet("background: #11161d; border-radius: 14px;")
        self._pixmap = QPixmap()

    def set_image(self, image: QImage) -> None:
        self._pixmap = QPixmap.fromImage(image)
        self._scale()

    def set_placeholder(self, text: str) -> None:
        self._pixmap = QPixmap()
        self.setText(text)
        self.setStyleSheet(
            "background: #11161d; color: #8994a3; border-radius: 14px;"
            "font-size: 14px; padding: 20px;"
        )

    def _scale(self) -> None:
        if not self._pixmap.isNull():
            self.setText("")
            self.setStyleSheet("background: #11161d; border-radius: 14px;")
            self.setPixmap(self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale()


class LogoMark(QLabel):
    def __init__(self, size: int = 64, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setObjectName("splashLogo")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(LOGO_PATH))
        if pixmap.isNull():
            self.setText("▣")
            self.setStyleSheet("color:#23a8ff; font-size:32px; background:transparent;")
        else:
            self.setPixmap(pixmap.scaled(
                size, size, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))


class MediaCard(QFrame):
    clicked = Signal(str)

    def __init__(self, path: Path, is_video: bool):
        super().__init__()
        self.path = path
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setObjectName("mediaCard")
        self.setFixedSize(188, 172)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 8)
        layout.setSpacing(6)
        self.thumb = QLabel("VIDEO" if is_video else "PHOTO")
        self.thumb.setObjectName("thumbnail")
        self.thumb.setFixedSize(THUMBNAIL_SIZE)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setScaledContents(False)
        self.thumb.setStyleSheet("background: #11161d; color: #8190a2; border-radius: 8px;")
        layout.addWidget(self.thumb)
        self.name = QLabel(path.name)
        self.name.setObjectName("cardName")
        self.name.setToolTip(str(path))
        self.name.setWordWrap(False)
        layout.addWidget(self.name)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.clicked.emit(str(self.path))
        super().mousePressEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_thumbnail(self, image: QImage) -> None:
        if image.isNull():
            return
        self.thumb.setText("")
        self.thumb.setPixmap(QPixmap.fromImage(image).scaled(
            THUMBNAIL_SIZE, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        ))


class ConfirmMoveDialog(QDialog):
    def __init__(self, item_name: str, destination_name: str, final_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm move")
        self.setMinimumWidth(410)
        layout = QVBoxLayout(self)
        title = QLabel("Move this item?")
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        target_text = f"<b>{item_name}</b><br><span style='color:#8d99a8'>→ {destination_name}/{final_name}</span>"
        details = QLabel(target_text)
        details.setWordWrap(True)
        layout.addWidget(details)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Move and continue")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class DeveloperCreditDialog(QDialog):
    """Opening splash carrying the developer credit requested by Shhmyr."""

    def __init__(self, button_text: str = "Open frameSorter  →", parent=None):
        super().__init__(parent)
        self.setWindowTitle("frameSorter")
        self.setFixedWidth(540)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 28)
        layout.setSpacing(12)

        eyebrow = QLabel("LOCAL PHOTO + VIDEO ORGANIZER")
        eyebrow.setObjectName("splashEyebrow")
        layout.addWidget(eyebrow)

        hero = QHBoxLayout()
        hero.setSpacing(16)
        logo = LogoMark(64)
        hero.addWidget(logo)
        name_stack = QVBoxLayout()
        name_stack.setSpacing(0)
        title = QLabel("frameSorter")
        title.setObjectName("splashTitle")
        name_stack.addWidget(title)
        byline = QLabel("by Shhmyr")
        byline.setObjectName("splashByline")
        name_stack.addWidget(byline)
        hero.addLayout(name_stack)
        hero.addStretch(1)
        layout.addLayout(hero)

        subtitle = QLabel("A calmer way to sort your photo and video library.")
        subtitle.setObjectName("splashSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setObjectName("splashDivider")
        layout.addWidget(divider)

        credit = QLabel("✦  Developed and Organized by <b>Shhmyr</b> - Muhammad Shahmeer Mughal")
        credit.setObjectName("splashCredit")
        credit.setWordWrap(True)
        layout.addWidget(credit)
        contact = QLabel(
            '<a href="mailto:shhmyr@hotmail.com">✉  shhmyr@hotmail.com</a><br>'
            '<a href="tel:+92332771881">☎  +92332771881</a><br>'
            '<a href="https://www.linkedin.com/in/shhmyr771/">↗  linkedin.com/in/shhmyr771</a>'
        )
        contact.setObjectName("splashContact")
        contact.setOpenExternalLinks(True)
        contact.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(contact)
        layout.addSpacing(8)
        continue_button = QPushButton(button_text)
        continue_button.setObjectName("primaryButton")
        continue_button.setMinimumHeight(42)
        continue_button.clicked.connect(self.accept)
        layout.addWidget(continue_button)

        self._intro_animations: list[QPropertyAnimation] = []
        self._intro_targets = [logo, title, byline, subtitle, credit, contact, continue_button]
        for widget in self._intro_targets:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.0)
            widget.setGraphicsEffect(effect)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._intro_animations:
            return
        for index, widget in enumerate(self._intro_targets):
            effect = widget.graphicsEffect()
            animation = QPropertyAnimation(effect, b"opacity", self)
            animation.setDuration(380)
            animation.setStartValue(0.0)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._intro_animations.append(animation)
            QTimer.singleShot(index * 65, animation.start)


class FrameSorter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Shhmyr", "frameSorter")
        self.root: Path | None = None
        self.items: list[MediaItem] = []
        self.categories: list[str] = []
        self.filter_name = "all"
        self.search_text = ""
        self.visible_items: list[MediaItem] = []
        self.selected_path: Path | None = None
        self.cards: dict[str, MediaCard] = {}
        self.thumb_cache: dict[str, QImage] = {}
        self.thumb_running: set[str] = set()
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(6)
        self.undo_stack: list[tuple[Path, Path]] = []
        self.loaded_count = 0
        self.columns = 4
        self._refreshing = False
        self.thumbnail_tasks: dict[str, ThumbnailTask] = {}

        self.setWindowTitle("frameSorter")
        self.setMinimumSize(1080, 680)
        self.resize(1450, 900)
        self._build_ui()
        self._install_shortcuts()
        last_root = self.settings.value("last_root", "", type=str)
        if not last_root:
            for old_org, old_app in [("Shhmyr", "FrameSort"), ("FrameSorter", "FrameSorter")]:
                last_root = QSettings(old_org, old_app).value("last_root", "", type=str)
                if last_root:
                    self.settings.setValue("last_root", last_root)
                    break
        if last_root and Path(last_root).is_dir():
            self.load_library(Path(last_root))

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        shell = QHBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(242)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(20, 24, 16, 18)
        side.setSpacing(12)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(10)
        main_logo = LogoMark(44)
        main_logo.setToolTip("frameSorter logo")
        brand_row.addWidget(main_logo)
        brand_details = QVBoxLayout()
        brand_details.setSpacing(2)
        brand = QLabel("frameSorter")
        brand.setObjectName("brand")
        tagline = QLabel("PHOTO + VIDEO SORTER")
        tagline.setObjectName("tagline")
        brand_details.addWidget(brand)
        brand_details.addWidget(tagline)
        brand_row.addLayout(brand_details, 1)
        side.addLayout(brand_row)
        self.library_label = QLabel("No library selected")
        self.library_label.setObjectName("libraryLabel")
        self.library_label.setWordWrap(True)
        side.addWidget(self.library_label)
        choose_btn = QPushButton("＋  Choose library folder")
        choose_btn.setObjectName("primaryButton")
        choose_btn.clicked.connect(self.choose_library)
        side.addWidget(choose_btn)
        side.addSpacing(16)

        self.filter_all = self._nav_button("▦", "All media", "all")
        self.filter_unsorted = self._nav_button("◌", "Needs sorting", "unsorted")
        side.addWidget(self.filter_all)
        side.addWidget(self.filter_unsorted)
        side.addSpacing(12)
        folder_heading = QHBoxLayout()
        folder_title = QLabel("PEOPLE & FOLDERS")
        folder_title.setObjectName("sectionLabel")
        folder_heading.addWidget(folder_title)
        folder_heading.addStretch(1)
        add_btn = QPushButton("＋")
        add_btn.setObjectName("iconButton")
        add_btn.setToolTip("Create a person folder")
        add_btn.clicked.connect(self.create_category)
        folder_heading.addWidget(add_btn)
        side.addLayout(folder_heading)
        self.category_host = QWidget()
        self.category_layout = QVBoxLayout(self.category_host)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(4)
        side.addWidget(self.category_host)
        side.addStretch(1)
        shortcuts = QLabel("← →  Browse   ·   1–9  Move\n0  Return to unsorted   ·   Ctrl+Z  Undo")
        shortcuts.setObjectName("shortcutHint")
        shortcuts.setWordWrap(True)
        side.addWidget(shortcuts)
        info_button = QPushButton("ⓘ  Info")
        info_button.setObjectName("secondaryButton")
        info_button.clicked.connect(self.show_info)
        side.addWidget(info_button)
        shell.addWidget(sidebar)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 18)
        content_layout.setSpacing(16)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)
        self.heading = QLabel("Your media, in order")
        self.heading.setObjectName("pageTitle")
        toolbar.addWidget(self.heading)
        toolbar.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search filenames…   Ctrl+F")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self.search.textChanged.connect(self.on_search)
        toolbar.addWidget(self.search)
        self.confirm_moves = QCheckBox("Confirm moves")
        self.confirm_moves.setChecked(self.settings.value("confirm_each_move", True, type=bool))
        self.confirm_moves.toggled.connect(lambda enabled: self.settings.setValue("confirm_each_move", enabled))
        toolbar.addWidget(self.confirm_moves)
        content_layout.addLayout(toolbar)

        self.stats_label = QLabel("Choose a folder to get started")
        self.stats_label.setObjectName("muted")
        content_layout.addWidget(self.stats_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.gallery = self._build_gallery()
        splitter.addWidget(self.gallery)
        self.preview_panel = self._build_preview()
        splitter.addWidget(self.preview_panel)
        splitter.setSizes([720, 490])
        content_layout.addWidget(splitter, 1)
        shell.addWidget(content, 1)
        self.statusBar().showMessage("Choose a folder containing photos and videos to begin.")

    def _nav_button(self, icon: str, label: str, filter_name: str) -> QPushButton:
        button = QPushButton(f"{icon}   {label}")
        button.setObjectName("navButton")
        button.setCheckable(True)
        button.setProperty("filterName", filter_name)
        button.clicked.connect(lambda: self.set_filter(filter_name))
        return button

    def _build_gallery(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(8)
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.gallery_body = QWidget()
        self.grid = QGridLayout(self.gallery_body)
        self.grid.setContentsMargins(2, 2, 2, 12)
        self.grid.setSpacing(12)
        self.gallery_scroll.setWidget(self.gallery_body)
        layout.addWidget(self.gallery_scroll, 1)
        footer = QHBoxLayout()
        self.load_more_button = QPushButton("Load more")
        self.load_more_button.setObjectName("secondaryButton")
        self.load_more_button.clicked.connect(self.load_more)
        footer.addWidget(self.load_more_button)
        footer.addStretch(1)
        self.page_count = QLabel("")
        self.page_count.setObjectName("muted")
        footer.addWidget(self.page_count)
        layout.addLayout(footer)
        return panel

    def _build_preview(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("previewPanel")
        panel.setMinimumWidth(350)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.media_kind = QLabel("PREVIEW")
        self.media_kind.setObjectName("sectionLabel")
        top.addWidget(self.media_kind)
        top.addStretch(1)
        self.position_label = QLabel("—")
        self.position_label.setObjectName("muted")
        top.addWidget(self.position_label)
        layout.addLayout(top)
        self.preview_image = PreviewImage()
        self.preview_image.set_placeholder("Select a photo or video to preview it")
        layout.addWidget(self.preview_image, 1)
        self.preview_title = QLabel("Nothing selected")
        self.preview_title.setObjectName("previewTitle")
        self.preview_title.setWordWrap(True)
        layout.addWidget(self.preview_title)
        self.preview_meta = QLabel("Your files stay on this computer.")
        self.preview_meta.setObjectName("muted")
        self.preview_meta.setWordWrap(True)
        layout.addWidget(self.preview_meta)
        actions = QHBoxLayout()
        self.destination = QComboBox()
        self.destination.setMinimumWidth(150)
        self.move_button = QPushButton("Move item")
        self.move_button.setObjectName("primaryButton")
        self.move_button.clicked.connect(self.move_selected_from_combo)
        self.play_button = QPushButton("▶  Play video")
        self.play_button.setObjectName("secondaryButton")
        self.play_button.clicked.connect(self.play_selected_video)
        actions.addWidget(self.destination, 1)
        actions.addWidget(self.move_button)
        layout.addLayout(actions)
        layout.addWidget(self.play_button)
        self.trash_button = QPushButton("🗑  Move to Trash")
        self.trash_button.setObjectName("trashButton")
        self.trash_button.clicked.connect(self.trash_selected)
        layout.addWidget(self.trash_button)
        self._update_preview_controls()
        return panel

    def _install_shortcuts(self) -> None:
        find = QAction(self)
        find.setShortcut(QKeySequence("Ctrl+F"))
        find.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        find.triggered.connect(lambda: (self.search.setFocus(), self.search.selectAll()))
        self.addAction(find)
        open_folder = QAction(self)
        open_folder.setShortcut(QKeySequence("Ctrl+O"))
        open_folder.triggered.connect(self.choose_library)
        self.addAction(open_folder)

    def keyPressEvent(self, event) -> None:
        if isinstance(QApplication.focusWidget(), QLineEdit):
            super().keyPressEvent(event)
            return
        key = event.key()
        if key == Qt.Key.Key_Z and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.undo_move()
        elif key == Qt.Key.Key_Left:
            self.step_selection(-1)
        elif key == Qt.Key.Key_Right:
            self.step_selection(1)
        elif key == Qt.Key.Key_Up:
            self.step_selection(-self.columns)
        elif key == Qt.Key.Key_Down:
            self.step_selection(self.columns)
        elif key == Qt.Key.Key_Home:
            self.select_index(0)
        elif key == Qt.Key.Key_End:
            self.select_index(len(self.visible_items) - 1)
        elif key == Qt.Key.Key_Delete:
            self.trash_selected()
        elif int(Qt.Key.Key_0) <= key <= int(Qt.Key.Key_9):
            self.quick_move(key - int(Qt.Key.Key_0))
        else:
            super().keyPressEvent(event)

    def choose_library(self) -> None:
        start = str(self.root or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose your media library", start)
        if folder:
            self.load_library(Path(folder))

    def load_library(self, root: Path) -> None:
        self.root = root.resolve()
        self.settings.setValue("last_root", str(self.root))
        self.library_label.setText(self.root.name or str(self.root))
        self.library_label.setToolTip(str(self.root))
        self.scan_library()

    def scan_library(self) -> None:
        if not self.root:
            return
        old_selection = self.selected_path
        items: list[MediaItem] = []
        try:
            with os.scandir(self.root) as entries:
                root_entries = list(entries)
        except OSError as exc:
            QMessageBox.critical(self, "Can't open folder", str(exc))
            return
        directories: list[Path] = []
        for entry in root_entries:
            try:
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    directories.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in MEDIA_EXTENSIONS:
                    stat = entry.stat(follow_symlinks=False)
                    items.append(MediaItem(Path(entry.path), None, stat.st_size, stat.st_mtime))
            except OSError:
                continue
        categories = sorted(path.name for path in directories if path.name not in {".DS_Store"})
        for directory in directories:
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in MEDIA_EXTENSIONS:
                            stat = entry.stat(follow_symlinks=False)
                            items.append(MediaItem(Path(entry.path), directory.name, stat.st_size, stat.st_mtime))
            except OSError:
                continue
        self.categories = categories
        self.items = sorted(items, key=lambda item: item.modified, reverse=True)
        self._rebuild_category_buttons()
        self._rebuild_destination_choices()
        if self.filter_name not in {"all", "unsorted"} and self.filter_name not in self.categories:
            self.filter_name = "all"
        self._sync_filter_buttons()
        self.apply_filter(old_selection)

    def _rebuild_category_buttons(self) -> None:
        while self.category_layout.count():
            child = self.category_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        counts: dict[str, int] = {name: 0 for name in self.categories}
        for item in self.items:
            if item.category in counts:
                counts[item.category] += 1
        self.category_buttons: dict[str, QPushButton] = {}
        for index, name in enumerate(self.categories):
            shortcut = f"{index + 1}  " if index < 9 else "    "
            button = QPushButton(f"▱   {shortcut}{name}   ·   {counts[name]}")
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setProperty("filterName", name)
            button.clicked.connect(lambda checked=False, category=name: self.set_filter(category))
            self.category_buttons[name] = button
            self.category_layout.addWidget(button)
        self.category_layout.addStretch(1)

    def _rebuild_destination_choices(self) -> None:
        current = self.destination.currentData() if self.destination.count() else "unsorted"
        self.destination.blockSignals(True)
        self.destination.clear()
        self.destination.addItem("↩  Unsorted", "unsorted")
        for index, category in enumerate(self.categories):
            prefix = f"{index + 1}  " if index < 9 else ""
            self.destination.addItem(f"{prefix}{category}", category)
        index = self.destination.findData(current)
        self.destination.setCurrentIndex(index if index >= 0 else 0)
        self.destination.blockSignals(False)
        self._update_preview_controls()

    def _sync_filter_buttons(self) -> None:
        self.filter_all.setChecked(self.filter_name == "all")
        self.filter_unsorted.setChecked(self.filter_name == "unsorted")
        for name, button in getattr(self, "category_buttons", {}).items():
            button.setChecked(self.filter_name == name)

    def set_filter(self, filter_name: str) -> None:
        self.filter_name = filter_name
        self._sync_filter_buttons()
        self.apply_filter()

    def on_search(self, text: str) -> None:
        self.search_text = text.strip().casefold()
        self.apply_filter()

    def apply_filter(self, preferred: Path | None = None) -> None:
        self._refreshing = True
        previous = self.selected_path
        if self.filter_name == "unsorted":
            filtered = [item for item in self.items if item.category is None]
        elif self.filter_name == "all":
            filtered = list(self.items)
        else:
            filtered = [item for item in self.items if item.category == self.filter_name]
        if self.search_text:
            filtered = [item for item in filtered if self.search_text in item.path.name.casefold()]
        self.visible_items = filtered
        self.loaded_count = 0
        self._clear_cards()
        self.heading.setText({"all": "All media", "unsorted": "Needs sorting"}.get(self.filter_name, self.filter_name))
        self.stats_label.setText(
            f"{len(filtered):,} items  ·  {sum(item.size for item in filtered) / (1024 ** 3):.1f} GB"
            if self.root else "Choose a folder to get started"
        )
        target = preferred if preferred else previous
        target_index = next((i for i, item in enumerate(filtered) if item.path == target), 0 if filtered else -1)
        self._append_cards(min(max(target_index + PAGE_SIZE, PAGE_SIZE), len(filtered)))
        if target_index >= 0:
            self.select_index(target_index, scroll=False)
        else:
            self.selected_path = None
            self.show_preview(None)
        self._refreshing = False

    def _clear_cards(self) -> None:
        self.cards.clear()
        while self.grid.count():
            child = self.grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _append_cards(self, count: int) -> None:
        if count <= self.loaded_count:
            return
        self.columns = max(2, min(5, (self.gallery_scroll.viewport().width() + 12) // 200))
        start = self.loaded_count
        self.loaded_count = count
        for index in range(start, count):
            item = self.visible_items[index]
            key = str(item.path)
            card = MediaCard(item.path, item.is_video)
            card.clicked.connect(self.select_path_string)
            self.cards[key] = card
            row, column = divmod(index, self.columns)
            self.grid.addWidget(card, row, column)
            if key in self.thumb_cache:
                card.set_thumbnail(self.thumb_cache[key])
            else:
                self._request_thumbnail(item.path)
        self.load_more_button.setVisible(self.loaded_count < len(self.visible_items))
        self.page_count.setText(f"Showing {self.loaded_count:,} of {len(self.visible_items):,}")

    def load_more(self) -> None:
        self._append_cards(min(self.loaded_count + PAGE_SIZE, len(self.visible_items)))

    def _request_thumbnail(self, path: Path) -> None:
        key = str(path)
        if key in self.thumb_running:
            return
        self.thumb_running.add(key)
        task = ThumbnailTask(path)
        self.thumbnail_tasks[key] = task
        task.signals.ready.connect(self.on_thumbnail_ready)
        self.thread_pool.start(task)

    def on_thumbnail_ready(self, key: str, image: QImage) -> None:
        self.thumb_running.discard(key)
        self.thumbnail_tasks.pop(key, None)
        if not image.isNull():
            self.thumb_cache[key] = image
            card = self.cards.get(key)
            if card:
                card.set_thumbnail(image)
            if self.selected_path and str(self.selected_path) == key:
                self.show_preview_image(image)

    def select_path_string(self, path: str) -> None:
        index = next((i for i, item in enumerate(self.visible_items) if str(item.path) == path), -1)
        if index >= 0:
            self.select_index(index)

    def select_index(self, index: int, scroll: bool = True) -> None:
        if not self.visible_items:
            self.selected_path = None
            self.show_preview(None)
            return
        index = max(0, min(index, len(self.visible_items) - 1))
        while index >= self.loaded_count:
            self.load_more()
        item = self.visible_items[index]
        old = str(self.selected_path) if self.selected_path else None
        self.selected_path = item.path
        if old in self.cards:
            self.cards[old].set_selected(False)
        card = self.cards.get(str(item.path))
        if card:
            card.set_selected(True)
            if scroll:
                self.gallery_scroll.ensureWidgetVisible(card, 20, 20)
        self.position_label.setText(f"{index + 1} / {len(self.visible_items)}")
        self.show_preview(item)

    def step_selection(self, delta: int) -> None:
        if self.search.hasFocus():
            return
        if not self.visible_items:
            return
        current = next((i for i, item in enumerate(self.visible_items) if item.path == self.selected_path), -1)
        self.select_index((current if current >= 0 else 0) + delta)

    def show_preview(self, item: MediaItem | None) -> None:
        if item is None:
            self.media_kind.setText("PREVIEW")
            self.position_label.setText("—")
            self.preview_title.setText("Nothing selected")
            self.preview_meta.setText("Your files stay on this computer.")
            self.preview_image.set_placeholder("Select a photo or video to preview it")
            self._update_preview_controls()
            return
        self.media_kind.setText("VIDEO" if item.is_video else "PHOTO")
        try:
            dimensions = self._dimensions(item.path)
            dimension_text = f"{dimensions[0]:,} × {dimensions[1]:,}" if dimensions else "Preview unavailable"
        except (OSError, ValueError, subprocess.SubprocessError):
            dimension_text = "Preview unavailable"
        changed = datetime.fromtimestamp(item.modified).strftime("%b %d, %Y")
        size_text = self._format_size(item.size)
        self.preview_title.setText(item.path.name)
        location = f"Currently in  {item.category}" if item.category else "Currently in  Needs sorting"
        self.preview_meta.setText(f"{location}\n{dimension_text}  ·  {size_text}  ·  {changed}")
        cached = self.thumb_cache.get(str(item.path))
        if cached:
            self.show_preview_image(cached)
        else:
            self.preview_image.set_placeholder("Preparing preview…")
            self._request_thumbnail(item.path)
        self._update_preview_controls()

    @staticmethod
    def _dimensions(path: Path) -> tuple[int, int] | None:
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                return None
            result = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=width,height", "-of", "csv=s=x:p=0", str(path)],
                capture_output=True, text=True, timeout=5, check=False,
            )
            if result.returncode == 0 and "x" in result.stdout:
                width, height = result.stdout.strip().split("x", 1)
                return int(width), int(height)
            return None
        try:
            with Image.open(path) as image:
                return image.size
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            return (size.width(), size.height()) if size.isValid() else None

    def show_preview_image(self, image: QImage) -> None:
        if image.isNull():
            suffix = self.selected_path.suffix.lower() if self.selected_path else ""
            extra = " Install ffmpeg to see video posters." if suffix in VIDEO_EXTENSIONS else ""
            self.preview_image.set_placeholder("Preview unavailable." + extra)
        else:
            self.preview_image.set_image(image)

    def _update_preview_controls(self) -> None:
        has_item = bool(self.selected_path and self.selected_path.exists())
        self.destination.setEnabled(has_item)
        self.move_button.setEnabled(has_item and self.destination.count() > 0)
        self.trash_button.setVisible(has_item)
        self.trash_button.setEnabled(has_item)
        is_video = has_item and self.selected_path.suffix.lower() in VIDEO_EXTENSIONS
        self.play_button.setVisible(bool(is_video))

    def move_selected_from_combo(self) -> None:
        target = self.destination.currentData()
        if target is not None:
            self.move_selected(str(target))

    def move_selected(self, target: str) -> None:
        item = next((entry for entry in self.items if entry.path == self.selected_path), None)
        if not item or not self.root:
            return
        destination_dir = self.root if target == "unsorted" else self.root / target
        if item.path.parent.resolve() == destination_dir.resolve():
            self.statusBar().showMessage("This item is already in that folder.", 2500)
            return
        if not destination_dir.is_dir() or (
            target != "unsorted"
            and (destination_dir.is_symlink() or destination_dir.resolve().parent != self.root.resolve())
        ):
            QMessageBox.warning(self, "Folder not available", "That destination folder no longer exists. Rescan and try again.")
            self.scan_library()
            return
        target_path = self._non_conflicting_path(destination_dir / item.path.name)
        target_name = "Needs sorting" if target == "unsorted" else target
        if self.filter_name == "all":
            unsorted_before = [entry for entry in self.visible_items if entry.category is None]
            old_index = next((i for i, entry in enumerate(unsorted_before) if entry.path == item.path), 0)
            self.filter_name = "unsorted"
        else:
            old_index = next((i for i, entry in enumerate(self.visible_items) if entry.path == item.path), 0)
        ask = self.confirm_moves.isChecked()
        if ask:
            dialog = ConfirmMoveDialog(item.path.name, target_name, target_path.name, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
        origin = item.path
        try:
            self._move_without_overwrite(origin, target_path)
        except OSError as exc:
            QMessageBox.critical(self, "Move failed", f"The original file is still in place.\n\n{exc}")
            return
        self.undo_stack.append((target_path, origin))
        self.scan_library()
        if self.visible_items:
            self.select_index(min(old_index, len(self.visible_items) - 1))
        self.statusBar().showMessage(
            f"Moved to {target_name}  ·  Ctrl+Z to undo", 5000
        )

    @staticmethod
    def _non_conflicting_path(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 1
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _move_without_overwrite(source: Path, destination: Path) -> None:
        """Move within a library without ever replacing an existing file."""
        try:
            os.link(source, destination)
            try:
                source.unlink()
            except OSError:
                destination.unlink(missing_ok=True)
                raise
            return
        except FileExistsError:
            raise
        except OSError:
            # Hard links can be unavailable on some file systems. Copy exclusively,
            # then remove the original only after the copy and metadata are safe.
            created_destination = False
            try:
                with source.open("rb") as src, destination.open("xb") as dst:
                    created_destination = True
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                shutil.copystat(source, destination, follow_symlinks=False)
                source.unlink()
            except Exception:
                if created_destination:
                    destination.unlink(missing_ok=True)
                raise

    def quick_move(self, number: int) -> None:
        if isinstance(QApplication.focusWidget(), QLineEdit) or not self.selected_path:
            return
        if number == 0:
            self.move_selected("unsorted")
        elif number <= min(len(self.categories), 9):
            self.move_selected(self.categories[number - 1])

    def undo_move(self) -> None:
        if not self.undo_stack:
            self.statusBar().showMessage("There are no moves to undo.", 2500)
            return
        moved, original = self.undo_stack[-1]
        if not moved.exists():
            self.undo_stack.pop()
            self.statusBar().showMessage("That moved file is no longer available to undo.", 3000)
            return
        destination = self._non_conflicting_path(original)
        try:
            self._move_without_overwrite(moved, destination)
        except OSError as exc:
            QMessageBox.critical(self, "Undo failed", str(exc))
            return
        self.undo_stack.pop()
        self.filter_name = "all"
        self.scan_library()
        self.select_path_string(str(destination))
        self.statusBar().showMessage("Move undone.", 3000)

    def create_category(self) -> None:
        if not self.root:
            QMessageBox.information(self, "Choose a library", "Choose a library folder first.")
            return
        from PySide6.QtWidgets import QInputDialog
        name, accepted = QInputDialog.getText(self, "Create person folder", "Folder name")
        if not accepted:
            return
        name = name.strip()
        if not name or name in {".", ".."} or any(ch in name for ch in ("/", "\\", "\0")):
            QMessageBox.warning(self, "Invalid folder name", "Enter a simple folder name without slashes.")
            return
        target = self.root / name
        if target.exists():
            if target.is_dir():
                self.scan_library()
                self.set_filter(name)
                return
            QMessageBox.warning(self, "Name already in use", "A file with that name already exists in this library.")
            return
        try:
            target.mkdir()
        except OSError as exc:
            QMessageBox.critical(self, "Could not create folder", str(exc))
            return
        self.scan_library()
        self.set_filter(name)
        self.statusBar().showMessage(f"Created folder “{name}”.  Shortcut: {self.categories.index(name) + 1 if name in self.categories and self.categories.index(name) < 9 else 'use the Move menu'}", 5000)

    def play_selected_video(self) -> None:
        if self.selected_path and self.selected_path.exists():
            from PySide6.QtGui import QDesktopServices
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.selected_path))):
                self.statusBar().showMessage("Couldn't open this video in the default player.", 4000)

    def trash_selected(self) -> None:
        if not self.selected_path or not self.selected_path.is_file():
            return
        path = self.selected_path
        answer = QMessageBox.question(
            self,
            "Move to Trash?",
            f"Move <b>{escape(path.name)}</b> to your computer's Trash? You can restore it from Trash later.",
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not hasattr(QFile, "moveToTrash"):
            QMessageBox.warning(
                self, "Trash support unavailable",
                "Update PySide6 to version 6.8 or newer to use Move to Trash.",
            )
            return
        old_index = next((i for i, item in enumerate(self.visible_items) if item.path == path), 0)
        if not QFile.moveToTrash(str(path)):
            QMessageBox.critical(
                self, "Couldn't move item to Trash",
                "The original file is still in its library folder. Your computer may not have Trash available for this location.",
            )
            return
        self.selected_path = path
        self.scan_library()
        if self.visible_items:
            self.select_index(min(old_index, len(self.visible_items) - 1))
        self.statusBar().showMessage(f"Moved {path.name} to Trash. You can restore it from your computer's Trash.", 5000)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_columns = max(2, min(5, (self.gallery_scroll.viewport().width() + 12) // 200))
        if new_columns != self.columns and self.visible_items:
            self.columns = new_columns
            current = self.selected_path
            self.apply_filter(current)

    def _format_size(self, size: int) -> str:
        if size >= 1024 ** 3:
            return f"{size / (1024 ** 3):.1f} GB"
        if size >= 1024 ** 2:
            return f"{size / (1024 ** 2):.1f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} bytes"

    def show_info(self) -> None:
        dialog = DeveloperCreditDialog("Close", self)
        dialog.exec()


STYLE = """
QWidget { background: #171c23; color: #e8edf3; font-family: 'Inter', 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow { background: #171c23; }
#sidebar { background: #11161d; border-right: 1px solid #28313d; }
#brand { color: #f2f5f8; font-size: 24px; font-weight: 800; letter-spacing: 1.5px; }
#tagline, #sectionLabel { color: #718095; font-size: 10px; font-weight: 700; letter-spacing: 1.4px; }
#libraryLabel { color: #aeb8c5; font-size: 12px; padding-top: 8px; }
#pageTitle { color: #f1f4f7; font-size: 23px; font-weight: 700; }
#muted { color: #8994a3; font-size: 12px; }
#shortcutHint { color: #738092; font-size: 11px; line-height: 1.4; padding: 8px 0; }
QPushButton { border: none; border-radius: 8px; padding: 9px 12px; color: #dce3ea; background: #242c36; }
QPushButton:hover { background: #303b48; }
QPushButton:disabled { color: #616b79; background: #20262f; }
#primaryButton { background: #dc805b; color: #1e1715; font-weight: 700; }
#primaryButton:hover { background: #ed9671; }
#secondaryButton { background: #283340; font-weight: 600; }
#trashButton { background: #39262b; color: #f0b4b4; font-weight: 650; }
#trashButton:hover { background: #4a2d34; }
#iconButton { padding: 5px 9px; color: #aeb9c8; font-size: 16px; }
#navButton { text-align: left; background: transparent; color: #aeb8c5; padding: 9px 10px; }
#navButton:hover { background: #1b232d; }
#navButton:checked { background: #252f3b; color: #f5f7f9; font-weight: 650; }
QLineEdit, QComboBox { background: #202832; border: 1px solid #303a47; border-radius: 8px; padding: 9px 11px; color: #e8edf3; selection-background-color: #b66e51; }
QComboBox QAbstractItemView { background: #202832; selection-background-color: #384656; }
QScrollArea { background: transparent; }
#mediaCard { background: #202832; border: 1px solid #2d3744; border-radius: 11px; }
#mediaCard:hover { border: 1px solid #68798d; }
#mediaCard[selected="true"] { border: 2px solid #e68d68; background: #29313a; }
#thumbnail { border-radius: 8px; }
#cardName { color: #d4dbe3; font-size: 11px; padding: 0 3px; }
#previewPanel { background: #1d242d; border: 1px solid #2d3743; border-radius: 14px; }
#previewTitle { color: #eff2f5; font-size: 15px; font-weight: 650; }
#dialogTitle { color: #eff2f5; font-size: 18px; font-weight: 700; padding-bottom: 8px; }
#splashEyebrow { color: #e3906c; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
#splashLogo { background: transparent; border: none; }
#splashTitle { color: #f3f5f7; font-size: 34px; font-weight: 800; letter-spacing: -1px; padding-top: 2px; }
#splashByline { color: #e3906c; font-size: 13px; font-weight: 650; padding-left: 2px; }
#splashSubtitle { color: #9ca7b5; font-size: 14px; padding-bottom: 3px; }
#splashDivider { color: #303a47; background: #303a47; max-height: 1px; margin: 8px 0; }
#splashCredit { color: #e2e8ee; font-size: 14px; padding-top: 3px; }
#splashContact { color: #b5bfcb; font-size: 13px; line-height: 1.8; }
#splashContact a { color: #e4a080; text-decoration: none; }
QCheckBox { spacing: 8px; color: #aeb8c5; }
QCheckBox::indicator { width: 16px; height: 16px; }
QStatusBar { background: #11161d; border-top: 1px solid #28313d; color: #aeb8c5; }
QSplitter::handle { background: transparent; width: 10px; }
QMessageBox, QDialog { background: #1b222b; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    splash = DeveloperCreditDialog()
    if splash.exec() != QDialog.DialogCode.Accepted:
        return 0
    window = FrameSorter()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
