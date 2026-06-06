/* ============================
   解题能手 - 前端逻辑
   ============================ */

let serverPort = 5199;
let currentFile = null;
let parsedQuestions = [];
let solvedAnswers = [];
let monacoEditor = null;
let currentCodeQuestion = null;
let currentCodeFiles = [];      // [{name, code}, ...] — multi-file support (P1 C3)
let currentMainFile = '';       // entry-point filename
let lastOutputPath = null;

// Agent 标准模式（Phase 2a.3）
let agentPlanSteps = [];
let agentPlanFingerprint = '';
let agentDocumentIds = [];
let agentSectionsConfig = {};
let agentSplitIdx = null;
let agentClarifications = [];
let agentClarificationAnswers = {};
let agentRunId = null;
let agentEventSource = null;
let agentPlanStale = false;
let agentExecutionMode = false;
let agentPlanStepsSnapshot = '';
let agentPlanBaselineSteps = [];
let agentPlanFeedback = null;
let agentReplanNotified = false;
let agentUnderstand = null;
let agentVerificationReport = null;
let parsedMetadata = {};
let agentFormatSpec = null;
let agentFillTarget = null;
let agentOutputMode = 'deliverable';
let currentDeliverable = null;
let pairedDocxPath = null;
let agentModuleResults = null;
let agentConfirmedSteps = [];
let agentDecisionLog = [];
let lastSessionRunMode = 'standard';
let agentRunFinished = false;
let agentThoughtCollapsed = true;
let agentThoughtLog = [];
let lastThoughtLogPath = null;
let lastAgentRunId = null;
let agentDirtyModules = [];
let agentFillSections = null;
let agentAnswerTemplateText = '';
let uploadedDocuments = [];
let agentDocLayout = null;
let agentSplitAtHeading = '';
let agentSplitCandidates = [];
let agentPrimaryFullText = '';
let agentAssignmentText = '';
let agentTemplatePending = null;
let agentTemplateConfirmed = false;
let agentAwaitingSplitConfirm = false;
let agentSplitDirty = false;

// DA4: section detection state
let agentSectionsDetected = [];
let agentSectionMap = {};
let agentFillHints = {};
let agentReportLayout = '';
let agentTableMap = [];
let agentUserSemanticOverrides = {};

const DOC_ROLE_OPTIONS = [
  { value: 'auto', label: '自动识别' },
  { value: 'fill_target', label: '待填报告' },
  { value: 'assignment', label: '题目 / 要求' },
  { value: 'answer_template', label: '范文 / 模版' },
  { value: 'fill_template', label: '空白填表模版' },
  { value: 'reference', label: '参考资料' },
];

const DOC_ROLE_LABELS = {
  auto: '自动识别',
  fill_target: '待填报告',
  assignment: '题目 / 要求',
  answer_template: '范文 / 模版',
  fill_template: '空白填表模版',
  reference: '参考资料',
};

const DOC_ROLE_COLORS = {
  fill_target: 'var(--accent)',
  assignment: 'var(--purple)',
  answer_template: 'var(--yellow)',
  fill_template: 'var(--green)',
  reference: 'var(--text-secondary)',
  auto: 'var(--text-muted)',
};

const DOC_FORMAT_ICONS = {
  docx: '📄',
  pdf: '📕',
  doc: '📝',
  text: '📋',
};

const SPLIT_HEADING_PATTERNS = [
  /^三[、．.\s]*.*(实验步骤|实验内容|内容及步骤)/i,
  /^3[、．.\s]*.*(实验步骤|实验内容|内容及步骤)/i,
  /^三[、．.\s]*实验步骤/i,
  /^三[、．.\s]*实验内容/i,
];

const SECTION_ROW_DEFS = [
  { id: 'cover', label: '封面 / 表头' },
  { id: 'steps', label: '三、实验内容及步骤' },
  { id: 'result', label: '四、实验结果' },
  { id: 'summary', label: '五、实验总结' },
];

function getDynamicSectionRowDefs() {
  const detected = agentSectionsDetected || [];
  const overrides = agentUserSemanticOverrides || {};

  // Dynamic mode: build row defs from detected sections
  if (detected.length) {
    return detected.map((sec, i) => {
      const id = `sec_${i}`;
      const overriddenRole = Object.entries(overrides).find(([, h]) => h === sec.heading)?.[0];
      const effectiveSemantic = overriddenRole || sec.semantic;
      const roleLabel = effectiveSemantic && SEMANTIC_LABEL_MAP[effectiveSemantic]
        ? ` → ${SEMANTIC_LABEL_MAP[effectiveSemantic]}`
        : '';
      return {
        id,
        label: `${sec.heading}${roleLabel}`,
        _detectedHeading: sec.heading,
        _semantic: effectiveSemantic || null,
      };
    });
  }

  // Fallback: old static defs with section_map enrichment
  const sm = agentSectionMap || {};
  return SECTION_ROW_DEFS.map((def) => {
    if (def.id === 'cover') return { ...def };
    const mapped = sm[def.id];
    const heading = mapped?.heading || '';
    const overridden = overrides[def.id];
    if (overridden) {
      return { ...def, label: `${heading} → ${overridden}（已手动映射）`, _detectedHeading: heading };
    }
    if (heading) {
      return { ...def, label: heading, _detectedHeading: heading };
    }
    return { ...def, _detectedHeading: '' };
  });
}

const LAYOUT_BADGE_LABELS = {
  standard_sections: '标准三节',
  variant_sections: '变体节号',
  training_table: '实训表格',
};

function getLayoutBadgeLabel() {
  return LAYOUT_BADGE_LABELS[agentReportLayout] || '';
}

const SEMANTIC_LABEL_MAP = {
  objective: '实验目的',
  principles: '实验原理',
  steps: '实验步骤',
  result: '实验结果',
  summary: '实验总结',
  discussion: '讨论/思考题',
  appendix: '附录',
  other: '未知类型',
};

function getEffectiveSectionMap() {
  const base = { ...(agentSectionMap || {}) };
  Object.entries(agentUserSemanticOverrides || {}).forEach(([role, heading]) => {
    if (heading === '__none__') {
      base[role] = null;
    } else if (heading) {
      const entry = (agentSectionsDetected || []).find((s) => s.heading === heading);
      base[role] = entry
        ? { type: 'paragraph', heading: entry.heading, para_index: entry.index }
        : base[role];
    }
  });
  return base;
}

const FILL_MODE_OPTIONS = [
  { value: 'auto', label: 'AI 填写' },
  { value: 'user_provided', label: '用我的内容' },
  { value: 'skip', label: '不填' },
  { value: 'preserve', label: '有内容不覆盖' },
  { value: 'generate_only', label: '只生成不写入' },
];

const VERIFY_CHECK_LABELS = {
  schema_complete: '结构完整',
  no_placeholder: '无占位符',
  code_runs: '代码可运行',
  output_consistency: '输出一致性',
  fill_ready: '可填表',
  images_ready: '截图就绪',
  uml_code_consistency: 'UML 与代码一致',
  uml_render_valid: '图表渲染有效',
  diagram_schema: '图表 schema',
  diagram_render: '图表渲染结果',
  plagiarism_check: '范文相似度',
  constraint_present: '老师要求',
  constraint_position: '要求位置',
};

const VERIFY_ACTION_LABELS = {
  fix_code: '自动修代码',
  revise_full: '整题重写',
  'revise_section:result': '修订结果节',
};

const REVISE_SCOPE_OPTIONS = [
  { id: 'steps', label: '实验步骤' },
  { id: 'result', label: '结果说明' },
  { id: 'summary', label: '总结' },
  { id: 'code', label: '代码' },
  { id: 'screenshots', label: '截图/格式' },
];

const REVISE_QUICK_TAGS = [
  '写得太短',
  '写得太长',
  '代码跑不通',
  '和题目无关',
  '语气不对',
  '要像模版',
];

const VERIFY_WARN_IDS = new Set([
  'plagiarism_check', 'fill_ready', 'output_consistency', 'images_ready',
  'uml_code_consistency', 'uml_render_valid',
]);

const AGENT_MODULE_LABELS = {
  solve_lab: '生成实验报告内容',
  solve_theory: '理论题解答',
  run_code: '运行代码',
  fix_code: '修复代码',
  screenshot_ide: 'IDE 截图',
  screenshot_terminal: '终端截图',
  render_uml: '渲染图表',
  fix_diagrams: '修复图表',
  fill_report: '填入 Word（实验性）',
  present_deliverable: '汇编答案交付物',
};

const DELIVERABLE_SECTION_TABS = [
  { id: 'steps_analysis', label: '步骤 / 分析' },
  { id: 'result_description', label: '结果说明' },
  { id: 'summary', label: '总结' },
  { id: 'code', label: '代码' },
  { id: 'diagrams', label: '图表' },
];

const DELIVERABLE_VALIDATION_LABELS = {
  verified: '已验证',
  failed: '验证失败',
  skipped: '未验证',
  not_requested: '未请求验证',
};

function isContentOnlyOutputMode(mode) {
  const m = mode || getOutputMode();
  return m === 'deliverable' || m === 'answer_only';
}

// ============================
// 初始化
// ============================

async function init() {
  serverPort = await window.electronAPI.getServerPort();
  await initSettingsStorage();

  // 监听服务器就绪事件
  window.electronAPI.onServerReady(() => {
    hideLoading();
    loadSettings();
    fetchLogFilePath(apiGet).catch(() => {});
    runComplianceStartupSequence(apiGet).catch(() => {});
    renderHistory();
    showToast('AI引擎就绪', 'success');
    setServerStatus(true);
  });

  window.electronAPI.onServerError((msg) => {
    document.getElementById('loadingStatus').textContent = '后端启动失败: ' + msg;
    setServerStatus(false);
    // 即使后端失败也允许使用界面
    setTimeout(hideLoading, 2000);
  });

  // 超时保护：5秒后强制显示
  setTimeout(() => {
    hideLoading();
    loadSettings();
    fetchLogFilePath(apiGet).catch(() => {});
    runComplianceStartupSequence(apiGet).catch(() => {});
    renderHistory();
  }, 5000);

  initMonaco();
  initAgentPlanWatchers();
  initRevisePanelUI();
  renderDocumentList();
}

function initRevisePanelUI() {
  const tagsEl = document.getElementById('agentReviseTags');
  if (tagsEl) {
    tagsEl.innerHTML = '';
    REVISE_QUICK_TAGS.forEach((tag) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'revise-tag-btn';
      btn.textContent = tag;
      btn.onclick = () => appendReviseTag(tag);
      tagsEl.appendChild(btn);
    });
  }
  const scopesEl = document.getElementById('agentReviseScopes');
  if (scopesEl) {
    REVISE_SCOPE_OPTIONS.forEach((opt) => {
      const label = document.createElement('label');
      label.className = 'revise-scope-check';
      label.innerHTML = `<input type="checkbox" name="reviseScope" value="${opt.id}"> ${opt.label}`;
      scopesEl.appendChild(label);
    });
  }
}

function appendReviseTag(tag) {
  const el = document.getElementById('agentReviseFeedback');
  if (!el) return;
  const cur = el.value.trim();
  el.value = cur ? `${cur}；${tag}` : tag;
}

function getUserConstraints() {
  const out = [];
  if (document.getElementById('constraintSkipValidation')?.checked) {
    out.push('skip_validation');
  }
  if (document.getElementById('constraintNoExternalJar')?.checked) {
    out.push('no_external_jar');
  }
  if (document.getElementById('constraintProvenanceLabel')?.checked) {
    out.push('provenance_label');
  }
  return out;
}

function getProvenanceCustomLabel() {
  return document.getElementById('provenanceCustomLabel')?.value?.trim() || '';
}

function syncUserConstraintsUI(constraints) {
  const list = constraints || [];
  const skipEl = document.getElementById('constraintSkipValidation');
  const jarEl = document.getElementById('constraintNoExternalJar');
  const provEl = document.getElementById('constraintProvenanceLabel');
  if (skipEl) skipEl.checked = list.includes('skip_validation');
  if (jarEl) jarEl.checked = list.includes('no_external_jar');
  if (provEl) provEl.checked = list.includes('provenance_label');
}

function onUserConstraintsChange() {
  const constraints = getUserConstraints();
  persistSettingsPatch({ userConstraints: constraints });
  markAgentPlanStale();
}

function onProvenanceLabelChange() {
  persistSettingsPatch({ provenanceCustomLabel: getProvenanceCustomLabel() });
}

function initAgentPlanWatchers() {
  ['solveLang', 'includeCodeCheck', 'includeUmlCheck', 'constraintSkipValidation', 'constraintNoExternalJar', 'constraintProvenanceLabel'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => {
      syncSectionsGlobalFromSolveBar();
      markAgentPlanStale();
    });
  });
  const globalRules = document.getElementById('sectionsGlobalRules');
  if (globalRules) {
    globalRules.addEventListener('input', () => {
      syncAgentSectionsConfigFromUI();
      markAgentPlanStale();
    });
  }
}

function getShowThoughtTrace() {
  const el = document.getElementById('showThoughtTraceSettings');
  if (el) return el.checked;
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  return saved.showThoughtTrace === true;
}

function onShowThoughtTraceChange() {
  const el = document.getElementById('showThoughtTraceSettings');
  persistSettingsPatch({ showThoughtTrace: el ? el.checked : false });
  updateThoughtSidebarVisibility();
}

function shouldShowThoughtSidebarShell() {
  const showSetting = getRunMode() === 'deep' || getRunMode() === 'react' || getShowThoughtTrace();
  return showSetting && (agentExecutionMode || agentRunFinished);
}

function shouldExpandThoughtBody() {
  return shouldShowThoughtSidebarShell() && !agentThoughtCollapsed;
}

function updateThoughtSidebarVisibility() {
  const sidebar = document.getElementById('agentThoughtSidebar');
  const layout = document.getElementById('step3Layout');
  const body = document.getElementById('agentThoughtBody');
  const toggle = document.getElementById('thoughtSidebarToggle');
  const showShell = shouldShowThoughtSidebarShell();
  if (sidebar) sidebar.classList.toggle('visible', showShell);
  if (layout) layout.classList.toggle('has-thought', showShell);
  if (body) body.classList.toggle('collapsed', !shouldExpandThoughtBody());
  if (toggle) {
    toggle.textContent = agentThoughtCollapsed ? '展开' : '收起';
    toggle.setAttribute('aria-expanded', String(!agentThoughtCollapsed));
  }
  updateThoughtSidebarBadge();
}

function toggleThoughtSidebar() {
  agentThoughtCollapsed = !agentThoughtCollapsed;
  updateThoughtSidebarVisibility();
}

function updateThoughtSidebarBadge() {
  const badge = document.getElementById('thoughtSidebarBadge');
  const body = document.getElementById('agentThoughtBody');
  const exportBtn = document.getElementById('thoughtExportBtn');
  if (!badge) return;
  const n = agentThoughtLog.length
    || (body ? body.querySelectorAll('.agent-thought-block').length : 0);
  if (n > 0) {
    badge.textContent = `${n} 段`;
  } else if (getRunMode() === 'deep' && (agentExecutionMode || agentRunFinished)) {
    badge.textContent = '深度';
  } else {
    badge.textContent = '';
  }
  if (exportBtn) {
    exportBtn.style.display = n ? 'inline-block' : 'none';
  }
}

function clearAgentThoughtLog() {
  agentThoughtLog = [];
  lastThoughtLogPath = null;
  const exportBtn = document.getElementById('thoughtExportBtn');
  if (exportBtn) exportBtn.style.display = 'none';
}

function recordAgentThought(entry) {
  if (!entry) return;
  agentThoughtLog.push({
    timestamp: new Date().toISOString(),
    ...entry,
  });
  updateThoughtSidebarBadge();
}

function ingestThoughtTrace(trace) {
  if (!Array.isArray(trace) || !trace.length) return;
  agentThoughtLog = trace.map((item) => ({
    timestamp: new Date().toISOString(),
    type: 'react_cycle',
    round: item.round,
    max_rounds: item.max_rounds,
    thought: item.thought || '',
    action: item.action || '',
    params: item.params || {},
    result_ok: item.result_ok,
    result_summary: item.result_summary || '',
  }));
  updateThoughtSidebarBadge();
}

function defaultThoughtLogFileName() {
  const stem = (currentFile && currentFile !== 'demo')
    ? currentFile.split(/[\\/]/).pop().replace(/\.[^.]+$/, '')
    : '实验报告';
  const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
  const mode = lastSessionRunMode || getRunMode() || 'agent';
  return `思考过程_${stem}_${mode}_${ts}.txt`;
}

function formatThoughtLogText() {
  const lines = [];
  const now = new Date();
  const docName = (currentFile && currentFile !== 'demo')
    ? currentFile.split(/[\\/]/).pop()
    : '(未命名)';
  lines.push('解题能手 — 思考过程导出');
  lines.push(`导出时间: ${now.toLocaleString('zh-CN')}`);
  lines.push(`运行模式: ${lastSessionRunMode || getRunMode() || 'unknown'}`);
  lines.push(`文档: ${docName}`);
  if (lastAgentRunId || agentRunId) lines.push(`运行 ID: ${lastAgentRunId || agentRunId}`);
  if (lastOutputPath) lines.push(`报告输出: ${lastOutputPath}`);
  lines.push('');

  const notes = solvedAnswers[0]?.parsed?.notes
    || agentModuleResults?.solve_lab?.data?.parsed?.notes;
  if (notes) {
    lines.push('=== AI 自述 (notes) ===');
    lines.push(notes);
    lines.push('');
  }

  if (agentDecisionLog.length) {
    lines.push('=== 决策日志 ===');
    agentDecisionLog.forEach((d, i) => {
      lines.push(`[${i + 1}] ${d.agent || ''} · ${d.decision || ''} → ${d.target || ''}`);
      if (d.reason) lines.push(`    原因: ${d.reason}`);
      if (d.evidence) lines.push(`    依据: ${d.evidence}`);
    });
    lines.push('');
  }

  if (!agentThoughtLog.length) {
    lines.push('（无思考过程记录）');
    return lines.join('\n');
  }

  lines.push('=== 思考过程 ===');
  agentThoughtLog.forEach((item) => {
    if (item.type === 'react_cycle') {
      const status = item.result_ok ? 'OK' : 'FAIL';
      lines.push('');
      lines.push(`--- 第 ${item.round || '?'}/${item.max_rounds || '?'} 轮 [${item.action || '?'} ${status}] ---`);
      if (item.thought) {
        lines.push('【思考】');
        lines.push(item.thought);
      }
      if (item.params && Object.keys(item.params).length) {
        lines.push('【参数】');
        lines.push(JSON.stringify(item.params, null, 2));
      }
      if (item.result_summary) {
        lines.push('【结果】');
        lines.push(item.result_summary);
      }
      return;
    }
    lines.push('');
    lines.push(`--- ${item.phase || item.type || '记录'} ---`);
    if (item.text) lines.push(item.text);
  });
  lines.push('');
  return lines.join('\n');
}

async function saveThoughtLogAuto() {
  if (!agentThoughtLog.length && !agentDecisionLog.length) return null;
  const content = formatThoughtLogText();
  const fileName = defaultThoughtLogFileName();
  try {
    const resp = await window.electronAPI.writeThoughtLog(fileName, content);
    lastThoughtLogPath = resp.filePath || null;
    return lastThoughtLogPath;
  } catch (e) {
    console.warn('auto-save thought log failed', e);
    return null;
  }
}

async function exportThoughtLogManual() {
  const content = formatThoughtLogText();
  if (!content || content.includes('（无思考过程记录）')) {
    showToast('暂无可导出的思考过程', 'info');
    return;
  }
  try {
    const resp = await window.electronAPI.saveTextDialog(defaultThoughtLogFileName(), content);
    if (resp.canceled) return;
    lastThoughtLogPath = resp.filePath || null;
    updateThoughtLogSavedUI(lastThoughtLogPath);
    showToast('思考过程已导出', 'success');
    if (lastThoughtLogPath) {
      const open = confirm('是否用记事本打开导出的文件？');
      if (open) await window.electronAPI.openFileExternal(lastThoughtLogPath);
    }
  } catch (e) {
    showToast('导出失败: ' + e.message, 'error');
  }
}

function updateThoughtLogSavedUI(filePath) {
  const note = document.getElementById('thoughtLogSavedNote');
  const openBtn = document.getElementById('openThoughtLogBtn');
  if (note && filePath) {
    note.textContent = '思考过程已保存: ' + filePath;
    note.style.display = 'block';
  }
  if (openBtn) {
    openBtn.style.display = filePath ? 'inline-flex' : 'none';
  }
}

async function openThoughtLogFile() {
  if (!lastThoughtLogPath) {
    showToast('暂无已保存的思考过程', 'info');
    return;
  }
  await window.electronAPI.openFileExternal(lastThoughtLogPath);
}

function estimateSectionCharCounts(fullText) {
  const counts = { cover: 0, steps: 0, result: 0, summary: 0 };
  if (!fullText) return counts;
  const lines = fullText.split('\n').map((l) => l.trim()).filter(Boolean);
  const bounds = [];
  const patterns = [
    { id: 'steps', re: /^三[、.．\s]/ },
    { id: 'result', re: /^四[、.．\s]/ },
    { id: 'summary', re: /^五[、.．\s]/ },
  ];
  lines.forEach((line, idx) => {
    for (const p of patterns) {
      if (p.re.test(line)) bounds.push({ id: p.id, idx });
    }
  });
  bounds.sort((a, b) => a.idx - b.idx);
  const firstIdx = bounds.length ? bounds[0].idx : lines.length;
  counts.cover = lines.slice(0, firstIdx).join('\n').length;
  for (let i = 0; i < bounds.length; i++) {
    const start = bounds[i].idx + 1;
    const end = i + 1 < bounds.length ? bounds[i + 1].idx : lines.length;
    const body = lines.slice(start, end).join('\n');
    counts[bounds[i].id] = body.length;
  }
  return counts;
}

function estimateSectionCharCountsFromDetected(fullText, sectionsDetected) {
  const counts = {};
  if (!fullText || !sectionsDetected?.length) return counts;

  const positions = [];
  sectionsDetected.forEach((sec, i) => {
    const heading = sec.heading || '';
    if (!heading) return;
    const pos = fullText.indexOf(heading);
    if (pos >= 0) {
      positions.push({ id: `sec_${i}`, pos, heading });
    }
  });
  positions.sort((a, b) => a.pos - b.pos);

  if (!positions.length) return counts;

  // Content before first heading belongs to first section
  if (positions[0].pos > 0) {
    counts[positions[0].id] = fullText.slice(0, positions[0].pos).length;
  }

  // Content between heading A and heading B belongs to section A
  for (let i = 0; i < positions.length; i++) {
    const startPos = positions[i].pos + positions[i].heading.length;
    const endPos = i + 1 < positions.length ? positions[i + 1].pos : fullText.length;
    const content = fullText.slice(Math.max(0, startPos), Math.max(0, endPos));
    counts[positions[i].id] = (counts[positions[i].id] || 0) + content.length;
  }

  return counts;
}

function syncSectionsGlobalFromSolveBar() {
  const lang = document.getElementById('solveLang')?.value;
  const includeCode = document.getElementById('includeCodeCheck')?.checked !== false;
  const includeUml = document.getElementById('includeUmlCheck')?.checked === true;
  if (!agentSectionsConfig.global) agentSectionsConfig.global = {};
  if (lang) agentSectionsConfig.global.language = lang;
  agentSectionsConfig.global.include_code = includeCode;
  agentSectionsConfig.global.include_uml = includeUml;
  agentSectionsConfig.global.screenshot_style = getScreenshotChrome() === 'mac' ? 'mac' : 'ide';
}

function buildDefaultSectionsConfig(question, metadata) {
  const fullText = question?.full_text || question?.content || '';
  const detected = agentSectionsDetected || [];

  let sections;
  if (detected.length) {
    const counts = estimateSectionCharCountsFromDetected(fullText, detected);
    sections = detected.map((sec, i) => {
      const id = `sec_${i}`;
      const semantic = sec.semantic || null;
      const chars = counts[id] || 0;
      const isCore = semantic === 'steps' || semantic === 'result' || semantic === 'summary';
      return {
        id,
        mode: isCore ? 'auto' : 'skip',
        input: '',
        attachments: {},
        _doc_chars: chars,
        _semantic: semantic,
        _label: sec.heading || '',
      };
    });
  } else {
    // Fallback to old 4-row template
    const counts = estimateSectionCharCounts(fullText);
    sections = SECTION_ROW_DEFS.map((def) => {
      const chars = counts[def.id] || 0;
      let mode = 'auto';
      if (def.id === 'cover') mode = 'skip';
      else if (chars > 80) mode = 'preserve';
      return {
        id: def.id,
        mode,
        input: '',
        attachments: {},
        _doc_chars: chars,
      };
    });
  }

  return {
    global: {
      language: document.getElementById('solveLang')?.value || 'python',
      include_code: document.getElementById('includeCodeCheck')?.checked !== false,
      include_uml: document.getElementById('includeUmlCheck')?.checked === true,
      screenshot_style: 'ide',
    },
    sections,
    _meta: { source: 'parse', metadata: metadata || {} },
  };
}

