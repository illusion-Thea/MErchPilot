/**
 * 文件职责：封装 Agent WebSocket 连接、心跳、重连和事件解析。
 */

import { getRuntimeWsBaseUrl } from "@/lib/runtime-config";

export interface RunEvent {
  event_id?: string;
  event_type: string;
  occurred_at?: string;
  payload?: Record<string, unknown>;
}

/** 定义`RunSocketOptions`数据契约，约束组件属性或接口响应字段。 */
export interface RunSocketOptions {
  runId: string;
  onEvent: (event: RunEvent) => void;
  onStatus: (status: "connecting" | "connected" | "disconnected" | "error") => void;
}

/** 封装`RunSocket`相关状态与行为，并统一调用边界。 */
export class RunSocket {
  private socket?: WebSocket;
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private reconnectAttempts = 0;
  private lastEventId?: string;
  private stopped = false;

  constructor(private readonly options: RunSocketOptions) {}

  connect(): void {
    if (this.stopped) {
      return;
    }
    if (
      this.socket &&
      (this.socket.readyState === WebSocket.CONNECTING ||
        this.socket.readyState === WebSocket.OPEN)
    ) {
      return;
    }
    this.options.onStatus("connecting");
    const baseUrl = getRuntimeWsBaseUrl();
    const query = new URLSearchParams();
    if (this.lastEventId) {
      query.set("last_event_id", this.lastEventId);
    }
    const accessToken = window.localStorage.getItem("merchpilot_access_token");
    if (accessToken) {
      query.set("access_token", accessToken);
    }
    const queryString = query.size > 0 ? `?${query.toString()}` : "";
    try {
      this.socket = new WebSocket(`${baseUrl}/ws/runs/${this.options.runId}${queryString}`);
    } catch {
      this.options.onStatus("error");
      this.scheduleReconnect();
      return;
    }
    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
      this.options.onStatus("connected");
    };
    this.socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data as string) as RunEvent;
        this.lastEventId = event.event_id ?? this.lastEventId;
        this.options.onEvent(event);
      } catch {
        this.options.onStatus("error");
      }
    };
    this.socket.onerror = () => this.options.onStatus("error");
    this.socket.onclose = () => {
      this.socket = undefined;
      this.options.onStatus("disconnected");
      if (!this.stopped) {
        this.scheduleReconnect();
      }
    };
  }

  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }
    if (this.socket) {
      this.socket.onclose = null;
    }
    this.socket?.close();
    this.socket = undefined;
  }

  private scheduleReconnect(): void {
    if (this.stopped) {
      return;
    }
    const delay = Math.min(1_000 * 2 ** this.reconnectAttempts, 15_000);
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }
}
