/**
 * Quiz Immersif — Coach IA dynamique
 * Claude mène l'entretien. Questions simples, adaptées, naturelles.
 * TTS, waveform, VAD, transcript preview, text fallback.
 */
(function () {
    'use strict';

    const state = {
        quizId: 'pack_clarte',
        conversation: [],   // {role:'coach'|'user', text}
        audioBlobs: {},      // turn index → Blob
        turnIndex: 0,
        isRecording: false,
        isProcessing: false,
        micGranted: false,
        mediaRecorder: null,
        audioStream: null,
        audioChunks: [],
        recordingStartTime: null,
        recordingTimer: null,
        leadCaptured: false,
        waveformRAF: null,
        vadAnalyser: null,
        vadContext: null,
        vadInterval: null
    };

    const COACH_IMG = 'https://images.tilto.co/production/2025/10/d8564b8b_tilto_home_video_poster.webp';
    const FIRST_QUESTION = 'Qu\'est-ce qui t\'amène aujourd\'hui ?';
    const MAX_RECORDING_TIME = 120; // 2 min max per answer

    const WHISPER_HALLUCINATIONS = [
        'merci d\'avoir regardé', 'sous-titres réalisés', 'sous-titres par',
        'merci d\'avoir écouté', 'merci de votre attention', 'abonnez-vous',
        'n\'oubliez pas de', 'à bientôt', 'music', '♪', 'thank you for watching', 'subscribe'
    ];

    let els = {};

    // ── Helpers ──
    function isSafari() { return /Safari/.test(navigator.userAgent) && !/Chrome/.test(navigator.userAgent) && !/Edge/.test(navigator.userAgent); }
    function fmtTime(s) { return `${Math.floor(s/60)}:${(s%60).toString().padStart(2,'0')}`; }
    function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
    function isHallucination(t) { if (!t || t.trim().length < 5) return true; const l = t.toLowerCase(); return WHISPER_HALLUCINATIONS.some(h => l.includes(h)); }

    // ── Transitions ──
    function fadeOut() { return new Promise(r => { els.stage.classList.add('fade-out'); setTimeout(r, 380); }); }
    function fadeIn() {
        els.stage.classList.remove('fade-out');
        els.stage.classList.add('fade-in');
        requestAnimationFrame(() => requestAnimationFrame(() => {
            els.stage.classList.remove('fade-in');
            els.stage.classList.add('fade-visible');
        }));
    }
    function hideAll() {
        ['micZone','recZone','processing','feedback','leadForm','avatar','waveformCanvas','nudges'].forEach(k => {
            if (els[k]) els[k].style.display = 'none';
        });
    }

    // ── Show text as subtitle (smooth fade) ──
    function showSubtitle(el, text) {
        // Fade out current text
        el.classList.remove('imm-subtitle-visible');
        return new Promise(resolve => {
            // Wait for fade out (300ms), then swap text and fade in
            setTimeout(() => {
                el.textContent = text;
                el.style.display = 'block';
                // Force reflow then fade in
                void el.offsetWidth;
                el.classList.add('imm-subtitle-visible');
                resolve();
            }, el.textContent ? 350 : 100); // faster if empty (first time)
        });
    }


    // ── Pause helper ──
    function pause(ms) { return new Promise(r => setTimeout(r, ms)); }

    // ── Progress bar ──
    function updateProgress() {
        if (!els.progressFill) return;
        const maxTurns = 5;
        const pct = Math.min((state.turnIndex / maxTurns) * 100, 95);
        els.progressFill.style.width = pct + '%';
    }

    // ── Waveform ──
    function startWaveform() {
        if (!state.vadAnalyser || !els.waveformCanvas) return;
        els.waveformCanvas.style.display = 'block';
        const canvas = els.waveformCanvas, ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const W = 220, H = 60;
        canvas.width = W * dpr; canvas.height = H * dpr;
        canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
        ctx.scale(dpr, dpr);
        state.vadAnalyser.fftSize = 256;
        const bufLen = state.vadAnalyser.frequencyBinCount;
        const freqData = new Uint8Array(bufLen);
        const bars = 28, barW = 3, totalW = bars * barW + (bars - 1) * 3, offsetX = (W - totalW) / 2;

        function draw() {
            if (!state.isRecording) { ctx.clearRect(0, 0, W, H); return; }
            state.waveformRAF = requestAnimationFrame(draw);
            state.vadAnalyser.getByteFrequencyData(freqData);
            ctx.clearRect(0, 0, W, H);
            for (let i = 0; i < bars; i++) {
                const idx = Math.floor((i / bars) * (bufLen * 0.6));
                const v = freqData[idx] / 255;
                const h = Math.max(3, v * (H - 4));
                const x = offsetX + i * (barW + 3), y = (H - h) / 2, r = barW / 2;
                ctx.fillStyle = '#A11857'; ctx.globalAlpha = 0.3 + v * 0.7;
                ctx.beginPath();
                ctx.moveTo(x+r,y); ctx.lineTo(x+barW-r,y); ctx.quadraticCurveTo(x+barW,y,x+barW,y+r);
                ctx.lineTo(x+barW,y+h-r); ctx.quadraticCurveTo(x+barW,y+h,x+barW-r,y+h);
                ctx.lineTo(x+r,y+h); ctx.quadraticCurveTo(x,y+h,x,y+h-r);
                ctx.lineTo(x,y+r); ctx.quadraticCurveTo(x,y,x+r,y);
                ctx.fill();
            }
            ctx.globalAlpha = 1;
        }
        draw();
    }
    function stopWaveform() {
        if (state.waveformRAF) { cancelAnimationFrame(state.waveformRAF); state.waveformRAF = null; }
        if (els.waveformCanvas) els.waveformCanvas.style.display = 'none';
    }


    // ── Show coach question (single smooth transition) ──
    async function showCoachQuestion(questionText, insight) {
        if (els.stage.classList.contains('fade-visible')) await fadeOut();
        hideAll();

        // Avatar always visible
        els.avatar.style.display = 'block';
        els.question.classList.remove('imm-subtitle-visible');

        if (insight) {
            els.feedback.style.display = 'flex';
            const isIntro = insight.includes('café');
            els.feedback.innerHTML = isIntro
                ? `<p class="imm-intro-text">${esc(insight)}</p>`
                : `<div class="imm-insight-inline">
                    <span class="imm-insight-badge">✓ Noté</span>
                    <p class="imm-insight-text">${esc(insight)}</p>
                </div>`;
            fadeIn();
            await pause(isIntro ? 2500 : 3000);
            await fadeOut();
            hideAll();
            els.avatar.style.display = 'block';
        }

        // Show question — let user read it first
        showSubtitle(els.question, questionText);
        fadeIn();

        const last = state.conversation[state.conversation.length - 1];
        if (!(last && last.role === 'coach' && last.text === questionText)) {
            state.conversation.push({ role: 'coach', text: questionText });
        }
        saveState();

        // Wait for user to read, then show mic
        await pause(1500);
        els.micZone.style.display = 'flex';
        els.micHint.textContent = 'Appuie pour répondre';
        els.micHint.style.color = '';
    }

    // ── Conversation end → save and redirect to dashboard ──
    async function showConversationEnd(insight, summary) {
        // Save full conversation in background
        try {
            const fd = new FormData();
            fd.append('quiz_id', state.quizId);
            fd.append('quiz_answers', JSON.stringify(formatAnswers()));
            fd.append('update_only', 'true');
            Object.entries(state.audioBlobs).forEach(([idx, blob]) => {
                fd.append(`audio_qturn_${idx}`, blob, `turn_${idx}.${isSafari()?'mp4':'webm'}`);
            });
            fetch('/lead/capture', { method:'POST', body:fd, headers:{'X-Requested-With':'XMLHttpRequest'} });
        } catch(e) {}

        // Closing message
        await fadeOut();
        hideAll();
        if (els.progressFill) els.progressFill.style.width = '100%';
        els.avatar.style.display = 'block';
        els.feedback.style.display = 'flex';
        els.feedback.innerHTML = `
            <div class="imm-insight-inline">
                <p class="imm-insight-text">${esc(summary || insight || 'Super échange ! Je te prépare ton bilan.')}</p>
            </div>`;
        fadeIn();
        await pause(2500);

        // Redirect to dashboard (analysis is generating in background)
        clearSaved();
        await fadeOut();
        hideAll();
        els.feedback.style.display = 'flex';
        els.feedback.innerHTML = `
            <div class="imm-success">
                <div class="imm-success-check">✓</div>
                <p class="imm-success-title">Ton bilan est en préparation</p>
                <p class="imm-success-sub">Tu vas le recevoir dans quelques minutes</p>
            </div>`;
        fadeIn();
        setTimeout(() => { window.location.href = '/dashboard'; }, 2500);
    }


    // ── Recording ──
    async function startRecording() {
        if (state.isRecording || state.isProcessing) return;
        // (TTS removed)
        try {
            state.audioStream = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: !isSafari(), noiseSuppression: !isSafari(), autoGainControl: !isSafari() }
            });
            state.audioChunks = [];
            let mime = 'audio/webm;codecs=opus';
            if (isSafari() && !MediaRecorder.isTypeSupported(mime))
                mime = ['audio/mp4','audio/webm','audio/wav'].find(t => MediaRecorder.isTypeSupported(t)) || '';
            const opts = { audioBitsPerSecond: 128000 };
            if (mime) opts.mimeType = mime;

            state.mediaRecorder = new MediaRecorder(state.audioStream, opts);
            state.mediaRecorder.addEventListener('dataavailable', e => { if (e.data.size > 0) state.audioChunks.push(e.data); });
            state.mediaRecorder.addEventListener('stop', onRecordingStop);
            state.mediaRecorder.start(isSafari() ? 3000 : 1000);

            state.isRecording = true;
            state.micGranted = true;
            state.recordingStartTime = Date.now();
            if (navigator.vibrate) navigator.vibrate(50);

            els.micBtn?.classList.remove('imm-mic--invite');
            els.micZone.style.display = 'none';
            els.textFallback.style.display = 'none';
            els.recZone.style.display = 'flex';
            els.recHint.textContent = 'Appuie pour terminer';
            startTimer();
            // Start analyser for waveform visual only
            startVAD();
            startWaveform();
        } catch (err) { console.error('[Imm] Mic error:', err); }
    }

    function startVAD() {
        // Setup audio analyser for waveform visual only — user controls start/stop manually
        try {
            state.vadContext = new (window.AudioContext || window.webkitAudioContext)();
            if (state.vadContext.state === 'suspended') state.vadContext.resume();
            const source = state.vadContext.createMediaStreamSource(state.audioStream);
            state.vadAnalyser = state.vadContext.createAnalyser();
            state.vadAnalyser.fftSize = 512;
            source.connect(state.vadAnalyser);
        } catch (e) { console.warn('[Imm] Analyser fail:', e); }
    }

    function stopVAD() {
        if (state.vadInterval) { clearInterval(state.vadInterval); state.vadInterval = null; }
        if (state.vadContext) { try { state.vadContext.close(); } catch(e){} state.vadContext = null; }
        state.vadAnalyser = null;
    }

    function stopRecording() {
        if (!state.mediaRecorder || !state.isRecording) return;
        if (navigator.vibrate) navigator.vibrate([30, 50, 30]);
        try { if (state.mediaRecorder.state === 'recording') state.mediaRecorder.stop(); } catch(e){}
        state.isRecording = false;
        if (state.recordingTimer) { clearInterval(state.recordingTimer); state.recordingTimer = null; }
        stopVAD(); stopWaveform();
        if (state.audioStream) { state.audioStream.getTracks().forEach(t => t.stop()); state.audioStream = null; }
    }

    async function onRecordingStop() {
        const mime = isSafari() ? 'audio/mp4' : 'audio/webm';
        const blob = new Blob(state.audioChunks, { type: mime });
        const dur = Math.floor((Date.now() - state.recordingStartTime) / 1000);

        els.recZone.style.display = 'none';

        if (dur < 1) {
            // Less than 1 second — accidental tap, let them retry
            els.micZone.style.display = 'flex';
                return;
        }

        state.audioBlobs[state.turnIndex] = blob;
        showProcessing("");

        try {
            const text = await transcribe(blob);
            if (isHallucination(text)) { showRetry(); return; }
            updateProcessingText("");
            await onTranscriptReady(text);
        } catch (e) { showRetry(); }
    }

    async function transcribe(blob) {
        const fd = new FormData();
        fd.append('audio', blob, `rec.${isSafari()?'mp4':'webm'}`);
        const res = await fetch('/api/transcribe-whisper', { method:'POST', body:fd });
        const d = await res.json();
        if (d.success && d.transcript) return d.transcript;
        throw new Error('fail');
    }

    function startTimer() {
        const el = els.recTimer;
        if (el) el.textContent = '0:00';
        let lastNudge = -1;
        const nudges = state.currentNudges || [];
        // Nudges appear at 8s, 18s, 30s
        const nudgeTimes = [8, 18, 30];

        if (els.nudges) { els.nudges.innerHTML = ''; els.nudges.style.display = 'flex'; }

        state.recordingTimer = setInterval(() => {
            const s = Math.floor((Date.now() - state.recordingStartTime) / 1000);
            if (el) el.textContent = fmtTime(s);

            // Progressive contextual nudges from Claude
            if (els.nudges && !els.recHint.classList.contains('imm-rec-hint--ending')) {
                for (let i = 0; i < nudges.length && i < nudgeTimes.length; i++) {
                    if (s >= nudgeTimes[i] && i > lastNudge) {
                        const tag = document.createElement('span');
                        tag.className = 'imm-nudge';
                        tag.textContent = '💡 ' + nudges[i];
                        els.nudges.appendChild(tag);
                        lastNudge = i;
                    }
                }
            }

            // Hint evolution
            if (s >= 50 && !els.recHint.classList.contains('imm-rec-hint--ending')) {
                els.recHint.textContent = 'Tu peux conclure quand tu veux';
            } else if (s >= 20 && !els.recHint.classList.contains('imm-rec-hint--ending')) {
                els.recHint.textContent = 'C\'est bien, continue';
            }

            if (s >= MAX_RECORDING_TIME) stopRecording();
        }, 1000);
    }

    // ── Transcript done → send directly to coach ──
    async function onTranscriptReady(text) {
        await onUserAnswer(text);
    }

    // ── Retry ──
    function showRetry() {
        hideAll();
        els.avatar.style.display = 'block';
        els.question.style.display = 'block';
        els.feedback.style.display = 'flex';
        els.feedback.innerHTML = `
            <div class="imm-retry-card">
                <p class="imm-retry-text">Je n'ai pas bien compris, tu peux réessayer ?</p>
                <div class="imm-retry-actions">
                    <button type="button" class="imm-retry-btn" id="immRetryBtn">🎙️ Réessayer</button>
                    <button type="button" class="imm-retry-skip" id="immRetrySkip">Passer →</button>
                </div>
            </div>`;
        document.getElementById('immRetryBtn')?.addEventListener('click', () => {
            els.feedback.style.display = 'none';
            els.micZone.style.display = 'flex';
                startRecording();
        });
        document.getElementById('immRetrySkip')?.addEventListener('click', () => {
            onUserAnswer('(pas de réponse)');
        });
    }

    function showProcessing(text) {
        hideAll();
        els.avatar.style.display = 'block';
        els.processing.style.display = 'flex';
        els.processingText.textContent = text;
    }

    // Transition processing text as steps progress
    function updateProcessingText(text) {
        if (els.processingText) els.processingText.textContent = text;
    }

    // ── Core loop: user answered → ask Claude for next step ──
    const LEAD_AFTER_TURNS = 3; // Ask for lead info after 3 user answers

    async function onUserAnswer(text) {
        state.conversation.push({ role: 'user', text });
        state.turnIndex++;
        updateProgress();
        saveState();

        // After 2 answers → capture lead before continuing
        if (state.turnIndex === LEAD_AFTER_TURNS && !state.leadCaptured) {
            await showMidConversationLead();
            return;
        }

        await fetchNextCoachStep();
    }

    async function fetchNextCoachStep() {
        state.isProcessing = true;
        if (!els.processing || els.processing.style.display === 'none') {
            showProcessing("");
        }

        try {
            const res = await fetch('/coach-next', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conversation: state.conversation, quiz_id: state.quizId })
            });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const result = await res.json();

            if (result.done) {
                showConversationEnd(result.insight, result.summary);
            } else {
                state.currentNudges = result.nudges || [];
                showCoachQuestion(result.question, result.insight);
            }
        } catch (err) {
            console.error('[Imm] Coach error:', err);
            showConversationEnd(null, 'Merci pour cet échange !');
        } finally {
            state.isProcessing = false;
        }
    }

    // ── Mid-conversation lead capture ──
    async function showMidConversationLead() {
        await fadeOut();
        hideAll();

        // Show minimal lead form — just name + email
        els.question.style.display = 'none';
        els.leadForm.style.display = 'block';

        // Replace the form content with minimal version
        els.leadForm.innerHTML = `
            <div class="imm-lead-minimal">
                <div class="imm-lead-minimal__header">
                    <img src="${COACH_IMG}" alt="Claire" class="imm-lead-minimal__avi">
                    <p class="imm-lead-minimal__msg">Crée ton compte pour que je puisse t'envoyer tes résultats après notre échange</p>
                </div>
                <input type="text" id="immFirstname" class="imm-input" placeholder="Ton prénom" autocomplete="given-name">
                <input type="email" id="immEmail" class="imm-input" placeholder="Ton email" autocomplete="email">
                <button type="button" id="immLeadSubmit" class="imm-submit">Continuer</button>
                <p class="imm-note">Gratuit · confidentiel</p>
            </div>`;

        fadeIn();
    }

    async function submitLead() {
        const fn = document.getElementById('immFirstname')?.value.trim();
        const em = document.getElementById('immEmail')?.value.trim();
        const btn = document.getElementById('immLeadSubmit');
        if (!fn || !em) return;
        if (btn) { btn.disabled = true; btn.textContent = 'Un instant...'; }

        state.firstname = fn;

        const fd = new FormData();
        fd.append('firstname', fn);
        fd.append('email', em);
        fd.append('newsletter_consent', 'yes');
        fd.append('partner_consent', 'no');
        fd.append('lead_source', 'quiz_immersive');
        fd.append('quiz_id', state.quizId);
        fd.append('quiz_answers', JSON.stringify(formatAnswers()));
        Object.entries(state.audioBlobs).forEach(([idx, blob]) => {
            fd.append(`audio_qturn_${idx}`, blob, `turn_${idx}.${isSafari()?'mp4':'webm'}`);
        });

        try {
            const res = await fetch('/lead/capture', { method:'POST', body:fd, headers:{'X-Requested-With':'XMLHttpRequest'} });
            const data = await res.json();
            if (data.success) {
                state.leadCaptured = true;
                saveState();

                if (state.turnIndex < 7) {
                    // Mid-conversation → Claire uses the name and continues
                    els.leadForm.style.display = 'none';
                    const continueMsg = `Merci ${fn} ! On continue.`;
                    els.avatar.style.display = 'block';
            
                    showSubtitle(els.question, continueMsg);
                    await new Promise(r => setTimeout(r, 1500));
                                await fetchNextCoachStep();
                } else {
                    // End of conversation → redirect
                    clearSaved();
                    els.leadForm.innerHTML = `
                        <div class="imm-success">
                            <div class="imm-success-check">✓</div>
                            <p class="imm-success-title">C'est parti !</p>
                            <p class="imm-success-sub">Ton diagnostic arrive dans quelques minutes...</p>
                        </div>`;
                    setTimeout(() => { window.location.href = '/dashboard'; }, 2000);
                }
            } else {
                if (btn) { btn.disabled = false; btn.textContent = state.leadCaptured ? 'Recevoir mes pistes' : 'Continuer l\'entretien'; }
                if (data.error_type === 'email_exists') {
                    // Email exists — treat as "already captured" and continue
                    state.leadCaptured = true;
                    els.leadForm.style.display = 'none';
                    await fetchNextCoachStep();
                }
            }
        } catch (err) {
            if (btn) { btn.disabled = false; btn.textContent = 'Continuer l\'entretien'; }
        }
    }

    // ── Lead form — format conversation for backend ──
    function formatAnswers() {
        // Build full transcript
        const transcript = state.conversation.map(m =>
            m.role === 'coach' ? `[Claire] ${m.text}` : `[Réponse] ${m.text}`
        ).join('\n');

        // Also format per-turn for compatibility with answer_user table
        // Each user response maps to a "virtual question"
        const answers = {};
        let turnIdx = 0;
        for (let i = 0; i < state.conversation.length; i++) {
            const msg = state.conversation[i];
            if (msg.role === 'user') {
                // Find the coach question before this answer
                let coachQuestion = '';
                for (let j = i - 1; j >= 0; j--) {
                    if (state.conversation[j].role === 'coach') {
                        coachQuestion = state.conversation[j].text;
                        break;
                    }
                }
                answers[`turn_${turnIdx}`] = {
                    value: [msg.text],
                    text: `[Question] ${coachQuestion}\n[Réponse] ${msg.text}`
                };
                turnIdx++;
            }
        }

        // Add full transcript as special key
        answers['_conversation'] = {
            value: [transcript],
            text: transcript
        };

        return answers;
    }

    // ── Persistence ──
    const STORAGE_KEY = 'tilto_coach';
    const STORAGE_TTL = 30 * 60 * 1000; // 30 min

    function saveState() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                conversation: state.conversation,
                turnIndex: state.turnIndex,
                nudges: state.currentNudges,
                leadCaptured: state.leadCaptured,
                ts: Date.now()
            }));
        } catch (e) {}
    }

    function loadSaved() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return null;
            const d = JSON.parse(raw);
            if (Date.now() - d.ts > STORAGE_TTL) { localStorage.removeItem(STORAGE_KEY); return null; }
            return d;
        } catch (e) { return null; }
    }

    function clearSaved() {
        localStorage.removeItem(STORAGE_KEY);
        state.conversation = [];
        state.turnIndex = 0;
    }

    // ── Init ──
    function open() {
        els.screen.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        startFlow();
    }
    function close() {
        els.screen.style.display = 'none';
        document.body.style.overflow = '';
        if (state.isRecording) stopRecording();
        // (TTS removed)
    }

    async function startFlow() {
        try {
            const saved = loadSaved();

            if (saved && saved.conversation && saved.conversation.length >= 2) {
                // Resume conversation
                state.conversation = saved.conversation;
                state.turnIndex = saved.turnIndex || 0;
                state.currentNudges = saved.nudges || [];
                state.leadCaptured = saved.leadCaptured || false;
                state.micGranted = true;

                hideAll();
                els.avatar.style.display = 'block';
        
                showSubtitle(els.question, 'On reprend où on en était...');
                fadeIn();
                await pause(1500);
        
                // Ask Claude for next step based on history
                state.isProcessing = true;
                try {
                    const res = await fetch('/coach-next', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ conversation: state.conversation, quiz_id: state.quizId })
                    });
                    const result = await res.json();
                    state.isProcessing = false;

                    if (result.done) {
                        showCompletion(result.insight, result.summary);
                    } else {
                        state.currentNudges = result.nudges || [];
                                showCoachQuestion(result.question, result.insight);
                    }
                } catch (e) {
                    state.isProcessing = false;
                    clearSaved();
                    await freshStart();
                }
            } else {
                clearSaved();
                await freshStart();
            }
        } catch (err) {
            console.error('[Imm] Start error:', err);
            clearSaved();
        }
    }

    async function freshStart() {
        state.currentNudges = ['Ta situation actuelle', 'Ce qui te tracasse', 'Ce que tu cherches'];
        // First question with a warm intro as insight
        showCoachQuestion(FIRST_QUESTION, 'Parle comme si on prenait un café ☕');
    }

    function init() {
        els = {
            screen: document.getElementById('quizImmersive'),
            stage: document.getElementById('immContent'),
            progressFill: document.getElementById('immProgressFill'),
            avatar: document.getElementById('immAvatar'),
            question: document.getElementById('immQuestion'),
            feedback: document.getElementById('immFeedback'),
            transcript: document.getElementById('immTranscript'),
            micZone: document.getElementById('immMicZone'),
            micBtn: document.getElementById('immMicBtn'),
            micHint: document.getElementById('immMicHint'),
            textarea: document.getElementById('immTextarea'),
            sendBtn: document.getElementById('immSendBtn'),
            recZone: document.getElementById('immRecZone'),
            recOrb: document.getElementById('immRecOrb'),
            recStatus: document.getElementById('immRecStatus'),
            recTimer: document.getElementById('immRecTimer'),
            recHint: document.getElementById('immRecHint'),
            nudges: document.getElementById('immNudges'),
            waveformCanvas: document.getElementById('immWaveform'),
            processing: document.getElementById('immProcessing'),
            processingText: document.getElementById('immProcessingText'),
            leadForm: document.getElementById('immLeadForm'),
            closeBtn: document.getElementById('immClose')
        };

        if (!els.screen) return;

        els.micBtn?.addEventListener('click', startRecording);
        document.getElementById('immStopBtn')?.addEventListener('click', stopRecording);
        els.closeBtn?.addEventListener('click', close);
        document.addEventListener('click', e => { if (e.target.id === 'immLeadSubmit') submitLead(); });

        document.getElementById('immStartBtn')?.addEventListener('click', open);
    }

    window.QuizChat = { init, open, close };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => { if (window.QUIZ_CHAT_MODE) init(); });
    } else { if (window.QUIZ_CHAT_MODE) init(); }
})();
