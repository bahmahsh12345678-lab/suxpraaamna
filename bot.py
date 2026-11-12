# ═══════════════════════════════════════════════════════════
# DEĞİŞİKLİK ÖZETİ (sadece eklenen / değişen bölümler)
# ═══════════════════════════════════════════════════════════
# 1) ADMIN ONAY SİSTEMİ  -> .py / .js / .zip / diğerleri için
#    upload -> owner'a "Onayla / Reddet" butonlu mesaj
#    onaylanınca -> normal akış (run_script / run_js_script)
# 2) BTN_STYLE (BOT API 9.0+) -> ReplyKeyboardMarkup(style=...)
#    InlineKeyboardButton(style=...) destekleniyorsa kullan, değilse sessizce atla
# 3) HIZLI YANIT -> kısa sleep süreleri (0.3s)
# 4) CPU/RAM -> ön kontrol süresi kısaltıldı, sleep azaltıldı,
#    periyodik GC tetikleyici, loglar suppress
# ═══════════════════════════════════════════════════════════

import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
import gc

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive server started.")

BOT_START_TIME = datetime.now()

def get_uptime():
    uptime = datetime.now() - BOT_START_TIME
    days = uptime.days
    hours, remainder = divmod(uptime.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days}d {hours}h {minutes}m {seconds}s"

TOKEN = '9060512331:AAFidPWi-6qNi8B5YNRDPPQ9NslysPKgRS0'
OWNER_ID =8947359034
ADMIN_ID =8947359034
YOUR_USERNAME = '@suprapanel'
UPDATE_CHANNEL = 'https://t.me/logsuzlarpanelvip'

A4F_API_URL = "https://samuraiapi.in/v1/chat/completions"
A4F_API_KEY = "sk-NK6SS9tpWghyFJwkZLoCis1sMaF6"
A4F_MODEL = "provider10-claude-sonnet-4-20250514(clinesp)"

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

FREE_USER_LIMIT = 2
SUBSCRIBED_USER_LIMIT = 2
ADMIN_LIMIT = 20
OWNER_LIMIT = float('inf')

# ══════════════ BTN STYLE ══════════════
# Bot API 9.0+ style destekler. Eski sürümlerde sessizce atlanır.
BTN_STYLE_PRIMARY = "primary"
BTN_STYLE_SUCCESS = "success"
BTN_STYLE_DANGER  = "danger"
BTN_STYLE_WARNING = "warning"

def _btn_style_supported():
    """Telebot InlineKeyboardButton style destekliyor mu test et."""
    try:
        types.InlineKeyboardButton("t", callback_data="x", style=BTN_STYLE_PRIMARY)
        return True
    except TypeError:
        return False

BTN_STYLE_OK = _btn_style_supported()

def make_btn(text, **kwargs):
    """Style destekli buton yap; desteklemiyorsa stylesiz."""
    if BTN_STYLE_OK and "style" in kwargs:
        try:
            return types.InlineKeyboardButton(text, **kwargs)
        except TypeError:
            kwargs.pop("style", None)
    else:
        kwargs.pop("style", None)
    return types.InlineKeyboardButton(text, **kwargs)

def make_kb_style(kb_button):
    """ReplyKeyboardButton'a style uygula (destekleniyorsa)."""
    try:
        return types.KeyboardButton(kb_button, style=BTN_STYLE_PRIMARY)
    except TypeError:
        return types.KeyboardButton(kb_button)

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False

# ══════════════ ADMIN ONAY BEKLEYEN DOSYALAR ══════════════
# key: approval_token (str), value: dict with file metadata
pending_approvals = {}
pending_lock = threading.Lock()

def _new_approval_token():
    import uuid
    return uuid.uuid4().hex[:16]

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel", "⏱ Uptime"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["📞 Contact Owner", "🤖 MPX Ai"]
]

ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC = [
    ["📢 Updates Channel", "/ping"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"],
    ["👑 Admin Panel", "📞 Contact Owner"],
    ["🤖 MPX Ai", "⏱ Uptime"],
]

def init_db():
    logger.info(f"Initializing database at: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database initialization error: {e}", exc_info=True)

def load_data():
    logger.info("Loading data from database...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except ValueError:
                logger.warning(f"Invalid expiry date format for user {user_id}: {expiry}. Skipping.")

        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        conn.close()
        logger.info(f"Data loaded: {len(active_users)} users, {len(user_subscriptions)} subscriptions, {len(admin_ids)} admins.")
    except Exception as e:
        logger.error(f"Error loading data: {e}", exc_info=True)

init_db()
load_data()

def get_user_folder(user_id):
    user_folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    return user_folder

def get_user_file_limit(user_id):
    if user_id == OWNER_ID: return OWNER_LIMIT
    if user_id in admin_ids: return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT

def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))

def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try: script_info['log_file'].close()
                    except: pass
                if script_key in bot_scripts: del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try: script_info['log_file'].close()
                except: pass
            if script_key in bot_scripts: del bot_scripts[script_key]
            return False
        except Exception:
            return False
    return False

def kill_process_tree(process_info):
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')
    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
            except: pass

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try: child.terminate()
                        except psutil.NoSuchProcess: pass
                        except Exception:
                            try: child.kill()
                            except: pass
                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try: p.kill()
                        except: pass
                    try:
                        parent.terminate()
                        try: parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            try: parent.kill()
                            except: pass
                    except psutil.NoSuchProcess: pass
                    except Exception:
                        try: parent.kill()
                        except: pass
                except psutil.NoSuchProcess: pass
    except Exception as e:
        logger.error(f"kill_process_tree error: {e}")

TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'telethon.sync': 'telethon',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'pandas': 'pandas',
    'numpy': 'numpy',
    'flask': 'Flask',
    'django': 'Django',
    'sqlalchemy': 'SQLAlchemy',
    'asyncio': None, 'json': None, 'datetime': None, 'os': None,
    'sys': None, 're': None, 'time': None, 'math': None,
    'random': None, 'logging': None, 'threading': None,
    'subprocess': None, 'zipfile': None, 'tempfile': None,
    'shutil': None, 'sqlite3': None, 'psutil': 'psutil',
    'atexit': None, 'gc': None
}

