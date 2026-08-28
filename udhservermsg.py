#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Корпоративный мессенджер - серверная часть (udhservermsg).
ПОЛНАЯ ВЕРСИЯ СО ВСЕМИ ФУНКЦИЯМИ.
Админ-сервер работает по WSS.
Добавлена поддержка обновления клиента.
Добавлена система логирования.
Добавлена админ-панель.
"""

import asyncio
import json
import random
import string
import sqlite3
import datetime
import smtplib
import os
import configparser
import hashlib
import secrets
import socket
import base64
import ssl
import sys
import logging
from logging.handlers import RotatingFileHandler
from email.mime.text import MIMEText
from typing import Optional, Dict, Any

import websockets

# ----------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------
CONFIG_FILENAME = "udhservermsg.ini"
USERS_DB_FILENAME = "users.db"
MESSAGES_DB_FILENAME = "messages.db"

DEFAULT_PORT = 8765
ADMIN_PORT = 8766

DEFAULT_SMTP_SERVER = ""
DEFAULT_SMTP_PORT = 25
DEFAULT_SMTP_USERNAME = ""
DEFAULT_SMTP_PASSWORD = ""
DEFAULT_FROM_EMAIL = "noreply@hk-vostok.ru"

CODE_EXPIRATION_SECONDS = 600
MAX_WS_MESSAGE_SIZE = 50 * 1024 * 1024
ALLOWED_EMAIL_DOMAINS = {"uvadrev.ru", "hk-vostok.ru"}

SERVER_PORT = DEFAULT_PORT
ADMIN_PORT = ADMIN_PORT
ADMIN_PASSWORD = ""
SERVER_PRIVATE_KEY_PEM = ""
SERVER_PUBLIC_KEY_PEM = ""

SMTP_SERVER = DEFAULT_SMTP_SERVER
SMTP_PORT = DEFAULT_SMTP_PORT
SMTP_USERNAME = DEFAULT_SMTP_USERNAME
SMTP_PASSWORD = DEFAULT_SMTP_PASSWORD
FROM_EMAIL = DEFAULT_FROM_EMAIL

# Добавить для обновлений клиента
CLIENT_VERSIONS_DIR = "client_versions"
CLIENT_VERSIONS_FILE = os.path.join(CLIENT_VERSIONS_DIR, "versions.json")

# ----------------------------------------------------------------------
# Инициализация логирования
# ----------------------------------------------------------------------
def init_logging():
    """Инициализация системы логирования"""
    global logger
    
    logger = logging.getLogger('udhservermsg')
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
        log_file = "udhservermsg.log"
        handler = RotatingFileHandler(
            log_file, 
            maxBytes=10*1024*1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        print(f"📝 Логирование включено в файл: {log_file} (уровень: {logging.getLevelName(log_level)})")
    else:
        # Логирование в консоль (только INFO и выше)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            '[%(levelname)s] %(asctime)s - %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        print("📝 Логирование в консоль (уровень: INFO)")
    
    # Добавляем отдельный обработчик для ошибок
    error_handler = RotatingFileHandler(
        "udhservermsg_error.log",
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
# Загрузка конфигурации
# ----------------------------------------------------------------------
def load_config():
    global SERVER_PORT, ADMIN_PORT, ADMIN_PASSWORD, SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, FROM_EMAIL
    global SERVER_PRIVATE_KEY_PEM, SERVER_PUBLIC_KEY_PEM

    config = configparser.ConfigParser()
    config_created = False
    if os.path.exists(CONFIG_FILENAME):
        config.read(CONFIG_FILENAME, encoding='utf-8')
    else:
        config['server'] = {
            'port': str(DEFAULT_PORT),
            'admin_port': str(ADMIN_PORT),
            'private_key_file': '',
            'public_key_file': ''
        }
        config['smtp'] = {
            'server': DEFAULT_SMTP_SERVER,
            'port': str(DEFAULT_SMTP_PORT),
            'username': DEFAULT_SMTP_USERNAME,
            'password': DEFAULT_SMTP_PASSWORD,
            'from_email': DEFAULT_FROM_EMAIL
        }
        config['logging'] = {
            'enabled': '0',
            'level': 'INFO'
        }
        config['admin'] = {
            'password': secrets.token_urlsafe(16)
        }
        with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
            config.write(f)
        config_created = True
        print(f"Создан конфигурационный файл {CONFIG_FILENAME}")

    try:
        SERVER_PORT = config.getint('server', 'port', fallback=DEFAULT_PORT)
        ADMIN_PORT = config.getint('server', 'admin_port', fallback=ADMIN_PORT)
    except ValueError:
        SERVER_PORT = DEFAULT_PORT
        ADMIN_PORT = ADMIN_PORT

    # Загрузка ключей
    private_key_file = config.get('server', 'private_key_file', fallback='')
    if private_key_file and os.path.exists(private_key_file):
        try:
            with open(private_key_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
            if '-----BEGIN PRIVATE KEY-----' in file_content:
                start = file_content.index('-----BEGIN PRIVATE KEY-----')
                end = file_content.index('-----END PRIVATE KEY-----') + len('-----END PRIVATE KEY-----')
                SERVER_PRIVATE_KEY_PEM = file_content[start:end]
                logger.info(f"Приватный ключ загружен из {private_key_file}")
            else:
                logger.warning(f"{private_key_file} не содержит PEM-ключа")
        except Exception as e:
            logger.error(f"Ошибка загрузки приватного ключа: {e}")
    else:
        if private_key_file:
            logger.warning(f"Файл приватного ключа не найден: {private_key_file}")
        SERVER_PRIVATE_KEY_PEM = ""

    public_key_file = config.get('server', 'public_key_file', fallback='')
    if public_key_file and os.path.exists(public_key_file):
        try:
            with open(public_key_file, 'r', encoding='utf-8') as f:
                file_content = f.read()
            if '-----BEGIN CERTIFICATE-----' in file_content:
                start = file_content.index('-----BEGIN CERTIFICATE-----')
                end = file_content.index('-----END CERTIFICATE-----') + len('-----END CERTIFICATE-----')
                SERVER_PUBLIC_KEY_PEM = file_content[start:end]
                logger.info(f"Публичный ключ (сертификат) загружен из {public_key_file}")
            elif '-----BEGIN PUBLIC KEY-----' in file_content:
                start = file_content.index('-----BEGIN PUBLIC KEY-----')
                end = file_content.index('-----END PUBLIC KEY-----') + len('-----END PUBLIC KEY-----')
                SERVER_PUBLIC_KEY_PEM = file_content[start:end]
                logger.info(f"Публичный ключ загружен из {public_key_file}")
        except Exception as e:
            logger.error(f"Ошибка загрузки публичного ключа: {e}")
    else:
        if public_key_file:
            logger.warning(f"Файл публичного ключа не найден: {public_key_file}")
        SERVER_PUBLIC_KEY_PEM = ""

    # SMTP
    SMTP_SERVER = config.get('smtp', 'server', fallback=DEFAULT_SMTP_SERVER)
    try:
        SMTP_PORT = config.getint('smtp', 'port', fallback=DEFAULT_SMTP_PORT)
    except ValueError:
        SMTP_PORT = DEFAULT_SMTP_PORT
    SMTP_USERNAME = config.get('smtp', 'username', fallback=DEFAULT_SMTP_USERNAME)
    SMTP_PASSWORD = config.get('smtp', 'password', fallback=DEFAULT_SMTP_PASSWORD)
    FROM_EMAIL = config.get('smtp', 'from_email', fallback=DEFAULT_FROM_EMAIL)

    if not config.has_section('admin'):
        config.add_section('admin')
    admin_password = config.get('admin', 'password', fallback='').strip()
    if not admin_password:
        admin_password = secrets.token_urlsafe(16)
        config['admin']['password'] = admin_password
        with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
            config.write(f)
        log_warning(f"Задан пароль админ-панели в секции [admin] файла {CONFIG_FILENAME}")
    elif config_created:
        log_info(f"Пароль админ-панели записан в секцию [admin] файла {CONFIG_FILENAME}")
    ADMIN_PASSWORD = admin_password


def verify_admin_password(password):
    if not ADMIN_PASSWORD or password is None:
        return False
    return secrets.compare_digest(str(password), str(ADMIN_PASSWORD))

# ----------------------------------------------------------------------
# Логирование
# ----------------------------------------------------------------------
def log_info(message):
    if logger:
        logger.info(message)
    else:
        print(f"[INFO] {datetime.datetime.now().strftime('%H:%M:%S')} {message}")

def log_error(message):
    if logger:
        logger.error(message)
    else:
        print(f"[ERROR] {datetime.datetime.now().strftime('%H:%M:%S')} {message}")

def log_debug(message):
    if logger:
        logger.debug(message)
    else:
        print(f"[DEBUG] {datetime.datetime.now().strftime('%H:%M:%S')} {message}")

def log_warning(message):
    if logger:
        logger.warning(message)
    else:
        print(f"[WARNING] {datetime.datetime.now().strftime('%H:%M:%S')} {message}")

# ----------------------------------------------------------------------
# SSL-контекст
# ----------------------------------------------------------------------
def create_ssl_context():
    if not SERVER_PRIVATE_KEY_PEM or not SERVER_PUBLIC_KEY_PEM:
        log_warning("Ключи не загружены, SSL недоступен")
        return None
    try:
        with open("_temp_key.pem", 'w') as f:
            f.write(SERVER_PRIVATE_KEY_PEM)
        with open("_temp_cert.pem", 'w') as f:
            f.write(SERVER_PUBLIC_KEY_PEM)
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain("_temp_cert.pem", "_temp_key.pem")
        os.remove("_temp_key.pem")
        os.remove("_temp_cert.pem")
        log_info("SSL-контекст создан")
        return ssl_context
    except Exception as e:
        log_error(f"Ошибка создания SSL-контекста: {e}")
        return None

# ----------------------------------------------------------------------
# Инициализация БД
# ----------------------------------------------------------------------
def init_db():
    log_info("Инициализация базы данных...")
    # Пользователи
    conn = sqlite3.connect(USERS_DB_FILENAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            nickname TEXT UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            department_id INTEGER,
            password_hash TEXT NOT NULL,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_registrations (
            email TEXT PRIMARY KEY,
            nickname TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            phone TEXT,
            department_id INTEGER,
            code TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            settings_json TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    conn.commit()
    conn.close()
    log_info("База пользователей инициализирована")

    # Сообщения
    conn = sqlite3.connect(MESSAGES_DB_FILENAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user_id INTEGER NOT NULL,
            to_user_id INTEGER,
            to_department_id INTEGER,
            message_type TEXT NOT NULL DEFAULT 'text',
            content TEXT,
            file_name TEXT,
            timestamp TEXT,
            is_read INTEGER DEFAULT 0,
            reply_to TEXT
        )
    """)
    conn.commit()
    conn.close()
    log_info("База сообщений инициализирована")

    # Миграция - добавляем колонку reply_to если её нет (для существующих БД)
    conn = sqlite3.connect(MESSAGES_DB_FILENAME)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(messages)")
    columns = [col[1] for col in cur.fetchall()]
    if 'reply_to' not in columns:
        cur.execute("ALTER TABLE messages ADD COLUMN reply_to TEXT")
        log_info("Добавлена колонка reply_to в таблицу messages")
    conn.commit()
    conn.close()

    # Миграция пользователей
    conn = sqlite3.connect(USERS_DB_FILENAME)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cur.fetchall()]
    if 'password_hash' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
    if 'phone' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    if 'department_id' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN department_id INTEGER")
    conn.commit()
    conn.close()
    log_info("Миграция базы пользователей завершена")

