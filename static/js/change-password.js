document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('change-password-form');
    
    if (!form) return;
    
    const oldPasswordInput = document.getElementById('ancien_mot_de_passe');
    const newPasswordInput = document.getElementById('nouveau_mot_de_passe');
    const confirmPasswordInput = document.getElementById('confirmer_mot_de_passe');
    const submitBtn = form.querySelector('button[type="submit"]');
    
    // Fonction pour afficher les erreurs
    function showError(input, message) {
        // Supprimer les anciennes erreurs
        const existingError = input.parentElement.querySelector('.error-message');
        if (existingError) {
            existingError.remove();
        }
        
        // Ajouter la nouvelle erreur
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.style.color = '#ef4444';
        errorDiv.style.fontSize = '0.875rem';
        errorDiv.style.marginTop = '0.25rem';
        errorDiv.textContent = message;
        input.parentElement.appendChild(errorDiv);
        input.style.borderColor = '#ef4444';
    }
    
    // Fonction pour supprimer les erreurs
    function clearError(input) {
        const existingError = input.parentElement.querySelector('.error-message');
        if (existingError) {
            existingError.remove();
        }
        input.style.borderColor = '';
    }
    
    // Validation en temps réel
    newPasswordInput.addEventListener('input', function() {
        clearError(this);
        if (this.value.length > 0 && this.value.length < 8) {
            showError(this, 'Le mot de passe doit contenir au moins 8 caractères');
        }
    });
    
    confirmPasswordInput.addEventListener('input', function() {
        clearError(this);
        if (this.value.length > 0 && this.value !== newPasswordInput.value) {
            showError(this, 'Les mots de passe ne correspondent pas');
        }
    });
    
    // Soumission du formulaire
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Réinitialiser les erreurs
        [oldPasswordInput, newPasswordInput, confirmPasswordInput].forEach(clearError);
        
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
        const oldPassword = oldPasswordInput.value.trim();
        const newPassword = newPasswordInput.value.trim();
        const confirmPassword = confirmPasswordInput.value.trim();
        
        // Validations côté client
        let hasError = false;
        
        if (!oldPassword) {
            showError(oldPasswordInput, 'L\'ancien mot de passe est requis');
            hasError = true;
        }
        
        if (!newPassword) {
            showError(newPasswordInput, 'Le nouveau mot de passe est requis');
            hasError = true;
        } else if (newPassword.length < 8) {
            showError(newPasswordInput, 'Le mot de passe doit contenir au moins 8 caractères');
            hasError = true;
        }
        
        if (!confirmPassword) {
            showError(confirmPasswordInput, 'Veuillez confirmer le mot de passe');
            hasError = true;
        } else if (newPassword !== confirmPassword) {
            showError(confirmPasswordInput, 'Les mots de passe ne correspondent pas');
            hasError = true;
        }
        
        if (hasError) return;
        
        // Désactiver le bouton et afficher le loading
        const originalBtnText = submitBtn.innerHTML;
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Changement en cours...';
        submitBtn.style.opacity = '0.6';
        
        // Préparer les données
        const data = {
            ancien_mot_de_passe: oldPassword,
            nouveau_mot_de_passe: newPassword,
            confirmer_mot_de_passe: confirmPassword
        };
        
        // Récupérer la langue
        const langCode = document.documentElement.lang || 'fr';
        
        // Envoyer la requête
        fetch(`/${langCode}/changer-mot-de-passe`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(err => Promise.reject(err));
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                // Afficher le message de succès
                showSuccessMessage(data.message || 'Mot de passe changé avec succès ! 🎉');
                
                // Redirection après 1.5 secondes
                setTimeout(() => {
                    window.location.href = `/${langCode}/mon-compte`;
                }, 1500);
            } else {
                // Réactiver le bouton
                submitBtn.disabled = false;
                submitBtn.innerHTML = originalBtnText;
                submitBtn.style.opacity = '1';
                
                // Afficher l'erreur
                showErrorMessage(data.message || 'Une erreur est survenue');
            }
        })
        .catch(error => {
            console.error('Erreur:', error);
            
            // Réactiver le bouton
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnText;
            submitBtn.style.opacity = '1';
            
            // Afficher l'erreur
            const message = error.message || 'Une erreur est survenue lors de la communication avec le serveur';
            showErrorMessage(message);
        });
    });
    
    // Fonction pour afficher un message de succès
    function showSuccessMessage(message) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-success';
        alertDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #d1fae5;
            color: #065f46;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            border: 1px solid #a7f3d0;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            z-index: 9999;
            animation: slideIn 0.3s ease-out;
        `;
        alertDiv.textContent = message;
        document.body.appendChild(alertDiv);
        
        // Animation CSS
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
        `;
        document.head.appendChild(style);
        
        // Supprimer après 3 secondes
        setTimeout(() => {
            alertDiv.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => alertDiv.remove(), 300);
        }, 3000);
    }
    
    // Fonction pour afficher un message d'erreur
    function showErrorMessage(message) {
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-error';
        alertDiv.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: #fee2e2;
            color: #991b1b;
            padding: 1rem 1.5rem;
            border-radius: 12px;
            border: 1px solid #fecaca;
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
            z-index: 9999;
            animation: slideIn 0.3s ease-out;
        `;
        alertDiv.textContent = message;
        document.body.appendChild(alertDiv);
        
        // Supprimer après 5 secondes
        setTimeout(() => {
            alertDiv.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => alertDiv.remove(), 300);
        }, 5000);
    }
    
    // Animation de sortie
    const styleOut = document.createElement('style');
    styleOut.textContent = `
        @keyframes slideOut {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
        .spinner {
            display: inline-block;
            width: 14px;
            height: 14px;
            border: 2px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    `;
    document.head.appendChild(styleOut);
});