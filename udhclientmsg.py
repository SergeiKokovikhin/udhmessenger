#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Корпоративный мессенджер - клиентская часть (udhclientmsg).
ИСПРАВЛЕНО: Галочка "Показывать всех" и подсветка вкладок.
Добавлен телефон в подсказку при наведении на пользователя.
Добавлена система логирования.
Добавлена функция ответа на сообщение (reply).
Добавлена кнопка "История общений".
Добавлена массовая рассылка (всем пользователям и по отделам).
"""

import sys
import os
import json
import base64
import uuid
import configparser
import asyncio
import ssl
import socket
import platform
import traceback
import ctypes
import logging
import io
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta

# Фикс для Windows консоли - поддержка UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QTabWidget, QTextEdit, QLineEdit,
    QPushButton, QLabel, QDialog, QFormLayout, QMessageBox, QFileDialog,
    QSplitter, QTextBrowser, QCheckBox, QScrollArea, QFrame,
    QComboBox, QTreeWidget, QTreeWidgetItem, QMenu, QSystemTrayIcon,
    QGridLayout, QStatusBar, QInputDialog
)
from PySide6.QtCore import Qt, QByteArray, QBuffer, QIODevice, QUrl, QEvent, QTimer, QThread, Signal, QPoint, QSize
from PySide6.QtGui import QPixmap, QImage, QClipboard, QAction, QMouseEvent, QIcon, QPainter, QColor, QBrush, QTextCursor
import websockets
from cryptography.fernet import Fernet

# ----------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------
CONFIG_FILENAME = "udhclientmsg.ini"
SAVED_FILES_DIR = "saved_files"
SCREENSHOTS_DIR = "screenshots"
DEFAULT_SERVER_HOST = "udhmsg.hk-vostok.ru"
DEFAULT_SERVER_PORT = 8765
HISTORY_PAGE_SIZE = 50
HISTORY_DAYS = 3
ERROR_LOG = "udhclientmsg_error.log"

EMOJI_LIST = [
    "😊", "😂", "🤣", "❤️", "😍", "😒", "😘", "👍", "👎", "👏",
    "🙏", "🤝", "💪", "🔥", "🎉", "✨", "😢", "😭", "😅", "🤔",
    "😎", "🥳", "😇", "🤗", "😴", "🤤", "😱", "🤯", "😡", "🤬",
    "💀", "👻", "🎃", "🤖", "👽", "🐱", "🐶", "🦊", "🐻", "🐼",
    "🌸", "🌺", "🌞", "🌈", "⭐", "🌙", "☀️", "⛄", "🍕", "🍔",
]

# ----------------------------------------------------------------------
# Инициализация логирования
# ----------------------------------------------------------------------
def init_logging():
    """Инициализация системы логирования"""
    global logger
    
    logger = logging.getLogger('udhclientmsg')
    logger.setLevel(logging.DEBUG)
    
    # Читаем настройки из конфига
    config = configparser.ConfigParser()
    log_to_file = False
    log_level = logging.INFO
    
    if os.path.exists(CONFIG_FILENAME):
        try:
            config.read(CONFIG_FILENAME, encoding='utf-8')
            if config.has_section('logging'):
                log_enabled = config.get('logging', 'enabled', fallback='0')
                log_to_file = log_enabled.strip() == '1'
                
                level_str = config.get('logging', 'level', fallback='INFO')
                if level_str.upper() == 'DEBUG':
                    log_level = logging.DEBUG
                elif level_str.upper() == 'INFO':
                    log_level = logging.INFO
                elif level_str.upper() == 'WARNING':
                    log_level = logging.WARNING
                elif level_str.upper() == 'ERROR':
                    log_level = logging.ERROR
        except Exception as e:
            print(f"Ошибка чтения настроек логирования: {e}")
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    if log_to_file:
        # Логирование в файл с ротацией
        log_file = "udhclientmsg.log"
        handler = RotatingFileHandler(
            log_file, 
            maxBytes=5*1024*1024,  # 5 MB
            backupCount=3,
            encoding='utf-8'
        )
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        print(f"[LOG] Логирование в файл: {log_file} (уровень: {logging.getLevelName(log_level)})")
    else:
        # Логирование в консоль
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '[%(levelname)s] %(asctime)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        print("[LOG] Логирование в консоль (уровень: INFO)")
    
    # Добавляем отдельный обработчик для ошибок
    error_handler = RotatingFileHandler(
        "udhclientmsg_error.log",
        maxBytes=5*1024*1024,
        backupCount=3,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s\n%(exc_info)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    error_handler.setFormatter(error_formatter)
    logger.addHandler(error_handler)
    
    return logger

# Инициализируем логгер
logger = None

# ----------------------------------------------------------------------
# Логирование
# ----------------------------------------------------------------------
def log_info(message):
    if logger:
        logger.info(message)
    else:
        print(f"[INFO] {datetime.now().strftime('%H:%M:%S')} {message}")

def log_error(message):
    if logger:
        logger.error(message)
    else:
        print(f"[ERROR] {datetime.now().strftime('%H:%M:%S')} {message}")

def log_debug(message):
    if logger:
        logger.debug(message)
    else:
        print(f"[DEBUG] {datetime.now().strftime('%H:%M:%S')} {message}")

def log_warning(message):
    if logger:
        logger.warning(message)
    else:
        print(f"[WARNING] {datetime.now().strftime('%H:%M:%S')} {message}")

# ----------------------------------------------------------------------
# SettingsManager
# ----------------------------------------------------------------------
class SettingsManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.cipher = None
        self.load_config()

    def load_config(self):
        log_debug("Загрузка конфигурации")
        if not os.path.exists(CONFIG_FILENAME):
            log_info(f"Файл {CONFIG_FILENAME} не найден, создаю новый")
            self.config['server'] = {'host': DEFAULT_SERVER_HOST, 'port': str(DEFAULT_SERVER_PORT)}
            self.config['security'] = {'fernet_key': Fernet.generate_key().decode()}
            self.config['user'] = {}
            self.config['settings'] = {'show_all_users': 'true'}
            self.config['logging'] = {'enabled': '0', 'level': 'INFO'}
            self.save_config()
        else:
            self.config.read(CONFIG_FILENAME, encoding='utf-8')
            if not self.config.has_section('server'):
                self.config['server'] = {'host': DEFAULT_SERVER_HOST, 'port': str(DEFAULT_SERVER_PORT)}
            if not self.config.has_section('security'):
                self.config['security'] = {'fernet_key': Fernet.generate_key().decode()}
            if not self.config.has_section('user'):
                self.config['user'] = {}
            if not self.config.has_section('settings'):
                self.config['settings'] = {'show_all_users': 'true'}
            if not self.config.has_section('logging'):
                self.config['logging'] = {'enabled': '0', 'level': 'INFO'}
            self.save_config()

        key_str = self.config.get('security', 'fernet_key', fallback='')
        if not key_str:
            key_str = Fernet.generate_key().decode()
            self.config['security']['fernet_key'] = key_str
            self.save_config()
        self.cipher = Fernet(key_str.encode())

    def save_config(self):
        try:
            with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
                self.config.write(f)
                f.flush()
                os.fsync(f.fileno())
            log_debug("Конфигурация сохранена")
        except Exception as e:
            log_error(f"Ошибка сохранения: {e}")

    def get_server_host(self):
        return self.config.get('server', 'host', fallback=DEFAULT_SERVER_HOST)

    def get_server_port(self):
        try:
            return self.config.getint('server', 'port', fallback=DEFAULT_SERVER_PORT)
        except ValueError:
            return DEFAULT_SERVER_PORT

    def set_server(self, host, port):
        self.config['server']['host'] = host
        self.config['server']['port'] = str(port)
        self.save_config()

    def get_show_all_users(self):
        try:
            val = self.config.get('settings', 'show_all_users', fallback='true')
            result = val.strip().lower() == 'true'
            log_debug(f"show_all_users = {result}")
            return result
        except Exception as e:
            log_error(f"Ошибка get_show_all_users: {e}")
            return True

    def set_show_all_users(self, value):
        try:
            if isinstance(value, bool):
                str_val = 'true' if value else 'false'
            else:
                str_val = 'true' if value else 'false'
            self.config['settings']['show_all_users'] = str_val
            self.save_config()
            log_debug(f"show_all_users сохранено = {str_val}")
        except Exception as e:
            log_error(f"Ошибка set_show_all_users: {e}")

    def save_user_profile(self, email, password):
        try:
            data = {'email': email, 'password': password}
            encrypted = self.cipher.encrypt(json.dumps(data).encode())
            self.config['user']['profile'] = encrypted.decode()
            self.save_config()
            log_info(f"Профиль пользователя {email} сохранен")
            return True
        except Exception as e:
            log_error(f"Ошибка сохранения профиля: {e}")
            return False

    def get_user_profile(self):
        encrypted = self.config.get('user', 'profile', fallback='')
        if not encrypted:
            return None
        try:
            decrypted = self.cipher.decrypt(encrypted.encode())
            return json.loads(decrypted.decode())
        except Exception as e:
            log_error(f"Ошибка загрузки профиля: {e}")
            return None

    def clear_user_profile(self):
        if self.config.has_section('user'):
            self.config.remove_section('user')
        self.config['user'] = {}
        self.save_config()
        log_info("Профиль пользователя очищен")

    def get_allmessages_permission(self):
        """Проверка права на массовую рассылку всем пользователям"""
        try:
            val = self.config.get('settings', 'allmessages', fallback='0')
            return val.strip() == '1'
        except Exception as e:
            log_error(f"Ошибка get_allmessages_permission: {e}")
            return False


# ----------------------------------------------------------------------
# WebSocketClient
# ----------------------------------------------------------------------
class WebSocketClient(QThread):
    message_received = Signal(str)
    connection_changed = Signal(bool)

    def __init__(self, host, port):
        super().__init__()
        self.host = host
        self.port = port
        self.ws = None
        self.loop = None
        self.running = False

    def run(self):
        log_debug(f"WebSocketClient запущен для {self.host}:{self.port}")
        self.running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.connect_loop())
        self.loop.close()

    async def connect_loop(self):
        url = f"wss://{self.host}:{self.port}"
        log_debug(f"Подключение к {url}")
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        while self.running:
            try:
                async with websockets.connect(url, ssl=ssl_context, max_size=50*1024*1024) as ws:
                    self.ws = ws
                    log_info(f"WebSocket подключен к {self.host}:{self.port}")
                    self.connection_changed.emit(True)
                    await self.receive_messages(ws)
            except Exception as e:
                log_error(f"Ошибка подключения: {e}")
            self.ws = None
            self.connection_changed.emit(False)
            if self.running:
                log_debug("Переподключение через 30 секунд...")
                await asyncio.sleep(30)

    async def receive_messages(self, ws):
        async for message in ws:
            self.message_received.emit(message)

    def send_message(self, message):
        if self.ws and self.running and self.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.ws.send(message), self.loop)
                future.result(timeout=30)
                log_debug(f"Сообщение отправлено: {message[:100]}...")
                return True
            except Exception as e:
                log_error(f"Ошибка отправки: {e}")
                return False
        return False

    def stop(self):
        log_debug("Остановка WebSocketClient")
        self.running = False
        if self.ws and self.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
                future.result(timeout=5)
            except:
                pass
        self.wait(5000)


# ----------------------------------------------------------------------
# SettingsDialog
# ----------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, current_host, current_port, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки подключения")
        self.setModal(True)
        layout = QFormLayout(self)
        self.host_edit = QLineEdit(current_host)
        self.port_edit = QLineEdit(str(current_port))
        layout.addRow("Адрес сервера:", self.host_edit)
        layout.addRow("Порт:", self.port_edit)
        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def get_values(self):
        host = self.host_edit.text().strip()
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            port = DEFAULT_SERVER_PORT
        return host, port


# ----------------------------------------------------------------------
# ProfileDialog
# ----------------------------------------------------------------------
class ProfileDialog(QDialog):
    def __init__(self, email, nickname, first_name, last_name, phone, department_id, departments, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование профиля")
        self.setModal(True)
        layout = QFormLayout(self)
        self.email_edit = QLineEdit(email)
        self.nickname_edit = QLineEdit(nickname)
        self.first_name_edit = QLineEdit(first_name)
        self.last_name_edit = QLineEdit(last_name)
        self.phone_edit = QLineEdit(phone)
        self.department_combo = QComboBox()
        self.department_combo.addItem("Без отдела", None)
        for dept in departments:
            self.department_combo.addItem(dept["name"], dept["id"])
        if department_id:
            index = self.department_combo.findData(department_id)
            if index >= 0:
                self.department_combo.setCurrentIndex(index)
        layout.addRow("Email:", self.email_edit)
        layout.addRow("Никнейм:", self.nickname_edit)
        layout.addRow("Имя:", self.first_name_edit)
        layout.addRow("Фамилия:", self.last_name_edit)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Отдел:", self.department_combo)
        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def get_values(self):
        return (self.email_edit.text().strip(),
                self.nickname_edit.text().strip(),
                self.first_name_edit.text().strip(),
                self.last_name_edit.text().strip(),
                self.phone_edit.text().strip(),
                self.department_combo.currentData())


# ----------------------------------------------------------------------
# AuthDialog
# ----------------------------------------------------------------------
class AuthDialog(QDialog):
    def __init__(self, departments, saved_email=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Авторизация")
        self.setModal(True)
        self.resize(420, 550)
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        login_widget = QWidget()
        login_layout = QFormLayout(login_widget)
        self.login_email = QLineEdit()
        if saved_email:
            self.login_email.setText(saved_email)
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.Password)
        self.login_btn = QPushButton("Войти")
        self.login_btn.clicked.connect(self.login_requested)
        login_layout.addRow("Email:", self.login_email)
        login_layout.addRow("Пароль:", self.login_password)
        login_layout.addRow(self.login_btn)

        reg_widget = QWidget()
        reg_layout = QFormLayout(reg_widget)
        self.reg_email = QLineEdit()
        self.reg_nickname = QLineEdit()
        self.reg_first_name = QLineEdit()
        self.reg_last_name = QLineEdit()
        self.reg_phone = QLineEdit()
        self.reg_department = QComboBox()
        self.reg_department.addItem("Без отдела", None)
        for dept in departments:
            self.reg_department.addItem(dept["name"], dept["id"])
        self.reg_code = QLineEdit()
        self.reg_code.setPlaceholderText("6-значный код")
        self.reg_password = QLineEdit()
        self.reg_password.setEchoMode(QLineEdit.Password)
        self.reg_send_code_btn = QPushButton("Отправить код")
        self.reg_confirm_btn = QPushButton("Зарегистрироваться")
        self.reg_send_code_btn.clicked.connect(self.send_registration_code_requested)
        self.reg_confirm_btn.clicked.connect(self.confirm_registration_requested)
        reg_layout.addRow("Email:", self.reg_email)
        reg_layout.addRow("Никнейм:", self.reg_nickname)
        reg_layout.addRow("Имя:", self.reg_first_name)
        reg_layout.addRow("Фамилия:", self.reg_last_name)
        reg_layout.addRow("Телефон:", self.reg_phone)
        reg_layout.addRow("Отдел:", self.reg_department)
        reg_layout.addRow(self.reg_send_code_btn)
        reg_layout.addRow("Код из email:", self.reg_code)
        reg_layout.addRow("Пароль (мин. 6 символов):", self.reg_password)
        reg_layout.addRow(self.reg_confirm_btn)

        self.tabs.addTab(login_widget, "Вход")
        self.tabs.addTab(reg_widget, "Регистрация")

        self.autologin_checkbox = QCheckBox("Автологин (не запрашивать пароль при следующем запуске)")
        layout.addWidget(self.autologin_checkbox)

        settings_btn = QPushButton("Настройки сервера")
        settings_btn.clicked.connect(self.open_settings_requested)
        layout.addWidget(settings_btn)

    def login_requested(self): pass
    def send_registration_code_requested(self): pass
    def confirm_registration_requested(self): pass
    def open_settings_requested(self): pass


# ----------------------------------------------------------------------
# ImageViewerDialog
# ----------------------------------------------------------------------
class ImageViewerDialog(QDialog):
    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Просмотр изображения")
        self.original_pixmap = pixmap
        self.scale_factor = 1.0
        self.resize(900, 700)
        
        layout = QVBoxLayout(self)
        
        toolbar = QHBoxLayout()
        
        zoom_out_btn = QPushButton("−")
        zoom_out_btn.setFixedSize(40, 40)
        zoom_out_btn.clicked.connect(self.zoom_out)
        
        zoom_in_btn = QPushButton("+")
        zoom_in_btn.setFixedSize(40, 40)
        zoom_in_btn.clicked.connect(self.zoom_in)
        
        fit_btn = QPushButton("По размеру окна")
        fit_btn.clicked.connect(self.fit_to_window)
        
        original_btn = QPushButton("Оригинал (100%)")
        original_btn.clicked.connect(self.original_size)
        
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.save_image)
        
        self.zoom_label = QLabel("100%")
        
        toolbar.addWidget(zoom_out_btn)
        toolbar.addWidget(zoom_in_btn)
        toolbar.addWidget(fit_btn)
        toolbar.addWidget(original_btn)
        toolbar.addWidget(save_btn)
        toolbar.addStretch()
        toolbar.addWidget(self.zoom_label)
        layout.addLayout(toolbar)
        
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.scroll.setWidget(self.image_label)
        layout.addWidget(self.scroll)
        
        self.update_image()

    def update_image(self):
        scaled = self.original_pixmap.scaled(
            int(self.original_pixmap.width() * self.scale_factor),
            int(self.original_pixmap.height() * self.scale_factor),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.image_label.setPixmap(scaled)
        self.image_label.adjustSize()
        self.zoom_label.setText(f"{int(self.scale_factor * 100)}%")

    def zoom_in(self):
        self.scale_factor = min(self.scale_factor * 1.25, 10.0)
        self.update_image()

    def zoom_out(self):
        self.scale_factor = max(self.scale_factor / 1.25, 0.1)
        self.update_image()

    def fit_to_window(self):
        available = self.scroll.size()
        scaled = self.original_pixmap.scaled(available, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.adjustSize()
        self.scale_factor = scaled.width() / self.original_pixmap.width()
        self.zoom_label.setText(f"{int(self.scale_factor * 100)}%")

    def original_size(self):
        self.scale_factor = 1.0
        self.update_image()

    def save_image(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить изображение", "image.png", "PNG (*.png);;JPEG (*.jpg);;Все файлы (*.*)"
        )
        if file_path:
            if self.original_pixmap.save(file_path):
                QMessageBox.information(self, "Сохранение", "Изображение сохранено")

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, '_resized'):
            self._resized = True
            QTimer.singleShot(100, self.fit_to_window)


# ----------------------------------------------------------------------
# MessageWidget
# ----------------------------------------------------------------------
class MessageWidget(QFrame):
    reply_requested = Signal(object)  # Сигнал для запроса ответа
    
    def __init__(self, text=None, image_pixmap=None, timestamp=None, is_outgoing=False, 
                 message_id=None, from_user_id=None, parent=None):
        super().__init__(parent)
        self.is_outgoing = is_outgoing
        self.image_pixmap = image_pixmap
        self.timestamp = timestamp
        self.text = text or ""
        self.message_id = message_id
        self.from_user_id = from_user_id
        self.text_label = None
        self.message_data = {
            'id': message_id,
            'from_user_id': from_user_id,
            'text': text,
            'timestamp': timestamp
        }

        self.setObjectName("MessageWidget")
        self.setStyleSheet("QFrame#MessageWidget { background-color: transparent; }")
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        if is_outgoing:
            self.layout.addStretch(1)
        self.bubble = QFrame()
        if is_outgoing:
            self.bubble.setStyleSheet("background-color: #dcf8c6; border-radius: 10px;")
        else:
            self.bubble.setStyleSheet("background-color: #ffffff; border-radius: 10px;")
        bubble_layout = QVBoxLayout(self.bubble)
        bubble_layout.setContentsMargins(10, 5, 10, 5)

        if text is not None:
            self.text_label = QLabel(text)
            self.text_label.setWordWrap(True)
            self.text_label.setStyleSheet("background: transparent; font-size: 14px;")
            self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.text_label.setContextMenuPolicy(Qt.CustomContextMenu)
            self.text_label.customContextMenuRequested.connect(self.show_context_menu)
            bubble_layout.addWidget(self.text_label)
        elif image_pixmap is not None:
            self.image_label = QLabel()
            self.image_label.setPixmap(image_pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.image_label.setCursor(Qt.PointingHandCursor)
            self.image_label.mousePressEvent = self.on_image_click
            bubble_layout.addWidget(self.image_label)

        if timestamp:
            time_str = self.format_time(timestamp)
            time_label = QLabel(time_str)
            time_label.setStyleSheet("color: gray; font-size: 10px;")
            bubble_layout.addWidget(time_label)

        self.layout.addWidget(self.bubble)
        if not is_outgoing:
            self.layout.addStretch(1)

    def format_time(self, timestamp):
        try:
            msg_dt = datetime.fromisoformat(timestamp)
            today = datetime.now().date()
            msg_date = msg_dt.date()
            if msg_date == today:
                return msg_dt.strftime("%H:%M")
            elif msg_date == today - timedelta(days=1):
                return f"Вчера {msg_dt.strftime('%H:%M')}"
            else:
                return msg_dt.strftime("%d.%m.%Y %H:%M")
        except:
            return timestamp

    def show_context_menu(self, pos):
        menu = QMenu(self)
        copy_action = menu.addAction("Копировать")
        copy_action.triggered.connect(self.copy_text)
        
        # Добавляем пункт "Ответить"
        reply_action = menu.addAction("Ответить")
        reply_action.triggered.connect(self.reply_to_message)
        
        menu.exec(self.text_label.mapToGlobal(pos))

    def copy_text(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text)

    def reply_to_message(self):
        """Отправка сигнала о запросе ответа на сообщение"""
        if self.message_data:
            self.reply_requested.emit(self.message_data)

    def on_image_click(self, event):
        if event.button() == Qt.LeftButton and self.image_pixmap:
            viewer = ImageViewerDialog(self.image_pixmap, self)
            viewer.exec()

    def highlight_text(self, query):
        if not self.text_label or not query:
            return False
        if query.lower() in self.text_label.text().lower():
            self.text_label.setStyleSheet("background-color: yellow; font-size: 14px;")
            return True
        return False

    def reset_highlight(self):
        if self.text_label:
            self.text_label.setStyleSheet("background: transparent; font-size: 14px;")


# ----------------------------------------------------------------------
# ChatTab
# ----------------------------------------------------------------------
class ChatTab(QWidget):
    def __init__(self, chat_id, display_name, chat_type, main_window, parent=None):
        super().__init__(parent)
        self.chat_id = chat_id
        self.display_name = display_name
        self.chat_type = chat_type
        self.main_window = main_window
        self.history_offset = 0
        self.loaded_message_ids = set()
        self.history_fully_loaded = False
        self.message_widgets = []
        self.search_results = []
        self.current_search_index = -1
        self.unread_count = 0
        self.reply_data = None  # Данные для ответа

        layout = QVBoxLayout(self)

        self.history_btn = QPushButton("Загрузить историю (3 дня)")
        self.history_btn.clicked.connect(self.load_history)
        layout.addWidget(self.history_btn)

        search_panel = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск в чате...")
        self.search_input.returnPressed.connect(self.search_next)
        self.search_prev_btn = QPushButton("<")
        self.search_prev_btn.setFixedWidth(40)
        self.search_prev_btn.clicked.connect(self.search_prev)
        self.search_next_btn = QPushButton(">")
        self.search_next_btn.setFixedWidth(40)
        self.search_next_btn.clicked.connect(self.search_next)
        self.search_count_label = QLabel("")
        self.clear_search_btn = QPushButton("X")
        self.clear_search_btn.setFixedWidth(40)
        self.clear_search_btn.clicked.connect(self.clear_search)
        search_panel.addWidget(self.search_input)
        search_panel.addWidget(self.search_prev_btn)
        search_panel.addWidget(self.search_next_btn)
        search_panel.addWidget(self.search_count_label)
        search_panel.addWidget(self.clear_search_btn)
        layout.addLayout(search_panel)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(Qt.AlignTop)
        self.scroll_layout.setSpacing(5)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        # Контейнер для цитаты ответа
        self.reply_container = QWidget()
        self.reply_container.setStyleSheet("""
            QWidget {
                background-color: #f0f0f0;
                border-left: 3px solid #0066cc;
                border-radius: 4px;
                padding: 5px;
                margin-bottom: 5px;
            }
        """)
        self.reply_container.hide()
        
        reply_layout = QVBoxLayout(self.reply_container)
        reply_layout.setContentsMargins(10, 5, 10, 5)
        
        # Метка с именем автора
        self.reply_author = QLabel("")
        self.reply_author.setStyleSheet("font-weight: bold; font-size: 12px; color: #0066cc;")
        reply_layout.addWidget(self.reply_author)
        
        # Метка с текстом цитаты
        self.reply_text = QLabel("")
        self.reply_text.setStyleSheet("font-size: 12px; color: #555555;")
        self.reply_text.setWordWrap(True)
        reply_layout.addWidget(self.reply_text)
        
        # Кнопка закрытия цитаты
        close_btn_layout = QHBoxLayout()
        close_btn_layout.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("border: none; color: red; font-weight: bold;")
        close_btn.clicked.connect(self.clear_reply)
        close_btn_layout.addWidget(close_btn)
        reply_layout.addLayout(close_btn_layout)
        
        # Добавляем контейнер в layout перед полем ввода
        layout.insertWidget(layout.indexOf(self.history_btn) + 5, self.reply_container)

        self.input_field = QTextEdit()
        self.input_field.setFixedHeight(60)
        self.input_field.installEventFilter(self)
        layout.addWidget(self.input_field)

        button_layout = QHBoxLayout()
        self.emoji_btn = QPushButton("😊")
        self.emoji_btn.setFixedSize(40, 40)
        self.emoji_btn.clicked.connect(self.show_emoji_panel)
        self.send_btn = QPushButton("Отправить")
        self.send_btn.clicked.connect(self.send_message)
        self.file_btn = QPushButton("Файл")
        self.file_btn.clicked.connect(self.send_file)
        button_layout.addWidget(self.emoji_btn)
        button_layout.addWidget(self.send_btn)
        button_layout.addWidget(self.file_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)

    def show_emoji_panel(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Эмодзи")
        grid = QGridLayout(dialog)
        for i, emoji in enumerate(EMOJI_LIST):
            btn = QPushButton(emoji)
            btn.setFixedSize(45, 45)
            btn.setStyleSheet("font-size: 24px;")
            btn.clicked.connect(lambda checked=False, e=emoji: self.insert_emoji_and_close(e, dialog))
            grid.addWidget(btn, i // 10, i % 10)
        dialog.exec()

    def insert_emoji_and_close(self, emoji, dialog):
        self.insert_emoji(emoji)
        dialog.accept()

    def insert_emoji(self, emoji):
        cursor = self.input_field.textCursor()
        cursor.insertText(emoji)
        self.input_field.setFocus()

    def set_reply(self, message_data):
        """Установка данных для ответа"""
        self.reply_data = message_data
        
        # Получаем имя отправителя
        sender_name = self.main_window.get_display_name_by_id(message_data.get('from_user_id'))
        if not sender_name:
            sender_name = "Пользователь"
        
        self.reply_author.setText(f"Ответ для {sender_name}:")
        self.reply_text.setText(message_data.get('text', '')[:200])
        self.reply_container.show()
        self.input_field.setFocus()

    def clear_reply(self):
        """Очистка данных ответа"""
        self.reply_data = None
        self.reply_container.hide()
        self.input_field.setFocus()

    def search_next(self):
        if not self.search_results:
            self.perform_search()
        if self.search_results:
            self.current_search_index = (self.current_search_index + 1) % len(self.search_results)
            self.highlight_search_result()

    def search_prev(self):
        if not self.search_results:
            self.perform_search()
        if self.search_results:
            self.current_search_index = (self.current_search_index - 1) % len(self.search_results)
            self.highlight_search_result()

    def perform_search(self):
        query = self.search_input.text().strip()
        if not query:
            return
        self.search_results = []
        for i in range(len(self.message_widgets) - 1, -1, -1):
            if query.lower() in self.message_widgets[i].text.lower():
                self.search_results.append(i)
        self.current_search_index = -1
        if self.search_results:
            self.search_count_label.setText(str(len(self.search_results)))
            self.search_next()
        else:
            self.search_count_label.setText("0")
            QMessageBox.information(self, "Поиск", "Ничего не найдено")

    def highlight_search_result(self):
        if not self.search_results:
            return
        for w in self.message_widgets:
            w.reset_highlight()
        idx = self.search_results[self.current_search_index]
        self.message_widgets[idx].highlight_text(self.search_input.text())
        self.scroll.verticalScrollBar().setValue(self.message_widgets[idx].y())
        self.search_count_label.setText(f"{self.current_search_index + 1}/{len(self.search_results)}")

    def clear_search(self):
        self.search_input.clear()
        for w in self.message_widgets:
            w.reset_highlight()
        self.search_results = []
        self.current_search_index = -1
        self.search_count_label.setText("")

    def eventFilter(self, obj, event):
        if obj == self.input_field and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ControlModifier:
                    self.input_field.insertPlainText("\n")
                else:
                    self.send_message()
                return True
            elif event.key() == Qt.Key_Escape:
                self.clear_reply()
                return True
            elif event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
                clipboard = QApplication.clipboard()
                image = clipboard.image()
                if not image.isNull():
                    self.main_window.send_image(self.chat_id, image)
                    return True
                text = clipboard.text()
                if text:
                    self.input_field.insertPlainText(text)
                    return True
        return super().eventFilter(obj, event)

    def send_message(self):
        text = self.input_field.toPlainText().strip()
        if text:
            reply_data = self.reply_data
            self.clear_reply()
            self.main_window.send_text_message(self.chat_id, text, reply_data)
            self.input_field.clear()

    def send_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            self.main_window.send_file(self.chat_id, file_path)

    def load_history(self):
        if not self.history_fully_loaded:
            self.main_window.request_history(self.chat_id, HISTORY_PAGE_SIZE, self.history_offset)

    def add_message(self, text=None, pixmap=None, timestamp=None, is_outgoing=False, message_id=None, from_user_id=None):
        if message_id and message_id in self.loaded_message_ids:
            return
        if message_id:
            self.loaded_message_ids.add(message_id)
        
        widget = MessageWidget(
            text=text, 
            image_pixmap=pixmap, 
            timestamp=timestamp, 
            is_outgoing=is_outgoing,
            message_id=message_id,
            from_user_id=from_user_id
        )
        # Подключаем сигнал для ответа
        widget.reply_requested.connect(self.set_reply)
        
        self.scroll_layout.addWidget(widget)
        self.message_widgets.append(widget)
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def add_file_message(self, file_name, file_path, is_outgoing=False):
        widget = QFrame()
        layout = QHBoxLayout(widget)
        if is_outgoing:
            layout.addStretch(1)
        btn = QPushButton(f"Файл: {file_name}")
        btn.clicked.connect(lambda: self.main_window.open_file_folder(file_path))
        layout.addWidget(btn)
        if not is_outgoing:
            layout.addStretch(1)
        self.scroll_layout.addWidget(widget)
        QTimer.singleShot(50, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def set_history_fully_loaded(self):
        self.history_fully_loaded = True
        self.history_btn.setText("История загружена")
        self.history_btn.setEnabled(False)


# ----------------------------------------------------------------------
# MainWindow
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        log_info("=== Инициализация клиента ===")
        self.computer_name = socket.gethostname()
        self.os_type = platform.system()
        self.setWindowTitle(f"Мессенджер - {self.computer_name}")
        self.resize(1000, 700)

        self.settings = SettingsManager()
        self.server_host = self.settings.get_server_host()
        self.server_port = self.settings.get_server_port()
        self.show_all_users = self.settings.get_show_all_users()
        log_info(f"Сервер: {self.server_host}:{self.server_port}")

        self.current_user_id = None
        self.current_user_email = None
        self.current_user_nickname = None
        self.current_user_first_name = None
        self.current_user_last_name = None
        self.current_user_phone = None
        self.current_user_department_id = None
        self.all_users = []
        self.departments = []
        self.chat_tabs = {}
        self.auto_login_pending = False
        self.auto_login_save = False
        self.departments_loaded = False
        self.tray_blink_timer = None
        self.tray_icon_visible = True
        self.tray_icon = None
        self.pending_login_password = ""
        self.user_search_query = ""
        self.connected = False
        self.selected_user_id = None
        self.last_notification_user_id = None
        self.last_notification_user_name = ""
        self._original_title = ""

        self.ws_client = None
        self.connect_websocket()
        self.init_ui()
        self.init_tray()

        saved_profile = self.settings.get_user_profile()
        if saved_profile:
            log_info("Найден сохраненный профиль, автологин включен")
            self.auto_login_pending = True
            self.saved_profile = saved_profile
        else:
            log_info("Сохраненный профиль не найден")
            self.show()
            QTimer.singleShot(1000, self.check_and_show_auth_dialog)

    def connect_websocket(self):
        log_info(f"Подключение к WebSocket {self.server_host}:{self.server_port}")
        if self.ws_client:
            self.ws_client.stop()
        self.ws_client = WebSocketClient(self.server_host, self.server_port)
        self.ws_client.message_received.connect(self.handle_ws_message)
        self.ws_client.connection_changed.connect(self.on_connection_changed)
        self.ws_client.start()

    def on_connection_changed(self, connected):
        log_info(f"Состояние подключения: {connected}, auto_login_pending={self.auto_login_pending}, current_user_id={self.current_user_id}")
        self.connected = connected
        if connected:
            self.status_label.setText("[OK] Связь с сервером активна")
            self.status_label.setStyleSheet("color: green; padding: 3px;")
            self.request_departments()
            
            # Автологин при первом подключении или переподключении
            if hasattr(self, 'saved_profile'):
                if self.current_user_id is None:
                    # Если пользователь не авторизован - выполняем автологин
                    log_info(f"Выполняю автологин для {self.saved_profile.get('email')}")
                    self.auto_login_save = True
                    self.send_login(
                        email=self.saved_profile.get('email'),
                        password=self.saved_profile.get('password')
                    )
            elif self.auto_login_pending and hasattr(self, 'saved_profile'):
                log_info(f"Выполняю автологин для {self.saved_profile.get('email')} (первый запуск)")
                self.auto_login_pending = False
                self.auto_login_save = True
                self.send_login(
                    email=self.saved_profile.get('email'),
                    password=self.saved_profile.get('password')
                )
        else:
            self.status_label.setText("[ERR] Связь с сервером потеряна")
            self.status_label.setStyleSheet("color: red; padding: 3px;")
            # Сбрасываем авторизацию при потере связи
            self.current_user_id = None

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.create_tray_icon())
        self.tray_icon.setToolTip(f"Мессенджер - {self.computer_name}")
        tray_menu = QMenu()
        show_action = tray_menu.addAction("Показать окно")
        show_action.triggered.connect(self.show_from_tray)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Выход")
        quit_action.triggered.connect(self.quit_application)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def create_tray_icon(self, blinking=False):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QBrush(QColor(255, 0, 0) if blinking else QColor(0, 120, 215)))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        painter.setPen(QColor(255, 255, 255))
        font = painter.font()
        font.setPointSize(24)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "M")
        painter.end()
        return QIcon(pixmap)

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_from_tray()
        elif reason == QSystemTrayIcon.Trigger:
            if self.last_notification_user_id:
                self.open_chat_tab_for_user(self.last_notification_user_id, self.last_notification_user_name)

    def show_from_tray(self):
        self.show()
        self.setWindowState(Qt.WindowActive)
        self.raise_()
        self.activateWindow()
        self.stop_blinking()

    def quit_application(self):
        reply = QMessageBox.question(self, "Выход", "Вы уверены?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.logout()

    def flash_window(self):
        try:
            if sys.platform == 'win32':
                hwnd = int(self.winId())
                ctypes.windll.user32.FlashWindow(hwnd, True)
                QTimer.singleShot(3000, lambda: ctypes.windll.user32.FlashWindow(hwnd, False))
        except Exception as e:
            log_error(f"Ошибка FlashWindow: {e}")

    def notify_new_message(self, from_user_id, content):
        """Показывает уведомление о новом сообщении."""
        sender = next((u for u in self.all_users if u["id"] == from_user_id), None)
        sender_name = self.get_display_name(sender) if sender else f"User{from_user_id}"
        
        self.last_notification_user_id = from_user_id
        self.last_notification_user_name = sender_name
        
        # Подсвечиваем вкладку СИНИМ цветом
        key = f"user_{from_user_id}"
        if key in self.chat_tabs:
            tab = self.chat_tabs[key]
            tab.unread_count += 1
            idx = self.tabs.indexOf(tab)
            if idx >= 0 and idx != self.tabs.currentIndex():
                self.tabs.setTabText(idx, f"[NEW] {tab.display_name} ({tab.unread_count})")
                self.tabs.tabBar().setTabTextColor(idx, QColor("#0066cc"))
        
        if not self.isVisible():
            self.start_blinking()
            self.tray_icon.showMessage(
                f"Сообщение от {sender_name}",
                content[:100],
                QSystemTrayIcon.Information,
                5000
            )
        elif not self.isActiveWindow():
            self.start_blinking()
            self.flash_window()
            if not self.windowTitle().startswith("[NEW]"):
                self._original_title = self.windowTitle()
                self.setWindowTitle(f"[NEW] Новое сообщение от {sender_name}")
            QTimer.singleShot(5000, self.reset_title_after_notification)

    def reset_title_after_notification(self):
        if self._original_title:
            self.setWindowTitle(self._original_title)
            self._original_title = ""
        elif self.current_user_id:
            self.setWindowTitle(f"Мессенджер - {self.current_user_nickname} ({self.current_user_email}) - {self.computer_name}")
        else:
            self.setWindowTitle(f"Мессенджер - {self.computer_name}")

    def start_blinking(self):
        if not self.tray_blink_timer:
            self.tray_blink_timer = QTimer(self)
            self.tray_blink_timer.timeout.connect(self.toggle_tray_icon)
            self.tray_blink_timer.start(500)
            self.tray_icon_visible = True

    def stop_blinking(self):
        if self.tray_blink_timer:
            self.tray_blink_timer.stop()
            self.tray_blink_timer = None
        self.tray_icon.setIcon(self.create_tray_icon(False))

    def toggle_tray_icon(self):
        self.tray_icon_visible = not self.tray_icon_visible
        self.tray_icon.setIcon(self.create_tray_icon(not self.tray_icon_visible))

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        right_panel = QVBoxLayout()
        right_panel.addWidget(QLabel("Пользователи:"))
        
        search_panel = QHBoxLayout()
        self.user_search_input = QLineEdit()
        self.user_search_input.setPlaceholderText("Поиск...")
        self.user_search_input.textChanged.connect(self.on_user_search_changed)
        self.clear_user_search_btn = QPushButton("X")
        self.clear_user_search_btn.setFixedWidth(40)
        self.clear_user_search_btn.clicked.connect(self.clear_user_search)
        search_panel.addWidget(self.user_search_input)
        search_panel.addWidget(self.clear_user_search_btn)
        right_panel.addLayout(search_panel)
        
        self.user_tree = QTreeWidget()
        self.user_tree.setHeaderHidden(True)
        self.user_tree.itemDoubleClicked.connect(self.on_tree_item_double_clicked)
        right_panel.addWidget(self.user_tree)
        
        # Горизонтальный контейнер для галочки и кнопки
        history_layout = QHBoxLayout()
        
        self.show_all_checkbox = QCheckBox("Показывать всех")
        self.show_all_checkbox.setChecked(self.show_all_users)
        self.show_all_checkbox.clicked.connect(self.on_show_all_clicked)
        history_layout.addWidget(self.show_all_checkbox)
        
        history_btn = QPushButton("История общений")
        history_btn.clicked.connect(self.show_history_dialog)
        history_btn.setFixedWidth(150)
        history_layout.addWidget(history_btn)
        history_layout.addStretch()
        
        right_panel.addLayout(history_layout)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.close_chat_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        splitter = QSplitter(Qt.Horizontal)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        splitter.addWidget(self.tabs)
        splitter.addWidget(right_widget)
        splitter.setSizes([650, 350])
        main_layout.addWidget(splitter)

        self.status_label = QLabel("[ERR] Связь с сервером потеряна")
        self.status_label.setStyleSheet("color: red; padding: 3px;")
        self.statusBar().addWidget(self.status_label)

        menubar = self.menuBar()
        file_menu = menubar.addMenu("Файл")
        logout_action = QAction("Выйти", self)
        logout_action.triggered.connect(self.quit_application)
        file_menu.addAction(logout_action)
        settings_action = QAction("Настройки сервера", self)
        settings_action.triggered.connect(self.open_settings)
        file_menu.addAction(settings_action)
        
        profile_menu = menubar.addMenu("Профиль")
        edit_profile_action = QAction("Редактировать профиль", self)
        edit_profile_action.triggered.connect(self.open_profile_dialog)
        profile_menu.addAction(edit_profile_action)

    def on_tab_changed(self, index):
        """Сбрасывает подсветку вкладки при её открытии."""
        if index < 0:
            return
        widget = self.tabs.widget(index)
        for key, tab in self.chat_tabs.items():
            if tab == widget:
                tab.unread_count = 0
                self.tabs.setTabText(index, tab.display_name)
                self.tabs.tabBar().setTabTextColor(index, QColor("#000000"))
                break

    def on_user_search_changed(self, text):
        self.user_search_query = text.strip().lower()
        self.refresh_user_tree()

    def on_show_all_changed(self, state):
        """Обработчик галочки. ИСПРАВЛЕНО."""
        if isinstance(state, bool):
            self.show_all_users = state
        else:
            self.show_all_users = (state == 2)
        self.settings.set_show_all_users(self.show_all_users)
        self.refresh_user_tree()
        log_debug(f"show_all_users = {self.show_all_users}, state={state}")

    def clear_user_search(self):
        self.user_search_input.clear()
        self.user_search_query = ""
        self.refresh_user_tree()

    def check_and_show_auth_dialog(self):
        if not self.departments_loaded:
            self.request_departments()
            QTimer.singleShot(1000, self.check_and_show_auth_dialog)
        else:
            self.show_auth_dialog()

    def show_auth_dialog(self, saved_email=None):
        self.show()
        self.auth_dialog = AuthDialog(self.departments, saved_email=saved_email, parent=self)
        self.auth_dialog.login_requested = lambda: self.send_login(
            self.auth_dialog.login_email.text().strip(),
            self.auth_dialog.login_password.text().strip())
        self.auth_dialog.send_registration_code_requested = lambda: self.send_registration_code()
        self.auth_dialog.confirm_registration_requested = lambda: self.confirm_registration()
        self.auth_dialog.open_settings_requested = lambda: self.open_settings()
        self.auth_dialog.exec()

    def open_settings(self):
        dlg = SettingsDialog(self.server_host, self.server_port, self)
        if dlg.exec() == QDialog.Accepted:
            host, port = dlg.get_values()
            log_info(f"Изменены настройки сервера: {host}:{port}")
            self.server_host = host
            self.server_port = port
            self.settings.set_server(host, port)
            self.connect_websocket()

    def open_profile_dialog(self):
        if self.current_user_id is None:
            QMessageBox.warning(self, "Ошибка", "Вы не авторизованы")
            return
        dlg = ProfileDialog(
            self.current_user_email,
            self.current_user_nickname,
            self.current_user_first_name or "",
            self.current_user_last_name or "",
            self.current_user_phone or "",
            self.current_user_department_id,
            self.departments,
            self
        )
        if dlg.exec() == QDialog.Accepted:
            email, nickname, first_name, last_name, phone, department_id = dlg.get_values()
            log_info(f"Обновление профиля: {email}")
            self.send_json({
                "type": "update_profile",
                "payload": {
                    "email": email,
                    "nickname": nickname,
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": phone,
                    "department_id": department_id
                }
            })

    def send_json(self, data):
        if self.ws_client:
            return self.ws_client.send_message(json.dumps(data))
        return False

    def request_departments(self):
        log_debug("Запрос списка отделов")
        self.send_json({"type": "get_departments", "payload": {}})

    def send_login(self, email, password):
        log_info(f"Отправка запроса на вход: {email}")
        if not email or not password:
            QMessageBox.warning(self, "Ошибка", "Введите email и пароль")
            return
        self.pending_login_password = password
        if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
            self.auto_login_save = self.auth_dialog.autologin_checkbox.isChecked()
        else:
            self.auto_login_save = True
        self.send_json({"type": "login_request", "payload": {
            "email": email, "password": password,
            "computer_name": self.computer_name,
            "os_type": self.os_type}})

    def send_registration_code(self):
        email = self.auth_dialog.reg_email.text().strip()
        nickname = self.auth_dialog.reg_nickname.text().strip()
        log_info(f"Запрос кода регистрации: {email}")
        if not email or not nickname:
            QMessageBox.warning(self, "Ошибка", "Email и никнейм обязательны")
            return
        self.send_json({"type": "register_request", "payload": {
            "email": email, "nickname": nickname,
            "first_name": self.auth_dialog.reg_first_name.text().strip(),
            "last_name": self.auth_dialog.reg_last_name.text().strip(),
            "phone": self.auth_dialog.reg_phone.text().strip(),
            "department_id": self.auth_dialog.reg_department.currentData(),
            "computer_name": self.computer_name,
            "os_type": self.os_type}})

    def confirm_registration(self):
        email = self.auth_dialog.reg_email.text().strip()
        code = self.auth_dialog.reg_code.text().strip()
        password = self.auth_dialog.reg_password.text().strip()
        log_info(f"Подтверждение регистрации: {email}")
        if not email or not code or not password:
            QMessageBox.warning(self, "Ошибка", "Введите email, код и пароль")
            return
        if len(password) < 6:
            QMessageBox.warning(self, "Ошибка", "Пароль должен быть не менее 6 символов")
            return
        self.reg_pending_password = password
        self.auto_login_save = self.auth_dialog.autologin_checkbox.isChecked()
        self.send_json({"type": "register_code", "payload": {
            "email": email, "code": code, "password": password}})

    def handle_ws_message(self, message):
        try:
            data = json.loads(message)
            log_debug(f"Получено сообщение: {data.get('type')}")
        except Exception as e:
            log_error(f"Ошибка парсинга JSON: {e}")
            return
        msg_type = data.get("type")
        payload = data.get("payload", {})

        if msg_type == "departments_list":
            self.departments = payload.get("departments", [])
            self.departments_loaded = True
            log_debug(f"Получен список отделов: {len(self.departments)}")
        elif msg_type in ["register_success", "login_success"]:
            log_info(f"УСПЕШНАЯ АВТОРИЗАЦИЯ! user_id={payload.get('user_id')}")
            self.current_user_id = payload["user_id"]
            self.current_user_email = payload["email"]
            self.current_user_nickname = payload["nickname"]
            self.current_user_first_name = payload.get("first_name", "")
            self.current_user_last_name = payload.get("last_name", "")
            self.current_user_phone = payload.get("phone", "")
            self.current_user_department_id = payload.get("department_id")
            self.user_settings = payload.get("settings", {})
            
            # Право allmessages хранится локально в INI файле
            # Не перезаписываем его при авторизации
            
            if self.auto_login_save:
                self.settings.save_user_profile(self.current_user_email, self.pending_login_password)
            if hasattr(self, 'auth_dialog') and self.auth_dialog.isVisible():
                self.auth_dialog.accept()
            self.after_login()
        elif msg_type == "login_error":
            log_warning(f"Ошибка входа: {payload.get('message', '')}")
            QMessageBox.warning(self, "Ошибка входа", payload.get("message", ""))
        elif msg_type == "register_error":
            log_warning(f"Ошибка регистрации: {payload.get('message', '')}")
            QMessageBox.warning(self, "Ошибка регистрации", payload.get("message", ""))
        elif msg_type == "profile_updated":
            log_info("Профиль обновлен")
            self.current_user_email = payload.get("email", self.current_user_email)
            self.current_user_nickname = payload.get("nickname", self.current_user_nickname)
            self.current_user_first_name = payload.get("first_name", self.current_user_first_name)
            self.current_user_last_name = payload.get("last_name", self.current_user_last_name)
            self.current_user_phone = payload.get("phone", self.current_user_phone)
            self.current_user_department_id = payload.get("department_id", self.current_user_department_id)
            self.setWindowTitle(f"Мессенджер - {self.current_user_nickname} ({self.current_user_email}) - {self.computer_name}")
            QMessageBox.information(self, "Профиль", "Профиль обновлён")
            self.refresh_user_tree()
        elif msg_type == "user_list_update":
            self.all_users = payload.get("users", [])
            log_debug(f"Обновлен список пользователей: {len(self.all_users)}")
            self.refresh_user_tree()
        elif msg_type == "chat_message_deliver":
            from_user_id = payload.get("from_user_id")
            content = payload.get("content")
            reply_to = payload.get("reply_to")
            log_debug(f"Получено сообщение от {from_user_id}")
            if from_user_id and content:
                self.display_incoming_message(from_user_id, content, reply_to)
                self.notify_new_message(from_user_id, content)
        elif msg_type == "file_transfer_deliver":
            from_user_id = payload.get("from_user_id")
            file_name = payload.get("file_name")
            file_data_b64 = payload.get("data")
            is_image = payload.get("is_image", False)
            log_debug(f"Получен файл от {from_user_id}: {file_name}")
            if from_user_id and file_name and file_data_b64:
                try:
                    file_data = base64.b64decode(file_data_b64)
                    self.handle_incoming_file(from_user_id, file_name, file_data, is_image)
                    if not is_image:
                        self.notify_new_message(from_user_id, f"Файл: {file_name}")
                except Exception as e:
                    log_error(f"Ошибка файла: {e}")
        elif msg_type == "history_response":
            self.handle_history_response(payload)
        elif msg_type == "history_users_response":
            users = payload.get("users", [])
            self.display_history_users(users)

    def after_login(self):
        log_info(f"Пользователь {self.current_user_nickname} ({self.current_user_email}) авторизован")
        self.setWindowTitle(f"Мессенджер - {self.current_user_nickname} ({self.current_user_email}) - {self.computer_name}")
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_user_tree(self):
        # Очищаем всё дерево
        self.user_tree.clear()
        
        # Создаем корневой элемент
        root_item = QTreeWidgetItem()
        root_item.setText(0, "Пользователи")
        root_item.setData(0, Qt.UserRole, "root_all")
        root_item.setData(0, Qt.UserRole + 1, -2)
        
        # Добавляем корневой элемент в дерево
        self.user_tree.addTopLevelItem(root_item)
        
        dept_items = {}
        for dept in self.departments:
            item = QTreeWidgetItem()
            item.setText(0, dept["name"])
            item.setData(0, Qt.UserRole, None)
            item.setData(0, Qt.UserRole + 1, dept["id"])
            root_item.addChild(item)
            dept_items[dept["id"]] = item
            
        no_dept = QTreeWidgetItem()
        no_dept.setText(0, "Без отдела")
        no_dept.setData(0, Qt.UserRole, None)
        no_dept.setData(0, Qt.UserRole + 1, -1)
        root_item.addChild(no_dept)
        
        for user in self.all_users:
            if user["id"] == self.current_user_id:
                continue
            
            if not self.show_all_users and not user.get("online", False):
                continue
            
            if self.user_search_query:
                first = (user.get("first_name") or "").lower()
                last = (user.get("last_name") or "").lower()
                nickname = (user.get("nickname") or "").lower()
                email = (user.get("email") or "").lower()
                if (self.user_search_query not in first and
                    self.user_search_query not in last and
                    self.user_search_query not in nickname and
                    self.user_search_query not in email):
                    continue
            
            display = self.get_display_name(user)
            item = QTreeWidgetItem()
            item.setText(0, display)
            item.setData(0, Qt.UserRole, f"user_{user['id']}")
            
            os_type = user.get("os_type") or "Неизвестно"
            tooltip = f"Имя: {user.get('first_name', '')} {user.get('last_name', '')}\n"
            tooltip += f"Никнейм: {user.get('nickname', '')}\n"
            tooltip += f"Email: {user.get('email', '')}\n"
            tooltip += f"Телефон: {user.get('phone', '')}\n"
            tooltip += f"Отдел: {user.get('department_name', 'Без отдела')}\n"
            tooltip += f"Компьютер: {user.get('computer_name', user.get('hostname', 'Неизвестно'))}\n"
            tooltip += f"ОС: {os_type}"
            item.setToolTip(0, tooltip)
            
            if not user.get("online", False):
                item.setForeground(0, Qt.gray)
            
            dept_id = user.get("department_id")
            if dept_id and dept_id in dept_items:
                dept_items[dept_id].addChild(item)
            else:
                no_dept.addChild(item)
        
        self.user_tree.expandAll()

    def get_display_name(self, user):
        first = user.get("first_name") or ""
        last = user.get("last_name") or ""
        if first or last:
            return f"{last} {first}".strip()
        return user.get("nickname") or user.get("email")

    def get_display_name_by_id(self, user_id):
        """Получение отображаемого имени пользователя по ID"""
        user = next((u for u in self.all_users if u["id"] == user_id), None)
        if user:
            return self.get_display_name(user)
        return None

    def on_tree_item_double_clicked(self, item, column):
        data = item.data(0, Qt.UserRole)
        item_text = item.text(0)
        
        # Корневой элемент "Пользователи"
        if data == "root_all":
            if not self.settings.get_allmessages_permission():
                QMessageBox.warning(
                    self,
                    "Доступ запрещен",
                    "У вас нет прав на массовую рассылку всем пользователям."
                )
                return
            self.show_broadcast_dialog(-2, "Всем пользователям")
            return
        
        # Пользователь
        if data and isinstance(data, str) and data.startswith("user_"):
            user_id = int(data.replace("user_", ""))
            user = next((u for u in self.all_users if u["id"] == user_id), None)
            if user:
                self.open_chat_tab_for_user(user_id, self.get_display_name(user))
            return
        
        # Отдел
        dept_id = item.data(0, Qt.UserRole + 1)
        if dept_id is not None:
            if dept_id == -1:
                self.show_broadcast_dialog(-1, "Без отдела")
                return
            elif dept_id >= 0:
                self.show_broadcast_dialog(dept_id, item_text)
                return

    def open_chat_tab_for_user(self, user_id, display_name):
        key = f"user_{user_id}"
        if key not in self.chat_tabs:
            tab = ChatTab(user_id, display_name, 'user', self)
            self.tabs.addTab(tab, display_name)
            self.chat_tabs[key] = tab
            self.request_history(user_id, HISTORY_PAGE_SIZE, 0)
        self.tabs.setCurrentWidget(self.chat_tabs[key])
        idx = self.tabs.indexOf(self.chat_tabs[key])
        self.on_tab_changed(idx)

    def close_chat_tab(self, index):
        widget = self.tabs.widget(index)
        for key, tab in list(self.chat_tabs.items()):
            if tab == widget:
                del self.chat_tabs[key]
                break
        self.tabs.removeTab(index)

    def request_history(self, other_user_id, limit=HISTORY_PAGE_SIZE, offset=0):
        since_date = (datetime.now() - timedelta(days=HISTORY_DAYS)).isoformat()
        self.send_json({"type": "history_request", "payload": {
            "other_user_id": other_user_id, "limit": limit, "offset": offset,
            "since": since_date}})

    def handle_history_response(self, payload):
        other_user_id = payload.get("other_user_id")
        messages = payload.get("messages", [])
        has_more = payload.get("has_more", False)
        key = f"user_{other_user_id}"
        tab = self.chat_tabs.get(key)
        if not tab:
            return
        
        # Сервер возвращает сообщения в порядке от новых к старым (ORDER BY id DESC)
        # Переворачиваем список для правильного отображения (старые сверху, новые снизу)
        for msg in reversed(messages):
            msg_type = msg.get("message_type")
            timestamp = msg.get("timestamp")
            is_outgoing = (msg.get("from_user_id") == self.current_user_id)
            message_id = msg.get("id")
            from_user_id = msg.get("from_user_id")
            reply_to = msg.get("reply_to")
            
            if msg_type == 'text':
                content = msg.get("content", "")
                display_text = content
                if reply_to:
                    sender_name = self.get_display_name_by_id(reply_to.get('from_user_id'))
                    if not sender_name:
                        sender_name = "Пользователь"
                    display_text = f"┌── {sender_name}:\n│ {reply_to.get('text', '')[:100]}\n└── {content}"
                
                tab.add_message(
                    text=display_text,
                    timestamp=timestamp,
                    is_outgoing=is_outgoing,
                    message_id=message_id,
                    from_user_id=from_user_id
                )
            elif msg_type == 'image':
                file_name = msg.get("file_name", "")
                img_path = os.path.join(os.getcwd(), SCREENSHOTS_DIR, file_name)
                if os.path.exists(img_path):
                    pixmap = QPixmap(img_path)
                    tab.add_message(
                        pixmap=pixmap,
                        timestamp=timestamp,
                        is_outgoing=is_outgoing,
                        message_id=message_id,
                        from_user_id=from_user_id
                    )
                else:
                    tab.add_message(
                        text=f"Изображение: {file_name}",
                        timestamp=timestamp,
                        is_outgoing=is_outgoing,
                        message_id=message_id,
                        from_user_id=from_user_id
                    )
            elif msg_type == 'file':
                tab.add_file_message(msg.get("file_name", "Файл"), "", is_outgoing=is_outgoing)
        
        tab.history_offset += len(messages)
        if not has_more:
            tab.set_history_fully_loaded()
        
        # Прокручиваем вниз к последнему сообщению
        QTimer.singleShot(100, lambda: tab.scroll.verticalScrollBar().setValue(
            tab.scroll.verticalScrollBar().maximum()))

    def send_text_message(self, to_user_id, text, reply_data=None):
        if not self.connected:
            QMessageBox.warning(self, "Ошибка", "Нет соединения с сервером")
            return
        
        message_data = {
            "to_user_id": to_user_id,
            "from_user_id": self.current_user_id,
            "content": text,
            "timestamp": datetime.now().isoformat()
        }
        
        if reply_data:
            message_data["reply_to"] = {
                "message_id": reply_data.get('id'),
                "from_user_id": reply_data.get('from_user_id'),
                "text": reply_data.get('text', '')
            }
        
        log_debug(f"Отправка сообщения пользователю {to_user_id}")
        message = {"type": "chat_message", "payload": message_data}
        self.send_json(message)
        
        tab = self.chat_tabs.get(f"user_{to_user_id}")
        if tab:
            display_text = text
            if reply_data:
                sender_name = self.get_display_name_by_id(reply_data.get('from_user_id'))
                if not sender_name:
                    sender_name = "Пользователь"
                display_text = f"┌── {sender_name}:\n│ {reply_data.get('text', '')[:100]}\n└── {text}"
            
            tab.add_message(
                text=display_text,
                timestamp=message_data["timestamp"],
                is_outgoing=True,
                from_user_id=self.current_user_id
            )

    def send_file(self, to_user_id, file_path):
        if not self.connected:
            QMessageBox.warning(self, "Ошибка", "Нет соединения с сервером")
            return
        try:
            file_name = os.path.basename(file_path)
            is_image = file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))
            log_debug(f"Отправка файла {file_name} пользователю {to_user_id}")
            with open(file_path, 'rb') as f:
                file_data = f.read()
            b64_data = base64.b64encode(file_data).decode()
            message = {"type": "file_transfer", "payload": {
                "to_user_id": to_user_id, "from_user_id": self.current_user_id,
                "file_name": file_name, "data": b64_data, "is_image": is_image,
                "timestamp": datetime.now().isoformat()}}
            self.send_json(message)
            tab = self.chat_tabs.get(f"user_{to_user_id}")
            if tab:
                if is_image:
                    pixmap = QPixmap(file_path)
                    tab.add_message(pixmap=pixmap, timestamp=message["payload"]["timestamp"], is_outgoing=True)
                else:
                    tab.add_file_message(file_name, file_path, is_outgoing=True)
        except Exception as e:
            log_error(f"Ошибка отправки файла: {e}")

    def send_image(self, to_user_id, image: QImage):
        if not self.connected:
            QMessageBox.warning(self, "Ошибка", "Нет соединения с сервером")
            return
        try:
            log_debug(f"Отправка изображения пользователю {to_user_id}")
            pixmap = QPixmap.fromImage(image)
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.WriteOnly)
            pixmap.save(buffer, "PNG")
            b64_data = base64.b64encode(bytes(byte_array)).decode()
            file_name = f"image_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            
            screenshots_dir = os.path.join(os.getcwd(), SCREENSHOTS_DIR)
            os.makedirs(screenshots_dir, exist_ok=True)
            img_path = os.path.join(screenshots_dir, file_name)
            pixmap.save(img_path)
            
            message = {"type": "file_transfer", "payload": {
                "to_user_id": to_user_id, "from_user_id": self.current_user_id,
                "file_name": file_name, "data": b64_data, "is_image": True,
                "timestamp": datetime.now().isoformat()}}
            self.send_json(message)
            
            tab = self.chat_tabs.get(f"user_{to_user_id}")
            if tab:
                tab.add_message(pixmap=pixmap, timestamp=message["payload"]["timestamp"], is_outgoing=True)
        except Exception as e:
            log_error(f"Ошибка отправки изображения: {e}")

    def display_incoming_message(self, from_user_id, text, reply_to=None):
        key = f"user_{from_user_id}"
        if key not in self.chat_tabs:
            user = next((u for u in self.all_users if u["id"] == from_user_id), None)
            if user:
                self.open_chat_tab_for_user(from_user_id, self.get_display_name(user))
        
        tab = self.chat_tabs.get(key)
        if tab:
            display_text = text
            if reply_to:
                sender_name = self.get_display_name_by_id(reply_to.get('from_user_id'))
                if not sender_name:
                    sender_name = "Пользователь"
                display_text = f"┌── {sender_name}:\n│ {reply_to.get('text', '')[:100]}\n└── {text}"
            
            tab.add_message(
                text=display_text,
                timestamp=datetime.now().isoformat(),
                is_outgoing=False,
                from_user_id=from_user_id
            )

    def handle_incoming_file(self, from_user_id, file_name, file_data, is_image):
        key = f"user_{from_user_id}"
        if key not in self.chat_tabs:
            user = next((u for u in self.all_users if u["id"] == from_user_id), None)
            if user:
                self.open_chat_tab_for_user(from_user_id, self.get_display_name(user))
        tab = self.chat_tabs.get(key)
        if tab:
            if is_image:
                pixmap = QPixmap()
                pixmap.loadFromData(file_data)
                screenshots_dir = os.path.join(os.getcwd(), SCREENSHOTS_DIR)
                os.makedirs(screenshots_dir, exist_ok=True)
                img_path = os.path.join(screenshots_dir, file_name)
                pixmap.save(img_path)
                tab.add_message(pixmap=pixmap, timestamp=datetime.now().isoformat(), is_outgoing=False)
            else:
                save_dir = os.path.join(os.getcwd(), SAVED_FILES_DIR)
                os.makedirs(save_dir, exist_ok=True)
                file_path = os.path.join(save_dir, file_name)
                with open(file_path, 'wb') as f:
                    f.write(file_data)
                tab.add_file_message(file_name, file_path, is_outgoing=False)

    def open_file_folder(self, file_path):
        if file_path and sys.platform == 'win32':
            os.system(f'explorer /select,"{file_path}"')

    # ------------------------------------------------------------------
    # История общений
    # ------------------------------------------------------------------
    def show_history_dialog(self):
        """Показ диалога выбора даты для истории общений"""
        dialog = QDialog(self)
        dialog.setWindowTitle("История общений")
        dialog.resize(450, 400)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Выбор даты
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("Дата:"))
        
        date_edit = QLineEdit()
        date_edit.setPlaceholderText("ДД.ММ.ГГГГ")
        date_edit.setText(datetime.now().strftime("%d.%m.%Y"))
        date_layout.addWidget(date_edit)
        
        load_btn = QPushButton("Загрузить")
        load_btn.clicked.connect(lambda: self.load_history_users(date_edit.text(), user_list, dialog))
        date_layout.addWidget(load_btn)
        
        layout.addLayout(date_layout)
        
        # Список пользователей
        user_list = QListWidget()
        user_list.itemDoubleClicked.connect(
            lambda item: self.open_history_chat(item.data(Qt.UserRole), date_edit.text(), dialog)
        )
        layout.addWidget(user_list)
        
        # Статус
        status_label = QLabel("Выберите дату и нажмите 'Загрузить'")
        status_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(status_label)
        
        dialog.exec()
    
    def load_history_users(self, date_str, user_list, dialog):
        """Загрузка пользователей, с которыми были диалоги в указанную дату"""
        try:
            # Парсим дату
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            date_from = date_obj.replace(hour=0, minute=0, second=0).isoformat()
            date_to = date_obj.replace(hour=23, minute=59, second=59).isoformat()
            
            user_list.clear()
            user_list.addItem("Загрузка...")
            
            # Запрашиваем список пользователей у сервера
            self.send_json({
                "type": "get_history_users",
                "payload": {
                    "date_from": date_from,
                    "date_to": date_to
                }
            })
            
            # Сохраняем дату для дальнейшего использования
            self._history_date = date_str
            self._history_dialog = dialog
            
        except ValueError:
            QMessageBox.warning(self, "Ошибка", "Неверный формат даты. Используйте ДД.ММ.ГГГГ")
    
    def open_history_chat(self, user_id, date_str, dialog):
        """Открытие чата с историей с начала дня"""
        dialog.accept()
        
        # Находим пользователя
        user = next((u for u in self.all_users if u["id"] == user_id), None)
        if not user:
            QMessageBox.warning(self, "Ошибка", "Пользователь не найден")
            return
        
        # Открываем чат с пользователем
        display_name = self.get_display_name(user)
        self.open_chat_tab_for_user(user_id, display_name)
        
        # Загружаем историю с начала дня
        try:
            date_obj = datetime.strptime(date_str, "%d.%m.%Y")
            since_date = date_obj.replace(hour=0, minute=0, second=0).isoformat()
            
            tab = self.chat_tabs.get(f"user_{user_id}")
            if tab:
                # Очищаем существующие сообщения
                tab.loaded_message_ids.clear()
                for widget in tab.message_widgets:
                    widget.deleteLater()
                tab.message_widgets.clear()
                tab.history_offset = 0
                tab.history_fully_loaded = False
                tab.history_btn.setText("Загрузить историю (3 дня)")
                tab.history_btn.setEnabled(True)
                
                # Загружаем историю с начала дня
                self.send_json({
                    "type": "history_request",
                    "payload": {
                        "other_user_id": user_id,
                        "limit": 1000,
                        "offset": 0,
                        "since": since_date
                    }
                })
                
        except ValueError:
            pass
    
    def display_history_users(self, users):
        """Отображение списка пользователей в диалоге истории"""
        if not hasattr(self, '_history_dialog'):
            return
        
        # Находим список в диалоге
        user_list = None
        for widget in self._history_dialog.findChildren(QListWidget):
            user_list = widget
            break
        
        if not user_list:
            return
        
        user_list.clear()
        
        if not users:
            user_list.addItem("В этот день диалогов не было")
            return
        
        for user_id in users:
            user = next((u for u in self.all_users if u["id"] == user_id), None)
            if user:
                item = QListWidgetItem(self.get_display_name(user))
                item.setData(Qt.UserRole, user_id)
                user_list.addItem(item)

    # ------------------------------------------------------------------
    # Массовая рассылка
    # ------------------------------------------------------------------
    def show_broadcast_dialog(self, dept_id, target_name):
        """Показ диалога массовой рассылки"""
        log_debug(f"show_broadcast_dialog: dept_id={dept_id}, target_name={target_name}")
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Массовая рассылка: {target_name}")
        dialog.resize(500, 300)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        
        # Информация
        info_label = QLabel(f"Рассылка для: {target_name}")
        info_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(info_label)
        
        # Количество получателей
        recipients = self.get_recipients(dept_id)
        count_label = QLabel(f"Получателей: {len(recipients)}")
        count_label.setStyleSheet("color: gray;")
        layout.addWidget(count_label)
        
        # Поле ввода
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("Введите сообщение для рассылки...")
        text_edit.setFixedHeight(150)
        layout.addWidget(text_edit)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        send_btn = QPushButton("Отправить")
        send_btn.setFixedHeight(40)
        send_btn.clicked.connect(lambda: self.send_broadcast(dialog, text_edit.toPlainText().strip(), dept_id, recipients))
        btn_layout.addWidget(send_btn)
        
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(dialog.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def get_recipients(self, dept_id):
        """Получение списка получателей для рассылки"""
        recipients = []
        
        # Приводим к int для надежности
        if dept_id is not None:
            dept_id = int(dept_id)
        
        log_debug(f"=== get_recipients: dept_id={dept_id} ===")
        
        for user in self.all_users:
            if user["id"] == self.current_user_id:
                continue  # Не отправляем себе
            
            user_dept_id = user.get("department_id")
            log_debug(f"Пользователь {user.get('nickname')}: dept_id={user_dept_id}, online={user.get('online')}")
            
            if dept_id == -2:  # Всем пользователям
                # Только активным (онлайн)
                if user.get("online", False):
                    recipients.append(user["id"])
            elif dept_id == -1:  # Без отдела
                if user.get("online", False) and user_dept_id is None:
                    recipients.append(user["id"])
            else:  # Конкретный отдел
                if user.get("online", False) and user_dept_id == dept_id:
                    recipients.append(user["id"])
        
        log_debug(f"Найдено {len(recipients)} получателей")
        return recipients
    
    def send_broadcast(self, dialog, text, dept_id, recipients):
        """Отправка массовой рассылки"""
        if not text:
            QMessageBox.warning(self, "Ошибка", "Введите текст сообщения")
            return
        
        if not recipients:
            QMessageBox.warning(self, "Ошибка", "Нет получателей для рассылки")
            return
        
        # Подтверждение
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Отправить сообщение {len(recipients)} получателям?\n\n{text[:100]}...",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Отправка каждому получателю
        success_count = 0
        for user_id in recipients:
            try:
                self.send_text_message(user_id, text)
                success_count += 1
            except Exception as e:
                log_error(f"Ошибка отправки пользователю {user_id}: {e}")
        
        dialog.accept()
        
        QMessageBox.information(
            self,
            "Рассылка завершена",
            f"Сообщение отправлено {success_count} из {len(recipients)} получателей"
        )

    def logout(self):
        log_info("Выход из системы")
        if not self.auto_login_save:
            self.settings.clear_user_profile()
        if self.tray_icon:
            self.tray_icon.hide()
        if self.ws_client:
            self.ws_client.stop()
        QApplication.quit()

    def closeEvent(self, event):
        if self.tray_icon and self.tray_icon.isVisible() and self.current_user_id is not None:
            self.hide()
            event.ignore()
        else:
            if self.ws_client:
                self.ws_client.stop()
            event.accept()
            QApplication.quit()

    def on_show_all_clicked(self, checked):
        self.show_all_users = checked
        self.settings.set_show_all_users(self.show_all_users)
        self.refresh_user_tree()
        log_debug(f"show_all_users = {self.show_all_users}")

# ----------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Инициализируем логирование до создания приложения
    logger = init_logging()
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())