def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None: return False
    try:
        bot.reply_to(message, f"Module `{module_name}` not found. Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"Package `{package_name}` installed.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"Failed to install `{package_name}`.\nLog:\n```\n{(result.stderr or result.stdout)[:2000]}\n```"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except Exception as e:
        bot.reply_to(message, f"Error installing `{package_name}`: {str(e)}")
        return False

def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"Node package `{module_name}` not found. Installing locally...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False, cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"Node package `{module_name}` installed locally.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"Failed to install Node package `{module_name}`.\nLog:\n```\n{(result.stderr or result.stdout)[:2000]}\n```"
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except FileNotFoundError:
        bot.reply_to(message, "Error: 'npm' not found.")
        return False
    except Exception as e:
        bot.reply_to(message, f"Error installing Node package `{module_name}`: {str(e)}")
        return False

def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"Error: Script '{file_name}' not found!")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=3)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            bot.reply_to(message_obj_for_reply, f"Install successful. Retrying '{file_name}'...")
                            threading.Thread(target=run_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"Install failed. Cannot run '{file_name}'.")
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"Error in script pre-check for '{file_name}':\n```\n{error_summary}\n```\nFix the script.", parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, f"Error: Python interpreter '{sys.executable}' not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"Unexpected error in script pre-check for '{file_name}': {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill(); check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"Failed to open log file '{log_file_path}': {e}")
            return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"Python script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, f"Error: Python interpreter '{sys.executable}' not found.")
            if log_file and not log_file.closed: log_file.close()
            if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"Error starting Python script '{file_name}': {str(e)}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"Unexpected error running Python script '{file_name}': {str(e)}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"Failed to run '{file_name}' after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"Error: Script '{file_name}' not found!")
            if script_owner_id in user_files:
                user_files[script_owner_id] = [f for f in user_files.get(script_owner_id, []) if f[0] != file_name]
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = ['node', script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=3)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                bot.reply_to(message_obj_for_reply, f"NPM Install successful. Retrying '{file_name}'...")
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"NPM Install failed. Cannot run '{file_name}'.")
                                return
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"Error in JS script pre-check for '{file_name}':\n```\n{error_summary}\n```", parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None: check_proc.kill(); check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, "Error: 'node' not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"Unexpected error in JS pre-check for '{file_name}': {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill(); check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None; process = None
        try: log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"Failed to open log file '{log_file_path}': {e}")
            return
        try:
            startupinfo = None; creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder, 'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"JS script '{file_name}' started! (PID: {process.pid}) (For User: {script_owner_id})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, "Error: 'node' not found.")
            if log_file and not log_file.closed: log_file.close()
            if script_key in bot_scripts: del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed: log_file.close()
            bot.reply_to(message_obj_for_reply, f"Error starting JS script '{file_name}': {str(e)}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts: del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"Unexpected error running JS script '{file_name}': {str(e)}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]

DB_LOCK = threading.Lock()

def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files: user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
        except sqlite3.Error as e: logger.error(f"SQLite error saving file: {e}")
        finally: conn.close()

def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]: del user_files[user_id]
        except sqlite3.Error as e: logger.error(f"SQLite error removing file: {e}")
        finally: conn.close()

def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except sqlite3.Error as e: logger.error(f"SQLite error adding active user: {e}")
        finally: conn.close()

def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)', (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
        except sqlite3.Error as e: logger.error(f"SQLite error saving subscription: {e}")
        finally: conn.close()

def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions: del user_subscriptions[user_id]
        except sqlite3.Error as e: logger.error(f"SQLite error removing subscription: {e}")
        finally: conn.close()

def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
        except sqlite3.Error as e: logger.error(f"SQLite error adding admin: {e}")
        finally: conn.close()

def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0
                if removed: admin_ids.discard(admin_id)
            else:
                admin_ids.discard(admin_id)
            return removed
        except sqlite3.Error as e: logger.error(f"SQLite error removing admin: {e}"); return False
        finally: conn.close()

# ══════════════ KLAVYE & MENÜ (STYLE'LI) ══════════════
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(make_btn('📢 Updates Channel', url=UPDATE_CHANNEL, style=BTN_STYLE_PRIMARY))
    markup.add(make_btn('📤 Upload File', callback_data='upload', style=BTN_STYLE_SUCCESS),
               make_btn('📂 Check Files', callback_data='check_files', style=BTN_STYLE_PRIMARY))
    markup.add(make_btn('⚡ Bot Speed', callback_data='speed', style=BTN_STYLE_WARNING),
               make_btn('📊 Statistics', callback_data='stats', style=BTN_STYLE_PRIMARY))
    markup.add(make_btn('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}', style=BTN_STYLE_PRIMARY),
               make_btn('🤖 MPX AI', callback_data='mpx_ai', style=BTN_STYLE_PRIMARY))

    if user_id in admin_ids:
        markup.add(make_btn('💳 Subscriptions', callback_data='subscription', style=BTN_STYLE_PRIMARY),
                   make_btn('📢 Broadcast', callback_data='broadcast', style=BTN_STYLE_WARNING))
        markup.add(
            make_btn('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                     callback_data='lock_bot' if not bot_locked else 'unlock_bot',
                     style=BTN_STYLE_DANGER if not bot_locked else BTN_STYLE_SUCCESS),
            make_btn('🟢 Run All User Scripts', callback_data='run_all_scripts', style=BTN_STYLE_SUCCESS))
        markup.add(make_btn('👑 Admin Panel', callback_data='admin_panel', style=BTN_STYLE_PRIMARY))

    markup.add(make_btn('⏱ Uptime', callback_data='uptime', style=BTN_STYLE_PRIMARY))
    return markup

def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout_to_use = ADMIN_COMMAND_BUTTONS_LAYOUT_USER_SPEC if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER_SPEC
    for row_buttons_text in layout_to_use:
        markup.add(*[make_kb_style(text) for text in row_buttons_text])
    return markup

