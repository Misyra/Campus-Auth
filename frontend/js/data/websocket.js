// WebSocket 相关数据
export function websocketData() {
  return {
    ws: null,
    _wsDestroyed: false,
    _wsRetryTimer: null,
    _wsWasConnected: false,
    wsReconnecting: false,
    wsRetryCount: 0,
    wsMaxRetries: 5,
  };
}
