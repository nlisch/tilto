//New quiz js file
let allQuestions = [];
let currentQuestionIndex = 0;
let userAnswers = {};
let isEditingFromReview = false;
let questionHistory = [];
// Variables pour le mode homepage
let isHomepageMode = false;
let homepageQuizAnswers = {};
let homepageQuestionHistory = [];
let homepageCurrentQuestionIndex = 0;
let homepageAllQuestions = [];
let currentQuestionAudioState = {}; // État audio pour la question actuelle
let globalAudioStorage = {}; // Stockage global de tous les audios

// Variables globales pour l'enregistrement
let isRecording = false;
let mediaRecorder = null;
let audioStream = null;
let audioChunks = [];
let audioBlob = null;
let audioURL = null;
let recordingTimer = null;
let recordingStartTime = 0;
let recordingTimerDisplay = null;
let animationFrame = null;

// 1. REMPLACER votre structure QUIZ_CHAPTERS existante par celle-ci
const QUIZ_CHAPTERS = {
    'pack_clarte': {
        chapters: [
            {
                id: 'chapter_1',
                title: 'Ton parcours jusqu\'ici',
                intro: 'On commence doucement : raconte-moi ton parcours, de là où tu viens.',
                questions: [63, 51, 52, 53],
                transition: 'Merci 🙏 tu viens de poser les bases. Maintenant, explorons ce que tu aimerais retrouver demain.',
                introSeen: false // AJOUT IMPORTANT
            },
            {
                id: 'chapter_2', 
                title: 'Ce que tu cherches pour demain',
                intro: null,
                questions: [54, 55, 56],
                transition: 'Super ✨ tu as mis des mots sur tes envies. Voyons maintenant ce que tu as déjà exploré et ce dont tu aurais besoin.',
                introSeen: false
            },
            {
                id: 'chapter_3',
                title: 'Tes pistes & besoins', 
                intro: null,
                questions: [57, 58],
                transition: 'Merci 🙌 tu as identifié tes besoins. Passons au dernier chapitre : ton futur idéal.',
                introSeen: false
            },
            {
                id: 'chapter_4',
                title: 'Ton futur idéal',
                intro: null, 
                questions: [59, 26, 60, 61, 62],
                transition: null,
                introSeen: false
            }
        ]
    }
};

// Variables globales pour les chapitres
let currentChapter = 0;
let currentChapterQuestionIndex = 0;
let isShowingTransition = false;

// ===== SYSTÈME DE TRACKING ANALYTICS =====
const QuizTracking = {
    // Constantes pour les noms d'événements
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
    
    // Tracker une page virtuelle
    trackPage: function(pagePath, pageTitle) {
        if (typeof gtag === 'undefined') {
            console.log('[Tracking] Page virtuelle:', pagePath, pageTitle);
            return;
        }
        
        gtag('event', 'page_view', {
            page_path: pagePath,
            page_title: pageTitle,
            page_location: window.location.href
        });
        
        console.log('[GA] Page virtuelle trackée:', pagePath);
    },
    
    // Tracker un événement
    trackEvent: function(eventName, eventParams = {}) {
        if (typeof gtag === 'undefined') {
            console.log('[Tracking] Event:', eventName, eventParams);
            return;
        }
        
        // Ajouter des paramètres par défaut
        const params = {
            ...eventParams,
            quiz_mode: isHomepageMode ? 'homepage' : 'authenticated',
            timestamp: new Date().toISOString()
        };
        
        gtag('event', eventName, params);
        
        console.log('[GA] Event tracké:', eventName, params);
    },
    
    // Tracker le démarrage du quiz
    trackQuizStart: function() {
        this.trackPage('/quiz/start', 'Quiz - Démarrage');
        this.trackEvent(this.EVENTS.QUIZ_START, {
            event_category: 'Quiz',
            event_label: 'quiz_homepage_start'
        });
    },
    
    // Tracker l'intro d'un chapitre
    trackChapterIntro: function(chapterNumber, chapterTitle) {
        const pagePath = `/quiz/chapter-${chapterNumber}/intro`;
        const pageTitle = `Quiz - Chapitre ${chapterNumber}: ${chapterTitle}`;
        
        this.trackPage(pagePath, pageTitle);
        this.trackEvent(this.EVENTS.QUIZ_CHAPTER_START, {
            event_category: 'Quiz',
            event_label: `chapter_${chapterNumber}_intro`,
            chapter_number: chapterNumber,
            chapter_title: chapterTitle
        });
    },
    
    // Tracker une question
    trackQuestion: function(chapterNumber, questionIndex, questionId, questionText) {
        const pagePath = `/quiz/chapter-${chapterNumber}/question-${questionIndex + 1}`;
        const pageTitle = `Quiz - Chapitre ${chapterNumber} - Question ${questionIndex + 1}`;
        
        this.trackPage(pagePath, pageTitle);
    },
    
    // Tracker une réponse
    trackQuestionAnswer: function(questionId, questionText, answerType, answerLength = null) {
        this.trackEvent(this.EVENTS.QUIZ_QUESTION_ANSWERED, {
            event_category: 'Quiz',
            event_label: `question_${questionId}`,
            question_id: questionId,
            question_text: questionText.substring(0, 100), // Limiter la longueur
            answer_type: answerType, // 'text', 'audio', 'choice', 'multi_choice', etc.
            answer_length: answerLength,
            chapter_number: currentChapter + 1,
            question_index: currentChapterQuestionIndex + 1
        });
    },
    
    // Tracker un enregistrement audio
    trackAudioRecording: function(questionId, duration) {
        this.trackEvent(this.EVENTS.QUIZ_AUDIO_RECORDED, {
            event_category: 'Quiz',
            event_label: `audio_question_${questionId}`,
            question_id: questionId,
            duration_seconds: duration,
            chapter_number: currentChapter + 1
        });
    },
    
    // Tracker une saisie texte
    trackTextEntry: function(questionId, textLength) {
        this.trackEvent(this.EVENTS.QUIZ_TEXT_ENTERED, {
            event_category: 'Quiz',
            event_label: `text_question_${questionId}`,
            question_id: questionId,
            text_length: textLength,
            chapter_number: currentChapter + 1
        });
    },
    
    // Tracker une transition entre chapitres
    trackChapterTransition: function(fromChapter, toChapter) {
        const pagePath = `/quiz/chapter-${fromChapter}/transition`;
        const pageTitle = `Quiz - Transition Chapitre ${fromChapter} vers ${toChapter}`;
        
        this.trackPage(pagePath, pageTitle);
        this.trackEvent(this.EVENTS.QUIZ_CHAPTER_COMPLETE, {
            event_category: 'Quiz',
            event_label: `chapter_${fromChapter}_complete`,
            from_chapter: fromChapter,
            to_chapter: toChapter
        });
    },
    
    // Tracker la navigation arrière
    trackBackNavigation: function(fromQuestion, toQuestion) {
        this.trackEvent(this.EVENTS.QUIZ_NAVIGATION_BACK, {
            event_category: 'Quiz',
            event_label: 'back_button_clicked',
            from_question: fromQuestion,
            to_question: toQuestion,
            chapter_number: currentChapter + 1
        });
    },
    
    // Tracker la complétion du quiz
    trackQuizComplete: function(totalQuestions, totalDuration) {
        const pagePath = '/quiz/complete';
        const pageTitle = 'Quiz - Terminé';
        
        this.trackPage(pagePath, pageTitle);
        this.trackEvent(this.EVENTS.QUIZ_COMPLETE, {
            event_category: 'Quiz',
            event_label: 'quiz_completed',
            total_questions: totalQuestions,
            total_duration_seconds: totalDuration,
            total_chapters: currentChapter + 1
        });
    },
    
    // Tracker l'affichage du formulaire lead
    trackLeadFormView: function() {
        const pagePath = '/quiz/lead-form';
        const pageTitle = 'Quiz - Formulaire de contact';
        
        this.trackPage(pagePath, pageTitle);
        this.trackEvent(this.EVENTS.QUIZ_LEAD_FORM_VIEW, {
            event_category: 'Quiz',
            event_label: 'lead_form_viewed'
        });
    },
    
    // Tracker la soumission du formulaire lead
    trackLeadSubmit: function(hasAudioResponses, responseCount) {
        this.trackEvent(this.EVENTS.QUIZ_LEAD_SUBMIT, {
            event_category: 'Quiz',
            event_label: 'lead_form_submitted',
            has_audio_responses: hasAudioResponses,
            response_count: responseCount,
            value: 1 // Valeur de conversion
        });
    },
    
    // Tracker une erreur
    trackError: function(errorType, errorMessage, context = {}) {
        this.trackEvent(this.EVENTS.QUIZ_ERROR, {
            event_category: 'Quiz',
            event_label: errorType,
            error_message: errorMessage,
            ...context
        });
    }
};

// Initialisation du quiz
document.addEventListener('DOMContentLoaded', async function() {
    const quizContent = getElement('#quizContent');
    
    // Vérifier si on est sur la page quiz normale ou en mode popup homepage
    if (!quizContent) {
        log("Pas sur la page quiz");
        return;
    }

    // Si on est en mode homepage (détecté par la présence du modal parent)
    const isInModal = quizContent.closest('.quiz-modal');
    if (isInModal) {
        log("Mode quiz homepage détecté");
        // L'initialisation sera faite par openQuizModal()
        return;
    }

    // NOUVEAU : Attacher la sauvegarde à la fermeture de la modal
    setTimeout(() => {
        const closeModalBtns = document.querySelectorAll('.close-quiz-modal, .quiz-modal-overlay');
        closeModalBtns.forEach(btn => {
            btn.addEventListener('click', handleQuizModalClose);
        });
        console.log('Gestionnaire de fermeture modal attaché');
    }, 1000);

    // Mode quiz normal - garder le code existant
    log("=== DÉMARRAGE INITIALISATION QUIZ NORMAL ===");

    // Initialiser les éléments de l'interface modale
    const backToAnswersBtn = document.getElementById('backToAnswersBtn');
    const confirmAnalysisBtn = document.getElementById('confirmAnalysisBtn');
    const modal = document.getElementById('confirmationModal');

    // Configuration des événements de la modale
    if (backToAnswersBtn) {
        backToAnswersBtn.addEventListener('click', () => {
            if (modal) {
                modal.style.display = 'none';
            }
        });
    }

    if (confirmAnalysisBtn) {
        confirmAnalysisBtn.addEventListener('click', () => {
            if (modal) {
                modal.style.display = 'none';
            }
            confirmAnalysis();
        });
    }

    // Permettre la fermeture en cliquant en dehors de la modale
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.style.display = 'none';
            }
        });
    }

    log("DOM quiz chargé");
    
    try {
        const urlParams = new URLSearchParams(window.location.search);
        const quizId = urlParams.get('quiz_id') || 'personal_profiling';
        const shouldResume = urlParams.get('resume') === 'true';
        const showRecap = urlParams.get('show_recap') === 'true';

        log("Paramètres URL:", {
            quizId,
            shouldResume,
            showRecap
        });

        // Initialiser l'historique global
        window.questionHistory = [];
        
        // Charger les questions
        await loadQuestions(quizId);
        
        // Vérifier d'abord si on doit afficher le récapitulatif
        if (showRecap) {
            log("=== AFFICHAGE RÉCAPITULATIF (showRecap) ===");
            showCongratulations();
            toggleReviewAnswers();
            return; // Important : arrêter l'exécution ici
        }
        
        // Récupérer la progression
        log("Chargement de la progression...");
        const progressData = await loadQuizProgress(quizId);
        log("Données de progression reçues:", progressData);
        
        if (progressData && progressData.progress) {
            log("Status du quiz:", progressData.progress.quiz_status);
            log("Quiz complété?", progressData.quiz_completed);
            log("Nombre de questions répondues:", progressData.progress.questions_answered_count);

            const isQuizCompleted = progressData.quiz_completed || 
                                  progressData.progress.quiz_status === 'completed' || 
                                  progressData.progress.quiz_status === 'answers_review';
            
            log("Quiz considéré comme terminé?", isQuizCompleted);

            if (isQuizCompleted) {
                log("=== AFFICHAGE RÉCAPITULATIF (Quiz terminé) ===");
                showCongratulations();
                toggleReviewAnswers();
                return; // Important : arrêter l'exécution ici
            }

            if (shouldResume && progressData.progress.questions_answered_count > 0) {
                log("=== REPRISE DU QUIZ ===");
                
                // Restaurer l'état du quiz
                currentQuestionIndex = progressData.progress.questions_answered_count || 0;
                userAnswers = progressData.answers || {};
                window.questionHistory = progressData.progress.question_history || [];
                
                log("Index de départ:", currentQuestionIndex);
                log("Historique chargé:", window.questionHistory);
                log("Nombre de réponses:", Object.keys(userAnswers).length);

                // Sauvegarder l'historique dans le localStorage
                if (window.questionHistory.length > 0) {
                    localStorage.setItem(`quiz_${quizId}_history`, JSON.stringify(window.questionHistory));
                }
                
                // Afficher la question actuelle
                quizContent.style.display = 'block';
                await showQuestion(quizId);
            } else {
                // Démarrer un nouveau quiz
                log("=== NOUVEAU QUIZ (Pas de reprise) ===");
                currentQuestionIndex = 0;
                window.questionHistory = [];
                userAnswers = {};
                localStorage.removeItem(`quiz_${quizId}_history`);
                quizContent.style.display = 'block';
                await showQuestion(quizId);
            }
        } else {
            // Démarrer un nouveau quiz
            log("=== NOUVEAU QUIZ ===");
            currentQuestionIndex = 0;
            window.questionHistory = [];
            userAnswers = {};
            localStorage.removeItem(`quiz_${quizId}_history`);
            quizContent.style.display = 'block';
            await showQuestion(quizId);
        }
    } catch (error) {
        log("=== ERREUR D'INITIALISATION ===");
        log("Message d'erreur:", error.message);
        log("Stack trace:", error.stack);
        console.error("Erreur d'initialisation:", error);
        alert(getTranslation('erreurChargement'));
    }
});

// 2. Corriger getCurrentQuestionId pour être plus robuste
function getCurrentQuestionInChapter() {
    const chapter = getCurrentChapter('pack_clarte');
    if (!chapter || currentChapterQuestionIndex >= chapter.questions.length) {
        return null;
    }
    
    const questionId = chapter.questions[currentChapterQuestionIndex];
    
    // Pour le mode homepage
    if (isHomepageMode && homepageAllQuestions) {
        return homepageAllQuestions.find(q => q.id == questionId);
    }
    
    // Pour le mode normal
    if (allQuestions) {
        return allQuestions.find(q => q.id == questionId);
    }
    
    return null;
}

// Fonction de chargement des questions modifiée
async function loadQuestions(quizId) {
    console.log('Début loadQuestions pour quiz:', quizId);
    
    try {
        const response = await fetch(`/get_questions/?quiz_id=${encodeURIComponent(quizId)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error('Failed to load questions');
        }

        const data = await response.json();
        console.log('Questions reçues du serveur:', data);
        
        if (!data.questions || !Array.isArray(data.questions)) {
            throw new Error('Invalid questions data');
        }

        allQuestions = data.questions.map(q => ({
            ...q,
            max_choices: q.max_choices !== null ? q.max_choices : Infinity
        }));

        console.log('Questions chargées et formatées:', allQuestions);
        
        // Ne pas appeler showQuestion ici - laissons le code d'initialisation le faire
        return allQuestions;
    } catch (error) {
        console.error('Erreur lors du chargement des questions:', error);
        throw error; // Propager l'erreur pour la gestion dans l'initialisation
    }
}

function findNextAvailableQuestion(currentIndex, answers) {
    for (let i = currentIndex + 1; i < allQuestions.length; i++) {
        const question = allQuestions[i];
        
        // Si la question n'est pas conditionnelle, elle est disponible
        if (!question.is_conditional) {
            return i;
        }
        
        // Si la question est conditionnelle, vérifier si elle doit être affichée
        if (question.parent_question_id && answers[question.parent_question_id]) {
            const parentAnswer = answers[question.parent_question_id];
            const conditionValue = question.condition_value ? JSON.parse(question.condition_value) : null;
            
            // Vérifier si la réponse du parent correspond à la condition
            if (shouldShowConditionalQuestion(parentAnswer, conditionValue)) {
                return i;
            }
        }
    }
    return -1;
}

async function loadQuizProgress(quizId) {
    const requestId = Math.random().toString(36).substring(7);
    log(`=== DÉBUT LOAD QUIZ PROGRESS (${requestId}) ===`);
    log(`QuizId: ${quizId}`);
    try {
        const response = await fetch(`/get_quiz_progress/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error(getTranslation('erreurChargement'));
        }

        const data = await response.json();
        log(`[${requestId}] Données reçues:`, data);
        log(`[${requestId}] Status du quiz:`, data.progress?.quiz_status);
        log(`[${requestId}] Quiz complété?`, data.quiz_completed);

        // Initialiser notre historique global avec celui du serveur
        window.questionHistory = data.progress.question_history || [];
        log("Historique initialisé à:", window.questionHistory);

        // Si on a des questions répondues
        if (window.questionHistory.length > 0) {
            // Se positionner sur la dernière question répondue
            currentQuestionIndex = window.questionHistory[window.questionHistory.length - 1];
            
            // Afficher cette question
            const quizContent = getElement('#quizContent', true);
            if (quizContent) quizContent.style.display = 'block';
            await showQuestion(quizId);

            // Puis trouver et passer à la prochaine question disponible
            const nextIndex = findNextAvailableQuestion(currentQuestionIndex, data.answers);
            if (nextIndex !== -1) {
                currentQuestionIndex = nextIndex;
                await showQuestion(quizId);
            }
        }

        userAnswers = data.answers || {};

        if (!data.quiz_completed) {
            const quizContent = getElement('#quizContent', true);
            if (quizContent && quizContent.style.display !== 'block') {
                quizContent.style.display = 'block';
                await showQuestion(quizId);
            }
        }
        
        return data;
    } catch (error) {
        log("Erreur lors du chargement de la progression : " + error);
        alert(getTranslation('erreurProgression'));
        throw error;
    }
}

function shouldShowConditionalQuestion(parentAnswer, conditionValue) {
    if (!parentAnswer || !conditionValue) return false;
    
    // Si la condition est un tableau de valeurs
    if (Array.isArray(conditionValue)) {
        return parentAnswer.value.some(value => conditionValue.includes(value));
    }
    
    // Si la condition est une valeur simple
    return parentAnswer.value.includes(conditionValue.toString());
}

function createQuestionElement(question, quizId) {
    log(`Création de l'élément pour la question: ${question.id}`);
    const questionDiv = document.createElement('div');
    questionDiv.className = 'question active';
    questionDiv.id = 'question-' + question.id;

    try {
        if (question.media_type === 'image' && question.media_url) {
            appendQuestionImage(questionDiv, question.media_url);
        }
        
        if (question.question) {
            appendQuestionTitle(questionDiv, question.question, question); 
        } else {
            throw new Error(getTranslation('erreurChargement'));
        }
        
        // Ajouter l'indice de question s'il existe
        appendQuestionHint(questionDiv, question);
        
        // Ajouter les instructions de choix pour les questions multi-select
        if (question.question_type === 'multi_select') {
            appendChoiceInstructions(questionDiv, question);
        }

        if (question.question_type === 'location') {
            appendLocationInput(questionDiv);
        } else if (question.question_type === 'free_text') {
            appendFreeTextInput(questionDiv, question.max_character_input);
        } else if (question.question_type === 'ranking') {
            if (Array.isArray(question.choices) && question.choices.length > 0) {
                appendRankingList(questionDiv, question);
            } else {
                throw new Error(getTranslation('erreurChargement'));
            }
        } else if (Array.isArray(question.choices) && question.choices.length > 0) {
            appendChoiceList(questionDiv, question);
        } else {
            throw new Error(getTranslation('erreurChargement'));
        }

        appendErrorElement(questionDiv);
        appendButtonContainer(questionDiv, quizId);

    } catch (error) {
        log(`Erreur lors de la création de l'élément pour la question ${question.id}: ${error.message}`);
        questionDiv.textContent = getTranslation('erreurChargement');
    }

    return questionDiv;
}

function appendLocationInput(questionDiv) {
    const locationContainer = document.createElement('div');
    locationContainer.className = 'location-container';

    const locationInput = document.createElement('input');
    locationInput.type = 'text';
    locationInput.className = 'location-input';
    locationInput.placeholder = getTranslation('emptyLocationError') || 'Enter your city';
    locationInput.autocomplete = 'off';

    const suggestionsContainer = document.createElement('div');
    suggestionsContainer.className = 'suggestions-container';
    suggestionsContainer.style.display = 'none';

    const locationData = document.createElement('input');
    locationData.type = 'hidden';
    locationData.className = 'location-data';

    locationContainer.appendChild(locationInput);
    locationContainer.appendChild(locationData);
    locationContainer.appendChild(suggestionsContainer);
    questionDiv.appendChild(locationContainer);

    let debounceTimer;
    locationInput.addEventListener('input', (e) => {
        clearTimeout(debounceTimer);
        const searchTerm = e.target.value;
        
        if (searchTerm.length < 3) {
            suggestionsContainer.style.display = 'none';
            return;
        }

        debounceTimer = setTimeout(() => {
            fetchCities(searchTerm)
                .then(cities => displaySuggestions(cities, suggestionsContainer, locationInput, locationData));
        }, 300);
    });

    document.addEventListener('click', (e) => {
        if (!locationContainer.contains(e.target)) {
            suggestionsContainer.style.display = 'none';
        }
    });
}

function getLocationAnswer() {
    const locationInput = document.querySelector('.location-input');
    const locationData = document.querySelector('.location-data');
    let value = locationInput.value.trim();
    let fullData = {};
    
    try {
        fullData = JSON.parse(locationData.value);
    } catch (e) {
        fullData = { display_name: value };
    }
    
    return [[value], fullData.display_name || value];
}

