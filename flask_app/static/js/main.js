// UI state stays small: current profile, selected job, saved results and chat status.
let socket = null;
let currentProfileId = null;
let selectedJobId = null;
let resultsCache = [];
let selectedFile = null;
let chatBusy = false;
let chatReady = false;
let chatTimer = null;
let pollTimer = null;
let loadingResults = false;
let latestStageIndex = -1;
let rankingDegraded = false;
const stages = ['cv_analysis', 'embedding', 'fetch_jobs', 'matching', 'complete'];
const terminalStages = ['complete', 'partial', 'failed', 'error'];
const el = id => document.getElementById(id);
const show = (id, visible) => el(id).classList.toggle('hidden', !visible);

document.addEventListener('DOMContentLoaded', () => {
    el('upload-form').addEventListener('submit', handleUpload);
    el('cv-file').addEventListener('change', event => chooseFile(event.target.files[0]));
    const zone = el('drop-zone');
    ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, event => {
        event.preventDefault(); zone.classList.add('dragging');
    }));
    ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, event => {
        event.preventDefault(); zone.classList.remove('dragging');
    }));
    zone.addEventListener('drop', event => chooseFile(event.dataTransfer.files[0]));
    el('chat-form').addEventListener('submit', handleChatSubmit);
    el('chat-input').addEventListener('keydown', event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
            event.preventDefault(); el('chat-form').requestSubmit();
        }
    });
    el('clear-selection').addEventListener('click', () => selectJob(null));
    document.addEventListener('click', event => {
        const question = event.target.closest('[data-question]');
        if (question) sendChat(question.dataset.question, question.dataset.action || 'ask');
        const button = event.target.closest('[data-job-action]');
        if (!button) return;
        selectJob(Number(button.dataset.jobId));
        if (button.dataset.jobAction === 'cover_letter') {
            sendChat('اكتب لي خطاب تقديم لهذه الوظيفة', 'cover_letter');
        }
        el('chat-panel').scrollIntoView({behavior: 'smooth', block: 'nearest'});
        if (button.dataset.jobAction === 'select') el('chat-input').focus({preventScroll: true});
    });
    welcomeChat();
    if (PROFILE_ID) {
        currentProfileId = PROFILE_ID;
        show('upload-section', false); show('new-analysis', true);
        initSocket(currentProfileId);
        loadResults(currentProfileId);
    }
});

function chooseFile(file) {
    if (el('upload-btn').disabled || !file) return;
    const error = !/\.pdf$/i.test(file.name) ? 'اختر ملفًا بصيغة PDF.' :
        file.size > 16 * 1024 * 1024 ? 'حجم الملف أكبر من 16 MB.' :
        file.size === 0 ? 'الملف فارغ. اختر ملفًا آخر.' : '';
    el('upload-error').textContent = error;
    selectedFile = error ? null : file;
    if (error) el('cv-file').value = '';
    el('drop-zone').classList.toggle('has-file', !!selectedFile);
    el('file-name').textContent = selectedFile ? file.name : 'اسحب سيرتك الذاتية إلى هنا';
    el('file-hint').textContent = selectedFile ? 'الملف جاهز · اضغط هنا لاختيار ملف آخر' : 'أو اختر ملفًا من جهازك';
}

async function handleUpload(event) {
    event.preventDefault();
    if (!selectedFile) { el('upload-error').textContent = 'اختر سيرتك الذاتية أولًا.'; return; }
    const button = el('upload-btn');
    button.disabled = true; button.textContent = 'جاري رفع سيرتك…';
    el('upload-error').textContent = '';
    try {
        const form = new FormData(); form.append('file', selectedFile);
        const response = await fetch('/upload', {method: 'POST', body: form});
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.error || 'تعذر رفع الملف.');
        currentProfileId = data.profile_id;
        history.replaceState(null, '', '/results/' + currentProfileId);
        show('upload-section', false); show('progress-section', true); show('new-analysis', true);
        initSocket(currentProfileId);
        loadResults(currentProfileId);
    } catch (error) {
        el('upload-error').textContent = error.message || 'تعذر الاتصال بالخادم.';
    } finally {
        button.disabled = false; button.innerHTML = 'اكتشف الوظائف المناسبة <span aria-hidden="true">←</span>';
    }
}