# ----------------------------------------------------------------------
# Вспомогательные функции БД
# ----------------------------------------------------------------------
def db_execute(db_file, query, params=()):
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute(query, params)
    conn.commit()
    lastrowid = cur.lastrowid
    conn.close()
    return lastrowid

def db_fetchone(db_file, query, params=()):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def db_fetchall(db_file, query, params=()):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ----------------------------------------------------------------------
# Хэширование паролей
# ----------------------------------------------------------------------
def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + '$' + dk.hex()

def verify_password(password, stored_hash):
    try:
        salt_hex, hash_hex = stored_hash.split('$')
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return dk.hex() == hash_hex
    except:
        return False

# ----------------------------------------------------------------------
# Проверка email
# ----------------------------------------------------------------------
def is_email_allowed(email):
    if '@' not in email:
        return False
    domain = email.split('@')[-1].strip().lower()
    return domain in ALLOWED_EMAIL_DOMAINS

# ----------------------------------------------------------------------
# Отправка кода
# ----------------------------------------------------------------------
def generate_code(length=6):
    return ''.join(random.choices(string.digits, k=length))

def send_email_code(to_email, code, subject="Код подтверждения"):
    if SMTP_SERVER:
        try:
            msg = MIMEText(
                f"Регистрация в корпоративном мессенджере ООО Увадрев-Холдинг\n"
                f"Ваш код подтверждения: {code}\n"
                f"Код действителен {CODE_EXPIRATION_SECONDS // 60} минут."
            )
            msg["Subject"] = subject
            msg["From"] = FROM_EMAIL
            msg["To"] = to_email
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.ehlo()
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)
            log_info(f"Код {code} отправлен на {to_email}")
        except Exception as e:
            log_error(f"Ошибка отправки email: {e}. Код {code} для {to_email}")
    else:
        log_warning(f"SMTP не настроен. Код для {to_email}: {code}")

