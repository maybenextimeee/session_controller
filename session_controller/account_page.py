"""Аккаунт Session Controller и сохранённые записи."""

import base64
import json

from PySide6.QtCore import QByteArray, QBuffer, QEvent, QIODevice, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QStyle, QStyledItemDelegate, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from session_controller import dialogs, theme
from session_controller.account_limits import MAX_ENTRIES, MAX_FIELDS
from session_controller.i18n import tr
from session_controller.widgets import Segmented, SmoothScrollArea


def avatar_pixmap(encoded: str, size: int) -> QPixmap:
    canvas = QPixmap(size * 2, size * 2)
    canvas.setDevicePixelRatio(2)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    bounds = QRectF(0, 0, size, size)
    path = QPainterPath()
    path.addEllipse(bounds)
    painter.setClipPath(path)
    picture = QPixmap()
    try:
        loaded = bool(encoded) and picture.loadFromData(base64.b64decode(encoded, validate=True), "PNG")
    except ValueError:
        loaded = False
    if loaded:
        edge = min(picture.width(), picture.height())
        crop = QRectF((picture.width() - edge) / 2, (picture.height() - edge) / 2, edge, edge)
        painter.drawPixmap(bounds, picture, crop)
    else:
        palette = theme.current()
        painter.fillRect(bounds, QColor(palette.surface_2))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.muted))
        painter.drawEllipse(QRectF(size * .36, size * .20, size * .28, size * .28))
        painter.drawRoundedRect(QRectF(size * .24, size * .55, size * .52, size * .28), size / 8, size / 8)
    painter.end()
    return canvas


def line(placeholder: str, limit: int, secret: bool = False) -> QLineEdit:
    widget = QLineEdit()
    widget.setObjectName("accountInput")
    widget.setPlaceholderText(placeholder)
    widget.setMaxLength(limit)
    if secret:
        widget.setEchoMode(QLineEdit.EchoMode.Password)
    return widget


def button(label, handler):
    widget = QPushButton(label)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.clicked.connect(handler)
    return widget


def row(*widgets):
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    return layout


class EntryDelegate(QStyledItemDelegate):
    """Рисуем строку целиком: системная тема Windows добавляет рамку вокруг текста."""

    def paint(self, painter, option, index):
        palette = theme.current()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = option.rect.adjusted(1, 1, -1, -1)
        if selected or hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(palette.inverse_bg if selected else palette.surface_hover))
            painter.drawRoundedRect(bounds, 6, 6)
        painter.setFont(option.font)
        text_rect = bounds.adjusted(12, 0, -12, 0)
        number_width = option.fontMetrics.horizontalAdvance(str(index.model().rowCount())) + 8
        number_rect = QRect(text_rect)
        number_rect.setWidth(number_width)
        painter.setPen(QColor(palette.inverse_text if selected else palette.muted))
        painter.drawText(number_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         str(index.row() + 1))
        text_rect.setLeft(number_rect.right() + 7)
        painter.setPen(QColor(palette.inverse_text if selected else palette.text))
        label = option.fontMetrics.elidedText(index.data(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), 36))
        return size


