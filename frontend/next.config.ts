/**
 * 文件职责：配置 Next.js standalone 构建与 React 严格模式，供 Docker 最小镜像使用。
 */

import type { NextConfig } from "next";

/** standalone 会把生产运行必需文件收集到 .next/standalone，避免复制完整 node_modules。 */
const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
};

export default nextConfig;
