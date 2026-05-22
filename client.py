import asyncio
import json
import os
import threading
import platform
import time
from datetime import datetime
import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox
import websockets
from websockets.exceptions import ConnectionClosed
from PIL import Image

import numpy as np
import matplotlib

matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

from config import SERVER_HOST, SERVER_PORT, CONFIG_FILE
from scheduler import InteractiveScheduler


class LoginWindow(ctk.CTkToplevel):
    def __init__(self, parent, client_app):
        super().__init__(parent)
        self.client_app = client_app
        self.title("Вход в Мессенджер")
        self.geometry("300x350")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.label = ctk.CTkLabel(self, text="Авторизация", font=ctk.CTkFont(size=20, weight="bold"))
        self.label.pack(pady=(20, 10))

        self.username_entry = ctk.CTkEntry(self, placeholder_text="Имя пользователя")
        self.username_entry.pack(pady=10, padx=20, fill="x")

        self.password_entry = ctk.CTkEntry(self, placeholder_text="Пароль", show="*")
        self.password_entry.pack(pady=10, padx=20, fill="x")

        self.login_btn = ctk.CTkButton(self, text="Войти", command=self.login)
        self.login_btn.pack(pady=10)

        self.register_btn = ctk.CTkButton(self, text="Регистрация", fg_color="transparent", border_width=1,
                                          command=self.register)
        self.register_btn.pack(pady=5)

        self.error_label = ctk.CTkLabel(self, text="", text_color="red")
        self.error_label.pack(pady=5)

        if "last_username" in self.client_app.config:
            self.username_entry.insert(0, self.client_app.config["last_username"])
        self.bind('<Return>', lambda event: self.login())

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            self.error_label.configure(text="Введите логин и пароль")
            return
        self.login_btn.configure(state="disabled")
        self.client_app.password = password
        self.client_app.send_to_server({"type": "login", "username": username, "password": password})

    def register(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            self.error_label.configure(text="Введите логин и пароль")
            return
        self.register_btn.configure(state="disabled")
        self.client_app.send_to_server({"type": "register", "username": username, "password": password})

    def show_error(self, message):
        self.error_label.configure(text=message)
        self.login_btn.configure(state="normal")
        self.register_btn.configure(state="normal")


class MessengerClient(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Schedule & Chat Pro")
        self.geometry("1000x700")
        self.minsize(800, 500)
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.websocket = None
        self.loop = asyncio.new_event_loop()
        self.username = None
        self.password = None
        self.current_chat_user = None

        self.users_status = {}
        self.unread_counts = {}
        self.message_bubbles = {}
        self.temp_to_real_ids = {}
        self.current_history_data = []

        self.typing_timer = None
        self.last_typing_time = 0
        self.reply_to_data = ""
        self.editing_msg_id = None
        self.active_context_menu = None

        # Глобальная переменная для контроля всплывающих окон
        self.active_tooltip = None

        self.scheduler_obj = None

        self.config = self.load_config()
        self.server_host = self.config.get("server_host", SERVER_HOST)
        self.server_port = self.config.get("server_port", SERVER_PORT)

        self.load_emoji_images()

        self.setup_ui()
        self.msg_queue = []
        self.network_thread = threading.Thread(target=self.run_asyncio_loop, daemon=True)
        self.network_thread.start()
        self.check_queue()

        self.bind_all("<Button-1>", self.close_menu_on_click, add="+")
        self.withdraw()
        self.login_window = LoginWindow(self, self)

    def load_emoji_images(self):
        self.emoji_images = {}
        emoji_files = {
            "👍": "like.png", "❤️": "heart.png", "😂": "laugh.png",
            "😲": "wow.png", "😢": "cry.png", "👏": "clap.png"
        }

        for emoji, filename in emoji_files.items():
            path = os.path.join("emojis", filename)
            if os.path.exists(path):
                img = Image.open(path)
                self.emoji_images[emoji] = ctk.CTkImage(light_image=img, dark_image=img, size=(18, 18))
            else:
                self.emoji_images[emoji] = None

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def save_config(self):
        self.config["last_username"] = self.username
        with open(CONFIG_FILE, 'w') as f: json.dump(self.config, f)

    def setup_ui(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(3, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="Чаты", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.sidebar_buttons = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.sidebar_buttons.grid(row=1, column=0, padx=15, pady=(0, 10), sticky="ew")
        self.sidebar_buttons.grid_columnconfigure((0, 1), weight=1)

        self.add_contact_btn = ctk.CTkButton(self.sidebar_buttons, text="👤 Контакт", fg_color="#2B5278",
                                             hover_color="#1A334B", command=self.prompt_add_contact)
        self.add_contact_btn.grid(row=0, column=0, padx=(0, 2), sticky="ew")
        self.add_group_btn = ctk.CTkButton(self.sidebar_buttons, text="👥 Группа", fg_color="#2B5278",
                                           hover_color="#1A334B", command=self.prompt_create_group)
        self.add_group_btn.grid(row=0, column=1, padx=(2, 0), sticky="ew")

        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="Подключение...", text_color="orange")
        self.status_label.grid(row=2, column=0, padx=20, pady=(0, 10))

        self.contacts_scroll = ctk.CTkScrollableFrame(self.sidebar_frame)
        self.contacts_scroll.grid(row=3, column=0, sticky="nsew", padx=10, pady=10)

        self.settings_frame = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        self.settings_frame.grid(row=4, column=0, padx=20, pady=20)
        self.theme_switch = ctk.CTkSwitch(self.settings_frame, text="Темная тема", command=self.change_theme)
        self.theme_switch.pack()
        if ctk.get_appearance_mode() == "Dark": self.theme_switch.select()

        self.right_frame = ctk.CTkFrame(self, corner_radius=0)
        self.right_frame.grid(row=0, column=1, sticky="nsew")
        self.right_frame.grid_rowconfigure(1, weight=1)
        self.right_frame.grid_columnconfigure(0, weight=1)

        self.chat_header = ctk.CTkFrame(self.right_frame, height=50, corner_radius=0)
        self.chat_header.grid(row=0, column=0, sticky="ew")
        self.chat_header.grid_columnconfigure(2, weight=1)

        self.chat_header_label = ctk.CTkLabel(self.chat_header, text="Выберите чат для начала общения",
                                              font=ctk.CTkFont(size=16, weight="bold"))
        self.chat_header_label.grid(row=0, column=0, pady=10, padx=20, sticky="w")
        self.typing_label = ctk.CTkLabel(self.chat_header, text="", font=ctk.CTkFont(size=12, slant="italic"),
                                         text_color="gray")
        self.typing_label.grid(row=0, column=1, pady=10, padx=10, sticky="w")

        self.view_var = tk.StringVar(value="chat")
        self.view_switch = ctk.CTkSegmentedButton(self.chat_header, values=["💬 Чат", "📅 Планер"],
                                                  variable=self.view_var, command=self.on_view_change)
        self.view_switch.grid(row=0, column=2, padx=10)
        self.view_switch.grid_remove()

        self.close_chat_btn = ctk.CTkButton(self.chat_header, text="✖ Закрыть", width=80, fg_color="transparent",
                                            text_color="#FF5555", hover_color=("gray80", "gray20"),
                                            command=self.close_chat)
        self.close_chat_btn.grid(row=0, column=3, padx=20)
        self.close_chat_btn.grid_remove()

        self.add_member_btn = ctk.CTkButton(self.chat_header, text="➕ Добавить", width=80, fg_color="transparent",
                                            text_color="#5eb5f7", hover_color=("gray80", "gray20"),
                                            command=self.prompt_add_group_members)
        self.add_member_btn.grid(row=0, column=4, padx=(0, 20))
        self.add_member_btn.grid_remove()

        self.chat_container = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.chat_container.grid(row=1, column=0, sticky="nsew")
        self.chat_container.grid_rowconfigure(0, weight=1)
        self.chat_container.grid_columnconfigure(0, weight=1)

        self.messages_scroll = ctk.CTkScrollableFrame(self.chat_container)
        self.messages_scroll.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.reply_frame = ctk.CTkFrame(self.chat_container, height=40, fg_color=("gray85", "gray20"), corner_radius=0)
        self.reply_frame.grid_columnconfigure(0, weight=1)
        self.reply_info_label = ctk.CTkLabel(self.reply_frame, text="", font=ctk.CTkFont(size=12, weight="bold"),
                                             anchor="w")
        self.reply_info_label.grid(row=0, column=0, padx=20, pady=(5, 0), sticky="ew")
        self.reply_text_label = ctk.CTkLabel(self.reply_frame, text="", font=ctk.CTkFont(size=11), text_color="gray",
                                             anchor="w")
        self.reply_text_label.grid(row=1, column=0, padx=20, pady=(0, 5), sticky="ew")
        self.cancel_reply_btn = ctk.CTkButton(self.reply_frame, text="✖", width=30, fg_color="transparent",
                                              text_color="gray", command=self.cancel_reply_edit)
        self.cancel_reply_btn.grid(row=0, column=1, rowspan=2, padx=10)

        self.input_frame = ctk.CTkFrame(self.chat_container, height=60, corner_radius=0)
        self.input_frame.grid(row=2, column=0, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.msg_entry = ctk.CTkEntry(self.input_frame, placeholder_text="Введите сообщение...", state="disabled")
        self.msg_entry.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="ew")
        self.msg_entry.bind('<Return>', lambda event: self.send_chat_message())
        self.msg_entry.bind('<KeyRelease>', self.on_key_release_typing)

        self.send_btn = ctk.CTkButton(self.input_frame, text="Отправить", width=100, command=self.send_chat_message,
                                      state="disabled")
        self.send_btn.grid(row=0, column=1, padx=(5, 10), pady=10)

        self.schedule_container = ctk.CTkFrame(self.right_frame, fg_color="transparent")
        self.schedule_container.grid(row=1, column=0, sticky="nsew")
        self.schedule_container.grid_remove()

    def on_view_change(self, value):
        if value == "💬 Чат":
            self.schedule_container.grid_remove()
            self.chat_container.grid()
        elif value == "📅 Планер":
            self.chat_container.grid_remove()
            self.schedule_container.grid()
            if not self.scheduler_obj:
                self.send_to_server({"type": "get_schedule", "chat_id": self.current_chat_user})

    def send_schedule_update_to_server(self, edited_nick, grid_list):
        if self.current_chat_user:
            self.send_to_server({
                "type": "update_schedule",
                "chat_id": self.current_chat_user,
                "nick": edited_nick,
                "grid": grid_list
            })

    def change_theme(self):
        if self.theme_switch.get() == 1:
            ctk.set_appearance_mode("Dark")
        else:
            ctk.set_appearance_mode("Light")

    def prompt_add_contact(self):
        d = ctk.CTkInputDialog(text="Введите логин:", title="Добавление контакта")
        if (v := d.get_input()): self.send_to_server({"type": "add_contact", "contact": v.strip()})

    def prompt_create_group(self):
        contacts = [u for u in self.users_status.keys() if not u.startswith("#")]
        if not contacts:
            messagebox.showwarning("Внимание", "У вас нет контактов для добавления в группу.")
            return

        d = ctk.CTkToplevel(self)
        d.title("Создать группу")
        d.geometry("380x420")
        d.transient(self)
        d.grab_set()

        ctk.CTkLabel(d, text="Название группы:", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 5))
        n_e = ctk.CTkEntry(d, placeholder_text="Например: Друзья", width=280)
        n_e.pack(pady=5)

        ctk.CTkLabel(d, text="Выберите участников:", font=ctk.CTkFont(weight="bold")).pack(pady=(15, 5))

        scroll = ctk.CTkScrollableFrame(d, width=260, height=150)
        scroll.pack(pady=5)

        checkboxes = {}
        for c in contacts:
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(scroll, text=c, variable=var)
            cb.pack(anchor="w", pady=2, padx=5)
            checkboxes[c] = var

        def submit():
            nm = n_e.get().strip()
            mm = [c for c, var in checkboxes.items() if var.get()]
            if not nm:
                messagebox.showerror("Ошибка", "Введите название", parent=d)
                return
            if not mm:
                messagebox.showerror("Ошибка", "Выберите хотя бы одного участника", parent=d)
                return
            self.send_to_server({"type": "create_group", "group_name": nm, "members": mm})
            d.destroy()

        ctk.CTkButton(d, text="Создать", command=submit, width=200).pack(pady=(25, 10))

    def prompt_add_group_members(self):
        if not self.current_chat_user or not self.current_chat_user.startswith("#"):
            return

        contacts = [u for u in self.users_status.keys() if not u.startswith("#")]
        if not contacts:
            messagebox.showwarning("Внимание", "У вас нет доступных контактов.")
            return

        d = ctk.CTkToplevel(self)
        d.title(f"Добавить в {self.current_chat_user}")
        d.geometry("300x350")
        d.transient(self)
        d.grab_set()

        ctk.CTkLabel(d, text="Выберите контакты:", font=ctk.CTkFont(weight="bold")).pack(pady=(20, 10))

        scroll = ctk.CTkScrollableFrame(d, width=240, height=180)
        scroll.pack(pady=5)

        checkboxes = {}
        for c in contacts:
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(scroll, text=c, variable=var)
            cb.pack(anchor="w", pady=2, padx=5)
            checkboxes[c] = var

        def submit():
            mm = [c for c, var in checkboxes.items() if var.get()]
            if not mm:
                messagebox.showerror("Ошибка", "Выберите хотя бы одного участника", parent=d)
                return
            self.send_to_server({"type": "add_group_members", "group_name": self.current_chat_user, "members": mm})
            d.destroy()

        ctk.CTkButton(d, text="Добавить", command=submit, width=200).pack(pady=(20, 10))

    async def network_task(self):
        actual_host = "127.0.0.1" if self.server_host == "0.0.0.0" else self.server_host
        protocol = "wss" if str(self.server_port) == "443" else "ws"
        uri = f"{protocol}://{actual_host}:{self.server_port}"
        headers = {"ngrok-skip-browser-warning": "true"}

        while True:
            try:
                self.queue_to_ui(lambda: self.update_connection_status("Подключение...", "orange"))

                async with websockets.connect(uri, additional_headers=headers) as ws:
                    self.websocket = ws
                    self.queue_to_ui(lambda: self.update_connection_status("Подключено", "green"))
                    if self.username and self.password:
                        await ws.send(
                            json.dumps({"type": "login", "username": self.username, "password": self.password}))
                    async for message in ws:
                        data = json.loads(message)
                        self.process_server_message(data)
            except (ConnectionClosed, ConnectionRefusedError, OSError) as e:
                self.websocket = None
                self.queue_to_ui(lambda: self.update_connection_status("Нет связи. Переподключение...", "red"))
                await asyncio.sleep(3)

    def run_asyncio_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.network_task())

    def queue_to_ui(self, func):
        self.msg_queue.append(func)

    def check_queue(self):
        while self.msg_queue: self.msg_queue.pop(0)()
        self.after(100, self.check_queue)

    def send_to_server(self, data):
        if self.websocket:
            asyncio.run_coroutine_threadsafe(self.websocket.send(json.dumps(data)), self.loop)
        else:
            messagebox.showerror("Ошибка", "Нет подключения")
            if hasattr(self, 'login_window') and self.login_window.winfo_exists():
                self.login_window.login_btn.configure(state="normal")
                self.login_window.register_btn.configure(state="normal")

    def process_server_message(self, data):
        msg_type = data.get("type")
        if msg_type == "login_result":
            if data["success"]:
                self.username = data["username"];
                self.save_config();
                self.queue_to_ui(self.on_login_success)
            else:
                self.queue_to_ui(lambda: self.login_window.show_error("Неверный логин или пароль"))
        elif msg_type == "register_result":
            if data["success"]:
                self.queue_to_ui(lambda: messagebox.showinfo("Успех",
                                                             "Регистрация успешна! Теперь вы можете войти."));
                self.queue_to_ui(
                    lambda: self.login_window.show_error(""))
            else:
                self.queue_to_ui(lambda: self.login_window.show_error("Пользователь уже существует"))
        elif msg_type == "reaction_updated":
            self.queue_to_ui(lambda d=data: self.update_reactions_ui(d["msg_id"], d["reactions"]))

        elif msg_type == "add_contact_result":
            if data["success"]:
                self.queue_to_ui(lambda: messagebox.showinfo("Успех", data["message"]))
            else:
                self.queue_to_ui(lambda: messagebox.showerror("Ошибка", data["message"]))
        elif msg_type == "create_group_result":
            if data["success"]:
                self.queue_to_ui(lambda: messagebox.showinfo("Успех", f"Группа {data['message']} создана!"))
            else:
                self.queue_to_ui(lambda: messagebox.showerror("Ошибка", data["message"]))
        elif msg_type == "add_group_members_result":
            if data["success"]:
                self.queue_to_ui(lambda: messagebox.showinfo("Успех", data["message"]))
            else:
                self.queue_to_ui(lambda: messagebox.showerror("Ошибка", data["message"]))
        elif msg_type == "contacts_list":
            self.users_status = data["contacts"]
            if "unread_counts" in data: self.unread_counts = data["unread_counts"]
            self.queue_to_ui(self.update_contacts_ui)
        elif msg_type == "message_sent":
            self.queue_to_ui(lambda d=data: self.confirm_message_sent(d))
        elif msg_type == "read_receipt":
            self.queue_to_ui(lambda d=data: self.process_read_receipt(d["reader"]))
        elif msg_type == "typing":
            self.queue_to_ui(lambda d=data: self.show_typing_indicator(d["sender"], data.get("group")))
        elif msg_type in ["edit_message", "delete_message"]:
            self.queue_to_ui(lambda d=data: self.update_history_after_edit(d, msg_type))
        elif msg_type == "chat_history":
            if data["other_user"] == self.current_chat_user:
                self.current_history_data = data["history"]
                self.queue_to_ui(lambda h=self.current_history_data: self.display_history(h))
        elif msg_type == "new_message":
            self.queue_to_ui(lambda d=data: self.receive_message(d))
        elif msg_type == "schedule_data":
            chat_id = data["chat_id"]
            if chat_id == self.current_chat_user:
                schedules = data["schedules"]
                for s in schedules: s["grid"] = np.array(s["grid"])
                self.queue_to_ui(lambda s=schedules: self.render_scheduler(s))
        elif msg_type == "schedule_updated":
            chat_id = data["chat_id"]
            if chat_id == self.current_chat_user and self.scheduler_obj:
                self.queue_to_ui(
                    lambda n=data["nick"], g=data["grid"]: self.scheduler_obj.update_data_from_server(n, g))

    def on_login_success(self):
        self.login_window.destroy()
        self.deiconify()
        self.title(f"Convene - {self.username}")

    def update_connection_status(self, text, color):
        self.status_label.configure(text=text, text_color=color)

    def update_reactions_ui(self, msg_id, reactions_json):
        target_id = msg_id
        if target_id not in self.message_bubbles:
            target_id = str(msg_id) if isinstance(msg_id, int) else int(msg_id) if str(msg_id).isdigit() else msg_id

        if target_id in self.message_bubbles:
            self.message_bubbles[target_id]["reactions"] = json.loads(reactions_json)
            self.render_reactions(target_id)

    def update_contacts_ui(self):
        for w in self.contacts_scroll.winfo_children(): w.destroy()

        def get_sort_key(item):
            u, d = item
            if isinstance(d, dict): return (not d.get("pinned", False), not d.get("online", False), u)
            return (True, not d, u)

        for user, data in sorted(self.users_status.items(), key=get_sort_key):
            if isinstance(data, dict):
                is_online, is_pinned = data.get("online", False), data.get("pinned", False)
            else:
                is_online, is_pinned = data, False
            is_group = user.startswith("#")
            status_symbol = "👥" if is_group else "●"
            color = ("white" if ctk.get_appearance_mode() == "Dark" else "black") if is_group else (
                "green" if is_online else "gray")
            display_name = f"📌 {user}" if is_pinned else user
            f = ctk.CTkFrame(self.contacts_scroll,
                             fg_color=("gray75", "gray25") if user == self.current_chat_user else "transparent",
                             corner_radius=5)
            f.pack(fill="x", pady=2)
            btn = ctk.CTkButton(f, text=f"{status_symbol} {display_name}", anchor="w", text_color=color,
                                fg_color="transparent", hover_color=("gray70", "gray30"),
                                command=lambda u=user: self.select_contact(u))
            btn.pack(side="left", fill="x", expand=True)
            bind_event = "<Button-2>" if platform.system() == "Darwin" else "<Button-3>"

            def bind_tree(widget, u, p):
                widget.bind(bind_event, lambda e, usr=u, pin=p: self.show_contact_context_menu(e, usr, pin))
                for child in widget.winfo_children(): bind_tree(child, u, p)

            bind_tree(f, user, is_pinned)
            unread = self.unread_counts.get(user, 0)
            if unread > 0:
                badge = ctk.CTkLabel(f, text=str(unread), fg_color="#FF5555", text_color="white", width=22, height=22,
                                     corner_radius=11, font=ctk.CTkFont(size=11, weight="bold"))
                badge.pack(side="right", padx=(0, 10), pady=4)
                badge.bind("<Button-1>", lambda e, u=user: self.select_contact(u))

    def highlight_active_contact(self):
        for f in self.contacts_scroll.winfo_children():
            try:
                ch = f.winfo_children()
                if not ch: continue

                btn = ch[0]
                u = btn.cget("text").split(" ", 1)[-1].replace("📌 ", "")

                if u == self.current_chat_user:
                    f.configure(fg_color=("gray75", "gray25"))
                    if len(ch) > 1:
                        badge_widget = ch[1]
                        self.after(50, badge_widget.destroy)
                else:
                    f.configure(fg_color="transparent")
            except Exception:
                pass

    def select_contact(self, user):
        self.current_chat_user = user
        self.cancel_reply_edit()
        if user in self.unread_counts: self.unread_counts[user] = 0

        self.chat_header_label.configure(text=f"Группа {user}" if user.startswith("#") else f"Чат с {user}")
        self.view_switch.grid()
        self.close_chat_btn.grid()

        if user.startswith("#"):
            self.add_member_btn.grid()
        else:
            self.add_member_btn.grid_remove()

        self.msg_entry.configure(state="normal")
        self.send_btn.configure(state="normal")

        self.view_var.set("💬 Чат")
        self.on_view_change("💬 Чат")

        for w in self.messages_scroll.winfo_children(): w.destroy()

        if self.scheduler_obj and hasattr(self.scheduler_obj, 'fig'):
            plt.close(self.scheduler_obj.fig)
        for w in self.schedule_container.winfo_children(): w.destroy()
        self.scheduler_obj = None

        self.message_bubbles.clear()
        self.temp_to_real_ids.clear()
        self.current_history_data.clear()
        self.highlight_active_contact()

        self.send_to_server({"type": "get_history", "other_user": user})
        self.send_to_server({"type": "mark_read", "other_user": user})

    def render_scheduler(self, schedules):
        if self.scheduler_obj and hasattr(self.scheduler_obj, 'fig'):
            plt.close(self.scheduler_obj.fig)
        for w in self.schedule_container.winfo_children(): w.destroy()
        self.scheduler_obj = InteractiveScheduler(
            schedules_data=schedules,
            my_nick=self.username,
            container=self.schedule_container,
            on_grid_update=self.send_schedule_update_to_server
        )

    def close_chat(self):
        self.current_chat_user = None
        self.chat_header_label.configure(text="Выберите чат для начала общения")
        self.view_switch.grid_remove()
        self.close_chat_btn.grid_remove()
        self.add_member_btn.grid_remove()
        self.typing_label.configure(text="")
        self.cancel_reply_edit()
        self.msg_entry.configure(state="disabled")
        self.send_btn.configure(state="disabled")
        self.msg_entry.delete(0, 'end')

        if self.scheduler_obj and hasattr(self.scheduler_obj, 'fig'):
            plt.close(self.scheduler_obj.fig)
        for w in self.messages_scroll.winfo_children(): w.destroy()
        for w in self.schedule_container.winfo_children(): w.destroy()
        self.scheduler_obj = None

        self.message_bubbles.clear()
        self.temp_to_real_ids.clear()
        self.current_history_data.clear()
        self.highlight_active_contact()

    def scroll_to_bottom(self):
        try:
            self.messages_scroll.update_idletasks();
            self.messages_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def display_history(self, history):
        for w in self.messages_scroll.winfo_children(): w.destroy()
        self.message_bubbles.clear()
        self.temp_to_real_ids.clear()
        for msg in history:
            msg_id, sender, content, timestamp, status, reply_text, is_edited, is_deleted = msg[:8]
            reactions = json.loads(msg[8]) if len(msg) > 8 else {}
            if len(timestamp) > 5 and "-" in timestamp: timestamp = timestamp.split()[-1][:5]
            self.add_message_bubble(sender, content, timestamp, msg_id, status, reply_text, is_edited, is_deleted,
                                    scroll=False, reactions=reactions)
        self.after(50, self.scroll_to_bottom)

    def on_key_release_typing(self, event):
        if event.keysym == 'Return': return
        if time.time() - self.last_typing_time > 2.0 and self.current_chat_user:
            self.last_typing_time = time.time()
            self.send_to_server({"type": "typing", "receiver": self.current_chat_user})

    def show_typing_indicator(self, sender, group=None):
        target_chat = group if group else sender
        if target_chat == self.current_chat_user:
            self.typing_label.configure(text=f"{sender} печатает...")
            if self.typing_timer: self.after_cancel(self.typing_timer)
            self.typing_timer = self.after(3000, lambda: self.typing_label.configure(text=""))

    def setup_reply(self, sender, content):
        self.reply_to_data = f"{sender}: {content[:30]}..." if len(content) > 30 else f"{sender}: {content}"
        self.editing_msg_id = None
        self.reply_info_label.configure(text="Ответ на сообщение")
        self.reply_text_label.configure(text=self.reply_to_data)
        self.reply_frame.grid(row=1, column=0, sticky="ew")
        self.msg_entry.focus()

    def setup_edit(self, msg_id, content):
        self.reply_to_data = ""
        self.editing_msg_id = msg_id
        self.reply_info_label.configure(text="Редактирование")
        self.reply_text_label.configure(text=content[:40] + ("..." if len(content) > 40 else ""))
        self.reply_frame.grid(row=1, column=0, sticky="ew")
        self.msg_entry.delete(0, 'end')
        self.msg_entry.insert(0, content)
        self.msg_entry.focus()

    def cancel_reply_edit(self):
        was_editing = self.editing_msg_id is not None
        self.reply_to_data = ""
        self.editing_msg_id = None
        self.reply_frame.grid_remove()
        if was_editing and self.msg_entry.get():
            self.msg_entry.delete(0, 'end')

    def send_delete(self, msg_id):
        if messagebox.askyesno("Удаление", "Удалить сообщение?"):
            self.send_to_server({"type": "delete_message", "msg_id": msg_id, "receiver": self.current_chat_user})
            self.update_history_after_edit({"msg_id": msg_id}, "delete_message")

    def delete_contact_chat(self, contact):
        if messagebox.askyesno("Удаление", f"Покинуть/Удалить чат {contact}?"):
            self.send_to_server({"type": "delete_chat", "contact": contact})
            if self.current_chat_user == contact: self.close_chat()

    def close_menu_on_click(self, event):
        if self.active_context_menu and self.active_context_menu.winfo_exists():
            try:
                x, y, m = event.x_root, event.y_root, self.active_context_menu
                if not (
                        m.winfo_rootx() <= x <= m.winfo_rootx() + m.winfo_width() and m.winfo_rooty() <= y <= m.winfo_rooty() + m.winfo_height()): m.destroy()
            except Exception:
                pass

    def show_contact_context_menu(self, event, contact, is_pinned):
        if self.active_context_menu and self.active_context_menu.winfo_exists(): self.active_context_menu.destroy()
        menu = ctk.CTkToplevel(self)
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.configure(fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        frame = ctk.CTkFrame(menu, corner_radius=8, border_width=1, border_color=("gray75", "gray25"),
                             fg_color=("gray95", "gray15"))
        frame.pack(fill="both", expand=True)
        self.active_context_menu = menu

        def exc(func, *args):
            menu.destroy();
            func(*args)

        opts = [("Открепить" if is_pinned else "Закрепить",
                 lambda: exc(self.send_to_server, {"type": "pin_chat", "contact": contact, "pinned": not is_pinned}),
                 ("black", "white")),
                ("Покинуть/Удалить", lambda: exc(self.delete_contact_chat, contact), ("black", "white"))]
        for i, (txt, cmd, col) in enumerate(opts):
            ctk.CTkButton(frame, text=txt, width=140, height=30, fg_color="transparent",
                          hover_color=("gray85", "gray25"), text_color=col, anchor="w", font=ctk.CTkFont(size=12),
                          command=cmd).pack(padx=4, pady=(6 if i == 0 else 2, 6 if i == len(opts) - 1 else 2))
        menu.update_idletasks()
        menu.geometry(f"+{event.x_root}+{event.y_root}")

    def show_context_menu(self, event, msg_id):
        if str(msg_id).startswith("temp_"):
            if msg_id in self.temp_to_real_ids:
                msg_id = self.temp_to_real_ids[msg_id]
            else:
                return
        w = self.message_bubbles.get(msg_id)
        if not w or w.get("is_deleted", False): return
        content, sender, is_me = w["content"], self.username if w["is_me"] else self.current_chat_user, w["is_me"]

        if self.active_context_menu and self.active_context_menu.winfo_exists(): self.active_context_menu.destroy()
        menu = ctk.CTkToplevel(self)
        menu.overrideredirect(True)
        menu.attributes("-topmost", True)
        menu.configure(fg_color=ctk.ThemeManager.theme["CTkFrame"]["fg_color"])
        frame = ctk.CTkFrame(menu, corner_radius=8, border_width=1, border_color=("gray75", "gray25"),
                             fg_color=("gray95", "gray15"))
        frame.pack(fill="both", expand=True)
        self.active_context_menu = menu

        def exc(func, *args):
            menu.destroy();
            func(*args)

        emojis = ["👍", "❤️", "😂", "😲", "😢", "👏"]
        emoji_frame = ctk.CTkFrame(frame, fg_color="transparent")
        emoji_frame.pack(padx=4, pady=4, fill="x")

        for em in emojis:
            img = getattr(self, 'emoji_images', {}).get(em)

            cmd = lambda e=em, m=msg_id: exc(self.send_to_server, {
                "type": "toggle_reaction",
                "msg_id": self.temp_to_real_ids.get(m, m) if str(m).startswith("temp_") else m,
                "reaction": e,
                "receiver": self.current_chat_user
            })

            if img:
                btn = ctk.CTkButton(emoji_frame, text="", image=img, width=32, height=32, corner_radius=16,
                                    fg_color="transparent", hover_color=("gray85", "gray30"), command=cmd)
            else:
                btn = ctk.CTkButton(emoji_frame, text=em, width=32, height=32, corner_radius=16,
                                    fg_color="transparent", hover_color=("gray85", "gray30"),
                                    font=ctk.CTkFont(size=18), command=cmd)
            btn.pack(side="left", padx=1, expand=True)

        opts = [("Ответить", lambda: exc(self.setup_reply, sender, content), ("black", "white"))]

        if is_me:
            opts.extend([("Изменить", lambda: exc(self.setup_edit, msg_id, content), ("black", "white")),
                         ("Удалить", lambda: exc(self.send_delete, msg_id), "#FF5555")])
        for i, (txt, cmd, col) in enumerate(opts):
            ctk.CTkButton(frame, text=txt, width=140, height=30, fg_color="transparent",
                          hover_color=("gray85", "gray25"), text_color=col, anchor="w", font=ctk.CTkFont(size=12),
                          command=cmd).pack(padx=4, pady=(6 if i == 0 else 2, 6 if i == len(opts) - 1 else 2))
        menu.update_idletasks()
        menu.geometry(f"+{event.x_root}+{event.y_root}")

    def process_read_receipt(self, reader):
        if reader == self.current_chat_user:
            for msg_id, w in self.message_bubbles.items():
                if w["is_me"] and w["status"] <= 0:
                    w["status"] = 1
                    if "status_label" in w and w["status_label"]:
                        w["status_label"].configure(text="✓", text_color="#5eb5f7")
                        if not w.get("status_label_2"):
                            lbl2 = ctk.CTkLabel(w["status_frame"], text="✓", font=ctk.CTkFont(size=11),
                                                text_color="#5eb5f7")
                            lbl2.place(x=4, rely=0.5, anchor="w")
                            w["status_label_2"] = lbl2

    def confirm_message_sent(self, data):
        t_id, r_id = data["temp_id"], data["msg_id"]
        self.temp_to_real_ids[t_id] = r_id
        if t_id in self.message_bubbles:
            w = self.message_bubbles.pop(t_id)
            self.message_bubbles[r_id] = w
            if w["status"] < 1:
                w["status"] = 0
                if "status_label" in w and w["status_label"]:
                    w["status_label"].configure(text="✓", text_color="gray60")
                    if w.get("status_label_2"): w["status_label_2"].destroy(); w["status_label_2"] = None

            self.current_history_data.append((
                (r_id, self.username, w["content"], data["timestamp"], w["status"], w["reply_text"], 0, 0, "{}")
            ))

    def update_history_after_edit(self, data, act):
        msg_id = data["msg_id"]
        for i, msg in enumerate(self.current_history_data):
            if msg[0] == msg_id:
                m_l = list(msg)
                if act == "edit_message":
                    m_l[2] = data["content"];
                    m_l[6] = 1
                elif act == "delete_message":
                    m_l[2] = "🚫 Сообщение удалено";
                    m_l[7] = 1
                self.current_history_data[i] = tuple(m_l)
                break
        if msg_id in self.message_bubbles:
            w = self.message_bubbles[msg_id]
            if act == "edit_message":
                w["content"] = data["content"];
                w["msg_label"].configure(text=data["content"])
            elif act == "delete_message":
                w["content"] = "🚫 Сообщение удалено"
                w["is_deleted"] = True
                w["msg_label"].configure(text="🚫 Сообщение удалено", text_color="gray")
                if w.get("reply_lbl"): w["reply_lbl"].destroy()

    def send_chat_message(self):
        c = self.msg_entry.get().strip()
        if not c or not self.current_chat_user: return
        self.msg_entry.delete(0, 'end')
        if self.editing_msg_id:
            self.send_to_server(
                {"type": "edit_message", "msg_id": self.editing_msg_id, "receiver": self.current_chat_user,
                 "content": c})
            self.update_history_after_edit({"msg_id": self.editing_msg_id, "content": c}, "edit_message")
            self.cancel_reply_edit()
            return

        t_id = f"temp_{os.urandom(4).hex()}"
        ts = datetime.now().strftime("%H:%M")
        r_t = self.reply_to_data
        self.add_message_bubble(self.username, c, ts, msg_id=t_id, status=-1, reply_text=r_t)
        self.send_to_server({"type": "send_message", "receiver": self.current_chat_user, "content": c, "temp_id": t_id,
                             "reply_text": r_t})
        self.cancel_reply_edit()

    def receive_message(self, data):
        snd, rcv, c, ts, m_id, r_t = data["sender"], data.get("receiver", data["sender"]), data["content"], \
            data["timestamp"].split()[-1][:5], data.get("msg_id"), data.get("reply_text", "")
        c_id = rcv if rcv.startswith("#") else snd

        if c_id == self.current_chat_user:
            self.add_message_bubble(snd, c, ts, m_id, status=1, reply_text=r_t)
            self.current_history_data.append((m_id, snd, c, data["timestamp"], 1, r_t, 0, 0, "{}"))
            self.send_to_server({"type": "mark_read", "other_user": c_id})
            self.typing_label.configure(text="")
        else:
            self.show_notification(c_id, f"{snd}: {c}" if c_id.startswith("#") else c)
            self.unread_counts[c_id] = self.unread_counts.get(c_id, 0) + 1
            if c_id not in self.users_status: self.users_status[c_id] = True
            self.update_contacts_ui()

    def show_notification(self, t, c):
        if platform.system() == "Windows":
            try:
                import winsound;
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except:
                pass
        tst = ctk.CTkFrame(self, width=250, height=70, corner_radius=10, border_width=1,
                           border_color=("gray70", "gray30"))
        tst.place(relx=0.98, rely=0.02, anchor="ne")
        ctk.CTkLabel(tst, text=f"От: {t}", font=ctk.CTkFont(weight="bold")).pack(padx=15, pady=(10, 0), anchor="w")
        ctk.CTkLabel(tst, text=c if len(c) < 30 else c[:27] + "...").pack(padx=15, pady=(0, 10), anchor="w")
        self.after(4000, tst.destroy)

    def render_reactions(self, msg_id):
        # Принудительно прячем зависшие тултипы перед перерисовкой кнопок
        if getattr(self, 'active_tooltip', None):
            try:
                self.active_tooltip.destroy()
            except:
                pass
            self.active_tooltip = None

        w = self.message_bubbles.get(msg_id)
        if not w or w.get("is_deleted"): return
        reactions = w.get("reactions", {})

        if w.get("reactions_widget") and w["reactions_widget"].winfo_exists():
            w["reactions_widget"].destroy()
            w["reactions_widget"] = None

        if not reactions or all(len(users) == 0 for users in reactions.values()):
            return

        rx_frame = ctk.CTkFrame(w["bubble_frame"], fg_color="transparent")
        rx_frame.pack(padx=10, pady=(0, 6), anchor="w" if not w["is_me"] else "e")
        w["reactions_widget"] = rx_frame

        for emoji, users in reactions.items():
            count = len(users)
            if count == 0: continue
            is_reacted = self.username in users
            bg_color = "#3B8ED0" if is_reacted else ("gray75", "gray30")
            text_color = "white" if is_reacted else ("black", "white")

            cmd = lambda e=emoji, m=msg_id: self.send_to_server({
                "type": "toggle_reaction",
                "msg_id": self.temp_to_real_ids.get(m, m) if str(m).startswith("temp_") else m,
                "reaction": e,
                "receiver": self.current_chat_user
            })

            img = getattr(self, 'emoji_images', {}).get(emoji)

            if img:
                btn = ctk.CTkButton(rx_frame, text=f" {count}", image=img, width=35, height=20, corner_radius=10,
                                    fg_color=bg_color, text_color=text_color, font=ctk.CTkFont(size=11, weight="bold"),
                                    hover_color=("#2B5278" if is_reacted else "gray60"), command=cmd)
            else:
                btn = ctk.CTkButton(rx_frame, text=f"{emoji} {count}", width=35, height=20, corner_radius=10,
                                    fg_color=bg_color, text_color=text_color,
                                    font=ctk.CTkFont(family="Segoe UI Emoji", size=11),
                                    hover_color=("#2B5278" if is_reacted else "gray60"), command=cmd)
            btn.pack(side="left", padx=2)

            tooltip_text = ", ".join(users)
            self.create_tooltip(btn, tooltip_text)

    def create_tooltip(self, widget, text):
        tip_timer = [None]

        def show_tip(event):
            hide_tip()
            # Добавляем задержку 400 мс перед показом окошка
            tip_timer[0] = self.after(400, lambda: _draw_tip(event))

        def _draw_tip(event):
            hide_tip()  # На всякий случай чистим еще раз
            tw = ctk.CTkToplevel(self)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            tw.geometry(f"+{event.x_root + 15}+{event.y_root + 15}")

            lbl = ctk.CTkLabel(tw, text=text, fg_color=("gray85", "#1E1E1E"),
                               text_color=("black", "white"), corner_radius=6,
                               font=ctk.CTkFont(size=11, weight="bold"), padx=10, pady=4)
            lbl.pack()
            self.active_tooltip = tw

        def hide_tip(event=None):
            if tip_timer[0]:
                self.after_cancel(tip_timer[0])
                tip_timer[0] = None
            if getattr(self, 'active_tooltip', None):
                try:
                    self.active_tooltip.destroy()
                except:
                    pass
                self.active_tooltip = None

        widget.bind("<Enter>", show_tip)
        widget.bind("<Leave>", hide_tip)
        widget.bind("<ButtonPress>", hide_tip)  # Скрываем при клике

    def add_message_bubble(self, sender, content, timestamp, msg_id=None, status=0, reply_text="", is_edited=False,
                           is_deleted=False, scroll=True, reactions=None):
        is_me = (sender == self.username)
        align_frame = ctk.CTkFrame(self.messages_scroll, fg_color="transparent")
        align_frame.pack(fill="x", pady=1)

        color = ("#DCEEFA", "#2B5278") if is_me else ("#E8E8E8", "#3E3E40")
        bubble = ctk.CTkFrame(align_frame, fg_color=color, corner_radius=8)
        bubble.pack(side="right" if is_me else "left", padx=10)

        is_group = self.current_chat_user and self.current_chat_user.startswith("#")
        if is_group and not is_me and not is_deleted:
            ctk.CTkLabel(bubble, text=sender, font=ctk.CTkFont(size=11, weight="bold"), text_color="#5eb5f7").pack(
                padx=10, pady=(4, 0), anchor="w")

        reply_lbl_widget = None
        if reply_text and not is_deleted:
            reply_lbl_widget = ctk.CTkLabel(bubble, text=reply_text, font=ctk.CTkFont(size=10, slant="italic"),
                                            text_color="gray", justify="left")
            reply_lbl_widget.pack(padx=10, pady=(2 if (is_group and not is_me) else 4, 0), anchor="w")

        display_text = "🚫 Сообщение удалено" if is_deleted else content
        msg_label = ctk.CTkLabel(bubble, text=display_text, wraplength=350, justify="left",
                                 text_color="gray" if is_deleted else ("black", "white"))
        msg_label.pack(padx=10, pady=(1 if reply_text else (2 if (is_group and not is_me) else 4), 0),
                       anchor="w" if not is_me else "e")

        bottom_frame = ctk.CTkFrame(bubble, fg_color="transparent", height=12)
        bottom_frame.pack(padx=10, pady=(0, 4), anchor="e")

        if is_edited and not is_deleted:
            ctk.CTkLabel(bottom_frame, text="изм.", font=ctk.CTkFont(size=9, slant="italic"),
                         text_color=("gray50", "gray70")).pack(side="left", padx=(0, 4))

        time_label = ctk.CTkLabel(bottom_frame, text=timestamp, font=ctk.CTkFont(size=9),
                                  text_color=("gray50", "gray70"))
        time_label.pack(side="left")

        status_frame = None
        status_label = None
        status_label_2 = None

        if is_me:
            status_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent", width=18, height=12)
            status_frame.pack_propagate(False)
            status_frame.pack(side="left", padx=(4, 0))
            if status == -1:
                status_label = ctk.CTkLabel(status_frame, text="🕒", font=ctk.CTkFont(size=10), text_color="gray60")
                status_label.place(x=0, rely=0.5, anchor="w")
            else:
                status_color = "#5eb5f7" if status == 1 else "gray60"
                status_label = ctk.CTkLabel(status_frame, text="✓", font=ctk.CTkFont(size=11), text_color=status_color)
                status_label.place(x=0, rely=0.5, anchor="w")
                if status == 1:
                    status_label_2 = ctk.CTkLabel(status_frame, text="✓", font=ctk.CTkFont(size=11),
                                                  text_color=status_color)
                    status_label_2.place(x=4, rely=0.5, anchor="w")

        bind_event = "<Button-2>" if platform.system() == "Darwin" else "<Button-3>"

        def bind_tree(widget, m_id):
            widget.bind(bind_event, lambda e: self.show_context_menu(e, m_id))
            for child in widget.winfo_children():
                bind_tree(child, m_id)

        bind_tree(bubble, msg_id)

        if msg_id:
            self.message_bubbles[msg_id] = {
                "is_me": is_me, "status": status, "status_frame": status_frame, "status_label": status_label,
                "status_label_2": status_label_2, "content": content, "reply_text": reply_text,
                "is_deleted": is_deleted, "frame": align_frame, "msg_label": msg_label,
                "reply_lbl": reply_lbl_widget,
                "bubble_frame": bubble, "reactions": reactions or {}, "reactions_widget": None
            }
            self.render_reactions(msg_id)

        if scroll:
            self.after(10, self.scroll_to_bottom)