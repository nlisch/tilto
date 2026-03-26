// ╔════════════════════════════════════════════════════════════════════════════╗
// ║                                                                            ║
// ║                              QUIZ.JS                                       ║
// ║                                                                            ║
// ║         Fichier principal du quiz - Config, Audio & Core                   ║
// ║                                                                            ║
// ╚════════════════════════════════════════════════════════════════════════════╝

// ============================================================================
// ============================================================================
//
//                         PARTIE 1 : CONFIGURATION
//
// ============================================================================
// ============================================================================

// ============================================================================
// CONSTANTES GLOBALES
// ============================================================================

const MAX_RECORDING_TIME = 120;      // Durée max enregistrement (secondes)
const MIN_RECORDING_TIME = 15;       // Durée min enregistrement (secondes)
const MAX_TEXT_LENGTH = 2000;        // Caractères max textarea
const MIN_TEXT_LENGTH = 70;         // Caractères min textarea

// ============================================================================
// STRUCTURE DES CHAPITRES
// ============================================================================

const QUIZ_CHAPTERS = {
    'pack_clarte': {
        chapters: [
            {
                id: 'chapter_1',
                title: 'Ton profil',
                intro: null,
                questions: [67, 68, 69, 70],
                transition: null,
                introSeen: false
            }
        ]
    },
    'pack_orientation': {
        chapters: [
            {
                id: 'chapter_1',
                title: 'Découverte',
                intro: null,
                questions: [66, 53],
                transition: null,
                introSeen: false
            }
        ]
    },
    'smart_contact': {
        chapters: [
            {
                id: 'chapter_1',
                title: 'Ton projet',
                intro: null,
                questions: [66, 53],
                transition: null,
                introSeen: false
            }
        ]
    }
};

// ============================================================================
// MESSAGES D'ENCOURAGEMENT (bulles pendant enregistrement)
// ============================================================================

const ENCOURAGEMENT_MESSAGES = {
    'default': {
        45: "Prends ton temps",
        75: "Tu peux faire une pause si tu veux",
        120: "Tu maîtrises parfaitement",
        160: "Tu peux conclure quand tu le souhaites"
    },
    51: {
        45: "Qu'est-ce qui t'a marqué ?",
        75: "Continue, ton parcours m'intéresse",
        120: "N'hésite pas à parler de tes ressentis",
        160: "Parfait, ajoute ce qui te vient"
    },
    61: {
        45: "Pas besoin d'être précis",
        75: "Dis juste ce qui te vient",
        120: "Tu peux donner un ordre de grandeur",
        160: "Parfait, c'est suffisant"
    },
    65: {
        45: "Qu'est-ce qui te pèse au quotidien ?",
        75: "Continue, je t'écoute",
        120: "Tu peux détailler ce qui te ferait vibrer",
        160: "Parfait, ajoute ce qui te vient"
    },
    52: {  // Question Hero orientation
        45: "Qu'est-ce qui te passionne vraiment ?",
        75: "Parle aussi de ce qui t'ennuie...",
        120: "Super, tu peux développer encore",
        160: "Parfait, tu peux conclure"
    },
    53: {
        45: "Quelles matières te plaisent ?",
        75: "Et celles que tu détestes ?",
        120: "Continue, c'est intéressant",
        160: "Tu peux terminer quand tu veux"
    },
    54: {
        45: "Laisse libre cours à tes rêves...",
        75: "Ne te censure pas !",
        120: "Qu'est-ce qui te ferait vibrer ?",
        160: "Super, tu peux conclure"
    },
    58: {
        45: "Parle de tes contraintes...",
        75: "Géographie, argent, famille...",
        120: "C'est important pour te conseiller",
        160: "Tu peux terminer"
    },
    59: {
        45: "Décris ton métier idéal...",
        75: "L'ambiance, le rythme...",
        120: "Continue à rêver !",
        160: "Parfait !"
    }

};

// ============================================================================
// MESSAGES STATIQUES (pendant enregistrement)
// ============================================================================

const STATIC_RECORDING_MESSAGES = {
    'default': "On t'écoute...",
    51: "Raconte avec tes mots",
    52: "Parle de ce qui te fait vibrer...",
    53: "Tes matières préférées et détestées...",
    54: "Tes rêves, sans te censurer...",
    55: "Pense aussi perso ✨",
    56: "Ce qui te viens en premier",
    57: "Des loisirs, bénévolat, tests…",
    58: "Tes contraintes réelles...",
    59: "Ton métier idéal...",
    61: "Plus c'est précis, plus c'est puissant 🎯",
    65: "Ce qui te manque, ce qui te ferait vibrer..."
};

// ============================================================================
// MESSAGES D'ENCOURAGEMENT BARRE DE PROGRESSION
// ============================================================================

const PROGRESS_ENCOURAGEMENTS = {
    1: "C'est parti ! 🚀",
    2: "Encore une ! 💪",
    'complete': "Bravo, c'est fini ! 🎉"
};

// ============================================================================
// MESSAGES D'INVITATION (avant clic micro)
// ============================================================================

const QUESTION_INVITATION_MESSAGES = {
    'default': "Partage ton histoire",
    51: "Depuis le début, les secteurs, les structures sans trop de détails",
    52: "Spontanément, en positif et en négatif ?",
    54: "Pense à ce qui t'apporte de l'énergie…",
    55: "Pas forcément pro, mais ce qui revient souvent",
    56: "Repositionnement ou nouveau départ ? Transition plutôt en mois ou en années?",
    57: "Raconte tes explorations",
    59: "Laisse ton imagination parler",
    60: "Parle de ton environnement rêvé",
    61: "Partage ton idée de salaire",
    65: "Parle de ce qui te pèse et ce qui te ferait vibrer"
};

// ============================================================================
// TRACKING ANALYTICS (Google Analytics)
// ============================================================================

const QuizTracking = {
    
    EVENTS: {
        QUIZ_START: 'quiz_started',
        QUIZ_CHAPTER_START: 'quiz_chapter_started',
        QUIZ_CHAPTER_COMPLETE: 'quiz_chapter_completed',
        QUIZ_QUESTION_ANSWERED: 'quiz_question_answered',
        QUIZ_NAVIGATION_BACK: 'quiz_navigation_back',
        QUIZ_COMPLETE: 'quiz_completed',
        QUIZ_LEAD_FORM_VIEW: 'quiz_lead_form_viewed',
        QUIZ_LEAD_SUBMIT: 'quiz_lead_submitted',
        QUIZ_AUDIO_RECORDED: 'quiz_audio_recorded',
        QUIZ_TEXT_ENTERED: 'quiz_text_entered',
        QUIZ_ERROR: 'quiz_error'
    },

    trackPage: function(pagePath, pageTitle) {
        if (typeof gtag === 'undefined') {
            console.log('[Tracking] Page:', pagePath);
            return;
        }
        gtag('event', 'page_view', {
            page_path: pagePath,
            page_title: pageTitle,
            page_location: window.location.href
        });
    },

    trackEvent: function(eventName, eventParams = {}) {
        if (typeof gtag === 'undefined') {
            console.log('[Tracking] Event:', eventName, eventParams);
            return;
        }
        gtag('event', eventName, {
            ...eventParams,
            quiz_mode: typeof isHomepageMode !== 'undefined' && isHomepageMode ? 'homepage' : 'authenticated',
            timestamp: new Date().toISOString()
        });
    },

    trackQuizStart: function() {
        this.trackPage('/quiz/start', 'Quiz - Démarrage');
        this.trackEvent(this.EVENTS.QUIZ_START, {
            event_category: 'Quiz',
            event_label: 'quiz_homepage_start'
        });
    },

    trackChapterIntro: function(chapterNumber, chapterTitle) {
        this.trackPage(`/quiz/chapter-${chapterNumber}/intro`, `Quiz - Chapitre ${chapterNumber}: ${chapterTitle}`);
        this.trackEvent(this.EVENTS.QUIZ_CHAPTER_START, {
            event_category: 'Quiz',
            event_label: `chapter_${chapterNumber}_intro`,
            chapter_number: chapterNumber,
            chapter_title: chapterTitle
        });
    },

    // CORRECTION: Ajouter questionText comme paramètre
    trackQuestion: function(chapterNumber, questionIndex, questionId, questionText) {
        const pagePath = `/quiz/chapter-${chapterNumber}/question-${questionIndex + 1}`;
        const pageTitle = `Quiz - Chapitre ${chapterNumber} - Question ${questionIndex + 1}`;
        
        this.trackPage(pagePath, pageTitle);
        
        // AJOUT: Event pour la question vue
        if (questionText) {
            this.trackEvent('quiz_question_viewed', {
                event_category: 'Quiz',
                question_id: questionId,
                question_text: questionText.substring(0, 100),
                chapter_number: chapterNumber,
                question_index: questionIndex + 1
            });
        }
    },

    trackQuestionAnswer: function(questionId, questionText, answerType, answerLength = null) {
        this.trackEvent(this.EVENTS.QUIZ_QUESTION_ANSWERED, {
            event_category: 'Quiz',
            event_label: `question_${questionId}`,
            question_id: questionId,
            question_text: questionText ? questionText.substring(0, 100) : '',
            answer_type: answerType,
            answer_length: answerLength,
            chapter_number: typeof currentChapter !== 'undefined' ? currentChapter + 1 : 1,
            question_index: typeof currentChapterQuestionIndex !== 'undefined' ? currentChapterQuestionIndex + 1 : 1
        });
    },

    trackAudioRecording: function(questionId, duration) {
        this.trackEvent(this.EVENTS.QUIZ_AUDIO_RECORDED, {
            event_category: 'Quiz',
            event_label: `audio_question_${questionId}`,
            question_id: questionId,
            duration_seconds: duration,
            chapter_number: typeof currentChapter !== 'undefined' ? currentChapter + 1 : 1
        });
    },

    trackTextEntry: function(questionId, textLength) {
        this.trackEvent(this.EVENTS.QUIZ_TEXT_ENTERED, {
            event_category: 'Quiz',
            event_label: `text_question_${questionId}`,
            question_id: questionId,
            text_length: textLength,
            chapter_number: typeof currentChapter !== 'undefined' ? currentChapter + 1 : 1
        });
    },

    trackChapterTransition: function(fromChapter, toChapter) {
        this.trackPage(`/quiz/chapter-${fromChapter}/transition`, `Quiz - Transition ${fromChapter} → ${toChapter}`);
        this.trackEvent(this.EVENTS.QUIZ_CHAPTER_COMPLETE, {
            event_category: 'Quiz',
            event_label: `chapter_${fromChapter}_complete`,
            from_chapter: fromChapter,
            to_chapter: toChapter
        });
    },

    trackBackNavigation: function(fromQuestion, toQuestion) {
        this.trackEvent(this.EVENTS.QUIZ_NAVIGATION_BACK, {
            event_category: 'Quiz',
            event_label: 'back_button_clicked',
            from_question: fromQuestion,
            to_question: toQuestion,
            chapter_number: typeof currentChapter !== 'undefined' ? currentChapter + 1 : 1
        });
    },

    trackQuizComplete: function(totalQuestions, totalDuration) {
        this.trackPage('/quiz/complete', 'Quiz - Terminé');
        this.trackEvent(this.EVENTS.QUIZ_COMPLETE, {
            event_category: 'Quiz',
            event_label: 'quiz_completed',
            total_questions: totalQuestions,
            total_duration_seconds: totalDuration,
            total_chapters: typeof currentChapter !== 'undefined' ? currentChapter + 1 : 1
        });
    },

    trackLeadFormView: function() {
        this.trackPage('/quiz/lead-form', 'Quiz - Formulaire');
        this.trackEvent(this.EVENTS.QUIZ_LEAD_FORM_VIEW, {
            event_category: 'Quiz',
            event_label: 'lead_form_viewed'
        });
    },

    trackLeadSubmit: function(hasAudioResponses, responseCount) {
        this.trackEvent(this.EVENTS.QUIZ_LEAD_SUBMIT, {
            event_category: 'Quiz',
            event_label: 'lead_form_submitted',
            has_audio_responses: hasAudioResponses,
            response_count: responseCount,
            value: 1
        });
        
        // AJOUT: Tracking conversion GA4
        if (typeof gtag !== 'undefined') {
            gtag('event', 'conversion', {
                send_to: 'AW-XXXXXXXXX/XXXXX', // Remplacer par votre ID si applicable
                value: 1.0,
                currency: 'EUR'
            });
        }
        
        // AJOUT: Tracking Facebook Pixel si disponible
        if (typeof fbq !== 'undefined') {
            fbq('track', 'Lead', {
                content_category: 'quiz_completion',
                value: 1.0,
                currency: 'EUR'
            });
        }
    },

    trackError: function(errorType, errorMessage, context = {}) {
        this.trackEvent(this.EVENTS.QUIZ_ERROR, {
            event_category: 'Quiz',
            event_label: errorType,
            error_message: errorMessage,
            ...context
        });
    }
};

window.QuizTracking = QuizTracking;


// ============================================================================
// ============================================================================
//
//                         PARTIE 2 : AUDIO
//
// ============================================================================
// ============================================================================

// ============================================================================
// VARIABLES GLOBALES AUDIO
// ============================================================================

let isRecording = false;
let mediaRecorder = null;
let audioStream = null;
let audioChunks = [];
let audioBlob = null;
let audioURL = null;
let recordingTimer = null;
let recordingStartTime = 0;
let audioContext = null;
let analyser = null;
let dataArray = null;
let lastVolumeCheck = 0;
let isContinuingRecording = false;
let existingAudioDuration = 0;

// État audio par question
let currentQuestionAudioState = {};
let globalAudioStorage = {};

// ============================================================================
// DÉTECTION NAVIGATEUR
// ============================================================================

function isSafari() {
    const ua = navigator.userAgent;
    return /Safari/.test(ua) && !/Chrome/.test(ua) && !/Edge/.test(ua);
}

function isIOSSafari() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) &&
           /Safari/.test(navigator.userAgent) &&
           !/CriOS/.test(navigator.userAgent);
}

// ============================================================================
// UTILITAIRES AUDIO
// ============================================================================

/**
 * Formate les secondes en MM:SS
 */
function formatRecordingTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

/**
 * Nettoie toutes les ressources audio
 */
function cleanupAudioResources() {
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close().catch(() => {});
        audioContext = null;
    }
    if (audioStream) {
        audioStream.getTracks().forEach(track => track.stop());
        audioStream = null;
    }
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }
    analyser = null;
    dataArray = null;
    lastVolumeCheck = 0;
}

// ============================================================================
// DÉMARRAGE ENREGISTREMENT
// ============================================================================

/**
 * Démarre l'enregistrement audio
 */
async function startEnhancedRecording(audioContainer, questionId) {
    console.log('▶ Démarrage enregistrement pour question:', questionId);

    try {
        // Vérifier support navigateur
        if (!navigator.mediaDevices?.getUserMedia) {
            throw new Error('Votre navigateur ne supporte pas l\'enregistrement audio');
        }

        // Réinitialiser
        audioChunks = [];
        audioBlob = null;
        audioURL = null;

        // Configuration audio (simplifiée pour Safari)
        const constraints = {
            audio: {
                echoCancellation: !isSafari(),
                noiseSuppression: !isSafari(),
                autoGainControl: !isSafari()
            }
        };

        // Demander accès micro
        try {
            audioStream = await navigator.mediaDevices.getUserMedia(constraints);
        } catch (err) {
            if (err.name === 'NotAllowedError' && isSafari()) {
                throw new Error('Safari : autorisez le micro dans Réglages > Safari > Micro');
            }
            throw err;
        }

        // Initialiser état question
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0
            };
        }
        currentQuestionAudioState[questionId].isRecording = true;
        isRecording = true;

        // Mettre à jour UI
        updateRecordingUI(audioContainer, 'recording');

        // Démarrer timer
        recordingStartTime = Date.now();
        lastVolumeCheck = Date.now();
        startRecordingTimer(audioContainer);

        // Système d'encouragement
        initializeEncouragementSystem(audioContainer, questionId);

        // Analyse audio temps réel (sauf Safari)
        if (!isSafari()) {
            setupAudioAnalysis(audioStream, audioContainer);
        }

        // Créer MediaRecorder
        let mimeType = 'audio/webm;codecs=opus';
        if (isSafari() && !MediaRecorder.isTypeSupported(mimeType)) {
            const types = ['audio/mp4', 'audio/webm', 'audio/wav'];
            mimeType = types.find(t => MediaRecorder.isTypeSupported(t)) || '';
        }

        const options = { audioBitsPerSecond: 128000 };
        if (mimeType) options.mimeType = mimeType;

        mediaRecorder = new MediaRecorder(audioStream, options);

        mediaRecorder.addEventListener('dataavailable', e => {
            if (e.data.size > 0) audioChunks.push(e.data);
        });

        mediaRecorder.addEventListener('stop', () => {
            handleRecordingComplete(audioContainer, questionId);
        });

        // Démarrer (intervalle plus grand pour Safari)
        mediaRecorder.start(isSafari() ? 3000 : 1000);

        console.log('✓ Enregistrement démarré');

    } catch (error) {
        console.error('✗ Erreur enregistrement:', error);
        handleRecordingError(audioContainer, error);
        isRecording = false;
        if (currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId].isRecording = false;
        }
    }
}

// ============================================================================
// ARRÊT ENREGISTREMENT
// ============================================================================

/**
 * Arrête l'enregistrement audio
 */
/**
 * Arrête l'enregistrement audio
 */
function stopEnhancedRecording(audioContainer, questionId) {
    console.log('■ Arrêt enregistrement pour question:', questionId);

    if (!mediaRecorder || !isRecording) {
        console.warn('Pas d\'enregistrement actif');
        return;
    }

    // Calculer la durée AVANT d'arrêter
    const duration = Math.floor((Date.now() - recordingStartTime) / 1000);
    
    try {
        if (mediaRecorder.state === 'recording') {
            mediaRecorder.stop();
        }
    } catch (e) {
        console.error('Erreur arrêt MediaRecorder:', e);
    }

    // Marquer comme arrêté
    isRecording = false;
    if (currentQuestionAudioState[questionId]) {
        currentQuestionAudioState[questionId].isRecording = false;
        currentQuestionAudioState[questionId].duration = duration;
    }

    // Nettoyer timers d'encouragement
    if (audioContainer._encouragementTimers) {
        audioContainer._encouragementTimers.forEach(t => clearTimeout(t));
        audioContainer._encouragementTimers = null;
    }

    // Nettoyer timer principal
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }

    // Fermer contexte audio
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close().catch(() => {});
        audioContext = null;
        analyser = null;
        dataArray = null;
    }

    // Arrêter flux micro
    if (audioStream) {
        audioStream.getTracks().forEach(track => track.stop());
        audioStream = null;
    }

    // Masquer éléments UI
    const bubble = audioContainer.querySelector('.encouragement-bubble');
    if (bubble) {
        bubble.classList.remove('show');
        bubble.style.display = 'none';
    }

    const timer = audioContainer.querySelector('.enhanced-timer');
    if (timer) timer.style.display = 'none';

    const halo = audioContainer.querySelector('.voice-feedback-halo');
    if (halo) {
        halo.style.display = 'none';
        halo.style.opacity = '0';
    }

    const switchBtn = audioContainer.querySelector('.switch-to-text-btn');
    if (switchBtn) switchBtn.style.display = 'none';

    lastVolumeCheck = 0;

    // Cacher le hint minimum
    var minHint = audioContainer.querySelector('.audio-min-hint');
    if (minHint) minHint.style.display = 'none';

    console.log('✓ Enregistrement arrêté, durée:', duration, 's');

}



// ============================================================================
// TRAITEMENT FIN ENREGISTREMENT
// ============================================================================

/**
 * Traite l'audio après arrêt de l'enregistrement
 */
function handleRecordingComplete(audioContainer, questionId) {
    console.log('⚙ Traitement audio pour question:', questionId);

    const mimeType = isSafari() ? 'audio/mp4' : 'audio/webm';
    audioBlob = new Blob(audioChunks, { type: mimeType });
    audioURL = URL.createObjectURL(audioBlob);

    const duration = Math.floor((Date.now() - recordingStartTime) / 1000);

    // Sauvegarder état
    currentQuestionAudioState[questionId].audioBlob = audioBlob;
    currentQuestionAudioState[questionId].audioURL = audioURL;
    currentQuestionAudioState[questionId].duration = duration;

    // Configurer élément audio
    const audioElement = audioContainer.querySelector('.audio-element');
    if (audioElement) {
        audioElement.src = audioURL;
        audioElement.load();
    }

    // ════════════════════════════════════════════════════════════════
    // NOUVEAU : UI différente selon si valide ou trop court
    // ════════════════════════════════════════════════════════════════
    if (duration < MIN_RECORDING_TIME) {
        updateRecordingUI(audioContainer, 'too_short', duration);
    } else {
        updateRecordingUI(audioContainer, 'completed');
    }

    // Sauvegarder pour envoi final
    if (!window.tempQuizAudios) window.tempQuizAudios = {};

    const audioId = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    window.tempQuizAudios[audioId] = {
        blob: audioBlob,
        url: audioURL,
        questionId: questionId,
        duration: duration,
        mimeType: mimeType
    };

    console.log('✓ Audio traité, durée:', duration, 's');

    // Scroll vers bouton suivant seulement si valide
    if (duration >= MIN_RECORDING_TIME) {
        scrollToNextButton();
    }
}

// ============================================================================
// TIMER ENREGISTREMENT
// ============================================================================

/**
 * Démarre le timer d'enregistrement
 */
