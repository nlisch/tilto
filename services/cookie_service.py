import logging
from flask import session

logger = logging.getLogger(__name__)

class CookieService:
    @staticmethod
    def get_consent():
        """
        Récupère les préférences de consentement aux cookies depuis la session.
        """
        return session.get('cookie_consent', None)
    
    @staticmethod
    def set_consent(consent_data):
        """
        Enregistre les préférences de consentement aux cookies dans la session.
        
        Args:
            consent_data (dict): Dictionnaire contenant les préférences de consentement.
                Par exemple: {'necessary': True, 'analytics': False, 'marketing': False, 'preferences': True}
        """
        try:
            # Assurez-vous que necessary est toujours True
            consent_data['necessary'] = True
            
            # Vérifiez que toutes les clés nécessaires sont présentes
            required_keys = ['necessary', 'analytics', 'marketing', 'preferences']
            for key in required_keys:
                if key not in consent_data:
                    consent_data[key] = False
            
            # Enregistrez dans la session
            session['cookie_consent'] = consent_data
            session.modified = True
            
            logger.info(f"Préférences de consentement aux cookies mises à jour: {consent_data}")
            return True
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement des préférences de consentement: {e}")
            return False
    
    @staticmethod
    def can_use_analytics():
        """
        Vérifie si l'utilisation des cookies d'analyse est autorisée.
        """
        consent = CookieService.get_consent()
        return consent and consent.get('analytics', False)
    
    @staticmethod
    def can_use_marketing():
        """
        Vérifie si l'utilisation des cookies marketing est autorisée.
        """
        consent = CookieService.get_consent()
        return consent and consent.get('marketing', False)
    
    @staticmethod
    def can_use_preferences():
        """
        Vérifie si l'utilisation des cookies de préférences est autorisée.
        """
        consent = CookieService.get_consent()
        return consent and consent.get('preferences', False)
    
    @staticmethod
    def has_given_consent():
        """
        Vérifie si l'utilisateur a déjà donné son consentement (quelle que soit sa décision).
        """
        return CookieService.get_consent() is not None