# ----------------------------------------------------------------------
# Активные клиенты
# ----------------------------------------------------------------------
connected_clients: Dict[int, Dict[str, Any]] = {}

def get_client_info(websocket):
    client_info = websocket.remote_address
    client_ip = client_info[0] if client_info else "Unknown"
    try:
        client_hostname = socket.gethostbyaddr(client_ip)[0]
    except:
        client_hostname = client_ip
    return {"hostname": client_hostname, "ip": client_ip}

async def broadcast_user_list():
    if not connected_clients:
        log_debug("Нет подключенных клиентов для broadcast")
        return
    users = db_fetchall(
        USERS_DB_FILENAME,
        """SELECT u.id, u.email, u.nickname, u.first_name, u.last_name, u.phone,
                  u.department_id, d.name as department_name
           FROM users u
           LEFT JOIN departments d ON u.department_id = d.id"""
    )
    online_ids = set(connected_clients.keys())
    user_list = []
    for u in users:
        user_info = connected_clients.get(u["id"], {})
        user_list.append({
            "id": u["id"],
            "email": u["email"],
            "nickname": u["nickname"],
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name"),
            "phone": u.get("phone"),
            "department_id": u.get("department_id"),
            "department_name": u.get("department_name"),
            "online": u["id"] in online_ids,
            "hostname": user_info.get("hostname", ""),
            "ip": user_info.get("ip", ""),
            "os_type": user_info.get("os_type", "Неизвестно"),
            "computer_name": user_info.get("hostname", "")
        })
    message = {"type": "user_list_update", "payload": {"users": user_list}}
    log_debug(f"Broadcast user_list: {len(user_list)} пользователей, {len(connected_clients)} онлайн")
    for user_data in connected_clients.values():
        try:
            await user_data["websocket"].send(json.dumps(message))
        except Exception as e:
            log_error(f"Ошибка отправки user_list: {e}")

async def broadcast_departments():
    departments = db_fetchall(USERS_DB_FILENAME, "SELECT id, name FROM departments ORDER BY name")
    message = {"type": "departments_update", "payload": {"departments": departments}}
    for user_data in connected_clients.values():
        try:
            await user_data["websocket"].send(json.dumps(message))
        except:
            pass

# ----------------------------------------------------------------------
# Настройки пользователей
# ----------------------------------------------------------------------
def get_user_settings(user_id):
    row = db_fetchone(USERS_DB_FILENAME, "SELECT settings_json FROM user_settings WHERE user_id = ?", (user_id,))
    if row:
        try:
            return json.loads(row["settings_json"])
        except:
            return {}
    return {}

def save_user_settings(user_id, settings):
    settings_json = json.dumps(settings)
    db_execute(
        USERS_DB_FILENAME,
        "INSERT OR REPLACE INTO user_settings (user_id, settings_json, updated_at) VALUES (?, ?, ?)",
        (user_id, settings_json, datetime.datetime.now().isoformat())
    )