def create_control_buttons(script_owner_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(
            make_btn("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}', style=BTN_STYLE_DANGER),
            make_btn("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}', style=BTN_STYLE_WARNING))
        markup.row(
            make_btn("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}', style=BTN_STYLE_DANGER),
            make_btn("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}', style=BTN_STYLE_PRIMARY))
    else:
        markup.row(
            make_btn("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}', style=BTN_STYLE_SUCCESS),
            make_btn("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}', style=BTN_STYLE_DANGER))
        markup.row(
            make_btn("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}', style=BTN_STYLE_PRIMARY))
    markup.add(make_btn("🔙 Back to Files", callback_data='check_files', style=BTN_STYLE_PRIMARY))
    return markup

def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        make_btn('➕ Add Admin', callback_data='add_admin', style=BTN_STYLE_SUCCESS),
        make_btn('➖ Remove Admin', callback_data='remove_admin', style=BTN_STYLE_DANGER))
    markup.row(make_btn('📋 List Admins', callback_data='list_admins', style=BTN_STYLE_PRIMARY))
    markup.row(make_btn('🔙 Back to Main', callback_data='back_to_main', style=BTN_STYLE_PRIMARY))
    return markup

def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        make_btn('➕ Add Subscription', callback_data='add_subscription', style=BTN_STYLE_SUCCESS),
        make_btn('➖ Remove Subscription', callback_data='remove_subscription', style=BTN_STYLE_DANGER))
    markup.row(make_btn('🔍 Check Subscription', callback_data='check_subscription', style=BTN_STYLE_PRIMARY))
    markup.row(make_btn('🔙 Back to Main', callback_data='back_to_main', style=BTN_STYLE_PRIMARY))
    return markup

# ══════════════ ADMIN ONAY KLAVYESİ ══════════════
def create_approval_kb(token):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        make_btn("✅ Onayla / Başlat", callback_data=f'approve_file_{token}', style=BTN_STYLE_SUCCESS),
        make_btn("❌ Reddet", callback_data=f'reject_file_{token}', style=BTN_STYLE_DANGER))
    return markup

# ══════════════ ADMIN ONAY AKIŞI ══════════════
def send_for_approval(user_id, file_name, file_type, local_file_path, message, raw_bytes_or_none=None):
    """
    Kullanıcı dosya yüklediğinde çağrılır.
    Dosyayı OWNER_ID'ye gönderir + Onayla/Reddet butonu ekler.
    Onay gelince run_script / run_js_script tetiklenir.
    """
    token = _new_approval_token()
    record = {
        "token": token,
        "user_id": user_id,
        "file_name": file_name,
        "file_type": file_type,
        "local_path": local_file_path,
        "chat_id": message.chat.id,
        "message_id": message.message_id,
        "created": datetime.now().isoformat(),
    }
    with pending_lock:
        pending_approvals[token] = record

    try:
        # Owner'a orijinal dosyayı forward et
        try:
            bot.forward_message(OWNER_ID, message.chat.id, message.message_id)
        except Exception:
            pass

        caption = (
            f"🛡️ **DOSYA ONAYI GEREKLİ**\n\n"
            f"👤 Kullanıcı: `{user_id}`\n"
            f"📄 Dosya: `{file_name}`\n"
            f"🏷️ Tür: `{file_type}`\n"
            f"🕐 Tarih: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
            f"Onaylarsan **otomatik başlatılır**, reddedersen **silinir**."
        )
        bot.send_message(OWNER_ID, caption, parse_mode='Markdown', reply_markup=create_approval_kb(token))
        bot.reply_to(message, "⏳ Dosyanız **admin onayına** gönderildi. Onaylanınca otomatik başlatılacak.")
    except Exception as e:
        logger.error(f"send_for_approval error: {e}")
        bot.reply_to(message, f"Onay mesajı gönderilemedi: {e}")

def _delete_user_file(user_id, file_name, file_type='py'):
    """Onay reddedilirse dosyayı ve logu diskten + DB'den sil."""
    script_key = f"{user_id}_{file_name}"
    # Çalışıyorsa durdur
    if is_bot_running(user_id, file_name):
        info = bot_scripts.get(script_key)
        if info: kill_process_tree(info)
        if script_key in bot_scripts: del bot_scripts[script_key]
    user_folder = get_user_folder(user_id)
    fp = os.path.join(user_folder, file_name)
    lp = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
    for p in (fp, lp):
        if os.path.exists(p):
            try: os.remove(p)
            except: pass
    remove_user_file_db(user_id, file_name)

def handle_approve_callback(call):
    try:
        token = call.data.replace('approve_file_', '')
    except Exception:
        return
    with pending_lock:
        record = pending_approvals.pop(token, None)
    if not record:
        bot.answer_callback_query(call.id, "Onay kaydı bulunamadı (süresi geçmiş olabilir).", show_alert=True)
        return
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Sadece admin onaylayabilir.", show_alert=True)
        with pending_lock: pending_approvals[token] = record
        return

    bot.answer_callback_query(call.id, "✅ Onaylandı, başlatılıyor...")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except: pass

    user_id = record['user_id']
    file_name = record['file_name']
    file_type = record['file_type']
    user_folder = get_user_folder(user_id)
    file_path = os.path.join(user_folder, file_name)

    if not os.path.exists(file_path):
        try: bot.send_message(OWNER_ID, f"⚠️ Dosya diskte bulunamadı: `{file_name}` (User `{user_id}`)", parse_mode='Markdown')
        except: pass
        return

    # Kayıt + çalıştır
    save_user_file(user_id, file_name, file_type)
    try:
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, user_id, user_folder, file_name, record_msg_stub(record))).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, user_id, user_folder, file_name, record_msg_stub(record))).start()
    except Exception as e:
        logger.error(f"approve start error: {e}")

    try:
        bot.send_message(user_id, f"✅ Dosyan `{file_name}` admin tarafından **onaylandı** ve başlatıldı!")
    except: pass

def handle_reject_callback(call):
    try:
        token = call.data.replace('reject_file_', '')
    except Exception:
        return
    with pending_lock:
        record = pending_approvals.pop(token, None)
    if not record:
        bot.answer_callback_query(call.id, "Kayıt bulunamadı.", show_alert=True)
        return
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Sadece admin reddedebilir.", show_alert=True)
        with pending_lock: pending_approvals[token] = record
        return

    bot.answer_callback_query(call.id, "❌ Reddedildi.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except: pass

    _delete_user_file(record['user_id'], record['file_name'], record['file_type'])
    try:
        bot.send_message(record['user_id'], f"❌ Dosyan `{record['file_name']}` admin tarafından **reddedildi** ve silindi.")
    except: pass

def record_msg_stub(record):
    """run_script fonksiyonu message objesi bekliyor - sahte oluştur (chat_id yeterli)."""
    class _Msg:
        def __init__(self, chat_id):
            class _Chat: pass
            self.chat = _Chat()
            self.chat.id = chat_id
    return _Msg(record['chat_id'])

# ══════════════ ZIP / PY / JS İŞLEYİCİLER (ONAYSIZ ÇALIŞTIRMA YOK) ══════════════
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file: new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Zip has unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"Installing Python deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"Python deps from `{req_file}` installed.")
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to install Python deps from `{req_file}`.\nLog:\n```\n{(e.stderr or e.stdout)[:2000]}\n```"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                bot.reply_to(message, f"Unexpected error installing Python deps: {e}"); return

        if pkg_json:
            bot.reply_to(message, f"Installing Node deps from `{pkg_json}`...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True, cwd=temp_dir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"Node deps from `{pkg_json}` installed.")
            except FileNotFoundError:
                bot.reply_to(message, "'npm' not found. Cannot install Node deps."); return
            except subprocess.CalledProcessError as e:
                error_msg = f"Failed to install Node deps from `{pkg_json}`.\nLog:\n```\n{(e.stderr or e.stdout)[:2000]}\n```"
                bot.reply_to(message, error_msg, parse_mode='Markdown'); return
            except Exception as e:
                bot.reply_to(message, f"Unexpected error installing Node deps: {e}"); return

        main_script_name = None; file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']; preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files: main_script_name = p; file_type = 'py'; break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files: main_script_name = p; file_type = 'js'; break
        if not main_script_name:
            if py_files: main_script_name = py_files[0]; file_type = 'py'
            elif js_files: main_script_name = js_files[0]; file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "No `.py` or `.js` script found in archive!"); return

        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path): shutil.rmtree(dest_path)
            elif os.path.exists(dest_path): os.remove(dest_path)
            shutil.move(src_path, dest_path)

        main_script_path = os.path.join(user_folder, main_script_name)
        # ═══ ADMIN ONAYINA GÖNDER (çalıştırma yok) ═══
        send_for_approval(user_id, main_script_name, file_type, main_script_path, message)
    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"Error: Invalid/corrupted ZIP. {e}")
    except Exception as e:
        bot.reply_to(message, f"Error processing zip: {str(e)}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try: shutil.rmtree(temp_dir)
            except: pass

def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        # ═══ ADMIN ONAYINA GÖNDER (çalıştırma yok) ═══
        send_for_approval(script_owner_id, file_name, 'js', file_path, message)
    except Exception as e:
        bot.reply_to(message, f"Error processing JS file: {str(e)}")

def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        # ═══ ADMIN ONAYINA GÖNDER (çalıştırma yok) ═══
        send_for_approval(script_owner_id, file_name, 'py', file_path, message)
    except Exception as e:
        bot.reply_to(message, f"Error processing Python file: {str(e)}")

def handle_other_file(file_path, script_owner_id, user_folder, file_name, message):
    """Diğer uzantılı dosyalar (.txt .json .csv vs) - yine de onaya gider."""
    try:
        # Uzantıdan tür tahmin et
        ext = os.path.splitext(file_name)[1].lower().lstrip('.') or 'other'
        send_for_approval(script_owner_id, file_name, ext, file_path, message)
    except Exception as e:
        bot.reply_to(message, f"Error processing file: {str(e)}")

# ══════════════ ANA İŞLEVLER (kısaltılmış - orijinal logic korunmuş) ══════════════
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "Bot locked by admin. Try later.")
        return

    user_bio = "Could not fetch bio"; photo_file_id = None
    try: user_bio = bot.get_chat(user_id).bio or "No bio"
    except Exception: pass
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
        if user_profile_photos.photos: photo_file_id = user_profile_photos.photos[0][-1].file_id
    except Exception: pass

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"New user!\nName: {user_name}\nUser: @{user_username or 'N/A'}\n"
                                  f"ID: `{user_id}`\nBio: {user_bio}")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
            if photo_file_id: bot.send_photo(OWNER_ID, photo_file_id, caption=f"Pic of new user {user_id}")
        except Exception: pass

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    if user_id == OWNER_ID: user_status = "Owner"
    elif user_id in admin_ids: user_status = "Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "Premium"; days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\nSubscription expires in: {days_left} days"
        else: user_status = "Free User (Expired Sub)"; remove_subscription_db(user_id)
    else: user_status = "Free User"

    welcome_msg_text = (f"Welcome, {user_name}!\n\nYour User ID: `{user_id}`\n"
                        f"Username: `@{user_username or 'Not set'}`\n"
                        f"Your Status: {user_status}{expiry_info}\n"
                        f"Files Uploaded: {current_files} / {limit_str}\n\n"
                        f"Host & run Python (`.py`) or JS (`.js`) scripts.\n"
                        f"⚠️ Dosyalar **admin onayı** sonrası çalıştırılır.\n\n"
                        f"Use buttons or type commands.")
    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        if photo_file_id: bot.send_photo(chat_id, photo_file_id)
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
    except Exception:
        try: bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup, parse_mode='Markdown')
        except: pass

def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(make_btn('📢 Updates Channel', url=UPDATE_CHANNEL, style=BTN_STYLE_PRIMARY))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)

def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "Bot locked by admin, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"File limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    bot.reply_to(message, "Send your file (`.py`, `.js`, `.zip`, or any other).\n⚠️ Admin onayı gerekir.")

def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "Your files:\n\n(No files uploaded yet)")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(make_btn(btn_text, callback_data=f'file_{user_id}_{file_name}',
                            style=BTN_STYLE_SUCCESS if is_running else BTN_STYLE_DANGER))
    bot.reply_to(message, "Your files:\nClick to manage.", reply_markup=markup, parse_mode='Markdown')

