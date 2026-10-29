/**
 * 文件职责：解析浏览器运行时的 API 与 WebSocket 地址，兼容本机和局域网访问。
 */

const DEFAULT_API_PORT = "8000";

/** 判断地址是否仍然指向当前浏览器无法访问的宿主机回环地址。 */
function isLoopbackHostname(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]";
}

/** 将仅对服务端有效的回环主机替换为浏览器正在访问的主机，同时保留配置端口。 */
function resolveConfiguredUrl(configuredUrl: string, browserOrigin: string): string {
  const browserUrl = new URL(browserOrigin);
  const parsedUrl = new URL(configuredUrl, browserOrigin);
  if (isLoopbackHostname(parsedUrl.hostname) && !isLoopbackHostname(browserUrl.hostname)) {
    parsedUrl.hostname = browserUrl.hostname;
  }
  return parsedUrl.toString().replace(/\/$/, "");
}

/** 返回当前浏览器可访问的 API 地址；显式配置的端口和路径始终保留。 */
export function getRuntimeApiBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_API_BASE_URL;

  if (typeof window === "undefined") {
    return configuredUrl ?? `http://localhost:${DEFAULT_API_PORT}/api/v1`;
  }

  if (configuredUrl) {
    try {
      return resolveConfiguredUrl(configuredUrl, window.location.origin);
    } catch {
      // 浏览器地址无效时继续使用当前页面主机名兜底。
    }
  }

  const runtimeUrl = new URL(window.location.origin);
  runtimeUrl.port = DEFAULT_API_PORT;
  runtimeUrl.pathname = "/api/v1";
  runtimeUrl.search = "";
  runtimeUrl.hash = "";
  return runtimeUrl.toString().replace(/\/$/, "");
}

/** 返回当前浏览器所在主机的 WebSocket 地址，自动匹配 HTTP 或 HTTPS。 */
export function getRuntimeWsBaseUrl(): string {
  const configuredUrl = process.env.NEXT_PUBLIC_WS_BASE_URL;

  if (typeof window === "undefined") {
    return configuredUrl ?? `ws://localhost:${DEFAULT_API_PORT}`;
  }

  if (configuredUrl) {
    try {
      return resolveConfiguredUrl(configuredUrl, window.location.origin);
    } catch {
      // 浏览器地址无效时继续使用当前页面主机名兜底。
    }
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.hostname}:${DEFAULT_API_PORT}`;
}
