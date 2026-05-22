import multiprocessing
import time
import asyncio


def run_server():
    """Запуск сервера мессенджера в отдельном процессе."""
    try:
        from server import MessengerServer
        from config import SERVER_HOST, SERVER_PORT

        print("[SERVER] Запуск асинхронного сервера...")
        server = MessengerServer(SERVER_HOST, SERVER_PORT)
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("[SERVER] Сервер остановлен.")
    except Exception as e:
        print(f"[SERVER] Ошибка сервера: {e}")


def run_client(username, password, client_index):
    """Запуск клиента мессенджера с автоматическим заполнением данных и смещением окон."""
    try:
        import customtkinter as ctk
        from client import MessengerClient, LoginWindow

        # Переопределяем инициализацию LoginWindow для автозаполнения учётных данных и смещения окна входа
        original_login_init = LoginWindow.__init__

        def patched_login_init(self, parent, client_app):
            original_login_init(self, parent, client_app)

            # Очищаем поля на случай, если там что-то было из конфигов, и пишем тестовые данные
            self.username_entry.delete(0, 'end')
            self.password_entry.delete(0, 'end')
            self.username_entry.insert(0, username)
            self.password_entry.insert(0, password)

            # Красиво расставляем окна авторизации по горизонтали, чтобы они не перекрывали друг друга
            x_offset = 100 + (client_index * 350)
            y_offset = 200
            self.geometry(f"300x350+{x_offset}+{y_offset}")
            print(f"[{username}] Окно авторизации открыто на позиции +{x_offset}+{y_offset}")

        # Переопределяем метод успешного входа, чтобы основное окно чата тоже открывалось со смещением
        original_login_success = MessengerClient.on_login_success

        def patched_login_success(self):
            original_login_success(self)
            # Смещение для основного окна мессенджера (размер 1000x700 по умолчанию в client.py)
            x_offset = 50 + (client_index * 300)
            y_offset = 100
            self.geometry(f"1000x700+{x_offset}+{y_offset}")
            print(f"[{username}] Вход успешен! Окно чата смещено на +{x_offset}+{y_offset}")

        # Применяем патчи перед созданием экземпляра приложения
        LoginWindow.__init__ = patched_login_init
        MessengerClient.on_login_success = patched_login_success

        # Запускаем клиент
        print(f"[{username}] Инициализация клиента...")
        app = MessengerClient()
        app.mainloop()

    except Exception as e:
        print(f"[{username}] Ошибка клиента: {e}")


if __name__ == '__main__':
    # На Windows для корректной работы multiprocessing обязателен freeze_support
    multiprocessing.freeze_support()

    print("=== ЗАПУСК ТЕСТОВОГО ОКРУЖЕНИЯ МЕССЕНДЖЕРА ===")

    # 1. Запускаем процесс сервера
    server_process = multiprocessing.Process(target=run_server, name="MessengerServer-Process")
    server_process.daemon = True  # Чтобы сервер закрывался при закрытии основного скрипта
    server_process.start()

    # Небольшая пауза, чтобы сервер успел поднять порт до подключения клиентов
    time.sleep(1.5)

    # Данные тестовых пользователей
    test_users = [
        ("user1", "1234"),
        ("user2", "1234"),
        ("user3", "1234")
    ]

    client_processes = []

    # 2. Запускаем процессы клиентов
    for index, (username, password) in enumerate(test_users):
        p = multiprocessing.Process(
            target=run_client,
            args=(username, password, index),
            name=f"Client-{username}"
        )
        p.start()
        client_processes.append(p)
        time.sleep(0.3)  # Легкая задержка для плавности появления окон

    print("\n[INFO] Сервер и 3 клиента успешно запущены.")
    print("[INFO] Окна автоматически распределены по экрану.")
    print("[INFO] Для завершения закройте окна приложений или нажмите Ctrl+C здесь.\n")

    try:
        # Держим главный поток активным, пока работают клиенты
        for p in client_processes:
            p.join()
    except KeyboardInterrupt:
        print("\n[INFO] Получен сигнал прерывания. Завершение всех процессов...")

        for p in client_processes:
            if p.is_alive():
                p.terminate()

        if server_process.is_alive():
            server_process.terminate()

        print("[INFO] Все процессы успешно остановлены.")