function renderSectionsWorkbench(question, metadata, formatSpec) {
  const workbench = document.getElementById('sectionsWorkbench');
  const actionBar = document.querySelector('.sections-action-bar');
  const list = document.getElementById('sectionsRowsList');
  if (!list) return;

  const isLab = question?.type === 'lab_report';
  if (workbench) workbench.style.display = isLab ? 'block' : 'none';
  if (actionBar) actionBar.style.display = isLab ? 'flex' : 'none';
  if (!isLab) return;

  // Training table: independent UI, no section rows
  if (agentReportLayout === 'training_table') {
    renderTrainingTablePanel();
    return;
  }

  if (!agentSectionsConfig.sections?.length) {
    agentSectionsConfig = buildDefaultSectionsConfig(question, metadata);
  }
  syncSectionsGlobalFromSolveBar();

  const hasDynamicSections = (agentSectionsDetected || []).length > 0;
  const counts = hasDynamicSections
    ? {}
    : estimateSectionCharCounts(question?.full_text || '');
  const specMap = formatSpec?.section_map || formatSpec?.aligned_section_map || {};

  list.innerHTML = '';
  const dynamicDefs = getDynamicSectionRowDefs();
  (agentSectionsConfig.sections || []).forEach((sec, idx) => {
    const def = dynamicDefs.find((d) => d.id === sec.id) || { id: sec.id, label: sec.id };
    const chars = sec._doc_chars ?? counts[sec.id] ?? 0;
    const statusText = chars > 0 ? `文档已有约 ${chars} 字` : '文档为空';
    const tpl = specMap[sec.id];
    const tplHint = tpl?.avg_chars
      ? `模版建议约 ${tpl.avg_chars} 字${tpl.requires_images ? '，需配图' : ''}`
      : '';

    const row = document.createElement('div');
    row.className = 'section-row';
    row.dataset.sectionId = sec.id;
    const modeOpts = FILL_MODE_OPTIONS.map(
      (o) => `<option value="${o.value}" ${sec.mode === o.value ? 'selected' : ''}>${o.label}</option>`
    ).join('');

    row.innerHTML = `
      <div class="section-row-head">
        <span class="section-row-title">${escapeHtml(def.label)}</span>
        <span class="section-row-status">${escapeHtml(statusText)}</span>
        <select class="section-row-mode" data-section-idx="${idx}">${modeOpts}</select>
      </div>
      ${tplHint ? `<div class="section-row-tags"><span class="section-tag template">${escapeHtml(tplHint)}</span></div>` : ''}
      <textarea class="form-input section-row-input" data-section-idx="${idx}" rows="3"
        placeholder="可粘贴本节全文；也可写老师要求（如：末尾须有防伪码 CS2024）；可混写，点「智能解析」拆分"></textarea>
      <div class="section-constraints" data-constraints-idx="${idx}" style="display:none"></div>
      <details class="section-attachments" data-attachments-idx="${idx}">
        <summary class="form-hint">附件（代码 / 图片，可选）</summary>
        <textarea class="form-input section-attach-code" data-section-idx="${idx}" rows="2" placeholder="本节附带代码（写入步骤节时）"></textarea>
        <label class="section-attach-images">
          <span class="form-hint">结果节图片</span>
          <input type="file" accept="image/*" multiple class="section-attach-file" data-section-idx="${idx}">
          <span class="section-attach-count form-hint" data-section-idx="${idx}"></span>
        </label>
      </details>
      <div class="section-row-actions">
        <button type="button" class="btn-secondary btn-sm section-parse-btn" data-section-idx="${idx}">智能解析本段</button>
      </div>
    `;

    const modeSel = row.querySelector('.section-row-mode');
    const input = row.querySelector('.section-row-input');
    input.value = sec.input || '';
    const disabled = sec.mode === 'skip';
    input.disabled = disabled;
    input.placeholder = disabled
      ? '本节不填，可只读记录老师要求备查'
      : input.placeholder;

    modeSel.addEventListener('change', () => {
      agentSectionsConfig.sections[idx].mode = modeSel.value;
      const dis = modeSel.value === 'skip';
      input.disabled = dis;
      syncAgentSectionsConfigFromUI();
      markAgentPlanStale();
      maybeWarnLongTextForAutoMode(row, idx, input.value, modeSel.value);
    });
    input.addEventListener('input', () => {
      agentSectionsConfig.sections[idx].input = input.value;
      syncAgentSectionsConfigFromUI();
      markAgentPlanStale();
      maybeWarnLongTextForAutoMode(row, idx, input.value, modeSel.value);
    });
    row.querySelector('.section-parse-btn').addEventListener('click', () => parseSectionBriefForRow(idx));

    const attachCode = row.querySelector('.section-attach-code');
    if (attachCode) {
      attachCode.value = sec.attachments?.code || '';
      attachCode.addEventListener('input', () => {
        if (!agentSectionsConfig.sections[idx].attachments) {
          agentSectionsConfig.sections[idx].attachments = {};
        }
        agentSectionsConfig.sections[idx].attachments.code = attachCode.value;
        markAgentPlanStale();
      });
    }
    const attachFile = row.querySelector('.section-attach-file');
    if (attachFile) {
      const imgCount = (sec.attachments?.images_b64 || []).length;
      updateSectionAttachCount(row, idx, imgCount);
      attachFile.addEventListener('change', () => loadSectionImages(idx, attachFile, row));
    }

    renderSectionConstraints(row, idx, sec.constraints || []);
    list.appendChild(row);
  });

  const globalRules = document.getElementById('sectionsGlobalRules');
  if (globalRules) {
    globalRules.value = agentSectionsConfig.global_rules || '';
  }
}

function renderTrainingTablePanel() {
  const list = document.getElementById('sectionsRowsList');
  if (!list) return;

  const entries = agentTableMap || [];
  list.innerHTML = '';

  if (!entries.length) {
    list.innerHTML = '<div class="empty-state"><span>📋</span><p>未检测到实训表格结构</p><p class="form-hint">请确认报告版式为 training_table，或尝试重新解析</p></div>';
    return;
  }

  // Build fill config keyed by table cell coordinate
  if (!agentSectionsConfig._tableFillConfig) {
    agentSectionsConfig._tableFillConfig = {};
  }
  const fillCfg = agentSectionsConfig._tableFillConfig;

  entries.forEach((entry) => {
    const key = `t${entry.table || 0}_r${entry.row}_c${entry.col}`;
    if (!(key in fillCfg)) {
      fillCfg[key] = { mode: 'auto', input: '' };
    }
    const cfg = fillCfg[key];
    const label = entry.label || `表${(entry.table || 0) + 1} [${entry.row},${entry.col}]`;
    const excerpt = (entry.text_excerpt || '').slice(0, 120);

    const row = document.createElement('div');
    row.className = 'section-row';
    row.dataset.tableKey = key;

    const modeOpts = FILL_MODE_OPTIONS.map(
      (o) => `<option value="${o.value}" ${cfg.mode === o.value ? 'selected' : ''}>${o.label}</option>`
    ).join('');

    row.innerHTML = `
      <div class="section-row-head">
        <span class="section-row-title">${escapeHtml(label)}</span>
        <span class="section-row-status">${escapeHtml(excerpt || '（无原文）')}</span>
        <select class="section-row-mode" data-table-key="${key}">${modeOpts}</select>
      </div>
      <textarea class="form-input section-row-input" data-table-key="${key}" rows="2"
        placeholder="可选：提供你的内容替代 AI 生成"></textarea>
    `;

    const modeSel = row.querySelector('.section-row-mode');
    const input = row.querySelector('.section-row-input');
    input.value = cfg.input || '';
    input.disabled = cfg.mode === 'skip';

    modeSel.addEventListener('change', () => {
      cfg.mode = modeSel.value;
      input.disabled = cfg.mode === 'skip';
      markAgentPlanStale();
    });
    input.addEventListener('input', () => {
      cfg.input = input.value;
      markAgentPlanStale();
    });

    list.appendChild(row);
  });
}

function maybeWarnLongTextForAutoMode(row, idx, text, mode) {
  let hint = row.querySelector('.section-mode-hint');
  if (mode !== 'auto' || !text || text.trim().length < 120) {
    if (hint) hint.remove();
    return;
  }
  if (!hint) {
    hint = document.createElement('div');
    hint.className = 'section-mode-hint form-hint';
    row.querySelector('.section-row-input')?.after(hint);
  }
  hint.innerHTML = '检测到较长正文，是否改为「用我的内容」？ '
    + '<button type="button" class="btn-ghost btn-sm">切换</button>';
  hint.querySelector('button')?.addEventListener('click', () => {
    const modeSel = row.querySelector('.section-row-mode');
    if (modeSel) modeSel.value = 'user_provided';
    agentSectionsConfig.sections[idx].mode = 'user_provided';
    hint.remove();
    markAgentPlanStale();
  });
}

function updateSectionAttachCount(row, idx, count) {
  const el = row.querySelector(`.section-attach-count[data-section-idx="${idx}"]`);
  if (el) el.textContent = count ? `已选 ${count} 张` : '';
}

async function loadSectionImages(idx, fileInput, row) {
  const files = fileInput?.files;
  if (!files?.length) return;
  const b64list = [];
  for (const file of files) {
    const b64 = await readFileAsBase64(file);
    if (b64) b64list.push(b64);
  }
  if (!agentSectionsConfig.sections[idx].attachments) {
    agentSectionsConfig.sections[idx].attachments = {};
  }
  agentSectionsConfig.sections[idx].attachments.images_b64 = b64list;
  updateSectionAttachCount(row, idx, b64list.length);
  markAgentPlanStale();
}

function readFileAsBase64(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result || '';
      const b64 = String(dataUrl).split(',')[1] || '';
      resolve(b64);
    };
    reader.onerror = () => resolve('');
    reader.readAsDataURL(file);
  });
}

async function parseGlobalRulesBrief() {
  const el = document.getElementById('sectionsGlobalRules');
  const text = (el?.value || '').trim();
  if (!text) {
    showToast('请先填写老师总体要求', 'error');
    return;
  }
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  try {
    const resp = await apiPost('/api/agent/parse-section-brief', {
      api_key: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      custom_url: settings.customUrl || '',
      section_id: 'global',
      input: text,
    });
    (resp.constraints || []).forEach((c, i) => {
      const rule = typeof c === 'string' ? c : (c.text || c.rule || '');
      const section = (typeof c === 'object' && c.section) ? c.section : 'summary';
      if (!rule) return;
      const sec = (agentSectionsConfig.sections || []).find((s) => s.id === section);
      if (!sec) return;
      if (!sec.constraints) sec.constraints = [];
      sec.constraints.push({
        id: `global_${i}`,
        text: rule,
        section,
        position: c.position || 'end',
      });
      if (!sec.input) sec.input = rule;
      else if (!sec.input.includes(rule)) sec.input = `${sec.input}\n${rule}`.trim();
    });
    if (parsedQuestions[0]) {
      renderSectionsWorkbench(parsedQuestions[0], parsedMetadata, agentFormatSpec);
    }
    markAgentPlanStale();
    showToast(resp.note || '总体要求已解析并写入各节，请确认', 'success');
  } catch (err) {
    showToast('解析总体要求失败: ' + err.message, 'error');
  }
}

function buildSectionsSummaryHtml() {
  const cfg = collectSectionsConfigForApi();
  const modeLabel = (m) => FILL_MODE_OPTIONS.find((o) => o.value === m)?.label || m;
  const dynamicDefs = getDynamicSectionRowDefs();
  const lines = (cfg.sections || []).map((s) => {
    const def = dynamicDefs.find((d) => d.id === s.id) || SECTION_ROW_DEFS.find((d) => d.id === s.id);
    const rules = (s.constraints || []).length;
    const extra = rules ? `，${rules} 条要求` : '';
    return `${def?.label || s.id}：${modeLabel(s.mode)}${extra}`;
  });
  return lines.length
    ? `<div class="form-hint" style="margin:0">分节摘要（只读）：${escapeHtml(lines.join(' · '))}</div>`
    : '';
}

function renderSectionConstraints(row, idx, constraints) {
  const wrap = row.querySelector(`[data-constraints-idx="${idx}"]`);
  if (!wrap) return;
  if (!constraints.length) {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    return;
  }
  wrap.style.display = 'flex';
  wrap.innerHTML = '<span class="form-hint" style="margin:0">解析出的要求（可编辑）：</span>';
  constraints.forEach((c, ci) => {
    const item = document.createElement('div');
    item.className = 'section-constraint-item';
    item.innerHTML = `
      <input type="text" data-c-idx="${ci}" value="${escapeHtml(c.text || '')}">
      <button type="button" class="btn-ghost btn-sm" data-c-del="${ci}">删</button>
    `;
    item.querySelector('input').addEventListener('input', (e) => {
      agentSectionsConfig.sections[idx].constraints[ci].text = e.target.value;
      markAgentPlanStale();
    });
    item.querySelector('[data-c-del]').addEventListener('click', () => {
      agentSectionsConfig.sections[idx].constraints.splice(ci, 1);
      renderSectionConstraints(row, idx, agentSectionsConfig.sections[idx].constraints);
      markAgentPlanStale();
    });
    wrap.appendChild(item);
  });
}

function syncAgentSectionsConfigFromUI() {
  syncSectionsGlobalFromSolveBar();
  document.querySelectorAll('.section-row').forEach((row) => {
    const sid = row.dataset.sectionId;
    const sec = (agentSectionsConfig.sections || []).find((s) => s.id === sid);
    if (!sec) return;
    const modeSel = row.querySelector('.section-row-mode');
    const input = row.querySelector('.section-row-input');
    if (modeSel) sec.mode = modeSel.value;
    if (input) sec.input = input.value;
  });
}

function collectSectionsConfigForApi() {
  syncAgentSectionsConfigFromUI();
  const cfg = {
    global: { ...(agentSectionsConfig.global || {}) },
    sections: (agentSectionsConfig.sections || []).map((s) => ({
      id: s.id,
      mode: s.mode || 'auto',
      input: s.input || '',
      attachments: s.attachments || {},
      constraints: s.constraints || [],
      _semantic: s._semantic,
    })),
  };
  const gr = document.getElementById('sectionsGlobalRules')?.value?.trim();
  if (gr) {
    const summarySec = cfg.sections.find((s) => s._semantic === 'summary')
      || cfg.sections[cfg.sections.length - 1];
    if (summarySec && !summarySec.input) summarySec.input = gr;
    else if (summarySec) summarySec.input = `${gr}\n\n${summarySec.input}`.trim();
  }
  if (agentSectionsConfig._tableFillConfig) {
    cfg._table_fill = agentSectionsConfig._tableFillConfig;
  }
  return cfg;
}

async function parseSectionBriefForRow(idx) {
  const sec = agentSectionsConfig.sections[idx];
  if (!sec) return;
  const row = document.querySelector(`.section-row[data-section-id="${sec.id}"]`);
  const input = row?.querySelector('.section-row-input');
  const text = (input?.value || '').trim();
  if (!text) {
    showToast('请先在本节输入框填写内容', 'error');
    return;
  }
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  const btn = row?.querySelector('.section-parse-btn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '解析中…';
  }
  try {
    const resp = await apiPost('/api/agent/parse-section-brief', {
      api_key: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      custom_url: settings.customUrl || '',
      section_id: sec.id,
      input: text,
    });
    if (resp.suggested_mode) {
      sec.mode = resp.suggested_mode;
      const modeSel = row?.querySelector('.section-row-mode');
      if (modeSel) modeSel.value = sec.mode;
      if (input) input.disabled = sec.mode === 'skip';
    }
    if (resp.user_content) {
      const uc = typeof resp.user_content === 'string' ? resp.user_content : JSON.stringify(resp.user_content);
      if (input) input.value = uc;
      sec.input = uc;
      if (!resp.suggested_mode) sec.mode = 'user_provided';
    }
    const constraints = (resp.constraints || []).map((c, i) => {
      if (typeof c === 'string') return { id: `${sec.id}_${i}`, text: c, section: sec.id };
      return {
        id: c.id || `${sec.id}_${i}`,
        text: c.text || c.rule || '',
        section: c.section || sec.id,
        position: c.position || 'end',
      };
    }).filter((c) => c.text);
    sec.constraints = constraints;
    if (row) renderSectionConstraints(row, idx, constraints);
    if (resp.note) showToast(resp.note, 'info');
    syncAgentSectionsConfigFromUI();
    markAgentPlanStale();
    showToast('本段已智能解析，请确认后生成计划', 'success');
  } catch (err) {
    showToast('智能解析失败: ' + err.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '智能解析本段';
    }
  }
}

function hideLoading() {
  const overlay = document.getElementById('loadingOverlay');
  overlay.classList.add('hidden');
}

function setServerStatus(online) {
  const dot = document.getElementById('serverStatus');
  const text = document.getElementById('serverStatusText');
  if (online) {
    dot.className = 'status-dot online';
    text.textContent = '已连接';
  } else {
    dot.className = 'status-dot error';
    text.textContent = '离线';
  }
}

function initMonaco() {
  require.config({
    paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.46.0/min/vs' }
  });
  require(['vs/editor/editor.main'], function() {
    monacoEditor = monaco.editor.create(document.getElementById('monacoEditor'), {
      value: '# 在这里编写或查看代码\n',
      language: 'python',
      theme: 'vs-dark',
      fontSize: 13,
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      lineNumbers: 'on',
      wordWrap: 'on',
      automaticLayout: true,
    });
  });
}

// ============================
// 导航/标签切换
// ============================

function switchTab(tab) {
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(el => el.classList.remove('active'));

  document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');
}

// ============================
// 步骤控制
// ============================

function goToStep(n) {
  document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
  document.getElementById(`step-${n}`).classList.add('active');
  updateStepBar(n);
  if (n === 2 && parsedQuestions.length > 0) {
    showModeSwitchBar();
  }
}

function updateStepBar(currentStep) {
  document.querySelectorAll('.step').forEach((el, i) => {
    const stepNum = i + 1;
    el.classList.remove('active', 'done');
    if (stepNum < currentStep) el.classList.add('done');
    else if (stepNum === currentStep) el.classList.add('active');
  });
}

// ============================
// 文件上传 & 多文档
// ============================

