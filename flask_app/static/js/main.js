// Frontend behavior for the AI Opportunity Agent.
let socket = null;
let currentProfileId = null;

document.addEventListener('DOMContentLoaded', () => {
    const fileInput = document.getElementById('cv-file');
    const fileName = document.getElementById('file-name');
    if (fileInput) {
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) fileName.textContent = fileInput.files[0].name;
        });
    }
    const uploadForm = document.getElementById('upload-form');
    if (uploadForm) uploadForm.addEventListener('submit', handleUpload);
    const chatForm = document.getElementById('chat-form');
    if (chatForm) chatForm.addEventListener('submit', handleChatSubmit);
    if (typeof PROFILE_ID !== "undefined" && PROFILE_ID) {
        currentProfileId = PROFILE_ID;
        showResultsView();
    }
});

async function handleUpload(e) {
    e.preventDefault();
    const fileInput = document.getElementById("cv-file");
    const uploadBtn = document.getElementById("upload-btn");
    const errorDiv = document.getElementById("upload-error");
    if (!fileInput.files.length) { errorDiv.textContent = "يرجى اختيار ملف PDF"; return; }
    const formData = new FormData();
    formData.append("file", fileInput.files[0]);
    uploadBtn.disabled = true;
    uploadBtn.textContent = "جاري الرفع...";
    errorDiv.textContent = "";
    try {
        const resp = await fetch("/upload", {method:"POST", body:formData});
        const data = await resp.json();
        if (data.success) {
            currentProfileId = data.profile_id;
            showProgressView();
            initSocket(data.profile_id);
        } else {
            errorDiv.textContent = data.error || "حدث خطأ أثناء الرفع";
        }
    } catch(err) {
        errorDiv.textContent = "خطأ في الاتصال بالخادم";
        console.error(err);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.textContent = "رفع وتحليل";
    }
}

function showProgressView() {
    document.getElementById("upload-section").classList.add("hidden");
    document.getElementById("progress-section").classList.remove("hidden");
    document.getElementById("results-section").classList.add("hidden");
    resetProgressSteps();
}

function showResultsView() {
    document.getElementById("upload-section").classList.add("hidden");
    document.getElementById("progress-section").classList.add("hidden");
    document.getElementById("results-section").classList.remove("hidden");
    initSocket(currentProfileId);
    loadResults(currentProfileId);
}

async function loadResults(profileId) {
    try {
        const resp = await fetch("/api/results/" + profileId);
        const data = await resp.json();
        if (data.profile) {
            const p = data.profile;
            const skills = Array.isArray(p.skills) ? p.skills.join("، ") : "";
            document.getElementById("profile-content").innerHTML =
                "<p><strong>الاسم:</strong> " + (p.name || "غير محدد") + "</p>" +
                "<p><strong>البريد:</strong> " + (p.email || "غير محدد") + "</p>" +
                "<p><strong>المجال:</strong> " + (p.field || "غير محدد") + " — " + (p.level || "") + "</p>" +
                (skills ? "<p><strong>المهارات:</strong> " + skills + "</p>" : "") +
                (p.summary ? "<p>" + p.summary + "</p>" : "");
        }
        if (data.results && data.results.length > 0) {
            renderResults(data.results);
        } else if (!data.is_analyzed) {
            document.getElementById("results-list").innerHTML = "<p>جاري التحليل، يرجى الانتظار...</p>";
        } else {
            document.getElementById("results-list").innerHTML = "<p>لا توجد نتائج بعد.</p>";
        }
    } catch (err) {
        console.error("Error loading results:", err);
        document.getElementById("results-list").innerHTML = "<p>خطأ في تحميل النتائج.</p>";
    }
}

