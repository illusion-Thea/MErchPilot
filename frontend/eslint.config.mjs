/**
 * 文件职责：组合 Next.js、React 与 TypeScript ESLint 规则，并排除生成目录。
 */

import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// 生成目录由框架维护，不参与一方源码质量检查。
export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