function newDocLocalId() {
  return `doc-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function guessDefaultDocRole(fileName) {
  const lower = (fileName || '').toLowerCase();
  // PDF files default to fill_target (can't edit directly)
  if (lower.endsWith('.pdf')) return 'fill_target';
  // Files with "template" or "范文" or "答案" in the name are likely templates
  if (/范文|答案|模版|template|sample|example|参考/.test(fileName)) return 'answer_template';
  // Files with "题目" or "要求" or "assignment" are likely assignments
  if (/题目|要求|assignment|question|习题/.test(fileName)) return 'assignment';
  // Files with "参考" or "资料" or "reference" are likely references
  if (/资料|reference|ref-/.test(fileName)) return 'reference';
  return 'auto';
}

function renderDocumentList() {
  const list = document.getElementById('documentList');
  const empty = document.getElementById('documentListEmpty');
  const parseBtn = document.getElementById('parseDocumentsBtn');
  const uploadHint = document.getElementById('uploadAreaHint');
  if (!list) return;

  list.querySelectorAll('.document-list-item').forEach((el) => el.remove());
  if (empty) empty.style.display = uploadedDocuments.length ? 'none' : 'block';
  if (parseBtn) parseBtn.disabled = uploadedDocuments.length === 0;

  // Update upload area hint text
  if (uploadHint) {
    uploadHint.textContent = uploadedDocuments.length
      ? '拖拽或点击添加更多文档（已添加 ' + uploadedDocuments.length + ' 个）'
      : '支持 .doc / .docx / .pdf，或直接粘贴超星等平台上的题目文字';
  }

  const hasParsed = uploadedDocuments.some((d) => d.resolvedRole);

  uploadedDocuments.forEach((doc) => {
    const row = document.createElement('div');
    row.className = 'document-list-item';
    row.dataset.localId = doc.localId;

    const formatIcon = DOC_FORMAT_ICONS[doc.docFormat] || '📄';
    const guessedRole = doc.role || 'auto';
    const resolvedRole = doc.resolvedRole;
    const roleForSelect = resolvedRole || guessedRole;
    const isParsed = !!resolvedRole;

    // Role select options
    const roleOpts = DOC_ROLE_OPTIONS.map(
      (o) => `<option value="${o.value}" ${roleForSelect === o.value ? 'selected' : ''}>${o.label}</option>`
    ).join('');

    // Resolved role badge
    let resolvedBadge = '';
    if (isParsed) {
      const roleColor = DOC_ROLE_COLORS[resolvedRole] || 'var(--text-muted)';
      const roleLabel = DOC_ROLE_LABELS[resolvedRole] || resolvedRole;
      resolvedBadge = `<span class="doc-role-badge" style="background:${roleColor}20;color:${roleColor};border-color:${roleColor}40">${roleLabel}</span>`;
    }

    // Template format analysis indicator
    let templateFormatBadge = '';
    if (isParsed && resolvedRole === 'answer_template' && (agentFormatSpec || agentTemplatePending?.formatSpec)) {
      const spec = agentFormatSpec || agentTemplatePending?.formatSpec || {};
      const summary = spec.summary || '';
      templateFormatBadge = `<span class="doc-template-badge" title="格式已分析：${escapeHtml(summary)}">📐 格式已分析</span>`;
    }

    // Word count info
    let statsHtml = '';
    if (doc.isInline && doc.inlineText) {
      statsHtml = `<span class="doc-stats">${doc.inlineText.length.toLocaleString()} 字</span>`;
    } else if (isParsed && doc.fillBodyLen > 0) {
      statsHtml = `<span class="doc-stats">${doc.fillBodyLen.toLocaleString()} 字</span>`;
    }

    // Parse status indicator
    let parseStatus = '';
    if (isParsed) {
      parseStatus = '<span class="doc-parse-status parsed" title="已解析">✓</span>';
    }

    row.innerHTML = `
      <span class="doc-format-icon">${formatIcon}</span>
      <span class="doc-name" title="${escapeHtml(doc.path || doc.fileName)}">${escapeHtml(doc.fileName)}</span>
      ${parseStatus}
      ${statsHtml}
      ${resolvedBadge}
      ${templateFormatBadge}
      <select class="doc-role-select" data-local-id="${doc.localId}">${roleOpts}</select>
      <button type="button" class="btn-ghost btn-sm" data-remove-id="${doc.localId}" title="移除">✕</button>
    `;

    row.querySelector('.doc-role-select').addEventListener('change', (e) => {
      const id = e.target.getAttribute('data-local-id');
      const item = uploadedDocuments.find((d) => d.localId === id);
      if (item) {
        item.role = e.target.value;
        markAgentPlanStale();
      }
    });
    row.querySelector('[data-remove-id]').addEventListener('click', () => removeUploadedDocument(doc.localId));
    list.appendChild(row);
  });

  // Show document summary bar after parsing
  renderDocumentSummaryBar();
}

function deriveInlineDocName(text) {
  const firstLine = (text || '').trim().split('\n').find((l) => l.trim()) || '';
  const snippet = firstLine.replace(/\s+/g, ' ').trim().slice(0, 40);
  if (!snippet) return '粘贴的文字';
  return `粘贴：${snippet}${firstLine.length > 40 ? '…' : ''}`;
}

function addInlineTextDocument(text, role = 'assignment') {
  const trimmed = (text || '').trim();
  if (!trimmed) {
    showToast('粘贴内容不能为空', 'error');
    return false;
  }
  if (uploadedDocuments.some((d) => d.isInline && d.inlineText === trimmed)) {
    showToast('相同内容已在清单中', 'info');
    return false;
  }
  uploadedDocuments.push({
    localId: newDocLocalId(),
    path: null,
    fileName: deriveInlineDocName(trimmed),
    role: role || 'assignment',
    docFormat: 'text',
    isInline: true,
    inlineText: trimmed,
    resolvedRole: null,
    resolvedLayout: null,
    fillBodyLen: 0,
    assignmentExcerptLen: 0,
    splitAtHeading: '',
  });
  renderDocumentList();
  markAgentPlanStale();
  return true;
}

function openPasteAssignmentModal() {
  const modal = document.getElementById('pasteAssignmentModal');
  const textarea = document.getElementById('pasteAssignmentText');
  const roleSelect = document.getElementById('pasteAssignmentRole');
  const metaEl = document.getElementById('pasteAssignmentMeta');
  const confirmBtn = document.getElementById('pasteAssignmentConfirm');
  const cancelBtn = document.getElementById('pasteAssignmentCancel');
  if (!modal || !textarea) return;

  textarea.value = '';
  if (roleSelect) roleSelect.value = 'assignment';
  if (metaEl) metaEl.textContent = '';
  modal.style.display = 'flex';
  textarea.focus();

  function updateMeta() {
    if (!metaEl) return;
    const len = textarea.value.trim().length;
    metaEl.textContent = len ? `约 ${len.toLocaleString()} 字` : '';
  }

  textarea.oninput = updateMeta;

  function cleanup() {
    modal.style.display = 'none';
    textarea.oninput = null;
    confirmBtn.onclick = null;
    cancelBtn.onclick = null;
  }

  confirmBtn.onclick = () => {
    const role = roleSelect?.value || 'assignment';
    if (addInlineTextDocument(textarea.value, role)) {
      showToast('已添加粘贴内容到文档清单', 'success');
      cleanup();
    }
  };
  cancelBtn.onclick = cleanup;
}

function addUploadedDocument(filePath) {
  const fileName = filePath.split(/[\\/]/).pop();
  const lower = fileName.toLowerCase();
  if (uploadedDocuments.some((d) => d.path === filePath)) {
    showToast('该文件已在清单中', 'info');
    return false;
  }
  let format = 'docx';
  if (lower.endsWith('.pdf')) format = 'pdf';
  // Legacy .doc files are auto-converted to .docx on the backend;
  // use 'docx' as the working format for all downstream operations.
  // The original extension is preserved in fileName for display.
  uploadedDocuments.push({
    localId: newDocLocalId(),
    path: filePath,
    fileName,
    role: guessDefaultDocRole(fileName),
    docFormat: format,
    resolvedRole: null,
    resolvedLayout: null,
    fillBodyLen: 0,
    assignmentExcerptLen: 0,
    splitAtHeading: '',
  });
  currentFile = filePath;
  renderDocumentList();
  markAgentPlanStale();
  return true;
}

function renderDocumentSummaryBar() {
  const existing = document.getElementById('docSummaryBar');
  if (existing) existing.remove();

  const hasParsed = uploadedDocuments.some((d) => d.resolvedRole);
  if (!hasParsed) return;

  const panel = document.getElementById('documentListPanel');
  if (!panel) return;

  const bar = document.createElement('div');
  bar.id = 'docSummaryBar';
  bar.className = 'doc-summary-bar';

  const roleCounts = {};
  uploadedDocuments.forEach((d) => {
    const role = d.resolvedRole || d.role || 'auto';
    roleCounts[role] = (roleCounts[role] || 0) + 1;
  });

  const parts = Object.entries(roleCounts).map(([role, count]) => {
    const label = DOC_ROLE_LABELS[role] || role;
    const color = DOC_ROLE_COLORS[role] || 'var(--text-muted)';
    return `<span class="doc-summary-chip" style="background:${color}20;color:${color}">${label} ×${count}</span>`;
  });

  bar.innerHTML = `
    <span class="doc-summary-label">已解析 ${uploadedDocuments.length} 个文档：</span>
    ${parts.join(' ')}
    <span class="doc-summary-hint">角色可手动调整后重新解析</span>
  `;

  const actions = panel.querySelector('.document-list-actions');
  if (actions) {
    actions.before(bar);
  } else {
    panel.appendChild(bar);
  }
}

function removeUploadedDocument(localId) {
  uploadedDocuments = uploadedDocuments.filter((d) => d.localId !== localId);
  if (uploadedDocuments.length === 0) {
    currentFile = null;
    agentDocumentIds = [];
    hideSplitPreview();
    const bar = document.getElementById('docSummaryBar');
    if (bar) bar.remove();
  } else if (!uploadedDocuments.some((d) => d.path === currentFile)) {
    const nextWithPath = uploadedDocuments.find((d) => d.path);
    currentFile = nextWithPath ? nextWithPath.path : null;
  }
  renderDocumentList();
  markAgentPlanStale();
}

async function triggerAddDocuments() {
  const result = await window.electronAPI.openFileDialog();
  if (result.canceled || !result.filePaths?.length) return;
  let added = 0;
  for (const fp of result.filePaths) {
    if (addUploadedDocument(fp)) added += 1;
  }
  if (added) showToast(`已添加 ${added} 个文档`, 'success');
}

async function triggerFileUpload() {
  await triggerAddDocuments();
}

function findSplitCandidates(fullText) {
  const lines = (fullText || '').split('\n').map((l) => l.trim()).filter(Boolean);
  const hits = [];
  lines.forEach((line, idx) => {
    if (SPLIT_HEADING_PATTERNS.some((p) => p.test(line))) {
      hits.push({ idx, heading: line });
    }
  });
  return hits;
}

function hideSplitPreview() {
  agentAwaitingSplitConfirm = false;
  const panel = document.getElementById('splitPreviewPanel');
  const confirmBtn = document.getElementById('splitConfirmBtn');
  if (panel) panel.style.display = 'none';
  if (confirmBtn) confirmBtn.style.display = 'none';
}

function renderSplitPreview(resp) {
  const panel = document.getElementById('splitPreviewPanel');
  const assignEl = document.getElementById('splitPreviewAssignment');
  const fillEl = document.getElementById('splitPreviewFill');
  const select = document.getElementById('splitHeadingSelect');
  const confirmBtn = document.getElementById('splitConfirmBtn');
  if (!panel || !assignEl || !fillEl || !select) return;

  const layout = resp.layout || agentDocLayout;
  if (layout !== 'combined') {
    hideSplitPreview();
    return;
  }

  panel.style.display = 'block';
  const assignmentText = resp.assignment_text || '';
  const fillText = resp.fill_target?.full_text || resp.report_text || '';
  assignEl.textContent = assignmentText.slice(0, 800) || '（空）';
  fillEl.textContent = fillText.slice(0, 800) || '（空）';

  const fullText = agentPrimaryFullText || resp.question?.full_text || '';
  agentSplitCandidates = findSplitCandidates(fullText);
  if (resp.split_at_heading && !agentSplitCandidates.some((c) => c.heading === resp.split_at_heading)) {
    agentSplitCandidates.unshift({
      idx: resp.split_idx ?? 0,
      heading: resp.split_at_heading,
    });
  }
  if (!agentSplitCandidates.length && resp.split_at_heading) {
    agentSplitCandidates = [{ idx: resp.split_idx ?? 0, heading: resp.split_at_heading }];
  }

  select.innerHTML = '';
  agentSplitCandidates.forEach((c) => {
    const opt = document.createElement('option');
    opt.value = c.heading;
    opt.textContent = `[${c.idx}] ${c.heading}`;
    if (c.heading === (agentSplitAtHeading || resp.split_at_heading)) opt.selected = true;
    select.appendChild(opt);
  });
  agentSplitAtHeading = select.value || resp.split_at_heading || '';
  agentSplitIdx = resp.split_idx ?? null;
  agentDocLayout = layout;

  if (confirmBtn) confirmBtn.style.display = agentAwaitingSplitConfirm ? 'inline-flex' : 'none';
}

function onSplitHeadingChange() {
  const select = document.getElementById('splitHeadingSelect');
  agentSplitAtHeading = select?.value || '';
}

async function reparseWithSplitHeading() {
  onSplitHeadingChange();
  agentSplitDirty = true;
  await parseAllDocuments({ stayOnStep: 1, quiet: true });
  agentSplitDirty = false;
  showToast('已按所选标题重新拆分', 'success');
  markAgentPlanStale();
}

function confirmSplitAndContinue() {
  agentAwaitingSplitConfirm = false;
  const confirmBtn = document.getElementById('splitConfirmBtn');
  if (confirmBtn) confirmBtn.style.display = 'none';
  goToStep(2);
  updateStepBar(2);
}

async function buildDocumentsPayload() {
  if (!uploadedDocuments.length) {
    throw new Error('请先添加至少一份文档');
  }
  const documents = [];
  for (const doc of uploadedDocuments) {
    const item = {
      id: doc.localId,
      role: doc.role || 'auto',
      file_name: doc.fileName,
    };
    if (doc.isInline) {
      item.text_content = doc.inlineText;
    } else {
      const lower = doc.fileName.toLowerCase();
      if (lower.endsWith('.pdf') && !(await confirmPdfUploadIfNeeded(doc.fileName))) {
        throw new Error('已取消 PDF 上传');
      }
      item.file_data = await window.electronAPI.readFileBase64(doc.path);
    }
    if (doc.role === 'fill_target' && agentSplitAtHeading) {
      item.split_at_heading = agentSplitAtHeading;
    }
    documents.push(item);
  }

  if (pairedDocxPath) {
    const hasTemplate = documents.some((d) => d.role === 'fill_template');
    if (!hasTemplate) {
      const docxData = await window.electronAPI.readFileBase64(pairedDocxPath);
      const docxName = pairedDocxPath.split(/[\\/]/).pop();
      documents.push({
        id: 'd-pair-tpl',
        role: 'fill_template',
        file_data: docxData,
        file_name: docxName,
      });
    }
  }
  return { documents };
}

function applyParseResponse(resp, fileName) {
  parsedQuestions = resp.questions || (resp.question ? [resp.question] : []);
  renderQuestions(parsedQuestions);

  (resp.warnings || []).forEach((w) => {
    if (w && w.message) showToast(w.message, 'warning');
  });

  const meta = resp.metadata || resp.meta || {};
  parsedMetadata = meta;
  agentFillTarget = resp.fill_target || null;
  // V5: default deliverable (user copies content); advanced fill in details
  agentOutputMode = 'deliverable';
  updateOutputModeUI();
  agentDocumentIds = resp.document_ids || [];
  agentSplitIdx = resp.split_idx ?? null;
  agentDocLayout = resp.layout || null;
  agentSplitAtHeading = resp.split_at_heading || agentSplitAtHeading || '';
  agentPrimaryFullText = parsedQuestions[0]?.full_text || resp.question?.full_text || '';
  agentAssignmentText = resp.assignment_text || agentAssignmentText || '';
  agentSplitDirty = false;

  // Sync backend-resolved document roles into uploadedDocuments
  const backendDocs = resp.documents || [];
  if (backendDocs.length && uploadedDocuments.length) {
    const backendById = {};
    backendDocs.forEach((d) => { backendById[d.id] = d; });
    uploadedDocuments.forEach((doc) => {
      const bd = backendById[doc.localId];
      if (bd) {
        doc.resolvedRole = bd.role || doc.role;
        doc.resolvedLayout = bd.layout || '';
        doc.docFormat = bd.format || '';
        doc.fillBodyLen = bd.fill_body_len || 0;
        doc.assignmentExcerptLen = bd.assignment_excerpt_len || 0;
        doc.splitAtHeading = bd.split_at_heading || '';
      }
    });
    renderDocumentList();
  }

  // DA4: store section detection data
  agentSectionsDetected = resp.sections_detected || [];
  agentSectionMap = resp.section_map || {};
  agentFillHints = resp.fill_hints || {};
  agentReportLayout = resp.report_layout || '';
  agentTableMap = resp.table_map || [];
  agentUserSemanticOverrides = {};

  if (resp.format_spec && !agentTemplateConfirmed) {
    agentFormatSpec = resp.format_spec;
    agentAnswerTemplateText = resp.format_spec?.template_full_text
      || resp.format_spec?.full_text
      || agentAnswerTemplateText
      || '';

    // Surface template analysis from multi-doc parse (not manual upload)
    const templateDoc = (resp.documents || []).find((d) => d.role === 'answer_template');
    agentTemplatePending = agentTemplatePending || {
      path: templateDoc?.file_name || '',
      fileName: templateDoc?.file_name || '范文/模版',
      formatSpec: resp.format_spec,
      summary: resp.format_spec?.summary || resp.format_spec_summary || '从文档清单中的范文自动提取',
      source: 'parse',
    };
    renderTemplateSummary(agentTemplatePending);
  }

  if (parsedQuestions[0]?.type === 'lab_report') {
    renderSectionsWorkbench(parsedQuestions[0], meta, agentFormatSpec);
  }

  const showDetect = meta.course || meta.experiment_title || meta.major
    || meta.source_format === 'pdf' || (fileName || '').toLowerCase().endsWith('.pdf')
    || agentReportLayout || agentSectionsDetected.length;
  if (showDetect) {
    document.getElementById('detectInfoCard').style.display = 'flex';
    document.getElementById('detectCourse').textContent = meta.course || '—';
    document.getElementById('detectTitle').textContent = meta.experiment_title || '—';
    document.getElementById('detectMajor').textContent = meta.major || '—';
    renderLayoutBadge();
    renderSectionsDetectCard();
    renderTableMapPreview();
  } else {
    document.getElementById('detectInfoCard').style.display = 'none';
    hideSectionsDetectCard();
    hideTableMapPreview();
  }
  updatePdfExportHint(meta, fileName || uploadedDocuments[0]?.fileName || '');

  if (resp.needs_uml) {
    const umlChk = document.getElementById('includeUmlCheck');
    if (umlChk) umlChk.checked = true;
    showToast('报告可能要求 UML 图，已勾选「生成 UML 图」', 'info');
  }

  renderSplitPreview(resp);

  // Check runtime availability (fire-and-forget, non-blocking)
  checkAndPromptRuntimes().catch(() => {});
}

// ── DA4: section detection UI ──

function renderLayoutBadge() {
  const card = document.getElementById('detectInfoCard');
  if (!card) return;
  let badge = card.querySelector('.layout-badge');
  const label = getLayoutBadgeLabel();
  if (!label) {
    if (badge) badge.remove();
    return;
  }
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'layout-badge';
    card.appendChild(badge);
  }
  badge.textContent = label;
  badge.title = agentReportLayout === 'training_table'
    ? '实训表格模版 — 任务与作答均在表格内'
    : agentReportLayout === 'variant_sections'
      ? '节号/节数与标准三/四/五不同 — 已按关键词语义映射'
      : '标准三/四/五节结构';
}

function renderSectionsDetectCard() {
  let card = document.getElementById('sectionsDetectCard');
  const infoCard = document.getElementById('detectInfoCard');
  if (!infoCard) return;

  const items = agentSectionsDetected || [];
  if (!items.length) {
    if (card) card.style.display = 'none';
    return;
  }

  if (!card) {
    card = document.createElement('div');
    card.id = 'sectionsDetectCard';
    card.className = 'sections-detect-card';
    infoCard.after(card);
  }
  card.style.display = 'block';

  const overrides = agentUserSemanticOverrides || {};
  let html = '<div class="sections-detect-header">检测到的章节标题</div>';
  items.forEach((sec) => {
    const effectiveRole = Object.entries(overrides).find(
      ([, h]) => h === sec.heading
    )?.[0] || sec.semantic || '';
    const roleLabel = effectiveRole
      ? `<span class="detect-semantic-tag ${effectiveRole}">→ ${SEMANTIC_LABEL_MAP[effectiveRole] || effectiveRole}</span>`
      : '<span class="detect-semantic-tag none">未映射</span>';

    const opts = [
      '<option value="">自动检测</option>',
      '<option value="objective">实验目的</option>',
      '<option value="principles">实验原理</option>',
      '<option value="steps">实验步骤</option>',
      '<option value="result">实验结果</option>',
      '<option value="summary">实验总结</option>',
      '<option value="discussion">讨论/思考题</option>',
      '<option value="appendix">附录</option>',
      '<option value="other">未知类型</option>',
      '<option value="__none__">忽略此标题</option>',
    ].join('');

    const selVal = effectiveRole || '';
    const selAttr = selVal ? ` data-override-role="${selVal}"` : '';

    html += `<div class="section-detect-row">
      <span class="detect-heading-text">${escapeHtml(sec.heading)}</span>
      ${roleLabel}
      <select class="semantic-override-select" data-heading="${escapeHtml(sec.heading)}"${selAttr}
        onchange="onSemanticOverride(this)">
        ${opts}
      </select>
    </div>`;
  });

  // Fill hints (only when 1-3 sections detected — with many sections each is its own unit)
  if (items.length <= 3) {
    const hints = agentFillHints || {};
    const hintMsgs = [];
    if (hints.screenshots_target) {
      hintMsgs.push(`截图将放入「${SEMANTIC_LABEL_MAP[hints.screenshots_target] || hints.screenshots_target}」节`);
    }
    if (hints.merge_steps_into) {
      hintMsgs.push(`步骤内容将合并到「${SEMANTIC_LABEL_MAP[hints.merge_steps_into] || hints.merge_steps_into}」`);
    }
    if (hints.merge_result_into) {
      hintMsgs.push(`结果内容将合并到「${SEMANTIC_LABEL_MAP[hints.merge_result_into] || hints.merge_result_into}」`);
    }
    if (hintMsgs.length) {
      html += `<div class="sections-detect-hints">${hintMsgs.map((m) => `<span class="detect-hint-item">${escapeHtml(m)}</span>`).join('')}</div>`;
    }
  }

  card.innerHTML = html;

  // Restore override selections
  card.querySelectorAll('.semantic-override-select').forEach((sel) => {
    const heading = sel.getAttribute('data-heading');
    const overrideRole = sel.getAttribute('data-override-role');
    if (overrideRole) {
      sel.value = overrideRole;
    }
  });
}

function hideSectionsDetectCard() {
  const card = document.getElementById('sectionsDetectCard');
  if (card) card.style.display = 'none';
}

function onSemanticOverride(selectEl) {
  const heading = selectEl.getAttribute('data-heading');
  const value = selectEl.value;
  if (!heading) return;

  // Clear any previous override for this heading
  Object.keys(agentUserSemanticOverrides).forEach((role) => {
    if (agentUserSemanticOverrides[role] === heading) {
      delete agentUserSemanticOverrides[role];
    }
  });

  if (value) {
    agentUserSemanticOverrides[value] = heading;
  }

  // Sync section mode in agentSectionsConfig when semantic role changes
  const sections = agentSectionsConfig.sections || [];
  const detected = agentSectionsDetected || [];
  const idx = detected.findIndex((s) => s.heading === heading);
  if (idx >= 0 && sections[idx]) {
    const effectiveRole = value || detected[idx].semantic;
    const isCore = effectiveRole === 'steps' || effectiveRole === 'result' || effectiveRole === 'summary';
    if (isCore && sections[idx].mode === 'skip') {
      sections[idx].mode = 'auto';
    } else if (!isCore && sections[idx].mode === 'auto') {
      sections[idx].mode = 'skip';
    }
  }

  // Refresh the section workbench with new labels
  if (parsedQuestions[0]?.type === 'lab_report') {
    renderSectionsWorkbench(parsedQuestions[0], parsedMetadata, agentFormatSpec);
  }
  renderSectionsDetectCard();
  markAgentPlanStale();
}

function renderTableMapPreview() {
  let panel = document.getElementById('tableMapPreview');
  const infoCard = document.getElementById('detectInfoCard');
  if (!infoCard) return;

  const entries = agentTableMap || [];
  if (!entries.length) {
    if (panel) panel.style.display = 'none';
    return;
  }

  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'tableMapPreview';
    panel.className = 'table-map-preview';
    const detectCard = document.getElementById('sectionsDetectCard');
    if (detectCard) {
      detectCard.after(panel);
    } else {
      infoCard.after(panel);
    }
  }
  panel.style.display = 'block';

  const rows = entries.map((e) =>
    `<div class="table-map-entry">
      <span class="table-map-coord">表${(e.table || 0) + 1} [${e.row},${e.col}]</span>
      <span class="table-map-label">${escapeHtml(e.label || '')}</span>
      <span class="table-map-excerpt">${escapeHtml((e.text_excerpt || '').slice(0, 80))}</span>
    </div>`
  ).join('');

  panel.innerHTML = `
    <div class="table-map-header">实训表格结构</div>
    ${rows}
    <div class="table-map-hint">AI 将按表头定位单元格填入内容</div>
  `;
}

function hideTableMapPreview() {
  const panel = document.getElementById('tableMapPreview');
  if (panel) panel.style.display = 'none';
}

// ── Runtime detection & install guide ──

async function checkAndPromptRuntimes() {
  try {
    const resp = await apiGet('/api/runtime-status');
    if (resp.any_available) {
      renderRuntimeStatusBar(resp.runtimes);
      return true;
    }
    renderRuntimeStatusBar(resp.runtimes);
    const result = await showRuntimeMissingModal(resp.runtimes);
    if (result === 'retry') {
      return checkAndPromptRuntimes();
    }
    return result === 'skip';
  } catch (err) {
    console.warn('runtime check failed:', err);
    return true; // don't block on probe errors
  }
}

function showRuntimeMissingModal(runtimes) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('complianceModal');
    const titleEl = document.getElementById('complianceModalTitle');
    const bodyEl = document.getElementById('complianceModalBody');
    const primaryBtn = document.getElementById('complianceModalPrimary');
    const secondaryBtn = document.getElementById('complianceModalSecondary');
    const checkWrap = document.getElementById('complianceModalCheckWrap');

    if (!overlay || !titleEl || !bodyEl) { resolve('skip'); return; }

    titleEl.textContent = '⚠️ 未检测到编程环境';
    const entries = ['python', 'java', 'c', 'node'].map((k) => {
      const rt = runtimes[k] || {};
      const statusIcon = rt.available ? '✅' : '❌';
      const statusText = rt.available
        ? (rt.version || rt.version_info || '已安装')
        : '未安装';
      const btnHtml = !rt.available
        ? `<button class="btn-secondary btn-sm runtime-dl-btn" data-runtime="${k}">⬇️ 下载 ${rt.label || k}</button>`
        : '';
      const autoBtn = (!rt.available && rt.can_auto_download)
        ? `<button class="btn-primary btn-sm runtime-auto-btn" data-runtime="${k}">⚡ 一键安装 JRE（约 50MB）</button>`
        : '';
      return `<div class="runtime-modal-row">
        <span class="runtime-modal-name">${statusIcon} ${rt.label || k} — ${statusText}</span>
        ${btnHtml}${autoBtn}
        ${!rt.available ? `<span class="runtime-modal-guide">${escapeHtml(rt.install_guide || '')}</span>` : ''}
      </div>`;
    }).join('');

    bodyEl.innerHTML = `
      <div class="runtime-modal-body">
        <p style="margin-bottom:12px;color:var(--text-secondary)">
          解题能手需要以下任一运行时来执行代码。请至少安装一种，或选择伪代码模式继续。
        </p>
        <div class="runtime-modal-entries">${entries}</div>
        <div class="runtime-modal-footer-hint">
          安装完成后点「重新检测」刷新状态，或点「跳过安装」使用伪代码模式（代码仅生成不执行）。
        </div>
      </div>`;

    if (checkWrap) checkWrap.style.display = 'none';
    if (primaryBtn) {
      primaryBtn.textContent = '重新检测';
      primaryBtn.style.display = '';
    }
    if (secondaryBtn) {
      secondaryBtn.textContent = '跳过安装，使用伪代码';
      secondaryBtn.style.display = '';
    }

    overlay.classList.add('visible');

    function cleanup() {
      overlay.classList.remove('visible');
      overlay.removeEventListener('click', onOverlayClick);
      if (primaryBtn) primaryBtn.onclick = null;
      if (secondaryBtn) secondaryBtn.onclick = null;
      // Remove dynamic download button listeners
      bodyEl.querySelectorAll('.runtime-dl-btn, .runtime-auto-btn').forEach((b) => {
        b.onclick = null;
      });
    }

    function onOverlayClick(e) {
      if (e.target === overlay) { cleanup(); resolve('skip'); }
    }
    overlay.addEventListener('click', onOverlayClick);

    if (primaryBtn) {
      primaryBtn.onclick = () => { cleanup(); resolve('retry'); };
    }
    if (secondaryBtn) {
      secondaryBtn.onclick = () => { cleanup(); resolve('skip'); };
    }

    // Wire download buttons
    bodyEl.querySelectorAll('.runtime-dl-btn').forEach((btn) => {
      btn.onclick = (e) => {
        e.stopPropagation();
        const k = btn.getAttribute('data-runtime');
        const rt = runtimes[k] || {};
        if (rt.download_url && window.electronAPI && window.electronAPI.openExternalUrl) {
          window.electronAPI.openExternalUrl(rt.download_url);
          showToast(`正在打开 ${rt.label} 下载页面（国内镜像）`, 'info');
        }
      };
    });

    // Wire auto-download buttons (JRE)
    bodyEl.querySelectorAll('.runtime-auto-btn').forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        btn.disabled = true;
        btn.textContent = '下载中…';
        try {
          await apiPost('/api/download-jre', {});
          showToast('JRE 安装完成！请点「重新检测」刷新状态', 'success');
          btn.textContent = '✅ 已安装';
        } catch (err) {
          showToast('JRE 下载失败: ' + err.message, 'error');
          btn.disabled = false;
          btn.textContent = '⚡ 一键安装 JRE（约 50MB）';
        }
      };
    });

    // Stop propagation on modal content clicks
    const modalContent = overlay.querySelector('.compliance-modal');
    if (modalContent) {
      modalContent.addEventListener('click', (e) => e.stopPropagation());
    }
  });
}

function renderRuntimeStatusBar(runtimes) {
  let bar = document.getElementById('runtimeStatusBar');
  const infoCard = document.getElementById('detectInfoCard');
  if (!infoCard) return;

  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'runtimeStatusBar';
    bar.className = 'runtime-status-bar';
    const detectCard = document.getElementById('sectionsDetectCard');
    if (detectCard) {
      detectCard.after(bar);
    } else {
      infoCard.after(bar);
    }
  }

  const badges = ['python', 'java', 'c', 'node'].map((k) => {
    const rt = runtimes[k] || {};
    const cls = rt.available ? 'available' : 'missing';
    const label = rt.available
      ? `${rt.label || k} ${rt.version || rt.version_info || ''}`.trim()
      : `${rt.label || k} 未安装`;
    return `<span class="runtime-badge ${cls}" title="${escapeHtml(label)}">${escapeHtml(label)}</span>`;
  }).join('');

  bar.innerHTML = `
    <span class="runtime-bar-label">运行环境</span>
    ${badges}
    <button class="btn-ghost btn-sm runtime-refresh-btn" onclick="refreshRuntimeStatus()">🔄</button>
  `;
}

async function refreshRuntimeStatus() {
  try {
    const resp = await apiGet('/api/runtime-status');
    renderRuntimeStatusBar(resp.runtimes);
    if (!resp.any_available) {
      const result = await showRuntimeMissingModal(resp.runtimes);
      if (result === 'retry') {
        await refreshRuntimeStatus();
      }
    } else {
      showToast('检测到编程环境，可正常执行代码', 'success');
    }
  } catch (err) {
    showToast('环境检测失败: ' + err.message, 'error');
  }
}

async function parseAllDocuments(options = {}) {
  const { stayOnStep, quiet } = options;
  if (!uploadedDocuments.length) {
    showToast('请先添加文档', 'error');
    return;
  }

  resetAgentPlanState({ keepDocuments: true, keepTemplate: true });
  const primaryName = uploadedDocuments[0].fileName;
  if (!quiet) showToast(`正在解析 ${uploadedDocuments.length} 个文档…`, 'info');

  try {
    const payload = await buildDocumentsPayload();
    const resp = await apiPost('/api/parse-report', payload);
    applyParseResponse(resp, primaryName);

    if (parsedQuestions.length === 0) {
      showToast('未检测到题目，请确认文档格式与角色', 'error');
      goToStep(1);
      return;
    }

    const typeLabel = parsedQuestions[0].type === 'lab_report' ? '实验报告' : `${parsedQuestions.length} 个题目`;
    if (!quiet) showToast(`已解析：${typeLabel}`, 'success');

    if (resp.layout === 'combined') {
      agentAwaitingSplitConfirm = true;
      renderSplitPreview(resp);
      goToStep(1);
      updateStepBar(1);
      showToast('检测到合体文档，请确认拆分点后进入计划', 'info');
      return;
    }

    agentAwaitingSplitConfirm = false;
    hideSplitPreview();
    if (stayOnStep !== 1) {
      goToStep(2);
      updateStepBar(2);
    }
  } catch (err) {
    showToast('解析失败: ' + err.message, 'error');
    goToStep(1);
  }
}

async function triggerAnswerTemplateUpload() {
  const result = await window.electronAPI.openDocxDialog();
  if (result.canceled || !result.filePaths?.length) return;
  const path = result.filePaths[0];
  const fileName = path.split(/[\\/]/).pop();
  try {
    const fileData = await window.electronAPI.readFileBase64(path);
    const resp = await apiPost('/api/template/analyze', {
      file_data: fileData,
      file_name: fileName,
      template_type: 'user_sample',
      metadata: parsedMetadata,
      assignment_text: parsedQuestions[0]?.full_text || agentPrimaryFullText || '',
    });
    agentTemplatePending = { path, fileName, formatSpec: resp.format_spec, summary: resp.summary || '' };
    agentTemplateConfirmed = false;
    renderTemplateSummary(agentTemplatePending);
    showToast('范文已分析，请确认是否采用格式建议', 'info');
  } catch (err) {
    showToast('模版分析失败: ' + err.message, 'error');
  }
}

function renderTemplateSummary(pending) {
  const card = document.getElementById('templateSummaryCard');
  const confirmedBar = document.getElementById('templateConfirmedBar');
  const clearBtn = document.getElementById('clearTemplateBtn');
  const textEl = document.getElementById('templateSummaryText');
  const tagsEl = document.getElementById('templateSectionTags');
  const disclaimer = document.querySelector('.template-disclaimer');
  const uploadActions = document.querySelector('.template-upload-actions');
  if (!card || !textEl || !tagsEl) return;

  card.style.display = 'block';
  if (confirmedBar) confirmedBar.style.display = 'none';
  if (clearBtn) clearBtn.style.display = 'inline-flex';

  const isAutoDetected = pending?.source === 'parse';
  if (disclaimer) {
    disclaimer.textContent = isAutoDetected
      ? '已从文档清单中的范文自动提取；仅供参考，以当前报告为准'
      : '仅供参考，以当前报告为准；不与作业章节硬性绑定';
  }

  const spec = pending?.formatSpec || {};
  const fileName = pending?.fileName || '';
  const sourceNote = isAutoDetected && fileName
    ? `（来源：${fileName}）`
    : '';
  textEl.textContent = `${pending?.summary || spec.summary || '已解析模版格式'}${sourceNote}`;
  tagsEl.innerHTML = '';
  const sm = spec.section_map || spec.aligned_section_map || {};
  Object.entries(sm).forEach(([secId, info]) => {
    if (!info || typeof info !== 'object') return;
    const label = SECTION_ROW_DEFS.find((d) => d.id === secId)?.label || secId;
    const hint = info.avg_chars
      ? `${label} 约 ${info.avg_chars} 字${info.requires_images ? '，需配图' : ''}`
      : label;
    const tag = document.createElement('span');
    tag.className = 'section-tag template';
    tag.textContent = hint;
    tagsEl.appendChild(tag);
  });
}

function confirmAnswerTemplate() {
  if (!agentTemplatePending?.formatSpec) {
    showToast('请先上传并分析范文', 'error');
    return;
  }
  agentFormatSpec = agentTemplatePending.formatSpec;
  agentAnswerTemplateText = agentFormatSpec?.template_full_text
    || agentFormatSpec?.full_text
    || '';
  agentTemplateConfirmed = true;
  markAgentPlanStale();

  const card = document.getElementById('templateSummaryCard');
  const confirmedBar = document.getElementById('templateConfirmedBar');
  const label = document.getElementById('templateConfirmedLabel');
  if (card) card.style.display = 'none';
  if (confirmedBar) confirmedBar.style.display = 'block';
  if (label) {
    label.textContent = `已确认格式建议：${agentTemplatePending.fileName}（仅供参考）`;
  }

  if (parsedQuestions[0]?.type === 'lab_report') {
    renderSectionsWorkbench(parsedQuestions[0], parsedMetadata, agentFormatSpec);
  }
  showToast('格式建议已注入后续计划与校验', 'success');
}

function clearAnswerTemplate() {
  agentTemplatePending = null;
  agentTemplateConfirmed = false;
  if (!agentDocumentIds.length) {
    agentFormatSpec = null;
    agentAnswerTemplateText = '';
  }
  const card = document.getElementById('templateSummaryCard');
  const confirmedBar = document.getElementById('templateConfirmedBar');
  const clearBtn = document.getElementById('clearTemplateBtn');
  if (card) card.style.display = 'none';
  if (confirmedBar) confirmedBar.style.display = 'none';
  if (clearBtn) clearBtn.style.display = 'none';
  markAgentPlanStale();
  if (parsedQuestions[0]?.type === 'lab_report') {
    renderSectionsWorkbench(parsedQuestions[0], parsedMetadata, null);
  }
}

function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  document.getElementById('uploadArea').classList.add('dragover');
}

function handleDragLeave(e) {
  e.preventDefault();
  e.stopPropagation();
  document.getElementById('uploadArea').classList.remove('dragover');
}

function handleDrop(e) {
  e.preventDefault();
  document.getElementById('uploadArea').classList.remove('dragover');
  const files = e.dataTransfer.files;
  if (!files.length) return;
  let added = 0;
  for (let i = 0; i < files.length; i += 1) {
    const fp = files[i].path;
    if (fp && addUploadedDocument(fp)) added += 1;
  }
  if (added === 1) {
    parseAllDocuments();
  } else if (added > 1) {
    showToast(`已添加 ${added} 个文档，请确认角色后点「解析并继续」`, 'success');
  }
}

function isPdfSource(metadata, fileName) {
  const lower = (fileName || '').toLowerCase();
  return (metadata && metadata.source_format === 'pdf') || lower.endsWith('.pdf');
}

async function confirmPdfUploadIfNeeded(fileName) {
  const lower = (fileName || '').toLowerCase();
  if (!lower.endsWith('.pdf')) return true;
  return window.confirm(
    '无法直接编辑 PDF，完成实验后将导出为 .docx。\n\n是否继续上传？'
  );
}

function updatePdfExportHint(metadata, fileName) {
  const hint = document.getElementById('pdfExportHint');
  const pairBar = document.getElementById('pdfPairDocxBar');
  const isPdf = isPdfSource(metadata, fileName);
  if (hint) hint.style.display = isPdf ? 'flex' : 'none';
  if (pairBar) pairBar.style.display = isPdf ? 'flex' : 'none';
  updatePdfPairDocxLabel();
}

function updatePdfPairDocxLabel() {
  const label = document.getElementById('pdfPairDocxLabel');
  const clearBtn = document.getElementById('clearPairedDocxBtn');
  if (!label) return;
  if (pairedDocxPath) {
    const name = pairedDocxPath.split(/[\\/]/).pop();
    label.textContent = `已配对 Word 模版：${name}（填表将写入该 docx）`;
    if (clearBtn) clearBtn.style.display = 'inline-flex';
  } else {
    label.textContent = '可选：添加空白 Word 模版，填表写入该 docx（题目 PDF + 空白 Word 亦可）';
    if (clearBtn) clearBtn.style.display = 'none';
  }
}

async function triggerPairedDocxUpload() {
  const result = await window.electronAPI.openDocxDialog();
  if (result.canceled || !result.filePaths?.length) return;
  pairedDocxPath = result.filePaths[0];
  updatePdfPairDocxLabel();
  markAgentPlanStale();
  showToast(`已配对 Word 模版：${pairedDocxPath.split(/[\\/]/).pop()}`, 'success');
}

function clearPairedDocx() {
  pairedDocxPath = null;
  updatePdfPairDocxLabel();
  markAgentPlanStale();
}

function buildFillMetadata() {
  const meta = { ...(parsedMetadata || {}) };
  if (agentAssignmentText && !meta.assignment_text) {
    meta.assignment_text = agentAssignmentText;
  }
  if (agentReportLayout) meta.report_layout = agentReportLayout;
  if ((agentTableMap || []).length) meta.table_map = agentTableMap;
  if ((agentSectionsDetected || []).length) meta.sections_detected = agentSectionsDetected;
  if (agentSectionMap && Object.keys(agentSectionMap).length) {
    meta.section_map = agentSectionMap;
  }
  if (agentFillHints && Object.keys(agentFillHints).length) {
    meta.fill_hints = agentFillHints;
  }
  if (agentUserSemanticOverrides && Object.keys(agentUserSemanticOverrides).length) {
    meta.semantic_overrides = agentUserSemanticOverrides;
  }
  return meta;
}

async function buildFillReportPayload() {
  const payload = { answers: solvedAnswers };
  let fileName = '实验报告.docx';
  const meta = buildFillMetadata();
  let isPdf = isPdfSource(meta, '');

  if (currentFile && currentFile !== 'demo') {
    fileName = currentFile.split(/[\\/]/).pop();
    isPdf = isPdfSource(meta, fileName);
  }

  payload.metadata = meta;
  payload.fill_body_text = parsedQuestions[0]?.full_text
    || parsedQuestions[0]?.content
    || agentPrimaryFullText
    || '';

  if (pairedDocxPath) {
    payload.paired_docx_data = await window.electronAPI.readFileBase64(pairedDocxPath);
    payload.paired_docx_name = pairedDocxPath.split(/[\\/]/).pop();
    payload.source_format = isPdf ? 'pdf' : (meta.source_format || 'docx');
    if (!isPdf && currentFile && currentFile !== 'demo') {
      payload.file_data = await window.electronAPI.readFileBase64(currentFile);
      payload.file_name = fileName;
    } else {
      payload.file_name = fileName;
    }
    return payload;
  }

  if (isPdf) {
    payload.source_format = 'pdf';
    payload.file_name = fileName;
    return payload;
  }

  payload.source_format = meta.source_format || 'docx';
  if (currentFile && currentFile !== 'demo') {
    payload.file_data = await window.electronAPI.readFileBase64(currentFile);
    payload.file_name = fileName;
  } else {
    payload.file_name = fileName;
  }
  return payload;
}

function defaultExportFileName() {
  if (isPdfSource(parsedMetadata, currentFile?.split(/[\\/]/).pop())) {
    const stem = (currentFile && currentFile !== 'demo')
      ? currentFile.split(/[\\/]/).pop().replace(/\.pdf$/i, '')
      : '实验报告';
    return `${stem}_已完成.docx`;
  }
  return '实验报告_已完成.docx';
}

async function handleFile(filePath) {
  if (addUploadedDocument(filePath)) {
    await parseAllDocuments();
  }
}

function renderQuestions(questions) {
  const list = document.getElementById('questionsList');
  list.innerHTML = '';

  if (questions.length === 0) {
    list.innerHTML = '<div class="empty-state"><span>📭</span><p>未找到题目</p></div>';
    return;
  }

  questions.forEach((q, i) => {
    const typeMap = {
      'code': { label: '编程题', cls: 'badge-code' },
      'theory': { label: '理论题', cls: 'badge-theory' },
      'analysis': { label: '分析题', cls: 'badge-analysis' },
    };
    const type = typeMap[q.type] || { label: '其他', cls: 'badge-theory' };

    const card = document.createElement('div');
    card.className = 'question-card';
    card.innerHTML = `
      <span class="question-type-badge ${type.cls}">${type.label}</span>
      <div class="question-content">
        <div class="question-title">题目 ${i + 1}: ${q.title || '未命名'}</div>
        <div class="question-preview">${q.content?.substring(0, 120) || ''}...</div>
      </div>
    `;
    list.appendChild(card);
  });
}

// ============================
// 工具箱模式（Phase 2）
// ============================

let currentToolMode = 'guided';

const TOOL_DEFS = [
  { id: 'parse',  num: 1, icon: '📄', label: '解析文档',       hasInput: false, hasOutput: true,  inputLabel: '',                                                    outputLabel: '解析结果', standalone: false },
  { id: 'solve',  num: 2, icon: '🧠', label: 'AI 解题',         hasInput: true,  hasOutput: true,  inputLabel: '题目文本（来自 #1 解析结果）',                   outputLabel: '解题结果 (JSON)', standalone: false },
  { id: 'run',    num: null, icon: '▶', label: '运行代码（手动）', hasInput: true,  hasOutput: true,  inputLabel: '代码（来自 #2 中的 code）',                       outputLabel: '运行结果', standalone: true, advanced: true },
  { id: 'screenshot', num: 4, icon: '📸', label: '截图',        hasInput: true,  hasOutput: true,  inputLabel: '代码（来自 #2 中的 code）',                       outputLabel: '截图 (PNG base64)', standalone: true },
  { id: 'uml',    num: 5, icon: '📊', label: '图表渲染',         hasInput: true,  hasOutput: true,  inputLabel: 'diagrams JSON / PlantUML / dfd_json（来自 #2 的 diagrams，最多 12 张）', outputLabel: 'UML / DFD 图片', standalone: true },
  { id: 'fill',   num: null, icon: '📝', label: '填写报告（实验性）', hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON（来自 #2 + #3 + #4 + #5）',            outputLabel: '填写后的 docx', standalone: false, advanced: true },
  { id: 'fix',    num: null, icon: '🔧', label: '修复代码',      hasInput: true,  hasOutput: true,  inputLabel: '代码 + 错误文本',                                  outputLabel: '修复后代码', standalone: true },
  { id: 'verify', num: null, icon: '✅', label: '校验答案',      hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON',                                       outputLabel: '校验结果', standalone: true },
  { id: 'revise', num: null, icon: '✏️', label: '修订答案',      hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON + 反馈',                                outputLabel: '修订后答案', standalone: true },
];

function makeToolState() {
  return {
    status: 'idle',   // idle | running | success | failed | stale
    input: '',        // editable text (user typed or auto-filled)
    output: null,     // parsed result object
    outputText: '',
    meta: null,       // optional: { tokens, duration, ... }
  };
}

let toolState = {};
TOOL_DEFS.forEach((t) => { toolState[t.id] = makeToolState(); });

const TOOLBOX_STORAGE_KEY = 'toolboxState';

function saveToolboxState() {
  const data = {};
  for (const [id, state] of Object.entries(toolState)) {
    data[id] = {
      status: state.status,
      input: state.input,
      output: state.output,
      outputText: state.outputText,
      meta: state.meta,
    };
  }
  try { localStorage.setItem(TOOLBOX_STORAGE_KEY, JSON.stringify(data)); } catch {}
}

function loadToolboxState() {
  try {
    const saved = JSON.parse(localStorage.getItem(TOOLBOX_STORAGE_KEY) || 'null');
    if (!saved) return false;
    let restored = false;
    for (const [id, data] of Object.entries(saved)) {
      if (toolState[id] && data.status && data.status !== 'idle') {
        toolState[id] = { ...toolState[id], ...data };
        restored = true;
      }
    }
    return restored;
  } catch { return false; }
}

function clearToolboxStorage() {
  try { localStorage.removeItem(TOOLBOX_STORAGE_KEY); } catch {}
}

function syncToolboxParseFromAgent() {
  if (!agentPrimaryFullText) return;
  const ps = toolState.parse;
  if (ps.status === 'idle' && !ps.input) {
    ps.status = 'success';
    ps.output = {
      full_text: agentPrimaryFullText,
      sections: agentSectionsDetected,
      section_map: agentSectionMap,
      tables: [],
      images: [],
      metadata: parsedMetadata,
      source_format: parsedMetadata?.source_format || 'docx',
      char_count: agentPrimaryFullText.length,
    };
    ps.outputText = JSON.stringify(ps.output, null, 2);
    ps.meta = { source: 'from_agent', note: '来自引导模式解析' };
  }
}

function switchToToolboxMode() {
  currentToolMode = 'toolbox';
  document.getElementById('guidedModeContent').style.display = 'none';
  document.getElementById('toolboxPanel').style.display = 'flex';
  document.querySelectorAll('.mode-switch-tab').forEach((el) => {
    el.classList.toggle('active', el.dataset.mode === 'toolbox');
  });
  syncToolboxParseFromAgent();
  loadToolboxState();
  renderToolboxPanel();
  refreshToolboxDiagramStatus();
}

function switchToGuidedMode() {
  currentToolMode = 'guided';
  document.getElementById('guidedModeContent').style.display = '';
  document.getElementById('toolboxPanel').style.display = 'none';
  document.querySelectorAll('.mode-switch-tab').forEach((el) => {
    el.classList.toggle('active', el.dataset.mode === 'guided');
  });
}

function showModeSwitchBar() {
  const bar = document.getElementById('modeSwitchBar');
  if (bar) bar.style.display = 'flex';
}

function showReviseFeedbackModal() {
  return new Promise((resolve) => {
    const modal = document.getElementById('reviseFeedbackModal');
    const textarea = document.getElementById('reviseFeedbackText');
    const submitBtn = document.getElementById('reviseFeedbackSubmit');
    const cancelBtn = document.getElementById('reviseFeedbackCancel');
    if (!modal || !textarea) { resolve('请改进答案质量'); return; }

    textarea.value = '请改进答案质量';
    modal.style.display = 'flex';

    function cleanup() {
      modal.style.display = 'none';
      submitBtn.onclick = null;
      cancelBtn.onclick = null;
    }

    submitBtn.onclick = () => {
      const val = textarea.value.trim() || '请改进答案质量';
      cleanup();
      resolve(val);
    };
    cancelBtn.onclick = () => {
      cleanup();
      resolve(null);
    };
  });
}

const DIAGRAM_KIND_LABELS = {
  class: '类图', sequence: '时序图', usecase: '用例图', activity: '活动图',
  state: '状态图', er: 'ER图', deployment: '部署图', component: '构件图',
  package: '包图', flowchart: '流程图', dfd: 'DFD',
};

function parseDiagramToolInput(input) {
  const text = (input || '').trim();
  if (!text) return null;
  if (text.startsWith('[') || text.startsWith('{')) {
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) return { diagrams: parsed };
      if (parsed && typeof parsed === 'object') {
        if (Array.isArray(parsed.diagrams)) return { diagrams: parsed.diagrams };
        if (parsed.plantuml || parsed.dfd_json || parsed.kind) return { diagrams: [parsed] };
      }
    } catch {
      // fall through to PlantUML text
    }
  }
  return { plantuml_src: text };
}

function formatDiagramToolOutput(data) {
  if (!data) return '';
  const lines = [];
  if (data.summary) lines.push(data.summary);
  else if (data.images_b64?.length) {
    lines.push(`图表渲染完成，共 ${data.images_b64.length} 张`);
  } else {
    lines.push('未生成图片');
  }
  if (data.kind_stats && Object.keys(data.kind_stats).length) {
    const parts = Object.entries(data.kind_stats).map(
      ([k, n]) => `${DIAGRAM_KIND_LABELS[k] || k}×${n}`
    );
    lines.push(`类型统计: ${parts.join('，')}`);
  }
  if (data.titles?.length) lines.push(`标题: ${data.titles.join(' · ')}`);
  if (data.errors?.length) lines.push(`错误:\n${data.errors.join('\n')}`);
  if (data.consistency?.message) lines.push(`一致性: ${data.consistency.message}`);
  const val = data.validation;
  if (val) {
    lines.push(val.ok ? '验错: 通过' : '验错: 未通过');
    for (const chk of val.checks || []) {
      if (!chk.ok) lines.push(`  ✗ ${chk.id}: ${chk.message}`);
    }
    for (const issue of val.issues || []) {
      lines.push(`  · ${issue.message || issue}`);
    }
    if (val.suggested_actions?.length) {
      lines.push(`建议: ${val.suggested_actions.join(' → ')}`);
    }
  }
  return lines.join('\n');
}

function buildDiagramPreviewHtml(data) {
  const imgs = data?.images_b64 || [];
  if (!imgs.length) return '';
  return `<div class="tool-diagram-preview">${imgs.map((b64, i) => {
    const title = data.titles?.[i] || `图 ${i + 1}`;
    return `<div class="tool-diagram-item">
      <div class="tool-diagram-title">${escapeHtml(title)}</div>
      <img src="data:image/png;base64,${b64}" alt="${escapeHtml(title)}" loading="lazy"/>
    </div>`;
  }).join('')}</div>`;
}

async function refreshToolboxDiagramStatus() {
  const el = document.getElementById('toolboxDiagramStatus');
  if (!el) return;
  try {
    const resp = await apiGet('/api/runtime-status');
    const dt = resp.diagram_tools || {};
    const items = [
      { ok: dt.plantuml_jar_ok, label: 'PlantUML JAR' },
      { ok: dt.java_ok, label: 'Java' },
      { ok: dt.graphviz_ok, label: 'Graphviz (DFD)' },
    ];
    const badges = items.map((b) => (
      `<span class="diagram-badge ${b.ok ? 'ok' : 'missing'}" title="${b.ok ? '可用' : '不可用'}">${b.ok ? '✅' : '❌'} ${escapeHtml(b.label)}</span>`
    )).join('');
    el.innerHTML = `<span class="diagram-bar-label">图表引擎</span>${badges}`;
    el.style.display = 'flex';
  } catch (err) {
    console.warn('diagram status check failed:', err);
    el.style.display = 'none';
  }
}

function confirmResetToolbox() {
  const hasResults = Object.values(toolState).some(
    (s) => s.status === 'success' || s.status === 'failed'
  );
  if (!hasResults || confirm('确定要重置所有工具状态吗？这将清除所有输入和输出。')) {
    resetToolboxState();
  }
}

function resolveToolInput(toolId) {
  const state = toolState[toolId];
  if (state.input && state.input.trim()) return state.input;

  switch (toolId) {
    case 'solve':
      return toolState.parse.output?.full_text || agentPrimaryFullText || '';
    case 'run': {
      const solveOut = toolState.solve.output;
      if (solveOut) return solveOut.code || '';
      return '';
    }
    case 'screenshot': {
      const solveOut = toolState.solve.output;
      if (solveOut) return solveOut.code || '';
      return '';
    }
    case 'uml': {
      const solveOut = toolState.solve.output;
      if (solveOut?.diagrams?.length) {
        return JSON.stringify(solveOut.diagrams, null, 2);
      }
      return '';
    }
    case 'fill': {
      const solveOut = toolState.solve.output;
      if (solveOut) return JSON.stringify(solveOut, null, 2);
      return '';
    }
    case 'fix': {
      const runOut = toolState.run.output;
      const solveOut = toolState.solve.output;
      const code = solveOut?.code || '';
      const err = runOut?.stderr || runOut?.stdout || '';
      return code;
    }
    case 'verify': {
      const solveOut = toolState.solve.output;
      if (solveOut) return JSON.stringify(solveOut, null, 2);
      return '';
    }
    case 'revise': {
      const solveOut = toolState.solve.output;
      if (solveOut) return JSON.stringify(solveOut, null, 2);
      return '';
    }
    default:
      return '';
  }
}

function markDownstreamStale(toolId) {
  const order = ['parse', 'solve', 'run', 'screenshot', 'uml', 'fill'];
  const idx = order.indexOf(toolId);
  if (idx < 0) return;
  for (let i = idx + 1; i < order.length; i++) {
    const tid = order[i];
    if (toolState[tid].status === 'success') {
      toolState[tid].status = 'stale';
    }
  }
}

/** After fix_code succeeds, push fixed code into solve + run + screenshot inputs. */
function propagateFixedCodeToToolbox(fixPayload) {
  if (!fixPayload) return;
  const fixedCode = fixPayload.code || '';
  const codeFiles = fixPayload.code_files || [];
  const mainFile = fixPayload.main_file || '';
  const language = fixPayload.language || '';

  const codeForRun = fixedCode || (codeFiles.length
    ? (codeFiles.find((f) => f.name === mainFile) || codeFiles[0])?.code || ''
    : '');
  if (!codeForRun && !codeFiles.length) return;

  if (toolState.solve.output) {
    const merged = { ...toolState.solve.output };
    if (fixedCode) merged.code = fixedCode;
    if (language) merged.language = language;
    if (codeFiles.length) merged.code_files = codeFiles;
    if (mainFile) merged.main_file = mainFile;
    if (merged.parsed) {
      merged.parsed = { ...merged.parsed };
      if (fixedCode) merged.parsed.code = fixedCode;
      if (codeFiles.length) merged.parsed.code_files = codeFiles;
      if (mainFile) merged.parsed.main_file = mainFile;
      if (language) merged.parsed.language = language;
    }
    toolState.solve.output = merged;
  }

  if (codeForRun) {
    toolState.run.input = codeForRun;
    toolState.screenshot.input = codeForRun;
  }

  for (const tid of ['run', 'screenshot', 'fill']) {
    const st = toolState[tid];
    if (st.status === 'success' || st.status === 'failed') {
      st.status = 'stale';
    }
  }
}

function updateToolStatusUI(toolId) {
  const card = document.querySelector(`.tool-card[data-tool="${toolId}"]`);
  if (!card) return;
  const state = toolState[toolId];
  card.classList.remove('running', 'success', 'failed', 'stale');
  if (state.status !== 'idle') card.classList.add(state.status);
  const statusEl = card.querySelector('.tool-card-status');
  if (statusEl) {
    statusEl.className = 'tool-card-status ' + state.status;
    const labels = { idle: '⏸ 未执行', running: '⏳ 执行中…', success: '✅ 成功', failed: '❌ 失败', stale: '⚠️ 输入已更新' };
    statusEl.textContent = labels[state.status] || state.status;
  }
  const outputEl = card.querySelector('.tool-card-output');
  if (outputEl && state.outputText) {
    outputEl.textContent = state.outputText;
  }
  const metaEl = card.querySelector('.tool-card-meta');
  if (metaEl && state.meta) {
    const parts = [];
    if (state.meta.tokens) parts.push(`tokens ${state.meta.tokens}`);
    if (state.meta.duration) parts.push(`耗时 ${state.meta.duration}`);
    metaEl.textContent = parts.join(' · ');
  }
}

function buildToolCardHtml(def, state) {
  const inputVal = resolveToolInput(def.id);
  if (!state.input && inputVal) state.input = inputVal;

  const statusLabels = { idle: '⏸ 未执行', running: '⏳ 执行中…', success: '✅ 成功', failed: '❌ 失败', stale: '⚠️ 输入已更新' };
  const statusText = statusLabels[state.status] || state.status;
  const inputPreview = (state.input || inputVal || '').slice(0, 80);

  return `<div class="tool-card ${state.status !== 'idle' ? state.status : ''}" data-tool="${def.id}">
    <div class="tool-card-head" onclick="toggleToolCard('${def.id}')">
      ${def.num ? `<span class="tool-card-num">${def.num}.</span>` : ''}
      <span class="tool-card-icon">${def.icon}</span>
      <span class="tool-card-label">${def.label}</span>
      <span class="tool-card-input-hint" title="${escapeHtml(inputPreview)}">${escapeHtml(inputPreview || '（点击展开配置输入）')}</span>
      <span class="tool-card-status ${state.status}">${statusText}</span>
      <span class="tool-card-expand">▼</span>
    </div>
    <div class="tool-card-body">
      ${def.hasInput ? `
      <textarea class="tool-card-input" data-tool-input="${def.id}" rows="4"
        placeholder="${escapeHtml(def.inputLabel || '')}"
        oninput="onToolInputChange('${def.id}', this.value)">${escapeHtml(state.input || '')}</textarea>
      ` : ''}
      ${def.id === 'run' ? `
      <div class="tool-card-config">
        <label style="font-size:12px;color:var(--text-secondary)">语言</label>
        <select data-tool-config="${def.id}-lang" onchange="onToolConfigChange('${def.id}')">
          <option value="python">Python</option>
          <option value="java">Java</option>
          <option value="c">C</option>
          <option value="cpp">C++</option>
          <option value="javascript">JavaScript</option>
        </select>
      </div>` : ''}
      ${def.id === 'screenshot' ? `
      <div class="tool-card-config">
        <label style="font-size:12px;color:var(--text-secondary)">主题</label>
        <select data-tool-config="${def.id}-theme" onchange="onToolConfigChange('${def.id}')">
          <option value="windows">Windows</option>
          <option value="mac">macOS</option>
        </select>
      </div>` : ''}
      ${def.id === 'uml' ? `
      <div class="tool-card-config tool-card-config-col">
        <label style="font-size:12px;color:var(--text-secondary);display:flex;align-items:center;gap:6px">
          <input type="checkbox" data-tool-config="${def.id}-online"
            ${loadSettings().umlAllowOnline !== false ? 'checked' : ''}
            onchange="onToolConfigChange('${def.id}')"/>
          PlantUML 允许在线渲染（本地 JAR 优先；DFD 始终走便携 Graphviz）
        </label>
        <div class="form-hint">支持 kind：class / sequence / state / er / deployment / dfd 等；dfd 用 dfd_json</div>
      </div>` : ''}
      ${def.id === 'fix' ? `
      <div class="tool-card-config">
        <label style="font-size:12px;color:var(--text-secondary)">语言</label>
        <select data-tool-config="${def.id}-lang" onchange="onToolConfigChange('${def.id}')">
          <option value="python">Python</option>
          <option value="java">Java</option>
          <option value="c">C</option>
          <option value="cpp">C++</option>
          <option value="javascript">JavaScript</option>
        </select>
      </div>
      <textarea class="tool-card-input" data-tool-input="${def.id}-error" rows="2"
        placeholder="错误文本（来自 #3 运行结果）"
        oninput="onToolConfigChange('${def.id}')"></textarea>
      ` : ''}
      <div class="tool-card-actions">
        <button type="button" class="btn-primary btn-sm" onclick="executeTool('${def.id}')"
          ${state.status === 'running' ? 'disabled' : ''}>
          ${state.status === 'running' ? '⏳ 执行中…' : '▶ 执行'}
        </button>
        ${def.id === 'uml' ? `
        <button type="button" class="btn-secondary btn-sm" onclick="verifyDiagramsTool('${def.id}')"
          ${state.status === 'running' ? 'disabled' : ''}>🔍 验错</button>
        <button type="button" class="btn-secondary btn-sm" onclick="fixDiagramsTool('${def.id}')"
          ${state.status === 'running' ? 'disabled' : ''}>🛠 AI 修复</button>
        ` : ''}
        ${state.status === 'failed' ?
          `<button type="button" class="btn-secondary btn-sm" onclick="executeTool('${def.id}')">🔄 重试</button>` : ''}
        ${def.hasOutput ? `<button type="button" class="btn-ghost btn-sm" onclick="copyToolOutput('${def.id}')">📋 复制输出</button>` : ''}
      </div>
      ${state.status === 'running' ? '<div class="tool-card-progress"></div>' : ''}
      ${(def.id === 'verify' || def.id === 'revise') && state.input ?
        (() => { try { JSON.parse(state.input); return ''; }
          catch { return '<div class="tool-card-validation-hint">⚠️ 输入不是有效的 JSON 格式</div>'; }
        })() : ''}
      ${def.hasOutput && state.outputText ? `
      <div class="tool-card-output">${escapeHtml(state.outputText)}</div>
      ` : (def.hasOutput ? `<div class="tool-card-output" style="color:var(--text-muted);font-style:italic">（输出将显示在这里）</div>` : '')}
      ${def.id === 'uml' && state.output ? buildDiagramPreviewHtml(state.output) : ''}
      ${state.meta ? `<div class="tool-card-meta">${state.meta.tokens ? `tokens ${state.meta.tokens}` : ''}${state.meta.duration ? ` · 耗时 ${state.meta.duration}` : ''}</div>` : ''}
    </div>
  </div>`;
}

const ARROW_LABELS = {
  parse: '自动传递: full_text',
  solve: '自动传递: answer_json',
  run: '自动传递: stdout',
  screenshot: '自动传递: images_b64',
  uml: '自动传递: diagrams → 图片',
};

function renderToolboxPanel() {
  const container = document.getElementById('toolboxTools');
  if (!container) return;

  const seqTools = TOOL_DEFS.filter((d) => d.num !== null);
  const auxTools = TOOL_DEFS.filter((d) => d.num === null && !d.advanced);
  const advancedTools = TOOL_DEFS.filter((d) => d.advanced);

  // Sequential tools: render cards with arrows between them
  let html = '<div class="toolbox-seq-group">';
  seqTools.forEach((def, i) => {
    const state = toolState[def.id] || makeToolState();
    html += buildToolCardHtml(def, state);

    if (i < seqTools.length - 1) {
      const nextDef = seqTools[i + 1];
      const nextState = toolState[nextDef.id];
      const arrowStale = nextState && nextState.status === 'stale' ? ' stale' : '';
      const arrowLabel = ARROW_LABELS[def.id] || '';
      html += `<div class="tool-arrow${arrowStale}" data-from="${def.id}" data-to="${nextDef.id}">
        <span class="tool-arrow-line"></span>
        <span class="tool-arrow-label">${arrowLabel}</span>
      </div>`;
    }
  });
  html += '</div>';

  // Auxiliary tools row
  html += '<div class="toolbox-aux-row">';
  auxTools.forEach((def) => {
    const state = toolState[def.id] || makeToolState();
    html += buildToolCardHtml(def, state);
  });
  html += '</div>';

  if (advancedTools.length) {
    html += '<details class="toolbox-advanced-group"><summary>高级 / 实验性</summary><div class="toolbox-aux-row">';
    advancedTools.forEach((def) => {
      const state = toolState[def.id] || makeToolState();
      html += buildToolCardHtml(def, state);
    });
    html += '</div></details>';
  }

  container.innerHTML = html;

  // Update chain button enabled state
  updateChainButtonState();
}

function updateChainButtonState() {
  const btn = document.getElementById('toolboxChainBtn');
  if (!btn) return;
  const hasDocs = uploadedDocuments.length > 0;
  const parseRunning = toolState.parse.status === 'running';
  const solveRunning = toolState.solve.status === 'running';
  const fillRunning = toolState.fill.status === 'running';
  const chainRunning = parseRunning || solveRunning || fillRunning;
  btn.disabled = !hasDocs || chainRunning;
  if (chainRunning) {
    btn.textContent = '⏳ 链式执行中…';
  } else {
    btn.textContent = '⚡ 一键链 (#1→#2 解题)';
  }
}

async function runToolChain() {
  if (!uploadedDocuments.length) {
    showToast('请先在 Step 1 添加文档', 'error');
    goToStep(1);
    return;
  }

  const chain = ['parse', 'solve'];
  updateChainButtonState();

  for (const toolId of chain) {
    const def = TOOL_DEFS.find((t) => t.id === toolId);
    showToast(`链式执行：${def?.label || toolId}…`, 'info');
    await executeTool(toolId);
    const state = toolState[toolId];
    if (state.status === 'failed') {
      showToast(`链式执行中断：${def?.label || toolId} 失败`, 'error');
      updateChainButtonState();
      return;
    }
  }

  updateChainButtonState();
  showToast('链式执行完成！', 'success');
}

function toggleToolCard(toolId) {
  const card = document.querySelector(`.tool-card[data-tool="${toolId}"]`);
  if (card) card.classList.toggle('expanded');
}

function onToolInputChange(toolId, value) {
  toolState[toolId].input = value;
  markDownstreamStale(toolId);
  updateToolStatusUI(toolId);
  renderToolboxPanel(); // refresh input hints
}

function onToolConfigChange(toolId) {
  // Just mark for re-render hints; values read at execute time
}

async function executeTool(toolId) {
  const settings = loadSettings();
  const state = toolState[toolId];
  if (!state) return;

  // Check API key for LLM-dependent tools
  const needsKey = ['solve', 'fix', 'revise'].includes(toolId);
  if (needsKey && !settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }

  state.status = 'running';
  state.output = null;
  state.outputText = '';
  state.meta = null;
  updateToolStatusUI(toolId);
  renderToolboxPanel();

  const startTime = Date.now();
  try {
    let resp;
    const lang = document.querySelector(`[data-tool-config="${toolId}-lang"]`)?.value || 'python';
    const theme = document.querySelector(`[data-tool-config="${toolId}-theme"]`)?.value || 'windows';

    switch (toolId) {
      case 'parse': {
        if (!uploadedDocuments.length) {
          throw new Error('请先在 Step 1 添加文档');
        }
        const doc = uploadedDocuments[0];
        const fileData = await window.electronAPI.readFileBase64(doc.path);
        resp = await apiPost('/api/tool/parse', {
          file_data: fileData,
          file_name: doc.fileName,
        });
        break;
      }
      case 'solve': {
        const text = state.input || resolveToolInput('solve');
        if (!text) throw new Error('请先执行 #1 解析文档，或手动粘贴题目文本');
        resp = await apiPost('/api/tool/solve', {
          api_key: settings.apiKey,
          provider: settings.provider,
          model: settings.model,
          custom_url: settings.customUrl || '',
          text,
          language: settings.codeLanguage || 'python',
          include_uml: settings.includeUml === true,
          format_spec: agentFormatSpec || undefined,
          user_constraints: getUserConstraints(),
          provenance_custom_label: getProvenanceCustomLabel() || undefined,
        });
        break;
      }
      case 'run': {
        const code = state.input || resolveToolInput('run');
        if (!code) throw new Error('请先执行 #2 AI 解题，或手动粘贴代码');
        resp = await apiPost('/api/tool/run', { code, language: lang });
        break;
      }
      case 'screenshot': {
        const code = state.input || resolveToolInput('screenshot');
        if (!code) throw new Error('请先执行 #2 AI 解题，或手动粘贴代码');
        resp = await apiPost('/api/tool/screenshot', {
          code,
          language: lang,
          chrome_style: theme,
          ...getTerminalConfig(),
        });
        break;
      }
      case 'uml': {
        const rawInput = state.input || resolveToolInput('uml');
        if (!rawInput) {
          throw new Error('请先执行 #2 AI 解题（需含 diagrams），或粘贴 PlantUML / dfd_json / diagrams JSON');
        }
        const parsed = parseDiagramToolInput(rawInput);
        const allowOnline = document.querySelector('[data-tool-config="uml-online"]')?.checked !== false;
        resp = await apiPost('/api/tool/uml', {
          ...parsed,
          allow_online: allowOnline,
          code: toolState.solve.output?.code || '',
          language: toolState.solve.output?.language || lang,
        });
        break;
      }
      case 'fill': {
        // Build answer_json from all upstream outputs
        const solveOut = toolState.solve.output || {};
        const runOut = toolState.run.output || {};
        const shotOut = toolState.screenshot.output || {};
        const umlOut = toolState.uml.output || {};
        const answers = [{
          ...solveOut,
          code: solveOut.code || '',
          code_files: solveOut.code_files || [],
          main_file: solveOut.main_file || '',
          language: solveOut.language || settings.codeLanguage || 'python',
          output: runOut.stdout || '',
          images_b64: shotOut.images_b64 || [],
          uml_images_b64: umlOut.images_b64 || [],
        }];
        let fillPayload = {
          answer_json: answers,
          file_name: (uploadedDocuments[0]?.fileName || 'report.docx'),
          fill_sections: collectSectionsConfigForApi().sections || undefined,
          metadata: parsedMetadata,
        };
        if (uploadedDocuments.length && uploadedDocuments[0].path) {
          const doc = uploadedDocuments[0];
          fillPayload.file_data = await window.electronAPI.readFileBase64(doc.path);
          fillPayload.file_name = doc.fileName;
          fillPayload.source_format = doc.docFormat || 'docx';
        }
        resp = await apiPost('/api/tool/fill', fillPayload);
        break;
      }
      case 'fix': {
        const code = state.input || resolveToolInput('fix');
        if (!code) throw new Error('请提供要修复的代码');
        const errorEl = document.querySelector(`[data-tool-input="${toolId}-error"]`);
        const errorOutput = errorEl?.value || toolState.run.output?.stderr || toolState.run.output?.stdout || '';
        resp = await apiPost('/api/tool/fix', {
          api_key: settings.apiKey,
          provider: settings.provider,
          model: settings.model,
          custom_url: settings.customUrl || '',
          code,
          language: lang,
          error_output: errorOutput,
          report_excerpt: agentPrimaryFullText || '',
        });
        break;
      }
      case 'verify': {
        let answerJson;
        try {
          answerJson = JSON.parse(state.input || resolveToolInput('verify') || '{}');
        } catch {
          answerJson = toolState.solve.output || {};
        }
        resp = await apiPost('/api/tool/verify', {
          answer_json: answerJson,
          answer_template_text: agentAnswerTemplateText || '',
        });
        break;
      }
      case 'revise': {
        let answerJson;
        try {
          answerJson = JSON.parse(state.input || resolveToolInput('revise') || '{}');
        } catch {
          answerJson = toolState.solve.output || {};
        }
        const feedback = await showReviseFeedbackModal();
        if (!feedback) {
          state.status = 'idle';
          updateToolStatusUI(toolId);
          renderToolboxPanel();
          return;
        }
        resp = await apiPost('/api/tool/revise', {
          api_key: settings.apiKey,
          provider: settings.provider,
          model: settings.model,
          custom_url: settings.customUrl || '',
          answer_json: answerJson,
          feedback,
          report_excerpt: agentPrimaryFullText || '',
          scope: ['full'],
          format_spec: agentFormatSpec || undefined,
        });
        break;
      }
      default:
        throw new Error('未知工具: ' + toolId);
    }

    const duration = ((Date.now() - startTime) / 1000).toFixed(1) + 's';
    if (resp && resp.ok) {
      const payload = resp.data || resp;
      const umlFailed = toolId === 'uml' && payload && payload.success === false;
      state.status = umlFailed ? 'failed' : 'success';
      state.output = payload;
      if (toolId === 'uml') {
        state.outputText = formatDiagramToolOutput(state.output);
      } else {
        state.outputText = JSON.stringify(payload, null, 2);
      }
      state.meta = {
        tokens: resp.data?.tokens || resp.tokens || null,
        duration,
      };
      // Reverse sync: toolbox parse → agent mode
      if (toolId === 'parse') {
        agentPrimaryFullText = resp.data?.full_text || agentPrimaryFullText;
      }
      if (toolId === 'fix') {
        propagateFixedCodeToToolbox(payload);
      }
      markDownstreamStale(toolId);
    } else {
      state.status = 'failed';
      state.outputText = resp?.error || '未知错误';
    }
  } catch (err) {
    state.status = 'failed';
    state.outputText = err.message;
  }

  updateToolStatusUI(toolId);
  renderToolboxPanel();
  // Update output toolbar
  updateToolboxOutputBar();
  updateChainButtonState();
  saveToolboxState();

  if (state.status === 'success') {
    if (toolId === 'fix') {
      showToast('修复完成，已同步到「运行代码」— 请重新执行 #3 验证', 'success');
    } else {
      showToast(`${TOOL_DEFS.find((t) => t.id === toolId)?.label || toolId} 执行成功`, 'success');
    }
  } else if (state.status === 'failed' && toolId === 'uml' && state.output?.images_b64?.length) {
    showToast('图表已部分渲染，但验错未通过 — 可点「AI 修复」', 'error');
  } else {
    showToast(`${TOOL_DEFS.find((t) => t.id === toolId)?.label || toolId} 执行失败`, 'error');
  }
}

async function verifyDiagramsTool(toolId) {
  if (toolId !== 'uml') return;
  const settings = loadSettings();
  const state = toolState[toolId];
  const solveOut = toolState.solve.output || {};
  const parsed = solveOut.parsed || solveOut;
  let diagrams;
  try {
    const parsedInput = parseDiagramToolInput(state.input || resolveToolInput('uml'));
    diagrams = parsedInput?.diagrams;
  } catch {
    diagrams = null;
  }
  if (!diagrams?.length && !parsed?.diagrams?.length) {
    showToast('请先填写 diagrams 或执行 #2 解题', 'error');
    return;
  }
  state.status = 'running';
  renderToolboxPanel();
  try {
    const resp = await apiPost('/api/tool/verify-diagrams', {
      answer_json: solveOut,
      diagrams,
      render_result: state.output || undefined,
      code: solveOut.code || parsed.code || '',
      language: solveOut.language || parsed.language || 'java',
    });
    const report = resp.data || resp;
    state.status = report.ok ? 'success' : 'failed';
    state.output = { ...(state.output || {}), validation: report };
    state.outputText = formatDiagramToolOutput({
      ...(state.output || {}),
      validation: report,
      summary: report.ok ? '验错通过' : '验错未通过',
    });
    showToast(report.ok ? '图表验错通过' : '图表验错发现问题', report.ok ? 'success' : 'error');
  } catch (err) {
    state.status = 'failed';
    state.outputText = err.message;
    showToast('验错失败: ' + err.message, 'error');
  }
  renderToolboxPanel();
  saveToolboxState();
}

async function fixDiagramsTool(toolId) {
  if (toolId !== 'uml') return;
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  const state = toolState[toolId];
  const solveOut = toolState.solve.output;
  if (!solveOut) {
    showToast('请先执行 #2 AI 解题', 'error');
    return;
  }
  state.status = 'running';
  renderToolboxPanel();
  try {
    const resp = await apiPost('/api/tool/fix-diagrams', {
      api_key: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      custom_url: settings.customUrl || '',
      answer_json: solveOut,
      render_result: state.output || undefined,
      feedback: state.output?.validation ? '请根据验错结果修正' : '',
      issues: state.output?.validation?.issues,
      report_excerpt: agentPrimaryFullText || '',
    });
    const data = resp.data || resp;
    const merged = data.answer_json || solveOut;
    toolState.solve.output = merged;
    toolState.solve.input = JSON.stringify(merged.parsed || merged, null, 2);
    state.input = JSON.stringify(data.diagrams || merged.parsed?.diagrams || [], null, 2);
    state.status = 'stale';
    state.outputText = `已修复 diagrams（变更字段: ${(data.changed_fields || []).join(', ')}）\n请重新点击「执行」渲染。`;
    markDownstreamStale('solve');
    showToast('图表 JSON 已修复，请重新渲染', 'success');
  } catch (err) {
    state.status = 'failed';
    state.outputText = err.message;
    showToast('修复失败: ' + err.message, 'error');
  }
  renderToolboxPanel();
  saveToolboxState();
}

function updateToolboxOutputBar() {
  const bar = document.getElementById('toolboxOutputBar');
  if (!bar) return;
  const hasFill = toolState.fill.status === 'success';
  const hasSolve = toolState.solve.status === 'success';
  bar.style.display = (hasFill || hasSolve) ? 'flex' : 'none';
}

function copyToolOutput(toolId) {
  const state = toolState[toolId];
  if (!state?.outputText) {
    showToast('没有可复制的输出', 'info');
    return;
  }
  navigator.clipboard.writeText(state.outputText).then(() => {
    showToast('已复制到剪贴板', 'success');
  }).catch(() => {
    showToast('复制失败', 'error');
  });
}

function toolboxCopyLastJson() {
  const order = ['fill', 'revise', 'verify', 'solve'];
  for (const tid of order) {
    const state = toolState[tid];
    if (state?.outputText) {
      navigator.clipboard.writeText(state.outputText).then(() => {
        showToast('已复制 ' + (TOOL_DEFS.find((t) => t.id === tid)?.label || tid) + ' 的输出', 'success');
      });
      return;
    }
  }
  showToast('没有可复制的输出', 'info');
}

async function toolboxDownloadOutput() {
  const fillOut = toolState.fill.output;
  if (!fillOut?.output_path) {
    showToast('请先执行 #6 填写报告', 'error');
    return;
  }
  // Trigger download via save dialog
  const result = await window.electronAPI.saveFileDialog(fillOut.file_name || '实验报告_已完成.docx');
  if (result.canceled) return;
  try {
    // Re-fill with output_path set
    const solveOut = toolState.solve.output || {};
    const answers = [{ ...solveOut }];
    let fillPayload = {
      answer_json: answers,
      output_path: result.filePath,
      file_name: fillOut.file_name || 'report.docx',
      metadata: parsedMetadata,
    };
    if (uploadedDocuments.length && uploadedDocuments[0].path) {
      const doc = uploadedDocuments[0];
      fillPayload.file_data = await window.electronAPI.readFileBase64(doc.path);
      fillPayload.file_name = doc.fileName;
      fillPayload.source_format = doc.docFormat || 'docx';
    }
    await apiPost('/api/tool/fill', fillPayload);
    showToast('报告已保存！', 'success');
  } catch (err) {
    showToast('保存失败: ' + err.message, 'error');
  }
}

function resetToolboxState() {
  TOOL_DEFS.forEach((t) => { toolState[t.id] = makeToolState(); });
  clearToolboxStorage();
  const bar = document.getElementById('toolboxOutputBar');
  if (bar) bar.style.display = 'none';
  renderToolboxPanel();
  updateChainButtonState();
}

// ============================
// Agent 标准模式（计划 → 执行 + SSE）
// ============================

function resetAgentPlanState(options = {}) {
  const keepDocuments = options.keepDocuments === true;
  const keepTemplate = options.keepTemplate === true;
  agentPlanSteps = [];
  agentPlanFingerprint = '';
  agentDocumentIds = [];
  agentSectionsConfig = {};
  if (!keepDocuments) {
    parsedMetadata = {};
    // Clear resolved roles on all documents
    uploadedDocuments.forEach((d) => {
      d.resolvedRole = null;
      d.resolvedLayout = null;
      d.fillBodyLen = 0;
      d.assignmentExcerptLen = 0;
      d.splitAtHeading = '';
    });
    const bar = document.getElementById('docSummaryBar');
    if (bar) bar.remove();
  }
  agentFillTarget = null;
  if (!keepDocuments) pairedDocxPath = null;
  agentModuleResults = null;
  agentConfirmedSteps = [];
  agentSplitIdx = null;
  if (!keepDocuments) {
    agentDocLayout = null;
    agentSplitAtHeading = '';
    agentSplitCandidates = [];
    agentPrimaryFullText = '';
    agentAssignmentText = '';
    agentAwaitingSplitConfirm = false;
    hideSplitPreview();
    // DA4: clear section detection state
    agentSectionsDetected = [];
    agentSectionMap = {};
    agentFillHints = {};
    agentReportLayout = '';
    agentTableMap = [];
    agentUserSemanticOverrides = {};
    hideSectionsDetectCard();
    hideTableMapPreview();
  }
  agentSplitDirty = false;
  agentClarifications = [];
  agentClarificationAnswers = {};
  agentPlanStale = false;
  agentExecutionMode = false;
  agentPlanStepsSnapshot = '';
  agentPlanBaselineSteps = [];
  agentPlanFeedback = null;
  agentReplanNotified = false;
  agentDecisionLog = [];
  clearAgentThoughtLog();
  agentRunFinished = false;
  agentThoughtCollapsed = true;
  agentDirtyModules = [];
  agentFillSections = null;
  if (!keepTemplate) {
    agentFormatSpec = null;
    agentAnswerTemplateText = '';
    agentTemplatePending = null;
    agentTemplateConfirmed = false;
    clearAnswerTemplate();
  }
  disconnectAgentSSE();
  const panel = document.getElementById('agentPlanPanel');
  if (panel) panel.style.display = 'none';
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;
  const stale = document.getElementById('agentStaleBanner');
  if (stale) stale.style.display = 'none';
}

function markAgentPlanStale() {
  if (!agentPlanSteps.length) return;
  agentPlanStale = true;
  const stale = document.getElementById('agentStaleBanner');
  if (stale) stale.style.display = 'block';
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;
}

function getRunMode() {
  const checked = document.querySelector('input[name="runMode"]:checked');
  return checked?.value || 'standard';
}

function getOutputMode() {
  const checked = document.querySelector('input[name="outputMode"]:checked');
  return checked?.value || agentOutputMode;
}

function onOutputModeChange() {
  agentOutputMode = getOutputMode();
}

function updateOutputModeUI() {
  const deliverableRadio = document.querySelector('input[name="outputMode"][value="deliverable"]');
  const fillOriginalRadio = document.querySelector('input[name="outputMode"][value="fill_original"]');
  if (!deliverableRadio) return;

  if (!agentFillTarget && fillOriginalRadio) {
    fillOriginalRadio.disabled = true;
    fillOriginalRadio.parentElement?.classList.add('disabled');
    if (fillOriginalRadio.checked) {
      deliverableRadio.checked = true;
      agentOutputMode = 'deliverable';
    }
  } else if (fillOriginalRadio) {
    fillOriginalRadio.disabled = false;
    fillOriginalRadio.parentElement?.classList.remove('disabled');
  }

  const checked = document.querySelector('input[name="outputMode"]:checked');
  if (checked) agentOutputMode = checked.value;
  updateExportActionBarVisibility();
}

function updateExportActionBarVisibility() {
  const bar = document.getElementById('exportActionBar');
  const advanced = document.getElementById('exportAdvancedFill');
  const hint = document.getElementById('exportActionHint');
  if (!bar) return;
  if (isContentOnlyOutputMode()) {
    if (hint) {
      hint.textContent = '💡 答案已生成，请从上方工作区复制分节内容；也可在代码面板试跑';
    }
    if (advanced) advanced.style.display = '';
  } else {
    if (hint) {
      hint.textContent = '💡 高级填表模式：建议先运行代码并截图，再生成报告';
    }
    if (advanced) advanced.open = true;
  }
}

function onRunModeChange() {
  const mode = getRunMode();
  persistSettingsPatch({ runMode: mode });
  if (mode === 'deep') {
    showToast('深度模式：理解+审稿+预检，约 3～4 次 API 调用', 'info');
  } else if (mode === 'react') {
    showToast('ReAct 模式：AI 自主决策工具调用，自动循环执行', 'info');
  }
}

function syncRunModeUI(runMode) {
  const val = runMode || 'standard';
  document.querySelectorAll('input[name="runMode"]').forEach((el) => {
    if (el.value === val) el.checked = true;
  });
}

function collectSolveOptions(settings) {
  const solveLangEl = document.getElementById('solveLang');
  const includeCodeEl = document.getElementById('includeCodeCheck');
  const includeUmlEl = document.getElementById('includeUmlCheck');
  if (solveLangEl) settings.codeLanguage = solveLangEl.value;
  settings.includeCode = includeCodeEl ? includeCodeEl.checked : true;
  settings.includeUml = includeUmlEl ? includeUmlEl.checked : false;
  return settings;
}

function getAgentApiSettings() {
  const settings = collectSolveOptions(loadSettings());
  return {
    api_key: settings.apiKey,
    provider: settings.provider,
    model: settings.model,
    custom_url: settings.customUrl || '',
    run_mode: getRunMode(),
    include_uml: settings.includeUml === true,
    profile: {
      default_language: settings.codeLanguage || 'python',
      screenshot_style: 'ide',
      prefer_uml: settings.includeUml === true,
      optimize_plan_from_usage: settings.optimizePlanFromUsage === true,
    },
    sections_config: collectSectionsConfigForApi(),
    user_constraints: getUserConstraints(),
    provenance_custom_label: getProvenanceCustomLabel() || undefined,
  };
}

function getSectionContextPayload() {
  const payload = {};
  if ((agentSectionsDetected || []).length) {
    payload.sections_detected = agentSectionsDetected;
  }
  if (agentSectionMap && Object.keys(agentSectionMap).length) {
    payload.section_map = agentSectionMap;
  }
  if (agentUserSemanticOverrides && Object.keys(agentUserSemanticOverrides).length) {
    payload.semantic_overrides = agentUserSemanticOverrides;
  }
  if (agentReportLayout) {
    payload.report_layout = agentReportLayout;
  }
  if (agentFillHints && Object.keys(agentFillHints).length) {
    payload.fill_hints = agentFillHints;
  }
  return payload;
}

async function buildAgentDocumentPayload() {
  if (agentDocumentIds.length && !agentSplitDirty) {
    return { document_ids: agentDocumentIds };
  }
  if (uploadedDocuments.length) {
    return buildDocumentsPayload();
  }
  if (!currentFile || currentFile === 'demo') {
    throw new Error('演示模式不支持 Agent 计划，请上传真实报告');
  }
  const fileData = await window.electronAPI.readFileBase64(currentFile);
  const fileName = currentFile.split(/[\\/]/).pop();
  const lower = fileName.toLowerCase();

  if (pairedDocxPath && lower.endsWith('.pdf')) {
    const docxData = await window.electronAPI.readFileBase64(pairedDocxPath);
    const docxName = pairedDocxPath.split(/[\\/]/).pop();
    return {
      documents: [
        { id: 'd-pdf', role: 'fill_target', file_data: fileData, file_name: fileName },
        { id: 'd-tpl', role: 'fill_template', file_data: docxData, file_name: docxName },
      ],
    };
  }

  return { file_data: fileData, file_name: fileName };
}

async function generateAgentPlan() {
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  if (!parsedQuestions.length) {
    showToast('请先上传并解析报告', 'error');
    return;
  }
  if (!hasCompletedOnboarding()) {
    await showOnboardingModal();
  }

  const btn = document.getElementById('generatePlanBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 生成计划中…';
  }

  try {
    const doc = await buildAgentDocumentPayload();
    const resp = await apiPost('/api/agent/plan', {
      ...getAgentApiSettings(),
      ...doc,
      output_mode: getOutputMode(),
      format_spec: agentFormatSpec || undefined,
      split_idx: agentSplitIdx,
    });

    agentPlanSteps = resp.steps || [];
    agentPlanFingerprint = resp.plan_fingerprint || '';
    agentUnderstand = resp.understand || null;
    agentDocumentIds = resp.document_ids || [];
    agentClarifications = resp.clarifications || [];
    agentSplitIdx = resp.split_idx ?? null;
    agentPlanStale = false;
    agentClarificationAnswers = {};
    if (resp.format_spec) agentFormatSpec = resp.format_spec;
    agentAnswerTemplateText = resp.format_spec?.template_full_text
      || resp.format_spec?.full_text
      || agentAnswerTemplateText
      || '';

    const stale = document.getElementById('agentStaleBanner');
    if (stale) stale.style.display = 'none';

    renderAgentPlanPanel(resp);
    syncAgentPlanBaseline();
    agentPlanStepsSnapshot = snapshotPlanChecks(agentPlanSteps);
    const execBtn = document.getElementById('executePlanBtn');
    if (execBtn) execBtn.disabled = !agentPlanSteps.length;

    const clarHint = agentClarifications.length
      ? `，${agentClarifications.length} 项待确认`
      : '';
    showToast(`计划已生成（${agentPlanSteps.length} 步）${clarHint}`, 'success');
  } catch (err) {
    showToast('生成计划失败: ' + err.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '📋 生成计划';
    }
  }
}

function renderAgentPlanPanel(planMeta) {
  const panel = document.getElementById('agentPlanPanel');
  const list = document.getElementById('planStepsList');
  const meta = document.getElementById('agentPlanMeta');
  const summaryEl = document.getElementById('agentSectionsSummary');
  if (!panel || !list) return;

  panel.style.display = 'block';
  if (summaryEl) {
    const html = buildSectionsSummaryHtml();
    summaryEl.innerHTML = html;
    summaryEl.style.display = html ? 'block' : 'none';
  }
  if (meta) {
    const fpShort = agentPlanFingerprint ? agentPlanFingerprint.slice(0, 20) + '…' : '';
    const u = planMeta?.understand?.summary || agentUnderstand?.summary;
    const modeHint = getRunMode() === 'deep' && u ? ` · ${String(u).slice(0, 60)}` : '';
    meta.textContent = fpShort ? `指纹 ${fpShort}${modeHint}` : (modeHint || '');
  }

  list.innerHTML = '';
  agentPlanSteps.forEach((step, i) => {
    const mod = step.module || 'unknown';
    const checked = step.default_checked !== false
      && !(step.source === 'profile' && step.confidence === 'low');
    const conf = step.confidence || 'high';
    const evidence = step.evidence ? String(step.evidence).slice(0, 400) : '';
    const item = document.createElement('label');
    item.className = 'plan-step-item';
    item.innerHTML = `
      <input type="checkbox" data-plan-idx="${i}" ${checked ? 'checked' : ''}>
      <div class="plan-step-body">
        <div class="plan-step-module">${AGENT_MODULE_LABELS[mod] || mod}</div>
        <div class="plan-step-reason">${escapeHtml(step.reason || '')}</div>
        ${evidence ? `<details class="plan-step-evidence"><summary>依据原文</summary><div class="plan-step-evidence-text">${escapeHtml(evidence)}</div></details>` : ''}
        <div class="plan-step-confidence">置信度: ${conf}${step.source ? ` · 来源: ${escapeHtml(step.source)}` : ''}</div>
      </div>
    `;
    item.querySelector('input').addEventListener('change', (e) => {
      agentPlanSteps[i].default_checked = e.target.checked;
      const execBtn = document.getElementById('executePlanBtn');
      if (execBtn && !agentPlanStale) execBtn.disabled = false;
    });
    list.appendChild(item);
  });

  renderClarificationsPanel();
}

function renderClarificationsPanel() {
  const wrap = document.getElementById('clarificationsPanel');
  if (!wrap) return;

  if (!agentClarifications.length) {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    return;
  }

  wrap.style.display = 'flex';
  wrap.innerHTML = '<div style="font-size:13px;font-weight:600">待确认项</div>';

  agentClarifications.forEach((c) => {
    const card = document.createElement('div');
    card.className = 'clarification-card';
    const opts = (c.options || []).map((o) => {
      const label = typeof o === 'string' ? o : (o.label || '');
      return `<option value="${escapeHtml(label)}">${escapeHtml(label)}</option>`;
    }).join('');
    const defaultVal = c.default || '';
    card.innerHTML = `
      <label>${escapeHtml(c.question || '')}</label>
      <select data-clarify-id="${escapeHtml(c.id || '')}">
        ${opts}
      </select>
    `;
    const sel = card.querySelector('select');
    if (defaultVal) sel.value = defaultVal;
    sel.addEventListener('change', () => markAgentPlanStale());
    wrap.appendChild(card);
  });

  const applyBtn = document.createElement('button');
  applyBtn.className = 'btn-secondary';
  applyBtn.textContent = '应用确认并更新计划';
  applyBtn.onclick = submitClarifications;
  wrap.appendChild(applyBtn);
}

async function submitClarifications() {
  const settings = loadSettings();
  if (!settings.apiKey) return;

  const answers = {};
  document.querySelectorAll('[data-clarify-id]').forEach((sel) => {
    const id = sel.getAttribute('data-clarify-id');
    if (id) answers[id] = sel.value;
  });
  agentClarificationAnswers = answers;

  try {
    const resp = await apiPost('/api/agent/plan/clarify', {
      ...getAgentApiSettings(),
      document_ids: agentDocumentIds,
      steps: agentPlanSteps,
      plan_fingerprint: agentPlanFingerprint,
      clarification_answers: answers,
      sections_config: collectSectionsConfigForApi(),
      split_idx: agentSplitIdx,
      format_spec: agentFormatSpec || undefined,
    });
    agentPlanSteps = resp.steps || agentPlanSteps;
    agentPlanFingerprint = resp.plan_fingerprint || agentPlanFingerprint;
    agentClarifications = resp.clarifications || [];
    agentPlanStale = false;
    syncAgentPlanBaseline();
    agentPlanStepsSnapshot = snapshotPlanChecks(agentPlanSteps);
    renderAgentPlanPanel();
    const execBtn = document.getElementById('executePlanBtn');
    if (execBtn) execBtn.disabled = !agentPlanSteps.length;
    showToast('计划已根据确认项更新', 'success');
  } catch (err) {
    showToast('更新计划失败: ' + err.message, 'error');
  }
}

function snapshotPlanChecks(steps) {
  return JSON.stringify(
    (steps || []).map((s) => ({ m: s.module, c: s.default_checked !== false }))
  );
}

function clonePlanStepsForBaseline(steps) {
  return (steps || []).map((s) => ({
    module: s.module,
    params: s.params ? { ...s.params } : {},
    reason: s.reason,
    confidence: s.confidence,
    default_checked: s.default_checked,
    source: s.source,
    evidence: s.evidence,
  }));
}

function syncAgentPlanBaseline() {
  agentPlanBaselineSteps = clonePlanStepsForBaseline(agentPlanSteps);
}

async function postAgentPlanFeedback(confirmedSteps, fingerprint) {
  try {
    const resp = await apiPost('/api/agent/plan/feedback', {
      plan_fingerprint: fingerprint || agentPlanFingerprint,
      baseline_steps: agentPlanBaselineSteps,
      steps: confirmedSteps,
      document_ids: agentDocumentIds,
      apply_to_profile: loadSettings().optimizePlanFromUsage === true,
      profile: getAgentApiSettings().profile,
    });
    if (resp && resp.history) {
      agentPlanFeedback = resp.history;
    }
    if (resp && resp.decision_log_entry) {
      agentDecisionLog.push(resp.decision_log_entry);
    }
    return resp;
  } catch (err) {
    console.warn('plan feedback:', err);
    return null;
  }
}

function getConfirmedPlanSteps() {
  return agentPlanSteps.map((s) => ({
    module: s.module,
    params: s.params || {},
    reason: s.reason,
    confidence: s.confidence,
    default_checked: s.default_checked !== false,
  }));
}

async function executeAgentPlan() {
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  if (agentPlanStale) {
    showToast('计划已过期，请重新生成计划', 'error');
    return;
  }
  if (!agentPlanSteps.length) {
    showToast('请先生成计划', 'error');
    return;
  }

  const steps = getConfirmedPlanSteps();
  const willFillReport = !isContentOnlyOutputMode() && steps.some(
    (s) => s.module === 'fill_report' && s.default_checked !== false
  );
  if (willFillReport && parsedQuestions.length > 0) {
    syncAgentSectionsConfigFromUI();
    const isLab = parsedQuestions[0]?.type === 'lab_report';
    const ok = await confirmBeforeFillReport(
      collectSectionsConfigForApi(),
      getDynamicSectionRowDefs(),
      FILL_MODE_OPTIONS,
      isLab
    );
    if (!ok) return;
  }

  let fingerprint = agentPlanFingerprint;
  if (snapshotPlanChecks(steps) !== agentPlanStepsSnapshot) {
    fingerprint = '';
  }
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;

  agentExecutionMode = true;
  agentRunFinished = false;
  agentThoughtCollapsed = true;
  agentReplanNotified = false;
  solvedAnswers = [];
  goToStep(3);
  updateStepBar(3);

  const titleEl = document.getElementById('step3Title');
  if (titleEl) titleEl.textContent = '📋 正在生成答案…';
  const dlvWs = document.getElementById('deliverableWorkspace');
  if (dlvWs) dlvWs.style.display = 'none';
  currentDeliverable = null;
  document.getElementById('agentProgressWrap').style.display = 'block';
  document.getElementById('cancelAgentRunBtn').style.display = 'inline-flex';
  const thoughtBody = document.getElementById('agentThoughtBody');
  const verifyWrap = document.getElementById('agentVerifyWrap');
  if (thoughtBody) thoughtBody.innerHTML = '';
  updateThoughtSidebarBadge();
  if (verifyWrap) verifyWrap.style.display = 'none';
  agentVerificationReport = null;
  agentModuleResults = null;
  agentConfirmedSteps = steps;
  agentDecisionLog = [];
  clearAgentThoughtLog();
  lastSessionRunMode = getRunMode();
  updateThoughtSidebarVisibility();
  updateAgentProgress(0, steps.length, '正在启动…');

  if (getRunMode() === 'react') {
    renderReactProgressList(steps);
  } else {
    renderAgentProgressList(steps);
  }

  try {
    await postAgentPlanFeedback(steps, fingerprint);
    const resp = await apiPost('/api/agent/run', {
      ...getAgentApiSettings(),
      document_ids: agentDocumentIds,
      steps,
      plan_fingerprint: fingerprint,
      output_mode: getOutputMode(),
      auto_remediate: loadSettings().autoRemediate === true,
      sections_config: collectSectionsConfigForApi(),
      split_idx: agentSplitIdx,
      format_spec: agentFormatSpec || undefined,
      understand: agentUnderstand,
      fallback_on_failure: true,
      ...getSectionContextPayload(),
      ...getTerminalConfig(),
      code_language: settings.codeLanguage,
    });

    agentRunId = resp.run_id;
    connectAgentSSE(agentRunId, steps.length);
  } catch (err) {
    agentExecutionMode = false;
    if (execBtn) execBtn.disabled = false;
    if (err.message && err.message.includes('计划已过期')) {
      markAgentPlanStale();
    }
    showToast('启动执行失败: ' + err.message, 'error');
    goToStep(2);
  }
}

function renderAgentProgressList(steps) {
  const list = document.getElementById('solvingList');
  list.innerHTML = '';
  steps.forEach((step, i) => {
    const mod = step.module || '';
    const item = document.createElement('div');
    item.className = 'solving-item';
    item.id = `agent-step-${mod}`;
    item.dataset.module = mod;
    const willRun = step.default_checked !== false;
    item.innerHTML = `
      <div class="solving-status">${willRun ? '⏳' : '⏭'}</div>
      <div class="solving-info">
        <div class="solving-title">${AGENT_MODULE_LABELS[mod] || mod}</div>
        <div class="solving-answer" id="agent-detail-${mod}">${willRun ? '等待执行…' : '已跳过（未勾选）'}</div>
      </div>
    `;
    if (!willRun) item.classList.add('skipped');
    list.appendChild(item);
  });
}

function renderReactProgressList(steps) {
  const list = document.getElementById('solvingList');
  if (!list) return;
  list.innerHTML = '';
  const item = document.createElement('div');
  item.className = 'solving-item solving';
  item.id = 'agent-step-react';
  item.innerHTML = '<div class="solving-status">🔄</div>' +
    '<div class="solving-info">' +
      '<div class="solving-title">ReAct 自主执行</div>' +
      '<div class="solving-answer" id="agent-detail-react">AI 正在决策下一步…</div>' +
    '</div>';
  list.appendChild(item);
  steps.forEach(function(step) {
    var mod = step.module || '';
    var refItem = document.createElement('div');
    refItem.className = 'solving-item';
    refItem.style.opacity = '0.6';
    refItem.innerHTML = '<div class="solving-status">⬜</div>' +
      '<div class="solving-info"><div class="solving-title">' + (AGENT_MODULE_LABELS[mod] || mod) + '</div></div>';
    list.appendChild(refItem);
  });
}

function updateAgentProgress(done, total, label) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const fill = document.getElementById('agentProgressFill');
  const pctEl = document.getElementById('agentProgressPct');
  const lbl = document.getElementById('agentProgressLabel');
  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (lbl) lbl.textContent = label || `进度 ${done}/${total}`;
}

function connectAgentSSE(runId, totalSteps) {
  disconnectAgentSSE();
  const url = `http://localhost:${serverPort}/api/agent/events?run_id=${encodeURIComponent(runId)}`;
  const es = new EventSource(url);
  agentEventSource = es;
  let completed = 0;

  es.onmessage = (ev) => {
    let data;
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    handleAgentSSEEvent(data, {
      totalSteps,
      onProgress: (n, label) => updateAgentProgress(n, totalSteps, label),
      bumpDone: () => {
        completed += 1;
        updateAgentProgress(completed, totalSteps, '执行中…');
      },
    });
  };

  es.onerror = () => {
    if (agentRunId) {
      showToast('SSE 连接中断，请查看后端日志', 'error');
    }
    disconnectAgentSSE();
  };
}