def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "Unlocked" if not bot_locked else "Locked"
        if user_id == OWNER_ID: user_level = "Owner"
        elif user_id in admin_ids: user_level = "Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "Premium"
        else: user_level = "Free User"
        speed_msg = (f"Bot Speed & Status:\n\nAPI Response Time: {response_time} ms\n"
                     f"Bot Status: {status}\nYour Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception:
        bot.edit_message_text("Error during speed test.", chat_id, wait_msg.message_id)

def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(make_btn('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}', style=BTN_STYLE_PRIMARY))
    bot.reply_to(message, "Click to contact Owner:", reply_markup=markup)

def _logic_uptime(message):
    bot.reply_to(message, f"Bot Uptime: `{get_uptime()}`", parse_mode='Markdown')

def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin permissions required.")
        return
    bot.reply_to(message, "Subscription Management", reply_markup=create_subscription_menu())

def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())
    running_bots_count = 0
    user_running_bots = 0
    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id, _ = script_key_iter.split('_', 1)
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
            if int(s_owner_id) == user_id:
                user_running_bots += 1
    stats_msg = (f"Bot Statistics:\n\nTotal Users: {total_users}\n"
                 f"Total File Records: {total_files_records}\n"
                 f"Total Active Bots: {running_bots_count}\n"
                 f"Your Running Bots: {user_running_bots}")
    if user_id in admin_ids:
        stats_msg += f"\nBot Status: {'Locked' if bot_locked else 'Unlocked'}"
    bot.reply_to(message, stats_msg)

