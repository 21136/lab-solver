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
let agentSseClosingGracefully = false;
let agentSseEventIndex = 0;
let agentSseTotalSteps = 0;
let agentSseReconnectAttempts = 0;
let agentJarConsentInFlight = false;
let agentThoughtCollapsed = true;
let agentThoughtLog = [];
let lastThoughtLogPath = null;
let lastAgentRunId = null;
let lastRunSummary = null;
let agentDirtyModules = [];
let agentFillSections = null;
let agentAnswerTemplateText = '';
let uploadedDocuments = [];
let uploadInputMode = 'paste';
let assignmentImageItems = [];
let assignmentImageDragId = null;
let agentDocLayout = null;
let agentSplitAtHeading = '';
let agentSplitCandidates = [];
let agentPrimaryFullText = '';
let agentAssignmentText = '';
let agentImageAssets = [];
let agentImageSections = [];
let agentImageReadSummary = null;
let agentImageReadingMode = 'ocr_only';
let agentAssignmentFromImages = false;
let agentAssignmentBodyPrefix = '';
let agentAssignmentPreviewConfirmed = false;
let agentParseImageWarnings = [];
let agentContextSnapshot = null;
let _ocrOkCached = null;
let agentTemplatePending = null;
let agentTemplateConfirmed = false;
let agentAwaitingSplitConfirm = false;
let agentSplitDirty = false;

const AGENT_ACTIVE_RUN_KEY = 'labSolverAgentActiveRun';

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
  docx: 'file-text',
  pdf: 'book-open',
  doc: 'file-pen',
  text: 'clipboard-list',
};

function ico(name, className = 'icon-sm') {
  return Icons.iconHtml(name, { className });
}

function icoLabel(name, text, className = 'icon-xs') {
  return Icons.iconLabel(name, text, className);
}

function emptyStateHtml(iconName, title, hint = '') {
  const hintHtml = hint ? `<p class="empty-state-hint">${hint}</p>` : '';
  return `<div class="empty-state"><div class="empty-state-illustration" aria-hidden="true">${ico(iconName, 'icon-lg')}</div><p class="empty-state-title">${escapeHtml(title)}</p>${hintHtml}</div>`;
}

function setHeadingIcon(el, iconName, text) {
  if (!el) return;
  el.innerHTML = `${ico(iconName, 'icon-sm')}${escapeHtml(text)}`;
}

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
  code_cloze_schema: '代码完形结构',
  deliverable_ready: '答案交付物',
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
  solve_code_cloze: '代码完形填空',
  solve_theory: '理论题解答',
  solve_short_answer: '解答简答题',
  run_code: '运行代码',
  fix_code: '修复代码',
  render_uml: '渲染图表',
  fix_diagrams: '修复图表',
  fill_report: '填入 Word（实验性）',
  present_deliverable: '汇编答案交付物',
};

const PIPELINE_PHASE_LABELS = {
  understand_brief: '读题对齐',
  solve_code: '生成代码',
  run_code_sandbox: '内化验证',
  fix_code_narrow: '修复代码',
  write_report_text: '撰写报告',
};

const DELIVERABLE_SECTION_TABS = [
  { id: 'steps_analysis', label: '步骤 / 分析' },
  { id: 'result_description', label: '结果说明' },
  { id: 'summary', label: '总结' },
  { id: 'code', label: '代码' },
  { id: 'diagrams', label: '图表' },
];

const DELIVERABLE_TEXT_SECTIONS = DELIVERABLE_SECTION_TABS.filter(
  (t) => t.id !== 'code' && t.id !== 'diagrams',
);

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


function uiHide(el) {
  if (el) el.classList.add('is-hidden');
}

function uiShow(el, display) {
  if (!el) return;
  el.classList.remove('is-hidden');
  if (display) el.style.display = display;
  else el.style.removeProperty('display');
}

// ============================
// 初始化
// ============================

let serverBootstrapDone = false;
let serverStartupFailed = false;

function runServerReadyBootstrap() {
  if (serverBootstrapDone || serverStartupFailed) return;
  serverBootstrapDone = true;
  hideLoading();
  readSettings();
  ensureModelCatalog().catch(() => {});
  seedHostedAgnesIfNeeded().catch(() => {});
  fetchLogFilePath(apiGet).catch(() => {});
  runComplianceStartupSequence(apiGet).catch(() => {});
  renderHistory();
  showToast('AI引擎就绪', 'success');
  setServerStatus(true);
  tryRestoreAgentRunAfterLoad().catch(() => {});
}

function loadAgentActiveRun() {
  try {
    return JSON.parse(localStorage.getItem(AGENT_ACTIVE_RUN_KEY) || 'null');
  } catch {
    return null;
  }
}

function persistAgentActiveRun(patch = {}) {
  const prev = loadAgentActiveRun() || {};
  const snap = {
    run_id: agentRunId || prev.run_id,
    totalSteps: agentSseTotalSteps || prev.totalSteps || 0,
    sseSince: agentSseEventIndex,
    steps: (agentConfirmedSteps && agentConfirmedSteps.length)
      ? agentConfirmedSteps
      : (prev.steps || []),
    runMode: getRunMode(),
    startedAt: prev.startedAt || Date.now(),
    partial: Boolean(prev.partial),
    ...patch,
  };
  if (!snap.run_id) return;
  try {
    localStorage.setItem(AGENT_ACTIVE_RUN_KEY, JSON.stringify(snap));
  } catch (_) { /* quota */ }
}

function clearAgentActiveRun() {
  try {
    localStorage.removeItem(AGENT_ACTIVE_RUN_KEY);
  } catch (_) { /* ignore */ }
}

async function tryRestoreAgentRunAfterLoad() {
  if (agentRunId || agentRunFinished) return;

  let snap = loadAgentActiveRun();
  if (!snap?.run_id) {
    try {
      const active = await apiGet('/api/agent/active-run');
      if (active?.run_id) {
        snap = {
          run_id: active.run_id,
          totalSteps: 0,
          sseSince: 0,
          steps: [],
          runMode: getRunMode(),
        };
      }
    } catch (_) {
      return;
    }
  }
  if (!snap?.run_id) return;

  let statusResp;
  try {
    statusResp = await apiGet(
      `/api/agent/run-status?run_id=${encodeURIComponent(snap.run_id)}&since=0`
    );
  } catch (_) {
    clearAgentActiveRun();
    return;
  }

  const totalSteps = snap.totalSteps || snap.steps?.length || 1;
  const runMode = snap.runMode || getRunMode();
  agentRunId = snap.run_id;
  agentExecutionMode = true;
  agentRunFinished = false;
  agentSseClosingGracefully = false;
  agentSseEventIndex = 0;
  agentSseReconnectAttempts = 0;
  agentSseTotalSteps = totalSteps;
  if (Array.isArray(snap.steps) && snap.steps.length) {
    agentPlanSteps = snap.steps;
    agentConfirmedSteps = snap.steps;
  }
  goToStep(3);
  updateStepBar(3);
  setAgentProgressBarVisible(!isAutonomousRunMode(runMode));
  const cancelBtn = document.getElementById('cancelAgentRunBtn');
  if (cancelBtn) uiShow(cancelBtn, 'inline-flex');
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;
  const stepsForUi = agentConfirmedSteps.length ? agentConfirmedSteps : (snap.steps || []);
  renderAgentExecutionProgress(stepsForUi, runMode);
  if (!isAutonomousRunMode(runMode)) {
    updateAgentProgress(0, totalSteps, '正在恢复进度…');
  }
  updateThoughtSidebarVisibility();

  let completed = 0;
  const replayCtx = {
    totalSteps,
    onProgress: (n, label) => updateAgentProgress(n, totalSteps, label),
    bumpDone: () => { completed += 1; },
  };
  for (const ev of statusResp.events || []) {
    if (ev.type !== 'heartbeat') {
      agentSseEventIndex += 1;
    }
    handleAgentSSEEvent(ev, replayCtx);
  }
  persistAgentActiveRun({ sseSince: agentSseEventIndex });

  if (agentRunFinished) {
    clearAgentActiveRun();
    return;
  }

  if (statusResp.status === 'running') {
    showToast('已恢复执行中的任务', 'info');
    connectAgentSSE(agentRunId, totalSteps, agentSseEventIndex);
    return;
  }

  clearAgentActiveRun();
  if (agentRunId) {
    finishAgentRunUI(false);
  }
}

async function pollServerHealth(maxMs = 15000) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    if (serverBootstrapDone) return true;
    if (serverStartupFailed) return false;
    try {
      const resp = await fetch(`http://localhost:${serverPort}/api/health`);
      if (resp.ok) return true;
    } catch (_) { /* retry */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function init() {
  serverPort = await window.electronAPI.getServerPort();
  await initSettingsStorage();

  window.electronAPI.onServerReady(() => {
    runServerReadyBootstrap();
  });

  window.electronAPI.onServerError((msg) => {
    serverStartupFailed = true;
    document.getElementById('loadingStatus').textContent = '后端启动失败: ' + msg;
    setServerStatus(false);
    setTimeout(() => {
      hideLoading();
      loadSettings();
      renderHistory();
    }, 2000);
  });

  // 兜底：避免 server-ready 早于监听绑定导致前端一直“连接中”
  try {
    const status = await window.electronAPI.getServerStatus();
    if (status?.ready) {
      runServerReadyBootstrap();
    } else if (status?.error) {
      serverStartupFailed = true;
      document.getElementById('loadingStatus').textContent = '后端启动失败: ' + status.error;
      setServerStatus(false);
    }
  } catch (_) { /* optional */ }

  // UI 解锁：本地设置可先加载；后端 API 仅在后端就绪（IPC 或 health 轮询）后调用
  setTimeout(async () => {
    hideLoading();
    if (serverBootstrapDone || serverStartupFailed) return;
    loadSettings();
    renderHistory();
    if (await pollServerHealth()) {
      runServerReadyBootstrap();
    } else if (!serverBootstrapDone && !serverStartupFailed) {
      setServerStatus(false);
    }
  }, 5000);

  initMonaco();
  initAgentPlanWatchers();
  initRevisePanelUI();
  initDeliverableWorkspaceUI();
  initUploadInputUI();
  renderDocumentList();
  switchSettingsPane(_activeSettingsPane);
  window.addEventListener('resize', updateDocumentListEmptyHint);
}

function initUploadInputUI() {
  bindUploadPasteTextarea();
  setUploadInputMode('paste');
}

function setUploadInputMode(mode) {
  uploadInputMode = mode === 'file' ? 'file' : 'paste';
  const uploadArea = document.getElementById('uploadArea');
  const pastePanel = document.getElementById('uploadPastePanel');
  const filePanel = document.getElementById('uploadFilePanel');
  document.querySelectorAll('.upload-mode-tab').forEach((btn) => {
    btn.classList.toggle('active', btn.getAttribute('data-mode') === uploadInputMode);
  });
  if (pastePanel) pastePanel.classList.toggle('is-hidden', uploadInputMode !== 'paste');
  if (filePanel) filePanel.classList.toggle('is-hidden', uploadInputMode !== 'file');
  if (uploadArea) {
    uploadArea.classList.toggle('upload-mode-paste', uploadInputMode === 'paste');
    uploadArea.classList.toggle('upload-mode-file', uploadInputMode === 'file');
  }
  if (uploadInputMode === 'paste') {
    document.getElementById('uploadPasteText')?.focus();
  }
}

function bindUploadPasteTextarea() {
  const textarea = document.getElementById('uploadPasteText');
  if (!textarea) return;
  textarea.addEventListener('input', updateUploadPasteMeta);
  textarea.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      confirmUploadPaste();
    }
  });
  updateUploadPasteMeta();
}

function updateUploadPasteMeta() {
  const meta = document.getElementById('uploadPasteMeta');
  const textarea = document.getElementById('uploadPasteText');
  if (!meta || !textarea) return;
  const len = textarea.value.trim().length;
  meta.textContent = len ? `约 ${len.toLocaleString()} 字 · Ctrl+Enter 快速添加` : 'Ctrl+Enter 快速添加';
}

function confirmUploadPaste() {
  const textarea = document.getElementById('uploadPasteText');
  if (addInlineTextDocument(textarea?.value || '', 'assignment')) {
    showToast('已添加题目文字', 'success');
    if (textarea) textarea.value = '';
    updateUploadPasteMeta();
  }
}

function focusUploadPaste() {
  goToStep(1);
  setUploadInputMode('paste');
  const textarea = document.getElementById('uploadPasteText');
  if (!textarea) return;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  textarea.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest' });
  textarea.focus();
}

function initDeliverableWorkspaceUI() {
  const grid = document.getElementById('deliverableGrid');
  if (!grid) return;
  window.addEventListener('resize', updateDeliverablePreviewChrome);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (grid.classList.contains('preview-open')) {
        toggleDeliverablePreview(false);
      }
      closeExportMenu();
    }
  });
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('exportMenu');
    if (menu && !menu.contains(e.target)) closeExportMenu();
  });
  updateDeliverablePreviewChrome();
}

function toggleExportMenu(event) {
  if (event) event.stopPropagation();
  const panel = document.getElementById('exportMenuPanel');
  const trigger = document.getElementById('exportMenuTrigger');
  if (!panel || !trigger) return;
  const open = panel.classList.contains('is-hidden');
  closeExportMenu();
  if (open) {
    panel.classList.remove('is-hidden');
    trigger.setAttribute('aria-expanded', 'true');
  }
}

function closeExportMenu() {
  const panel = document.getElementById('exportMenuPanel');
  const trigger = document.getElementById('exportMenuTrigger');
  if (panel) panel.classList.add('is-hidden');
  if (trigger) trigger.setAttribute('aria-expanded', 'false');
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
  if (document.getElementById('constraintAllowCuratedJars')?.checked) {
    out.push('allow_curated_jars');
  }
  if (document.getElementById('constraintProvenanceLabel')?.checked) {
    out.push('provenance_label');
  }
  return out;
}

function onJarConstraintChange(which) {
  const noJar = document.getElementById('constraintNoExternalJar');
  const allowJar = document.getElementById('constraintAllowCuratedJars');
  if (which === 'no_external_jar' && noJar?.checked && allowJar) {
    allowJar.checked = false;
  }
  if (which === 'allow_curated_jars' && allowJar?.checked && noJar) {
    noJar.checked = false;
  }
  onUserConstraintsChange();
}

function getProvenanceCustomLabel() {
  return document.getElementById('provenanceCustomLabel')?.value?.trim() || '';
}

function syncUserConstraintsUI(constraints) {
  const list = constraints || [];
  const skipEl = document.getElementById('constraintSkipValidation');
  const jarEl = document.getElementById('constraintNoExternalJar');
  const allowJarEl = document.getElementById('constraintAllowCuratedJars');
  const provEl = document.getElementById('constraintProvenanceLabel');
  if (skipEl) skipEl.checked = list.includes('skip_validation');
  if (jarEl) jarEl.checked = list.includes('no_external_jar');
  if (allowJarEl) allowJarEl.checked = list.includes('allow_curated_jars');
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
  ['solveLang', 'includeCodeCheck', 'includeUmlCheck', 'constraintSkipValidation', 'constraintNoExternalJar', 'constraintAllowCuratedJars', 'constraintProvenanceLabel'].forEach((id) => {
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

function onAutoRemediateChange() {
  const el = document.getElementById('autoRemediateSettings');
  persistSettingsPatch({ autoRemediate: el ? el.checked : true });
  onAutoRemediateMaxRoundsChange();
  updateStep2ModeBanner();
}

function getAutoRemediateMaxRounds() {
  const el = document.getElementById('autoRemediateMaxRoundsSettings');
  const raw = el ? parseInt(el.value, 10) : NaN;
  if (!Number.isFinite(raw)) return 1;
  return Math.max(0, Math.min(5, raw));
}

function onAutoRemediateMaxRoundsChange() {
  const rounds = getAutoRemediateMaxRounds();
  persistSettingsPatch({ autoRemediateMaxRounds: rounds });
  updateStep2ModeBanner();
}

function getMaxReplanRounds() {
  const el = document.getElementById('maxReplanRoundsSettings');
  const raw = el ? parseInt(el.value, 10) : NaN;
  if (!Number.isFinite(raw)) return 1;
  return Math.max(0, Math.min(5, raw));
}

function onMaxReplanRoundsChange() {
  persistSettingsPatch({ maxReplanRounds: getMaxReplanRounds() });
  updateStep2ModeBanner();
}

function resolveMaxReplanRoundsForRun() {
  const settings = readSettings();
  const raw = Number(settings.maxReplanRounds);
  if (!Number.isFinite(raw)) return 1;
  return Math.max(0, Math.min(5, raw));
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
    if (n) uiShow(exportBtn, 'inline-block');
    else uiHide(exportBtn);
  }
}

function clearAgentThoughtLog() {
  agentThoughtLog = [];
  lastThoughtLogPath = null;
  const exportBtn = document.getElementById('thoughtExportBtn');
  if (exportBtn) uiHide(exportBtn);
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
    uiShow(note, 'block');
  }
  if (openBtn) {
    if (filePath) uiShow(openBtn, 'inline-flex');
    else uiHide(openBtn);
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
    },
    sections,
    _meta: { source: 'parse', metadata: metadata || {} },
  };
}

function sectionStatusBadgeClass(sec, chars) {
  const mode = sec?.mode || 'auto';
  if (mode === 'skip') return 'skip';
  if (mode === 'preserve') return 'preserve';
  if (mode === 'user_provided') return 'user';
  if (chars > 0) return 'parsed';
  return 'pending';
}

function sectionStatusBadgeLabel(sec, chars) {
  const mode = sec?.mode || 'auto';
  if (mode === 'skip') return '不填';
  if (mode === 'preserve') return '保留原文';
  if (mode === 'user_provided') return '用我的内容';
  if (chars > 0) return `约 ${chars} 字`;
  return '待填写';
}

function sectionStatusBadgeHtml(sec, chars) {
  const cls = sectionStatusBadgeClass(sec, chars);
  const label = sectionStatusBadgeLabel(sec, chars);
  return `<span class="section-status-badge ${cls}">${escapeHtml(label)}</span>`;
}

function refreshSectionStatusBadge(row, sec, chars) {
  const badge = row?.querySelector('.section-status-badge');
  if (!badge) return;
  badge.className = `section-status-badge ${sectionStatusBadgeClass(sec, chars)}`;
  badge.textContent = sectionStatusBadgeLabel(sec, chars);
}

function getCodeClozeParseInfo(questions, metadata) {
  if (!questions?.length) return null;
  if (metadata?.mixed_assignment && questions.length > 1) {
    const clozeQs = questions.filter((q) => q.type === 'code_cloze');
    const theoryCount = questions.filter((q) => q.type === 'theory').length;
    const blankCount = clozeQs.reduce((sum, q) => {
      const c = q.metadata?.code_cloze;
      return sum + (c?.blank_count || 0);
    }, 0);
    return {
      blankCount,
      mixed: true,
      segmentCount: questions.length,
      theoryCount,
      clozeCount: clozeQs.length,
    };
  }
  const q = questions[0];
  const cloze = q.metadata?.code_cloze || metadata?.code_cloze;
  const isCloze = q.type === 'code_cloze' || cloze?.is_code_cloze;
  if (!isCloze) return null;
  const blankCount = cloze?.blank_count
    ?? (Array.isArray(cloze?.blanks) ? cloze.blanks.length : 0);
  return { blankCount: blankCount || 0 };
}

function codeClozeParseBadgeLabel(blankCount) {
  return `代码填空 · 检测到 ${blankCount} 个空`;
}

function mixedAssignmentParseBadgeLabel(info) {
  const parts = [];
  if (info.theoryCount) parts.push(`简答 ${info.theoryCount}`);
  if (info.clozeCount) parts.push(`填空 ${info.blankCount} 空`);
  return parts.length
    ? `混排卷 · ${parts.join(' + ')}`
    : `混排卷 · ${info.segmentCount} 段`;
}

function formatCodeClozeParseBadgeText(questions, metadata) {
  const info = getCodeClozeParseInfo(questions, metadata);
  if (!info) return '';
  if (info.mixed) return mixedAssignmentParseBadgeLabel(info);
  if (info.blankCount < 1) return '';
  return codeClozeParseBadgeLabel(info.blankCount);
}

function hideCodeClozeParseBadge() {
  const badge = document.getElementById('codeClozeParseBadge');
  if (badge) uiHide(badge);
}

function renderCodeClozeParseBadge(questions, metadata) {
  const badge = document.getElementById('codeClozeParseBadge');
  const textEl = document.getElementById('codeClozeParseBadgeText');
  if (!badge || !textEl) return;
  const label = formatCodeClozeParseBadgeText(questions, metadata);
  if (!label) {
    hideCodeClozeParseBadge();
    return;
  }
  textEl.textContent = label;
  uiShow(badge, 'flex');
  if (window.Icons?.initDataIcons) Icons.initDataIcons(badge);
}