// Fonction pour récupérer les suggestions de villes
async function fetchCities(searchTerm) {
    try {
        if (!searchTerm || searchTerm.length < 3) {
            return [];
        }

        const response = await fetch(`/api/cities?search=${encodeURIComponent(searchTerm)}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        
        if (!Array.isArray(data)) {
            console.error('Format de données invalide:', data);
            return [];
        }

        return data;
    } catch (error) {
        console.error('Error fetching cities:', error);
        return [];
    }
}

// Fonction améliorée pour afficher les suggestions
function displaySuggestions(cities, container, input, dataInput) {
    if (!container || !input || !dataInput) {
        console.error('Éléments manquants pour l\'affichage des suggestions');
        return;
    }

    container.innerHTML = '';
    
    if (!Array.isArray(cities) || cities.length === 0) {
        container.style.display = 'none';
        return;
    }

    // Map pour dédupliquer les villes
    const uniqueCities = new Map();

    cities.forEach(city => {
        if (!city || !city.name) return;
        
        const key = `${city.name}-${city.region || ''}`;
        if (!uniqueCities.has(key)) {
            uniqueCities.set(key, city);
        }
    });

    Array.from(uniqueCities.values()).forEach(city => {
        try {
            const suggestion = document.createElement('div');
            suggestion.className = 'suggestion-item';

            const cityText = document.createElement('div');
            cityText.className = 'city-text';
            cityText.textContent = city.name;

            const regionText = document.createElement('div');
            regionText.className = 'region-text';
            regionText.textContent = city.region || '';

            suggestion.appendChild(cityText);
            suggestion.appendChild(regionText);
            
            suggestion.addEventListener('click', () => {
                const displayText = city.region ? 
                    `${city.name}, ${city.region}` : city.name;
                input.value = displayText;
                dataInput.value = JSON.stringify({
                    name: city.name,
                    region: city.region || '',
                    display_name: displayText,
                    lat: city.lat,
                    lon: city.lon
                });
                container.style.display = 'none';
            });
            
            container.appendChild(suggestion);
        } catch (error) {
            console.error('Erreur lors de la création de la suggestion:', error);
        }
    });
    
    container.style.display = uniqueCities.size > 0 ? 'block' : 'none';
}

function validateLocationAnswer() {
    const locationInput = document.querySelector('.location-input');
    const locationData = document.querySelector('.location-data');
    
    if (!locationInput.value.trim()) {
        showError('emptyLocationError');
        return false;
    }
    
    try {
        const data = JSON.parse(locationData.value);
        if (!data || !data.name) {
            showError('invalidLocationError');
            return false;
        }
    } catch (e) {
        showError('invalidLocationError');
        return false;
    }
    
    return true;
}

function appendChoiceList(questionDiv, question) {
    const tagList = document.createElement('div');
    
    const isCardGrid = question.question_type === 'select' && 
                       question.choices && 
                       question.choices.length === 4 &&
                       question.choices.some(c => c.choice_description);
    
    if (isCardGrid) {
        tagList.classList.add('choice-cards-grid', `choice-cards-grid-question-${question.id}`);
    } else {
        tagList.classList.add('tag-list', `tag-list-question-${question.id}`);
    }
    
    // 🔥 AJOUT : Empêcher la propagation des clics sur le conteneur
    tagList.addEventListener('click', function(e) {
        // Ne rien faire ici, laisser les enfants gérer
        e.stopPropagation();
    });
    
    question.choices.forEach(choice => {
        if (choice && choice.value !== undefined && choice.text !== undefined) {
            const tag = createChoiceTag(choice, question);
            tagList.appendChild(tag);
        } else {
            console.warn('Choix invalide ignoré:', choice);
        }
    });
    
    questionDiv.appendChild(tagList);
    
    const hasOtherChoice = question.choices.some(choice => 
        choice.text.trim().toLowerCase() === 'autre'
    );
    if (hasOtherChoice) {
        appendOtherInputContainer(questionDiv, question.choices);
    }
}

function appendQuestionImage(questionDiv, mediaUrl) {
    const img = document.createElement('img');
    img.src = mediaUrl;
    img.alt = 'Question Image';
    img.className = 'question-image';
    questionDiv.appendChild(img);
}

function appendQuestionTitle(questionDiv, questionText, question = null) {
    const questionTitle = document.createElement('h2');
    questionTitle.className = 'question-title';
    questionTitle.innerHTML = `<span class="question-text">${questionText}</span>`;
    questionDiv.appendChild(questionTitle);
    
    // ✅ Afficher la description uniquement pour SELECT avec 4 choix
    if (question && 
        question.question_description && 
        question.question_type === 'select' && 
        question.choices && 
        question.choices.length === 4) {
        const descriptionDiv = document.createElement('div');
        descriptionDiv.className = 'question-description';
        descriptionDiv.textContent = question.question_description;
        questionDiv.appendChild(descriptionDiv);
    }
}

// Variables pour l'enregistrement vocal
const MAX_RECORDING_TIME = 120; // 2 minutes
const ENCOURAGEMENT_MESSAGES = {
    // Messages génériques par timing (en secondes) - POUR BULLES UNIQUEMENT
    'default': {
        45: "Prends ton temps",
        75: "Tu peux faire une pause si tu veux", 
        120: "Tu maîtrises parfaitement",
        160: "Tu peux conclure quand tu le souhaites"
    },
    // Messages spécifiques par question - POUR BULLES UNIQUEMENT
    51: {
        45: "Qu'est-ce qui t'a marqué ?",
        75: "Continue, ton parcours m'intéresse",
        120: "N'hésite pas à parler de tes ressentis",
        160: "Parfait, ajoute ce qui te vient"
    },
    52: {
        45: "Qu'est-ce qui te vient en premier ?",
        75: "Continue à explorer cette idée", 
        120: "Tu peux donner des détails concrets",
        160: "Développe autant que tu veux"
    },
    54: {
        45: "Explore cette envie profonde",
        75: "Continue à creuser cette idée",
        120: "Qu'est-ce qui te ferait vibrer ?",
        160: "Parfait, développe cette vision"
    },
    55: {
        45: "Qu'est-ce qu'on te dit souvent ?",
        75: "Continue, ces retours m'intéressent",
        120: "Tu peux donner des exemples concrets",
        160: "Super, ajoute d'autres feedbacks"
    },
    57: {
        45: "Qu'est-ce qui t'a inspiré ?",
        75: "Continue sur cette piste",
        120: "Tu peux détailler cette expérience",
        160: "Parfait, raconte-moi la suite"
    },
    59: {
        45: "Décris ce que tu visualises",
        75: "Continue à rêver, c'est parfait",
        120: "Qu'est-ce qui te fait vibrer ?",
        160: "Ajoute tous les détails qui comptent"
    },
    61: {
        45: "Pas besoin d'être précis",
        75: "Dis juste ce qui te vient",
        120: "Tu peux donner un ordre de grandeur",
        160: "Parfait, c'est suffisant"
    }
};

// NOUVEAUX MESSAGES STATIQUES PAR QUESTION
const STATIC_RECORDING_MESSAGES = {
    'default': "Je t'écoute...",
    51: "Raconte avec tes mots",
    52: "Pas de pression, réfléchis", 
    54: "Ce qui compte vraiment pour toi",
    55: "Pense aussi perso ✨ ",
    56: "Ce qui te viens en premier",
    57: "Des loisirs, bénévolat, tests…",
    59: "Laisse ton imagination parler",
    61: "Plus c’est précis, plus c’est puissant 🎯"
};

// Messages d'invitation avant de cliquer sur le micro
const QUESTION_INVITATION_MESSAGES = {
    'default': "Partage ton histoire",
    51: "Depuis le début, les secteurs, les structures sans trop de détails", 
    52: "Spontanément, en positif et en négatif ?",
    54: "Pense à ce qui t’apporte de l’énergie…",
    55: "Pas forcément pro, mais ce qui revient souvent",
    56: "Repositionnement ou nouveau départ ? Transition plutôt en mois ou en années?",
    57: "Raconte tes explorations",
    59: "Laisse ton imagination parler",
    60: "Parle de ton environnement rêvé", 
    61: "Partage ton idée de salaire",
};

// Variables pour l'analyse audio en temps réel
let audioContext;
let silenceTimer = null; // S'assurer que c'est null au départ
let lastVolumeCheck = 0;  // Timestamp de la dernière détection de voix
let analyser = null;      // Analyseur audio
let dataArray = null;     // Buffer pour les données audio

// 7. CONSTANTES CORRIGÉES
const SILENCE_TIMEOUT = 25000; // 25 secondes au lieu de 20
const MIN_RECORDING_TIME = 15;  // 15 secondes au lieu de 20 pour être moins strict


const MAX_TEXT_LENGTH = 2000; // MANQUAIT - cause de votre erreur
const MIN_TEXT_LENGTH = 500; // Si pas déjà défini

// Nouvelles variables pour l'enregistrement continu
let existingAudioDuration = 0; // Durée de l'audio existant
let isContinuingRecording = false; // Flag pour savoir si on continue un enregistrement


function handleSessionExpiration(error) {
    if (error instanceof SyntaxError && error.message.includes("Unexpected token '<'")) {
        alert("Votre session a expiré. Vous allez être redirigé vers la page de connexion.");
        window.location.href = '/login';
        return true;
    }
    return false;
}


// Fonction pour créer l'affichage du temps d'enregistrement
function createRecordingTimer(container) {
    const timerContainer = document.createElement('div');
    timerContainer.className = 'recording-timer';
    timerContainer.style.display = 'none';
    
    const timerLabel = document.createElement('span');
    timerLabel.className = 'timer-label';
    timerLabel.textContent = 'Durée : ';
    
    recordingTimerDisplay = document.createElement('span');
    recordingTimerDisplay.className = 'timer-display';
    recordingTimerDisplay.textContent = '00:00';
    
    timerContainer.appendChild(timerLabel);
    timerContainer.appendChild(recordingTimerDisplay);
    
    container.appendChild(timerContainer);
    return timerContainer;
}




function appendRankingList(questionDiv, question) {
    const rankingList = document.createElement('div');
    rankingList.className = `ranking-list ranking-list-question-${question.id}`;
    question.choices.forEach((choice, index) => {
        if (choice && choice.value !== undefined && choice.text !== undefined) {
            const rankingItem = document.createElement('div');
            rankingItem.className = 'ranking-item';
            rankingItem.draggable = true;
            rankingItem.id = `ranking-item-${question.id}-${index}`;
            rankingItem.dataset.value = choice.value;

            const rankNumber = document.createElement('span');
            rankNumber.className = 'rank-number';
            rankNumber.textContent = index + 1;
            rankingItem.appendChild(rankNumber);

            const choiceText = document.createElement('span');
            choiceText.className = 'choice-text';
            choiceText.textContent = choice.text;
            rankingItem.appendChild(choiceText);

            rankingItem.addEventListener('dragstart', dragStart);
            rankingItem.addEventListener('dragover', dragOver);
            rankingItem.addEventListener('drop', drop);
            rankingItem.addEventListener('dragend', dragEnd);

            rankingList.appendChild(rankingItem);
        } else {
            log(`Choix invalide ignoré pour la question ${question.id}`);
        }
    });
    questionDiv.appendChild(rankingList);
}

function appendChoiceInstructions(questionDiv, question) {
    const instructionsDiv = document.createElement('div');
    instructionsDiv.className = 'choice-instructions';
    
    let instructions = '';
    const icon = '✨';

    const isInfiniteChoices = !question.max_choices || question.max_choices === Infinity;

    if (isInfiniteChoices && !question.min_choices) {
        instructions = getTranslation('maxChoicesInfinite');
    } else if (question.min_choices && isInfiniteChoices) {
        instructions = getTranslation('minChoicesInfinite', { min: question.min_choices });
    } else if (question.min_choices && question.max_choices) {
        if (question.min_choices === question.max_choices) {
            instructions = getTranslation('exactChoices', { count: question.min_choices });
        } else {
            instructions = getTranslation('rangeChoices', { min: question.min_choices, max: question.max_choices });
        }
    } else if (question.min_choices) {
        instructions = getTranslation('minChoicesOnly', { min: question.min_choices });
    } else if (question.max_choices) {
        instructions = getTranslation('maxChoicesOnly', { max: question.max_choices });
    }

    if (instructions) {
        instructionsDiv.innerHTML = `
            <p class="instruction-text">
                <span class="instruction-icon">${icon}</span>
                ${instructions}
            </p>
        `;
        
        const questionTitle = questionDiv.querySelector('.question-title');
        if (questionTitle && questionTitle.nextSibling) {
            questionDiv.insertBefore(instructionsDiv, questionTitle.nextSibling);
        } else {
            questionDiv.appendChild(instructionsDiv);
        }
    }
}

function createChoiceTag(choice, question) {
    const tag = document.createElement('div');
    
    const isCardMode = question.question_type === 'select' && 
                       question.choices && 
                       question.choices.length === 4 &&
                       choice.choice_description;
    
    if (isCardMode) {
        tag.className = 'choice-card';
        tag.dataset.value = choice.value;
        tag.dataset.maxCharacterInput = choice.max_character_input || '2000';
        
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

        const imageContainer = document.createElement('div');
        imageContainer.className = 'image-container';

        if (choice.choice_media_type === 'emoji' && choice.choice_media_url) {
            appendChoiceMedia(imageContainer, choice.choice_media_url, choice.text, 'emoji');
        } else if (choice.choice_media_type === 'image' && choice.choice_media_url) {
            appendChoiceMedia(imageContainer, choice.choice_media_url, choice.text, 'image');
        }
        
        tag.appendChild(imageContainer);
        
        if (!choice.choice_media_type || !choice.choice_media_url) {
            const textSpan = document.createElement('span');
            textSpan.className = 'choice-text';
            textSpan.textContent = choice.text;
            tag.appendChild(textSpan);
        }
    }
    console.log('🏷️ Création tag:', {
        text: choice.text,
        value: choice.value,
        questionType: question.question_type,
        hasExistingListener: tag.onclick !== null
    });

    // 🔥 CORRECTION : Arrêter la propagation + passer directement "tag"
        tag.addEventListener('click', function(e) {
            console.log('🖱️ CLIC ÉVÉNEMENT DÉCLENCHÉ');
            console.log('Event target:', e.target);
            console.log('Event currentTarget:', e.currentTarget);
            console.log('This:', this);
            console.log('Tag:', tag);
            console.log('Sont identiques?', this === tag);
            
            e.stopPropagation();
            e.preventDefault();
            
            console.log('➡️ Appel de selectChoice...');
            selectChoice(this, question);
            console.log('✅ selectChoice terminé');
        });
    
    return tag;
}

function appendOtherInputContainer(questionDiv, choices) {
    const otherChoice = choices.find(choice => choice.text.toLowerCase() === 'autre');
    const maxLength = otherChoice && otherChoice.max_character_input ? parseInt(otherChoice.max_character_input, 10) : 2000;
    
    const otherInputContainer = document.createElement('div');
    otherInputContainer.className = 'other-input-container';
    otherInputContainer.style.display = 'none';

    const otherInput = document.createElement('textarea');
    otherInput.className = 'other-input';
    otherInput.placeholder = getTranslation('otherInputPlaceholder');
    otherInput.maxLength = maxLength;

    const charCount = document.createElement('div');
    charCount.className = 'char-count';
    charCount.textContent = `0 / ${maxLength}`;

    otherInput.addEventListener('input', () => updateCharCount(otherInput, charCount, maxLength));

    otherInputContainer.appendChild(otherInput);
    otherInputContainer.appendChild(charCount);
    questionDiv.appendChild(otherInputContainer);
}

function appendChoiceMedia(tag, mediaUrl, altText, mediaType) {
    if (mediaType === 'emoji') {
        // ✅ Pour les emojis : afficher directement le caractère Unicode
        const emojiSpan = document.createElement('span');
        emojiSpan.className = 'choice-emoji';
        emojiSpan.textContent = mediaUrl; // L'emoji est déjà le caractère (🔍, 🚀, etc.)
        tag.appendChild(emojiSpan);
    } else {
        // ✅ Pour les images : utiliser une balise <img>
        const media = document.createElement('img');
        media.src = mediaUrl;
        media.alt = altText;
        media.className = 'choice-image';
        tag.appendChild(media);
    }
}

function appendErrorElement(questionDiv) {
    const errorElement = document.createElement('div');
    errorElement.className = 'choices-error';
    errorElement.style.display = 'none';
    questionDiv.appendChild(errorElement);
}

function appendButtonContainer(questionDiv, quizId) {
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'button-container';

    // Conteneur pour les boutons
    const buttonsDiv = document.createElement('div');
    buttonsDiv.className = 'flex gap-4';

    // Bouton précédent
    if (!isEditingFromReview) {
        const prevButton = document.createElement('button');
        prevButton.className = 'prev-btn';
        prevButton.textContent = getTranslation('previousButton');
        prevButton.addEventListener('click', (e) => {
            e.preventDefault();
            previousQuestion(quizId);
        });
        
        // Vérifier si on peut reculer en se basant sur l'historique global
        const canGoBack = window.questionHistory && 
                         Array.isArray(window.questionHistory) && 
                         window.questionHistory.length > 0 &&
                         currentQuestionIndex > window.questionHistory[0];
        
        log("Peut reculer:", canGoBack);
        log("questionHistory:", window.questionHistory);
        log("currentQuestionIndex:", currentQuestionIndex);
        
        prevButton.style.display = canGoBack ? 'inline-block' : 'none';
        buttonsDiv.appendChild(prevButton);
    }

    // Bouton suivant
    const actionButton = document.createElement('button');
    if (isEditingFromReview) {
        actionButton.className = 'next-btn';
        actionButton.innerHTML = `
            <span class="flex items-center">
                ${getTranslation('updateAndReturn')}
            </span>
        `;
        actionButton.addEventListener('click', (event) => {
            event.preventDefault();
            updateAnswerAndReturn(allQuestions[currentQuestionIndex], quizId);
        });
    } else {
        actionButton.className = 'next-btn';
        actionButton.textContent = currentQuestionIndex === allQuestions.length - 1 ? 
            getTranslation('finishButton') : getTranslation('nextButton');
        actionButton.addEventListener('click', (event) => {
            event.preventDefault();
            nextQuestion(allQuestions[currentQuestionIndex], quizId);
        });
    }
    
    buttonsDiv.appendChild(actionButton);
    buttonContainer.appendChild(buttonsDiv);
    questionDiv.appendChild(buttonContainer);
}

async function updateAnswerAndReturn(question, quizId) {
    try {
        if (!validateAnswer(question)) {
            return;
        }

        const [answerValue, answerText] = getQuestionAnswer(question);
        
        const payload = {
            quiz_id: quizId,
            current_question_index: currentQuestionIndex,
            answer: {
                question_id: question.id,
                value: answerValue,
                text: answerText
            },
            is_reviewing: true
        };

        console.log('Envoi mise à jour avec payload:', payload);

        const response = await fetch('/update_quiz_progress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error('Échec de la mise à jour');
        }

        const result = await response.json();
        
        // Cacher le quiz
        const quizContent = getElement('#quizContent');
        if (quizContent) {
            quizContent.style.display = 'none';
        }

        // Afficher le récapitulatif avec les données reçues directement
        const accordionContainer = document.getElementById('answersAccordion');
        if (accordionContainer) {
            // Vider le conteneur
            accordionContainer.innerHTML = '';

            // Créer les cartes pour chaque question avec les réponses reçues
            allQuestions.forEach((question, index) => {
                const answer = result.answers[question.id];
                if (answer) {
                    const questionCard = document.createElement('div');
                    questionCard.className = 'bg-white rounded-lg shadow-sm mb-4';

                    questionCard.innerHTML = `
                        <div class="p-4 border-l-4 border-[#D7942D]">
                            <div class="mb-2">
                                <h4 class="text-lg font-medium mb-3">${question.question}</h4>
                                <div class="answer-tag bg-[#D7942D] text-white rounded-lg p-3 flex items-center transition-all hover:bg-[#c17d1e]">
                                    ${answer.text}
                                </div>
                            </div>
                            <div class="mt-3">
                                <button 
                                    class="edit-question-btn btn flex items-center gap-2"
                                    data-index="${index}">
                                    <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                        <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                                    </svg>
                                    Modifier
                                </button>
                            </div>
                        </div>
                    `;

                    accordionContainer.appendChild(questionCard);
                }
            });
        }

        // Afficher l'écran de félicitations
        const congratulations = getElement('#congratulations');
        if (congratulations) {
            congratulations.style.display = 'block';
            congratulations.scrollIntoView({ behavior: 'smooth' });
        }

        showUpdateConfirmation();
        isEditingFromReview = false;
        setTimeout(() => {
            console.log('Réattachement des écouteurs après léger délai');
            attachEditButtonListeners();
        }, 100);

    } catch (error) {
        console.error("Erreur lors de la mise à jour:", error);
        alert(getTranslation('erreurMiseAJour'));
    }
}

function showUpdateConfirmation() {
    // Créer un message flash vert sans SVG
    const confirmationMessage = document.createElement('div');
    confirmationMessage.className = 'fixed bottom-4 right-4 bg-green-100 border-l-4 border-green-500 text-green-700 p-4 rounded shadow-lg z-50';
    confirmationMessage.innerHTML = `
        <div class="flex items-center">
            <span class="font-bold">${getTranslation('answerUpdated')}</span>
        </div>
    `;
    
    // Ajouter le message flash au corps du document
    document.body.appendChild(confirmationMessage);

    // Supprimer le message après 3 secondes
    //setTimeout(() => confirmationMessage.remove(), 3000);
}


function selectChoice(tag, question) {
    console.log('🎯 selectChoice APPELÉ');
    console.log('Processing status:', tag?.dataset?.processing);
    
    // ✅ CORRECTION : Vérifier ET undefined ET 'true'
    if (tag.dataset.processing === 'true' || tag.dataset.processing === undefined) {
        // ✅ Si undefined, initialiser à false
        if (tag.dataset.processing === undefined) {
            tag.dataset.processing = 'false';
        }
        
        // ✅ Si déjà en cours, ignorer
        if (tag.dataset.processing === 'true') {
            console.log('⏳ Déjà en traitement, ignoré');
            return;
        }
    }
    
    // ✅ Poser le verrou
    tag.dataset.processing = 'true';
    console.log('✅ Verrou posé:', tag.dataset.processing);
    
    hideError();
    
    // Trouver le conteneur DIRECT
    const container = tag.parentElement;
    
    if (!container) {
        console.error('Conteneur introuvable');
        tag.dataset.processing = 'false'; // ✅ Libérer même en cas d'erreur
        return;
    }
    
    // Lister UNIQUEMENT les enfants directs
    const allTags = [];
    for (let i = 0; i < container.children.length; i++) {
        const child = container.children[i];
        if (child.classList.contains('tag') || child.classList.contains('choice-card')) {
            allTags.push(child);
        }
    }
    
    const isOtherOption = tag.textContent.trim().toLowerCase() === 'autre';
    
    // Logique de sélection
    if (question.question_type !== 'multi_select') {
        // Single select
        allTags.forEach(t => {
            if (t !== tag) t.classList.remove('selected');
        });
        tag.classList.add('selected');
    } else {
        // Multi-select
        if (isOtherOption) {
            allTags.forEach(t => {
                if (t !== tag) t.classList.remove('selected');
            });
        } else {
            const otherTag = allTags.find(t => 
                t.textContent.trim().toLowerCase() === 'autre'
            );
            if (otherTag && otherTag.classList.contains('selected')) {
                otherTag.classList.remove('selected');
                const otherInputContainer = document.querySelector('.other-input-container');
                if (otherInputContainer) {
                    otherInputContainer.style.display = 'none';
                    const otherInput = otherInputContainer.querySelector('.other-input');
                    if (otherInput) otherInput.value = '';
                }
            }
        }
        
        tag.classList.toggle('selected');
    }

    // Gérer l'input "autre"
    const otherInputContainer = document.querySelector('.other-input-container');
    if (otherInputContainer && isOtherOption) {
        const isSelected = tag.classList.contains('selected');
        otherInputContainer.style.display = isSelected ? 'block' : 'none';
        
        if (isSelected) {
            const otherInput = otherInputContainer.querySelector('.other-input');
            if (otherInput) {
                otherInput.focus();
                const maxLength = parseInt(tag.dataset.maxCharacterInput, 10) || 500;
                otherInput.maxLength = maxLength;
                
                const charCount = otherInputContainer.querySelector('.char-count');
                if (charCount) {
                    updateCharCount(otherInput, charCount, maxLength);
                }
            }
        }
    }
    
    // ✅ CRITIQUE : Libérer le verrou dans un setTimeout
    setTimeout(() => {
        tag.dataset.processing = 'false';
        console.log('🔓 Verrou libéré:', tag.dataset.processing);
    }, 100);
}

async function showQuestion(quizId) {
    log("Affichage de la question avec chapitres");
    
    const quizContent = getElement('#quizContent');
    if (quizContent) {
        quizContent.style.display = 'block';
    }

    if (!allQuestions || allQuestions.length === 0) {
        console.error('Aucune question disponible');
        return;
    }

    const quizForm = getElement('#quizForm');
    if (!quizForm) {
        console.error('Form container not found');
        return;
    }

    try {
        const chapter = getCurrentChapter(quizId);
        
        if (!chapter) {
            console.log('Fin des chapitres atteinte');
            showResult();
            return;
        }


        // Vérifier si on doit afficher la transition
        if (isShowingTransition) {
            showChapterTransition(chapter, quizId);
            return;
        }

        // Afficher la question normale
        const currentQuestion = getCurrentQuestionInChapter();
        
        if (!currentQuestion) {
            // Fin du chapitre - passer à la transition ou au chapitre suivant
            const chapters = QUIZ_CHAPTERS[quizId]?.chapters || [];
            if (currentChapter < chapters.length - 1 && chapter.transition) {
                isShowingTransition = true;
                showChapterTransition(chapter, quizId);
                return;
            } else {
                // Passer au chapitre suivant
                currentChapter++;
                currentChapterQuestionIndex = 0;
                await showQuestion(quizId);
                return;
            }
        }

        quizForm.innerHTML = '';
        const questionElement = createQuestionElement(currentQuestion, quizId);
        quizForm.appendChild(questionElement);

        if (userAnswers[currentQuestion.id]) {
            restorePreviousAnswer(currentQuestion, quizForm);
        }

        updateChapterProgress();

    } catch (error) {
        console.error('Erreur lors de l\'affichage de la question:', error);
        quizForm.innerHTML = `<p class="error">Erreur lors du chargement de la question</p>`;
    }
}


function restorePreviousAnswer(question, quizForm) {
    const previousAnswer = userAnswers[question.id];
    if (previousAnswer) {
        if (question.question_type === 'free_text') {
            restoreFreeTextAnswer(quizForm, previousAnswer, question.max_character_input);
        } else if (question.question_type === 'ranking') {
            restoreRankingAnswer(quizForm, previousAnswer);
        } else if (question.question_type === 'location') {
            restoreLocationAnswer(quizForm, previousAnswer);
        } else {
            restoreChoiceAnswer(quizForm, previousAnswer, question.max_character_input);
        }
    }
}

function restoreLocationAnswer(quizForm, previousAnswer) {
    const locationInput = quizForm.querySelector('.location-input');
    const locationData = quizForm.querySelector('.location-data');
    
    if (locationInput && previousAnswer.value) {
        locationInput.value = previousAnswer.value[0] || '';
        locationData.value = JSON.stringify({
            name: previousAnswer.value[0],
            display_name: previousAnswer.text
        });
    }
}

function restoreFreeTextAnswer(quizForm, previousAnswer, maxCharacterInput) {
    const maxLength = maxCharacterInput || 2000;
    const textArea = quizForm.querySelector('.free-text-input');
    const audioContainer = quizForm.querySelector('.enhanced-audio-container');
    const charCount = quizForm.querySelector('.char-count');
    
    console.log('restoreFreeTextAnswer appelé:', {
        hasTextArea: !!textArea,
        hasAudioContainer: !!audioContainer,
        hasCharCount: !!charCount,
        previousAnswer: previousAnswer
    });
    
    if (!textArea || !audioContainer) {
        console.error('Éléments manquants dans restoreFreeTextAnswer');
        return;
    }
    
    // Vérifier si la réponse précédente est un audio
    const isAudioAnswer = Array.isArray(previousAnswer.value) && 
                          previousAnswer.value[0] && 
                          previousAnswer.value[0].startsWith('[AUDIO:');
    
    console.log('Type de réponse:', isAudioAnswer ? 'Audio' : 'Texte');
    
    if (isAudioAnswer) {
        // Mode vocal - s'assurer que l'audio est affiché
        console.log('Restauration mode vocal');
        
        const vocalBtn = quizForm.querySelector('.mode-btn[data-mode="vocal"]');
        const textBtn = quizForm.querySelector('.mode-btn[data-mode="text"]');
        
        if (vocalBtn && textBtn) {
            // Activer le mode vocal
            vocalBtn.classList.add('active');
            textBtn.classList.remove('active');
            
            // Afficher le conteneur audio, masquer le texte
            audioContainer.style.display = 'block';
            textArea.style.display = 'none';
            if (charCount) charCount.style.display = 'none';
        }
        
        // Extraire et restaurer l'audio
        try {
            const audioId = previousAnswer.value[0].match(/\[AUDIO:(.+)\]/)?.[1];
            console.log('Restauration audio ID:', audioId);
            
            if (audioId && window.tempQuizAudios && window.tempQuizAudios[audioId]) {
                const audioData = window.tempQuizAudios[audioId];
                console.log('Audio trouvé dans tempQuizAudios:', {
                    id: audioId,
                    hasBlob: !!audioData.blob,
                    duration: audioData.duration
                });
                
                // Restaurer dans l'état de la question
                const questionId = getCurrentQuestionId();
                if (!currentQuestionAudioState[questionId]) {
                    currentQuestionAudioState[questionId] = {
                        audioBlob: null,
                        audioURL: null,
                        isRecording: false,
                        duration: 0
                    };
                }
                
                // Restaurer complètement l'état audio
                currentQuestionAudioState[questionId].audioBlob = audioData.blob;
                currentQuestionAudioState[questionId].audioURL = audioData.url || URL.createObjectURL(audioData.blob);
                currentQuestionAudioState[questionId].duration = audioData.duration || 0;
                currentQuestionAudioState[questionId].isRecording = false;
                
                // Mettre à jour les variables globales
                audioBlob = audioData.blob;
                audioURL = currentQuestionAudioState[questionId].audioURL;
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
                        console.log('Audio element configuré');
                    }
                }, 100);
                
            } else {
                console.warn('Audio non trouvé pour ID:', audioId);
                // Interface audio vide mais prête
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
        // Mode texte - restaurer le texte MAIS GARDER LA POSSIBILITÉ DE BASCULER
        console.log('Restauration mode texte');
        
        const vocalBtn = quizForm.querySelector('.mode-btn[data-mode="vocal"]');
        const textBtn = quizForm.querySelector('.mode-btn[data-mode="text"]');
        
        if (vocalBtn && textBtn) {
            // Activer le mode texte
            textBtn.classList.add('active');
            vocalBtn.classList.remove('active');
        }
        
        // ✅ CORRECTION : Afficher le texte, masquer l'audio
        textArea.style.display = 'block';
        textArea.disabled = false;
        audioContainer.style.display = 'none';
        if (charCount) charCount.style.display = 'block';
        
        // Restaurer le contenu du texte
        if (textArea) {
            textArea.value = previousAnswer.value[0] || '';
            
            // Mettre à jour le compteur de caractères
            if (charCount) {
                updateCharCount(textArea, charCount, maxLength);
            }
            
            console.log('Texte restauré:', textArea.value);
        }
        
        // ✅ NOUVEAU : Ajouter/réafficher le bouton pour retourner à l'audio
        const existingBackBtn = quizForm.querySelector('.back-to-audio-btn');
        if (!existingBackBtn && textArea && textArea.parentNode) {
            const backBtn = document.createElement('button');
            backBtn.type = 'button';
            backBtn.className = 'back-to-audio-btn';
            backBtn.innerHTML = '🎙️ Finalement, je préfère parler';
            backBtn.style.cssText = `
                margin-top: 1rem;
                padding: 0.5rem 1rem;
                background: none;
                border: 1px solid #A11857;
                color: #A11857;
                border-radius: 8px;
                font-size: 0.85rem;
                cursor: pointer;
                opacity: 0.7;
                transition: all 0.3s ease;
            `;
            
            // Gestion des événements pour mobile et desktop
            const handleBackToAudio = function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                // Éviter le double déclenchement touch/click
                if (e.type === 'touchend') {
                    this.touchHandled = true;
                    setTimeout(() => { this.touchHandled = false; }, 500);
                } else if (e.type === 'click' && this.touchHandled) {
                    return;
                }
                
                // Supprimer la réponse texte de l'état
                const questionId = getCurrentQuestionId();
                if (isHomepageMode && homepageQuizAnswers[questionId]) {
                    delete homepageQuizAnswers[questionId];
                } else if (userAnswers[questionId]) {
                    delete userAnswers[questionId];
                }
                
                // Vider le textarea
                if (textArea) textArea.value = '';
                
                // Basculer l'interface
                if (audioContainer) audioContainer.style.display = 'block';
                if (textArea) {
                    textArea.style.display = 'none';
                }
                if (charCount) charCount.style.display = 'none';
                backBtn.remove();
                
                console.log('Retour vers mode audio');
            };
            
            backBtn.addEventListener('touchend', handleBackToAudio, { passive: false });
            backBtn.addEventListener('click', handleBackToAudio);
            
            // Effet hover
            backBtn.addEventListener('mouseenter', () => {
                backBtn.style.opacity = '1';
                backBtn.style.transform = 'translateY(-1px)';
            });
            
            backBtn.addEventListener('mouseleave', () => {
                backBtn.style.opacity = '0.7';
                backBtn.style.transform = 'translateY(0)';
            });
            
            textArea.parentNode.appendChild(backBtn);
        } else if (existingBackBtn) {
            // S'assurer que le bouton existant est visible
            existingBackBtn.style.display = 'block';
        }
    }
}

function restoreRankingAnswer(quizForm, previousAnswer) {
    const rankingList = quizForm.querySelector('.ranking-list');
    if (rankingList && Array.isArray(previousAnswer.value)) {
        const rankingItems = Array.from(rankingList.querySelectorAll('.ranking-item'));
        previousAnswer.value.forEach((value, index) => {
            const item = rankingItems.find(item => item.dataset.value === value);
            if (item) {
                rankingList.appendChild(item);
            }
        });
        updateRankNumbers();
    }
}

function restoreChoiceAnswer(quizForm, previousAnswer) {
    // ✅ CORRECTION : Chercher .tag ET .choice-card
    const tags = quizForm.querySelectorAll('.tag, .choice-card');
    
    // Déselectionner d'abord tous les tags
    tags.forEach(tag => {
        tag.classList.remove('selected');
    });

    // Sélectionner uniquement le bon tag en se basant sur la valeur
    tags.forEach(tag => {
        if (previousAnswer.value.includes(tag.dataset.value)) {
            tag.classList.add('selected');
            
            // Si c'est une réponse "autre"
            if (tag.textContent.trim().toLowerCase() === 'autre') {
                const otherInputContainer = quizForm.querySelector('.other-input-container');
                const otherInput = otherInputContainer ? otherInputContainer.querySelector('.other-input') : null;
                if (otherInput && otherInputContainer) {
                    const otherText = previousAnswer.text;
                    otherInput.value = otherText;
                    otherInputContainer.style.display = 'block';
                    const maxLength = parseInt(tag.dataset.maxCharacterInput, 10) || 500;
                    const charCount = otherInputContainer.querySelector('.char-count');
                    if (charCount) {
                        updateCharCount(otherInput, charCount, maxLength);
                    }
                }
            }
        }
    });
}

async function nextQuestion(question, quizId) {
    try {
        if (!validateAnswer(question)) {
            return;
        }

        const [answerValue, answerText] = getQuestionAnswer(question);
        
        // Enregistrer la réponse localement
        userAnswers[question.id] = { value: answerValue, text: answerText };
        
        // Gérer l'historique de navigation
        if (!window.questionHistory) {
            window.questionHistory = [];
        }
        
        // Si nous sommes revenus en arrière et que nous avançons sur un nouveau chemin,
        // nous devons tronquer l'historique jusqu'à la position actuelle
        const currentIndex = window.questionHistory.indexOf(currentQuestionIndex);
        if (currentIndex !== -1) {
            window.questionHistory = window.questionHistory.slice(0, currentIndex + 1);
        }
        
        // Ajouter l'index actuel à l'historique s'il n'y est pas déjà
        if (!window.questionHistory.includes(currentQuestionIndex)) {
            window.questionHistory.push(currentQuestionIndex);
        }

        // Déterminer si c'est la dernière question possible - ADAPTATION CHAPITRES
        const chapter = getCurrentChapter(quizId);
        const chapters = QUIZ_CHAPTERS[quizId]?.chapters || [];
        const isLastQuestionInChapter = chapter && currentChapterQuestionIndex >= chapter.questions.length - 1;
        const isLastChapter = currentChapter >= chapters.length - 1;
        const isLastQuestion = isLastQuestionInChapter && isLastChapter;

        // Créer le payload avec le statut approprié
        const payload = {
            quiz_id: quizId,
            current_question_index: currentQuestionIndex,
            answer: {
                question_id: question.id,
                value: answerValue,
                text: answerText
            },
            is_completed: isLastQuestion
        };

        // Mettre à jour le quiz sur le serveur
        await updateQuizProgress(question.id, answerValue, answerText, quizId, isLastQuestion);
        
        // Mettre à jour l'historique côté serveur
        await updateQuestionHistory(quizId, window.questionHistory);

        // Trouver la prochaine question basée sur next_question_id en premier
        const selectedChoice = question.choices?.find(choice =>
            choice.value === answerValue[0] && choice.next_question_id
        );

        if (selectedChoice && selectedChoice.next_question_id) {
            // Si un next_question_id est spécifié dans le choix, l'utiliser
            const nextQuestionIndex = allQuestions.findIndex(q =>
                q.id === selectedChoice.next_question_id
            );
            if (nextQuestionIndex !== -1) {
                // ADAPTATION CHAPITRES : Trouver dans quel chapitre se trouve cette question
                const nextQuestion = allQuestions[nextQuestionIndex];
                let foundChapter = false;
                
                for (let chapterIdx = 0; chapterIdx < chapters.length; chapterIdx++) {
                    const chapterQuestionIdx = chapters[chapterIdx].questions.indexOf(nextQuestion.id);
                    if (chapterQuestionIdx !== -1) {
                        currentChapter = chapterIdx;
                        currentChapterQuestionIndex = chapterQuestionIdx;
                        foundChapter = true;
                        break;
                    }
                }
                
                if (foundChapter) {
                    currentQuestionIndex = nextQuestionIndex;
                    // Ajouter le nouvel index à l'historique
                    window.questionHistory.push(currentQuestionIndex);
                    await updateQuestionHistory(quizId, window.questionHistory);
                    await showQuestion(quizId);
                    return;
                }
            }
        }

        // LOGIQUE CHAPITRES : Passer à la question suivante dans le chapitre
        if (chapter) {
            currentChapterQuestionIndex++;
            
            // Vérifier si on a terminé le chapitre
            if (currentChapterQuestionIndex >= chapter.questions.length) {
                // Fin du chapitre - vérifier s'il y a une transition
                if (currentChapter < chapters.length - 1 && chapter.transition) {
                    isShowingTransition = true;
                    await showQuestion(quizId);
                    return;
                } else if (currentChapter >= chapters.length - 1) {
                    // Fin de tous les chapitres
                    showCongratulations();
                    return;
                } else {
                    // Passer directement au chapitre suivant
                    currentChapter++;
                    currentChapterQuestionIndex = 0;
                    await showQuestion(quizId);
                    return;
                }
            }
            
            // Continuer dans le chapitre actuel
            const nextQuestionInChapter = getCurrentQuestionInChapter();
            if (nextQuestionInChapter) {
                // Mettre à jour currentQuestionIndex pour correspondre à la nouvelle question
                currentQuestionIndex = allQuestions.findIndex(q => q.id === nextQuestionInChapter.id);
                // Ajouter le nouvel index à l'historique
                window.questionHistory.push(currentQuestionIndex);
                await updateQuestionHistory(quizId, window.questionHistory);
                await showQuestion(quizId);
                return;
            }
        }

        // FALLBACK : Si le système de chapitres ne fonctionne pas, utiliser l'ancienne logique
        const nextAvailableIndex = findNextAvailableQuestion(currentQuestionIndex, userAnswers);
        const isLastQuestionFallback = nextAvailableIndex === -1;

        // Si c'est la dernière question possible
        if (isLastQuestionFallback) {
            showCongratulations();
        } else {
            currentQuestionIndex = nextAvailableIndex;
            // Ajouter le nouvel index à l'historique avant d'afficher la question
            window.questionHistory.push(currentQuestionIndex);
            await updateQuestionHistory(quizId, window.questionHistory);
            await showQuestion(quizId);
        }
        
    } catch (error) {
        log("Erreur dans nextQuestion: " + error);
        console.error(error);
        alert(getTranslation('erreurGlobale'));
    }
}



function getQuestionAnswer(question) {
    switch (question.question_type) {
        case 'ranking':
            return getRankingAnswer();
        case 'free_text':
            return getFreeTextAnswer();
        case 'location':
            return getLocationAnswer();
        case 'multi_select':
            return getMultiSelectAnswer();
        default:
            // ✅ CORRECTION : Chercher dans le formulaire actif ET gérer les cards
            const quizForm = document.getElementById('quizForm');
            const selectedTag = quizForm.querySelector('.tag.selected, .choice-card.selected');
            
            if (!selectedTag) {
                console.error('No answer selected');
                throw new Error('No answer selected');
            }
            
            // S'assurer que la valeur est bien capturée
            const answerValue = [selectedTag.dataset.value];
            let answerText;
            
            // Si c'est une réponse "autre"
            if (selectedTag.textContent.trim().toLowerCase() === 'autre') {
                const otherInput = quizForm.querySelector('.other-input');
                if (otherInput && otherInput.style.display !== 'none') {
                    answerText = otherInput.value.trim();
                } else {
                    answerText = selectedTag.textContent.trim();
                }
            } else {
                // ✅ Pour les cards, prendre le texte du titre
                const cardTitle = selectedTag.querySelector('.choice-card-title');
                answerText = cardTitle ? cardTitle.textContent.trim() : selectedTag.textContent.trim();
            }
            
            // Log pour débogage
            console.log('Capturing answer:', {
                element: selectedTag,
                value: answerValue,
                text: answerText,
                questionId: question.id
            });

            return [answerValue, answerText];
    }
}

function getRankingAnswer() {
    const rankingItems = document.querySelectorAll('.ranking-item');
    const answerValue = Array.from(rankingItems).map(item => item.dataset.value);
    const answerText = Array.from(rankingItems).map(item => item.querySelector('.choice-text').textContent).join(' > ');
    return [answerValue, answerText];
}

function getMultiSelectAnswer() {
    // ✅ CORRECTION : Chercher .tag ET .choice-card
    const selectedTags = document.querySelectorAll('.tag.selected, .choice-card.selected');
    const answerValue = Array.from(selectedTags).map(tag => tag.dataset.value);
    
    // Gérer le cas où "autre" est sélectionné
    const otherTag = Array.from(selectedTags).find(tag => tag.textContent.toLowerCase() === 'autre');
    if (otherTag) {
        const otherInput = document.querySelector('.other-input');
        if (otherInput && otherInput.style.display !== 'none') {
            const otherText = otherInput.value.trim();
            return [answerValue, otherText];
        }
    }
    
    // ✅ Pour les cards, prendre le texte des titres
    const answerText = Array.from(selectedTags).map(tag => {
        const cardTitle = tag.querySelector('.choice-card-title');
        return cardTitle ? cardTitle.textContent.trim() : tag.textContent.trim();
    }).join(', ');
    
    return [answerValue, answerText];
}

function validateAnswer(question) {
    log("Début de la validation de la réponse");
    hideError();

    if (question.question_type === 'ranking') {
        return validateRankingAnswer();
    } else if (question.question_type === 'free_text') {
        return validateFreeTextAnswer(question.max_character_input);
    } else if (question.question_type === 'location') {
        return validateLocationAnswer();
    } else {
        return validateChoiceAnswer(question);
    }
}

function validateRankingAnswer() {
    const rankingItems = document.querySelectorAll('.ranking-item');
    if (rankingItems.length === 0) {
        showError('noChoiceError');
        return false;
    }
    return true;
}

function validateFreeTextAnswer(maxCharacterInput) {
    const textArea = document.querySelector('.free-text-input');
    const audioContainer = document.querySelector('.enhanced-audio-container');
    
    if (!textArea || !audioContainer) {
        showError('erreurTechnique');
        return false;
    }
    
    // Mode texte actif
    if (textArea.style.display !== 'none') {
        const answerText = textArea.value.trim();
        if (answerText === '') {
            showError('emptyTextAreaError');
            return false;
        }
        if (answerText.length < MIN_TEXT_LENGTH) {
            showError('shortTextAreaError', { min: MIN_TEXT_LENGTH });
            textArea.focus();
            return false;
        }
        const maxLength = Math.min(maxCharacterInput || MAX_TEXT_LENGTH, MAX_TEXT_LENGTH);
        if (answerText.length > maxLength) {
            showError('longTextAreaError', { max: maxLength });
            return false;
        }
        return true;
    }
    
    // Mode audio - vérifier qu'il y a un enregistrement
    const questionId = getCurrentQuestionId();
    const questionState = currentQuestionAudioState[questionId];
    
    if (!questionState || !questionState.audioBlob) {
        showError('noAudioRecordingError');
        return false;
    }
    
    // Vérifier la durée minimale (plus souple)
    if (questionState.duration < MIN_RECORDING_TIME) {
        showError('shortAudioError', { min: MIN_RECORDING_TIME, current: questionState.duration });
        return false;
    }
    
    return true;
}

function validateChoiceAnswer(question) {
    // ✅ CORRECTION : Chercher à la fois .tag ET .choice-card
    const selectedTags = document.querySelectorAll('.tag.selected, .choice-card.selected');
    
    log("Nombre de choix sélectionnés : " + selectedTags.length);
    log("Nombre minimum requis : " + question.min_choices);
    log("Nombre maximum autorisé : " + question.max_choices);

    if (selectedTags.length === 0) {
        log("Erreur : aucun choix sélectionné");
        if (question.question_type === 'multi_select' && question.min_choices > 0) {
            showMinChoicesError(question.min_choices);
        } else {
            showNoChoiceError();
        }
        return false;
    }

    // Vérifier qu'il n'y a pas de mélange entre "autre" et les choix normaux
    if (question.question_type === 'multi_select') {
        const hasOtherSelected = Array.from(selectedTags).some(tag => 
            tag.textContent.trim().toLowerCase() === 'autre'
        );
        const hasNormalSelected = Array.from(selectedTags).some(tag => 
            tag.textContent.trim().toLowerCase() !== 'autre'
        );
        
        if (hasOtherSelected && hasNormalSelected) {
            log("Erreur : mélange de réponses 'autre' et normales");
            showError('mixedChoicesError');
            return false;
        }
    }

    if (question.min_choices && selectedTags.length < question.min_choices) {
        log("Erreur : nombre minimum de choix non atteint");
        showMinChoicesError(question.min_choices);
        return false;
    }
    
    if (question.max_choices && selectedTags.length > question.max_choices) {
        log("Erreur : nombre maximum de choix dépassé");
        showMaxChoicesError(question.max_choices);
        return false;
    }

    // Valider l'input "autre" si sélectionné
    const selectedOtherTag = Array.from(selectedTags)
        .find(tag => tag.textContent.trim().toLowerCase() === 'autre');
        
    if (selectedOtherTag) {
        return validateOtherInput(parseInt(selectedOtherTag.dataset.maxCharacterInput, 10));
    }

    return true;
}

function validateOtherInput(maxCharacterInput) {
    const maxLength = maxCharacterInput || 500;
    const otherInput = document.querySelector('.other-input');
    if (otherInput && otherInput.style.display !== 'none') {
        const otherText = otherInput.value.trim();
        if (otherText === '') {
            showError('emptyOtherError');
            return false;
        }
        if (otherText.length > maxLength) {
            showError('longInputError', { max: maxLength });
            return false;
        }
    }
    return true;
}

function updateCharCount(textarea, charCountElement, maxLength) {
    if (!textarea || !charCountElement) {
        return;
    }
    
    const currentLength = textarea.value.length;
    const charCountText = charCountElement.querySelector('.char-count-text');
    
    if (charCountText) {
        charCountText.textContent = `${currentLength} / ${maxLength}`;
    } else {
        charCountElement.textContent = `${currentLength} / ${maxLength}`;
    }
    
    // Tronquer si nécessaire
    if (currentLength > maxLength) {
        textarea.value = textarea.value.slice(0, maxLength);
        const newLength = maxLength;
        if (charCountText) {
            charCountText.textContent = `${newLength} / ${maxLength}`;
        } else {
            charCountElement.textContent = `${newLength} / ${maxLength}`;
        }
    }
    
    // Gérer l'affichage des warnings (si voulu)
    charCountElement.classList.toggle('warning-active', currentLength > 0 && currentLength < MIN_TEXT_LENGTH);
}

function dragStart(e) {
    e.dataTransfer.setData('text/plain', e.target.id);
    e.target.classList.add('dragging');
}

function dragOver(e) {
    e.preventDefault();
}

function drop(e) {
    e.preventDefault();
    const id = e.dataTransfer.getData('text');
    const draggableElement = document.getElementById(id);
    
    if (!draggableElement) {
        console.error('Élément glissable non trouvé:', id);
        return;
    }

    const dropzone = e.target.closest('.ranking-item');
    if (!dropzone) {
        console.error('Zone de dépôt non trouvée');
        return;
    }

    const container = dropzone.parentNode;
    if (!container) {
        console.error('Conteneur parent non trouvé');
        return;
    }

    try {
        const afterElement = getDragAfterElement(container, e.clientY);
        if (afterElement == null) {
            container.appendChild(draggableElement);
        } else {
            container.insertBefore(draggableElement, afterElement);
        }
        updateRankNumbers();
    } catch (error) {
        console.error('Erreur lors du drop:', error);
    }
}

function dragEnd(e) {
    e.target.classList.remove('dragging');
    updateRankNumbers();
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.ranking-item:not(.dragging)')];

    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

function updateRankNumbers() {
    const rankingItems = document.querySelectorAll('.ranking-item');
    rankingItems.forEach((item, index) => {
        const rankNumber = item.querySelector('.rank-number');
        if (rankNumber) {
            rankNumber.textContent = index + 1;
        }
    });
}

async function updateQuizProgress(questionId, answerValue, answerText, quizId, isCompleted = false) {
    log("=== DÉBUT UPDATE QUIZ PROGRESS ===");
    log(`QuestionId: ${questionId}, QuizId: ${quizId}`);
    log(`IsCompleted: ${isCompleted}`);
    log(`CurrentQuestionIndex: ${currentQuestionIndex}`);
    log(`Réponse:`, { value: answerValue, text: answerText });

    log(`Mise à jour du progrès - questionId: ${questionId}, quizId: ${quizId}`);
    log(`Réponse - value: ${JSON.stringify(answerValue)}, text: ${answerText}`);

    if (!quizId || typeof quizId !== 'string') {
        log(`Erreur: quizId invalide: ${quizId}`);
        alert(getTranslation('erreurProgression'));
        return;
    }

    // Déterminer si c'est la dernière question possible
    const nextAvailableIndex = findNextAvailableQuestion(currentQuestionIndex, userAnswers);
    const isLastQuestion = isCompleted || nextAvailableIndex === -1;

    const payload = {
        quiz_id: quizId,
        current_question_index: currentQuestionIndex,
        answer: {
            question_id: questionId,
            value: answerValue,
            text: answerText
        },
        is_completed: isLastQuestion,
        is_reviewing: window.isEditingFromReview || false
    };

    log(`Payload envoyé: ${JSON.stringify(payload)}`);

    try {
        const response = await fetch('/update_quiz_progress', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        log("Progression mise à jour : " + JSON.stringify(data));
        
        // Mettre à jour les réponses locales
        userAnswers[questionId] = { value: answerValue, text: answerText };

        // Mettre à jour la barre de progression
        updateProgress();

        return data;
    } catch (error) {
        log("Erreur lors de la mise à jour de la progression : " + error);
        alert(getTranslation('erreurProgression'));
        throw error;
    }
}

function updateProgress() {
    const progressBar = document.getElementById('progress');
    if (progressBar) {
        // Calculer la progression en fonction des réponses réelles plutôt que de l'index
        const answeredQuestions = Object.keys(userAnswers).length;
        const progress = (answeredQuestions / allQuestions.length) * 100;
        progressBar.style.width = `${progress}%`;
    }
}

function showResult() {
    const result = getElement('#result');
    const loadingIndicator = getElement('#loadingIndicator');

    if (result) result.style.display = 'block';
    if (loadingIndicator) loadingIndicator.style.display = 'block';
    
    try {
        const promptData = Object.entries(userAnswers).map(([questionId, answer]) => {
            const question = allQuestions.find(q => q.id == questionId);
            if (!question) {
                throw new Error('Question non trouvée');
            }
            return {
                question: question.question,
                answer: answer.text
            };
        });

        log("prompt data: " + JSON.stringify(promptData));
        const quizId = getQuizId();

        getPromptResult(promptData, quizId)
            .then(() => {
                // Rediriger vers la page d'analyse après la complétion de l'analyse
                window.location.href = `/analysis/view/${quizId}`;
            })
            .catch(error => {
                log("Erreur lors de l'obtention du résultat : " + error);
                alert(getTranslation('erreurAnalyse'));
            });
    } catch (error) {
        log("Erreur lors de la préparation des résultats : " + error);
        alert(getTranslation('erreurAnalyse'));
    }
}

function showCongratulations() {
    // Cacher le contenu du quiz
    const quizContent = getElement('#quizContent');
    if (quizContent) {
        quizContent.style.display = 'none';
    }

    // Préparer le récapitulatif des réponses
    prepareAnswersReview();

    // Afficher l'écran de félicitations
    const congratulations = getElement('#congratulations');
    if (congratulations) {
        congratulations.style.display = 'block';
        
        // Ajouter l'ancre à l'URL sans recharger la page
        const urlParams = new URLSearchParams(window.location.search);
        if (!urlParams.has('show_recap')) {
            urlParams.set('show_recap', 'true');
            const newUrl = `${window.location.pathname}?${urlParams.toString()}#congratulations`;
            window.history.pushState({ path: newUrl }, '', newUrl);
        } else if (!window.location.hash) {
            // Si show_recap existe déjà mais pas le hash
            window.location.hash = 'congratulations';
        }
    }

    // S'assurer que le modal est caché
    const modal = document.getElementById('confirmationModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

async function prepareAnswersReview() {
    console.log('Début prepareAnswersReview');
    
    const accordionContainer = document.getElementById('answersAccordion');
    if (!accordionContainer) {
        console.error("Conteneur d'accordéon non trouvé");
        return;
    }

    try {
        // Vider le conteneur avant de commencer
        accordionContainer.innerHTML = '';
        
        // Récupérer le quiz_id de manière sécurisée
        const urlParams = new URLSearchParams(window.location.search);
        const quizId = urlParams.get('quiz_id') || 'personal_profiling';
        console.log('Quiz ID:', quizId);

        // Charger les questions si nécessaire
        if (!allQuestions || allQuestions.length === 0) {
            const questionsResponse = await fetch(`/get_questions/?quiz_id=${quizId}`);
            const questionsData = await questionsResponse.json();
            allQuestions = questionsData.questions;
            console.log('Questions chargées:', allQuestions);
        }

        // Charger la progression et les réponses
        const progressResponse = await fetch(`/get_quiz_progress/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!progressResponse.ok) {
            throw new Error('Failed to load quiz progress');
        }

        const progressData = await progressResponse.json();
        console.log('Données de progression chargées:', progressData);

        // Mettre à jour userAnswers
        userAnswers = progressData.answers || {};
        console.log('userAnswers mis à jour:', userAnswers);

        // Vérifier si nous avons des réponses
        const hasAnswers = userAnswers && Object.keys(userAnswers).length > 0;
        console.log('A des réponses:', hasAnswers);

        if (!hasAnswers) {
            accordionContainer.innerHTML = '<p class="text-center p-4">Aucune réponse enregistrée</p>';
            return;
        }

        // Créer les cartes pour chaque question
        allQuestions.forEach((question, index) => {
            const answer = userAnswers[question.id];
            if (!answer) return;

            const questionCard = document.createElement('div');
            questionCard.className = 'bg-white rounded-lg shadow-sm mb-4';
            
            const answerText = answer.text || answer.value?.join(', ') || 'Pas de réponse';
            
            // Créer le contenu HTML 
            questionCard.innerHTML = `
                <div class="p-4 border-l-4 border-[#D7942D]">
                    <div class="mb-2">
                        <h4 class="text-lg font-medium mb-3">${question.question}</h4>
                        <div class="answer-tag bg-[#D7942D] text-white rounded-lg p-3 flex items-center transition-all hover:bg-[#c17d1e]">
                            ${answerText}
                        </div>
                    </div>
                    <div class="mt-3">
                        <button 
                            class="edit-question-btn btn flex items-center gap-2"
                            data-index="${index}">
                            <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                                <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
                            </svg>
                            Modifier
                        </button>
                    </div>
                </div>
            `;

            // Ajouter la carte au conteneur
            accordionContainer.appendChild(questionCard);
            
            // Ajouter l'écouteur d'événement au bouton "Modifier"
            const editButton = questionCard.querySelector('.edit-question-btn');
            if (editButton) {
                editButton.addEventListener('click', function() {
                    const questionIndex = parseInt(this.getAttribute('data-index'));
                    navigateToQuestion(questionIndex);
                });
            }
        });

        console.log('Nombre de cartes créées:', accordionContainer.children.length);
        attachEditButtonListeners();

    } catch (error) {
        console.error("Erreur lors de la préparation du récapitulatif:", error);
        accordionContainer.innerHTML = '<p class="text-center p-4 text-red-500">Une erreur est survenue lors du chargement des réponses</p>';
    }

}


function attachEditButtonListeners() {
    console.log("=== DÉBUT ATTACHEMENT DES ÉCOUTEURS ===");
    const editButtons = document.querySelectorAll('.edit-question-btn');
    console.log(`Nombre de boutons trouvés: ${editButtons.length}`);
    
    editButtons.forEach((button, index) => {
        console.log(`Configuration du bouton ${index}, data-index=${button.getAttribute('data-index')}`);
        
        // On clone le bouton pour supprimer tous les écouteurs
        const newButton = button.cloneNode(true);
        button.parentNode.replaceChild(newButton, button);
        
        // Ajouter le nouvel écouteur
        newButton.addEventListener('click', function() {
            console.log(`Bouton ${index} cliqué, data-index=${this.getAttribute('data-index')}`);
            const questionIndex = parseInt(this.getAttribute('data-index'));
            navigateToQuestion(questionIndex);
        });
    });
    console.log("=== FIN ATTACHEMENT DES ÉCOUTEURS ===");
}


function toggleReviewAnswers() {
    const reviewSection = document.getElementById('answersReview');
    if (reviewSection) {
        const isHidden = reviewSection.style.display === 'none';
        reviewSection.style.display = isHidden ? 'block' : 'none';
    }
}

function navigateToQuestion(index) {
    if (index >= 0 && index < allQuestions.length) {
        // Ajouter l'index actuel à l'historique avant de naviguer
        questionHistory.push(currentQuestionIndex);

        currentQuestionIndex = index;
        isEditingFromReview = true;  // Marquer que nous venons de la page de révision

        // Cacher l'écran de félicitations
        const congratulations = document.getElementById('congratulations');
        if (congratulations) {
            console.log('Hiding congratulations');
            congratulations.style.display = 'none';
        }

        // Afficher le contenu du quiz
        const quizContent = document.getElementById('quizContent');
        if (quizContent) {
            console.log('Showing quiz content');
            quizContent.style.display = 'block';

            // Réinitialiser le formulaire du quiz
            const quizForm = document.getElementById('quizForm');
            if (quizForm) {
                console.log('Clearing quiz form');
                quizForm.innerHTML = '';
            }

            // Afficher la question sélectionnée
            showQuestion(getQuizId());

            // Faire défiler jusqu'à la question
            quizContent.scrollIntoView({ behavior: 'smooth' });
        }
    }
}

function getPromptResult(promptData, quizId) {
    // Modifier l'URL pour inclure step_id
    return fetch(`/analysis/generate/vision_360`, {  // Ajout de vision_360 comme step_id
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ 
            quiz_id: quizId,
            prompt_data: promptData 
        })
    })
    .then(response => {
        if (!response.ok) {
            return response.text().then(text => {
                throw new Error(`Erreur serveur (${response.status}): ${text}`);
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.error) {
            throw new Error(data.error);
        }
        displayResult(data);
    })
    .catch(error => {
        console.error('Erreur lors de la récupération du résultat:', error);
        document.getElementById('loadingIndicator').style.display = 'none';
        alert(getTranslation('erreurAnalyse'));
    });
}

function displayResult(result) {
    const loadingIndicator = document.getElementById('loadingIndicator');
    if (loadingIndicator) {
        loadingIndicator.style.display = 'none';
    }

    if (result.error) {
        log("Error in result: " + result.error);
        alert(getTranslation('erreurAnalyse'));
        return;
    }

    // Get quiz ID for redirection
    const quizId = getQuizId();
    window.location.href = `/analysis/view/${quizId}`;
}

function getQuizId() {
    // Priorité 1 : Variable Globale
    if (typeof window.currentQuizId === 'string' && window.currentQuizId) {
        log("Found quizId in global variable:", window.currentQuizId);
        return window.currentQuizId;
    }

    // Priorité 2 : Champ Caché
    const hiddenQuizId = document.getElementById('currentQuizId');
    if (hiddenQuizId instanceof HTMLInputElement && hiddenQuizId.value) {
        log("Found quizId in hidden input:", hiddenQuizId.value);
        return hiddenQuizId.value;
    }

    // Priorité 3 : URL
    const urlParams = new URLSearchParams(window.location.search);
    const quizIdFromURL = urlParams.get('quiz_id');
    if (quizIdFromURL) {
        log("Found quizId in URL:", quizIdFromURL);
        return quizIdFromURL;
    }

    // Priorité 4 : Bouton de démarrage
    const startQuizBtn = document.getElementById('startQuizBtn');
    if (startQuizBtn && startQuizBtn.getAttribute('data-quiz-id')) {
        const quizIdFromButton = startQuizBtn.getAttribute('data-quiz-id');
        log("Found quizId in startQuizBtn:", quizIdFromButton);
        return quizIdFromButton;
    }

    // Valeur par défaut
    log("No quizId found, using default 'personal_profiling'");
    return 'personal_profiling';
}

function showError(errorType, params = {}) {
    const errorElement = document.querySelector('.choices-error');
    if (errorElement) {
        let errorMessage;
        
        // Nouvelles erreurs audio
        if (errorType === 'noAudioRecordingError') {
            errorMessage = 'Veuillez enregistrer votre réponse ou choisir le mode texte.';
        } else if (errorType === 'shortAudioError') {
            errorMessage = `Votre enregistrement de ${params.current} secondes est trop court. Minimum requis : ${params.min} secondes. Veuillez réenregistrer.`;
        } else if (errorType === 'erreurTechnique') {
            errorMessage = 'Une erreur technique est survenue. Veuillez réessayer.';
        } else {
            // Erreurs existantes
            errorMessage = getTranslation(errorType, params);
        }
        
        console.log("Affichage de l'erreur :", errorMessage);
        errorElement.textContent = errorMessage;
        errorElement.style.display = 'block';
        errorElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function hideError() {
    const errorElement = document.querySelector('.choices-error');
    if (errorElement) {
        errorElement.style.display = 'none';
    }
}

function showMaxChoicesError(maxChoices) {
    showError('maxChoicesError', { max: maxChoices });
}

function showMinChoicesError(minChoices) {
    showError('minChoicesError', { min: minChoices });
}

function showNoChoiceError() {
    showError('noChoiceError');
}

async function previousQuestion(quizId) {
    log("Début de previousQuestion");
    
    if (!quizId) {
        log("Quiz ID manquant dans previousQuestion");
        const currentQuizId = getQuizId();
        if (!currentQuizId) {
            log("Impossible de récupérer le quiz ID");
            return;
        }
        quizId = currentQuizId;
    }

    // Vérifier si nous avons un historique valide
    if (!window.questionHistory || !Array.isArray(window.questionHistory) || window.questionHistory.length === 0) {
        try {
            // Charger l'historique depuis le serveur si nécessaire
            const response = await fetch(`/get_quiz_progress/${quizId}`);
            const data = await response.json();
            if (data.progress && data.progress.question_history) {
                window.questionHistory = data.progress.question_history;
            }
        } catch (error) {
            log("Erreur lors du chargement de l'historique:", error);
            return;
        }
    }

    if (window.questionHistory && window.questionHistory.length > 0) {
        try {
            // Récupérer l'index précédent
            const prevIndex = window.questionHistory[window.questionHistory.length - 2];
            
            if (prevIndex !== undefined) {
                // Retirer le dernier élément de l'historique
                window.questionHistory.pop();
                currentQuestionIndex = prevIndex;

                log("Retour à la question précédente, nouvel index:", currentQuestionIndex);
                
                // Mettre à jour l'historique côté serveur
                await updateQuestionHistory(quizId, window.questionHistory);
                
                // Afficher la question
                await showQuestion(quizId);
                
                // Mettre à jour l'affichage du bouton précédent
                const prevButton = document.querySelector('.prev-btn');
                if (prevButton) {
                    prevButton.style.display = window.questionHistory.length > 1 ? 'inline-block' : 'none';
                }
            } else {
                log("Pas de question précédente disponible");
                const prevButton = document.querySelector('.prev-btn');
                if (prevButton) {
                    prevButton.style.display = 'none';
                }
            }
        } catch (error) {
            log("Erreur lors de la navigation précédente:", error);
            console.error(error);
        }
    } else {
        log("Aucun historique disponible");
        const prevButton = document.querySelector('.prev-btn');
        if (prevButton) {
            prevButton.style.display = 'none';
        }
    }
}

// Fonction pour mettre à jour l'historique des questions côté serveur et localStorage
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

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Erreur ${response.status}: ${errorText}`);
        }

        const data = await response.json();
        log("Historique mis à jour avec succès:", data);

        // Sauvegarder dans le localStorage
        localStorage.setItem(`quiz_${quizId}_history`, JSON.stringify(history));
    } catch (error) {
        log("Erreur lors de la mise à jour de l'historique:", error);
        console.error(error);
        // Vous pouvez choisir d'afficher un avertissement à l'utilisateur ici
    }
}


log("Chargement du script terminé");

// Fonctions pour gérer le modal

function closeConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// Remplacer la fonction startAnalysis existante
async function startAnalysis(event) {
    if (event) event.preventDefault();
    log("startAnalysis() appelée");
    await showConfirmationModal();
}

async function showConfirmationModal() {
    log("=== DÉBUT SHOW CONFIRMATION MODAL ===");
    
    const modal = document.getElementById('confirmationModal');
    const tokenStatusMessage = document.getElementById('tokenStatusMessage');
    const modalButtons = document.getElementById('modalButtons');
    const modalText = document.getElementById('modalWarningText');
    const loadingIndicator = document.getElementById('loadingIndicator');
    
    log("Éléments DOM récupérés:", {
        modal: !!modal,
        tokenStatusMessage: !!tokenStatusMessage,
        modalButtons: !!modalButtons,
        modalText: !!modalText
    });

    if (!modal || !tokenStatusMessage || !modalButtons || !modalText) {
        console.error('Éléments du modal manquants');
        return;
    }

    try {
        const quizId = getQuizId();
        log("Quiz ID récupéré:", quizId);

        // Afficher l'indicateur de chargement
        if (loadingIndicator) loadingIndicator.style.display = 'block';

        const response = await fetch(`/check-token-status/${quizId}`, {
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        const data = await response.json();
        log("Données reçues du serveur:", data);

        // Mise à jour du message de statut
        tokenStatusMessage.innerHTML = `
            <p class="tilto-token-status ${data.message_type === 'success' ? 'status-valid' : 'status-invalid'}">
                ${data.primary_message || ''}
            </p>
            ${data.info_message ? `<p class="info-message">${data.info_message}</p>` : ''}
        `;
        // Afficher le texte d'avertissement uniquement si on a un token disponible 
        // et qu'il n'y a pas d'analyse en cours, ou si on peut générer une nouvelle analyse
        const showWarning = data.has_token && (!data.token_in_progress || (data.token_in_progress && data.has_token));
        modalText.style.display = showWarning ? 'block' : 'none';
        
        log("Affichage de l'avertissement:", showWarning);
        
        // Vider le conteneur de boutons
        modalButtons.innerHTML = '';
        
        log("Génération des boutons pour le cas:", {
            has_token: data.has_token,
            token_in_progress: data.token_in_progress
        });

        // Gestion des boutons selon les différents cas
        if (data.buttons && Array.isArray(data.buttons)) {
            data.buttons.forEach(button => {
                log("Ajout du bouton:", button);
                const btn = document.createElement('button');
                btn.className = `tilto-btn-${button.type}`;
                btn.textContent = button.label;
                
                btn.addEventListener('click', () => {
                    log("Clic sur le bouton:", button.label);
                    if (button.url === '#') {
                        if (button.label.includes('nouvelle analyse') || button.label.includes('Lancer l\'analyse')) {
                            confirmAnalysis();
                        }
                        closeConfirmationModal();
                    } else if (button.url.includes('/analysis/view/')) {
                        const urlWithToken = `${button.url}${button.url.includes('?') ? '&' : '?'}token_id=${data.token_code}`;
                        log("Redirection vers:", urlWithToken);
                        window.location.href = urlWithToken;
                    } else {
                        window.location.href = button.url;
                    }
                });
                
                modalButtons.appendChild(btn);
            });
        }

        // Afficher le modal
        modal.style.display = 'flex';
        log("Modal affiché avec succès");

    } catch (error) {
        log("Erreur dans showConfirmationModal:", error);
        console.error('Erreur complète:', error);
        alert(getTranslation('erreurTechnique'));
    } finally {
        if (loadingIndicator) loadingIndicator.style.display = 'none';
    }
}


// Fonction de nettoyage des événements
function cleanupAudioResources() {
    // Nettoyer l'audioContext
    if (audioContext && audioContext.state !== 'closed') {
        audioContext.close().catch(err => console.warn('Erreur fermeture audioContext:', err));
        audioContext = null;
    }
    
    // Nettoyer le stream
    if (audioStream) {
        audioStream.getTracks().forEach(track => track.stop());
        audioStream = null;
    }
    
    // Nettoyer les timers
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }
    
    if (silenceTimer) {
        clearTimeout(silenceTimer);
        silenceTimer = null;
    }
    
    // Nettoyer les variables globales
    analyser = null;
    dataArray = null;
    lastVolumeCheck = 0;
}

async function confirmAnalysis() {
    log("=== DÉBUT DE L'ANALYSE ===");
    const loadingIndicator = document.getElementById('loadingIndicator');
    
    try {
        const quizId = getQuizId();
        log("Quiz ID:", quizId);

        if (!quizId) {
            throw new Error('Quiz ID is missing');
        }

        // Afficher l'indicateur de chargement
        if (loadingIndicator) {
            loadingIndicator.style.display = 'block';
        }

        // Appel pour générer l'analyse
        const response = await fetch('/analysis/generate/vision_360', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ 
                quiz_id: quizId,
                force_new: true  // Ajout de ce paramètre
            }),
            credentials: 'same-origin'
        });

        log("Status de la réponse:", response.status);

        const contentType = response.headers.get("content-type");
        if (!contentType || !contentType.includes("application/json")) {
            throw new Error('Réponse invalide du serveur');
        }

        const result = await response.json();

        // En cas d'erreur dans la réponse JSON
        if (result.error) {
            throw new Error(result.error);
        }

        // Si nous avons une redirection et c'est parce que
        // l'analyse est déjà générée, aller directement à la vue
        if (result.redirect_url && result.message === 'Analysis already exists') {
            window.location.href = result.redirect_url;
            return;
        }

        // Si on a une redirection dans la réponse JSON, mais c'est pour une nouvelle analyse
        if (result.redirect_url) {
            window.location.href = result.redirect_url;
            return;
        }

        // Si on a un message de succès mais pas de redirection
        if (response.status === 200 && !result.redirect_url) {
            // Rediriger vers la page d'analyse
            window.location.href = `/analysis/view/${quizId}?skip_loading=false`;
            return;
        }

        throw new Error('Format de réponse inattendu');

    } catch (error) {
        log("=== ERREUR ===");
        log("Message:", error.message);
        log("Stack:", error.stack);
        
        // Afficher l'erreur à l'utilisateur
        alert(getTranslation('erreurAnalyse'));
        
        // Si on a l'indicateur de chargement, le masquer
        if (loadingIndicator) {
            loadingIndicator.style.display = 'none';
        }
        
        // Garder l'utilisateur sur la page actuelle en cas d'erreur
        const modal = document.getElementById('confirmationModal');
        if (modal) {
            modal.style.display = 'none';
        }
    }
}