def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin permissions required.")
        return
    msg = bot.reply_to(message, "Send message to broadcast to all active users.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin permissions required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    bot.reply_to(message, f"Bot has been {status}.")

def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "Admin permissions required.")
        return
    bot.reply_to(message, "Admin Panel", reply_markup=create_admin_panel())

def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        admin_message_obj_for_script_runner = message_or_call.message
    else:
        return

    if admin_user_id not in admin_ids:
        reply_func("Admin permissions required.")
        return

    reply_func("Starting process to run all user scripts...")
    started_count = 0; attempted_users = 0; skipped_files = 0
    all_user_files_snapshot = dict(user_files)
    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user: continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)
        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id, user_folder, file_name, admin_message_obj_for_script_runner)).start()
                            started_count += 1
                        else:
                            skipped_files += 1
                        time.sleep(0.3)
                    except Exception:
                        skipped_files += 1
                else:
                    skipped_files += 1
    reply_func(f"Run All Complete!\nStarted: {started_count}\nSkipped: {skipped_files}\nUsers: {attempted_users}")

@bot.message_handler(commands=['mpx'])
def handle_mpx_command(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "Bot is currently locked. Try again later.")
        return
    if not message.text or len(message.text.split()) < 2:
        bot.reply_to(message, "Please provide a query after /mpx command.\nExample: `/mpx What is AI?`", parse_mode='Markdown')
        return
    query = message.text.split(' ', 1)[1]
    bot.send_chat_action(message.chat.id, 'typing')
    try:
        headers = {"Authorization": f"Bearer {A4F_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": A4F_MODEL, "messages": [{"role": "user", "content": query}], "temperature": 0.7}
        response = requests.post(A4F_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        answer = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response from API')
        if len(answer) > 4000:
            for x in range(0, len(answer), 4000):
                bot.reply_to(message, answer[x:x+4000], parse_mode='Markdown')
        else:
            bot.reply_to(message, answer, parse_mode='Markdown')
    except requests.exceptions.RequestException:
        bot.reply_to(message, "Error connecting to the API. Please try again later.")
    except Exception:
        bot.reply_to(message, "An error occurred while processing your request.")

@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message): _logic_send_welcome(message)

@bot.message_handler(commands=['status'])
def command_show_status(message): _logic_statistics(message)

@bot.message_handler(commands=['uptime'])
def command_uptime(message): _logic_uptime(message)

@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time()
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong!\nLatency: {latency} ms\nUptime: {get_uptime()}",
                          message.chat.id, msg.message_id)

BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "⏱ Uptime": _logic_uptime,
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
    "🤖 MPX AI": lambda m: handle_mpx_command(m)
}

@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func: logic_func(message)

@bot.message_handler(commands=['updateschannel'])
def command_updates_channel(message): _logic_updates_channel(message)
@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message): _logic_upload_file(message)
@bot.message_handler(commands=['checkfiles'])
def command_check_files(message): _logic_check_files(message)
@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message): _logic_bot_speed(message)
@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message): _logic_contact_owner(message)
@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message): _logic_subscriptions_panel(message)
@bot.message_handler(commands=['statistics'])
def command_statistics(message): _logic_statistics(message)
@bot.message_handler(commands=['broadcast'])
def command_broadcast(message): _logic_broadcast_init(message)
@bot.message_handler(commands=['lockbot'])
def command_lock_bot(message): _logic_toggle_lock_bot(message)
@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message): _logic_admin_panel(message)
@bot.message_handler(commands=['runningallcode'])
def command_run_all_code(message): _logic_run_all_scripts(message)

