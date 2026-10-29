/**
 * 文件职责：定义 Next.js 根布局、全局元数据和 Ant Design 样式注册。
 */

import type { Metadata } from "next";
import { AntdRegistry } from "@ant-design/nextjs-registry";

import { StoreProvider } from "@/store/provider";

import "./globals.css";

/** 定义浏览器标题与说明等Next.js页面元数据。 */
export const metadata: Metadata = {
  title: "MerchPilot 品策智选",
  description: "企业级商品规划与智能选品平台",
};

/** 定义应用根布局，注册全局样式、元数据和Ant Design服务端样式兼容。 */
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <AntdRegistry>
          <StoreProvider>{children}</StoreProvider>
        </AntdRegistry>
      </body>
    </html>
  );
}