// Fonction d'initialisation du quiz homepage
// Fonction d'initialisation du quiz homepage MODIFIÉE
async function initializeHomepageQuiz() {
    log("=== INITIALISATION QUIZ HOMEPAGE ===");
    
    QuizTracking.trackQuizStart();

    // IMPORTANT : Initialiser le système de chapitres
    currentChapter = 0;
    currentChapterQuestionIndex = 0;
    isShowingTransition = false;
    
    console.log('Variables chapitres initialisées:', {
        currentChapter: currentChapter,
        currentChapterQuestionIndex: currentChapterQuestionIndex,
        isShowingTransition: isShowingTransition
    });

    // Marquer le mode homepage
    isHomepageMode = true;
    homepageQuizAnswers = {};
    homepageQuestionHistory = [];
    homepageCurrentQuestionIndex = 0;
    
    try {
        // Charger les questions sans authentification
        await loadHomepageQuestions();
        
        console.log('Questions chargées pour homepage:', {
            count: homepageAllQuestions.length,
            firstQuestion: homepageAllQuestions[0]?.id,
            startIndex: homepageCurrentQuestionIndex
        });
        
        // NOUVEAU : Afficher d'abord l'écran d'accueil
        const quizWelcome = document.getElementById('quizWelcome');
        const quizContent = document.getElementById('quizContent');
        
        if (quizWelcome) {
            quizWelcome.style.display = 'flex';
        }
        if (quizContent) {
            quizContent.style.display = 'none';
        }
        
        // Configurer le bouton de démarrage
        setupWelcomeButton();
        
    } catch (error) {
        log("Erreur d'initialisation homepage:", error);
        console.error("Erreur d'initialisation:", error);
        alert("Une erreur est survenue lors du chargement du quiz: " + error.message);
    }
}