function startRecordingTimer(audioContainer) {
    const timerDisplay = audioContainer.querySelector('.timer-display');
    const progressRing = audioContainer.querySelector('.progress-ring-bar');
    const circumference = 2 * Math.PI * 70;

    const timerContainer = audioContainer.querySelector('.enhanced-timer');
    if (timerContainer) timerContainer.style.display = 'block';

// Ajouter hint minimum si pas déjà là
var minHint = audioContainer.querySelector('.audio-min-hint');
if (!minHint) {
    minHint = document.createElement('div');
    minHint.className = 'audio-min-hint recording';
    minHint.textContent = '15 secondes minimum';
    var timerEl = audioContainer.querySelector('.enhanced-timer');
    if (timerEl) {
        timerEl.parentNode.insertBefore(minHint, timerEl.nextSibling);
    }
}

recordingTimer = setInterval(() => {
    if (!recordingStartTime) return;

    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;

    if (timerDisplay) {
        timerDisplay.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    }

    if (progressRing) {
        const progress = elapsed / MAX_RECORDING_TIME;
        progressRing.style.strokeDashoffset = circumference * (1 - progress);
    }

    // Mettre à jour hint minimum
    if (minHint) {
        if (elapsed < MIN_RECORDING_TIME) {
            var remaining = MIN_RECORDING_TIME - elapsed;
            minHint.textContent = '🎙️ Continue encore ' + remaining + 's avant de passer à la suite';
            minHint.className = 'audio-min-hint recording';
        } else {
            minHint.textContent = '✓ Tu peux t\'arrêter ou continuer pour une analyse plus fine';
            minHint.className = 'audio-min-hint reached';
        }
    }

    // Arrêt automatique à la limite
    if (elapsed >= MAX_RECORDING_TIME) {
        const questionId = getCurrentQuestionId();
        stopEnhancedRecording(audioContainer, questionId);
    }
}, 1000);
}

// ============================================================================
// ANALYSE AUDIO TEMPS RÉEL
// ============================================================================

/**
 * Configure l'analyse audio pour feedback visuel
 */
function setupAudioAnalysis(stream, audioContainer) {
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();

        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.8;
        source.connect(analyser);

        dataArray = new Uint8Array(analyser.frequencyBinCount);

        startVoiceFeedback(audioContainer);
    } catch (e) {
        console.warn('Analyse audio non disponible:', e);
    }
}

/**
 * Feedback visuel du volume en temps réel
 */
function startVoiceFeedback(audioContainer) {
    const halo = audioContainer.querySelector('.voice-feedback-halo');
    if (!halo || !analyser) return;

    function update() {
        if (!isRecording || !analyser) return;

        analyser.getByteFrequencyData(dataArray);

        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
        const volume = (sum / dataArray.length) / 255;

        const intensity = Math.max(0.1, volume);
        halo.style.transform = `scale(${1 + intensity * 0.3})`;
        halo.style.opacity = 0.3 + intensity * 0.4;

        if (volume > 0.02) lastVolumeCheck = Date.now();

        requestAnimationFrame(update);
    }

    update();
}

// ============================================================================
// SYSTÈME D'ENCOURAGEMENT
// ============================================================================

/**
 * Initialise les bulles d'encouragement programmées
 */
function initializeEncouragementSystem(audioContainer, questionId) {
    const timers = [
        setTimeout(() => showEncouragementBubble(audioContainer, questionId, 45), 45000),
        setTimeout(() => showEncouragementBubble(audioContainer, questionId, 75), 75000),
        setTimeout(() => showEncouragementBubble(audioContainer, questionId, 120), 120000),
        setTimeout(() => showEncouragementBubble(audioContainer, questionId, 160), 160000)
    ];
    audioContainer._encouragementTimers = timers;
}

/**
 * Affiche une bulle d'encouragement
 */
function showEncouragementBubble(audioContainer, questionId, timing) {
    if (!isRecording) return;

    const bubble = audioContainer.querySelector('.encouragement-bubble');
    const content = bubble?.querySelector('.bubble-content');
    if (!bubble || !content) return;

    const messages = ENCOURAGEMENT_MESSAGES[questionId] || ENCOURAGEMENT_MESSAGES['default'];
    let message = "Continue, je t'écoute...";

    if (timing >= 120) message = messages[120] || messages['default']?.[120] || message;
    else if (timing >= 60) message = messages[75] || messages['default']?.[75] || message;
    else if (timing >= 25) message = messages[45] || messages['default']?.[45] || message;

    content.textContent = message;
    bubble.style.display = 'block';
    setTimeout(() => bubble.classList.add('show'), 10);

    setTimeout(() => {
        bubble.classList.remove('show');
        setTimeout(() => bubble.style.display = 'none', 300);
    }, 4000);
}

// ============================================================================
// MISE À JOUR UI AUDIO
// ============================================================================

/**
 * Met à jour l'interface selon l'état d'enregistrement
 */
/**
 * Met à jour l'interface selon l'état d'enregistrement
 */
function updateRecordingUI(audioContainer, state, duration = 0) {
    const readyMsg = audioContainer.querySelector('.status-message.ready');
    const recordingMsg = audioContainer.querySelector('.status-message.recording');
    const completedMsg = audioContainer.querySelector('.status-message.completed');
    const micButton = audioContainer.querySelector('.enhanced-mic-button');
    const timer = audioContainer.querySelector('.enhanced-timer');
    const controls = audioContainer.querySelector('.post-recording-controls');
    const halo = audioContainer.querySelector('.voice-feedback-halo');
    const switchBtn = audioContainer.querySelector('.switch-to-text-btn');

    // Masquer tous les messages
    [readyMsg, recordingMsg, completedMsg].forEach(m => {
        if (m) m.style.display = 'none';
    });

    // Bouton texte visible seulement pendant enregistrement
    if (switchBtn) switchBtn.style.display = state === 'recording' ? 'block' : 'none';

    switch (state) {
        case 'ready':
            if (readyMsg) {
                readyMsg.style.display = 'block';
                const qId = getCurrentQuestionId();
                readyMsg.textContent = QUESTION_INVITATION_MESSAGES[qId] || QUESTION_INVITATION_MESSAGES['default'];
            }
            if (micButton) {
                micButton.className = 'enhanced-mic-button ready';
            }
            if (timer) timer.style.display = 'none';
            if (controls) controls.style.display = 'none';
            if (halo) halo.style.display = 'none';
            const tapToSpeakReady = audioContainer.querySelector('.tap-to-speak');
            if (tapToSpeakReady) tapToSpeakReady.style.display = 'block';
            break;
    
        case 'recording':
            if (recordingMsg) recordingMsg.style.display = 'block';
            if (micButton) {
                micButton.className = 'enhanced-mic-button recording';
                micButton.innerHTML = '<div class="stop-hand-icon" style="font-size:28px;animation:pulse 2s infinite">✋</div>';
                setupStopButton(micButton, audioContainer);
            }
            if (timer) timer.style.display = 'block';
            if (controls) controls.style.display = 'none';
            if (halo) halo.style.display = 'block';
            const tapToSpeakRec = audioContainer.querySelector('.tap-to-speak');
            if (tapToSpeakRec) tapToSpeakRec.style.display = 'none';
            break;
    
            case 'completed':
                if (completedMsg) completedMsg.style.display = 'block';
                if (micButton) {
                    micButton.className = 'enhanced-mic-button completed';
                    micButton.innerHTML = '<div class="check-icon" style="font-size:32px;color:white">✓</div>';
                }
                if (timer) timer.style.display = 'none';
                if (controls) controls.style.display = 'block';
                if (halo) halo.style.display = 'none';
                
                // Réafficher le bouton "Écouter"
                const listenBtnCompleted = audioContainer.querySelector('.listen-btn');
                if (listenBtnCompleted) listenBtnCompleted.style.display = 'inline-flex';
                
                const tapToSpeakDone = audioContainer.querySelector('.tap-to-speak');
                if (tapToSpeakDone) tapToSpeakDone.style.display = 'none';
                // Réinitialiser jauge
                const ring = audioContainer.querySelector('.progress-ring-bar');
                if (ring) ring.style.strokeDashoffset = '439.8';
                break;

        // ════════════════════════════════════════════════════════════════
        // NOUVEAU : État "trop court"
        // ════════════════════════════════════════════════════════════════
        case 'too_short':
            const remaining = MIN_RECORDING_TIME - duration;
            
            // Message d'encouragement à la place de "Merci pour ce partage"
            if (completedMsg) {
                completedMsg.style.display = 'block';
                const secondeText = remaining > 1 ? 'secondes' : 'seconde';
                completedMsg.innerHTML = '<span class="too-short-message">⏱️ Moins de 15 secondes, c\'est trop court ! Réenregistre-toi en développant un peu plus.</span>';
                completedMsg.classList.add('too-short');
            }
            
            // Bouton orange/jaune au lieu de vert avec coche
            if (micButton) {
                micButton.className = 'enhanced-mic-button too-short';
                micButton.innerHTML = '<div class="mic-icon" style="font-size:28px">🎙️</div>';
            }
            
            if (timer) timer.style.display = 'none';
            if (controls) controls.style.display = 'block';
            if (halo) halo.style.display = 'none';
            
            // Cacher le bouton "Écouter" si trop court
            const listenBtnShort = audioContainer.querySelector('.listen-btn');
            if (listenBtnShort) listenBtnShort.style.display = 'none';
            
            const tapToSpeakShort = audioContainer.querySelector('.tap-to-speak');
            if (tapToSpeakShort) tapToSpeakShort.style.display = 'none';
            
            // Réinitialiser jauge
            const ringShort = audioContainer.querySelector('.progress-ring-bar');
            if (ringShort) ringShort.style.strokeDashoffset = '439.8';
            break;
    }
}

/**
 * Configure le bouton stop pendant l'enregistrement
 */
function setupStopButton(micButton, audioContainer) {
    const questionId = getCurrentQuestionId();

    const handleStop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        stopEnhancedRecording(audioContainer, questionId);
    };

    // Nettoyer anciens listeners
    micButton.onclick = null;
    micButton.addEventListener('click', handleStop);
    micButton.addEventListener('touchend', handleStop, { passive: false });
}

/**
 * Met à jour l'affichage selon l'état sauvegardé
 */
function updateAudioDisplayState(audioContainer, questionState) {
    const micButton = audioContainer.querySelector('.enhanced-mic-button');
    const controls = audioContainer.querySelector('.post-recording-controls');
    const audioElement = audioContainer.querySelector('.audio-element');
    const readyMsg = audioContainer.querySelector('.status-message.ready');
    const completedMsg = audioContainer.querySelector('.status-message.completed');
    const tapToSpeak = audioContainer.querySelector('.tap-to-speak');

    // Masquer tous les messages
    const messages = audioContainer.querySelectorAll('.status-message');
    messages.forEach(m => m.style.display = 'none');

    if (questionState.audioBlob && questionState.audioURL) {
        // Audio enregistré - ÉTAT COMPLET
        console.log('updateAudioDisplayState: audio enregistré détecté');
        
        if (micButton) {
            micButton.className = 'enhanced-mic-button completed';
            micButton.innerHTML = '<div class="check-icon" style="font-size:32px;color:white">✓</div>';
            micButton.style.display = 'block';
        }
        if (controls) controls.style.display = 'block';
        
        // CRITIQUE: Configurer l'élément audio
        if (audioElement) {
            if (audioElement.src !== questionState.audioURL) {
                audioElement.src = questionState.audioURL;
                audioElement.load();
            }
            audioElement.style.display = 'block';
        }
        
        if (completedMsg) completedMsg.style.display = 'block';
        if (tapToSpeak) tapToSpeak.style.display = 'none';

        // Bouton continuer si trop court
        const continueBtn = audioContainer.querySelector('.continue-btn');
        if (continueBtn) {
            continueBtn.style.display = (questionState.duration || 0) < MIN_RECORDING_TIME ? 'inline-block' : 'none';
        }

    } else if (questionState.isRecording) {
        // Enregistrement en cours
        if (micButton) {
            micButton.className = 'enhanced-mic-button recording';
        }
        if (controls) controls.style.display = 'none';

    } else {
        // Prêt à enregistrer
        console.log('updateAudioDisplayState: état prêt');
        
        if (micButton) {
            micButton.className = 'enhanced-mic-button ready';
            micButton.innerHTML = '<div class="mic-icon">🎙️</div>';
            micButton.style.display = 'block';
        }
        if (controls) controls.style.display = 'none';
        if (audioElement) {
            audioElement.src = '';
            audioElement.style.display = 'none';
        }
        if (readyMsg) readyMsg.style.display = 'block';
        if (tapToSpeak) tapToSpeak.style.display = 'block';
    }
}


// ============================================================================
// ACTIONS UTILISATEUR
// ============================================================================

/**
 * Lit l'enregistrement
 */
/**
 * Lit ou met en pause l'enregistrement (toggle)
 */
function playRecording(audioContainer, questionId) {
    const audioElement = audioContainer.querySelector('.audio-element');
    const listenBtn = audioContainer.querySelector('.listen-btn');
    const state = currentQuestionAudioState[questionId];

    if (!audioElement) {
        console.error('Élément audio non trouvé');
        showAudioError(audioContainer, 'Impossible de lire l\'enregistrement');
        return;
    }

    if (!state?.audioURL) {
        console.error('URL audio non disponible pour question:', questionId);
        
        // Tentative de récupération depuis tempQuizAudios
        if (window.tempQuizAudios) {
            for (const [audioId, data] of Object.entries(window.tempQuizAudios)) {
                if (data.questionId == questionId && data.blob) {
                    const newUrl = URL.createObjectURL(data.blob);
                    state.audioURL = newUrl;
                    data.url = newUrl;
                    console.log('URL audio recréée depuis tempQuizAudios');
                    break;
                }
            }
        }
        
        if (!state?.audioURL) {
            showAudioError(audioContainer, 'Enregistrement non disponible');
            return;
        }
    }

    // Configurer la source si nécessaire
    if (audioElement.src !== state.audioURL) {
        audioElement.src = state.audioURL;
        audioElement.load();
    }

    // Toggle play/pause
    if (!audioElement.paused) {
        // En cours de lecture -> mettre en pause
        audioElement.pause();
        if (listenBtn) {
            listenBtn.innerHTML = '<i class="fas fa-headphones btn-icon"></i> Écouter';
        }
        console.log('⏸️ Audio mis en pause');
    } else {
        // En pause ou arrêté -> lire
        audioElement.play().then(() => {
            if (listenBtn) {
                listenBtn.innerHTML = '<i class="fas fa-pause btn-icon"></i> Pause';
            }
            console.log('▶️ Lecture audio');
        }).catch(e => {
            console.error('Erreur lecture:', e);
            
            if (isSafari()) {
                showAudioError(audioContainer, 'Appuyez à nouveau pour écouter');
            } else {
                showAudioError(audioContainer, 'Impossible de lire l\'enregistrement');
            }
        });
        
        // Écouter la fin de lecture pour remettre le bouton
        audioElement.onended = () => {
            if (listenBtn) {
                listenBtn.innerHTML = '<i class="fas fa-headphones btn-icon"></i> Écouter';
            }
            console.log('✓ Lecture terminée');
        };
    }
}


/**
 * Réinitialise l'enregistrement pour réenregistrer
 */

function resetRecording(audioContainer, questionId) {
    const state = currentQuestionAudioState[questionId];
    if (state) {
        if (state.audioURL) URL.revokeObjectURL(state.audioURL);
        state.audioBlob = null;
        state.audioURL = null;
        state.isRecording = false;
        state.duration = 0;

        if (getCurrentQuestionId() === questionId) {
            audioBlob = null;
            audioURL = null;
            audioChunks = [];
        }

        // Nettoyer stockage temporaire
        if (window.tempQuizAudios) {
            Object.keys(window.tempQuizAudios).forEach(id => {
                if (window.tempQuizAudios[id].questionId === questionId) {
                    if (window.tempQuizAudios[id].url) URL.revokeObjectURL(window.tempQuizAudios[id].url);
                    delete window.tempQuizAudios[id];
                }
            });
        }
    }

    // Nettoyer l'état "too-short" du message
    const completedMsg = audioContainer.querySelector('.status-message.completed');
    if (completedMsg) {
        completedMsg.classList.remove('too-short');
        completedMsg.textContent = 'Merci pour ton partage';
    }

    // Cacher le feedback de durée courte (ancien système)
    const feedback = audioContainer.querySelector('.short-recording-feedback');
    if (feedback) {
        feedback.style.display = 'none';
    }

    // Cacher l'erreur globale si visible
    hideError();

    updateRecordingUI(audioContainer, 'ready');

    const ring = audioContainer.querySelector('.progress-ring-bar');
    if (ring) ring.style.strokeDashoffset = '439.8';
}

/**
 * Supprime l'audio d'une question
 */
function deleteQuestionAudio(questionId, audioContainer, voiceButton, textArea) {
    console.log('🗑 Suppression audio question:', questionId);

    const state = currentQuestionAudioState[questionId];
    if (state) {
        if (state.audioURL) URL.revokeObjectURL(state.audioURL);
        state.audioBlob = null;
        state.audioURL = null;
        state.isRecording = false;

        if (getCurrentQuestionId() === questionId) {
            audioBlob = null;
            audioURL = null;
            audioChunks = [];
        }

        // Restaurer bouton micro
        if (voiceButton) {
            voiceButton.innerHTML = '<div class="mic-icon">🎙️</div>';
            voiceButton.className = 'enhanced-mic-button ready';
            voiceButton.style.display = 'block';
        }

        // Masquer contrôles
        const controls = audioContainer.querySelector('.post-recording-controls');
        if (controls) controls.style.display = 'none';

        // Nettoyer élément audio
        const audioElement = audioContainer.querySelector('.audio-element');
        if (audioElement) {
            audioElement.pause();
            audioElement.src = '';
            audioElement.style.display = 'none';
        }

        // Nettoyer stockages
        if (globalAudioStorage[questionId]) delete globalAudioStorage[questionId];

        if (window.tempQuizAudios) {
            Object.keys(window.tempQuizAudios).forEach(id => {
                if (window.tempQuizAudios[id].questionId === questionId) {
                    if (window.tempQuizAudios[id].url) URL.revokeObjectURL(window.tempQuizAudios[id].url);
                    delete window.tempQuizAudios[id];
                }
            });
        }
    }
}

// ============================================================================
// GESTION ERREURS AUDIO
// ============================================================================

/**
 * Gère les erreurs d'enregistrement
 */
function handleRecordingError(audioContainer, error) {
    console.error('Erreur audio:', error);

    updateRecordingUI(audioContainer, 'ready');
    isRecording = false;

    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }

    let message = 'Impossible d\'accéder au microphone.';

    if (isSafari() || isIOSSafari()) {
        if (error.name === 'NotAllowedError') {
            message = 'Safari : cliquez sur l\'icône micro dans la barre d\'adresse pour autoriser.';
        } else if (error.name === 'NotFoundError') {
            message = 'Microphone non détecté. Vérifiez vos paramètres.';
        } else {
            message = 'Erreur Safari : rechargez la page et réessayez.';
        }
    }

    showAudioError(audioContainer, message);
}

/**
 * Affiche un message d'erreur audio
 */
function showAudioError(audioContainer, message) {
    // Supprimer ancien message
    const old = audioContainer.querySelector('.audio-error-message');
    if (old) old.remove();

    const div = document.createElement('div');
    div.className = 'audio-error-message';
    div.textContent = message;
    div.style.cssText = 'color:#ef4444;font-size:0.85rem;margin-top:0.5rem;text-align:center;padding:0.5rem;background:#fef2f2;border-radius:8px;';
    audioContainer.appendChild(div);

    setTimeout(() => {
        if (div.parentNode) div.remove();
    }, 5000);
}

// ============================================================================
// CONFIGURATION ÉVÉNEMENTS AUDIO
// ============================================================================

/**
 * Configure tous les événements audio pour une question
 */
function setupEnhancedAudioEvents(audioContainer, textArea, charCount, questionId, maxLength) {
    console.log('⚙ Config événements audio question:', questionId);

    setTimeout(() => {
        const micButton = audioContainer.querySelector('.enhanced-mic-button');
        const switchBtn = audioContainer.querySelector('.switch-to-text-btn');
        const listenBtn = audioContainer.querySelector('.listen-btn');
        const rerecordBtn = audioContainer.querySelector('.rerecord-btn');
        const continueBtn = audioContainer.querySelector('.continue-btn');

        // Bouton micro principal
        if (micButton) {
            micButton.onclick = null;

            const handleMic = (e) => {
                e.preventDefault();
                e.stopPropagation();

                const state = currentQuestionAudioState[questionId];
                if (state?.isRecording) {
                    stopEnhancedRecording(audioContainer, questionId);
                } else if (!state?.audioBlob) {
                    startEnhancedRecording(audioContainer, questionId);
                }
            };

            micButton.addEventListener('click', handleMic);
            micButton.addEventListener('touchend', (e) => {
                e.preventDefault();
                handleMic(e);
            }, { passive: false });
        }

        // Bouton "Je préfère écrire"
        if (switchBtn) {
            const handleSwitch = (e) => {
                e.preventDefault();
                e.stopPropagation();
                if (textArea && charCount) {
                    switchToTextMode(audioContainer, textArea, charCount);
                }
            };
            switchBtn.addEventListener('click', handleSwitch);
            switchBtn.addEventListener('touchend', handleSwitch, { passive: false });
        }

        // Bouton écouter
        if (listenBtn) {
            listenBtn.addEventListener('click', () => playRecording(audioContainer, questionId));
        }

        // Bouton réenregistrer
        if (rerecordBtn) {
            rerecordBtn.addEventListener('click', () => {
                resetRecording(audioContainer, questionId);
                startEnhancedRecording(audioContainer, questionId);
            });
        }

        // Bouton continuer (pour enregistrements courts)
        if (continueBtn) {
            continueBtn.addEventListener('click', () => {
                isContinuingRecording = true;
                startEnhancedRecording(audioContainer, questionId);
            });
        }

        // Événements textarea
        if (textArea && charCount) {
            textArea.addEventListener('input', () => {
                updateCharCount(textArea, charCount, maxLength);
            });
        }

    }, 100);
}

/**
 * Configure le message statique d'enregistrement
 */
