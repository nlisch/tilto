import os
from dotenv import load_dotenv
import logging
from typing import Dict, Any, Optional
from google.cloud import secretmanager
import json
from google.api_core import retry
import google.cloud.secretmanager_v1.types as types
from google.api_core import exceptions
import time
from flask import g

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chargement des variables d'environnement pour le développement
load_dotenv()

# CSP policy par défaut
DEFAULT_CSP_POLICY = {
    "default-src": ["'self'"],
    "script-src": [
        "'self'",
        "'unsafe-inline'",
        "'unsafe-eval'",
        "{nonce}" 
    ],
    "style-src": [
        "'self'",
        "'unsafe-inline'"
    ],
    "img-src": [
        "'self'",
        "data:"
    ],
    "font-src": [
        "'self'",
        "data:"
    ],
    "connect-src": [
        "'self'"
    ],
    "frame-src": [
        "'self'"
    ],
    "frame-ancestors": ["'none'"],
    "form-action": ["'self'"],
    "base-uri": ["'self'"],
    "object-src": ["'none'"]
}

# Fonction pour charger la CSP policy depuis un fichier JSON
def load_csp_policy_from_file(file_path: Optional[str] = None) -> dict:
    """
    Charge la CSP policy depuis un fichier JSON.
    Retourne la politique par défaut en cas d'erreur.
    
    Args:
        file_path: Chemin vers le fichier JSON contenant la CSP policy
                  Si None, utilise la valeur de la variable d'environnement CSP_POLICY_FILE
    
    Returns:
        dict: La CSP policy chargée ou la policy par défaut
    """
    if file_path is None:
        file_path = os.getenv('CSP_POLICY_FILE')
        if file_path and not os.path.isabs(file_path):
            file_path = os.path.join(os.path.dirname(__file__), file_path)
    
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"Fichier CSP policy introuvable: {file_path}")
        return DEFAULT_CSP_POLICY
    
    try:
        with open(file_path, 'r') as f:
            policy = json.load(f)
            logger.info(f"CSP policy chargée depuis {file_path}")
            return policy
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Erreur lors du chargement de la CSP policy depuis {file_path}: {e}")
        return DEFAULT_CSP_POLICY

def load_stripe_products_from_file(file_path: Optional[str] = None) -> dict:
    """
    Charge la configuration des produits Stripe depuis un fichier JSON.
    Retourne un dictionnaire vide en cas d'erreur.
    
    Args:
        file_path: Chemin vers le fichier JSON contenant la configuration des produits
                  Si None, utilise la valeur de la variable d'environnement STRIPE_PRODUCTS
    
    Returns:
        dict: La configuration des produits ou un dictionnaire vide
    """
    if file_path is None:
        file_path = os.getenv('STRIPE_PRODUCTS')
        if file_path and not os.path.isabs(file_path):
            file_path = os.path.join(os.path.dirname(__file__), file_path)
    
    if not file_path or not os.path.exists(file_path):
        logger.warning(f"Fichier de configuration des produits Stripe introuvable: {file_path}")
        return {}
    
    try:
        with open(file_path, 'r') as f:
            products = json.load(f)
            logger.info(f"Configuration des produits Stripe chargée depuis {file_path}")
            return products
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Erreur lors du chargement des produits Stripe depuis {file_path}: {e}")
        return {}

# Fonction commune pour gérer la CSP avec nonce
def get_csp_policy(csp_template: dict) -> dict:
    """
    Génère une CSP policy avec nonce si disponible
    
    Args:
        csp_template: Le template de CSP policy à utiliser
    
    Returns:
        dict: La CSP policy avec le nonce intégré si disponible
    """
    if not hasattr(g, 'nonce'):
        return csp_template
    
    # Copie profonde pour ne pas modifier le template
    policy = json.loads(json.dumps(csp_template))
    
    # Remplace {nonce} par la vraie valeur dans script-src
    if 'script-src' in policy:
        policy['script-src'] = [
            src.replace('{nonce}', f"'nonce-{g.nonce}'") if '{nonce}' in src else src 
            for src in policy['script-src']
        ]
    
    return policy

