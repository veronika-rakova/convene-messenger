import asyncio
from server import MessengerServer
from client import MessengerClient
from config import SERVER_HOST, SERVER_PORT

#ручной запуск сервера и клиентов
def main():
    print("Выберите режим запуска:")
    print("1 - Запустить сервер")
    print("2 - Запустить клиент (GUI)")

    ch = input("Ваш выбор (1/2): ").strip()

    if ch == '1':
        print("\n--- СЕРВЕР МЕССЕНДЖЕРА ---")
        asyncio.run(MessengerServer(SERVER_HOST, SERVER_PORT).start())
    elif ch == '2':
        print("\n--- КЛИЕНТ МЕССЕНДЖЕРА ---")
        app = MessengerClient()
        app.mainloop()
    else:
        print("Неверный выбор. Завершение.")

if __name__ == "__main__":
    main()