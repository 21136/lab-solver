# -*- coding: utf-8 -*-
"""Add checkbox selection UI to exam question bank HTML."""
import sys
from pathlib import Path

SRC = Path(r"c:\Users\21136\Documents\xwechat_files\wxid_bgqqrg5yurk912_d07a\msg\file\2026-06\软件项目管理期末复习题库.html")
DST = Path(__file__).resolve().parents[1] / "exam-bank-with-checkboxes.html"

CSS_OLD = (
    ".q-block { margin:8px 0 4px; padding:8px 12px; background:var(--ans-bg); "
    "border:1px solid var(--ans-border); border-radius:var(--radius); box-shadow:var(--shadow-sm); }"
)
CSS_NEW = """.q-block { position:relative; margin:8px 0 4px; padding:8px 36px 8px 12px; background:var(--ans-bg); border:1px solid var(--ans-border); border-radius:var(--radius); box-shadow:var(--shadow-sm); transition:border-color 0.2s, background 0.2s; }
.q-block.q-selected { border-color:var(--accent); background:var(--accent-dim); }
.q-check { position:absolute; top:8px; right:10px; width:18px; height:18px; cursor:pointer; accent-color:var(--accent); }
.q-toolbar { padding:0 16px 14px; border-bottom:1px solid rgba(255,255,255,0.07); margin-bottom:12px; }
.q-toolbar .sel-count { font-size:11px; color:var(--sbar-active); margin-bottom:8px; }
.q-toolbar button { display:block; width:100%; margin-bottom:6px; padding:6px 10px; font-size:11px; border:none; border-radius:5px; cursor:pointer; background:rgba(100,181,246,0.15); color:var(--sbar-active); transition:background 0.15s; }
.q-toolbar button:hover { background:rgba(100,181,246,0.28); }
.q-toolbar button.primary { background:var(--accent); color:#fff; font-weight:500; }
.q-toolbar button.primary:hover { background:var(--btn-hover); }
.q-block.q-hidden-filter { display:none!important; }"""

TOOLBAR_OLD = (
    '<div class="sidebar-search"><input type="text" id="search-input" '
    'placeholder="搜索题目…" oninput="searchQuestions()"></div>\n<ul class="sidebar-nav">'
)
TOOLBAR_NEW = """<div class="sidebar-search"><input type="text" id="search-input" placeholder="搜索题目…" oninput="searchQuestions()"></div>
<div class="q-toolbar">
<div class="sel-count" id="sel-count">已选 0 / 186 题</div>
<button type="button" id="btn-filter-sel" onclick="toggleFilterSelected()">仅显示已选</button>
<button type="button" onclick="selectAllQuestions(true)">全选</button>
<button type="button" onclick="selectAllQuestions(false)">取消全选</button>
<button type="button" class="primary" onclick="exportSelectedHTML()">导出已选题目 HTML</button>
<button type="button" onclick="saveSelectionsToFile()">保存勾选状态到文件</button>
</div>
<ul class="sidebar-nav">"""