# ----------------------------------------------------------------------
# Функции для обновления клиента
# ----------------------------------------------------------------------
def load_client_versions():
    """Загрузка информации о доступных версиях клиента"""
    try:
        # Создаем папку если её нет
        if not os.path.exists(CLIENT_VERSIONS_DIR):
            os.makedirs(CLIENT_VERSIONS_DIR, exist_ok=True)
            log_info(f"Создана папка: {CLIENT_VERSIONS_DIR}")
        
        # Проверяем наличие файла манифеста
        if not os.path.exists(CLIENT_VERSIONS_FILE):
            log_info(f"Файл манифеста не найден: {CLIENT_VERSIONS_FILE}")
            # Создаем дефолтный манифест
            default_versions = {
                "client": {
                    "latest": "1.0.1",
                    "versions": {
                        "1.0.0": {
                            "file": "udhclientmsg_v1.0.0.exe",
                            "hash": "default_hash",
                            "size": 0,
                            "date": "2026-08-01"
                        },
                        "1.0.1": {
                            "file": "udhclientmsg_v1.0.1.exe",
                            "hash": "default_hash",
                            "size": 0,
                            "date": "2026-08-15"
                        }
                    },
                    "changelog": {
                        "1.0.1": "Исправлен баг с отображением телефона\nДобавлена поддержка обновлений"
                    }
                }
            }
            with open(CLIENT_VERSIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_versions, f, indent=2, ensure_ascii=False)
            log_info(f"Создан файл манифеста версий: {CLIENT_VERSIONS_FILE}")
            return default_versions
        
        # Пытаемся прочитать существующий файл
        try:
            with open(CLIENT_VERSIONS_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Пустой файл манифеста")
                return json.loads(content)
        except json.JSONDecodeError as e:
            log_error(f"Ошибка парсинга манифеста: {e}")
            # Создаем бэкап поврежденного файла
            backup_file = f"{CLIENT_VERSIONS_FILE}.broken"
            if os.path.exists(CLIENT_VERSIONS_FILE):
                os.rename(CLIENT_VERSIONS_FILE, backup_file)
                log_info(f"Поврежденный манифест сохранен как {backup_file}")
            
            # Создаем новый манифест
            default_versions = {
                "client": {
                    "latest": "1.0.1",
                    "versions": {
                        "1.0.0": {
                            "file": "udhclientmsg_v1.0.0.exe",
                            "hash": "default_hash",
                            "size": 0,
                            "date": "2024-01-01"
                        },
                        "1.0.1": {
                            "file": "udhclientmsg_v1.0.1.exe",
                            "hash": "default_hash",
                            "size": 0,
                            "date": "2024-01-15"
                        }
                    },
                    "changelog": {
                        "1.0.1": "Исправлен баг с отображением телефона\nДобавлена поддержка обновлений"
                    }
                }
            }
            with open(CLIENT_VERSIONS_FILE, 'w', encoding='utf-8') as f:
                json.dump(default_versions, f, indent=2, ensure_ascii=False)
            log_info(f"Создан новый файл манифеста версий: {CLIENT_VERSIONS_FILE}")
            return default_versions
            
    except Exception as e:
        log_error(f"Ошибка в load_client_versions: {e}")
        import traceback
        log_error(traceback.format_exc())
        return None

def get_client_file_path(version):
    """Получение пути к файлу клиента по версии"""
    versions_data = load_client_versions()
    if not versions_data:
        return None
    
    client_info = versions_data.get("client", {})
    versions = client_info.get("versions", {})
    
    if version in versions:
        file_name = versions[version].get("file")
        if file_name:
            return os.path.join(CLIENT_VERSIONS_DIR, file_name)
    
    return None

# ----------------------------------------------------------------------
# Обработка клиентского соединения
# ----------------------------------------------------------------------
async def handle_connection(websocket):
    user_id = None
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
                log_debug(f"Получено сообщение: {message.get('type')} от user_id={user_id}")
            except json.JSONDecodeError:
                log_error("Неверный JSON от клиента")
                await websocket.send(json.dumps({"type": "error", "payload": {"message": "Invalid JSON"}}))
                continue

            msg_type = message.get("type")
            payload = message.get("payload", {})

            # ---------- РЕГИСТРАЦИЯ ----------
            if msg_type == "register_request":
                email = payload.get("email")
                nickname = payload.get("nickname")
                first_name = payload.get("first_name", "")
                last_name = payload.get("last_name", "")
                phone = payload.get("phone", "")
                department_id = payload.get("department_id")
                os_type = payload.get("os_type", "Неизвестно")

                log_info(f"Регистрация: email={email}, nickname={nickname}")

                if not email or not nickname:
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Email и никнейм обязательны"}
                    }))
                    continue

                if not is_email_allowed(email):
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Регистрация разрешена только для email с доменами @uvadrev.ru или @hk-vostok.ru"}
                    }))
                    continue

                existing = db_fetchone(USERS_DB_FILENAME, "SELECT id FROM users WHERE email = ? OR nickname = ?", (email, nickname))
                if existing:
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Пользователь с таким email или никнеймом уже существует"}
                    }))
                    continue

                code = generate_code()
                expires_at = (datetime.datetime.now() + datetime.timedelta(seconds=CODE_EXPIRATION_SECONDS)).timestamp()
                db_execute(USERS_DB_FILENAME, "DELETE FROM pending_registrations WHERE email = ?", (email,))
                db_execute(
                    USERS_DB_FILENAME,
                    "INSERT INTO pending_registrations (email, nickname, first_name, last_name, phone, department_id, code, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (email, nickname, first_name, last_name, phone, department_id, code, expires_at)
                )
                send_email_code(email, code, "Код подтверждения регистрации")
                await websocket.send(json.dumps({
                    "type": "register_confirm",
                    "payload": {"message": "Код отправлен на email", "email": email}
                }))
                log_info(f"Код подтверждения отправлен на {email}")

            elif msg_type == "register_code":
                email = payload.get("email")
                code = payload.get("code")
                password = payload.get("password")
                os_type = payload.get("os_type", "Неизвестно")

                log_info(f"Подтверждение регистрации: email={email}")

                if not email or not code or not password:
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Email, код и пароль обязательны"}
                    }))
                    continue

                if len(password) < 6:
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Пароль должен быть не менее 6 символов"}
                    }))
                    continue

                pending = db_fetchone(
                    USERS_DB_FILENAME,
                    "SELECT * FROM pending_registrations WHERE email = ? AND code = ?",
                    (email, code)
                )
                if not pending:
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Неверный код"}
                    }))
                    continue

                if pending["expires_at"] < datetime.datetime.now().timestamp():
                    db_execute(USERS_DB_FILENAME, "DELETE FROM pending_registrations WHERE email = ?", (email,))
                    await websocket.send(json.dumps({
                        "type": "register_error",
                        "payload": {"message": "Код истёк"}
                    }))
                    continue

                password_hash = hash_password(password)
                user_id = db_execute(
                    USERS_DB_FILENAME,
                    "INSERT INTO users (email, nickname, first_name, last_name, phone, department_id, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (email, pending["nickname"], pending["first_name"], pending["last_name"], pending["phone"], pending["department_id"], password_hash, datetime.datetime.now().isoformat())
                )
                db_execute(USERS_DB_FILENAME, "DELETE FROM pending_registrations WHERE email = ?", (email,))

                save_user_settings(user_id, {})

                client_info = get_client_info(websocket)
                connected_clients[user_id] = {
                    "websocket": websocket,
                    "hostname": client_info["hostname"],
                    "ip": client_info["ip"],
                    "os_type": os_type
                }
                log_info(f"Пользователь {email} (id={user_id}) зарегистрирован и подключен")

                await websocket.send(json.dumps({
                    "type": "register_success",
                    "payload": {
                        "user_id": user_id,
                        "email": email,
                        "nickname": pending["nickname"],
                        "first_name": pending["first_name"],
                        "last_name": pending["last_name"],
                        "phone": pending["phone"],
                        "department_id": pending["department_id"],
                        "settings": {}
                    }
                }))
                await broadcast_user_list()

            # ---------- ВХОД ----------
            elif msg_type == "login_request":
                email = payload.get("email")
                password = payload.get("password")
                os_type = payload.get("os_type", "Неизвестно")

                log_info(f"Вход: email={email}")

                if not email or not password:
                    await websocket.send(json.dumps({
                        "type": "login_error",
                        "payload": {"message": "Email и пароль обязательны"}
                    }))
                    continue

                user = db_fetchone(
                    USERS_DB_FILENAME,
                    """SELECT u.id, u.email, u.nickname, u.first_name, u.last_name, u.phone,
                              u.department_id, d.name as department_name, u.password_hash
                       FROM users u
                       LEFT JOIN departments d ON u.department_id = d.id
                       WHERE u.email = ?""",
                    (email,)
                )
                if not user:
                    log_warning(f"Пользователь {email} не найден")
                    await websocket.send(json.dumps({
                        "type": "login_error",
                        "payload": {"message": "Неверный email или пароль"}
                    }))
                    continue

                if not verify_password(password, user["password_hash"]):
                    log_warning(f"Неверный пароль для {email}")
                    await websocket.send(json.dumps({
                        "type": "login_error",
                        "payload": {"message": "Неверный email или пароль"}
                    }))
                    continue

                user_id = user["id"]
                client_info = get_client_info(websocket)
                connected_clients[user_id] = {
                    "websocket": websocket,
                    "hostname": client_info["hostname"],
                    "ip": client_info["ip"],
                    "os_type": os_type
                }
                log_info(f"Пользователь {email} (id={user_id}) вошел в систему. Всего онлайн: {len(connected_clients)}")

                settings = get_user_settings(user_id)
                
                # Проверяем право на массовую рассылку
                allmessages = settings.get('allmessages', 0)

                await websocket.send(json.dumps({
                    "type": "login_success",
                    "payload": {
                        "user_id": user_id,
                        "email": user["email"],
                        "nickname": user["nickname"],
                        "first_name": user["first_name"],
                        "last_name": user["last_name"],
                        "phone": user["phone"],
                        "department_id": user["department_id"],
                        "department_name": user["department_name"],
                        "settings": settings,
                        "allmessages": allmessages
                    }
                }))
                await broadcast_user_list()

            # ---------- ОБНОВЛЕНИЕ ПРОФИЛЯ ----------
            elif msg_type == "update_profile":
                if user_id is None:
                    log_warning("update_profile: user_id is None")
                    continue

                email = payload.get("email", "")
                nickname = payload.get("nickname", "")
                first_name = payload.get("first_name", "")
                last_name = payload.get("last_name", "")
                phone = payload.get("phone", "")
                department_id = payload.get("department_id")

                log_info(f"Обновление профиля пользователя {user_id}")

                db_execute(
                    USERS_DB_FILENAME,
                    "UPDATE users SET email = ?, nickname = ?, first_name = ?, last_name = ?, phone = ?, department_id = ? WHERE id = ?",
                    (email, nickname, first_name, last_name, phone, department_id, user_id)
                )

                updated_user = db_fetchone(
                    USERS_DB_FILENAME,
                    """SELECT u.id, u.email, u.nickname, u.first_name, u.last_name, u.phone,
                              u.department_id, d.name as department_name
                       FROM users u
                       LEFT JOIN departments d ON u.department_id = d.id
                       WHERE u.id = ?""",
                    (user_id,)
                )

                await websocket.send(json.dumps({
                    "type": "profile_updated",
                    "payload": {
                        "user_id": user_id,
                        "email": updated_user["email"],
                        "nickname": updated_user["nickname"],
                        "first_name": updated_user["first_name"],
                        "last_name": updated_user["last_name"],
                        "phone": updated_user["phone"],
                        "department_id": updated_user["department_id"],
                        "department_name": updated_user["department_name"]
                    }
                }))
                await broadcast_user_list()

            # ---------- ЗАПРОС ОТДЕЛОВ ----------
            elif msg_type == "get_departments":
                departments = db_fetchall(USERS_DB_FILENAME, "SELECT id, name FROM departments ORDER BY name")
                await websocket.send(json.dumps({
                    "type": "departments_list",
                    "payload": {"departments": departments}
                }))
                log_debug(f"Отправлен список отделов ({len(departments)})")

            # ---------- СОХРАНЕНИЕ НАСТРОЕК ----------
            elif msg_type == "save_settings":
                if user_id is None:
                    continue
                settings = payload.get("settings")
                if isinstance(settings, dict):
                    save_user_settings(user_id, settings)
                    log_debug(f"Настройки сохранены для пользователя {user_id}")

            # ---------- ПРОВЕРКА ВЕРСИИ КЛИЕНТА ----------
            # Не перезаписываем сессионный user_id: лаунчер шлёт user_id=0
            # и может работать без авторизации.
            elif msg_type == "check_client_version":
                requester_id = payload.get("user_id")
                current_version = payload.get("current_version", "0.0.0")

                log_info(f"Проверка версии клиента: requester_id={requester_id}, current_version={current_version}")

                versions_data = load_client_versions()
                if not versions_data:
                    await websocket.send(json.dumps({
                        "type": "version_response",
                        "payload": {
                            "has_update": False,
                            "message": "Информация о версиях недоступна"
                        }
                    }))
                    continue

                client_info = versions_data.get("client", {})
                latest_version = client_info.get("latest", "1.0.0")
                changelog = client_info.get("changelog", {}).get(latest_version, "Новая версия")

                # Проверяем, есть ли обновление
                has_update = current_version != latest_version

                # Получаем информацию о файле
                file_info = client_info.get("versions", {}).get(latest_version, {})
                file_size = file_info.get("size", 0)
                file_hash = file_info.get("hash", "")

                log_info(f"Версия клиента: текущая={current_version}, последняя={latest_version}, обновление={has_update}")

                await websocket.send(json.dumps({
                    "type": "version_response",
                    "payload": {
                        "has_update": has_update,
                        "latest_version": latest_version,
                        "file_size": file_size,
                        "file_hash": file_hash,
                        "changelog": changelog
                    }
                }))

            # ---------- СКАЧИВАНИЕ КЛИЕНТА ----------
            elif msg_type == "download_client":
                requester_id = payload.get("user_id")
                version = payload.get("version")

                log_info(f"Скачивание клиента: requester_id={requester_id}, version={version}")

                if not version:
                    await websocket.send(json.dumps({
                        "type": "download_error",
                        "payload": {"message": "Не указана версия"}
                    }))
                    continue

                # Лаунчер скачивает без авторизации (requester_id может быть 0 / None)
                if requester_id:
                    log_info(f"Скачивание клиента пользователем {requester_id}")
                else:
                    log_info("Скачивание клиента (Launcher)")

                # Получаем путь к файлу
                file_path = get_client_file_path(version)
                if not file_path or not os.path.exists(file_path):
                    log_error(f"Файл версии {version} не найден: {file_path}")
                    await websocket.send(json.dumps({
                        "type": "download_error",
                        "payload": {"message": f"Файл версии {version} не найден"}
                    }))
                    continue

                try:
                    # Читаем файл
                    with open(file_path, 'rb') as f:
                        file_data = f.read()

                    log_info(f"Файл клиента версии {version} загружен, размер={len(file_data)} байт")

                    # Разбиваем на чанки (по 64 КБ)
                    chunk_size = 64 * 1024
                    total_chunks = (len(file_data) + chunk_size - 1) // chunk_size

                    for i in range(total_chunks):
                        start = i * chunk_size
                        end = min(start + chunk_size, len(file_data))
                        chunk = file_data[start:end]

                        # Отправляем чанк
                        await websocket.send(json.dumps({
                            "type": "download_chunk",
                            "payload": {
                                "chunk_index": i,
                                "total_chunks": total_chunks,
                                "data": base64.b64encode(chunk).decode(),
                                "last": (i == total_chunks - 1)
                            }
                        }))

                        # Небольшая задержка для предотвращения перегрузки
                        await asyncio.sleep(0.01)

                    # Отправляем подтверждение завершения
                    await websocket.send(json.dumps({
                        "type": "download_complete",
                        "payload": {
                            "hash": "verified",
                            "size": len(file_data)
                        }
                    }))

                    log_info(f"Клиент версии {version} отправлен")

                except Exception as e:
                    log_error(f"Ошибка отправки клиента: {e}")
                    await websocket.send(json.dumps({
                        "type": "download_error",
                        "payload": {"message": f"Ошибка отправки: {str(e)}"}
                    }))

            # ---------- ПОДТВЕРЖДЕНИЕ УСТАНОВКИ ОБНОВЛЕНИЯ ----------
            elif msg_type == "update_installed":
                requester_id = payload.get("user_id")
                version = payload.get("version")

                if requester_id and version:
                    log_info(f"Пользователь {requester_id} обновил клиент до версии {version}")
                    await websocket.send(json.dumps({
                        "type": "update_confirmed",
                        "payload": {"status": "ok"}
                    }))

            # ---------- ЛИЧНЫЕ СООБЩЕНИЯ ----------
            elif msg_type == "chat_message":
                # Проверяем, что пользователь авторизован
                if user_id is None:
                    log_warning("Попытка отправки сообщения без авторизации")
                    await websocket.send(json.dumps({
                        "type": "error",
                        "payload": {"message": "Не авторизован"}
                    }))
                    continue
                
                to_user_id = payload.get("to_user_id")
                content = payload.get("content")
                reply_to = payload.get("reply_to")

                if not content:
                    continue

                log_info(f"Сообщение от {user_id} к {to_user_id}: {content[:50]}...")

                # Сохраняем сообщение в БД с reply_to
                reply_to_json = json.dumps(reply_to) if reply_to else None
                db_execute(
                    MESSAGES_DB_FILENAME,
                    "INSERT INTO messages (from_user_id, to_user_id, message_type, content, timestamp, reply_to) VALUES (?, ?, 'text', ?, ?, ?)",
                    (user_id, to_user_id, content, datetime.datetime.now().isoformat(), reply_to_json)
                )

                # Формируем payload для доставки
                deliver_payload = {
                    "from_user_id": user_id,
                    "content": content,
                    "timestamp": datetime.datetime.now().isoformat()
                }
                
                # Добавляем информацию об ответе, если она есть
                if reply_to:
                    deliver_payload["reply_to"] = reply_to
                    log_debug(f"Ответ на сообщение {reply_to.get('message_id')}")

                if to_user_id in connected_clients:
                    await connected_clients[to_user_id]["websocket"].send(json.dumps({
                        "type": "chat_message_deliver",
                        "payload": deliver_payload
                    }))
                    log_debug(f"Сообщение доставлено пользователю {to_user_id}")
                else:
                    log_warning(f"Пользователь {to_user_id} не в сети")

            # ---------- ПЕРЕДАЧА ФАЙЛОВ ----------
            elif msg_type == "file_transfer":
                # Проверяем, что пользователь авторизован
                if user_id is None:
                    log_warning("Попытка передачи файла без авторизации")
                    continue
                
                to_user_id = payload.get("to_user_id")
                is_image = payload.get("is_image", False)
                file_name = payload.get("file_name", "")
                data_b64 = payload.get("data", "")

                log_info(f"Передача файла от {user_id} к {to_user_id}: {file_name} (image={is_image})")

                if is_image:
                    # Для изображений в БД сохраняем ТОЛЬКО имя файла
                    db_execute(
                        MESSAGES_DB_FILENAME,
                        "INSERT INTO messages (from_user_id, to_user_id, message_type, file_name, timestamp) VALUES (?, ?, 'image', ?, ?)",
                        (user_id, to_user_id, file_name, datetime.datetime.now().isoformat())
                    )
                else:
                    db_execute(
                        MESSAGES_DB_FILENAME,
                        "INSERT INTO messages (from_user_id, to_user_id, message_type, file_name, timestamp) VALUES (?, ?, 'file', ?, ?)",
                        (user_id, to_user_id, file_name, datetime.datetime.now().isoformat())
                    )

                if to_user_id in connected_clients:
                    await connected_clients[to_user_id]["websocket"].send(json.dumps({
                        "type": "file_transfer_deliver",
                        "payload": payload
                    }))
                    log_debug(f"Файл доставлен пользователю {to_user_id}")

            # ---------- ЗАПРОС ИСТОРИИ ----------
            elif msg_type == "history_request":
                if user_id is None:
                    log_warning("Запрос истории без авторизации")
                    continue

                other_user_id = payload.get("other_user_id")
                limit = payload.get("limit", 50)
                offset = payload.get("offset", 0)
                since = payload.get("since", "")

                log_info(f"Запрос истории: user_id={user_id}, other_user_id={other_user_id}, limit={limit}, offset={offset}")

                query = """SELECT id, from_user_id, to_user_id, message_type, content, file_name, timestamp, reply_to
                           FROM messages
                           WHERE (from_user_id = ? AND to_user_id = ?)
                              OR (from_user_id = ? AND to_user_id = ?)"""
                params = [user_id, other_user_id, other_user_id, user_id]

                if since:
                    query += " AND timestamp >= ?"
                    params.append(since)

                query += " ORDER BY id DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])

                messages = db_fetchall(MESSAGES_DB_FILENAME, query, tuple(params))

                result = []
                for m in messages:
                    msg = {
                        "id": m["id"],
                        "from_user_id": m["from_user_id"],
                        "to_user_id": m["to_user_id"],
                        "message_type": m["message_type"],
                        "content": m["content"],
                        "file_name": m["file_name"],
                        "timestamp": m["timestamp"]
                    }
                    # Добавляем reply_to если есть
                    if m.get("reply_to"):
                        try:
                            msg["reply_to"] = json.loads(m["reply_to"])
                        except:
                            pass
                    result.append(msg)

                log_debug(f"История: найдено {len(result)} сообщений")

                await websocket.send(json.dumps({
                    "type": "history_response",
                    "payload": {
                        "other_user_id": other_user_id,
                        "messages": result,
                        "has_more": len(result) == limit
                    }
                }))

            # ---------- ПОЛУЧЕНИЕ СПИСКА ПОЛЬЗОВАТЕЛЕЙ ДЛЯ ИСТОРИИ ----------
            elif msg_type == "get_history_users":
                if user_id is None:
                    log_warning("Запрос истории без авторизации")
                    continue
                
                date_from = payload.get("date_from")
                date_to = payload.get("date_to")
                
                if not date_from or not date_to:
                    await websocket.send(json.dumps({
                        "type": "history_users_response",
                        "payload": {"users": []}
                    }))
                    continue
                
                log_info(f"Запрос пользователей для истории: user_id={user_id}, date_from={date_from}, date_to={date_to}")
                
                # Находим всех пользователей, с которыми были диалоги в указанный период
                query = """SELECT DISTINCT 
                            CASE 
                                WHEN from_user_id = ? THEN to_user_id
                                ELSE from_user_id
                            END as other_user_id
                          FROM messages
                          WHERE (from_user_id = ? OR to_user_id = ?)
                            AND timestamp >= ?
                            AND timestamp <= ?
                            AND message_type = 'text'"""
                
                params = [user_id, user_id, user_id, date_from, date_to]
                
                rows = db_fetchall(MESSAGES_DB_FILENAME, query, tuple(params))
                
                users = [row["other_user_id"] for row in rows if row["other_user_id"] is not None]
                
                log_debug(f"Найдено {len(users)} пользователей для истории")
                
                await websocket.send(json.dumps({
                    "type": "history_users_response",
                    "payload": {"users": users}
                }))

    except websockets.exceptions.ConnectionClosed:
        log_debug(f"Соединение закрыто (user_id={user_id})")
    except Exception as e:
        log_error(f"Ошибка в handle_connection: {e}")
        import traceback
        log_error(traceback.format_exc())
    finally:
        if user_id is not None and user_id in connected_clients:
            del connected_clients[user_id]
            await broadcast_user_list()
            log_info(f"Пользователь {user_id} отключен. Всего онлайн: {len(connected_clients)}")
        else:
            log_debug(f"Соединение закрыто без авторизации")

