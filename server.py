import asyncio
import json
from datetime import datetime
import websockets
from websockets.exceptions import ConnectionClosed
from database import Database


class MessengerServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.db = Database()
        self.connected_clients = {}

    def get_canonical_chat_id(self, u1, u2):
        if u2.startswith("#"): return u2
        return f"{min(u1, u2)}___{max(u1, u2)}"

    async def send_contact_list(self, username, websocket):
        contacts = self.db.get_contacts(username)
        contact_data = {c: {"online": (c in self.connected_clients), "pinned": bool(pinned)} for c, pinned in
                        contacts.items()}
        unread_counts = self.db.get_unread_counts(username)
        await websocket.send(
            json.dumps({"type": "contacts_list", "contacts": contact_data, "unread_counts": unread_counts}))

    async def broadcast_status_update(self):
        for username, ws in self.connected_clients.items():
            try:
                await self.send_contact_list(username, ws)
            except:
                pass

    async def handle_client(self, websocket):
        current_username = None
        try:
            async for message in websocket:
                data = json.loads(message)
                msg_type = data.get("type")

                if msg_type == "register":
                    success = self.db.register_user(data["username"], data["password"])
                    await websocket.send(json.dumps({"type": "register_result", "success": success}))

                elif msg_type == "login":
                    success = self.db.check_credentials(data["username"], data["password"])
                    if success:
                        if data["username"] in self.connected_clients:
                            await self.connected_clients[data["username"]].close()
                        current_username = data["username"]
                        self.connected_clients[current_username] = websocket
                        await websocket.send(
                            json.dumps({"type": "login_result", "success": True, "username": current_username}))
                        await self.broadcast_status_update()
                    else:
                        await websocket.send(
                            json.dumps({"type": "login_result", "success": False, "error": "Invalid credentials"}))

                elif msg_type == "toggle_reaction":
                    if current_username:
                        new_rx_json = self.db.toggle_reaction(data["msg_id"], current_username, data["reaction"])
                        receiver = data["receiver"]
                        msg_data = {"type": "reaction_updated", "msg_id": data["msg_id"], "reactions": new_rx_json}

                        if receiver.startswith("#"):
                            for member in self.db.get_group_members(receiver):
                                if member in self.connected_clients:
                                    await self.connected_clients[member].send(json.dumps(msg_data))
                        else:
                            if current_username in self.connected_clients:
                                await self.connected_clients[current_username].send(json.dumps(msg_data))
                            if receiver != current_username and receiver in self.connected_clients:
                                await self.connected_clients[receiver].send(json.dumps(msg_data))

                elif msg_type == "add_contact":
                    if current_username:
                        success, msg = self.db.add_contact(current_username, data["contact"])
                        await websocket.send(
                            json.dumps({"type": "add_contact_result", "success": success, "message": msg}))
                        if success: await self.send_contact_list(current_username, websocket)

                elif msg_type == "create_group":
                    if current_username:
                        success, result = self.db.create_group(data["group_name"], current_username, data["members"])
                        if success:
                            members = self.db.get_group_members(result)
                            for member in members:
                                if member in self.connected_clients:
                                    await self.send_contact_list(member, self.connected_clients[member])
                        await websocket.send(
                            json.dumps({"type": "create_group_result", "success": success, "message": result}))

                elif msg_type == "add_group_members":
                    if current_username:
                        group_name = data["group_name"]
                        new_members = data["members"]
                        added, errors = self.db.add_group_members(group_name, new_members)

                        if added:
                            msg = f"Добавлены: {', '.join(added)}."
                            if errors:
                                msg += f" Ошибки: {', '.join(errors)}"

                            await websocket.send(json.dumps({
                                "type": "add_group_members_result",
                                "success": True,
                                "message": msg
                            }))
                            all_members = self.db.get_group_members(group_name)
                            for member in all_members:
                                if member in self.connected_clients:
                                    await self.send_contact_list(member, self.connected_clients[member])
                        else:
                            await websocket.send(json.dumps({
                                "type": "add_group_members_result",
                                "success": False,
                                "message": "\n".join(errors)
                            }))

                elif msg_type == "pin_chat":
                    if current_username:
                        self.db.toggle_pin_contact(current_username, data["contact"], data["pinned"])
                        await self.send_contact_list(current_username, websocket)

                elif msg_type == "delete_chat":
                    if current_username:
                        self.db.delete_chat(current_username, data["contact"])
                        await self.send_contact_list(current_username, websocket)

                elif msg_type == "typing":
                    if current_username:
                        receiver = data["receiver"]
                        if receiver.startswith("#"):
                            for member in self.db.get_group_members(receiver):
                                if member != current_username and member in self.connected_clients:
                                    await self.connected_clients[member].send(
                                        json.dumps({"type": "typing", "sender": current_username, "group": receiver}))
                        else:
                            if receiver in self.connected_clients:
                                await self.connected_clients[receiver].send(
                                    json.dumps({"type": "typing", "sender": current_username}))

                elif msg_type == "mark_read":
                    if current_username:
                        sender_to_mark = data["other_user"]
                        self.db.mark_as_read(sender_to_mark, current_username)
                        if not sender_to_mark.startswith("#") and sender_to_mark in self.connected_clients:
                            await self.connected_clients[sender_to_mark].send(
                                json.dumps({"type": "read_receipt", "reader": current_username}))

                elif msg_type == "edit_message":
                    if current_username:
                        self.db.edit_message(data["msg_id"], data["content"])
                        receiver = data["receiver"]
                        if receiver.startswith("#"):
                            for member in self.db.get_group_members(receiver):
                                if member in self.connected_clients: await self.connected_clients[member].send(
                                    json.dumps(data))
                        elif receiver in self.connected_clients:
                            await self.connected_clients[receiver].send(json.dumps(data))

                elif msg_type == "delete_message":
                    if current_username:
                        self.db.delete_message(data["msg_id"])
                        receiver = data["receiver"]
                        if receiver.startswith("#"):
                            for member in self.db.get_group_members(receiver):
                                if member in self.connected_clients: await self.connected_clients[member].send(
                                    json.dumps(data))
                        elif receiver in self.connected_clients:
                            await self.connected_clients[receiver].send(json.dumps(data))

                elif msg_type == "send_message":
                    if current_username:
                        receiver = data["receiver"]
                        content = data["content"]
                        reply_text = data.get("reply_text", "")
                        msg_id = self.db.save_message(current_username, receiver, content, reply_text)
                        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                        await websocket.send(json.dumps(
                            {"type": "message_sent", "temp_id": data.get("temp_id"), "msg_id": msg_id,
                             "timestamp": timestamp}))
                        msg_to_send = {"type": "new_message", "msg_id": msg_id, "sender": current_username,
                                       "receiver": receiver, "content": content, "timestamp": timestamp,
                                       "reply_text": reply_text}

                        if receiver.startswith("#"):
                            for member in self.db.get_group_members(receiver):
                                if member != current_username and member in self.connected_clients:
                                    await self.connected_clients[member].send(json.dumps(msg_to_send))
                        elif receiver in self.connected_clients:
                            await self.connected_clients[receiver].send(json.dumps(msg_to_send))

                elif msg_type == "get_history":
                    if current_username:
                        other_user = data["other_user"]
                        history = self.db.get_chat_history(current_username, other_user)
                        await websocket.send(
                            json.dumps({"type": "chat_history", "other_user": other_user, "history": history}))

                elif msg_type == "get_schedule":
                    if current_username:
                        chat_id = data["chat_id"]
                        month_key = data.get("month_key", datetime.now().strftime("%m-%Y"))
                        canonical_id = self.get_canonical_chat_id(current_username, chat_id)

                        if chat_id.startswith("#"):
                            participants = self.db.get_group_members(chat_id)
                        else:
                            participants = [current_username, chat_id]

                        participants = sorted(participants, key=lambda x: x != current_username)
                        schedules_data = self.db.get_chat_schedules(canonical_id, participants, month_key)

                        for s in schedules_data: s["grid"] = s["grid"].tolist()
                        await websocket.send(
                            json.dumps({"type": "schedule_data", "chat_id": chat_id, "schedules": schedules_data}))

                elif msg_type == "update_schedule":
                    if current_username:
                        chat_id = data["chat_id"]
                        month_key = data.get("month_key", datetime.now().strftime("%m-%Y"))
                        grid_list = data["grid"]
                        edited_nick = data.get("nick", current_username)
                        canonical_id = self.get_canonical_chat_id(current_username, chat_id)

                        self.db.save_schedule_grid(edited_nick, canonical_id, month_key, grid_list)

                        if chat_id.startswith("#"):
                            update_msg = json.dumps(
                                {"type": "schedule_updated", "chat_id": chat_id, "nick": edited_nick,
                                 "grid": grid_list})
                            for member in self.db.get_group_members(chat_id):
                                if member != current_username and member in self.connected_clients:
                                    await self.connected_clients[member].send(update_msg)
                        else:
                            update_msg = json.dumps(
                                {"type": "schedule_updated", "chat_id": current_username, "nick": edited_nick,
                                 "grid": grid_list})
                            if chat_id in self.connected_clients:
                                await self.connected_clients[chat_id].send(update_msg)

        except ConnectionClosed:
            pass
        finally:
            if current_username in self.connected_clients:
                del self.connected_clients[current_username]
                await self.broadcast_status_update()

    async def start(self):
        print(f"Запуск сервера на ws://{self.host}:{self.port}")
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()