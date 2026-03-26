// Force les logs à rester visibles
console.debug = console.log;

// Définition des traductions
const translations = {
    'fr': {
        'restartQuiz': "Recommencer le quiz",
        'voirAnalyse': "Voir ma page d'analyse profiling",
        'analyseEnCours': "Analyse en cours...",
        'erreurAnalyse': "Une erreur est survenue lors de l'analyse. Veuillez réessayer.",
        'erreurGlobale': "Une erreur inattendue s'est produite. Veuillez réessayer.",
        'erreurChargement': "Erreur lors du chargement des questions. Veuillez réessayer.",
        'erreurProgression': "Erreur lors de la mise à jour de la progression. Veuillez réessayer.",
        'previousButton': "Précédent",
        'nextButton': "Suivant",
        'finishButton': "Prochaine étape",
        'startQuiz': "Commence l'aventure !",
        'resumeQuiz': "Reprendre le quiz",
        'seeLastProfile': "Voir mon dernier profil",
        'minChoicesError': "Veuillez sélectionner au moins {min} options.",
        'maxChoicesError': "Veuillez sélectionner au maximum {max} options.",
        'noChoiceError': "Veuillez sélectionner une option.",
        'emptyInputError': "Ce champ ne peut pas être vide.",
        'longInputError': "Le texte est trop long. Maximum {max} caractères.",
        'emptyTextAreaError': "Veuillez entrer une réponse.",
        'longTextAreaError': "Votre réponse ne doit pas dépasser {max} caractères.",
        'otherInputPlaceholder': "Autre réponse ? Écris-la ici !",
        'freeTextPlaceholder': "Écris ta réponse ici !",
        'emptyOtherError': "Veuillez remplir le champ 'Autre' ou sélectionner une réponse différente.",
        'locationPlaceholder': 'Entrez votre ville',
        'emptyLocationError': 'Veuillez sélectionner une ville',
        'invalidLocationError': 'Veuillez sélectionner une ville valide dans la liste',
        'tokenValid': "Token vérifié avec succès. Vous pouvez commencer le quiz.",
        'startQuiz': "C'est parti ! ",
        'resumeQuiz': "Reprendre le Quiz",
        'getToken': "Obtenir un Token",
        'tokenRequired': "Un token valide est requis pour accéder à ce quiz.",
        'noQuestionsFound': "Aucune question n'a été trouvée pour ce quiz.",
        'otherInputPlaceholder': "Veuillez spécifier...",
        'freeTextPlaceholder': "Votre réponse...",
        'noTokenMessage': 'Vous n\'avez pas de token valide pour ce quiz. Veuillez en obtenir un pour commencer.',
        'yourAnswer': 'Votre réponse',
        'modifyAnswer': 'Modifier cette réponse',
        'backToReview': 'Retour au récapitulatif',
        'updateAndReturn': 'Mettre à jour et revenir au récapitulatif',
        'answerUpdated': 'Réponse mise à jour avec succès !',
        'erreurMiseAJour': 'Une erreur est survenue lors de la mise à jour de la réponse.',
        'minChoicesInfinite': "Sélectionnez au moins une réponse",
        'maxChoicesInfinite': "Sélectionnez autant de réponses que vous le souhaitez",
        'exactChoices': "Sélectionnez exactement {count} options",
        'rangeChoices': "Sélectionnez entre {min} et {max} options",
        'minChoicesOnly': "Sélectionnez au moins {min} options",
        'maxChoicesOnly': "Sélectionnez au maximum {max} options",
        'erreurGenerationAnalyse': "Une erreur est survenue lors de la génération de l'analyse",
        'voiceRecordButton': 'Enregistrer votre réponse',
        'stopRecording': 'Arrêter l\'enregistrement',
        'processingAudio': 'Transcription en cours...',
        'microphoneError': 'Impossible d\'accéder au microphone. Veuillez vérifier les permissions de votre navigateur.',
        'freeTextPlaceholder': 'Saisissez votre réponse ou utilisez l\'enregistrement vocal...',
        'emptyAudioOrTextError': 'Veuillez soit enregistrer un audio soit saisir du texte pour continuer',
        'shortAudioError': 'Votre enregistrement dure moins de {min} secondes. Développez un peu plus votre réponse pour nous aider à mieux vous conseiller.',
        'longAudioError': 'Votre enregistrement dépasse la durée maximale autorisée de {max} secondes.',
        'emptyTextAreaError': 'Veuillez saisir une réponse avant de continuer.',
        'shortTextAreaError': 'Votre réponse est un peu courte. Développez davantage pour nous aider à mieux vous conseiller (minimum {min} caractères).',
        'longTextAreaError': 'Votre réponse dépasse la limite de {max} caractères. Merci de raccourcir votre texte.',
        'erreurGlobale': 'Une erreur est survenue. Veuillez réessayer.',
        'erreurTechnique': 'Erreur technique. Veuillez recharger la page et réessayer.',
        'erreurProgression': 'Impossible de sauvegarder votre progression. Vérifiez votre connexion.',
        'erreurAnalyse': 'Impossible de générer votre analyse. Veuillez réessayer plus tard.'
    },
    'en': {
        'restartQuiz': "Restart the quiz",
        'voirAnalyse': "View my profiling analysis page",
        'analyseEnCours': "Analysis in progress...",
        'erreurAnalyse': "An error occurred during the analysis. Please try again.",
        'erreurGlobale': "An unexpected error occurred. Please try again.",
        'erreurChargement': "Error loading questions. Please try again.",
        'erreurProgression': "Error updating progress. Please try again.",
        'previousButton': "Previous",
        'nextButton': "Next",
        'finishButton': "Finish",
        'startQuiz': "Start the adventure!",
        'resumeQuiz': "Resume the quiz",
        'seeLastProfile': "View my last profile",
        'minChoicesError': "Please select at least {min} options.",
        'maxChoicesError': "Please select a maximum of {max} options.",
        'noChoiceError': "Please select an option.",
        'emptyInputError': "This field cannot be empty.",
        'longInputError': "The text is too long. Maximum {max} characters.",
        'emptyTextAreaError': "Please enter an answer.",
        'longTextAreaError': "Your answer should not exceed {max} characters.",
        'otherInputPlaceholder': "Other answer? Write it here!",
        'freeTextPlaceholder': "Write your answer here!",
        'emptyOtherError': "Please fill in the 'Other' field or select a different answer.",
        'locationPlaceholder': 'Enter your city',
        'emptyLocationError': 'Please select a city',
        'invalidLocationError': 'Please select a valid city from the list',
        'tokenValid': "Token successfully verified. You can start the quiz.",
        'startQuiz': "Start Quiz",
        'resumeQuiz': "Resume Quiz",
        'getToken': "Get Token",
        'tokenRequired': "A valid token is required to access this quiz.",
        'noQuestionsFound': "No questions were found for this quiz.",
        'otherInputPlaceholder': "Please specify...",
        'freeTextPlaceholder': "Your answer...",
        'noTokenMessage': 'You do not have a valid token for this quiz. Please get one to start.',
        'yourAnswer': 'Your answer',
        'modifyAnswer': 'Modify this answer',
        'backToReview': 'Back to review',
        'updateAndReturn': 'Update and return to summary',
        'answerUpdated': 'Answer successfully updated!',
        'erreurMiseAJour': 'An error occurred while updating the answer.',
        'minChoicesInfinite': "Select at least {min} options",
        'maxChoicesInfinite': "Select up to {max} options",
        'exactChoices': "Select exactly {count} options",
        'rangeChoices': "Select between {min} and {max} options",
        'minChoicesOnly': "Select at least {min} options",
        'maxChoicesOnly': "Select a maximum of {max} options",
        'erreurGenerationAnalyse': "An error occurred while generating the analysis",
        'voiceRecordButton': 'Enregistrer votre réponse',
        'stopRecording': 'Arrêter l\'enregistrement',
        'processingAudio': 'Transcription en cours...',
        'microphoneError': 'Impossible d\'accéder au microphone. Veuillez vérifier les permissions de votre navigateur.',
        'freeTextPlaceholder': 'Saisissez votre réponse ou utilisez l\'enregistrement vocal...',
        'shortTextAreaError': 'Votre réponse doit contenir au moins {min} caractères pour être suffisamment détaillée.',
        'shortAudioError': 'Votre enregistrement doit durer au moins {min} secondes. Pensez à développer vos idées !'
    }
};

