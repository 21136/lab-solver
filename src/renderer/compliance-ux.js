/* Phase 3 — compliance & onboarding (disclaimer, privacy, guide, fill confirm, history helpers) */

const COMPLIANCE_STORAGE_KEY = 'compliance';
const DISCLAIMER_VERSION = 1;
const ONBOARDING_VERSION = 2;

const DISCLAIMER_HTML = `
<p>本软件（解题能手）仅供<strong>课程学习与实验报告写作参考</strong>，不构成代写或学术不端服务。</p>
<ul>
  <li>生成内容由 AI 产生，可能存在事实错误、逻辑漏洞或与实验不符之处，请<strong>自行核对、修改并承担提交后果</strong>。</li>
  <li>请勿将 AI 输出或上传的<strong>范文/答题模版原样照抄</strong>提交；应结合本人实验过程与课程要求独立完成。</li>
  <li>使用本工具产生的任何学术诚信、版权与成绩责任由<strong>用户本人</strong>承担。</li>
</ul>
`;

const PRIVACY_HTML = (logFilePath) => `
<p><strong>数据去向</strong></p>
<ul>
  <li>您在设置中填写的 <strong>API Key</strong> 与上传的<strong>实验报告/题目文档全文</strong>会通过 HTTPS 发送至您在设置中选择的 AI 服务商（如 DeepSeek、OpenAI、智谱、Claude 或自定义端点），用于解析、解题与填表。</li>
  <li>API Key 优先经操作系统加密（Electron <code>safeStorage</code>）保存在本机；若系统加密不可用则降级为浏览器本地存储。无论哪种方式，均<strong>不会上传</strong>至本软件作者的服务器（详见设置页「Key 存于本机」说明）。</li>
  <li><strong>深度模式</strong>可能向模型发送更完整的作业原文与中间推理/审稿内容，调用次数与 token 消耗高于标准模式。</li>
</ul>
<p><strong>本地日志</strong></p>
<p>后端运行日志（已脱敏，不含 API Key 与长正文）写入本机文件，便于排查问题：</p>
<p class="compliance-log-path"><code>${escapeComplianceHtml(logFilePath || '%APPDATA%\\lab-solver\\app.log')}</code></p>
<p class="form-hint">可在设置页点击「打开日志目录」查看；日志请勿分享给他人。</p>
`;

const ONBOARDING_STEPS = [
  {
    title: '1. 上传文档',
    body: '将实验报告（.docx）或题目 PDF 拖入 Step 1。主路径是<strong>生成答案内容</strong>，由你自行粘贴到学校模版或学习通。',
  },
  {
    title: '2. 生成约束与执行',
    body: 'Step 2 可设置语言、是否内化验证代码、诚信标注等。点「生成计划 → 执行」后进入<strong>答案工作区</strong>，分节复制或下载 Markdown / docx / 代码 zip。',
  },
  {
    title: '3. 填表为高级可选',
    body: '「尝试填入 Word 模版」在<strong>高级 / 实验性</strong>区，不保证版式；填表失败不影响复制或下载答案。工具箱主链为 #1 解析 → #2 解题。',
  },
];

function escapeComplianceHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function getCompliancePrefs() {
  try {
    return JSON.parse(localStorage.getItem(COMPLIANCE_STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

function setCompliancePrefs(patch) {
  const next = { ...getCompliancePrefs(), ...patch };
  localStorage.setItem(COMPLIANCE_STORAGE_KEY, JSON.stringify(next));
  return next;
}

function hasAcceptedDisclaimer() {
  const p = getCompliancePrefs();
  return p.disclaimer_version >= DISCLAIMER_VERSION && p.disclaimer_accepted === true;
}

function markDisclaimerAccepted() {
  setCompliancePrefs({
    disclaimer_accepted: true,
    disclaimer_version: DISCLAIMER_VERSION,
    disclaimer_accepted_at: new Date().toISOString(),
  });
}

function hasCompletedOnboarding() {
  const p = getCompliancePrefs();
  return p.onboarding_version >= ONBOARDING_VERSION && p.onboarding_completed === true;
}

function markOnboardingCompleted() {
  setCompliancePrefs({
    onboarding_completed: true,
    onboarding_version: ONBOARDING_VERSION,
    onboarding_completed_at: new Date().toISOString(),
  });
}

function showAppModal(options) {
  const overlay = document.getElementById('complianceModal');
  const titleEl = document.getElementById('complianceModalTitle');
  const bodyEl = document.getElementById('complianceModalBody');
  const primaryBtn = document.getElementById('complianceModalPrimary');
  const secondaryBtn = document.getElementById('complianceModalSecondary');
  const checkWrap = document.getElementById('complianceModalCheckWrap');
  const checkEl = document.getElementById('complianceModalCheck');

  if (!overlay || !titleEl || !bodyEl || !primaryBtn) {
    return Promise.resolve(options.allowDismiss !== false);
  }

  titleEl.textContent = options.title || '';
  bodyEl.innerHTML = options.bodyHtml || '';
  primaryBtn.textContent = options.primaryLabel || '确定';
  if (secondaryBtn) {
    if (options.secondaryLabel) {
      secondaryBtn.style.display = 'inline-flex';
      secondaryBtn.textContent = options.secondaryLabel;
    } else {
      secondaryBtn.style.display = 'none';
    }
  }
  if (checkWrap && checkEl) {
    if (options.checkboxLabel) {
      checkWrap.style.display = 'flex';
      checkEl.checked = false;
      const label = checkWrap.querySelector('span');
      if (label) label.textContent = options.checkboxLabel;
      if (options.requireCheckbox) {
        primaryBtn.disabled = true;
        checkEl.onchange = () => {
          primaryBtn.disabled = !checkEl.checked;
        };
      } else {
        primaryBtn.disabled = false;
        checkEl.onchange = null;
      }
    } else {
      checkWrap.style.display = 'none';
      primaryBtn.disabled = false;
    }
  }

  overlay.classList.add('visible');
  overlay.setAttribute('aria-hidden', 'false');
  const modalBox = overlay.querySelector('.compliance-modal');
  if (modalBox) {
    modalBox.onclick = (e) => e.stopPropagation();
  }

  return new Promise((resolve) => {
    const cleanup = () => {
      overlay.classList.remove('visible');
      overlay.setAttribute('aria-hidden', 'true');
      primaryBtn.onclick = null;
      primaryBtn.disabled = false;
      if (secondaryBtn) secondaryBtn.onclick = null;
      overlay.onclick = null;
      if (checkEl) checkEl.onchange = null;
    };

    primaryBtn.onclick = () => {
      if (options.requireCheckbox && checkEl && !checkEl.checked) {
        return;
      }
      cleanup();
      if (options.onPrimary) options.onPrimary();
      resolve(true);
    };

    if (secondaryBtn && options.secondaryLabel) {
      secondaryBtn.onclick = () => {
        cleanup();
        if (options.onSecondary) options.onSecondary();
        resolve(false);
      };
    }

    if (options.allowDismiss !== false) {
      overlay.onclick = (e) => {
        if (e.target === overlay) {
          cleanup();
          resolve(false);
        }
      };
    } else {
      overlay.onclick = null;
    }
  });
}

function showDisclaimerModal(required) {
  return showAppModal({
    title: '免责声明',
    bodyHtml: `<div class="compliance-prose">${DISCLAIMER_HTML}</div>`,
    primaryLabel: required ? '我已阅读并同意' : '关闭',
    secondaryLabel: required ? null : '查看隐私说明',
    checkboxLabel: required ? '我已阅读并理解上述条款' : null,
    requireCheckbox: !!required,
    allowDismiss: !required,
    onPrimary: () => {
      if (required) markDisclaimerAccepted();
    },
    onSecondary: required
      ? undefined
      : () => {
          showPrivacyModal();
        },
  });
}

function showPrivacyModal() {
  const path = window.__labSolverLogFile || '';
  return showAppModal({
    title: '隐私说明',
    bodyHtml: `<div class="compliance-prose">${PRIVACY_HTML(path)}</div>`,
    primaryLabel: '知道了',
    allowDismiss: true,
  });
}

function showOnboardingModal() {
  const stepsHtml = ONBOARDING_STEPS.map(
    (s) => `<div class="onboarding-step"><h4>${escapeComplianceHtml(s.title)}</h4><p>${s.body}</p></div>`
  ).join('');
  return showAppModal({
    title: '欢迎使用解题能手',
    bodyHtml: `<div class="compliance-prose onboarding-flow">${stepsHtml}</div>`,
    primaryLabel: '开始使用',
    secondaryLabel: '稍后再看',
    allowDismiss: true,
    onPrimary: () => markOnboardingCompleted(),
  });
}

function renderComplianceSettings(logFilePath) {
  const disclaimerEl = document.getElementById('complianceDisclaimerText');
  const privacyEl = document.getElementById('compliancePrivacyText');
  const logPathEl = document.getElementById('complianceLogPath');
  if (disclaimerEl) disclaimerEl.innerHTML = DISCLAIMER_HTML;
  if (privacyEl) privacyEl.innerHTML = PRIVACY_HTML(logFilePath || window.__labSolverLogFile || '');
  if (logPathEl) {
    logPathEl.textContent = logFilePath || window.__labSolverLogFile || '';
  }
}

async function fetchLogFilePath(apiGet) {
  try {
    const resp = await apiGet('/api/logs?n=1');
    if (resp && resp.log_file) {
      window.__labSolverLogFile = resp.log_file;
      renderComplianceSettings(resp.log_file);
      return resp.log_file;
    }
  } catch {
    /* ignore */
  }
  return window.__labSolverLogFile || '';
}

let complianceStartupPromise = null;

async function runComplianceStartupSequence(apiGet) {
  if (complianceStartupPromise) return complianceStartupPromise;
  complianceStartupPromise = (async () => {
    await fetchLogFilePath(apiGet);
    if (!hasAcceptedDisclaimer()) {
      await showDisclaimerModal(true);
    }
    if (!hasCompletedOnboarding()) {
      await showOnboardingModal();
    }
  })();
  return complianceStartupPromise;
}

function buildSectionsSummary(sectionsConfig, sectionRowDefs, fillModeOptions) {
  const cfg = sectionsConfig || {};
  const sections = cfg.sections || [];
  const labelById = {};
  (sectionRowDefs || []).forEach((d) => {
    labelById[d.id] = d.label;
  });
  const modeLabel = {};
  (fillModeOptions || []).forEach((o) => {
    modeLabel[o.value] = o.label;
  });
  return sections.map((s) => {
    const id = s.id || '?';
    const mode = s.mode || 'auto';
    return {
      id,
      label: labelById[id] || id,
      mode,
      mode_label: modeLabel[mode] || mode,
    };
  });
}

function buildDocumentRolesSummary(ctx) {
  const roles = [];
  const file = ctx.currentFile;
  if (!file || file === 'demo') {
    roles.push({ role: 'demo', name: '演示文档' });
    return roles;
  }
  const name = file.split(/[\\/]/).pop();
  const meta = ctx.parsedMetadata || {};
  const fmt = meta.source_format || (name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'docx');
  roles.push({
    role: meta.document_role || 'report',
    name,
    format: fmt,
    course: meta.course || undefined,
  });
  if (ctx.agentSplitIdx != null) {
    roles.push({ role: 'split', note: `合体拆分索引 ${ctx.agentSplitIdx}` });
  }
  if (ctx.agentDocumentIds && ctx.agentDocumentIds.length > 1) {
    roles.push({ role: 'multi_doc', count: ctx.agentDocumentIds.length });
  }
  return roles;
}

function summarizeDecisionLog(entries, maxItems) {
  const max = maxItems == null ? 8 : maxItems;
  return (entries || []).slice(-max).map((e) => ({
    agent: e.agent || '',
    decision: e.decision || '',
    target: e.target || '',
    reason: (e.reason || '').slice(0, 120),
  }));
}

function buildHistoryRecord(base, ctx) {
  const sectionsSummary = buildSectionsSummary(
    ctx.sectionsConfig,
    ctx.sectionRowDefs,
    ctx.fillModeOptions
  );
  const documentRoles = buildDocumentRolesSummary(ctx);
  const decisionSummary = summarizeDecisionLog(ctx.decisionLog);
  const runMode = ctx.runMode || 'standard';
  const runModeLabel =
    runMode === 'react'
      ? '实验 ReAct'
      : runMode === 'deep'
        ? '深度'
        : '标准';

  const record = {
    ...base,
    run_mode: runMode,
    run_mode_label: runModeLabel,
    sections_summary: sectionsSummary,
    document_roles: documentRoles,
    decision_summary: decisionSummary,
    plan_fingerprint: ctx.planFingerprint || undefined,
    exported_at: new Date().toISOString(),
  };
  const rs = ctx.runSummary;
  if (rs && typeof rs === 'object') {
    record.run_summary = rs;
    if (rs.pipeline_version || rs.code_status) {
      record.pipeline_meta = {
        version: rs.pipeline_version,
        code_status: rs.code_status,
      };
    }
  }
  const pf = ctx.planFeedback;
  if (pf && pf.plan_feedback) {
    record.plan_feedback = pf.plan_feedback;
  }
  return record;
}

async function confirmBeforeFillReport(sectionsConfig, sectionRowDefs, fillModeOptions, isLabReport) {
  if (isLabReport) {
    return showFillConfirmModal(sectionsConfig, sectionRowDefs, fillModeOptions);
  }
  return showAppModal({
    title: '填表前确认',
    bodyHtml:
      '<div class="compliance-prose"><p>将把 AI 解答写入 Word 对应题目位置。请确认原报告中无需保留的手写内容已备份。</p></div>',
    primaryLabel: '确认并生成报告',
    secondaryLabel: '取消',
    allowDismiss: true,
  });
}

function showFillConfirmModal(sectionsConfig, sectionRowDefs, fillModeOptions) {
  const summary = buildSectionsSummary(sectionsConfig, sectionRowDefs, fillModeOptions);
  const overwrite = summary.filter((s) => s.mode === 'auto' || s.mode === 'user_provided');
  const protectedModes = summary.filter((s) => s.mode === 'skip' || s.mode === 'preserve');
  const other = summary.filter(
    (s) => !overwrite.includes(s) && !protectedModes.includes(s)
  );

  const rowHtml = (items, cls) =>
    items.length
      ? `<ul class="fill-confirm-list ${cls}">${items
          .map(
            (s) =>
              `<li><strong>${escapeComplianceHtml(s.label)}</strong> — ${escapeComplianceHtml(s.mode_label)}</li>`
          )
          .join('')}</ul>`
      : '<p class="form-hint">（无）</p>';

  const bodyHtml = `
    <p>即将把 AI 生成内容写入 Word 报告。请确认以下范围：</p>
    <h4 class="fill-confirm-heading fill-confirm-overwrite">将写入或覆盖的节</h4>
    ${rowHtml(overwrite, 'fill-overwrite')}
    <h4 class="fill-confirm-heading fill-confirm-protected">不覆盖（跳过 / 保留原文）</h4>
    ${rowHtml(protectedModes, 'fill-protected')}
    ${
      other.length
        ? `<h4 class="fill-confirm-heading">其他</h4>${rowHtml(other, 'fill-other')}`
        : ''
    }
    <p class="form-hint fill-confirm-warn">请确认无重要手写内容会被覆盖；不确定的节请在 Step 2 改为「有内容不覆盖」或「不填」。</p>
  `;

  return showAppModal({
    title: '填表前确认',
    bodyHtml: `<div class="compliance-prose">${bodyHtml}</div>`,
    primaryLabel: '确认并生成报告',
    secondaryLabel: '取消',
    allowDismiss: true,
  });
}

function openLogFolder() {
  const p = window.__labSolverLogFile;
  if (!p) {
    return false;
  }
  const sep = p.includes('\\') ? '\\' : '/';
  const folder = p.substring(0, p.lastIndexOf(sep));
  if (folder && window.electronAPI && window.electronAPI.openFileExternal) {
    window.electronAPI.openFileExternal(folder);
    return true;
  }
  return false;
}