// NOUVELLE FONCTION : Configuration du bouton d'accueil
function setupWelcomeButton() {
    const startBtn = document.getElementById('startQuizFromWelcome');
    
    if (startBtn) {
        const handleStart = function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Éviter le double déclenchement touch/click
            if (e.type === 'touchend') {
                this.touchHandled = true;
                setTimeout(() => { this.touchHandled = false; }, 500);
            } else if (e.type === 'click' && this.touchHandled) {
                return;
            }
            
            startQuizFromWelcome();
        };
        
        startBtn.addEventListener('touchend', handleStart, { passive: false });
        startBtn.addEventListener('click', handleStart);
    }
}

async function startQuizFromWelcome() {
    console.log('Démarrage du quiz depuis l\'écran d\'accueil');
    
    // Réinitialiser complètement l'état
    resetQuizState();
    
    // Masquer l'écran d'accueil
    const quizWelcome = document.getElementById('quizWelcome');
    if (quizWelcome) {
        quizWelcome.style.display = 'none';
    }
    
    // Afficher le contenu du quiz
    const quizContent = document.getElementById('quizContent');
    if (quizContent) {
        quizContent.style.display = 'block';
    }
    
    // Afficher la première question (qui sera l'intro du chapitre 1)
    await showHomepageQuestion();
}

// Fonction de chargement des questions pour homepage
async function loadHomepageQuestions() {
    console.log('Début loadHomepageQuestions');
    
    try {
        const response = await fetch('/get_questions_homepage/?quiz_id=pack_clarte', {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        if (!response.ok) {
            throw new Error('Failed to load questions');
        }

        const data = await response.json();
        console.log('Questions reçues du serveur:', data);
        
        if (!data.questions || !Array.isArray(data.questions)) {
            throw new Error('Invalid questions data');
        }

        homepageAllQuestions = data.questions.map(q => ({
            ...q,
            max_choices: q.max_choices !== null ? q.max_choices : Infinity
        }));

        console.log('Questions chargées et formatées:', homepageAllQuestions);
        
        return homepageAllQuestions;
    } catch (error) {
        console.error('Erreur lors du chargement des questions:', error);
        throw error;
    }
}

async function showHomepageQuestion() {
    console.log("=== DEBUT showHomepageQuestion ===");
    debugCurrentState(); // Appeler le debug au début
    
    const quizContent = getElement('#quizContent');
    if (quizContent) {
        quizContent.style.display = 'block';
    }

    if (!homepageAllQuestions || homepageAllQuestions.length === 0) {
        console.error('Aucune question disponible');
        alert('Aucune question disponible pour ce quiz.');
        return;
    }

    const quizForm = getElement('#quizForm');
    if (!quizForm) {
        console.error('Form container not found');
        return;
    }

    try {
        const chapter = getCurrentChapter('pack_clarte');
        
        if (!chapter) {
            console.log('Fin des chapitres atteinte');
            showHomepageCompletion();
            return;
        }


        // Vérifier transition
        if (isShowingTransition) {
            console.log('AFFICHAGE TRANSITION');
            showChapterTransition(chapter, 'pack_clarte');
            return;
        }

        // Vérifier fin de chapitre
        if (currentChapterQuestionIndex >= chapter.questions.length) {
            console.log('FIN DU CHAPITRE');
            const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
            if (currentChapter < chapters.length - 1 && chapter.transition) {
                // Ajouter l'état actuel à l'historique avant la transition
                const preTransitionState = {
                    chapter: currentChapter,
                    questionIndex: currentChapterQuestionIndex - 1,
                    isTransition: false,
                    hasIntro: false
                };
                homepageQuestionHistory.push(preTransitionState);
                
                isShowingTransition = true;
                showChapterTransition(chapter, 'pack_clarte');
                return;
            } else {
                currentChapter++;
                currentChapterQuestionIndex = 0;
                await showHomepageQuestion();
                return;
            }
        }

        // AFFICHAGE QUESTION NORMALE
        console.log('AFFICHAGE QUESTION NORMALE');
        const currentQuestionId = chapter.questions[currentChapterQuestionIndex];
        const currentQuestion = homepageAllQuestions.find(q => q.id == currentQuestionId);
        
        console.log('Recherche question:', {
            questionId: currentQuestionId,
            found: !!currentQuestion
        });
        
        if (!currentQuestion) {
            console.error('Question non trouvée:', currentQuestionId);
            console.log('Questions disponibles:', homepageAllQuestions.map(q => q.id));
            // Essayer question suivante
            currentChapterQuestionIndex++;
            await showHomepageQuestion();
            return;
        }

        console.log('CREATION ELEMENT QUESTION');
        quizForm.innerHTML = '';
        const questionElement = createHomepageQuestionElement(currentQuestion);
        quizForm.appendChild(questionElement);

        QuizTracking.trackQuestion(
            currentChapter + 1,
            currentChapterQuestionIndex,
            currentQuestion.id,
            currentQuestion.question
        );

        // Restaurer réponses
        if (homepageQuizAnswers[currentQuestion.id]) {
            restoreHomepagePreviousAnswer(currentQuestion, quizForm);
        }

        updateChapterProgress();
        console.log("=== FIN showHomepageQuestion (succès) ===");

    } catch (error) {
        console.error('ERREUR dans showHomepageQuestion:', error);
        quizForm.innerHTML = `<p class="error">Erreur: ${error.message}</p>`;
    }
}


// Fonction de création d'élément question pour homepage
function createHomepageQuestionElement(question) {
    log(`Création de l'élément pour la question homepage: ${question.id}`);
    const questionDiv = document.createElement('div');
    questionDiv.className = 'question active';
    questionDiv.id = 'question-' + question.id;

    try {
        // Vérification de la structure de la question
        if (!question.id || !question.question) {
            throw new Error('Structure de question invalide: ' + JSON.stringify(question));
        }
        
        if (question.media_type === 'image' && question.media_url) {
            appendQuestionImage(questionDiv, question.media_url);
        }
        
        appendQuestionTitle(questionDiv, question.question, question);
        // Ajouter l'indice de question s'il existe
        appendQuestionHint(questionDiv, question);

        // Ajouter les instructions de choix pour les questions multi-select
        if (question.question_type === 'multi_select') {
            appendChoiceInstructions(questionDiv, question);
        }

        if (question.question_type === 'location') {
            appendLocationInput(questionDiv);
        } else if (question.question_type === 'free_text') {
            // CORRECTION: Utiliser une valeur par défaut si max_character_input n'est pas défini
            const maxCharInput = question.max_character_input || 2000;
            console.log('Création free_text question - mode vocal par défaut');
            appendFreeTextInput(questionDiv, maxCharInput);
        } else if (question.question_type === 'ranking') {
            if (Array.isArray(question.choices) && question.choices.length > 0) {
                appendRankingList(questionDiv, question);
            } else {
                throw new Error('Choix manquants pour ranking');
            }
        } else if (Array.isArray(question.choices) && question.choices.length > 0) {
            appendChoiceList(questionDiv, question);
        } else {
            throw new Error('Choix manquants pour question: ' + question.question_type);
        }

        appendErrorElement(questionDiv);
        appendHomepageButtonContainer(questionDiv);

    } catch (error) {
        log(`Erreur lors de la création de l'élément pour la question ${question.id}: ${error.message}`);
        console.error('Erreur complète:', error);
        console.error('Question problématique:', question);
        questionDiv.textContent = `Erreur lors du chargement de la question: ${error.message}`;
    }

    return questionDiv;
}


function appendHomepageButtonContainer(questionDiv) {
    const buttonContainer = document.createElement('div');
    buttonContainer.className = 'button-container';
    
    const buttonsDiv = document.createElement('div');
    buttonsDiv.className = 'flex gap-4';
    
    // ✅ Vérifier si on peut revenir en arrière
    const canGoBack = homepageQuestionHistory.length > 0 ||
        currentChapter > 0 ||
        currentChapterQuestionIndex > 0 ||
        isShowingTransition;
    
    // ✅ Bouton précédent (seulement si on peut revenir)
    if (canGoBack) {
        const prevButton = document.createElement('button');
        prevButton.className = 'prev-btn';
        prevButton.innerHTML = window.innerWidth <= 768 ? 
            '<span class="btn-text"></span>' : 
            '<span class="btn-text">Précédent</span>';
        
        prevButton.addEventListener('click', (e) => {
            e.preventDefault();
            if ('vibrate' in navigator && window.innerWidth <= 768) {
                navigator.vibrate(50);
            }
            homepagePreviousQuestion();
        });
        
        buttonsDiv.appendChild(prevButton);
    }
    
    // ✅ Bouton suivant
    const actionButton = document.createElement('button');
    actionButton.className = 'next-btn';
    actionButton.innerHTML = '<span class="btn-text">Suivant</span>';
    
    actionButton.addEventListener('click', (event) => {
        event.preventDefault();
        if ('vibrate' in navigator && window.innerWidth <= 768) {
            navigator.vibrate([50, 100]);
        }
        const currentQuestion = getCurrentQuestionInChapter();
        if (currentQuestion) {
            homepageNextQuestion(currentQuestion);
        }
    });
    
    buttonsDiv.appendChild(actionButton);
    buttonContainer.appendChild(buttonsDiv);
    questionDiv.appendChild(buttonContainer);
}

// Fonction de navigation suivante pour homepage
async function homepageNextQuestion(question) {
    try {
        // Valider la réponse actuelle
        if (!validateAnswer(question)) {
            return;
        }

        const [answerValue, answerText] = getQuestionAnswer(question);
        
        // ===== AJOUT TRACKING - INSÉRER ICI =====
        // Déterminer le type de réponse
        let answerType = 'choice';
        let answerLength = null;
        
        if (question.question_type === 'free_text') {
            const isAudio = Array.isArray(answerValue) && 
                           answerValue[0] && 
                           answerValue[0].startsWith('[AUDIO:');
            
            answerType = isAudio ? 'audio' : 'text';
            
            if (isAudio) {
                const questionState = currentQuestionAudioState[question.id];
                if (questionState && questionState.duration) {
                    QuizTracking.trackAudioRecording(question.id, questionState.duration);
                }
            } else {
                answerLength = answerValue[0] ? answerValue[0].length : 0;
                QuizTracking.trackTextEntry(question.id, answerLength);
            }
        } else if (question.question_type === 'multi_select') {
            answerType = 'multi_choice';
            answerLength = answerValue.length;
        } else if (question.question_type === 'ranking') {
            answerType = 'ranking';
            answerLength = answerValue.length;
        } else if (question.question_type === 'location') {
            answerType = 'location';
        }
        
        // Tracker la réponse
        QuizTracking.trackQuestionAnswer(
            question.id,
            question.question,
            answerType,
            answerLength
        );
        // ===== FIN AJOUT TRACKING =====
        
        // Enregistrer la réponse (écrase l'ancienne si elle existait)
        homepageQuizAnswers[question.id] = {
            value: answerValue,
            text: answerText
        };
        
        console.log('Réponse enregistrée/mise à jour:', {
            questionId: question.id,
            answer: homepageQuizAnswers[question.id]
        });

        // ✅ CORRECTION : Vérifier si cet état exact existe déjà dans l'historique
        const currentState = {
            chapter: currentChapter,
            questionIndex: currentChapterQuestionIndex,
            isTransition: false,
            hasIntro: false,
            screenType: 'question',
            questionId: question.id
        };

        // Vérifier les doublons
        const isDuplicate = homepageQuestionHistory.some(state =>
            state.chapter === currentState.chapter &&
            state.questionIndex === currentState.questionIndex &&
            state.screenType === currentState.screenType
        );

        if (!isDuplicate) {
            homepageQuestionHistory.push(currentState);
            console.log('📌 Historique ajouté:', currentState.questionId, '| Total:', homepageQuestionHistory.length);
        } else {
            console.log('⚠️ Doublon évité pour question:', currentState.questionId);
        }

        // ✅ Sauvegarder l'état après chaque réponse
        QuizPersistence.saveQuizState();

        // Passer à la question suivante
        const chapter = getCurrentChapter('pack_clarte');
        if (chapter) {
            currentChapterQuestionIndex++;

            // Mettre à jour la progression
            if (currentChapterQuestionIndex < chapter.questions.length) {
                updateHomepageProgress();
            }

            // Vérifier si on a terminé le chapitre
            if (currentChapterQuestionIndex >= chapter.questions.length) {
                updateHomepageProgress();
                triggerChapterCompletionEffect();

                const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
                if (currentChapter < chapters.length - 1 && chapter.transition) {
                    setTimeout(() => {
                        isShowingTransition = true;
                        showHomepageQuestion();
                    }, 400);
                    return;
                } else if (currentChapter >= chapters.length - 1) {
                    setTimeout(() => {
                        showHomepageCompletion();
                    }, 400);
                    return;
                } else {
                    setTimeout(() => {
                        currentChapter++;
                        currentChapterQuestionIndex = 0;
                        updateHomepageProgress();
                        showHomepageQuestion();
                    }, 400);
                    return;
                }
            }

            // Continuer dans le chapitre actuel
            await showHomepageQuestion();
        }
    } catch (error) {
        console.error("Erreur dans homepageNextQuestion:", error);
        
        // ===== AJOUT TRACKING ERREUR =====
        if (typeof QuizTracking !== 'undefined') {
            QuizTracking.trackError('question_navigation_error', error.message, {
                question_id: question.id,
                chapter: currentChapter + 1,
                question_index: currentChapterQuestionIndex
            });
        }
        // ===== FIN AJOUT TRACKING ERREUR =====
        
        alert('Une erreur est survenue: ' + error.message);
    }
}

async function homepagePreviousQuestion() {
    console.log('=== DÉBUT homepagePreviousQuestion ===');
    console.log('Historique actuel:', JSON.stringify(homepageQuestionHistory));
    console.log('État actuel:', {
        currentChapter,
        currentChapterQuestionIndex,
        isShowingTransition
    });
    
    if (homepageQuestionHistory && homepageQuestionHistory.length > 0) {
        // Récupérer l'état précédent
        const previousState = homepageQuestionHistory.pop();
        
        console.log('État précédent récupéré:', previousState);
        console.log('Historique après pop:', homepageQuestionHistory.length, 'entrées');
        
        QuizTracking.trackBackNavigation(
            currentChapterQuestionIndex,
            previousState.questionIndex
        );

        // Restaurer l'état exact
        currentChapter = previousState.chapter;
        currentChapterQuestionIndex = previousState.questionIndex;
        isShowingTransition = previousState.isTransition || false;
        
        // Gérer les cas spéciaux selon le type d'écran
        if (previousState.screenType === 'intro') {
            // Retour vers un écran d'intro
            const chapter = getCurrentChapter('pack_clarte');
            if (chapter) {
                chapter.introSeen = false;
                console.log('Retour vers intro du chapitre', currentChapter);
            }
        } else if (previousState.screenType === 'transition') {
            // Retour vers un écran de transition
            isShowingTransition = true;
            console.log('Retour vers transition du chapitre', currentChapter);
        } else {
            // C'est une vraie question
            console.log('Retour vers question normale:', {
                chapter: currentChapter,
                questionIndex: currentChapterQuestionIndex
            });
        }
        
        console.log('État restauré:', {
            currentChapter,
            currentChapterQuestionIndex,
            isShowingTransition,
            screenType: previousState.screenType || 'question'
        });
        
        // ✅ IMPORTANT : Conserver TOUTES les réponses en mémoire
        // Ne RIEN supprimer de homepageQuizAnswers ni de tempQuizAudios
        // L'utilisateur peut modifier ses réponses mais on ne les perd pas
        
        // ✅ IMPORTANT : Ne pas sauvegarder ici
        // On sauvegarde uniquement lors d'un "suivant" pour éviter
        // de sauvegarder un état "entre deux questions"
        
        await showHomepageQuestion();
        
    } else {
        // Pas d'historique - retour au tout début
        console.log('Pas d\'historique - retour au début du quiz');
        
        currentChapter = 0;
        currentChapterQuestionIndex = 0;
        isShowingTransition = false;
        
        const firstChapter = getCurrentChapter('pack_clarte');
        if (firstChapter) {
            firstChapter.introSeen = false;
        }
        
        // ✅ CORRECTION : Afficher l'écran d'accueil, pas directement la question
        const quizWelcome = document.getElementById('quizWelcome');
        const quizContent = document.getElementById('quizContent');
        
        if (quizWelcome && quizContent) {
            quizWelcome.style.display = 'flex';
            quizContent.style.display = 'none';
            console.log('Retour à l\'écran d\'accueil');
        } else {
            // Si pas d'écran d'accueil, afficher directement la première question
            await showHomepageQuestion();
        }
    }
    
    console.log('=== FIN homepagePreviousQuestion ===');
}

// Fonction de recherche de prochaine question pour homepage
function findNextAvailableQuestionHomepage(currentIndex, answers) {
    console.log('Recherche prochaine question depuis index:', currentIndex);
    
    for (let i = currentIndex + 1; i < homepageAllQuestions.length; i++) {
        const question = homepageAllQuestions[i];
        
        console.log(`Vérification question index ${i}:`, {
            id: question.id,
            isConditional: question.is_conditional,
            parentId: question.parent_question_id
        });
        
        // Si la question n'est pas conditionnelle, elle est disponible
        if (!question.is_conditional) {
            console.log(`Question non-conditionnelle trouvée à l'index ${i}`);
            return i;
        }
        
        // Si la question est conditionnelle, vérifier si elle doit être affichée
        if (question.parent_question_id && answers[question.parent_question_id]) {
            const parentAnswer = answers[question.parent_question_id];
            
            let conditionValue = null;
            if (question.condition_value) {
                try {
                    conditionValue = typeof question.condition_value === 'string' 
                        ? JSON.parse(question.condition_value) 
                        : question.condition_value;
                } catch (e) {
                    console.error('Erreur parsing condition_value:', e);
                    continue;
                }
            }
            
            // Vérifier si la réponse du parent correspond à la condition
            if (shouldShowConditionalQuestion(parentAnswer, conditionValue)) {
                console.log(`Question conditionnelle trouvée à l'index ${i}`);
                return i;
            }
        }
    }
    
    console.log('Aucune question suivante trouvée');
    return -1;
}

// 5. FONCTION restoreHomepagePreviousAnswer (s'assurer qu'elle appelle la bonne fonction)
function restoreHomepagePreviousAnswer(question, quizForm) {
    const previousAnswer = homepageQuizAnswers[question.id];
    if (previousAnswer) {
        console.log('Restauration réponse homepage pour question', question.id, 'type:', question.question_type);
        if (question.question_type === 'free_text') {
            // ✅ CORRECTION : Utiliser la fonction restoreFreeTextAnswer qui gère audio/texte
            restoreFreeTextAnswer(quizForm, previousAnswer, question.max_character_input);
        } else if (question.question_type === 'ranking') {
            restoreRankingAnswer(quizForm, previousAnswer);
        } else if (question.question_type === 'location') {
            restoreLocationAnswer(quizForm, previousAnswer);
        } else {
            restoreChoiceAnswer(quizForm, previousAnswer, question.max_character_input);
        }
    } else {
        console.log('Pas de réponse précédente - mode vocal par défaut maintenu');
    }
}

// Fonction de mise à jour du progrès pour homepage
function updateHomepageProgress() {
    const progressContainer = document.querySelector('.progress-container');
    if (!progressContainer) return;

    // Utiliser les chapitres pour le mode homepage
    const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
    if (chapters.length === 0) {
        // Fallback sur l'ancienne méthode si pas de chapitres
        const progressBar = document.getElementById('progress');
        const progressIndicator = document.getElementById('progress-indicator');
        
        if (progressBar && typeof homepageQuizAnswers !== 'undefined' && typeof homepageAllQuestions !== 'undefined') {
            const answeredQuestions = Object.keys(homepageQuizAnswers).length;
            const totalQuestions = homepageAllQuestions.length;
            
            if (totalQuestions > 0) {
                const progress = Math.round((answeredQuestions / totalQuestions) * 100);
                progressBar.style.width = progress + '%';
                
                if (progressIndicator) {
                    progressIndicator.textContent = progress + '%';
                }
                
                if (progress === 100) {
                    progressBar.classList.add('progress-complete');
                }
            }
        }
        return;
    }

    // Créer la nouvelle structure HTML avec le système de chapitres
    progressContainer.innerHTML = `
        <div class="chapter-progress-bar">
            ${chapters.map((chapter, index) => {
                let segmentClass = 'upcoming';
                if (index < currentChapter) segmentClass = 'completed';
                else if (index === currentChapter) segmentClass = 'current';
                
                return `<div class="chapter-segment ${segmentClass}" data-chapter="${index}"></div>`;
            }).join('')}
        </div>
        <div class="chapter-labels" style="display: none;">
            ${chapters.map((chapter, index) => {
                let labelClass = 'upcoming';
                if (index < currentChapter) labelClass = 'completed';
                else if (index === currentChapter) labelClass = 'current';
                
                return `<div class="chapter-label ${labelClass}">Chapitre ${index + 1}</div>`;
            }).join('')}
        </div>
        <div class="progress-text">
            ${getHomepageProgressText(chapters)}
        </div>
    `;


    // Calculer et appliquer la progression du chapitre actuel
    updateHomepageCurrentChapterProgress();

    // Ajouter une barre de connexion entre les étapes pour mobile
    const progressWrapper = progressContainer.querySelector('.chapter-progress-bar');
    if (progressWrapper && window.innerWidth <= 768) {
        // Calculer le pourcentage de progression global
        const totalChapters = chapters.length;
        let globalProgressPercentage = 0;
        
        if (currentChapter > 0) {
            globalProgressPercentage = (currentChapter / (totalChapters - 1)) * 100;
        }
        
        // Ajouter une barre de progression fine entre les segments
        const existingLine = progressWrapper.querySelector('.progress-line');
        if (existingLine) {
            existingLine.remove();
        }
        
        const progressLine = document.createElement('div');
        progressLine.className = 'progress-line';
        progressLine.style.cssText = `
            position: absolute;
            top: 50%;
            left: 0;
            right: 0;
            height: 1px;
            background: #e9ecef;
            border-radius: 1px;
            z-index: 1;
            transform: translateY(-50%);
        `;
        
        const progressLineFill = document.createElement('div');
        progressLineFill.className = 'progress-line-fill';
        progressLineFill.style.cssText = `
            height: 100%;
            width: ${globalProgressPercentage}%;
            background: linear-gradient(90deg, #10b981 0%, #059669 100%);
            border-radius: 1px;
            transition: width 0.6s ease-out;
        `;
        
        progressLine.appendChild(progressLineFill);
        progressWrapper.style.position = 'relative';
        progressWrapper.appendChild(progressLine);
    }
}

function getHomepageProgressText(chapters) {
    if (currentChapter >= chapters.length) {
        return 'Quiz terminé !';
    }
    
    const currentChapterData = chapters[currentChapter];
    if (!currentChapterData) {
        return 'Chargement...';
    }
    
    const totalQuestionsInChapter = currentChapterData.questions.length;
    const currentQuestionInChapter = currentChapterQuestionIndex + 1;
    
    return `Chapitre ${currentChapter + 1} – Question ${currentQuestionInChapter} sur ${totalQuestionsInChapter}`;
}

function updateHomepageCurrentChapterProgress() {
    const currentSegment = document.querySelector('.chapter-segment.current');
    if (!currentSegment) return;

    const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
    if (currentChapter >= chapters.length) return;

    const currentChapterData = chapters[currentChapter];
    if (!currentChapterData) return;
    
    // NOUVELLE LOGIQUE : Progression uniquement par chapitre complet
    let progress = 0;
    
    if (isShowingTransition) {
        // Si on est en transition, le chapitre est terminé à 100%
        progress = 100;
    } else if (currentChapterData.intro && !currentChapterData.introSeen) {
        // Si l'intro n'a pas encore été vue, progression à 0%
        progress = 0;
    } else {
        // Pendant le chapitre : progression linéaire de 10% à 90%
        // On évite 0% et 100% pour bien distinguer "pas commencé" et "terminé"
        const totalQuestions = currentChapterData.questions.length;
        const baseProgress = 10; // Minimum quand on commence
        const maxProgress = 90;   // Maximum avant d'être "terminé"
        const progressRange = maxProgress - baseProgress;
        
        const questionProgress = (currentChapterQuestionIndex + 1) / totalQuestions;
        progress = baseProgress + (questionProgress * progressRange);
    }

    // Appliquer la progression visuelle
    currentSegment.style.setProperty('--progress', `${Math.round(progress)}%`);
    
    // Animation fluide
    requestAnimationFrame(() => {
        currentSegment.style.transition = 'all 0.6s ease-out';
    });
}

// Fonction de completion du quiz homepage
function showHomepageCompletion() {
    // Cacher le contenu du quiz
    const quizContent = getElement('#quizContent');
    if (quizContent) {
        quizContent.style.display = 'none';
    }

    // Afficher l'écran de completion
    const quizComplete = document.getElementById('quizComplete');
    if (quizComplete) {
        quizComplete.style.display = 'block';
        
        QuizTracking.trackLeadFormView();
        // Configurer le formulaire
        setupQuizLeadForm();
    }
}

function setupQuizLeadForm() {
    const quizForm = document.getElementById('quiz-lead-form');
    const submitBtn = document.querySelector('.btn-continue-minimal');
    const formMessage = document.getElementById('quiz-form-message');
    
    if (!quizForm || !submitBtn || !formMessage) {
        console.error('Éléments du formulaire quiz manquants');
        return;
    }

    // QUICK FIX : Vérifier expiration session AVANT tout le reste
    const savedState = localStorage.getItem('tilto_quiz_temp');
    if (savedState) {
        try {
            const state = JSON.parse(savedState);
            const hoursSince = (Date.now() - state.timestamp) / (1000 * 60 * 60);
            
            if (hoursSince > 7.5) {
                console.log('Session expirée détectée, nettoyage et reload');
                sessionStorage.setItem('quiz_session_expired', 'true');
                window.location.reload();
                return;
            }
        } catch (e) {
            console.warn('Erreur parsing quiz state:', e);
        }
    }
    
    // Gérer le retour après reload
    if (sessionStorage.getItem('quiz_session_expired')) {
        sessionStorage.removeItem('quiz_session_expired');
        showQuizFormMessage('info', '🔄', 'Session rafraîchie', 
            'Votre progression est sauvegardée. Vous pouvez continuer.');
    }

    // Fonction pour nettoyer les caractères Unicode échappés
    function cleanUnicodeMessage(message) {
        if (!message || typeof message !== 'string') return message;
        
        return message
            .replace(/\\u00e9/g, 'é')
            .replace(/\\u00e8/g, 'è')
            .replace(/\\u00ea/g, 'ê')
            .replace(/\\u00eb/g, 'ë')
            .replace(/\\u00e0/g, 'à')
            .replace(/\\u00e2/g, 'â')
            .replace(/\\u00e4/g, 'ä')
            .replace(/\\u00e7/g, 'ç')
            .replace(/\\u00f9/g, 'ù')
            .replace(/\\u00fb/g, 'û')
            .replace(/\\u00fc/g, 'ü')
            .replace(/\\u00ee/g, 'î')
            .replace(/\\u00ef/g, 'ï')
            .replace(/\\u00f4/g, 'ô')
            .replace(/\\u00f6/g, 'ö')
            .replace(/\\u00e1/g, 'á')
            .replace(/\\u00ed/g, 'í')
            .replace(/\\u00f3/g, 'ó')
            .replace(/\\u00fa/g, 'ú')
            .replace(/\\u00e5/g, 'å')
            .replace(/\\u00f1/g, 'ñ')
            .replace(/\\u00df/g, 'ß')
            .replace(/\\u0153/g, 'œ')
            .replace(/\\u00c9/g, 'É')
            .replace(/\\u00c8/g, 'È')
            .replace(/\\u00ca/g, 'Ê')
            .replace(/\\u00c0/g, 'À')
            .replace(/\\u00c7/g, 'Ç')
            .replace(/\\u00[0-9a-fA-F]{2}/g, '');
    }

    quizForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Récupération des valeurs
        const firstname = document.getElementById('quiz-firstname').value.trim();
        const email = document.getElementById('quiz-email').value.trim();

        // ✅ Newsletter optionnelle (checkbox NON cochée par défaut)
        const newsletterCheckbox = document.getElementById('newsletter-consent');
        const newsletterChecked = newsletterCheckbox ? newsletterCheckbox.checked : false;
        
        
        // ✅ HONEY POT
        const honeypot = document.getElementById('website');
        if (honeypot && honeypot.value !== '') {
            console.warn('🤖 Bot détecté - honey pot rempli');
            showQuizFormMessage('success', '✓', 'Inscription réussie', 
                'Merci ! Vous recevrez vos recommandations par email.');
            setTimeout(() => {
                quizForm.reset();
            }, 2000);
            return;
        }
        
        // Reset du message précédent
        formMessage.style.display = 'none';
        formMessage.classList.remove('show');
        
        // ===== VALIDATION GRANULAIRE =====

        if (!firstname) {
            showQuizFormMessage('error', '👤', 'Prénom manquant', 'Merci de renseigner ton prénom pour continuer');
            focusAndHighlight('quiz-firstname');
            return;
        }

        if (!email) {
            showQuizFormMessage('error', '📧', 'Email manquant', 'Merci de renseigner ton email pour continuer');
            focusAndHighlight('quiz-email');
            return;
        }

        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            showQuizFormMessage('error', '📧', 'Email invalide', 'Cette adresse email ne semble pas valide. Vérifie le format (exemple@domaine.com)');
            focusAndHighlight('quiz-email');
            return;
        }
        
        console.log('✅ Validation quiz complète OK - Soumission du formulaire');
        
        // Générer le nom d'utilisateur
        const username = (firstname + '_user_' + Date.now()).toLowerCase()
            .replace(/[^a-z0-9_]/g, '')
            .substring(0, 80);
        
        submitBtn.disabled = true;
        submitBtn.classList.add('loading');
        submitBtn.innerHTML = '<span class="btn-text">Envoi en cours...</span>';
        
        // ===== PRÉPARER LES DONNÉES =====
        const formData = new FormData();
        formData.append('website', honeypot ? honeypot.value : ''); // Honey pot
        formData.append('firstname', firstname);
        formData.append('email', email);
        formData.append('profile', 'quiz_completion');
        formData.append('source', 'quiz_homepage');

        // ✅ Consentements
        formData.append('partner_consent', 'no'); // Automatiquement "no"
        formData.append('newsletter_consent', newsletterChecked ? 'yes' : 'no');
        
        // Token CSRF
        const csrfToken = document.querySelector('meta[name=csrf-token]');
        if (csrfToken) {
            formData.append('csrf_token', csrfToken.getAttribute('content'));
        } else {
            console.warn('CSRF token non trouvé');
        }
        
        // ===== TRAITEMENT DES RÉPONSES QUIZ AVEC AUDIO =====
        if (typeof homepageQuizAnswers !== 'undefined' && Object.keys(homepageQuizAnswers).length > 0) {
            console.log('Préparation des réponses quiz avec audios pour envoi');
            
            const formattedAnswers = {};
            const audioToUpload = {};
            let audioCount = 0;
            
            Object.keys(homepageQuizAnswers).forEach(questionId => {
                const answer = homepageQuizAnswers[questionId];
                
                if (Array.isArray(answer.value) && answer.value[0] && answer.value[0].startsWith('[AUDIO:')) {
                    try {
                        const audioId = answer.value[0].match(/\[AUDIO:(.+)\]/)[1];
                        
                        if (window.tempQuizAudios && window.tempQuizAudios[audioId]) {
                            audioToUpload[questionId] = window.tempQuizAudios[audioId].blob;
                            audioCount++;
                            
                            formattedAnswers[questionId] = {
                                value: ['[AUDIO_RESPONSE]'],
                                text: `[Audio - Question ${questionId}]`
                            };
                            
                            console.log(`Audio préparé pour question ${questionId}: ${window.tempQuizAudios[audioId].blob.size} bytes`);
                        } else {
                            console.warn(`Audio manquant pour l'ID ${audioId}`);
                            formattedAnswers[questionId] = {
                                value: [''],
                                text: ''
                            };
                        }
                    } catch (e) {
                        console.error(`Erreur parsing audio ID pour question ${questionId}:`, e);
                        formattedAnswers[questionId] = {
                            value: [''],
                            text: ''
                        };
                    }
                } else {
                    formattedAnswers[questionId] = {
                        value: Array.isArray(answer.value) ? answer.value : [answer.value],
                        text: answer.text || (Array.isArray(answer.value) ? answer.value.join(', ') : answer.value.toString())
                    };
                }
            });
            
            formData.append('quiz_answers', JSON.stringify(formattedAnswers));
            
            Object.keys(audioToUpload).forEach(questionId => {
                const audioBlob = audioToUpload[questionId];
                if (audioBlob && audioBlob.size > 0) {
                    formData.append(`audio_q${questionId}`, audioBlob, `question_${questionId}.webm`);
                }
            });
            
            console.log(`Quiz formaté avec ${Object.keys(formattedAnswers).length} réponses et ${audioCount} fichiers audio`);
        } else {
            console.log('Aucune réponse quiz disponible');
        }
        
        // DEBUG
        console.log('=== CONTENU FORMDATA ===');
        for (let pair of formData.entries()) {
            if (pair[1] instanceof Blob) {
                console.log(`${pair[0]}: [BLOB - ${pair[1].size} bytes]`);
            } else {
                console.log(`${pair[0]}: ${pair[1]}`);
            }
        }
        console.log('========================');
        
        if (QuizPersistence.refreshIfExpired()) {
            return;
        }
        
        if (sessionStorage.getItem('quiz_refreshed')) {
            sessionStorage.removeItem('quiz_refreshed');
            console.log('✅ Token CSRF rafraîchi, soumission maintenant');
        }

        // ✅ Variable pour tracker le succès
        let isSuccess = false;

        // ===== ENVOI DES DONNÉES =====
        fetch('/lead/capture', {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => {
            console.log('=== ANALYSE RÉPONSE SERVEUR ===');
            console.log('Status:', response.status);
            console.log('Content-Type:', response.headers.get('Content-Type'));
            
            return response.text().then(text => {
                console.log('Réponse brute:', text.substring(0, 100));
                
                // ✅ AJOUT : Gestion explicite du statut 409 (email existant)
                if (response.status === 409) {
                    try {
                        const data = JSON.parse(text);
                        // Nettoyer le message Unicode
                        if (data.message) {
                            data.message = cleanUnicodeMessage(data.message);
                        }
                        return data; // Retourner les données pour le traitement dans .then()
                    } catch (parseError) {
                        throw new Error('Email déjà enregistré');
                    }
                }
                
                if (!response.ok) {
                    console.error('Erreur HTTP:', text);
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                try {
                    const data = JSON.parse(text);
                    console.log('JSON parsé:', data);
                    
                    if (data.message) {
                        data.message = cleanUnicodeMessage(data.message);
                    }
                    if (data.error && typeof data.error === 'string') {
                        data.error = cleanUnicodeMessage(data.error);
                    }
                    
                    return data;
                } catch (parseError) {
                    console.error('Erreur parsing JSON:', parseError);
                    throw new Error('Réponse serveur invalide');
                }
            });
        })
        .then(data => {
            console.log('=== TRAITEMENT DONNÉES ===');
            console.log('Données reçues:', data);
            
            if (data.success) {
                console.log('✅ Inscription réussie !');
                
                // ✅ Marquer comme succès
                isSuccess = true;
                
                // Sauvegarder les infos du lead
                const leadData = {
                    email: email,
                    firstname: firstname,
                    timestamp: Date.now(),
                    hasCompletedQuiz: true
                };
                localStorage.setItem('tilto_lead_completed', JSON.stringify(leadData));
            
                const hasAudioResponses = Object.values(homepageQuizAnswers || {}).some(answer => 
                    Array.isArray(answer.value) && 
                    answer.value[0] && 
                    answer.value[0].startsWith('[AUDIO:')
                );
                const responseCount = Object.keys(homepageQuizAnswers || {}).length;
                
                QuizTracking.trackLeadSubmit(hasAudioResponses, responseCount);
                
                // Nettoyer l'état du quiz
                QuizPersistence.clearQuizState();
                console.log('État du quiz nettoyé après inscription réussie');
                
                // Nettoyer le formulaire
                quizForm.reset();
                
                const allInputs = document.querySelectorAll('#quiz-lead-form .form-control');
                allInputs.forEach(input => {
                    input.style.borderColor = '';
                    input.style.boxShadow = '';
                });
                
                if (window.tempQuizAudios) {
                    Object.keys(window.tempQuizAudios).forEach(audioId => {
                        if (window.tempQuizAudios[audioId].url) {
                            try {
                                URL.revokeObjectURL(window.tempQuizAudios[audioId].url);
                            } catch (e) {
                                console.warn('Erreur révocation URL:', e);
                            }
                        }
                    });
                    window.tempQuizAudios = {};
                }
                
                // ✅ TRACKING ANALYTICS
                if (typeof gtag !== 'undefined') {
                    gtag('event', 'quiz_lead_generation', {
                        'event_category': 'Quiz',
                        'event_label': 'homepage_completion_with_quiz',
                        'value': 1,
                        'quiz_completed': data.quiz_saved || false,
                        'has_audio_responses': data.audio_saved || false
                    });
                }
                
                if (typeof fbq !== 'undefined') {
                    fbq('track', 'Lead', {
                        content_category: 'quiz_completion',
                        value: 1.0,
                        currency: 'EUR'
                    });
                }
                
                // 🔥 NOUVEAU : Afficher l'écran de transition puis rediriger
                showTransitionScreen(firstname);
                
                console.log('⏳ Redirection dans 2 secondes...');
                setTimeout(() => {
                    console.log('🚀 Redirection vers /dashboard');
                    window.location.href = '/dashboard';
                }, 2000);
            
            } else {
                // ✅ AJOUT : Gestion spécifique de l'email existant
                if (data.error_type === 'email_exists') {
                    const cleanMessage = cleanUnicodeMessage(data.message) || 'Cette adresse email est déjà enregistrée.';
                    showQuizFormMessage('error', '📧', 'Email déjà utilisé', cleanMessage);
                    focusAndHighlight('quiz-email');
                } else {
                    const cleanMessage = cleanUnicodeMessage(data.message) || 'Une erreur est survenue.';
                    showQuizFormMessage('error', '❌', 'Erreur', cleanMessage);
                }
            }
        })
        .catch(error => {
            console.error('=== ERREUR FETCH ===');
            console.error('Type:', error.name);
            console.error('Message:', error.message);
            
            let errorMessage = 'Impossible de traiter votre demande. ';
            
            if (error.message.includes('Failed to fetch')) {
                errorMessage += 'Vérifiez votre connexion internet.';
            } else if (error.message.includes('NetworkError')) {
                errorMessage += 'Problème de connexion réseau.';
            } else {
                errorMessage += cleanUnicodeMessage(error.message) || 'Erreur inconnue.';
            }
            
            showQuizFormMessage('error', '❌', 'Erreur de connexion', errorMessage);
        })
        .finally(() => {
            // ✅ CORRECTION : Ne réactiver le bouton QUE si ce n'est PAS un succès
            if (!isSuccess) {
                setTimeout(() => {
                    submitBtn.disabled = false;
                    submitBtn.classList.remove('loading');
                    submitBtn.innerHTML = '<span class="btn-text">Je veux recevoir mes recos maintenant</span><span class="btn-arrow">🚀</span>';
                }, 2000);
            }
        });
    });
    
    setupQuizFormValidation();
}

// ===== ÉCRAN DE TRANSITION POST-INSCRIPTION =====
function showTransitionScreen(firstname) {
    console.log('Affichage écran de transition pour:', firstname);
    
    // Masquer le formulaire
    const quizComplete = document.getElementById('quizComplete');
    if (quizComplete) {
        quizComplete.style.display = 'none';
    }
    
    // Récupérer le modal content
    const modalContent = document.querySelector('.quiz-modal-content');
    if (!modalContent) {
        console.error('Modal content non trouvé');
        return;
    }
    
    // Créer l'écran de transition
    const transitionScreen = document.createElement('div');
    transitionScreen.className = 'quiz-transition-screen';
    transitionScreen.innerHTML = `
<div class="transition-content">
    <!-- Icône check SVG sobre et pro -->
    <div class="transition-icon">
        <svg width="64" height="64" viewBox="0 0 64 64">
            <circle cx="32" cy="32" r="30" fill="url(#gradientSuccess)"/>
            <path d="M20 32L28 40L44 24" stroke="white" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
            <defs>
                <linearGradient id="gradientSuccess" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:#10b981;stop-opacity:1" />
                    <stop offset="100%" style="stop-color:#059669;stop-opacity:1" />
                </linearGradient>
            </defs>
        </svg>
    </div>
    
    <h2 class="transition-title">Compte créé</h2>
    <p class="transition-subtitle">Tes réponses ont été sauvegardées.</p>
    
    <div class="transition-loader">
        <span class="loader-text">Redirection en cours</span>
        <div class="loader-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
        </div>
    </div>
</div>
    `;
    
    // Remplacer le contenu du modal
    modalContent.innerHTML = '';
    modalContent.appendChild(transitionScreen);
    
    // Faire défiler en haut
    modalContent.scrollTop = 0;
}

// Fonction helper pour afficher les messages
function showQuizFormMessage(type, icon, title, message) {
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

function showSuccessScreen(isReturning = false, leadData = null) {
    const quizComplete = document.getElementById('quizComplete');
    const newSuccessScreen = document.getElementById('quiz-success-screen');
    
    if (isReturning && leadData) {
        if (quizComplete) {
            quizComplete.innerHTML = `
                <div class="quiz-success-container">
                    <div class="quiz-success-content">
                        <div class="success-icon-container">
                            <div class="success-icon" style="font-size: 3rem;">👋</div>
                        </div>
                        
                        <h2 class="quiz-success-title">
                            Re-bonjour ${leadData.firstname} !
                        </h2>
                        
                        <div class="quiz-success-messages">
                            <p class="success-message primary">
                                <strong>Tu es déjà inscrit(e)</strong>&nbsp;avec cette adresse email.
                            </p>
                            
                            <p class="success-message secondary">
                                On a bien enregistré tes nouvelles réponses au quiz 👍
                            </p>
                            
                            <!-- Bloc violet avec les 3 étapes -->
                            <div style="background: linear-gradient(135deg, #A11857 0%, #8b1a6b 100%); padding: 1.5rem; border-radius: 12px; margin: 1.5rem 0; border: none;">
                                <div style="color: white; text-align: left;">
                                    <p style="font-weight: 700; margin: 0 0 1rem; font-size: 1.1rem;">📋 Prochaines étapes :</p>
                                    
                                    <div style="display: flex; flex-direction: column; gap: 0.75rem;">
                                        <!-- Étape 1 -->
                                        <div style="display: flex; align-items: flex-start; gap: 0.75rem;">
                                            <span style="background: rgba(255,255,255,0.2); width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-weight: 700;">1</span>
                                            <div style="flex: 1;">
                                                <strong>Active ton compte</strong><br>
                                                <span style="font-size: 0.9rem; opacity: 0.95;">Clique sur le lien dans l'email envoyé à ${leadData.email || 'ton adresse'}</span>
                                            </div>
                                        </div>
                                        
                                        <!-- Étape 2 -->
                                        <div style="display: flex; align-items: flex-start; gap: 0.75rem;">
                                            <span style="background: rgba(255,255,255,0.2); width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-weight: 700;">2</span>
                                            <div style="flex: 1;">
                                                <strong>Crée ton mot de passe</strong><br>
                                                <span style="font-size: 0.9rem; opacity: 0.95;">Pour sécuriser ton compte Tilto</span>
                                            </div>
                                        </div>
                                        
                                        <!-- Étape 3 -->
                                        <div style="display: flex; align-items: flex-start; gap: 0.75rem;">
                                            <span style="background: rgba(255,255,255,0.2); width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; font-weight: 700;">3</span>
                                            <div style="flex: 1;">
                                                <strong>Reçois tes recos sous 48h</strong><br>
                                                <span style="font-size: 0.9rem; opacity: 0.95;">Disponibles directement dans ton espace</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            
                        <p style="text-align: center; margin-top: 1.5rem; font-size: 0.875rem; color: #666; line-height: 1.6;">
                            Email introuvable ? Vérifie tes <strong>spams</strong> ou attends 5 min.<br>
                            Besoin d'aide ? <a href="mailto:contact@tilto.ai" style="color: #A11857; font-weight: 600; text-decoration: none;">contact@tilto.ai</a>
                        </p>
                        </div>
                    </div>
                </div>
            `;
            quizComplete.style.display = 'block';
            if (newSuccessScreen) newSuccessScreen.style.display = 'none';
        }
    } else {
        // ✅ NOUVEL UTILISATEUR : Afficher le nouvel écran
        if (quizComplete) quizComplete.style.display = 'none';
        
        if (newSuccessScreen) {
            // Récupérer l'email du formulaire
            const emailInput = document.getElementById('quiz-email');
            const userEmail = emailInput ? emailInput.value : 'ton adresse';
            
            // Mettre à jour l'email dans le bloc violet
            const emailInCard = document.getElementById('user-email-in-card');
            if (emailInCard) {
                emailInCard.textContent = userEmail;
            }
            
            // Mettre à jour l'email sous le bouton
            const emailDisplay = document.getElementById('user-email-display');
            if (emailDisplay) {
                emailDisplay.textContent = userEmail;
            }
            
            // Afficher le nouvel écran
            newSuccessScreen.style.display = 'block';
            
            // Scroll to top du modal
            const modalContent = document.querySelector('.quiz-modal-content');
            if (modalContent) {
                modalContent.scrollTop = 0;
            }
        }
    }
}

// Fonction helper pour focus et highlight
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





// Fonction de nettoyage pour homepage MODIFIÉE
function cleanupHomepageQuiz() {
    isHomepageMode = false;
    homepageQuizAnswers = {};
    homepageQuestionHistory = [];
    homepageCurrentQuestionIndex = 0;
    homepageAllQuestions = [];
    
    // Cacher toutes les sections du quiz
    const quizWelcome = document.getElementById('quizWelcome');
    const quizContent = document.getElementById('quizContent');
    const quizComplete = document.getElementById('quizComplete');
    
    if (quizWelcome) quizWelcome.style.display = 'none';
    if (quizContent) quizContent.style.display = 'none';
    if (quizComplete) quizComplete.style.display = 'none';
}

// NOUVEAU : Sauvegarder avant fermeture de la modal
function handleQuizModalClose() {
    console.log('Fermeture de la modal quiz - sauvegarde en cours');
    
    // Sauvegarder l'état si le quiz est en cours
    if (isHomepageMode && Object.keys(homepageQuizAnswers).length > 0) {
        QuizPersistence.saveQuizState();
        console.log('État sauvegardé avant fermeture');
    }
}

async function startVoiceRecording(textArea, button, visualizer, timerContainer, audioContainer) {
    try {
        console.log('Début enregistrement audio avec limite de 3 minutes');
        
        const questionId = getCurrentQuestionId();
        console.log('Enregistrement pour question:', questionId);
        
        // Vérifier et initialiser l'état si nécessaire
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0
            };
        }
        
        // Si on continue un enregistrement, conserver l'audio existant
        if (!isContinuingRecording) {
            audioChunks = [];
            audioBlob = null;
            audioURL = null;
            existingAudioDuration = 0;
        } else {
            // En mode continuation, on garde les chunks existants
            console.log('Mode continuation - durée existante:', existingAudioDuration);
        }
        
        // Mettre à jour l'état AVANT de commencer l'enregistrement
        currentQuestionAudioState[questionId].isRecording = true;
        isRecording = true;
        
        console.log('État mis à jour - isRecording:', currentQuestionAudioState[questionId].isRecording);
        
        // Cacher les contrôles de lecture s'ils étaient visibles
        const playbackControls = audioContainer.querySelector('.audio-playback-controls');
        const audioElement = audioContainer.querySelector('.audio-element');
        const recordingWarning = audioContainer.querySelector('.recording-warning');
        const existingAudioInfo = audioContainer.querySelector('.existing-audio-info');
        
        if (playbackControls) playbackControls.style.display = 'none';
        if (audioElement) audioElement.style.display = 'none';
        if (recordingWarning) recordingWarning.style.display = 'none';
        if (existingAudioInfo && !isContinuingRecording) existingAudioInfo.style.display = 'none';
        
        // Afficher les infos de l'audio existant si on continue
        if (isContinuingRecording && existingAudioInfo) {
            const durationValue = existingAudioInfo.querySelector('.duration-value');
            if (durationValue) {
                durationValue.textContent = formatRecordingTime(existingAudioDuration);
            }
            existingAudioInfo.style.display = 'block';
        }
        
        // Demander l'autorisation microphone
        audioStream = await navigator.mediaDevices.getUserMedia({ 
            audio: { 
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            } 
        });
        
        console.log('Microphone autorisé');
        
        // Initialiser les alertes visuelles avec overlay de temps
        initializeRecordingAlerts(button, true);
        
        // Changer l'interface visuelle - ICONE STOP - CORRECTION ICI
        if (isContinuingRecording) {
            // En mode continuation, le bouton principal devient le bouton stop
            button.style.display = 'block';
            button.innerHTML = `
                <div class="pulse-ring"></div>
                <i class="fas fa-stop"></i>
            `;
            button.classList.add('recording');
            
            // Masquer le bouton continuer
            const continueBtn = audioContainer.querySelector('.continue-audio-btn');
            if (continueBtn) continueBtn.style.display = 'none';
        } else {
            // Mode normal
            button.innerHTML = `
                <div class="pulse-ring"></div>
                <i class="fas fa-stop"></i>
            `;
            button.classList.add('recording');
        }
        
        // Gérer les états d'affichage
        const listenStateReady = audioContainer.querySelector('.listen-state .ready');
        const listenStateRecording = audioContainer.querySelector('.listen-state .recording');
        const listenStateRecorded = audioContainer.querySelector('.listen-state .recorded');
        
        if (listenStateReady) listenStateReady.style.display = 'none';
        if (listenStateRecording) listenStateRecording.style.display = 'block';
        if (listenStateRecorded) listenStateRecorded.style.display = 'none';
        if (visualizer) visualizer.style.display = 'flex';
        
        // Créer la barre de progression visuelle
        let progressContainer = null;
        if (audioContainer) {
            progressContainer = createProgressBar(audioContainer);
        }
        
        // Démarrer le timer avec toutes les mises à jour visuelles
        if (timerContainer) {
            timerContainer.style.display = 'flex';
            recordingStartTime = Date.now() - (existingAudioDuration * 1000); // Ajuster pour la durée existante
            recordingTimer = setInterval(() => {
                updateRecordingTimer(timerContainer);
                if (progressContainer) {
                    updateProgressBar(progressContainer);
                }
            }, 1000);
            updateRecordingTimer(timerContainer);
        }
        
        // Animer les barres d'onde
        const waveBars = visualizer.querySelectorAll('.wave-bar');
        if (waveBars.length > 0) {
            waveBars.forEach(bar => {
                bar.style.animationPlayState = 'running';
            });
        }
        
        // Créer le MediaRecorder
        mediaRecorder = new MediaRecorder(audioStream, {
            mimeType: 'audio/webm;codecs=opus',
            audioBitsPerSecond: 128000
        });
        
        // Collecter les données audio
        mediaRecorder.addEventListener('dataavailable', event => {
            console.log('Données audio reçues:', event.data.size);
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        });
        
        // Lorsque l'enregistrement est terminé
        mediaRecorder.addEventListener('stop', async () => {
            console.log('Enregistrement terminé, traitement...');
            
            const currentQuestionId = getCurrentQuestionId();
            console.log('Sauvegarde audio pour question:', currentQuestionId);
            
            // Nettoyer les alertes visuelles
            cleanupRecordingAlerts(button);
            
            // Arrêter et masquer le timer
            if (recordingTimer) {
                clearInterval(recordingTimer);
                recordingTimer = null;
            }
            if (timerContainer) {
                timerContainer.style.display = 'none';
            }
            
            // Masquer le visualiseur et arrêter les animations
            if (visualizer) {
                visualizer.style.display = 'none';
                const waveBars = visualizer.querySelectorAll('.wave-bar');
                if (waveBars.length > 0) {
                    waveBars.forEach(bar => {
                        bar.style.animationPlayState = 'paused';
                    });
                }
            }
            
            // Supprimer la barre de progression
            if (progressContainer && progressContainer.parentNode) {
                progressContainer.remove();
            }
            
            // Mettre à jour les états d'affichage
            if (listenStateRecording) listenStateRecording.style.display = 'none';
            if (listenStateReady) listenStateReady.style.display = 'none';
            if (listenStateRecorded) listenStateRecorded.style.display = 'block';
            
            // Calculer la durée totale
            const newRecordingDuration = Math.floor((Date.now() - recordingStartTime) / 1000);
            const totalDuration = isContinuingRecording ? existingAudioDuration + newRecordingDuration : newRecordingDuration;
            
            // CRÉER LE BLOB AUDIO
            audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            audioURL = URL.createObjectURL(audioBlob);
            
            console.log('Audio blob créé:', audioBlob.size, 'bytes, durée totale:', totalDuration);

            // Configurer l'audio element
            if (audioElement) {
                audioElement.src = audioURL;
                audioElement.load();
                audioElement.style.display = 'block';
                console.log('Audio element configuré et visible');
            }

            // Vérifier la durée minimale et afficher le warning si nécessaire
            const continueBtn = audioContainer.querySelector('.continue-audio-btn');
            const recordingWarning = audioContainer.querySelector('.recording-warning');
            
            if (totalDuration < MIN_RECORDING_TIME) {
                console.log('Enregistrement trop court:', totalDuration, 'secondes');
                if (recordingWarning) {
                    recordingWarning.style.display = 'block';
                }
                if (continueBtn) {
                    continueBtn.style.display = 'inline-block';
                }
            } else {
                if (recordingWarning) {
                    recordingWarning.style.display = 'none';
                }
                if (continueBtn) {
                    continueBtn.style.display = 'none';
                }
            }

            // Afficher les contrôles de lecture
            if (playbackControls) {
                playbackControls.style.display = 'flex';
            }

            // Masquer le bouton d'enregistrement principal
            button.style.display = 'none';
            
            // Mettre à jour le placeholder du textarea si disponible
            if (textArea) {
                textArea.placeholder = 'Enregistrement terminé. Utilisez les boutons ci-dessus pour réécouter, supprimer ou réenregistrer.';
                textArea.disabled = false;
            }
            
            // Arrêter toutes les pistes du flux
            if (audioStream) {
                audioStream.getTracks().forEach(track => track.stop());
                audioStream = null;
            }
            
            // Sauvegarder l'état pour la question spécifique
            if (currentQuestionAudioState[currentQuestionId]) {
                currentQuestionAudioState[currentQuestionId].audioBlob = audioBlob;
                currentQuestionAudioState[currentQuestionId].audioURL = audioURL;
                currentQuestionAudioState[currentQuestionId].isRecording = false;
                currentQuestionAudioState[currentQuestionId].duration = totalDuration;
            }
            
            isRecording = false;
            existingAudioDuration = totalDuration;
            
            // Sauvegarder dans le stockage global
            globalAudioStorage[currentQuestionId] = {
                blob: audioBlob,
                url: audioURL,
                questionId: currentQuestionId,
                timestamp: Date.now(),
                duration: totalDuration
            };
            
            // Réinitialiser le flag de continuation
            isContinuingRecording = false;
            
            console.log('Interface mise à jour après enregistrement pour question:', currentQuestionId);
            console.log('Audio sauvegardé dans globalAudioStorage:', Object.keys(globalAudioStorage));
        });
        
        // Démarrer l'enregistrement
        mediaRecorder.start(1000); // Chunk de 1 seconde
        
        console.log('Enregistrement démarré pour question:', questionId);
        
    } catch (error) {
        console.error('Erreur d\'accès au microphone:', error);
        
        // Réinitialiser l'état en cas d'erreur
        const questionId = getCurrentQuestionId();
        if (currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId].isRecording = false;
        }
        isRecording = false;
        isContinuingRecording = false;
        
        alert('Impossible d\'accéder au microphone. Veuillez vérifier les permissions de votre navigateur.');
        resetRecordingUI(button, audioContainer);
    }
}