class EntryEditor(QDialog):
    def __init__(self, parent, entry=None):
        super().__init__(parent)
        self.setWindowTitle("Редактировать запись" if entry else "Новая запись")
        self.setFixedSize(560, 340)
        self.fields = []
        self.result_data = None
        layout = QVBoxLayout(self)
        self.service = line("Название сервиса", 80)
        layout.addWidget(self.service)

        scroll = SmoothScrollArea()
        rows = QWidget()
        self.rows_layout = QVBoxLayout(rows)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(rows)
        layout.addWidget(scroll, 1)

        self.add_button = button("Добавить поле", lambda: self.add_field())
        layout.addWidget(self.add_button)
        self.error = QLabel()
        layout.addWidget(self.error)
        save_button = button("Сохранить", self.save)
        save_button.setObjectName("dialogPrimary")
        layout.addLayout(row(button("Отмена", self.reject), save_button))

        if entry:
            self.service.setText(entry["service"])
            for field in entry["fields"]:
                self._append_field(**field)
            if len(self.fields) > MAX_FIELDS:
                self.error.setText(tr("В записи может быть не больше 5 полей."))
        else:
            self.add_field("Логин")
            self.add_field("Пароль", secret=True)

    def add_field(self, label="", value="", secret=False):
        if len(self.fields) < MAX_FIELDS:
            self._append_field(label, value, secret)

    def _append_field(self, label="", value="", secret=False):
        name = line("Название поля", 80)
        name.setText(label)
        content = line("Значение", 1000, secret)
        content.setText(value)
        hidden = QCheckBox("Скрыто")
        hidden.setChecked(secret)
        hidden.toggled.connect(lambda checked: content.setEchoMode(
            QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal
        ))
        widget = QWidget()
        field = (name, content, hidden)

        def remove():
            self.fields.remove(field)
            self.rows_layout.removeWidget(widget)
            widget.hide()
            widget.deleteLater()
            self.add_button.setEnabled(len(self.fields) < MAX_FIELDS)
            if len(self.fields) <= MAX_FIELDS:
                self.error.clear()

        layout = row(name, content, hidden, button("Убрать", remove))
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setLayout(layout)
        self.rows_layout.addWidget(widget)
        self.fields.append(field)
        self.add_button.setEnabled(len(self.fields) < MAX_FIELDS)

    def save(self):
        if len(self.fields) > MAX_FIELDS:
            self.error.setText(tr("В записи может быть не больше 5 полей."))
            return
        service = self.service.text().strip()
        fields = [
            {"label": name.text().strip(), "value": value.text(), "secret": hidden.isChecked()}
            for name, value, hidden in self.fields
        ]
        if not service or not fields or any(not field["label"] for field in fields):
            self.error.setText("Укажи название сервиса и названия всех полей.")
            return
        self.result_data = {"service": service, "fields": fields}
        self.accept()


