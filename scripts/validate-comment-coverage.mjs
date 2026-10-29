/**
 * 文件职责：使用 TypeScript AST 检查前端顶层声明是否具有 JSDoc，避免新增代码失去阅读入口。
 */

import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const projectRoot = path.resolve(import.meta.dirname, "..");
const frontendRoot = path.join(projectRoot, "frontend", "src");
// 检查脚本位于项目根目录，因此显式从前端工作区解析 TypeScript 编译器。
const frontendRequire = createRequire(path.join(projectRoot, "frontend", "package.json"));
const ts = frontendRequire("typescript");

/** 递归列出一方 TypeScript/TSX 文件，排除框架生成目录。 */
function listSourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return listSourceFiles(target);
    return /\.tsx?$/.test(target) ? [target] : [];
  });
}

/** 判断声明前是否存在 JSDoc；普通行注释不作为稳定的声明契约。 */
function hasJsDoc(sourceText, declaration) {
  const ranges = ts.getLeadingCommentRanges(sourceText, declaration.getFullStart()) ?? [];
  return ranges.some((range) => sourceText.slice(range.pos, range.end).includes("/**"));
}

/** 返回需要纳入说明覆盖的顶层声明名称；解构导出由其源声明负责说明。 */
function declarationName(sourceFile, declaration) {
  if (
    ts.isInterfaceDeclaration(declaration)
    || ts.isTypeAliasDeclaration(declaration)
    || ts.isClassDeclaration(declaration)
    || ts.isFunctionDeclaration(declaration)
    || ts.isEnumDeclaration(declaration)
  ) {
    return declaration.name?.text ?? "<anonymous>";
  }
  if (!ts.isVariableStatement(declaration)) return undefined;
  const names = declaration.declarationList.declarations.map((item) => item.name.getText(sourceFile));
  if (names.some((name) => name.startsWith("{") || name.startsWith("["))) return undefined;
  return names.join(", ");
}

const missing = [];
for (const file of listSourceFiles(frontendRoot)) {
  const sourceText = fs.readFileSync(file, "utf8");
  const sourceFile = ts.createSourceFile(
    file,
    sourceText,
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  for (const declaration of sourceFile.statements) {
    const name = declarationName(sourceFile, declaration);
    if (!name || hasJsDoc(sourceText, declaration)) continue;
    const line = sourceFile.getLineAndCharacterOfPosition(declaration.getStart(sourceFile)).line + 1;
    missing.push(`${path.relative(projectRoot, file)}:${line} ${name}`);
  }
}

if (missing.length > 0) {
  console.error("以下前端顶层声明缺少 JSDoc：");
  console.error(missing.join("\n"));
  process.exit(1);
}

console.log("PASS  前端顶层声明均包含 JSDoc");