function setupStaticRecordingMessage(audioContainer, questionId) {
    const staticMsg = audioContainer.querySelector('.static-message');
    if (!staticMsg) return;

    staticMsg.textContent = STATIC_RECORDING_MESSAGES[questionId] || STATIC_RECORDING_MESSAGES['default'];
}

// ============================================================================
// BASCULE MODE TEXTE
// ============================================================================

/**
 * Bascule de l'audio vers le mode texte
 */
function switchToTextMode(audioContainer, textArea, charCount) {
    console.log('→ Bascule vers mode texte');

    // Arrêter enregistrement si actif
    const questionId = getCurrentQuestionId();
    const state = currentQuestionAudioState[questionId];

    if (state?.isRecording) {
        try {
            stopEnhancedRecording(audioContainer, questionId);
        } catch (e) {
            console.warn('Erreur arrêt:', e);
        }
    }

    // Masquer audio, afficher texte
    audioContainer.style.display = 'none';

    if (textArea) {
        textArea.style.display = 'block';
        textArea.disabled = false;
        if (!textArea.value.trim()) {
            textArea.placeholder = 'Partage tes idées ici...';
        }
    }

    if (charCount) charCount.style.display = 'block';

    // Focus
    setTimeout(() => {
        if (textArea) textArea.focus();
    }, 150);

    // Bouton retour audio
    if (!document.querySelector('.back-to-audio-btn') && textArea?.parentNode) {
        const backBtn = document.createElement('button');
        backBtn.type = 'button';
        backBtn.className = 'text-fallback switch-to-text-btn';
        backBtn.innerHTML = '🎙️ Finalement, je préfère parler';

        const handleBack = (e) => {
            e.preventDefault();
            e.stopPropagation();
            audioContainer.style.display = 'block';
            if (textArea) {
                textArea.style.display = 'none';
                textArea.value = '';
            }
            if (charCount) charCount.style.display = 'none';
            backBtn.remove();
        };

        backBtn.addEventListener('click', handleBack);
        backBtn.addEventListener('touchend', handleBack, { passive: false });

        textArea.parentNode.appendChild(backBtn);
    }
}

// ============================================================================
// UTILITAIRE SCROLL
// ============================================================================

/**
 * Scroll vers le bouton suivant après enregistrement
 */
/**
 * Scroll vers le bouton suivant après enregistrement (seulement si valide)
 */
function scrollToNextButton() {
    setTimeout(() => {
        // Vérifier si l'enregistrement est assez long
        const questionId = getCurrentQuestionId();
        const state = currentQuestionAudioState[questionId];
        
        // Ne pas animer si enregistrement trop court
        if (state && state.duration < MIN_RECORDING_TIME) {
            console.log('⏳ Enregistrement trop court, pas d\'animation du bouton');
            return;
        }
        
        const btn = document.querySelector('.next-btn');
        if (btn) {
            btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
            btn.style.animation = 'pulse 0.8s ease-in-out 3';
            setTimeout(() => btn.style.animation = '', 2400);
        }
    }, 800);
}

// ============================================================================
// NETTOYAGE GLOBAL AUDIO
// ============================================================================

window.addEventListener('beforeunload', cleanupAudioResources);
window.addEventListener('pagehide', cleanupAudioResources);


// ============================================================================
// ============================================================================
//
//                         PARTIE 3 : CORE
//
// ============================================================================
// ============================================================================

// ============================================================================
// ÉTAT GLOBAL
// ============================================================================

// --- Questions et réponses ---
let allQuestions = [];
let userAnswers = {};
let questionHistory = [];

// --- Mode homepage (non authentifié) ---
let isHomepageMode = false;
let homepageAllQuestions = [];
let homepageQuizAnswers = {};
let homepageQuestionHistory = [];

// --- Navigation ---
let currentQuestionIndex = 0;
let currentChapter = 0;
let currentChapterQuestionIndex = 0;
let isShowingTransition = false;
let isEditingFromReview = false;

// ============================================================================
// ACCESSEURS UNIFIÉS (évite la duplication homepage/normal)
// ============================================================================

function getAnswers() {
    return isHomepageMode ? homepageQuizAnswers : userAnswers;
}

function setAnswer(questionId, answer) {
    if (isHomepageMode) {
        homepageQuizAnswers[questionId] = answer;
    } else {
        userAnswers[questionId] = answer;
    }
}

function getHistory() {
    return isHomepageMode ? homepageQuestionHistory : questionHistory;
}

function pushToHistory(state) {
    if (isHomepageMode) {
        homepageQuestionHistory.push(state);
    } else {
        questionHistory.push(state);
    }
}

function popFromHistory() {
    return isHomepageMode ? homepageQuestionHistory.pop() : questionHistory.pop();
}

function getAllQuestions() {
    return isHomepageMode ? homepageAllQuestions : allQuestions;
}

function setAllQuestions(questions) {
    if (isHomepageMode) {
        homepageAllQuestions = questions;
    } else {
        allQuestions = questions;
    }
}

// ============================================================================
// UTILITAIRES
// ============================================================================

function log(message, data = '') {
    console.log(`[Quiz] ${message}`, data);
}

function getElement(selector, silent = false) {
    const el = document.querySelector(selector);
    if (!el && !silent) console.warn(`Élément non trouvé: ${selector}`);
    return el;
}

function getQuizId() {
    // Variable globale (définie dans la page orientation.html)
    if (typeof window.ORIENTATION_QUIZ_ID === 'string' && window.ORIENTATION_QUIZ_ID) {
        return window.ORIENTATION_QUIZ_ID;
    }
    if (typeof window.currentQuizId === 'string' && window.currentQuizId) {
        return window.currentQuizId;
    }
    // Champ caché
    const hidden = document.getElementById('currentQuizId');
    if (hidden?.value) return hidden.value;
    // URL
    const urlParams = new URLSearchParams(window.location.search);
    const fromUrl = urlParams.get('quiz_id');
    if (fromUrl) return fromUrl;
    // Détecter la page orientation
    if (window.location.pathname === '/orientation') {
        return 'pack_orientation';
    }
    // Défaut
    return 'pack_clarte';
}

function getCurrentQuestionId() {
    const questions = getAllQuestions();
    const chapter = getCurrentChapter();

    if (chapter && currentChapterQuestionIndex < chapter.questions.length) {
        return chapter.questions[currentChapterQuestionIndex];
    }

    if (questions.length > 0 && currentQuestionIndex < questions.length) {
        return questions[currentQuestionIndex]?.id;
    }

    return `question_${Date.now()}`;
}

function getCurrentChapter(quizId) {
    // Utiliser le quizId passé ou détecter automatiquement
    const effectiveQuizId = quizId || getQuizId();
    const chapters = QUIZ_CHAPTERS[effectiveQuizId]?.chapters || [];
    if (currentChapter >= 0 && currentChapter < chapters.length) {
        return chapters[currentChapter];
    }
    return null;
}

function getCurrentQuestionInChapter() {
    const quizId = getQuizId();
    const chapter = getCurrentChapter(quizId);
    
    if (!chapter || currentChapterQuestionIndex >= chapter.questions.length) {
        console.warn('[Quiz] Pas de chapitre ou index hors limites:', currentChapter, currentChapterQuestionIndex);
        return null;
    }

    const questionId = chapter.questions[currentChapterQuestionIndex];
    const questions = getAllQuestions();
    
    // Comparaison flexible (number ou string)
    const found = questions.find(q => String(q.id) === String(questionId));
    
    if (!found) {
        console.warn('[Quiz] Question non trouvée:', questionId, 'dans', questions.map(q => q.id));
    }
    
    return found;
}

// ============================================================================
// API - CHARGEMENT DONNÉES
// ============================================================================

/**
 * Charge les questions depuis le serveur
 */
async function loadQuestions(quizId = 'pack_clarte') {
    log('Chargement questions, mode homepage:', isHomepageMode);

    let endpoint;
    if (isHomepageMode) {
        endpoint = `/get_questions_homepage/?quiz_id=${quizId}`;
    } else if (quizId === 'smart_contact') {
        endpoint = `/get_questions_smart_contact/?quiz_id=${quizId}`;
    } else {
        endpoint = `/get_questions/?quiz_id=${encodeURIComponent(quizId)}`;
    }

    try {
        const response = await fetch(endpoint, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: isHomepageMode ? 'omit' : 'same-origin'
        });

        if (!response.ok) throw new Error('Erreur chargement questions');

        const data = await response.json();

        if (!data.questions || !Array.isArray(data.questions)) {
            throw new Error('Format questions invalide');
        }

        const formatted = data.questions.map(q => ({
            ...q,
            max_choices: q.max_choices !== null ? q.max_choices : Infinity
        }));

        setAllQuestions(formatted);
        log('Questions chargées:', formatted.length);

        return formatted;

    } catch (error) {
        console.error('Erreur loadQuestions:', error);
        throw error;
    }
}

/**
 * Charge la progression du quiz (mode authentifié)
 */