class BaseConfig:
    """Configuration de base commune à tous les environnements"""
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'  # Ou 'Strict' selon vos besoins
    REMEMBER_COOKIE_SAMESITE = 'Lax'  # Ou 'Strict'
    SESSION_PROTECTION = 'strong'
    TEMPLATES_AUTO_RELOAD = False
    CACHE_TYPE = 'null'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MYSQL_CHARSET = 'utf8mb4'
    IMAGES = {
    'ALLOWED_EXTENSIONS': {'png', 'jpg', 'jpeg', 'gif', 'webp'},
    'MAX_SIZE': (800, 800),
    'QUALITY': 85
    }
    VIDEOS = {
        'ALLOWED_EXTENSIONS': {'mp4', 'webm', 'mov', 'avi', 'mkv'},
        'MAX_SIZE_MB': 100,
    }
    STORAGE_BUCKET = os.environ.get('STORAGE_BUCKET', 'images-tilto')
    DATA_BUCKET = os.environ.get('DATA_BUCKET', 'tilto-data')
    CDN_URL = 'https://images.tilto.co'
    GCS_CACHE_CONTROL = 'public, max-age=31536000, immutable'
    # Configuration des types de fichiers autorisés pour l'upload
    ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'webm', 'm4a', 'ogg'}
    MAX_AUDIO_SIZE = 10 * 1024 * 1024  # 10 MB
    

    # Configuration des domaines
    PRIMARY_DOMAIN = 'tilto.co'
    REDIRECT_DOMAINS = ['tilto.ai', 'www.tilto.ai', 'www.tilto.co']

    # Configuration de l'API OpenAI pour Whisper
    OPENAI_API_KEY = None  # À remplir dans les configurations spécifiques
    
    # CSP policy par défaut
    CSP_POLICY_TEMPLATE = DEFAULT_CSP_POLICY

    STRIPE_PRODUCTS = {}

    #Statut Autoentrepreneur
    APPLY_VAT = False  # Mettre à True quand vous dépasserez le plafond
    VAT_RATE = 20.0   # Taux de TVA en pourcentage

    # Google Analytics
    GOOGLE_ANALYTICS_ID = None
    #Facebook
    FACEBOOK_PIXEL_ID = None
    #Google Ads
    GOOGLE_ADS_ID = None
    GOOGLE_ADS_CONVERSION_LABEL = None

    #Cloud Task
    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID')
    GCP_LOCATION = os.environ.get('GCP_LOCATION', 'europe-west1')  # Région de la queue
    CLOUD_TASKS_QUEUE = os.environ.get('CLOUD_TASKS_QUEUE', 'analysis-generation')  # Nom de la queue
    BASE_URL = os.environ.get('BASE_URL', 'https://tilto.co')

