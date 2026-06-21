/**
 * 文档格式 AI 校验与一键排版助手 - 前端应用
 * 3 步流程：上传 → 排版 → 下载
 */
(function () {
  'use strict';

  // ========== 全局状态 ==========
  const state = {
    currentStep: 1,
    jobId: null,
    templateFile: null,
    contentFile: null,
    pollTimer: null
  };

  // ========== DOM 快捷查找 ==========
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  // ========== 初始化 ==========
  function init() {
    bindUploadEvents();
    bindStepNavEvents();
    bindProcessEvents();
    bindResultEvents();
  }

  // ========== Step 1: 文件上传 ==========
  function bindUploadEvents() {
    // 模板上传
    setupUploadCard('template');
    // 内容上传
    setupUploadCard('content');

    $('#toStep2').addEventListener('click', startProcessing);
  }

  function setupUploadCard(type) {
    const card = $(`#${type}Card`);
    const zone = $(`#${type}Zone`);
    const input = $(`#${type}Input`);
    const removeBtn = $(`#${type}Remove`);

    zone.addEventListener('click', () => input.click());
    zone.addEventListener('dragover', (e) => { e.preventDefault(); card.classList.add('is-dragover'); });
    zone.addEventListener('dragleave', () => card.classList.remove('is-dragover'));
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      card.classList.remove('is-dragover');
      if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0], type);
    });
    input.addEventListener('change', (e) => {
      if (e.target.files[0]) handleFile(e.target.files[0], type);
    });
    removeBtn.addEventListener('click', () => removeFile(type));
  }

  function handleFile(file, type) {
    const ext = '.' + file.name.split('.').pop().toLowerCase();
    if (!['.docx', '.pdf'].includes(ext)) {
      showStatus(type, '不支持的文件格式，请上传 .docx 或 .pdf');
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      showStatus(type, '文件不能超过 50MB');
      return;
    }

    // 检查是否与另一个文件相同
    const other = type === 'template' ? state.contentFile : state.templateFile;
    if (other && other.name === file.name && other.size === file.size) {
      showStatus(type, '模板和内容文件不能相同');
      return;
    }

    if (type === 'template') state.templateFile = file;
    else state.contentFile = file;

    clearStatus(type);
    showFileInfo(type, file);
    updateStartButton();
  }

  function showFileInfo(type, file) {
    $(`#${type}Zone`).style.display = 'none';
    $(`#${type}Info`).style.display = 'flex';
    $(`#${type}Name`).textContent = file.name;
    $(`#${type}Size`).textContent = formatSize(file.size);
    $(`#${type}Card`).classList.add('has-file');
  }

  function removeFile(type) {
    if (type === 'template') state.templateFile = null;
    else state.contentFile = null;
    $(`#${type}Zone`).style.display = '';
    $(`#${type}Info`).style.display = 'none';
    $(`#${type}Card`).classList.remove('has-file');
    $(`#${type}Input`).value = '';
    clearStatus(type);
    updateStartButton();
  }

  function showStatus(type, msg) {
    const el = $(`#${type}Status`);
    el.textContent = msg;
    el.className = 'upload-status error';
  }
  function clearStatus(type) {
    const el = $(`#${type}Status`);
    el.textContent = '';
    el.className = 'upload-status';
  }
  function updateStartButton() {
    $('#toStep2').disabled = !(state.templateFile && state.contentFile);
  }
  function formatSize(b) {
    return b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(1) + ' KB' : (b / 1048576).toFixed(1) + ' MB';
  }

  // ========== 步骤导航 ==========
  function bindStepNavEvents() {
    $('#backToStep1FromProcess')?.addEventListener('click', () => goToStep(1));
    $('#startOver')?.addEventListener('click', () => resetAll());
  }

  function goToStep(n) {
    state.currentStep = n;
    $$('.step').forEach(el => {
      const s = parseInt(el.dataset.step);
      el.classList.remove('active', 'completed');
      if (s === n) el.classList.add('active');
      if (s < n) el.classList.add('completed');
    });
    $$('.step-panel').forEach(p => p.classList.remove('active'));
    $(`#step${n}`).classList.add('active');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function resetAll() {
    clearInterval(state.pollTimer);
    state.jobId = null;
    state.templateFile = null;
    state.contentFile = null;
    removeFile('template');
    removeFile('content');
    goToStep(1);
  }

  // ========== Step 2: 处理 ==========
  function bindProcessEvents() {
    $('#retryProcess')?.addEventListener('click', startProcessing);
  }

  async function startProcessing() {
    if (!state.templateFile || !state.contentFile) {
      showToast('请先上传两个文件', 'error');
      return;
    }

    goToStep(2);
    resetProgressUI();

    try {
      // 1. 上传文件
      updateStage(1, 'active', '上传文件中...');
      setProgress(5);
      log('正在上传文件...');

      const form = new FormData();
      form.append('template', state.templateFile);
      form.append('content', state.contentFile);

      const upRes = await fetch('/api/upload', { method: 'POST', body: form });
      const upData = await upRes.json();
      if (upData.error) throw new Error(upData.message);

      state.jobId = upData.jobId;
      updateStage(1, 'completed');
      setProgress(10);

      // 2. 启动处理
      updateStage(2, 'active');
      log('正在启动 AI 排版引擎...');

      const pRes = await fetch('/api/process', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jobId: state.jobId })
      });
      const pData = await pRes.json();
      if (pData.error) throw new Error(pData.message);

      setProgress(15);

      // 3. 轮询进度
      await pollProgress(state.jobId);

    } catch (err) {
      // 显示详细错误
      const errorMsg = err.message || '网络连接失败，请检查服务器是否运行';
      log('❌ ' + errorMsg);
      // 红色错误横幅
      const errEl = $('#processError');
      errEl.textContent = '❌ ' + errorMsg;
      errEl.style.display = 'block';
      // 所有阶段标为失败
      for (let i = 1; i <= 4; i++) {
        const s = $(`#stage${i}`);
        s.classList.remove('active');
        s.classList.add('completed');
        s.querySelector('.stage-icon').textContent = '❌';
      }
      $('#processActions').style.display = 'flex';
      showToast(errorMsg, 'error');
    }
  }

  function resetProgressUI() {
    setProgress(0);
    log('准备中...');
    $('#processError').style.display = 'none';
    $('#processError').textContent = '';
    $('#processActions').style.display = 'none';
    for (let i = 1; i <= 4; i++) {
      const s = $(`#stage${i}`);
      s.classList.remove('active', 'completed');
      s.querySelector('.stage-icon').textContent = '○';
    }
  }

  async function pollProgress(jobId) {
    return new Promise((resolve, reject) => {
      const tick = async () => {
        try {
          const r = await fetch(`/api/job/${jobId}/status`);
          const d = await r.json();
          if (d.error) { clearInterval(state.pollTimer); reject(new Error(d.message)); return; }

          setProgress(d.progress);
          if (d.log) log(d.log);

          // 阶段映射
          const stageMap = {
            'parsing-template': [1],
            'parsing-content': [1, 2],
            'ai-matching': [1, 2, 3],
            'generating-docx': [1, 2, 3, 4]
          };
          if (stageMap[d.currentStage]) {
            stageMap[d.currentStage].forEach((n, idx) => {
              updateStage(n, idx === stageMap[d.currentStage].length - 1 ? 'active' : 'completed');
            });
          }

          if (d.status === 'complete') {
            clearInterval(state.pollTimer);
            for (let i = 1; i <= 4; i++) updateStage(i, 'completed');
            setProgress(100);
            log('✅ 排版完成！');
            setTimeout(() => loadPreview(jobId), 600);
            resolve();
          } else if (d.status === 'error') {
            clearInterval(state.pollTimer);
            $('#processActions').style.display = 'flex';
            reject(new Error(d.error || '未知错误'));
          }
        } catch (e) {
          clearInterval(state.pollTimer);
          reject(e);
        }
      };
      tick();
      state.pollTimer = setInterval(tick, 1000);
    });
  }

  function setProgress(v) { $('#progressBar').style.width = v + '%'; }
  function log(msg) { const el = $('#processLog'); if (el) el.textContent = msg; }
  function updateStage(n, status, customText) {
    const s = $(`#stage${n}`);
    if (!s) return;
    s.classList.remove('active', 'completed');
    if (status === 'active') s.classList.add('active');
    if (status === 'completed') s.classList.add('completed');
    const icon = s.querySelector('.stage-icon');
    if (status === 'active') icon.textContent = '⏳';
    if (status === 'completed') icon.textContent = '✅';
    if (customText) s.querySelector('.stage-text').textContent = customText;
  }

  // ========== Step 3: 预览与下载 ==========
  function bindResultEvents() {
    $('#downloadDocx')?.addEventListener('click', downloadDocx);
  }

  async function loadPreview(jobId) {
    goToStep(3);
    try {
      const r = await fetch(`/api/job/${jobId}/preview`);
      const d = await r.json();
      if (d.error) throw new Error(d.message);

      renderSummary(d.formattingSummary || []);
      $('#previewContainer').innerHTML = d.html || '<div class="preview-loading">预览生成中...</div>';
    } catch (e) {
      $('#previewContainer').innerHTML = `<div class="preview-loading">预览加载失败: ${e.message}</div>`;
    }
  }

  function renderSummary(summary) {
    const list = $('#summaryList');
    list.innerHTML = '';
    if (!summary.length) { list.innerHTML = '<div class="summary-entry">暂无格式变更</div>'; return; }
    for (const item of summary) {
      const div = document.createElement('div');
      div.className = 'summary-entry';
      const alignMap = { left: '左对齐', center: '居中', right: '右对齐', both: '两端对齐' };
      div.innerHTML = `<span class="change-icon">📐</span><span class="change-detail">
        <strong>${item.styleName || item.styleId}</strong>：${item.font} ${item.size}${item.bold ? ' 加粗' : ''} ${alignMap[item.alignment] || item.alignment || ''} — ${item.appliedCount} 个段落</span>`;
      list.appendChild(div);
    }
  }

  function downloadDocx() {
    if (!state.jobId) { showToast('没有可下载的文件', 'error'); return; }
    const a = document.createElement('a');
    a.href = `/api/job/${state.jobId}/download`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    showToast('开始下载...', 'success');
  }

  // ========== Toast ==========
  function showToast(msg, type) {
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.textContent = msg;
    $('#toastContainer').appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transform = 'translateX(40px)'; t.style.transition = 'all 0.3s ease'; setTimeout(() => t.remove(), 300); }, 3500);
  }

  // ========== 启动 ==========
  document.addEventListener('DOMContentLoaded', init);
})();