async function loadQuizProgress(quizId) {
    log('Chargement progression quiz:', quizId);

    try {
        const response = await fetch(`/get_quiz_progress/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) throw new Error('Erreur chargement progression');

        const data = await response.json();

        questionHistory = data.progress?.question_history || [];
        userAnswers = data.answers || {};

        return data;

    } catch (error) {
        console.error('Erreur loadQuizProgress:', error);
        throw error;
    }
}

/**
 * Met à jour la progression sur le serveur (mode authentifié)
 */
async function updateQuizProgress(questionId, answerValue, answerText, quizId, isCompleted = false) {
    log('Mise à jour progression:', questionId);

    const payload = {
        quiz_id: quizId,
        current_question_index: currentQuestionIndex,
        answer: {
            question_id: questionId,
            value: answerValue,
            text: answerText
        },
        is_completed: isCompleted,
        is_reviewing: isEditingFromReview
    };

    try {
        const response = await fetch('/update_quiz_progress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) throw new Error('Erreur mise à jour progression');

        const data = await response.json();
        userAnswers[questionId] = { value: answerValue, text: answerText };

        return data;

    } catch (error) {
        console.error('Erreur updateQuizProgress:', error);
        throw error;
    }
}

/**
 * Met à jour l'historique des questions sur le serveur
 */
async function updateQuestionHistory(quizId, history) {
    try {
        const response = await fetch('/update_quiz_history', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ quiz_id: quizId, question_history: history }),
            credentials: 'same-origin'
        });

        if (!response.ok) throw new Error('Erreur mise à jour historique');

        localStorage.setItem(`quiz_${quizId}_history`, JSON.stringify(history));

    } catch (error) {
        console.error('Erreur updateQuestionHistory:', error);
    }
}

function updateQuizProgress() {
    const container = document.getElementById('quizProgressContainer');
    const progressText = document.getElementById('quizProgressText');
    const steps = document.querySelectorAll('.quiz-progress-step');
    const line1 = document.getElementById('progressLine1');
    const line2 = document.getElementById('progressLine2');
    const line3 = document.getElementById('progressLine3');
    
    if (!container) return;
    container.style.display = 'block';
    
    const currentQuestion = currentChapterQuestionIndex + 1;
    const totalQuestions = 4;
    
    if (progressText) {
        progressText.textContent = 'Étape ' + currentQuestion + ' sur ' + totalQuestions;
    }
    
    steps.forEach(function(step, index) {
        step.classList.remove('active', 'completed');
        var stepNum = step.querySelector('.step-number');
        
        if (index < currentQuestion - 1) {
            step.classList.add('completed');
            if (stepNum) stepNum.textContent = '✓';
        } else if (index === currentQuestion - 1) {
            step.classList.add('active');
            if (stepNum) stepNum.textContent = index + 1;
        } else {
            if (stepNum) stepNum.textContent = index + 1;
        }
    });
    
    if (line1) line1.style.width = currentQuestion > 1 ? '100%' : '0%';
    if (line2) line2.style.width = currentQuestion > 2 ? '100%' : '0%';
    if (line3) line3.style.width = currentQuestion > 3 ? '100%' : '0%';
}

/**
 * Met à jour la progression quand une question est répondue
 */
function updateProgressOnAnswer() {
    var steps = document.querySelectorAll('.quiz-progress-step');
    var progressText = document.getElementById('quizProgressText');
    var line1 = document.getElementById('progressLine1');
    var line2 = document.getElementById('progressLine2');
    var line3 = document.getElementById('progressLine3');
    
    var answeredQuestions = currentChapterQuestionIndex + 1;
    
    if (steps[answeredQuestions - 1]) {
        steps[answeredQuestions - 1].classList.remove('active');
        steps[answeredQuestions - 1].classList.add('completed');
        var stepNum = steps[answeredQuestions - 1].querySelector('.step-number');
        if (stepNum) stepNum.textContent = '✓';
    }
    
    if (answeredQuestions === 1 && line1) line1.style.width = '100%';
    if (answeredQuestions === 2 && line2) line2.style.width = '100%';
    if (answeredQuestions === 3 && line3) line3.style.width = '100%';
    
    if (answeredQuestions > 3) {
        if (progressText) progressText.textContent = 'Bravo, c\'est fini ! 🎉';
    }
}

/**
 * Cache la barre de progression
 */
function hideQuizProgress() {
    const container = document.getElementById('quizProgressContainer');
    if (container) {
        container.style.display = 'none';
    }
}

window.updateQuizProgress = updateQuizProgress;
window.updateProgressOnAnswer = updateProgressOnAnswer;
window.hideQuizProgress = hideQuizProgress;

// ============================================================================
// NAVIGATION - AFFICHAGE QUESTIONS
// ============================================================================

/**
 * Affiche la question courante
 */
async function showQuestion(quizId) {
    // Utiliser le quizId passé ou détecter automatiquement
    const effectiveQuizId = quizId || getQuizId();
    log('Affichage question pour quiz:', effectiveQuizId);

    const quizContent = getElement('#quizContent');
    if (quizContent) quizContent.style.display = 'block';
    
    // Cacher le welcome screen et stopper la vidéo
    const welcomeScreen = document.getElementById('quizWelcome');
    if (welcomeScreen) {
        welcomeScreen.style.display = 'none';
        const video = document.getElementById('welcomeVideo');
        if (video) { video.pause(); video.currentTime = 0; }
    }

    const questions = getAllQuestions();
    if (!questions || questions.length === 0) {
        console.error('Aucune question disponible');
        return;
    }

    const quizForm = getElement('#quizForm');
    if (!quizForm) {
        console.error('Formulaire quiz non trouvé');
        return;
    }

    try {
        const chapter = getCurrentChapter(effectiveQuizId);

        // Fin des chapitres
        if (!chapter) {
            log('Fin des chapitres');
            showCompletion();
            return;
        }

        // Intro du chapitre (si pas encore vue)
        if (chapter.intro && !chapter.introSeen) {
            showChapterIntro(chapter, effectiveQuizId);
            return;
        }

        // Transition entre chapitres
        if (isShowingTransition) {
            showChapterTransition(chapter, effectiveQuizId);
            return;
        }

        // Fin du chapitre actuel
        if (currentChapterQuestionIndex >= chapter.questions.length) {
            const chapters = QUIZ_CHAPTERS[effectiveQuizId]?.chapters || [];

            if (currentChapter < chapters.length - 1 && chapter.transition) {
                isShowingTransition = true;
                showChapterTransition(chapter, effectiveQuizId);
                return;
            } else if (currentChapter >= chapters.length - 1) {
                showCompletion();
                return;
            } else {
                currentChapter++;
                currentChapterQuestionIndex = 0;
                await showQuestion(effectiveQuizId);
                return;
            }
        }

        // Afficher la question normale
        const currentQuestion = getCurrentQuestionInChapter();

        if (!currentQuestion) {
            console.error('Question non trouvée');
            currentChapterQuestionIndex++;
            await showQuestion(effectiveQuizId);
            return;
        }

        quizForm.innerHTML = '';
        const questionElement = createQuestionElement(currentQuestion, effectiveQuizId);
        quizForm.appendChild(questionElement);

        // Tracking
        QuizTracking.trackQuestion(currentChapter + 1, currentChapterQuestionIndex, currentQuestion.id);

        // Restaurer réponse précédente
        const answers = getAnswers();
        if (answers[currentQuestion.id]) {
            restorePreviousAnswer(currentQuestion, quizForm);
        }

        // Mettre à jour la barre de progression
        updateQuizProgress();

        updateProgress();

    } catch (error) {
        console.error('Erreur showQuestion:', error);
        quizForm.innerHTML = `<p class="error">Erreur: ${error.message}</p>`;
    }
}

/**
 * Affiche l'intro d'un chapitre
 */
function showChapterIntro(chapter, quizId) {
    // Désactivé - passage direct à la première question du chapitre
    log('Intro chapitre désactivée, passage direct aux questions');

    chapter.introSeen = true;
    currentChapterQuestionIndex = 0;

    showQuestion(quizId);
}

/**
 * Affiche la transition entre chapitres
 */
function showChapterTransition(chapter, quizId) {
    // Désactivé - passage direct au chapitre suivant sans écran de transition
    log('Transition désactivée, passage au chapitre suivant');

    currentChapter++;
    currentChapterQuestionIndex = 0;
    isShowingTransition = false;

    showQuestion(quizId);
}

// ============================================================================
// NAVIGATION - SUIVANT / PRÉCÉDENT
// ============================================================================

/**
 * Passe à la question suivante
 */
async function nextQuestion(question, quizId = 'pack_clarte') {
    try {
        if (!validateAnswer(question)) return;

        const [answerValue, answerText] = getQuestionAnswer(question);

        // Sauvegarder réponse
        setAnswer(question.id, { value: answerValue, text: answerText });

        // Tracking
        trackAnswer(question, answerValue, answerText);

        // Mettre à jour la progression
        updateProgressOnAnswer();

        // Historique

        const currentState = {
            chapter: currentChapter,
            questionIndex: currentChapterQuestionIndex,
            screenType: 'question',
            questionId: question.id
        };

        const history = getHistory();
        const isDuplicate = history.some(s =>
            s.chapter === currentState.chapter &&
            s.questionIndex === currentState.questionIndex &&
            s.screenType === currentState.screenType
        );

        if (!isDuplicate) pushToHistory(currentState);

        // Sauvegarder selon le mode
        if (isHomepageMode) {
            QuizPersistence.saveQuizState();
        } else {
            await updateQuizProgress(question.id, answerValue, answerText, quizId, false);
            await updateQuestionHistory(quizId, getHistory());
        }

        // Navigation chapitre
        const chapter = getCurrentChapter(quizId);
        if (chapter) {
            currentChapterQuestionIndex++;

            if (currentChapterQuestionIndex < chapter.questions.length) {
                updateProgress();
            }

            // Fin du chapitre ?
            if (currentChapterQuestionIndex >= chapter.questions.length) {
                updateProgress();
                triggerChapterCompletionEffect();

                const chapters = QUIZ_CHAPTERS[quizId]?.chapters || [];

                if (currentChapter < chapters.length - 1 && chapter.transition) {
                    setTimeout(() => {
                        isShowingTransition = true;
                        showQuestion(quizId);
                    }, 400);
                    return;
                } else if (currentChapter >= chapters.length - 1) {
                    setTimeout(() => showCompletion(), 400);
                    return;
                } else {
                    setTimeout(() => {
                        currentChapter++;
                        currentChapterQuestionIndex = 0;
                        updateProgress();
                        showQuestion(quizId);
                    }, 400);
                    return;
                }
            }

            await showQuestion(quizId);
        }

    } catch (error) {
        console.error('Erreur nextQuestion:', error);
        QuizTracking.trackError('navigation_error', error.message, { question_id: question.id });
        alert('Une erreur est survenue: ' + error.message);
    }
}

/**
 * Retourne à la question précédente
 */
async function previousQuestion(quizId = 'pack_clarte') {
    log('Navigation précédent');
    const history = getHistory();
    if (history && history.length > 0) {
        const previousState = popFromHistory();
        QuizTracking.trackBackNavigation(currentChapterQuestionIndex, previousState.questionIndex);
        currentChapter = previousState.chapter;
        currentChapterQuestionIndex = previousState.questionIndex;
        isShowingTransition = previousState.isTransition || false;
        if (previousState.screenType === 'intro') {
            const chapter = getCurrentChapter(quizId);
            if (chapter) chapter.introSeen = false;
        } else if (previousState.screenType === 'transition') {
            isShowingTransition = true;
        }
        await showQuestion(quizId);
    } else {
        currentChapter = 0;
        currentChapterQuestionIndex = 0;
        isShowingTransition = false;
        const firstChapter = getCurrentChapter(quizId);
        if (firstChapter) firstChapter.introSeen = false;
        if (isHomepageMode) {
            const welcome = document.getElementById('quizWelcome');
            const content = document.getElementById('quizContent');
            if (welcome && content) {
                welcome.style.display = 'flex';
                content.style.display = 'none';
                const startBtn = document.getElementById('welcomeStartBtn');
                if (startBtn) {
                    const newBtn = startBtn.cloneNode(true);
                    startBtn.parentNode.replaceChild(newBtn, startBtn);
                    newBtn.addEventListener('click', async function(e) {
                        e.preventDefault();
                        welcome.style.display = 'none';
                        content.style.display = 'block';
                        await showQuestion(quizId);
                    });
                }
            } else {
                await showQuestion(quizId);
            }
        } else {
            await showQuestion(quizId);
        }
    }
}

/**
 * Track une réponse pour analytics
 */
function trackAnswer(question, answerValue, answerText) {
    let answerType = 'choice';
    let answerLength = null;

    if (question.question_type === 'free_text') {
        const isAudio = Array.isArray(answerValue) && answerValue[0]?.startsWith('[AUDIO:');
        answerType = isAudio ? 'audio' : 'text';

        if (isAudio) {
            const state = currentQuestionAudioState[question.id];
            if (state?.duration) QuizTracking.trackAudioRecording(question.id, state.duration);
        } else {
            answerLength = answerValue[0]?.length || 0;
            QuizTracking.trackTextEntry(question.id, answerLength);
        }
    } else if (question.question_type === 'multi_select') {
        answerType = 'multi_choice';
        answerLength = answerValue.length;
    } else if (question.question_type === 'ranking') {
        answerType = 'ranking';
    } else if (question.question_type === 'location') {
        answerType = 'location';
    }

    QuizTracking.trackQuestionAnswer(question.id, question.question, answerType, answerLength);
}

// ============================================================================
// VALIDATION RÉPONSES
// ============================================================================

/**
 * Valide la réponse selon le type de question
 */
function validateAnswer(question) {
    hideError();

    switch (question.question_type) {
        case 'ranking':
            return validateRankingAnswer();
        case 'free_text':
            return validateFreeTextAnswer(question.max_character_input);
        case 'location':
            return validateLocationAnswer();
        default:
            return validateChoiceAnswer(question);
    }
}

function validateRankingAnswer() {
    const items = document.querySelectorAll('.ranking-item');
    if (items.length === 0) {
        showError('noChoiceError');
        return false;
    }
    return true;
}

function validateFreeTextAnswer(maxCharInput) {
    // Cas spécial : Question poste + boîte (68)
    const dualPoste = document.getElementById('dual-input-poste');
    const dualBoite = document.getElementById('dual-input-boite');
    if (dualPoste && dualBoite) {
        if (!dualPoste.value.trim()) {
            showError('emptyPosteError');
            dualPoste.focus();
            return false;
        }
        if (!dualBoite.value.trim()) {
            showError('emptyBoiteError');
            dualBoite.focus();
            return false;
        }
        return true;
    }
    // Cas spécial : Question salaire (61)
    const salaryInput = document.querySelector('.salary-text-input');
    if (salaryInput) {
        const value = salaryInput.value.replace(/\s/g, '');
        
        if (!value) {
            showError('emptySalaryError');
            salaryInput.focus();
            return false;
        }
        
        if (!/^\d+$/.test(value)) {
            showError('invalidSalaryError');
            salaryInput.focus();
            return false;
        }
        
        const num = parseInt(value);
        if (num < 1000) {
            showError('tooLowSalaryError');
            salaryInput.focus();
            return false;
        }
        
        if (num > 999999) {
            showError('tooHighSalaryError');
            salaryInput.focus();
            return false;
        }
        
        return true;
    }

    // Questions normales (audio/texte) - Nouveau système de choix
    const questionId = getCurrentQuestionId();
    const state = currentQuestionAudioState[questionId];
    
    const choiceScreen = document.querySelector('.response-choice-screen');
    const audioContainer = document.querySelector('.enhanced-audio-container');
    const textContainer = document.querySelector('.text-mode-container');
    
    // Vérifier si un mode a été choisi
    const choiceScreenVisible = choiceScreen && choiceScreen.style.display !== 'none';
    const selectedMode = state?.selectedMode;
    
    if (choiceScreenVisible || !selectedMode) {
        showError('noModeSelectedError');
        return false;
    }
    
    // Validation selon le mode sélectionné
    if (selectedMode === 'audio') {
        // Mode audio
        if (!state?.audioBlob) {
            showError('noAudioRecordingError');
            return false;
        }

        if (state.duration < MIN_RECORDING_TIME) {
            showError('shortAudioError');
            return false;
        }
        
        return true;
        
    } else if (selectedMode === 'text') {
        // Mode texte
        const textArea = textContainer?.querySelector('.free-text-input');
        
        if (!textArea) {
            showError('erreurTechnique');
            return false;
        }
        
        const text = textArea.value.trim();
        
        if (!text) {
            showError('emptyTextAreaError');
            textArea.focus();
            return false;
        }
        
        if (text.length < MIN_TEXT_LENGTH) {
            showError('shortTextAreaError');
            textArea.focus();
            return false;
        }
        
        const maxLen = Math.min(maxCharInput || MAX_TEXT_LENGTH, MAX_TEXT_LENGTH);
        if (text.length > maxLen) {
            showError('longTextAreaError', { max: maxLen });
            return false;
        }
        
        return true;
    }
    
    // Fallback
    showError('erreurTechnique');
    return false;
}

function validateLocationAnswer() {
    const input = document.querySelector('.location-input');
    const data = document.querySelector('.location-data');

    if (!input?.value.trim()) {
        showError('emptyLocationError');
        return false;
    }

    try {
        const parsed = JSON.parse(data.value);
        if (!parsed?.name) {
            showError('invalidLocationError');
            return false;
        }
    } catch (e) {
        showError('invalidLocationError');
        return false;
    }

    return true;
}

function validateChoiceAnswer(question) {
    const selected = document.querySelectorAll('.tag.selected, .choice-card.selected');

    if (selected.length === 0) {
        if (question.question_type === 'multi_select' && question.min_choices > 0) {
            showError('minChoicesError', { min: question.min_choices });
        } else {
            showError('noChoiceError');
        }
        return false;
    }

    // Vérifier mélange "autre" et choix normaux
    if (question.question_type === 'multi_select') {
        const hasOther = Array.from(selected).some(t => t.textContent.trim().toLowerCase() === 'autre');
        const hasNormal = Array.from(selected).some(t => t.textContent.trim().toLowerCase() !== 'autre');

        if (hasOther && hasNormal) {
            showError('mixedChoicesError');
            return false;
        }
    }

    if (question.min_choices && selected.length < question.min_choices) {
        showError('minChoicesError', { min: question.min_choices });
        return false;
    }

    if (question.max_choices && selected.length > question.max_choices) {
        showError('maxChoicesError', { max: question.max_choices });
        return false;
    }

    // Valider input "autre"
    const otherTag = Array.from(selected).find(t => t.textContent.trim().toLowerCase() === 'autre');
    if (otherTag) {
        return validateOtherInput(parseInt(otherTag.dataset.maxCharacterInput, 10) || 70);
    }

    return true;
}

function validateOtherInput(maxLength) {
    const input = document.querySelector('.other-input');
    if (input && input.style.display !== 'none') {
        const text = input.value.trim();
        if (!text) { showError('emptyOtherError'); return false; }
        if (text.length > maxLength) { showError('longInputError', { max: maxLength }); return false; }
    }
    return true;
}

// ============================================================================
// GESTION ERREURS
// ============================================================================

function showError(errorType, params = {}) {
    const el = document.querySelector('.choices-error');
    if (!el) return;

    const messages = {
        // Erreurs générales
        noChoiceError: '👆 Sélectionne une réponse pour continuer',
        
        // Choix mode audio/texte
        noModeSelectedError: '🎙️ Choisis si tu veux parler ou écrire pour continuer',
        
        // Erreurs texte
        emptyTextAreaError: '✍️ Écris ta réponse pour continuer',
        shortTextAreaError: '✍️ Développe un peu plus ta réponse, ça m\'aidera à mieux t\'analyser',
        longTextAreaError: '📝 Ta réponse est trop longue (maximum ' + (params.max || 2000) + ' caractères)',
        
        // Erreurs audio
        noAudioRecordingError: '🎙️ Appuie sur le micro pour enregistrer ta réponse',
        shortAudioError: '🎙️ Développe un peu plus, ça m\'aide à mieux te comprendre',
        
        // Erreurs localisation
        emptyLocationError: '📍 Indique ta ville pour continuer',
        invalidLocationError: '📍 Sélectionne une ville dans la liste',
        
        // Erreurs choix multiples
        minChoicesError: '👆 Sélectionne au moins ' + (params.min || 1) + ' réponse(s)',
        maxChoicesError: '✋ Tu peux sélectionner ' + (params.max || 3) + ' réponse(s) maximum',
        emptyOtherError: '✍️ Précise ta réponse',
        longInputError: '📝 Ta réponse est trop longue (maximum ' + (params.max || 70) + ' caractères)',
        mixedChoicesError: '🚫 Tu ne peux pas mélanger "Autre" avec d\'autres choix',
        
        // Erreurs salaire (Q61)
        emptySalaryError: '💰 Indique le salaire souhaité pour continuer',
        invalidSalaryError: '🔢 Saisis uniquement des chiffres',
        tooLowSalaryError: '💰 Le salaire semble un peu faible. Vérifie ta saisie.',
        tooHighSalaryError: '💰 Le salaire semble très élevé. Vérifie ta saisie.',

        // Erreurs postes (Q70)
        emptyPosteError: '💼 Indique ton poste actuel/dernier poste pour continuer',
        emptyBoiteError: '🏢 Indique le nom de ta boîte/dernière boîte pour continuer',
        
        // Erreur technique
        erreurTechnique: '⚠️ Oups, une erreur technique est survenue'
    };

    el.textContent = messages[errorType] || 'Erreur';
    el.style.display = 'block';
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function hideError() {
    const el = document.querySelector('.choices-error');
    if (el) el.style.display = 'none';
}

function hideError() {
    const el = document.querySelector('.choices-error');
    if (el) el.style.display = 'none';
}

// ============================================================================
// RÉCUPÉRATION RÉPONSES
// ============================================================================

function getQuestionAnswer(question) {
    switch (question.question_type) {
        case 'ranking': return getRankingAnswer();
        case 'free_text': return getFreeTextAnswer();
        case 'location': return getLocationAnswer();
        case 'multi_select': return getMultiSelectAnswer();
        default: return getSingleChoiceAnswer();
    }
}

function getRankingAnswer() {
    const items = document.querySelectorAll('.ranking-item');
    const values = Array.from(items).map(i => i.dataset.value);
    const texts = Array.from(items).map(i => i.querySelector('.choice-text').textContent);
    return [values, texts.join(' > ')];
}

function getFreeTextAnswer() {
    // Cas spécial : Question poste + boîte (70)
    const dualPoste = document.getElementById('dual-input-poste');
    const dualBoite = document.getElementById('dual-input-boite');
    if (dualPoste && dualBoite) {
        const combined = dualPoste.value.trim() + ' — ' + dualBoite.value.trim();
        return [[combined], combined];
    }
    // Question salaire
    const salaryInput = document.querySelector('.salary-text-input');
    if (salaryInput) {
        const value = salaryInput.value.replace(/\s/g, '');
        return [[value], value];
    }

    // Questions normales - Nouveau système de choix
    const questionId = getCurrentQuestionId();
    const state = currentQuestionAudioState[questionId];
    const selectedMode = state?.selectedMode;
    
    if (!selectedMode) {
        return [[''], ''];
    }
    
    if (selectedMode === 'text') {
        // Mode texte
        const textContainer = document.querySelector('.text-mode-container');
        const textArea = textContainer?.querySelector('.free-text-input');
        
        if (textArea && textArea.value.trim()) {
            return [[textArea.value.trim()], textArea.value.trim()];
        }
        return [[''], ''];
    }
    
    if (selectedMode === 'audio') {
        // Mode audio
        if (state?.audioBlob) {
            // Trouver ou créer l'ID audio
            let audioId = null;

            if (window.tempQuizAudios) {
                for (const [id, data] of Object.entries(window.tempQuizAudios)) {
                    if (data.questionId == questionId) {
                        audioId = id;
                        break;
                    }
                }
            }

            if (!audioId) {
                audioId = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                if (!window.tempQuizAudios) window.tempQuizAudios = {};
                window.tempQuizAudios[audioId] = {
                    blob: state.audioBlob,
                    url: state.audioURL,
                    questionId: questionId,
                    duration: state.duration || 0
                };
            }

            return [[`[AUDIO:${audioId}]`], `[Audio - ${state.duration || 0}s]`];
        }
    }

    return [[''], ''];
}

function getLocationAnswer() {
    const input = document.querySelector('.location-input');
    const data = document.querySelector('.location-data');
    const value = input?.value.trim() || '';

    let fullData = {};
    try { fullData = JSON.parse(data?.value || '{}'); } catch (e) {}

    return [[value], fullData.display_name || value];
}

function getMultiSelectAnswer() {
    const selected = document.querySelectorAll('.tag.selected, .choice-card.selected');
    const values = Array.from(selected).map(t => t.dataset.value);

    const otherTag = Array.from(selected).find(t => t.textContent.toLowerCase().includes('autre'));
    if (otherTag) {
        const input = document.querySelector('.other-input');
        if (input?.value.trim()) {
            return [values, input.value.trim()];
        }
    }

    const texts = Array.from(selected).map(t => {
        const title = t.querySelector('.choice-card-title');
        return title ? title.textContent.trim() : t.textContent.trim();
    });

    return [values, texts.join(', ')];
}

function getSingleChoiceAnswer() {
    const selected = document.querySelector('.tag.selected, .choice-card.selected');
    if (!selected) throw new Error('Aucune réponse sélectionnée');

    const value = [selected.dataset.value];
    let text;

    if (selected.textContent.trim().toLowerCase() === 'autre') {
        const input = document.querySelector('.other-input');
        text = input?.value.trim() || selected.textContent.trim();
    } else {
        const title = selected.querySelector('.choice-card-title');
        text = title ? title.textContent.trim() : selected.textContent.trim();
    }

    return [value, text];
}

// ============================================================================
// RESTAURATION RÉPONSES
// ============================================================================

function restorePreviousAnswer(question, quizForm) {
    const answers = getAnswers();
    const answer = answers[question.id];
    if (!answer) return;

    switch (question.question_type) {
        case 'free_text':
            restoreFreeTextAnswer(quizForm, answer, question.max_character_input);
            break;
        case 'ranking':
            restoreRankingAnswer(quizForm, answer);
            break;
        case 'location':
            restoreLocationAnswer(quizForm, answer);
            break;
        default:
            restoreChoiceAnswer(quizForm, answer);
    }
}

function restoreFreeTextAnswer(quizForm, answer, maxCharInput) {
    // Cas spécial : dual input (question 70)
    const dualPoste = quizForm.querySelector('#dual-input-poste');
    const dualBoite = quizForm.querySelector('#dual-input-boite');
    if (dualPoste && dualBoite && answer.value?.[0]) {
        const parts = answer.value[0].split(' — ');
        dualPoste.value = parts[0] || '';
        dualBoite.value = parts[1] || '';
        return;
    }
    const choiceScreen = quizForm.querySelector('.response-choice-screen');
    const audioContainer = quizForm.querySelector('.enhanced-audio-container');
    const textContainer = quizForm.querySelector('.text-mode-container');
    const textArea = textContainer?.querySelector('.free-text-input');
    const charCount = textContainer?.querySelector('.char-count');
    const questionId = getCurrentQuestionId();

    if (!choiceScreen || !audioContainer || !textContainer) {
        console.error('Éléments manquants dans restoreFreeTextAnswer');
        return;
    }

    const isAudioAnswer = Array.isArray(answer.value) && 
                          answer.value[0]?.startsWith('[AUDIO:');

    // Cacher l'écran de choix dans tous les cas
    choiceScreen.style.display = 'none';

    if (isAudioAnswer) {
        // Mode audio
        console.log('Restauration mode vocal');
        
        // Tracker le mode
        if (currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId].selectedMode = 'audio';
        }
        
        audioContainer.style.display = 'block';
        textContainer.style.display = 'none';

        try {
            const audioId = answer.value[0].match(/\[AUDIO:(.+)\]/)?.[1];
            console.log('Restauration audio ID:', audioId);

            if (audioId && window.tempQuizAudios?.[audioId]) {
                const data = window.tempQuizAudios[audioId];

                // Initialiser l'état si nécessaire
                if (!currentQuestionAudioState[questionId]) {
                    currentQuestionAudioState[questionId] = {
                        audioBlob: null,
                        audioURL: null,
                        isRecording: false,
                        duration: 0,
                        selectedMode: 'audio'
                    };
                }

                // Créer une nouvelle URL si nécessaire
                let audioURL = data.url;
                if (!audioURL && data.blob) {
                    audioURL = URL.createObjectURL(data.blob);
                    window.tempQuizAudios[audioId].url = audioURL;
                }

                // Restaurer complètement l'état audio
                currentQuestionAudioState[questionId].audioBlob = data.blob;
                currentQuestionAudioState[questionId].audioURL = audioURL;
                currentQuestionAudioState[questionId].duration = data.duration || 0;
                currentQuestionAudioState[questionId].isRecording = false;
                currentQuestionAudioState[questionId].selectedMode = 'audio';

                // Mettre à jour les variables globales
                audioBlob = data.blob;
                window.audioURL = audioURL;
                isRecording = false;

                console.log('État audio restauré pour question:', questionId);

                // Mettre à jour l'interface après un court délai
                setTimeout(() => {
                    updateAudioDisplayState(audioContainer, currentQuestionAudioState[questionId]);

                    // Configurer l'élément audio
                    const audioElement = audioContainer.querySelector('.audio-element');
                    if (audioElement && currentQuestionAudioState[questionId].audioURL) {
                        audioElement.src = currentQuestionAudioState[questionId].audioURL;
                        audioElement.load();
                        audioElement.style.display = 'block';
                    }
                }, 100);

            } else {
                console.warn('Audio non trouvé pour ID:', audioId);
                setTimeout(() => {
                    updateAudioDisplayState(audioContainer, {
                        audioBlob: null,
                        audioURL: null,
                        isRecording: false,
                        duration: 0
                    });
                }, 100);
            }
        } catch (e) {
            console.error('Erreur lors de la restauration audio:', e);
        }

    } else {
        // Mode texte
        console.log('Restauration mode texte');
        
        // Tracker le mode
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0,
                selectedMode: 'text'
            };
        }
        currentQuestionAudioState[questionId].selectedMode = 'text';
        
        audioContainer.style.display = 'none';
        textContainer.style.display = 'block';
        
        if (textArea) {
            textArea.value = answer.value?.[0] || '';
            textArea.disabled = false;
        }
        
        if (charCount) {
            updateCharCount(textArea, charCount, maxCharInput || MAX_TEXT_LENGTH);
        }
    }
}

function addBackToAudioButton(quizForm, textArea, audioContainer, charCount) {
    if (quizForm.querySelector('.back-to-audio-btn')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'back-to-audio-btn';
    btn.innerHTML = '🎙️ Finalement, je préfère parler';
    btn.style.cssText = `
        margin-top:1rem;padding:0.5rem 1rem;background:none;
        border:1px solid #A11857;color:#A11857;border-radius:8px;
        font-size:0.85rem;cursor:pointer;opacity:0.7;
    `;

    btn.addEventListener('click', (e) => {
        e.preventDefault();
        const questionId = getCurrentQuestionId();
        const answers = getAnswers();
        if (answers[questionId]) delete answers[questionId];

        textArea.value = '';
        audioContainer.style.display = 'block';
        textArea.style.display = 'none';
        if (charCount) charCount.style.display = 'none';
        btn.remove();
    });

    textArea.parentNode.appendChild(btn);
}

function restoreRankingAnswer(quizForm, answer) {
    const list = quizForm.querySelector('.ranking-list');
    if (!list || !Array.isArray(answer.value)) return;

    const items = Array.from(list.querySelectorAll('.ranking-item'));
    answer.value.forEach(value => {
        const item = items.find(i => i.dataset.value === value);
        if (item) list.appendChild(item);
    });
    updateRankNumbers();
}

function restoreLocationAnswer(quizForm, answer) {
    const input = quizForm.querySelector('.location-input');
    const data = quizForm.querySelector('.location-data');

    if (input && answer.value) {
        input.value = answer.value[0] || '';
        if (data) {
            data.value = JSON.stringify({ name: answer.value[0], display_name: answer.text });
        }
    }
}

function restoreChoiceAnswer(quizForm, answer) {
    const tags = quizForm.querySelectorAll('.tag, .choice-card');
    tags.forEach(t => t.classList.remove('selected'));

    tags.forEach(tag => {
        if (answer.value.includes(tag.dataset.value)) {
            tag.classList.add('selected');

            if (tag.textContent.trim().toLowerCase() === 'autre') {
                const container = quizForm.querySelector('.other-input-container');
                const input = container?.querySelector('.other-input');
                if (input && container) {
                    input.value = answer.text;
                    container.style.display = 'block';
                }
            }
        }
    });
}

// ============================================================================
// CRÉATION UI - QUESTIONS
// ============================================================================

/**
 * Crée l'élément DOM pour une question
 */
function createQuestionElement(question, quizId = 'pack_clarte') {
    const div = document.createElement('div');
    div.className = 'question active';
    div.id = 'question-' + question.id;

    try {
        if (question.media_type === 'image' && question.media_url) {
            appendQuestionImage(div, question.media_url);
        }

        appendQuestionTitle(div, question.question, question);
        appendQuestionHint(div, question);

        if (question.question_type === 'multi_select') {
            appendChoiceInstructions(div, question);
        }

        switch (question.question_type) {
            case 'location':
                appendLocationInput(div);
                break;
            case 'free_text':
                appendFreeTextInput(div, question.max_character_input || MAX_TEXT_LENGTH);
                break;
            case 'ranking':
                appendRankingList(div, question);
                break;
            default:
                if (question.choices?.length > 0) {
                    appendChoiceList(div, question);
                }
        }

        appendErrorElement(div);
        appendButtonContainer(div, quizId);

    } catch (error) {
        console.error('Erreur création question:', error);
        div.textContent = `Erreur: ${error.message}`;
    }

    return div;
}

function appendQuestionImage(div, url) {
    const img = document.createElement('img');
    img.src = url;
    img.alt = 'Question Image';
    img.className = 'question-image';
    div.appendChild(img);
}

function appendQuestionTitle(div, text, question) {
    const title = document.createElement('h2');
    title.className = 'question-title';
    title.innerHTML = `<span class="question-text">${text}</span>`;

    // Description pour cartes 4 choix
    const hasDescription = question?.question_description &&
        question.question_type === 'select' &&
        question.choices?.length === 4;

    // Pour la première question (id 63), inverser : description puis titre
    if (question?.id == 63 && hasDescription) {
        const desc = document.createElement('div');
        desc.className = 'question-description';
        desc.textContent = question.question_description;
        div.appendChild(desc);
        div.appendChild(title);
    } else {
        div.appendChild(title);
        if (hasDescription) {
            const desc = document.createElement('div');
            desc.className = 'question-description';
            desc.textContent = question.question_description;
            div.appendChild(desc);
        }
    }
}

function appendQuestionHint(div, question) {
    var helpers = {
        67: {
            intro: "Quelques idées pour répondre :",
            items: [
                "Tu peux parler de ta situation pro & perso",
                "Ton état d'esprit du moment",
                "Tes points de frustration",
                "Et au contraire ce qui te motive"
            ]
        },
        68: {
            intro: "Quelques idées pour répondre :",
            items: [
                "Tu peux décrire l'environnement de travail et les conditions (ex: travail en équipe, télétravail…)"
            ]
        },
        69: {
            intro: "Quelques idées pour répondre :",
            items: [
                "Pense à ce qui t'apporte de l'énergie au quotidien",
                "Les sujets sur lesquels on te demande souvent conseil"
            ]
        }
    };

    var helper = helpers[question.id];
    if (!helper) return;

    var helperDiv = document.createElement('div');
    helperDiv.className = 'question-helper';
    
    var html = '<div class="question-helper-toggle">';
    html += '<span class="helper-icon">💡</span>';
    html += '<span class="helper-label">' + helper.intro + '</span>';
    html += '<span class="helper-chevron">▼</span>';
    html += '</div>';
    html += '<ul class="question-helper-list">';
    helper.items.forEach(function(item) {
        html += '<li>' + item + '</li>';
    });
    html += '</ul>';
    
    helperDiv.innerHTML = html;
    
    // Insérer après le titre
    var title = div.querySelector('.question-title');
    if (title && title.nextSibling) {
        div.insertBefore(helperDiv, title.nextSibling);
    } else {
        div.appendChild(helperDiv);
    }
    
    // Toggle au clic
    var toggle = helperDiv.querySelector('.question-helper-toggle');
    var list = helperDiv.querySelector('.question-helper-list');
    toggle.addEventListener('click', function() {
        helperDiv.classList.toggle('open');
        list.classList.toggle('open');
    });
}

function appendChoiceInstructions(div, question) {
    const inst = document.createElement('div');
    inst.className = 'choice-instructions';

    const isInfinite = !question.max_choices || question.max_choices === Infinity;
    let text = '';

    if (isInfinite && !question.min_choices) {
        text = 'Sélectionne autant de réponses que tu le souhaites';
    } else if (question.min_choices && isInfinite) {
        text = `Sélectionne au moins ${question.min_choices} réponse(s)`;
    } else if (question.min_choices && question.max_choices) {
        if (question.min_choices === question.max_choices) {
            text = `Sélectionne exactement ${question.min_choices} réponse(s)`;
        } else {
            text = `Sélectionne entre ${question.min_choices} et ${question.max_choices} réponses`;
        }
    } else if (question.max_choices) {
        text = `Sélectionne au maximum ${question.max_choices} réponse(s)`;
    }

    if (text) {
        inst.innerHTML = `<p class="instruction-text"><span class="instruction-icon">✨</span> ${text}</p>`;
        const title = div.querySelector('.question-title');
        if (title?.nextSibling) {
            div.insertBefore(inst, title.nextSibling);
        } else {
            div.appendChild(inst);
        }
    }
}

function appendErrorElement(div) {
    const err = document.createElement('div');
    err.className = 'choices-error';
    err.style.display = 'none';
    div.appendChild(err);
}

// ============================================================================
// CRÉATION UI - CHOIX
// ============================================================================

function appendChoiceList(div, question) {
    const list = document.createElement('div');

    const isCardGrid = question.question_type === 'select' &&
                       question.choices?.length === 4 &&
                       question.choices.some(c => c.choice_description);

    list.className = isCardGrid
        ? `choice-cards-grid choice-cards-grid-question-${question.id}`
        : `tag-list tag-list-question-${question.id}`;

    list.addEventListener('click', e => e.stopPropagation());

    question.choices.forEach(choice => {
        if (choice?.value !== undefined && choice?.text !== undefined) {
            const tag = createChoiceTag(choice, question);
            list.appendChild(tag);
        }
    });

    div.appendChild(list);

    // Input "autre"
    if (question.choices.some(c => c.text.trim().toLowerCase() === 'autre')) {
        appendOtherInputContainer(div, question.choices);
    }
}

function createChoiceTag(choice, question) {
    const tag = document.createElement('div');

    const isCard = question.question_type === 'select' &&
                   question.choices?.length === 4 &&
                   choice.choice_description;

    if (isCard) {
        tag.className = 'choice-card';
        tag.dataset.value = choice.value;
        tag.innerHTML = `
            <div class="choice-card-emoji">${choice.choice_media_url || '❓'}</div>
            <div class="choice-card-content">
                <div class="choice-card-title">${choice.text}</div>
                ${choice.choice_description ? `<div class="choice-card-description">${choice.choice_description}</div>` : ''}
            </div>
        `;
    } else {
        tag.className = 'tag';
        tag.dataset.value = choice.value;
        tag.dataset.maxCharacterInput = choice.max_character_input || '2000';

        const imgContainer = document.createElement('div');
        imgContainer.className = 'image-container';

        if (choice.choice_media_type === 'emoji' && choice.choice_media_url) {
            const emoji = document.createElement('span');
            emoji.className = 'choice-emoji';
            emoji.textContent = choice.choice_media_url;
            imgContainer.appendChild(emoji);
        } else if (choice.choice_media_type === 'image' && choice.choice_media_url) {
            const img = document.createElement('img');
            img.src = choice.choice_media_url;
            img.alt = choice.text;
            img.className = 'choice-image';
            imgContainer.appendChild(img);
        }

        tag.appendChild(imgContainer);

        if (!choice.choice_media_type || !choice.choice_media_url) {
            const span = document.createElement('span');
            span.className = 'choice-text';
            span.textContent = choice.text;
            tag.appendChild(span);
        }
    }

    tag.addEventListener('click', (e) => {
        e.stopPropagation();
        e.preventDefault();
        selectChoice(tag, question);
    });

    return tag;
}

function selectChoice(tag, question) {
    if (tag.dataset.processing === 'true') return;
    tag.dataset.processing = 'true';

    hideError();

    const container = tag.parentElement;
    const allTags = Array.from(container.children).filter(c =>
        c.classList.contains('tag') || c.classList.contains('choice-card')
    );

    const isOther = tag.textContent.trim().toLowerCase() === 'autre';

    if (question.question_type !== 'multi_select') {
        // Single select
        allTags.forEach(t => { if (t !== tag) t.classList.remove('selected'); });
        tag.classList.add('selected');
    } else {
        // Multi select
        if (isOther) {
            allTags.forEach(t => { if (t !== tag) t.classList.remove('selected'); });
        } else {
            const otherTag = allTags.find(t => t.textContent.trim().toLowerCase() === 'autre');
            if (otherTag?.classList.contains('selected')) {
                otherTag.classList.remove('selected');
                const otherContainer = document.querySelector('.other-input-container');
                if (otherContainer) {
                    otherContainer.style.display = 'none';
                    const input = otherContainer.querySelector('.other-input');
                    if (input) input.value = '';
                }
            }
        }
        tag.classList.toggle('selected');
    }

    // Input "autre"
    const otherContainer = document.querySelector('.other-input-container');
    if (otherContainer && isOther) {
        const isSelected = tag.classList.contains('selected');
        otherContainer.style.display = isSelected ? 'block' : 'none';
        if (isSelected) {
            const input = otherContainer.querySelector('.other-input');
            if (input) {
                input.focus();
                const maxLen = parseInt(tag.dataset.maxCharacterInput, 10) || 70;
                input.maxLength = maxLen;
            }
        }
    }

    setTimeout(() => { tag.dataset.processing = 'false'; }, 100);
}

function appendOtherInputContainer(div, choices) {
    const otherChoice = choices.find(c => c.text.toLowerCase() === 'autre');
    const maxLen = otherChoice?.max_character_input || 70;

    const container = document.createElement('div');
    container.className = 'other-input-container';
    container.style.display = 'none';

    const input = document.createElement('textarea');
    input.className = 'other-input';
    input.placeholder = 'Précisez votre réponse...';
    input.maxLength = maxLen;

    const count = document.createElement('div');
    count.className = 'char-count';
    count.textContent = `0 / ${maxLen}`;

    input.addEventListener('input', () => updateCharCount(input, count, maxLen));

    container.appendChild(input);
    container.appendChild(count);
    div.appendChild(container);
}

// ============================================================================
// CRÉATION UI - INPUTS SPÉCIAUX
// ============================================================================

function appendFreeTextInput(div, maxCharInput) {
    const maxLen = Math.min(maxCharInput || MAX_TEXT_LENGTH, MAX_TEXT_LENGTH);
    const questionId = div.id.replace('question-', '') || `q_${Date.now()}`;
    const isSalary = questionId === '61';

    const container = document.createElement('div');
    container.className = 'free-text-input-container';

    const isDualInput = questionId === '70';

    if (isDualInput) {
        container.innerHTML = `
            <div class="dual-input-group">
                <div class="dual-input-field">
                    <label class="dual-input-label">Ton poste actuel/dernier poste</label>
                    <input type="text" class="dual-input" id="dual-input-poste" placeholder="Ex: Chef de projet, Développeur, Commercial..." maxlength="100" autocomplete="off">
                </div>
                <div class="dual-input-field">
                    <label class="dual-input-label">Nom de ta boîte/dernière boîte</label>
                    <input type="text" class="dual-input" id="dual-input-boite" placeholder="Ex: Decathlon, freelance, startup..." maxlength="100" autocomplete="off">
                </div>
            </div>
        `;
        div.appendChild(container);
        return;
    }

    if (isSalary) {
        // Question salaire : texte simple
        const textArea = document.createElement('textarea');
        textArea.className = 'free-text-input salary-text-input';
        textArea.maxLength = 20;
        textArea.placeholder = 'Exemple: 2000';
        textArea.rows = 1;
        textArea.style.resize = 'none';

        const charCount = document.createElement('div');
        charCount.className = 'char-count';
        charCount.innerHTML = '<span class="char-count-text">0 / 20</span>';

        textArea.addEventListener('input', (e) => {
            let value = e.target.value.replace(/[^\d\s]/g, '').slice(0, 20);
            e.target.value = value;
            updateCharCount(e.target, charCount, 20);
        });

        container.appendChild(textArea);
        container.appendChild(charCount);

    } else {
        // Écran de choix initial
        const choiceScreen = document.createElement('div');
        choiceScreen.className = 'response-choice-screen';
        choiceScreen.innerHTML = `
            <div class="audio-first-choice">
                <button type="button" class="audio-first-btn" data-mode="audio">
                    <span class="audio-first-btn__icon">🎙️</span>
                    <span class="audio-first-btn__label">Répondre en vocal</span>
                    <span class="audio-first-btn__badge">Recommandé</span>
                </button>
                <button type="button" class="audio-first-text-link" data-mode="text">✍️ Je préfère écrire</button>
            </div>
        `;

        // Container audio (caché par défaut)
        const audioContainer = document.createElement('div');
        audioContainer.className = 'enhanced-audio-container';
        audioContainer.style.display = 'none';
        audioContainer.innerHTML = `
            <div class="mic-central-container">
                <div class="circular-progress">
                    <svg class="progress-ring" viewBox="0 0 160 160">
                        <circle class="progress-ring-background" cx="80" cy="80" r="70" fill="none" stroke="#e5e7eb" stroke-width="6"/>
                        <circle class="progress-ring-bar" cx="80" cy="80" r="70" fill="none" stroke="url(#progressGradient${questionId})" stroke-width="6" stroke-linecap="round" transform="rotate(-90 80 80)" stroke-dasharray="439.8" stroke-dashoffset="439.8"/>
                        <defs>
                            <linearGradient id="progressGradient${questionId}" x1="0%" y1="0%" x2="100%" y2="0%">
                                <stop offset="0%" style="stop-color:#10b981"/>
                                <stop offset="75%" style="stop-color:#f59e0b"/>
                                <stop offset="100%" style="stop-color:#ef4444"/>
                            </linearGradient>
                        </defs>
                    </svg>
                    <div class="voice-feedback-halo"></div>
                    <button type="button" class="enhanced-mic-button">
                        <div class="mic-icon">🎙️</div>
                    </button>
                </div>
                <div class="audio-status-container">
                    <div class="status-message ready" data-question-id="${questionId}"></div>
                    <div class="tap-to-speak">Appuie pour parler</div>
                    <div class="status-message recording" style="display:none">
                        <div class="recording-indicator">
                            <div class="red-dot"></div>
                            <span class="static-message">Enregistrement en cours...</span>
                        </div>
                    </div>
                    <div class="status-message completed" style="display:none">Merci pour ton partage</div>
                </div>
                <div class="enhanced-timer" style="display:none">
                    <span class="timer-display">0:00</span>
                    <span class="timer-hint"><span style="margin-right:0.3em">/</span>2 min max</span>
                </div>
                <div class="encouragement-bubble" style="display:none">
                    <div class="bubble-content"></div>
                </div>
                <div class="post-recording-controls" style="display:none">
                    <div class="control-buttons">
                        <button type="button" class="control-btn listen-btn">
                            <i class="fas fa-headphones btn-icon"></i> Écouter
                        </button>
                        <button type="button" class="control-btn rerecord-btn">
                            <i class="fas fa-redo btn-icon"></i> Réenregistrer
                        </button>
                    </div>
                </div>
                <audio class="audio-element" style="display:none"></audio>
            </div>
            <button type="button" class="switch-mode-link" data-switch-to="text">
                ✍️ Finalement, je préfère écrire
            </button>
        `;

        // Container texte (caché par défaut)
        const textContainer = document.createElement('div');
        textContainer.className = 'text-mode-container';
        textContainer.style.display = 'none';
        textContainer.innerHTML = `
            <textarea class="free-text-input expanded-textarea" placeholder="Partage tes idées ici..." maxlength="${maxLen}"></textarea>
            <div class="char-count"><span class="char-count-text">0 / ${maxLen}</span></div>
            <button type="button" class="switch-mode-link" data-switch-to="audio">
                🎙️ Finalement, je préfère parler
            </button>
        `;

        container.appendChild(choiceScreen);
        container.appendChild(audioContainer);
        container.appendChild(textContainer);

        // Initialiser état audio
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0
            };
        }

        // Configurer événements
        setTimeout(() => {
            const textArea = textContainer.querySelector('.free-text-input');
            const charCount = textContainer.querySelector('.char-count');
            const choiceBtns = choiceScreen.querySelectorAll('[data-mode]');
            const switchLinks = container.querySelectorAll('.switch-mode-link');

            // Fonction pour afficher un mode
            const showMode = (mode) => {
                choiceScreen.style.display = 'none';
                
                // AJOUT: Tracker le mode sélectionné
                if (currentQuestionAudioState[questionId]) {
                    currentQuestionAudioState[questionId].selectedMode = mode;
                }
                
                if (mode === 'audio') {
                    audioContainer.style.display = 'block';
                    textContainer.style.display = 'none';
                } else {
                    audioContainer.style.display = 'none';
                    textContainer.style.display = 'block';
                    textArea.focus();
                }
            };

            // Boutons de choix initial
            choiceBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    showMode(btn.dataset.mode);
                });
            });

            // Liens pour changer de mode
            switchLinks.forEach(link => {
                link.addEventListener('click', () => {
                    showMode(link.dataset.switchTo);
                });
            });

            // Message d'invitation audio
            const readyMsg = audioContainer.querySelector('.status-message.ready');
            if (readyMsg) {
                readyMsg.textContent = QUESTION_INVITATION_MESSAGES[questionId] || QUESTION_INVITATION_MESSAGES['default'];
            }

            // Events audio
            setupEnhancedAudioEvents(audioContainer, textArea, charCount, questionId, maxLen);
            setupStaticRecordingMessage(audioContainer, questionId);

            // Event textarea
            textArea.addEventListener('input', () => {
                updateCharCount(textArea, charCount, maxLen);
            });

        }, 100);
    }

    div.appendChild(container);
}

function appendLocationInput(div) {
    const container = document.createElement('div');
    container.className = 'location-container';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'location-input';
    input.placeholder = 'Entrez votre ville';
    input.autocomplete = 'off';

    const suggestions = document.createElement('div');
    suggestions.className = 'suggestions-container';
    suggestions.style.display = 'none';

    const data = document.createElement('input');
    data.type = 'hidden';
    data.className = 'location-data';

    container.appendChild(input);
    container.appendChild(data);
    container.appendChild(suggestions);
    div.appendChild(container);

    let timer;
    input.addEventListener('input', (e) => {
        clearTimeout(timer);
        const term = e.target.value;

        if (term.length < 3) {
            suggestions.style.display = 'none';
            return;
        }

        timer = setTimeout(() => {
            fetchCities(term).then(cities => displaySuggestions(cities, suggestions, input, data));
        }, 300);
    });

    document.addEventListener('click', (e) => {
        if (!container.contains(e.target)) suggestions.style.display = 'none';
    });
}

async function fetchCities(term) {
    try {
        const response = await fetch(`/api/cities?search=${encodeURIComponent(term)}`, {
            headers: { 'Accept': 'application/json' }
        });
        if (!response.ok) return [];
        return await response.json();
    } catch (e) {
        console.error('Erreur fetchCities:', e);
        return [];
    }
}

function displaySuggestions(cities, container, input, dataInput) {
    container.innerHTML = '';

    if (!cities?.length) {
        container.style.display = 'none';
        return;
    }

    const unique = new Map();
    cities.forEach(city => {
        if (city?.name) {
            const key = `${city.name}-${city.region || ''}`;
            if (!unique.has(key)) unique.set(key, city);
        }
    });

    Array.from(unique.values()).forEach(city => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';

        const nameDiv = document.createElement('div');
        nameDiv.className = 'city-text';
        nameDiv.textContent = city.name;

        const regionDiv = document.createElement('div');
        regionDiv.className = 'region-text';
        regionDiv.textContent = city.region || '';

        item.appendChild(nameDiv);
        item.appendChild(regionDiv);

        item.addEventListener('click', () => {
            const display = city.region ? `${city.name}, ${city.region}` : city.name;
            input.value = display;
            dataInput.value = JSON.stringify({
                name: city.name,
                region: city.region || '',
                display_name: display
            });
            container.style.display = 'none';
        });

        container.appendChild(item);
    });

    container.style.display = unique.size > 0 ? 'block' : 'none';
}

function appendRankingList(div, question) {
    const list = document.createElement('div');
    list.className = `ranking-list ranking-list-question-${question.id}`;

    question.choices.forEach((choice, index) => {
        if (choice?.value !== undefined) {
            const item = document.createElement('div');
            item.className = 'ranking-item';
            item.draggable = true;
            item.id = `ranking-item-${question.id}-${index}`;
            item.dataset.value = choice.value;

            const rank = document.createElement('span');
            rank.className = 'rank-number';
            rank.textContent = index + 1;

            const text = document.createElement('span');
            text.className = 'choice-text';
            text.textContent = choice.text;

            item.appendChild(rank);
            item.appendChild(text);

            item.addEventListener('dragstart', dragStart);
            item.addEventListener('dragover', dragOver);
            item.addEventListener('drop', drop);
            item.addEventListener('dragend', dragEnd);

            list.appendChild(item);
        }
    });

    div.appendChild(list);
}

// Drag & Drop
function dragStart(e) {
    e.dataTransfer.setData('text/plain', e.target.id);
    e.target.classList.add('dragging');
}

function dragOver(e) { e.preventDefault(); }

function drop(e) {
    e.preventDefault();
    const id = e.dataTransfer.getData('text');
    const dragged = document.getElementById(id);
    const dropzone = e.target.closest('.ranking-item');

    if (!dragged || !dropzone) return;

    const container = dropzone.parentNode;
    const after = getDragAfterElement(container, e.clientY);

    if (after === null) {
        container.appendChild(dragged);
    } else {
        container.insertBefore(dragged, after);
    }

    updateRankNumbers();
}

function dragEnd(e) {
    e.target.classList.remove('dragging');
    updateRankNumbers();
}

function getDragAfterElement(container, y) {
    const elements = [...container.querySelectorAll('.ranking-item:not(.dragging)')];
    return elements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            return { offset, element: child };
        }
        return closest;
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function updateRankNumbers() {
    document.querySelectorAll('.ranking-item').forEach((item, index) => {
        const rank = item.querySelector('.rank-number');
        if (rank) rank.textContent = index + 1;
    });
}

// ============================================================================
// CRÉATION UI - BOUTONS
// ============================================================================

function appendButtonContainer(div, quizId) {
    const container = document.createElement('div');
    container.className = 'button-container';

    const buttons = document.createElement('div');
    buttons.className = 'flex gap-4';

    // Bouton précédent
    const history = getHistory();
    const canGoBack = history.length > 0 || currentChapter > 0 || currentChapterQuestionIndex > 0 || (isHomepageMode && document.getElementById('quizWelcome'));

    if (canGoBack && !isEditingFromReview) {
        const prevBtn = document.createElement('button');
        prevBtn.className = 'prev-btn';
        prevBtn.textContent = '← Retour';

        prevBtn.addEventListener('click', (e) => {
            e.preventDefault();
            previousQuestion(quizId);
        });

        buttons.appendChild(prevBtn);
    }

    // Bouton suivant
    const nextBtn = document.createElement('button');
    nextBtn.className = 'next-btn';

    if (isEditingFromReview) {
        nextBtn.innerHTML = '<span class="btn-text">Mettre à jour</span>';
        nextBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const questions = getAllQuestions();
            updateAnswerAndReturn(questions[currentQuestionIndex], quizId);
        });
    } else {
        nextBtn.textContent = 'Suivant →';
        nextBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const question = getCurrentQuestionInChapter();
            if (question) nextQuestion(question, quizId);
        });
    }

    buttons.appendChild(nextBtn);
    container.appendChild(buttons);
    div.appendChild(container);
}

// ============================================================================
// PROGRESSION
// ============================================================================

function updateProgress() {
    // Désactivé - pas de barre de progression
    return;
}

function getProgressText(chapters) {
    // Désactivé
    return '';
}

function updateCurrentChapterProgress() {
    // Désactivé
    return;
}

function triggerChapterCompletionEffect() {
    // Désactivé - pas d'effet visuel de complétion
    return;
}

function updateCharCount(textarea, countEl, maxLen) {
    if (!textarea || !countEl) return;

    const len = textarea.value.length;
    const text = countEl.querySelector('.char-count-text');

    if (text) {
        text.textContent = `${len} / ${maxLen}`;
    } else {
        countEl.textContent = `${len} / ${maxLen}`;
    }

    if (len > maxLen) {
        textarea.value = textarea.value.slice(0, maxLen);
    }

    // Classes état
    countEl.classList.remove('warning-active', 'valid');
    if (len > 0 && len < MIN_TEXT_LENGTH) {
        countEl.classList.add('warning-active');
    } else if (len >= MIN_TEXT_LENGTH) {
        countEl.classList.add('valid');
    }

    // Barre de progression minimum
    let bar = countEl.querySelector('.char-min-bar');
    let hint = countEl.querySelector('.char-min-hint');

    if (!bar) {
        bar = document.createElement('div');
        bar.className = 'char-min-bar';
        bar.innerHTML = '<div class="char-min-bar-fill"></div>';
        countEl.appendChild(bar);
    }
    if (!hint) {
        hint = document.createElement('div');
        hint.className = 'char-min-hint';
        countEl.appendChild(hint);
    }

    const fill = bar.querySelector('.char-min-bar-fill');
    const progress = Math.min(len / MIN_TEXT_LENGTH, 1);

    if (fill) {
        fill.style.width = (progress * 100) + '%';
        if (len === 0) {
            fill.style.background = '#e5e7eb';
        } else if (len < MIN_TEXT_LENGTH) {
            fill.style.background = 'linear-gradient(90deg, #f59e0b, #fbbf24)';
        } else {
            fill.style.background = 'linear-gradient(90deg, #10b981, #059669)';
        }
    }

    // Hint texte
    hint.classList.remove('reached');
    if (len === 0) {
        hint.textContent = MIN_TEXT_LENGTH + ' caractères minimum';
    } else if (len < MIN_TEXT_LENGTH) {
        var remaining = MIN_TEXT_LENGTH - len;
        hint.textContent = '✍️ Développe encore un peu — ' + remaining + ' caractère' + (remaining > 1 ? 's' : '') + ' avant de passer à la suite';
    } else {
        hint.textContent = '✓ Tu peux continuer ou développer encore pour une analyse plus fine';
        hint.classList.add('reached');
    }

    // Cacher barre et hint si max atteint (pas pertinent)
    if (len >= MIN_TEXT_LENGTH) {
        bar.style.opacity = '0.5';
    } else {
        bar.style.opacity = '1';
    }
}

// ============================================================================
// COMPLETION
// ============================================================================

function showCompletion() {
    // Cacher la barre de progression
    hideQuizProgress();
    
    if (isHomepageMode) {
        showHomepageCompletion();
    } else {
        showCongratulations();
    }
}

function showCongratulations() {
    const quizContent = getElement('#quizContent');
    if (quizContent) quizContent.style.display = 'none';

    prepareAnswersReview();

    const congrats = getElement('#congratulations');
    if (congrats) {
        congrats.style.display = 'block';

        const urlParams = new URLSearchParams(window.location.search);
        if (!urlParams.has('show_recap')) {
            urlParams.set('show_recap', 'true');
            const newUrl = `${window.location.pathname}?${urlParams.toString()}#congratulations`;
            window.history.pushState({}, '', newUrl);
        }
    }
}

