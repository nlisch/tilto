// static/js/utils.js

// ===== GESTIONNAIRE D'ERREURS GLOBAL =====
// Doit être en PREMIER pour capturer toutes les erreurs

// Filtrer l'erreur ResizeObserver
window.addEventListener('error', function(e) {
    // Ignorer l'erreur ResizeObserver qui est bénigne
    if (e.message === 'ResizeObserver loop completed with undelivered notifications.' ||
        (e.message && e.message.includes('ResizeObserver loop'))) {
        e.stopImmediatePropagation();
        return false;
    }
    
    // Logger les vraies erreurs
    console.error('Erreur globale capturée:', e.message);
    log('Erreur globale capturée: ' + e.message);
    return true;
});

// Gérer les rejections de promesses
window.addEventListener('unhandledrejection', function(e) {
    if (e.reason && e.reason.message && e.reason.message.includes('ResizeObserver')) {
        e.stopImmediatePropagation();
        return false;
    }
    return true;
});

// ===== FONCTIONS UTILITAIRES =====

function log(...messages) {
    console.log(...messages);
    const logContent = document.getElementById('logContent');
    if (logContent) {
        logContent.innerHTML += messages.join(' ') + '<br>';
        logContent.scrollTop = logContent.scrollHeight;
    }
}

function getElement(selector, required = false) {
    console.log(`Recherche élément: ${selector} (required: ${required})`);
    const element = document.querySelector(selector);
    if (required && !element) {
        console.error(`Élément requis non trouvé: ${selector}`, {
            documentReady: document.readyState,
            parentExists: document.querySelector(selector.split(' ')[0])
        });
        throw new Error(`Element ${selector} not found`);
    }
    console.log(`Élément trouvé: ${selector}`, { exists: !!element });
    return element;
}

// Fonction pour optimiser les mises à jour DOM
function batchDOMUpdates(callback) {
    if (typeof requestAnimationFrame !== 'undefined') {
        requestAnimationFrame(() => {
            callback();
        });
    } else {
        setTimeout(callback, 0);
    }
}

// Export pour utilisation dans d'autres fichiers si nécessaire
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        log,
        getElement,
        batchDOMUpdates
    };
}