class DevelopmentConfig(BaseConfig):
    """Configuration pour l'environnement de développement"""
    
    def __init__(self):
        super().__init__()

        self.BASE_URL = os.getenv('BASE_URL', 'http://127.0.0.1:5000/')

        self.DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() in ('true', '1', 'yes')
        self.TESTING = False
        self.SECRET_KEY = os.getenv('SECRET_KEY')
        
        # Sécurité en développement
        self.SESSION_COOKIE_SECURE = False
        self.REMEMBER_COOKIE_SECURE = False
        self.TALISMAN_FORCE_HTTPS = False
        
        # Configuration MySQL directement dans l'objet config
        self.MYSQL_HOST = os.getenv('DB_HOST')
        self.MYSQL_PORT = int(os.getenv('DB_PORT', '3306'))
        self.MYSQL_USER = os.getenv('DB_USER')
        self.MYSQL_PASSWORD = os.getenv('DB_PASSWORD')
        self.MYSQL_DB = os.getenv('DB_NAME')
        
        # Configuration additionnelle MySQL dans un dictionnaire séparé
        self.MYSQL_CONFIG = {
            'pool_name': os.getenv('DB_POOL_NAME', 'dev-pool'),
            'pool_size': int(os.getenv('DB_POOL_SIZE', '5')),
            'pool_timeout': int(os.getenv('DB_POOL_TIMEOUT', '30')),
            'read_timeout': int(os.getenv('DB_READ_TIMEOUT', '10')),
            'write_timeout': int(os.getenv('DB_WRITE_TIMEOUT', '5'))
        }

        # STRIPE
        self.STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')
        self.STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
        self.STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET') 

        #Logo DEV
        self.LOGO_DEV_PUBLIC_KEY = os.getenv('LOGO_DEV_PUBLIC_KEY')

        #STRIPE PRODUCT
        self.STRIPE_PRODUCTS = load_stripe_products_from_file()
        logger.info(f"Configuration Stripe products chargée: {len(self.STRIPE_PRODUCTS)} produits")

        # CORS
        self.ALLOWED_ORIGINS = ['*']

        # CSP policy - chargée depuis un fichier JSON
        self.CSP_POLICY_TEMPLATE = load_csp_policy_from_file()
        
        # Définir correctement la fonction pour CSP
        self.TALISMAN_CONTENT_SECURITY_POLICY = self.CSP_POLICY_TEMPLATE
        
        # APIs
        self.ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
        self.ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4.5-20250929')
        self.ANTHROPIC_MAX_TOKENS = int(os.getenv('ANTHROPIC_MAX_TOKENS', '16384'))
        self.ANTHROPIC_TEMPERATURE = float(os.getenv('ANTHROPIC_TEMPERATURE', '0.7'))

        self.ENABLE_WEB_SEARCH = os.getenv('ENABLE_WEB_SEARCH')

        self.OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

        #Cloud Bucket audio
        self.QUIZ_AUDIO_BUCKET = os.getenv('tilto_quiz_audios_dev')

        # Configuration YouCanBookMe
        self.YOUCANBOOK_BASE_URL = os.getenv('YOUCANBOOK_BASE_URL', 'https://tilto.youcanbook.me')
        self.YOUCANBOOK_BOOKING_PAGE = os.getenv('YOUCANBOOK_BOOKING_PAGE', 'pack-clarte')
        self.YOUCANBOOK_SUBDOMAIN = os.getenv('YOUCANBOOK_SUBDOMAIN', 'tilto')
        self.YOUCANBOOK_WEBHOOK_SECRET = os.getenv('YOUCANBOOK_WEBHOOK_SECRET')

        # Google Analytics
        self.GOOGLE_ANALYTICS_ID = os.getenv('GOOGLE_ANALYTICS_ID')

        #Facebook
        self.FACEBOOK_PIXEL_ID = os.getenv('FACEBOOK_PIXEL_ID', '')

        #Google Ads
        self.GOOGLE_ADS_ID = os.getenv('GOOGLE_ADS_ID')
        self.GOOGLE_ADS_CONVERSION_LABEL = os.getenv('GOOGLE_ADS_CONVERSION_LABEL')

        # Configuration Slack
        self.SLACK_WEBHOOK_URL_LEADS = os.getenv('SLACK_WEBHOOK_URL_LEADS')
        self.SLACK_WEBHOOK_URL_MONITORING = os.getenv('SLACK_WEBHOOK_URL_MONITORING')
        self.SLACK_WEBHOOK_URL_CHAT = os.getenv('SLACK_WEBHOOK_URL_CHAT')
        self.SLACK_BOT_NAME = os.getenv('SLACK_BOT_NAME', 'tilto Bot')
        self.SLACK_BOT_EMOJI = os.getenv('SLACK_BOT_EMOJI', ':rocket:')

        # En dev, version basée sur timestamp pour développement
        self.ASSETS_VERSION = str(int(time.time()))

        #PRE_LAUNCH
        self.PRELAUNCH_MODE = os.getenv('PRELAUNCH_MODE', 'True').lower() in ('true', '1', 'yes')

        # Configuration Mail avec Brevo
        self.MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp-relay.brevo.com')
        self.MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
        self.MAIL_USE_TLS = True
        self.MAIL_USERNAME = os.getenv('MAIL_USERNAME')
        self.MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')  # Clé SMTP Brevo
        self.MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'contact@tilto.ai')

        # Log des paramètres MySQL
        logger.info(f"Configuration MySQL : HOST={self.MYSQL_HOST}, USER={self.MYSQL_USER}, DB={self.MYSQL_DB}")

        # Log des paramètres Slack
        if self.SLACK_WEBHOOK_URL_LEADS:
            logger.info("Configuration Slack chargée depuis les variables d'environnement")
        else:
            logger.warning("SLACK_WEBHOOK_URL_LEADS non trouvé dans les variables d'environnement")

        if self.SLACK_WEBHOOK_URL_MONITORING:
            logger.info("Configuration Slack chargée depuis les variables d'environnement")
        else:
            logger.warning("SLACK_WEBHOOK_URL_MONITORING non trouvé dans les variables d'environnement")

        if self.SLACK_WEBHOOK_URL_CHAT:
            logger.info("Configuration Slack chargée depuis les variables d'environnement")
        else:
            logger.warning("SLACK_WEBHOOK_URL_CHAT non trouvé dans les variables d'environnement")