function showHomepageCompletion() {
    const quizContent = getElement('#quizContent');
    if (quizContent) quizContent.style.display = 'none';

    const quizComplete = document.getElementById('quizComplete');
    if (quizComplete) {
        quizComplete.style.display = 'block';
        QuizTracking.trackLeadFormView();
        setupQuizLeadForm();
    }
}

// ============================================================================
// RÉCAPITULATIF RÉPONSES (mode authentifié)
// ============================================================================

async function prepareAnswersReview() {
    const container = document.getElementById('answersAccordion');
    if (!container) return;

    container.innerHTML = '';

    try {
        const quizId = getQuizId();

        if (!allQuestions?.length) {
            const response = await fetch(`/get_questions/?quiz_id=${quizId}`);
            const data = await response.json();
            allQuestions = data.questions;
        }

        const progressResponse = await fetch(`/get_quiz_progress/${quizId}`);
        const progressData = await progressResponse.json();
        userAnswers = progressData.answers || {};

        if (!Object.keys(userAnswers).length) {
            container.innerHTML = '<p class="text-center p-4">Aucune réponse enregistrée</p>';
            return;
        }

        allQuestions.forEach((question, index) => {
            const answer = userAnswers[question.id];
            if (!answer) return;

            const card = document.createElement('div');
            card.className = 'bg-white rounded-lg shadow-sm mb-4';

            const answerText = answer.text || answer.value?.join(', ') || 'Pas de réponse';

            card.innerHTML = `
                <div class="p-4 border-l-4 border-[#D7942D]">
                    <div class="mb-2">
                        <h4 class="text-lg font-medium mb-3">${question.question}</h4>
                        <div class="answer-tag bg-[#D7942D] text-white rounded-lg p-3">${answerText}</div>
                    </div>
                    <div class="mt-3">
                        <button class="edit-question-btn btn flex items-center gap-2" data-index="${index}">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
                            </svg>
                            Modifier
                        </button>
                    </div>
                </div>
            `;

            const editBtn = card.querySelector('.edit-question-btn');
            editBtn.addEventListener('click', function() {
                navigateToQuestion(parseInt(this.dataset.index));
            });

            container.appendChild(card);
        });

    } catch (error) {
        console.error('Erreur prepareAnswersReview:', error);
        container.innerHTML = '<p class="text-center p-4 text-red-500">Erreur de chargement</p>';
    }
}