function disconnectAgentSSE() {
  if (agentEventSource) {
    agentEventSource.close();
    agentEventSource = null;
  }
}

function handleAgentSSEEvent(data, ctx) {
  const type = data.type;

  if (type === 'progress') {
    const mod = data.module || '';
    const el = document.getElementById(`agent-step-${mod}`);
    const detail = document.getElementById(`agent-detail-${mod}`);
    const statusMap = {
      running: { icon: '🔄', cls: 'solving', text: '执行中…' },
      done: { icon: '✅', cls: 'done', text: '完成' },
      failed: { icon: '❌', cls: 'error', text: data.error || '失败' },
      skipped: { icon: '⏭', cls: 'skipped', text: '已跳过' },
    };
    const st = statusMap[data.status] || statusMap.running;
    if (el) {
      el.classList.remove('solving', 'done', 'error', 'skipped', 'degraded');
      el.classList.add(st.cls);
      if (data.error_meta?.degraded) el.classList.add('degraded');
      const icon = el.querySelector('.solving-status');
      if (icon) icon.textContent = st.icon;
    }
    if (detail) {
      let detailHtml = st.text;
      const meta = data.error_meta || {};
      if (data.status === 'failed' && meta.category) {
        const catLabels = {
          compile_error: '编译错误', missing_module: '缺少模块',
          timeout_blocking: '运行超时(阻塞)', timeout_slow: '运行超时(慢)',
          runtime_exception: '运行异常',
        };
        const catLabel = catLabels[meta.category] || meta.category;
        detailHtml += ` <span class="solving-error-badge ${meta.category}">${escapeHtml(catLabel)}</span>`;
        // Show toast for preflight-blocked code (JSP, web server, interactive)
        if (mod === 'run_code' && meta.category !== 'runtime_exception') {
          const prLabels = {
            compile_error: '代码编译失败，将在修复后重试',
            timeout_blocking: '代码包含阻塞模式，将跳过执行并尝试修复',
          };
          const label = prLabels[meta.category];
          if (label) showToast(label, 'warning');
        }
      }
      if (meta.degraded) {
        detailHtml += ' <span class="solving-degraded-badge">已降级为文本输出</span>';
        detailHtml += `<div class="solving-degraded-reason">${escapeHtml(meta.degraded_reason || '')}</div>`;
      }
      detail.innerHTML = detailHtml;
    }
    if (data.status === 'done' || data.status === 'failed' || data.status === 'skipped') {
      ctx.bumpDone();
    }
    return;
  }

  if (type === 'plan_updated') {
    agentPlanSteps = data.steps || agentPlanSteps;
    agentPlanFingerprint = data.plan_fingerprint || agentPlanFingerprint;
    syncAgentPlanBaseline();
    agentPlanStepsSnapshot = snapshotPlanChecks(agentPlanSteps);
    const label = document.getElementById('agentProgressLabel');
    if (label) {
      label.textContent = '计划已自动调整，继续执行剩余步骤…';
    }
    if (!agentReplanNotified) {
      agentReplanNotified = true;
      showToast('计划已自动调整（增量 replan）', 'info');
    }
    renderAgentProgressList(getConfirmedPlanSteps());
    return;
  }

  if (type === 'decision') {
    const entry = {
      timestamp: data.timestamp,
      agent: data.agent,
      decision: data.decision,
      target: data.target,
      reason: data.reason,
      evidence: data.evidence,
      fingerprint: data.fingerprint,
      overridden: data.overridden,
    };
    agentDecisionLog.push(entry);
    recordAgentThought({ type: 'decision', phase: '决策', text: formatDecisionLogLine(entry) });
    return;
  }

  if (type === 'thought') {
    appendAgentThought(data.phase || '思考', data.text || '');
    recordAgentThought({ type: 'thought', phase: data.phase || '思考', text: data.text || '' });
    return;
  }

  if (type === 'preflight') {
    const ok = data.ok ? '通过' : '未通过';
    const preflightText = `预检${ok}: ${(data.checks || []).map((c) => c.message).join('; ')}`;
    appendAgentThought('预检', preflightText);
    recordAgentThought({ type: 'preflight', phase: '预检', text: preflightText });
    // Show toast warning for code patterns that need fixing
    if (!data.exec_ok && data.exec_pattern && data.exec_pattern !== 'script') {
      const patternLabels = {
        jsp_template: '代码混合了 JSP/HTML，无法作为纯 Java 编译',
        web_server: '代码包含 Web 服务器，将跳过执行并尝试修复',
        interactive: '代码需要交互输入，将在修复后重试',
        possible_infinite: '代码可能包含死循环',
        emoji_in_code: '代码含 emoji，Windows 无法编码，将尝试修复',
      };
      showToast(patternLabels[data.exec_pattern] || data.exec_message || '代码需修复', 'warning');
    }
    return;
  }

  if (type === 'reflect') {
    const issues = data.issues || [];
    const reflectText = data.pass
      ? '审稿通过'
      : `审稿意见 ${issues.length} 条: ${issues.map((i) => i.message).join('; ')}`;
    appendAgentThought('审稿', reflectText);
    recordAgentThought({ type: 'reflect', phase: '审稿', text: reflectText });
    return;
  }

  if (type === 'react_thinking') {
    const body = document.getElementById('agentThoughtBody');
    if (body) {
      const el = document.createElement('div');
      el.className = 'react-cycle-thinking';
      el.innerHTML = '<span class="react-thinking-dot"></span> 第 ' + (data.round || '?') + ' 轮思考中…';
      body.appendChild(el);
      body.scrollTop = body.scrollHeight;
    }
    return;
  }

  if (type === 'react_cycle') {
    const body = document.getElementById('agentThoughtBody');
    if (body) {
      const thinkingEl = body.querySelector('.react-cycle-thinking:last-child');
      if (thinkingEl) thinkingEl.remove();
      const block = document.createElement('div');
      block.className = 'agent-thought-block react-cycle';
      const statusIcon = data.result_ok ? 'OK' : 'FAIL';
      const statusClass = data.result_ok ? 'react-ok' : 'react-fail';
      block.innerHTML =
        '<div class="react-cycle-header">' +
          '<span class="react-cycle-round">第 ' + (data.round || 0) + '/' + (data.max_rounds || 12) + ' 轮</span>' +
          '<span class="react-cycle-action ' + statusClass + '">' + escapeHtml(data.action) + ' ' + statusIcon + '</span>' +
        '</div>' +
        '<div class="react-cycle-thought"><strong>思考</strong><pre>' + escapeHtml(data.thought || '') + '</pre></div>' +
        '<div class="react-cycle-result"><strong>结果</strong><pre>' + escapeHtml(data.result_summary || '') + '</pre></div>';
      body.appendChild(block);
      body.scrollTop = body.scrollHeight;
    }
    recordAgentThought({
      type: 'react_cycle',
      round: data.round,
      max_rounds: data.max_rounds,
      thought: data.thought || '',
      action: data.action || '',
      result_ok: data.result_ok,
      result_summary: data.result_summary || '',
    });
    updateThoughtSidebarVisibility();
    return;
  }

  if (type === 'verification') {
    agentVerificationReport = data;
    renderVerificationPanel(data);
    return;
  }

  if (type === 'error') {
    showToast(data.error || '执行出错', 'error');
    return;
  }

  if (type === 'cancelled') {
    showToast('已取消执行', 'info');
    finishAgentRunUI(false);
    return;
  }

  if (type === 'done') {
    if (data.verification_report) {
      agentVerificationReport = data.verification_report;
      renderVerificationPanel(data.verification_report);
    } else if (data.run_summary && data.run_summary.auto_remediate_rounds) {
      renderVerificationPanel({
        passed: data.run_summary.verify_pass,
        remediated: true,
        remediate_rounds: data.run_summary.auto_remediate_rounds,
        checks: [],
        suggested_actions: [],
      });
    }
    applyAgentRunDone(data);
    finishAgentRunUI(data.ok !== false);
  }
}