// Fonction pour arrêter l'enregistrement vocal
function stopVoiceRecording(textArea, button, visualizer, timerContainer, audioContainer) {
    console.log('Arrêt de l\'enregistrement demandé');
    if (mediaRecorder && isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        console.log('MediaRecorder arrêté');
        // L'interface sera mise à jour dans l'événement 'stop' du MediaRecorder
    }
}


// Solution de fallback pour les icônes Font Awesome dans le quiz modal
function ensureFontAwesome() {
    // Vérifier si Font Awesome est chargé
    const testElement = document.createElement('i');
    testElement.className = 'fas fa-play';
    testElement.style.visibility = 'hidden';
    testElement.style.position = 'absolute';
    document.body.appendChild(testElement);
    
    const computedStyle = window.getComputedStyle(testElement, '::before');
    const fontFamily = computedStyle.fontFamily;
    
    document.body.removeChild(testElement);
    
    // Si Font Awesome n'est pas détecté, utiliser des caractères Unicode
    if (!fontFamily.includes('Font Awesome')) {
        console.warn('Font Awesome non détecté, utilisation des fallbacks Unicode');
        return {
            play: '▶️',
            stop: '⏹️',
            trash: '🗑️'
        };
    }
    
    return {
        play: '<div class="mic-design"></div>',
        stop: '<i class="fas fa-stop"></i>',
        trash: '<i class="fas fa-trash"></i>'
    };
}


function setupAudioEventsWithQuestionId(audioContainer, textArea, questionId) {
    setTimeout(() => {
        const voiceButton = audioContainer.querySelector('.listen-button');
        const audioWave = audioContainer.querySelector('.audio-wave');
        const timerContainer = audioContainer.querySelector('.timer');
        const audioElement = audioContainer.querySelector('.audio-element');
        const playbackControls = audioContainer.querySelector('.audio-playback-controls');
        const replayBtn = audioContainer.querySelector('.replay-audio-btn');
        const deleteBtn = audioContainer.querySelector('.delete-audio-btn');
        const recordAgainBtn = audioContainer.querySelector('.record-again-btn');
        const continueBtn = audioContainer.querySelector('.continue-audio-btn');
        const existingAudioInfo = audioContainer.querySelector('.existing-audio-info');
        
        console.log('Setup audio pour question (fixed):', questionId);
        
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0
            };
        }
        
        const questionState = currentQuestionAudioState[questionId];
        audioBlob = questionState.audioBlob;
        audioURL = questionState.audioURL;
        isRecording = questionState.isRecording;
        existingAudioDuration = questionState.duration || 0;
        
        updateAudioDisplayState(audioContainer, questionState);
        
        // Bouton principal d'enregistrement
        if (voiceButton) {
            voiceButton.removeEventListener('click', voiceButton.clickHandler);
            
            voiceButton.clickHandler = function() {
                const currentState = currentQuestionAudioState[questionId];
                
                if (currentState.isRecording) {
                    stopVoiceRecording(textArea, voiceButton, audioWave, timerContainer, audioContainer);
                } else if (!currentState.audioBlob) {
                    isContinuingRecording = false;
                    existingAudioDuration = 0;
                    startVoiceRecording(textArea, voiceButton, audioWave, timerContainer, audioContainer);
                }
            };
            
            voiceButton.addEventListener('click', voiceButton.clickHandler);
        }
        
        // Bouton continuer l'enregistrement
        if (continueBtn) {
            continueBtn.removeEventListener('click', continueBtn.clickHandler);
            
            continueBtn.clickHandler = function() {
                console.log('Continuation enregistrement pour question:', questionId);
                isContinuingRecording = true;
                startVoiceRecording(textArea, voiceButton, audioWave, timerContainer, audioContainer);
            };
            
            continueBtn.addEventListener('click', continueBtn.clickHandler);
        }
        
        // Bouton réécouter
        if (replayBtn) {
            replayBtn.removeEventListener('click', replayBtn.clickHandler);
            
            replayBtn.clickHandler = function() {
                console.log('Réécoute audio question:', questionId);
                if (audioElement && currentQuestionAudioState[questionId].audioURL) {
                    audioElement.style.display = 'block';
                    audioElement.currentTime = 0;
                    audioElement.play().catch(err => {
                        console.error('Erreur lecture audio:', err);
                    });
                }
            };
            
            replayBtn.addEventListener('click', replayBtn.clickHandler);
        }
        
        // Bouton supprimer
        if (deleteBtn) {
            deleteBtn.removeEventListener('click', deleteBtn.clickHandler);
            
            deleteBtn.clickHandler = function() {
                console.log('Suppression audio question:', questionId);
                deleteQuestionAudio(questionId, audioContainer, voiceButton, textArea);
            };
            
            deleteBtn.addEventListener('click', deleteBtn.clickHandler);
        }
        
        // Bouton réenregistrer
        if (recordAgainBtn) {
            recordAgainBtn.removeEventListener('click', recordAgainBtn.clickHandler);
            
            recordAgainBtn.clickHandler = function() {
                console.log('Réenregistrement audio question:', questionId);
                deleteQuestionAudio(questionId, audioContainer, voiceButton, textArea);
                setTimeout(() => {
                    isContinuingRecording = false;
                    existingAudioDuration = 0;
                    startVoiceRecording(textArea, voiceButton, audioWave, timerContainer, audioContainer);
                }, 100);
            };
            
            recordAgainBtn.addEventListener('click', recordAgainBtn.clickHandler);
        }
        
    }, 150);
}

// ===== 3. NOUVELLE FONCTION - Configuration des événements audio =====
function setupEnhancedAudioEvents(audioContainer, textArea, charCount, questionId, maxLength) {
    console.log('Configuration événements audio pour question:', questionId);
    
    // Attendre que les éléments soient bien dans le DOM
    setTimeout(() => {
        const micButton = audioContainer.querySelector('.enhanced-mic-button');
        const switchToTextBtn = audioContainer.querySelector('.switch-to-text-btn');
        const listenBtn = audioContainer.querySelector('.listen-btn');
        const rerecordBtn = audioContainer.querySelector('.rerecord-btn');
        const continueBtn = audioContainer.querySelector('.continue-btn');
        
        console.log('Éléments trouvés:', {
            micButton: !!micButton,
            listenBtn: !!listenBtn,
            rerecordBtn: !!rerecordBtn,
            continueBtn: !!continueBtn
        });
        
        // Bouton micro principal - VERSION SIMPLIFIÉE
        if (micButton) {
            // Supprimer les anciens handlers
            micButton.onclick = null;
            micButton.ontouchend = null;
            micButton.removeEventListener('click', micButton.clickHandler);
            micButton.removeEventListener('touchend', micButton.touchHandler);
            
            // Handler unique et simple
            const handleMicClick = function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                console.log('=== CLIC MICRO BUTTON ===');
                console.log('Question ID:', questionId);
                console.log('Event type:', e.type);
                
                const questionState = currentQuestionAudioState[questionId];
                console.log('Question state:', questionState);
                console.log('Is recording:', questionState.isRecording);
                console.log('Has audioBlob:', !!questionState.audioBlob);
                
                if (questionState.isRecording) {
                    console.log('APPEL stopEnhancedRecording');
                    stopEnhancedRecording(audioContainer, questionId);
                } else if (!questionState.audioBlob) {
                    console.log('APPEL startEnhancedRecording');
                    startEnhancedRecording(audioContainer, questionId);
                }
                console.log('=== FIN CLIC MICRO ===');
            };
            
            // Attacher les événements de façon simple
            micButton.addEventListener('click', handleMicClick);
            micButton.addEventListener('touchend', function(e) {
                e.preventDefault();
                handleMicClick(e);
            }, { passive: false });
            
            console.log('Event listeners attachés simplement');
        }
        
        // Bouton "Je préfère écrire"
        if (switchToTextBtn) {
            switchToTextBtn.removeEventListener('click', switchToTextBtn.clickHandler);
            switchToTextBtn.removeEventListener('touchend', switchToTextBtn.touchHandler);
            
            const handleSwitchToText = function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                console.log('Basculement vers mode texte demandé');
                
                if (!textArea || !charCount) {
                    console.error('textArea ou charCount manquant pour le basculement');
                    return;
                }
                
                switchToTextMode(audioContainer, textArea, charCount);
            };
            
            switchToTextBtn.addEventListener('click', handleSwitchToText);
            switchToTextBtn.addEventListener('touchend', handleSwitchToText, { passive: false });
            
            console.log('Gestionnaires "Je préfère écrire" configurés');
        } else {
            console.warn('Bouton "Je préfère écrire" non trouvé');
        }
        
        // Boutons de contrôle post-enregistrement
        if (listenBtn) {
            listenBtn.removeEventListener('click', listenBtn.clickHandler);
            listenBtn.clickHandler = () => playRecording(audioContainer, questionId);
            listenBtn.addEventListener('click', listenBtn.clickHandler);
        }
        
        if (rerecordBtn) {
            rerecordBtn.removeEventListener('click', rerecordBtn.clickHandler);
            rerecordBtn.clickHandler = () => {
                resetRecording(audioContainer, questionId);
                startEnhancedRecording(audioContainer, questionId);
            };
            rerecordBtn.addEventListener('click', rerecordBtn.clickHandler);
        }
        
        if (continueBtn) {
            continueBtn.removeEventListener('click', continueBtn.clickHandler);
            continueBtn.clickHandler = function() {
                console.log('Continuation enregistrement pour question:', questionId);
                isContinuingRecording = true;
                startEnhancedRecording(audioContainer, questionId);
            };
            continueBtn.addEventListener('click', continueBtn.clickHandler);
        }
        
        // Configuration des événements textarea
        if (textArea && charCount) {
            textArea.removeEventListener('input', textArea.inputHandler);
            
            textArea.inputHandler = function() {
                updateCharCount(textArea, charCount, maxLength);
            };
            
            textArea.addEventListener('input', textArea.inputHandler);
            
            console.log('Gestionnaires textarea configurés');
        }
        
        console.log('Configuration des événements audio terminée pour question:', questionId);
        
    }, 100);
}

