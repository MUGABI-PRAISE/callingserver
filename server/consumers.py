import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django.db import connection
from datetime import datetime
from channels.db import database_sync_to_async

# Store connected clients by user ID
clients = {}  # user_id -> consumer instance

class SignalingConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def disconnect(self, close_code):
        # Remove disconnected client from the clients dict
        for uid, consumer in list(clients.items()):
            if consumer == self:
                del clients[uid]

    async def receive(self, text_data):
        try:
            message = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(json.dumps({"error": "Invalid JSON"}))
            return

        # Register new client
        if message.get("type") == "register" and "id" in message:
            clients[message["id"]] = self
            await self.send(json.dumps({"status": "registered"}))
            return

        # Forward message to target client if connected
        target_id = message.get("to")
        if target_id and target_id in clients:
            await clients[target_id].send(text_data)


# chat-server consumer
import json
from datetime import datetime

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.db import connection


class ChatConsumer(AsyncJsonWebsocketConsumer):
    # Stores active connections
    user_connections = {}  # {user_id: set of self instances}

    async def connect(self):
        # Extract user_id from query string
        self.user_id = int(self.scope['query_string'].decode().split('user_id=')[-1] or 0)

        if self.user_id <= 0:
            await self.close()
            return

        # Store connection
        if self.user_id not in self.user_connections:
            self.user_connections[self.user_id] = set()
        self.user_connections[self.user_id].add(self)

        # Mark user online
        await self.mark_user_online(self.user_id)

        await self.accept()

        # Send unread counts
        unread_counts = await self.get_unread_counts(self.user_id)
        await self.send_json({'type': 'unread_counts', 'data': unread_counts})

        # Notify others if first connection
        if len(self.user_connections[self.user_id]) == 1:
            await self.broadcast_presence(self.user_id, 'online')

        await self.log_server_event(self.user_id, 'connected', 'User connected via WebSocket')

    async def disconnect(self, close_code):
        if hasattr(self, 'user_id') and self.user_id in self.user_connections:
            self.user_connections[self.user_id].remove(self)
            if not self.user_connections[self.user_id]:
                del self.user_connections[self.user_id]
                await self.mark_user_offline(self.user_id)

        await self.log_server_event(getattr(self, 'user_id', 0), 'disconnected', 'User disconnected')

    async def receive_json(self, data):
        msg_type = data.get('type')

        if msg_type == 'message':
            await self.handle_send_message(data)
        elif msg_type == 'delete':
            await self.handle_delete_message(data)
        elif msg_type == 'edit':
            await self.handle_edit_message(data)
        elif msg_type in ['typing', 'stop_typing']:
            await self.send_to_recipient(data.get('to', 0), {
                'type': 'typing',
                'from': self.user_id,
                'is_typing': msg_type == 'typing'
            })
        elif msg_type == 'read':
            await self.handle_read_receipt(data)
        elif msg_type == 'presence':
            await self.broadcast_presence(self.user_id, data.get('status'))
        elif msg_type == 'get_presence':
            await self.handle_get_presence()
        else:
            print(f"Unknown message type from {self.user_id}: {msg_type}")

    # ======================= Database Helpers =======================

    @database_sync_to_async
    def get_unread_counts(self, user_id):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT sender_office_id AS sender_id, COUNT(*) AS unread_count
                FROM files
                WHERE receiver_office_id = %s AND is_read = 0
                GROUP BY sender_office_id
            """, [user_id])
            return self.dictfetchall(cursor)

    @database_sync_to_async
    def handle_send_message_db(self, recipient_id, message, file_name, file_path, reply_to_id):
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO files (file_name, file_path, sender_office_id, receiver_office_id, message, reply_to_id, time_sent, is_read)
                VALUES (%s,%s,%s,%s,%s,%s,NOW(),0)
            """, [file_name, file_path, self.user_id, recipient_id, message, reply_to_id])
            message_id = cursor.lastrowid
            cursor.execute("SELECT * FROM files WHERE file_id=%s", [message_id])
            return self.dictfetchall(cursor)[0]

    async def handle_send_message(self, data):
        recipient_id = int(data.get('to', 0))
        message = data.get('content', '')
        file_name = data.get('file_name')
        file_path = data.get('file_path')
        reply_to_id = data.get('reply_to_id')

        if recipient_id <= 0 or (not message and not file_path):
            return

        new_message = await self.handle_send_message_db(recipient_id, message, file_name, file_path, reply_to_id)
        await self.send_to_recipient(recipient_id, {'type':'message','message':new_message})
        await self.send_to_recipient(self.user_id, {'type':'message_sent','message':new_message})

    @database_sync_to_async
    def handle_delete_message_db(self, file_id):
        with connection.cursor() as cursor:
            cursor.execute("SELECT sender_office_id, receiver_office_id FROM files WHERE file_id=%s", [file_id])
            return self.dictfetchall(cursor)

    async def handle_delete_message(self, data):
        file_id = int(data.get('file_id',0))
        if file_id <= 0:
            return
        msg = await self.handle_delete_message_db(file_id)
        if not msg or msg[0]['sender_office_id'] != self.user_id:
            return
        await database_sync_to_async(lambda: connection.cursor().execute("DELETE FROM files WHERE file_id=%s",[file_id]))()
        await self.send_to_recipient(msg[0]['receiver_office_id'], {'type':'message_deleted','file_id':file_id})
        await self.send_to_recipient(self.user_id, {'type':'message_deleted','file_id':file_id})

    @database_sync_to_async
    def mark_user_online(self, user_id):
        with connection.cursor() as cursor:
            cursor.execute("REPLACE INTO online_users (user_id,last_online) VALUES (%s,%s)", [user_id,datetime.now()])

    @database_sync_to_async
    def mark_user_offline(self, user_id):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE online_users SET last_online=%s WHERE user_id=%s",[datetime.now(),user_id])

    async def handle_get_presence(self):
        online_users = list(self.user_connections.keys())
        await self.send_json({'type':'initial_presence','online_users':online_users})

    async def broadcast_presence(self, user_id, status):
        for uid, conns in self.user_connections.items():
            for conn in conns:
                await conn.send_json({'type':'presence','user_id':user_id,'status':status})

    async def send_to_recipient(self, recipient_id, payload):
        for conn in self.user_connections.get(recipient_id, set()):
            await conn.send_json(payload)

    @database_sync_to_async
    def log_server_event(self, user_id, action, details='N/A'):
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO server_logs (user_id, action, details) VALUES (%s,%s,%s)",[user_id,action,details])

    # ================= Helper =================
    def dictfetchall(self, cursor):
        columns = [col[0] for col in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        for row in rows:
            for k, v in row.items():
                if isinstance(v, datetime):
                    row[k] = v.isoformat()  # Convert datetime to ISO string
        return rows