function formatDecisionLogLine(entry) {
  const parts = [
    entry.agent || '',
    entry.decision || '',
    entry.target ? `→ ${entry.target}` : '',
  ].filter(Boolean);
  let line = parts.join(' · ');
  if (entry.reason) line += `\n原因: ${entry.reason}`;
  if (entry.evidence) line += `\n依据: ${entry.evidence}`;
  return line;
}

function appendAgentThought(phase, text) {
  const body = document.getElementById('agentThoughtBody');
  if (!body || !text) return;
  updateThoughtSidebarVisibility();
  const block = document.createElement('div');
  block.className = 'agent-thought-block';
  block.innerHTML = `<strong>${escapeHtml(phase)}</strong><pre>${escapeHtml(text)}</pre>`;
  body.appendChild(block);
  body.scrollTop = body.scrollHeight;
  updateThoughtSidebarBadge();
}

function getReviseScopeFromUI() {
  const checked = Array.from(document.querySelectorAll('input[name="reviseScope"]:checked'))
    .map((el) => el.value);
  if (!checked.length) return ['full'];
  const mapped = checked.map((id) => (id === 'screenshots' ? 'result' : id));
  return [...new Set(mapped)];
}

function setReviseScopeChecks(scopeList) {
  const scopes = new Set(scopeList || []);
  document.querySelectorAll('input[name="reviseScope"]').forEach((el) => {
    el.checked = scopes.has(el.value)
      || (el.value === 'screenshots' && scopes.has('result'))
      || (scopes.has('full'));
  });
}

