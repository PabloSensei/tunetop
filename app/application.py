"""Application shell: tray icon, menus, hotkey routing, single instance guard."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import __version__, icons, system
from .config import Settings, migrate_legacy_config
from .hotkeys import HotkeyManager
from .i18n import set_language, tr
from .media import MediaController, PlayerState, friendly_source_name
from .player_widget import PlayerWidget
from .settings_dialog import SettingsDialog
from .skins import available_skins, load_skin
from .updates import (
    RELEASES_PAGE_URL,
    ReleaseInfo,
    UpdateChecker,
    check_is_due,
    check_stamp,
    is_newer,
    offer_update,
)

IPC_KEY = "Tunetop.singleton"


def another_instance_notified() -> bool:
    """True if an instance is already running (and was asked to show itself)."""
    socket = QLocalSocket()
    socket.connectToServer(IPC_KEY)
    if socket.waitForConnected(250):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(250)
        socket.disconnectFromServer()
        return True
    return False


class MusicControlApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings = Settings.load()
        set_language(self.settings.language)
        self.dialog: SettingsDialog | None = None
        self._update_checker: UpdateChecker | None = None
        # Set when the user asks for the widget explicitly; suppresses the
        # "hide when nothing is playing" rule until a track shows up.
        self._forced_visible = False

        self.controller = MediaController(self.settings.source_mode, self.settings.pinned_source)
        self.widget = PlayerWidget(self.settings)
        self.hotkeys = HotkeyManager(app)
        self.tray = QSystemTrayIcon()

        self._server = QLocalServer()
        QLocalServer.removeServer(IPC_KEY)
        self._server.listen(IPC_KEY)
        self._server.newConnection.connect(self._on_ipc)

        self._wire()
        self._build_tray()
        self._apply_hotkeys()

        self.controller.start()
        if not self.settings.start_in_tray:
            self.widget.show()
        self._maybe_check_for_updates()

    # ----------------------------------------------------------------- wiring

    def _wire(self) -> None:
        self.controller.state_changed.connect(self._on_state)
        self.controller.failed.connect(self._on_failure)

        self.widget.command.connect(self.run_action)
        self.widget.open_settings.connect(self.show_settings)
        self.widget.open_menu.connect(self._show_context_menu)
        self.widget.hide_to_tray.connect(self.hide_widget)
        self.widget.quit_requested.connect(self.quit)

        self.hotkeys.triggered.connect(self.run_action_name)
        self.app.aboutToQuit.connect(self._cleanup)

    def _on_ipc(self) -> None:
        connection = self._server.nextPendingConnection()
        if connection is None:
            return
        connection.readyRead.connect(lambda: (connection.readAll(), self.show_widget()))
        connection.disconnected.connect(connection.deleteLater)

    # ------------------------------------------------------------------- tray

    def app_icon(self) -> QIcon:
        accent = self.widget.skin.color("accent")
        icon = QIcon()
        for size in (16, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            icons.paint_app_icon(painter, QRectF(0, 0, size, size), accent)
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    def _refresh_icon(self) -> None:
        """Recompute the icon (skin accent may have changed) and apply it everywhere."""
        icon = self.app_icon()
        self.tray.setIcon(icon)
        self.app.setWindowIcon(icon)  # default for dialogs/message boxes with no icon of their own

    def _build_tray(self) -> None:
        self._refresh_icon()
        self.tray.setToolTip("Tunetop")
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.setContextMenu(self._build_menu())
        self.tray.show()

    def _build_menu(self) -> QMenu:
        menu = QMenu()

        toggle = QAction(tr("menu.hide_widget") if self.widget.isVisible()
                         else tr("menu.show_widget"), menu)
        toggle.triggered.connect(self.toggle_widget)
        menu.addAction(toggle)
        menu.addSeparator()

        state = self.controller.state
        play = QAction(tr("menu.pause") if state.playing else tr("menu.play"), menu)
        play.triggered.connect(lambda: self.run_action("play_pause", None))
        menu.addAction(play)
        prev_action = QAction(tr("menu.previous"), menu)
        prev_action.triggered.connect(lambda: self.run_action("prev_track", None))
        menu.addAction(prev_action)
        next_action = QAction(tr("menu.next"), menu)
        next_action.triggered.connect(lambda: self.run_action("next_track", None))
        menu.addAction(next_action)
        menu.addSeparator()

        source_menu = menu.addMenu(tr("menu.source"))
        group = QActionGroup(source_menu)
        group.setExclusive(True)
        auto = QAction(tr("menu.source_auto"), source_menu)
        auto.setCheckable(True)
        auto.setChecked(self.settings.source_mode != "pinned")
        auto.triggered.connect(lambda: self._pick_source("auto", ""))
        group.addAction(auto)
        source_menu.addAction(auto)
        sources = self.controller.sources
        if sources:
            source_menu.addSeparator()
        for entry in sources:
            action = QAction(entry["name"] + (" ▶" if entry.get("playing") else ""), source_menu)
            action.setCheckable(True)
            action.setChecked(self.settings.source_mode == "pinned"
                              and self.settings.pinned_source == entry["app_id"])
            action.triggered.connect(
                lambda _=False, app_id=entry["app_id"]: self._pick_source("pinned", app_id)
            )
            group.addAction(action)
            source_menu.addAction(action)

        skin_menu = menu.addMenu(tr("menu.skin"))
        skin_group = QActionGroup(skin_menu)
        skin_group.setExclusive(True)
        for skin in available_skins():
            action = QAction(skin.name, skin_menu)
            action.setCheckable(True)
            action.setChecked(skin.id == self.settings.skin)
            action.triggered.connect(lambda _=False, skin_id=skin.id: self._pick_skin(skin_id))
            skin_group.addAction(action)
            skin_menu.addAction(action)

        compact = QAction(tr("menu.compact"), menu)
        compact.setCheckable(True)
        compact.setChecked(self.settings.compact)
        compact.triggered.connect(self._toggle_compact)
        menu.addAction(compact)

        on_top = QAction(tr("menu.always_on_top"), menu)
        on_top.setCheckable(True)
        on_top.setChecked(self.settings.always_on_top)
        on_top.triggered.connect(self._toggle_on_top)
        menu.addAction(on_top)

        menu.addSeparator()
        settings_action = QAction(tr("menu.settings"), menu)
        settings_action.triggered.connect(self.show_settings)
        menu.addAction(settings_action)
        quit_action = QAction(tr("menu.quit"), menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        return menu

    def _refresh_menu(self) -> None:
        self.tray.setContextMenu(self._build_menu())

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_widget()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = self._build_menu()
        menu.exec(global_pos)

    # ---------------------------------------------------------------- actions

    def run_action_name(self, action: str) -> None:
        self.run_action(action, None)

    def run_action(self, action: str, value=None) -> None:
        if action == "toggle_widget":
            self.toggle_widget()
        elif action == "volume_up":
            system.volume_up()
        elif action == "volume_down":
            system.volume_down()
        elif action == "settings":
            self.show_settings()
        else:
            self.controller.command(action, value)

    def toggle_widget(self) -> None:
        if self.widget.isVisible():
            self.hide_widget()
        else:
            self.show_widget()

    def show_widget(self) -> None:
        self._forced_visible = True
        self.widget.show()
        self.widget.raise_()
        self._refresh_menu()

    def hide_widget(self) -> None:
        self._forced_visible = False
        self.widget.save_position()
        self.widget.hide()
        self._refresh_menu()

    def _toggle_compact(self, checked: bool) -> None:
        self.widget.set_compact(checked)
        self.settings.save()

    def _toggle_on_top(self, checked: bool) -> None:
        self.settings.always_on_top = checked
        self.settings.save()
        self.widget.refresh_window_flags()

    def _pick_skin(self, skin_id: str) -> None:
        self.settings.skin = skin_id
        self.settings.save()
        self.widget.apply_skin(skin_id)
        self._refresh_icon()
        if self.dialog is not None:
            self.dialog._reload_skins()

    def _pick_source(self, mode: str, app_id: str) -> None:
        self.settings.source_mode = mode
        self.settings.pinned_source = app_id
        self.settings.save()
        self.controller.set_source(mode, app_id)

    # ------------------------------------------------------------------ state

    def _on_state(self, state: PlayerState) -> None:
        self.widget.set_state(state)
        if state.has_track:
            source = friendly_source_name(state.app_id)
            mark = "▶" if state.playing else "❚❚"
            tip = f"{mark} {state.title}"
            if state.artist:
                tip += f"\n{state.artist}"
            tip += f"\n{source}"
        else:
            tip = tr("tray.idle")
        self.tray.setToolTip(tip[:127])  # Windows tooltip limit

        if self.settings.hide_when_no_music:
            if state.has_track:
                self._forced_visible = False
                if not self.widget.isVisible():
                    self.widget.show()
            elif self.widget.isVisible() and not self._forced_visible:
                self.widget.hide()

    def _on_failure(self, message: str) -> None:
        QMessageBox.critical(None, "Tunetop", tr("error.smtc", error=message))

    # ------------------------------------------------------------------ updates

    def _maybe_check_for_updates(self) -> None:
        if not self.settings.check_for_updates:
            return
        if self._offer_known_update():
            return  # an earlier run already found it; no point asking GitHub again
        if not check_is_due(self.settings.last_update_check):
            return
        self._update_checker = UpdateChecker()
        self._update_checker.available.connect(self._on_update_available)
        self._update_checker.up_to_date.connect(self._on_update_none)
        self._update_checker.start()

    def _offer_known_update(self) -> bool:
        """Report an update a previous run found, without waiting on the network."""
        known = self.settings.latest_known_version
        if not known or not is_newer(known, __version__):
            return False
        if known == self.settings.skipped_update_version:
            return False  # deliberately ignored; a fresh check may turn up a later one
        # The event loop is not running yet while the app is being constructed.
        QTimer.singleShot(
            0, lambda: offer_update(None, self.settings, ReleaseInfo(known, RELEASES_PAGE_URL))
        )
        return True

    def _on_update_available(self, release) -> None:
        self._record_check(release.version)
        if release.version == self.settings.skipped_update_version:
            return
        offer_update(None, self.settings, release)

    def _on_update_none(self) -> None:
        self._record_check("")

    def _record_check(self, latest: str) -> None:
        """Stamp a *completed* check, so a failed one is retried on the next launch."""
        self.settings.last_update_check = check_stamp()
        self.settings.latest_known_version = latest
        self.settings.save()

    # --------------------------------------------------------------- settings

    def show_settings(self) -> None:
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.hotkeys.unregister_all()  # so the capture field can see the keys
        self.dialog = SettingsDialog(self.settings, self.controller)
        self.dialog.setWindowIcon(self.app_icon())
        self.dialog.applied.connect(self._on_settings_applied)
        self.dialog.finished.connect(self._on_settings_closed)
        self.controller.refresh()
        self.dialog.show()

    def _on_settings_applied(self, hint: str) -> None:
        if hint == "language":
            set_language(self.settings.language)
            self.widget.set_state(self.controller.state)  # redraw placeholder strings
            self._reopen_settings()
            return
        if hint == "window":
            self.widget.refresh_window_flags()
        elif hint == "skin":
            self.widget.apply_skin(self.settings.skin)
            self._refresh_icon()
        elif hint == "layout":
            self.widget.apply_skin(self.settings.skin)
        elif hint == "source":
            self.controller.set_source(self.settings.source_mode, self.settings.pinned_source)
        elif hint == "visibility":
            if not self.settings.hide_when_no_music and not self.widget.isVisible():
                self.widget.show()
        self.widget.update()
        self._refresh_menu()

    def _reopen_settings(self) -> None:
        """Rebuild the settings window so its widgets pick up the new language."""
        dialog, self.dialog = self.dialog, None
        if dialog is not None:
            tab = dialog.current_tab()
            for signal in (dialog.applied, dialog.finished):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            dialog.close()
            dialog.deleteLater()
            self.show_settings()
            if self.dialog is not None:
                self.dialog.set_current_tab(tab)
        self._refresh_menu()

    def _on_settings_closed(self, _result: int = 0) -> None:
        self.dialog = None
        self._apply_hotkeys()
        self._refresh_menu()

    def _apply_hotkeys(self) -> None:
        failures = self.hotkeys.apply(self.settings.hotkeys, self.settings.hotkeys_enabled)
        if failures and self.settings.hotkeys_enabled:
            names = ", ".join(text for _, text in failures)
            self.tray.showMessage(
                "Tunetop",
                tr("tray.hotkeys_failed", names=names),
                QSystemTrayIcon.MessageIcon.Warning,
                6000,
            )

    # ------------------------------------------------------------------- quit

    def quit(self) -> None:
        self.widget.save_position()
        self.settings.save()
        self.app.quit()

    def _cleanup(self) -> None:
        try:
            self.hotkeys.shutdown()
        except Exception:
            pass
        self.controller.shutdown()
        self.tray.hide()
        self._server.close()


def run() -> int:
    # Before anything reads or creates the config folder.
    migrate_legacy_config()
    system.migrate_legacy_autostart()

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication(sys.argv)
    app.setApplicationName("Tunetop")
    app.setOrganizationName("Tunetop")
    app.setQuitOnLastWindowClosed(False)

    if another_instance_notified():
        return 0

    if not QSystemTrayIcon.isSystemTrayAvailable():
        set_language(Settings.load().language)
        QMessageBox.warning(None, "Tunetop", tr("tray.unavailable"))

    MusicControlApp(app)
    return app.exec()