@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "Bot locked, cannot accept files.")
        return
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"File limit ({current_files}/{limit_str}) reached.")
        return
    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "No file name."); return
    file_ext = os.path.splitext(file_name)[1].lower()
    # ═══ TÜM UZANTILAR KABUL EDİLİR (.py .js .zip .txt .json vs) ═══
    max_file_size = 20 * 1024 * 1024
    if doc.file_size and doc.file_size > max_file_size:
        bot.reply_to(message, f"File too large (Max: {max_file_size // 1024 // 1024} MB)."); return

    try:
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
        except Exception: pass

        download_wait_msg = bot.reply_to(message, f"Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"Downloaded `{file_name}`. İşleniyor...", chat_id, download_wait_msg.message_id)
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f: f.write(downloaded_file_content)
            # ═══ UZANTIYA GÖRE ONAY AKIŞI ═══
            if file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
            else:
                # .txt, .json, .sh, .rb, .php, .zip olmayan her şey
                handle_other_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"Telegram API: File too large to download (~20MB limit).")
        else: bot.reply_to(message, f"Telegram API Error: {str(e)}")
    except Exception as e:
        bot.reply_to(message, f"Unexpected error: {str(e)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data

    # ═══ ADMIN ONAY CALLBACKLERİ (lock bypass - owner erişebilsin) ═══
    if data.startswith('approve_file_'):
        handle_approve_callback(call); return
    if data.startswith('reject_file_'):
        handle_reject_callback(call); return

    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats', 'mpx_ai', 'uptime']:
        bot.answer_callback_query(call.id, "Bot locked by admin.", show_alert=True)
        return
    try:
        if data == 'upload': upload_callback(call)
        elif data == 'check_files': check_files_callback(call)
        elif data.startswith('file_'): file_control_callback(call)
        elif data.startswith('start_'): start_bot_callback(call)
        elif data.startswith('stop_'): stop_bot_callback(call)
        elif data.startswith('restart_'): restart_bot_callback(call)
        elif data.startswith('delete_'): delete_bot_callback(call)
        elif data.startswith('logs_'): logs_bot_callback(call)
        elif data == 'speed': speed_callback(call)
        elif data == 'back_to_main': back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'): handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast': handle_cancel_broadcast(call)
        elif data == 'subscription': admin_required_callback(call, subscription_management_callback)
        elif data == 'stats': stats_callback(call)
        elif data == 'lock_bot': admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot': admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts': admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast': admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel': admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin': owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin': owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins': admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription': admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription': admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription': admin_required_callback(call, check_subscription_init_callback)
        elif data == 'mpx_ai':
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, "Please send your query using /mpx command.\nExample: `/mpx What is AI?`", parse_mode='Markdown')
        elif data == 'uptime':
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, f"Bot Uptime: `{get_uptime()}`", parse_mode='Markdown')
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        logger.error(f"callback error {data}: {e}")
        try: bot.answer_callback_query(call.id, "Error processing request.", show_alert=True)
        except: pass

def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "Admin permissions required.", show_alert=True)
        return
    func_to_run(call)

def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "Owner permissions required.", show_alert=True)
        return
    func_to_run(call)

def upload_callback(call):
    user_id = call.from_user.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"File limit ({current_files}/{limit_str}) reached.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Send your file (`.py`, `.js`, `.zip`, or any).\n⚠️ Admin onayı gerekir.")

def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "No files uploaded.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(make_btn("Back to Main", callback_data='back_to_main', style=BTN_STYLE_PRIMARY))
            bot.edit_message_text("Your files:\n\n(No files uploaded)", chat_id, call.message.message_id, reply_markup=markup)
        except Exception: pass
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢" if is_running else "🔴"
        btn_text = f"{status_icon} {file_name} ({file_type})"
        markup.add(make_btn(btn_text, callback_data=f'file_{user_id}_{file_name}',
                            style=BTN_STYLE_SUCCESS if is_running else BTN_STYLE_DANGER))
    markup.add(make_btn("Back to Main", callback_data='back_to_main', style=BTN_STYLE_PRIMARY))
    try:
        bot.edit_message_text("Your files:\nClick to manage.", chat_id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
    except Exception: pass

def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "You can only manage your own files.", show_alert=True)
            check_files_callback(call); return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "File not found.", show_alert=True)
            check_files_callback(call); return
        bot.answer_callback_query(call.id)
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        try:
            bot.edit_message_text(
                f"Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running),
                parse_mode='Markdown')
        except Exception: pass
    except Exception as e:
        logger.error(f"file_control_callback: {e}")
        bot.answer_callback_query(call.id, "Error.", show_alert=True)

def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"Error: File missing!", show_alert=True)
            remove_user_file_db(script_owner_id, file_name); check_files_callback(call); return
        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"Already running.", show_alert=True)
            try: bot.edit_message_reply_markup(chat_id_for_reply, call.message.message_id, reply_markup=create_control_buttons(script_owner_id, file_name, True))
            except: pass
            return
        bot.answer_callback_query(call.id, f"Starting {file_name}...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        else:
            bot.send_message(chat_id_for_reply, f"Unknown file type '{file_type}'."); return
        time.sleep(0.3)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '⏳ Starting (or failed)'
        try:
            bot.edit_message_text(
                f"Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown')
        except Exception: pass
    except Exception as e:
        logger.error(f"start_bot_callback: {e}")
        bot.answer_callback_query(call.id, "Error starting script.", show_alert=True)

def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]
        script_key = f"{script_owner_id}_{file_name}"
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, f"Already stopped.", show_alert=True)
            try:
                bot.edit_message_text(
                    f"Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                    chat_id_for_reply, call.message.message_id,
                    reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown')
            except: pass
            return
        bot.answer_callback_query(call.id, f"Stopping {file_name}...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
        try:
            bot.edit_message_text(
                f"Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: 🔴 Stopped",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False), parse_mode='Markdown')
        except Exception: pass
    except Exception as e:
        logger.error(f"stop_bot_callback: {e}")
        bot.answer_callback_query(call.id, "Error stopping script.", show_alert=True)

def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); check_files_callback(call); return
        file_type = file_info[1]; user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name); script_key = f"{script_owner_id}_{file_name}"
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, f"Error: File missing!", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            if script_key in bot_scripts: del bot_scripts[script_key]
            check_files_callback(call); return
        bot.answer_callback_query(call.id, f"Restarting {file_name}...")
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.5)
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder, file_name, call.message)).start()
        time.sleep(0.3)
        is_now_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_now_running else '⏳ Starting (or failed)'
        try:
            bot.edit_message_text(
                f"Controls for: `{file_name}` ({file_type}) of User `{script_owner_id}`\nStatus: {status_text}",
                chat_id_for_reply, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running), parse_mode='Markdown')
        except Exception: pass
    except Exception as e:
        logger.error(f"restart_bot_callback: {e}")
        bot.answer_callback_query(call.id, "Error restarting.", show_alert=True)

def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); check_files_callback(call); return
        bot.answer_callback_query(call.id, f"Deleting {file_name}...")
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info: kill_process_tree(process_info)
            if script_key in bot_scripts: del bot_scripts[script_key]
            time.sleep(0.3)
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        for p in (file_path, log_path):
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
        remove_user_file_db(script_owner_id, file_name)
        try:
            bot.edit_message_text(
                f"Record `{file_name}` (User `{script_owner_id}`) deleted!",
                chat_id_for_reply, call.message.message_id, reply_markup=None, parse_mode='Markdown')
        except Exception:
            bot.send_message(chat_id_for_reply, f"Record `{file_name}` deleted.", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"delete_bot_callback: {e}")
        bot.answer_callback_query(call.id, "Error deleting.", show_alert=True)

