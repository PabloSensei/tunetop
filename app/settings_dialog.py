"""Settings window: appearance, behaviour, hotkeys, media source, skins.

Changes are applied live (there is no OK/Cancel dance) and written to disk
immediately, so the widget always reflects what you see here.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QSlider,
    QTabWidget, QVBoxLayout, QWidget,
)

from .config import HOTKEY_ACTIONS, Settings, user_skins_dir
from .hotkeys import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, format_hotkey, parse_hotkey
from .i18n import available_languages, language_name, resolve_language, tr
from .media import friendly_source_name
from .skins import available_skins, load_skin
from . import system

FUNCTION_KEYS = set(range(0x70, 0x88))  # F1..F24
MEDIA_KEYS = {0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}


def hint_label(text: str) -> QLabel:
    """Muted explanatory text that stays readable on light and dark themes."""
    label = QLabel(text)
    label.setWordWrap(True)
    color = label.palette().color(QPalette.ColorRole.WindowText)
    color.setAlpha(155)
    label.setStyleSheet(
        f"color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()});"
    )
    return label


class HotkeyEdit(QLineEdit):
    """Captures a key combination using the native virtual key code."""

    captured = Signal(str)

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setReadOnly(True)
        self.setPlaceholderText(tr("settings.hotkey_placeholder"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setClearButtonEnabled(False)

    def event(self, event: QEvent) -> bool:
        # Intercept before Qt turns Tab/arrows into focus navigation.
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride) and self.hasFocus():
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            self._capture(event)
            return True
        return super().event(event)

    def _capture(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift, Qt.Key.Key_Meta,
                   Qt.Key.Key_unknown):
            return
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.setText("")
            self.captured.emit("")
            return

        modifiers = event.modifiers()
        mods = 0
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            mods |= MOD_CONTROL
        if modifiers & Qt.KeyboardModifier.AltModifier:
            mods |= MOD_ALT
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            mods |= MOD_SHIFT
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            mods |= MOD_WIN

        vk = int(event.nativeVirtualKey())
        if not vk:
            return
        if not mods and vk not in FUNCTION_KEYS and vk not in MEDIA_KEYS:
            self.setText(tr("settings.hotkey_need_modifier"))
            return
        text = format_hotkey(mods, vk)
        self.setText(text)
        self.captured.emit(text)


class SettingsDialog(QDialog):
    """Live settings editor. `applied` carries a hint about what changed."""

    applied = Signal(str)

    def __init__(self, settings: Settings, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.controller = controller
        self._sources: list[dict] = controller.sources
        self._loading = True

        self.setWindowTitle(tr("settings.title"))
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(540)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_general_tab(), tr("settings.tab.general"))
        self._tabs.addTab(self._build_hotkeys_tab(), tr("settings.tab.hotkeys"))
        self._tabs.addTab(self._build_source_tab(), tr("settings.tab.source"))
        self._tabs.addTab(self._build_skins_tab(), tr("settings.tab.skins"))
        self._tabs.addTab(self._build_about_tab(), tr("settings.tab.about"))

        close_button = QPushButton(tr("settings.close"))
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._tabs)
        layout.addLayout(buttons)

        controller.sources_changed.connect(self._on_sources)
        # re-read after connecting: the first update may have landed while the
        # tabs above were still being built
        self._sources = controller.sources or self._sources
        self._loading = False
        self._refresh_sources_ui()

    # -- tab state, so a language switch can reopen on the same tab ------------

    def current_tab(self) -> int:
        return self._tabs.currentIndex()

    def set_current_tab(self, index: int) -> None:
        if 0 <= index < self._tabs.count():
            self._tabs.setCurrentIndex(index)

    # ------------------------------------------------------------- general

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        window_box = QGroupBox(tr("settings.group.window"))
        window_form = QVBoxLayout(window_box)
        self.cb_on_top = QCheckBox(tr("settings.always_on_top"))
        self.cb_on_top.setChecked(self.settings.always_on_top)
        self.cb_on_top.toggled.connect(lambda v: self._set("always_on_top", v, "window"))

        self.cb_lock = QCheckBox(tr("settings.lock_position"))
        self.cb_lock.setChecked(self.settings.lock_position)
        self.cb_lock.toggled.connect(lambda v: self._set("lock_position", v, ""))

        self.cb_snap = QCheckBox(tr("settings.snap"))
        self.cb_snap.setChecked(self.settings.snap_to_edges)
        self.cb_snap.toggled.connect(lambda v: self._set("snap_to_edges", v, ""))

        self.cb_remember = QCheckBox(tr("settings.remember_position"))
        self.cb_remember.setChecked(self.settings.remember_position)
        self.cb_remember.toggled.connect(lambda v: self._set("remember_position", v, ""))

        self.cb_compact = QCheckBox(tr("settings.compact"))
        self.cb_compact.setChecked(self.settings.compact)
        self.cb_compact.toggled.connect(lambda v: self._set("compact", v, "skin"))

        self.cb_hide_idle = QCheckBox(tr("settings.hide_when_no_music"))
        self.cb_hide_idle.setChecked(self.settings.hide_when_no_music)
        self.cb_hide_idle.toggled.connect(lambda v: self._set("hide_when_no_music", v, "visibility"))

        for widget in (self.cb_on_top, self.cb_lock, self.cb_snap, self.cb_remember,
                       self.cb_compact, self.cb_hide_idle):
            window_form.addWidget(widget)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel(tr("settings.opacity")))
        self.sl_opacity = QSlider(Qt.Orientation.Horizontal)
        self.sl_opacity.setRange(20, 100)
        self.sl_opacity.setValue(int(self.settings.opacity * 100))
        self.lb_opacity = QLabel(f"{self.sl_opacity.value()}%")
        self.sl_opacity.valueChanged.connect(self._on_opacity)
        opacity_row.addWidget(self.sl_opacity, 1)
        opacity_row.addWidget(self.lb_opacity)
        window_form.addLayout(opacity_row)

        content_box = QGroupBox(tr("settings.group.content"))
        content_form = QVBoxLayout(content_box)
        self.cb_art = QCheckBox(tr("settings.show_art"))
        self.cb_art.setChecked(self.settings.show_album_art)
        self.cb_art.toggled.connect(lambda v: self._set("show_album_art", v, "layout"))
        self.cb_progress = QCheckBox(tr("settings.show_progress"))
        self.cb_progress.setChecked(self.settings.show_progress)
        self.cb_progress.toggled.connect(lambda v: self._set("show_progress", v, "layout"))
        self.cb_scroll = QCheckBox(tr("settings.scroll_titles"))
        self.cb_scroll.setChecked(self.settings.scroll_long_titles)
        self.cb_scroll.toggled.connect(lambda v: self._set("scroll_long_titles", v, ""))
        self.cb_wheel = QCheckBox(tr("settings.wheel_volume"))
        self.cb_wheel.setChecked(self.settings.wheel_volume)
        self.cb_wheel.toggled.connect(lambda v: self._set("wheel_volume", v, ""))
        for widget in (self.cb_art, self.cb_progress, self.cb_scroll, self.cb_wheel):
            content_form.addWidget(widget)

        start_box = QGroupBox(tr("settings.group.startup"))
        start_form = QVBoxLayout(start_box)
        self.cb_autostart = QCheckBox(tr("settings.autostart"))
        self.cb_autostart.setChecked(system.autostart_enabled())
        self.cb_autostart.toggled.connect(self._on_autostart)
        self.cb_tray_start = QCheckBox(tr("settings.start_in_tray"))
        self.cb_tray_start.setChecked(self.settings.start_in_tray)
        self.cb_tray_start.toggled.connect(lambda v: self._set("start_in_tray", v, ""))
        start_form.addWidget(self.cb_autostart)
        start_form.addWidget(self.cb_tray_start)

        language_box = QGroupBox(tr("settings.group.language"))
        language_row = QHBoxLayout(language_box)
        language_row.addWidget(QLabel(tr("settings.language")))
        self.cmb_language = QComboBox()
        self.cmb_language.addItem(
            tr("settings.language_auto", name=language_name(resolve_language("auto"))), "auto"
        )
        for code, name in available_languages():
            self.cmb_language.addItem(name, code)
        index = self.cmb_language.findData(self.settings.language or "auto")
        self.cmb_language.setCurrentIndex(max(0, index))
        self.cmb_language.currentIndexChanged.connect(self._on_language)
        language_row.addWidget(self.cmb_language, 1)

        layout.addWidget(window_box)
        layout.addWidget(content_box)
        layout.addWidget(start_box)
        layout.addWidget(language_box)
        layout.addStretch(1)
        return page

    def _on_opacity(self, value: int) -> None:
        self.lb_opacity.setText(f"{value}%")
        self._set("opacity", value / 100.0, "window")

    def _on_autostart(self, value: bool) -> None:
        if not system.set_autostart(value):
            QMessageBox.warning(self, tr("settings.autostart_failed_title"),
                                tr("settings.autostart_failed"))
            return
        self._set("autostart", value, "")

    def _on_language(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self.settings.language = self.cmb_language.itemData(index) or "auto"
        self.settings.save()
        self.applied.emit("language")

    # ------------------------------------------------------------- hotkeys

    def _build_hotkeys_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.cb_hotkeys = QCheckBox(tr("settings.hotkeys_enabled"))
        self.cb_hotkeys.setChecked(self.settings.hotkeys_enabled)
        self.cb_hotkeys.toggled.connect(lambda v: self._set("hotkeys_enabled", v, "hotkeys"))
        layout.addWidget(self.cb_hotkeys)

        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self._hotkey_edits: dict[str, HotkeyEdit] = {}
        for row, action in enumerate(HOTKEY_ACTIONS):
            grid.addWidget(QLabel(tr(f"hotkey.{action}")), row, 0)
            edit = HotkeyEdit(self.settings.hotkeys.get(action, ""))
            edit.captured.connect(lambda text, a=action: self._on_hotkey(a, text))
            self._hotkey_edits[action] = edit
            grid.addWidget(edit, row, 1)
            clear = QPushButton(tr("settings.hotkey_clear"))
            clear.clicked.connect(lambda _=False, a=action: self._on_hotkey(a, "", clear=True))
            grid.addWidget(clear, row, 2)
        layout.addLayout(grid)

        self.lb_hotkey_status = QLabel("")
        self.lb_hotkey_status.setWordWrap(True)
        layout.addWidget(self.lb_hotkey_status)

        layout.addWidget(hint_label(tr("settings.hotkey_hint")))
        layout.addStretch(1)
        return page

    def _on_hotkey(self, action: str, text: str, clear: bool = False) -> None:
        if clear:
            self._hotkey_edits[action].setText("")
        if text:
            for other, value in self.settings.hotkeys.items():
                if other != action and value and value.lower() == text.lower():
                    self.lb_hotkey_status.setText(tr(
                        "settings.hotkey_conflict", hotkey=text, action=tr(f"hotkey.{other}")
                    ))
                    self.settings.hotkeys[other] = ""
                    if other in self._hotkey_edits:
                        self._hotkey_edits[other].setText("")
            if parse_hotkey(text) is None:
                self.lb_hotkey_status.setText(tr("settings.hotkey_unsupported", hotkey=text))
                return
        self.settings.hotkeys[action] = text
        self.settings.save()
        self.applied.emit("hotkeys_preview")

    def report_hotkey_failures(self, failures: list[tuple[str, str]]) -> None:
        if not failures:
            return
        names = ", ".join(f"{tr(f'hotkey.{action}')} ({text})" for action, text in failures)
        self.lb_hotkey_status.setText(tr("settings.hotkey_failed", names=names))

    # -------------------------------------------------------------- source

    def _build_source_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.rb_auto = QRadioButton(tr("settings.source_auto"))
        self.rb_pinned = QRadioButton(tr("settings.source_pinned"))
        self.rb_auto.setChecked(self.settings.source_mode != "pinned")
        self.rb_pinned.setChecked(self.settings.source_mode == "pinned")
        self.rb_auto.toggled.connect(self._on_source_mode)

        self.cmb_source = QComboBox()
        self.cmb_source.setEnabled(self.settings.source_mode == "pinned")
        self.cmb_source.currentIndexChanged.connect(self._on_source_pick)

        refresh = QPushButton(tr("settings.refresh"))
        refresh.clicked.connect(self.controller.refresh)

        row = QHBoxLayout()
        row.addWidget(self.cmb_source, 1)
        row.addWidget(refresh)

        self.lb_sources = QLabel("")
        self.lb_sources.setWordWrap(True)

        layout.addWidget(self.rb_auto)
        layout.addWidget(self.rb_pinned)
        layout.addLayout(row)
        layout.addWidget(self.lb_sources)
        layout.addWidget(hint_label(tr("settings.source_hint")))
        layout.addStretch(1)
        return page

    def _on_sources(self, sources: list) -> None:
        self._sources = list(sources or [])
        self._refresh_sources_ui()

    def _refresh_sources_ui(self) -> None:
        self._loading = True
        self.cmb_source.clear()
        entries = list(self._sources)
        pinned = self.settings.pinned_source
        if pinned and not any(entry["app_id"] == pinned for entry in entries):
            entries.append({
                "app_id": pinned,
                "name": tr("settings.source_not_running", name=friendly_source_name(pinned)),
                "playing": False,
            })
        for entry in entries:
            label = entry["name"] + (" ▶" if entry.get("playing") else "")
            self.cmb_source.addItem(label, entry["app_id"])
        index = self.cmb_source.findData(pinned)
        if index >= 0:
            self.cmb_source.setCurrentIndex(index)
        if self._sources:
            self.lb_sources.setText(tr(
                "settings.sources_found",
                count=len(self._sources),
                names=", ".join(entry["name"] for entry in self._sources),
            ))
        else:
            self.lb_sources.setText(tr("settings.no_sources"))
        self._loading = False

    def _on_source_mode(self, auto: bool) -> None:
        self.cmb_source.setEnabled(not auto)
        self.settings.source_mode = "auto" if auto else "pinned"
        if not auto and not self.settings.pinned_source and self.cmb_source.count():
            self.settings.pinned_source = self.cmb_source.currentData() or ""
        self.settings.save()
        self.applied.emit("source")

    def _on_source_pick(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self.settings.pinned_source = self.cmb_source.itemData(index) or ""
        self.settings.save()
        if self.settings.source_mode == "pinned":
            self.applied.emit("source")

    # --------------------------------------------------------------- skins

    def _build_skins_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        self.list_skins = QListWidget()
        self.list_skins.itemSelectionChanged.connect(self._on_skin_selected)
        layout.addWidget(self.list_skins, 1)

        self.lb_skin_info = QLabel("")
        self.lb_skin_info.setWordWrap(True)
        layout.addWidget(self.lb_skin_info)

        row = QHBoxLayout()
        reload_button = QPushButton(tr("settings.refresh"))
        reload_button.clicked.connect(self._reload_skins)
        folder_button = QPushButton(tr("settings.skins_folder"))
        folder_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_skins_dir())))
        )
        row.addWidget(reload_button)
        row.addWidget(folder_button)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addWidget(hint_label(tr("settings.skins_hint")))

        self._reload_skins()
        return page

    def _reload_skins(self) -> None:
        self._loading = True
        self.list_skins.clear()
        for skin in available_skins():
            item = QListWidgetItem(skin.name)
            item.setData(Qt.ItemDataRole.UserRole, skin.id)
            item.setToolTip(str(skin.path))
            self.list_skins.addItem(item)
            if skin.id == self.settings.skin:
                self.list_skins.setCurrentItem(item)
        self._loading = False
        self._on_skin_selected()

    def _on_skin_selected(self) -> None:
        item = self.list_skins.currentItem()
        if item is None:
            return
        skin_id = item.data(Qt.ItemDataRole.UserRole)
        skin = load_skin(skin_id)
        width, height = skin.size(self.settings.compact)
        author = tr("settings.skin_author", author=skin.author) if skin.author else ""
        self.lb_skin_info.setText(f"{skin.name}{author} · {width}×{height} · {skin.path}")
        if self._loading or skin_id == self.settings.skin:
            return
        self.settings.skin = skin_id
        self.settings.save()
        self.applied.emit("skin")

    # --------------------------------------------------------------- about

    def _build_about_tab(self) -> QWidget:
        from . import __version__

        page = QWidget()
        layout = QVBoxLayout(page)
        text = QLabel(
            f"<h3>Tunetop {__version__}</h3>"
            f"<p>{tr('about.tagline')}</p>"
            f"<p><b>{tr('about.mouse')}</b><br>"
            f"{tr('about.drag')}<br>"
            f"{tr('about.double_click')}<br>"
            f"{tr('about.middle_click')}<br>"
            f"{tr('about.wheel')}<br>"
            f"{tr('about.right_click')}</p>"
            f"<p><b>{tr('about.files')}</b><br>{tr('about.files_text')} "
            f"<code>{user_skins_dir().parent}</code></p>"
            f"<p>{tr('about.license')}</p>"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(text)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- helpers

    def _set(self, field: str, value, hint: str) -> None:
        if self._loading:
            return
        setattr(self.settings, field, value)
        self.settings.save()
        self.applied.emit(hint or "refresh")

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.controller.sources_changed.disconnect(self._on_sources)
        except (RuntimeError, TypeError):
            pass
        super().closeEvent(event)
