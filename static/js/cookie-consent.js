document.addEventListener('DOMContentLoaded', function() {
    const cookieConsent = {
        init: function() {
            this.banner = document.getElementById('cookie-banner');
            this.acceptAllBtn = document.getElementById('accept-all-cookies');
            this.rejectAllBtn = document.getElementById('reject-all-cookies');
            this.preferencesBtn = document.getElementById('cookie-preferences');
            this.savePreferencesBtn = document.getElementById('save-preferences');
            this.preferencesModal = document.getElementById('preferences-modal');
            this.closeModalBtn = document.getElementById('close-modal');
            
            if (!this.banner) {
                console.error("L'élément banner n'a pas été trouvé dans le DOM");
                return;
            }
            
            this.checkConsent();
            this.bindEvents();
        },
        
        bindEvents: function() {
            if (this.acceptAllBtn) {
                this.acceptAllBtn.addEventListener('click', () => {
                    this.addButtonAnimation(this.acceptAllBtn);
                    this.setConsent({
                        necessary: true,
                        analytics: true,
                        marketing: true,
                        preferences: true
                    });
                });
            }
            
            if (this.rejectAllBtn) {
                this.rejectAllBtn.addEventListener('click', () => {
                    this.addButtonAnimation(this.rejectAllBtn);
                    this.setConsent({
                        necessary: true,
                        analytics: false,
                        marketing: false,
                        preferences: false
                    });
                });
            }
            
            if (this.preferencesBtn) {
                this.preferencesBtn.addEventListener('click', () => {
                    this.addButtonAnimation(this.preferencesBtn);
                    this.openModal();
                });
            }
            
            if (this.closeModalBtn) {
                this.closeModalBtn.addEventListener('click', () => {
                    this.closeModal();
                });
            }
            
            if (this.preferencesModal) {
                this.preferencesModal.addEventListener('click', (e) => {
                    if (e.target === this.preferencesModal) {
                        this.closeModal();
                    }
                });
            }
            
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && this.preferencesModal && !this.preferencesModal.classList.contains('cookie-hidden')) {
                    this.closeModal();
                }
            });
            
            if (this.savePreferencesBtn) {
                this.savePreferencesBtn.addEventListener('click', () => {
                    this.addButtonAnimation(this.savePreferencesBtn);
                    
                    const consent = {
                        necessary: true,
                        analytics: document.getElementById('consent-analytics')?.checked || false,
                        marketing: document.getElementById('consent-marketing')?.checked || false,
                        preferences: document.getElementById('consent-preferences')?.checked || false
                    };
                    
                    this.setConsent(consent);
                    this.closeModal();
                });
            }
        },
        
        addButtonAnimation: function(button) {
            button.style.transform = 'scale(0.95)';
            setTimeout(() => {
                button.style.transform = 'scale(1)';
            }, 150);
        },
        
        openModal: function() {
            if (this.preferencesModal) {
                document.body.style.overflow = 'hidden';
                this.preferencesModal.classList.remove('cookie-hidden');
                this.trapFocus();
            }
        },
        
        closeModal: function() {
            if (this.preferencesModal) {
                document.body.style.overflow = '';
                this.preferencesModal.classList.add('cookie-hidden');
            }
        },
        
        trapFocus: function() {
            setTimeout(() => {
                const focusableElements = this.preferencesModal?.querySelectorAll('button, input, select, textarea, [tabindex]:not([tabindex="-1"])');
                if (focusableElements && focusableElements.length > 0) {
                    focusableElements[0].focus();
                }
            }, 100);
        },
        
        checkConsent: function() {
            try {
                fetch('/cookie/status')
                    .then(response => {
                        if (!response.ok) {
                            throw new Error(`Erreur HTTP: ${response.status}`);
                        }
                        const contentType = response.headers.get('content-type');
                        if (!contentType?.includes('application/json')) {
                            throw new Error(`Réponse non-JSON: ${contentType}`);
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (!data.consent) {
                            this.showBanner();
                        } else {
                            this.updatePreferencesUI(data.consent);
                            this.applyConsentPreferences(data.consent);
                        }
                    })
                    .catch(error => {
                        console.error('Erreur vérification consentement:', error);
                        this.showBanner();
                    });
            } catch (error) {
                console.error('Exception vérification consentement:', error);
                this.showBanner();
            }
        },
        
        showBanner: function() {
            if (this.banner) {
                setTimeout(() => {
                    this.banner.classList.remove('cookie-hidden');
                }, 2000);
            }
        },
        
        hideBanner: function() {
            if (this.banner) {
                this.banner.classList.add('cookie-hidden');
            }
        },
        
        updateGoogleAnalytics: function(analyticsEnabled) {
            console.log('🔄 MAJ Google Analytics:', analyticsEnabled);
            
            if (typeof gtag === 'function') {
                gtag('consent', 'update', {
                    'analytics_storage': analyticsEnabled ? 'granted' : 'denied'
                });
                
                if (analyticsEnabled) {
                    gtag('event', 'page_view', {
                        'page_title': document.title,
                        'page_location': window.location.href
                    });
                    console.log('✅ GA: Événement page_view envoyé');
                }
                
                console.log('✅ GA: Consentement mis à jour vers', analyticsEnabled ? 'granted' : 'denied');
            } else {
                console.error('❌ gtag fonction non disponible');
                console.log('window.dataLayer:', window.dataLayer);
                console.log('Scripts chargés:', document.querySelectorAll('script[src*="googletagmanager"]').length);
            }
        },

        // ← AJOUTÉ : mise à jour consentement Google Ads
        updateGoogleAds: function(marketingEnabled) {
            console.log('🔄 MAJ Google Ads:', marketingEnabled);
            if (typeof gtag === 'function') {
                gtag('consent', 'update', {
                    'ad_storage':          marketingEnabled ? 'granted' : 'denied',
                    'ad_user_data':        marketingEnabled ? 'granted' : 'denied',
                    'ad_personalization':  marketingEnabled ? 'granted' : 'denied'
                });
                if (marketingEnabled && window.GOOGLE_ADS_ID) {
                    gtag('config', window.GOOGLE_ADS_ID);
                }
                console.log('✅ Google Ads: Consentement mis à jour vers', marketingEnabled ? 'granted' : 'denied');
            }
        },
        
        updatePreferencesUI: function(consent) {
            ['analytics', 'marketing', 'preferences'].forEach(type => {
                const checkbox = document.getElementById(`consent-${type}`);
                if (checkbox && consent[type] !== undefined) {
                    checkbox.checked = consent[type];
                }
            });
        },
        
        setConsent: function(consent) {
            const csrfToken = this.getCSRFToken();
            
            fetch('/cookie/consent', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(consent),
                credentials: 'same-origin'
            })
            .then(response => {
                if (!response.ok) throw new Error(`Erreur HTTP: ${response.status}`);
                const contentType = response.headers.get('content-type');
                if (!contentType?.includes('application/json')) {
                    throw new Error(`Réponse non-JSON: ${contentType}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success') {
                    this.hideBanner();
                    this.updatePreferencesUI(consent);
                    this.showNotification('Préférences enregistrées ! 🎉');
                    this.applyConsentPreferences(consent);
                } else {
                    throw new Error('Réponse serveur non réussie');
                }
            })
            .catch(error => {
                console.error('Erreur enregistrement:', error);
                this.showNotification('Erreur. Réessaie plus tard 😕', 'error');
            });
        },
        
        showNotification: function(message, type = 'success') {
            const notification = document.createElement('div');
            notification.className = `cookie-notification notification-${type}`;
            
            const icon = document.createElement('span');
            icon.className = 'notification-icon';
            icon.textContent = type === 'success' ? '✓' : '⚠';
            
            const text = document.createElement('span');
            text.textContent = message;
            
            notification.appendChild(icon);
            notification.appendChild(text);
            document.body.appendChild(notification);
            
            setTimeout(() => notification.classList.add('visible'), 10);
            
            setTimeout(() => {
                notification.classList.remove('visible');
                setTimeout(() => {
                    if (notification.parentNode) {
                        document.body.removeChild(notification);
                    }
                }, 300);
            }, 3000);
        },
        
        getCSRFToken: function() {
            const metaToken = document.querySelector('meta[name="csrf-token"]');
            const inputToken = document.querySelector('input[name="csrf_token"]');
            return metaToken?.getAttribute('content') || inputToken?.value || '';
        },
        
        applyConsentPreferences: function(consent) {
            console.log('Application préférences:', consent);
            
            this.updateGoogleAnalytics(consent.analytics);
            this.updateGoogleAds(consent.marketing); // ← AJOUTÉ
            
            if (consent.analytics)   this.enableAnalytics();
            if (consent.marketing)   this.enableMarketing();
            if (consent.preferences) this.enablePreferences();
        },
        
        enableAnalytics: function() {
            console.log('Analytics activés');
            window.dispatchEvent(new CustomEvent('analyticsEnabled'));
        },
        
        enableMarketing: function() {
            console.log('Marketing activé');
            try {
                if (typeof fbq === 'function') {
                    fbq('consent', 'grant');
                    if (window.FACEBOOK_PIXEL_ID) {
                        fbq('init', window.FACEBOOK_PIXEL_ID);
                        fbq('track', 'PageView');
                    }
                }
            } catch (e) {
                console.warn('Facebook Pixel error (non-bloquant):', e);
            }
            window.dispatchEvent(new CustomEvent('marketingEnabled'));
        },
        
        enablePreferences: function() {
            console.log('Préférences activées');
            window.dispatchEvent(new CustomEvent('preferencesEnabled'));
        }
    };
    
    cookieConsent.init();
    window.cookieConsent = cookieConsent;
});

document.addEventListener('DOMContentLoaded', function() {
    const originalFetch = window.fetch;
    window.fetch = function(...args) {
        return originalFetch.apply(this, args)
            .then(response => {
                if (response.status === 400) {
                    return response.clone().text().then(text => {
                        if (text.includes('CSRF')) {
                            if (confirm('Votre session a expiré. Voulez-vous recharger la page ?')) {
                                window.location.reload();
                            }
                            throw new Error('CSRF token expired');
                        }
                        return response;
                    });
                }
                return response;
            });
    };
});