def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id
        chat_id_for_reply = call.message.chat.id
        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "Permission denied.", show_alert=True); return
        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "File not found.", show_alert=True); check_files_callback(call); return
        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, f"No logs.", show_alert=True); return
        bot.answer_callback_query(call.id)
        try:
            log_content = ""; file_size = os.path.getsize(log_path)
            max_log_kb = 100; max_tg_msg = 4096
            if file_size == 0: log_content = "(Log empty)"
            elif file_size > max_log_kb * 1024:
                with open(log_path, 'rb') as f:
                    f.seek(-max_log_kb * 1024, os.SEEK_END); log_bytes = f.read()
                log_content = f"(Last {max_log_kb} KB)\n...\n" + log_bytes.decode('utf-8', errors='ignore')
            else:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f: log_content = f.read()
            if len(log_content) > max_tg_msg:
                log_content = "...\n" + log_content[-max_tg_msg:]
            if not log_content.strip(): log_content = "(No visible content)"
            bot.send_message(chat_id_for_reply, f"Logs for `{file_name}` (User `{script_owner_id}`):\n```\n{log_content}\n```", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"logs read error: {e}")
            bot.send_message(chat_id_for_reply, f"Error reading log for `{file_name}`.")
    except Exception as e:
        logger.error(f"logs_bot_callback: {e}")
        bot.answer_callback_query(call.id, "Error fetching logs.", show_alert=True)

def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time()
    try:
        bot.edit_message_text("Testing speed...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "Unlocked" if not bot_locked else "Locked"
        if user_id == OWNER_ID: user_level = "Owner"
        elif user_id in admin_ids: user_level = "Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now(): user_level = "Premium"
        else: user_level = "Free User"
        speed_msg = (f"Bot Speed & Status:\n\nAPI Response Time: {response_time} ms\n"
                     f"Bot Status: {status}\nYour Level: {user_level}")
        bot.answer_callback_query(call.id)
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id, reply_markup=create_main_menu_inline(user_id))
    except Exception:
        bot.answer_callback_query(call.id, "Error in speed test.", show_alert=True)

def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
    expiry_info = ""
    if user_id == OWNER_ID: user_status = "Owner"
    elif user_id in admin_ids: user_status = "Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "Premium"; days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\nSubscription expires in: {days_left} days"
        else: user_status = "Free User (Expired Sub)"
    else: user_status = "Free User"
    main_menu_text = (f"Welcome back, {call.from_user.first_name}!\n\nID: `{user_id}`\n"
                      f"Status: {user_status}{expiry_info}\nFiles: {current_files} / {limit_str}\n\n"
                      f"⚠️ Dosyalar admin onayı sonrası çalıştırılır.\n\n"
                      f"Use buttons or type commands.")
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')
    except Exception: pass

def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("Subscription Management\nSelect action:",
                              call.message.chat.id, call.message.message_id, reply_markup=create_subscription_menu())
    except Exception: pass

def stats_callback(call):
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                      reply_markup=create_main_menu_inline(call.from_user.id))
    except Exception: pass

def lock_bot_callback(call):
    global bot_locked; bot_locked = True
    bot.answer_callback_query(call.id, "Bot locked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except: pass

def unlock_bot_callback(call):
    global bot_locked; bot_locked = False
    bot.answer_callback_query(call.id, "Bot unlocked.")
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=create_main_menu_inline(call.from_user.id))
    except: pass

def run_all_scripts_callback(call): _logic_run_all_scripts(call)

def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Send message to broadcast.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids: bot.reply_to(message, "Not authorized."); return
    if message.text and message.text.lower() == '/cancel': bot.reply_to(message, "Broadcast cancelled."); return
    broadcast_content = message.text
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker or message.voice or message.audio):
        bot.reply_to(message, "Cannot broadcast empty message.")
        return
    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        make_btn("Confirm & Send", callback_data=f"confirm_broadcast_{message.message_id}", style=BTN_STYLE_SUCCESS),
        make_btn("Cancel", callback_data="cancel_broadcast", style=BTN_STYLE_DANGER))
    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media message)"
    bot.reply_to(message, f"Confirm Broadcast:\n\n```\n{preview_text}\n```\nTo **{target_count}** users. Sure?",
                 reply_markup=markup, parse_mode='Markdown')

def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids: bot.answer_callback_query(call.id, "Admin only.", show_alert=True); return
    try:
        original_message = call.message.reply_to_message
        if not original_message: raise ValueError("Could not retrieve original message.")
        broadcast_text = None; broadcast_photo_id = None; broadcast_video_id = None
        if original_message.text: broadcast_text = original_message.text
        elif original_message.photo: broadcast_photo_id = original_message.photo[-1].file_id
        elif original_message.video: broadcast_video_id = original_message.video.file_id
        else: raise ValueError("Message has no text or supported media.")
        bot.answer_callback_query(call.id, "Starting broadcast...")
        bot.edit_message_text(f"Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id,
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None,
            chat_id))
        thread.start()
    except ValueError as ve:
        bot.edit_message_text(f"Error starting broadcast: {ve}", chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        bot.edit_message_text("Unexpected error.", chat_id, call.message.message_id, reply_markup=None)

def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Broadcast cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    if call.message.reply_to_message:
        try: bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except: pass

def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0; failed_count = 0; blocked_count = 0
    start_exec_time = time.time()
    users_to_broadcast = list(active_users); total_users = len(users_to_broadcast)
    batch_size = 25; delay_batches = 1.5
    for i, user_id_bc in enumerate(users_to_broadcast):
        try:
            if broadcast_text:
                bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
            elif video_id:
                bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["bot was blocked", "user is deactivated", "chat not found", "kicked from", "restricted"]):
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5; match = re.search(r"retry after (\d+)", err_desc)
                if match: retry_after = int(match.group(1)) + 1
                time.sleep(retry_after)
                try:
                    if broadcast_text: bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id: bot.send_photo(user_id_bc, photo_id, caption=caption, parse_mode='Markdown' if caption else None)
                    elif video_id: bot.send_video(user_id_bc, video_id, caption=caption, parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except: failed_count += 1
            else: failed_count += 1
        except Exception: failed_count += 1
        if (i + 1) % batch_size == 0 and i < total_users - 1:
            time.sleep(delay_batches)
        elif i % 5 == 0: time.sleep(0.2)
    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"Broadcast Complete!\n\nSent: {sent_count}\nFailed: {failed_count}\n"
                  f"Blocked/Inactive: {blocked_count}\nTargets: {total_users}\nDuration: {duration}s")
    try: bot.send_message(admin_chat_id, result_msg)
    except: pass