# ----------------------------------------------------------------------
# Обработка админ-соединения
# ----------------------------------------------------------------------
async def handle_admin_connection(websocket):
    authenticated = False
    try:
        async for raw_message in websocket:
            try:
                message = json.loads(raw_message)
            except json.JSONDecodeError:
                await websocket.send(json.dumps({"type": "error", "payload": {"message": "Invalid JSON"}}))
                continue

            msg_type = message.get("type")
            payload = message.get("payload", {})

            if msg_type == "admin_login":
                if verify_admin_password(payload.get("password", "")):
                    authenticated = True
                    log_info("Админ-панель: успешный вход")
                    await websocket.send(json.dumps({
                        "type": "admin_login_success",
                        "payload": {"message": "Авторизация успешна"}
                    }))
                else:
                    authenticated = False
                    log_warning("Админ-панель: неверный пароль")
                    await websocket.send(json.dumps({
                        "type": "admin_login_error",
                        "payload": {"message": "Неверный пароль"}
                    }))
                continue

            if not authenticated:
                log_warning(f"Админ-панель: отказ без логина ({msg_type})")
                await websocket.send(json.dumps({
                    "type": "error",
                    "payload": {"message": "Требуется авторизация. Отправьте admin_login"}
                }))
                continue

            # ---------- ОТДЕЛЫ ----------
            if msg_type == "get_departments":
                departments = db_fetchall(USERS_DB_FILENAME, "SELECT id, name, created_at FROM departments ORDER BY name")
                await websocket.send(json.dumps({
                    "type": "departments_list",
                    "payload": {"departments": departments}
                }))

            elif msg_type == "create_department":
                name = payload.get("name", "").strip()
                if not name:
                    await websocket.send(json.dumps({"type": "error", "payload": {"message": "Название отдела обязательно"}}))
                    continue
                existing = db_fetchone(USERS_DB_FILENAME, "SELECT id FROM departments WHERE name = ?", (name,))
                if existing:
                    await websocket.send(json.dumps({"type": "error", "payload": {"message": "Отдел с таким названием уже существует"}}))
                    continue
                dept_id = db_execute(
                    USERS_DB_FILENAME,
                    "INSERT INTO departments (name, created_at) VALUES (?, ?)",
                    (name, datetime.datetime.now().isoformat())
                )
                log_info(f"Создан отдел: {name} (id={dept_id})")
                await websocket.send(json.dumps({"type": "department_created", "payload": {"id": dept_id, "name": name}}))
                await broadcast_departments()

            elif msg_type == "update_department":
                dept_id = payload.get("id")
                name = payload.get("name", "").strip()
                if not dept_id or not name:
                    continue
                db_execute(USERS_DB_FILENAME, "UPDATE departments SET name = ? WHERE id = ?", (name, dept_id))
                log_info(f"Обновлен отдел: id={dept_id}, name={name}")
                await websocket.send(json.dumps({"type": "department_updated", "payload": {"id": dept_id, "name": name}}))
                await broadcast_departments()

            elif msg_type == "delete_department":
                dept_id = payload.get("id")
                if not dept_id:
                    continue
                db_execute(USERS_DB_FILENAME, "UPDATE users SET department_id = NULL WHERE department_id = ?", (dept_id,))
                db_execute(USERS_DB_FILENAME, "DELETE FROM departments WHERE id = ?", (dept_id,))
                log_info(f"Удален отдел: id={dept_id}")
                await websocket.send(json.dumps({"type": "department_deleted", "payload": {"id": dept_id}}))
                await broadcast_departments()
                await broadcast_user_list()

            # ---------- ПОЛЬЗОВАТЕЛИ ----------
            elif msg_type == "get_users":
                users = db_fetchall(
                    USERS_DB_FILENAME,
                    """SELECT u.id, u.email, u.nickname, u.first_name, u.last_name, u.phone,
                              u.department_id, d.name as department_name, u.created_at
                       FROM users u
                       LEFT JOIN departments d ON u.department_id = d.id
                       ORDER BY u.id"""
                )
                await websocket.send(json.dumps({
                    "type": "users_list",
                    "payload": {"users": users}
                }))

            elif msg_type == "create_user":
                email = payload.get("email")
                nickname = payload.get("nickname")
                first_name = payload.get("first_name", "")
                last_name = payload.get("last_name", "")
                phone = payload.get("phone", "")
                department_id = payload.get("department_id")
                password = payload.get("password", "")

                if not email or not nickname:
                    await websocket.send(json.dumps({"type": "error", "payload": {"message": "Email и никнейм обязательны"}}))
                    continue

                existing = db_fetchone(USERS_DB_FILENAME, "SELECT id FROM users WHERE email = ? OR nickname = ?", (email, nickname))
                if existing:
                    await websocket.send(json.dumps({"type": "error", "payload": {"message": "Пользователь уже существует"}}))
                    continue

                if not password:
                    password = generate_code(8)

                password_hash = hash_password(password)
                user_id = db_execute(
                    USERS_DB_FILENAME,
                    "INSERT INTO users (email, nickname, first_name, last_name, phone, department_id, password_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (email, nickname, first_name, last_name, phone, department_id, password_hash, datetime.datetime.now().isoformat())
                )
                save_user_settings(user_id, {})
                log_info(f"Создан пользователь: {email} (id={user_id})")
                await websocket.send(json.dumps({
                    "type": "user_created",
                    "payload": {"user_id": user_id, "email": email, "nickname": nickname, "password": password}
                }))
                await broadcast_user_list()

            elif msg_type == "update_user":
                user_id = payload.get("id")
                if not user_id:
                    continue
                updates = []
                params = []
                for field in ['email', 'nickname', 'first_name', 'last_name', 'phone', 'department_id']:
                    if field in payload:
                        updates.append(f"{field} = ?")
                        params.append(payload[field])
                password = (payload.get("password") or "").strip()
                if password:
                    updates.append("password_hash = ?")
                    params.append(hash_password(password))
                if updates:
                    params.append(user_id)
                    db_execute(USERS_DB_FILENAME, f"UPDATE users SET {', '.join(updates)} WHERE id = ?", tuple(params))
                log_info(f"Обновлен пользователь: id={user_id}")
                await websocket.send(json.dumps({"type": "user_updated", "payload": {"id": user_id}}))
                await broadcast_user_list()

            elif msg_type == "delete_user":
                user_id = payload.get("id")
                if not user_id:
                    continue
                db_execute(USERS_DB_FILENAME, "DELETE FROM users WHERE id = ?", (user_id,))
                db_execute(USERS_DB_FILENAME, "DELETE FROM user_settings WHERE user_id = ?", (user_id,))
                log_info(f"Удален пользователь: id={user_id}")
                await websocket.send(json.dumps({"type": "user_deleted", "payload": {"id": user_id}}))
                await broadcast_user_list()

            # ---------- СООБЩЕНИЯ ----------
            elif msg_type == "get_messages":
                limit = payload.get("limit", 1000)
                
                query = """SELECT id, from_user_id, to_user_id, message_type, content, file_name, timestamp
                           FROM messages 
                           ORDER BY id DESC LIMIT ?"""
                
                messages = db_fetchall(MESSAGES_DB_FILENAME, query, (limit,))
                
                # Преобразуем для отправки
                result = [
                    {
                        "id": m["id"],
                        "from_user_id": m["from_user_id"],
                        "to_user_id": m["to_user_id"],
                        "message_type": m["message_type"],
                        "content": m["content"],
                        "file_name": m["file_name"],
                        "timestamp": m["timestamp"]
                    }
                    for m in messages
                ]
                
                log_info(f"Отправлено {len(result)} сообщений в админ-панель")
                
                await websocket.send(json.dumps({
                    "type": "messages_list",
                    "payload": {"messages": result}
                }))

    except websockets.exceptions.ConnectionClosed:
        pass
    except Exception as e:
        log_error(f"Ошибка в handle_admin_connection: {e}")

