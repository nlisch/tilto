// ============================================================
// ASYNC ANALYSIS - Génération en arrière-plan
// ============================================================

// Récupérer le CSRF token
function getAsyncCsrfToken() {
    if (typeof csrfToken !== 'undefined') return csrfToken;
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) return meta.content;
    return '';
}

let currentAsyncJob = null;
let asyncPollingInterval = null;
const ASYNC_POLL_INTERVAL = 5000;

// Lancer génération async
async function generateAnalysisAsync(userId, quizId, stepId) {
    const systemPrompt = document.querySelector('.initial-system-prompt')?.value || '';
    const humanPrompt = document.querySelector('.initial-human-prompt')?.value || '';
    const validationCriteria = document.querySelector('.initial-validation-criteria')?.value || '';
    
    showAsyncLoadingOverlay();
    
    try {
        const response = await fetch('/analysis/async/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getAsyncCsrfToken()
            },
            body: JSON.stringify({
                user_id: userId,
                quiz_id: quizId,
                step_id: stepId,
                system_prompt: systemPrompt,
                human_prompt: humanPrompt,
                validation_criteria: validationCriteria
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            currentAsyncJob = { job_uuid: data.job_uuid, status: 'pending' };
            updateAsyncJobUI('pending');
            startAsyncPolling(data.job_uuid);
            if (typeof showFlashMessage === 'function') {
                showFlashMessage('success', 'Job créé ! Génération en cours en arrière-plan...');
            }
        } else {
            hideAsyncLoadingOverlay();
            if (typeof showFlashMessage === 'function') {
                showFlashMessage('error', data.error || 'Erreur création job');
            }
        }
    } catch (error) {
        hideAsyncLoadingOverlay();
        if (typeof showFlashMessage === 'function') {
            showFlashMessage('error', 'Erreur: ' + error.message);
        }
    }
}

function startAsyncPolling(jobUuid) {
    stopAsyncPolling();
    pollAsyncJobStatus(jobUuid);
    asyncPollingInterval = setInterval(function() { pollAsyncJobStatus(jobUuid); }, ASYNC_POLL_INTERVAL);
}

function stopAsyncPolling() {
    if (asyncPollingInterval) {
        clearInterval(asyncPollingInterval);
        asyncPollingInterval = null;
    }
}

async function pollAsyncJobStatus(jobUuid) {
    try {
        const response = await fetch('/analysis/async/status/' + jobUuid);
        const data = await response.json();
        
        updateAsyncJobUI(data.status, data);
        
        if (['completed', 'error', 'cancelled'].indexOf(data.status) !== -1) {
            stopAsyncPolling();
            
            if (data.status === 'completed') {
                if (typeof showFlashMessage === 'function') {
                    showFlashMessage('success', 'Analyse générée en ' + (data.duration_seconds?.toFixed(1) || '?') + 's !');
                }
                setTimeout(function() { window.location.reload(); }, 2000);
            } else if (data.status === 'error') {
                if (typeof showFlashMessage === 'function') {
                    showFlashMessage('error', 'Erreur: ' + data.error);
                }
            }
        }
    } catch (error) {
        console.error('Erreur polling:', error);
    }
}

function showAsyncLoadingOverlay() {
    let overlay = document.getElementById('async-loading-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = 'async-loading-overlay';
        overlay.innerHTML = 
            '<div class="async-overlay-backdrop"></div>' +
            '<div class="async-overlay-content">' +
                '<button type="button" class="async-close-btn" data-action="close-async-overlay" title="Fermer (le job continue en arrière-plan)">' +
                    '<i class="fas fa-times"></i>' +
                '</button>' +
                '<div class="async-spinner-container">' +
                    '<div class="async-spinner"></div>' +
                    '<div class="async-spinner-icon">⚡</div>' +
                '</div>' +
                '<h3 id="async-status-title" class="async-title">Création du job...</h3>' +
                '<p id="async-status-message" class="async-message">Le job est en cours de création.</p>' +
                '<div id="async-progress-container" class="async-progress-container">' +
                    '<div class="async-progress-bar">' +
                        '<div id="async-progress-fill" class="async-progress-fill"></div>' +
                    '</div>' +
                    '<p id="async-elapsed-time" class="async-elapsed-time"></p>' +
                '</div>' +
                '<div class="async-info-box">' +
                    '<i class="fas fa-info-circle"></i>' +
                    '<span>Vous pouvez fermer cette fenêtre, l\'analyse sera générée en arrière-plan.</span>' +
                '</div>' +
                '<div class="async-actions">' +
                    '<button type="button" id="async-cancel-btn" class="async-btn async-btn-cancel" data-action="cancel-async-job">' +
                        '<i class="fas fa-stop-circle"></i> Annuler le job' +
                    '</button>' +
                    '<button type="button" class="async-btn async-btn-close" data-action="close-async-overlay">' +
                        '<i class="fas fa-eye-slash"></i> Masquer' +
                    '</button>' +
                '</div>' +
            '</div>';
        
        // Ajouter les styles
        const style = document.createElement('style');
        style.textContent = `
            #async-loading-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                z-index: 99999;
                display: none;
                align-items: center;
                justify-content: center;
            }
            
            #async-loading-overlay.active {
                display: flex;
            }
            
            .async-overlay-backdrop {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.85);
                backdrop-filter: blur(8px);
            }
            
            .async-overlay-content {
                position: relative;
                background: white;
                padding: 3rem;
                border-radius: 20px;
                box-shadow: 0 25px 80px rgba(0, 0, 0, 0.4);
                text-align: center;
                max-width: 500px;
                width: 90%;
                animation: asyncSlideIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
            }
            
            @keyframes asyncSlideIn {
                from {
                    opacity: 0;
                    transform: translateY(30px) scale(0.95);
                }
                to {
                    opacity: 1;
                    transform: translateY(0) scale(1);
                }
            }
            
            .async-close-btn {
                position: absolute;
                top: 1rem;
                right: 1rem;
                width: 40px;
                height: 40px;
                border: none;
                background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
                border-radius: 50%;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 1.1rem;
                color: #6b7280;
                transition: all 0.3s ease;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            }
            
            .async-close-btn:hover {
                background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
                color: #dc2626;
                transform: rotate(90deg);
                box-shadow: 0 4px 12px rgba(220, 38, 38, 0.2);
            }
            
            .async-spinner-container {
                position: relative;
                width: 100px;
                height: 100px;
                margin: 0 auto 2rem;
            }
            
            .async-spinner {
                width: 100%;
                height: 100%;
                border: 4px solid #e5e7eb;
                border-radius: 50%;
                position: relative;
            }
            
            .async-spinner::before {
                content: '';
                position: absolute;
                top: -4px;
                left: -4px;
                right: -4px;
                bottom: -4px;
                border: 4px solid transparent;
                border-top-color: #667eea;
                border-right-color: #764ba2;
                border-radius: 50%;
                animation: asyncSpin 1.2s linear infinite;
            }
            
            .async-spinner-icon {
                position: absolute;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                font-size: 2.5rem;
                animation: asyncPulse 2s ease-in-out infinite;
            }
            
            @keyframes asyncSpin {
                from { transform: rotate(0deg); }
                to { transform: rotate(360deg); }
            }
            
            @keyframes asyncPulse {
                0%, 100% { transform: translate(-50%, -50%) scale(1); }
                50% { transform: translate(-50%, -50%) scale(1.15); }
            }
            
            .async-title {
                font-size: 1.5rem;
                font-weight: 700;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
                margin: 0 0 0.75rem 0;
            }
            
            .async-message {
                font-size: 1rem;
                color: #6b7280;
                margin: 0 0 1.5rem 0;
            }
            
            .async-progress-container {
                display: none;
                margin-bottom: 1.5rem;
            }
            
            .async-progress-container.visible {
                display: block;
            }
            
            .async-progress-bar {
                width: 100%;
                height: 8px;
                background: #e5e7eb;
                border-radius: 4px;
                overflow: hidden;
            }
            
            .async-progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #667eea 100%);
                background-size: 200% 100%;
                border-radius: 4px;
                width: 0%;
                transition: width 0.5s ease;
                animation: asyncGradient 2s linear infinite;
            }
            
            @keyframes asyncGradient {
                0% { background-position: 0% 50%; }
                100% { background-position: 200% 50%; }
            }
            
            .async-progress-fill.success {
                background: #10b981;
                animation: none;
            }
            
            .async-progress-fill.error {
                background: #ef4444;
                animation: none;
            }
            
            .async-elapsed-time {
                margin: 0.75rem 0 0 0;
                font-size: 0.9rem;
                color: #9ca3af;
                font-family: 'Monaco', 'Menlo', monospace;
            }
            
            .async-info-box {
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.75rem;
                padding: 1rem;
                background: linear-gradient(135deg, #dbeafe 0%, #e0e7ff 100%);
                border-radius: 12px;
                margin-bottom: 1.5rem;
                font-size: 0.9rem;
                color: #3730a3;
            }
            
            .async-info-box i {
                font-size: 1.2rem;
            }
            
            .async-actions {
                display: flex;
                gap: 1rem;
                justify-content: center;
                flex-wrap: wrap;
            }
            
            .async-btn {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                padding: 0.75rem 1.25rem;
                border: none;
                border-radius: 10px;
                font-weight: 600;
                font-size: 0.9rem;
                cursor: pointer;
                transition: all 0.3s ease;
            }
            
            .async-btn-cancel {
                background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
                color: #92400e;
            }
            
            .async-btn-cancel:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);
            }
            
            .async-btn-close {
                background: linear-gradient(135deg, #f3f4f6 0%, #e5e7eb 100%);
                color: #374151;
            }
            
            .async-btn-close:hover {
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(107, 114, 128, 0.2);
            }
            
            .async-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
                transform: none !important;
            }
        `;
        document.head.appendChild(style);
        document.body.appendChild(overlay);
    }
    overlay.classList.add('active');
}

function hideAsyncLoadingOverlay() {
    const overlay = document.getElementById('async-loading-overlay');
    if (overlay) overlay.classList.remove('active');
}

function updateAsyncJobUI(status, data) {
    data = data || {};
    const title = document.getElementById('async-status-title');
    const msg = document.getElementById('async-status-message');
    const progress = document.getElementById('async-progress-container');
    const fill = document.getElementById('async-progress-fill');
    const elapsed = document.getElementById('async-elapsed-time');
    const cancelBtn = document.getElementById('async-cancel-btn');
    const spinnerIcon = document.querySelector('.async-spinner-icon');
    
    if (!title) return;
    
    if (status === 'pending') {
        title.textContent = 'En attente...';
        msg.textContent = 'Le job est en file d\'attente.';
        if (spinnerIcon) spinnerIcon.textContent = '⏳';
        if (cancelBtn) cancelBtn.style.display = 'inline-flex';
    } else if (status === 'processing') {
        title.textContent = 'Génération en cours...';
        msg.textContent = 'L\'IA génère l\'analyse (2-5 min).';
        if (spinnerIcon) spinnerIcon.textContent = '⚡';
        if (cancelBtn) cancelBtn.style.display = 'none';
        if (progress) progress.classList.add('visible');
        if (data.elapsed_seconds && fill && elapsed) {
            var mins = Math.floor(data.elapsed_seconds / 60);
            var secs = Math.floor(data.elapsed_seconds % 60);
            elapsed.textContent = mins + 'm ' + String(secs).padStart(2, '0') + 's';
            fill.style.width = Math.min((data.elapsed_seconds / 180) * 100, 95) + '%';
        }
    } else if (status === 'completed') {
        title.textContent = '✨ Terminé !';
        msg.textContent = 'Analyse générée avec succès.';
        if (spinnerIcon) spinnerIcon.textContent = '✅';
        if (fill) { 
            fill.style.width = '100%'; 
            fill.classList.add('success');
        }
        if (cancelBtn) cancelBtn.style.display = 'none';
    } else if (status === 'error') {
        title.textContent = '❌ Erreur';
        msg.textContent = data.error || 'Une erreur est survenue.';
        if (spinnerIcon) spinnerIcon.textContent = '❌';
        if (fill) { 
            fill.style.width = '100%'; 
            fill.classList.add('error');
        }
    } else if (status === 'cancelled') {
        title.textContent = 'Annulé';
        msg.textContent = 'Le job a été annulé.';
        if (spinnerIcon) spinnerIcon.textContent = '🚫';
    }
}

async function cancelAsyncJob() {
    if (!currentAsyncJob || !currentAsyncJob.job_uuid) return;
    if (!confirm('Annuler ce job ?')) return;
    
    try {
        const response = await fetch('/analysis/async/cancel/' + currentAsyncJob.job_uuid, {
            method: 'POST',
            headers: { 'X-CSRFToken': getAsyncCsrfToken() }
        });
        const data = await response.json();
        if (data.success) {
            stopAsyncPolling();
            hideAsyncLoadingOverlay();
            currentAsyncJob = null;
            if (typeof showFlashMessage === 'function') {
                showFlashMessage('success', 'Job annulé');
            }
        }
    } catch (error) {
        if (typeof showFlashMessage === 'function') {
            showFlashMessage('error', error.message);
        }
    }
}

// ============================================================
// DÉLÉGATION D'ÉVÉNEMENTS pour boutons async
// ============================================================
document.addEventListener('click', function(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    
    const action = target.dataset.action;
    
    // Générer async (génération initiale)
    if (action === 'generate-async') {
        e.preventDefault();
        const userId = target.dataset.userId;
        const quizId = target.dataset.quizId;
        const stepId = target.dataset.stepId || 'career_path_v2';
        
        if (!userId || !quizId) {
            if (typeof showFlashMessage === 'function') {
                showFlashMessage('error', 'User ID ou Quiz ID manquant');
            }
            return;
        }
        generateAnalysisAsync(userId, quizId, stepId);
    }
    
    // Relancer async (analyse existante)
    if (action === 'replay-async') {
        e.preventDefault();
        const userId = target.dataset.userId;
        const quizId = target.dataset.quizId;
        const stepId = target.dataset.stepId || 'career_path_v2';
        
        generateAnalysisAsync(userId, quizId, stepId);
    }
    
    // Annuler job async
    if (action === 'cancel-async-job') {
        e.preventDefault();
        cancelAsyncJob();
    }
    
    // Fermer l'overlay (le job continue en arrière-plan)
    if (action === 'close-async-overlay') {
        e.preventDefault();
        hideAsyncLoadingOverlay();
        if (typeof showFlashMessage === 'function') {
            showFlashMessage('info', 'Le job continue en arrière-plan. Rafraîchissez la page pour voir le résultat.');
        }
    }
});