function updateAgentVersionUI() {
  const row = document.getElementById('agentVersionRow');
  const sel = document.getElementById('agentVersionSelect');
  const versions = solvedAnswers[0]?.versions || [];
  if (!row || !sel) return;
  if (!versions.length) {
    row.style.display = 'none';
    return;
  }
  row.style.display = 'flex';
  sel.innerHTML = versions.map((v) =>
    `<option value="${v.v}">v${v.v} · ${escapeHtml((v.feedback || '').slice(0, 40))}</option>`
  ).join('');
}

function restoreAgentVersion() {
  const sel = document.getElementById('agentVersionSelect');
  const vNum = parseInt(sel?.value || '', 10);
  const versions = solvedAnswers[0]?.versions || [];
  const hit = versions.find((v) => v.v === vNum);
  if (!hit?.parsed) {
    showToast('未找到可恢复的版本', 'error');
    return;
  }
  solvedAnswers[0].parsed = { ...hit.parsed };
  solvedAnswers[0].code = hit.parsed.code || solvedAnswers[0].code;
  showToast(`已恢复到 v${vNum}`, 'success');
  runAgentVerify();
  onSolveComplete(collectSolveOptions(loadSettings()));
}

function renderVerificationPanel(report) {
  const wrap = document.getElementById('agentVerifyWrap');
  const list = document.getElementById('agentVerifyList');
  const fixes = document.getElementById('agentVerifyFixes');
  if (!wrap || !list || !report) return;
  wrap.style.display = 'block';
  if (solvedAnswers[0]) solvedAnswers[0].verification_report = report;
  const checks = report.checks || [];
  list.innerHTML = checks
    .map((c) => {
      const isWarn = !c.ok && VERIFY_WARN_IDS.has(c.id);
      const cls = c.ok ? 'verify-ok' : (isWarn ? 'verify-warn' : 'verify-fail');
      const label = VERIFY_CHECK_LABELS[c.id] || c.id;
      const icon = c.ok ? '✓' : (isWarn ? '⚠' : '✗');
      return `<li class="${cls}">${icon} ${escapeHtml(label)}：${escapeHtml(c.message || '')}</li>`;
    })
    .join('');
  const actions = report.suggested_actions || [];
  const hint = document.getElementById('agentVerifyActions');
  const hasConstraintFail = checks.some((c) =>
    !c.ok && (c.id === 'constraint_present' || c.id === 'constraint_position')
  );
  if (hint) {
    const labels = actions.map((a) => VERIFY_ACTION_LABELS[a] || a);
    let text = labels.length
      ? `建议操作：${labels.join('、')}`
      : (report.passed ? '校验通过，可生成报告' : '存在需处理项，可修订或回分节调整要求');
    if (hasConstraintFail) text += ' · 可回 Step2 按老师要求补全';
    if (report.remediated && report.remediate_rounds) {
      text += ` · 已自动修复 ${report.remediate_rounds} 轮`;
    }
    hint.textContent = text;
  }
  if (fixes) {
    fixes.innerHTML = '';
    const autoActions = [...new Set(
      actions.filter(Boolean).concat(
        checks.filter((c) => !c.ok && c.auto_fix).map((c) => c.auto_fix)
      )
    )];
    autoActions.forEach((action) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-secondary btn-sm';
      btn.textContent = VERIFY_ACTION_LABELS[action] || action;
      btn.onclick = () => applyVerifySuggestedAction(action);
      fixes.appendChild(btn);
    });
    if (hasConstraintFail) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-secondary btn-sm';
      btn.textContent = '回分节补全要求';
      btn.onclick = () => goToStep(2);
      fixes.appendChild(btn);
    }
    (report.rerun_modules || []).forEach((mod) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'btn-ghost btn-sm';
      btn.textContent = `重跑 ${AGENT_MODULE_LABELS[mod] || mod}`;
      btn.onclick = () => runAgentPartialRerun([mod]);
      fixes.appendChild(btn);
    });
  }
}

async function runAgentVerify() {
  if (!agentModuleResults && !solvedAnswers[0]?.parsed) {
    showToast('请先完成 Agent 执行', 'error');
    return;
  }
  const settings = getAgentApiSettings();
  try {
    const ctx = {
      module_results: agentModuleResults || {},
      confirmed_steps: agentConfirmedSteps,
      teacher_constraints: {},
      user_content: {},
    };
    const resp = await apiPost('/api/agent/verify', {
      ...settings,
      agent_context: ctx,
      module_results: agentModuleResults,
      steps: agentConfirmedSteps,
      sections_config: collectSectionsConfigForApi(),
      answer_template_text: agentAnswerTemplateText,
      format_spec: agentFormatSpec || undefined,
    });
    agentVerificationReport = resp.verification_report;
    renderVerificationPanel(agentVerificationReport);
    showToast(
      agentVerificationReport?.passed ? '校验通过' : '校验完成，请查看清单',
      agentVerificationReport?.passed ? 'success' : 'warning'
    );
  } catch (err) {
    showToast('校验失败: ' + err.message, 'error');
  }
}

async function applyVerifySuggestedAction(action) {
  if (action === 'fix_code') {
    await requestAgentFixCode('代码运行失败，请修复并保证输出与预期一致');
    return;
  }
  if (action === 'revise_full' || (action && action.startsWith('revise_section'))) {
    if (action === 'revise_full') setReviseScopeChecks(['full']);
    else if (action.includes('result')) setReviseScopeChecks(['result']);
    const feedbackEl = document.getElementById('agentReviseFeedback');
    if (feedbackEl && !feedbackEl.value.trim()) {
      feedbackEl.value = '请根据校验清单修正内容';
    }
    const panel = document.getElementById('agentRevisePanel');
    if (panel) panel.open = true;
    showToast('已选择修订范围，请补充说明后点「按选中范围修订」', 'info');
  }
}

async function requestAgentReviseFull() {
  setReviseScopeChecks(['full']);
  const feedbackEl = document.getElementById('agentReviseFeedback');
  if (feedbackEl && !feedbackEl.value.trim()) {
    feedbackEl.value = '请整体重写，提高质量并符合报告要求';
  }
  await requestAgentRevise(['full']);
}

async function requestAgentFixCode(prefill) {
  setReviseScopeChecks(['code']);
  const feedbackEl = document.getElementById('agentReviseFeedback');
  if (feedbackEl) {
    feedbackEl.value = prefill || feedbackEl.value || '代码无法运行，请修复编译/运行错误';
  }
  await requestAgentRevise(['code'], { rerunModules: ['fix_code', 'run_code', 'screenshot_ide', 'fill_report'] });
}

function openManualEdit() {
  const a = solvedAnswers[0];
  if (!a) { showToast('没有可编辑的解题结果', 'info'); return; }
  const codeFiles = a.code_files || a.parsed?.code_files || [];
  const code = a.code || a.parsed?.code || '';
  const settings = loadSettings();
  const lang = a.language || settings.codeLanguage || 'python';
  if (codeFiles.length) {
    showCodePanel(a, codeFiles, lang, 0, a.main_file);
  } else if (code.trim()) {
    showCodePanel(a, code, lang, 0);
  } else {
    showToast('该题没有代码可编辑', 'info');
    return;
  }
  showToast('可在代码编辑器修改后，点「仅重新填充」或「运行+截图」', 'info');
}

async function refillReportOnly() {
  if (!solvedAnswers.length || !solvedAnswers[0]) {
    showToast('无可填充的解题结果', 'error');
    return;
  }
  syncAgentSectionsConfigFromUI();
  const isLab = parsedQuestions[0]?.type === 'lab_report';
  const ok = await confirmBeforeFillReport(
    collectSectionsConfigForApi(),
    getDynamicSectionRowDefs(),
    FILL_MODE_OPTIONS,
    isLab
  );
  if (!ok) return;
  try {
    const fillPayload = await buildFillReportPayload();
    const resp = await apiPost('/api/fill-report', fillPayload);
    if (resp.output_path) lastOutputPath = resp.output_path;
    showToast('已按当前内容与分节设置重新填充 Word', 'success');
  } catch (err) {
    showToast('填充失败: ' + err.message, 'error');
  }
}

function buildPartialRerunSteps(moduleIds) {
  const want = new Set(moduleIds || []);
  const fromPlan = (agentConfirmedSteps || []).filter(
    (s) => want.has(s.module) && s.default_checked !== false
  );
  if (fromPlan.length) return fromPlan;
  return [...want].map((module) => ({
    module,
    params: {},
    default_checked: true,
    reason: '修订后增量重跑',
  }));
}