function updateQuestionsPanelSummary(questions) {
  const summary = document.getElementById('step2QuestionsSummaryText');
  const panel = document.getElementById('step2QuestionsPanel');
  const count = questions?.length || 0;
  if (!summary) return;
  if (count === 0) {
    summary.textContent = '未检测到题目';
    if (panel) panel.open = false;
    return;
  }
  const clozeInfo = getCodeClozeParseInfo(questions, parsedMetadata);
  if (clozeInfo?.mixed) {
    const parts = [];
    if (clozeInfo.theoryCount) parts.push(`简答 ${clozeInfo.theoryCount} 道`);
    if (clozeInfo.clozeCount) parts.push(`代码填空 ${clozeInfo.blankCount} 空`);
    summary.textContent = parts.length ? `混排卷 · ${parts.join(' + ')}` : `混排卷 · ${clozeInfo.segmentCount} 段`;
  } else if (clozeInfo) {
    summary.textContent = codeClozeParseBadgeLabel(clozeInfo.blankCount);
  } else if (questions[0]?.type === 'lab_report') {
    summary.textContent = '实验报告（1 份）';
  } else {
    summary.textContent = `检测到 ${count} 道题目`;
  }
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
    const tpl = specMap[sec.id];
    const tplHint = tpl?.avg_chars
      ? `模版建议约 ${tpl.avg_chars} 字${tpl.requires_images ? '，需配图' : ''}`
      : '';

    const row = document.createElement('div');
    row.className = 'section-row section-card';
    row.dataset.sectionId = sec.id;
    const modeOpts = FILL_MODE_OPTIONS.map(
      (o) => `<option value="${o.value}" ${sec.mode === o.value ? 'selected' : ''}>${o.label}</option>`
    ).join('');

    row.innerHTML = `
      <div class="section-row-head">
        <span class="section-row-title">${escapeHtml(def.label)}</span>
        ${sectionStatusBadgeHtml(sec, chars)}
        <div class="section-row-mode-wrap">
          <select class="section-row-mode" data-section-idx="${idx}" aria-label="填写方式">${modeOpts}</select>
        </div>
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
      refreshSectionStatusBadge(row, agentSectionsConfig.sections[idx], chars);
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
    list.innerHTML = emptyStateHtml('clipboard-list', '未检测到实训表格结构', '请确认报告版式为 training_table，或尝试重新解析');
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
    row.className = 'section-row section-card';
    row.dataset.tableKey = key;

    const modeOpts = FILL_MODE_OPTIONS.map(
      (o) => `<option value="${o.value}" ${cfg.mode === o.value ? 'selected' : ''}>${o.label}</option>`
    ).join('');
    const pseudoSec = { mode: cfg.mode };
    const excerptChars = (entry.text_excerpt || '').length;

    row.innerHTML = `
      <div class="section-row-head">
        <span class="section-row-title">${escapeHtml(label)}</span>
        ${excerptChars > 0
          ? `<span class="section-status-badge parsed">有原文</span>`
          : `<span class="section-status-badge pending">待填写</span>`}
        <div class="section-row-mode-wrap">
          <select class="section-row-mode" data-table-key="${key}" aria-label="填写方式">${modeOpts}</select>
        </div>
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
      pseudoSec.mode = cfg.mode;
      refreshSectionStatusBadge(row, pseudoSec, excerptChars);
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
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
    uiHide(wrap);
    wrap.innerHTML = '';
    return;
  }
  uiShow(wrap, 'flex');
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
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
  const wrap = document.querySelector('.sidebar-status');
  if (online) {
    dot.className = 'status-dot online';
    if (text) text.textContent = '在线';
    if (wrap) wrap.title = '在线';
  } else {
    dot.className = 'status-dot error';
    if (text) text.textContent = '离线';
    if (wrap) wrap.title = '离线';
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

let _activeSettingsPane = 'settings-pane-runmode';

function switchSettingsPane(paneId) {
  _activeSettingsPane = paneId;
  document.querySelectorAll('.settings-nav-item').forEach((btn) => {
    const active = btn.dataset.settingsPane === paneId;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.settings-pane').forEach((pane) => {
    const active = pane.id === paneId;
    pane.classList.toggle('active', active);
    pane.hidden = !active;
  });
  if (paneId === 'settings-pane-ai') {
    refreshSkillCandidates().catch(() => {});
  }
}

async function refreshSkillCandidates() {
  const listEl = document.getElementById('skillCandidatesList');
  if (!listEl) return;
  listEl.innerHTML = '<p class="form-hint">加载中…</p>';
  try {
    const resp = await apiGet('/api/skill-candidates?status=pending');
    const items = Array.isArray(resp.candidates) ? resp.candidates : [];
    if (!items.length) {
      listEl.innerHTML = '<p class="form-hint">暂无待处理候选（重复错误分类或 notes 达阈值后会出现）</p>';
      return;
    }
    listEl.innerHTML = items.map((c) => {
      const id = escapeHtml(c.id || '');
      const source = escapeHtml(c.source || '');
      const occ = Number(c.occurrences) || 0;
      const trigger = escapeHtml(c.suggested_trigger || '');
      const inject = escapeHtml(c.suggested_inject || '');
      return `<div class="skill-candidate-card" role="listitem" data-candidate-id="${id}">
        <div class="skill-candidate-head"><strong>${id}</strong> <span class="form-hint">×${occ}</span></div>
        <div class="form-hint">${source}</div>
        <div class="form-hint">触发: ${trigger}</div>
        <textarea class="form-input skill-candidate-inject" rows="3" placeholder="注入 prompt 的文本（可编辑）">${inject}</textarea>
        <button type="button" class="btn-primary btn-sm skill-candidate-promote-btn" data-candidate-id="${id}">写入 skill_store</button>
      </div>`;
    }).join('');
    listEl.querySelectorAll('.skill-candidate-promote-btn').forEach((btn) => {
      btn.addEventListener('click', () => promoteSkillCandidate(btn.dataset.candidateId));
    });
  } catch (e) {
    listEl.innerHTML = `<p class="form-hint">加载失败: ${escapeHtml(e.message || String(e))}</p>`;
  }
}

async function promoteSkillCandidate(candidateId) {
  if (!candidateId) return;
  const card = document.querySelector(`.skill-candidate-card[data-candidate-id="${CSS.escape(candidateId)}"]`);
  const inject = card?.querySelector('.skill-candidate-inject')?.value?.trim() || '';
  try {
    const resp = await apiPost('/api/skill-candidates/promote', { id: candidateId, inject });
    showToast(`已 promote 技能 ${candidateId}${resp.insights_updated ? '（已更新 AI_INSIGHTS）' : ''}`);
    await refreshSkillCandidates();
  } catch (e) {
    showToast(`Promote 失败: ${e.message || e}`, 'error');
  }
}

// ============================
// 步骤控制
// ============================

function goToStep(n) {
  if (n === 4) {
    goToStep(3);
    showExportSuccessPanel();
    return;
  }
  if (n !== 3) hideExportSuccessPanel();
  document.querySelectorAll('.step-content').forEach(el => el.classList.remove('active'));
  document.getElementById(`step-${n}`).classList.add('active');
  updateStepBar(n);
  if (n === 2) {
    updateStep2ModeBanner();
    if (parsedQuestions.length > 0) showModeSwitchBar();
  }
}

function updateStepBar(currentStep) {
  const step = Math.min(Math.max(currentStep, 1), 3);
  document.querySelectorAll('.step').forEach((el) => {
    const stepNum = Number(el.dataset.step);
    el.classList.remove('active', 'done');
    if (stepNum < step) el.classList.add('done');
    else if (stepNum === step) el.classList.add('active');
  });
  document.querySelectorAll('.step-line').forEach((line) => {
    const after = Number(line.dataset.afterStep);
    line.classList.toggle('done', after < step);
  });
}

function showExportSuccessPanel() {
  const panel = document.getElementById('exportSuccessPanel');
  if (!panel) return;
  uiShow(panel, 'block');
  requestAnimationFrame(() => panel.classList.add('visible'));
  panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideExportSuccessPanel() {
  const panel = document.getElementById('exportSuccessPanel');
  if (!panel) return;
  panel.classList.remove('visible');
  uiHide(panel);
}

function updateStep3CompletionActions() {
  const show = agentRunFinished && !agentExecutionMode;
  ['step3HomeBtn', 'exportActionHomeBtn'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (show) uiShow(el, 'inline-flex');
    else uiHide(el);
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

function updateDocumentListEmptyHint() {
  const emptyHint = document.querySelector('#documentListEmpty .empty-state-hint');
  if (!emptyHint) return;
  const narrow = window.matchMedia('(max-width: 959px)').matches;
  emptyHint.textContent = narrow
    ? '粘贴题目文字，或点击「+ 添加」上传文件'
    : '在左侧粘贴文字，或切换到「上传文件」添加 docx / pdf';
}

function renderDocumentList() {
  const list = document.getElementById('documentList');
  const empty = document.getElementById('documentListEmpty');
  const parseBtn = document.getElementById('parseDocumentsBtn');
  const uploadHint = document.getElementById('uploadAreaHint');
  const uploadArea = document.getElementById('uploadArea');
  const listCount = document.getElementById('documentListCount');
  if (!list) return;

  list.querySelectorAll('tr.document-list-item').forEach((el) => el.remove());
  if (empty) empty.style.display = uploadedDocuments.length ? 'none' : 'table-row';
  if (listCount) {
    listCount.textContent = String(uploadedDocuments.length);
    listCount.classList.toggle('is-hidden', uploadedDocuments.length === 0);
  }
  if (parseBtn) parseBtn.disabled = uploadedDocuments.length === 0 && assignmentImageItems.length === 0;
  updateDocumentListEmptyHint();

  if (uploadArea) {
    uploadArea.classList.toggle('has-documents', uploadedDocuments.length > 0);
  }

  // Update upload area hint text
  if (uploadHint) {
    uploadHint.textContent = uploadedDocuments.length
      ? '拖拽或点击添加更多文档（已添加 ' + uploadedDocuments.length + ' 个）'
      : '支持 .doc / .docx / .pdf；仅题目文字请用「粘贴题目」';
  }

  const onlyInline = uploadedDocuments.length > 0
    && uploadedDocuments.every((d) => d.isInline);
  const parseLead = document.querySelector('.upload-paste-lead');
  if (parseLead && uploadInputMode === 'paste') {
    parseLead.innerHTML = onlyInline
      ? '题目文字已添加，点右侧「解析并继续」即可，<strong>无需再上传文件</strong>'
      : '从超星、慕课等平台复制题目文字，粘贴到下方即可开始，<strong>无需上传文件</strong>';
  }

  const hasParsed = uploadedDocuments.some((d) => d.resolvedRole);

  uploadedDocuments.forEach((doc) => {
    const row = document.createElement('tr');
    row.className = 'document-list-item';
    row.dataset.localId = doc.localId;

    const formatIcon = ico(DOC_FORMAT_ICONS[doc.docFormat] || 'file-text', 'doc-format-icon');
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
      templateFormatBadge = `<span class="doc-template-badge" title="格式已分析：${escapeHtml(summary)}">${ico('ruler', 'icon-xs')} 格式已分析</span>`;
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
      parseStatus = `<span class="doc-parse-status parsed" title="已解析">${ico('check', 'icon-xs')}</span>`;
    }

    row.innerHTML = `
      <td class="col-filename">
        <div class="doc-filename-cell">
          <span class="doc-format-icon">${formatIcon}</span>
          <span class="doc-name" title="${escapeHtml(doc.path || doc.fileName)}">${escapeHtml(doc.fileName)}</span>
          ${parseStatus}
          ${statsHtml}
          ${templateFormatBadge}
        </div>
      </td>
      <td class="col-role">
        <div class="doc-role-cell">
          ${resolvedBadge}
          <select class="doc-role-select" data-local-id="${doc.localId}">${roleOpts}</select>
        </div>
      </td>
      <td class="col-actions">
        <button type="button" class="btn-ghost btn-sm doc-remove-btn" data-remove-id="${doc.localId}" title="移除" aria-label="移除">${ico('x', 'icon-sm')}</button>
      </td>
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
  focusUploadPaste();
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

  const clozeInfo = getCodeClozeParseInfo(parsedQuestions, parsedMetadata);
  const clozeLabel = formatCodeClozeParseBadgeText(parsedQuestions, parsedMetadata);
  const clozeChip = clozeLabel
    ? `<span class="doc-summary-chip doc-summary-chip-cloze">${escapeHtml(clozeLabel)}</span>`
    : '';

  bar.innerHTML = `
    <span class="doc-summary-label">已解析 ${uploadedDocuments.length} 个文档：</span>
    ${parts.join(' ')}
    ${clozeChip}
    <span class="doc-summary-hint">角色可手动调整后重新解析</span>
  `;

  const tableWrap = panel.querySelector('.document-table-wrap');
  const actions = panel.querySelector('.document-list-actions');
  if (tableWrap) {
    tableWrap.before(bar);
  } else if (actions) {
    actions.before(bar);
  } else {
    panel.appendChild(bar);
  }
}

function nextAssignmentImageId() {
  return `img-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
}

function normalizeAssignmentImageOrder() {
  assignmentImageItems.forEach((item, idx) => {
    item.order = idx;
  });
}

function addAssignmentImagePaths(filePaths) {
  let added = 0;
  for (const fp of filePaths || []) {
    const fileName = fp.split(/[\\/]/).pop() || 'image.png';
    const lower = fileName.toLowerCase();
    if (!/\.(png|jpe?g|gif|webp|bmp|tiff?)$/.test(lower)) continue;
    if (assignmentImageItems.some((d) => d.path === fp)) continue;
    assignmentImageItems.push({
      localId: nextAssignmentImageId(),
      path: fp,
      fileName,
      includeOcr: true,
      order: assignmentImageItems.length,
    });
    added += 1;
  }
  if (added) {
    normalizeAssignmentImageOrder();
    renderAssignmentImageStrip();
    markAgentPlanStale();
    renderDocumentList();
    const fold = document.getElementById('step1AssignmentImagesFold');
    if (fold) fold.open = true;
  }
  return added;
}

async function triggerAddAssignmentImages() {
  if (!window.electronAPI?.openImageDialog) {
    showToast('当前环境不支持图片选择', 'error');
    return;
  }
  const result = await window.electronAPI.openImageDialog();
  if (result.canceled || !result.filePaths?.length) return;
  const added = addAssignmentImagePaths(result.filePaths);
  if (added) showToast(`已添加 ${added} 张题目图片`, 'success');
}

function removeAssignmentImage(localId) {
  assignmentImageItems = assignmentImageItems.filter((d) => d.localId !== localId);
  normalizeAssignmentImageOrder();
  renderAssignmentImageStrip();
  markAgentPlanStale();
  renderDocumentList();
}

function clearAssignmentImages() {
  assignmentImageItems = [];
  renderAssignmentImageStrip();
  markAgentPlanStale();
  renderDocumentList();
}

function toggleAssignmentImageOcr(localId, checked) {
  const item = assignmentImageItems.find((d) => d.localId === localId);
  if (item) {
    item.includeOcr = !!checked;
    markAgentPlanStale();
    renderAssignmentImageStrip();
  }
}

const VISION_MODEL_HINTS = [
  'gpt-4o', 'gpt-4-turbo', 'gpt-4-vision', 'gpt-4.1', 'o1', 'o3',
  'glm-4v', 'glm4v', 'qwen-vl', 'qwen2-vl', 'qwen3-vl',
  'deepseek-vl', 'deepseek-v2', 'claude-3', 'claude-sonnet', 'claude-opus',
  'claude-haiku', 'vision', 'vl-', '-vl',
];

function supportsVisionModel(settings) {
  const s = settings || readSettings();
  const provider = (s.provider || 'deepseek').toLowerCase();
  const model = (s.model || 'deepseek-v4-flash').toLowerCase();
  if (provider === 'claude') {
    return ['claude-3', 'claude-sonnet', 'claude-opus', 'claude-haiku'].some((x) => model.includes(x));
  }
  return VISION_MODEL_HINTS.some((h) => model.includes(h));
}

function countAssignmentImagesIncluded() {
  return assignmentImageItems.filter((d) => d.includeOcr !== false).length;
}

function renderAssignmentImageModeHint() {
  const hint = document.getElementById('assignmentImageModeHint');
  if (!hint) return;

  const settings = readSettings();
  const mode = settings.imageReadingMode || 'ocr_only';
  const ocrOn = settings.enableImageOcr === true;
  const visionMax = parseInt(settings.imageVisionMaxPages, 10) || 5;
  const ocrMax = parseInt(settings.imageOcrMaxPages, 10) || 20;
  const included = countAssignmentImagesIncluded();
  const total = assignmentImageItems.length;
  const visionCapable = supportsVisionModel(settings);
  const parts = [];
  let warn = false;

  const modeLabel = { ocr_only: '仅 OCR', hybrid: '混合', vision: '仅 Vision' }[mode] || mode;
  parts.push(`识图模式：${modeLabel}`);
  parts.push(ocrOn ? 'OCR 已开启' : 'OCR 未开启（正文极短/扫描 PDF 仍可能自动 OCR）');

  if (total) {
    parts.push(`已选 ${total} 张，${included} 张参与识题`);
  }

  if (mode === 'ocr_only') {
    if (total && included > ocrMax) {
      parts.push(`超过 OCR 上限 ${ocrMax} 张，解析时可能截断`);
      warn = true;
    }
  } else {
    if (!visionCapable) {
      parts.push('当前模型可能不支持 Vision，混合/仅 Vision 将回退或跳过');
      warn = true;
    } else if (needsUserApiKey(settings)) {
      parts.push('混合/仅 Vision 需要 API Key');
      warn = true;
    }
    if (included > visionMax) {
      parts.push(`参与识题 ${included} 张，超过 Vision 上限 ${visionMax} 张（将提示 vision_limit_exceeded）`);
      warn = true;
    }
  }

  if (!total && !ocrOn && mode === 'ocr_only') {
    uiHide(hint);
    return;
  }

  hint.textContent = parts.join(' · ');
  hint.classList.toggle('is-warn', warn);
  uiShow(hint, 'block');
}

function moveAssignmentImage(dragId, targetId) {
  if (!dragId || dragId === targetId) return;
  const fromIdx = assignmentImageItems.findIndex((d) => d.localId === dragId);
  const toIdx = assignmentImageItems.findIndex((d) => d.localId === targetId);
  if (fromIdx < 0 || toIdx < 0) return;
  const [moved] = assignmentImageItems.splice(fromIdx, 1);
  assignmentImageItems.splice(toIdx, 0, moved);
  normalizeAssignmentImageOrder();
  renderAssignmentImageStrip();
  markAgentPlanStale();
}

function renderAssignmentImageStrip() {
  const strip = document.getElementById('assignmentImageStrip');
  const empty = document.getElementById('assignmentImageEmpty');
  const clearBtn = document.getElementById('clearAssignmentImagesBtn');
  if (!strip) return;

  if (!assignmentImageItems.length) {
    strip.innerHTML = '';
    uiHide(strip);
    if (empty) uiShow(empty, 'block');
    if (clearBtn) uiHide(clearBtn);
    return;
  }

  if (empty) uiHide(empty);
  uiShow(strip, 'flex');
  if (clearBtn) uiShow(clearBtn, 'inline-flex');

  strip.innerHTML = '';
  assignmentImageItems.forEach((item, idx) => {
    const included = item.includeOcr !== false;
    const card = document.createElement('div');
    card.className = 'assignment-image-card' + (included ? '' : ' is-excluded');
    card.draggable = true;
    card.dataset.id = item.localId;
    card.innerHTML = `
      <span class="img-order-badge" title="解析顺序">${idx + 1}</span>
      <button type="button" class="img-remove-btn" title="移除" aria-label="移除图片">${Icons.iconHtml('x', { className: 'icon-xs' })}</button>
      <img alt="" loading="lazy" />
      <div class="assignment-image-card-footer">
        <label title="勾选后纳入识题（OCR / Vision）">
          <input type="checkbox" ${included ? 'checked' : ''} aria-label="参与识题" />
          <span class="assignment-image-card-name" title="${escapeHtml(item.fileName)}">${escapeHtml(item.fileName)}</span>
        </label>
      </div>
    `;

    const imgEl = card.querySelector('img');
    if (imgEl) {
      const fileUrl = 'file:///' + item.path.replace(/\\/g, '/').replace(/^\/+/, '');
      imgEl.src = fileUrl;
    }

    card.querySelector('.img-remove-btn')?.addEventListener('click', (e) => {
      e.stopPropagation();
      removeAssignmentImage(item.localId);
    });
    card.querySelector('input[type="checkbox"]')?.addEventListener('change', (e) => {
      toggleAssignmentImageOcr(item.localId, e.target.checked);
    });

    card.addEventListener('dragstart', (e) => {
      assignmentImageDragId = item.localId;
      card.classList.add('is-dragging');
      strip.classList.add('is-dragging');
      if (e.dataTransfer) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', item.localId);
      }
    });
    card.addEventListener('dragend', () => {
      assignmentImageDragId = null;
      card.classList.remove('is-dragging');
      strip.classList.remove('is-dragging');
      strip.querySelectorAll('.is-drop-target').forEach((el) => el.classList.remove('is-drop-target'));
    });
    card.addEventListener('dragover', (e) => {
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'move';
      card.classList.add('is-drop-target');
    });
    card.addEventListener('dragleave', () => {
      card.classList.remove('is-drop-target');
    });
    card.addEventListener('drop', (e) => {
      e.preventDefault();
      card.classList.remove('is-drop-target');
      const dragId = assignmentImageDragId || (e.dataTransfer && e.dataTransfer.getData('text/plain'));
      moveAssignmentImage(dragId, item.localId);
    });

    strip.appendChild(card);
  });
  renderAssignmentImageModeHint();
}

function imageSectionSeparator(order, source) {
  if (source === 'vision') {
    return `\n\n--- 图 ${order} ---\n\n`;
  }
  return `\n\n--- 图 ${order}（OCR）---\n\n`;
}

function computeAssignmentBodyPrefix(fullText, sections, imageMerged) {
  const full = (fullText || '').trim();
  const merged = (imageMerged || '').trim();
  if (merged && full.endsWith(merged)) {
    return full.slice(0, full.length - merged.length).trim();
  }
  if (sections && sections.length) {
    let rest = full;
    sections.forEach((sec, idx) => {
      const order = idx + 1;
      const sep = imageSectionSeparator(order, sec.source || 'ocr');
      const chunk = sep + (sec.text || '');
      if (rest.includes(chunk)) {
        rest = rest.replace(chunk, '').trim();
      }
    });
    return rest;
  }
  return sections && sections.length ? '' : full;
}

function rebuildAssignmentTextFromSections() {
  const parts = [];
  (agentImageSections || []).forEach((sec, idx) => {
    const text = (sec.text || '').trim();
    if (!text) return;
    parts.push(imageSectionSeparator(idx + 1, sec.source || 'ocr') + text);
  });
  const merged = parts.join('').trim();
  const body = (agentAssignmentBodyPrefix || '').trim();
  if (body && merged) return body + '\n\n' + merged;
  return merged || body;
}

function syncAssignmentPreviewTextarea() {
  const textEl = document.getElementById('assignmentPreviewText');
  if (!textEl) return;
  const rebuilt = rebuildAssignmentTextFromSections();
  if (rebuilt) {
    textEl.value = rebuilt;
    agentAssignmentText = rebuilt;
  }
}

function onAssignmentSectionTextInput(index, value) {
  if (!agentImageSections[index]) return;
  agentImageSections[index].text = value;
  syncAssignmentPreviewTextarea();
  agentAssignmentPreviewConfirmed = false;
  const chk = document.getElementById('assignmentPreviewConfirm');
  if (chk) chk.checked = false;
  markAgentPlanStale();
}

function onAssignmentPreviewTextInput() {
  const textEl = document.getElementById('assignmentPreviewText');
  agentAssignmentText = textEl?.value || '';
  agentAssignmentPreviewConfirmed = false;
  const chk = document.getElementById('assignmentPreviewConfirm');
  if (chk) chk.checked = false;
  markAgentPlanStale();
}

function onAssignmentPreviewConfirmChange() {
  const chk = document.getElementById('assignmentPreviewConfirm');
  agentAssignmentPreviewConfirmed = chk?.checked === true;
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

function setStep1PrimaryMode(mode) {
  const parseActions = document.querySelector('.document-list-actions');
  const splitBtn = document.getElementById('splitConfirmBtn');
  if (parseActions) {
    parseActions.style.display = mode === 'split' ? 'none' : '';
  }
  if (splitBtn && mode !== 'split') {
    uiHide(splitBtn);
  }
}

function hideSplitPreview() {
  agentAwaitingSplitConfirm = false;
  const panel = document.getElementById('splitPreviewPanel');
  const confirmBtn = document.getElementById('splitConfirmBtn');
  if (panel) uiHide(panel);
  if (confirmBtn) uiHide(confirmBtn);
  setStep1PrimaryMode('idle');
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

  uiShow(panel, 'block');
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

  if (confirmBtn) {
    if (agentAwaitingSplitConfirm) uiShow(confirmBtn, 'inline-flex');
    else uiHide(confirmBtn);
  }
  setStep1PrimaryMode('split');

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  panel.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest' });
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
  if (confirmBtn) uiHide(confirmBtn);
  setStep1PrimaryMode('idle');
  goToStep(2);
  updateStepBar(2);
}

async function buildDocumentsPayload() {
  if (!uploadedDocuments.length && !assignmentImageItems.length) {
    throw new Error('请先粘贴题目文字、添加文档或题目图片');
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
  const payload = { documents, ...getImageOcrPayload() };
  if (assignmentImageItems.length) {
    const assignment_images = [];
    for (let i = 0; i < assignmentImageItems.length; i += 1) {
      const item = assignmentImageItems[i];
      assignment_images.push({
        id: item.localId,
        file_name: item.fileName,
        file_data: await window.electronAPI.readFileBase64(item.path),
        order: i,
        include_in_ocr: item.includeOcr !== false,
      });
    }
    payload.assignment_images = assignment_images;
  }
  return payload;
}

function applyParseResponse(resp, fileName) {
  parsedQuestions = resp.questions || (resp.question ? [resp.question] : []);
  renderQuestions(parsedQuestions);

  renderParseOcrBanner(resp.warnings || []);
  (resp.warnings || []).forEach((w) => {
    if (w && w.message && w.action !== 'enable_ocr_reparse') {
      showToast(w.message, 'warning');
    }
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
  agentImageAssets = resp.image_assets || parsedQuestions[0]?.image_assets || [];
  agentImageSections = resp.image_sections || parsedQuestions[0]?.image_sections || [];
  agentImageReadSummary = resp.image_read_summary || parsedQuestions[0]?.image_read_summary || null;
  agentImageReadingMode = resp.image_reading_mode || parsedQuestions[0]?.image_reading_mode || 'ocr_only';
  agentAssignmentFromImages = !!(resp.assignment_from_images || parsedQuestions[0]?.assignment_from_images);
  agentParseImageWarnings = (resp.warnings || []).filter((w) => w && (
    w.code === 'vision_limit_exceeded'
    || w.code === 'vision_unavailable'
    || w.code === 'vision_no_api_key'
    || w.code === 'multi_question_in_image'
    || w.code === 'multiple_assignment_images'
  ));
  agentAssignmentPreviewConfirmed = false;
  const imageMerged = (resp.metadata || parsedQuestions[0]?.metadata || {}).image_ocr_merged
    || resp.image_ocr_merged
    || '';
  agentAssignmentBodyPrefix = computeAssignmentBodyPrefix(
    agentAssignmentText,
    agentImageSections,
    imageMerged,
  );
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
    uiShow(document.getElementById('detectInfoCard'), 'flex');
    document.getElementById('detectCourse').textContent = meta.course || '—';
    document.getElementById('detectTitle').textContent = meta.experiment_title || '—';
    document.getElementById('detectMajor').textContent = meta.major || '—';
    renderLayoutBadge();
    renderSectionsDetectCard();
    renderTableMapPreview();
  } else {
    uiHide(document.getElementById('detectInfoCard'));
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
  renderAssignmentPreview(resp);
  renderCodeClozeParseBadge(parsedQuestions, meta);

  // Check runtime availability (fire-and-forget, non-blocking)
  checkAndPromptRuntimes().catch(() => {});
}

function getImageOcrPayload(settings) {
  const s = settings || readSettings();
  const maxPages = parseInt(s.imageOcrMaxPages, 10);
  const visionMax = parseInt(s.imageVisionMaxPages, 10);
  const readingMode = s.imageReadingMode || 'ocr_only';
  const payload = {
    enableImageOcr: s.enableImageOcr === true,
    imageOcrLang: s.imageOcrLang || 'chi_sim+eng',
    imageReadingMode: readingMode,
    imageOcrMaxPages: Number.isFinite(maxPages) && maxPages > 0 ? maxPages : 20,
    imageVisionMaxPages: Number.isFinite(visionMax) && visionMax > 0 ? visionMax : 5,
  };
  if (readingMode === 'hybrid' || readingMode === 'vision') {
    payload.api_key = s.apiKey || '';
    payload.provider = s.provider || 'deepseek';
    payload.model = s.model || 'deepseek-v4-flash';
    payload.customUrl = s.customUrl || '';
  }
  return payload;
}

function hideAssignmentPreview() {
  const panel = document.getElementById('assignmentPreviewPanel');
  if (panel) uiHide(panel);
  const sectionsEl = document.getElementById('assignmentImageSections');
  if (sectionsEl) {
    sectionsEl.innerHTML = '';
    uiHide(sectionsEl);
  }
  const warnEl = document.getElementById('assignmentPreviewWarn');
  if (warnEl) uiHide(warnEl);
  const confirmChk = document.getElementById('assignmentPreviewConfirm');
  if (confirmChk) confirmChk.checked = false;
  agentAssignmentPreviewConfirmed = false;
}

function renderAssignmentImageSectionsList(sections) {
  const host = document.getElementById('assignmentImageSections');
  if (!host) return;
  const items = sections || [];
  if (!items.length) {
    host.innerHTML = '';
    uiHide(host);
    return;
  }
  uiShow(host, 'flex');
  host.innerHTML = '';
  items.forEach((sec, idx) => {
    const source = (sec.source || 'ocr').toLowerCase();
    const sourceLabel = source === 'vision' ? 'Vision' : 'OCR';
    const card = document.createElement('div');
    card.className = 'assignment-section-card';
    card.innerHTML = `
      <div class="assignment-section-card-header">
        <span>图 ${idx + 1}</span>
        <span class="assignment-section-source source-${source === 'vision' ? 'vision' : 'ocr'}">${sourceLabel}</span>
        <span class="form-hint">${escapeHtml(sec.image_id || '')}</span>
      </div>
      <textarea class="assignment-section-text" rows="3" aria-label="图 ${idx + 1} 识别文字"></textarea>
    `;
    const ta = card.querySelector('textarea');
    if (ta) {
      ta.value = sec.text || '';
      ta.addEventListener('input', (e) => onAssignmentSectionTextInput(idx, e.target.value));
    }
    host.appendChild(card);
  });
}

function renderAssignmentPreview(resp) {
  const panel = document.getElementById('assignmentPreviewPanel');
  const textEl = document.getElementById('assignmentPreviewText');
  const metaEl = document.getElementById('assignmentPreviewMeta');
  const hintEl = document.getElementById('assignmentPreviewHint');
  const warnEl = document.getElementById('assignmentPreviewWarn');
  if (!panel || !textEl) return;

  const assignmentText = (resp.assignment_text || agentAssignmentText || '').trim();
  const imageAssets = resp.image_assets || agentImageAssets || [];
  const sections = resp.image_sections || agentImageSections || [];
  const fromImages = !!(resp.assignment_from_images || agentAssignmentFromImages);
  const summary = resp.image_read_summary || agentImageReadSummary;
  const readingMode = resp.image_reading_mode || agentImageReadingMode || 'ocr_only';
  const imageWarns = agentParseImageWarnings.length
    ? agentParseImageWarnings
    : (resp.warnings || []).filter((w) => w && (
      w.code === 'vision_limit_exceeded'
      || w.code === 'vision_unavailable'
      || w.code === 'multi_question_in_image'
      || w.code === 'multiple_assignment_images'
    ));
  const shouldShow = fromImages || sections.length > 0 || (imageAssets.length > 0 && assignmentText);

  if (!shouldShow) {
    hideAssignmentPreview();
    return;
  }

  uiShow(panel, 'block');
  textEl.value = assignmentText || '（暂无合并题干，请开启 OCR / Vision 或粘贴题目）';
  agentAssignmentText = textEl.value;

  const modeLabels = { ocr_only: 'OCR', hybrid: '混合', vision: 'Vision' };
  if (hintEl) {
    if (fromImages) {
      hintEl.textContent = `已合并识图结果（${modeLabels[readingMode] || readingMode}），生成计划前请核对题干`;
    } else {
      hintEl.textContent = '检测到嵌入图片，生成计划前请确认题干是否完整';
    }
  }

  if (warnEl) {
    const msgs = imageWarns.map((w) => w.message).filter(Boolean);
    if (msgs.length) {
      warnEl.textContent = msgs.join('；');
      uiShow(warnEl, 'block');
    } else {
      uiHide(warnEl);
    }
  }

  renderAssignmentImageSectionsList(sections);

  const confirmChk = document.getElementById('assignmentPreviewConfirm');
  if (confirmChk) confirmChk.checked = false;
  agentAssignmentPreviewConfirmed = false;

  if (metaEl) {
    metaEl.innerHTML = '';
    const badges = [];
    if (readingMode && readingMode !== 'ocr_only') {
      badges.push(`<span class="ocr-meta-badge vision">${modeLabels[readingMode] || readingMode}</span>`);
    }
    if (summary) {
      if (summary.ocr_attempted != null) {
        badges.push(`<span class="ocr-meta-badge">OCR ${summary.ocr_attempted} 张</span>`);
      }
      if (summary.ocr_ok) {
        badges.push(`<span class="ocr-meta-badge ok">OCR 成功 ${summary.ocr_ok}</span>`);
      }
      if (summary.ocr_empty) {
        badges.push(`<span class="ocr-meta-badge warn">OCR 空 ${summary.ocr_empty}</span>`);
      }
      if (summary.vision_attempted) {
        badges.push(`<span class="ocr-meta-badge vision">Vision ${summary.vision_attempted} 张</span>`);
      }
      if (summary.vision_limit_exceeded) {
        badges.push(`<span class="ocr-meta-badge warn">Vision 超限 ${summary.vision_limit_exceeded}</span>`);
      }
      if (summary.merged_chars) {
        badges.push(`<span class="ocr-meta-badge">合并 ${summary.merged_chars} 字</span>`);
      }
    }
    if (sections.length) {
      badges.push(`<span class="ocr-meta-badge">${sections.length} 段图题</span>`);
    } else if (imageAssets.length) {
      badges.push(`<span class="ocr-meta-badge">${imageAssets.length} 张嵌入图</span>`);
    }
    if (badges.length) {
      metaEl.innerHTML = badges.join('');
      uiShow(metaEl, 'flex');
    } else {
      uiHide(metaEl);
    }
  }
}

function assignmentPreviewRequiresConfirm() {
  const panel = document.getElementById('assignmentPreviewPanel');
  return !!(panel && !panel.classList.contains('is-hidden'));
}

function renderParseOcrBanner(warnings) {
  const banner = document.getElementById('parseOcrBanner');
  const textEl = document.getElementById('parseOcrBannerText');
  const btn = document.getElementById('parseOcrEnableBtn');
  if (!banner || !textEl) return;

  const actionable = (warnings || []).filter((w) => w && w.action === 'enable_ocr_reparse');
  if (!actionable.length) {
    uiHide(banner);
    return;
  }

  uiShow(banner, 'flex');
  textEl.textContent = actionable.map((w) => w.message).join('；');
  if (btn) {
    const settings = readSettings();
    btn.disabled = false;
    btn.textContent = settings.enableImageOcr ? '重新解析（OCR 已开启）' : '开启 OCR 并重解析';
  }
}

async function enableOcrAndReparse() {
  const settings = readSettings();
  if (!settings.enableImageOcr) {
    persistSettingsPatch({ enableImageOcr: true });
    const chk = document.getElementById('enableImageOcrSettings');
    if (chk) chk.checked = true;
  }
  showToast('已开启图片 OCR，正在重新解析…', 'info');
  await parseAllDocuments({ stayOnStep: 1, quiet: true });
  showToast('OCR 重解析完成，请查看识题预览', 'success');
}

// ── DA4: section detection UI ──

function renderLayoutBadge() {
  const badgesHost = document.getElementById('detectHeroBadges');
  if (!badgesHost) return;
  let badge = badgesHost.querySelector('.layout-badge');
  const label = getLayoutBadgeLabel();
  if (!label) {
    if (badge) badge.remove();
    return;
  }
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'layout-badge';
    badgesHost.appendChild(badge);
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
    if (card) uiHide(card);
    return;
  }

  if (!card) {
    card = document.createElement('div');
    card.id = 'sectionsDetectCard';
    card.className = 'sections-detect-card';
    infoCard.after(card);
  }
  uiShow(card, 'block');

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
  if (card) uiHide(card);
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
    if (panel) uiHide(panel);
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
  uiShow(panel, 'block');

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
  if (panel) uiHide(panel);
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

    setHeadingIcon(titleEl, 'alert-triangle', '未检测到编程环境');
    const entries = ['python', 'java', 'c', 'node'].map((k) => {
      const rt = runtimes[k] || {};
      const statusIcon = ico(rt.available ? 'check-circle' : 'x-circle', 'icon-xs');
      const statusText = rt.available
        ? (rt.version || rt.version_info || '已安装')
        : '未安装';
      const btnHtml = !rt.available
        ? `<button class="btn-secondary btn-sm runtime-dl-btn" data-runtime="${k}">${icoLabel('download', `下载 ${rt.label || k}`, 'icon-sm')}</button>`
        : '';
      const autoBtn = (!rt.available && rt.can_auto_download)
        ? `<button class="btn-primary btn-sm runtime-auto-btn" data-runtime="${k}">${icoLabel('zap', '一键安装 JRE（约 50MB）', 'icon-sm')}</button>`
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

    if (checkWrap) uiHide(checkWrap);
    if (primaryBtn) {
      primaryBtn.textContent = '重新检测';
      uiShow(primaryBtn);
    }
    if (secondaryBtn) {
      secondaryBtn.textContent = '跳过安装，使用伪代码';
      uiShow(secondaryBtn);
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
          Icons.setIconText(btn, 'check-circle', '已安装', 'icon-sm');
        } catch (err) {
          showToast('JRE 下载失败: ' + err.message, 'error');
          btn.disabled = false;
          Icons.setIconText(btn, 'zap', '一键安装 JRE（约 50MB）', 'icon-sm');
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

function formatJarSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

function extractMissingJarsFromSolvePayload(payload) {
  const session = payload?.solve_session;
  const run = session?.run_result || {};
  if (run.reason !== 'missing_jar') return [];
  return (run.missing_jars || []).filter((j) => j && j.id);
}

function showJarConsentModal(missingJars) {
  return new Promise((resolve) => {
    const overlay = document.getElementById('complianceModal');
    const titleEl = document.getElementById('complianceModalTitle');
    const bodyEl = document.getElementById('complianceModalBody');
    const primaryBtn = document.getElementById('complianceModalPrimary');
    const secondaryBtn = document.getElementById('complianceModalSecondary');
    const checkWrap = document.getElementById('complianceModalCheckWrap');

    if (!overlay || !titleEl || !bodyEl || !missingJars?.length) {
      resolve('decline');
      return;
    }

    titleEl.textContent = '验证需要 Java 扩展库';
    const rows = missingJars.map((j) => `
      <div class="runtime-modal-row jar-modal-row">
        <span class="runtime-modal-name">${escapeHtml(j.label || j.id)}</span>
        <span class="runtime-modal-guide">${escapeHtml(j.purpose || '')}</span>
        <span class="jar-modal-size">约 ${formatJarSize(j.size_bytes)}</span>
      </div>
    `).join('');

    bodyEl.innerHTML = `
      <div class="runtime-modal-body">
        <p class="jar-modal-intro">
          内化验证沙箱需要以下白名单 jar 试编译/试跑。<strong>仅用于生成质量检查</strong>，不表示本应用能替代你的实验环境。
        </p>
        <div class="runtime-modal-entries">${rows}</div>
        <div class="runtime-modal-footer-hint">
          下载到本机验证沙箱目录；拒绝则跳过验证，你仍可复制代码自行运行。
        </div>
      </div>`;

    if (checkWrap) uiHide(checkWrap);
    if (primaryBtn) {
      primaryBtn.textContent = '同意下载并继续验证';
      uiShow(primaryBtn);
    }
    if (secondaryBtn) {
      secondaryBtn.textContent = '暂不下载，跳过验证';
      uiShow(secondaryBtn);
    }

    overlay.classList.add('visible');

    function cleanup() {
      overlay.classList.remove('visible');
      overlay.removeEventListener('click', onOverlayClick);
      if (primaryBtn) primaryBtn.onclick = null;
      if (secondaryBtn) secondaryBtn.onclick = null;
    }

    function onOverlayClick(e) {
      if (e.target === overlay) {
        cleanup();
        resolve('decline');
      }
    }
    overlay.addEventListener('click', onOverlayClick);

    if (primaryBtn) {
      primaryBtn.onclick = () => {
        cleanup();
        resolve('approve');
      };
    }
    if (secondaryBtn) {
      secondaryBtn.onclick = () => {
        cleanup();
        resolve('decline');
      };
    }

    const modalContent = overlay.querySelector('.compliance-modal');
    if (modalContent) {
      modalContent.onclick = (e) => e.stopPropagation();
    }
  });
}

async function downloadCuratedJars(jarIds) {
  const ids = [...new Set((jarIds || []).filter(Boolean))];
  if (!ids.length) return;
  await apiPost('/api/java-jars/download', { ids });
}

function buildRetryValidationBody(solveBody, solveSession, jarIds) {
  return {
    api_key: solveBody.api_key,
    provider: solveBody.provider,
    model: solveBody.model,
    custom_url: solveBody.custom_url || '',
    text: solveBody.text,
    language: solveBody.language,
    user_constraints: solveBody.user_constraints,
    solve_session: solveSession,
    approved_jar_ids: jarIds,
  };
}

async function maybeRetryValidationForMissingJars(solvePayload, solveBody) {
  const missing = extractMissingJarsFromSolvePayload(solvePayload);
  if (!missing.length || !solvePayload?.solve_session) return solvePayload;

  const decision = await showJarConsentModal(missing);
  if (decision !== 'approve') {
    showToast('已跳过 jar 下载，内化验证未完成', 'info');
    return solvePayload;
  }

  const jarIds = missing.map((j) => j.id);
  try {
    showToast('正在下载验证用 jar…', 'info');
    await downloadCuratedJars(jarIds);
    const retryResp = await apiPost(
      '/api/tool/retry-validation',
      buildRetryValidationBody(solveBody, solvePayload.solve_session, jarIds),
    );
    if (!retryResp?.ok) {
      showToast('验证重试失败: ' + (retryResp?.error || '未知错误'), 'error');
      return solvePayload;
    }
    const retried = retryResp.data || retryResp;
    showToast('jar 已安装，内化验证已重试', 'success');
    return { ...solvePayload, ...retried, solve_session: retried.solve_session || solvePayload.solve_session };
  } catch (err) {
    showToast('jar 下载或验证重试失败: ' + err.message, 'error');
    return solvePayload;
  }
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
    <button class="btn-ghost btn-sm runtime-refresh-btn" onclick="refreshRuntimeStatus()" aria-label="刷新运行环境">${ico('refresh-cw', 'icon-sm')}</button>
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
  if (!uploadedDocuments.length && !assignmentImageItems.length) {
    showToast('请先粘贴题目文字，或添加文档/题目图片', 'error');
    return;
  }

  resetAgentPlanState({ keepDocuments: true, keepTemplate: true });
  const primaryName = uploadedDocuments[0]?.fileName
    || (assignmentImageItems[0]?.fileName ? `题目图片组（${assignmentImageItems.length} 张）` : '题目图片组');
  const parseHint = [];
  if (uploadedDocuments.length) parseHint.push(`${uploadedDocuments.length} 个文档`);
  if (assignmentImageItems.length) parseHint.push(`${assignmentImageItems.length} 张题目图`);
  if (!quiet) showToast(`正在解析 ${parseHint.join(' + ')}…`, 'info');

  try {
    const payload = await buildDocumentsPayload();
    const resp = await apiPost('/api/parse-report', payload);
    applyParseResponse(resp, primaryName);

    if (parsedQuestions.length === 0) {
      showToast('未检测到题目，请确认文档格式与角色', 'error');
      goToStep(1);
      return;
    }

    let typeLabel;
    const clozeInfo = getCodeClozeParseInfo(parsedQuestions, parsedMetadata);
    if (clozeInfo?.mixed) {
      const parts = [];
      if (clozeInfo.theoryCount) parts.push(`简答 ${clozeInfo.theoryCount}`);
      if (clozeInfo.clozeCount) parts.push(`填空 ${clozeInfo.blankCount} 空`);
      typeLabel = `混排卷（${parts.join(' + ')}）`;
    } else if (clozeInfo) {
      typeLabel = `代码填空（${clozeInfo.blankCount} 空）`;
    } else if (parsedQuestions[0].type === 'lab_report') {
      typeLabel = '实验报告';
    } else {
      typeLabel = `${parsedQuestions.length} 个题目`;
    }
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

  uiShow(card, 'block');
  if (confirmedBar) uiHide(confirmedBar);
  if (clearBtn) uiShow(clearBtn, 'inline-flex');

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
  if (card) uiHide(card);
  if (confirmedBar) uiShow(confirmedBar, 'block');
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
  if (card) uiHide(card);
  if (confirmedBar) uiHide(confirmedBar);
  if (clearBtn) uiHide(clearBtn);
  markAgentPlanStale();
  if (parsedQuestions[0]?.type === 'lab_report') {
    renderSectionsWorkbench(parsedQuestions[0], parsedMetadata, null);
  }
}

function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  if (uploadInputMode !== 'file') setUploadInputMode('file');
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
  if (uploadInputMode !== 'file') setUploadInputMode('file');
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
  if (hint) {
    if (isPdf) uiShow(hint, 'inline-flex');
    else uiHide(hint);
  }
  if (pairBar) {
    if (isPdf) uiShow(pairBar, 'flex');
    else uiHide(pairBar);
  }
  updatePdfPairDocxLabel();
}

function updatePdfPairDocxLabel() {
  const label = document.getElementById('pdfPairDocxLabel');
  const clearBtn = document.getElementById('clearPairedDocxBtn');
  if (!label) return;
  if (pairedDocxPath) {
    const name = pairedDocxPath.split(/[\\/]/).pop();
    label.textContent = `已配对 Word 模版：${name}（填表将写入该 docx）`;
    if (clearBtn) uiShow(clearBtn, 'inline-flex');
  } else {
    label.textContent = '可选：添加空白 Word 模版，填表写入该 docx（题目 PDF + 空白 Word 亦可）';
    if (clearBtn) uiHide(clearBtn);
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
  if (!list) return;
  list.innerHTML = '';
  updateQuestionsPanelSummary(questions);

  if (questions.length === 0) {
    list.innerHTML = emptyStateHtml('inbox', '未找到题目', '请检查上传的文档是否包含实验题目');
    return;
  }

  questions.forEach((q, i) => {
    const typeMap = {
      'code': { label: '编程题', cls: 'badge-code' },
      'code_cloze': { label: '代码填空', cls: 'badge-code-cloze' },
      'theory': { label: '理论题', cls: 'badge-theory' },
      'analysis': { label: '分析题', cls: 'badge-analysis' },
      'lab_report': { label: '实验报告', cls: 'badge-analysis' },
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
  { id: 'parse',  num: 1, icon: 'file-text', label: '解析文档',       hasInput: false, hasOutput: true,  inputLabel: '',                                                    outputLabel: '解析结果', standalone: false },
  { id: 'solve',  num: 2, icon: 'brain', label: 'AI 解题',         hasInput: true,  hasOutput: true,  inputLabel: '题目文本（来自 #1 解析结果）',                   outputLabel: '解题结果 (JSON)', standalone: false },
  { id: 'run',    num: null, icon: 'play', label: '运行代码（手动）', hasInput: true,  hasOutput: true,  inputLabel: '代码（来自 #2 中的 code）',                       outputLabel: '运行结果', standalone: true, advanced: true },
  { id: 'uml',    num: 4, icon: 'bar-chart', label: '图表渲染',         hasInput: true,  hasOutput: true,  inputLabel: 'diagrams JSON / PlantUML / dfd_json（来自 #2 的 diagrams，最多 12 张）', outputLabel: 'UML / DFD 图片', standalone: true },
  { id: 'fill',   num: null, icon: 'file-pen', label: '填写报告（实验性）', hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON（来自 #2 + #3 + #4）',            outputLabel: '填写后的 docx', standalone: false, advanced: true },
  { id: 'fix',    num: null, icon: 'wrench', label: '修复代码',      hasInput: true,  hasOutput: true,  inputLabel: '代码 + 错误文本',                                  outputLabel: '修复后代码', standalone: true },
  { id: 'verify', num: null, icon: 'check-circle', label: '校验答案',      hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON',                                       outputLabel: '校验结果', standalone: true },
  { id: 'revise', num: null, icon: 'pencil', label: '修订答案',      hasInput: true,  hasOutput: true,  inputLabel: '答案 JSON + 反馈',                                outputLabel: '修订后答案', standalone: true },
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
  uiHide(document.getElementById('guidedModeContent'));
  uiShow(document.getElementById('toolboxPanel'), 'flex');
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
  uiShow(document.getElementById('guidedModeContent'));
  uiHide(document.getElementById('toolboxPanel'));
  document.querySelectorAll('.mode-switch-tab').forEach((el) => {
    el.classList.toggle('active', el.dataset.mode === 'guided');
  });
}

function showModeSwitchBar() {
  const bar = document.getElementById('modeSwitchBar');
  if (bar) uiShow(bar, 'flex');
}

function showReviseFeedbackModal() {
  return new Promise((resolve) => {
    const modal = document.getElementById('reviseFeedbackModal');
    const textarea = document.getElementById('reviseFeedbackText');
    const submitBtn = document.getElementById('reviseFeedbackSubmit');
    const cancelBtn = document.getElementById('reviseFeedbackCancel');
    if (!modal || !textarea) { resolve('请改进答案质量'); return; }

    textarea.value = '请改进答案质量';
    uiShow(modal, 'flex');

    function cleanup() {
      uiHide(modal);
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
      if (!chk.ok) lines.push(`  [×] ${chk.id}: ${chk.message}`);
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

function formatSolveToolOutput(payload) {
  if (!payload) return '';
  const parsed = payload.parsed || payload;
  const type = payload.type || parsed.type;
  if (type !== 'code_cloze') {
    return JSON.stringify(payload, null, 2);
  }
  const blanks = parsed.blanks || payload.blanks || {};
  const entries = Object.entries(blanks)
    .map(([k, v]) => {
      const n = Number(k);
      if (v && typeof v === 'object') {
        return {
          n: Number.isFinite(n) ? n : k,
          answer: String(v.answer || '').trim(),
          brief: String(v.brief || '').trim(),
        };
      }
      return { n: Number.isFinite(n) ? n : k, answer: String(v || '').trim(), brief: '' };
    })
    .sort((a, b) => (Number(a.n) || 0) - (Number(b.n) || 0));
  const lines = [
    '【代码完形填空】',
    `检测到 ${entries.length} 个空号：`,
    '',
  ];
  for (const e of entries) {
    lines.push(`  ${e.n}. ${e.answer}${e.brief ? `  // ${e.brief}` : ''}`);
  }
  const note = parsed.pattern_note || payload.pattern_note;
  if (note) lines.push('', `模式说明：${note}`);
  const code = parsed.completed_code || payload.completed_code;
  if (code) {
    lines.push('', '--- 完整代码预览 ---', code);
  }
  lines.push('', '提示：切到引导模式执行计划可在 Step3 使用空号工作区。');
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
      `<span class="diagram-badge ${b.ok ? 'ok' : 'missing'}" title="${b.ok ? '可用' : '不可用'}">${ico(b.ok ? 'check-circle' : 'x-circle', 'icon-xs')} ${escapeHtml(b.label)}</span>`
    )).join('');
    el.innerHTML = `<span class="diagram-bar-label">图表引擎</span>${badges}`;
    uiShow(el, 'flex');
  } catch (err) {
    console.warn('diagram status check failed:', err);
    uiHide(el);
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
  const order = ['parse', 'solve', 'run', 'uml', 'fill'];
  const idx = order.indexOf(toolId);
  if (idx < 0) return;
  for (let i = idx + 1; i < order.length; i++) {
    const tid = order[i];
    if (toolState[tid].status === 'success') {
      toolState[tid].status = 'stale';
    }
  }
}

/** After fix_code succeeds, push fixed code into solve + run inputs. */
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
  }

  for (const tid of ['run', 'fill']) {
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
    statusEl.innerHTML = Icons.toolStatusHtml(state.status);
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

  const statusText = Icons.toolStatusHtml(state.status);
  const inputPreview = (state.input || inputVal || '').slice(0, 80);

  return `<div class="tool-card ${state.status !== 'idle' ? state.status : ''}" data-tool="${def.id}">
    <div class="tool-card-head" onclick="toggleToolCard('${def.id}')">
      ${def.num ? `<span class="tool-card-num">${def.num}.</span>` : ''}
      <span class="tool-card-icon">${ico(def.icon, 'tool-card-icon')}</span>
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
      ${def.id === 'uml' ? `
      <div class="tool-card-config tool-card-config-col">
        <label style="font-size:12px;color:var(--text-secondary);display:flex;align-items:center;gap:6px">
          <input type="checkbox" data-tool-config="${def.id}-online"
            ${readSettings().umlAllowOnline !== false ? 'checked' : ''}
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
          ${state.status === 'running' ? icoLabel('loader', '执行中…', 'icon-sm icon-spin') : icoLabel('play', '执行', 'icon-sm')}
        </button>
        ${def.id === 'uml' ? `
        <button type="button" class="btn-secondary btn-sm" onclick="verifyDiagramsTool('${def.id}')"
          ${state.status === 'running' ? 'disabled' : ''}>${icoLabel('search', '验错', 'icon-sm')}</button>
        <button type="button" class="btn-secondary btn-sm" onclick="fixDiagramsTool('${def.id}')"
          ${state.status === 'running' ? 'disabled' : ''}>${icoLabel('sparkles', 'AI 修复', 'icon-sm')}</button>
        ` : ''}
        ${state.status === 'failed' ?
          `<button type="button" class="btn-secondary btn-sm" onclick="executeTool('${def.id}')">${icoLabel('refresh-cw', '重试', 'icon-sm')}</button>` : ''}
        ${def.hasOutput ? `<button type="button" class="btn-ghost btn-sm" onclick="copyToolOutput('${def.id}')">${icoLabel('copy', '复制输出', 'icon-sm')}</button>` : ''}
      </div>
      ${state.status === 'running' ? '<div class="tool-card-progress"></div>' : ''}
      ${(def.id === 'verify' || def.id === 'revise') && state.input ?
        (() => { try { JSON.parse(state.input); return ''; }
          catch { return `<div class="tool-card-validation-hint">${icoLabel('alert-triangle', '输入不是有效的 JSON 格式', 'icon-sm')}</div>`; }
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
  const chainRunning = parseRunning || solveRunning;
  btn.disabled = !hasDocs || chainRunning;
  if (chainRunning) {
    Icons.setIconText(btn, 'loader', '链式执行中…', 'icon-sm icon-spin');
  } else {
    Icons.setIconText(btn, 'zap', '一键链 (#1→#2 解题)', 'icon-sm');
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
  const settings = readSettings();
  const state = toolState[toolId];
  if (!state) return;

  // Check API key for LLM-dependent tools
  const needsKey = ['solve', 'fix', 'revise'].includes(toolId);
  if (needsKey && needsUserApiKey(settings)) {
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
        const solveBody = {
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
        };
        const solveResp = await apiPost('/api/tool/solve', solveBody);
        if (solveResp?.ok) {
          const initial = solveResp.data || solveResp;
          const finalPayload = await maybeRetryValidationForMissingJars(initial, solveBody);
          resp = { ...solveResp, data: finalPayload };
        } else {
          resp = solveResp;
        }
        break;
      }
      case 'run': {
        const code = state.input || resolveToolInput('run');
        if (!code) throw new Error('请先执行 #2 AI 解题，或手动粘贴代码');
        resp = await apiPost('/api/tool/run', { code, language: lang });
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
        const umlOut = toolState.uml.output || {};
        const answers = [{
          ...solveOut,
          code: solveOut.code || '',
          code_files: solveOut.code_files || [],
          main_file: solveOut.main_file || '',
          language: solveOut.language || settings.codeLanguage || 'python',
          output: runOut.stdout || '',
          images_b64: solveOut.images_b64 || [],
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
      } else if (toolId === 'solve') {
        state.outputText = formatSolveToolOutput(state.output);
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
  } else if (state.status === 'failed' && toolId === 'fill') {
    showToast('填表未成功，可从 #2 解题结果或答案工作区复制内容', 'warning');
  } else if (state.status === 'failed') {
    showToast(`${TOOL_DEFS.find((t) => t.id === toolId)?.label || toolId} 执行失败`, 'error');
  }
}

async function verifyDiagramsTool(toolId) {
  if (toolId !== 'uml') return;
  const settings = readSettings();
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
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
  if (hasFill || hasSolve) uiShow(bar, 'flex');
  else uiHide(bar);
  const downloadBtn = document.getElementById('toolboxDownloadBtn');
  if (downloadBtn) {
    if (hasFill) uiShow(downloadBtn);
    else uiHide(downloadBtn);
  }
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
    showToast('请先在高级区执行「填写报告（实验性）」', 'error');
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
  if (bar) uiHide(bar);
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
    agentImageAssets = [];
    agentImageSections = [];
    agentImageReadSummary = null;
    agentImageReadingMode = 'ocr_only';
    agentAssignmentFromImages = false;
    agentAssignmentBodyPrefix = '';
    agentAssignmentPreviewConfirmed = false;
    agentParseImageWarnings = [];
    hideAssignmentPreview();
    hideCodeClozeParseBadge();
    const ocrBanner = document.getElementById('parseOcrBanner');
    if (ocrBanner) uiHide(ocrBanner);
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
  agentContextSnapshot = null;
  clearAgentThoughtLog();
  agentRunFinished = false;
  agentSseClosingGracefully = false;
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
  if (panel) uiHide(panel);
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;
  const stale = document.getElementById('agentStaleBanner');
  if (stale) uiHide(stale);
}

function markAgentPlanStale() {
  if (!agentPlanSteps.length) return;
  agentPlanStale = true;
  const stale = document.getElementById('agentStaleBanner');
  if (stale) uiShow(stale, 'block');
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = true;
}

function getExperimentalReactMode() {
  const el = document.getElementById('experimentalReactModeSettings');
  if (el) return el.checked === true;
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  return saved.experimentalReactMode === true;
}

function getRunMode() {
  const checked = document.querySelector('input[name="runMode"]:checked');
  const mode = checked?.value || 'standard';
  if (mode === 'react' && !getExperimentalReactMode()) {
    return 'standard';
  }
  return mode;
}

function isAutonomousRunMode(mode) {
  const m = mode || lastSessionRunMode || getRunMode();
  return m === 'react' || m === 'deep';
}

function setAgentProgressBarVisible(visible) {
  const wrap = document.getElementById('agentProgressWrap');
  if (!wrap) return;
  if (visible) uiShow(wrap, 'block');
  else uiHide(wrap);
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
      hint.innerHTML = `${ico('lightbulb', 'icon-sm')} 答案已生成：中间复制分节正文，右侧预览区一键复制代码/图表`;
    }
    if (advanced) uiShow(advanced);
  } else {
    if (hint) {
      hint.innerHTML = `${ico('lightbulb', 'icon-sm')} 高级填表模式：不保证版式；建议以答案工作区复制粘贴为主`;
    }
    if (advanced) advanced.open = true;
  }
}

function onRunModeChange() {
  const mode = getRunMode();
  syncRunModeUI(mode);
  persistSettingsPatch({ runMode: mode });
  if (mode === 'deep') {
    showToast('深度模式：理解 + 审稿修订 + V4 执行，约 3～4 次 API 调用', 'info');
  } else if (mode === 'react') {
    showToast('实验 ReAct：V4 流水线优先，AI 补跑 UML / 交付', 'info');
  }
}

function onExperimentalReactChange() {
  const enabled = getExperimentalReactMode();
  syncExperimentalReactUI(enabled);
  persistSettingsPatch({ experimentalReactMode: enabled });
  if (!enabled && (document.querySelector('input[name="runMode"][value="react"]')?.checked)) {
    const standard = document.querySelector('input[name="runMode"][value="standard"]');
    if (standard) {
      standard.checked = true;
      onRunModeChange();
    }
  } else if (enabled) {
    showToast('已启用实验 ReAct；选用后 API 仍发送 run_mode=react', 'info');
  }
}

function syncExperimentalReactUI(enabled) {
  const card = document.getElementById('experimentalReactCard');
  const checkbox = document.getElementById('experimentalReactModeSettings');
  const on = enabled === true;
  if (checkbox) checkbox.checked = on;
  if (card) {
    if (on) uiShow(card, 'flex');
    else uiHide(card);
  }
}

function getSolveQualityTier() {
  const el = document.querySelector('input[name="solveQualityTier"]:checked');
  const val = el ? el.value : 'standard';
  return ['fast', 'standard', 'thorough'].includes(val) ? val : 'standard';
}

function onAutoFastTierSettingsChange() {
  const el = document.getElementById('autoFastTierForLightQuestionsSettings');
  persistSettingsPatch({ autoFastTierForLightQuestions: el ? el.checked : true });
  updateStep2ModeBanner();
}

function onParallelModuleStepsChange() {
  const el = document.getElementById('enableParallelModuleStepsSettings');
  persistSettingsPatch({ enableParallelModuleSteps: el ? el.checked : true });
}

function onSolveQualityTierChange() {
  const tier = getSolveQualityTier();
  syncSolveQualityTierUI(tier);
  persistSettingsPatch({ solveQualityTier: tier, solveQualityTierExplicit: true });
  const hints = {
    fast: '极速档位：跳过内化验证，约 2 次 LLM',
    standard: '标准档位：默认内化验证与修复轮次',
    thorough: '稳妥档位：更多修复与同错重生',
  };
  showToast(hints[tier] || hints.standard, 'info');
}

function syncSolveQualityTierUI(tier) {
  const val = ['fast', 'standard', 'thorough'].includes(tier) ? tier : 'standard';
  document.querySelectorAll('input[name="solveQualityTier"]').forEach((el) => {
    const selected = el.value === val;
    if (selected) el.checked = true;
    const card = el.closest('.run-mode-card');
    if (card) card.classList.toggle('active', selected);
  });
  updateStep2ModeBanner();
}

function resolveAutoRemediateForRun(runMode) {
  void runMode;
  const settings = readSettings();
  return settings.autoRemediate !== false;
}

function resolveAutoRemediateMaxRoundsForRun() {
  const settings = readSettings();
  const raw = Number(settings.autoRemediateMaxRounds);
  if (!Number.isFinite(raw)) return 1;
  return Math.max(0, Math.min(5, raw));
}

function resolveLlmReplanForRun() {
  return readSettings().llmReplan !== false;
}

async function recordBehaviorOutcome(event, meta = {}) {
  if (!event) return;
  try {
    await apiPost('/api/profile/behavior-outcome', {
      event,
      section: meta.section || '',
      run_id: meta.runId || agentRunId || '',
      format: meta.format || '',
    });
  } catch (err) {
    console.warn('[behavior-outcome]', event, err?.message || err);
  }
}

const SOLVE_QUALITY_TIER_LABELS = {
  fast: '极速',
  standard: '标准',
  thorough: '稳妥',
};

function updateStep2ModeBanner() {
  const el = document.getElementById('step2ModeBanner');
  if (!el) return;
  const runMode = getRunMode();
  const tier = getSolveQualityTier();
  const tierLabel = SOLVE_QUALITY_TIER_LABELS[tier] || tier;
  const autoFix = resolveAutoRemediateForRun(runMode);
  const autoFixRounds = resolveAutoRemediateMaxRoundsForRun();
  const replanRounds = resolveMaxReplanRoundsForRun();

  const settings = readSettings();
  const autoFast = settings.autoFastTierForLightQuestions !== false;
  const tierLocked = settings.solveQualityTierExplicit === true;

  if (runMode === 'deep') {
    el.className = 'step2-mode-banner step2-mode-banner--deep';
    el.innerHTML =
      `${ico('brain', 'icon-sm')}<div class="step2-mode-banner-text">` +
      `<strong>深度模式</strong> · 质量档位 ${tierLabel} · 执行前 AI 审稿 + V4 流水线 + 内化验证` +
      `${autoFix ? ` · 校验失败自动修复(${autoFixRounds}轮)` : ''}` +
      `${replanRounds ? ` · 失败重规划≤${replanRounds}轮` : ' · 重规划已关闭'}` +
      `<span class="step2-mode-banner-sub">适合长报告与多约束；比标准多约 2～3 次 LLM</span></div>`;
    return;
  }
  if (runMode === 'react') {
    el.className = 'step2-mode-banner step2-mode-banner--react';
    el.innerHTML =
      `${ico('sparkles', 'icon-sm')}<div class="step2-mode-banner-text">` +
      `<strong>ReAct 实验模式</strong> · V4 优先解题 + AI 自主补跑 UML / 交付` +
      `<span class="step2-mode-banner-sub">延迟与费用最高；适合计划难覆盖的收尾步骤</span></div>`;
    return;
  }

  const tierHint = tier === 'fast'
    ? '极速档位：跳过部分验证，编程题建议改标准或稳妥'
    : tier === 'thorough'
      ? '稳妥档位：多轮修复，质量最高'
      : '标准档位：内化验证 + 适量修复';
  const autoFastHint = autoFast && !tierLocked
    ? ' · 轻量题型将自动用极速档位（可在设置关闭）'
    : '';
  el.className = 'step2-mode-banner step2-mode-banner--standard';
  el.innerHTML =
    `${ico('check-circle', 'icon-sm')}<div class="step2-mode-banner-text">` +
    `<strong>标准模式</strong> · ${tierLabel}档位 · V4 分阶段解题 · 沙箱试跑代码 · 执行后规则校验` +
    `${autoFix ? ` · <span class="step2-mode-banner-accent">校验未通过将自动修复 ${autoFixRounds} 轮</span>` : ' · 自动修复已关闭（可在设置开启）'}` +
    `${replanRounds ? ` · 失败重规划≤${replanRounds}轮` : ' · 重规划已关闭'}` +
    `<span class="step2-mode-banner-sub">${tierHint}${autoFastHint} · 编程题不满意可改稳妥或切深度</span></div>`;
}

function syncRunModeUI(runMode) {
  let val = runMode || 'standard';
  if (val === 'react' && !getExperimentalReactMode()) {
    val = 'standard';
  }
  document.querySelectorAll('input[name="runMode"]').forEach((el) => {
    if (el.value === 'react' && !getExperimentalReactMode()) return;
    const selected = el.value === val;
    if (selected) el.checked = true;
    const card = el.closest('.run-mode-card');
    if (card) card.classList.toggle('active', selected);
  });
  updateStep2ModeBanner();
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
  const settings = collectSolveOptions(readSettings());
  return {
    api_key: settings.apiKey,
    provider: settings.provider,
    model: settings.model,
    custom_url: settings.customUrl || '',
    run_mode: getRunMode(),
    include_uml: settings.includeUml === true,
    profile: {
      default_language: settings.codeLanguage || 'python',
      prefer_uml: settings.includeUml === true,
      optimize_plan_from_usage: settings.optimizePlanFromUsage === true,
    },
    sections_config: collectSectionsConfigForApi(),
    user_constraints: getUserConstraints(),
    solveQualityTier: settings.solveQualityTier || getSolveQualityTier(),
    solveQualityTierExplicit: settings.solveQualityTierExplicit === true,
    autoFastTierForLightQuestions: settings.autoFastTierForLightQuestions !== false,
    enableParallelModuleSteps: settings.enableParallelModuleSteps !== false,
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

async function buildAgentDocumentPayload(options = {}) {
  const forceReupload = options.forceReupload === true;
  if (!forceReupload && agentDocumentIds.length && !agentSplitDirty) {
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

async function postAgentRunWithDocRetry(runPayload) {
  try {
    return await apiPost('/api/agent/run', runPayload);
  } catch (err) {
    if (err.stale_plan === true && err.plan_fingerprint && !runPayload.__stale_plan_retried) {
      const retryPayload = {
        ...runPayload,
        plan_fingerprint: err.plan_fingerprint,
        __stale_plan_retried: true,
      };
      delete retryPayload.__stale_plan_retried;
      agentPlanFingerprint = err.plan_fingerprint || agentPlanFingerprint;
      return apiPost('/api/agent/run', retryPayload);
    }
    if (!err.stale_documents) throw err;
    const retryPayload = { ...runPayload };
    delete retryPayload.document_ids;
    const doc = await buildAgentDocumentPayload({ forceReupload: true });
    return apiPost('/api/agent/run', { ...retryPayload, ...doc });
  }
}

async function generateAgentPlan() {
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
    showToast('请先在设置中填写 API Key', 'error');
    switchTab('settings');
    return;
  }
  if (!parsedQuestions.length) {
    showToast('请先上传并解析报告', 'error');
    return;
  }
  if (assignmentPreviewRequiresConfirm() && !agentAssignmentPreviewConfirmed) {
    showToast('请先在识题预览中核对题干，并勾选「已核对题干完整」', 'warning');
    const panel = document.getElementById('assignmentPreviewPanel');
    if (panel) {
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      panel.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'nearest' });
    }
    return;
  }
  if (!hasCompletedOnboarding()) {
    await showOnboardingModal();
  }

  const previewText = document.getElementById('assignmentPreviewText')?.value?.trim();
  if (previewText) {
    agentAssignmentText = previewText;
  }

  const btn = document.getElementById('generatePlanBtn');
  if (btn) {
    btn.disabled = true;
    Icons.setIconText(btn, 'loader', '生成计划中…', 'icon-sm icon-spin');
  }

  try {
    const doc = await buildAgentDocumentPayload();
    const planPayload = {
      ...getAgentApiSettings(),
      ...doc,
      output_mode: getOutputMode(),
      format_spec: agentFormatSpec || undefined,
      split_idx: agentSplitIdx,
    };
    const previewPanel = document.getElementById('assignmentPreviewPanel');
    if (agentAssignmentText && previewPanel && !previewPanel.classList.contains('is-hidden')) {
      planPayload.assignment_text = agentAssignmentText;
    }
    const resp = await apiPost('/api/agent/plan', planPayload);

    agentPlanSteps = resp.steps || [];
    agentPlanFingerprint = resp.plan_fingerprint || '';
    agentUnderstand = resp.understand || null;
    agentDocumentIds = resp.document_ids || [];
    agentContextSnapshot = resp.agent_context_snapshot || null;
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
    if (stale) uiHide(stale);

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
      Icons.setIconText(btn, 'clipboard-list', '生成计划', 'icon-sm');
    }
  }
}

function renderAgentPlanPanel(planMeta) {
  const panel = document.getElementById('agentPlanPanel');
  const list = document.getElementById('planStepsList');
  const meta = document.getElementById('agentPlanMeta');
  const summaryEl = document.getElementById('agentSectionsSummary');
  if (!panel || !list) return;

  uiShow(panel, 'block');
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
    uiHide(wrap);
    wrap.innerHTML = '';
    return;
  }

  uiShow(wrap, 'flex');
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) return;

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
      apply_to_profile: readSettings().optimizePlanFromUsage !== false,
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
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
  agentSseClosingGracefully = false;
  agentSseEventIndex = 0;
  agentSseReconnectAttempts = 0;
  agentThoughtCollapsed = true;
  agentReplanNotified = false;
  solvedAnswers = [];
  goToStep(3);
  updateStepBar(3);

  const titleEl = document.getElementById('step3Title');
  if (titleEl) setHeadingIcon(titleEl, 'clipboard-list', '正在生成答案…');
  const dlvWs = document.getElementById('deliverableWorkspace');
  if (dlvWs) uiHide(dlvWs);
  currentDeliverable = null;
  const runMode = getRunMode();
  setAgentProgressBarVisible(!isAutonomousRunMode(runMode));
  uiShow(document.getElementById('cancelAgentRunBtn'), 'inline-flex');
  updateStep3CompletionActions();
  const thoughtBody = document.getElementById('agentThoughtBody');
  const verifyWrap = document.getElementById('agentVerifyWrap');
  if (thoughtBody) thoughtBody.innerHTML = '';
  updateThoughtSidebarBadge();
  if (verifyWrap) uiHide(verifyWrap);
  agentVerificationReport = null;
  agentModuleResults = null;
  agentConfirmedSteps = steps;
  agentDecisionLog = [];
  clearAgentThoughtLog();
  lastSessionRunMode = runMode;
  updateThoughtSidebarVisibility();
  if (!isAutonomousRunMode(runMode)) {
    updateAgentProgress(0, steps.length, '正在启动…（执行中请勿刷新页面）');
  }
  renderAgentExecutionProgress(steps, runMode);

  try {
    await postAgentPlanFeedback(steps, fingerprint);
    const resp = await postAgentRunWithDocRetry({
      ...getAgentApiSettings(),
      document_ids: agentDocumentIds,
      agent_context_snapshot: agentContextSnapshot || undefined,
      steps,
      plan_fingerprint: fingerprint,
      output_mode: getOutputMode(),
      auto_remediate: resolveAutoRemediateForRun(runMode),
      auto_remediate_max_rounds: resolveAutoRemediateMaxRoundsForRun(),
      max_replan_rounds: resolveMaxReplanRoundsForRun(),
      llm_replan: resolveLlmReplanForRun(),
      sections_config: collectSectionsConfigForApi(),
      split_idx: agentSplitIdx,
      format_spec: agentFormatSpec || undefined,
      understand: agentUnderstand,
      fallback_on_failure: true,
      ...getSectionContextPayload(),
      assignment_text: agentAssignmentText || undefined,
      code_language: settings.codeLanguage,
    });

    agentRunId = resp.run_id;
    persistAgentActiveRun({
      run_id: resp.run_id,
      totalSteps: steps.length,
      sseSince: 0,
      steps,
      partial: false,
      startedAt: Date.now(),
    });
    connectAgentSSE(agentRunId, steps.length);
  } catch (err) {
    agentExecutionMode = false;
    clearAgentActiveRun();
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
      <div class="solving-status">${ico(willRun ? 'loader' : 'skip-forward', willRun ? 'icon-sm icon-spin' : 'icon-sm')}</div>
      <div class="solving-info">
        <div class="solving-title">${AGENT_MODULE_LABELS[mod] || mod}</div>
        <div class="solving-answer" id="agent-detail-${mod}">${willRun ? '等待执行…' : '已跳过（未勾选）'}</div>
      </div>
    `;
    if (!willRun) item.classList.add('skipped');
    list.appendChild(item);
  });
}

function renderAgentExecutionProgress(steps, mode) {
  if (isAutonomousRunMode(mode)) {
    renderAutonomousStatusItem(mode);
  } else {
    renderAgentProgressList(steps);
  }
}

function renderAutonomousStatusItem(mode) {
  const list = document.getElementById('solvingList');
  if (!list) return;
  list.innerHTML = '';
  const isReact = mode === 'react';
  const item = document.createElement('div');
  item.className = 'solving-item solving';
  item.id = isReact ? 'agent-step-react' : 'agent-step-deep';
  const title = isReact ? 'ReAct 自主执行' : '深度模式执行';
  const detail = isReact ? 'AI 正在决策下一步…' : '理解、审稿与预检进行中…';
  const detailId = isReact ? 'agent-detail-react' : 'agent-detail-deep';
  item.innerHTML = `<div class="solving-status">${ico('loader', 'icon-sm icon-spin')}</div>` +
    '<div class="solving-info">' +
      '<div class="solving-title">' + title + '</div>' +
      '<div class="solving-answer" id="' + detailId + '">' + detail + '</div>' +
    '</div>';
  list.appendChild(item);
}

function updateAgentProgress(done, total, label) {
  if (isAutonomousRunMode()) return;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const fill = document.getElementById('agentProgressFill');
  const pctEl = document.getElementById('agentProgressPct');
  const lbl = document.getElementById('agentProgressLabel');
  if (fill) fill.style.width = `${pct}%`;
  if (pctEl) pctEl.textContent = `${pct}%`;
  if (lbl) lbl.textContent = label || `进度 ${done}/${total}`;
}

function connectAgentSSE(runId, totalSteps, since = 0) {
  disconnectAgentSSE();
  agentSseClosingGracefully = false;
  agentSseTotalSteps = totalSteps;
  const url = `http://localhost:${serverPort}/api/agent/events?run_id=${encodeURIComponent(runId)}&since=${since}`;
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
    if (data.type !== 'heartbeat') {
      agentSseEventIndex += 1;
      persistAgentActiveRun();
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
    if (agentSseClosingGracefully || agentRunFinished) {
      disconnectAgentSSE();
      return;
    }
    if (agentRunId && agentSseReconnectAttempts < 3) {
      agentSseReconnectAttempts += 1;
      const resumeFrom = agentSseEventIndex;
      disconnectAgentSSE();
      showToast('连接中断，正在重连…', 'warning');
      setTimeout(() => {
        if (agentRunId && !agentRunFinished) {
          connectAgentSSE(agentRunId, agentSseTotalSteps || totalSteps, resumeFrom);
        }
      }, 1200);
      return;
    }
    if (agentRunId) {
      showToast('SSE 连接中断，请查看后端日志', 'error');
    }
    disconnectAgentSSE();
  };
}

async function handleAgentJarConsentRequired(data) {
  if (agentJarConsentInFlight || !agentRunId) return;
  const missing = (data.missing_jars || []).filter((j) => j && j.id);
  if (!missing.length) return;
  agentJarConsentInFlight = true;
  const detailEl = document.getElementById('agent-detail-solve_lab');
  if (detailEl) {
    detailEl.textContent = '待确认 Java 扩展库（内化验证）…';
  }
  appendAgentThought('JAR 确认', '验证需要下载白名单 jar，请在弹窗中确认');
  try {
    const decision = await showJarConsentModal(missing);
    const approved = decision === 'approve';
    if (approved) {
      showToast('正在下载验证用 jar…', 'info');
      await downloadCuratedJars(missing.map((j) => j.id));
    }
    await apiPost('/api/agent/jar-consent', {
      run_id: agentRunId,
      approved,
      jar_ids: approved ? missing.map((j) => j.id) : [],
    });
    if (!approved) {
      showToast('已跳过 jar 下载，内化验证将暂停', 'info');
    }
  } catch (err) {
    showToast('jar 确认失败: ' + err.message, 'error');
    try {
      await apiPost('/api/agent/jar-consent', { run_id: agentRunId, approved: false });
    } catch (_) { /* ignore */ }
  } finally {
    agentJarConsentInFlight = false;
  }
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
    if (data.status === 'running' && data.module === 'solve_code_cloze') {
      const label = AGENT_MODULE_LABELS.solve_code_cloze || 'solve_code_cloze';
      appendAgentThought(label, data.detail || '正在分析填空…');
      recordAgentThought({ type: 'progress', phase: label, text: data.detail || '执行中…', status: 'running' });
    }
    if (isAutonomousRunMode()) return;
    const mod = data.module || '';
    const el = document.getElementById(`agent-step-${mod}`);
    const detail = document.getElementById(`agent-detail-${mod}`);
    const statusMap = {
      running: { icon: 'loader', spin: true, cls: 'solving', text: '执行中…' },
      done: { icon: 'check-circle', cls: 'done', text: '完成' },
      degraded: { icon: 'alert-triangle', cls: 'degraded', text: data.error || '未成功（不影响主流程）' },
      failed: { icon: 'x-circle', cls: 'error', text: data.error || '失败' },
      skipped: { icon: 'skip-forward', cls: 'skipped', text: '已跳过' },
    };
    const st = statusMap[data.status] || statusMap.running;
    if (el) {
      el.classList.remove('solving', 'done', 'error', 'skipped', 'degraded');
      el.classList.add(st.cls);
      if (data.error_meta?.degraded) el.classList.add('degraded');
      const icon = el.querySelector('.solving-status');
      if (icon) icon.innerHTML = ico(st.icon, st.spin ? 'icon-sm icon-spin' : 'icon-sm');
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
        const badge = mod === 'fill_report'
          ? '填表未成功（可继续复制答案）'
          : '已降级为文本输出';
        detailHtml += ` <span class="solving-degraded-badge">${escapeHtml(badge)}</span>`;
        detailHtml += `<div class="solving-degraded-reason">${escapeHtml(meta.degraded_reason || data.error || '')}</div>`;
      } else if (data.status === 'degraded' && mod === 'fill_report') {
        detailHtml += ' <span class="solving-degraded-badge">填表未成功（可继续复制答案）</span>';
      }
      detail.innerHTML = detailHtml;
    }
    if (data.status === 'done' || data.status === 'degraded' || data.status === 'failed' || data.status === 'skipped') {
      ctx.bumpDone();
    }
    if (data.status === 'done' && data.deliverable) {
      currentDeliverable = data.deliverable;
      renderDeliverableWorkspace(data.deliverable);
      const titleEl = document.getElementById('step3Title');
      if (titleEl) setHeadingIcon(titleEl, 'clipboard-list', '答案工作区');
      updateStep3CompletionActions();
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
    if (!isAutonomousRunMode()) {
      renderAgentProgressList(getConfirmedPlanSteps());
    }
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

  if (type === 'jar_consent_required') {
    handleAgentJarConsentRequired(data);
    return;
  }

  if (type === 'pipeline_phase') {
    const phaseId = data.phase || '';
    const phaseLabel = PIPELINE_PHASE_LABELS[phaseId] || phaseId || '子阶段';
    const status = data.status || 'running';
    const detail = (data.detail || '').trim();
    let text = phaseLabel;
    if (status === 'running') {
      text = detail ? `${phaseLabel}：${detail}` : `${phaseLabel}…`;
    } else if (status === 'ok') {
      text = `${phaseLabel} ✓`;
    } else if (detail) {
      text = `${phaseLabel}：${detail}`;
    }
    const mod = data.module || 'solve_lab';
    const modLabel = AGENT_MODULE_LABELS[mod] || mod;
    if (!isAutonomousRunMode()) {
      const detailEl = document.getElementById(`agent-detail-${mod}`);
      if (detailEl) detailEl.textContent = text;
    }
    const progressLabel = document.getElementById('agentProgressLabel');
    if (progressLabel && isAutonomousRunMode()) {
      progressLabel.textContent = `${modLabel} · ${text}`;
    }
    appendAgentThought(`${modLabel} · V4`, text);
    recordAgentThought({ type: 'pipeline_phase', phase: phaseLabel, text, status });
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
    // 执行中不展示校验失败态，避免在答案工作区就绪前误导用户
    if (!agentExecutionMode) {
      renderVerificationPanel(data);
      if (data.remediated) {
        showToast('校验未通过，已自动修复并重验…', 'info');
      } else if (data.passed === false && !data.remediated) {
        showToast('校验未通过，请查看下方「校验清单」或修订答案', 'warning');
      }
    }
    return;
  }

  if (type === 'error') {
    showToast(data.error || '执行出错', 'error');
    return;
  }

  if (type === 'cancelled') {
    agentSseClosingGracefully = true;
    showToast('已取消执行', 'info');
    finishAgentRunUI(false);
    return;
  }

  if (type === 'done') {
    agentSseClosingGracefully = true;
    if (data.run_summary) {
      lastRunSummary = data.run_summary;
    }
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
    applyAgentRunDone(data).then(() => finishAgentRunUI(data.ok !== false));
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
    uiHide(row);
    return;
  }
  uiShow(row, 'flex');
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
  onSolveComplete(collectSolveOptions(readSettings()));
}

function renderVerificationPanel(report) {
  const wrap = document.getElementById('agentVerifyWrap');
  const list = document.getElementById('agentVerifyList');
  const fixes = document.getElementById('agentVerifyFixes');
  if (!wrap || !list || !report) return;
  uiShow(wrap, 'block');
  if (solvedAnswers[0]) solvedAnswers[0].verification_report = report;
  const checks = report.checks || [];
  list.innerHTML = checks
    .map((c) => {
      const isWarn = !c.ok && VERIFY_WARN_IDS.has(c.id);
      const cls = c.ok ? 'verify-ok' : (isWarn ? 'verify-warn' : 'verify-fail');
      const label = VERIFY_CHECK_LABELS[c.id] || c.id;
      const iconName = c.ok ? 'check' : (isWarn ? 'alert-triangle' : 'x');
      return `<li class="${cls}">${ico(iconName, 'icon-xs')} ${escapeHtml(label)}：${escapeHtml(c.message || '')}</li>`;
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
  await requestAgentRevise(['code'], { rerunModules: ['fix_code', 'run_code', 'fill_report'] });
}

function openManualEdit() {
  const a = solvedAnswers[0];
  if (!a) { showToast('没有可编辑的解题结果', 'info'); return; }
  const codeFiles = a.code_files || a.parsed?.code_files || [];
  const code = a.code || a.parsed?.code || '';
  const settings = readSettings();
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
  const settings = readSettings();
  if (needsUserApiKey(settings)) {
    showToast('请先在设置中填写 API Key', 'error');
    return;
  }
  const steps = buildPartialRerunSteps(moduleIds);
  agentExecutionMode = true;
  agentRunFinished = false;
  agentSseClosingGracefully = false;
  agentSseEventIndex = 0;
  agentSseReconnectAttempts = 0;
  uiShow(document.getElementById('agentProgressWrap'), 'block');
  uiShow(document.getElementById('cancelAgentRunBtn'), 'inline-flex');
  updateStep3CompletionActions();
  updateThoughtSidebarVisibility();
  renderAgentProgressList(steps);
  updateAgentProgress(0, steps.length, '增量重跑…');
  try {
    const resp = await postAgentRunWithDocRetry({
      ...getAgentApiSettings(),
      document_ids: agentDocumentIds,
      agent_context_snapshot: agentContextSnapshot || undefined,
      steps,
      plan_fingerprint: '',
      sections_config: collectSectionsConfigForApi(),
      split_idx: agentSplitIdx,
      format_spec: agentFormatSpec || undefined,
      module_results: agentModuleResults,
      dirty_modules: moduleIds,
      fill_sections: agentFillSections,
      fallback_on_failure: false,
      code_language: settings.codeLanguage,
    });
    agentRunId = resp.run_id;
    persistAgentActiveRun({
      run_id: resp.run_id,
      totalSteps: steps.length,
      sseSince: 0,
      steps,
      partial: true,
      startedAt: Date.now(),
    });
    connectAgentSSE(agentRunId, steps.length);
  } catch (err) {
    agentExecutionMode = false;
    clearAgentActiveRun();
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
    recordBehaviorOutcome('revise_submit');
    await runAgentVerify();
    const settings2 = collectSolveOptions(readSettings());
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

async function applyAgentRunDone(event) {
  const settings = collectSolveOptions(readSettings());
  const mr = event.module_results || {};
  const serverDeliverable = event.deliverable
    || mr.present_deliverable?.data?.deliverable;
  const isMixedRun = serverDeliverable?.type === 'mixed_assignment'
    || parsedMetadata?.mixed_assignment;

  let solveData = null;
  if (!isMixedRun) {
    solveData = (mr.solve_code_cloze?.ok && mr.solve_code_cloze.data)
      ? mr.solve_code_cloze.data
      : (mr.solve_lab?.data || mr.solve_short_answer?.data || mr.solve_theory?.data);
  }

  if (solveData && mr.solve_lab?.data) {
    const apiSettings = getAgentApiSettings();
    const solveBody = {
      api_key: apiSettings.api_key,
      provider: apiSettings.provider,
      model: apiSettings.model,
      custom_url: apiSettings.custom_url || '',
      text: parsedQuestions[0]?.full_text || agentPrimaryFullText || '',
      language: settings.codeLanguage || 'python',
      user_constraints: apiSettings.user_constraints,
    };
    const retried = await maybeRetryValidationForMissingJars(solveData, solveBody);
    if (retried !== solveData) {
      solveData = retried;
      mr.solve_lab = { ...(mr.solve_lab || {}), ok: true, data: retried };
      if (event.deliverable) {
        event.deliverable = null;
      }
    }
  }

  agentModuleResults = mr;

  if (solveData && !isMixedRun) {
    const q = parsedQuestions[0] || { type: 'lab_report' };
    solvedAnswers = [{
      ...q,
      type: q.type || solveData.type || (solveData.parsed || {}).type || 'lab_report',
      answer: solveData.answer || solveData.result_description || '',
      code: solveData.code || '',
      code_files: solveData.code_files || [],
      main_file: solveData.main_file || '',
      language: solveData.language || settings.codeLanguage,
      parsed: solveData.parsed || {},
      include_code: settings.includeCode !== false,
      include_uml: settings.includeUml === true,
    }];
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

  currentDeliverable = serverDeliverable
    || buildDeliverableFromSolveData(solveData, mr);
  if (currentDeliverable?.type === 'mixed_assignment') {
    window._mixedDeliverableTab = String(
      currentDeliverable.mixed_parts?.[0]?.segment_id ?? 0,
    );
    window._mixedClozeBlankTab = null;
  }
  if (currentDeliverable) {
    renderDeliverableWorkspace(currentDeliverable);
  }

  const t3El = document.getElementById('step3Title');
  if (t3El) setHeadingIcon(t3El, event.ok !== false ? 'clipboard-list' : 'alert-triangle',
    event.ok !== false ? '答案工作区' : '生成未完全成功');
  ['agent-step-react', 'agent-step-deep'].forEach(function(stepId) {
    var item = document.getElementById(stepId);
    if (!item) return;
    item.classList.remove('solving');
    item.classList.add(event.ok !== false ? 'done' : 'error');
    var icon = item.querySelector('.solving-status');
    if (icon) icon.innerHTML = ico(event.ok !== false ? 'check-circle' : 'x-circle', 'icon-sm');
    var detail = item.querySelector('.solving-answer');
    if (detail) {
      detail.textContent = event.ok !== false ? '已完成' : '未完全成功';
    }
  });
  if (!isAutonomousRunMode()) {
    updateAgentProgress(
      document.querySelectorAll('.solving-item.done').length,
      agentPlanSteps.length,
      event.ok !== false ? '全部完成' : '部分失败'
    );
  }
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
  clearAgentActiveRun();
  agentRunId = null;
  agentExecutionMode = false;
  agentRunFinished = true;
  agentSseClosingGracefully = false;
  uiHide(document.getElementById('cancelAgentRunBtn'));
  const execBtn = document.getElementById('executePlanBtn');
  if (execBtn) execBtn.disabled = agentPlanStale || !agentPlanSteps.length;
  updateThoughtSidebarVisibility();

  saveThoughtLogAuto().then((path) => {
    if (path) {
      updateThoughtLogSavedUI(path);
      showToast('思考过程已自动保存至 thought_logs 文件夹', 'info');
    }
  });

  updateStep3CompletionActions();
  if (success && solvedAnswers.length) {
    const settings = readSettings();
    onSolveComplete(settings);
    updateAgentVersionUI();
  } else if (!success) {
    showToast('执行未完全成功，可返回修改计划后重试', 'warning');
  } else if (agentVerificationReport && agentVerificationReport.passed === false) {
    showToast('答案已生成，但校验仍有未通过项 — 建议展开「校验清单」修订', 'warning');
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
  const solveType = solveData.type || parsed.type || '';
  if (solveType === 'short_answer' || solveType === 'theory') {
    const constraints = getUserConstraints();
    return {
      id: `dlv_local_${Date.now()}`,
      type: 'theory',
      created_at: new Date().toISOString(),
      sections: {
        answer: solveData.answer || parsed.answer || '',
        notes: parsed.notes || solveData.notes || '',
      },
      code: { files: [], language: '', main_file: '' },
      diagrams: [],
      execution: {
        validation_status: 'not_requested',
        validation_note: '简答题无需代码验证',
      },
      constraints_applied: constraints,
      provenance: {
        ai_assisted: true,
        generated_at: new Date().toISOString(),
      },
      quality: {},
    };
  }
  const isCodeCloze = solveType === 'code_cloze';
  const codeFiles = solveData.code_files || parsed.code_files || [];
  const files = codeFiles.length
    ? codeFiles.map((f) => ({ name: f.name || f.filename || 'main', code: f.code || f.content || '' }))
    : (solveData.code || parsed.code)
      ? [{ name: solveData.main_file || parsed.main_file || 'main.py', code: solveData.code || parsed.code }]
      : (parsed.completed_code || '').trim()
        ? [{ name: solveData.main_file || parsed.main_file || 'main.java', code: parsed.completed_code }]
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
    const runReason = runResult.reason || '';
    if (codeStatus === 'verified') {
      validationStatus = 'verified';
      validationNote = '代码已通过内化验证沙箱';
    } else if (codeStatus === 'degraded') {
      validationStatus = 'failed';
      validationNote = '内化验证未通过';
    } else if (runReason === 'missing_jar') {
      validationStatus = 'skipped';
      const labels = (runResult.missing_jars || []).map((j) => j.label || j.id).join('、');
      validationNote = labels
        ? `验证需要白名单 jar（${labels}），等待你确认下载`
        : '验证需要白名单 jar，等待你确认下载';
    } else if (runReason === 'jar_download_declined') {
      validationStatus = 'skipped';
      validationNote = '未同意下载验证所需 jar';
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
    type: isCodeCloze ? 'code_cloze' : 'lab_report',
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
    ...(isCodeCloze
      ? (() => {
        const refBlanks = getCodeClozeReferenceBlanks({});
        return {
          code_cloze: {
            blanks: parsed.blanks || {},
            completed_code: parsed.completed_code || '',
            pattern_note: parsed.pattern_note || '',
            ...(Object.keys(refBlanks).length ? { reference_blanks: refBlanks } : {}),
          },
        };
      })()
      : {}),
  };
}

let activeDeliverableTab = 'steps_analysis';
let activeDeliverablePreviewTab = 'code';

function deliverableSectionHasContent(dlv, tabId) {
  if (tabId === 'code') {
    return (dlv.code?.files || []).some((f) => (f.code || '').trim());
  }
  if (tabId === 'diagrams') {
    return (dlv.diagrams || []).length > 0;
  }
  return Boolean((dlv.sections || {})[tabId]?.trim());
}

function deliverableSectionCharCount(dlv, tabId) {
  if (tabId === 'code') {
    return (dlv.code?.files || []).reduce((n, f) => n + (f.code || '').replace(/\s/g, '').length, 0);
  }
  if (tabId === 'diagrams') {
    return (dlv.diagrams || []).length;
  }
  return ((dlv.sections || {})[tabId] || '').replace(/\s/g, '').length;
}

function normalizeDeliverableTextTab(tabId, dlv) {
  if (isCodeClozeDeliverable(dlv)) {
    const blanks = getCodeClozeBlankEntries(dlv);
    if (!blanks.length) return 'blank:1';
    const cur = String(tabId || '');
    if (cur.startsWith('blank:')) {
      const n = Number(cur.slice(6));
      if (blanks.some((b) => b.n === n)) return cur;
    }
    return `blank:${blanks[0].n}`;
  }
  if (DELIVERABLE_TEXT_SECTIONS.some((t) => t.id === tabId)) return tabId;
  const withContent = DELIVERABLE_TEXT_SECTIONS.find((t) => deliverableSectionHasContent(dlv, t.id));
  return withContent?.id || 'steps_analysis';
}

function isMixedAssignmentDeliverable(dlv) {
  return dlv?.type === 'mixed_assignment'
    || (Array.isArray(dlv?.mixed_parts) && dlv.mixed_parts.length > 1);
}

function isCodeClozeDeliverable(dlv) {
  if (isMixedAssignmentDeliverable(dlv)) return false;
  return (dlv?.type === 'code_cloze')
    || Boolean(dlv?.code_cloze?.blanks)
    || Boolean(dlv?.code_cloze?.completed_code);
}

function getCodeClozeBlankEntries(dlv) {
  const blanks = dlv?.code_cloze?.blanks || {};
  if (!blanks || typeof blanks !== 'object') return [];
  return Object.entries(blanks)
    .map(([k, v]) => {
      const n = Number(k);
      if (!Number.isFinite(n)) return null;
      if (v && typeof v === 'object') {
        return {
          n,
          answer: String(v.answer || '').trim(),
          brief: String(v.brief || '').trim(),
        };
      }
      return { n, answer: String(v || '').trim(), brief: '' };
    })
    .filter(Boolean)
    .sort((a, b) => a.n - b.n);
}

function getCodeClozeCompletedCode(dlv) {
  const code = String(dlv?.code_cloze?.completed_code || '').trim();
  if (code) return code;
  const files = dlv?.code?.files || [];
  if (files.length === 1) return String(files[0]?.code || '');
  if (files.length > 1) return files.map((f) => String(f.code || '')).join('\n\n');
  return '';
}

function getCodeClozePatternNote(dlv) {
  return String(dlv?.code_cloze?.pattern_note || '').trim();
}

function normalizeClozeAnswer(s) {
  return String(s || '').trim().replace(/\s+/g, ' ');
}

function matchClozeAnswer(user, primary, answerAlt) {
  const normUser = normalizeClozeAnswer(user);
  if (!normUser) return false;
  const candidates = [primary].concat(answerAlt || []);
  return candidates.some((c) => c && normalizeClozeAnswer(c) === normUser);
}

function normalizeReferenceBlanksMap(raw) {
  const out = {};
  if (!raw || typeof raw !== 'object') return out;
  if (Array.isArray(raw)) {
    raw.forEach((item) => {
      if (!item || typeof item !== 'object' || item.n == null) return;
      const key = String(item.n).trim();
      if (!key) return;
      out[key] = {
        answer: String(item.answer || '').trim(),
        answer_alt: (item.answer_alt || []).map((a) => String(a).trim()).filter(Boolean),
        brief: String(item.brief || item.explanation || '').trim(),
      };
    });
    return out;
  }
  Object.entries(raw).forEach(([k, v]) => {
    const key = String(k).trim();
    if (!key) return;
    if (v && typeof v === 'object') {
      out[key] = {
        answer: String(v.answer || '').trim(),
        answer_alt: (v.answer_alt || []).map((a) => String(a).trim()).filter(Boolean),
        brief: String(v.brief || v.explanation || '').trim(),
      };
    } else {
      out[key] = { answer: String(v || '').trim(), answer_alt: [], brief: '' };
    }
  });
  return out;
}

function getCodeClozeReferenceBlanks(dlv, segmentId) {
  if (segmentId != null && Array.isArray(dlv?.mixed_parts)) {
    const part = dlv.mixed_parts.find((p) => String(p.segment_id) === String(segmentId));
    const fromPart = part?.code_cloze?.reference_blanks;
    if (fromPart && Object.keys(fromPart).length) {
      return normalizeReferenceBlanksMap(fromPart);
    }
  }
  const fromDlv = dlv?.code_cloze?.reference_blanks;
  if (fromDlv && typeof fromDlv === 'object' && Object.keys(fromDlv).length) {
    return normalizeReferenceBlanksMap(fromDlv);
  }
  const questions = parsedQuestions || [];
  const q = segmentId != null
    ? questions.find((item) => String(item.id) === String(segmentId))
    : questions.find((item) => item.type === 'code_cloze') || questions[0];
  const meta = q?.metadata || parsedMetadata || {};
  const raw = meta.reference_blanks || meta.code_cloze?.reference_blanks;
  return normalizeReferenceBlanksMap(raw);
}

function getActiveMixedDeliverablePart(dlv) {
  const parts = Array.isArray(dlv?.mixed_parts) ? dlv.mixed_parts : [];
  if (!parts.length) return null;
  const activeId = window._mixedDeliverableTab;
  return parts.find((p) => String(p.segment_id) === String(activeId)) || parts[0];
}

function buildCodeClozeReferenceCompareHtml(aiBlanks, refBlanks) {
  const refKeys = Object.keys(refBlanks || {});
  if (!refKeys.length) return '';
  const rows = aiBlanks.map((b) => {
    const ref = refBlanks[String(b.n)];
    if (!ref || !ref.answer) {
      return `<tr class="code-cloze-ref-row ref-skip">
        <td>空 ${b.n}</td>
        <td><code class="code-cloze-ref-code">${escapeHtml(b.answer || '—')}</code></td>
        <td class="code-cloze-ref-muted">—</td>
        <td><span class="code-cloze-ref-badge ref-na">无参考答案</span></td>
      </tr>`;
    }
    const matched = matchClozeAnswer(b.answer, ref.answer, ref.answer_alt);
    const altHint = (ref.answer_alt || []).length
      ? `<span class="code-cloze-ref-alt-hint">亦可：${escapeHtml(ref.answer_alt.join(' / '))}</span>`
      : '';
    return `<tr class="code-cloze-ref-row ${matched ? 'ref-match' : 'ref-mismatch'}">
      <td>空 ${b.n}</td>
      <td><code class="code-cloze-ref-code">${escapeHtml(b.answer || '（空）')}</code></td>
      <td><code class="code-cloze-ref-code">${escapeHtml(ref.answer)}</code>${altHint}</td>
      <td><span class="code-cloze-ref-badge ${matched ? 'ref-ok' : 'ref-diff'}">${matched ? '一致' : '不一致'}</span></td>
    </tr>`;
  });
  const comparable = aiBlanks.filter((b) => {
    const ref = refBlanks[String(b.n)];
    return ref && ref.answer;
  });
  const matchedCount = comparable.filter((b) => {
    const ref = refBlanks[String(b.n)];
    return matchClozeAnswer(b.answer, ref.answer, ref.answer_alt);
  }).length;
  const summaryText = comparable.length
    ? `一致 ${matchedCount} / 共 ${comparable.length} 空（有参考答案）`
    : '暂无可用参考答案';
  return `<details class="code-cloze-ref-compare"${comparable.length ? ' open' : ''}>
    <summary class="code-cloze-ref-summary-row">
      <span>与参考答案对照</span>
      <span class="code-cloze-ref-summary ${matchedCount === comparable.length && comparable.length ? 'is-perfect' : ''}">${summaryText}</span>
    </summary>
    <div class="code-cloze-ref-table-wrap">
      <table class="code-cloze-ref-table">
        <thead>
          <tr><th>空</th><th>AI 答案</th><th>参考答案</th><th>状态</th></tr>
        </thead>
        <tbody>${rows.join('')}</tbody>
      </table>
    </div>
    <p class="form-hint code-cloze-ref-note">只读对照：忽略首尾与中间多余空白；不做法题输入判分。</p>
  </details>`;
}

function updateDeliverablePreviewChrome() {
  const grid = document.getElementById('deliverableGrid');
  const backdrop = document.getElementById('deliverablePreviewBackdrop');
  const openBtn = document.getElementById('deliverablePreviewOpen');
  const toggleBtn = document.getElementById('deliverablePreviewToggle');
  const narrow = window.matchMedia('(max-width: 1199px)').matches;
  const isOpen = Boolean(grid?.classList.contains('preview-open'));
  if (openBtn) {
    if (narrow && !isOpen) uiShow(openBtn, 'inline-flex');
    else uiHide(openBtn);
  }
  if (toggleBtn) toggleBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
  if (backdrop) backdrop.hidden = !(narrow && isOpen);
  if (grid && !narrow && isOpen) grid.classList.remove('preview-open');
}

function toggleDeliverablePreview(forceOpen) {
  const grid = document.getElementById('deliverableGrid');
  if (!grid) return;
  const open = typeof forceOpen === 'boolean' ? forceOpen : !grid.classList.contains('preview-open');
  grid.classList.toggle('preview-open', open);
  updateDeliverablePreviewChrome();
}

function switchDeliverablePreviewTab(tabId) {
  activeDeliverablePreviewTab = tabId;
  if (currentDeliverable) renderDeliverablePreview(currentDeliverable);
}

function isTheoryDeliverable(dlv) {
  return dlv?.type === 'theory';
}

function resetTheoryWorkspaceState() {
  window._theoryQuestionId = null;
  window._theoryViewTab = 'questions';
  window._theoryWorkspaceEntered = false;
  if (window.TheoryMotion?.killTheoryMotion) window.TheoryMotion.killTheoryMotion();
  document.getElementById('deliverableGrid')?.classList.remove('deliverable-grid--theory');
  document.getElementById('theoryCopyAllBtn')?.remove();
}

function parseTheoryAnswerBlocks(text) {
  const raw = String(text || '').trim();
  if (!raw) return [];

  const headerRe = /^\*\*(第?\d+题[^*]*|[^*]+)\*\*\s*$/;
  const lines = raw.split('\n');
  const chunks = [];
  let current = null;

  for (const line of lines) {
    const m = line.match(headerRe);
    if (m) {
      if (current) chunks.push(current);
      const title = m[1].trim();
      const idMatch = title.match(/^第?(\d+)题/);
      current = {
        id: idMatch ? idMatch[1] : String(chunks.length + 1),
        title,
        bodyLines: [],
      };
    } else if (current) {
      current.bodyLines.push(line);
    } else if (line.trim()) {
      if (!current) current = { id: '1', title: '简答答案', bodyLines: [] };
      current.bodyLines.push(line);
    }
  }
  if (current) {
    chunks.push({
      id: current.id,
      title: current.title,
      body: current.bodyLines.join('\n').trim(),
    });
  }
  if (chunks.length) return chunks;

  const numbered = raw.split(/(?=^\d+[.、．]\s)/m).filter((s) => s.trim());
  if (numbered.length > 1) {
    return numbered.map((chunk, i) => {
      const firstLine = (chunk.trim().split('\n')[0] || '').trim();
      return {
        id: String(i + 1),
        title: firstLine.slice(0, 80) || `第 ${i + 1} 题`,
        body: chunk.trim(),
      };
    });
  }

  return [{ id: 'all', title: '简答答案', body: raw }];
}

function getTheoryAnswerBlocks(dlv) {
  return parseTheoryAnswerBlocks((dlv?.sections || {}).answer || '');
}

function getActiveTheoryBlock(dlv) {
  const blocks = getTheoryAnswerBlocks(dlv);
  if (!blocks.length) return null;
  const wanted = window._theoryQuestionId;
  if (wanted != null && wanted !== '') {
    const hit = blocks.find((b) => String(b.id) === String(wanted));
    if (hit) return hit;
  }
  return blocks[0];
}

function ensureTheoryCopyAllBtn() {
  const actions = document.querySelector('.deliverable-toolbar-actions');
  if (!actions || document.getElementById('theoryCopyAllBtn')) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn-secondary btn-sm';
  btn.id = 'theoryCopyAllBtn';
  btn.innerHTML = `${ico('copy', 'icon-sm')}复制全部`;
  btn.onclick = () => copyTheoryAllAnswers();
  actions.insertBefore(btn, actions.firstChild);
}

function removeTheoryCopyAllBtn() {
  document.getElementById('theoryCopyAllBtn')?.remove();
}

async function copyTheoryAllAnswers() {
  if (!currentDeliverable || !isTheoryDeliverable(currentDeliverable)) return;
  const text = String((currentDeliverable.sections || {}).answer || '').trim();
  if (!text) {
    showToast('暂无简答内容', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast('已复制全部简答', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyActiveTheoryQuestion() {
  if (!currentDeliverable || !isTheoryDeliverable(currentDeliverable)) return;
  await copyTheoryQuestionBody(getActiveTheoryBlock(currentDeliverable));
}

async function copyTheoryQuestionBody(block) {
  const text = String(block?.body || '').trim();
  if (!text) {
    showToast('本题暂无内容', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    showToast('已复制本题', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

function switchTheoryQuestion(questionId) {
  window._theoryQuestionId = String(questionId);
  window._theoryViewTab = 'questions';
  if (currentDeliverable) renderTheoryWorkspace(currentDeliverable, { animate: true });
}

function switchTheoryNotesTab() {
  window._theoryViewTab = 'notes';
  if (currentDeliverable) renderTheoryWorkspace(currentDeliverable, { animate: true });
}

function renderTheoryWorkspace(dlv, opts = {}) {
  const grid = document.getElementById('deliverableGrid');
  const tabsEl = document.getElementById('deliverableTabs');
  const navCount = document.getElementById('deliverableNavCount');
  const navTitle = document.querySelector('.deliverable-nav-title');
  const titleEl = document.getElementById('deliverableSectionTitle');
  const copyBtn = document.getElementById('copySectionBtn');
  const body = document.getElementById('deliverableSectionBody');
  const previewTabs = document.getElementById('deliverablePreviewTabs');
  const badge = document.getElementById('deliverableValidationBadge');
  const noteEl = document.getElementById('deliverableValidationNote');
  if (!grid || !tabsEl || !body) return;

  grid.classList.add('deliverable-grid--theory');
  ensureTheoryCopyAllBtn();
  if (previewTabs) previewTabs.classList.add('is-hidden');

  const blocks = getTheoryAnswerBlocks(dlv);
  const notes = String((dlv.sections || {}).notes || '').trim();
  const viewingNotes = window._theoryViewTab === 'notes';

  if (badge) {
    badge.textContent = blocks.length > 1 ? `简答题 · 共 ${blocks.length} 题` : '简答题';
    badge.className = 'deliverable-validation-badge skipped';
  }
  if (noteEl) noteEl.textContent = '逐题阅读与复制答案';
  if (navTitle) {
    navTitle.innerHTML = `<span class="icon icon-sm" data-icon="layout-list"></span>题目导航`;
    if (window.Icons?.initDataIcons) Icons.initDataIcons(navTitle);
  }
  if (navCount) {
    navCount.textContent = blocks.length > 1 ? `${blocks.length} 题` : '单题';
  }

  const activeBlock = getActiveTheoryBlock(dlv);
  if (!window._theoryQuestionId && activeBlock) {
    window._theoryQuestionId = String(activeBlock.id);
  }

  tabsEl.innerHTML = blocks.map((b) => {
    const isActive = !viewingNotes && String(b.id) === String(activeBlock?.id);
    const hasContent = Boolean(b.body);
    const label = b.title.length > 28 ? `${b.title.slice(0, 28)}…` : b.title;
    const statusHtml = hasContent
      ? '<span class="deliverable-nav-status icon icon-sm" data-icon="check-circle"></span>'
      : '<span class="deliverable-nav-status" aria-hidden="true"></span>';
    return `<button type="button" role="tab" aria-selected="${isActive}"
      class="deliverable-nav-item${isActive ? ' active' : ''}${hasContent ? ' has-content' : ' empty'}"
      data-theory-q="${escapeHtml(String(b.id))}" onclick="switchTheoryQuestion('${escapeHtml(String(b.id))}')">
      ${statusHtml}
      <span class="deliverable-nav-text">
        <span class="deliverable-nav-label">${escapeHtml(label)}</span>
        <span class="deliverable-nav-meta">${hasContent ? '已生成' : '暂无'}</span>
      </span>
    </button>`;
  }).join('')
    + (notes
      ? `<button type="button" role="tab" aria-selected="${viewingNotes}"
      class="deliverable-nav-item${viewingNotes ? ' active' : ''} has-content"
      onclick="switchTheoryNotesTab()">
      <span class="deliverable-nav-status icon icon-sm" data-icon="check-circle"></span>
      <span class="deliverable-nav-text">
        <span class="deliverable-nav-label">备注</span>
        <span class="deliverable-nav-meta">已生成</span>
      </span>
    </button>`
      : '');
  if (window.Icons?.initDataIcons) Icons.initDataIcons(tabsEl);

  if (viewingNotes) {
    if (titleEl) titleEl.textContent = '备注';
    body.innerHTML = notes
      ? `<div class="theory-qa-card"><div class="theory-qa-body">${escapeHtml(notes).replace(/\n/g, '<br>')}</div></div>`
      : emptyStateHtml('file-text', '暂无备注', '');
    if (copyBtn) {
      copyBtn.disabled = !notes;
      copyBtn.innerHTML = `${ico('copy', 'icon-sm')}复制备注`;
    }
  } else if (activeBlock?.body) {
    if (titleEl) titleEl.textContent = activeBlock.title;
    body.innerHTML = `<article class="theory-qa-card" data-theory-card="${escapeHtml(String(activeBlock.id))}">
      <h5 class="theory-qa-title">${escapeHtml(activeBlock.title)}</h5>
      <div class="theory-qa-body">${escapeHtml(activeBlock.body).replace(/\n/g, '<br>')}</div>
      <div class="theory-qa-actions">
        <button type="button" class="btn-ghost btn-sm" onclick="copyActiveTheoryQuestion()">
          ${ico('copy', 'icon-sm')}复制本题
        </button>
      </div>
    </article>`;
    if (copyBtn) {
      copyBtn.disabled = false;
      copyBtn.innerHTML = `${ico('copy', 'icon-sm')}复制本题`;
    }
  } else {
    if (titleEl) titleEl.textContent = '简答答案';
    body.innerHTML = emptyStateHtml('file-text', '暂无简答内容', '执行完成后将显示逐题答案');
    if (copyBtn) copyBtn.disabled = true;
  }

  updateDeliverablePreviewChrome();

  const shouldEnter = !window._theoryWorkspaceEntered && !opts.animate;
  if (shouldEnter) {
    window._theoryWorkspaceEntered = true;
    const cards = body.querySelectorAll('.theory-qa-card');
    const contentCol = document.querySelector('.deliverable-content-col');
    if (window.TheoryMotion?.animateTheoryWorkspaceEnter) {
      window.TheoryMotion.animateTheoryWorkspaceEnter(grid, cards, contentCol);
    }
  } else if (opts.animate && window.TheoryMotion?.animateTheoryTabSwitch) {
    window.TheoryMotion.animateTheoryTabSwitch(body);
  }
}

function renderDeliverableWorkspace(dlv) {
  const wrap = document.getElementById('deliverableWorkspace');
  if (!wrap || !dlv) return;
  uiShow(wrap, 'block');
  currentDeliverable = dlv;

  if (!isTheoryDeliverable(dlv)) {
    resetTheoryWorkspaceState();
  }

  activeDeliverableTab = normalizeDeliverableTextTab(activeDeliverableTab, dlv);
  const copyBtn = document.getElementById('copySectionBtn');
  if (copyBtn) {
    copyBtn.innerHTML = `${ico('copy', 'icon-sm')}复制本节`;
  }
  const previewTabs = document.getElementById('deliverablePreviewTabs');
  if (previewTabs) {
    previewTabs.querySelector('[data-preview="code"]')?.classList.remove('is-hidden');
    previewTabs.querySelector('[data-preview="diagrams"]')?.classList.remove('is-hidden');
  }

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

  if (isMixedAssignmentDeliverable(dlv)) {
    renderMixedAssignmentWorkspace(dlv);
    updateDeliverablePreviewChrome();
    return;
  }

  if (isCodeClozeDeliverable(dlv)) {
    renderCodeClozeWorkspace(dlv);
    updateDeliverablePreviewChrome();
    return;
  }

  if (isTheoryDeliverable(dlv)) {
    renderTheoryWorkspace(dlv);
    return;
  }

  const filledCount = DELIVERABLE_TEXT_SECTIONS.filter((t) => deliverableSectionHasContent(dlv, t.id)).length;
  const navCount = document.getElementById('deliverableNavCount');
  if (navCount) {
    navCount.textContent = `共 ${DELIVERABLE_TEXT_SECTIONS.length} 节 · ${filledCount} 已完成`;
  }

  const tabsEl = document.getElementById('deliverableTabs');
  if (tabsEl) {
    tabsEl.innerHTML = DELIVERABLE_TEXT_SECTIONS.map((t) => {
      const hasContent = deliverableSectionHasContent(dlv, t.id);
      const chars = deliverableSectionCharCount(dlv, t.id);
      const meta = hasContent ? `${chars.toLocaleString()} 字` : '暂无内容';
      const statusHtml = hasContent
        ? '<span class="deliverable-nav-status icon icon-sm" data-icon="check-circle"></span>'
        : '<span class="deliverable-nav-status" aria-hidden="true"></span>';
      return `<button type="button" role="tab" aria-selected="${activeDeliverableTab === t.id}"
        class="deliverable-nav-item${activeDeliverableTab === t.id ? ' active' : ''}${hasContent ? ' has-content' : ' empty'}"
        data-tab="${t.id}" onclick="switchDeliverableTab('${t.id}')">
        ${statusHtml}
        <span class="deliverable-nav-text">
          <span class="deliverable-nav-label">${escapeHtml(t.label)}</span>
          <span class="deliverable-nav-meta">${meta}</span>
        </span>
      </button>`;
    }).join('');
    if (window.Icons?.initDataIcons) Icons.initDataIcons(tabsEl);
  }

  const titleEl = document.getElementById('deliverableSectionTitle');
  const activeMeta = DELIVERABLE_TEXT_SECTIONS.find((t) => t.id === activeDeliverableTab);
  if (titleEl && activeMeta) titleEl.textContent = activeMeta.label;

  if (copyBtn) {
    const hasText = deliverableSectionHasContent(dlv, activeDeliverableTab);
    copyBtn.disabled = !hasText;
  }

  renderDeliverableTabContent(dlv, activeDeliverableTab);
  renderDeliverablePreview(dlv);
  updateDeliverablePreviewChrome();
}

function renderMixedAssignmentWorkspace(dlv) {
  const parts = Array.isArray(dlv.mixed_parts) ? dlv.mixed_parts : [];
  const tabsEl = document.getElementById('deliverableTabs');
  const navCount = document.getElementById('deliverableNavCount');
  const titleEl = document.getElementById('deliverableSectionTitle');
  const copyBtn = document.getElementById('copySectionBtn');
  const body = document.getElementById('deliverableSectionBody');
  const previewTabs = document.getElementById('deliverablePreviewTabs');
  const codeEl = document.getElementById('deliverableCodePreview');
  const diagramsWrap = document.getElementById('deliverableDiagrams');
  if (!tabsEl || !body) return;

  if (!window._mixedDeliverableTab && parts.length) {
    window._mixedDeliverableTab = String(parts[0].segment_id ?? 0);
  }
  const activePart = getActiveMixedDeliverablePart(dlv);

  if (navCount) {
    navCount.textContent = `混排卷 · ${parts.length} 段`;
  }
  tabsEl.innerHTML = parts.map((p) => {
    const isActive = String(p.segment_id) === String(activePart?.segment_id);
    const label = p.title || (p.type === 'code_cloze' ? '代码填空' : '简答题');
    const typeBadge = p.type === 'code_cloze'
      ? '<span class="mixed-segment-badge mixed-segment-badge-cloze">填空</span>'
      : '<span class="mixed-segment-badge mixed-segment-badge-theory">简答</span>';
    const meta = p.type === 'code_cloze'
      ? `${Object.keys(p.code_cloze?.blanks || {}).length} 空`
      : (p.answer_text ? '已生成' : '暂无');
    const hasContent = p.type === 'code_cloze'
      ? Object.keys(p.code_cloze?.blanks || {}).length > 0
      : Boolean(p.answer_text);
    const statusHtml = hasContent
      ? '<span class="deliverable-nav-status icon icon-sm" data-icon="check-circle"></span>'
      : '<span class="deliverable-nav-status" aria-hidden="true"></span>';
    return `<button type="button" role="tab" aria-selected="${isActive}"
      class="deliverable-nav-item${isActive ? ' active' : ''}${hasContent ? ' has-content' : ' empty'}"
      data-mixed-seg="${p.segment_id}" onclick="switchMixedDeliverableTab('${p.segment_id}')">
      ${statusHtml}
      <span class="deliverable-nav-text">
        <span class="deliverable-nav-label">${typeBadge}${escapeHtml(label)}</span>
        <span class="deliverable-nav-meta">${escapeHtml(meta)}</span>
      </span>
    </button>`;
  }).join('');
  if (window.Icons?.initDataIcons) Icons.initDataIcons(tabsEl);

  if (titleEl && activePart) {
    titleEl.textContent = activePart.title || (activePart.type === 'code_cloze' ? '代码填空' : '简答题');
  }

  if (activePart?.type === 'code_cloze') {
    const clozeDlv = {
      ...dlv,
      type: 'code_cloze',
      code_cloze: activePart.code_cloze || dlv.code_cloze || {},
    };
    renderCodeClozeWorkspace(clozeDlv, {
      embeddedInMixed: true,
      segmentId: activePart.segment_id,
    });
    return;
  }

  window._mixedClozeBlankTab = null;
  if (previewTabs) previewTabs.classList.add('is-hidden');
  if (codeEl) {
    codeEl.innerHTML = '';
    uiHide(codeEl);
  }
  if (diagramsWrap) {
    diagramsWrap.innerHTML = '';
    uiHide(diagramsWrap);
  }
  const text = String(activePart?.answer_text || '').trim();
  body.innerHTML = text
    ? `<div class="deliverable-section-text">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`
    : emptyStateHtml('file-text', '暂无简答内容', '执行完成后将显示本段答案');
  if (copyBtn) {
    copyBtn.disabled = !text;
    copyBtn.innerHTML = `${ico('copy', 'icon-sm')}复制本节`;
  }
  updateDeliverablePreviewChrome();
}

function switchMixedDeliverableTab(segmentId) {
  window._mixedDeliverableTab = String(segmentId);
  window._mixedClozeBlankTab = null;
  activeDeliverableTab = 'blank:1';
  if (currentDeliverable) renderMixedAssignmentWorkspace(currentDeliverable);
}

function switchMixedClozeBlankTab(blankId) {
  window._mixedClozeBlankTab = String(blankId);
  activeDeliverableTab = `blank:${blankId}`;
  if (currentDeliverable && isMixedAssignmentDeliverable(currentDeliverable)) {
    renderMixedAssignmentWorkspace(currentDeliverable);
  }
}

function renderCodeClozeWorkspace(dlv, opts = {}) {
  const embeddedInMixed = opts.embeddedInMixed === true;
  const segmentId = opts.segmentId;
  const tabsEl = document.getElementById('deliverableTabs');
  const navCount = document.getElementById('deliverableNavCount');
  const titleEl = document.getElementById('deliverableSectionTitle');
  const copyBtn = document.getElementById('copySectionBtn');
  const body = document.getElementById('deliverableSectionBody');
  const codeEl = document.getElementById('deliverableCodePreview');
  const diagramsWrap = document.getElementById('deliverableDiagrams');
  const previewTabs = document.getElementById('deliverablePreviewTabs');
  const blanks = getCodeClozeBlankEntries(dlv);
  const filled = blanks.filter((b) => b.answer).length;

  if (!embeddedInMixed) {
    if (navCount) navCount.textContent = `共 ${blanks.length} 空 · ${filled} 已填写`;
    if (titleEl) titleEl.textContent = '空号答案';
  } else if (titleEl) {
    titleEl.textContent = '空号答案';
  }

  const blankTabId = embeddedInMixed && window._mixedClozeBlankTab
    ? `blank:${window._mixedClozeBlankTab}`
    : activeDeliverableTab;
  const currentBlank = Number(String(blankTabId || '').replace('blank:', ''));
  const selected = blanks.find((b) => b.n === currentBlank) || blanks[0] || null;
  if (selected) {
    activeDeliverableTab = `blank:${selected.n}`;
    if (embeddedInMixed) window._mixedClozeBlankTab = String(selected.n);
  }

  if (copyBtn) {
    copyBtn.innerHTML = `${ico('copy', 'icon-sm')}复制本空`;
    const hasCurrent = selected && selected.answer;
    copyBtn.disabled = !hasCurrent;
  }

  const blankNavHtml = blanks.map((b) => {
    const activeId = `blank:${b.n}`;
    const isActive = selected && b.n === selected.n;
    const answerMeta = b.answer || '待填写';
    const onClick = embeddedInMixed
      ? `switchMixedClozeBlankTab('${b.n}')`
      : `switchDeliverableTab('${activeId}')`;
    return `<button type="button" role="tab" aria-selected="${isActive ? 'true' : 'false'}"
      class="mixed-cloze-blank-item${isActive ? ' active' : ''}${b.answer ? ' has-content' : ''}"
      data-tab="${activeId}" onclick="${onClick}">
      <span class="mixed-cloze-blank-label">空 ${b.n}</span>
      <span class="mixed-cloze-blank-meta">${escapeHtml(answerMeta)}</span>
    </button>`;
  }).join('');

  if (!embeddedInMixed && tabsEl) {
    tabsEl.innerHTML = blanks.map((b) => {
      const activeId = `blank:${b.n}`;
      const isActive = selected && b.n === selected.n;
      const answerMeta = b.answer || '待填写';
      const statusHtml = b.answer
        ? '<span class="deliverable-nav-status icon icon-sm" data-icon="check-circle"></span>'
        : '<span class="deliverable-nav-status" aria-hidden="true"></span>';
      return `<button type="button" role="tab" aria-selected="${isActive ? 'true' : 'false'}"
        class="deliverable-nav-item${isActive ? ' active' : ''}${b.answer ? ' has-content' : ' empty'}"
        data-tab="${activeId}" onclick="switchDeliverableTab('${activeId}')">
        ${statusHtml}
        <span class="deliverable-nav-text">
          <span class="deliverable-nav-label">空 ${b.n}</span>
          <span class="deliverable-nav-meta">${escapeHtml(answerMeta)}</span>
        </span>
      </button>`;
    }).join('');
    if (window.Icons?.initDataIcons) Icons.initDataIcons(tabsEl);
  }

  if (body) {
    const refBlanks = getCodeClozeReferenceBlanks(dlv, segmentId);
    const compareHtml = buildCodeClozeReferenceCompareHtml(blanks, refBlanks);
    const innerNav = embeddedInMixed && blanks.length
      ? `<div class="mixed-cloze-inner-nav" role="tablist" aria-label="空号">${blankNavHtml}</div>`
      : '';
    if (selected) {
      const brief = selected.brief
        ? `<div class="code-cloze-blank-brief">${escapeHtml(selected.brief)}</div>`
        : '';
      body.innerHTML = `<div class="mixed-cloze-inner">${innerNav}<div class="code-cloze-answer-card">
        <div class="code-cloze-blank-head">空 ${selected.n}</div>
        <pre class="deliverable-code-block">${escapeHtml(selected.answer || '（暂无答案）')}</pre>
        ${brief}
      </div>${compareHtml}</div>`;
    } else {
      body.innerHTML = `<div class="mixed-cloze-inner">${innerNav}<p class="form-hint">（未识别到空号）</p>${compareHtml}</div>`;
    }
  }

  if (previewTabs) {
    previewTabs.classList.remove('is-hidden');
    previewTabs.querySelector('[data-preview="code"]')?.classList.remove('is-hidden');
    previewTabs.querySelector('[data-preview="diagrams"]')?.classList.add('is-hidden');
  }
  activeDeliverablePreviewTab = 'code';
  if (codeEl) {
    const completed = getCodeClozeCompletedCode(dlv);
    const note = getCodeClozePatternNote(dlv);
    codeEl.innerHTML = completed
      ? `<pre class="deliverable-code-block">${escapeHtml(completed)}</pre>`
      : '<p class="form-hint">（无完整代码预览）</p>';
    if (note) {
      codeEl.innerHTML += `<p class="form-hint code-cloze-pattern-note">${escapeHtml(note)}</p>`;
    }
  }
  if (diagramsWrap) {
    diagramsWrap.innerHTML = '';
    uiHide(diagramsWrap);
  }
  if (codeEl) uiShow(codeEl);
  updateDeliverablePreviewCopyBtn(dlv, { embeddedInMixed });
  if (embeddedInMixed) updateDeliverablePreviewChrome();
}

function switchDeliverableTab(tabId) {
  if (currentDeliverable && isMixedAssignmentDeliverable(currentDeliverable)) {
    if (String(tabId).startsWith('blank:')) {
      switchMixedClozeBlankTab(String(tabId).replace('blank:', ''));
    }
    return;
  }
  if (currentDeliverable && isCodeClozeDeliverable(currentDeliverable)) {
    if (!String(tabId).startsWith('blank:')) return;
    activeDeliverableTab = tabId;
    renderDeliverableWorkspace(currentDeliverable);
    animateDeliverableSectionEnter();
    return;
  }
  if (!DELIVERABLE_TEXT_SECTIONS.some((t) => t.id === tabId)) return;
  activeDeliverableTab = tabId;
  if (currentDeliverable) {
    renderDeliverableWorkspace(currentDeliverable);
    animateDeliverableSectionEnter();
  }
}

function animateDeliverableSectionEnter() {
  const body = document.getElementById('deliverableSectionBody');
  if (!body || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  body.classList.remove('is-entering');
  void body.offsetWidth;
  body.classList.add('is-entering');
  body.addEventListener('animationend', () => body.classList.remove('is-entering'), { once: true });
}

function renderDeliverableTabContent(dlv, tabId) {
  const body = document.getElementById('deliverableSectionBody');
  if (!body) return;

  const text = (dlv.sections || {})[tabId] || '';
  body.innerHTML = text.trim()
    ? `<pre class="deliverable-text-block">${escapeHtml(text)}</pre>`
    : '<p class="form-hint">（本节暂无内容）</p>';
}

function renderDeliverablePreview(dlv) {
  const codeEl = document.getElementById('deliverableCodePreview');
  const diagramsWrap = document.getElementById('deliverableDiagrams');
  const previewTabs = document.getElementById('deliverablePreviewTabs');
  if (!codeEl || !diagramsWrap) return;

  previewTabs?.querySelectorAll('.deliverable-preview-tab').forEach((btn) => {
    const on = btn.getAttribute('data-preview') === activeDeliverablePreviewTab;
    btn.classList.toggle('active', on);
    btn.setAttribute('aria-selected', on ? 'true' : 'false');
  });

  const files = dlv.code?.files || [];
  codeEl.innerHTML = files.length
    ? files.map((f, idx) => `
      <div class="deliverable-code-file">
        <div class="deliverable-code-file-head">
          <div class="deliverable-code-filename">${escapeHtml(f.name || 'code')}</div>
          <button type="button" class="btn-ghost btn-xs" onclick="copyDeliverableCodeFile(${idx})" title="复制此文件">
            <span class="icon icon-sm" data-icon="copy"></span>复制
          </button>
        </div>
        <pre class="deliverable-code-block">${escapeHtml(f.code || '')}</pre>
      </div>`).join('')
    : '<p class="form-hint">（无代码）</p>';
  if (files.length && window.Icons?.initDataIcons) Icons.initDataIcons(codeEl);

  const items = dlv.diagrams || [];
  diagramsWrap.innerHTML = items.length
    ? items.map((d, idx) => {
      const img = d.image_b64
        ? `<img src="data:image/png;base64,${d.image_b64}" alt="${escapeHtml(d.title || '')}" class="deliverable-diagram-img"/>`
        : '';
      const src = d.plantuml
        ? `<pre class="deliverable-code-block">${escapeHtml(d.plantuml)}</pre>`
        : '';
      const actions = [];
      if (d.image_b64) {
        actions.push(`<button type="button" class="btn-ghost btn-xs" onclick="copyDeliverableDiagramImage(${idx})"><span class="icon icon-sm" data-icon="copy"></span>复制图片</button>`);
      }
      if (d.plantuml) {
        actions.push(`<button type="button" class="btn-ghost btn-xs" onclick="copyDeliverableDiagramSource(${idx})"><span class="icon icon-sm" data-icon="copy"></span>复制图源</button>`);
      }
      const actionsHtml = actions.length
        ? `<div class="deliverable-diagram-actions">${actions.join('')}</div>`
        : '';
      return `<div class="deliverable-diagram-card"><h5>${escapeHtml(d.title || '图')}</h5>${img}${src}${actionsHtml}</div>`;
    }).join('')
    : '<p class="form-hint">（无图表）</p>';
  if (items.length && window.Icons?.initDataIcons) Icons.initDataIcons(diagramsWrap);

  const showCode = activeDeliverablePreviewTab === 'code';
  if (showCode) {
    uiShow(codeEl);
    uiHide(diagramsWrap);
  } else {
    uiHide(codeEl);
    uiShow(diagramsWrap);
  }

  updateDeliverablePreviewCopyBtn(dlv);
}

function updateDeliverablePreviewCopyBtn(dlv, opts = {}) {
  const btn = document.getElementById('copyPreviewBtn');
  if (!btn) return;
  const clozeDlv = opts.embeddedInMixed && isMixedAssignmentDeliverable(dlv)
    ? {
      ...dlv,
      code_cloze: getActiveMixedDeliverablePart(dlv)?.code_cloze || dlv.code_cloze || {},
    }
    : dlv;
  if (isCodeClozeDeliverable(clozeDlv) || opts.embeddedInMixed) {
    const hasBlanks = getCodeClozeBlankEntries(clozeDlv).length > 0;
    btn.disabled = !hasBlanks;
    btn.innerHTML = `${ico('copy', 'icon-sm')}复制全部空号`;
    return;
  }
  const isCode = activeDeliverablePreviewTab === 'code';
  const hasCode = (dlv?.code?.files || []).length > 0;
  const hasDiagrams = (dlv?.diagrams || []).length > 0;
  btn.disabled = isCode ? !hasCode : !hasDiagrams;
  btn.innerHTML = isCode
    ? `${ico('copy', 'icon-sm')}复制代码`
    : `${ico('copy', 'icon-sm')}复制图表`;
}

function buildDeliverableCodeText(dlv) {
  const files = dlv?.code?.files || [];
  if (!files.length) return '';
  if (files.length === 1) return files[0].code || '';
  return files.map((f) => {
    const name = f.name || 'code';
    return `// ${name}\n${f.code || ''}`;
  }).join('\n\n');
}

async function copyImageB64ToClipboard(b64) {
  const blob = await fetch(`data:image/png;base64,${b64}`).then((r) => r.blob());
  if (!navigator.clipboard?.write || typeof ClipboardItem === 'undefined') {
    throw new Error('当前环境不支持复制图片');
  }
  const type = blob.type || 'image/png';
  await navigator.clipboard.write([new ClipboardItem({ [type]: blob })]);
}

async function copyDeliverableCode() {
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  const text = buildDeliverableCodeText(currentDeliverable);
  if (!text.trim()) {
    showToast('暂无代码', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    const n = (currentDeliverable.code?.files || []).length;
    showToast(n > 1 ? `已复制 ${n} 个代码文件` : '已复制代码', 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyDeliverableCodeFile(fileIndex) {
  if (!currentDeliverable) return;
  const file = (currentDeliverable.code?.files || [])[fileIndex];
  if (!file?.code) {
    showToast('暂无代码', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(file.code);
    showToast(`已复制 ${file.name || '代码'}`, 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyDeliverableDiagrams() {
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  const items = currentDeliverable.diagrams || [];
  if (!items.length) {
    showToast('暂无图表', 'info');
    return;
  }
  if (items.length === 1 && items[0].image_b64) {
    try {
      await copyImageB64ToClipboard(items[0].image_b64);
      showToast('已复制图表图片', 'success');
      return;
    } catch (err) {
      if (items[0].plantuml) {
        try {
          await navigator.clipboard.writeText(items[0].plantuml);
          showToast('图片复制不可用，已复制 PlantUML 源码', 'info');
          return;
        } catch (innerErr) {
          showToast('复制失败: ' + innerErr.message, 'error');
          return;
        }
      }
      showToast('复制失败: ' + err.message, 'error');
      return;
    }
  }

  const sources = items
    .map((d, i) => (d.plantuml
      ? `' ${d.title || `图 ${i + 1}`}\n${d.plantuml}`
      : ''))
    .filter(Boolean);
  if (sources.length) {
    try {
      await navigator.clipboard.writeText(sources.join('\n\n'));
      showToast(`已复制 ${sources.length} 段图源`, 'success');
      return;
    } catch (err) {
      showToast('复制失败: ' + err.message, 'error');
      return;
    }
  }

  const firstImage = items.find((d) => d.image_b64);
  if (firstImage) {
    try {
      await copyImageB64ToClipboard(firstImage.image_b64);
      showToast('已复制第一张图表（多张请点卡片上的「复制图片」）', 'success');
    } catch (err) {
      showToast('复制失败: ' + err.message, 'error');
    }
    return;
  }
  showToast('暂无可复制内容', 'info');
}

async function copyDeliverableDiagramImage(index) {
  if (!currentDeliverable) return;
  const item = (currentDeliverable.diagrams || [])[index];
  if (!item?.image_b64) {
    showToast('该图暂无图片', 'info');
    return;
  }
  try {
    await copyImageB64ToClipboard(item.image_b64);
    showToast(`已复制「${item.title || '图表'}」图片`, 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyDeliverableDiagramSource(index) {
  if (!currentDeliverable) return;
  const item = (currentDeliverable.diagrams || [])[index];
  if (!item?.plantuml) {
    showToast('该图暂无源码', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(item.plantuml);
    showToast(`已复制「${item.title || '图表'}」图源`, 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyDeliverablePreview() {
  if (currentDeliverable && isMixedAssignmentDeliverable(currentDeliverable)) {
    const activePart = getActiveMixedDeliverablePart(currentDeliverable);
    if (activePart?.type === 'code_cloze') {
      const clozeDlv = {
        ...currentDeliverable,
        code_cloze: activePart.code_cloze || {},
      };
      const prev = currentDeliverable;
      currentDeliverable = clozeDlv;
      await copyCodeClozeAllBlanks();
      currentDeliverable = prev;
      return;
    }
    showToast('当前段无可复制的代码预览', 'info');
    return;
  }
  if (currentDeliverable && isCodeClozeDeliverable(currentDeliverable)) {
    await copyCodeClozeAllBlanks();
    return;
  }
  if (activeDeliverablePreviewTab === 'code') {
    await copyDeliverableCode();
  } else {
    await copyDeliverableDiagrams();
  }
}

async function copyDeliverableSection() {
  if (currentDeliverable && isTheoryDeliverable(currentDeliverable)) {
    if (window._theoryViewTab === 'notes') {
      const notes = String((currentDeliverable.sections || {}).notes || '').trim();
      if (!notes) {
        showToast('暂无备注', 'info');
        return;
      }
      try {
        await navigator.clipboard.writeText(notes);
        showToast('已复制备注', 'success');
      } catch (err) {
        showToast('复制失败: ' + err.message, 'error');
      }
      return;
    }
    await copyTheoryQuestionBody(getActiveTheoryBlock(currentDeliverable));
    return;
  }
  if (currentDeliverable && isMixedAssignmentDeliverable(currentDeliverable)) {
    const activePart = getActiveMixedDeliverablePart(currentDeliverable);
    if (activePart?.type === 'code_cloze') {
      const blankNo = Number(String(activeDeliverableTab || '').replace('blank:', ''));
      const clozeDlv = {
        ...currentDeliverable,
        code_cloze: activePart.code_cloze || {},
      };
      const prev = currentDeliverable;
      currentDeliverable = clozeDlv;
      await copyCodeClozeBlank(blankNo);
      currentDeliverable = prev;
      return;
    }
    const text = String(activePart?.answer_text || '').trim();
    if (!text) {
      showToast('本节暂无内容', 'info');
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      showToast('已复制本节简答', 'success');
    } catch (err) {
      showToast('复制失败: ' + err.message, 'error');
    }
    return;
  }
  if (currentDeliverable && isCodeClozeDeliverable(currentDeliverable)) {
    const blankNo = Number(String(activeDeliverableTab || '').replace('blank:', ''));
    await copyCodeClozeBlank(blankNo);
    return;
  }
  if (!currentDeliverable) {
    showToast('暂无答案交付物', 'error');
    return;
  }
  const text = (currentDeliverable.sections || {})[activeDeliverableTab] || '';
  if (!text.trim()) {
    showToast('本节暂无内容', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    const label = DELIVERABLE_TEXT_SECTIONS.find((t) => t.id === activeDeliverableTab)?.label || '本节';
    showToast(`已复制「${label}」`, 'success');
    recordBehaviorOutcome('copy_section', { section: activeDeliverableTab || '' });
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyCodeClozeBlank(blankNo) {
  if (!currentDeliverable || !isCodeClozeDeliverable(currentDeliverable)) {
    showToast('暂无代码完形答案', 'info');
    return;
  }
  const blanks = getCodeClozeBlankEntries(currentDeliverable);
  const item = blanks.find((b) => b.n === blankNo);
  if (!item?.answer) {
    showToast('该空暂无答案', 'info');
    return;
  }
  try {
    await navigator.clipboard.writeText(item.answer);
    showToast(`已复制空 ${item.n}`, 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
}

async function copyCodeClozeAllBlanks() {
  if (!currentDeliverable || !isCodeClozeDeliverable(currentDeliverable)) {
    showToast('暂无代码完形答案', 'info');
    return;
  }
  const blanks = getCodeClozeBlankEntries(currentDeliverable);
  if (!blanks.length) {
    showToast('暂无空号答案', 'info');
    return;
  }
  const text = blanks.map((b) => `${b.n}\t${b.answer || ''}`).join('\n');
  try {
    await navigator.clipboard.writeText(text);
    showToast(`已复制 ${blanks.length} 个空号答案`, 'success');
  } catch (err) {
    showToast('复制失败: ' + err.message, 'error');
  }
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
  if (hash || prov.custom_label) uiShow(wrap, 'flex');
  else uiHide(wrap);
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
    const outcomeEvent = format === 'markdown' ? 'export_markdown' : format === 'docx' ? 'export_docx' : 'export_deliverable';
    recordBehaviorOutcome(outcomeEvent, { format: format || '' });
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
  if (bar) uiShow(bar, 'flex');
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
  const extra = umlCount ? `，右侧预览区可复制 ${umlCount} 张图表` : '';
  showToast(`答案已生成！复制分节正文，或在右侧预览区复制代码/图表${extra}`, 'success');
}

// ============================
// 代码编辑器
// ============================

function showCodePanel(question, codeOrFiles, language, questionIndex, mainFile) {
  currentCodeQuestion = { question, questionIndex };
  const panel = document.getElementById('codePanel');
  if (!panel) return;
  uiShow(panel, 'block');
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
    uiHide(tabs);
    return;
  }
  uiShow(tabs, 'flex');
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
  uiHide(document.getElementById('codePanel'));
  currentCodeFiles = [];
  currentMainFile = '';
  const tabs = document.getElementById('codeFileTabs');
  if (tabs) uiHide(tabs);
}

function changeLanguage() {
  const lang = document.getElementById('langSelect').value;
  const langMap = { python: 'python', javascript: 'javascript', c: 'c', cpp: 'cpp', java: 'java' };
  if (monacoEditor) {
    monaco.editor.setModelLanguage(monacoEditor.getModel(), langMap[lang] || 'python');
  }
}

async function runCode() {
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
  Icons.setIconText(btn, 'loader', '运行中...', 'icon-sm icon-spin');
  consoleBody.className = 'console-body';
  consoleBody.textContent = '正在执行...';

  try {
    let resp;
    if (isMultiFile) {
      resp = await apiPost('/api/run-code-multi', {
        files: currentCodeFiles,
        language,
        main_file: mainFile,
      });
    } else {
      resp = await apiPost('/api/run-code', {
        code,
        language,
        has_gui: hasGui,
      });
    }

    if (resp.needs_jre) {
      btn.disabled = false;
      Icons.setIconText(btn, 'play', '运行', 'icon-sm');
      consoleBody.textContent = '';
      await promptDownloadJRE();
      return;
    }

    const output = resp.output || '';
    const isError = resp.error || resp.is_error || false;

    consoleBody.textContent = output || '(程序运行完成，无输出)';
    consoleBody.className = isError ? 'console-body console-error' : 'console-body console-success';

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
    Icons.setIconText(btn, 'play', '运行', 'icon-sm');
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
    runSummary: lastRunSummary || undefined,
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
    goToStep(3);
    showExportSuccessPanel();
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
      <div style="font-weight:600;margin-bottom:4px;display:flex;align-items:center;gap:6px;">${ico('bar-chart', 'icon-sm')} 解题统计</div>
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
  resetTheoryWorkspaceState();
  currentFile = null;
  parsedQuestions = [];
  solvedAnswers = [];
  lastOutputPath = null;
  uploadedDocuments = [];
  assignmentImageItems = [];
  renderAssignmentImageStrip();
  renderDocumentList();
  pairedDocxPath = null;
  agentFillTarget = null;
  resetAgentPlanState();
  resetToolboxState();
  goToStep(1);
  updateStepBar(1);
  closeCodePanel();
  uiHide(document.getElementById('exportActionBar'));
  uiHide(document.getElementById('modeSwitchBar'));
  hideExportSuccessPanel();
  updateStep3CompletionActions();
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

function formatHistoryDate(item) {
  if (item.exported_at) {
    const d = new Date(item.exported_at);
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    }
  }
  return item.date || '';
}

function historyCardTitle(item) {
  const roles = item.document_roles || [];
  const reportRole = roles.find((r) => r.role === 'report') || roles[0];
  const course = reportRole?.course || '';
  const rawName = item.name || reportRole?.name || '报告';
  const title = String(rawName).replace(/\.[^.]+$/, '');
  if (course && course !== title) return `${course} · ${title}`;
  return title;
}

function historyGeneratedSectionCount(item) {
  return (item.sections_summary || []).filter(
    (s) => s.mode === 'auto' || s.mode === 'user_provided'
  ).length;
}

function historyRunModeMeta(item) {
  const mode = item.run_mode || 'standard';
  const label = item.run_mode_label || (
    mode === 'deep' ? '深度'
      : mode === 'react' ? '实验 ReAct'
        : '标准'
  );
  const cls = mode === 'deep' ? 'mode-deep' : mode === 'react' ? 'mode-react' : 'mode-standard';
  return { label, cls };
}

function historyCodeStatusMeta(item) {
  const rs = item.run_summary || {};
  const pm = item.pipeline_meta || {};
  const status = rs.code_status || pm.code_status;
  if (!status) return '';
  const labels = { verified: '代码已验证', skipped: '无代码', degraded: '代码降级' };
  return labels[status] || status;
}

function historyCardStatusClass(item) {
  const sectionCount = historyGeneratedSectionCount(item);
  return sectionCount > 0 ? 'complete' : 'pending';
}

function historyCardExcerpt(item) {
  const summaries = item.sections_summary || [];
  const generated = summaries.filter((s) => s.mode === 'auto' || s.mode === 'user_provided');
  if (generated.length) {
    const titles = generated.slice(0, 3).map((s) => s.label).join('、');
    const suffix = generated.length > 3 ? '…' : '';
    return `摘要：${titles}${suffix}`;
  }
  const title = historyCardTitle(item);
  if (title && title.length > 60) return `摘要：${title.slice(0, 60)}…`;
  if (title) return `摘要：${title}`;
  return '';
}

function openHistoryItem(index) {
  const history = JSON.parse(localStorage.getItem('history') || '[]');
  const item = history[index];
  if (item?.path && window.electronAPI?.openFileExternal) {
    window.electronAPI.openFileExternal(item.path);
  }
}

function deleteHistoryItem(index, event) {
  if (event) event.stopPropagation();
  const history = JSON.parse(localStorage.getItem('history') || '[]');
  if (index < 0 || index >= history.length) return;
  history.splice(index, 1);
  localStorage.setItem('history', JSON.stringify(history));
  renderHistory();
  showToast('已删除历史记录', 'info');
}

function renderHistory() {
  const history = JSON.parse(localStorage.getItem('history') || '[]');
  const list = document.getElementById('historyList');
  if (!list) return;

  if (history.length === 0) {
    list.innerHTML = emptyStateHtml('clipboard-list', '暂无历史记录', '完成解题并导出后，记录会显示在这里');
    return;
  }

  list.innerHTML = history.map((item, index) => {
    const sectionCount = historyGeneratedSectionCount(item);
    const questionCount = Number(item.questions) || 0;
    const metaParts = [];
    const { label: modeLabel, cls: modeCls } = historyRunModeMeta(item);
    metaParts.push(modeLabel);
    const codeMeta = historyCodeStatusMeta(item);
    if (codeMeta) metaParts.push(codeMeta);
    if (sectionCount > 0) metaParts.push(`${sectionCount} 节`);
    else if (questionCount > 0) metaParts.push(`${questionCount} 道题`);
    if (sectionCount > 0) metaParts.push('已生成答案');
    else metaParts.push('已导出');
    const statusCls = historyCardStatusClass(item);
    const excerpt = historyCardExcerpt(item);
    const excerptHtml = excerpt
      ? `<p class="history-card-excerpt">${escapeHtml(excerpt)}</p>`
      : '';

    return `
    <article class="history-card" data-history-index="${index}">
      <div class="history-card-header">
        <span class="history-card-status ${statusCls}" aria-hidden="true" title="${statusCls === 'complete' ? '已生成答案' : '仅计划或未完成'}"></span>
        <h3 class="history-card-title">${escapeHtml(historyCardTitle(item))}</h3>
        <time class="history-card-date" datetime="${escapeHtml(item.exported_at || '')}">${escapeHtml(formatHistoryDate(item))}</time>
      </div>
      <p class="history-card-meta">${escapeHtml(metaParts.join(' · '))}</p>
      ${excerptHtml}
      <div class="history-card-footer">
        <div class="history-card-actions">
          <button type="button" class="btn-secondary btn-sm" onclick="openHistoryItem(${index})">打开</button>
          <button type="button" class="btn-ghost btn-sm" onclick="deleteHistoryItem(${index}, event)">删除</button>
        </div>
      </div>
    </article>`;
  }).join('');
}

// ============================
// 设置
// ============================

const SETTINGS_SCHEMA_VERSION = 11;
let _runtimeApiKey = '';
let _encryptionAvailable = false;
let _fallbackNotified = false;
let _hostedProviderStatus = null;
let _modelCatalog = null;

const FALLBACK_MODEL_CATALOG = {
  catalog_version: 1,
  providers: {
    deepseek: [
      { id: 'deepseek-v4-flash', label: 'deepseek-v4-flash（推荐）', default: true },
      { id: 'deepseek-v4-pro', label: 'deepseek-v4-pro（高质量）' },
    ],
    agnes: [{ id: 'agnes-2.0-flash', label: 'agnes-2.0-flash', default: true }],
    openai: [
      { id: 'gpt-4o', label: 'gpt-4o', default: true },
      { id: 'gpt-4o-mini', label: 'gpt-4o-mini' },
      { id: 'gpt-4-turbo', label: 'gpt-4-turbo' },
    ],
    claude: [
      { id: 'claude-3-5-sonnet-20241022', label: 'claude-3-5-sonnet-20241022', default: true },
      { id: 'claude-3-haiku-20240307', label: 'claude-3-haiku-20240307' },
    ],
    zhipu: [
      { id: 'glm-4-flash', label: 'glm-4-flash', default: true },
      { id: 'glm-4', label: 'glm-4' },
    ],
    custom: [{ id: 'custom-model', label: 'custom-model', default: true }],
  },
  defaults: {
    deepseek: 'deepseek-v4-flash',
    agnes: 'agnes-2.0-flash',
    openai: 'gpt-4o',
    claude: 'claude-3-5-sonnet-20241022',
    zhipu: 'glm-4-flash',
    custom: 'custom-model',
  },
  deprecated_aliases: {
    'deepseek-chat': { api_model: 'deepseek-v4-flash', thinking: 'disabled' },
    'deepseek-reasoner': { api_model: 'deepseek-v4-flash', thinking: 'enabled' },
  },
};

async function ensureModelCatalog() {
  if (_modelCatalog) return _modelCatalog;
  try {
    _modelCatalog = await apiGet('/api/llm-models');
  } catch {
    _modelCatalog = FALLBACK_MODEL_CATALOG;
  }
  return _modelCatalog;
}

function migrateSavedModel(provider, model) {
  const catalog = _modelCatalog || FALLBACK_MODEL_CATALOG;
  const id = (model || '').trim();
  if (catalog.deprecated_aliases?.[id]) {
    return catalog.deprecated_aliases[id].api_model;
  }
  const known = (catalog.providers?.[provider] || []).map((m) => m.id);
  if (known.length && id && !known.includes(id) && provider !== 'custom') {
    return catalog.defaults?.[provider] || 'deepseek-v4-flash';
  }
  return id || catalog.defaults?.[provider] || 'deepseek-v4-flash';
}

async function renderModelSelect(provider, selectedModel) {
  const catalog = await ensureModelCatalog();
  const models = catalog.providers?.[provider] || [{ id: 'default', label: 'default' }];
  const select = document.getElementById('modelSelect');
  if (!select) return;
  select.innerHTML = models.map((m) =>
    `<option value="${m.id}">${m.label || m.id}</option>`
  ).join('');
  const wanted = migrateSavedModel(provider, selectedModel);
  if (models.some((m) => m.id === wanted)) {
    select.value = wanted;
  } else {
    select.value = models.find((m) => m.default)?.id || models[0]?.id || wanted;
  }
}

function isHostedProvider(provider) {
  return (provider || '').toLowerCase() === 'agnes';
}

function needsUserApiKey(settings) {
  if (isHostedProvider(settings?.provider)) return false;
  return !(settings?.apiKey || '').trim();
}

async function refreshHostedProviderStatus() {
  try {
    _hostedProviderStatus = await apiGet('/api/hosted-providers/status');
  } catch {
    _hostedProviderStatus = null;
  }
  return _hostedProviderStatus;
}

async function syncHostedProviderUI() {
  const provider = document.getElementById('aiProvider')?.value || '';
  const apiKeyGroup = document.getElementById('apiKeyGroup');
  const hostedNotice = document.getElementById('hostedKeyNotice');
  const keyNotice = document.getElementById('keyStorageNotice');

  if (!isHostedProvider(provider)) {
    if (apiKeyGroup) uiShow(apiKeyGroup, 'flex');
    if (hostedNotice) uiHide(hostedNotice);
    if (keyNotice) uiShow(keyNotice);
    updateKeyStorageNotice();
    return;
  }

  if (apiKeyGroup) uiHide(apiKeyGroup);
  if (keyNotice) uiHide(keyNotice);
  if (hostedNotice) {
    uiShow(hostedNotice, 'flex');
    const status = _hostedProviderStatus || await refreshHostedProviderStatus();
    const textEl = document.getElementById('hostedKeyNoticeText');
    if (textEl) {
      textEl.textContent = status?.agnes?.configured
        ? '已启用应用内置 Agnes 免费额度，无需自行注册或填写 Key。'
        : '正在配置内置 Key… 若长时间无响应，请重启应用或暂时改用 DeepSeek。';
    }
  }
}

async function seedHostedAgnesIfNeeded() {
  try {
    const status = await refreshHostedProviderStatus();
    if (status?.agnes?.configured) {
      await syncHostedProviderUI();
      return;
    }
    const provider = document.getElementById('aiProvider')?.value
      || readSettings().provider
      || '';
    if (!isHostedProvider(provider)) return;
    const key = (_runtimeApiKey || '').trim()
      || (document.getElementById('apiKey')?.value || '').trim();
    if (!key) return;
    await apiPost('/api/hosted-providers/agnes/seed', { api_key: key });
    await refreshHostedProviderStatus();
    await persistApiKeyToStorage('');
    const apiKeyEl = document.getElementById('apiKey');
    if (apiKeyEl) apiKeyEl.value = '';
    showToast('Agnes 内置 Key 已就绪', 'success');
    await syncHostedProviderUI();
  } catch (err) {
    console.warn('[hosted] seed agnes failed:', err);
  }
}

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
    model: migrateSavedModel(saved.provider || 'deepseek', saved.model || 'deepseek-v4-flash'),
    codeLanguage: saved.codeLanguage || 'python',
    customUrl: saved.customUrl || '',
    includeUml: saved.includeUml === true,
    umlAllowOnline: saved.umlAllowOnline !== false,
    runMode: saved.runMode || 'standard',
    experimentalReactMode: saved.experimentalReactMode === true,
    showThoughtTrace: saved.showThoughtTrace === true,
    optimizePlanFromUsage: saved.optimizePlanFromUsage !== false,
    llmReplan: saved.llmReplan !== false,
    autoRemediate: saved.autoRemediate !== false,
    autoRemediateMaxRounds: Number.isFinite(Number(saved.autoRemediateMaxRounds))
      ? Math.max(0, Math.min(5, Number(saved.autoRemediateMaxRounds)))
      : 1,
    maxReplanRounds: Number.isFinite(Number(saved.maxReplanRounds))
      ? Math.max(0, Math.min(5, Number(saved.maxReplanRounds)))
      : 1,
    solveQualityTier: ['fast', 'standard', 'thorough'].includes(saved.solveQualityTier)
      ? saved.solveQualityTier
      : 'standard',
    solveQualityTierExplicit: saved.solveQualityTierExplicit === true,
    autoFastTierForLightQuestions: saved.autoFastTierForLightQuestions !== false,
    enableParallelModuleSteps: saved.enableParallelModuleSteps !== false,
    userConstraints: Array.isArray(saved.userConstraints) ? saved.userConstraints : [],
    provenanceCustomLabel: saved.provenanceCustomLabel || '',
    enableImageOcr: saved.enableImageOcr === true,
    imageOcrLang: saved.imageOcrLang || 'chi_sim+eng',
    imageReadingMode: saved.imageReadingMode || 'ocr_only',
    imageOcrMaxPages: Number.isFinite(Number(saved.imageOcrMaxPages))
      ? Math.max(1, Math.min(100, Number(saved.imageOcrMaxPages)))
      : 20,
    imageVisionMaxPages: Number.isFinite(Number(saved.imageVisionMaxPages))
      ? Math.max(1, Math.min(20, Number(saved.imageVisionMaxPages)))
      : 5,
    schema_version: SETTINGS_SCHEMA_VERSION,
  };
  if (version < SETTINGS_SCHEMA_VERSION) {
    const migration = {
      schema_version: SETTINGS_SCHEMA_VERSION,
      enableImageOcr: merged.enableImageOcr,
      imageOcrLang: merged.imageOcrLang,
      imageReadingMode: merged.imageReadingMode,
      imageOcrMaxPages: merged.imageOcrMaxPages,
      imageVisionMaxPages: merged.imageVisionMaxPages,
    };
    if (version < 4) {
      migration.solveQualityTier = merged.solveQualityTier;
    }
    if (version < 5) {
      migration.experimentalReactMode = merged.experimentalReactMode;
      if (merged.runMode === 'react' && !merged.experimentalReactMode) {
        migration.runMode = 'standard';
        merged.runMode = 'standard';
      }
    }
    if (version < 6) {
      migration.model = merged.model;
    }
    if (version < 7 && saved.autoRemediate !== false) {
      migration.autoRemediate = true;
      merged.autoRemediate = true;
    }
    if (version < 8) {
      migration.autoRemediateMaxRounds = merged.autoRemediateMaxRounds;
      merged.autoRemediateMaxRounds = merged.autoRemediateMaxRounds;
    }
    if (version < 9) {
      migration.maxReplanRounds = merged.maxReplanRounds;
      merged.maxReplanRounds = merged.maxReplanRounds;
    }
    if (version < 10) {
      migration.autoFastTierForLightQuestions = true;
      migration.enableParallelModuleSteps = true;
      merged.autoFastTierForLightQuestions = true;
      merged.enableParallelModuleSteps = true;
      if (merged.solveQualityTier && merged.solveQualityTier !== 'standard') {
        migration.solveQualityTierExplicit = true;
        merged.solveQualityTierExplicit = true;
      } else {
        migration.solveQualityTierExplicit = false;
        merged.solveQualityTierExplicit = false;
      }
    }
    if (version < 11) {
      if (saved.optimizePlanFromUsage === undefined) {
        migration.optimizePlanFromUsage = true;
        merged.optimizePlanFromUsage = true;
      }
      if (saved.llmReplan === undefined) {
        migration.llmReplan = true;
        merged.llmReplan = true;
      }
    }
    persistSettingsPatch(migration);
  }
  return merged;
}

function readSettings() {
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  return mergeSettings(saved);
}

function applySettingsToForm(settings) {
  const apiKeyEl = document.getElementById('apiKey');
  const providerEl = document.getElementById('aiProvider');
  if (!apiKeyEl || !providerEl) return;

  const umlOnlineEl = document.getElementById('umlAllowOnlineSettings');
  if (umlOnlineEl) umlOnlineEl.checked = settings.umlAllowOnline;
  const umlStepEl = document.getElementById('includeUmlCheck');
  if (umlStepEl) umlStepEl.checked = settings.includeUml;

  apiKeyEl.value = settings.apiKey;
  providerEl.value = settings.provider;
  document.getElementById('codeLanguage').value = settings.codeLanguage;
  document.getElementById('customUrl').value = settings.customUrl;

  syncExperimentalReactUI(settings.experimentalReactMode);
  syncRunModeUI(settings.runMode);
  syncSolveQualityTierUI(settings.solveQualityTier);
  syncUserConstraintsUI(settings.userConstraints);
  const provLabelEl = document.getElementById('provenanceCustomLabel');
  if (provLabelEl) provLabelEl.value = settings.provenanceCustomLabel || '';
  const thoughtEl = document.getElementById('showThoughtTraceSettings');
  if (thoughtEl) thoughtEl.checked = settings.showThoughtTrace;
  const optimizeEl = document.getElementById('optimizePlanFromUsageSettings');
  if (optimizeEl) optimizeEl.checked = settings.optimizePlanFromUsage !== false;
  const autoRemediateEl = document.getElementById('autoRemediateSettings');
  if (autoRemediateEl) autoRemediateEl.checked = settings.autoRemediate !== false;
  const autoRemediateRoundsEl = document.getElementById('autoRemediateMaxRoundsSettings');
  if (autoRemediateRoundsEl) autoRemediateRoundsEl.value = String(settings.autoRemediateMaxRounds ?? 1);
  const maxReplanRoundsEl = document.getElementById('maxReplanRoundsSettings');
  if (maxReplanRoundsEl) maxReplanRoundsEl.value = String(settings.maxReplanRounds ?? 1);
  const autoFastEl = document.getElementById('autoFastTierForLightQuestionsSettings');
  if (autoFastEl) autoFastEl.checked = settings.autoFastTierForLightQuestions !== false;
  const parallelEl = document.getElementById('enableParallelModuleStepsSettings');
  if (parallelEl) parallelEl.checked = settings.enableParallelModuleSteps !== false;
  syncImageOcrSettingsUI(settings);
  refreshOcrStatusNotice().catch(() => {});
  updateKeyStorageNotice();
  onProviderChange({ persist: false });
  renderModelSelect(settings.provider, settings.model).then(() => {
    document.getElementById('modelSelect').value = settings.model;
  });
  renderComplianceSettings(window.__labSolverLogFile || '');
  syncHostedProviderUI().catch(() => {});
}

function loadSettings() {
  const settings = readSettings();
  applySettingsToForm(settings);
  return settings;
}

function syncImageOcrSettingsUI(settings) {
  const s = settings || readSettings();
  const enableEl = document.getElementById('enableImageOcrSettings');
  if (enableEl) enableEl.checked = s.enableImageOcr === true;
  const langEl = document.getElementById('imageOcrLangSettings');
  if (langEl) langEl.value = s.imageOcrLang || 'chi_sim+eng';
  const maxEl = document.getElementById('imageOcrMaxPagesSettings');
  if (maxEl) maxEl.value = String(s.imageOcrMaxPages || 20);
  const visionMaxEl = document.getElementById('imageVisionMaxPagesSettings');
  if (visionMaxEl) visionMaxEl.value = String(s.imageVisionMaxPages || 5);
  const modeEl = document.getElementById('imageReadingModeSettings');
  if (modeEl) modeEl.value = s.imageReadingMode || 'ocr_only';
}

function onImageOcrSettingsChange() {
  const maxRaw = parseInt(document.getElementById('imageOcrMaxPagesSettings')?.value, 10);
  const visionMaxRaw = parseInt(document.getElementById('imageVisionMaxPagesSettings')?.value, 10);
  persistSettingsPatch({
    enableImageOcr: document.getElementById('enableImageOcrSettings')?.checked === true,
    imageOcrLang: document.getElementById('imageOcrLangSettings')?.value || 'chi_sim+eng',
    imageOcrMaxPages: Number.isFinite(maxRaw) ? Math.max(1, Math.min(100, maxRaw)) : 20,
    imageVisionMaxPages: Number.isFinite(visionMaxRaw) ? Math.max(1, Math.min(20, visionMaxRaw)) : 5,
    imageReadingMode: document.getElementById('imageReadingModeSettings')?.value || 'ocr_only',
  });
  renderAssignmentImageModeHint();
  markAgentPlanStale();
}

function openOcrExternalUrl(url) {
  if (!url) return;
  if (window.electronAPI && window.electronAPI.openExternalUrl) {
    window.electronAPI.openExternalUrl(url);
  } else {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

function renderOcrInstallGuide(ocr) {
  const stepsEl = document.getElementById('ocrInstallSteps');
  const actionsEl = document.getElementById('ocrInstallActions');
  const altEl = document.getElementById('ocrInstallAltHint');
  const summaryEl = document.getElementById('ocrUnavailableSummary');
  if (!stepsEl || !actionsEl) return;

  const steps = Array.isArray(ocr?.install_steps) ? ocr.install_steps : [];
  stepsEl.innerHTML = steps.map((s) => `<li>${escapeHtml(s)}</li>`).join('');

  const buttons = [];
  if (ocr?.issue !== 'missing_pytesseract' && ocr?.download_url) {
    buttons.push(
      `<button type="button" class="btn-secondary btn-sm ocr-dl-btn" data-ocr-url="${escapeHtml(ocr.download_url)}">${icoLabel('download', ocr.download_label || '下载 Tesseract', 'icon-sm')}</button>`
    );
  }
  if (ocr?.lang_pack_url && ocr?.issue !== 'missing_pytesseract') {
    buttons.push(
      `<button type="button" class="btn-secondary btn-sm ocr-dl-btn" data-ocr-url="${escapeHtml(ocr.lang_pack_url)}">${icoLabel('download', ocr.lang_pack_label || '下载中文语言包', 'icon-sm')}</button>`
    );
  }
  buttons.push(
    `<button type="button" class="btn-secondary btn-sm" id="ocrRecheckBtn">${icoLabel('refresh-cw', '重新检测', 'icon-sm')}</button>`
  );
  actionsEl.innerHTML = buttons.join('');

  actionsEl.querySelectorAll('.ocr-dl-btn').forEach((btn) => {
    btn.onclick = (e) => {
      e.stopPropagation();
      openOcrExternalUrl(btn.getAttribute('data-ocr-url'));
    };
  });
  const recheckBtn = document.getElementById('ocrRecheckBtn');
  if (recheckBtn) {
    recheckBtn.onclick = async (e) => {
      e.stopPropagation();
      _ocrOkCached = null;
      await refreshOcrStatusNotice({ force: true });
    };
  }

  if (summaryEl) {
    summaryEl.textContent = ocr?.install_guide
      ? `本机未检测到 Tesseract。${ocr.install_guide}`
      : '本机未检测到 Tesseract，无法使用本地 OCR。';
  }
  if (altEl) {
    altEl.textContent = ocr?.alt_hint || '也可在解析页手动粘贴题目文字，无需安装 OCR。';
  }
}

async function refreshOcrStatusNotice(opts = {}) {
  const notice = document.getElementById('ocrUnavailableNotice');
  if (!notice) return;
  try {
    if (_ocrOkCached == null || opts.force) {
      const resp = await apiGet('/api/runtime-status');
      _ocrOkCached = resp.ocr_ok === true;
      if (!_ocrOkCached && resp.ocr) renderOcrInstallGuide(resp.ocr);
    }
    if (_ocrOkCached) {
      uiHide(notice);
      if (opts.force) showToast('已检测到 Tesseract，本地 OCR 可用', 'success');
    } else {
      uiShow(notice, 'flex');
      if (opts.force) showToast('仍未检测到 Tesseract，请确认已安装并重启应用', 'warning');
    }
  } catch {
    uiHide(notice);
  }
}

function onUmlSettingsChange() {
  const el = document.getElementById('umlAllowOnlineSettings');
  persistSettingsPatch({ umlAllowOnline: el ? el.checked : true });
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

async function saveSettings() {
  const provider = document.getElementById('aiProvider').value;
  let apiKey = document.getElementById('apiKey').value;
  if (isHostedProvider(provider)) {
    await seedHostedAgnesIfNeeded();
    apiKey = '';
  }
  const settings = {
    provider,
    model: document.getElementById('modelSelect').value,
    codeLanguage: document.getElementById('codeLanguage').value,
    customUrl: document.getElementById('customUrl').value,
    includeUml: document.getElementById('includeUmlCheck')?.checked === true,
    umlAllowOnline: document.getElementById('umlAllowOnlineSettings')?.checked !== false,
    runMode: getRunMode(),
    experimentalReactMode: getExperimentalReactMode(),
    showThoughtTrace: document.getElementById('showThoughtTraceSettings')?.checked === true,
    optimizePlanFromUsage: document.getElementById('optimizePlanFromUsageSettings')?.checked === true,
    autoRemediate: document.getElementById('autoRemediateSettings')?.checked === true,
    autoRemediateMaxRounds: getAutoRemediateMaxRounds(),
    maxReplanRounds: getMaxReplanRounds(),
    solveQualityTier: getSolveQualityTier(),
    solveQualityTierExplicit: readSettings().solveQualityTierExplicit === true,
    autoFastTierForLightQuestions: document.getElementById('autoFastTierForLightQuestionsSettings')?.checked !== false,
    enableParallelModuleSteps: document.getElementById('enableParallelModuleStepsSettings')?.checked !== false,
    enableImageOcr: document.getElementById('enableImageOcrSettings')?.checked === true,
    imageOcrLang: document.getElementById('imageOcrLangSettings')?.value || 'chi_sim+eng',
    imageOcrMaxPages: parseInt(document.getElementById('imageOcrMaxPagesSettings')?.value, 10) || 20,
    imageVisionMaxPages: parseInt(document.getElementById('imageVisionMaxPagesSettings')?.value, 10) || 5,
    imageReadingMode: document.getElementById('imageReadingModeSettings')?.value || 'ocr_only',
    schema_version: SETTINGS_SCHEMA_VERSION,
  };
  const saved = JSON.parse(localStorage.getItem('settings') || '{}');
  Object.assign(saved, settings);
  delete saved.apiKey;
  delete saved.apiKeyEncrypted;
  delete saved.apiKeyStorage;
  localStorage.setItem('settings', JSON.stringify(saved));
  await persistApiKeyToStorage(apiKey);
  await syncHostedProviderUI();
  showToast('设置已保存', 'success');
}

function onProviderChange(options = {}) {
  const { persist = true } = options;
  const provider = document.getElementById('aiProvider').value;
  const hints = {
    deepseek: 'DeepSeek API Key，在 platform.deepseek.com 获取（推荐，价格低）',
    agnes: '使用应用内置 Agnes 免费额度（无需填写 Key）。代码题建议仍用 DeepSeek；识图请开 OCR',
    openai: 'OpenAI API Key，在 platform.openai.com 获取',
    claude: 'Anthropic API Key，在 console.anthropic.com 获取',
    zhipu: '智谱AI API Key，在 open.bigmodel.cn 获取',
    custom: '请填写自定义API Key'
  };

  document.getElementById('apiKeyHint').textContent = hints[provider] || '';
  const currentModel = document.getElementById('modelSelect')?.value || '';
  renderModelSelect(provider, currentModel).then(() => {
    const customUrlGroup = document.getElementById('customUrlGroup');
    if (provider === 'custom') uiShow(customUrlGroup, 'flex');
    else uiHide(customUrlGroup);
    renderAssignmentImageModeHint();
    if (persist) {
      persistSettingsPatch({
        provider,
        model: document.getElementById('modelSelect').value,
      });
    }
    syncHostedProviderUI().catch(() => {});
  });
}

function onModelChange() {
  persistSettingsPatch({
    provider: document.getElementById('aiProvider').value,
    model: document.getElementById('modelSelect').value,
  });
}

async function testConnection() {
  const settings = {
    apiKey: document.getElementById('apiKey').value,
    provider: document.getElementById('aiProvider').value,
    model: document.getElementById('modelSelect').value,
    customUrl: document.getElementById('customUrl').value
  };
  const resultEl = document.getElementById('testResult');

  if (needsUserApiKey(settings)) {
    resultEl.className = 'test-result error';
    resultEl.innerHTML = icoLabel('x-circle', '请填写 API Key', 'icon-sm');
    return;
  }

  resultEl.className = 'test-result';
  uiShow(resultEl, 'flex');
  resultEl.innerHTML = icoLabel('loader', '测试中...', 'icon-sm icon-spin');
  resultEl.style.background = 'var(--bg-elevated)';
  resultEl.style.color = 'var(--text-secondary)';

  try {
    const resp = await apiPost('/api/test-connection', settings);
    resultEl.className = 'test-result success';
    resultEl.innerHTML = icoLabel('check-circle', '连接成功！模型：' + (resp.model || settings.model), 'icon-sm');
    persistSettingsPatch({
      apiKey: settings.apiKey,
      provider: settings.provider,
      model: settings.model,
      customUrl: settings.customUrl || '',
    });
  } catch (err) {
    resultEl.className = 'test-result error';
    resultEl.innerHTML = icoLabel('x-circle', '连接失败：' + err.message, 'icon-sm');
  }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById('apiKey');
  const isHidden = input.type === 'password';
  input.type = isHidden ? 'text' : 'password';
  const iconEl = document.getElementById('apiKeyToggleIcon');
  if (iconEl) {
    iconEl.setAttribute('data-icon', isHidden ? 'eye-off' : 'eye');
    iconEl.removeAttribute('data-icon-inited');
    Icons.initDataIcons(iconEl.parentElement);
  }
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
    const e = new Error(msg);
    if (err.stale_documents === true) e.stale_documents = true;
    if (err.stale_plan === true) e.stale_plan = true;
    if (typeof err.plan_fingerprint === 'string' && err.plan_fingerprint.trim()) {
      e.plan_fingerprint = err.plan_fingerprint.trim();
    }
    throw e;
  }

  return resp.json();
}

// ============================
// Toast通知
// ============================

function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const icons = { success: 'check-circle', error: 'x-circle', info: 'info' };
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `${ico(icons[type] || 'info', 'icon-sm')}<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
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
  <div style="color:var(--yellow);font-weight:600;margin-bottom:10px;display:flex;align-items:center;gap:6px;">${ico('alert-triangle', 'icon-sm')} 需要 Java 运行环境</div>
  <div style="color:var(--text-secondary);margin-bottom:12px;line-height:1.6">
    运行 Java 代码需要下载便携版 JRE（约 50MB）<br>
    下载后永久保存，无需重复下载，完全离线可用
  </div>
  <button id="downloadJreBtn" class="btn-run">${icoLabel('download', '一键下载 JRE（约 50MB）', 'icon-sm')}</button>
  <span id="jreDownloadStatus" style="margin-left:12px;color:var(--text-secondary);font-size:12px"></span>
</div>`;

  document.getElementById('downloadJreBtn').onclick = async () => {
    const btn = document.getElementById('downloadJreBtn');
    const status = document.getElementById('jreDownloadStatus');
    btn.disabled = true;
    btn.innerHTML = icoLabel('loader', '下载中...', 'icon-sm icon-spin');
    status.textContent = '正在从 GitHub 下载，请耐心等待（约 1–3 分钟）...';

    try {
      await apiPost('/api/download-jre', {});
      status.innerHTML = icoLabel('check-circle', '下载完成！', 'icon-xs');
      btn.innerHTML = icoLabel('check-circle', 'JRE 已就绪', 'icon-sm');
      showToast('Java 运行环境安装成功！', 'success');
      consoleBody.className = 'console-body console-success';
      consoleBody.innerHTML = icoLabel('check-circle', 'JRE 安装完成，现在可以运行 Java 代码了！', 'icon-sm');
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = icoLabel('download', '重试下载', 'icon-sm');
      status.innerHTML = icoLabel('x-circle', '下载失败: ' + err.message, 'icon-xs');
      showToast('JRE 下载失败，请检查网络', 'error');
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
