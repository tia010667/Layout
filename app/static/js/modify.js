/**
 * FormatAI — 自然语言格式微调页面
 * Pure HTML/CSS/JS, zero framework dependency.
 */

(function () {
    'use strict';

    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const state = {
        file: null,
        resultJobId: null,
    };

    // ============================================================
    // Tabs
    // ============================================================
    const tabs = $$('.tab');
    const panels = {
        job: $('#panel-job'),
        file: $('#panel-file'),
    };

    tabs.forEach((t) => {
        t.addEventListener('click', () => {
            tabs.forEach((x) => x.classList.remove('active'));
            t.classList.add('active');
            Object.values(panels).forEach((p) => p.classList.remove('active'));
            panels[t.dataset.tab].classList.add('active');
        });
    });

    // ============================================================
    // Pre-fill job_id from URL (?job_id=...)
    // ============================================================
    const params = new URLSearchParams(location.search);
    if (params.get('job_id')) {
        $('#job-id-input').value = params.get('job_id');
    }

    // ============================================================
    // File upload
    // ============================================================
    const fileZone = $('#file-zone');
    const fileInput = $('#file-input');
    const fileTag = $('#file-tag');

    fileZone.addEventListener('click', (e) => {
        if (e.target.closest('.btn-choose')) return;
        fileInput.click();
    });
    fileZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        fileZone.classList.add('drag-over');
    });
    fileZone.addEventListener('dragleave', () => fileZone.classList.remove('drag-over'));
    fileZone.addEventListener('drop', (e) => {
        e.preventDefault();
        fileZone.classList.remove('drag-over');
        if (e.dataTransfer.files.length > 0) setFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) setFile(fileInput.files[0]);
    });

    function setFile(file) {
        state.file = file;
        fileTag.classList.remove('hidden');
        fileTag.querySelector('.tag-name').textContent = file.name;
        fileZone.classList.add('has-file');
    }

    // ============================================================
    // Example chips
    // ============================================================
    $$('.example-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            $('#instruction').value = chip.textContent;
            $('#instruction').focus();
        });
    });

    // ============================================================
    // Apply
    // ============================================================
    const btnApply = $('#btn-apply');

    btnApply.addEventListener('click', async () => {
        const instruction = $('#instruction').value.trim();
        if (!instruction) {
            showError('请输入格式修改指令');
            return;
        }

        const activeTab = document.querySelector('.tab.active').dataset.tab;
        const formData = new FormData();
        formData.append('instruction', instruction);

        if (activeTab === 'file' && state.file) {
            formData.append('file', state.file);
        } else {
            const jobId = $('#job-id-input').value.trim();
            if (!jobId) {
                showError('请输入作业 ID，或切换到「上传 .docx」上传文档');
                return;
            }
            formData.append('source_job_id', jobId);
        }

        hideError();
        btnApply.disabled = true;
        btnApply.innerHTML = '<span class="btn-icon">&#x23F3;</span> 调整中...';

        try {
            const resp = await fetch('/api/modify', { method: 'POST', body: formData });
            if (!resp.ok) {
                let detail = '请求失败';
                try { detail = (await resp.json()).detail || detail; } catch (_) {}
                throw new Error(detail);
            }

            const data = await resp.json();
            state.resultJobId = data.job_id;

            $('#summary').textContent = data.summary || '已完成格式调整';
            $('#result-section').classList.remove('hidden');
            $('#preview-frame').srcdoc = data.preview_html || '';
            $('#preview-pane').classList.add('hidden');
        } catch (err) {
            showError(err.message);
        } finally {
            btnApply.disabled = false;
            btnApply.innerHTML = '&#x2728; 应用格式修改';
        }
    });

    // ============================================================
    // Result actions
    // ============================================================
    $('#btn-preview').addEventListener('click', () => {
        $('#preview-pane').classList.remove('hidden');
    });
    $('#btn-close-preview').addEventListener('click', () => {
        $('#preview-pane').classList.add('hidden');
    });
    $('#btn-download').addEventListener('click', () => {
        if (state.resultJobId) {
            window.open(`/api/job/${state.resultJobId}/download`, '_blank');
        }
    });
    $('#btn-continue').addEventListener('click', () => {
        if (!state.resultJobId) return;
        // Switch back to the "from job" tab, carrying the current result.
        tabs.forEach((x) => x.classList.remove('active'));
        document.querySelector('.tab[data-tab="job"]').classList.add('active');
        Object.values(panels).forEach((p) => p.classList.remove('active'));
        panels.job.classList.add('active');

        $('#job-id-input').value = state.resultJobId;
        $('#instruction').value = '';
        $('#preview-pane').classList.add('hidden');
        $('#result-section').classList.add('hidden');
        state.file = null;
        $('#file-tag').classList.add('hidden');
        $('#file-zone').classList.remove('has-file');
        fileInput.value = '';
    });

    // ============================================================
    // Error handling
    // ============================================================
    function showError(msg) {
        $('#error-message').textContent = msg;
        $('#error-banner').classList.remove('hidden');
    }

    function hideError() {
        $('#error-banner').classList.add('hidden');
        $('#error-message').textContent = '';
    }
})();