// ===== FONCTION startEnhancedRecording COMPLÈTE =====
async function startEnhancedRecording(audioContainer, questionId) {
    console.log('=== DEBUT startEnhancedRecording ===');
    console.log('QuestionId:', questionId);
    console.log('AudioContainer:', !!audioContainer);
    
    try {
        console.log('Démarrage enregistrement amélioré pour question:', questionId);
        
        // CORRECTION SAFARI : Vérifier le support avant de continuer
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            throw new Error('Votre navigateur ne supporte pas l\'enregistrement audio');
        }
        
        // Réinitialiser l'état
        audioChunks = [];
        audioBlob = null;
        audioURL = null;
        
        // CORRECTION SAFARI : Configuration audio spécifique
        const audioConstraints = {
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            }
        };
        
        // Pour Safari, simplifier les contraintes
        if (isSafari()) {
            audioConstraints.audio = {
                echoCancellation: false,
                noiseSuppression: false,
                autoGainControl: false
            };
        }
        
        try {
            if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
                console.log('Appel getUserMedia avec contraintes:', audioConstraints);
                audioStream = await navigator.mediaDevices.getUserMedia(audioConstraints);
                console.log('getUserMedia réussi, stream:', audioStream);
            } else if (navigator.webkitGetUserMedia) {
                audioStream = await new Promise((resolve, reject) => {
                    navigator.webkitGetUserMedia(audioConstraints, resolve, reject);
                });
            } else {
                throw new Error('Microphone non supporté sur ce navigateur');
            }
        } catch (permissionError) {
            if (permissionError.name === 'NotAllowedError' && isSafari()) {
                throw new Error('Sur Safari iOS : allez dans Réglages > Safari > Micro et autorisez l\'accès, puis rechargez la page.');
            }
            throw permissionError;
        }
        
        // Mettre à jour l'interface
        updateRecordingUI(audioContainer, 'recording');
        
        // Marquer comme enregistrement en cours
        currentQuestionAudioState[questionId].isRecording = true;
        isRecording = true;
        
        // Démarrer le timer
        recordingStartTime = Date.now();
        lastVolumeCheck = Date.now();
        startEnhancedTimer(audioContainer);
        
        // NOUVEAU : Démarrer le message dynamique
        if (audioContainer._updateRecordingMessage) {
            setTimeout(() => {
                if (isRecording) {
                    audioContainer._updateRecordingMessage();
                }
            }, 1000); // Démarrer après 1 seconde
        }
        
        // NOUVEAU : Initialiser le système d'encouragement (sans boucle)
        initializeEncouragementSystem(audioContainer, questionId);
        
        // Configurer l'analyse audio (optionnel sur Safari)
        if (!isSafari()) {
            setupAudioAnalysis(audioStream, audioContainer);
        }
        
        // CORRECTION SAFARI : Vérifier les codecs supportés
        let mimeType = 'audio/webm;codecs=opus';
        if (isSafari() && !MediaRecorder.isTypeSupported(mimeType)) {
            const supportedTypes = [
                'audio/mp4',
                'audio/mp4;codecs=mp4a.40.2',
                'audio/webm',
                'audio/wav'
            ];
            
            mimeType = supportedTypes.find(type => MediaRecorder.isTypeSupported(type)) || '';
        }
        
        // Créer le MediaRecorder avec options Safari
        const recorderOptions = {
            audioBitsPerSecond: 128000
        };
        
        if (mimeType) {
            recorderOptions.mimeType = mimeType;
        }
        
        mediaRecorder = new MediaRecorder(audioStream, recorderOptions);
        
        mediaRecorder.addEventListener('dataavailable', event => {
            if (event.data.size > 0) {
                audioChunks.push(event.data);
            }
        });
        
        mediaRecorder.addEventListener('stop', () => {
            handleRecordingComplete(audioContainer, questionId);
        });
        
        // CORRECTION SAFARI : Démarrer avec un intervalle plus grand
        const timeslice = isSafari() ? 3000 : 1000; // 3s pour Safari, 1s pour les autres
        mediaRecorder.start(timeslice);
        
        console.log('Enregistrement démarré avec succès sur', isSafari() ? 'Safari' : 'autre navigateur');
        console.log('Message dynamique programmé:', !!audioContainer._updateRecordingMessage);
        console.log('Système d\'encouragement initialisé');
        
    } catch (error) {
        console.error('Erreur démarrage enregistrement:', error);
        handleRecordingError(audioContainer, error);
        
        // Nettoyer l'état en cas d'erreur
        isRecording = false;
        if (currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId].isRecording = false;
        }
    }
}

function setupAudioAnalysis(stream, audioContainer) {
    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.8;
        source.connect(analyser);
        
        const bufferLength = analyser.frequencyBinCount;
        dataArray = new Uint8Array(bufferLength);
        
        // Démarrer l'analyse en temps réel
        startVoiceFeedback(audioContainer);
        
    } catch (error) {
        console.error('Erreur configuration analyse audio:', error);
    }
}

// ===== 6. NOUVELLE FONCTION - Feedback vocal temps réel =====
function startVoiceFeedback(audioContainer) {
    const halo = audioContainer.querySelector('.voice-feedback-halo');
    if (!halo || !analyser) return;
    
    function updateFeedback() {
        if (!isRecording || !analyser) return;
        
        analyser.getByteFrequencyData(dataArray);
        
        // Calculer le volume moyen
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
            sum += dataArray[i];
        }
        const average = sum / dataArray.length;
        const volume = average / 255; // Normaliser entre 0 et 1
        
        // Appliquer le feedback visuel
        const intensity = Math.max(0.1, volume);
        const scale = 1 + (intensity * 0.3);
        const opacity = 0.3 + (intensity * 0.4);
        
        halo.style.transform = `scale(${scale})`;
        halo.style.opacity = opacity;
        
        // CORRECTION : NE PAS gérer le timer de silence ici
        // Juste mettre à jour lastVolumeCheck si il y a de la voix
        if (volume > 0.02) {
            lastVolumeCheck = Date.now();
        }
        
        // Continuer l'analyse
        requestAnimationFrame(updateFeedback);
    }
    
    updateFeedback();
}

function initializeEncouragementSystem(audioContainer, questionId) {
    // Timer unique pour chaque palier de temps - BULLES UNIQUEMENT
    const encouragementTimers = [
        setTimeout(() => {
            if (isRecording) {
                showSingleEncouragementMessage(audioContainer, questionId, 45);
            }
        }, 45000),
        
        setTimeout(() => {
            if (isRecording) {
                showSingleEncouragementMessage(audioContainer, questionId, 75);
            }
        }, 75000),
        
        setTimeout(() => {
            if (isRecording) {
                showSingleEncouragementMessage(audioContainer, questionId, 120);
            }
        }, 120000),
        
        setTimeout(() => {
            if (isRecording) {
                showSingleEncouragementMessage(audioContainer, questionId, 160);
            }
        }, 160000)
    ];
    
    // Stocker les timers pour les nettoyer plus tard
    audioContainer._encouragementTimers = encouragementTimers;
}

function showSingleEncouragementMessage(audioContainer, questionId, timing) {
    const bubble = audioContainer.querySelector('.encouragement-bubble');
    const content = bubble.querySelector('.bubble-content');
    
    if (!bubble || !content) return;
    
    // Récupérer le message approprié
    const questionMessages = ENCOURAGEMENT_MESSAGES[questionId] || ENCOURAGEMENT_MESSAGES['default'];
    let message = "Continue, je t'écoute...";
    
    // Sélectionner le message selon le timing
    if (timing >= 120) {
        message = questionMessages[120] || "Tu peux conclure quand tu le souhaites";
    } else if (timing >= 60) {
        message = questionMessages[75] || "Tu peux faire une pause si tu veux";
    } else if (timing >= 25) {
        message = questionMessages[45] || "Prends ton temps";
    }
    
    console.log(`Encouragement à ${timing}s: "${message}"`);
    content.textContent = message;
    
    // Afficher
    bubble.style.display = 'block';
    setTimeout(() => bubble.classList.add('show'), 10);
    
    // Masquer après 4 secondes
    setTimeout(() => {
        bubble.classList.remove('show');
        setTimeout(() => bubble.style.display = 'none', 300);
    }, 4000);
}


// ===== 7. NOUVELLE FONCTION - Timer amélioré =====
function startEnhancedTimer(audioContainer) {
    const timerDisplay = audioContainer.querySelector('.timer-display');
    const progressRing = audioContainer.querySelector('.progress-ring-bar');
    const progressCircumference = 2 * Math.PI * 70; // rayon 70px
    
    if (!timerDisplay) return;
    
    // Afficher le timer
    const timerContainer = audioContainer.querySelector('.enhanced-timer');
    if (timerContainer) {
        timerContainer.style.display = 'block';
    }
    
    recordingTimer = setInterval(() => {
        if (!recordingStartTime) return;
        
        const elapsedSeconds = Math.floor((Date.now() - recordingStartTime) / 1000);
        const minutes = Math.floor(elapsedSeconds / 60);
        const seconds = elapsedSeconds % 60;
        
        // Mettre à jour l'affichage
        timerDisplay.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        
        // Mettre à jour la jauge circulaire
        if (progressRing) {
            const progress = elapsedSeconds / MAX_RECORDING_TIME;
            const offset = progressCircumference * (1 - progress);
            progressRing.style.strokeDashoffset = offset;
        }
        
        // Arrêt automatique à la limite
        if (elapsedSeconds >= MAX_RECORDING_TIME) {
            const questionId = getCurrentQuestionId();
            stopEnhancedRecording(audioContainer, questionId);
        }
        
    }, 1000);
}


// NOUVEAU CODE AVEC TIMING
function showEncouragementMessage(audioContainer, questionId) {
    const bubble = audioContainer.querySelector('.encouragement-bubble');
    const content = bubble.querySelector('.bubble-content');
    
    if (!bubble || !content) {
        console.warn('Éléments de bulle d\'encouragement manquants');
        return;
    }
    
    // Calculer le temps écoulé depuis le début de l'enregistrement
    const elapsedSeconds = Math.floor((Date.now() - recordingStartTime) / 1000);
    console.log(`Affichage encouragement à ${elapsedSeconds}s`);
    
    // Récupérer les messages pour cette question ou utiliser les messages par défaut
    const questionMessages = ENCOURAGEMENT_MESSAGES[questionId] || ENCOURAGEMENT_MESSAGES['default'];
    
    // Trouver le message approprié selon le timing
    let message = "Continue, je t'écoute..."; // Fallback de sécurité
    
    // NOUVELLE LOGIQUE : Messages par paliers de temps
    if (elapsedSeconds >= 160) {
        message = questionMessages[160] || questionMessages['default'][160] || "Tu peux conclure quand tu le souhaites";
    } else if (elapsedSeconds >= 120) {
        message = questionMessages[120] || questionMessages['default'][120] || "Tu maîtrises parfaitement";
    } else if (elapsedSeconds >= 75) {
        message = questionMessages[75] || questionMessages['default'][75] || "Tu peux faire une pause si tu veux";
    } else if (elapsedSeconds >= 45) {
        message = questionMessages[45] || questionMessages['default'][45] || "Prends ton temps";
    } else if (elapsedSeconds >= 20) {
        message = questionMessages[20] || questionMessages['default'][20] || "Je t'écoute...";
    }
    
    console.log(`Message sélectionné: "${message}"`);
    content.textContent = message;
    
    // Afficher avec animation
    bubble.style.display = 'block';
    setTimeout(() => bubble.classList.add('show'), 10);
    
    // Masquer après 4 secondes
    setTimeout(() => {
        bubble.classList.remove('show');
        setTimeout(() => {
            if (bubble.style.display !== 'none') {
                bubble.style.display = 'none';
            }
        }, 300);
    }, 4000);
    
    // CORRECTION IMPORTANTE : Programmer le prochain message seulement après avoir affiché celui-ci
    setTimeout(() => {
        if (isRecording) {
            resetSilenceTimer(audioContainer, questionId);
        }
    }, 5000); // Attendre 5 secondes après l'affichage
}

// ===== FONCTION stopEnhancedRecording COMPLÈTE =====
function stopEnhancedRecording(audioContainer, questionId) {
    console.log('=== DÉBUT stopEnhancedRecording ===');
    console.log('QuestionId:', questionId);
    console.log('isRecording avant arrêt:', isRecording);
    console.log('mediaRecorder state:', mediaRecorder?.state);
    
    if (mediaRecorder && isRecording) {
        try {
            // Arrêter l'enregistrement
            if (mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
            
            isRecording = false;
            currentQuestionAudioState[questionId].isRecording = false;
            
            console.log('MediaRecorder arrêté avec succès');
        } catch (error) {
            console.error('Erreur lors de l\'arrêt du MediaRecorder:', error);
        }
        
        // NOUVEAU : Nettoyer les timers d'encouragement spécifiques
        if (audioContainer._encouragementTimers) {
            audioContainer._encouragementTimers.forEach((timer, index) => {
                clearTimeout(timer);
                console.log(`Timer d'encouragement ${index} nettoyé`);
            });
            audioContainer._encouragementTimers = null;
            console.log('Tous les timers d\'encouragement supprimés');
        }
        
        // Nettoyer les autres timers
        if (recordingTimer) {
            clearInterval(recordingTimer);
            recordingTimer = null;
            console.log('Recording timer nettoyé');
        }
        
        if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
            console.log('Silence timer nettoyé');
        }
        
        // Arrêter l'analyse audio
        if (audioContext && audioContext.state !== 'closed') {
            audioContext.close().catch(err => 
                console.warn('Erreur fermeture audioContext:', err)
            );
            audioContext = null;
            analyser = null;
            dataArray = null;
            console.log('AudioContext fermé');
        }
        
        // Nettoyer le stream audio
        if (audioStream) {
            audioStream.getTracks().forEach(track => {
                track.stop();
                console.log('Track audio arrêté:', track.kind);
            });
            audioStream = null;
        }
        
        // Masquer immédiatement toutes les bulles d'encouragement
        const bubble = audioContainer.querySelector('.encouragement-bubble');
        if (bubble) {
            bubble.classList.remove('show');
            bubble.style.display = 'none';
            console.log('Bulle d\'encouragement masquée');
        }
        
        // NOUVEAU : Réinitialiser le message dynamique
        const dynamicMessage = audioContainer.querySelector('.dynamic-message');
        if (dynamicMessage) {
            dynamicMessage.textContent = "Enregistrement terminé";
            console.log('Message dynamique réinitialisé');
        }
        
        // Mettre à jour l'interface utilisateur
        const micButton = audioContainer.querySelector('.enhanced-mic-button');
        if (micButton) {
            // Changer l'icône et retirer la classe recording
            micButton.classList.remove('recording');
            micButton.classList.add('completed');
            // Icône check stylée pour terminé
            micButton.innerHTML = `
                <div class="check-icon" style="
                    font-size: 32px;
                    color: white;
                    animation: checkBounce 0.6s ease-out;
                    filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.4));
                ">✓</div>
            `;
            console.log('Interface bouton micro mise à jour');
        }
        
        // Masquer le timer d'enregistrement
        const timer = audioContainer.querySelector('.enhanced-timer');
        if (timer) {
            timer.style.display = 'none';
            console.log('Timer masqué');
        }
        
        // Masquer le halo de feedback vocal
        const halo = audioContainer.querySelector('.voice-feedback-halo');
        if (halo) {
            halo.style.display = 'none';
            halo.style.opacity = '0';
            halo.style.transform = 'translate(-50%, -50%) scale(1)';
            console.log('Halo de feedback masqué');
        }
        
        // Mettre à jour les messages de statut
        const recordingMsg = audioContainer.querySelector('.status-message.recording');
        const readyMsg = audioContainer.querySelector('.status-message.ready');
        const completedMsg = audioContainer.querySelector('.status-message.completed');
        
        if (recordingMsg) recordingMsg.style.display = 'none';
        if (readyMsg) readyMsg.style.display = 'none';
        if (completedMsg) completedMsg.style.display = 'block';
        
        console.log('Messages de statut mis à jour');
        
        // Réinitialiser la jauge circulaire de progression
        const progressRing = audioContainer.querySelector('.progress-ring-bar');
        if (progressRing) {
            progressRing.style.strokeDashoffset = '439.8';
            progressRing.classList.remove('voice-active');
            console.log('Jauge circulaire réinitialisée');
        }
        
        // Masquer le bouton "Je préfère écrire" qui n'est visible que pendant l'enregistrement
        const switchToTextBtn = audioContainer.querySelector('.switch-to-text-btn');
        if (switchToTextBtn) {
            switchToTextBtn.style.display = 'none';
        }
        
        // Afficher les contrôles post-enregistrement
        const postRecordingControls = audioContainer.querySelector('.post-recording-controls');
        if (postRecordingControls) {
            postRecordingControls.style.display = 'block';
            console.log('Contrôles post-enregistrement affichés');
        }
        
        // Réinitialiser les variables de détection de silence
        lastVolumeCheck = 0;
        
        // Nettoyer les animations en cours
        if (animationFrame) {
            cancelAnimationFrame(animationFrame);
            animationFrame = null;
        }
        
        console.log('Enregistrement arrêté avec succès pour question:', questionId);
        console.log('État final - isRecording:', isRecording);
        
    } else {
        console.warn('Aucun enregistrement en cours à arrêter');
        console.warn('mediaRecorder:', !!mediaRecorder);
        console.warn('isRecording:', isRecording);
        
        // Même si pas d'enregistrement en cours, s'assurer que l'interface est propre
        isRecording = false;
        if (currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId].isRecording = false;
        }
        
        // NOUVEAU : Nettoyer les timers d'encouragement même sans enregistrement
        if (audioContainer._encouragementTimers) {
            audioContainer._encouragementTimers.forEach(timer => clearTimeout(timer));
            audioContainer._encouragementTimers = null;
            console.log('Timers d\'encouragement nettoyés (mode fallback)');
        }
        
        // Nettoyer les timers quand même
        if (recordingTimer) {
            clearInterval(recordingTimer);
            recordingTimer = null;
        }
        
        if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
        }
        
        // Masquer les éléments d'interface
        const bubble = audioContainer.querySelector('.encouragement-bubble');
        if (bubble) {
            bubble.classList.remove('show');
            bubble.style.display = 'none';
        }
        
        const timer = audioContainer.querySelector('.enhanced-timer');
        if (timer) {
            timer.style.display = 'none';
        }
        
        const halo = audioContainer.querySelector('.voice-feedback-halo');
        if (halo) {
            halo.style.display = 'none';
        }
        
        // NOUVEAU : Réinitialiser le message dynamique même en fallback
        const dynamicMessage = audioContainer.querySelector('.dynamic-message');
        if (dynamicMessage) {
            dynamicMessage.textContent = "Prêt pour un nouvel enregistrement";
            console.log('Message dynamique réinitialisé (mode fallback)');
        }
        
        console.log('Nettoyage d\'interface effectué même sans enregistrement actif');
    }
    
    console.log('=== FIN stopEnhancedRecording ===');
}


// ===== 10. NOUVELLE FONCTION - Fin d'enregistrement =====
function handleRecordingComplete(audioContainer, questionId) {
    console.log('Traitement fin d\'enregistrement pour question:', questionId);
    
    // CORRECTION SAFARI : Gérer les différents types MIME
    let mimeType = 'audio/webm';
    if (isSafari()) {
        mimeType = 'audio/mp4'; // Safari génère souvent du MP4
    }
    
    // Créer le blob audio avec le bon type MIME
    audioBlob = new Blob(audioChunks, { type: mimeType });
    audioURL = URL.createObjectURL(audioBlob);
    
    // Calculer la durée
    const duration = Math.floor((Date.now() - recordingStartTime) / 1000);
    
    // Sauvegarder l'état
    currentQuestionAudioState[questionId].audioBlob = audioBlob;
    currentQuestionAudioState[questionId].audioURL = audioURL;
    currentQuestionAudioState[questionId].duration = duration;
    
    // Configurer l'élément audio AVEC gestion Safari
    const audioElement = audioContainer.querySelector('.audio-element');
    if (audioElement) {
        audioElement.src = audioURL;
        
        // CORRECTION SAFARI : Forcer le chargement
        audioElement.load();
        
        // Safari a parfois besoin d'un délai
        if (isSafari()) {
            setTimeout(() => {
                audioElement.load();
            }, 100);
        }
    }
    
    // Mettre à jour l'interface
    updateRecordingUI(audioContainer, 'completed');
    
    // Sauvegarder dans le stockage global pour envoi final
    if (!window.tempQuizAudios) {
        window.tempQuizAudios = {};
    }
    
    const audioId = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    window.tempQuizAudios[audioId] = {
        blob: audioBlob,
        questionId: questionId,
        duration: duration,
        mimeType: mimeType // Ajouter le type MIME
    };
    
    console.log('Enregistrement traité avec succès, durée:', duration, 'secondes, type:', mimeType);
    scrollToNextButton();
}

// ===== 11. NOUVELLE FONCTION - Mise à jour UI =====
function updateRecordingUI(audioContainer, state) {
    const readyMsg = audioContainer.querySelector('.status-message.ready');
    const recordingMsg = audioContainer.querySelector('.status-message.recording');
    const completedMsg = audioContainer.querySelector('.status-message.completed');
    const micButton = audioContainer.querySelector('.enhanced-mic-button');
    const timer = audioContainer.querySelector('.enhanced-timer');
    const controls = audioContainer.querySelector('.post-recording-controls');
    const halo = audioContainer.querySelector('.voice-feedback-halo');

    console.log('=== updateRecordingUI ===');
    console.log('State:', state);
    console.log('MicButton found:', !!micButton);

    // Gestion du bouton "Je préfère écrire"
    const switchToTextBtn = audioContainer.querySelector('.switch-to-text-btn');
    if (switchToTextBtn) {
        switchToTextBtn.style.display = (state === 'recording') ? 'block' : 'none';
    }
    
    // Masquer tous les messages d'abord
    [readyMsg, recordingMsg, completedMsg].forEach(msg => {
        if (msg) msg.style.display = 'none';
    });
    
    switch (state) {
        case 'ready':
            if (readyMsg) {
                readyMsg.style.display = 'block';
                // S'assurer que le message personnalisé est affiché
                const questionId = getCurrentQuestionId();
                const personalizedMessage = QUESTION_INVITATION_MESSAGES[questionId] || QUESTION_INVITATION_MESSAGES['default'];
                readyMsg.textContent = personalizedMessage;
            }
            if (micButton) {
                micButton.classList.remove('recording', 'completed');
                micButton.classList.add('ready');
                micButton.innerHTML = '<div class="mic-icon">🎙️</div>';
            }
            if (timer) timer.style.display = 'none';
            if (controls) controls.style.display = 'none';
            if (halo) halo.style.display = 'none';
            break;
            
        case 'recording':
            const questionId = getCurrentQuestionId();
            if (recordingMsg) recordingMsg.style.display = 'block';
            if (micButton) {
                micButton.classList.remove('ready', 'completed');
                micButton.classList.add('recording');
                // Icône main stylée pour stop
                micButton.innerHTML = `
                    <div class="stop-hand-icon" style="
                        font-size: 28px;
                        animation: pulse 2s infinite;
                        filter: drop-shadow(0 0 8px rgba(255,255,255,0.5));
                    ">✋</div>
                `;
                
                // NOUVEAU : Configurer les event listeners pour le bouton STOP
                // Supprimer les anciens handlers
                micButton.removeEventListener('click', micButton.clickHandler);
                micButton.removeEventListener('touchend', micButton.touchHandler);
                
                // Handler unique pour STOP (même pattern que pour START)
                const handleStopClick = function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    console.log('=== CLIC BOUTON STOP ===');
                    console.log('Event type:', e.type);
                    
                    // Éviter le double déclenchement touch/click
                    if (e.type === 'touchend') {
                        this.touchHandled = true;
                        setTimeout(() => { this.touchHandled = false; }, 500);
                    } else if (e.type === 'click' && this.touchHandled) {
                        return;
                    }
                    
                    console.log('APPEL stopEnhancedRecording');
                    stopEnhancedRecording(audioContainer, questionId);
                    console.log('=== FIN CLIC STOP ===');
                };
                
                // Attacher les événements de façon simple (même pattern que pour START)
                micButton.clickHandler = handleStopClick;
                micButton.touchHandler = handleStopClick;
                
                micButton.addEventListener('click', handleStopClick);
                micButton.addEventListener('touchend', handleStopClick, { passive: false });
                
                console.log('Event listeners STOP attachés avec le même pattern que START');
            }
            if (timer) timer.style.display = 'block';
            if (controls) controls.style.display = 'none';
            if (halo) halo.style.display = 'block';
            break;
            
        case 'completed':
            if (completedMsg) completedMsg.style.display = 'block';
            if (micButton) {
                micButton.classList.remove('ready', 'recording');
                micButton.classList.add('completed');
                // Icône check stylée pour terminé
                micButton.innerHTML = `
                    <div class="check-icon" style="
                        font-size: 32px;
                        color: white;
                        animation: checkBounce 0.6s ease-out;
                        filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.4));
                    ">✓</div>
                `;
            }
            if (timer) timer.style.display = 'none';
            if (controls) controls.style.display = 'block';
            if (halo) halo.style.display = 'none';
            
            // Réinitialiser la jauge
            const progressRing = audioContainer.querySelector('.progress-ring-bar');
            if (progressRing) {
                progressRing.style.strokeDashoffset = '439.8';
            }
            break;
    }
}
// ===== 12. NOUVELLE FONCTION - Basculer vers mode texte =====
function switchToTextMode(audioContainer, textArea, charCount) {
    console.log('Basculement vers mode texte');
    
    // Arrêter l'enregistrement si en cours
    const questionId = getCurrentQuestionId();
    const questionState = currentQuestionAudioState[questionId];
    
    if (questionState && questionState.isRecording) {
        try {
            stopEnhancedRecording(audioContainer, questionId);
        } catch (error) {
            console.warn('Erreur lors de l\'arrêt d\'enregistrement:', error);
        }
    }
    
    // Arrêter aussi l'enregistrement global si actif
    if (typeof isRecording !== 'undefined' && isRecording) {
        try {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
            isRecording = false;
        } catch (error) {
            console.warn('Erreur lors de l\'arrêt de mediaRecorder:', error);
        }
    }
    
    // Masquer l'interface audio
    if (audioContainer) {
        audioContainer.style.display = 'none';
    }
    
    // Afficher l'interface texte
    if (textArea) {
        textArea.style.display = 'block';
        textArea.disabled = false; // S'assurer que le textarea est actif
        
        // Mettre un placeholder approprié
        if (!textArea.value.trim()) {
            textArea.placeholder = 'Partage tes idées ici...';
        }
    }
    
    if (charCount) {
        charCount.style.display = 'block';
    }
    
    // Focus sur le textarea avec un délai pour s'assurer que l'affichage est terminé
    setTimeout(() => {
        if (textArea && textArea.style.display !== 'none') {
            textArea.focus();
            console.log('Focus appliqué sur le textarea');
        }
    }, 150);
    
    // Ajouter un bouton retour vers audio (optionnel)
    const existingBackBtn = document.querySelector('.back-to-audio-btn');
    if (!existingBackBtn && textArea && textArea.parentNode) {
        const backBtn = document.createElement('button');
        backBtn.type = 'button';
        backBtn.className = 'back-to-audio-btn';
        backBtn.innerHTML = '🎙️ Finalement, je préfère parler';
        backBtn.style.cssText = `
            margin-top: 1rem;
            padding: 0.5rem 1rem;
            background: none;
            border: 1px solid #A11857;
            color: #A11857;
            border-radius: 8px;
            font-size: 0.85rem;
            cursor: pointer;
            opacity: 0.7;
            transition: all 0.3s ease;
        `;
        
        // Gestion des événements pour mobile et desktop
        const handleBackToAudio = function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // Éviter le double déclenchement touch/click
            if (e.type === 'touchend') {
                this.touchHandled = true;
                setTimeout(() => { this.touchHandled = false; }, 500);
            } else if (e.type === 'click' && this.touchHandled) {
                return;
            }
            
            if (audioContainer) audioContainer.style.display = 'block';
            if (textArea) {
                textArea.style.display = 'none';
                textArea.value = ''; // Vider le contenu
            }
            if (charCount) charCount.style.display = 'none';
            backBtn.remove();
            
            console.log('Retour vers mode audio');
        };
        
        backBtn.addEventListener('touchend', handleBackToAudio, { passive: false });
        backBtn.addEventListener('click', handleBackToAudio);
        
        // Effet hover
        backBtn.addEventListener('mouseenter', () => {
            backBtn.style.opacity = '1';
            backBtn.style.transform = 'translateY(-1px)';
        });
        
        backBtn.addEventListener('mouseleave', () => {
            backBtn.style.opacity = '0.7';
            backBtn.style.transform = 'translateY(0)';
        });
        
        textArea.parentNode.appendChild(backBtn);
    }
}