function navigateToQuestion(index) {
    const questions = getAllQuestions();
    if (index < 0 || index >= questions.length) return;

    questionHistory.push(currentQuestionIndex);
    currentQuestionIndex = index;
    isEditingFromReview = true;

    const congrats = document.getElementById('congratulations');
    if (congrats) congrats.style.display = 'none';

    const quizContent = document.getElementById('quizContent');
    if (quizContent) {
        quizContent.style.display = 'block';
        const quizForm = document.getElementById('quizForm');
        if (quizForm) quizForm.innerHTML = '';

        showQuestion(getQuizId());
        quizContent.scrollIntoView({ behavior: 'smooth' });
    }
}

async function updateAnswerAndReturn(question, quizId) {
    try {
        if (!validateAnswer(question)) return;

        const [answerValue, answerText] = getQuestionAnswer(question);

        await fetch('/update_quiz_progress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                quiz_id: quizId,
                current_question_index: currentQuestionIndex,
                answer: { question_id: question.id, value: answerValue, text: answerText },
                is_reviewing: true
            })
        });

        const quizContent = getElement('#quizContent');
        if (quizContent) quizContent.style.display = 'none';

        await prepareAnswersReview();

        const congrats = getElement('#congratulations');
        if (congrats) {
            congrats.style.display = 'block';
            congrats.scrollIntoView({ behavior: 'smooth' });
        }

        isEditingFromReview = false;

    } catch (error) {
        console.error('Erreur updateAnswerAndReturn:', error);
        alert('Erreur lors de la mise à jour');
    }
}

function hideFormMessage() {
    const formMessage = document.getElementById('quiz-form-message');
    if (formMessage) {
        formMessage.classList.remove('show');
        formMessage.style.display = 'none';
    }
}

// ============================================================================
// FORMULAIRE LEAD (mode homepage)
// ============================================================================

function setupQuizLeadForm() {
    const form = document.getElementById('quiz-lead-form');
    const submitBtn = document.querySelector('.btn-continue-minimal');

    if (!form || !submitBtn) return;

    // Initialiser l'autocomplete localisation
    initLeadLocationAutocomplete();

    // Bouton retour vers les questions
const backBtn = document.getElementById('leadFormBackBtn');
if (backBtn) {
    backBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        // Cacher le formulaire lead
        const quizComplete = document.getElementById('quizComplete');
        if (quizComplete) quizComplete.style.display = 'none';
        
        // Réafficher le quiz
        const quizContent = document.getElementById('quizContent');
        if (quizContent) quizContent.style.display = 'block';
        
        // Reculer d'une question
        const quizId = window.currentQuizId || getQuizId();
        const chapters = QUIZ_CHAPTERS[quizId]?.chapters || [];
        
        if (chapters.length > 0) {
            const lastChapter = chapters[chapters.length - 1];
            currentChapter = chapters.length - 1;
            currentChapterQuestionIndex = lastChapter.questions.length - 1;
        }
        
        // Réafficher la barre de progression
        updateQuizProgress();
        
        await showQuestion(quizId);
    });
}

    // Vérifier expiration session
    const savedState = localStorage.getItem('tilto_quiz_temp');
    if (savedState && !window.homepageQuizAnswers) {
        try {
            const state = JSON.parse(savedState);
            const hours = (Date.now() - state.timestamp) / (1000 * 60 * 60);
            if (hours > 7.5) {
                localStorage.removeItem('tilto_quiz_temp');
                console.log('[Quiz] Session expirée, données nettoyées');
            }
        } catch (e) {
            localStorage.removeItem('tilto_quiz_temp');
        }
    }

    // Gérer retour après reload CSRF
    if (sessionStorage.getItem('quiz_session_expired')) {
        sessionStorage.removeItem('quiz_session_expired');
    }

    form.addEventListener('submit', function(e) {
        e.preventDefault();
        hideFormMessage();

        const firstname = document.getElementById('quiz-firstname')?.value.trim();
        const email = document.getElementById('quiz-email')?.value.trim();
        const newsletter = document.getElementById('newsletter-consent')?.checked || false;

        // Honeypot
        const honeypot = document.getElementById('website');
        if (honeypot?.value) {
            showFormMessage('success', '✓', 'Inscription réussie', 'Merci !');
            setTimeout(() => form.reset(), 2000);
            return;
        }

        // Validation prénom
        if (!firstname) {
            showFormMessage('error', '👤', 'Prénom manquant', 'Merci de renseigner ton prénom');
            focusAndHighlight('quiz-firstname');
            return;
        }

        // Validation email
        if (!email) {
            showFormMessage('error', '📧', 'Email manquant', 'Merci de renseigner ton email');
            focusAndHighlight('quiz-email');
            return;
        }

        if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            showFormMessage('error', '📧', 'Email invalide', 'Vérifie le format de ton email');
            focusAndHighlight('quiz-email');
            return;
        }

        // Validation localisation (Question 26)
        if (!validateLeadLocation()) {
            return;
        }


        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="btn-text">Envoi en cours...</span>';

        // Préparer données
        const formData = new FormData();
        formData.append('firstname', firstname);
        formData.append('email', email);
        formData.append('profile', 'quiz_completion');
        formData.append('source', 'quiz_homepage');
        const currentQuizId = window.currentQuizId || getQuizId();
        formData.append('quiz_id', currentQuizId);
        formData.append('newsletter_consent', newsletter ? 'yes' : 'no');
        formData.append('partner_consent', 'no');

        const csrfToken = document.querySelector('meta[name=csrf-token]');
        if (csrfToken) formData.append('csrf_token', csrfToken.content);

        // ═══════════════════════════════════════════════════════════════
        // CORRECTION : Utiliser window.homepageQuizAnswers partout
        // ═══════════════════════════════════════════════════════════════
        

        // Ajouter la réponse localisation (Question 26)
        const locationAnswer = getLeadLocationAnswer();
        if (locationAnswer) {
            homepageQuizAnswers[26] = locationAnswer;
            console.log('[Lead Form] Localisation ajoutée:', locationAnswer);
        }

        // Debug logs
        console.log('[Lead Form] État homepageQuizAnswers:', homepageQuizAnswers);
        console.log('[Lead Form] Nombre de réponses:', Object.keys(homepageQuizAnswers).length);

        // Préparer réponses quiz avec audios
        const formatted = {};
        let audioCount = 0;

        Object.keys(homepageQuizAnswers).forEach(qId => {
            const answer = homepageQuizAnswers[qId];

            if (answer.value?.[0]?.startsWith('[AUDIO:')) {
                const audioId = answer.value[0].match(/\[AUDIO:(.+)\]/)?.[1];
                if (audioId && window.tempQuizAudios?.[audioId]) {
                    formData.append(`audio_q${qId}`, window.tempQuizAudios[audioId].blob, `question_${qId}.webm`);
                    audioCount++;
                    formatted[qId] = { value: ['[AUDIO_RESPONSE]'], text: `[Audio - Q${qId}]` };
                } else {
                    formatted[qId] = { value: [''], text: '' };
                }
            } else {
                formatted[qId] = {
                    value: Array.isArray(answer.value) ? answer.value : [answer.value],
                    text: answer.text || ''
                };
            }
        });

        // Toujours ajouter quiz_answers s'il y a des réponses
        if (Object.keys(formatted).length > 0) {
            formData.append('quiz_answers', JSON.stringify(formatted));
            console.log('[Quiz] Quiz formaté avec', audioCount, 'audios,', Object.keys(formatted).length, 'réponses');
        } else {
            console.warn('[Quiz] Aucune réponse à envoyer !');
        }

        // Envoi
        let isSuccess = false;

        fetch('/lead/capture', {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                isSuccess = true;

                localStorage.setItem('tilto_lead_completed', JSON.stringify({
                    email, firstname, timestamp: Date.now(), hasCompletedQuiz: true
                }));

                QuizTracking.trackLeadSubmit(
                    Object.values(homepageQuizAnswers).some(a => a.value?.[0]?.startsWith('[AUDIO:')),
                    Object.keys(homepageQuizAnswers).length
                );

                QuizPersistence.clearQuizState();

                // Nettoyer audios
                if (window.tempQuizAudios) {
                    Object.values(window.tempQuizAudios).forEach(a => {
                        if (a.url) URL.revokeObjectURL(a.url);
                    });
                    window.tempQuizAudios = {};
                }

                showTransitionScreen(firstname);

                setTimeout(() => {
                    window.location.href = '/dashboard';
                }, 2000);

            } else {
                if (data.error_type === 'email_exists') {
                    showFormMessage('error', '📧', 'Email déjà utilisé', data.message || 'Cette adresse est déjà enregistrée');
                    focusAndHighlight('quiz-email');
                } else {
                    showFormMessage('error', '❌', 'Erreur', data.message || 'Une erreur est survenue');
                }
            }
        })
        .catch(error => {
            console.error('Erreur envoi formulaire:', error);
            showFormMessage('error', '❌', 'Erreur de connexion', 'Vérifiez votre connexion internet');
        })
        .finally(() => {
            if (!isSuccess) {
                setTimeout(() => {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<span class="btn-text">Je veux recevoir mes recos maintenant</span><span class="btn-arrow">🚀</span>';
                }, 2000);
            }
        });
    });
}

    
function showFormMessage(type, icon, title, message) {
    const formMessage = document.getElementById('quiz-form-message');
    if (!formMessage) return;
    
    formMessage.className = `quiz-form-message ${type}`;
    formMessage.innerHTML = `
        <span class="message-icon">${icon}</span>
        <div class="message-content">
            <strong>${title}</strong>
            <p>${message}</p>
        </div>
    `;
    formMessage.style.display = 'flex';
    setTimeout(() => formMessage.classList.add('show'), 10);
}

function focusAndHighlight(fieldId) {
    const field = document.getElementById(fieldId);
    if (field) {
        field.focus();
        field.style.borderColor = '#e74c3c';
        field.style.boxShadow = '0 0 0 0.2rem rgba(231, 76, 60, 0.25)';
        setTimeout(() => {
            field.style.borderColor = '';
            field.style.boxShadow = '';
        }, 3000);
    }
}

function showTransitionScreen(firstname) {
    const quizComplete = document.getElementById('quizComplete');
    if (quizComplete) quizComplete.style.display = 'none';

    const modalContent = document.querySelector('.quiz-modal-content');
    if (!modalContent) return;

    modalContent.innerHTML = `
        <div class="quiz-transition-screen">
            <div class="transition-content">
                <div class="transition-icon">
                    <svg width="64" height="64" viewBox="0 0 64 64">
                        <circle cx="32" cy="32" r="30" fill="url(#gradSuccess)"/>
                        <path d="M20 32L28 40L44 24" stroke="white" stroke-width="4" stroke-linecap="round" fill="none"/>
                        <defs>
                            <linearGradient id="gradSuccess" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" style="stop-color:#10b981"/>
                                <stop offset="100%" style="stop-color:#059669"/>
                            </linearGradient>
                        </defs>
                    </svg>
                </div>
                <h2 class="transition-title">Compte créé</h2>
                <p class="transition-subtitle">Tes réponses ont été sauvegardées.</p>
                <div class="transition-loader">
                    <span class="loader-text">Redirection en cours</span>
                    <div class="loader-dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
                </div>
            </div>
        </div>
    `;

    modalContent.scrollTop = 0;
}

// ============================================================================
// PERSISTENCE ÉTAT (localStorage) - VERSION COMPLÈTE AVEC AUDIO BASE64 & CSRF
// ============================================================================

// Éviter redéclaration si déjà défini dans common.js
var QuizPersistence = window.QuizPersistence || {
    STORAGE_KEY: 'tilto_quiz_temp',
    AUDIO_PREFIX: 'tilto_audio_',
    MAX_AGE_DAYS: 7,
    SESSION_MAX_HOURS: 7.5, // Marge de sécurité avant les 8h

    // Vérifier si la session est expirée
    isSessionExpired: function() {
        const saved = localStorage.getItem(this.STORAGE_KEY);
        if (!saved) return false;

        try {
            const state = JSON.parse(saved);
            const hoursSince = (Date.now() - state.timestamp) / (1000 * 60 * 60);

            if (hoursSince > this.SESSION_MAX_HOURS) {
                console.warn('⚠️ Session expirée:', hoursSince.toFixed(1), 'heures');
                return true;
            }
            return false;
        } catch (e) {
            return false;
        }
    },

    // Rafraîchir la page pour obtenir un nouveau token CSRF
    refreshIfExpired: function() {
        if (this.isSessionExpired()) {
            console.log('🔄 Session expirée, nettoyage des données...');
            // Ne pas recharger, juste nettoyer
            localStorage.removeItem('tilto_quiz_temp');
            return false;  // Continuer sans recharger
        }
        return false;
    },

    // Sauvegarder l'état (appelé après chaque réponse)
    saveQuizState: function() {
        if (!isHomepageMode) return false;

        try {
            const state = {
                currentChapter: currentChapter,
                currentChapterQuestionIndex: currentChapterQuestionIndex,
                isShowingTransition: isShowingTransition,
                answers: {},
                audioRefs: [],
                timestamp: Date.now(),
                version: '1.0'
            };

            // Séparer réponses texte et audio
            for (const [qId, answer] of Object.entries(homepageQuizAnswers)) {
                if (this.isAudioAnswer(answer)) {
                    const audioId = this.extractAudioId(answer);
                    if (audioId && window.tempQuizAudios?.[audioId]) {
                        // Sauvegarder l'audio en base64 dans localStorage
                        this.saveAudio(audioId, window.tempQuizAudios[audioId]);
                        state.audioRefs.push({ qId: qId, audioId: audioId });
                    }
                }
                // Toujours sauvegarder la structure de réponse
                state.answers[qId] = answer;
            }

            // Sauvegarder l'historique de navigation
            state.history = homepageQuestionHistory || [];

            // Sauvegarder état introSeen des chapitres
            const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
            state.chaptersIntroSeen = chapters.map(function(ch) { return ch.introSeen; });

            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
            log('État sauvegardé:', Object.keys(state.answers).length, 'réponses');
            return true;

        } catch (error) {
            console.error('Erreur sauvegarde:', error);
            // Si localStorage plein, nettoyer les vieux audios
            if (error.name === 'QuotaExceededError') {
                this.cleanupOldAudios();
                return this.saveQuizState(); // Retry
            }
            return false;
        }
    },

    // Sauvegarder un audio en base64
    saveAudio: function(audioId, audioData) {
        try {
            const reader = new FileReader();
            const self = this;
            reader.onload = function() {
                const base64 = reader.result.split(',')[1];
                const compressed = {
                    data: base64,
                    qId: audioData.questionId,
                    duration: audioData.duration,
                    timestamp: Date.now()
                };
                localStorage.setItem(
                    self.AUDIO_PREFIX + audioId,
                    JSON.stringify(compressed)
                );
            };
            reader.readAsDataURL(audioData.blob);
        } catch (error) {
            console.warn('Audio non sauvegardé:', audioId, error);
        }
    },

    // Restaurer l'état
    restoreQuizState: function() {
        try {
            const saved = localStorage.getItem(this.STORAGE_KEY);
            if (!saved) return null;

            const state = JSON.parse(saved);

            // Vérifier l'âge (7 jours max) - SEULE condition pour effacer
            const age = Date.now() - state.timestamp;
            if (age > this.MAX_AGE_DAYS * 24 * 60 * 60 * 1000) {
                console.log('Données quiz expirées (> 7 jours), nettoyage');
                this.clearQuizState();
                return null;
            }

            // Restaurer les variables globales
            currentChapter = state.currentChapter || 0;
            currentChapterQuestionIndex = state.currentChapterQuestionIndex || 0;
            isShowingTransition = state.isShowingTransition || false;
            homepageQuizAnswers = state.answers || {};
            homepageQuestionHistory = Array.isArray(state.history) ? state.history : [];

            // Valider que les réponses sauvegardées correspondent aux questions actuelles
            var chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
            var validQuestionIds = [];
            chapters.forEach(function(ch) { 
                ch.questions.forEach(function(qId) { validQuestionIds.push(String(qId)); }); 
            });

            // Filtrer les réponses obsolètes
            var cleanedAnswers = {};
            for (var qId in homepageQuizAnswers) {
                if (validQuestionIds.indexOf(String(qId)) !== -1) {
                    cleanedAnswers[qId] = homepageQuizAnswers[qId];
                } else {
                    console.warn('[Restore] Réponse obsolète supprimée pour question:', qId);
                }
            }
            homepageQuizAnswers = cleanedAnswers;

            // Vérifier que l'index est valide
            var currentChapterObj = chapters[currentChapter];
            if (!currentChapterObj || currentChapterQuestionIndex >= currentChapterObj.questions.length) {
                console.warn('[Restore] Index invalide, reset à 0');
                currentChapter = 0;
                currentChapterQuestionIndex = 0;
            }

            // Restaurer introSeen
            if (state.chaptersIntroSeen) {
                const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
                state.chaptersIntroSeen.forEach(function(seen, i) {
                    if (chapters[i]) chapters[i].introSeen = seen;
                });
            }

            // Restaurer les audios
            if (state.audioRefs?.length > 0) {
                this.restoreAudios(state.audioRefs);
            }

            // ════════════════════════════════════════════════════════
            // AJOUT ICI : Rafraîchir le timestamp pour prolonger la durée de vie
            // ════════════════════════════════════════════════════════
            state.timestamp = Date.now();
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify(state));
            console.log('Timestamp rafraîchi, données prolongées de 7 jours');

            log('État restauré:', Object.keys(state.answers).length, 'réponses');
            return state;

        } catch (error) {
            console.error('Erreur restauration:', error);
            this.clearQuizState();
            return null;
        }
    },

    // Restaurer les audios depuis base64
    restoreAudios: function(audioRefs) {
        if (!window.tempQuizAudios) window.tempQuizAudios = {};
    
        for (var i = 0; i < audioRefs.length; i++) {
            var ref = audioRefs[i];
            var qId = ref.qId;
            var audioId = ref.audioId;
    
            try {
                var saved = localStorage.getItem(this.AUDIO_PREFIX + audioId);
                if (!saved) {
                    console.warn('Audio non trouvé dans localStorage:', audioId);
                    continue;
                }
    
                var compressed = JSON.parse(saved);
    
                // Convertir base64 en blob
                var byteString = atob(compressed.data);
                var bytes = new Uint8Array(byteString.length);
                for (var j = 0; j < byteString.length; j++) {
                    bytes[j] = byteString.charCodeAt(j);
                }
                var blob = new Blob([bytes], { type: 'audio/webm' });
                var url = URL.createObjectURL(blob);
    
                // Stocker dans tempQuizAudios
                window.tempQuizAudios[audioId] = {
                    blob: blob,
                    url: url,
                    questionId: compressed.qId,
                    duration: compressed.duration,
                    timestamp: compressed.timestamp
                };
    
                // CRITIQUE: Restaurer aussi dans currentQuestionAudioState
                if (!currentQuestionAudioState[compressed.qId]) {
                    currentQuestionAudioState[compressed.qId] = {};
                }
                currentQuestionAudioState[compressed.qId].audioBlob = blob;
                currentQuestionAudioState[compressed.qId].audioURL = url;
                currentQuestionAudioState[compressed.qId].duration = compressed.duration;
                currentQuestionAudioState[compressed.qId].isRecording = false;
    
                console.log('Audio restauré avec succès:', audioId, 'pour question:', compressed.qId);
    
            } catch (error) {
                console.error('Erreur restauration audio:', audioId, error);
            }
        }
    },

    // Nettoyer tout
    clearQuizState: function() {
        localStorage.removeItem(this.STORAGE_KEY);
        this.cleanupOldAudios();
        log('État effacé');
    },

    // Nettoyer les vieux audios
    cleanupOldAudios: function() {
        var keys = Object.keys(localStorage);
        var self = this;

        keys.forEach(function(key) {
            if (key.startsWith(self.AUDIO_PREFIX)) {
                try {
                    var item = JSON.parse(localStorage.getItem(key));
                    var age = Date.now() - item.timestamp;
                    if (age > self.MAX_AGE_DAYS * 24 * 60 * 60 * 1000) {
                        localStorage.removeItem(key);
                    }
                } catch (e) {
                    localStorage.removeItem(key);
                }
            }
        });
    },

    // Helpers
    isAudioAnswer: function(answer) {
        return Array.isArray(answer.value) &&
               answer.value[0]?.startsWith('[AUDIO:');
    },

    extractAudioId: function(answer) {
        return answer.value[0]?.match(/\[AUDIO:(.+)\]/)?.[1];
    }
};

