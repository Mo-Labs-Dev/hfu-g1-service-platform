from fastapi import APIRouter, WebSocket, WebSocketDisconnect


router = APIRouter()


class ConnectionManager:

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(
        self,
        websocket: WebSocket,
    ):
        await websocket.accept()
        self.active_connections.append(websocket)

        print(
            f"[WebSocket] Client connected "
            f"({len(self.active_connections)} active)"
        )

    def disconnect(
        self,
        websocket: WebSocket,
    ):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        print(
            f"[WebSocket] Client disconnected "
            f"({len(self.active_connections)} active)"
        )

    async def broadcast(
        self,
        event: dict,
    ):
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(event)
            except Exception:
                disconnected.append(connection)

        for connection in disconnected:
            self.disconnect(connection)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
):
    await manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        manager.disconnect(websocket)