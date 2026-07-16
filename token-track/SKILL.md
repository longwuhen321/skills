---
name: token-track
description: 设置 token 用量自动追踪，每次对话结束后更新项目中的 token-usage.md，记录提问内容、时间戳、token 消耗及拆分明细
---

# token-track — Token 用量追踪

在当前项目中设置自动 token 追踪。每次 Claude 回答完毕后，自动更新项目根目录的 `token-usage.md`，包含：
- 会话概览（总次数、总 token、总费用）
- 每个提问的原文
- 每个提问下按 API 调用拆分的 token 明细（总计行 + 各 depth 子行）

## 触发

当用户使用 `/token-track` 或明确说「记录 token」「追踪 token 用量」「设置 token 报告」时执行。

首次在当前项目运行时，询问用户选择运行模式：

1. **自动模式** — 每次对话结束自动更新报告，无需手动触发
2. **手动模式** — 仅当用户明确说「记录 token」或使用 `/token-track` 时才运行

> 模式按项目独立保存，不同项目可以有不同的模式。

## 文件布局

### 全局（所有项目共用，仅一份）

```
~/.claude/skills/token-track/
├── SKILL.md              ← 本 skill 文件
└── token-report.js       ← 报告生成脚本
```

### 每个项目独立

```
<项目根目录>/
├── .claude/
│   ├── token-track-mode.txt   ← 运行模式（auto / manual）
│   └── settings.local.json    ← Stop hook（自动模式）
└── token-usage.md             ← 生成的报告
```

## 执行流程

### 第一步：确保全局脚本存在

检查 `~/.claude/skills/token-track/token-report.js` 是否存在。不存在则从本 skill 末尾的嵌入式脚本写入。

### 第二步：确定运行模式

检查当前项目 `.claude/token-track-mode.txt` 是否存在。

**如果不存在**（首次在当前项目运行），询问用户：

> 请选择此项目的 token 追踪模式：
> 1. **自动模式（推荐）** — 每次对话结束自动更新 token-usage.md
> 2. **手动模式** — 仅当你说「记录 token」或使用 /token-track 时才更新

用户选择后，将 `auto` 或 `manual` 写入 `.claude/token-track-mode.txt`。

**如果已存在**，读取模式，跳过询问。

### 第三步：根据模式配置 Hook

**自动模式**：读取 `.claude/settings.local.json`，检查是否已有指向 `token-report.js` 的 Stop hook。没有则 merge：

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node ~/.claude/skills/token-track/token-report.js",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**手动模式**：不添加 Stop hook，仅靠用户主动触发。

### 第四步：生成报告

执行脚本，在当前项目根目录生成 `token-usage.md`：

```bash
node ~/.claude/skills/token-track/token-report.js
```

### 第五步：告知用户

**自动模式**：
```
✅ Token 追踪已设置完成！（自动模式）

- 脚本: ~/.claude/skills/token-track/token-report.js
- Hook: 当前项目 .claude/settings.local.json
- 报告: token-usage.md

以后每次对话结束，token-usage.md 会自动更新。
```

**手动模式**：
```
✅ Token 追踪已设置完成！（手动模式）

- 脚本: ~/.claude/skills/token-track/token-report.js
- 报告: token-usage.md

需要记录时，说「记录 token」或输入 /token-track 即可。
```

## 切换模式

如果想切换当前项目的运行模式：
1. 修改 `.claude/token-track-mode.txt` 内容为 `auto` 或 `manual`
2. 从 auto 切到 manual：从 `.claude/settings.local.json` 移除对应的 Stop hook
3. 从 manual 切到 auto：在 `.claude/settings.local.json` 添加 Stop hook（参考第三步）

## 注意事项

- 报告生成依赖 `~/.claude/telemetry/` 中的 API 调用记录（`tengu_api_success` 事件）
- 用户提问内容来自 `~/.claude/history.jsonl`
- 如果 telemetry 中没有当前会话的记录，报告内容为空（新会话需要至少一次 API 调用后才有数据）
- 脚本只处理当前活跃会话的数据，不会混入其他会话

---

## 嵌入式脚本

以下脚本是 `~/.claude/skills/token-track/token-report.js` 的完整内容。如果该文件不存在，将以下代码块写入 `~/.claude/skills/token-track/token-report.js`。