JS = r"""
/* ── 题目勾选与导出 ── */
const STORAGE_KEY = 'spm-exam-q-selections';
let filterSelectedOnly = false;

function initQuestionCheckboxes() {
    const blocks = document.querySelectorAll('.q-block');
    const saved = loadSelections();
    blocks.forEach((block, i) => {
        const qid = 'q-' + i;
        block.dataset.qid = qid;
        const cb = document.createElement('input');
        cb.type = 'checkbox';
        cb.className = 'q-check';
        cb.title = '标记此题（勾选后自动保存）';
        cb.checked = saved.has(qid);
        cb.addEventListener('change', () => {
            block.classList.toggle('q-selected', cb.checked);
            persistSelections();
            updateSelCount();
            if (filterSelectedOnly) applySelectedFilter();
        });
        block.appendChild(cb);
        if (cb.checked) block.classList.add('q-selected');
    });
    updateSelCount();
}

function loadSelections() {
    const embedded = document.getElementById('saved-selections');
    if (embedded && embedded.textContent.trim()) {
        try {
            const ids = JSON.parse(embedded.textContent);
            if (Array.isArray(ids)) return new Set(ids);
        } catch (_) {}
    }
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return new Set(JSON.parse(raw));
    } catch (_) {}
    return new Set();
}

function getSelectedIds() {
    return [...document.querySelectorAll('.q-block')].filter(b => b.querySelector('.q-check')?.checked).map(b => b.dataset.qid);
}

function persistSelections() {
    const ids = getSelectedIds();
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(ids)); } catch (_) {}
    let el = document.getElementById('saved-selections');
    if (!el) {
        el = document.createElement('script');
        el.id = 'saved-selections';
        el.type = 'application/json';
        document.body.appendChild(el);
    }
    el.textContent = JSON.stringify(ids);
}

function updateSelCount() {
    const total = document.querySelectorAll('.q-block').length;
    const n = getSelectedIds().length;
    const el = document.getElementById('sel-count');
    if (el) el.textContent = '已选 ' + n + ' / ' + total + ' 题';
}

function selectAllQuestions(checked) {
    document.querySelectorAll('.q-block .q-check').forEach(cb => {
        cb.checked = checked;
        cb.closest('.q-block').classList.toggle('q-selected', checked);
    });
    persistSelections();
    updateSelCount();
    if (filterSelectedOnly) applySelectedFilter();
}

function toggleFilterSelected() {
    filterSelectedOnly = !filterSelectedOnly;
    applySelectedFilter();
    const btn = document.getElementById('btn-filter-sel');
    if (btn) btn.textContent = filterSelectedOnly ? '显示全部题目' : '仅显示已选';
}

function applySelectedFilter() {
    document.querySelectorAll('.q-block').forEach(b => {
        const show = !filterSelectedOnly || b.querySelector('.q-check')?.checked;
        b.classList.toggle('q-hidden-filter', !show);
    });
}

function pruneEmptySections(root) {
    root.querySelectorAll('section').forEach(sec => {
        if (sec.id === 'top') return;
        if (!sec.querySelector('.q-block')) sec.remove();
    });
    root.querySelectorAll('.section-title').forEach(t => {
        let sib = t.nextElementSibling;
        let hasQ = false;
        while (sib && !sib.classList.contains('section-title') && !sib.classList.contains('module-title')) {
            if (sib.classList.contains('q-block')) { hasQ = true; break; }
            sib = sib.nextElementSibling;
        }
        if (!hasQ) t.remove();
    });
}

function buildSelectedDocument() {
    const selected = [...document.querySelectorAll('.q-block')].filter(b => b.querySelector('.q-check')?.checked);
    if (!selected.length) { alert('请先勾选至少一道题目'); return null; }
    const clone = document.documentElement.cloneNode(true);
    const selectedIds = new Set(selected.map(b => b.dataset.qid));
    clone.querySelectorAll('.q-block').forEach(b => {
        if (!selectedIds.has(b.dataset.qid)) {
            b.remove();
        } else {
            b.querySelector('.q-check')?.remove();
            b.classList.remove('q-selected', 'q-hidden-filter');
            b.style.paddingRight = '12px';
        }
    });
    clone.querySelector('.q-toolbar')?.remove();
    clone.querySelector('#saved-selections')?.remove();
    const title = clone.querySelector('.main-title');
    if (title) title.textContent = '软件项目管理 期末复习题库（已选 ' + selected.length + ' 题）';
    const badge = clone.querySelector('.sidebar-header .badge');
    if (badge) badge.textContent = '已选 ' + selected.length + ' 题';
    pruneEmptySections(clone);
    return '<!DOCTYPE html>\n' + clone.outerHTML;
}

function downloadHTML(filename, html) {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    URL.revokeObjectURL(a.href);
}

function exportSelectedHTML() {
    const html = buildSelectedDocument();
    if (!html) return;
    downloadHTML('软件项目管理期末复习题库-已选.html', html);
}

function saveSelectionsToFile() {
    const ids = getSelectedIds();
    if (!ids.length) { alert('请先勾选至少一道题目'); return; }
    const clone = document.documentElement.cloneNode(true);
    clone.querySelectorAll('.q-block').forEach(b => {
        const cb = b.querySelector('.q-check');
        if (cb) cb.checked = ids.includes(b.dataset.qid);
    });
    let el = clone.querySelector('#saved-selections');
    if (!el) {
        el = document.createElement('script');
        el.id = 'saved-selections';
        el.type = 'application/json';
        clone.querySelector('body').appendChild(el);
    }
    el.textContent = JSON.stringify(ids);
    const html = '<!DOCTYPE html>\n' + clone.outerHTML;
    downloadHTML('软件项目管理期末复习题库-含勾选.html', html);
}

initQuestionCheckboxes();
"""

MARKER = "document.querySelectorAll('section[id]').forEach(s => observer.observe(s));"


def patch(content: str) -> str:
    if "initQuestionCheckboxes" in content:
        print("Already patched, skipping.")
        return content
    if CSS_OLD not in content:
        raise SystemExit("CSS marker not found")
    if TOOLBAR_OLD not in content:
        raise SystemExit("Toolbar marker not found")
    if MARKER not in content:
        raise SystemExit("JS marker not found")
    content = content.replace(CSS_OLD, CSS_NEW)
    content = content.replace(TOOLBAR_OLD, TOOLBAR_NEW)
    content = content.replace(MARKER, MARKER + "\n" + JS)
    return content


def main() -> None:
    src = SRC if SRC.exists() else DST
    content = src.read_text(encoding="utf-8")
    patched = patch(content)
    DST.write_text(patched, encoding="utf-8")
    print(f"Written: {DST}")
    if SRC.exists() and SRC != DST:
        SRC.write_text(patched, encoding="utf-8")
        print(f"Written: {SRC}")


if __name__ == "__main__":
    main()