async function runAgentPartialRerun(moduleIds) {
  if (!moduleIds?.length) return;
  const settings = loadSettings();
  if (!settings.apiKey) {
    showToast('请先在设置中填写 API Key', 'error');
    return;
  }
  const steps = buildPartialRerunSteps(moduleIds);
  agentExecutionMode = true;
  agentRunFinished = false;
  document.getElementById('agentProgressWrap').style.display = 'block';
  document.getElementById('cancelAgentRunBtn').style.display = 'inline-flex';
  updateThoughtSidebarVisibility();
  renderAgentProgressList(steps);
  updateAgentProgress(0, steps.length, '增量重跑…');
  try {
    const resp = await apiPost('/api/agent/run', {
      ...getAgentApiSettings(),
      document_ids: agentDocumentIds,
      steps,
      plan_fingerprint: '',
      sections_config: collectSectionsConfigForApi(),
      split_idx: agentSplitIdx,
      format_spec: agentFormatSpec || undefined,
      module_results: agentModuleResults,
      dirty_modules: moduleIds,
      fill_sections: agentFillSections,
      fallback_on_failure: false,
      ...getTerminalConfig(),
      code_language: settings.codeLanguage,
    });
    agentRunId = resp.run_id;
    connectAgentSSE(agentRunId, steps.length);
  } catch (err) {
    agentExecutionMode = false;
    showToast('增量重跑失败: ' + err.message, 'error');
  }
}

async function requestAgentRevise(forcedScope, options = {}) {
  const feedbackEl = document.getElementById('agentReviseFeedback');
  const feedback = (feedbackEl?.value || '').trim();
  if (!feedback) {
    showToast('请填写不满意的原因或点选快捷标签', 'error');
    return;
  }
  if (!solvedAnswers.length || !solvedAnswers[0]?.parsed) {
    showToast('无可修订的解题结果', 'error');
    return;
  }
  const settings = getAgentApiSettings();
  const scope = forcedScope || getReviseScopeFromUI();
  try {
    const resp = await apiPost('/api/agent/revise', {
      ...settings,
      parsed: solvedAnswers[0].parsed,
      solve_data: solvedAnswers[0],
      scope,
      feedback,
      verification_report: agentVerificationReport,
      report_text: parsedQuestions[0]?.full_text || '',
      module_results: agentModuleResults,
      sections_config: collectSectionsConfigForApi(),
      format_spec: agentFormatSpec,
    });
    solvedAnswers[0].parsed = resp.parsed || solvedAnswers[0].parsed;
    solvedAnswers[0].code = resp.parsed?.code || solvedAnswers[0].code;
    if (!solvedAnswers[0].versions) solvedAnswers[0].versions = [];
    solvedAnswers[0].versions.push({
      v: solvedAnswers[0].versions.length + 1,
      parsed: JSON.parse(JSON.stringify(solvedAnswers[0].parsed)),
      feedback,
      at: new Date().toISOString(),
    });
    updateAgentVersionUI();
    if (resp.module_results?.solve_lab) {
      agentModuleResults = { ...(agentModuleResults || {}), ...resp.module_results };
    }
    agentDirtyModules = resp.dirty_modules || options.rerunModules || [];
    agentFillSections = resp.fill_sections ?? agentFillSections;
    showToast('已根据反馈修订内容', 'success');
    await runAgentVerify();
    const settings2 = collectSolveOptions(loadSettings());
    onSolveComplete(settings2);
    const rerun = options.rerunModules || agentDirtyModules;
    if (rerun?.length) {
      const ok = confirm(`修订后建议重跑：${rerun.map((m) => AGENT_MODULE_LABELS[m] || m).join('、')}。是否现在执行？`);
      if (ok) await runAgentPartialRerun(rerun);
    }
  } catch (err) {
    showToast('修订失败: ' + err.message, 'error');
  }
}

function applyAgentRunDone(event) {
  const settings = collectSolveOptions(loadSettings());
  const mr = event.module_results || {};
  agentModuleResults = mr;
  const solveData = mr.solve_lab?.data || mr.solve_theory?.data;

  if (solveData) {
    const q = parsedQuestions[0] || { type: 'lab_report' };
    solvedAnswers = [{
      ...q,
      type: q.type || 'lab_report',
      answer: solveData.answer || solveData.result_description || '',
      code: solveData.code || '',
      code_files: solveData.code_files || [],
      main_file: solveData.main_file || '',
      language: solveData.language || settings.codeLanguage,
      parsed: solveData.parsed || {},
      include_code: settings.includeCode !== false,
      include_uml: settings.includeUml === true,
    }];
    const shot = mr.screenshot_ide?.data || mr.screenshot_terminal?.data;
    if (shot?.images_b64?.length) {
      solvedAnswers[0].images_b64 = shot.images_b64;
      solvedAnswers[0].image_b64 = shot.image_b64 || shot.images_b64[0];
    }
    const uml = mr.render_uml?.data;
    if (uml?.images_b64?.length) {
      solvedAnswers[0].uml_images_b64 = uml.images_b64;
    }
  }

  if (event.output_path) {
    lastOutputPath = event.output_path;
  }
  if (event.run_id) {
    lastAgentRunId = event.run_id;
  }

  currentDeliverable = event.deliverable
    || mr.present_deliverable?.data?.deliverable
    || buildDeliverableFromSolveData(solveData, mr);
  if (currentDeliverable) {
    renderDeliverableWorkspace(currentDeliverable);
  }

  const t3El = document.getElementById('step3Title');
  if (t3El) t3El.textContent = event.ok !== false
    ? '📋 答案工作区'
    : '⚠️ 生成未完全成功';
  var reactItem = document.getElementById('agent-step-react');
  if (reactItem) {
    reactItem.classList.remove('solving');
    reactItem.classList.add(event.ok !== false ? 'done' : 'error');
    var icon = reactItem.querySelector('.solving-status');
    if (icon) icon.textContent = event.ok !== false ? '✅' : '❌';
  }
  updateAgentProgress(
    document.querySelectorAll('.solving-item.done').length,
    agentPlanSteps.length,
    event.ok !== false ? '全部完成' : '部分失败'
  );
  if (Array.isArray(event.thought_trace) && event.thought_trace.length) {
    ingestThoughtTrace(event.thought_trace);
  }
  if (Array.isArray(event.decision_log) && event.decision_log.length) {
    event.decision_log.forEach((d) => {
      if (!agentDecisionLog.some((x) => x.timestamp === d.timestamp && x.decision === d.decision)) {
        agentDecisionLog.push(d);
      }
    });
  }
  agentRunFinished = true;
  updateThoughtSidebarVisibility();
}

function finishAgentRunUI(success) {
  disconnectAgentSSE();
  agentRunId = null;
  agentExecutionMode = false;
  agentRunFinished = true;
  document.getElementById('cancelAgentRunBtn').style.display = 'none';
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = agentPlanStale || !agentPlanSteps.length;
  updateThoughtSidebarVisibility();

  saveThoughtLogAuto().then((path) => {
    if (path) {
      updateThoughtLogSavedUI(path);
      showToast('思考过程已自动保存至 thought_logs 文件夹', 'info');
    }
  });

  if (success && solvedAnswers.length) {
    const settings = loadSettings();
    onSolveComplete(settings);
    updateAgentVersionUI();
  } else if (!success) {
    showToast('执行未完全成功，可返回修改计划后重试', 'warning');
  }
}