# ----------------------------------------------------------------------
# Запуск
# ----------------------------------------------------------------------
async def main():
    global logger
    logger = init_logging()
    
    load_config()
    init_db()
    
    log_info(f"База пользователей: {os.path.abspath(USERS_DB_FILENAME)}")
    log_info(f"База сообщений: {os.path.abspath(MESSAGES_DB_FILENAME)}")

    # Создаем папку для версий клиента
    os.makedirs(CLIENT_VERSIONS_DIR, exist_ok=True)
    log_info(f"Папка для версий клиента: {os.path.abspath(CLIENT_VERSIONS_DIR)}")

    ssl_context = create_ssl_context()

    if ssl_context:
        log_info(f"✅ Сервер udhservermsg запущен на wss://0.0.0.0:{SERVER_PORT}")
        log_info(f"✅ Админ-сервер запущен на wss://0.0.0.0:{ADMIN_PORT}")
        log_info(f"✅ Трафик ШИФРУЕТСЯ (WSS)")
    else:
        log_warning(f"⚠️ Сервер udhservermsg запущен на ws://0.0.0.0:{SERVER_PORT}")
        log_warning(f"⚠️ Админ-сервер запущен на ws://0.0.0.0:{ADMIN_PORT}")
        log_warning(f"⚠️ Трафик НЕ шифруется")

    # Оба сервера с SSL
    client_server = websockets.serve(handle_connection, "0.0.0.0", SERVER_PORT, ssl=ssl_context, max_size=MAX_WS_MESSAGE_SIZE)
    admin_server = websockets.serve(handle_admin_connection, "0.0.0.0", ADMIN_PORT, ssl=ssl_context, max_size=MAX_WS_MESSAGE_SIZE)

    async with client_server:
        async with admin_server:
            await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Сервер остановлен")