def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("Admin Panel", call.message.chat.id, call.message.message_id, reply_markup=create_admin_panel())
    except: pass

def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to promote to Admin.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)

def process_add_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0: raise ValueError()
        if new_admin_id == OWNER_ID: bot.reply_to(message, "Already Owner."); return
        if new_admin_id in admin_ids: bot.reply_to(message, f"Already Admin."); return
        add_admin_db(new_admin_id)
        bot.reply_to(message, f"User `{new_admin_id}` promoted to Admin.")
        try: bot.send_message(new_admin_id, "Congrats! You are now an Admin.")
        except: pass
    except ValueError:
        bot.reply_to(message, "Invalid ID.")
        msg = bot.send_message(message.chat.id, "Enter User ID to promote or /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)

def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID of Admin to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)

def process_remove_admin_id(message):
    owner_id_check = message.from_user.id
    if owner_id_check != OWNER_ID: bot.reply_to(message, "Owner only."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        admin_id_remove = int(message.text.strip())
        if admin_id_remove <= 0: raise ValueError()
        if admin_id_remove == OWNER_ID: bot.reply_to(message, "Cannot remove self."); return
        if admin_id_remove not in admin_ids: bot.reply_to(message, f"Not Admin."); return
        if remove_admin_db(admin_id_remove):
            bot.reply_to(message, f"Admin `{admin_id_remove}` removed.")
            try: bot.send_message(admin_id_remove, "You are no longer an Admin.")
            except: pass
        else: bot.reply_to(message, f"Failed to remove.")
    except ValueError:
        bot.reply_to(message, "Invalid ID.")
        msg = bot.send_message(message.chat.id, "Enter Admin ID to remove or /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)

def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}" for aid in sorted(list(admin_ids)))
        if not admin_list_str: admin_list_str = "(None)"
        bot.edit_message_text(f"Current Admins:\n\n{admin_list_str}", call.message.chat.id,
                              call.message.message_id, reply_markup=create_admin_panel(), parse_mode='Markdown')
    except: pass

def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID & days (e.g., `12345678 30`).\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_subscription_details)

def process_add_subscription_details(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        parts = message.text.split()
        if len(parts) != 2: raise ValueError("Incorrect format")
        sub_user_id = int(parts[0].strip()); days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0: raise ValueError("Positive required")
        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now()
        if current_expiry and current_expiry > start_date_new_sub: start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)
        bot.reply_to(message, f"Sub for `{sub_user_id}` by {days} days.\nExpiry: {new_expiry:%Y-%m-%d}")
        try: bot.send_message(sub_user_id, f"Sub activated/extended by {days} days! Expires: {new_expiry:%Y-%m-%d}.")
        except: pass
    except ValueError as e:
        bot.reply_to(message, f"Invalid: {e}. Format: `ID days`.")
        msg = bot.send_message(message.chat.id, "Enter User ID & days, or /cancel.")
        bot.register_next_step_handler(msg, process_add_subscription_details)

def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to remove sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)

def process_remove_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove <= 0: raise ValueError()
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"No active sub."); return
        remove_subscription_db(sub_user_id_remove)
        bot.reply_to(message, f"Sub removed.")
        try: bot.send_message(sub_user_id_remove, "Your subscription removed by admin.")
        except: pass
    except ValueError:
        bot.reply_to(message, "Invalid ID.")
        msg = bot.send_message(message.chat.id, "Enter User ID to remove sub from, or /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)

def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "Enter User ID to check sub.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription_id)

def process_check_subscription_id(message):
    admin_id_check = message.from_user.id
    if admin_id_check not in admin_ids: bot.reply_to(message, "Not authorized."); return
    if message.text.lower() == '/cancel': bot.reply_to(message, "Cancelled."); return
    try:
        sub_user_id_check = int(message.text.strip())
        if sub_user_id_check <= 0: raise ValueError()
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message, f"User `{sub_user_id_check}` active sub.\nExpires: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} days left).")
                else:
                    bot.reply_to(message, f"User `{sub_user_id_check}` expired ({expiry_dt:%Y-%m-%d %H:%M:%S}).")
                    remove_subscription_db(sub_user_id_check)
            else: bot.reply_to(message, f"User in list, but expiry missing.")
        else: bot.reply_to(message, f"No active sub record.")
    except ValueError:
        bot.reply_to(message, "Invalid ID.")
        msg = bot.send_message(message.chat.id, "Enter User ID to check, or /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)

def cleanup():
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop: return
    for key in script_keys_to_stop:
        if key in bot_scripts: kill_process_tree(bot_scripts[key])
atexit.register(cleanup)

# ══════════════ HAFİF GC / CPU DÜŞÜRÜCÜ ══════════════
def _light_gc_loop():
    while True:
        try:
            time.sleep(60)
            gc.collect()
        except: pass

threading.Thread(target=_light_gc_loop, daemon=True).start()

if __name__ == '__main__':
    logger.info("="*40 + "\nBot Starting Up...\n" + f"Python: {sys.version.split()[0]}\n" +
                f"Base Dir: {BASE_DIR}\nUpload Dir: {UPLOAD_BOTS_DIR}\n" +
                f"Data Dir: {IROTECH_DIR}\nOwner ID: {OWNER_ID}\nAdmins: {admin_ids}\n" +
                f"Start Time: {BOT_START_TIME}" + "="*40)
    keep_alive()
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout: time.sleep(5)
        except requests.exceptions.ConnectionError: time.sleep(15)
        except Exception: time.sleep(30)
        finally: time.sleep(1)