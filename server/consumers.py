import json
from channels.generic.websocket import AsyncWebsocketConsumer

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