async function cancelAgentRun() {
  if (!agentRunId) return;
  try {
    await apiPost('/api/agent/cancel', { run_id: agentRunId });
  } catch (err) {
    showToast('取消失败: ' + err.message, 'error');
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function buildDeliverableFromSolveData(solveData, moduleResults) {
  if (!solveData) return null;
  const parsed = solveData.parsed || {};
  const mr = moduleResults || {};
  const codeFiles = solveData.code_files || parsed.code_files || [];
  const files = codeFiles.length
    ? codeFiles.map((f) => ({ name: f.name || f.filename || 'main', code: f.code || f.content || '' }))
    : (solveData.code || parsed.code)
      ? [{ name: solveData.main_file || parsed.main_file || 'main.py', code: solveData.code || parsed.code }]
      : [];
  const umlImages = mr.render_uml?.data?.images_b64 || [];
  const rawDiagrams = parsed.diagrams || solveData.diagrams || [];
  const diagrams = rawDiagrams.length
    ? rawDiagrams.map((d, i) => ({
      kind: d.kind || d.type || 'diagram',
      title: d.title || d.name || `图 ${i + 1}`,
      plantuml: d.plantuml || d.source || '',
      image_b64: umlImages[i] || null,
    }))
    : umlImages.map((b64, i) => ({ kind: 'uml', title: `图 ${i + 1}`, image_b64: b64 }));

  const solveSession = mr.solve_lab?.data?.solve_session;
  const constraints = getUserConstraints();
  let validationStatus = 'skipped';
  let validationNote = '未执行内化验证；请自行在实验环境运行代码';
  let sampleStdout = '';
  if (constraints.includes('skip_validation')) {
    validationStatus = 'not_requested';
    validationNote = '已按设置跳过内化验证';
  } else if (solveSession) {
    const codeStatus = solveSession.code_status || 'skipped';
    const runResult = solveSession.run_result || {};
    sampleStdout = (runResult.stdout || runResult.output || '').slice(0, 4000);
    if (codeStatus === 'verified') {
      validationStatus = 'verified';
      validationNote = '代码已通过内化验证沙箱';
    } else if (codeStatus === 'degraded') {
      validationStatus = 'failed';
      validationNote = '内化验证未通过';
    }
  } else {
    const runOk = mr.run_code?.ok;
    const runOut = mr.run_code?.data?.stdout || mr.run_code?.data?.output || '';
    sampleStdout = runOut ? runOut.slice(0, 4000) : '';
    if (runOk && runOut) {
      validationStatus = 'verified';
      validationNote = '代码已在本地试跑（请在实验环境再次确认）';
    }
  }

  return {
    id: `dlv_local_${Date.now()}`,
    created_at: new Date().toISOString(),
    sections: {
      steps_analysis: parsed.steps_analysis || '',
      result_description: parsed.result_description || '',
      summary: parsed.summary || '',
      notes: parsed.notes || solveData.notes || '',
    },
    code: {
      language: solveData.language || parsed.language || 'python',
      files,
      main_file: solveData.main_file || parsed.main_file || (files[0]?.name || ''),
    },
    diagrams,
    execution: {
      validation_status: validationStatus,
      validation_note: validationNote,
      sample_stdout: sampleStdout || undefined,
    },
    constraints_applied: constraints,
    provenance: {
      ai_assisted: true,
      generated_at: new Date().toISOString(),
      ...(constraints.includes('provenance_label') || getProvenanceCustomLabel()
        ? {
          custom_label: getProvenanceCustomLabel()
            || '内容由 AI 辅助生成，本人已核对',
        }
        : {}),
    },
    quality: {},
  };
}

let activeDeliverableTab = 'steps_analysis';

function renderDeliverableWorkspace(dlv) {
  const wrap = document.getElementById('deliverableWorkspace');
  if (!wrap || !dlv) return;
  wrap.style.display = 'block';
  currentDeliverable = dlv;

  const badge = document.getElementById('deliverableValidationBadge');
  const noteEl = document.getElementById('deliverableValidationNote');
  const exec = dlv.execution || {};
  const status = exec.validation_status || 'skipped';
  if (badge) {
    badge.textContent = DELIVERABLE_VALIDATION_LABELS[status] || status;
    badge.className = `deliverable-validation-badge ${status}`;
  }
  if (noteEl) noteEl.textContent = exec.validation_note || '';

  renderDeliverableProvenance(dlv);
  enrichDeliverableAsync(dlv);

  const tabsEl = document.getElementById('deliverableTabs');
  if (tabsEl) {
    tabsEl.innerHTML = DELIVERABLE_SECTION_TABS.map((t) => {
      const hasContent = t.id === 'code'
        ? (dlv.code?.files || []).some((f) => (f.code || '').trim())
        : t.id === 'diagrams'
          ? (dlv.diagrams || []).length > 0
          : Boolean((dlv.sections || {})[t.id]?.trim());
      return `<button type="button" class="deliverable-tab${activeDeliverableTab === t.id ? ' active' : ''}${hasContent ? '' : ' empty'}"
        data-tab="${t.id}" onclick="switchDeliverableTab('${t.id}')">${t.label}</button>`;
    }).join('');
  }
  renderDeliverableTabContent(dlv, activeDeliverableTab);
}

function switchDeliverableTab(tabId) {
  activeDeliverableTab = tabId;
  if (currentDeliverable) renderDeliverableWorkspace(currentDeliverable);
}

function renderDeliverableTabContent(dlv, tabId) {
  const body = document.getElementById('deliverableSectionBody');
  const diagramsWrap = document.getElementById('deliverableDiagrams');
  if (!body) return;

  if (tabId === 'diagrams') {
    body.style.display = 'none';
    if (diagramsWrap) {
      diagramsWrap.style.display = 'block';
      const items = dlv.diagrams || [];
      diagramsWrap.innerHTML = items.length
        ? items.map((d) => {
          const img = d.image_b64
            ? `<img src="data:image/png;base64,${d.image_b64}" alt="${escapeHtml(d.title || '')}" class="deliverable-diagram-img"/>`
            : '';
          const src = d.plantuml
            ? `<pre class="deliverable-code-block">${escapeHtml(d.plantuml)}</pre>`
            : '';
          return `<div class="deliverable-diagram-card"><h5>${escapeHtml(d.title || '图')}</h5>${img}${src}</div>`;
        }).join('')
        : '<p class="form-hint">（无图表）</p>';
    }
    return;
  }

  if (diagramsWrap) diagramsWrap.style.display = 'none';
  body.style.display = 'block';

  if (tabId === 'code') {
    const files = dlv.code?.files || [];
    const lang = dlv.code?.language || 'text';
    body.innerHTML = files.length
      ? files.map((f) => `
        <div class="deliverable-code-file">
          <div class="deliverable-code-filename">${escapeHtml(f.name || 'code')}</div>
          <pre class="deliverable-code-block">${escapeHtml(f.code || '')}</pre>
        </div>`).join('')
      : '<p class="form-hint">（无代码）</p>';
    return;
  }

  const text = (dlv.sections || {})[tabId] || '';
  body.innerHTML = text.trim()
    ? `<pre class="deliverable-text-block">${escapeHtml(text)}</pre>`
    : '<p class="form-hint">（本节暂无内容）</p>';
}

function renderDeliverableProvenance(dlv) {
  const wrap = document.getElementById('deliverableProvenance');
  const labelEl = document.getElementById('deliverableProvenanceLabel');
  const hashEl = document.getElementById('deliverableIntegrityHash');
  if (!wrap || !hashEl) return;
  const prov = dlv?.provenance || {};
  const hash = prov.integrity_hash || '';
  hashEl.textContent = hash || '—';
  if (labelEl) {
    labelEl.textContent = prov.custom_label || '';
    labelEl.style.display = prov.custom_label ? 'inline' : 'none';
  }
  wrap.style.display = hash || prov.custom_label ? 'flex' : 'none';
}

async function enrichDeliverableAsync(dlv) {
  if (!dlv || dlv.provenance?.integrity_hash) return;
  try {
    const resp = await apiPost('/api/deliverable/export', {
      deliverable: dlv,
      format: 'json',
    });
    const enriched = resp.deliverable;
    if (!enriched?.provenance?.integrity_hash) return;
    if (currentDeliverable?.id === dlv.id) {
      currentDeliverable = enriched;
      renderDeliverableProvenance(enriched);
    }
  } catch (_) { /* non-blocking */ }
}

function deliverableExportPayload() {
  return {
    deliverable: currentDeliverable,
    include_footer: document.getElementById('constraintProvenanceLabel')?.checked ?? false,
    provenance_custom_label: getProvenanceCustomLabel() || undefined,
  };
}

async function copyDeliverableIntegrityHash() {
  const hash = currentDeliverable?.provenance?.integrity_hash;
  if (!hash) {
    showToast('暂无校验码', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(hash);
    showToast('已复制校验码', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function downloadDeliverableExport(format, defaultName, filters) {
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  const result = await window.electronAPI.saveFileDialog(defaultName, filters);
  if (result.canceled || !result.filePath) return;
  try {
    const resp = await apiPost('/api/deliverable/export', {
      ...deliverableExportPayload(),
      format,
    });
    if (format === 'markdown') {
      await window.electronAPI.writeFileText(result.filePath, resp.markdown || '');
    } else if (resp.file_b64) {
      await window.electronAPI.writeFileBase64(result.filePath, resp.file_b64);
    } else {
      throw new Error('导出内容为空');
    }
    if (resp.deliverable?.provenance?.integrity_hash) {
      currentDeliverable = resp.deliverable;
      renderDeliverableProvenance(currentDeliverable);
    }
    showToast('已保存', 'success');
  } catch (err) {
    showToast('保存失败: ' + err.message, 'error');
  }
}

function downloadDeliverableMarkdown() {
  const id = currentDeliverable?.id || 'export';
  return downloadDeliverableExport('markdown', `lab_answer_${id}.md`, [
    { name: 'Markdown', extensions: ['md'] },
    { name: '所有文件', extensions: ['*'] },
  ]);
}

function downloadDeliverableDocx() {
  const id = currentDeliverable?.id || 'export';
  return downloadDeliverableExport('docx', `lab_answer_${id}.docx`, [
    { name: 'Word 文档', extensions: ['docx'] },
  ]);
}

function downloadDeliverableCodeZip() {
  const id = currentDeliverable?.id || 'export';
  return downloadDeliverableExport('code_zip', `lab_code_${id}.zip`, [
    { name: 'ZIP 压缩包', extensions: ['zip'] },
  ]);
}

function downloadDeliverableDiagramsZip() {
  const id = currentDeliverable?.id || 'export';
  return downloadDeliverableExport('diagrams_zip', `lab_diagrams_${id}.zip`, [
    { name: 'ZIP 压缩包', extensions: ['zip'] },
  ]);
}

async function copyDeliverableJson() {
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  try {
    await navigator.clipboard.writeText(JSON.stringify(currentDeliverable, null, 2));
    showToast('已复制 JSON', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyDeliverableMarkdown() {
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  try {
    const resp = await apiPost('/api/deliverable/export', {
      ...deliverableExportPayload(),
      format: 'markdown',
    });
    await navigator.clipboard.writeText(resp.markdown || '');
    showToast('已复制 Markdown', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

function onSolveComplete(settings) {
  const bar = document.getElementById('exportActionBar');
  if (bar) bar.style.display = 'flex';
  updateExportActionBarVisibility();

  if (!currentDeliverable && solvedAnswers[0]) {
    currentDeliverable = buildDeliverableFromSolveData(
      { ...solvedAnswers[0], parsed: solvedAnswers[0].parsed },
      agentModuleResults
    );
    if (currentDeliverable) renderDeliverableWorkspace(currentDeliverable);
  }

  // 自动打开第一个含代码的题目
  for (let i = 0; i < solvedAnswers.length; i++) {
    const a = solvedAnswers[i];
    if (!a || a.error) continue;
    const codeFiles = a.code_files || a.parsed?.code_files || [];
    const mainFile = a.main_file || a.parsed?.main_file || '';
    const code = a.code || a.parsed?.code || '';
    if (codeFiles.length) {
      const lang = a.language || settings.codeLanguage || 'python';
      showCodePanel(a, codeFiles, lang, i, mainFile);
      break;
    }
    if (code.trim()) {
      const lang = detectLang(code) || a.language || settings.codeLanguage || 'python';
      showCodePanel(a, code, lang, i);
      break;
    }
  }

  const umlCount = solvedAnswers.filter(a => a?.uml_images_b64?.length).reduce((n, a) => n + a.uml_images_b64.length, 0);
  const extra = umlCount ? `，已生成 ${umlCount} 张 UML 图` : '';
  showToast(`答案已生成！请从工作区复制分节内容${extra}`, 'success');
}

// ============================
// 代码编辑器
// ============================

function showCodePanel(question, codeOrFiles, language, questionIndex, mainFile) {
  currentCodeQuestion = { question, questionIndex };
  const panel = document.getElementById('codePanel');
  if (!panel) return;
  panel.style.display = 'block';
  const cpTitle = document.getElementById('codePanelTitle');
  if (cpTitle) cpTitle.textContent = `代码 - ${question.title || '题目' + (questionIndex + 1)}`;

  const langMap = { python: 'python', javascript: 'javascript', c: 'c', cpp: 'cpp', java: 'java' };
  const monacoLang = langMap[language] || 'python';

  // Normalize: single code string or multi-file array
  if (typeof codeOrFiles === 'string') {
    const filename = mainFile || _guessCodeFilename(language);
    currentCodeFiles = [{ name: filename, code: codeOrFiles }];
    currentMainFile = filename;
  } else if (Array.isArray(codeOrFiles) && codeOrFiles.length) {
    currentCodeFiles = codeOrFiles;
    currentMainFile = mainFile || codeOrFiles[0].name || _guessCodeFilename(language);
  } else {
    currentCodeFiles = [];
    currentMainFile = '';
  }

  renderCodeFileTabs();
  _showFileInMonaco(currentMainFile, monacoLang);

  const select = document.getElementById('langSelect');
  select.value = language || 'python';
}

function _guessCodeFilename(language) {
  const ext = { python: '.py', java: '.java', c: '.c', cpp: '.cpp', javascript: '.js' };
  return `main${ext[language] || '.py'}`;
}

function renderCodeFileTabs() {
  const tabs = document.getElementById('codeFileTabs');
  if (!tabs) return;
  tabs.innerHTML = '';
  if (currentCodeFiles.length <= 1) {
    tabs.style.display = 'none';
    return;
  }
  tabs.style.display = 'flex';
  currentCodeFiles.forEach((f) => {
    const name = f.name || f.filename || 'untitled';
    const btn = document.createElement('button');
    btn.className = 'code-file-tab';
    btn.textContent = name;
    if (name === currentMainFile || (currentCodeFiles.length > 0 && f === currentCodeFiles[0] && !currentMainFile)) {
      btn.classList.add('active');
    }
    btn.addEventListener('click', () => switchCodeFile(name));
    tabs.appendChild(btn);
  });
}

function switchCodeFile(name) {
  currentMainFile = name;
  const langMap = { python: 'python', javascript: 'javascript', c: 'c', cpp: 'cpp', java: 'java' };
  const lang = document.getElementById('langSelect').value || 'python';
  _showFileInMonaco(name, langMap[lang] || 'python');
  renderCodeFileTabs();
}

function _showFileInMonaco(name, monacoLang) {
  const file = currentCodeFiles.find((f) => (f.name || f.filename) === name);
  if (monacoEditor && file) {
    monacoEditor.setValue(file.code || file.content || '');
    monaco.editor.setModelLanguage(monacoEditor.getModel(), monacoLang);
  }
}

function closeCodePanel() {
  document.getElementById('codePanel').style.display = 'none';
  currentCodeFiles = [];
  currentMainFile = '';
  const tabs = document.getElementById('codeFileTabs');
  if (tabs) tabs.style.display = 'none';
}

function changeLanguage() {
  const lang = document.getElementById('langSelect').value;
  const langMap = { python: 'python', javascript: 'javascript', c: 'c', cpp: 'cpp', java: 'java' };
  if (monacoEditor) {
    monaco.editor.setModelLanguage(monacoEditor.getModel(), langMap[lang] || 'python');
  }
}

async function runCode(withScreenshot = false) {
  const code = monacoEditor?.getValue() || '';
  const language = document.getElementById('langSelect').value;
  const hasGui = document.getElementById('guiModeCheck')?.checked || false;
  const consoleBody = document.getElementById('consoleBody');
  const btn = document.querySelector('.btn-run');

  if (!btn || !consoleBody) return;

  // Save current editor content back to currentCodeFiles
  if (currentMainFile && currentCodeFiles.length) {
    const active = currentCodeFiles.find((f) => (f.name || f.filename) === currentMainFile);
    if (active) {
      active.code = code;
    }
  }

  const isMultiFile = currentCodeFiles.length > 1;
  let mainFile = currentMainFile || (currentCodeFiles[0] && currentCodeFiles[0].name) || '';

  btn.disabled = true;
  btn.textContent = withScreenshot ? '⏳ 执行+截图中...' : '⏳ 运行中...';
  consoleBody.className = 'console-body';
  consoleBody.textContent = '正在执行...';

  try {
    const endpoint = withScreenshot ? '/api/run-and-screenshot' : '/api/run-code';
    let resp;
    if (isMultiFile && !withScreenshot) {
      // Use multi-file endpoint
      resp = await apiPost('/api/run-code-multi', {
        files: currentCodeFiles,
        language,
        main_file: mainFile,
      });
    } else {
      // Single-file or screenshot still uses original endpoint
      // For screenshot with multi-file, use the main file code
      const runCode = isMultiFile
        ? (currentCodeFiles.find((f) => (f.name || f.filename) === mainFile)?.code || '')
        : code;
      resp = await apiPost(endpoint, {
        code: runCode,
        language,
        has_gui: hasGui,
        chrome_style: getScreenshotChrome(),
        ...getTerminalConfig(),
        full_layout: getScreenshotLayout() === 'full',
      });
    }

    if (resp.needs_jre) {
      btn.disabled = false;
      btn.textContent = '▶ 运行';
      consoleBody.textContent = '';
      await promptDownloadJRE();
      return;
    }

    const output = resp.output || '';
    const isError = resp.error || resp.is_error || false;

    consoleBody.textContent = output || '(程序运行完成，无输出)';
    consoleBody.className = isError ? 'console-body console-error' : 'console-body console-success';

    const shots = resp.images_b64?.length ? resp.images_b64 : (resp.image_b64 ? [resp.image_b64] : []);
    const previewWrap = document.getElementById('screenshotPreviewWrap');
    if (previewWrap) previewWrap.remove();

    if (shots.length) {
      const wrap = document.createElement('div');
      wrap.id = 'screenshotPreviewWrap';
      wrap.style.cssText = 'margin-top:8px;display:flex;flex-direction:column;gap:8px';
      if (shots.length > 1) {
        const hint = document.createElement('div');
        hint.style.cssText = 'font-size:12px;color:var(--text-secondary)';
        hint.textContent = `已生成 ${shots.length} 张分页截图（将全部插入实验结果）`;
        wrap.appendChild(hint);
      }
      shots.forEach((b64, i) => {
        const img = document.createElement('img');
        img.src = `data:image/png;base64,${b64}`;
        img.alt = `截图 ${i + 1}`;
        img.style.cssText = 'max-width:100%;border-radius:6px;border:1px solid var(--border)';
        wrap.appendChild(img);
      });
      consoleBody.parentElement.appendChild(wrap);

      if (currentCodeQuestion != null) {
        const idx = currentCodeQuestion.questionIndex;
        if (solvedAnswers[idx]) {
          solvedAnswers[idx].images_b64 = shots;
          solvedAnswers[idx].image_b64 = shots[0];
          solvedAnswers[idx].screenshot_pages = resp.page_count || shots.length;
        }
      }
    }

    // Update answer/progress display
    if (currentCodeQuestion) {
      const idx = currentCodeQuestion.questionIndex;
      if (solvedAnswers[idx]) {
        solvedAnswers[idx].code = code;
        solvedAnswers[idx].code_files = currentCodeFiles;
        solvedAnswers[idx].main_file = currentMainFile;
        solvedAnswers[idx].output = output;
        const ansEl = document.getElementById(`answer-${idx}`);
        if (ansEl) ansEl.textContent = `代码已执行\n输出: ${output.substring(0, 100)}`;
      }
    }

  } catch (err) {
    consoleBody.textContent = '运行失败: ' + err.message;
    consoleBody.className = 'console-body console-error';
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ 运行';
  }
}

// ============================
// 报告生成与导出
// ============================

function getHistoryContext() {
  return {
    currentFile,
    parsedMetadata,
    agentDocumentIds,
    agentSplitIdx,
    sectionsConfig: collectSectionsConfigForApi(),
    sectionRowDefs: SECTION_ROW_DEFS,
    fillModeOptions: FILL_MODE_OPTIONS,
    decisionLog: agentDecisionLog,
    runMode: lastSessionRunMode,
    planFingerprint: agentPlanFingerprint,
    planFeedback: agentPlanFeedback,
  };
}

function recordHistoryAfterExport(name, filePath) {
  addToHistory(
    buildHistoryRecord(
      {
        name,
        path: filePath,
        questions: parsedQuestions.length,
        date: new Date().toLocaleDateString('zh-CN'),
      },
      getHistoryContext()
    )
  );
}

async function generateReport() {
  const isLab = parsedQuestions[0]?.type === 'lab_report';
  if (parsedQuestions.length > 0) {
    const ok = await confirmBeforeFillReport(
      collectSectionsConfigForApi(),
      getDynamicSectionRowDefs(),
      FILL_MODE_OPTIONS,
      isLab
    );
    if (!ok) return;
  }

  try {
    const fillPayload = await buildFillReportPayload();
    const resp = await apiPost('/api/fill-report', fillPayload);

    if (resp.output_path) {
      lastOutputPath = resp.output_path;
    }

    renderExportPreview(solvedAnswers, resp.fill_target);
    if (lastOutputPath && currentFile && currentFile !== 'demo') {
      const histName = (currentFile.split(/[\\/]/).pop() || 'report').replace(/\.pdf$/i, '.docx');
      recordHistoryAfterExport(histName, lastOutputPath);
    }
    showToast('报告生成成功！', 'success');
    goToStep(4);
    updateStepBar(4);
  } catch (err) {
    showToast('报告生成失败: ' + err.message, 'error');
    console.error('generateReport error:', err);
  }
}

function renderExportPreview(answers, fillTarget) {
  const preview = document.getElementById('exportPreview');
  const subtitle = document.getElementById('exportSuccessSubtitle');
  const counts = { code: 0, theory: 0, analysis: 0, total: answers.length, done: 0 };
  answers.forEach(a => {
    if (a && !a.error) counts.done++;
    if (a?.type) counts[a.type] = (counts[a.type] || 0) + 1;
  });

  const fromPdf = fillTarget?.source_format === 'pdf'
    || isPdfSource(parsedMetadata, currentFile?.split(/[\\/]/).pop());
  const exportNote = fromPdf
    ? '<div style="font-size:12px;color:var(--text-secondary);margin-top:4px">原版 PDF 无法直接填回，已导出为 Word（.docx）</div>'
    : '';

  if (subtitle && fromPdf) {
    subtitle.textContent = '题目已解答，报告已写入 Word 文档（.docx）';
  } else if (subtitle) {
    subtitle.textContent = '所有题目已解答，报告已填充完毕';
  }

  preview.innerHTML = `
    <div style="display:flex;flex-direction:column;gap:8px;">
      <div style="font-weight:600;margin-bottom:4px;">📊 解题统计</div>
      <div style="display:flex;gap:16px;font-size:13px;color:var(--text-secondary)">
        <span>共 <b style="color:var(--text-primary)">${counts.total}</b> 题</span>
        <span>成功 <b style="color:var(--green)">${counts.done}</b> 题</span>
        <span>编程题 <b style="color:var(--accent)">${counts.code || 0}</b> 题</span>
      </div>
      ${exportNote}
      <div style="margin-top:8px;font-size:12px;color:var(--text-muted)">
        ${lastOutputPath ? '已保存至: ' + lastOutputPath : '报告已准备好下载'}
      </div>
    </div>
  `;
}

async function exportReport() {
  const isLab = parsedQuestions[0]?.type === 'lab_report';
  if (parsedQuestions.length > 0) {
    const ok = await confirmBeforeFillReport(
      collectSectionsConfigForApi(),
      getDynamicSectionRowDefs(),
      FILL_MODE_OPTIONS,
      isLab
    );
    if (!ok) return;
  }

  const result = await window.electronAPI.saveFileDialog(defaultExportFileName());
  if (result.canceled) return;

  try {
    const fillPayload = await buildFillReportPayload();
    fillPayload.output_path = result.filePath;

    const resp = await apiPost('/api/fill-report', fillPayload);

    showToast('报告已保存！', 'success');
    lastOutputPath = result.filePath;
    const histName = defaultExportFileName();
    recordHistoryAfterExport(histName, result.filePath);

  } catch (err) {
    showToast('保存失败: ' + err.message, 'error');
  }
}

async function openReportFolder() {
  if (lastOutputPath) {
    const folder = lastOutputPath.substring(0, lastOutputPath.lastIndexOf('\\'));
    await window.electronAPI.openFileExternal(folder);
  }
}

function startNew() {
  currentFile = null;
  parsedQuestions = [];
  solvedAnswers = [];
  lastOutputPath = null;
  uploadedDocuments = [];
  renderDocumentList();
  pairedDocxPath = null;
  agentFillTarget = null;
  resetAgentPlanState();
  resetToolboxState();
  goToStep(1);
  updateStepBar(1);
  closeCodePanel();
  document.getElementById('exportActionBar').style.display = 'none';
  document.getElementById('modeSwitchBar').style.display = 'none';
  switchToGuidedMode();
}

// ============================
// 演示功能
// ============================

async function loadDemo() {
  const demoQuestions = [
    {
      id: 0,
      type: 'code',
      title: '编写冒泡排序',
      content: '请用Python编写冒泡排序算法，对给定列表 [64, 34, 25, 12, 22, 11, 90] 进行排序，输出排序结果。',
      placeholder: '（此处填写代码和运行结果）'
    },
    {
      id: 1,
      type: 'theory',
      title: '时间复杂度分析',
      content: '分析冒泡排序的时间复杂度，并说明最好、最坏和平均情况。',
      placeholder: '（此处填写分析结果）'
    },
    {
      id: 2,
      type: 'analysis',
      title: '算法比较',
      content: '与快速排序相比，冒泡排序有哪些优缺点？请举例说明适用场景。',
      placeholder: '（此处填写比较分析）'
    }
  ];

  parsedQuestions = demoQuestions;
  currentFile = 'demo';
  resetAgentPlanState();
  renderQuestions(parsedQuestions);
  goToStep(2);
  updateStepBar(2);
  showToast('已加载演示文档（3道题目）', 'info');
}

// ============================
// 历史记录
// ============================

function addToHistory(item) {
  const history = JSON.parse(localStorage.getItem('history') || '[]');
  history.unshift(item);
  if (history.length > 20) history.pop();
  localStorage.setItem('history', JSON.stringify(history));
  renderHistory();
}

function renderHistory() {
  const history = JSON.parse(localStorage.getItem('history') || '[]');
  const list = document.getElementById('historyList');

  if (history.length === 0) {
    list.innerHTML = '<div class="empty-state"><span>📭</span><p>暂无历史记录</p></div>';
    return;
  }

  list.innerHTML = history.map((item) => {
    const pathJs = JSON.stringify(item.path || '');
    const modeLabel = item.run_mode_label || (
      item.run_mode === 'deep' ? '深度模式'
        : item.run_mode === 'standard' ? '标准模式'
          : item.run_mode === 'react' ? 'ReAct 模式'
            : ''
    );
    const modeCls =
      item.run_mode === 'deep' ? 'mode-deep' : '';
    const sections = item.sections_summary || [];
    const secPreview = sections
      .filter((s) => s.mode === 'auto' || s.mode === 'user_provided')
      .map((s) => s.label || s.id)
      .slice(0, 4)
      .join('、');
    const roles = (item.document_roles || [])
      .map((r) => r.name || r.role)
      .filter(Boolean)
      .join(' · ');
    const decisions = (item.decision_summary || []).length;
    const tags = [];
    if (modeLabel) tags.push(`<span class="history-tag ${modeCls}">${escapeHtml(modeLabel)}</span>`);
    if (secPreview) tags.push(`<span class="history-tag">写入: ${escapeHtml(secPreview)}</span>`);
    if (decisions) tags.push(`<span class="history-tag">决策 ${decisions} 条</span>`);

    return `
    <div class="question-card history-card" onclick="window.electronAPI.openFileExternal(${pathJs})">
      <span class="question-type-badge badge-analysis">已完成</span>
      <div class="question-content">
        <div class="question-title">${escapeHtml(item.name || '报告')}</div>
        <div class="question-preview">${item.questions} 道题 · ${escapeHtml(item.date || '')}</div>
        ${roles ? `<div class="history-card-meta">${escapeHtml(roles)}</div>` : ''}
        ${tags.length ? `<div class="history-card-tags">${tags.join('')}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ============================
// 设置
// ============================

const SETTINGS_SCHEMA_VERSION = 2;
let _runtimeApiKey = '';
let _encryptionAvailable = false;
let _fallbackNotified = false;

async function initSettingsStorage() {
  if (window.electronAPI?.isApiKeyEncryptionAvailable) {
    _encryptionAvailable = await window.electronAPI.isApiKeyEncryptionAvailable();
  }
  await migrateAndLoadApiKey();
}

async function migrateAndLoadApiKey() {
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');

  if (saved.apiKeyEncrypted) {
    _runtimeApiKey = await decryptStoredApiKey(saved);
    return;
  }

  if (saved.apiKey) {
    if (_encryptionAvailable && window.electronAPI?.encryptApiKey) {
      const result = await window.electronAPI.encryptApiKey(saved.apiKey);
      if (result.ok) {
        _runtimeApiKey = saved.apiKey;
        delete saved.apiKey;
        saved.apiKeyEncrypted = result.encrypted;
        saved.apiKeyStorage = 'encrypted';
        saved.schema_version = SETTINGS_SCHEMA_VERSION;
        localStorage.setItem('settings', JSON.stringify(saved));
        return;
      }
    }
    saved.apiKeyStorage = 'plaintext';
    saved.schema_version = Math.max(saved.schema_version || 0, SETTINGS_SCHEMA_VERSION);
    localStorage.setItem('settings', JSON.stringify(saved));
    _runtimeApiKey = saved.apiKey;
    notifyKeyStorageFallback();
    return;
  }

  _runtimeApiKey = '';
}

async function decryptStoredApiKey(saved) {
  if (!saved.apiKeyEncrypted) return saved.apiKey || '';
  if (!_encryptionAvailable || !window.electronAPI?.decryptApiKey) {
    notifyKeyStorageFallback();
    return saved.apiKey || '';
  }
  const result = await window.electronAPI.decryptApiKey(saved.apiKeyEncrypted);
  if (result.ok) return result.plainText || '';
  console.warn('[settings] decrypt api key failed:', result.reason);
  return '';
}

async function persistApiKeyToStorage(apiKey) {
  _runtimeApiKey = apiKey || '';
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');

  if (apiKey && _encryptionAvailable && window.electronAPI?.encryptApiKey) {
    const result = await window.electronAPI.encryptApiKey(apiKey);
    if (result.ok) {
      saved.apiKeyEncrypted = result.encrypted;
      delete saved.apiKey;
      saved.apiKeyStorage = 'encrypted';
      localStorage.setItem('settings', JSON.stringify(saved));
      return;
    }
  }

  if (apiKey) {
    saved.apiKey = apiKey;
    delete saved.apiKeyEncrypted;
    saved.apiKeyStorage = 'plaintext';
    notifyKeyStorageFallback();
  } else {
    delete saved.apiKey;
    delete saved.apiKeyEncrypted;
    delete saved.apiKeyStorage;
  }
  localStorage.setItem('settings', JSON.stringify(saved));
}

function notifyKeyStorageFallback() {
  if (_fallbackNotified) return;
  _fallbackNotified = true;
  showToast(
    '系统密钥环不可用，API Key 将以明文保存在本机存储中。请勿在公共或共享电脑上保存 Key。',
    'warning'
  );
}

function updateKeyStorageNotice() {
  const span = document.querySelector('#keyStorageNotice span');
  if (!span) return;
  if (_encryptionAvailable) {
    span.textContent =
      '经操作系统加密（safeStorage）后保存在本机，不会上传至软件作者服务器；调用 AI 时经 HTTPS 发送至您选择的厂商。请勿在公共或共享电脑上保存 Key。';
  } else {
    span.textContent =
      '系统加密不可用，Key 以明文保存在本机浏览器存储中，不会上传至软件作者服务器；调用 AI 时经 HTTPS 发送至您选择的厂商。请勿在公共或共享电脑上保存 Key。';
  }
}

function mergeSettings(saved) {
  const version = saved.schema_version || 0;
  const merged = {
    apiKey: _runtimeApiKey,
    provider: saved.provider || 'deepseek',
    model: saved.model || 'deepseek-chat',
    codeLanguage: saved.codeLanguage || 'python',
    customUrl: saved.customUrl || '',
    screenshotChrome: saved.screenshotChrome || 'windows',
    terminalProfile: saved.terminalProfile || 'win_powershell',
    terminalCwd: saved.terminalCwd || '',
    terminalCustom: saved.terminalCustom || '',
    screenshotLayout: saved.screenshotLayout || 'full',
    includeUml: saved.includeUml === true,
    umlAllowOnline: saved.umlAllowOnline !== false,
    runMode: saved.runMode || 'standard',
    showThoughtTrace: saved.showThoughtTrace === true,
    optimizePlanFromUsage: saved.optimizePlanFromUsage === true,
    autoRemediate: saved.autoRemediate === true,
    userConstraints: Array.isArray(saved.userConstraints) ? saved.userConstraints : [],
    provenanceCustomLabel: saved.provenanceCustomLabel || '',
    schema_version: SETTINGS_SCHEMA_VERSION,
  };
  if (version < SETTINGS_SCHEMA_VERSION) {
    persistSettingsPatch({ schema_version: SETTINGS_SCHEMA_VERSION });
  }
  return merged;
}

function loadSettings() {
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  const settings = mergeSettings(saved);

  const umlOnlineEl = document.getElementById('umlAllowOnlineSettings');
  if (umlOnlineEl) umlOnlineEl.checked = settings.umlAllowOnline;
  const umlStepEl = document.getElementById('includeUmlCheck');
  if (umlStepEl) umlStepEl.checked = settings.includeUml;

  syncScreenshotChrome(settings.screenshotChrome);
  syncTerminalSettings(settings);
  const layoutEl = document.getElementById('screenshotLayoutSettings');
  if (layoutEl) layoutEl.value = settings.screenshotLayout || 'full';

  document.getElementById('apiKey').value = settings.apiKey;
  document.getElementById('aiProvider').value = settings.provider;
  document.getElementById('modelSelect').value = settings.model;
  document.getElementById('codeLanguage').value = settings.codeLanguage;
  document.getElementById('customUrl').value = settings.customUrl;

  syncRunModeUI(settings.runMode);
  syncUserConstraintsUI(settings.userConstraints);
  const provLabelEl = document.getElementById('provenanceCustomLabel');
  if (provLabelEl) provLabelEl.value = settings.provenanceCustomLabel || '';
  const thoughtEl = document.getElementById('showThoughtTraceSettings');
  if (thoughtEl) thoughtEl.checked = settings.showThoughtTrace;
  const optimizeEl = document.getElementById('optimizePlanFromUsageSettings');
  if (optimizeEl) optimizeEl.checked = settings.optimizePlanFromUsage === true;
  const autoRemediateEl = document.getElementById('autoRemediateSettings');
  if (autoRemediateEl) autoRemediateEl.checked = settings.autoRemediate === true;
  updateKeyStorageNotice();
  onProviderChange();
  renderComplianceSettings(window.__labSolverLogFile || '');
  return settings;
}

function getScreenshotChrome() {
  const el = document.getElementById('screenshotChrome')
    || document.getElementById('screenshotChromeStep2')
    || document.getElementById('screenshotChromeSettings');
  return el?.value || 'windows';
}

function syncScreenshotChrome(value) {
  ['screenshotChrome', 'screenshotChromeStep2', 'screenshotChromeSettings'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = value;
  });
  persistSettingsPatch({ screenshotChrome: value });
}

const TERMINAL_PRESETS = {
  win_powershell: (cwd) => `PS ${cwd || 'C:\\Users\\Student\\Desktop\\lab'}> python main.py`,
  win_cmd: (cwd) => `${cwd || 'C:\\Users\\Student\\Desktop\\lab'}> python main.py`,
  win_gitbash: (cwd) => `${(cwd || 'C:/Users/Student/project').replace(/\\/g, '/')}> python main.py`,
  mac_zsh: (cwd) => `user@MacBook-Pro ${cwd || '~/Documents/project'} % python main.py`,
  mac_bash: () => `bash-3.2$ python main.py`,
  mac_ps: (cwd) => `PS ${cwd || '/Users/student/project'}> python main.py`,
  custom: (_, custom) => `${custom || '> '}python main.py`,
};

function getScreenshotLayout() {
  return document.getElementById('screenshotLayoutSettings')?.value || 'full';
}

function onScreenshotLayoutChange() {
  persistSettingsPatch({ screenshotLayout: getScreenshotLayout() });
}

function onUmlSettingsChange() {
  const el = document.getElementById('umlAllowOnlineSettings');
  persistSettingsPatch({ umlAllowOnline: el ? el.checked : true });
}

function getTerminalConfig() {
  const profile = document.getElementById('terminalProfileSettings')?.value
    || document.getElementById('terminalProfileStep2')?.value
    || 'win_powershell';
  const cwd = document.getElementById('terminalCwdSettings')?.value?.trim() || '';
  const custom = document.getElementById('terminalCustomSettings')?.value?.trim() || '';
  return {
    terminal_profile: profile,
    terminal_cwd: cwd,
    terminal_custom_prompt: custom,
  };
}

function syncTerminalSettings(settings) {
  const s = settings || JSON.parse(localStorage.getItem('settings') || '{}');
  const profile = s.terminalProfile || 'win_powershell';
  const ids = {
    terminalProfileSettings: profile,
    terminalProfileStep2: profile,
  };
  Object.entries(ids).forEach(([id, val]) => {
    const el = document.getElementById(id);
    if (el) el.value = val;
  });
  const cwdEl = document.getElementById('terminalCwdSettings');
  if (cwdEl) cwdEl.value = s.terminalCwd || '';
  const customEl = document.getElementById('terminalCustomSettings');
  if (customEl) customEl.value = s.terminalCustom || '';
  onTerminalSettingsChange(false);
}

function onTerminalSettingsChange(persist = true) {
  const cfg = getTerminalConfig();
  ['terminalProfileSettings', 'terminalProfileStep2'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = cfg.terminal_profile;
  });

  const group = document.getElementById('terminalCustomGroup');
  if (group) group.style.display = cfg.terminal_profile === 'custom' ? 'block' : 'none';

  const fn = TERMINAL_PRESETS[cfg.terminal_profile] || TERMINAL_PRESETS.win_powershell;
  const preview = cfg.terminal_profile === 'custom'
    ? TERMINAL_PRESETS.custom(cfg.terminal_cwd, cfg.terminal_custom_prompt)
    : fn(cfg.terminal_cwd);
  const hint = document.getElementById('terminalPreviewHint');
  if (hint) hint.textContent = `预览：${preview}`;

  if (persist) {
    persistSettingsPatch({
      terminalProfile: cfg.terminal_profile,
      terminalCwd: cfg.terminal_cwd,
      terminalCustom: cfg.terminal_custom_prompt,
    });
  }
}

function persistSettingsPatch(patch) {
  const { apiKey, ...rest } = patch;
  if (Object.keys(rest).length > 0) {
    const saved = JSON.parse(localStorage.getItem('settings') || '{}');
    Object.assign(saved, rest);
    localStorage.setItem('settings', JSON.stringify(saved));
  }
  if (apiKey !== undefined) {
    persistApiKeyToStorage(apiKey).catch((err) => {
      console.error('[settings] persist api key failed:', err);
    });
  }
}

async function collectTerminalEnv() {
  const hint = document.getElementById('terminalCollectHint');
  if (hint) hint.textContent = '正在采集...';

  try {
    if (!window.electronAPI?.detectTerminalEnv) {
      showToast('请在桌面版解题能手中使用一键采集', 'error');
      return;
    }
    const filePath = currentFile && currentFile !== 'demo' ? currentFile : '';
    const info = await window.electronAPI.detectTerminalEnv(filePath);

    if (!info.success) {
      showToast('采集失败: ' + (info.error || '未知错误'), 'error');
      if (hint) hint.textContent = '采集失败，请手动填写';
      return;
    }

    syncTerminalSettings({
      terminalProfile: info.terminal_profile,
      terminalCwd: info.terminal_cwd,
      terminalCustom: '',
    });
    if (info.chrome_style) syncScreenshotChrome(info.chrome_style);

    persistSettingsPatch({
      terminalProfile: info.terminal_profile,
      terminalCwd: info.terminal_cwd,
      screenshotChrome: info.chrome_style || getScreenshotChrome(),
    });

    if (hint) hint.textContent = info.sources ? `来源：${info.sources}` : '采集完成';
    showToast(info.message || '终端环境已采集', 'success');
  } catch (err) {
    showToast('采集失败: ' + err.message, 'error');
    if (hint) hint.textContent = '采集失败，请手动填写';
  }
}

async function saveSettings() {
  const term = getTerminalConfig();
  const apiKey = document.getElementById('apiKey').value;
  const settings = {
    provider: document.getElementById('aiProvider').value,
    model: document.getElementById('modelSelect').value,
    codeLanguage: document.getElementById('codeLanguage').value,
    customUrl: document.getElementById('customUrl').value,
    screenshotChrome: getScreenshotChrome(),
    terminalProfile: term.terminal_profile,
    terminalCwd: term.terminal_cwd,
    terminalCustom: term.terminal_custom_prompt,
    screenshotLayout: getScreenshotLayout(),
    includeUml: document.getElementById('includeUmlCheck')?.checked === true,
    umlAllowOnline: document.getElementById('umlAllowOnlineSettings')?.checked !== false,
    runMode: getRunMode(),
    showThoughtTrace: document.getElementById('showThoughtTraceSettings')?.checked === true,
    optimizePlanFromUsage: document.getElementById('optimizePlanFromUsageSettings')?.checked === true,
    autoRemediate: document.getElementById('autoRemediateSettings')?.checked === true,
    schema_version: SETTINGS_SCHEMA_VERSION,
  };
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  Object.assign(saved, settings);
  delete saved.apiKey;
  delete saved.apiKeyEncrypted;
  delete saved.apiKeyStorage;
  localStorage.setItem('settings', JSON.stringify(saved));
  await persistApiKeyToStorage(apiKey);
  showToast('设置已保存', 'success');
}

function onProviderChange() {
  const provider = document.getElementById('aiProvider').value;
  const hints = {
    deepseek: 'DeepSeek API Key，在 platform.deepseek.com 获取（推荐，价格低）',
    openai: 'OpenAI API Key，在 platform.openai.com 获取',
    claude: 'Anthropic API Key，在 console.anthropic.com 获取',
    zhipu: '智谱AI API Key，在 open.bigmodel.cn 获取',
    custom: '请填写自定义API Key'
  };

  const models = {
    deepseek: ['deepseek-chat', 'deepseek-reasoner'],
    openai: ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo'],
    claude: ['claude-3-5-sonnet-20241022', 'claude-3-haiku-20240307'],
    zhipu: ['glm-4-flash', 'glm-4'],
    custom: ['custom-model']
  };

  document.getElementById('apiKeyHint').textContent = hints[provider] || '';
  const select = document.getElementById('modelSelect');
  select.innerHTML = (models[provider] || ['default']).map(m =>
    `<option value="${m}">${m}</option>`
  ).join('');

  document.getElementById('customUrlGroup').style.display =
    provider === 'custom' ? 'flex' : 'none';
}

async function testConnection() {
  const settings = {
    apiKey: document.getElementById('apiKey').value,
    provider: document.getElementById('aiProvider').value,
    model: document.getElementById('modelSelect').value,
    customUrl: document.getElementById('customUrl').value
  };
  const resultEl = document.getElementById('testResult');

  if (!settings.apiKey) {
    resultEl.className = 'test-result error';
    resultEl.textContent = '❌ 请填写API Key';
    return;
  }

  resultEl.className = 'test-result';
  resultEl.style.display = 'block';
  resultEl.textContent = '🔄 测试中...';
  resultEl.style.background = 'var(--bg-hover)';
  resultEl.style.color = 'var(--text-secondary)';

  try {
    const resp = await apiPost('/api/test-connection', settings);
    resultEl.className = 'test-result success';
    resultEl.textContent = '✅ 连接成功！模型：' + (resp.model || settings.model);
    persistSettingsPatch({
      apiKey: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      customUrl: settings.customUrl || '',
    });
  } catch (err) {
    resultEl.className = 'test-result error';
    resultEl.textContent = '❌ 连接失败：' + err.message;
  }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById('apiKey');
  input.type = input.type === 'password' ? 'text' : 'password';
}

// ============================
// API通信
// ============================

async function apiGet(path) {
  const resp = await fetch(`http://localhost:${serverPort}${path}`);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    const msg = typeof err.error === 'string' ? err.error : (err.message || `HTTP ${resp.status}`);
    throw new Error(msg);
  }
  return resp.json();
}

async function apiPost(path, data) {
  const resp = await fetch(`http://localhost:${serverPort}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ error: resp.statusText }));
    // err.error 可能是字符串或布尔值，统一处理
    const msg = typeof err.error === 'string' ? err.error : (err.message || `HTTP ${resp.status}`);
    throw new Error(msg);
  }

  return resp.json();
}

// ============================
// Toast通知
// ============================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const icons = { success: '✅', error: '❌', info: 'ℹ️' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>${icons[type]}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'slideIn 0.2s ease reverse';
    setTimeout(() => toast.remove(), 200);
  }, 3000);
}

// ============================
// JRE 下载
// ============================

async function promptDownloadJRE() {
  // 在控制台区域显示下载提示
  const consoleBody = document.getElementById('consoleBody');
  consoleBody.className = 'console-body';
  consoleBody.innerHTML = `
<div style="padding:8px 0">
  <div style="color:#e3b341;font-weight:600;margin-bottom:10px">⚠️ 需要Java运行环境</div>
  <div style="color:#8b949e;margin-bottom:12px;line-height:1.6">
    运行Java代码需要下载便携版JRE（约50MB）<br>
    下载后永久保存，无需重复下载，完全离线可用
  </div>
  <button id="downloadJreBtn" style="background:#3fb950;color:white;border:none;border-radius:6px;padding:8px 18px;font-size:13px;cursor:pointer;font-weight:600">
    ⬇️ 一键下载JRE（约50MB）
  </button>
  <span id="jreDownloadStatus" style="margin-left:12px;color:#8b949e;font-size:12px"></span>
</div>`;

  document.getElementById('downloadJreBtn').onclick = async () => {
    const btn = document.getElementById('downloadJreBtn');
    const status = document.getElementById('jreDownloadStatus');
    btn.disabled = true;
    btn.textContent = '⏳ 下载中...';
    status.textContent = '正在从GitHub下载，请耐心等待（约1-3分钟）...';

    try {
      await apiPost('/api/download-jre', {});
      status.textContent = '✅ 下载完成！';
      btn.textContent = '✅ JRE已就绪';
      showToast('Java运行环境安装成功！', 'success');
      consoleBody.className = 'console-body console-success';
      consoleBody.textContent = '✅ JRE安装完成，现在可以运行Java代码了！';
    } catch (err) {
      btn.disabled = false;
      btn.textContent = '⬇️ 重试下载';
      status.textContent = '❌ 下载失败: ' + err.message;
      showToast('JRE下载失败，请检查网络', 'error');
    }
  };
}

// ============================
// 工具函数
// ============================

function detectLang(code) {
  if (!code) return null;
  if (/public\s+class\s+\w+/.test(code))           return 'java';
  if (/def\s+\w+\s*\(|import\s+\w+|print\s*\(/.test(code)) return 'python';
  if (/#include\s*</.test(code) && /cout|printf/.test(code)) return /cout/.test(code) ? 'cpp' : 'c';
  if (/function\s+\w+|const\s+\w+\s*=|let\s+\w+/.test(code)) return 'javascript';
  return null;
}

// ============================
// 启动
// ============================
window.addEventListener('DOMContentLoaded', init);