window.QuizPersistence = QuizPersistence;

// ============================================================================
// INITIALISATION
// ============================================================================

document.addEventListener('DOMContentLoaded', async function() {
    const quizContent = getElement('#quizContent', true);

    if (!quizContent) {
        log('Pas sur une page quiz');
        return;
    }

    // Mode modal homepage
    if (quizContent.closest('.quiz-modal')) {
        log('Mode quiz homepage détecté');
        return;
    }

    // Smart Contact: skip auto-init, le controller SC prend la main
    if (window.__SC_SKIP_QUIZ_AUTO_INIT) {
        log('Smart Contact mode — skip auto-init');
        return;
    }

    // Mode quiz normal (authentifié)
    log('=== INITIALISATION QUIZ NORMAL ===');

    try {
        const urlParams = new URLSearchParams(window.location.search);
        const quizId = urlParams.get('quiz_id') || 'personal_profiling';
        const shouldResume = urlParams.get('resume') === 'true';
        const showRecap = urlParams.get('show_recap') === 'true';

        questionHistory = [];

        await loadQuestions(quizId);

        if (showRecap) {
            showCongratulations();
            return;
        }

        const progressData = await loadQuizProgress(quizId);

        if (progressData?.progress) {
            const isCompleted = progressData.quiz_completed ||
                               progressData.progress.quiz_status === 'completed';

            if (isCompleted) {
                showCongratulations();
                return;
            }

            if (shouldResume && progressData.progress.questions_answered_count > 0) {
                currentQuestionIndex = progressData.progress.questions_answered_count || 0;
                userAnswers = progressData.answers || {};
                questionHistory = progressData.progress.question_history || [];

                quizContent.style.display = 'block';
                await showQuestion(quizId);
            } else {
                currentQuestionIndex = 0;
                questionHistory = [];
                userAnswers = {};
                quizContent.style.display = 'block';
                await showQuestion(quizId);
            }
        } else {
            currentQuestionIndex = 0;
            questionHistory = [];
            userAnswers = {};
            quizContent.style.display = 'block';
            await showQuestion(quizId);
        }

    } catch (error) {
        console.error('Erreur initialisation quiz:', error);
        alert('Erreur lors du chargement du quiz');
    }
});

/**
 * Initialise le quiz homepage (appelé depuis l'extérieur)
 */
/**
 * Initialise le quiz homepage (appelé depuis l'extérieur)
 */
async function initializeHomepageQuiz() {
    log('=== INITIALISATION QUIZ HOMEPAGE ===');

    QuizTracking.trackQuizStart();

    // Vérifier lead existant
    const existingLead = localStorage.getItem('tilto_lead_completed');
    if (existingLead) {
        try {
            const leadData = JSON.parse(existingLead);
            const days = (Date.now() - leadData.timestamp) / (1000 * 60 * 60 * 24);

            if (days < 30 && leadData.hasCompletedQuiz) {
                showReturningUserScreen(leadData);
                return;
            }
        } catch (e) {
            localStorage.removeItem('tilto_lead_completed');
        }
    }

    // Tenter restauration état
    isHomepageMode = true;
    const savedState = QuizPersistence.restoreQuizState();

    if (savedState && Object.keys(savedState.answers || {}).length > 0) {
        log('Restauration session précédente');

        try {
            await loadQuestions('pack_clarte');

            // Avancer à la question suivante non répondue
            const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
            const chapter = chapters[currentChapter];

            if (chapter) {
                const currentQId = chapter.questions[currentChapterQuestionIndex];
                if (homepageQuizAnswers[currentQId]) {
                    currentChapterQuestionIndex++;

                    if (currentChapterQuestionIndex >= chapter.questions.length) {
                        if (currentChapter < chapters.length - 1 && chapter.transition) {
                            isShowingTransition = true;
                        } else if (currentChapter < chapters.length - 1) {
                            currentChapter++;
                            currentChapterQuestionIndex = 0;
                        }
                    }
                }
            }

            const content = document.getElementById('quizContent');
            const complete = document.getElementById('quizComplete');

            if (content) content.style.display = 'block';
            if (complete) complete.style.display = 'none';

            await showQuestion('pack_clarte');
            return;

        } catch (error) {
            console.error('Erreur restauration, redémarrage:', error);
            QuizPersistence.clearQuizState();
        }
    }

// Nouveau quiz - afficher le Welcome Screen d'abord
resetQuizState();

try {
    await loadQuestions('pack_clarte');

    const content = document.getElementById('quizContent');
    const complete = document.getElementById('quizComplete');
    const welcome = document.getElementById('quizWelcome');

    // Flow normal : welcome screen d'abord
    if (content) content.style.display = 'none';
    if (complete) complete.style.display = 'none';
    if (welcome) welcome.style.display = 'flex';

    if (typeof window.playWelcomeVideo === 'function') {
        window.playWelcomeVideo();
    }

    const startBtn = document.getElementById('welcomeStartBtn');
    if (startBtn && !startBtn._bound) {
        startBtn._bound = true;
        startBtn.addEventListener('click', async function(e) {
            e.preventDefault();
            if (welcome) welcome.style.display = 'none';
            if (content) content.style.display = 'block';
            await showQuestion('pack_clarte');
        });
    }

} catch (error) {
    console.error('Erreur initialisation:', error);
    alert('Erreur lors du chargement du quiz: ' + error.message);
}
}


function resetQuizState() {
    log('Réinitialisation état quiz');

    QuizPersistence.clearQuizState();

    currentChapter = 0;
    currentChapterQuestionIndex = 0;
    isShowingTransition = false;

    isHomepageMode = true;
    homepageQuizAnswers = {};
    homepageQuestionHistory = [];

    // Reset introSeen
    const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
    chapters.forEach(ch => ch.introSeen = false);

    // Nettoyer audios
    if (window.tempQuizAudios) {
        Object.values(window.tempQuizAudios).forEach(a => {
            if (a.url) URL.revokeObjectURL(a.url);
        });
        window.tempQuizAudios = {};
    }

    currentQuestionAudioState = {};
    globalAudioStorage = {};
}

function showReturningUserScreen(leadData) {
    const welcome = document.getElementById('quizWelcome');
    const content = document.getElementById('quizContent');
    const complete = document.getElementById('quizComplete');

    if (welcome) welcome.style.display = 'none';
    if (content) content.style.display = 'none';

    if (complete) {
        complete.style.display = 'block';
        complete.innerHTML = `
            <div class="quiz-returning-container">
                <div class="returning-content">
                    <div class="returning-icon-wrapper">
                        <div class="returning-icon">🎧</div>
                    </div>
                    
                    <h2 class="returning-title">
                        Tu as déjà commencé ton expérience
                    </h2>
                    
                    <p class="returning-subtitle">
                        Tes réponses sont bien enregistrées.
                    </p>
                    
                    <a href="/dashboard" class="btn-cta-primary btn-returning">
                        👉 Accéder à mon espace
                    </a>
                    
                    <button type="button" class="btn-restart-quiz">
                        Recommencer depuis le début
                    </button>
                </div>
            </div>
        `;
        
        // Event listener pour le bouton recommencer
        const restartBtn = complete.querySelector('.btn-restart-quiz');
        if (restartBtn) {
            restartBtn.addEventListener('click', async function(e) {
                e.preventDefault();
                await restartQuizFresh();
            });
        }
    }
}

/**
 * Recommencer le quiz depuis le début (pour utilisateur revenant)
 */
async function restartQuizFresh() {
    console.log('🔄 Redémarrage du quiz depuis le début');
    
    // 1. Effacer le flag "lead completed"
    localStorage.removeItem('tilto_lead_completed');
    
    // 2. Effacer l'état du quiz sauvegardé
    QuizPersistence.clearQuizState();
    
    // 3. Réinitialiser les variables globales
    resetQuizState();
    
    // 4. Charger les questions
    try {
        await loadQuestions('pack_clarte');
        console.log('✓ Questions rechargées');
    } catch (error) {
        console.error('Erreur chargement questions:', error);
        alert('Erreur lors du chargement du quiz. Veuillez réessayer.');
        return;
    }
    
    // 5. Masquer tous les écrans sauf le contenu du quiz
    const complete = document.getElementById('quizComplete');
    const welcome = document.getElementById('quizWelcome');
    const content = document.getElementById('quizContent');
    
    if (complete) complete.style.display = 'none';
    if (welcome) welcome.style.display = 'none';  // Pas d'écran welcome
    if (content) content.style.display = 'block';
    
    // 6. Démarrer directement sur la première question
    await showQuestion('pack_clarte');
}

// ============================================================================
// MODAL ANALYSE (mode authentifié)
// ============================================================================

async function startAnalysis(event) {
    if (event) event.preventDefault();
    await showConfirmationModal();
}

async function showConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    const tokenStatus = document.getElementById('tokenStatusMessage');
    const modalButtons = document.getElementById('modalButtons');
    const modalText = document.getElementById('modalWarningText');

    if (!modal || !tokenStatus || !modalButtons) return;

    try {
        const quizId = getQuizId();

        const response = await fetch(`/check-token-status/${quizId}`, {
            headers: { 'Accept': 'application/json' }
        });

        const data = await response.json();

        tokenStatus.innerHTML = `
            <p class="tilto-token-status ${data.message_type === 'success' ? 'status-valid' : 'status-invalid'}">
                ${data.primary_message || ''}
            </p>
            ${data.info_message ? `<p class="info-message">${data.info_message}</p>` : ''}
        `;

        if (modalText) {
            modalText.style.display = data.has_token && !data.token_in_progress ? 'block' : 'none';
        }

        modalButtons.innerHTML = '';

        if (data.buttons) {
            data.buttons.forEach(button => {
                const btn = document.createElement('button');
                btn.className = `tilto-btn-${button.type}`;
                btn.textContent = button.label;

                btn.addEventListener('click', () => {
                    if (button.url === '#') {
                        if (button.label.includes('analyse')) confirmAnalysis();
                        closeConfirmationModal();
                    } else {
                        window.location.href = button.url;
                    }
                });

                modalButtons.appendChild(btn);
            });
        }

        modal.style.display = 'flex';

    } catch (error) {
        console.error('Erreur showConfirmationModal:', error);
        alert('Erreur technique');
    }
}

function closeConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    if (modal) modal.style.display = 'none';
}

async function confirmAnalysis() {
    log('=== LANCEMENT ANALYSE ===');

    const loading = document.getElementById('loadingIndicator');

    try {
        const quizId = getQuizId();

        if (loading) loading.style.display = 'block';

        const response = await fetch('/analysis/generate/vision_360', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ quiz_id: quizId, force_new: true })
        });

        const result = await response.json();

        if (result.error) throw new Error(result.error);

        if (result.redirect_url) {
            window.location.href = result.redirect_url;
        } else {
            window.location.href = `/analysis/view/${quizId}?skip_loading=false`;
        }

    } catch (error) {
        console.error('Erreur analyse:', error);
        alert('Erreur lors de l\'analyse');

        if (loading) loading.style.display = 'none';

        const modal = document.getElementById('confirmationModal');
        if (modal) modal.style.display = 'none';
    }
}

// ============================================================================
// HERO QUIZ - Quiz intégré dans le hero de la homepage
// ============================================================================