function handleProgress(data) {
    const stage = data.stage;
    const message = data.message;
    const progressSection = document.getElementById("progress-section");
    progressSection.classList.remove("hidden");
    document.getElementById("progress-message").textContent = message;
    document.querySelectorAll(".step").forEach(s => {
        if (s.dataset.step === stage) {
            s.classList.add("active");
            s.querySelector(".step-status").textContent = "⏳";
        }
    });
    if (stage === "complete") {
        document.querySelectorAll(".step").forEach(s => {
            s.classList.remove("active");
            s.classList.add("done");
            s.querySelector(".step-status").textContent = "✓";
        });
        document.getElementById("results-section").classList.remove("hidden");
        if (currentProfileId) loadResults(currentProfileId);
    } else if (stage === "error") {
        const activeStep = document.querySelector(".step.active");
        if (activeStep) {
            activeStep.classList.remove("active");
            activeStep.classList.add("error");
            activeStep.querySelector(".step-status").textContent = "✗";
        }
    }
}

function resetProgressSteps() {
    document.querySelectorAll(".step").forEach(s => {
        s.classList.remove("active","done","error");
        s.querySelector(".step-status").textContent = "";
    });
    document.getElementById("progress-message").textContent = "";
}

function initSocket(profileId) {
    if (socket) socket.disconnect();
    socket = io();
    socket.on("connect", () => {
        socket.emit("join", {profile_id: profileId});
        socket.emit("request_chat_history", {profile_id: profileId});
    });
    socket.on("analysis_progress", handleProgress);
    socket.on("chat_response", handleChatResponse);
    socket.on("chat_history", handleChatHistory);
}

function renderResults(results) {
    const c = document.getElementById("results-list");
    let html = "";
    results.forEach(r => {
        const sc = r.match_score >= 70 ? "score-high" : r.match_score >= 40 ? "score-mid" : "score-low";
        html += '<div class="result-item">';
        html += '<div class="result-header"><div><div class="result-title">' + (r.job_title||"") + '</div>';
        html += '<div class="result-company">' + (r.job_company||"") + '</div></div>';
        html += '<div class="score-badge ' + sc + '">' + r.match_score + '%</div></div>';
        html += '<div class="result-meta"><span>📍 ' + (r.job_location||"غير محدد") + '</span>';
        html += '<span>🏷️ ' + (r.recommendation||"") + '</span></div>';
        if (r.ai_comment) html += '<div class="result-skills">' + r.ai_comment + '</div>';
        if (r.strengths && r.strengths.length > 0) {
            html += '<div class="result-skills"><strong>نقاط القوة:</strong> ';
            r.strengths.forEach(s => html += '<span class="skill-tag">' + s + '</span>');
            html += '</div>';
        }
        if (r.missing_skills && r.missing_skills.length > 0) {
            html += '<div class="result-missing"><strong>مهارات ناقصة:</strong> ';
            r.missing_skills.forEach(s => html += '<span class="missing-tag">' + s + '</span>');
            html += '</div>';
        }
        if (r.job_link) html += '<div class="result-meta"><a href="' + r.job_link + '" target="_blank">🔗 رابط الوظيفة</a></div>';
        html += '</div>';
    });
    c.innerHTML = html;
}

function handleChatSubmit(e) {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message || !currentProfileId) return;
    appendChatMessage("user", message);
    input.value = "";
    if (socket) socket.emit("chat_message", {profile_id: currentProfileId, message: message});
}

function appendChatMessage(sender, text) {
    const c = document.getElementById("chat-messages");
    const d = document.createElement("div");
    d.className = "chat-message " + sender;
    d.innerHTML = '<div class="chat-bubble">' + escapeHtml(text) + '</div>';
    c.appendChild(d);
    c.scrollTop = c.scrollHeight;
}

function handleChatResponse(data) { appendChatMessage("agent", data.message); }

function handleChatHistory(data) {
    const c = document.getElementById("chat-messages");
    c.innerHTML = "";
    if (data.messages) data.messages.forEach(m => appendChatMessage(m.sender, m.message));
}

function escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML;
}