class ProductionConfig(BaseConfig):
    """Configuration pour l'environnement de production"""

    def __init__(self):
        """Initialisation avec récupération de tous les secrets"""
        super().__init__()

        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        if not project_id:
            raise ValueError("GOOGLE_CLOUD_PROJECT environment variable is required in production")

        config_str = os.getenv('APP_CONFIG')
        if not config_str:
            raise ValueError("APP_CONFIG environment variable is required in production")
        
        try:
            logger.info("Loading production configuration...")
            config = json.loads(config_str)
            logger.info("Configuration JSON parsed successfully")
            self.BASE_URL = config.get('BASE_URL', 'https://tilto.co')
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse APP_CONFIG JSON: %s", str(e))
            logger.error("Received APP_CONFIG: %s", config_str)
            raise
        
        # Configuration générale
        self.DEBUG = False
        self.TESTING = False
        self.SECRET_KEY = config['SECRET_KEY']
        
        # Sécurité
        self.SESSION_COOKIE_SECURE = True
        self.REMEMBER_COOKIE_SECURE = True
        self.TALISMAN_FORCE_HTTPS = True

        # CSRF
        self.WTF_CSRF_TIME_LIMIT = 28800  # 8 heures
        self.WTF_CSRF_SSL_STRICT = True
        
        # Configuration de la CSP policy (depuis le fichier de config en production)
        if 'CSP_POLICY' in config:
            self.CSP_POLICY_TEMPLATE = config['CSP_POLICY']
            logger.info("CSP Policy template loaded from production config")
        else:
            # Si pas de CSP dans la config, essayer de charger depuis un fichier
            csp_file = config.get('CSP_POLICY_FILE')
            if csp_file:
                self.CSP_POLICY_TEMPLATE = load_csp_policy_from_file(csp_file)
                logger.info(f"CSP Policy template loaded from file: {csp_file}")
            else:
                logger.info("Aucune CSP policy spécifique trouvée, utilisation de la policy par défaut")
                # La valeur par défaut est déjà définie dans BaseConfig
        
        # Fonction pour générer la CSP policy avec nonce dynamique
        self.TALISMAN_CONTENT_SECURITY_POLICY = self.CSP_POLICY_TEMPLATE
        
        # Configuration MySQL
        connection_name = config['CLOUD_SQL_CONNECTION_NAME']
        self.MYSQL_UNIX_SOCKET = f"/cloudsql/{connection_name}"
        self.MYSQL_USER = config['DATABASE']['USER']
        self.MYSQL_PASSWORD = config['DATABASE']['PASSWORD']
        self.MYSQL_DB = config['DATABASE']['NAME']
        
        # Configuration du pool
        self.MYSQL_CONFIG = {
            'pool_name': config['DATABASE'].get('POOL_NAME', 'prod-pool'),
            'pool_size': config['DATABASE'].get('POOL_SIZE', 10),
            'pool_recycle': config['DATABASE'].get('POOL_RECYCLE', 300),
            'connect_timeout': config['DATABASE'].get('CONNECT_TIMEOUT', 10),
            'time_zone': config['DATABASE'].get('TIME_ZONE', '+00:00')
        }

        # STRIPE
        self.STRIPE_PUBLIC_KEY = config['STRIPE_PUBLIC_KEY']
        self.STRIPE_SECRET_KEY = config['STRIPE_SECRET_KEY']
        self.STRIPE_WEBHOOK_SECRET = config['STRIPE_WEBHOOK_SECRET']

        #Logo DEV
        self.LOGO_DEV_PUBLIC_KEY = config['LOGO_DEV_PUBLIC_KEY']

        #STRIPE PRODUCT
        self.STRIPE_PRODUCTS = config['STRIPE_PRODUCTS']
        
        logger.info(f"Configuration Stripe products chargée: {len(self.STRIPE_PRODUCTS)} produits")

        # CORS
        self.ALLOWED_ORIGINS = config['ALLOWED_ORIGINS']
        
        # APIs
        self.ANTHROPIC_API_KEY = config['ANTHROPIC_API_KEY']
        self.ANTHROPIC_MODEL = config.get('ANTHROPIC_MODEL', 'claude-sonnet-4.5-20250929')
        self.ANTHROPIC_MAX_TOKENS = int(config.get('ANTHROPIC_MAX_TOKENS', 16384))
        self.ANTHROPIC_TEMPERATURE = float(config.get('ANTHROPIC_TEMPERATURE', 0.7))


        self.ENABLE_WEB_SEARCH = config['ENABLE_WEB_SEARCH']
        self.OPENAI_API_KEY = config['OPENAI_API_KEY']

        # Cloud Storage Buckets
        self.STORAGE_BUCKET = config.get('STORAGE_BUCKET', self.STORAGE_BUCKET)
        self.DATA_BUCKET = config.get('DATA_BUCKET', 'tilto-data')
        self.QUIZ_AUDIO_BUCKET = config.get('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_prod')

        # Configuration YouCanBookMe
        self.YOUCANBOOK_BASE_URL = config.get('YOUCANBOOK_BASE_URL', 'https://tilto.youcanbook.me')
        self.YOUCANBOOK_BOOKING_PAGE = config.get('YOUCANBOOK_BOOKING_PAGE', 'pack-clarte')
        self.YOUCANBOOK_SUBDOMAIN = config.get('YOUCANBOOK_SUBDOMAIN', 'tilto')
        self.YOUCANBOOK_WEBHOOK_SECRET = config.get('YOUCANBOOK_WEBHOOK_SECRET')

        # Google Analytics
        self.GOOGLE_ANALYTICS_ID = config.get('GOOGLE_ANALYTICS_ID')
        if self.GOOGLE_ANALYTICS_ID:
            logger.info(f"Google Analytics ID chargé depuis la config: {self.GOOGLE_ANALYTICS_ID}")
        else:
            logger.warning("Google Analytics ID non trouvé dans la configuration")

        #Facebook
        self.FACEBOOK_PIXEL_ID = config.get('FACEBOOK_PIXEL_ID', '')

        #Google Ads
        self.GOOGLE_ADS_ID = config.get('GOOGLE_ADS_ID')
        self.GOOGLE_ADS_CONVERSION_LABEL = config.get('GOOGLE_ADS_CONVERSION_LABEL')

        # Configuration Slack
        self.SLACK_WEBHOOK_URL_LEADS = config.get('SLACK_WEBHOOK_URL_LEADS')
        self.SLACK_WEBHOOK_URL_MONITORING = config.get('SLACK_WEBHOOK_URL_MONITORING')
        self.SLACK_WEBHOOK_URL_CHAT = config.get('SLACK_WEBHOOK_URL_CHAT')
        self.SLACK_BOT_NAME = config.get('SLACK_BOT_NAME', 'tilto Bot')
        self.SLACK_BOT_EMOJI = config.get('SLACK_BOT_EMOJI', ':rocket:')

        # Version statique basée sur le BUILD_ID pour cache busting
        self.ASSETS_VERSION = os.environ.get('BUILD_ID', str(int(time.time())))
        logger.info(f"Assets version set to: {self.ASSETS_VERSION}")
        
        #PRE_LAUNCH
        self.PRELAUNCH_MODE = config.get('PRELAUNCH_MODE', 'True').lower() in ('true', '1', 'yes')

        # Configuration Mail avec Brevo (PRODUCTION)
        # ========================================
        self.MAIL_SERVER = config.get('MAIL_SERVER', 'smtp-relay.brevo.com')
        self.MAIL_PORT = int(config.get('MAIL_PORT', 587))
        self.MAIL_USE_TLS = True
        self.MAIL_USERNAME = config.get('MAIL_USERNAME')  # ✅ Parenthèses, pas crochets
        self.MAIL_PASSWORD = config.get('MAIL_PASSWORD')  # ✅ Clé SMTP Brevo
        self.MAIL_DEFAULT_SENDER = config.get('MAIL_DEFAULT_SENDER', 'contact@tilto.ai')
        self.BREVO_FROM_NAME = config.get('BREVO_FROM_NAME', 'Tilto')
        
        # Warning si configuration mail incomplète
        if not self.MAIL_USERNAME or not self.MAIL_PASSWORD:
            logger.warning("=" * 60)
            logger.warning("⚠️  CONFIGURATION MAIL INCOMPLÈTE")
            logger.warning("=" * 60)
            logger.warning(f"MAIL_USERNAME: {'✓ Configuré' if self.MAIL_USERNAME else '✗ MANQUANT'}")
            logger.warning(f"MAIL_PASSWORD: {'✓ Configuré' if self.MAIL_PASSWORD else '✗ MANQUANT'}")
            logger.warning("L'envoi d'emails sera désactivé jusqu'à configuration complète.")
            logger.warning("Ajoutez ces clés dans Secret Manager (app-config):")
            logger.warning("  - MAIL_USERNAME")
            logger.warning("  - MAIL_PASSWORD")
            logger.warning("=" * 60)
        else:
            logger.info("✓ Configuration mail Brevo chargée avec succès")
        
        if self.SLACK_WEBHOOK_URL_LEADS:
            logger.info("Configuration Slack chargée depuis la config de production")
        else:
            logger.warning("SLACK_WEBHOOK_URL_LEADS non trouvé dans la configuration de production")

        if self.SLACK_WEBHOOK_URL_MONITORING:
            logger.info("Configuration Slack chargée depuis la config de production")
        else:
            logger.warning("SLACK_WEBHOOK_URL_MONITORING non trouvé dans la configuration de production")

        if self.SLACK_WEBHOOK_URL_CHAT:
            logger.info("Configuration Slack chargée depuis la config de production")
        else:
            logger.warning("SLACK_WEBHOOK_URL_CHAT non trouvé dans la configuration de production")

        # Configuration OpenTelemetry pour Google Cloud Trace
        self.GOOGLE_CLOUD_PROJECT = os.getenv('GOOGLE_CLOUD_PROJECT')
        self.OTEL_SERVICE_NAME = config.get('OTEL_SERVICE_NAME', 'tilto-app')
        self.OTEL_SERVICE_VERSION = config.get('OTEL_SERVICE_VERSION', '1.0.0')

        # Log de la configuration
        logger.info(f"Configuration MySQL : SOCKET={self.MYSQL_UNIX_SOCKET}, USER={self.MYSQL_USER}, DB={self.MYSQL_DB}")
        logger.info("CSP Policy template loaded successfully")

        if 'GCP_SERVICE_ACCOUNT' in config:
            self.GCP_SERVICE_ACCOUNT = config['GCP_SERVICE_ACCOUNT']
            logger.info("GCP Service Account configuration loaded")

def get_config():
    """Retourne la configuration appropriée"""
    is_production = bool(os.getenv('GOOGLE_CLOUD_PROJECT'))
    logger.info(f"Environnement détecté : {'Production' if is_production else 'Développement'}")
    logger.info(f"GOOGLE_CLOUD_PROJECT: {os.getenv('GOOGLE_CLOUD_PROJECT', 'Non défini')}")
    
    if is_production:
        logger.info("Chargement de la configuration de production depuis Secret Manager")
        return ProductionConfig()
    else:
        logger.info("Chargement de la configuration de développement depuis les variables d'environnement")
        logger.info(f"Variables de dev détectées :")
        logger.info(f"DB_HOST: {os.getenv('DB_HOST', 'Non défini')}")
        logger.info(f"DB_NAME: {os.getenv('DB_NAME', 'Non défini')}")
        logger.info(f"DB_USER: {os.getenv('DB_USER', 'Non défini')}")
        return DevelopmentConfig()