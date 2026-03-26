async function checkToken(quizId) {
    try {
        const response = await fetch(`/check-token/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error('Token check failed');
        }

        const data = await response.json();
        return data.has_token;
    } catch (error) {
        log("Erreur lors de la vérification du token: " + error);
        return false;
    }
}

// Fonction pour vérifier l'accès à l'analyse
async function checkAnalysisAccess(quizId) {
    try {
        const response = await fetch(`/analysis/get_latest_token/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            throw new Error('Failed to fetch token info');
        }

        const data = await response.json();
        return data;
    } catch (error) {
        log("Erreur lors de la vérification de l'accès à l'analyse: " + error);
        return null;
    }
}

// Initialisation du dashboard
document.addEventListener('DOMContentLoaded', async function() {
    const startScreen = getElement('#startScreen');
    if (!startScreen) {
        log("Pas sur la page dashboard");
        return;
    }

    log("DOM dashboard chargé");
    const startQuizBtn = getElement('#startQuizBtn', true);
    const quizId = startQuizBtn.getAttribute('data-quiz-id') || 'personal_profiling';
    
    // Vérifier d'abord si l'utilisateur a un token
    const hasToken = await checkToken(quizId);
    if (!hasToken) {
        // Si pas de token, afficher uniquement le bouton d'obtention de token
        const getTokenBtn = getElement('#getTokenBtn');
        if (getTokenBtn) {
            getTokenBtn.style.display = 'inline-block';
            getTokenBtn.style.visibility = 'visible';
            getTokenBtn.addEventListener('click', () => {
                window.location.href = '/get-token';
            });
        }
        return; // Ne pas continuer l'initialisation
    }

    // Si l'utilisateur a un token, initialiser normalement
    await initDashboard(quizId);
});

