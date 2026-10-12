export type G1Event = {
  type: string;
  data: Record<string, unknown>;
};

type EventCallback = (event: G1Event) => void;

class G1WebSocket {
  private socket: WebSocket | null = null;
  private listeners = new Set<EventCallback>();
  private reconnectTimer: ReturnType<
    typeof setTimeout
  > | null = null;

  connect() {
    if (
      this.socket?.readyState === WebSocket.OPEN ||
      this.socket?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    this.socket = new WebSocket(
      "ws://localhost:8000/ws"
    );

    this.socket.onopen = () => {
      console.log("[G1 WebSocket] Connected");
    };

    this.socket.onmessage = (message) => {
      try {
        const event: G1Event = JSON.parse(
          message.data
        );

        this.listeners.forEach((listener) => {
          listener(event);
        });
      } catch (error) {
        console.error(
          "[G1 WebSocket] Invalid event",
          error
        );
      }
    };

    this.socket.onclose = () => {
      console.log("[G1 WebSocket] Disconnected");

      this.socket = null;

      this.reconnectTimer = setTimeout(() => {
        this.connect();
      }, 2000);
    };
  }

  subscribe(callback: EventCallback) {
    this.listeners.add(callback);

    return () => {
      this.listeners.delete(callback);
    };
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    this.socket?.close();
    this.socket = null;
  }
}

export const g1WebSocket = new G1WebSocket();