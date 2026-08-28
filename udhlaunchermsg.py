#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Корпоративный мессенджер - Launcher (загрузчик клиента)
Версия: 1.0.0
Максимально упрощенная версия - только проверка обновлений и запуск клиента
"""

import sys
import os
import json
import base64
import configparser
import asyncio
import ssl
import socket
import subprocess
import shutil
import logging
import io
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

# Фикс для Windows консоли - поддержка UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QPushButton, QLabel, QDialog, QFormLayout, QLineEdit,
    QMessageBox, QProgressDialog
)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
import websockets
from cryptography.fernet import Fernet

# ----------------------------------------------------------------------
# Константы
# ----------------------------------------------------------------------
CONFIG_FILENAME = "udhclientmsg.ini"
DEFAULT_SERVER_HOST = "udhmsg.hk-vostok.ru"
DEFAULT_SERVER_PORT = 8765

# ----------------------------------------------------------------------
# Инициализация логирования
# ----------------------------------------------------------------------
def init_logging():
    global logger
    logger = logging.getLogger('udhlaunchermsg')
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
            "udhlaunchermsg.log",
            maxBytes=5*1024*1024,
            backupCount=3,
            encoding='utf-8'
        )
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        print("[LOG] Логирование в файл: udhlaunchermsg.log")
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
# SettingsManager - читает настройки из клиентского INI
# ----------------------------------------------------------------------
class SettingsManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.cipher = None
        self.load_config()

    def load_config(self):
        if os.path.exists(CONFIG_FILENAME):
            self.config.read(CONFIG_FILENAME, encoding='utf-8')
        else:
            log_info(f"Файл {CONFIG_FILENAME} не найден, создаю новый")
            self.config['server'] = {'host': DEFAULT_SERVER_HOST, 'port': str(DEFAULT_SERVER_PORT)}
            self.config['security'] = {'fernet_key': Fernet.generate_key().decode()}
            self.config['user'] = {}
            self.config['settings'] = {'show_all_users': 'true'}
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

    def get_user_profile(self):
        encrypted = self.config.get('user', 'profile', fallback='')
        if not encrypted:
            return None
        try:
            decrypted = self.cipher.decrypt(encrypted.encode())
            return json.loads(decrypted.decode())
        except:
            return None

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
        buttons = QVBoxLayout()
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
# LauncherMainWindow - Максимально упрощенный
# ----------------------------------------------------------------------
class LauncherMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Загрузчик мессенджера")
        self.resize(400, 300)
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        
        # Настройки
        self.settings = SettingsManager()
        self.server_host = self.settings.get_server_host()
        self.server_port = self.settings.get_server_port()
        
        # WebSocket
        self.ws_client = None
        self.connected = False
        self.update_checked = False
        self.download_completed = False
        
        # Статус обновления
        self.update_chunks = []
        self.latest_version = "1.0.0"
        self.update_progress = None
        
        # Инициализация
        self.init_ui()
        self.connect_websocket()
        
        # Показываем окно
        self.show()
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)
        
        # Заголовок
        title = QLabel("Корпоративный мессенджер")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # Статус
        self.status_label = QLabel("[WAIT] Подключение к серверу...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(self.status_label)
        
        # Информация о версии
        self.version_label = QLabel("Версия клиента: не установлен")
        self.version_label.setAlignment(Qt.AlignCenter)
        self.version_label.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(self.version_label)
        
        # Информация о сервере
        self.server_label = QLabel(f"Сервер: {self.server_host}:{self.server_port}")
        self.server_label.setAlignment(Qt.AlignCenter)
        self.server_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.server_label)
        
        layout.addStretch()
        
        # Кнопка настроек
        settings_btn = QPushButton("Настройки сервера")
        settings_btn.clicked.connect(self.open_settings)
        settings_btn.setFixedHeight(40)
        layout.addWidget(settings_btn)
        
        # Статусная строка
        self.statusBar().showMessage("Готов к работе")
    
    def connect_websocket(self):
        if self.ws_client:
            self.ws_client.stop()
        self.ws_client = WebSocketClient(self.server_host, self.server_port)
        self.ws_client.message_received.connect(self.handle_ws_message)
        self.ws_client.connection_changed.connect(self.on_connection_changed)
        self.ws_client.start()
    
    def on_connection_changed(self, connected):
        self.connected = connected
        if connected:
            self.status_label.setText("[OK] Подключено к серверу")
            self.status_label.setStyleSheet("color: green; font-size: 14px; padding: 10px;")
            self.statusBar().showMessage(f"Сервер: {self.server_host}:{self.server_port}")
            self.check_client_update()
        else:
            self.status_label.setText("[ERR] Нет связи с сервером")
            self.status_label.setStyleSheet("color: red; font-size: 14px; padding: 10px;")
            self.statusBar().showMessage("Ожидание подключения...")
            QTimer.singleShot(5000, self.connect_websocket)
    
    def open_settings(self):
        dlg = SettingsDialog(self.server_host, self.server_port, self)
        if dlg.exec() == QDialog.Accepted:
            host, port = dlg.get_values()
            self.server_host = host
            self.server_port = port
            self.settings.set_server(host, port)
            self.server_label.setText(f"Сервер: {host}:{port}")
            self.connect_websocket()
    
    def send_json(self, data):
        if self.ws_client:
            return self.ws_client.send_message(json.dumps(data))
        return False
    
    def handle_ws_message(self, message):
        try:
            data = json.loads(message)
            log_debug(f"Получено сообщение: {data.get('type')}")
        except:
            return
        
        msg_type = data.get("type")
        payload = data.get("payload", {})
        
        if msg_type == "version_response":
            self.handle_version_response(payload)
        elif msg_type == "download_chunk":
            self.handle_download_chunk(payload)
        elif msg_type == "download_complete":
            self.handle_download_complete(payload)
        elif msg_type == "download_error":
            log_error(f"Ошибка скачивания: {payload.get('message', '')}")
            self.status_label.setText("[ERR] Ошибка скачивания")
            QMessageBox.critical(self, "Ошибка", f"Ошибка скачивания:\n{payload.get('message', '')}")
            self.run_client()
    
    # ------------------------------------------------------------------
    # Логика обновления
    # ------------------------------------------------------------------
    def check_client_update(self):
        """Проверка обновления клиента"""
        self.update_checked = True
        
        # Читаем текущую версию клиента
        current_version = self.get_local_client_version()
        self.version_label.setText(f"Версия клиента: {current_version}")
        
        # Проверяем, есть ли клиент вообще
        client_path = os.path.join(os.path.dirname(sys.executable), "udhclientmsg.exe")
        if not os.path.exists(client_path):
            log_info("Клиент не найден, будет скачан")
            self.status_label.setText("[DOWNLOAD] Клиент не найден, скачивание...")
            self.status_label.setStyleSheet("color: orange; font-size: 14px; padding: 10px;")
            self.send_json({
                "type": "check_client_version",
                "payload": {
                    "current_version": "0.0.0",
                    "user_id": 0
                }
            })
            return
        
        # Отправляем запрос на сервер
        self.send_json({
            "type": "check_client_version",
            "payload": {
                "current_version": current_version,
                "user_id": 0
            }
        })
        
        log_info(f"Проверка версии: текущая={current_version}")
    
    def get_local_client_version(self):
        """Получение версии локального клиента"""
        app_dir = os.path.dirname(sys.executable)
        version_file = os.path.join(app_dir, "client_version.ini")
        
        if os.path.exists(version_file):
            try:
                with open(version_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith("version="):
                            return line.strip().split("=")[1]
            except:
                pass
        
        client_path = os.path.join(app_dir, "udhclientmsg.exe")
        if not os.path.exists(client_path):
            return "0.0.0"
        
        return "1.0.0"
    
    def handle_version_response(self, payload):
        """Обработка ответа с информацией о версии"""
        has_update = payload.get("has_update", False)
        self.latest_version = payload.get("latest_version", "1.0.0")
        
        if has_update:
            file_size = payload.get("file_size", 0)
            changelog = payload.get("changelog", "Новая версия")
            
            log_info(f"Доступно обновление до версии {self.latest_version}")
            
            self.status_label.setText(f"[DOWNLOAD] Скачивание обновления {self.latest_version}...")
            self.status_label.setStyleSheet("color: blue; font-size: 14px; padding: 10px;")
            
            self.download_client(self.latest_version)
        else:
            log_info("Клиент актуален")
            self.run_client()
    
    def download_client(self, version):
        """Скачивание клиента"""
        self.update_chunks = []
        self.download_completed = False
        
        self.update_progress = QProgressDialog(
            f"Скачивание обновления {version}...\nЭто может занять несколько секунд",
            None,
            0,
            100,
            self
        )
        self.update_progress.setWindowTitle("Обновление клиента")
        self.update_progress.setWindowFlags(Qt.WindowStaysOnTopHint)
        self.update_progress.setMinimumDuration(0)
        self.update_progress.show()
        
        self.send_json({
            "type": "download_client",
            "payload": {
                "version": version,
                "user_id": 0
            }
        })
    
    def handle_download_chunk(self, payload):
        """Обработка полученного чанка"""
        chunk_index = payload.get("chunk_index", 0)
        total_chunks = payload.get("total_chunks", 0)
        data_b64 = payload.get("data", "")
        is_last = payload.get("last", False)
        
        if not self.update_progress:
            return
        
        try:
            chunk_data = base64.b64decode(data_b64)
            self.update_chunks.append(chunk_data)
        except Exception as e:
            log_error(f"Ошибка декодирования чанка: {e}")
            self.status_label.setText("[ERR] Ошибка скачивания")
            self.update_progress.close()
            QMessageBox.critical(self, "Ошибка", f"Ошибка скачивания:\n{e}")
            self.run_client()
            return
        
        progress = int((chunk_index + 1) / total_chunks * 100)
        self.update_progress.setValue(progress)
        self.status_label.setText(f"[DOWNLOAD] Скачивание... {progress}%")
        
        if is_last:
            self.update_progress.setLabelText("Сохранение файла...")
            self.status_label.setText("[SAVE] Сохранение файла...")
            self.save_client_file()
    
    def handle_download_complete(self, payload):
        """Подтверждение завершения скачивания"""
        log_info("Получено подтверждение завершения скачивания")
    
    def save_client_file(self):
        """Сохранение скачанного клиента"""
        try:
            file_data = b''.join(self.update_chunks)
            if not file_data:
                raise Exception("Пустой файл")
            
            app_dir = os.path.dirname(sys.executable)
            
            old_client = os.path.join(app_dir, "udhclientmsg.exe")
            new_client = os.path.join(app_dir, "udhclientmsg_new.exe")
            backup_client = os.path.join(app_dir, "udhclientmsg_old.exe")
            
            log_info(f"Сохранение клиента, размер={len(file_data)} байт")
            
            with open(new_client, 'wb') as f:
                f.write(file_data)
            
            if os.path.exists(old_client):
                if os.path.exists(backup_client):
                    os.remove(backup_client)
                os.rename(old_client, backup_client)
                log_debug(f"Старый клиент сохранен как {backup_client}")
            
            os.rename(new_client, old_client)
            log_info("Новый клиент сохранен успешно")
            
            version_file = os.path.join(app_dir, "client_version.ini")
            with open(version_file, 'w', encoding='utf-8') as f:
                f.write(f"version={self.latest_version}")
            
            self.download_completed = True
            
            if self.update_progress:
                self.update_progress.setValue(100)
                self.update_progress.setLabelText("[OK] Обновление установлено!")
                self.update_progress.close()
            
            self.status_label.setText("[OK] Обновление установлено")
            self.status_label.setStyleSheet("color: green; font-size: 14px; padding: 10px;")
            
            # Запускаем клиент сразу
            self.run_client()
            
        except Exception as e:
            log_error(f"Ошибка сохранения клиента: {e}")
            self.status_label.setText("[ERR] Ошибка сохранения")
            if self.update_progress:
                self.update_progress.close()
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить обновление:\n{e}")
            self.run_client()
    
    def run_client(self):
        """Запуск клиента"""
        if self.update_progress:
            self.update_progress.close()
        
        client_path = os.path.join(os.path.dirname(sys.executable), "udhclientmsg.exe")
        
        if os.path.exists(client_path):
            try:
                log_info(f"Запуск клиента: {client_path}")
                
                if sys.platform == 'win32':
                    subprocess.Popen(
                        [client_path],
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                        close_fds=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL
                    )
                else:
                    subprocess.Popen(
                        [client_path],
                        start_new_session=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        stdin=subprocess.DEVNULL,
                        close_fds=True
                    )
                
                # Закрываем Launcher сразу после запуска клиента
                QApplication.quit()
                
            except Exception as e:
                log_error(f"Ошибка запуска клиента: {e}")
                QMessageBox.critical(self, "Ошибка", f"Не удалось запустить клиент:\n{e}")
                QApplication.quit()
        else:
            log_error("Файл клиента не найден")
            QMessageBox.critical(
                self,
                "Ошибка",
                "Файл клиента не найден!\n"
                "Пожалуйста, проверьте настройки сервера и перезапустите загрузчик."
            )
            self.status_label.setText("[ERR] Клиент не найден")
            self.status_label.setStyleSheet("color: red; font-size: 14px; padding: 10px;")
            self.statusBar().showMessage("Настройте сервер")
    
    def closeEvent(self, event):
        if self.ws_client:
            self.ws_client.stop()
        event.accept()

# ----------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logger = init_logging()
    log_info("=== Запуск Launcher ===")
    
    app = QApplication(sys.argv)
    window = LauncherMainWindow()
    sys.exit(app.exec())