// Variable pour stocker la langue courante
let currentLanguage = document.documentElement.lang || 'fr';

// Fonction de traduction avec remplacement des placeholders
function getTranslation(key, replacements = {}) {
    let translation = translations[currentLanguage][key] || key;
    for (const [placeholder, value] of Object.entries(replacements)) {
        translation = translation.replace(`{${placeholder}}`, value);
    }
    return translation;
}

window.getTranslation = getTranslation;

// Fonction pour mettre à jour le bouton de langue affiché
function updateLanguageButton(lang) {
    console.log("Updating language button to:", lang);
    const currentLangSpan = document.querySelector('.language-button .current-lang');
    if (currentLangSpan) {
        if (lang === 'fr') {
            currentLangSpan.textContent = 'FR';
        } else if (lang === 'en') {
            currentLangSpan.textContent = 'EN';
        }
    }
}


// Écouteur d'événement DOMContentLoaded
document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM fully loaded");
    
    const languageButton = document.querySelector('.language-button');
    const languageDropdown = document.querySelector('.language-dropdown');
    
    console.log("Language button found:", !!languageButton);
    console.log("Language dropdown found:", !!languageDropdown);
    
    if (languageButton && languageDropdown) {
        // Toggle du dropdown au clic sur le bouton
        languageButton.addEventListener('click', function(e) {
            console.log("Language button clicked");
            e.stopPropagation();
            languageDropdown.style.display = languageDropdown.style.display === 'none' ? 'block' : 'none';
            console.log("Dropdown display set to:", languageDropdown.style.display);
        });

        // Gestion de la sélection de langue
        document.querySelectorAll('.language-dropdown .language-option').forEach(item => {
            console.log("Setting up click listener for language option:", item.dataset.lang);
            
            item.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                
                const selectedLang = this.dataset.lang;
                console.log("Language option clicked:", selectedLang);
                
                fetch(this.href, {
                    method: 'GET',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    credentials: 'same-origin'  // Important pour la gestion des sessions
                })
                .then(response => {
                    console.log("Language change response:", response.status);
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    window.location.reload();
                })
                .catch(error => {
                    console.error('Error changing language:', error);
                });
            });
        });

        // Fermeture du dropdown au clic extérieur
        document.addEventListener('click', function() {
            languageDropdown.style.display = 'none';
        });
    }

    // Mise à jour initiale de l'interface
    updateLanguageButton(currentLanguage);

    // Prévention du clic droit sur les images
    const images = document.querySelectorAll('img');
    images.forEach(function(img) {
        img.addEventListener('contextmenu', function(e) {
            e.preventDefault();
            alert(getTranslation('invalidLocationError'));
        });
    });
});