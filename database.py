import sqlite3
import json
import hashlib
import numpy as np
from datetime import datetime

from config import DB_NAME

class Database:
    def __init__(self, db_name=DB_NAME):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)')
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL, receiver TEXT NOT NULL, content TEXT NOT NULL, timestamp TEXT NOT NULL)')
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_username TEXT NOT NULL, contact_username TEXT NOT NULL, UNIQUE(owner_username, contact_username))')
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, creator TEXT NOT NULL)')
        self.cursor.execute(
            'CREATE TABLE IF NOT EXISTS group_members (group_name TEXT NOT NULL, username TEXT NOT NULL, UNIQUE(group_name, username))')

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                month_key TEXT NOT NULL,
                grid_data TEXT NOT NULL,
                UNIQUE(username, chat_id, month_key)
            )
        ''')

        for col, dtype in [('status', 'INTEGER DEFAULT 0'), ('reply_text', 'TEXT DEFAULT ""'),
                           ('is_edited', 'INTEGER DEFAULT 0'), ('is_deleted', 'INTEGER DEFAULT 0'),
                           ('reactions', 'TEXT DEFAULT "{}"')]:
            try:
                self.cursor.execute(f"ALTER TABLE messages ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass

        try:
            self.cursor.execute("ALTER TABLE contacts ADD COLUMN is_pinned INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass



        self.conn.commit()

    def _hash_password(self, password):
        return hashlib.sha256(password.encode()).hexdigest()

    def register_user(self, username, password):
        try:
            self.cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                                (username, self._hash_password(password)))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def check_credentials(self, username, password):
        self.cursor.execute('SELECT * FROM users WHERE username = ? AND password_hash = ?',
                            (username, self._hash_password(password)))
        return self.cursor.fetchone() is not None

    def user_exists(self, username):
        self.cursor.execute('SELECT 1 FROM users WHERE username = ?', (username,))
        return self.cursor.fetchone() is not None

    def add_contact(self, owner, contact):
        if not self.user_exists(contact): return False, "Пользователь не найден"
        if owner == contact: return False, "Нельзя добавить самого себя"
        try:
            self.cursor.execute('INSERT INTO contacts (owner_username, contact_username) VALUES (?, ?)',
                                (owner, contact))
            self.conn.commit()
            return True, f"Контакт {contact} добавлен"
        except sqlite3.IntegrityError:
            return False, "Уже в списке"

    def create_group(self, name, creator, members):
        if not name.startswith("#"): name = "#" + name
        try:
            self.cursor.execute('INSERT INTO groups (name, creator) VALUES (?, ?)', (name, creator))
            self.cursor.execute('INSERT INTO group_members (group_name, username) VALUES (?, ?)', (name, creator))
            for member in members:
                if self.user_exists(member) and member != creator:
                    try:
                        self.cursor.execute('INSERT INTO group_members (group_name, username) VALUES (?, ?)',
                                            (name, member))
                    except sqlite3.IntegrityError:
                        pass
            self.conn.commit()
            return True, name
        except sqlite3.IntegrityError:
            return False, "Такая группа уже существует"

    def get_group_members(self, group_name):
        self.cursor.execute('SELECT username FROM group_members WHERE group_name = ?', (group_name,))
        return [row[0] for row in self.cursor.fetchall()]

    def add_group_members(self, group_name, new_members):
        added = []
        errors = []
        for member in new_members:
            if not self.user_exists(member):
                errors.append(f"{member} не найден")
                continue
            try:
                self.cursor.execute('INSERT INTO group_members (group_name, username) VALUES (?, ?)',
                                    (group_name, member))
                added.append(member)
            except sqlite3.IntegrityError:
                errors.append(f"{member} уже в группе")
        self.conn.commit()
        return added, errors

    def toggle_pin_contact(self, owner, contact, pinned):
        try:
            self.cursor.execute('INSERT OR IGNORE INTO contacts (owner_username, contact_username) VALUES (?, ?)',
                                (owner, contact))
            self.cursor.execute('UPDATE contacts SET is_pinned = ? WHERE owner_username = ? AND contact_username = ?',
                                (1 if pinned else 0, owner, contact))
            self.conn.commit()
        except Exception:
            pass

    def delete_chat(self, user1, user2):
        if user2.startswith("#"):
            self.cursor.execute('DELETE FROM group_members WHERE group_name = ? AND username = ?', (user2, user1))
        else:
            self.cursor.execute(
                'DELETE FROM messages WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?)',
                (user1, user2, user2, user1))
            self.cursor.execute('DELETE FROM contacts WHERE owner_username = ? AND contact_username = ?',
                                (user1, user2))
        self.conn.commit()

    def get_contacts(self, username):
        self.cursor.execute('SELECT contact_username, is_pinned FROM contacts WHERE owner_username = ?', (username,))
        explicit_contacts = {row[0]: row[1] for row in self.cursor.fetchall()}
        self.cursor.execute(
            '''SELECT receiver FROM messages WHERE sender = ? AND receiver NOT LIKE '#%' UNION SELECT sender FROM messages WHERE receiver = ? AND sender NOT LIKE '#%' ''',
            (username, username))
        chat_partners = {row[0]: 0 for row in self.cursor.fetchall()}
        self.cursor.execute('SELECT group_name FROM group_members WHERE username = ?', (username,))
        for row in self.cursor.fetchall(): chat_partners[row[0]] = 0
        chat_partners.update(explicit_contacts)
        return chat_partners

    def get_unread_counts(self, username):
        self.cursor.execute('SELECT sender, COUNT(*) FROM messages WHERE receiver = ? AND status = 0 GROUP BY sender',
                            (username,))
        counts = {row[0]: row[1] for row in self.cursor.fetchall()}
        self.cursor.execute(
            '''SELECT receiver, COUNT(*) FROM messages WHERE receiver LIKE '#%' AND status = 0 AND sender != ? AND receiver IN (SELECT group_name FROM group_members WHERE username = ?) GROUP BY receiver''',
            (username, username))
        for row in self.cursor.fetchall(): counts[row[0]] = counts.get(row[0], 0) + row[1]
        return counts

    def save_message(self, sender, receiver, content, reply_text=""):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            'INSERT INTO messages (sender, receiver, content, timestamp, status, reply_text, is_edited, is_deleted) VALUES (?, ?, ?, ?, 0, ?, 0, 0)',
            (sender, receiver, content, timestamp, reply_text))
        self.conn.commit()
        return self.cursor.lastrowid

    def get_chat_history(self, user1, user2):
        if user2.startswith("#"):
            self.cursor.execute(
                'SELECT id, sender, content, timestamp, status, reply_text, is_edited, is_deleted, COALESCE(reactions, "{}") FROM messages WHERE receiver = ? ORDER BY id',
                (user2,))
        else:
            self.cursor.execute(
                'SELECT id, sender, content, timestamp, status, reply_text, is_edited, is_deleted, COALESCE(reactions, "{}") FROM messages WHERE (sender = ? AND receiver = ?) OR (sender = ? AND receiver = ?) ORDER BY id',
                (user1, user2, user2, user1))
        return self.cursor.fetchall()

    def mark_as_read(self, sender, receiver):
        if sender.startswith("#"):
            self.cursor.execute('UPDATE messages SET status=1 WHERE receiver=? AND status=0', (sender,))
        else:
            self.cursor.execute('UPDATE messages SET status=1 WHERE sender=? AND receiver=? AND status=0',
                                (sender, receiver))
        self.conn.commit()

    def edit_message(self, msg_id, new_content):
        self.cursor.execute('UPDATE messages SET content=?, is_edited=1 WHERE id=?', (new_content, msg_id))
        self.conn.commit()

    def delete_message(self, msg_id):
        self.cursor.execute('UPDATE messages SET is_deleted=1, content="[Сообщение удалено]" WHERE id=?', (msg_id,))
        self.conn.commit()

    def save_schedule_grid(self, username, chat_id, month_key, grid_list):
        self.cursor.execute('''
            INSERT OR REPLACE INTO schedules (username, chat_id, month_key, grid_data)
            VALUES (?, ?, ?, ?)
        ''', (username, chat_id, month_key, json.dumps(grid_list)))
        self.conn.commit()

    def get_chat_schedules(self, chat_id, participants, month_key):
        self.cursor.execute('''
            SELECT username, grid_data FROM schedules 
            WHERE chat_id = ? AND month_key = ?
        ''', (chat_id, month_key))

        saved_data = {row[0]: row[1] for row in self.cursor.fetchall()}
        results = []
        for nick in participants:
            if nick in saved_data:
                grid = np.array(json.loads(saved_data[nick]))
            else:
                grid = np.zeros((7, 24))
            results.append({"nick": nick, "grid": grid})
        return results

    def toggle_reaction(self, msg_id, username, reaction):
        self.cursor.execute('SELECT reactions FROM messages WHERE id = ?', (msg_id,))
        row = self.cursor.fetchone()
        if not row: return "{}"

        try:
            reactions = json.loads(row[0] or "{}")
        except:
            reactions = {}

        if reaction not in reactions:
            reactions[reaction] = []

        if username in reactions[reaction]:
            reactions[reaction].remove(username)
            if not reactions[reaction]:
                del reactions[reaction]
        else:
            reactions[reaction].append(username)

        new_reactions = json.dumps(reactions)
        self.cursor.execute('UPDATE messages SET reactions=? WHERE id=?', (new_reactions, msg_id))
        self.conn.commit()
        return new_reactions

    def close(self):
        self.conn.close()