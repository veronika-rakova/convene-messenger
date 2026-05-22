import multiprocessing
import time
import asyncio


def run_server():

    try:
        from server import MessengerServer
        from config import SERVER_HOST, SERVER_PORT

        print("[SERVER] Запуск сервера...")
        server = MessengerServer(SERVER_HOST, SERVER_PORT)
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("[SERVER] Сервер остановлен.")
    except Exception as e:
        print(f"[SERVER] Ошибка сервера: {e}")


def run_client(username, password, client_index):
    try:
        import customtkinter as ctk
        from client import MessengerClient, LoginWindow

        original_login_init = LoginWindow.__init__

        def patched_login_init(self, parent, client_app):
            original_login_init(self, parent, client_app)

            self.username_entry.delete(0, 'end')
            self.password_entry.delete(0, 'end')
            self.username_entry.insert(0, username)
            self.password_entry.insert(0, password)

            x_offset = 100 + (client_index * 350)
            y_offset = 200
            self.geometry(f"300x350+{x_offset}+{y_offset}")
            print(f"[{username}] Окно авторизации открыто")

        original_login_success = MessengerClient.on_login_success

        def patched_login_success(self):
            original_login_success(self)
            x_offset = 50 + (client_index * 300)
            y_offset = 100
            self.geometry(f"1000x700+{x_offset}+{y_offset}")
            print(f"[{username}] Вход успешен!")

        LoginWindow.__init__ = patched_login_init
        MessengerClient.on_login_success = patched_login_success

        print(f"[{username}] Инициализация клиента")
        app = MessengerClient()
        app.mainloop()

    except Exception as e:
        print(f"[{username}] Ошибка клиента: {e}")


if __name__ == '__main__':
    multiprocessing.freeze_support()

    print("=== ЗАПУСК ТЕСТОВОГО ОКРУЖЕНИЯ МЕССЕНДЖЕРА ===")

    server_process = multiprocessing.Process(target=run_server, name="MessengerServer-Process")
    server_process.daemon = True
    server_process.start()

    time.sleep(1.5)

    test_users = [
        ("user1", "1234"),
        ("user2", "1234"),
        ("user3", "1234")
    ]

    client_processes = []

    for index, (username, password) in enumerate(test_users):
        p = multiprocessing.Process(
            target=run_client,
            args=(username, password, index),
            name=f"Client-{username}"
        )
        p.start()
        client_processes.append(p)
        time.sleep(0.3)
    print("\nСервер и 3 клиента запущены.")
    try:
        for p in client_processes:
            p.join()
    except KeyboardInterrupt:
        print("\nПолучен сигнал прерывания")
        for p in client_processes:
            if p.is_alive():
                p.terminate()
        if server_process.is_alive():
            server_process.terminate()
        print("Все процессы успешно остановлены.")