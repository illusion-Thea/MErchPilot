/**
 * 文件职责：提供浏览器默认请求的站点图标，避免局域网访问时出现 favicon 404。
 */

const faviconSvg = `
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="16" fill="#102a43"/>
  <path d="M16 17h8v30h-8zm12 0h8v12h4V17h8v30h-8V37h-4v10h-8z" fill="#7dd3fc"/>
</svg>`;

/** 返回 MerchPilot 站点图标，并允许浏览器缓存该静态资源。 */
export function GET(): Response {
  return new Response(faviconSvg, {
    headers: {
      "Cache-Control": "public, max-age=86400",
      "Content-Type": "image/svg+xml",
    },
  });
}