class AccountPage(QWidget):
    avatar_changed = Signal(str)

    def __init__(self, parent, address, storage):
        super().__init__(parent)
        self.address = address
        self.storage = storage
        self.network = QNetworkAccessManager(self)
        self.token = ""
        self.avatar_data = ""
        self.profile_avatar = ""
        self.reply = None
        self.generation = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.controls = QWidget()
        root.addWidget(self.controls, 1)
        controls = QVBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.picker = Segmented({"profile": "Профиль", "entries": "Пароли"}, "profile")
        self.picker.chosen.connect(self.tab_changed)
        controls.addWidget(self.picker)
        self.tabs = QStackedWidget()
        controls.addWidget(self.tabs)
        account = QWidget()
        account_layout = QVBoxLayout(account)
        profile_scroll = SmoothScrollArea()
        profile_scroll.setWidget(account)
        self.tabs.addWidget(profile_scroll)

        self.login_box = QFrame()
        self.login_box.setObjectName("panel")
        account_layout.addWidget(self.login_box)
        login_layout = QVBoxLayout(self.login_box)
        login_layout.setContentsMargins(18, 18, 18, 18)
        login_layout.setSpacing(8)
        auth = QFormLayout()
        login_layout.addLayout(auth)
        self.login = line("От 3 до 32 символов, латиница или цифры", 32)
        self.password = line("От 8 символов", 128, True)
        auth.addRow("Логин", self.login)
        auth.addRow("Пароль", self.password)
        self.confirm_password = line("Введи пароль ещё раз", 128, True)
        auth.addRow("Повтори пароль", self.confirm_password)
        self.auth_form = auth
        self.password.returnPressed.connect(self.submit_auth)
        self.confirm_password.returnPressed.connect(self.submit_auth)
        login_layout.addStretch(1)
        self.submit_button = button("Войти", self.submit_auth)
        self.submit_button.setObjectName("dialogPrimary")
        self.submit_button.setMinimumHeight(44)
        self.mode_button = button("Зарегистрироваться", self.toggle_auth_mode)
        login_layout.addWidget(self.submit_button)
        login_layout.addWidget(self.mode_button)

        self.pending_profile = QWidget()
        pending_layout = QVBoxLayout(self.pending_profile)
        pending_layout.addLayout(row(button("Повторить подключение", self.activate),
                                     button("Выйти", self.confirm_sign_out)))
        account_layout.addWidget(self.pending_profile)

        self.profile_box = QWidget()
        account_layout.addWidget(self.profile_box)
        account_layout.setContentsMargins(0, 0, 0, 0)
        account_layout.setSpacing(0)
        self.profile_stack = QStackedWidget(self.profile_box)
        profile_layout = QVBoxLayout(self.profile_box)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.addWidget(self.profile_stack)

        overview = QWidget()
        summary = QVBoxLayout(overview)
        summary.setContentsMargins(0, 0, 0, 0)
        summary.setSpacing(18)
        self.portrait = QLabel()
        self.portrait.setFixedSize(56, 56)
        self.identity = QLabel()
        self.identity.setObjectName("profileName")
        self.identity.setTextFormat(Qt.TextFormat.PlainText)
        self.identity.setWordWrap(True)
        identity_card = QFrame()
        identity_card.setObjectName("panel")
        hero = QHBoxLayout(identity_card)
        hero.setContentsMargins(16, 10, 16, 10)
        hero.setSpacing(12)
        hero.addWidget(self.portrait)
        hero.addWidget(self.identity, 1)
        summary.addWidget(identity_card)
        summary.addStretch(1)
        logout = button("Выйти из аккаунта", self.confirm_sign_out)
        logout.setObjectName("accountLogout")
        summary.addLayout(row(button("Редактировать профиль", self.edit_profile), logout))
        self.profile_stack.addWidget(overview)

        editor = QFrame()
        editor.setObjectName("panel")
        form = QVBoxLayout(editor)
        form.setContentsMargins(24, 18, 24, 18)
        form.setSpacing(10)
        title = QLabel("Редактирование профиля")
        title.setObjectName("cardTitle")
        form.addWidget(title)
        self.avatar = QLabel()
        self.avatar.setFixedSize(72, 72)
        photo = QHBoxLayout()
        photo.addWidget(self.avatar)
        photo.addWidget(button("Сменить фото", self.choose_avatar))
        photo.addWidget(button("Убрать фото", lambda: self.show_avatar("")))
        form.addLayout(photo)
        form.addWidget(QLabel("Имя"))
        self.name = line("Отображаемое имя", 80)
        form.addWidget(self.name)
        form.addStretch(1)
        save = button("Сохранить", self.save_profile)
        save.setObjectName("dialogPrimary")
        form.addLayout(row(button("Отмена", self.cancel_edit), save))
        self.profile_stack.addWidget(editor)

        entries = QFrame()
        entries.setObjectName("panel")
        entries_layout = QVBoxLayout(entries)
        self.entries_tab = self.tabs.addWidget(entries)
        self.entries = QListWidget()
        self.entries.setObjectName("accountEntries")
        self.entries.setItemDelegate(EntryDelegate(self.entries))
        self.entries.setMouseTracking(True)
        self.entries.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.entries.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.entries.setDragDropOverwriteMode(False)
        self.entries.model().rowsMoved.connect(self.entry_moved)
        QApplication.instance().installEventFilter(self)
        self.entries.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.entries.customContextMenuRequested.connect(self.entry_menu)
        self.entries.itemDoubleClicked.connect(lambda _item: self.edit_entry())
        entries_layout.addWidget(self.entries)
        self.create_button = button("Новая запись", self.new_entry)
        self.create_button.setObjectName("dialogPrimary")
        entries_layout.addLayout(row(self.create_button, button("Обновить", self.load_entries)))

        self.status = QLabel()
        self.status.setObjectName("small")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.status.hide()
        self.reset_profile()
        try:
            self.token = storage.load(self.server_url().toString())
        except ValueError:
            pass
        if self.token:
            self.login_box.hide()
            self.pending_profile.show()

    def server_url(self) -> QUrl:
        if not self.address:
            raise ValueError("Сервис аккаунтов недоступен. Попробуй позже.")
        url = QUrl(self.address, QUrl.ParsingMode.StrictMode)
        local = url.host() in {"localhost", "127.0.0.1", "::1"}
        if (not url.isValid() or not url.host() or "@" in url.authority()
                or url.hasQuery() or url.hasFragment() or url.path() not in {"", "/"}
                or (url.scheme() != "https" and not (local and url.scheme() == "http"))):
            raise ValueError("Не удалось подключиться к сервису аккаунтов.")
        url.setPath("")
        return url

    def request(self, method, path, done, data=None, *, revoke_token="", on_error=None,
                not_found_message=None):
        if self.reply is not None and not revoke_token:
            return
        try:
            url = self.server_url()
        except ValueError as error:
            if on_error:
                on_error()
            self.show_error(str(error))
            return
        url.setPath(path)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Accept", b"application/json")
        # У десктопного клиента нет браузерной сессии ngrok.
        if url.host().endswith((".ngrok-free.dev", ".ngrok-free.app")):
            request.setRawHeader(b"ngrok-skip-browser-warning", b"1")
        request.setTransferTimeout(10_000)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        token = revoke_token or self.token
        if token:
            request.setRawHeader(b"Authorization", f"Bearer {token}".encode("ascii"))
        body = QByteArray()
        if data is not None:
            request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
            body = QByteArray(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        elif method == "POST":
            request.setHeader(QNetworkRequest.KnownHeaders.ContentLengthHeader, 0)
        reply = self.network.sendCustomRequest(request, method.encode("ascii"), body)
        if revoke_token:
            reply.finished.connect(reply.deleteLater)
            return
        self.reply = reply
        generation = self.generation
        self.controls.setEnabled(False)
        self.status.clear()
        self.status.hide()

        def finish():
            code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            raw = bytes(reply.readAll())
            error = reply.error()
            reply.deleteLater()
            if self.reply is not reply or generation != self.generation:
                return
            self.reply = None
            self.controls.setEnabled(True)
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = None
            if code == 204 or (code is not None and 200 <= code < 300 and payload is not None):
                self.status.clear()
                done(payload)
                return
            if on_error:
                on_error()
            if self.token and code == 401 and not self.sign_out(revoke=False):
                return
            detail = payload.get("detail") if isinstance(payload, dict) else None
            if code == 404 and detail in ("Not Found", None):
                self.show_error(tr(not_found_message or "Сервер не нашёл запрошенный адрес."))
            elif isinstance(detail, str):
                self.show_error(tr(detail))
            elif code == 422 and path.startswith("/entries"):
                self.show_error("Проверь название сервиса и поля записи (от 1 до 5).")
            elif code == 422:
                self.show_error("Проверь поля формы. Логин — 3–32 символа, пароль — от 8.")
            elif code is not None and 200 <= code < 300:
                self.show_error("Сервис аккаунтов вернул неожиданный ответ. Попробуй позже.")
            elif code:
                self.show_error(f"Сервер ответил HTTP {code}. Попробуй снова позже.")
            elif error:
                self.show_error("Не удалось связаться с сервисом аккаунтов. Проверь интернет и попробуй снова.")
        reply.finished.connect(finish)

    def activate(self):
        if self.token:
            if self.profile_box.isHidden():
                self.request("GET", "/profile", self.show_profile)
            return

        def checked(data):
            if not isinstance(data, dict) or data.get("service") not in (
                "session-controller-accounts", "session-controller-demo",
            ):
                self.show_error("Сервис аккаунтов вернул неожиданный ответ.")

        self.request("GET", "/health", checked)

    def credentials(self):
        return {"login": self.login.text().strip(), "password": self.password.text()}

    def set_registration(self, enabled):
        self.registering = enabled
        self.confirm_password.clear()
        self.auth_form.setRowVisible(self.confirm_password, enabled)
        self.submit_button.setText("Создать аккаунт" if enabled else "Войти")
        self.mode_button.setText("Вернуться ко входу" if enabled else "Зарегистрироваться")
        self.status.clear()
        self.status.hide()

    def toggle_auth_mode(self):
        self.set_registration(not self.registering)

    def submit_auth(self):
        if not self.registering:
            self.sign_in()
            return
        if self.password.text() != self.confirm_password.text():
            self.show_error("Пароли не совпадают.")
            self.confirm_password.setFocus()
            self.confirm_password.selectAll()
            return

        def registered(_data):
            self.set_registration(False)
            self.sign_in()

        self.request("POST", "/register", registered, self.credentials())

    def sign_in(self):
        def signed_in(data):
            if not isinstance(data, dict) or not isinstance(data.get("token"), str):
                self.show_error("Сервер вернул неверный ответ при входе.")
                return
            self.token = data["token"]
            self.password.clear()
            self.login_box.hide()
            self.pending_profile.show()
            self.request("GET", "/profile", self.show_profile)
            try:
                self.storage.save(self.server_url().toString(), self.token)
            except (OSError, AttributeError):
                self.show_error("Вход выполнен, но Windows не смогла сохранить его для следующего запуска.")

        self.request("POST", "/login", signed_in, self.credentials())

    def sign_out(self, *, revoke=True) -> bool:
        try:
            self.storage.clear()
        except OSError:
            self.show_error("Не удалось удалить сохранённый вход. Попробуй выйти ещё раз.")
            return False
        token, self.token = self.token, ""
        self.generation += 1
        reply, self.reply = self.reply, None
        if reply is not None:
            reply.abort()
        self.controls.setEnabled(True)
        self.reset_profile()
        if token and revoke:
            self.request("POST", "/logout", None, revoke_token=token)
        self.status.clear()
        self.status.hide()
        return True

    def reset_profile(self):
        self.set_registration(False)
        self.password.clear()
        self.name.clear()
        self.identity.clear()
        self.profile_stack.setCurrentIndex(0)
        self.show_avatar("")
        self.profile_avatar = ""
        self.avatar_changed.emit("")
        self.show_entries([])
        self.tabs.setCurrentIndex(0)
        self.picker.buttons["profile"].setChecked(True)
        self.picker.buttons["entries"].setEnabled(False)
        self.profile_box.hide()
        self.pending_profile.hide()
        self.login_box.show()

    def show_profile(self, data):
        self.identity.setText(data["name"])
        self.profile_stack.setCurrentIndex(0)
        self.name.setText(data["name"])
        self.show_avatar(data["avatar"])
        self.profile_avatar = data["avatar"]
        self.portrait.setPixmap(avatar_pixmap(self.profile_avatar, self.portrait.width()))
        self.avatar_changed.emit(self.profile_avatar)
        self.login_box.hide()
        self.pending_profile.hide()
        self.profile_box.show()
        self.picker.buttons["entries"].setEnabled(True)

    def show_avatar(self, encoded):
        self.avatar_data = encoded
        self.avatar.setPixmap(avatar_pixmap(encoded, 72))

    def choose_avatar(self):
        picker = QFileDialog(self, "Выбрать фото")
        picker.setOption(QFileDialog.Option.DontUseNativeDialog)
        picker.setFileMode(QFileDialog.FileMode.ExistingFile)
        picker.setNameFilter("Изображения (*.png *.jpg *.jpeg)")
        picker.ensurePolished()
        picker.adjustSize()
        picker.setFixedSize(picker.size())
        picker.setSizeGripEnabled(False)
        accepted = picker.exec() == QDialog.DialogCode.Accepted
        files = picker.selectedFiles()
        picker.deleteLater()
        if not accepted or not files:
            return
        filename = files[0]
        reader = QImageReader(filename)
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > 25_000_000:
            self.show_error("Фото не читается или слишком большое.")
            return
        reader.setAutoTransform(True)
        image = reader.read().scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            self.show_error("Не удалось прочитать фото.")
            return
        self.show_avatar(base64.b64encode(bytes(buffer.data())).decode("ascii"))

    def show_error(self, message):
        self.status.setText(message)
        self.status.show()

    def edit_profile(self):
        self.name.setText(self.identity.text())
        self.show_avatar(self.profile_avatar)
        self.profile_stack.setCurrentIndex(1)
        self.name.setFocus()

    def cancel_edit(self):
        self.profile_stack.setCurrentIndex(0)
        self.status.hide()

    def confirm_sign_out(self):
        if dialogs.confirm(self, "Выйти из аккаунта?", "Для следующего входа понадобится пароль.",
                           "Выйти", dialogs.SIGN_OUT, dialogs.DANGER):
            self.sign_out()

    def save_profile(self):
        def saved(data):
            self.show_profile(data)

        self.request("PUT", "/profile", saved,
                     {"name": self.name.text().strip(), "avatar": self.avatar_data})

    def tab_changed(self, name):
        self.tabs.setCurrentIndex(self.entries_tab if name == "entries" else 0)
        if name == "entries" and self.token:
            self.load_entries()

    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Type.MouseButtonPress and self.entries.isVisible()
                and isinstance(watched, QWidget) and watched.window() is self.window()):
            viewport = self.entries.viewport()
            if watched is not viewport or self.entries.itemAt(event.position().toPoint()) is None:
                self.entries.clearSelection()
                self.entries.setCurrentRow(-1)
        return super().eventFilter(watched, event)

    def entry_menu(self, pos):
        item = self.entries.itemAt(pos)
        if item is None:
            return
        self.entries.setCurrentItem(item)
        menu = QMenu(self.entries)
        edit = menu.addAction("Редактировать")
        remove = menu.addAction("Удалить")
        chosen = menu.exec(self.entries.viewport().mapToGlobal(pos))
        menu.deleteLater()
        if chosen is edit:
            self.edit_entry()
        elif chosen is remove:
            self.delete_entry()

    def load_entries(self):
        self.request("GET", "/entries", self.show_entries)

    def show_entries(self, data):
        selected = self.entries.currentItem()
        selected_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.saved_entries = data
        has_room = len(data) < MAX_ENTRIES
        self.create_button.setEnabled(has_room)
        self.create_button.setToolTip("" if has_room else tr("Можно сохранить до 50 записей на аккаунт."))
        self.entries.clear()
        for entry in data:
            item = QListWidgetItem(entry["service"])
            item.setData(Qt.ItemDataRole.UserRole, entry["id"])
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
            self.entries.addItem(item)
            if entry["id"] == selected_id:
                self.entries.setCurrentItem(item)

    def entry_moved(self, _source, first, _last, _parent, destination):
        # Qt сообщает позицию вставки до извлечения перемещаемой строки.
        row_index = destination - 1 if first < destination else destination
        entry_id = self.entries.item(row_index).data(Qt.ItemDataRole.UserRole)
        following = self.entries.item(row_index + 1)
        before_id = following.data(Qt.ItemDataRole.UserRole) if following else None
        self.request("PUT", f"/entries/{entry_id}/position", self.show_entries,
                     {"before_id": before_id}, on_error=lambda: self.show_entries(self.saved_entries),
                     not_found_message="Сервер не поддерживает изменение порядка. Обнови и перезапусти сервер аккаунтов.")

    def open_editor(self, entry=None):
        generation = self.generation
        editor = EntryEditor(self, entry)
        accepted = editor.exec() == QDialog.DialogCode.Accepted
        data = editor.result_data
        editor.deleteLater()
        if accepted and self.token and generation == self.generation:
            method, path = ("PUT", "/entries/" + entry["id"]) if entry else ("POST", "/entries")
            self.request(method, path, lambda _data: self.load_entries(), data)

    def new_entry(self):
        self.open_editor()

    def edit_entry(self):
        item = self.entries.currentItem()
        if item:
            self.request("GET", "/entries/" + item.data(Qt.ItemDataRole.UserRole), self.open_editor)

    def delete_entry(self):
        item = self.entries.currentItem()
        if item and dialogs.confirm(
            self, "Удалить запись?", "Запись будет удалена с сервера.", "Удалить",
            dialogs.WARNING, dialogs.DANGER,
        ):
            self.request("DELETE", "/entries/" + item.data(Qt.ItemDataRole.UserRole),
                         lambda _data: self.load_entries())
