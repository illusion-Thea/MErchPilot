#!/usr/bin/env node

/**
 * 文件职责：验证八天面试课件仍然满足单文件、自学闭环和源码可追溯要求。
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(scriptDirectory, "..");
const coursewarePath = path.join(
  repositoryRoot,
  "docs",
  "merchpilot-8-day-ai-interview-course.html",
);
const html = fs.readFileSync(coursewarePath, "utf8");

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function extractConstant(name, nextName) {
  const startMarker = `const ${name} =`;
  const endMarker = `const ${nextName} =`;
  const start = html.indexOf(startMarker);
  const end = html.indexOf(endMarker, start + startMarker.length);
  assert(start >= 0, `未找到数据常量 ${name}`);
  assert(end > start, `未找到 ${name} 的结束边界 ${nextName}`);
  const expression = html
    .slice(html.indexOf("=", start) + 1, end)
    .trim()
    .replace(/;\s*$/, "");
  return Function(`"use strict"; return (${expression});`)();
}

function extractConstantUntilMarker(name, marker) {
  const startMarker = `const ${name} =`;
  const start = html.indexOf(startMarker);
  const end = html.indexOf(marker, start + startMarker.length);
  assert(start >= 0, `未找到数据常量 ${name}`);
  assert(end > start, `未找到 ${name} 的结束边界 ${marker}`);
  const expression = html
    .slice(html.indexOf("=", start) + 1, end)
    .trim()
    .replace(/;\s*$/, "");
  return Function(`"use strict"; return (${expression});`)();
}

function assertUnique(values, label) {
  const seen = new Set();
  const duplicates = new Set();
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value);
    seen.add(value);
  }
  assert(duplicates.size === 0, `${label} 存在重复项：${[...duplicates].join(", ")}`);
}

function resolveCodePath(reference) {
  const withoutLine = String(reference).replace(/:\d+(?::\d+)?$/, "");
  return path.resolve(repositoryRoot, withoutLine);
}

function isRepositoryCodeReference(reference) {
  return /^(backend|frontend|scripts|docs|models|monitoring)\//.test(String(reference));
}

function assertCodeReferencesExist(references, label) {
  const missing = references
    .map(resolveCodePath)
    .filter((referencePath) => !fs.existsSync(referencePath));
  assert(missing.length === 0, `${label} 引用了不存在的源码：${missing.join(", ")}`);
}

function parseLineRange(reference, label) {
  const match = String(reference).match(/^(\d+)\s*[–—-]\s*(\d+)$/);
  assert(match, `${label} 的源码行号格式无效：${reference}`);
  const start = Number(match[1]);
  const end = Number(match[2]);
  assert(start > 0 && end >= start, `${label} 的源码行号范围无效：${reference}`);
  return [start, end];
}

function assertSnippetWithinDeclaredRange(lab) {
  const sourceLines = fs.readFileSync(resolveCodePath(lab.path), "utf8").split(/\r?\n/);
  const [start, end] = parseLineRange(lab.lines, `Day ${lab.day}「${lab.title}」`);
  assert(end <= sourceLines.length, `Day ${lab.day}「${lab.title}」的结束行超出源码文件`);
  const declaredLines = sourceLines.slice(start - 1, end).map((line) => line.trim());
  const snippetLines = String(lab.code)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  let cursor = 0;
  for (const snippetLine of snippetLines) {
    const offset = declaredLines.slice(cursor).indexOf(snippetLine);
    assert(
      offset >= 0,
      `Day ${lab.day}「${lab.title}」与 ${lab.path}:${lab.lines} 不一致，未找到：${snippetLine}`,
    );
    cursor += offset + 1;
  }
}

const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)];
assert(scripts.length === 1, `课件必须只有一个内联脚本，当前为 ${scripts.length} 个`);
new Function(scripts[0][1]);

assert(!/<script\b[^>]*\bsrc=/i.test(html), "课件不能依赖外部 JavaScript");
assert(!/<link\b[^>]*\brel=["']stylesheet["']/i.test(html), "课件不能依赖外部样式表");
assert(!/<(?:img|audio|video|source)\b[^>]*\bsrc=["']https?:/i.test(html), "课件不能依赖远程媒体");

const staticIds = [...html.matchAll(/\sid="([^"]+)"/g)].map((match) => match[1]);
assertUnique(staticIds, "静态 HTML id");

const days = extractConstant("days", "sourceLabs");
const sourceLabs = extractConstant("sourceLabs", "dayLearningContracts");
const learningContracts = extractConstant("dayLearningContracts", "dailyOralChecks");
const dailyOralChecks = extractConstant("dailyOralChecks", "dayExitCriteria");
const exitCriteria = extractConstant("dayExitCriteria", "phaseGateChecks");
const phaseGateChecks = extractConstant("phaseGateChecks", "reviewIntervals");
const reviewIntervals = extractConstant("reviewIntervals", "questionBank");
const questionBank = extractConstant("questionBank", "projectIntroductions");
const projectIntroductions = extractConstant("projectIntroductions", "mockInterviewQuestions");
const mockQuestions = extractConstant("mockInterviewQuestions", "mockScoreDimensions");
const scoreDimensions = extractConstant("mockScoreDimensions", "oralAcceptanceGates");
const oralGates = extractConstant("oralAcceptanceGates", "knowledgeDependencies");
const knowledgeDependencies = extractConstant("knowledgeDependencies", "confusionRoutes");
const confusionRoutes = extractConstant("confusionRoutes", "dayGuidedStarts");
const guidedStarts = extractConstant("dayGuidedStarts", "projectGlossary");
const glossary = extractConstant("projectGlossary", "businessBackboneStages");
const conceptBridgeRows = extractConstantUntilMarker("conceptBridgeRows", "function conceptBridgeState");
const businessBackboneStages = extractConstantUntilMarker("businessBackboneStages", "const businessBackboneDayMap");
const businessBackboneDayMap = extractConstant("businessBackboneDayMap", "sourceLabGuides");
const sourceLabGuides = extractConstant("sourceLabGuides", "dayNav");

assert(days.length === 8, `课程必须是 8 天，当前为 ${days.length} 天`);
assert(conceptBridgeRows.length === 4, `概念桥必须包含 4 层判断，当前为 ${conceptBridgeRows.length} 层`);
assertUnique(conceptBridgeRows.map((row) => row[1]), "概念桥层次");
assert(
  JSON.stringify(conceptBridgeRows.map((row) => row[1]).sort()) === JSON.stringify(["ai", "business", "code", "process"]),
  "概念桥必须覆盖 business/process/ai/code 四层",
);
assert(businessBackboneStages.length === 9, `业务主线必须包含 9 个阶段，当前为 ${businessBackboneStages.length} 个`);
assertUnique(businessBackboneStages.map((row) => row[0]), "业务主线阶段");
assert(
  businessBackboneDayMap.length === businessBackboneStages.length && businessBackboneDayMap.every((day) => day >= 1 && day <= 8),
  "业务主线必须为每个阶段提供有效的 Day 映射",
);
assert(sourceLabGuides.length === 8, `源码导航必须覆盖 8 天，当前为 ${sourceLabGuides.length} 天`);
assertUnique(sourceLabGuides.map((row) => row[0]), "源码导航天数");
assertUnique(days.map((day) => day.day), "课程天数");
assert(
  JSON.stringify(days.map((day) => day.day)) === JSON.stringify([1, 2, 3, 4, 5, 6, 7, 8]),
  "课程天数必须连续为 Day 1–8",
);
const phaseCounts = days.reduce((counts, day) => {
  counts[day.phase] = (counts[day.phase] || 0) + 1;
  return counts;
}, {});
assert(phaseCounts["业务理解"] === 2, "业务理解阶段必须为 2 天");
assert(phaseCounts["整体流程"] === 3, "整体流程阶段必须为 3 天");
assert(phaseCounts["重难点"] === 3, "重难点阶段必须为 3 天");

for (const day of days) {
  assert(day.title && day.target && day.mustSay, `Day ${day.day} 缺少标题、目标或核心表达`);
  assert(day.schedule?.length >= 5, `Day ${day.day} 至少需要 5 个学习时段`);
  assert(day.concepts?.length >= 4, `Day ${day.day} 概念讲解不足`);
  assert(day.code?.length >= 5, `Day ${day.day} 源码锚点不足`);
  assert(day.questions?.length >= 3, `Day ${day.day} 面试问题不足`);
  assert(day.quiz?.length >= 3, `Day ${day.day} 自测题不足`);
  const repositoryReferences = day.code
    .map(([codePath]) => codePath)
    .filter(isRepositoryCodeReference);
  assert(repositoryReferences.length >= 2, `Day ${day.day} 至少需要两个真实仓库源码锚点`);
  assertCodeReferencesExist(repositoryReferences, `Day ${day.day}`);
}

assert(learningContracts.length === 8, "每天都必须有学习契约");
assertUnique(learningContracts.map((contract) => contract.day), "学习契约天数");
for (const contract of learningContracts) {
  for (const field of ["duration", "prerequisite", "coreQuestion", "deliverable", "passStandard"]) {
    assert(contract[field], `Day ${contract.day} 学习契约缺少 ${field}`);
  }
}

assert(dailyOralChecks.length === 8, "每天都必须有独立的口述验收题");
assertUnique(dailyOralChecks.map((check) => check.day), "每日口述验收天数");
for (const check of dailyOralChecks) {
  assert(check.question && check.duration, `Day ${check.day} 口述验收缺少问题或时长`);
  assert(check.scaffold?.length >= 3, `Day ${check.day} 口述结构不足三步`);
  assert(check.keywordGroups?.length >= 3, `Day ${check.day} 口述覆盖规则不足三组`);
}

assert(exitCriteria.length === 5, "每日通关必须包含概念、代码、练习、自测和口述五项");
assert(
  JSON.stringify(exitCriteria.map(([key]) => key)) ===
    JSON.stringify(["concept", "code", "practice", "quiz", "oral"]),
  "每日五项通关顺序或含义发生变化",
);
assert(phaseGateChecks.length === 3, `阶段综合验收必须包含 3 个关卡，当前为 ${phaseGateChecks.length} 个`);
assert(
  JSON.stringify(phaseGateChecks.map((check) => check.day)) === JSON.stringify([2, 5, 8]),
  "阶段综合验收必须设置在 Day 2、Day 5、Day 8",
);
for (const check of phaseGateChecks) {
  assert(check.phase && check.duration && check.question, `Day ${check.day} 阶段关卡缺少基本信息`);
  assert(check.scaffold?.length >= 3, `Day ${check.day} 阶段关卡结构不足三步`);
  assert(check.keywordGroups?.length >= 3, `Day ${check.day} 阶段关卡覆盖规则不足三组`);
}
assert(
  JSON.stringify(reviewIntervals.map(([daysAfter]) => daysAfter)) === JSON.stringify([1, 3, 7]),
  "复习间隔必须保持 1/3/7 天",
);

assert(sourceLabs.length >= 16, "源码实验室至少需要每天两个精读单元");
for (let dayNumber = 1; dayNumber <= 8; dayNumber += 1) {
  const dailyLabs = sourceLabs.filter((lab) => lab.day === dayNumber);
  assert(dailyLabs.length >= 2, `Day ${dayNumber} 源码精读不足两个`);
}
for (const lab of sourceLabs) {
  assert(lab.title && lab.problem && lab.path && lab.lines, `Day ${lab.day} 源码卡片基本信息不完整`);
  assert(lab.code?.trim(), `Day ${lab.day} 源码卡片缺少代码`);
  assert(lab.explain?.length >= 4, `Day ${lab.day} 源码卡片逐段解释不足`);
  assert(lab.takeaway && lab.check, `Day ${lab.day} 源码卡片缺少面试结论或合页自问`);
  assertSnippetWithinDeclaredRange(lab);
}
assertCodeReferencesExist(sourceLabs.map((lab) => lab.path), "源码精读实验室");

assert(questionBank.length >= 20, `高频题库至少需要 20 题，当前为 ${questionBank.length} 题`);
assert(projectIntroductions.length === 3, "项目介绍必须包含 30 秒、1 分钟和 3 分钟三个版本");
assert(mockQuestions.length >= 10, `最终压力面至少需要 10 题，当前为 ${mockQuestions.length} 题`);
assert(scoreDimensions.length === 5, "最终自评必须包含五个维度");
assert(oralGates.length === 5, "最终口述验收必须包含五关");
for (const gate of oralGates) {
  assert(gate.question && gate.scaffold?.length >= 3, `口述关卡 ${gate.title} 内容不足`);
  assert(gate.keywordGroups?.length >= 3, `口述关卡 ${gate.title} 缺少关键词覆盖规则`);
}

assert(knowledgeDependencies.length === 8, "知识依赖地图必须覆盖 Day 1–8");
assertUnique(knowledgeDependencies.map((item) => item.day), "知识依赖地图天数");
for (const dependency of knowledgeDependencies) {
  assert(
    dependency.shortTitle && dependency.foundation && dependency.focus && dependency.unlocks,
    `Day ${dependency.day} 知识衔接信息不完整`,
  );
}
assert(confusionRoutes.length >= 8, "困惑诊断至少要覆盖八类核心学习阻塞");
for (const [label, targetDay, advice] of confusionRoutes) {
  assert(label && advice, "困惑诊断存在空内容");
  assert(targetDay >= 1 && targetDay <= 8, `困惑诊断指向非法天数 Day ${targetDay}`);
}

assert(guidedStarts.length === 7, "Day 2–8 必须各有一个带学起手课");
assertUnique(guidedStarts.map((item) => item.day), "带学起手课天数");
assert(
  JSON.stringify(guidedStarts.map((item) => item.day)) === JSON.stringify([2, 3, 4, 5, 6, 7, 8]),
  "带学起手课必须连续覆盖 Day 2–8",
);
for (const item of guidedStarts) {
  assert(item.duration && item.sceneTitle && item.scene && item.ignore, `Day ${item.day} 起手课场景不完整`);
  assert(item.concepts?.length === 3, `Day ${item.day} 起手课必须有三个最小概念`);
  assert(item.question && item.template, `Day ${item.day} 起手课缺少首答模板`);
  assert(item.keywordGroups?.length === 3, `Day ${item.day} 起手课必须有三组反馈关键词`);
}

assert(glossary.length >= 24, `项目术语词典至少需要 24 个核心术语，当前为 ${glossary.length} 个`);
assertUnique(glossary.map((item) => item.term), "项目术语词典");
const glossaryCategories = new Set(glossary.map((item) => item.category));
for (const category of ["业务对象", "数据与 RAG", "Agent 编排", "异步执行", "可信与一致性", "性能与可靠性"]) {
  assert(glossaryCategories.has(category), `项目术语词典缺少分类：${category}`);
}
for (const item of glossary) {
  assert(item.term && item.aliases && item.plain && item.role && item.pitfall, `术语 ${item.term || "未知"} 内容不完整`);
  assert(item.day >= 1 && item.day <= 8, `术语 ${item.term} 指向非法学习日 Day ${item.day}`);
}

const requiredSections = [
  "courseDashboard",
  "projectGlossary",
  "knowledgeMap",
  "interviewReadiness",
  "sourceCodeLab",
  "courseGoal",
  "businessFlow",
  "dayContainer",
  "reviewCenter",
  "interviewBank",
  "mockInterviewSection",
  "finalChecklist",
];
for (const sectionId of requiredSections) {
  assert(staticIds.includes(sectionId), `缺少必需课件区域 #${sectionId}`);
}

const requiredRuntimeMarkers = [
  "localStorage",
  "IndexedDB",
  "MediaRecorder",
  "零基础请从这里开始",
  "beginnerDayOneBlock",
  "dayOneBeginnerFeedback",
  "conceptBridgeRows",
  "conceptBridgeState",
  "conceptBridgeBlock",
  "updateConceptBridge",
  "data-concept-bridge",
  "data-concept-bridge-select",
  "data-concept-bridge-explanation",
  "businessBackboneStages",
  "businessBackboneDayMap",
  "renderBusinessBackbone",
  "businessBackboneRecapState",
  "updateBusinessBackboneRecap",
  "businessBackboneRoot",
  "data-business-backbone-stage",
  "data-business-backbone-day",
  "data-business-backbone-recap-answer",
  "sourceLabGuides",
  "openSourceLabDay",
  "data-day-source-lab",
  "source-lab-start",
  "data-beginner-answer",
  "data-beginner-step",
  "dayOneBeginnerCurrentStep",
  "dayOneBeginnerStepMeta",
  "normalizeDayOneBeginnerState",
  "data-beginner-now",
  "data-beginner-content-step",
  "data-beginner-finish-step",
  "renderCourseDashboard",
  "currentLearningAction",
  "currentLearningStop",
  "startCurrentLearningAction",
  "currentActionButton",
  "showDay(dayNumber, false)",
  'scrollIntoView({behavior: "auto", block: "start"})',
  "dashboard-current-action",
  "learning-coach-card",
  "coach-stop",
  "data-dashboard-action",
  "renderProjectGlossary",
  "data-glossary-search",
  "data-glossary-category",
  "data-glossary-day",
  "renderKnowledgeMap",
  "renderInterviewReadiness",
  "interviewReadinessState",
  "dailyOralBlock",
  "dailyOralFeedback",
  "data-daily-oral-pass",
  "phaseGateChecks",
  "phaseGateBlock",
  "phaseGateFeedback",
  "data-phase-gate",
  "data-phase-gate-answer",
  "data-phase-gate-pass",
  "updatePhaseGate",
  "dayGuidedStarts",
  "guidedDayStartBlock",
  "guidedStartFeedback",
  "guidedStartCurrentStep",
  "normalizeGuidedStartState",
  "data-guided-now",
  "data-guided-content-step",
  "data-guided-finish-step",
  "data-guided-answer",
  "renderSourceCodeLab",
  "renderReviewCenter",
  "renderMockInterview",
  "data-day-exit-complete",
];
for (const marker of requiredRuntimeMarkers) {
  assert(html.includes(marker), `缺少自学闭环能力：${marker}`);
}

const summary = {
  file: path.relative(repositoryRoot, coursewarePath),
  bytes: Buffer.byteLength(html),
  days: days.length,
  phaseCounts,
  schedules: days.reduce((total, day) => total + day.schedule.length, 0),
  concepts: days.reduce((total, day) => total + day.concepts.length, 0),
  codeAnchors: days.reduce((total, day) => total + day.code.length, 0),
  dailyQuestions: days.reduce((total, day) => total + day.questions.length, 0),
  quizzes: days.reduce((total, day) => total + day.quiz.length, 0),
  sourceLabs: sourceLabs.length,
  interviewBank: questionBank.length,
  mockQuestions: mockQuestions.length,
  oralGates: oralGates.length,
  dailyOralChecks: dailyOralChecks.length,
  phaseGates: phaseGateChecks.length,
  glossaryTerms: glossary.length,
  conceptBridgeLayers: conceptBridgeRows.length,
  businessBackboneStages: businessBackboneStages.length,
  knowledgeNodes: knowledgeDependencies.length,
  confusionRoutes: confusionRoutes.length,
};

console.log("PASS  MerchPilot 八天 HTML 课件验收");
console.log(JSON.stringify(summary, null, 2));
