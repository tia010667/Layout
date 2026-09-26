/**
 * FormatAI — Frontend Application
 * Pure HTML/CSS/JS, zero framework dependency.
 */

(function () {
    'use strict';

    // ============================================================
    // State
    // ============================================================
    const state = {
        jobId: null,
        templateFile: null,
        contentFile: null,
        status: 'idle',
        pollTimer: null,
    };

    // ============================================================
    // DOM References
    // ============================================================
    const $ = (sel) => document.querySelector(sel);
    const $$ = (sel) => document.querySelectorAll(sel);

    const templateZone = $('#template-zone');
    const contentZone = $('#content-zone');
    const templateInput = $('#template-input');
    const contentInput = $('#content-input');
    const fileInfo = $('#file-info');
    const templateTag = $('#template-tag');
    const contentTag = $('#content-tag');
    const processSection = $('#process-section');
    const resultSection = $('#result-section');
    const btnProcess = $('#btn-process');
    const progressContainer = $('#progress-container');
    const progressFill = $('#progress-fill');
    const progressText = $('#progress-text');
    const progressStages = $('#progress-stages');
    const errorBanner = $('#error-banner');
    const errorMessage = $('#error-message');
    const previewPane = $('#preview-pane');
    const previewFrame = $('#preview-frame');
    const btnPreview = $('#btn-preview');
    const btnDownload = $('#btn-download');
    const btnModify = $('#btn-modify');
    const btnClosePreview = $('#btn-close-preview');

    // ============================================================
    // File Upload — Drag & Drop
    // ============================================================
    function setupDropZone(zone, input, fileHandler) {
        zone.addEventListener('dragover', (e) => {
            e.preventDefault();
            zone.classList.add('drag-over');
        });

        zone.addEventListener('dragleave', () => {
            zone.classList.remove('drag-over');
        });

        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileHandler(files[0]);
            }
        });

        zone.addEventListener('click', (e) => {
            // Don't trigger if clicking the remove tag button
            if (e.target.closest('.tag-remove')) return;
            if (e.target.closest('.btn-outline')) return;
            input.click();
        });

        const chooseBtn = zone.querySelector('.btn-choose');
        if (chooseBtn) {
            chooseBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                input.click();
            });
        }

        input.addEventListener('change', () => {
            if (input.files.length > 0) {
                fileHandler(input.files[0]);
            }
        });
    }

    function handleTemplateFile(file) {
        state.templateFile = file;
        const tagName = templateTag.querySelector('.tag-name');
        tagName.textContent = file.name;
        templateTag.classList.remove('hidden');
        templateZone.classList.add('has-file');
        updateFileInfo();
        updateProcessButton();
    }

    function handleContentFile(file) {
        state.contentFile = file;
        const tagName = contentTag.querySelector('.tag-name');
        tagName.textContent = file.name;
        contentTag.classList.remove('hidden');
        contentZone.classList.add('has-file');
        updateFileInfo();
        updateProcessButton();
    }

    function removeFile(type) {
        if (type === 'template') {
            state.templateFile = null;
            templateTag.classList.add('hidden');
            templateZone.classList.remove('has-file');
            templateInput.value = '';
        } else {
            state.contentFile = null;
            contentTag.classList.add('hidden');
            contentZone.classList.remove('has-file');
            contentInput.value = '';
        }
        updateFileInfo();
        updateProcessButton();
    }

    function updateFileInfo() {
        if (state.templateFile || state.contentFile) {
            fileInfo.classList.remove('hidden');
        } else {
            fileInfo.classList.add('hidden');
        }
    }

    function updateProcessButton() {
        processSection.classList.remove('hidden');
        btnProcess.disabled = !(state.templateFile && state.contentFile);
    }

    // Tag remove buttons
    document.querySelectorAll('.tag-remove').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            removeFile(btn.dataset.type);
        });
    });

    // Setup drop zones
    setupDropZone(templateZone, templateInput, handleTemplateFile);
    setupDropZone(contentZone, contentInput, handleContentFile);

    // ============================================================
    // Process — Upload + Start Agent
    // ============================================================
    btnProcess.addEventListener('click', async () => {
        if (!state.templateFile || !state.contentFile) return;

        btnProcess.disabled = true;
        btnProcess.innerHTML = '<span class="btn-icon">&#x23F3;</span> 上传中...';
        hideError();
        resetProgress();

        try {
            // Step 1: Upload files
            const formData = new FormData();
            formData.append('template', state.templateFile);
            formData.append('content', state.contentFile);

            const uploadResp = await fetch('/api/upload', {
                method: 'POST',
                body: formData,
            });

            if (!uploadResp.ok) {
                const err = await uploadResp.json();
                throw new Error(err.detail || 'Upload failed');
            }

            const uploadData = await uploadResp.json();
            state.jobId = uploadData.job_id;

            // Step 2: Start processing
            const processResp = await fetch('/api/process', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ job_id: state.jobId }),
            });

            if (!processResp.ok) {
                const err = await processResp.json();
                throw new Error(err.detail || 'Process failed');
            }

            // Show progress
            progressContainer.classList.remove('hidden');
            btnProcess.innerHTML = '<span class="btn-icon">&#x26A1;</span> 排版中...';

            // Start polling
            startPolling();

        } catch (err) {
            showError(err.message);
            btnProcess.innerHTML = '<span class="btn-icon">&#x26A1;</span> 开始智能排版';
            btnProcess.disabled = false;
        }
    });

    // ============================================================
    // Polling
    // ============================================================
    const STAGE_MAP = {
        'idle': { idx: -1, label: '等待开始...' },
        'parsing_template': { idx: 0, label: '正在解析模板格式...' },
        'analyzing_content': { idx: 1, label: '正在分析内容结构...' },
        'matching_styles': { idx: 2, label: 'AI 正在匹配样式...' },
        'verifying': { idx: 3, label: '正在校验格式映射...' },
        'generating_docx': { idx: 4, label: '正在生成文档...' },
        'completed': { idx: 5, label: '排版完成！' },
        'failed': { idx: -1, label: '排版失败' },
    };

    function startPolling() {
        if (state.pollTimer) clearInterval(state.pollTimer);
        state.pollTimer = setInterval(pollStatus, 500);
    }

    function stopPolling() {
        if (state.pollTimer) {
            clearInterval(state.pollTimer);
            state.pollTimer = null;
        }
    }

    async function pollStatus() {
        if (!state.jobId) return;

        try {
            const resp = await fetch(`/api/job/${state.jobId}/status`);
            if (!resp.ok) throw new Error('Status check failed');

            const data = await resp.json();
            updateProgress(data.status, data.retry_count, data.error);

            if (data.status === 'completed') {
                stopPolling();
                onComplete();
            } else if (data.status === 'failed') {
                stopPolling();
                showError(data.error || 'Agent processing failed');
                btnProcess.innerHTML = '<span class="btn-icon">&#x26A1;</span> 重新排版';
                btnProcess.disabled = false;
            }
        } catch (err) {
            console.error('Poll error:', err);
        }
    }

    function updateProgress(status, retryCount, error) {
        const stageInfo = STAGE_MAP[status] || { idx: -1, label: status };
        const totalStages = 5;
        const pct = status === 'completed'
            ? 100
            : Math.max(0, Math.min(100, ((stageInfo.idx) / totalStages) * 100));

        progressFill.style.width = pct + '%';
        progressText.textContent = stageInfo.label +
            (retryCount > 0 ? ` (重试第 ${retryCount} 次)` : '');

        // Update stage indicators
        const stageElements = progressStages.querySelectorAll('.stage');
        stageElements.forEach((el) => {
            const s = el.dataset.stage;
            const info = STAGE_MAP[s] || { idx: -1 };
            el.classList.remove('active', 'done');
            if (info.idx < stageInfo.idx) {
                el.classList.add('done');
            } else if (info.idx === stageInfo.idx && status !== 'completed') {
                el.classList.add('active');
            } else if (status === 'completed') {
                el.classList.add('done');
            }
        });
    }

    function resetProgress() {
        progressFill.style.width = '0%';
        progressText.textContent = '';
        const stageElements = progressStages.querySelectorAll('.stage');
        stageElements.forEach((el) => el.classList.remove('active', 'done'));
    }

    // ============================================================
    // Results
    // ============================================================
    function onComplete() {
        resultSection.classList.remove('hidden');
        btnProcess.innerHTML = '<span class="btn-icon">&#x26A1;</span> 开始智能排版';
        btnProcess.disabled = false;
        hideError();
    }

    btnPreview.addEventListener('click', async () => {
        if (!state.jobId) return;

        try {
            previewPane.classList.add('hidden');
            const resp = await fetch(`/api/job/${state.jobId}/preview`);
            if (!resp.ok) throw new Error('Preview not available');

            const html = await resp.text();
            previewFrame.srcdoc = html;
            previewPane.classList.remove('hidden');
        } catch (err) {
            showError('无法加载预览: ' + err.message);
        }
    });

    btnClosePreview.addEventListener('click', () => {
        previewPane.classList.add('hidden');
    });

    btnDownload.addEventListener('click', () => {
        if (!state.jobId) return;
        window.open(`/api/job/${state.jobId}/download`, '_blank');
    });

    btnModify.addEventListener('click', () => {
        if (!state.jobId) return;
        window.location.href = `/modify?job_id=${state.jobId}`;
    });

    // ============================================================
    // Error Handling
    // ============================================================
    function showError(msg) {
        errorMessage.textContent = msg;
        errorBanner.classList.remove('hidden');
    }

    function hideError() {
        errorBanner.classList.add('hidden');
        errorMessage.textContent = '';
    }

    // ============================================================
    // Config Status Check (on load)
    // ============================================================
    async function checkConfig() {
        try {
            const resp = await fetch('/api/config-status');
            const data = await resp.json();
            if (!data.configured) {
                console.warn(
                    'FormatAI: API key not configured. ' +
                    'Please set DEEPSEEK_API_KEY in .env'
                );
            }
        } catch (err) {
            console.warn('FormatAI: Could not check config status');
        }
    }

    checkConfig();

})();