```javascript
#!/usr/bin/env node
/**
 * Token 使用报告生成器
 *
 * 数据来源:
 *   ~/.claude/telemetry/   → tengu_api_success 事件 (token 数据)
 *   ~/.claude/history.jsonl → 用户提问内容
 *   ~/.claude/sessions/    → 当前会话 ID
 *
 * 输出: 当前工作目录/token-usage.md
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

// ── 路径 ──────────────────────────────────────────────
const HOME = os.homedir();
const CLAUDE_DIR = path.join(HOME, '.claude');
const TELEMETRY_DIR = path.join(CLAUDE_DIR, 'telemetry');
const SESSIONS_DIR = path.join(CLAUDE_DIR, 'sessions');
const HISTORY_FILE = path.join(CLAUDE_DIR, 'history.jsonl');

// ── 获取当前 session ID（取最近更新的 session 文件）───
function getSessionId() {
  try {
    const files = fs.readdirSync(SESSIONS_DIR).filter(f => f.endsWith('.json'));
    if (files.length === 0) return null;

    let latest = null;
    let latestTime = 0;
    for (const f of files) {
      const data = JSON.parse(fs.readFileSync(path.join(SESSIONS_DIR, f), 'utf8'));
      const t = data.updatedAt || fs.statSync(path.join(SESSIONS_DIR, f)).mtimeMs;
      if (t > latestTime) {
        latestTime = t;
        latest = data;
      }
    }
    return latest?.sessionId || null;
  } catch (_) { return null; }
}

// ── 读取用户提问 ──────────────────────────────────────
function readQuestions(sessionId) {
  const questions = [];
  try {
    const lines = fs.readFileSync(HISTORY_FILE, 'utf8').trim().split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const entry = JSON.parse(line);
        if (entry.sessionId === sessionId) {
          questions.push({
            text: entry.display || '',
            timestamp: entry.timestamp,
          });
        }
      } catch (_) {}
    }
  } catch (_) {}
  return questions;
}

// ── 读取 telemetry token 数据 ─────────────────────────
function readTokenEvents(sessionId) {
  const events = [];
  try {
    const files = fs.readdirSync(TELEMETRY_DIR).filter(f => f.includes(sessionId));
    for (const file of files) {
      const content = fs.readFileSync(path.join(TELEMETRY_DIR, file), 'utf8');
      const lines = content.trim().split('\n');
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const entry = JSON.parse(line);
          if (entry.event_data?.event_name === 'tengu_api_success' && entry.event_data?.session_id === sessionId) {
            const meta = JSON.parse(
              Buffer.from(entry.event_data.additional_metadata, 'base64').toString()
            );
            events.push({
              timestamp: entry.event_data.client_timestamp,
              queryChainId: meta.queryChainId,
              queryDepth: meta.queryDepth || 0,
              inputTokens: meta.inputTokens || 0,
              outputTokens: meta.outputTokens || 0,
              cachedInputTokens: meta.cachedInputTokens || 0,
              messageTokens: meta.messageTokens || 0,
              estimatedInputTokens: meta.estimatedInputTokens || 0,
              costUSD: meta.costUSD || 0,
              durationMs: meta.durationMs || 0,
              stopReason: meta.stop_reason || '',
              model: meta.preNormalizedModel || meta.model || '',
            });
          }
        } catch (_) {}
      }
    }
  } catch (_) {}
  return events;
}

// ── 匹配问题与 API 调用链 ─────────────────────────────
function matchQuestionsToChains(questions, events) {
  questions.sort((a, b) => a.timestamp - b.timestamp);
  events.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));

  // 按 queryChainId 分组
  const chainMap = new Map();
  for (const ev of events) {
    if (!chainMap.has(ev.queryChainId)) {
      chainMap.set(ev.queryChainId, []);
    }
    chainMap.get(ev.queryChainId).push(ev);
  }

  // 为每个 chain 找对应的用户问题（时间最接近的前一个问题）
  const chains = [];
  for (const [chainId, chainEvents] of chainMap) {
    const firstApiTime = new Date(chainEvents[0].timestamp).getTime();
    let matchedQuestion = null;
    for (const q of questions) {
      if (q.timestamp < firstApiTime + 3000) {
        matchedQuestion = q;
      } else {
        break;
      }
    }
    chains.push({
      question: matchedQuestion,
      chainId,
      events: chainEvents,
    });
  }

  chains.sort((a, b) => {
    const ta = a.events[0] ? new Date(a.events[0].timestamp).getTime() : 0;
    const tb = b.events[0] ? new Date(b.events[0].timestamp).getTime() : 0;
    return ta - tb;
  });

  return chains;
}

// ── 格式化 ────────────────────────────────────────────
function fmtNum(n) {
  if (n === 0) return '0';
  return n.toLocaleString('en-US');
}

function fmtCost(n) {
  if (n === 0) return '$0';
  return '$' + n.toFixed(4);
}

function fmtDuration(ms) {
  if (ms < 1000) return ms + 'ms';
  if (ms < 60000) return (ms / 1000).toFixed(1) + 's';
  return (ms / 60000).toFixed(1) + 'min';
}

function fmtTime(isoStr) {
  const d = new Date(isoStr);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

function truncate(str, maxLen) {
  if (!str) return '(无内容)';
  return str.length > maxLen ? str.substring(0, maxLen) + '...' : str;
}

// ── 生成 Markdown ─────────────────────────────────────
function generateMarkdown(sessionId, chains) {
  const now = new Date();
  const shortSessionId = sessionId ? sessionId.substring(0, 8) : 'unknown';

  let md = `# Token 使用记录\n\n`;
  md += `> 生成时间: ${now.toLocaleString('zh-CN')}\n`;
  md += `> 会话: \`${shortSessionId}\`\n\n`;
  md += `---\n\n`;

  if (chains.length === 0) {
    md += `*暂无数据 — 进行一次对话后自动更新*\n`;
    return md;
  }

  // 全局统计
  let totalInput = 0, totalOutput = 0, totalCost = 0, totalDuration = 0;
  for (const chain of chains) {
    for (const ev of chain.events) {
      totalInput += ev.inputTokens + ev.cachedInputTokens;
      totalOutput += ev.outputTokens;
      totalCost += ev.costUSD;
      totalDuration += ev.durationMs;
    }
  }

  md += `## 📊 会话概览\n\n`;
  md += `| 指标 | 数值 |\n`;
  md += `|------|------|\n`;
  md += `| 提问次数 | ${chains.length} |\n`;
  md += `| API 调用次数 | ${chains.reduce((s, c) => s + c.events.length, 0)} |\n`;
  md += `| 输入 Token | ${fmtNum(totalInput)} |\n`;
  md += `| 输出 Token | ${fmtNum(totalOutput)} |\n`;
  md += `| 总费用 | ${fmtCost(totalCost)} |\n`;
  md += `| 总耗时 | ${fmtDuration(totalDuration)} |\n\n`;
  md += `---\n\n`;

  // 每个问答对
  for (let i = 0; i < chains.length; i++) {
    const chain = chains[i];
    const qText = chain.question ? chain.question.text : '(未匹配到提问)';
    const questionTime = chain.question
      ? new Date(chain.question.timestamp).toLocaleTimeString('zh-CN', { hour12: false })
      : '--:--:--';

    let cInput = 0, cOutput = 0, cCached = 0, cCost = 0, cDuration = 0;
    for (const ev of chain.events) {
      cInput += ev.inputTokens + ev.cachedInputTokens;
      cOutput += ev.outputTokens;
      cCached += ev.cachedInputTokens;
      cCost += ev.costUSD;
      cDuration += ev.durationMs;
    }

    md += `## Q${i + 1}: ${truncate(qText, 80)}\n`;
    md += `> 提问时间: ${questionTime} | API 调用: ${chain.events.length} 次\n\n`;

    md += `| 层级 | 时间 | Input | Output | Cache | 费用 | 耗时 |\n`;
    md += `|------|------|-------|--------|-------|------|------|\n`;

    // 总计行
    md += `| **📌 总计** | - | **${fmtNum(cInput)}** | **${fmtNum(cOutput)}** | ${fmtNum(cCached)} | **${fmtCost(cCost)}** | ${fmtDuration(cDuration)} |\n`;

    // 拆分行 - 按 depth 排序
    const sorted = [...chain.events].sort((a, b) => a.queryDepth - b.queryDepth);
    for (let j = 0; j < sorted.length; j++) {
      const ev = sorted[j];
      const isLast = j === sorted.length - 1;
      const prefix = isLast ? ' └─' : ' ├─';
      const depthLabel = `depth ${ev.queryDepth}`;
      md += `| ${prefix} ${depthLabel} | ${fmtTime(ev.timestamp)} | ${fmtNum(ev.inputTokens + ev.cachedInputTokens)} | ${fmtNum(ev.outputTokens)} | ${fmtNum(ev.cachedInputTokens)} | ${fmtCost(ev.costUSD)} | ${fmtDuration(ev.durationMs)} |\n`;
    }

    md += `\n`;
  }

  return md;
}

// ── 主流程 ────────────────────────────────────────────
function main() {
  const sessionId = getSessionId();

  if (!sessionId) {
    console.error('[token-report] 无法获取 session ID');
    process.exit(1);
  }

  const questions = readQuestions(sessionId);
  const events = readTokenEvents(sessionId);

  if (events.length === 0) {
    console.log(`[token-report] 当前会话 (${sessionId.substring(0, 8)}) 暂无 API 调用记录，跳过生成。`);
    process.exit(0);
  }

  const chains = matchQuestionsToChains(questions, events);
  const md = generateMarkdown(sessionId, chains);

  const outputPath = path.join(process.cwd(), 'token-usage.md');
  fs.writeFileSync(outputPath, md, 'utf8');
  console.log(`[token-report] 已更新: token-usage.md (${chains.length} 个问答, ${events.length} 次 API 调用)`);
}

main();
```
