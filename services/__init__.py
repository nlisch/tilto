from .email_service import *
from .image_service import ImageService
from .video_service import VideoService
from .cookie_service import CookieService
from .audio_service import AudioService
from .anonymization_client import AnonymizationClient
from .quiz_analysis_service import QuizAnalysisService, PromptData
from .audio_capsule_service import AudioCapsuleService
from .youcanbook_service import YouCanBookMeService
from .analysis_access_service import AnalysisAccessModel
from .async_analysis_service import AsyncAnalysisService
from .piste_access_service import PisteAccessService
from .conversation_eval_service import ConversationCoachService
import logging

logger = logging.getLogger(__name__)

# Import Slack avec gestion d'erreur
try:
    from .slack_service import slack_service, SlackService
    SLACK_AVAILABLE = False  # ✅ Valeur par défaut, sera mise à jour par init_slack_service()
    logger.info("DEBUG: Service Slack importé avec succès")
except ImportError as e:
    # Log l'erreur mais continue sans interrompre l'application
    logger.warning(f"Service Slack non disponible: {e}")
    logger.info(f"DEBUG: Import Slack échoué: {e}")
    slack_service = None
    SlackService = None
    SLACK_AVAILABLE = False

def init_anonymization_service(app):
    """Initialise le client du service d'anonymisation distant."""
    # Configurer l'URL du service
    app.config['ANONYMIZATION_SERVICE_URL'] = app.config.get(
        'ANONYMIZATION_SERVICE_URL',
        'https://anonymization-service-[ID_UNIQUE].run.app'
    )
    
    # Déterminer si l'anonymisation est activée (par défaut: oui)
    anonymization_enabled = app.config.get('ANONYMIZATION_ENABLED', True)
    
    # Créer et stocker le client
    app.anonymization_service = AnonymizationClient(
        service_url=app.config['ANONYMIZATION_SERVICE_URL'],
        anonymization_enabled=anonymization_enabled
    )
    
    if anonymization_enabled:
        app.logger.info(f"Client du service d'anonymisation initialisé avec l'URL: {app.config['ANONYMIZATION_SERVICE_URL']}")
        app.anonymization_service.test_anonymization_logging("Test d'initialisation du service d'anonymisation")
    else:
        app.logger.info("Service d'anonymisation désactivé - mode dégradé activé")

def init_slack_service(app):
    """Initialise le service Slack avec le contexte Flask."""
    global slack_service, SLACK_AVAILABLE
    
    try:
        # ✅ Importer l'instance globale existante
        from .slack_service import slack_service as _slack_service
        
        # ✅ Utiliser l'instance globale (ne pas en créer une nouvelle)
        slack_service = _slack_service
        
        # ✅ FORCER l'initialisation DANS le contexte Flask
        with app.app_context():
            slack_service._ensure_initialized()
        
        # Vérifier si au moins un webhook est configuré
        SLACK_AVAILABLE = bool(slack_service.webhook_url_leads or slack_service.webhook_url_monitoring)
        
        if SLACK_AVAILABLE:
            logger.info("✓ Service Slack initialisé avec succès")
            logger.info(f"  - webhook_url_leads: {'✓' if slack_service.webhook_url_leads else '✗'}")
            logger.info(f"  - webhook_url_monitoring: {'✓' if slack_service.webhook_url_monitoring else '✗'}")
        else:
            logger.warning("⚠️ Service Slack initialisé mais aucun webhook configuré")
            
    except Exception as e:
        logger.error(f"❌ Erreur initialisation service Slack: {e}", exc_info=True)
        SLACK_AVAILABLE = False
        slack_service = None

__all__ = [
    'AnonymizationClient',
    'init_anonymization_service',
    'QuizAnalysisService',
    'PromptData',
    'ImageService',
    'VideoService',
    'CookieService',
    'AudioService',
    'send_email',
    'send_purchase_confirmation_email',
    'AudioCapsuleService',
    'YouCanBookMeService',
    'AnalysisAccessModel',
    'slack_service',
    'SlackService',
    'init_slack_service',
    'SLACK_AVAILABLE',
    'AsyncAnalysisService',
    'PisteAccessService',
    'ConversationCoachService'
]