async function initDashboard(quizId) {
    log("Initialisation du dashboard avec quizId: " + quizId);
    
    // Récupération des éléments du DOM
    const startQuizBtn = getElement('#startQuizBtn', true);
    const resumeQuizBtn = getElement('#resumeQuizBtn');
    const getTokenBtn = getElement('#getTokenBtn');
    const reviewAnswersBtn = getElement('#reviewAnswersBtn');
    const viewAnalysisBtn = getElement('#viewAnalysisBtn');

    // Cacher tous les boutons initialement
    const buttons = [startQuizBtn, resumeQuizBtn, getTokenBtn, reviewAnswersBtn, viewAnalysisBtn];
    buttons.forEach(btn => {
        if (btn) {
            btn.style.visibility = 'hidden';
            btn.style.display = 'none';
        }
    });

    try {
        const progressResponse = await fetch(`/get_quiz_progress/${quizId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (progressResponse.redirected) {
            window.location.href = progressResponse.url;
            return;
        }

        if (!progressResponse.ok) {
            throw new Error('Failed to fetch quiz progress');
        }

        const progressData = await progressResponse.json();
        log("Réponse de /get_quiz_progress : " + JSON.stringify(progressData));

        const totalQuestions = progressData.progress.total_possible_questions;

        // Vérifier que total_possible_questions est défini et supérieur à 0
        const allPossibleQuestionsAnswered = progressData.progress && progressData.answers && 
            typeof totalQuestions === 'number' && 
            totalQuestions > 0 &&
            Object.keys(progressData.answers).length >= totalQuestions;
        
        const isQuizCompleted = 
            progressData.quiz_completed || 
            (progressData.progress && (
                progressData.progress.quiz_status === 'completed' ||
                progressData.progress.quiz_status === 'answers_review' ||
                allPossibleQuestionsAnswered
            ));        

        log("Quiz complété?", isQuizCompleted);
        log("Toutes les questions possibles répondues?", allPossibleQuestionsAnswered);

        // Vérification du token avant d'afficher les boutons
        const hasToken = await checkToken(quizId);
        if (!hasToken) {
            if (getTokenBtn) {
                getTokenBtn.style.display = 'inline-block';
                getTokenBtn.style.visibility = 'visible';
                getTokenBtn.addEventListener('click', () => {
                    window.location.href = '/get-token';
                });
            }
            return;
        }

        if (isQuizCompleted) {
            log("Quiz complété - Affichage des boutons de revue/analyse");
            if (reviewAnswersBtn) {
                reviewAnswersBtn.style.display = 'inline-block';
            }
            if (progressData.progress && progressData.progress.has_analysis && viewAnalysisBtn) {
                viewAnalysisBtn.style.display = 'inline-block';
            }
        } else if (progressData.progress) {
            const quizStatus = progressData.progress.quiz_status;
            const questionHistory = progressData.progress.question_history || [];
            const questionsAnswered = progressData.progress.questions_answered_count || 0;

            log("Quiz status:", quizStatus);
            log("Questions answered:", questionsAnswered);
            log("Question history:", questionHistory);

            switch(quizStatus) {
                case 'not_started':
                    if (startQuizBtn) startQuizBtn.style.display = 'inline-block';
                    break;

                case 'in_progress':
                    // Vérifier s'il reste des questions à répondre
                    if (allPossibleQuestionsAnswered) {
                        log("Toutes les questions ont été répondues - Affichage du bouton de revue");
                        if (reviewAnswersBtn) reviewAnswersBtn.style.display = 'inline-block';
                    } else if (questionHistory.length > 0) {
                        log("Affichage du bouton reprendre - progression détectée");
                        if (resumeQuizBtn) resumeQuizBtn.style.display = 'inline-block';
                    } else {
                        log("Affichage du bouton démarrer - pas de progression réelle");
                        if (startQuizBtn) startQuizBtn.style.display = 'inline-block';
                    }
                    break;

                default:
                    if (startQuizBtn) startQuizBtn.style.display = 'inline-block';
                    break;
            }
        } else {
            if (startQuizBtn) startQuizBtn.style.display = 'inline-block';
        }

        // Configuration des événements des boutons
        if (startQuizBtn) {
            startQuizBtn.addEventListener('click', () => {
                log("Clic sur démarrer - Redirection vers /quiz");
                window.location.href = `/quiz?quiz_id=${encodeURIComponent(quizId)}`;
            });
        }
        
        if (resumeQuizBtn) {
            resumeQuizBtn.addEventListener('click', () => {
                log("Clic sur reprendre - Redirection vers /quiz avec resume=true");
                window.location.href = `/quiz?quiz_id=${encodeURIComponent(quizId)}&resume=true`;
            });
        }

        if (reviewAnswersBtn) {
            reviewAnswersBtn.addEventListener('click', () => {
                log("Clic sur revoir - Redirection vers /quiz avec show_recap=true");
                window.location.href = `/quiz?quiz_id=${encodeURIComponent(quizId)}&show_recap=true#congratulations`;
            });
        }

        if (viewAnalysisBtn) {
            viewAnalysisBtn.addEventListener('click', async () => {
                try {
                    log("Clic sur analyse - Vérification de l'accès");
                    
                    // 1. Vérifier d'abord l'état du quiz
                    const progressResponse = await fetch(`/get_quiz_progress/${quizId}`, {
                        method: 'GET',
                        headers: {
                            'Accept': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });
                    
                    if (!progressResponse.ok) {
                        throw new Error('Failed to check quiz progress');
                    }
                    
                    const progressData = await progressResponse.json();
                    log("État du quiz:", progressData);
                    
                    if (!progressData.progress || !progressData.progress.has_analysis) {
                        alert(getTranslation('analyseNonDisponible'));
                        return;
                    }
        
                    // 2. Récupérer les informations du token
                    const tokenResponse = await fetch(`/analysis/get_latest_token/${quizId}`, {
                        method: 'GET',
                        headers: {
                            'Accept': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        credentials: 'same-origin'
                    });
        
                    log("Réponse token:", tokenResponse.status);
                    
                    if (!tokenResponse.ok) {
                        const errorText = await tokenResponse.text();
                        log("Erreur détaillée token:", errorText);
                        throw new Error(`Token request failed: ${tokenResponse.status}`);
                    }
        
                    const tokenData = await tokenResponse.json();
                    log("Données du token:", tokenData);
        
                    if (!tokenData || !tokenData.token_id || !tokenData.result_id) {
                        log("Données token invalides:", tokenData);
                        alert(getTranslation('donneesTokenInvalides'));
                        return;
                    }
        
                    // Ici on construit l'URL avec tous les paramètres nécessaires
                    const analysisUrl = `/analysis/view/${quizId}?` + 
                        new URLSearchParams({
                            result_id: tokenData.result_id,
                            step_id: 'vision_360',
                            skip_loading: 'true'
                        });
        
                    log("Redirection vers:", analysisUrl);
                    window.location.href = analysisUrl;
        
                } catch (error) {
                    log("Erreur lors de l'accès à l'analyse:", error);
                    alert(getTranslation('erreurAccesAnalyse'));
                }
            });
        }

        if (getTokenBtn) {
            getTokenBtn.addEventListener('click', () => {
                window.location.href = '/get-token';
            });
        }

        // Rendre les boutons visibles
        buttons.forEach(btn => {
            if (btn && btn.style.display === 'inline-block') {
                btn.style.visibility = 'visible';
                log(`Bouton rendu visible: ${btn.id}`);
            }
        });

    } catch (error) {
        log("Erreur lors de la vérification de la progression: " + error);
        const hasToken = await checkToken(quizId);
        if (!hasToken) {
            if (getTokenBtn) {
                getTokenBtn.style.display = 'inline-block';
                getTokenBtn.style.visibility = 'visible';
            }
            return;
        }
        if (startQuizBtn) {
            startQuizBtn.style.display = 'inline-block';
            startQuizBtn.style.visibility = 'visible';
        }
    }
}

// Gestion des erreurs globales
window.onerror = function(message, source, lineno, colno, error) {
    log("Erreur globale capturée: " + message);
    return true;
};