async function loadResults(profileId) {
    if (loadingResults) return;
    loadingResults = true;
    try {
        const response = await fetch('/api/results/' + profileId);
        const data = await response.json();
        if (!response.ok) throw new Error(response.status === 403 ?
            'هذه النتائج غير متاحة لهذه الجلسة. ارفع سيرتك لبدء تحليل جديد.' :
            'تعذر تحميل النتائج. حاول إعادة تحميل الصفحة.');
        const p = data.profile;
        el('profile-content').innerHTML =
            '<h2 dir="auto">' + escapeHtml(p.name || 'ملفك المهني') + '</h2>' +
            '<p class="profile-meta"><bdi>' + escapeHtml(p.field || 'المجال غير محدد') + '</bdi> · <bdi>' +
            escapeHtml(p.level || 'المستوى غير محدد') + '</bdi></p>' +
            '<div class="tags">' + tags(p.skills) + '</div>' +
            (p.summary ? '<p class="profile-summary-text" dir="auto">' + escapeHtml(p.summary) + '</p>' : '');
        rankingDegraded = data.analysis?.data?.semantic_ranking === 'degraded';
        resultsCache = data.results || [];
        renderResults(resultsCache);
        const terminal = terminalStages.includes(data.analysis?.stage);
        show('results-section', terminal || resultsCache.length > 0);
        if (data.analysis) handleProgress(data.analysis, false);
        else { show('progress-section', true); schedulePoll(); }
        if (!resultsCache.length) {
            el('results-list').innerHTML = '<div class="empty-state">' +
                (terminal ? 'لا توجد نتائج مطابقة محفوظة. يمكنك تجربة تحليل جديد.' : 'نتائجك ستظهر هنا عند اكتمال المطابقة.') + '</div>';
        }
    } catch (error) {
        show('results-section', true);
        el('results-list').innerHTML = '<div class="empty-state">' + escapeHtml(error.message) + '</div>';
        show('profile-summary', false);
        if (pollTimer) clearTimeout(pollTimer);
    } finally { loadingResults = false; }
}

function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => loadResults(currentProfileId), 5000);
}

function handleProgress(data, refresh = true) {
    if (!data || !data.stage) return;
    const stage = data.stage;
    const terminal = terminalStages.includes(stage);
    show('progress-section', true);
    el('progress-message').textContent = data.message || 'جاري التحليل…';
    el('progress-section').classList.toggle('finished', terminal);
    show('progress-indicator', !['failed', 'error', 'partial'].includes(stage));
    el('progress-title').textContent = stage === 'complete' ? 'اكتمل تحليل سيرتك' :
        stage === 'partial' ? 'نتائج التحليل المتاحة' :
        ['failed', 'error'].includes(stage) ? 'لم يكتمل التحليل' : 'نبحث عن الفرص الأقرب إليك';
    show('retry-analysis', terminal && stage !== 'complete');
    latestStageIndex = Math.max(latestStageIndex, stages.indexOf(stage));
    document.querySelectorAll('.step').forEach((step, index) => {
        const done = stage === 'complete' || index < latestStageIndex;
        const active = !terminal && index === latestStageIndex;
        step.classList.toggle('done', done);
        step.classList.toggle('active', active);
        step.classList.toggle('error', ['failed', 'error'].includes(stage) && index === latestStageIndex);
        step.querySelector('.step-icon').textContent = done ? '✓' : String(index + 1).padStart(2, '0');
        step.querySelector('.step-status').textContent = done ? 'تم' : active ? 'جاري العمل' : '';
        if (active) step.setAttribute('aria-current', 'step'); else step.removeAttribute('aria-current');
    });
    const notes = [];
    if (data.data?.semantic_ranking === 'degraded') notes.push('تعذر إكمال البحث الدلالي. اختيار الوظائف تقريبي، وتقييم المطابقة المعروض صادر عن نموذج الذكاء الاصطناعي.');
    if (stage === 'partial' || stage === 'failed' || stage === 'error') notes.push(data.message || 'بعض النتائج غير متاحة.');
    el('analysis-notice').textContent = notes.join(' ');
    show('analysis-notice', notes.length > 0);
    if (terminal) {
        clearTimeout(pollTimer);
        if (refresh) loadResults(currentProfileId);
    } else schedulePoll();
}