// ===== 13. FONCTION getFreeTextAnswer MODIFIÉE =====
function getFreeTextAnswer() {
    const textArea = document.querySelector('.free-text-input');
    const audioContainer = document.querySelector('.enhanced-audio-container');
    
    console.log('getFreeTextAnswer appelé:', {
        hasTextArea: !!textArea,
        hasAudioContainer: !!audioContainer,
        textAreaDisplay: textArea?.style.display,
        audioContainerDisplay: audioContainer?.style.display
    });
    
    // Cas spécial : Question 61 (salaire) - interface texte uniquement
    const salaryInput = document.querySelector('.salary-text-input');
    if (salaryInput) {
        console.log('Question salaire détectée');
        const salaryValue = salaryInput.value.replace(/\s/g, ''); // Retirer les espaces
        return [[salaryValue], salaryValue];
    }
    
    if (!textArea || !audioContainer) {
        console.error('Éléments manquants dans getFreeTextAnswer');
        return [[''], ''];
    }
    
    // Mode texte actif (textArea visible)
    if (textArea.style.display !== 'none' && textArea.value.trim()) {
        console.log('Mode texte actif avec contenu');
        const answerValue = [textArea.value.trim()];
        const answerText = textArea.value.trim();
        return [answerValue, answerText];
    }
    
    // Mode audio actif - vérifier qu'il y a un enregistrement
    const questionId = getCurrentQuestionId();
    const questionState = currentQuestionAudioState[questionId];
    
    console.log('Vérification audio pour question:', questionId, {
        hasQuestionState: !!questionState,
        hasAudioBlob: questionState?.audioBlob ? 'oui' : 'non',
        duration: questionState?.duration || 0
    });
    
    if (questionState && questionState.audioBlob) {
        console.log('Audio trouvé, traitement...');
        
        // CORRECTION : Utiliser l'ID existant plutôt que d'en créer un nouveau
        let existingAudioId = null;
        
        // D'abord, chercher si cet audio est déjà dans tempQuizAudios
        if (window.tempQuizAudios) {
            for (const [audioId, audioData] of Object.entries(window.tempQuizAudios)) {
                if (audioData.questionId === questionId) {
                    existingAudioId = audioId;
                    console.log('Audio ID existant trouvé:', existingAudioId);
                    break;
                }
            }
        }
        
        // Si pas d'ID existant, en créer un nouveau et sauvegarder
        if (!existingAudioId) {
            existingAudioId = `audio_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            console.log('Nouvel audio ID créé:', existingAudioId);
            
            // Initialiser tempQuizAudios si nécessaire
            if (!window.tempQuizAudios) {
                window.tempQuizAudios = {};
            }
            
            // Sauvegarder l'audio dans tempQuizAudios
            window.tempQuizAudios[existingAudioId] = {
                blob: questionState.audioBlob,
                url: questionState.audioURL,
                questionId: questionId,
                duration: questionState.duration || 0,
                timestamp: Date.now(),
                mimeType: questionState.audioBlob.type || 'audio/webm'
            };
            
            console.log('Audio sauvegardé dans tempQuizAudios');
        } else {
            // Mettre à jour les données si nécessaire
            const existingAudio = window.tempQuizAudios[existingAudioId];
            if (existingAudio.blob !== questionState.audioBlob) {
                console.log('Mise à jour de l\'audio existant');
                window.tempQuizAudios[existingAudioId] = {
                    ...existingAudio,
                    blob: questionState.audioBlob,
                    url: questionState.audioURL,
                    duration: questionState.duration || existingAudio.duration,
                    timestamp: Date.now()
                };
            }
        }
        
        // Retourner la référence à l'audio
        const answerValue = [`[AUDIO:${existingAudioId}]`];
        const answerText = `[Réponse audio enregistrée - ${questionState.duration || 0}s]`;
        
        return [answerValue, answerText];
    }
    
    // Fallback : aucune réponse
    console.log('Aucune réponse trouvée (ni texte ni audio)');
    return [[''], ''];
}

// Fonction pour supprimer un enregistrement audio
function deleteAudioRecording(audioContainer, voiceButton, textArea) {
    console.log('Suppression de l\'enregistrement audio');
    
    // Arrêter l'audio s'il est en cours de lecture
    const audioElement = audioContainer.querySelector('.audio-element');
    if (audioElement) {
        audioElement.pause();
        audioElement.src = '';
        audioElement.style.display = 'none';
        audioElement.load();
    }
    
    // Masquer les contrôles de lecture
    const playbackControls = audioContainer.querySelector('.audio-playback-controls');
    if (playbackControls) {
        playbackControls.style.display = 'none';
    }
    
    // Remettre le bouton d'enregistrement principal
    if (voiceButton) {
        voiceButton.innerHTML = `
            <div class="pulse-ring"></div>
           <div class="mic-design"></div>
        `;
        voiceButton.classList.remove('recording');
        voiceButton.style.display = 'block';
    }
    
    // Réinitialiser les états d'écoute
    const listenStateReady = audioContainer.querySelector('.listen-state .ready');
    const listenStateRecording = audioContainer.querySelector('.listen-state .recording');
    const listenStateRecorded = audioContainer.querySelector('.listen-state .recorded');
    
    if (listenStateRecording) listenStateRecording.style.display = 'none';
    if (listenStateRecorded) listenStateRecorded.style.display = 'none';
    if (listenStateReady) listenStateReady.style.display = 'block';
    
    // Réinitialiser le placeholder
    if (textArea) {
        textArea.placeholder = 'Ou alors, si tu préfères écrire, partage tes idées ici...';
        textArea.disabled = false;
    }
    
    // Nettoyer les URL et les blobs
    if (audioURL) {
        URL.revokeObjectURL(audioURL);
        audioURL = null;
    }
    audioBlob = null;
    audioChunks = [];
    
    console.log('Enregistrement audio supprimé');
}


// Fonction pour réinitialiser l'interface en cas d'erreur
function resetRecordingUI(button, audioContainer) {
    console.log('Réinitialisation de l\'interface d\'enregistrement');
    
    if (button) {
        button.innerHTML = `
            <div class="pulse-ring"></div>
            <div class="mic-design"></div>
        `;
        button.classList.remove('recording');
        button.style.display = 'block';
    }
    
    const listenStateReady = audioContainer.querySelector('.listen-state .ready');
    const listenStateRecording = audioContainer.querySelector('.listen-state .recording');
    const listenStateRecorded = audioContainer.querySelector('.listen-state .recorded');
    
    if (listenStateRecording) listenStateRecording.style.display = 'none';
    if (listenStateRecorded) listenStateRecorded.style.display = 'none';
    if (listenStateReady) listenStateReady.style.display = 'block';
    
    const playbackControls = audioContainer.querySelector('.audio-playback-controls');
    if (playbackControls) {
        playbackControls.style.display = 'none';
    }
    
    const timer = audioContainer.querySelector('.timer');
    if (timer) {
        timer.style.display = 'none';
    }
    
    const visualizer = audioContainer.querySelector('.audio-wave');
    if (visualizer) {
        visualizer.style.display = 'none';
    }
    
    isRecording = false;
    
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }
}

// Fonction pour mettre à jour le timer d'enregistrement
function updateRecordingTimer(timerContainer) {
    if (!recordingStartTime) return;
    
    const elapsedSeconds = Math.floor((Date.now() - recordingStartTime) / 1000);
    
    // Mettre à jour l'affichage du timer
    if (timerContainer) {
        const timeDisplay = formatRecordingTime(elapsedSeconds);
        const maxTimeDisplay = formatRecordingTime(MAX_RECORDING_TIME);
        
        timerContainer.innerHTML = `
            <span class="timer-elapsed">${timeDisplay}</span>
            <span class="timer-separator"> / </span>
            <span class="timer-max">${maxTimeDisplay}</span>
        `;
        
        // Changer la couleur selon le temps restant
        const remainingSeconds = MAX_RECORDING_TIME - elapsedSeconds;
        timerContainer.classList.remove('timer-warning', 'timer-warning-critical', 'timer-pulse');
        
        if (remainingSeconds <= 30) { // 30 dernières secondes
            timerContainer.classList.add('timer-warning-critical', 'timer-pulse');
        } else if (remainingSeconds <= 60) { // Dernière minute
            timerContainer.classList.add('timer-warning');
        }
    }
    
    // Mettre à jour les alertes visuelles sur le bouton
    const recordingButton = document.querySelector('.listen-button.recording');
    if (recordingButton) {
        updateButtonVisualAlerts(recordingButton, elapsedSeconds);
        
        // Mettre à jour l'overlay de temps si présent
        const overlay = recordingButton.querySelector('.recording-time-overlay');
        if (overlay) {
            updateTimeOverlay(overlay, elapsedSeconds);
        }
    }
    
    // Arrêter automatiquement l'enregistrement si le temps maximum est atteint
    if (elapsedSeconds >= MAX_RECORDING_TIME && isRecording) {
        if (recordingButton) {
            recordingButton.click();
        }
        showRecordingTimeoutMessage();
    }
}

// Fonction pour formater le temps d'enregistrement (MM:SS)
function formatRecordingTime(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`;
}


// Fonction d'initialisation du quiz homepage CORRIGÉE
async function initializeHomepageQuiz() {
    log("=== INITIALISATION QUIZ HOMEPAGE ===");
    
    // Vérifier si le lead a déjà complété le quiz
    const existingLead = localStorage.getItem('tilto_lead_completed');
    if (existingLead) {
        try {
            const leadData = JSON.parse(existingLead);
            const daysSinceCompletion = (Date.now() - leadData.timestamp) / (1000 * 60 * 60 * 24);
            
            if (daysSinceCompletion < 30 && leadData.hasCompletedQuiz) {
                log("Lead déjà inscrit, affichage écran de retour");
                showReturningUserScreen(leadData);
                return;
            }
        } catch (e) {
            localStorage.removeItem('tilto_lead_completed');
        }
    }
    
// NOUVEAU : Tenter de restaurer l'état sauvegardé
const savedState = await QuizPersistence.restoreQuizState();

if (savedState && Object.keys(savedState.answers || {}).length > 0) {
    // L'utilisateur reprend où il s'était arrêté
    log("Quiz restauré depuis la session précédente");
    isHomepageMode = true;
    
    try {
        // Charger les questions
        await loadHomepageQuestions();
        
        // CORRECTION : Avancer à la question SUIVANTE non répondue
        const chapters = QUIZ_CHAPTERS['pack_clarte']?.chapters || [];
        const currentChapterData = chapters[currentChapter];
        
        if (currentChapterData) {
            // Vérifier si la question actuelle a déjà une réponse
            const currentQuestionId = currentChapterData.questions[currentChapterQuestionIndex];
            
            if (homepageQuizAnswers[currentQuestionId]) {
                // La question actuelle est déjà répondue, passer à la suivante
                currentChapterQuestionIndex++;
                
                // Si on a fini le chapitre, passer au suivant ou à la transition
                if (currentChapterQuestionIndex >= currentChapterData.questions.length) {
                    if (currentChapter < chapters.length - 1 && currentChapterData.transition) {
                        isShowingTransition = true;
                    } else if (currentChapter < chapters.length - 1) {
                        currentChapter++;
                        currentChapterQuestionIndex = 0;
                        isShowingTransition = false;
                    }
                }
            }
        }
        
        // Masquer l'écran d'accueil, afficher le quiz
        const quizWelcome = document.getElementById('quizWelcome');
        const quizContent = document.getElementById('quizContent');
        const quizComplete = document.getElementById('quizComplete');
        
        if (quizWelcome) quizWelcome.style.display = 'none';
        if (quizContent) quizContent.style.display = 'block';
        if (quizComplete) quizComplete.style.display = 'none';
        
        // Afficher la prochaine question non répondue
        await showHomepageQuestion();
        
        return;
    } catch (error) {
        console.error('Erreur restauration quiz, redémarrage:', error);
        QuizPersistence.clearQuizState();
        // Continue avec l'initialisation normale ci-dessous
    }
}
    
    // RÉINITIALISATION COMPLÈTE si pas de sauvegarde
    isHomepageMode = true;
    homepageQuizAnswers = {};
    homepageQuestionHistory = [];
    homepageCurrentQuestionIndex = 0;
    
    // RÉINITIALISER L'ÉTAT DES CHAPITRES
    currentChapter = 0;
    currentChapterQuestionIndex = 0;
    isShowingTransition = false;
    
    // RÉINITIALISER L'ÉTAT introSeen DE TOUS LES CHAPITRES
    if (QUIZ_CHAPTERS['pack_clarte'] && QUIZ_CHAPTERS['pack_clarte'].chapters) {
        QUIZ_CHAPTERS['pack_clarte'].chapters.forEach(chapter => {
            chapter.introSeen = false;
        });
    }
    
    try {
        // Charger les questions sans authentification
        await loadHomepageQuestions();
        
        console.log('Questions chargées pour homepage:', {
            count: homepageAllQuestions.length,
            firstQuestion: homepageAllQuestions[0]?.id,
            startIndex: homepageCurrentQuestionIndex
        });
        
        // CORRECTION : Masquer tout d'abord tous les écrans
        const quizWelcome = document.getElementById('quizWelcome');
        const quizContent = document.getElementById('quizContent');
        const quizComplete = document.getElementById('quizComplete');
        
        if (quizContent) quizContent.style.display = 'none';
        if (quizComplete) quizComplete.style.display = 'none';
        
        // CORRECTION : Afficher l'écran d'accueil en dernier
        if (quizWelcome) {
            quizWelcome.style.display = 'flex';
            console.log('Écran d\'accueil affiché');
        } else {
            console.error('Élément quizWelcome non trouvé');
        }
        
        // Configurer le bouton de démarrage
        setupWelcomeButton();
        
    } catch (error) {
        log("Erreur d'initialisation homepage:", error);
        console.error("Erreur d'initialisation:", error);
        alert("Une erreur est survenue lors du chargement du quiz: " + error.message);
    }
}

// 6. MODIFICATION d'appendFreeTextInput - correction de getCurrentQuestionId
function appendFreeTextInput(questionDiv, maxCharacterInput) {
    const maxLength = Math.min(maxCharacterInput || MAX_TEXT_LENGTH, MAX_TEXT_LENGTH);
    
    let questionId = questionDiv.id.replace('question-', '');
    if (!questionId) {
        questionId = `question_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
    
    // MODIFICATION: Vérifier si c'est la question 61 (salaire)
    const isSalaryQuestion = questionId === '61';
    
    // Créer le conteneur principal
    const inputContainer = document.createElement('div');
    inputContainer.className = 'free-text-input-container';
    
    if (isSalaryQuestion) {
        // QUESTION 61: Interface texte uniquement pour le salaire
        console.log('Question 61 détectée - Mode texte simple pour salaire');
        
        // Créer le textarea standard avec styles de box
        const textArea = document.createElement('textarea');
        textArea.className = 'free-text-input salary-text-input';
        textArea.maxLength = 20; // Limité à 20 caractères
        textArea.placeholder = 'Exemple: 2000';
        textArea.rows = 1;
        textArea.style.resize = 'none';
        textArea.style.overflow = 'hidden';
        
        // Compteur de caractères
        const charCount = document.createElement('div');
        charCount.className = 'char-count';
        charCount.innerHTML = `<span class="char-count-text">0 / 20</span>`;
        
        // Auto-resize et validation
        textArea.addEventListener('input', function(e) {
            let value = e.target.value;
            
            // Permettre seulement les chiffres et espaces
            value = value.replace(/[^\d\s]/g, '');
            
            // Limiter à 20 caractères
            if (value.length > 20) {
                value = value.slice(0, 20);
            }
            
            e.target.value = value;
            updateCharCount(e.target, charCount, 20);
            
            // Auto-resize
            e.target.style.height = 'auto';
            e.target.style.height = Math.max(e.target.scrollHeight, 50) + 'px';
        });
        
        // Validation au keypress
        textArea.addEventListener('keypress', function(e) {
            const char = String.fromCharCode(e.which);
            if (!/[0-9\s]/.test(char) && e.which !== 8 && e.which !== 0 && e.which !== 13) {
                e.preventDefault();
            }
        });
        
        // Empêcher les sauts de ligne
        textArea.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
            }
        });
        
        // Assembler pour question salaire
        inputContainer.appendChild(textArea);
        inputContainer.appendChild(charCount);
        
    } else {
        // AUTRES QUESTIONS: Interface audio/texte normale - TEMPLATE CORRIGÉ
        
        // Créer le conteneur audio AMÉLIORÉ (mode par défaut)
        const audioContainer = document.createElement('div');
        audioContainer.className = 'enhanced-audio-container';
        audioContainer.innerHTML = `
        <!-- Conteneur principal du micro -->
        <div class="mic-central-container">
            <!-- Jauge circulaire -->
            <div class="circular-progress">
                <svg class="progress-ring" viewBox="0 0 160 160">
                    <circle class="progress-ring-background" cx="80" cy="80" r="70" 
                            fill="none" stroke="#e5e7eb" stroke-width="6"/>
                    <circle class="progress-ring-bar" cx="80" cy="80" r="70" 
                            fill="none" stroke="url(#progressGradient)" stroke-width="6"
                            stroke-linecap="round" transform="rotate(-90 80 80)"
                            stroke-dasharray="439.8" stroke-dashoffset="439.8"/>
                    <defs>
                        <linearGradient id="progressGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" style="stop-color:#10b981" />
                            <stop offset="60%" style="stop-color:#10b981" />
                            <stop offset="75%" style="stop-color:#f59e0b" />
                            <stop offset="90%" style="stop-color:#f97316" />
                            <stop offset="100%" style="stop-color:#ef4444" />
                        </linearGradient>
                    </defs>
                </svg>
                    
                    <!-- Feedback vocal (halo pulsant) -->
                    <div class="voice-feedback-halo"></div>
                    
                    <!-- Bouton micro central -->
                    <button type="button" class="enhanced-mic-button">
                        <div class="mic-icon">🎙️</div>
                    </button>
                </div>
                
                <!-- États et messages -->
                <div class="audio-status-container">
                    <div class="status-message ready" data-question-id="${questionId}"></div>
                    <div class="status-message recording" style="display: none;">
                    <div class="recording-indicator">
                        <div class="red-dot"></div>
                        <span class="static-message">Enregistrement en cours...</span>
                    </div>
                </div>
                    <div class="status-message completed" style="display: none;">Merci pour ce partage</div>
                </div>
                
                <!-- Timer discret -->
                <div class="enhanced-timer" style="display: none;">
                    <span class="timer-display">0:00</span>
                    <span class="timer-hint"><span style="margin-right:0.3em">/</span>2 min max</span>
                </div>
                
                <!-- Messages d'encouragement -->
                <div class="encouragement-bubble" style="display: none;">
                    <div class="bubble-content"></div>
                </div>
                
                <!-- Contrôles après enregistrement -->
                <div class="post-recording-controls" style="display: none;">
                    <div class="control-buttons">
                        <button type="button" class="control-btn listen-btn">
                            <span class="btn-icon">🔊</span>
                            <span class="btn-text">Écouter</span>
                        </button>
                        <button type="button" class="control-btn rerecord-btn">
                            <span class="btn-icon">🔄</span>
                            <span class="btn-text">Réenregistrer</span>
                        </button>
                    </div>
                </div>
                
                <!-- Audio element caché -->
                <audio class="audio-element" style="display: none;"></audio>
            </div>
            
            <!-- Lien plan B discret -->
            <div class="text-fallback">
                <button type="button" class="switch-to-text-btn">✍️ Je préfère écrire</button>
            </div>
        `;
        
        // Créer le textarea (masqué par défaut)
        const textArea = document.createElement('textarea');
        textArea.className = 'free-text-input';
        textArea.maxLength = maxLength;
        textArea.placeholder = 'Partage tes idées ici...';
        textArea.style.display = 'none';
        
        // Compteur de caractères (masqué par défaut)
        const charCount = document.createElement('div');
        charCount.className = 'char-count';
        charCount.innerHTML = `<span class="char-count-text">0 / ${maxLength}</span>`;
        charCount.style.display = 'none';
        
        // Assembler les éléments
        inputContainer.appendChild(audioContainer);
        inputContainer.appendChild(textArea);
        inputContainer.appendChild(charCount);

        // Configurer le message personnalisé pour cette question
        setTimeout(() => {
            const readyMessage = audioContainer.querySelector('.status-message.ready');
            if (readyMessage) {
                const personalizedMessage = QUESTION_INVITATION_MESSAGES[questionId] || QUESTION_INVITATION_MESSAGES['default'];
                readyMessage.textContent = personalizedMessage;
            }
        }, 50);

        // Initialiser l'état pour cette question
        if (!currentQuestionAudioState[questionId]) {
            currentQuestionAudioState[questionId] = {
                audioBlob: null,
                audioURL: null,
                isRecording: false,
                duration: 0
            };
        }
        
        // Configurer les événements
        setTimeout(() => {
            setupEnhancedAudioEvents(audioContainer, textArea, charCount, questionId, maxLength);
            
            // NOUVEAU : Configurer le message dynamique d'enregistrement
            setupStaticRecordingMessage(audioContainer, questionId);
        }, 100);
        
        // Configurer les événements textarea immédiatement pour éviter les problèmes
        textArea.addEventListener('input', () => {
            updateCharCount(textArea, charCount, maxLength);
        });
    }
    
    questionDiv.appendChild(inputContainer);
}


function setupStaticRecordingMessage(audioContainer, questionId) {
    console.log('Configuration du message statique pour question:', questionId);
    
    const staticMessage = audioContainer.querySelector('.static-message');
    if (!staticMessage) {
        console.warn('Élément static-message non trouvé');
        return;
    }
    
    // Message statique qui reste fixe pendant l'enregistrement
    const fixedMessage = STATIC_RECORDING_MESSAGES[questionId] || STATIC_RECORDING_MESSAGES['default'];
    
    // Définir le message fixe une seule fois
    staticMessage.textContent = fixedMessage;
    
    console.log(`Message statique défini: "${fixedMessage}"`);
}


// Modification de la fonction validateFreeTextAnswer pour gérer la question 61
function validateFreeTextAnswer(maxCharacterInput) {
    const textArea = document.querySelector('.free-text-input');
    const audioContainer = document.querySelector('.enhanced-audio-container');
    
    // Si c'est la question salaire (question 61)
    const salaryInput = document.querySelector('.salary-text-input');
    if (salaryInput) {
        const salaryValue = salaryInput.value.replace(/\s/g, ''); // Retirer les espaces pour validation
        
        if (!salaryValue.trim()) {
            showError('emptySalaryError');
            salaryInput.focus();
            return false;
        }
        
        // Vérifier que c'est un nombre valide
        if (!/^\d+$/.test(salaryValue)) {
            showError('invalidSalaryError');
            salaryInput.focus();
            return false;
        }
        
        // Vérifier les limites raisonnables (optionnel)
        const numValue = parseInt(salaryValue);
        if (numValue < 1000) {
            showError('tooLowSalaryError');
            salaryInput.focus();
            return false;
        }
        
        if (numValue > 999999) {
            showError('tooHighSalaryError');
            salaryInput.focus();
            return false;
        }
        
        return true;
    }
    
    // Code existant pour les autres questions...
    if (!textArea || !audioContainer) {
        showError('erreurTechnique');
        return false;
    }
    
    // Mode texte actif
    if (textArea.style.display !== 'none') {
        const answerText = textArea.value.trim();
        if (answerText === '') {
            showError('emptyTextAreaError');
            return false;
        }
        if (answerText.length < MIN_TEXT_LENGTH) {
            showError('shortTextAreaError', { min: MIN_TEXT_LENGTH });
            textArea.focus();
            return false;
        }
        const maxLength = Math.min(maxCharacterInput || MAX_TEXT_LENGTH, MAX_TEXT_LENGTH);
        if (answerText.length > maxLength) {
            showError('longTextAreaError', { max: maxLength });
            return false;
        }
        return true;
    }
    
    // Mode audio - vérifier qu'il y a un enregistrement
    const questionId = getCurrentQuestionId();
    const questionState = currentQuestionAudioState[questionId];
    
    if (!questionState || !questionState.audioBlob) {
        showError('noAudioRecordingError');
        return false;
    }
    
    // Vérifier la durée minimale (plus souple)
    if (questionState.duration < MIN_RECORDING_TIME) {
        showError('shortAudioError', { min: MIN_RECORDING_TIME, current: questionState.duration });
        return false;
    }
    
    return true;
}

// Ajout des messages d'erreur spécifiques au salaire dans la fonction showError
function showError(errorType, params = {}) {
    const errorElement = document.querySelector('.choices-error');
    if (errorElement) {
        let errorMessage;
        
        // Nouveaux messages d'erreur pour le salaire
        if (errorType === 'emptySalaryError') {
            errorMessage = 'Merci d\'indiquer le salaire souhaité';
        } else if (errorType === 'invalidSalaryError') {
            errorMessage = 'Veuillez saisir uniquement des chiffres';
        } else if (errorType === 'tooLowSalaryError') {
            errorMessage = 'Le salaire semble un peu faible. Vérifiez votre saisie.';
        } else if (errorType === 'tooHighSalaryError') {
            errorMessage = 'Le salaire semble très élevé. Vérifiez votre saisie.';
        } 
        // Erreurs audio existantes
        else if (errorType === 'noAudioRecordingError') {
            errorMessage = 'Veuillez enregistrer votre réponse ou choisir le mode texte.';
        } else if (errorType === 'shortAudioError') {
            errorMessage = `Votre enregistrement de ${params.current} secondes est trop court. Minimum requis : ${params.min} secondes. Veuillez réenregistrer.`;
        } else if (errorType === 'erreurTechnique') {
            errorMessage = 'Une erreur technique est survenue. Veuillez réessayer.';
        } else {
            // Erreurs existantes
            errorMessage = getTranslation(errorType, params);
        }
        
        console.log("Affichage de l'erreur :", errorMessage);
        errorElement.textContent = errorMessage;
        errorElement.style.display = 'block';
        errorElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function showHomepageCompletion() {
    const quizContent = getElement('#quizContent');
    if (quizContent) {
        quizContent.style.display = 'none';
    }
    
    const quizComplete = document.getElementById('quizComplete');
    if (quizComplete) {
        quizComplete.style.display = 'block';
        setupQuizLeadForm(); // Appeler après affichage
    }
}



function appendQuestionHint(questionDiv, question) {
    if (!question.hint || question.hint.trim() === '') {
        return;
    }
    
    // Fonction pour formater le texte avec retours à la ligne
    function formatHintText(text) {
        return text
            .replace(/\s*[-–]\s*/g, '<br>• ')
            .replace(/\s*(💡|👉|🎯|✨|⚡|🔍|📝|🌟|💪|🚀|📊|⭐)\s*/g, '<br>$1 ')
            .replace(/^<br>/, '');
    }
    
    const hintDiv = document.createElement('div');
    hintDiv.className = 'question-hint-toggle';
    
    const formattedHint = formatHintText(question.hint);
    
    hintDiv.innerHTML = `
        <div class="hint-trigger" data-hint-id="hint-${question.id}">
            <span class="hint-icon">💡</span>
        </div>
        <div class="hint-popup" id="hint-${question.id}">
            <div class="hint-popup-content">
                <div class="hint-popup-text">${formattedHint}</div>
            </div>
        </div>
    `;
    
    // Positionner discrètement à côté du titre
    const questionTitle = questionDiv.querySelector('.question-title');
    if (questionTitle) {
        questionTitle.style.display = 'flex';
        questionTitle.style.justifyContent = 'center';
        questionTitle.style.alignItems = 'center';
        questionTitle.style.position = 'relative';
        const questionTextSpan = questionTitle.querySelector('.question-text');
    if (questionTextSpan) {
        questionTextSpan.style.paddingRight = '2rem';
    }
        hintDiv.style.position = 'absolute';
        hintDiv.style.right = '0';
        questionTitle.appendChild(hintDiv);
    }
    
    // Gestion des événements
    const trigger = hintDiv.querySelector('.hint-trigger');
    const popup = hintDiv.querySelector('.hint-popup');
    let isPopupVisible = false;
    
    trigger.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        isPopupVisible = !isPopupVisible;
        popup.style.display = isPopupVisible ? 'block' : 'none';
        trigger.classList.toggle('active', isPopupVisible);
    });
    
    // Fermer au clic ailleurs
    document.addEventListener('click', (e) => {
        if (!hintDiv.contains(e.target) && isPopupVisible) {
            popup.style.display = 'none';
            trigger.classList.remove('active');
            isPopupVisible = false;
        }
    });
}


// Fonction pour afficher un message quand la limite de temps est atteinte
function showRecordingTimeoutMessage() {
    const message = document.createElement('div');
    message.className = 'recording-timeout-message';
    message.innerHTML = `
        <div class="timeout-content">
            <span class="timeout-icon">⏰</span>
            <span class="timeout-text">Enregistrement arrêté automatiquement après 5 minutes</span>
        </div>
    `;
    
    const audioContainer = document.querySelector('.audio-controls-container');
    if (audioContainer) {
        audioContainer.appendChild(message);
        setTimeout(() => message.classList.add('show'), 10);
        setTimeout(() => {
            message.classList.remove('show');
            setTimeout(() => message.remove(), 300);
        }, 5000);
    }
}


// Fonction pour créer une barre de progression visuelle (optionnel)
function updateProgress() {
    const progressBar = document.getElementById('progress');
    const progressIndicator = document.getElementById('progress-indicator');
    
    if (!progressBar) return;
    
    let answeredQuestions = 0;
    let totalQuestions = 0;
    
    if (isHomepageMode && typeof homepageQuizAnswers !== 'undefined' && typeof homepageAllQuestions !== 'undefined') {
        answeredQuestions = Object.keys(homepageQuizAnswers).length;
        totalQuestions = homepageAllQuestions.length;
    } else if (typeof userAnswers !== 'undefined' && typeof allQuestions !== 'undefined') {
        answeredQuestions = Object.keys(userAnswers).length;
        totalQuestions = allQuestions.length;
    } else {
        return;
    }
    
    if (totalQuestions === 0) return;
    
    const progress = Math.round((answeredQuestions / totalQuestions) * 100);
    
    progressBar.style.width = progress + '%';
    
    if (progressIndicator) {
        progressIndicator.textContent = progress + '%';
    }
    
    // Animation simple à 100%
    if (progress === 100) {
        progressBar.classList.add('progress-complete');
    }
}


function adjustModalHeight() {
    if (window.innerWidth <= 768) {
        const modal = document.querySelector('.quiz-modal-content');
        if (modal) {
            // Utiliser la vraie hauteur du viewport (sans barre d'adresse sur mobile)
            const vh = window.innerHeight * 0.01;
            document.documentElement.style.setProperty('--vh', `${vh}px`);
            modal.style.height = `${window.innerHeight}px`;
        }
    }
}

// Appeler au redimensionnement et à l'orientation
window.addEventListener('resize', adjustModalHeight);
window.addEventListener('orientationchange', () => {
    setTimeout(adjustModalHeight, 100);
});

// Fonction pour mettre à jour la barre de progression
function updateProgressBar(progressContainer) {
    if (!recordingStartTime || !progressContainer) return;
    
    const elapsedSeconds = Math.floor((Date.now() - recordingStartTime) / 1000);
    const progressPercentage = (elapsedSeconds / MAX_RECORDING_TIME) * 100;
    
    const progressFill = progressContainer.querySelector('.recording-progress-fill');
    if (progressFill) {
        progressFill.style.width = `${Math.min(progressPercentage, 100)}%`;
        
        // Changer la couleur de la barre selon le temps restant
        const remainingSeconds = MAX_RECORDING_TIME - elapsedSeconds;
        
        if (remainingSeconds <= 60) {
            progressFill.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
        } else if (remainingSeconds <= 120) {
            progressFill.style.background = 'linear-gradient(90deg, #f59e0b, #d97706)';
        } else {
            progressFill.style.background = 'linear-gradient(90deg, #10b981, #059669)';
        }
    }
}



// Fonction pour mettre à jour les alertes visuelles sur le bouton d'enregistrement
function updateButtonVisualAlerts(button, elapsedSeconds) {
    if (!button || !isRecording) return;
    
    const remainingSeconds = MAX_RECORDING_TIME - elapsedSeconds;
    
    // Retirer toutes les classes d'alerte existantes
    button.classList.remove('time-warning', 'time-critical');
    
    // Ajouter la classe appropriée selon le temps restant
    if (remainingSeconds <= 60) { // Dernière minute
        button.classList.add('time-critical');
    } else if (remainingSeconds <= 120) { // 2 dernières minutes
        button.classList.add('time-warning');
    }
}

// Fonction pour créer un overlay de temps sur le bouton
function createTimeOverlay(button) {
    let overlay = button.querySelector('.recording-time-overlay');
    
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'recording-time-overlay';
        button.style.position = 'relative';
        button.appendChild(overlay);
    }
    
    return overlay;
}

function updateTimeOverlay(overlay, elapsedSeconds) {
    if (!overlay) return;
    
    const remainingSeconds = MAX_RECORDING_TIME - elapsedSeconds;
    const remainingMinutes = Math.floor(remainingSeconds / 60);
    const remainingSecondsDisplay = remainingSeconds % 60;
    
    overlay.textContent = `${remainingMinutes}:${remainingSecondsDisplay.toString().padStart(2, '0')}`;
    
    // Retirer les classes d'état existantes
    overlay.classList.remove('warning', 'critical');
    
    // Ajouter la classe appropriée
    if (remainingSeconds <= 60) {
        overlay.classList.add('critical');
    } else if (remainingSeconds <= 120) {
        overlay.classList.add('warning');
    }
    
    // Masquer l'overlay si le temps est écoulé
    if (remainingSeconds <= 0) {
        overlay.style.display = 'none';
    }
}

// Fonction pour initialiser les alertes visuelles au début de l'enregistrement
function initializeRecordingAlerts(button, showOverlay = true) {
    // Créer l'overlay de temps si demandé
    if (showOverlay && button) {
        const overlay = createTimeOverlay(button);
        overlay.textContent = '5:00';
        overlay.style.display = 'block';
    }
}

// Fonction pour nettoyer les alertes visuelles à la fin de l'enregistrement
function cleanupRecordingAlerts(button) {
    if (!button) return;
    
    // Retirer toutes les classes d'alerte
    button.classList.remove('time-warning', 'time-critical');
    
    // Supprimer l'overlay si présent
    const overlay = button.querySelector('.recording-time-overlay');
    if (overlay) {
        overlay.remove();
    }
    
    // Supprimer les messages temporaires
    const audioContainer = button.closest('.audio-controls-container');
    if (audioContainer) {
        const messages = audioContainer.querySelectorAll('.recording-info-message, .recording-timeout-message');
        messages.forEach(message => message.remove());
        
        // Supprimer la barre de progression
        const progressContainer = audioContainer.querySelector('.recording-progress-container');
        if (progressContainer) {
            progressContainer.remove();
        }
    }
}

// FONCTION POUR METTRE À JOUR L'AFFICHAGE SELON L'ÉTAT
function updateAudioDisplayState(audioContainer, questionState) {
    const micButton = audioContainer.querySelector('.enhanced-mic-button');
    const postRecordingControls = audioContainer.querySelector('.post-recording-controls');
    const audioElement = audioContainer.querySelector('.audio-element');
    
    // Messages de statut
    const readyMsg = audioContainer.querySelector('.status-message.ready');
    const recordingMsg = audioContainer.querySelector('.status-message.recording');
    const completedMsg = audioContainer.querySelector('.status-message.completed');
    
    console.log('updateAudioDisplayState appelé avec:', questionState);
    
    // Masquer tous les messages d'abord
    [readyMsg, recordingMsg, completedMsg].forEach(msg => {
        if (msg) msg.style.display = 'none';
    });
    
    if (questionState.audioBlob && questionState.audioURL) {
        // Il y a un audio enregistré - ÉTAT COMPLET
        console.log('Affichage état: audio enregistré');
        
        if (micButton) {
            micButton.classList.remove('ready', 'recording');
            micButton.classList.add('completed');
            micButton.innerHTML = `
                <div class="check-icon" style="
                    font-size: 32px;
                    color: white;
                    animation: checkBounce 0.6s ease-out;
                    filter: drop-shadow(0 0 8px rgba(16, 185, 129, 0.4));
                ">✓</div>
            `;
            micButton.style.display = 'block';
        }
        
        if (postRecordingControls) {
            postRecordingControls.style.display = 'block';
        }
        
        if (audioElement && questionState.audioURL) {
            audioElement.src = questionState.audioURL;
            audioElement.load();
            audioElement.style.display = 'block';
        }
        
        if (completedMsg) completedMsg.style.display = 'block';
        
        // Vérifier la durée et afficher les boutons appropriés
        const continueBtn = audioContainer.querySelector('.continue-btn');
        const audioDuration = questionState.duration || 0;
        
        if (audioDuration < MIN_RECORDING_TIME && continueBtn) {
            continueBtn.style.display = 'inline-block';
        } else if (continueBtn) {
            continueBtn.style.display = 'none';
        }
        
    } else if (questionState.isRecording) {
        // Enregistrement en cours
        console.log('Affichage état: enregistrement en cours');
        
        if (micButton) {
            micButton.classList.remove('ready', 'completed');
            micButton.classList.add('recording');
        }
        if (recordingMsg) recordingMsg.style.display = 'block';
        if (postRecordingControls) postRecordingControls.style.display = 'none';
        
    } else {
        // État initial - pas d'audio
        console.log('Affichage état: prêt à enregistrer');
        
        if (micButton) {
            micButton.classList.remove('recording', 'completed');
            micButton.classList.add('ready');
            micButton.innerHTML = '<div class="mic-icon">🎙️</div>';
            micButton.style.display = 'block';
        }
        
        if (postRecordingControls) postRecordingControls.style.display = 'none';
        if (audioElement) audioElement.style.display = 'none';
        if (readyMsg) readyMsg.style.display = 'block';
    }
}

// Fonction pour supprimer l'audio d'une question spécifique
function deleteQuestionAudio(questionId, audioContainer, voiceButton, textArea) {
    console.log('Suppression audio pour question:', questionId);
    
    const questionState = currentQuestionAudioState[questionId];
    if (questionState) {
        // Nettoyer les ressources audio
        if (questionState.audioURL) {
            URL.revokeObjectURL(questionState.audioURL);
        }
        
        // Réinitialiser l'état de la question
        questionState.audioBlob = null;
        questionState.audioURL = null;
        questionState.isRecording = false;
        
        // Mettre à jour les variables globales si c'est la question courante
        if (getCurrentQuestionId() === questionId) {
            audioBlob = null;
            audioURL = null;
            isRecording = false;
            audioChunks = [];
        }
        
        // Restaurer le bouton AVEC l'icône micro
        if (voiceButton) {
            voiceButton.innerHTML = '<div class="mic-icon">🎙️</div>';
            voiceButton.classList.remove('recording');
            voiceButton.style.display = 'block';
        }
        
        // Masquer les contrôles de lecture
        const playbackControls = audioContainer.querySelector('.audio-playback-controls');
        if (playbackControls) {
            playbackControls.style.display = 'none';
        }
        
        // Masquer et nettoyer l'élément audio
        const audioElement = audioContainer.querySelector('.audio-element');
        if (audioElement) {
            audioElement.pause();
            audioElement.src = '';
            audioElement.style.display = 'none';
            audioElement.load();
        }
        
        // Mettre à jour les états d'écoute
        const listenStateReady = audioContainer.querySelector('.listen-state .ready');
        const listenStateRecording = audioContainer.querySelector('.listen-state .recording');
        const listenStateRecorded = audioContainer.querySelector('.listen-state .recorded');
        
        if (listenStateRecording) listenStateRecording.style.display = 'none';
        if (listenStateRecorded) listenStateRecorded.style.display = 'none';
        if (listenStateReady) listenStateReady.style.display = 'block';
        
        // Masquer le timer et le visualiseur
        const timer = audioContainer.querySelector('.timer');
        const visualizer = audioContainer.querySelector('.audio-wave');
        if (timer) timer.style.display = 'none';
        if (visualizer) visualizer.style.display = 'none';
        
        // Arrêter les animations des barres d'onde
        if (visualizer) {
            const waveBars = visualizer.querySelectorAll('.wave-bar');
            waveBars.forEach(bar => {
                bar.style.animationPlayState = 'paused';
            });
        }
        
        // Réinitialiser le placeholder du textarea
        if (textArea) {
            textArea.placeholder = 'Ou alors, si tu préfères écrire, partage tes idées ici...';
            textArea.disabled = false;
        }
        
        // Supprimer du stockage global si présent
        if (globalAudioStorage[questionId]) {
            delete globalAudioStorage[questionId];
        }
        
        // Supprimer du stockage temporaire pour homepage si présent
        if (window.tempQuizAudios) {
            Object.keys(window.tempQuizAudios).forEach(audioId => {
                if (window.tempQuizAudios[audioId].questionId === questionId) {
                    if (window.tempQuizAudios[audioId].url) {
                        URL.revokeObjectURL(window.tempQuizAudios[audioId].url);
                    }
                    delete window.tempQuizAudios[audioId];
                }
            });
        }
        
        // Arrêter le flux audio si actif
        if (audioStream) {
            audioStream.getTracks().forEach(track => track.stop());
            audioStream = null;
        }
        
        // Arrêter le timer d'enregistrement si actif
        if (recordingTimer) {
            clearInterval(recordingTimer);
            recordingTimer = null;
        }
        
        console.log('Audio supprimé avec succès pour question:', questionId);
    }
}


// Fonction pour créer une barre de progression visuelle
function createProgressBar(container) {
    const progressContainer = document.createElement('div');
    progressContainer.className = 'recording-progress-container';
    
    progressContainer.innerHTML = `
        <div class="recording-progress-bar">
            <div class="recording-progress-fill"></div>
        </div>
    `;
    
    container.appendChild(progressContainer);
    return progressContainer;
}

function showReturningUserScreen(leadData) {
    const quizWelcome = document.getElementById('quizWelcome');
    const quizContent = document.getElementById('quizContent');
    const quizComplete = document.getElementById('quizComplete');
    
    if (quizWelcome) quizWelcome.style.display = 'none';
    if (quizContent) quizContent.style.display = 'none';
    
    if (quizComplete) {
        quizComplete.style.display = 'block';
        showSuccessScreen(true, leadData);
    }
}

// 2. GARDER UNE SEULE VERSION de getCurrentChapter (supprimer les doublons)
function getCurrentChapter(quizId = 'pack_clarte') {
    const chapters = QUIZ_CHAPTERS[quizId]?.chapters || [];
    
    console.log('getCurrentChapter appelé:', {
        currentChapter: currentChapter,
        totalChapters: chapters.length,
        quizId: quizId
    });
    
    if (currentChapter >= 0 && currentChapter < chapters.length) {
        return chapters[currentChapter];
    }
    return null;
}


// 3. MODIFICATION de getCurrentQuestionInChapter - fonction complète
function getCurrentQuestionInChapter() {
    const chapter = getCurrentChapter('pack_clarte');
    if (!chapter || currentChapterQuestionIndex >= chapter.questions.length) {
        console.log('getCurrentQuestionInChapter: pas de question trouvée', {
            hasChapter: !!chapter,
            currentChapterQuestionIndex,
            totalQuestions: chapter?.questions?.length || 0
        });
        return null;
    }
    
    const questionId = chapter.questions[currentChapterQuestionIndex];
    console.log('getCurrentQuestionInChapter: recherche question', questionId);
    
    // Pour le mode homepage
    if (isHomepageMode && homepageAllQuestions) {
        const question = homepageAllQuestions.find(q => q.id == questionId);
        console.log('Question trouvée (homepage):', !!question);
        return question;
    }
    
    // Pour le mode normal
    if (allQuestions) {
        const question = allQuestions.find(q => q.id == questionId);
        console.log('Question trouvée (normal):', !!question);
        return question;
    }
    
    return null;
}


function showChapterTransition(chapter, quizId) {
    const quizForm = getElement('#quizForm');
    if (!quizForm) return;

    const nextChapter = currentChapter + 2; // +2 car on passe au suivant
    QuizTracking.trackChapterTransition(currentChapter + 1, nextChapter);

    quizForm.innerHTML = '';
    
    // ✅ Vérifier si on peut revenir en arrière
    const canGoBack = homepageQuestionHistory.length > 0 || 
                     currentChapter > 0 || 
                     currentChapterQuestionIndex > 0;
    
    const transitionDiv = document.createElement('div');
    transitionDiv.className = 'chapter-transition active';
    
    // ✅ Construction HTML conditionnelle
    let transitionHTML = `
        <div class="chapter-transition-container">
            <div class="chapter-transition-content">
                <div class="transition-icon">
                    ✨
                </div>
                
                <div class="transition-message">
                    ${chapter.transition}
                </div>
                
                <div class="chapter-transition-cta">
    `;
    
    // ✅ Ajouter le bouton précédent seulement si nécessaire
    if (canGoBack) {
        transitionHTML += `
                    <button class="prev-btn">
                        <span class="btn-text">${window.innerWidth <= 768 ? '' : 'Précédent'}</span>
                    </button>
        `;
    }
    
    transitionHTML += `
                    <button class="btn-continue-transition">
                        Continuer 🌟
                    </button>
                </div>
            </div>
            
            <div class="transition-navigation">
            </div>
        </div>
    `;
    
    transitionDiv.innerHTML = transitionHTML;
    quizForm.appendChild(transitionDiv);

    // ✅ Event listener pour le bouton précédent (si créé)
    if (canGoBack) {
        const prevBtn = transitionDiv.querySelector('.prev-btn');
        if (prevBtn) {
            prevBtn.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                if ('vibrate' in navigator && window.innerWidth <= 768) {
                    navigator.vibrate(50);
                }
                
                console.log('Bouton précédent transition cliqué');
                
                if (isHomepageMode) {
                    homepagePreviousQuestion();
                } else {
                    previousQuestion(quizId);
                }
            });
            
            console.log('Event listener précédent configuré pour transition');
        }
    }

    // Event listener pour continuer
    const continueBtn = transitionDiv.querySelector('.btn-continue-transition');
    if (continueBtn) {
        const clickHandler = function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            if ('vibrate' in navigator && window.innerWidth <= 768) {
                navigator.vibrate([50, 100]);
            }
            
            console.log('Bouton "Continuer" cliqué', {
                isHomepageMode: isHomepageMode,
                currentChapter: currentChapter,
                quizId: quizId
            });
            
            // Ajouter l'état de transition à l'historique AVANT de passer au chapitre suivant
            const transitionState = {
                chapter: currentChapter,
                questionIndex: currentChapterQuestionIndex,
                isTransition: true,
                hasIntro: false
            };
            homepageQuestionHistory.push(transitionState);
            
            // Passer au chapitre suivant
            currentChapter++;
            currentChapterQuestionIndex = 0;
            isShowingTransition = false;
            
            if (isHomepageMode || quizId === 'pack_clarte') {
                console.log('Transition vers chapitre suivant (homepage)');
                showHomepageQuestion();
            } else {
                console.log('Transition vers chapitre suivant (quiz normal)');
                showQuestion(quizId);
            }
        };
        
        // Ajouter les event listeners (mobile + desktop)
        continueBtn.addEventListener('touchend', clickHandler, { passive: false });
        continueBtn.addEventListener('click', clickHandler);
        
        console.log('Event listener ajouté au bouton "Continuer"');
    } else {
        console.error('Bouton "Continuer" non trouvé dans le DOM');
    }
}

function showChapterIntro(chapter, quizId) {
    const quizForm = getElement('#quizForm');
    if (!quizForm) {
        console.error('quizForm introuvable dans showChapterIntro');
        return;
    }

    console.log('Création intro chapitre:', chapter.title);
    QuizTracking.trackChapterIntro(currentChapter + 1, chapter.title);

    quizForm.innerHTML = '';
    
    const chapterIntroDiv = document.createElement('div');
    chapterIntroDiv.className = 'chapter-intro active';
    chapterIntroDiv.innerHTML = `
        <div class="chapter-intro-container">
            <div class="chapter-intro-content">
                <div class="chapter-badge">
                    Chapitre ${currentChapter + 1}
                </div>
                
                <h2 class="chapter-title">
                    ${chapter.title}
                </h2>
                
                <div class="chapter-intro-text">
                    <p class="intro-line">
                        ${chapter.intro}
                    </p>
                </div>
                
                <div class="chapter-intro-cta">
                    <button class="btn-start-chapter" type="button">
                        C'est parti ! 🚀
                    </button>
                </div>
            </div>
        </div>
    `;

    quizForm.appendChild(chapterIntroDiv);

    // CORRECTION PRINCIPALE : Gestionnaire d'événement avec logs détaillés
    const startBtn = chapterIntroDiv.querySelector('.btn-start-chapter');
    
    if (startBtn) {
        // Supprimer les anciens gestionnaires
        const newBtn = startBtn.cloneNode(true);
        startBtn.parentNode.replaceChild(newBtn, startBtn);
        
        const handleStart = function(e) {
            e.preventDefault();
            e.stopPropagation();
            
            console.log('=== CLIC DETECTE SUR C\'EST PARTI ===');
            console.log('Avant - currentChapter:', currentChapter);
            console.log('Avant - currentChapterQuestionIndex:', currentChapterQuestionIndex);
            console.log('Avant - chapter.introSeen:', chapter.introSeen);
            
            // MARQUER L'INTRO COMME VUE
            chapter.introSeen = true;
            
            // Ajouter l'état actuel à l'historique AVANT de passer à la première question
            const introState = {
                chapter: currentChapter,
                questionIndex: 0,
                isTransition: false,
                hasIntro: true,
                wasIntro: true,
                screenType: 'intro' // Type d'écran pour la navigation
            };
            homepageQuestionHistory.push(introState);
            
            // RESTER sur currentChapterQuestionIndex = 0 (première question)
            currentChapterQuestionIndex = 0;
            
            console.log('Après - chapter.introSeen:', chapter.introSeen);
            console.log('Après - currentChapterQuestionIndex:', currentChapterQuestionIndex);
            
            // Appeler la fonction appropriée avec logs
            if (isHomepageMode) {
                console.log('Appel de showHomepageQuestion()');
                showHomepageQuestion();
            } else {
                console.log('Appel de showQuestion()');
                showQuestion(quizId);
            }
        };
        
        // Ajouter les gestionnaires
        newBtn.addEventListener('touchend', handleStart, { passive: false });
        newBtn.addEventListener('click', handleStart);
        
        console.log('Event listener configuré avec succès');
    } else {
        console.error('Bouton C\'est parti introuvable !');
    }
}



function updateChapterProgress() {
    const progressContainer = document.querySelector('.progress-container');
    if (!progressContainer) return;

    const chapters = QUIZ_CHAPTERS[getQuizId()]?.chapters || [];
    if (chapters.length === 0) {
        // Fallback sur l'ancienne barre si pas de chapitres
        updateFallbackProgress();
        return;
    }

    // Créer la nouvelle structure HTML
    progressContainer.innerHTML = `
        <div class="chapter-progress-bar">
            ${chapters.map((chapter, index) => {
                let segmentClass = 'upcoming';
                if (index < currentChapter) segmentClass = 'completed';
                else if (index === currentChapter) segmentClass = 'current';
                
                return `<div class="chapter-segment ${segmentClass}" data-chapter="${index}"></div>`;
            }).join('')}
        </div>
        <div class="progress-text">
            ${getProgressText(chapters)}
        </div>
    `;



    // Calculer et appliquer la progression du chapitre actuel
    updateCurrentChapterProgress();
}

function getProgressText(chapters) {
    if (currentChapter >= chapters.length) {
        return 'Quiz terminé !';
    }
    
    const currentChapterData = chapters[currentChapter];
    const totalQuestionsInChapter = currentChapterData.questions.length;
    const currentQuestionInChapter = currentChapterQuestionIndex + 1;
    
    return `Chapitre ${currentChapter + 1} – Question ${currentQuestionInChapter} sur ${totalQuestionsInChapter}`;
}

function updateCurrentChapterProgress() {
    const currentSegment = document.querySelector('.chapter-segment.current');
    if (!currentSegment) return;

    const chapters = QUIZ_CHAPTERS[getQuizId()]?.chapters || [];
    if (currentChapter >= chapters.length) return;

    const currentChapterData = chapters[currentChapter];
    const totalQuestions = currentChapterData.questions.length;
    const progress = Math.min(((currentChapterQuestionIndex + 1) / totalQuestions) * 100, 100);

    // Appliquer la progression visuelle
    currentSegment.style.setProperty('--progress', `${progress}%`);
    
    // Animation fluide avec un léger délai
    requestAnimationFrame(() => {
        currentSegment.style.transition = 'all 0.6s ease-out';
    });
}

function updateFallbackProgress() {
    const progressContainer = document.querySelector('.progress-container');
    if (!progressContainer) return;
    
    // Créer une barre de progression simple pour les quiz sans chapitres
    const totalQuestions = isHomepageMode ? 
        (homepageAllQuestions ? homepageAllQuestions.length : 0) : 
        (allQuestions ? allQuestions.length : 0);
    
    const answeredQuestions = isHomepageMode ? 
        Object.keys(homepageQuizAnswers || {}).length : 
        Object.keys(userAnswers || {}).length;
    
    if (totalQuestions === 0) return;
    
    const progress = Math.round((answeredQuestions / totalQuestions) * 100);
    
    progressContainer.innerHTML = `
        <div class="chapter-progress-bar">
            <div class="chapter-segment current" style="--progress: ${progress}%"></div>
        </div>
        <div class="progress-text">
            Question ${answeredQuestions + 1} sur ${totalQuestions}
        </div>
    `;
}

function debugCurrentState() {
    console.log('=== DEBUG ETAT COMPLET ===');
    console.log('isHomepageMode:', isHomepageMode);
    console.log('currentChapter:', currentChapter);
    console.log('currentChapterQuestionIndex:', currentChapterQuestionIndex);
    console.log('isShowingTransition:', isShowingTransition);
    
    const chapter = getCurrentChapter('pack_clarte');
    console.log('Chapter actuel:', chapter);
    
    if (chapter) {
        console.log('Chapter.introSeen:', chapter.introSeen);
        console.log('Chapter.questions:', chapter.questions);
        
        if (currentChapterQuestionIndex < chapter.questions.length) {
            const expectedQuestionId = chapter.questions[currentChapterQuestionIndex];
            console.log('Question ID attendue:', expectedQuestionId);
            
            const question = getCurrentQuestionInChapter();
            console.log('Question trouvée:', !!question);
            if (question) {
                console.log('Question details:', {
                    id: question.id,
                    question: question.question?.substring(0, 50) + '...'
                });
            }
        }
    }
    
    console.log('homepageAllQuestions.length:', homepageAllQuestions?.length || 0);
    console.log('========================');
}

// 1. MODIFICATION de getCurrentQuestionId - version robuste
function getCurrentQuestionId() {
    console.log('getCurrentQuestionId appelé');
    
    // Mode homepage avec système de chapitres
    if (isHomepageMode && typeof homepageAllQuestions !== 'undefined' && homepageAllQuestions && homepageAllQuestions.length > 0) {
        const chapter = getCurrentChapter('pack_clarte');
        if (chapter && currentChapterQuestionIndex < chapter.questions.length) {
            const questionId = chapter.questions[currentChapterQuestionIndex];
            console.log('Question ID (homepage avec chapitres):', questionId);
            return questionId;
        }
        
        // Fallback sur l'ancien système
        if (homepageCurrentQuestionIndex < homepageAllQuestions.length) {
            const question = homepageAllQuestions[homepageCurrentQuestionIndex];
            if (question && question.id) {
                console.log('Question ID (homepage fallback):', question.id);
                return question.id;
            }
        }
    } 
    
    // Mode normal
    if (typeof allQuestions !== 'undefined' && allQuestions && allQuestions.length > 0) {
        if (currentQuestionIndex < allQuestions.length) {
            const question = allQuestions[currentQuestionIndex];
            if (question && question.id) {
                console.log('Question ID (normal):', question.id);
                return question.id;
            }
        }
    }
    
    // Fallback avec plus d'informations pour debug
    const fallbackId = `question_${Date.now()}`;
    console.warn('getCurrentQuestionId fallback utilisé:', fallbackId);
    console.warn('État actuel:', {
        isHomepageMode,
        currentChapter,
        currentChapterQuestionIndex,
        homepageAllQuestions: homepageAllQuestions?.length || 0,
        allQuestions: allQuestions?.length || 0
    });
    return fallbackId;
}
function resetQuizState() {
    console.log('Réinitialisation complète de l\'état du quiz');
    
    // NOUVEAU : Nettoyer la persistance
    QuizPersistence.clearQuizState();
    
    // Variables globales
    currentChapter = 0;
    currentChapterQuestionIndex = 0;
    isShowingTransition = false;
    
    // Variables homepage
    isHomepageMode = true;
    homepageQuizAnswers = {};
    homepageQuestionHistory = [];
    homepageCurrentQuestionIndex = 0;
    
    // Réinitialiser l'état des chapitres
    if (QUIZ_CHAPTERS['pack_clarte'] && QUIZ_CHAPTERS['pack_clarte'].chapters) {
        QUIZ_CHAPTERS['pack_clarte'].chapters.forEach(chapter => {
            chapter.introSeen = false;
        });
    }
    
    // Nettoyer les audios temporaires
    if (window.tempQuizAudios) {
        Object.keys(window.tempQuizAudios).forEach(audioId => {
            if (window.tempQuizAudios[audioId].url) {
                try {
                    URL.revokeObjectURL(window.tempQuizAudios[audioId].url);
                } catch (e) {
                    console.warn('Erreur lors de la révocation URL:', e);
                }
            }
        });
        window.tempQuizAudios = {};
    }
    
    // Réinitialiser l'état audio des questions
    currentQuestionAudioState = {};
    globalAudioStorage = {};
}
function triggerChapterCompletionEffect() {
    // Effet visuel quand un chapitre est terminé
    const currentSegment = document.querySelector('.chapter-segment.current');
    if (!currentSegment) return;
    
    console.log('Déclenchement effet completion chapitre');
    
    // Animation de finalisation du segment à 100%
    currentSegment.style.setProperty('--progress', '100%');
    
    // Vibration mobile (si supportée)
    if ('vibrate' in navigator && window.innerWidth <= 768) {
        navigator.vibrate([50, 50, 100]);
    }
    
    // Effet de pulsation douce
    currentSegment.style.animation = 'chapterCompleted 0.8s ease-out';
    
    // Nettoyer l'animation après
    setTimeout(() => {
        if (currentSegment) {
            currentSegment.style.animation = '';
        }
    }, 800);
}


// Fonction pour gérer les erreurs d'enregistrement
function handleRecordingError(audioContainer, error) {
    console.error('Erreur enregistrement:', error);
    
    updateRecordingUI(audioContainer, 'ready');
    
    // Nettoyer l'état
    isRecording = false;
    if (recordingTimer) {
        clearInterval(recordingTimer);
        recordingTimer = null;
    }
    
    // Message d'erreur spécifique Safari
    let errorMessage = 'Impossible d\'accéder au microphone.';
    
    if (isSafari() || isIOSSafari()) {
        if (error.name === 'NotAllowedError') {
            errorMessage = 'Safari nécessite une autorisation explicite. Cliquez sur l\'icône micro dans la barre d\'adresse et autorisez l\'accès.';
        } else if (error.name === 'NotFoundError') {
            errorMessage = 'Microphone non détecté. Vérifiez vos paramètres dans Réglages > Safari > Micro.';
        } else if (error.message.includes('mediaDevices')) {
            errorMessage = 'Safari ne supporte pas cette fonction. Utilisez le mode texte ou essayez avec Chrome.';
        } else {
            errorMessage = 'Erreur Safari : rechargez la page et réessayez.';
        }
    }
    
    showAudioError(audioContainer, errorMessage);
}

// Afficher erreur audio
function showAudioError(audioContainer, message) {
    const existingError = audioContainer.querySelector('.audio-error-message');
    if (existingError) {
        existingError.remove();
    }
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'audio-error-message';
    errorDiv.textContent = message;
    audioContainer.appendChild(errorDiv);
    
    setTimeout(() => {
        if (errorDiv.parentNode) {
            errorDiv.remove();
        }
    }, 5000);
}

// Fonction pour lire l'enregistrement
function playRecording(audioContainer, questionId) {
    const audioElement = audioContainer.querySelector('.audio-element');
    const questionState = currentQuestionAudioState[questionId];
    
    if (!audioElement || !questionState || !questionState.audioURL) {
        console.error('Impossible de lire l\'enregistrement');
        return;
    }
    
    // CORRECTION SAFARI : Configuration de lecture
    audioElement.src = questionState.audioURL;
    audioElement.currentTime = 0;
    
    // Pour Safari, ajouter des événements de gestion d'erreur
    const playPromise = audioElement.play();
    
    if (playPromise !== undefined) {
        playPromise.then(() => {
            console.log('Lecture démarrée avec succès');
        }).catch(err => {
            console.error('Erreur lecture audio:', err);
            
            if (isSafari()) {
                showAudioError(audioContainer, 'Appuyez sur le bouton lecture pour écouter votre enregistrement');
            } else {
                showAudioError(audioContainer, 'Impossible de lire l\'enregistrement');
            }
        });
    }
}

// Fonction pour réinitialiser l'enregistrement
function resetRecording(audioContainer, questionId) {
    const questionState = currentQuestionAudioState[questionId];
    if (questionState) {
        // Nettoyer les ressources audio
        if (questionState.audioURL) {
            URL.revokeObjectURL(questionState.audioURL);
        }
        
        // Réinitialiser l'état
        questionState.audioBlob = null;
        questionState.audioURL = null;
        questionState.isRecording = false;
        questionState.duration = 0;
        
        // Nettoyer les variables globales si c'est la question courante
        if (getCurrentQuestionId() === questionId) {
            audioBlob = null;
            audioURL = null;
            isRecording = false;
            audioChunks = [];
        }
        
        // Supprimer du stockage temporaire
        if (window.tempQuizAudios) {
            Object.keys(window.tempQuizAudios).forEach(audioId => {
                if (window.tempQuizAudios[audioId].questionId === questionId) {
                    if (window.tempQuizAudios[audioId].blob) {
                        // Révoquer l'URL si elle existe
                        const url = window.tempQuizAudios[audioId].url;
                        if (url) URL.revokeObjectURL(url);
                    }
                    delete window.tempQuizAudios[audioId];
                }
            });
        }
    }
    
    // Remettre l'interface en état initial
    updateRecordingUI(audioContainer, 'ready');
    
    // Réinitialiser la jauge
    const progressRing = audioContainer.querySelector('.progress-ring-bar');
    if (progressRing) {
        progressRing.style.strokeDashoffset = '439.8';
    }
}

if (typeof startVoiceRecording !== 'undefined') {
    const originalStartVoiceRecording = startVoiceRecording;
    startVoiceRecording = function(...args) {
        console.warn('Ancienne fonction startVoiceRecording appelée, redirection vers nouvelle version');
        // Ne rien faire ou rediriger vers la nouvelle logique
    };
}

if (typeof stopVoiceRecording !== 'undefined') {
    const originalStopVoiceRecording = stopVoiceRecording;
    stopVoiceRecording = function(...args) {
        console.warn('Ancienne fonction stopVoiceRecording appelée, redirection vers nouvelle version');
        // Ne rien faire ou rediriger vers la nouvelle logique
    };
}

// ===== 9. ÉVÉNEMENTS GLOBAUX POUR CLEANUP =====
// Nettoyer les ressources quand on quitte la page
window.addEventListener('beforeunload', cleanupAudioResources);
window.addEventListener('pagehide', cleanupAudioResources);

// Nettoyer quand on change de question (si fonction existe)
if (typeof window.addEventListener !== 'undefined') {
    document.addEventListener('questionChanged', cleanupAudioResources);
}

function isSafari() {
    const ua = navigator.userAgent;
    return /Safari/.test(ua) && !/Chrome/.test(ua) && !/Edge/.test(ua);
}

function isIOSSafari() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) && 
           /Safari/.test(navigator.userAgent) && 
           !/CriOS/.test(navigator.userAgent);
}

function scrollToNextButton() {
    // Attendre 800ms que l'interface se mette à jour
    setTimeout(() => {
        const nextButton = document.querySelector('.next-btn');
        
        if (nextButton) {
            // Scroll simple vers le bouton
            nextButton.scrollIntoView({ 
                behavior: 'smooth', 
                block: 'center' 
            });
            
            // Petite pulsation pour attirer l'oeil (2 secondes)
            nextButton.style.animation = 'pulse 0.8s ease-in-out 3';
            
            setTimeout(() => {
                nextButton.style.animation = '';
            }, 2400);
        }
    }, 800);
}

// ===== VALIDATION MOT DE PASSE TEMPS RÉEL =====

function togglePasswordVisibility(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return;
    
    const button = input.parentElement.querySelector('.toggle-password i');
    
    if (input.type === 'password') {
        input.type = 'text';
        button.classList.remove('fa-eye');
        button.classList.add('fa-eye-slash');
    } else {
        input.type = 'password';
        button.classList.remove('fa-eye-slash');
        button.classList.add('fa-eye');
    }
}

function validatePassword(password) {
    const requirements = {
        length: password.length >= 12,
        uppercase: /[A-Z]/.test(password),
        lowercase: /[a-z]/.test(password),
        number: /\d/.test(password),
        special: /[@$!%*?&_\-]/.test(password)
    };
    
    // Mettre à jour l'affichage
    Object.keys(requirements).forEach(req => {
        const element = document.querySelector(`[data-requirement="${req}"]`);
        if (element) {
            if (requirements[req]) {
                element.classList.add('valid');
                element.classList.remove('invalid');
            } else {
                element.classList.add('invalid');
                element.classList.remove('valid');
            }
        }
    });
    
    // Retourner true si tous les critères sont remplis
    return Object.values(requirements).every(val => val === true);
}



// Exposer globalement
window.QuizTracking = QuizTracking;