(function() {
    'use strict';
    
    
    let heroState = {
        mode: null,
        isRecording: false,
        recordingTime: 0,
        hasRecording: false,
        textValue: ''
    };
    
    let heroMediaRecorder = null;
    let heroAudioStream = null;
    let heroAudioChunks = [];
    let heroAudioBlob = null;
    let heroAudioURL = null;
    let heroRecordingTimer = null;
    let heroRecordingStartTime = 0;
    
    let heroElements = {};
    
    function initHeroElements() {
        heroElements = {
            choiceScreen: document.getElementById('heroChoiceScreen'),
            audioMode: document.getElementById('heroAudioMode'),
            textMode: document.getElementById('heroTextMode'),
            voiceBtn: document.getElementById('heroVoiceBtn'),
            textBtn: document.getElementById('heroTextBtn'),
            placeholderZone: document.getElementById('heroPlaceholderZone'),
            recordingState: document.getElementById('heroRecordingState'),
            doneState: document.getElementById('heroDoneState'),
            timerDisplay: document.getElementById('heroTimerDisplay'),
            recordingHint: document.getElementById('heroRecordingHint'),
            stopBtn: document.getElementById('heroStopBtn'),
            cancelRecording: document.getElementById('heroCancelRecording'),
            switchToTextFromRecording: document.getElementById('heroSwitchToTextFromRecording'),
            doneText: document.getElementById('heroDoneText'),
            warningText: document.getElementById('heroWarningText'),
            listenBtn: document.getElementById('heroListenBtn'),
            rerecordBtn: document.getElementById('heroRerecordBtn'),
            backFromDone: document.getElementById('heroBackFromDone'),
            submitAudio: document.getElementById('heroSubmitAudio'),
            audioElement: document.getElementById('heroAudioElement'),
            textarea: document.getElementById('heroTextarea'),
            charCount: document.getElementById('heroCharCount'),
            backFromText: document.getElementById('heroBackFromText'),
            submitText: document.getElementById('heroSubmitText'),
            switchToAudio: document.getElementById('heroSwitchToAudio'),
            trustBadges: document.getElementById('heroTrustBadges')
        };
    }

    /**
 * Initialise les placeholders rotatifs du Hero Quiz
 * Utilise window.HERO_PLACEHOLDERS si défini, sinon placeholders par défaut
 */
function initHeroPlaceholders() {
    const defaultPlaceholders = [
        "Ex: J'aime créer, innover, trouver des solutions. Mais je déteste la routine et les tâches répétitives. J'aimerais un métier qui me challenge...",
        "Ex: Je suis passionné par les relations humaines, j'adore écouter et conseiller. Mais le stress constant me pèse...",
        "Ex: J'ai besoin de sens dans mon travail, de me sentir utile. Le salaire compte moins que l'impact..."
    ];
    
    const placeholders = window.HERO_PLACEHOLDERS || defaultPlaceholders;
    let currentIndex = 0;
    
    const rotatingEl = document.getElementById('rotatingPlaceholder');
    const textarea = document.getElementById('heroTextarea');
    
    // Initialiser avec le premier placeholder
    if (textarea && placeholders[0]) {
        textarea.placeholder = placeholders[0];
    }
    if (rotatingEl && placeholders[0]) {
        rotatingEl.textContent = placeholders[0];
    }
    
    // Rotation toutes les 10 secondes
    setInterval(() => {
        if (!rotatingEl) return;
        
        rotatingEl.style.opacity = '0';
        
        setTimeout(() => {
            currentIndex = (currentIndex + 1) % placeholders.length;
            rotatingEl.textContent = placeholders[currentIndex];
            rotatingEl.style.opacity = '1';
            
            if (textarea) {
                textarea.placeholder = placeholders[currentIndex];
            }
        }, 400);
    }, 10000);
}

    function getHeroQuestionId() {
        // 1. Vérifier si défini explicitement dans la page
        if (typeof window.HERO_QUESTION_ID !== 'undefined') {
            return window.HERO_QUESTION_ID;
        }
        
        // 2. Utiliser les questions déjà chargées (PRIORITÉ)
        const questions = getAllQuestions();
        if (questions && questions.length > 0) {
            console.log('[Hero] Utilisation de la première question chargée:', questions[0].id);
            return questions[0].id;
        }
        
        // 3. Fallback temporaire (sera remplacé après chargement)
        console.warn('[Hero] Questions pas encore chargées, fallback temporaire');
        return 65;
    }
    

    function showHeroChoiceScreen() {
        heroState.mode = null;
        heroElements.choiceScreen.style.display = 'block';
        heroElements.audioMode.style.display = 'none';
        heroElements.textMode.style.display = 'none';
        heroElements.trustBadges.style.display = 'flex';
    }
    
    function showHeroAudioMode() {
        heroState.mode = 'audio';
        heroElements.choiceScreen.style.display = 'none';
        heroElements.audioMode.style.display = 'block';
        heroElements.textMode.style.display = 'none';
        heroElements.trustBadges.style.display = 'none';
        
        heroElements.recordingState.style.display = 'block';
        heroElements.doneState.style.display = 'none';
        
        // ═══════════════════════════════════════════════════════════════
        // CACHER SEULEMENT le header "ENREGISTREMENT EN COURS"
        // ═══════════════════════════════════════════════════════════════
        const statusHeader = heroElements.audioMode.querySelector('.recording-status-header');
        if (statusHeader) statusHeader.style.visibility = 'hidden';
        
        // Message d'attente
        if (heroElements.recordingHint) {
            heroElements.recordingHint.textContent = "Autorise l'accès au micro...";
        }
        
        startHeroRecording();
    }

    
    function showHeroTextMode() {
        heroState.mode = 'text';
        heroElements.choiceScreen.style.display = 'none';
        heroElements.audioMode.style.display = 'none';
        heroElements.textMode.style.display = 'block';
        heroElements.trustBadges.style.display = 'none';
        setTimeout(() => heroElements.textarea.focus(), 100);
    }
    
    function showHeroRecordingState() {
        heroElements.recordingState.style.display = 'block';
        heroElements.doneState.style.display = 'none';
    }
    
    function showHeroDoneState() {
        heroElements.recordingState.style.display = 'none';
        heroElements.doneState.style.display = 'block';
        heroElements.doneText.textContent = `${formatRecordingTime(heroState.recordingTime)}`;
        
        if (heroState.recordingTime < MIN_RECORDING_TIME) {
            heroElements.warningText.style.display = 'block';
            heroElements.submitAudio.disabled = true;
            heroElements.submitAudio.style.opacity = '0.5';
            // CACHER le bouton écouter si trop court
            heroElements.listenBtn.style.display = 'none';
        } else {
            heroElements.warningText.style.display = 'none';
            heroElements.submitAudio.disabled = false;
            heroElements.submitAudio.style.opacity = '1';
            // AFFICHER le bouton écouter si assez long
            heroElements.listenBtn.style.display = 'inline-flex';
        }
    }

    async function startHeroRecording() {
        console.log('🎙️ [Hero] Démarrage enregistrement');
        
        try {

            heroElements.doneState.style.display = 'none';
            heroElements.recordingState.style.display = 'block';

            if (!navigator.mediaDevices?.getUserMedia) {
                throw new Error('Navigateur non supporté');
            }
            
            heroAudioChunks = [];
            heroAudioBlob = null;
            heroAudioURL = null;
            heroState.hasRecording = false;
            heroState.recordingTime = 0;
            
            const constraints = {
                audio: {
                    echoCancellation: !isSafari(),
                    noiseSuppression: !isSafari(),
                    autoGainControl: !isSafari()
                }
            };
            
            // Attendre l'autorisation du micro
            heroAudioStream = await navigator.mediaDevices.getUserMedia(constraints);
            
            // ═══════════════════════════════════════════════════════════════
            // MICRO AUTORISÉ : Réafficher le header "ENREGISTREMENT EN COURS"
            // ═══════════════════════════════════════════════════════════════
            const statusHeader = heroElements.audioMode.querySelector('.recording-status-header');
            if (statusHeader) statusHeader.style.visibility = 'visible';
            
            if (heroElements.recordingHint) {
                heroElements.recordingHint.textContent = "C'est parti ! Parle-moi de ta situation...";
            }
            
            // Configurer MediaRecorder
            let mimeType = 'audio/webm;codecs=opus';
            if (isSafari() && !MediaRecorder.isTypeSupported(mimeType)) {
                mimeType = ['audio/mp4', 'audio/webm', 'audio/wav'].find(t => MediaRecorder.isTypeSupported(t)) || '';
            }
            
            const options = { audioBitsPerSecond: 128000 };
            if (mimeType) options.mimeType = mimeType;
            
            heroMediaRecorder = new MediaRecorder(heroAudioStream, options);
            
            heroMediaRecorder.addEventListener('dataavailable', (e) => {
                if (e.data.size > 0) heroAudioChunks.push(e.data);
            });
            
            heroMediaRecorder.addEventListener('stop', handleHeroRecordingStop);
            
            heroMediaRecorder.start(isSafari() ? 3000 : 1000);
            heroState.isRecording = true;
            heroRecordingStartTime = Date.now();
            
            // Démarrer le timer et l'animation
            startHeroTimer();
            
            const circleOuter = document.querySelector('.recording-circle-outer');
            if (circleOuter) circleOuter.classList.add('is-recording');
            
            console.log('✓ [Hero] Enregistrement démarré');
            
        } catch (error) {
            console.error('✗ [Hero] Erreur:', error);
            alert('Impossible d\'accéder au microphone.');
            showHeroChoiceScreen();
        }
    }
    
    function stopHeroRecording() {
        if (!heroMediaRecorder || !heroState.isRecording) return;
        
        heroState.recordingTime = Math.floor((Date.now() - heroRecordingStartTime) / 1000);
        
        try {
            if (heroMediaRecorder.state === 'recording') heroMediaRecorder.stop();
        } catch (e) {}
        
        heroState.isRecording = false;
        
        // Stopper l'animation pulse
        const circleOuter = document.querySelector('.recording-circle-outer');
        if (circleOuter) circleOuter.classList.remove('is-recording');
        
        if (heroRecordingTimer) {
            clearInterval(heroRecordingTimer);
            heroRecordingTimer = null;
        }
        
        if (heroAudioStream) {
            heroAudioStream.getTracks().forEach(track => track.stop());
            heroAudioStream = null;
        }
    }
    
    function handleHeroRecordingStop() {
        const mimeType = isSafari() ? 'audio/mp4' : 'audio/webm';
        heroAudioBlob = new Blob(heroAudioChunks, { type: mimeType });
        heroAudioURL = URL.createObjectURL(heroAudioBlob);
        heroState.hasRecording = true;
        
        if (heroElements.audioElement) {
            heroElements.audioElement.src = heroAudioURL;
            heroElements.audioElement.load();
        }
        
        showHeroDoneState();
    }
    
    function startHeroTimer() {
        heroElements.timerDisplay.textContent = '0:00';
        
        // Utiliser les hints personnalisés si définis (orientation vs homepage)
        const defaultHints = {
            start: "C'est parti ! Parle-moi de ta situation...",
            early: "Continue, détaille ce qui te pèse et te ferait vibrer...",
            mid: "Super ! Tu peux aussi parler de tes rêves...",
            late: "Parfait ! Tu peux terminer quand tu veux."
        };
        
        const hints = window.HERO_RECORDING_HINTS || defaultHints;
        
        heroRecordingTimer = setInterval(() => {
            const elapsed = Math.floor((Date.now() - heroRecordingStartTime) / 1000);
            heroElements.timerDisplay.textContent = formatRecordingTime(elapsed);
            
            if (elapsed < 5) {
                heroElements.recordingHint.textContent = hints.start;
            } else if (elapsed < 20) {
                heroElements.recordingHint.textContent = hints.early;
            } else if (elapsed < 45) {
                heroElements.recordingHint.textContent = hints.mid;
            } else {
                heroElements.recordingHint.textContent = hints.late;
            }
            
            if (elapsed >= MAX_RECORDING_TIME) stopHeroRecording();
        }, 1000);
    }
    
    function playHeroRecording() {
        if (heroElements.audioElement && heroAudioURL) {
            const listenBtn = heroElements.listenBtn;
            
            // Toggle play/pause
            if (!heroElements.audioElement.paused) {
                // En cours de lecture -> mettre en pause
                heroElements.audioElement.pause();
                if (listenBtn) {
                    listenBtn.innerHTML = '🎧 Écouter';
                }
                console.log('⏸️ [Hero] Audio mis en pause');
            } else {
                // En pause ou arrêté -> lire
                heroElements.audioElement.play().then(() => {
                    if (listenBtn) {
                        listenBtn.innerHTML = '⏸️ Pause';
                    }
                    console.log('▶️ [Hero] Lecture audio');
                }).catch(() => {
                    alert('Impossible de lire');
                });
                
                // Écouter la fin de lecture pour remettre le bouton
                heroElements.audioElement.onended = () => {
                    if (listenBtn) {
                        listenBtn.innerHTML = '🎧 Écouter';
                    }
                    console.log('✓ [Hero] Lecture terminée');
                };
            }
        }
    }
    
    function rerecordHero() {
        console.log('🔄 [Hero] Réenregistrement');
        
        // Stopper tout
        if (heroRecordingTimer) {
            clearInterval(heroRecordingTimer);
            heroRecordingTimer = null;
        }
        
        if (heroAudioStream) {
            heroAudioStream.getTracks().forEach(track => track.stop());
            heroAudioStream = null;
        }
        
        // Nettoyer audio
        if (heroAudioURL) URL.revokeObjectURL(heroAudioURL);
        heroAudioBlob = null;
        heroAudioURL = null;
        heroAudioChunks = [];
        heroMediaRecorder = null;
        
        // Reset état
        heroState.hasRecording = false;
        heroState.recordingTime = 0;
        heroState.isRecording = false;
        
        // FORCER l'UI immédiatement
        heroElements.doneState.style.display = 'none';
        heroElements.recordingState.style.display = 'block';
        
        // Démarrer après petit délai
        setTimeout(() => {
            startHeroRecording();
        }, 100);
    }
    
    function updateHeroCharCount() {
        const len = heroElements.textarea.value.length;
        heroElements.charCount.textContent = `${len} / ${MAX_TEXT_LENGTH}`;
        
        heroElements.submitText.disabled = len < MIN_TEXT_LENGTH;
        heroElements.submitText.style.opacity = len >= MIN_TEXT_LENGTH ? '1' : '0.5';
        heroState.textValue = heroElements.textarea.value;
    }
    

    async function submitHeroResponse(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        const HERO_QUESTION_ID = getHeroQuestionId();
        const QUIZ_ID = getQuizId();
        
        console.log('📤 [Hero] Soumission pour quiz:', QUIZ_ID, 'question:', HERO_QUESTION_ID);
        
        // Validation
        if (heroState.mode === 'audio' && heroState.hasRecording) {
            if (heroState.recordingTime < MIN_RECORDING_TIME) {
                alert('Enregistrement trop court. Développe un peu plus ta réponse.');
                return;
            }
        } else if (heroState.mode === 'text') {
            if (!heroState.textValue.trim() || heroState.textValue.trim().length < MIN_TEXT_LENGTH) {
                alert('Ta réponse est trop courte. Développe un peu plus.');
                return;
            }
        } else {
            return;
        }
        
        if (!window.homepageQuizAnswers) window.homepageQuizAnswers = {};
        if (!window.tempQuizAudios) window.tempQuizAudios = {};
        
        // IMPORTANT: Mettre à jour les variables globales
        isHomepageMode = true;
        window.currentQuizId = QUIZ_ID;
        
        let answerValue, answerText;
        
        if (heroState.mode === 'audio' && heroState.hasRecording) {
            const audioId = `audio_hero_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            
            window.tempQuizAudios[audioId] = {
                blob: heroAudioBlob,
                url: heroAudioURL,
                questionId: HERO_QUESTION_ID,
                duration: heroState.recordingTime,
                mimeType: isSafari() ? 'audio/mp4' : 'audio/webm'
            };
            
            answerValue = [`[AUDIO:${audioId}]`];
            answerText = `[Audio - ${heroState.recordingTime}s]`;
            
        } else if (heroState.mode === 'text' && heroState.textValue.trim()) {
            answerValue = [heroState.textValue.trim()];
            answerText = heroState.textValue.trim();
        }
        
        // Sauvegarder la réponse Hero
        homepageQuizAnswers[HERO_QUESTION_ID] = { value: answerValue, text: answerText };
        
        console.log('✅ [Hero] Réponse sauvegardée:', HERO_QUESTION_ID);
        
        // Sauvegarder l'état
        QuizPersistence.saveQuizState();
        
        // ═══════════════════════════════════════════════════════════════════════
        // NOUVEAU : Vérifier s'il y a d'autres questions après le Hero
        // ═══════════════════════════════════════════════════════════════════════
        
        // Charger les questions si pas encore fait
        let questions = getAllQuestions();
        if (!questions || questions.length === 0) {
            try {
                await loadQuestions(QUIZ_ID);
                questions = getAllQuestions();
            } catch (err) {
                console.error('[Hero] Erreur chargement questions:', err);
            }
        }
        
        // Trouver l'index de la question Hero dans le chapitre
        const chapters = QUIZ_CHAPTERS[QUIZ_ID]?.chapters || [];
        let heroQuestionIndex = -1;
        let totalQuestionsInChapter = 0;
        
        if (chapters.length > 0) {
            const chapter = chapters[0]; // Premier chapitre
            totalQuestionsInChapter = chapter.questions.length;
            heroQuestionIndex = chapter.questions.indexOf(HERO_QUESTION_ID);
            
            // Si pas trouvé par ID exact, chercher par comparaison de string
            if (heroQuestionIndex === -1) {
                heroQuestionIndex = chapter.questions.findIndex(qId => qId == HERO_QUESTION_ID);
            }
        }
        
        const hasMoreQuestions = heroQuestionIndex >= 0 && heroQuestionIndex < totalQuestionsInChapter - 1;
        
        console.log('[Hero] Index question hero:', heroQuestionIndex, '/', totalQuestionsInChapter, '- Autres questions:', hasMoreQuestions);
        
        // Ouvrir la modal
        const quizModal = document.getElementById('quizModal');
        const quizContent = document.getElementById('quizContent');
        const quizComplete = document.getElementById('quizComplete');
        const quizWelcome = document.getElementById('quizWelcome');
        
        if (!quizModal) {
            console.error('[Hero] Modal non trouvée');
            return;
        }
        
        document.body.style.overflow = 'hidden';
        document.body.classList.add('quiz-modal-open');
        quizModal.style.display = 'flex';
        quizModal.style.opacity = '1';
        
        if (hasMoreQuestions) {
            // ═══════════════════════════════════════════════════════════════════
            // Continuer le quiz — directement Q2
            // ═══════════════════════════════════════════════════════════════════
            console.log('[Hero] Continuation directe vers Q2...');

            if (quizWelcome) quizWelcome.style.display = 'none';
            if (quizComplete) quizComplete.style.display = 'none';
            if (quizContent) quizContent.style.display = 'block';

            // Positionner sur la question suivante
            currentChapter = 0;
            currentChapterQuestionIndex = heroQuestionIndex + 1;

            // Sauvegarder l'historique de la question Hero
            homepageQuestionHistory.push({
                chapter: 0,
                questionIndex: heroQuestionIndex,
                screenType: 'question',
                questionId: HERO_QUESTION_ID
            });

            // Afficher Q2 directement
            await showQuestion(QUIZ_ID);
            
        } else {
            // ═══════════════════════════════════════════════════════════════════
            // Pas d'autres questions, aller au formulaire lead
            // ═══════════════════════════════════════════════════════════════════
            console.log('[Hero] Pas d\'autres questions, affichage formulaire lead');
            
            if (quizContent) quizContent.style.display = 'none';
            if (quizWelcome) quizWelcome.style.display = 'none';
            if (quizComplete) quizComplete.style.display = 'block';
            
            QuizTracking.trackLeadFormView();
            setupQuizLeadForm();
        }
    }

    function setupHeroEventListeners() {
        heroElements.voiceBtn?.addEventListener('click', showHeroAudioMode);
        heroElements.textBtn?.addEventListener('click', showHeroTextMode);
        heroElements.placeholderZone?.addEventListener('click', showHeroTextMode);
        
        heroElements.stopBtn?.addEventListener('click', stopHeroRecording);
        heroElements.cancelRecording?.addEventListener('click', () => { stopHeroRecording(); showHeroChoiceScreen(); });
        heroElements.switchToTextFromRecording?.addEventListener('click', () => { stopHeroRecording(); showHeroTextMode(); });
        
        heroElements.listenBtn?.addEventListener('click', playHeroRecording);
        heroElements.rerecordBtn?.addEventListener('click', rerecordHero);
        heroElements.backFromDone?.addEventListener('click', showHeroChoiceScreen);
        heroElements.submitAudio?.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            submitHeroResponse(e);
        });
        
        heroElements.textarea?.addEventListener('input', updateHeroCharCount);
        heroElements.backFromText?.addEventListener('click', showHeroChoiceScreen);
        heroElements.submitText?.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            submitHeroResponse(e);
        });
        heroElements.switchToAudio?.addEventListener('click', showHeroAudioMode);
    }
    
    async function initHeroQuiz() {
        if (!document.getElementById('heroInputCard')) return;
        
        console.log('🚀 [Hero] Initialisation');
        
        // Détecte automatiquement le quiz selon la page
        const quizId = getQuizId(); // Retourne 'pack_orientation' ou 'pack_clarte'
        isHomepageMode = true;
        
        try {
            await loadQuestions(quizId);
            const questions = getAllQuestions();
            if (questions && questions.length > 0) {
                window.HERO_QUESTION_ID = questions[0].id;
                console.log('✓ [Hero] Question Hero définie:', window.HERO_QUESTION_ID);
                
                // Mettre à jour le titre de la question
                const heroTitle = document.querySelector('.hero-question-title');
                if (heroTitle && questions[0].question) {
                    heroTitle.textContent = questions[0].question;
                }
            }
        } catch (e) {
            console.warn('[Hero] Erreur préchargement:', e);
        }
        
        // Initialiser les placeholders (utilise window.HERO_PLACEHOLDERS si défini)
        initHeroPlaceholders();
        
        initHeroElements();
        setupHeroEventListeners();
        console.log('✓ [Hero] Prêt');
    }
    
    // ═══════════════════════════════════════════════════════════════════════════
    // AUTO-INITIALISATION AU CHARGEMENT DE LA PAGE
    // ═══════════════════════════════════════════════════════════════════════════
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(initHeroQuiz, 50);
        });
    } else {
        setTimeout(initHeroQuiz, 50);
    }

    // ============================================================================
// LOCALISATION DANS LEAD FORM (Question 26)

    // ============================================================================
// LOCALISATION DANS LEAD FORM (Question 26)
// ============================================================================

const LEAD_LOCATION_QUESTION_ID = 26;

/**
 * Initialise l'autocomplete de localisation dans le lead form
 */
function initLeadLocationAutocomplete() {
    const input = document.getElementById('quiz-location');
    const suggestions = document.getElementById('locationSuggestionsLead');
    const dataInput = document.getElementById('quiz-location-data');
    
    if (!input || !suggestions || !dataInput) {
        console.log('[Lead Location] Éléments non trouvés, skip init');
        return;
    }
    
    console.log('[Lead Location] Initialisation autocomplete');
    
    let timer;
    
    input.addEventListener('input', (e) => {
        clearTimeout(timer);
        const term = e.target.value.trim();
        
        // Réinitialiser les données cachées si l'user tape
        dataInput.value = '';
        
        if (term.length < 3) {
            suggestions.style.display = 'none';
            return;
        }
        
        timer = setTimeout(async () => {
            try {
                const cities = await fetchCities(term);
                displayLeadSuggestions(cities, suggestions, input, dataInput);
            } catch (error) {
                console.error('[Lead Location] Erreur fetch:', error);
                suggestions.style.display = 'none';
            }
        }, 300);
    });
    
    // Fermer suggestions si clic ailleurs
    document.addEventListener('click', (e) => {
        const container = input.closest('.location-container-lead');
        if (container && !container.contains(e.target)) {
            suggestions.style.display = 'none';
        }
    });
    
    // Empêcher soumission si pas de sélection valide
    input.addEventListener('blur', () => {
        setTimeout(() => {
            if (input.value && !dataInput.value) {
                // L'user a tapé mais pas sélectionné dans la liste
                // On garde le texte mais on marque comme non validé
                console.log('[Lead Location] Pas de sélection, texte libre:', input.value);
            }
        }, 200);
    });
}

/**
 * Affiche les suggestions de villes pour le lead form
 * (réutilise la logique existante avec adaptations)
 */
function displayLeadSuggestions(cities, container, input, dataInput) {
    container.innerHTML = '';
    
    if (!cities?.length) {
        container.style.display = 'none';
        return;
    }
    
    // Dédupliquer par nom+région
    const unique = new Map();
    cities.forEach(city => {
        if (city?.name) {
            const key = `${city.name}-${city.region || ''}`;
            if (!unique.has(key)) unique.set(key, city);
        }
    });
    
    Array.from(unique.values()).slice(0, 5).forEach(city => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        
        const nameDiv = document.createElement('div');
        nameDiv.className = 'city-text';
        nameDiv.textContent = city.name;
        
        const regionDiv = document.createElement('div');
        regionDiv.className = 'region-text';
        regionDiv.textContent = city.region || '';
        
        item.appendChild(nameDiv);
        item.appendChild(regionDiv);
        
        item.addEventListener('click', () => {
            const display = city.region ? `${city.name}, ${city.region}` : city.name;
            input.value = display;
            dataInput.value = JSON.stringify({
                name: city.name,
                region: city.region || '',
                display_name: display
            });
            container.style.display = 'none';
            
            // Retirer l'erreur visuelle si présente
            input.style.borderColor = '';
            input.style.boxShadow = '';
            
            console.log('[Lead Location] Ville sélectionnée:', display);
        });
        
        container.appendChild(item);
    });
    
    container.style.display = unique.size > 0 ? 'block' : 'none';
}

/**
 * Valide et récupère la réponse localisation du lead form
 * @returns {object|null} { value: [...], text: '...' } ou null si invalide
 */
function getLeadLocationAnswer() {
    const input = document.getElementById('quiz-location');
    const dataInput = document.getElementById('quiz-location-data');
    
    if (!input) return null;
    
    const textValue = input.value.trim();
    
    if (!textValue) {
        return null; // Vide
    }
    
    // Si l'user a sélectionné dans la liste
    if (dataInput?.value) {
        try {
            const parsed = JSON.parse(dataInput.value);
            return {
                value: [parsed.name],
                text: parsed.display_name || parsed.name
            };
        } catch (e) {
            console.warn('[Lead Location] Erreur parsing data:', e);
        }
    }
    
    // Fallback: texte libre (l'user n'a pas cliqué sur une suggestion)
    return {
        value: [textValue],
        text: textValue
    };
}

/**
 * Valide le champ localisation du lead form
 * @returns {boolean}
 */
function validateLeadLocation() {
    const input = document.getElementById('quiz-location');
    
    if (!input) return true; // Pas de champ, pas de validation
    
    const value = input.value.trim();
    
    if (!value) {
        showFormMessage('error', '📍', 'Ville manquante', 'Indique ta ville pour continuer');
        focusAndHighlight('quiz-location');
        return false;
    }
    
    if (value.length < 2) {
        showFormMessage('error', '📍', 'Ville invalide', 'Le nom de ville semble trop court');
        focusAndHighlight('quiz-location');
        return false;
    }
    
    return true;
}

// Export pour utilisation globale
window.initLeadLocationAutocomplete = initLeadLocationAutocomplete;
window.getLeadLocationAnswer = getLeadLocationAnswer;
window.validateLeadLocation = validateLeadLocation;
    
})();

// ============================================================================
// EXPORTS GLOBAUX
// ============================================================================

window.initializeHomepageQuiz = initializeHomepageQuiz;
window.startAnalysis = startAnalysis;
window.closeConfirmationModal = closeConfirmationModal;
window.initHeroElements = initHeroElements;
window.initHeroPlaceholders = initHeroPlaceholders;
window.showHeroTextMode = showHeroTextMode;
window.showHeroAudioMode = showHeroAudioMode;
window.showHeroChoiceScreen = showHeroChoiceScreen;