function initSocket(profileId) {
    if (socket) socket.disconnect();
    if (typeof io !== 'function') {
        el('connection-status').textContent = 'تعذر تحميل اتصال الشات. أعد تحميل الصفحة.';
        return; // REST polling still delivers analysis results.
    }
    socket = io();
    socket.on('connect', () => {
        chatReady = false; updateChatControls();
        el('connection-status').textContent = 'جاري استعادة المحادثة…';
        socket.emit('join', {profile_id: profileId});
        socket.emit('request_chat_history', {profile_id: profileId});
    });
    socket.on('disconnect', () => {
        chatReady = false; setChatBusy(false);
        el('connection-status').textContent = 'انقطع الاتصال · نحاول إعادة الاتصال';
    });
    socket.on('connect_error', () => {
        chatReady = false; updateChatControls();
        el('connection-status').textContent = 'تعذر الاتصال بالشات · نحاول مجددًا';
    });
    socket.on('analysis_progress', data => handleProgress(data));
    socket.on('chat_response', data => {
        setChatBusy(false);
        appendChatMessage('agent', data.message, data.job_id);
    });
    socket.on('chat_history', data => {
        el('chat-messages').replaceChildren();
        (data.messages || []).forEach(message => appendChatMessage(message.sender, message.message, message.job_id));
        if (!(data.messages || []).length) welcomeChat();
        chatReady = true; updateChatControls();
        el('connection-status').textContent = 'متصل · جاهز لمساعدتك';
    });
}

