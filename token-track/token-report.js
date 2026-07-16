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
