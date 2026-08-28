#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Корпоративный мессенджер - Административная панель (udhadminmsg)
Версия 2.0
Подключение по WSS на порт admin_port из настроек сервера.
"""

import sys
import os
import json
import configparser
import asyncio
import ssl
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QTableWidget, QTableWidgetItem, QPushButton,
    QLabel, QDialog, QFormLayout, QLineEdit, QMessageBox,
    QComboBox, QHeaderView, QTreeWidget, QTreeWidgetItem,
    QInputDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
import websockets

# ----------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------
CONFIG_FILENAME = "udhservermsg.ini"
DEFAULT_HOST = "udhmsg.hk-vostok.ru"
DEFAULT_ADMIN_PORT = 8766

# ----------------------------------------------------------------------
# Инициализация логирования
# ----------------------------------------------------------------------
def init_logging():
    global logger
    logger = logging.getLogger('udhadminmsg')
    logger.setLevel(logging.DEBUG)
    
    config = configparser.ConfigParser()
    log_to_file = False
    
    if os.path.exists(CONFIG_FILENAME):
        try:
            config.read(CONFIG_FILENAME, encoding='utf-8')
            if config.has_section('logging'):
                log_to_file = config.get('logging', 'enabled', fallback='0').strip() == '1'
        except:
            pass
    
    logger.handlers.clear()
    
    if log_to_file:
        handler = RotatingFileHandler(
            "udhadminmsg.log",
            maxBytes=5*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        print("[LOG] Логирование в файл: udhadminmsg.log")
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('[%(levelname)s] %(asctime)s - %(message)s', datefmt='%H:%M:%S')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        print("[LOG] Логирование в консоль")
    
    return logger

logger = None

def log_info(msg):
    if logger:
        logger.info(msg)
    else:
        print(f"[INFO] {datetime.now().strftime('%H:%M:%S')} {msg}")

def log_error(msg):
    if logger:
        logger.error(msg)
    else:
        print(f"[ERROR] {datetime.now().strftime('%H:%M:%S')} {msg}")

def log_debug(msg):
    if logger:
        logger.debug(msg)
    else:
        print(f"[DEBUG] {datetime.now().strftime('%H:%M:%S')} {msg}")

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
        self.running = True
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.connect_loop())
        self.loop.close()

    async def connect_loop(self):
        url = f"wss://{self.host}:{self.port}"
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
                await asyncio.sleep(5)

    async def receive_messages(self, ws):
        async for message in ws:
            self.message_received.emit(message)

    def send_message(self, message):
        if self.ws and self.running and self.loop:
            try:
                future = asyncio.run_coroutine_threadsafe(self.ws.send(message), self.loop)
                future.result(timeout=30)
                return True
            except:
                return False
        return False

    def stop(self):
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
    def __init__(self, current_host, current_port, current_password="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки подключения")
        self.setModal(True)
        layout = QFormLayout(self)
        self.host_edit = QLineEdit(current_host)
        self.port_edit = QLineEdit(str(current_port))
        self.password_edit = QLineEdit(current_password)
        self.password_edit.setEchoMode(QLineEdit.Password)
        layout.addRow("Адрес сервера:", self.host_edit)
        layout.addRow("Порт (админ):", self.port_edit)
        layout.addRow("Пароль админки:", self.password_edit)
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
            port = DEFAULT_ADMIN_PORT
        return host, port, self.password_edit.text()

# ----------------------------------------------------------------------
# DepartmentDialog
# ----------------------------------------------------------------------
class DepartmentDialog(QDialog):
    def __init__(self, dept_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование отдела" if dept_data else "Создание отдела")
        self.setModal(True)
        layout = QFormLayout(self)
        
        self.name_edit = QLineEdit()
        if dept_data:
            self.name_edit.setText(dept_data.get("name", ""))
        
        layout.addRow("Название отдела:", self.name_edit)
        
        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def get_values(self):
        return {
            "name": self.name_edit.text().strip()
        }

# ----------------------------------------------------------------------
# UserDialog
# ----------------------------------------------------------------------
class UserDialog(QDialog):
    def __init__(self, departments, user_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование пользователя" if user_data else "Создание пользователя")
        self.setModal(True)
        self.resize(450, 550)
        layout = QFormLayout(self)
        
        self.email_edit = QLineEdit()
        self.nickname_edit = QLineEdit()
        self.first_name_edit = QLineEdit()
        self.last_name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.department_combo = QComboBox()
        self.department_combo.addItem("Без отдела", None)
        for dept in departments:
            self.department_combo.addItem(dept["name"], dept["id"])
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Оставьте пустым для генерации")
        
        if user_data:
            self.email_edit.setText(user_data.get("email", ""))
            self.nickname_edit.setText(user_data.get("nickname", ""))
            self.first_name_edit.setText(user_data.get("first_name", "") or "")
            self.last_name_edit.setText(user_data.get("last_name", "") or "")
            self.phone_edit.setText(user_data.get("phone", "") or "")
            if user_data.get("department_id"):
                index = self.department_combo.findData(user_data["department_id"])
                if index >= 0:
                    self.department_combo.setCurrentIndex(index)
            self.password_edit.setPlaceholderText("Оставьте пустым для сохранения текущего")
        
        layout.addRow("Email:", self.email_edit)
        layout.addRow("Никнейм:", self.nickname_edit)
        layout.addRow("Имя:", self.first_name_edit)
        layout.addRow("Фамилия:", self.last_name_edit)
        layout.addRow("Телефон:", self.phone_edit)
        layout.addRow("Отдел:", self.department_combo)
        layout.addRow("Пароль:", self.password_edit)
        
        buttons = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(save_btn)
        buttons.addWidget(cancel_btn)
        layout.addRow(buttons)

    def get_values(self):
        return {
            "email": self.email_edit.text().strip(),
            "nickname": self.nickname_edit.text().strip(),
            "first_name": self.first_name_edit.text().strip(),
            "last_name": self.last_name_edit.text().strip(),
            "phone": self.phone_edit.text().strip(),
            "department_id": self.department_combo.currentData(),
            "password": self.password_edit.text().strip()
        }

# ----------------------------------------------------------------------
# MainWindow
# ----------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Администрирование мессенджера")
        self.resize(1100, 750)
        
        # Читаем настройки сервера
        self.server_host = DEFAULT_HOST
        self.admin_port = DEFAULT_ADMIN_PORT
        self.admin_password = ""
        self.authenticated = False
        self.skip_password_prompt = False
        self.login_failed = False
        self.load_server_config()
        
        # WebSocket
        self.ws_client = None
        self.connected = False
        self.departments = []
        self.users = []
        
        self.init_ui()
        self.connect_websocket()
    
    def load_server_config(self):
        try:
            if os.path.exists(CONFIG_FILENAME):
                config = configparser.ConfigParser()
                config.read(CONFIG_FILENAME, encoding='utf-8')
                if config.has_section('server'):
                    self.admin_port = config.getint('server', 'admin_port', fallback=DEFAULT_ADMIN_PORT)
                if config.has_section('admin'):
                    self.server_host = config.get('admin', 'host', fallback=self.server_host).strip() or DEFAULT_HOST
                    self.admin_password = config.get('admin', 'password', fallback='')
            log_info(f"Загружены настройки: host={self.server_host}, порт админки={self.admin_port}")
        except Exception as e:
            log_error(f"Ошибка загрузки конфига: {e}")

    def save_server_config(self):
        try:
            config = configparser.ConfigParser()
            if os.path.exists(CONFIG_FILENAME):
                config.read(CONFIG_FILENAME, encoding='utf-8')
            if not config.has_section('server'):
                config.add_section('server')
            if not config.has_section('admin'):
                config.add_section('admin')
            config['server']['admin_port'] = str(self.admin_port)
            config['admin']['host'] = self.server_host
            config['admin']['password'] = self.admin_password
            with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
                config.write(f)
            log_info("Настройки подключения сохранены")
        except Exception as e:
            log_error(f"Ошибка сохранения конфига: {e}")
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Статусная строка
        status_layout = QHBoxLayout()
        self.status_label = QLabel("🔴 Подключение к серверу...")
        self.status_label.setStyleSheet("padding: 5px;")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        
        settings_btn = QPushButton("⚙ Настройки сервера")
        settings_btn.clicked.connect(self.open_settings)
        status_layout.addWidget(settings_btn)
        
        refresh_btn = QPushButton("🔄 Обновить все")
        refresh_btn.clicked.connect(self.refresh_all)
        status_layout.addWidget(refresh_btn)
        
        main_layout.addLayout(status_layout)
        
        # Табы
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Вкладка "Отделы"
        self.dept_tab = QWidget()
        self.init_dept_tab()
        self.tabs.addTab(self.dept_tab, "📁 Отделы")
        
        # Вкладка "Пользователи"
        self.users_tab = QWidget()
        self.init_users_tab()
        self.tabs.addTab(self.users_tab, "👤 Пользователи")
        
        # Вкладка "Сообщения"
        self.messages_tab = QWidget()
        self.init_messages_tab()
        self.tabs.addTab(self.messages_tab, "💬 Сообщения")
    
    # ------------------------------------------------------------------
    # Вкладка "Отделы"
    # ------------------------------------------------------------------
    def init_dept_tab(self):
        layout = QVBoxLayout(self.dept_tab)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить отдел")
        add_btn.clicked.connect(self.add_department)
        btn_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("✏️ Редактировать выбранный")
        edit_btn.clicked.connect(self.edit_selected_department)
        btn_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("🗑 Удалить выбранный")
        delete_btn.clicked.connect(self.delete_selected_department)
        btn_layout.addWidget(delete_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Таблица отделов
        self.dept_table = QTableWidget()
        self.dept_table.setColumnCount(3)
        self.dept_table.setHorizontalHeaderLabels(["ID", "Название", "Создан"])
        self.dept_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.dept_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.dept_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.dept_table.setSortingEnabled(True)
        self.dept_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.dept_table)
    
    def update_dept_table(self):
        self.dept_table.setRowCount(0)
        for dept in self.departments:
            row = self.dept_table.rowCount()
            self.dept_table.insertRow(row)
            
            id_item = QTableWidgetItem(str(dept.get("id", "")))
            id_item.setData(Qt.UserRole, dept.get("id"))
            self.dept_table.setItem(row, 0, id_item)
            self.dept_table.setItem(row, 1, QTableWidgetItem(dept.get("name", "")))
            
            created_at = dept.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at = dt.strftime("%d.%m.%Y %H:%M")
                except:
                    pass
            self.dept_table.setItem(row, 2, QTableWidgetItem(created_at))
    
    def add_department(self):
        dlg = DepartmentDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_values()
            if data["name"]:
                self.send_json({
                    "type": "create_department",
                    "payload": data
                })
    
    def edit_selected_department(self):
        row = self.dept_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите отдел для редактирования")
            return
        
        id_item = self.dept_table.item(row, 0)
        dept_id = id_item.data(Qt.UserRole)
        dept = next((d for d in self.departments if d["id"] == dept_id), None)
        if not dept:
            return
        
        dlg = DepartmentDialog(dept, self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_values()
            data["id"] = dept_id
            self.send_json({
                "type": "update_department",
                "payload": data
            })
    
    def delete_selected_department(self):
        row = self.dept_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите отдел для удаления")
            return
        
        id_item = self.dept_table.item(row, 0)
        dept_id = id_item.data(Qt.UserRole)
        dept = next((d for d in self.departments if d["id"] == dept_id), None)
        if not dept:
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить отдел '{dept.get('name')}'?\nПользователи будут перемещены в 'Без отдела'.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.send_json({
                "type": "delete_department",
                "payload": {"id": dept_id}
            })
    
    # ------------------------------------------------------------------
    # Вкладка "Пользователи"
    # ------------------------------------------------------------------
    def init_users_tab(self):
        layout = QVBoxLayout(self.users_tab)
        
        # Кнопки управления
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Добавить пользователя")
        add_btn.clicked.connect(self.add_user)
        btn_layout.addWidget(add_btn)
        
        edit_btn = QPushButton("✏️ Редактировать выбранного")
        edit_btn.clicked.connect(self.edit_selected_user)
        btn_layout.addWidget(edit_btn)
        
        delete_btn = QPushButton("🗑 Удалить выбранного")
        delete_btn.clicked.connect(self.delete_selected_user)
        btn_layout.addWidget(delete_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # Таблица пользователей
        self.user_table = QTableWidget()
        self.user_table.setColumnCount(9)
        self.user_table.setHorizontalHeaderLabels([
            "ID", "Email", "Никнейм", "Имя", "Фамилия", "Телефон", "Отдел", "Создан", "Пароль"
        ])
        self.user_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.user_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.user_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.user_table.setSortingEnabled(True)
        self.user_table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.user_table)
    
    def update_user_table(self):
        self.user_table.setRowCount(0)
        for user in self.users:
            row = self.user_table.rowCount()
            self.user_table.insertRow(row)
            
            id_item = QTableWidgetItem(str(user.get("id", "")))
            id_item.setData(Qt.UserRole, user.get("id"))
            self.user_table.setItem(row, 0, id_item)
            self.user_table.setItem(row, 1, QTableWidgetItem(user.get("email", "")))
            self.user_table.setItem(row, 2, QTableWidgetItem(user.get("nickname", "")))
            self.user_table.setItem(row, 3, QTableWidgetItem(user.get("first_name", "") or ""))
            self.user_table.setItem(row, 4, QTableWidgetItem(user.get("last_name", "") or ""))
            self.user_table.setItem(row, 5, QTableWidgetItem(user.get("phone", "") or ""))
            
            dept_name = user.get("department_name") or "Без отдела"
            self.user_table.setItem(row, 6, QTableWidgetItem(dept_name))
            
            created_at = user.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at = dt.strftime("%d.%m.%Y %H:%M")
                except:
                    pass
            self.user_table.setItem(row, 7, QTableWidgetItem(created_at))
            self.user_table.setItem(row, 8, QTableWidgetItem("****"))
    
    def add_user(self):
        dlg = UserDialog(self.departments, parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_values()
            if not data["email"] or not data["nickname"]:
                QMessageBox.warning(self, "Ошибка", "Email и никнейм обязательны")
                return
            self.send_json({
                "type": "create_user",
                "payload": data
            })
    
    def edit_selected_user(self):
        row = self.user_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите пользователя для редактирования")
            return
        
        id_item = self.user_table.item(row, 0)
        user_id = id_item.data(Qt.UserRole)
        user = next((u for u in self.users if u["id"] == user_id), None)
        if not user:
            return
        
        dlg = UserDialog(self.departments, user, self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_values()
            data["id"] = user_id
            if not data.get("password"):
                data.pop("password", None)
            log_debug(f"Отправка update_user: id={user_id}")
            self.send_json({
                "type": "update_user",
                "payload": data
            })
    
    def delete_selected_user(self):
        row = self.user_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "Ошибка", "Выберите пользователя для удаления")
            return
        
        id_item = self.user_table.item(row, 0)
        user_id = id_item.data(Qt.UserRole)
        user = next((u for u in self.users if u["id"] == user_id), None)
        if not user:
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить пользователя {user.get('email')}?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.send_json({
                "type": "delete_user",
                "payload": {"id": user_id}
            })
    
    # ------------------------------------------------------------------
    # Вкладка "Сообщения"
    # ------------------------------------------------------------------
    def init_messages_tab(self):
        layout = QVBoxLayout(self.messages_tab)
        
        # Информация
        info_label = QLabel("История сообщений пользователей")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        layout.addWidget(info_label)
        
        # Дерево сообщений
        self.messages_tree = QTreeWidget()
        self.messages_tree.setHeaderLabels(["Отправитель / Сообщение", "Получатель", "Дата", "Тип"])
        self.messages_tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.messages_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.messages_tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.messages_tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.messages_tree)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Обновить сообщения")
        refresh_btn.clicked.connect(self.refresh_messages)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
    
    def refresh_messages(self):
        self.send_json({"type": "get_messages", "payload": {"limit": 1000}})
    
    def update_messages_tree(self, messages):
        self.messages_tree.clear()
        
        if not messages:
            item = QTreeWidgetItem(["Нет сообщений", "", "", ""])
            self.messages_tree.addTopLevelItem(item)
            return
        
        # Группируем по отправителям
        users_msgs = {}
        for msg in messages:
            from_user_id = msg.get("from_user_id")
            user = next((u for u in self.users if u["id"] == from_user_id), None)
            if user:
                user_name = f"{user.get('nickname', '')} ({user.get('email', '')})"
            else:
                user_name = f"User {from_user_id}"
            
            if from_user_id not in users_msgs:
                users_msgs[from_user_id] = {
                    "name": user_name,
                    "messages": []
                }
            users_msgs[from_user_id]["messages"].append(msg)
        
        for user_id, data in sorted(users_msgs.items()):
            user_item = QTreeWidgetItem([data["name"], "", "", ""])
            user_item.setData(0, Qt.UserRole, user_id)
            self.messages_tree.addTopLevelItem(user_item)
            
            for msg in sorted(data["messages"], key=lambda x: x.get("timestamp", ""), reverse=True):
                content = msg.get("content", "") or f"Файл: {msg.get('file_name', '')}"
                msg_type = msg.get("message_type", "text")
                timestamp = msg.get("timestamp", "")[:16] if msg.get("timestamp") else ""
                
                to_user_id = msg.get("to_user_id")
                to_user = next((u for u in self.users if u["id"] == to_user_id), None)
                to_name = to_user.get("nickname", "Unknown") if to_user else "Unknown"
                
                msg_text = content[:200] + ("..." if len(content) > 200 else "")
                msg_item = QTreeWidgetItem([msg_text, to_name, timestamp, msg_type])
                msg_item.setData(0, Qt.UserRole, msg.get("id"))
                
                if msg_type == "image":
                    msg_item.setForeground(3, QColor(0, 100, 200))
                elif msg_type == "file":
                    msg_item.setForeground(3, QColor(200, 100, 0))
                
                user_item.addChild(msg_item)
            user_item.setExpanded(True)
    
    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    def connect_websocket(self):
        if self.ws_client:
            self.ws_client.stop()
        self.ws_client = WebSocketClient(self.server_host, self.admin_port)
        self.ws_client.message_received.connect(self.handle_ws_message)
        self.ws_client.connection_changed.connect(self.on_connection_changed)
        self.ws_client.start()
    
    def on_connection_changed(self, connected):
        self.connected = connected
        self.authenticated = False
        if connected:
            self.status_label.setText("🟡 Подключено, выполняется вход...")
            self.status_label.setStyleSheet("color: #b8860b; padding: 5px;")
            self.try_admin_login()
        else:
            self.status_label.setText("🔴 Связь с сервером потеряна")
            self.status_label.setStyleSheet("color: red; padding: 5px;")

    def try_admin_login(self):
        if self.login_failed:
            return
        if not self.admin_password:
            if self.skip_password_prompt:
                return
            password, ok = QInputDialog.getText(
                self,
                "Вход в админ-панель",
                "Пароль (секция [admin] в udhservermsg.ini):",
                QLineEdit.Password
            )
            if not ok or not password.strip():
                self.skip_password_prompt = True
                self.status_label.setText("🔴 Нет пароля админки — откройте настройки")
                self.status_label.setStyleSheet("color: red; padding: 5px;")
                return
            self.admin_password = password.strip()
            self.save_server_config()
        self.send_json({
            "type": "admin_login",
            "payload": {"password": self.admin_password}
        })
    
    def open_settings(self):
        dlg = SettingsDialog(self.server_host, self.admin_port, self.admin_password, self)
        if dlg.exec() == QDialog.Accepted:
            host, port, password = dlg.get_values()
            self.server_host = host
            self.admin_port = port
            self.admin_password = password
            self.skip_password_prompt = False
            self.login_failed = False
            self.save_server_config()
            self.connect_websocket()
    
    def send_json(self, data):
        if data.get("type") != "admin_login" and not self.authenticated:
            log_debug(f"Пропуск {data.get('type')}: нет авторизации")
            return False
        if self.ws_client:
            try:
                return self.ws_client.send_message(json.dumps(data))
            except Exception as e:
                log_error(f"Ошибка отправки: {e}")
                return False
        return False
    
    def refresh_all(self):
        if not self.authenticated:
            return
        self.send_json({"type": "get_departments", "payload": {}})
        self.send_json({"type": "get_users", "payload": {}})
        self.send_json({"type": "get_messages", "payload": {"limit": 1000}})
    
    def handle_ws_message(self, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            payload = data.get("payload", {})
            log_debug(f"Получено: {msg_type}")

            if msg_type == "admin_login_success":
                self.authenticated = True
                self.login_failed = False
                self.status_label.setText("🟢 Связь с сервером активна (авторизован)")
                self.status_label.setStyleSheet("color: green; padding: 5px;")
                self.refresh_all()
                return
            if msg_type == "admin_login_error":
                self.authenticated = False
                self.login_failed = True
                self.status_label.setText("🔴 Ошибка входа в админ-панель")
                self.status_label.setStyleSheet("color: red; padding: 5px;")
                QMessageBox.warning(self, "Ошибка входа", payload.get("message", "Неверный пароль"))
                return
            
            if msg_type == "departments_list":
                self.departments = payload.get("departments", [])
                self.update_dept_table()
            elif msg_type == "users_list":
                self.users = payload.get("users", [])
                self.update_user_table()
            elif msg_type == "messages_list":
                self.update_messages_tree(payload.get("messages", []))
            elif msg_type in ["department_created", "department_updated", "department_deleted",
                            "user_created", "user_updated", "user_deleted"]:
                if msg_type == "user_created" and payload.get("password"):
                    QMessageBox.information(
                        self,
                        "Пользователь создан",
                        f"Пользователь создан.\nПароль: {payload.get('password')}"
                    )
                else:
                    msg_text = {
                        "department_created": "Отдел создан",
                        "department_updated": "Отдел обновлен",
                        "department_deleted": "Отдел удален",
                        "user_created": "Пользователь создан",
                        "user_updated": "Пользователь обновлен",
                        "user_deleted": "Пользователь удален"
                    }.get(msg_type, "Операция выполнена")
                    QMessageBox.information(self, "Успех", msg_text)
                self.refresh_all()
            elif msg_type == "error":
                err = payload.get("message", "Неизвестная ошибка")
                if not self.authenticated and "авторизац" in err.lower():
                    return
                QMessageBox.warning(self, "Ошибка", err)
        except Exception as e:
            log_error(f"Ошибка обработки сообщения: {e}")

# ----------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logger = init_logging()
    log_info("=== Запуск административной панели ===")
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())