function renderResults(results) {
    el('jobs-count').textContent = results.length;
    el('result-count').textContent = results.length + ' فرص للمراجعة';
    el('results-list').innerHTML = results.map(result => {
        const id = Number(result.job_id);
        const score = Number(result.match_score);
        const similarity = Number(result.similarity);
        const recommendation = {'Highly Recommended': 'مطابقة قوية', 'Partial Match': 'مطابقة جزئية', 'Not Recommended': 'مطابقة محدودة'}[result.recommendation] || result.recommendation;
        const company = result.job_company || 'الجهة المعلنة';
        const scoreClass = score >= 70 ? 'score-high' : score >= 40 ? 'score-mid' : 'score-low';
        return '<article class="card result-item' + (id === selectedJobId ? ' selected' : '') + '" data-job-card="' + id + '">' +
            '<div class="result-header"><div class="job-identity"><span class="company-avatar" aria-hidden="true">' + escapeHtml(company.slice(0, 1)) + '</span><div>' +
            '<h3 class="result-title" dir="auto">' + escapeHtml(result.job_title) + '</h3><p class="result-company" dir="auto">' + escapeHtml(company) + '</p></div></div>' +
            '<div class="score-badge ' + scoreClass + '"><strong dir="ltr">' + (Number.isFinite(score) ? score : '—') + '<small>%</small></strong><small>تقييم المطابقة</small></div></div>' +
            '<div class="result-meta"><span>⌖ ' + escapeHtml(result.job_location || 'الموقع غير محدد') + '</span><span class="recommendation">' + escapeHtml(recommendation) + '</span></div>' +
            '<div class="result-skills"><div class="skill-group"><span class="skill-label">نقاط القوة</span><div class="tags">' + (tags(result.strengths, 'strength') || '<span class="tag">لم تُحدد</span>') + '</div></div>' +
            '<div class="skill-group"><span class="skill-label">للتطوير</span><div class="tags">' + (tags(result.missing_skills, 'missing') || '<span class="tag">لم تُذكر مهارات ناقصة</span>') + '</div></div></div>' +
            '<div class="similarity"><span>التشابه الدلالي</span>' + (rankingDegraded || !Number.isFinite(similarity) ? '<span>غير مكتمل</span>' : '<progress max="1" value="' + Math.max(0, Math.min(1, similarity)) + '" aria-label="التشابه الدلالي"></progress><strong dir="ltr">' + similarity.toFixed(2) + ' / 1</strong>') + '</div>' +
            '<details class="job-details"><summary>تفاصيل التقييم والوظيفة</summary><h4>رأي المساعد</h4><p dir="auto">' + escapeHtml(result.ai_comment || 'لا يوجد تعليق إضافي.') + '</p><h4>وصف الوظيفة</h4><p dir="auto">' + escapeHtml(result.job_description || 'الوصف غير متاح.') + '</p></details>' +
            '<div class="job-actions"><button type="button" class="button button-soft" data-job-action="select" data-job-id="' + id + '" aria-pressed="' + (id === selectedJobId) + '">ناقش هذه الفرصة</button>' +
            '<button type="button" class="button button-quiet" data-job-action="cover_letter" data-job-id="' + id + '">كتابة خطاب تقديم</button>' +
            (safeUrl(result.job_link) ? '<a class="job-link" href="' + escapeHtml(result.job_link) + '" target="_blank" rel="noopener noreferrer">الإعلان الأصلي ↗</a>' : '') + '</div></article>';
    }).join('');
    if (selectedJobId && !results.some(r => r.job_id === selectedJobId)) selectJob(null);
    updateChatControls();
}
function tags(values, kind = '') {
    return (Array.isArray(values) ? values : []).map(value => '<span class="tag ' + kind + '" dir="auto">' + escapeHtml(value) + '</span>').join('');
}
function safeUrl(value) {
    try { return ['http:', 'https:'].includes(new URL(value).protocol); } catch { return false; }
}
function selectJob(jobId) {
    const job = resultsCache.find(r => r.job_id === jobId);
    selectedJobId = job ? jobId : null;
    show('selected-job', !!job); show('quick-questions', !!job);
    el('selected-job-title').textContent = job ? job.job_title : '';
    document.querySelectorAll('[data-job-card]').forEach(card => {
        const selected = Number(card.dataset.jobCard) === selectedJobId;
        card.classList.toggle('selected', selected);
        card.querySelector('[data-job-action="select"]').setAttribute('aria-pressed', String(selected));
    });
}
function handleChatSubmit(event) {
    event.preventDefault();
    if (sendChat(el('chat-input').value.trim(), 'auto')) el('chat-input').value = '';
}
function sendChat(message, action) {
    if (!message || !currentProfileId || chatBusy) return false;
    if (!socket?.connected || !chatReady) {
        el('chat-error').textContent = 'انتظر اتصال المساعد ثم حاول مجددًا.'; return false;
    }
    const payload = {profile_id: currentProfileId, message, action};
    if (selectedJobId) payload.job_id = selectedJobId;
    appendChatMessage('user', message, selectedJobId);
    el('chat-error').textContent = '';
    setChatBusy(true);
    socket.emit('chat_message', payload);
    return true;
}
function setChatBusy(value) {
    chatBusy = value;
    clearTimeout(chatTimer);
    show('chat-busy', value); updateChatControls();
    if (value) chatTimer = setTimeout(() => {
        setChatBusy(false);
        el('chat-error').textContent = 'الرد يستغرق وقتًا أطول من المعتاد. يمكنك إعادة الاتصال قبل المحاولة مجددًا.';
    }, 270000);
}
function updateChatControls() {
    const disabled = chatBusy || !chatReady;
    el('chat-send').disabled = disabled;
    document.querySelectorAll('[data-question], [data-job-action="cover_letter"]').forEach(button => button.disabled = disabled);
}
function welcomeChat() {
    el('chat-messages').innerHTML = '<div class="chat-welcome"><span class="welcome-mark" aria-hidden="true">✦</span><h3>لنخطّط لخطوتك القادمة</h3><p>اسألني عن نتائجك، أو اختر وظيفة لنناقشها ونحسّن سيرتك لها ونكتب خطاب تقديم مخصصًا.</p></div>';
}
function appendChatMessage(sender, text, jobId) {
    el('chat-messages').querySelector('.chat-welcome')?.remove();
    const wrapper = document.createElement('div');
    wrapper.className = 'chat-message ' + (sender === 'user' ? 'user' : 'agent');
    const author = document.createElement('span'); author.className = 'message-author';
    author.textContent = sender === 'user' ? 'أنت' : 'مساعد فرصتك'; wrapper.append(author);
    const job = resultsCache.find(r => r.job_id === jobId);
    if (job) {
        const context = document.createElement('div'); context.className = 'message-job';
        context.textContent = job.job_title; wrapper.append(context);
    }
    const bubble = document.createElement('div'); bubble.className = 'chat-bubble';
    bubble.dir = 'auto'; bubble.textContent = text || ''; wrapper.append(bubble);
    el('chat-messages').append(wrapper);
    el('chat-messages').scrollTop = el('chat-messages').scrollHeight;
}
function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}
