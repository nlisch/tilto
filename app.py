from flask import Flask, request, flash, redirect, url_for, g, session, render_template, abort, jsonify, send_from_directory, current_app
from flask_limiter.errors import RateLimitExceeded
from flask_login import current_user
from config import get_config, get_csp_policy
from models import User, init_db, update_database
from routes import auth_bp, quiz_bp, quiz_analysis_bp, user_bp, image_bp, video_bp, token_bp, coupons_bp, cookie_bp, audio_bp, lead_bp, dashboard_bp, audio_capsule_bp, admin_bp, chat_bp, async_analysis_bp, help_requests_bp, seo_bp
import logging
import google.cloud.logging
from opentelemetry import trace
from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
import requests
from datetime import timedelta
import uuid
import time 
import os
import stripe
import sys
from datetime import datetime
from flask_babel import _, lazy_gettext as _l
import json
from flask_assets import Environment, Bundle
from memory_profiler import profile
from flask_compress import Compress
from flask_wtf.csrf import CSRFError 
from MySQLdb.cursors import DictCursor


# Import des extensions
from extensions import mysql, login_manager, csrf, oauth, babel, talisman, cors, limiter, mail
from services import init_anonymization_service, QuizAnalysisService, init_slack_service

# OPTIMISATION: Variable globale pour tracer le démarrage de l'application
APP_START_TIME = time.time()


from collections import defaultdict
import threading
_ip_request_counts = defaultdict(list)
_ip_lock = threading.Lock()

def is_ip_rate_limited(ip, max_requests=30, window_seconds=5):
    now = time.time()
    with _ip_lock:
        _ip_request_counts[ip] = [t for t in _ip_request_counts[ip] if now - t < window_seconds]
        _ip_request_counts[ip].append(now)
        return len(_ip_request_counts[ip]) > max_requests

# Configuration du logging
def setup_logging():
    # Formatter commun
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Configuration du handler console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Configuration des loggers spécifiques
    loggers = {
        'werkzeug': logging.INFO,
        'token_bp': logging.DEBUG,
        'coupons_bp': logging.DEBUG,
        'quiz_bp': logging.DEBUG,
        'auth_bp': logging.DEBUG,
        'user_bp': logging.DEBUG,
        'stripe': logging.INFO,
        '__main__': logging.DEBUG,
        'services.quiz_analysis': logging.INFO,
        'services.image_service': logging.INFO
    }

    # Configuration des loggers individuels
    for name, level in loggers.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        # Important: empêcher la propagation aux parents
        logger.propagate = False
        # Retirer les handlers existants
        logger.handlers = []
        # Ajouter notre handler
        logger.addHandler(console_handler)

    return logging.getLogger(__name__)
    
# Initialiser le logger principal
logger = setup_logging()

try:
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    logger.info("FlaskInstrumentor imported successfully")
    from opentelemetry.instrumentation.requests import RequestsInstrumentor  
    logger.info("RequestsInstrumentor imported successfully")
    TRACING_AVAILABLE = True
    logger.info("All OpenTelemetry packages imported successfully")
except ImportError as e:
    logger.error(f"OpenTelemetry import error - Module: {e.name if hasattr(e, 'name') else 'unknown'}, Error: {e}")
    logger.error(f"Full import error: {str(e)}")
    TRACING_AVAILABLE = False
except Exception as e:
    logger.error(f"Unexpected error during OpenTelemetry import: {str(e)}")
    TRACING_AVAILABLE = False


def setup_cloud_logging():
    """Configure Google Cloud Logging"""
    try:
        client = google.cloud.logging.Client()
        client.setup_logging()
        logger.info("Google Cloud Logging initialized successfully")
    except Exception as e:
        logger.warning(f"Could not initialize Google Cloud Logging: {e}")

def setup_detailed_tracing():
    """Configure detailed OpenTelemetry tracing"""
    if not TRACING_AVAILABLE:
        logger.warning("OpenTelemetry instrumentation packages not installed")
        return
        
    try:
        # Configuration du projet Google Cloud
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT')
        if not project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set, skipping tracing")
            return
        
        # Auto-instrumentation Flask
        FlaskInstrumentor().instrument()
        
        # Auto-instrumentation pour les requêtes HTTP sortantes
        RequestsInstrumentor().instrument()
        
        
        # Configuration du TracerProvider
        tracer_provider = TracerProvider()
        cloud_trace_exporter = CloudTraceSpanExporter(project_id=project_id)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(cloud_trace_exporter)
        )
        trace.set_tracer_provider(tracer_provider)
        
        logger.info(f"OpenTelemetry tracing initialized for project: {project_id}")
    except Exception as e:
        logger.error(f"Failed to initialize detailed tracing: {e}")

def track_event(event_type, extra_data=None):
    """
    Track un événement personnalisé (pour usage futur).
    
    Exemples:
        track_event('login', {'method': 'google'})
        track_event('quiz_complete', {'duration': 300})
    """
    try:
        if not current_user.is_authenticated:
            return
            
        ua = (request.user_agent.string or '').lower()
        device = 'mobile' if any(m in ua for m in ['iphone', 'android', 'mobile']) else 'desktop'
        
        session_id = session.get('_id', g.get('request_id', '')[:64])
        
        cursor = mysql.connection.cursor()
        cursor.execute('''
            INSERT INTO activity_logs 
            (user_id, session_id, event_type, page_path, device_type, extra_data)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (
            current_user.id,
            session_id,
            event_type[:50],
            request.path[:255],
            device,
            json.dumps(extra_data) if extra_data else None
        ))
        mysql.connection.commit()
        cursor.close()
        
    except Exception as e:
        logger.warning(f"Event tracking failed ({event_type}): {e}")

def get_locale():
    if 'lang_code' in session:
        return session['lang_code']
    return request.accept_languages.best_match(['fr', 'en'])

def needs_full_initialization():
    """Vérifie si une initialisation complète est nécessaire - VERSION OPTIMISÉE"""
    marker_file = '/tmp/db_initialized'
    
    # Éviter l'initialisation pendant le build Docker
    if os.environ.get('BUILDING_DOCKER', 'false').lower() == 'true':
        return False
    
    # OPTIMISATION CRITIQUE : Ne jamais forcer l'init en production
    if os.environ.get('GOOGLE_CLOUD_PROJECT'):
        # En production, initialiser seulement si explicitement demandé
        return os.environ.get('INIT_DB', 'false').lower() == 'true'
    
    # En développement, garder la logique existante
    if os.environ.get('INIT_DB', 'false').lower() == 'true':
        # Supprimer le marqueur pour forcer la réinitialisation
        if os.path.exists(marker_file):
            os.remove(marker_file)
        return True
    
    # Sinon, vérifier si déjà initialisé dans cette instance
    return not os.path.exists(marker_file)

def mark_as_initialized():
    """Marque la base comme initialisée"""
    with open('/tmp/db_initialized', 'w') as f:
        f.write('initialized')

def create_app():
    app = Flask(__name__, static_folder='static', static_url_path='/static')
    logger.info("Starting application initialization...")

    # Debug: vérifier les packages installés
    import pkg_resources
    installed_packages = [d.project_name for d in pkg_resources.working_set]
    otel_packages = [pkg for pkg in installed_packages if 'opentelemetry' in pkg.lower()]
    logger.info(f"OpenTelemetry packages found: {otel_packages}")
    
    try:
        config = get_config()
        app.config.from_object(config)
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        raise

     # Configuration des sessions    
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
    app.config['SESSION_REFRESH_EACH_REQUEST'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = 28800  # 8 heures (cohérent avec la session)
    app.config['WTF_CSRF_SSL_STRICT'] = True  # Force HTTPS en production

    # OPTIMISATION: Initialisation des extensions critiques seulement
    mysql.init_app(app)
    app.mysql = mysql
    login_manager.init_app(app)
    csrf.init_app(app)
    oauth.init_app(app)

    # OPTIMISATION: Services non-critiques initialisés à la demande ou différés
    try:
        init_anonymization_service(app)
        init_slack_service(app)
    except Exception as e:
        logger.warning(f"Non-critical service initialization failed: {e}")
    
    app.config['DEFAULT_LANGUAGE'] = 'fr'

    # ====== OPTION 1: Configuration Flask-Assets SANS auto-build ======
    # Les assets sont buildés pendant le déploiement, pas au runtime
    
    assets = Environment(app)
    
    # Bundle CSS principal
    css_main = Bundle(
        'css/styles.css',
        filters='cssmin',
        output='dist/css/main.min.css'
    )

    # Bundle JS principal (utilitaires communs)
    js_common = Bundle(
        'js/language-selector.js',
        'js/cookie-consent.js',
        'js/utils.js',
        'js/change-password.js',
        filters='jsmin',
        output='dist/js/common.min.js'
    )
    
    # Bundle pour le quiz
    js_quiz = Bundle(
        'js/quiz-script-new.js',
        filters='jsmin',
        output='dist/js/quiz.min.js'
    )
    
    # Bundle pour la génération d'analyse
    js_async_analysis = Bundle(
        'js/async-analysis.js',
        filters='jsmin',
        output='dist/js/async_analysis.min.js'
    )
    
    # Enregistrement des bundles
    assets.register('css_main', css_main)
    assets.register('js_common', js_common)
    assets.register('js_quiz', js_quiz)
    assets.register('js_async_analysis', js_async_analysis)
    
    # Configuration pour OPTION 1
    is_production = bool(app.config.get('GOOGLE_CLOUD_PROJECT'))
    
    # En développement: auto-build activé pour le confort
    # En production: PAS d'auto-build, les fichiers sont déjà buildés
    app.config['ASSETS_DEBUG'] = not is_production
    app.config['ASSETS_AUTO_BUILD'] = not is_production  # True en dev, False en prod
    
    # Vérifier que les assets buildés existent en production
    if is_production:
        required_assets = [
            'static/dist/css/main.min.css',
            'static/dist/js/common.min.js',
            'static/dist/js/quiz.min.js',
            'static/dist/js/async_analysis.min.js'
        ]
        
        missing_assets = [asset for asset in required_assets if not os.path.exists(asset)]
        
        if missing_assets:
            logger.error(f"❌ Missing built assets in production: {missing_assets}")
            logger.error("Assets should be built during deployment!")
            # Ne pas faire échouer le démarrage, mais logger l'erreur
        else:
            logger.info("✅ All required assets found in production")

    try:
        if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
            mail.init_app(app)
            logger.info("✓ Flask-Mail initialisé avec succès")
        else:
            logger.warning("⚠️ Flask-Mail NON initialisé - Configuration incomplète")
            logger.warning("Les fonctionnalités d'envoi d'emails seront désactivées")
    except Exception as e:
        # Protection contre tout problème d'init mail
        logger.error(f"❌ Erreur lors de l'initialisation de Flask-Mail : {e}")
        logger.warning("L'application continue sans support email")

    # Configuration de Flask-Babel
    babel.init_app(app, locale_selector=get_locale)
    app.config['BABEL_DEFAULT_LOCALE'] = 'fr'
    app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'

    # Ajustez la configuration existante de feature_policy dans talisman.init_app
    talisman.init_app(app,
        force_https=True,
        strict_transport_security=True,
        session_cookie_secure=True,
        content_security_policy=None,  # Set to None initially
        content_security_policy_nonce_in=['script-src'],
        frame_options='DENY',
        frame_options_allow_from=None,
        referrer_policy='strict-origin-when-cross-origin')

    cors.init_app(app, resources={
        "/api/*": {
            "origins": app.config['ALLOWED_ORIGINS'],
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": ["Content-Type", "Authorization", "Stripe-Signature"]
        },
        "/stripe-webhook": {
            "origins": ["*"],
            "methods": ["POST"],
            "allow_headers": ["*"]
        },
        "/dashboard/product/*/booking-webhook": {
            "origins": ["*"], 
            "methods": ["POST"],
            "allow_headers": ["Content-Type", "X-YCBM-Signature"]
        },
        "/setup_two_factor": {
            "origins": app.config['ALLOWED_ORIGINS'],
            "methods": ["GET", "POST"],
            "allow_headers": ["Content-Type", "Authorization"]
        },
        "/two_factor": {
            "origins": app.config['ALLOWED_ORIGINS'],
            "methods": ["GET", "POST"],
            "allow_headers": ["Content-Type", "Authorization"]
        },
        "/cookie/*": {
            "origins": ["*"],
            "methods": ["GET", "POST"],
            "allow_headers": ["Content-Type", "X-CSRFToken"]
        }
    })

    limiter.init_app(app)

    # Configuration de paiement stripe
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = _('Veuillez vous connecter pour accéder à cette page.')
    login_manager.login_message_category = 'error'
    login_manager.session_protection = "strong"

    # Compression
    Compress(app)
    
    # Configuration compression
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/xml',
        'application/json', 'application/javascript'
    ]

    @app.template_global()
    def versioned_asset_url(bundle_name):
        """Génère l'URL versionnée d'un bundle Flask-Assets"""
        try:
            # Mapping des bundles vers leurs fichiers de sortie
            bundle_mapping = {
                'css_main': 'dist/css/main.min.css',
                'js_common': 'dist/js/common.min.js',
                'js_quiz': 'dist/js/quiz.min.js',
                'js_async_analysis': 'dist/js/async_analysis.min.js'
            }
            
            if bundle_name in bundle_mapping:
                filename = bundle_mapping[bundle_name]
                version = app.config.get('ASSETS_VERSION', '1')
                return url_for('static', filename=filename, v=version)
            
            logger.warning(f"Bundle '{bundle_name}' not found")
            return ""
        except Exception as e:
            logger.error(f"Error generating versioned asset URL for {bundle_name}: {e}")
            return ""

    @app.before_request
    def block_scanners():
        # Bloquer les extensions inutiles
        blocked_extensions = ['.php', '.asp', '.aspx', '.jsp', '.cgi', '.env', '.git']
        if any(request.path.endswith(ext) for ext in blocked_extensions):
            return '', 204  # Réponse vide, pas de tracking, rien en DB
        
        # Bloquer les paths WordPress
        blocked_paths = ['/wp-admin', '/wp-content', '/wp-includes', '/xmlrpc']
        if any(request.path.startswith(p) for p in blocked_paths):
            return '', 204
        ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
        if is_ip_rate_limited(ip):
            logger.warning(f"IP flood bloquée: {ip} - {request.path}")
            return '', 429

    # OPTIMISATION: Logging minimal et conditionnel pour les requêtes
    @app.before_request
    def log_request_start():
        # Timer global pour toute la requête
        g.request_start_time = time.time()
        g.request_id = str(uuid.uuid4())[:8]  # ID court pour les logs
        
        # Log de début de requête (pour toutes les requêtes sauf statiques)
        if not (request.path.startswith('/static') or request.path == '/favicon.ico'):
            logger.info(f"[{g.request_id}] START REQUEST: {request.method} {request.path}")

    @app.before_request
    def before_request():
        # Timer pour before_request spécifiquement
        before_start = time.time()
        
        # OPTIMISATION CRITIQUE : Sortir immédiatement pour les fichiers statiques
        if request.path.startswith('/static') or request.path == '/favicon.ico':
            return

        # CORRECTION CSRF : REDIRECTION DE DOMAINE EN PREMIER
        # Faire ça AVANT toute création de session/CSRF/nonce
        current_host = request.host.lower()
        primary_domain = app.config.get('PRIMARY_DOMAIN', 'tilto.co')
        redirect_domains = app.config.get('REDIRECT_DOMAINS', [])
        
        if current_host in redirect_domains:
            logger.info(f"Domain redirect needed from {current_host} to {primary_domain}")
            # Préserver le protocole (http/https)
            scheme = 'https' if request.is_secure else 'http'
            
            # Construire l'URL complète
            if request.query_string:
                new_url = f"{scheme}://{primary_domain}{request.path}?{request.query_string.decode()}"
            else:
                new_url = f"{scheme}://{primary_domain}{request.path}"
            
            logger.info(f"Redirecting from {current_host} to {primary_domain}: {request.path}")
            return redirect(new_url, code=301)

        # Rendre les sessions permanentes
        session.permanent = True
        if '_id' not in session:
            session['_id'] = str(uuid.uuid4())

        logger.info("Starting before_request processing")
        
        # Génération des IDs (optimisé - une seule fois)
        step_start = time.time()
        request_id = str(uuid.uuid4())
        g.request_id = request_id
        g.nonce = uuid.uuid4().hex
        logger.info(f"[{g.request_id}] ID generation: {(time.time() - step_start)*1000:.1f}ms")
        
        # Gestion de la langue
        step_start = time.time()
        g.lang_code = get_locale()
        logger.info(f"[{g.request_id}] Locale handling: {(time.time() - step_start)*1000:.1f}ms")
        
        # NOUVEAU : Bypass du mode pré-lancement avec paramètre secret (SÉCURISÉ)
        bypass_key = request.args.get('bypass')
        if bypass_key and bypass_key == os.environ.get('PRELAUNCH_BYPASS_KEY'):
            # SÉCURITÉ : Créer un token unique pour cette session spécifique
            import secrets
            unique_bypass_token = secrets.token_hex(32)
            
            session['prelaunch_bypass_token'] = unique_bypass_token
            session['prelaunch_bypass_timestamp'] = time.time()
            session['prelaunch_bypass_ip'] = request.remote_addr
            session.permanent = True
            
            flash('Mode admin activé pour cette session', 'success')
            
            # Redirection sans le paramètre bypass
            clean_url = request.base_url
            if request.args:
                other_params = {k: v for k, v in request.args.items() if k != 'bypass'}
                if other_params:
                    from urllib.parse import urlencode
                    clean_url += '?' + urlencode(other_params)
            
            return redirect(clean_url)
        
        logger.info(f"[{g.request_id}] Bypass check: {(time.time() - step_start)*1000:.1f}ms")
            
        # Protection mode pré-lancement - LOGIQUE CORRIGÉE
        step_start = time.time()
        if app.config.get('PRELAUNCH_MODE', False):
            # Vérifier les autorisations dans l'ordre de priorité
            access_granted = False
            
            # 1. Admin complètement authentifié (priorité max)
            if (current_user.is_authenticated and 
                current_user.user_status == 'admin' and 
                session.get('two_factor_authenticated')):
                access_granted = True
                logger.debug(f"[{g.request_id}] Access granted: Admin with 2FA")
            
            # 2. Bypass temporaire valide
            elif session.get('prelaunch_bypass_token'):
                bypass_timestamp = session.get('prelaunch_bypass_timestamp')
                bypass_ip = session.get('prelaunch_bypass_ip')
                
                # Vérifications de sécurité du bypass
                if bypass_timestamp and bypass_ip:
                    # Vérifier l'expiration (1 heure seulement pour plus de sécurité)
                    bypass_age = time.time() - bypass_timestamp
                    ip_matches = bypass_ip == request.remote_addr
                    
                    if bypass_age < 3600 and ip_matches:  # 1 heure + même IP
                        access_granted = True
                        logger.debug(f"[{g.request_id}] Access granted: Valid bypass token")
                    else:
                        # Nettoyer le bypass expiré ou compromis
                        session.pop('prelaunch_bypass_token', None)
                        session.pop('prelaunch_bypass_timestamp', None)
                        session.pop('prelaunch_bypass_ip', None)
                        if not ip_matches:
                            logger.warning(f"[{g.request_id}] Bypass invalidated: IP mismatch")
                        else:
                            logger.info(f"[{g.request_id}] Bypass expired after {bypass_age/3600:.1f}h")
                        flash('Session admin expirée', 'warning')
            
            # 3. Si aucun accès accordé, appliquer les restrictions
            if not access_granted:
                # Liste des URLs autorisées en mode pré-lancement
                allowed_paths = [
                    '/',
                    '/health',
                    '/set-language',
                    '/cookie',
                    '/robots.txt',
                    '/sitemap.xml',
                    '/politique-de-confidentialite',
                    '/cookie-policy',
                    '/mentions-legales',
                    '/about',
                    '/orientation',
                    '/reconversion',
                    '/get_questions_homepage/',
                    '/startup-metrics'
                ]
                
                # URLs admin toujours autorisées
                admin_paths = [
                    '/setup_two_factor',
                    '/two_factor',
                    '/verify_setup',
                    '/reset_2fa'
                ]
                
                # Vérifier si l'URL actuelle est autorisée
                current_path = request.path
                
                # Vérifier si l'accès est autorisé
                path_allowed = (
                    current_path in allowed_paths or
                    current_path in admin_paths or
                    current_path.startswith('/cookie/') or
                    current_path.startswith('/lead/')
                )
                
                if not path_allowed:
                    logger.info(f"[{g.request_id}] Access denied in prelaunch mode: {current_path}")
                    if current_path != '/':
                        flash('Cette fonctionnalité sera bientôt disponible !', 'info')
                        return redirect(url_for('auth.home'))
        else:
            logger.debug(f"[{g.request_id}] Prelaunch access granted for: {request.path}")
        logger.info(f"[{g.request_id}] Prelaunch check: {(time.time() - step_start)*1000:.1f}ms")
        
        # OPTIMISATION : Logging minimal et conditionnel
        step_start = time.time()
        # Ne log que les requêtes importantes ou en cas d'erreur
        should_log = (
            request.method != 'GET' or
            '/stripe-webhook' in request.path or
            '/admin' in request.path or
            current_user.is_authenticated
        )
        
        if should_log:
            logger.info(f"[{request_id}] {request.method} {request.path}")
            
            # Log des headers seulement pour les webhooks et admin
            if '/stripe-webhook' in request.path:
                logger.debug('Webhook headers debug:')
                for header, value in request.headers.items():
                    logger.debug(f"{header}: {value}")
                logger.debug('Method: %s', request.method)
                logger.debug('URL: %s', request.url)
                logger.debug("Webhook body length: %d", len(request.get_data()))
            
            # Log du body seulement pour les requêtes non-sensibles
            if (request.method in ['POST', 'PUT'] and 
                not any(path in request.path for path in ['/login', '/signup', '/password'])):
                try:
                    body = request.get_json(silent=True)
                    if body:
                        safe_body = {
                            k: v if k not in ['password', 'token', 'key'] else '*****'
                            for k, v in body.items()
                        }
                        logger.debug(f"[{request_id}] Body: {safe_body}")
                except Exception as e:
                    logger.warning(f"[{request_id}] Could not parse JSON body: {e}")
        logger.info(f"[{g.request_id}] Logging setup: {(time.time() - step_start)*1000:.1f}ms")
        
        # Vérification du consentement aux cookies (optimisé)
        step_start = time.time()
        if not request.path.startswith('/cookie'):
            # Initialisation des variables par défaut (plus rapide)
            cookie_consent = session.get('cookie_consent')
            if cookie_consent:
                g.can_use_analytics = cookie_consent.get('analytics', False)
                g.can_use_marketing = cookie_consent.get('marketing', False)
                g.can_use_preferences = cookie_consent.get('preferences', False)
            else:
                g.can_use_analytics = False
                g.can_use_marketing = False
                g.can_use_preferences = False
        logger.info(f"[{g.request_id}] Cookie consent: {(time.time() - step_start)*1000:.1f}ms")
        
        # Log du temps total de before_request
        total_before_time = (time.time() - before_start) * 1000
        logger.info(f"[{g.request_id}] before_request completed: {total_before_time:.1f}ms")

    @app.after_request
    def log_request_end(response):
        if hasattr(g, 'request_start_time') and hasattr(g, 'request_id'):
            total_duration = (time.time() - g.request_start_time) * 1000
            
            # Log pour toutes les requêtes non-statiques
            if not (request.path.startswith('/static') or request.path == '/favicon.ico'):
                logger.info(f"[{g.request_id}] END REQUEST: {request.method} {request.path} - {total_duration:.1f}ms - Status: {response.status_code}")
                
                # Alerte spéciale pour les requêtes très lentes
                if total_duration > 5000:  # Plus de 5 secondes
                    logger.error(f"[{g.request_id}] VERY SLOW REQUEST: {total_duration:.1f}ms for {request.method} {request.path}")
                elif total_duration > 1000:  # Plus de 1 seconde
                    logger.warning(f"[{g.request_id}] SLOW REQUEST: {total_duration:.1f}ms for {request.method} {request.path}")
        
        return response

    @app.after_request
    def track_activity(response):
        """Track les page views de tous les visiteurs"""
        
        # Tracker uniquement les vraies pages HTML
        if 'text/html' not in response.content_type:
            return response

        if response.status_code in (204, 404):
            # Garder seulement les vraies pages de l'app
            real_paths = ['/dashboard', '/quiz', '/bilan', '/profil', '/user', '/token', '/audio']
            if not any(request.path.startswith(p) for p in real_paths):
                return response

        skip_paths = ['/static', '/favicon.ico', '/health', '/robots.txt', '/startup-metrics', '/cookie', '/obtiens-tes-smart-contacts', '/.well-known', '/meta.json', '/xmlrpc.php']
        
        if not any(request.path.startswith(p) for p in skip_paths):
            
            try:
                ua = (request.user_agent.string or '').lower()

                bot_keywords = ['bot', 'crawler', 'spider', 'scraper', 'curl', 'python-requests', 'wget', 'headless', 'phantom', 'selenium']
                if any(kw in ua for kw in bot_keywords):
                    return response

                device = 'mobile' if any(m in ua for m in ['iphone', 'android', 'mobile']) else 'desktop'
                
                raw_session_id = session.get('_id') or g.get('request_id', '')
                session_id = str(raw_session_id)[:128]
                
                if response.status_code in (301, 302, 303, 307, 308):
                    return response
                extra = {}
                extra['status_code'] = response.status_code

                if session.get('bilan_flash_slug'):
                    extra['bilan_slug'] = session.get('bilan_flash_slug')
                    extra['bilan_source'] = session.get('bilan_flash_meta', {}).get('source', '')
                    extra['bilan_variant'] = session.get('bilan_flash_meta', {}).get('variant', '')
                    extra['bilan_campaign'] = session.get('bilan_flash_meta', {}).get('campaign', '')

                if session.get('smart_contact_slug'):
                    extra['slug_id'] = session.get('smart_contact_slug')
                    meta = session.get('smart_contact_meta', {})
                    if meta:
                        extra.update(meta)

                if request.path.startswith('/dashboard') and current_user.is_authenticated:
                    if session.get('dashboard_state'):
                        extra['dashboard_state'] = session.get('dashboard_state')

                cursor = mysql.connection.cursor()
                cursor.execute('''
                    INSERT INTO activity_logs 
                    (user_id, session_id, event_type, page_path, referrer, device_type, extra_data)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                ''', (
                    current_user.id if current_user.is_authenticated else None,
                    session_id,
                    'page_view',
                    request.path[:255],
                    (request.referrer or '')[:500],
                    device,
                    json.dumps(extra) if extra else None
                ))
                mysql.connection.commit()
                cursor.close()
                
            except Exception as e:
                logger.warning(f"[TRACKING] ❌ Activity tracking failed: {e}")
        
        return response

    setup_detailed_tracing()
# Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(quiz_analysis_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(image_bp)
    app.register_blueprint(video_bp)
    app.register_blueprint(token_bp)
    app.register_blueprint(coupons_bp)
    app.register_blueprint(cookie_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(lead_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(audio_capsule_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(async_analysis_bp)
    app.register_blueprint(help_requests_bp)
    app.register_blueprint(seo_bp)


    @app.template_filter('status_badge_class')
    def status_badge_class(status):
        """Retourne la classe CSS pour les badges de statut de lead"""
        classes = {
            'new': 'badge-primary',
            'contacted': 'badge-info',
            'qualified': 'badge-success',
            'converted': 'badge-success',
            'lost': 'badge-danger',
            None: 'badge-secondary'
        }
        return classes.get(status, 'badge-secondary')

    @app.context_processor
    def inject_cookie_consent():
        return {
            'cookie_consent': session.get('cookie_consent', None)
        }

    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    @app.context_processor
    def inject_user_products():
        """OPTIMISATION ULTRA: Injecter des informations sur les produits - VERSION OPTIMISÉE"""
        start_time = time.time()
        request_id = getattr(g, 'request_id', 'unknown')
        
        logger.info(f"[{request_id}] Starting inject_user_products")
        
        # OPTIMISATION CRITIQUE : Early return pour utilisateurs non connectés
        # Évite toute la logique DB/cache pour 99% du trafic homepage
        if not current_user.is_authenticated:
            logger.info(f"[{request_id}] inject_user_products (not authenticated - early return): {(time.time() - start_time)*1000:.1f}ms")
            return {'user_products': []}

        logger.info(f"[{request_id}] User authenticated: {current_user.id}")

        # Cache plus agressif - 1 heure au lieu de 15 minutes
        cache_step_start = time.time()
        cache_key = f"user_products_{current_user.id}"
        cache_timestamp_key = f"{cache_key}_timestamp"
        
        # Vérifier si on a des données en cache (valides 1 heure maintenant)
        cached_products = session.get(cache_key)
        cached_timestamp = session.get(cache_timestamp_key)
        
        if cached_products is not None and cached_timestamp:
            # Cache valide pendant 1 heure (3600 secondes) au lieu de 15 minutes
            if time.time() - cached_timestamp < 3600:
                logger.info(f"[{request_id}] Cache hit for user {current_user.id}")
                
                context = {'user_products': cached_products}
                
                # Reconstituer has_pack_clarte depuis le cache
                for product in cached_products:
                    if product[1] and ('Pack Clarté' in product[1] or 'Pack Clarte' in product[1]):
                        context['has_pack_clarte'] = True
                        context['pack_clarte_id'] = product[0]
                        break
                
                logger.info(f"[{request_id}] inject_user_products (cached): {(time.time() - start_time)*1000:.1f}ms")
                return context
        
        logger.info(f"[{request_id}] Cache miss, querying database")
        logger.info(f"[{request_id}] Cache check: {(time.time() - cache_step_start)*1000:.1f}ms")

        # Initialiser le contexte par défaut
        context = {'user_products': []}

        # Requête base de données avec gestion d'erreur améliorée
        db_step_start = time.time()
        cursor = None
        
        try:
            cursor = mysql.connection.cursor()
            logger.info(f"[{request_id}] Database cursor created: {(time.time() - db_step_start)*1000:.1f}ms")
            
            # Vérification d'existence des tables avec requête combinée plus rapide
            table_check_start = time.time()
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = DATABASE() AND table_name = 'orders') as orders_exist,
                    (SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = DATABASE() AND table_name = 'product_catalog') as catalog_exist
            """)
            
            table_counts = cursor.fetchone()
            orders_exist = table_counts[0] > 0 if table_counts else False
            product_catalog_exist = table_counts[1] > 0 if table_counts else False
            
            logger.info(f"[{request_id}] Table existence check: {(time.time() - table_check_start)*1000:.1f}ms")
            
            if orders_exist and product_catalog_exist:
                # Requête optimisée avec LIMIT pour éviter les gros résultats
                query_start = time.time()
                cursor.execute('''
                    SELECT 
                        pc.product_id, 
                        pc.product_name, 
                        pc.product_type
                    FROM orders o
                    JOIN order_product op ON o.order_id = op.order_id
                    JOIN product_catalog pc ON op.product_id = pc.product_id
                    WHERE o.user_id = %s AND o.status = 'paid'
                    ORDER BY o.created_at DESC
                    LIMIT 50
                ''', (current_user.id,))
                
                results = cursor.fetchall()
                query_time = (time.time() - query_start) * 1000
                logger.info(f"[{request_id}] Database query executed: {query_time:.1f}ms, {len(results) if results else 0} results")
                
                if query_time > 1000:
                    logger.warning(f"[{request_id}] SLOW DATABASE QUERY in inject_user_products: {query_time:.1f}ms")
                
                if results:
                    context['user_products'] = results
                    
                    # Cache avec timestamp - cache plus long
                    session[cache_key] = results
                    session[cache_timestamp_key] = time.time()
                    logger.info(f"[{request_id}] Database results cached for user {current_user.id} (1h TTL)")
                    
                    # Pour la compatibilité avec le code existant
                    for product in results:
                        if product[1] and ('Pack Clarté' in product[1] or 'Pack Clarte' in product[1]):
                            context['has_pack_clarte'] = True
                            context['pack_clarte_id'] = product[0]
                            break
            else:
                logger.warning(f"[{request_id}] Required tables missing: orders={orders_exist}, product_catalog={product_catalog_exist}")
                
        except Exception as e:
            error_time = (time.time() - db_step_start) * 1000
            logger.error(f"[{request_id}] Error in inject_user_products after {error_time:.1f}ms: {str(e)}")
            
            # En cas d'erreur, nettoyer le cache défaillant
            session.pop(cache_key, None)
            session.pop(cache_timestamp_key, None)
            
        finally:
            if cursor:
                cursor.close()
                close_time = (time.time() - db_step_start) * 1000
                logger.info(f"[{request_id}] Database operations completed: {close_time:.1f}ms")
        
        total_time = (time.time() - start_time) * 1000
        logger.info(f"[{request_id}] inject_user_products completed: {total_time:.1f}ms")
        
        if total_time > 1000:
            logger.warning(f"[{request_id}] SLOW inject_user_products: {total_time:.1f}ms")
        
        return context

    @app.context_processor
    def inject_tracking_ids():
        return {
            'GOOGLE_ANALYTICS_ID':         app.config.get('GOOGLE_ANALYTICS_ID'),
            'GOOGLE_ADS_ID':               app.config.get('GOOGLE_ADS_ID', ''),
            'GOOGLE_ADS_CONVERSION_LABEL': app.config.get('GOOGLE_ADS_CONVERSION_LABEL', ''),
            'FACEBOOK_PIXEL_ID':           app.config.get('FACEBOOK_PIXEL_ID', ''),
        }

    @app.before_first_request
    def test_db_connection():
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                cursor = mysql.connection.cursor()
                cursor.execute('SELECT 1')
                cursor.close()
                logger.info("Database connection successful")
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Database connection failed after {max_retries} attempts: {e}")
                    raise
                logger.warning(f"Database connection attempt {attempt + 1} failed: {e}, retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)

    with app.app_context():
        try:
            # Appliquer les rate limits
            limiter.limit("130 per minute")(app.view_functions['auth.login'])
            limiter.limit("130 per minute")(app.view_functions['auth.signup'])
            limiter.limit("300 per minute")(app.view_functions['quiz.get_cities'])
            limiter.limit("1000 per hour")(app.view_functions['quiz.update_quiz_history'])
            logger.info("Rate limits applied successfully")
            
            # Rate limit global par IP
            @limiter.request_filter
            def exempt_local():
                """Exempter les IPs locales de développement"""
                return request.remote_addr in ['127.0.0.1', '::1']
            
            logger.info("Rate limits appliqués avec succès")

            if not os.environ.get('BUILDING_DOCKER'):
                if needs_full_initialization():
                    logger.info("Initialisation complète demandée")
                    init_db(force_init=True)
                    update_database()
                    mark_as_initialized()
                else:
                    logger.info("Instance déjà initialisée - démarrage rapide")
                    init_db(force_init=False)
            else:
                logger.info("Skip DB init - Building assets")
            
        except KeyError as e:
            logger.error(f"Endpoint not found pour appliquer le rate limit: {e}")
            raise

    @app.template_filter('date')
    def date_filter(value, format='%Y-%m-%d %H:%M:%S'):
        if isinstance(value, datetime):
            return value.strftime(format)
        return value

    @login_manager.user_loader
    def load_user(user_id):
        start_time = time.time()
        request_id = getattr(g, 'request_id', 'unknown')
        logger.debug(f"[{request_id}] Loading user: {user_id}")
        cursor = mysql.connection.cursor()
        try:
            cursor.execute("""
                SELECT user_id, username, email, user_status, country_code, 
                    two_factor_secret, nb_accompagnement, firstname, lastname
                FROM users 
                WHERE user_id = %s
            """, (user_id,))
            user = cursor.fetchone()
            load_time = (time.time() - start_time) * 1000
            
            if user:
                logger.debug(f"[{request_id}] User found: {user[1]} in {load_time:.1f}ms")
                return User(
                    user_id=user[0], 
                    username=user[1], 
                    email=user[2], 
                    user_status=user[3],
                    country_code=user[4],
                    two_factor_secret=user[5],
                    nb_accompagnement=user[6],
                    firstname=user[7],
                    lastname=user[8]
                )
            logger.debug(f"[{request_id}] User not found in {load_time:.1f}ms")
            return None
        except Exception as e:
            load_time = (time.time() - start_time) * 1000
            logger.error(f"[{request_id}] Error loading user in {load_time:.1f}ms: {e}")
            return None
        finally:
            cursor.close()

    # OPTIMISATION: Route de monitoring du démarrage
    @app.route('/startup-metrics')
    def startup_metrics():
        """Diagnostics détaillés du démarrage pour identifier les cold starts"""
        
        current_time = time.time()
        app_uptime = current_time - APP_START_TIME
        
        # Récupérer les temps du container si disponibles
        container_startup = os.environ.get('CONTAINER_STARTUP_TIME')
        container_prep = os.environ.get('CONTAINER_PREP_TIME')
        
        metrics = {
            'timestamps': {
                'container_start': container_startup,
                'app_start': APP_START_TIME,
                'current': current_time,
                'request_time': datetime.now().isoformat()
            },
            'durations': {
                'app_uptime_seconds': round(app_uptime, 3),
                'container_prep_seconds': container_prep
            },
            'environment': {
                'is_production': bool(os.getenv('GOOGLE_CLOUD_PROJECT')),
                'project_id': os.getenv('GOOGLE_CLOUD_PROJECT'),
                'service': os.getenv('K_SERVICE'),
                'revision': os.getenv('K_REVISION'),
                'configuration': os.getenv('K_CONFIGURATION')
            }
        }
        
        # Calculs de performance
        if container_startup and container_prep:
            try:
                container_start_float = float(container_startup)
                prep_time_float = float(container_prep)
                
                total_cold_start = current_time - container_start_float
                flask_init_time = APP_START_TIME - container_start_float - prep_time_float
                
                metrics['performance'] = {
                    'total_cold_start_seconds': round(total_cold_start, 3),
                    'container_prep_seconds': round(prep_time_float, 3),
                    'flask_init_seconds': round(flask_init_time, 3),
                    'app_uptime_seconds': round(app_uptime, 3)
                }
                
                # Alertes de performance
                alerts = []
                if total_cold_start > 10:
                    alerts.append('COLD_START_VERY_SLOW')
                elif total_cold_start > 5:
                    alerts.append('COLD_START_SLOW')
                    
                if flask_init_time > 3:
                    alerts.append('FLASK_INIT_SLOW')
                    
                metrics['alerts'] = alerts
                
            except ValueError:
                metrics['error'] = 'Invalid container timing data'
        
        # Test de connectivité actuel
        db_test_start = time.time()
        try:
            cursor = mysql.connection.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            db_response_time = (time.time() - db_test_start) * 1000
            metrics['current_db_response_ms'] = round(db_response_time, 1)
        except Exception as e:
            metrics['db_error'] = str(e)
        
        return jsonify(metrics)

    @app.route('/health')
    def health_check():
        start_time = time.time()
        try:
            cursor = mysql.connection.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            
            check_time = (time.time() - start_time) * 1000
            app_uptime = time.time() - APP_START_TIME
            
            response = {
                "status": "healthy",
                "database": "connected",
                "website": "accessible",
                "response_time_ms": round(check_time, 1),
                "app_uptime_seconds": round(app_uptime, 1)
            }
            
            # Alertes si les temps sont élevés
            if check_time > 1000:
                response["alerts"] = ["DB_RESPONSE_SLOW"]
            
            return jsonify(response), 200
            
        except Exception as e:
            check_time = (time.time() - start_time) * 1000
            return jsonify({
                "status": "unhealthy",
                "error": str(e),
                "response_time_ms": round(check_time, 1),
                "app_uptime_seconds": round(time.time() - APP_START_TIME, 1)
            }), 500

    @app.route('/cron/send-delayed-notifications')
    def cron_send_delayed_notifications():
        """Appelé par Cloud Scheduler entre 13h-16h."""
        # Vérifier appel interne (Cloud Scheduler ou cron)
        if (not request.headers.get('X-CloudScheduler') 
            and not request.headers.get('X-Appengine-Cron')
            and not app.debug):
            return jsonify({'error': 'Unauthorized'}), 403
        
        from scripts.send_delayed_notifications import send_pending_analysis_notifications
        count = send_pending_analysis_notifications(app)
        return jsonify({'sent': count, 'status': 'ok'})

    @app.route('/track-activity', methods=['POST'])
    def track_activity_endpoint():
        """
        Endpoint pour tracker les événements custom (vues pistes, impressions, etc.)
        """
        try:
            data = request.json or {}
            
            event_type = data.get('event_type', 'custom_event')
            page_path = data.get('page_path', request.path)
            extra_data = data.get('extra_data')
            
            ua = (request.user_agent.string or '').lower()
            device = 'mobile' if any(m in ua for m in ['iphone', 'android', 'mobile']) else 'desktop'
            
            user_id = current_user.id if current_user.is_authenticated else None
            session_id = str(session.get('_id') or g.get('request_id', ''))[:128]
            
            cursor = mysql.connection.cursor()
            cursor.execute('''
                INSERT INTO activity_logs 
                (user_id, session_id, event_type, page_path, device_type, extra_data)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (
                user_id,
                session_id,
                event_type[:50],
                page_path[:255],
                device,
                json.dumps(extra_data) if extra_data else None
            ))
            mysql.connection.commit()
            cursor.close()
            
            return jsonify({'success': True}), 200
            
        except Exception as e:
            logger.warning(f"Activity tracking failed: {e}")
            return jsonify({'success': False}), 200

    @app.route('/set-language/<lang_code>')
    def set_language(lang_code):
        if lang_code in ['fr', 'en']:
            session['lang_code'] = lang_code
        return redirect(request.referrer or url_for('auth.home'))

    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        # Alerte Slack monitoring
        try:
            from services import slack_service, SLACK_AVAILABLE
            if SLACK_AVAILABLE and slack_service:
                slack_service.send_notification(
                    message=f"🚦 *Rate Limit Atteint*\n• IP: `{request.remote_addr}`\n• Route: `{request.path}`\n• Method: `{request.method}`",
                    channel='monitoring'
                )
        except Exception as slack_error:
            logger.warning(f"Impossible d'envoyer l'alerte Slack: {slack_error}")
        
        logger.warning(f"Rate limit exceeded - IP: {request.remote_addr}, Path: {request.path}")
        return jsonify(error="Trop de requêtes. Veuillez réessayer plus tard."), 429

    @app.errorhandler(404)
    def page_not_found(e):
        logger.error('404 Error: %s', str(e))
        return render_template('errors/404.html', current_endpoint=request.endpoint or 'home'), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        logger.error('500 Error: %s', str(e), exc_info=True)
        return render_template('errors/500.html'), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        request_id = getattr(g, 'request_id', 'unknown')
        logger.warning(
            f"[{request_id}] CSRF Error: {e.description} - "
            f"Path: {request.path} - IP: {request.remote_addr}"
        )
        
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({
                'error': 'csrf_token_expired',
                'message': 'Votre session a expiré. Veuillez recharger la page.'
            }), 400
        
        flash('Votre session a expiré. Veuillez réessayer.', 'warning')
        return redirect(request.referrer or url_for('auth.home'))
    
    @app.route('/robots.txt')
    def robots_txt():
        return send_from_directory(app.static_folder, 'robots.txt')

# Route de diagnostic pour identifier les requêtes lentes
    @app.route('/debug/performance-test')
    def debug_performance():
        """Route de test pour identifier les goulots d'étranglement"""
        request_id = getattr(g, 'request_id', 'debug')
        start_time = time.time()
        
        results = {
            'test_start': datetime.now().isoformat(),
            'tests': {}
        }
        
        # Test 1: Connexion base de données simple
        test_start = time.time()
        try:
            cursor = mysql.connection.cursor()
            cursor.execute('SELECT 1')
            cursor.close()
            results['tests']['db_simple'] = f"{(time.time() - test_start)*1000:.1f}ms - OK"
        except Exception as e:
            results['tests']['db_simple'] = f"{(time.time() - test_start)*1000:.1f}ms - ERROR: {str(e)}"
        
        # Test 2: Session access
        test_start = time.time()
        try:
            test_session = session.get('test_key', 'default')
            session['test_timestamp'] = time.time()
            results['tests']['session_access'] = f"{(time.time() - test_start)*1000:.1f}ms - OK"
        except Exception as e:
            results['tests']['session_access'] = f"{(time.time() - test_start)*1000:.1f}ms - ERROR: {str(e)}"
        
        # Test 3: Template rendering simple
        test_start = time.time()
        try:
            from flask import render_template_string
            simple_template = render_template_string('<p>Test: {{ now }}</p>', now=datetime.now())
            results['tests']['template_render'] = f"{(time.time() - test_start)*1000:.1f}ms - OK"
        except Exception as e:
            results['tests']['template_render'] = f"{(time.time() - test_start)*1000:.1f}ms - ERROR: {str(e)}"
        
        # Test 4: User authentication check
        test_start = time.time()
        try:
            auth_status = current_user.is_authenticated if current_user else False
            results['tests']['auth_check'] = f"{(time.time() - test_start)*1000:.1f}ms - User authenticated: {auth_status}"
        except Exception as e:
            results['tests']['auth_check'] = f"{(time.time() - test_start)*1000:.1f}ms - ERROR: {str(e)}"
        
        # Test 5: Requête plus complexe (si tables existent)
        test_start = time.time()
        try:
            cursor = mysql.connection.cursor()
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            cursor.close()
            results['tests']['db_complex'] = f"{(time.time() - test_start)*1000:.1f}ms - Found {len(tables)} tables"
        except Exception as e:
            results['tests']['db_complex'] = f"{(time.time() - test_start)*1000:.1f}ms - ERROR: {str(e)}"
        
        total_time = (time.time() - start_time) * 1000
        results['total_time_ms'] = round(total_time, 1)
        results['request_id'] = request_id
        
        logger.info(f"[{request_id}] Performance test completed in {total_time:.1f}ms")
        
        return jsonify(results)

    if not app.config.get('GOOGLE_CLOUD_PROJECT'):
        @app.route('/test-404')
        def test_404():
            abort(404)

        @app.route('/test-500')
        def test_500():
            raise Exception("This is a test 500 error")

        @app.route('/api/test-anonymization', methods=['POST'])
        def test_anonymize():
            """Point d'entrée pour tester l'anonymisation."""
            try:
                data = request.json
                text = data.get('text', '')
                request_id = str(uuid.uuid4())
                
                cursor = mysql.connection.cursor()
                quiz_service = QuizAnalysisService(cursor, 1, 'test-quiz')
                original, anonymized = quiz_service.test_anonymization_logging(text, request_id)
                cursor.close()
                
                return jsonify({
                    'original': original,
                    'anonymized': anonymized,
                    'has_changes': original != anonymized,
                    'request_id': request_id
                })
                
            except Exception as e:
                app.logger.error(f"Erreur pendant le test d'anonymisation: {str(e)}", exc_info=True)
                return jsonify({'error': str(e)}), 500
            
        @app.route('/test-anonymization-ui')
        def test_anonymization_ui():
            return render_template('admin/test_anonymization.html')

    def get_db():
        if 'db' not in g:
            g.db = mysql.connection
        return g.db

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop('db', None)
        if db is not None:
            db.close()
            
    @app.after_request
    def set_csp_headers(response):
        if hasattr(g, 'nonce'):
            try:
                policy_template = app.config['TALISMAN_CONTENT_SECURITY_POLICY']
                
                if callable(policy_template):
                    policy = get_csp_policy(app.config['CSP_POLICY_TEMPLATE'])
                else:
                    policy = json.loads(json.dumps(policy_template))
                    
                    if 'script-src' in policy:
                        policy['script-src'] = [
                            src.replace('{nonce}', f"'nonce-{g.nonce}'") if '{nonce}' in src else src 
                            for src in policy['script-src']
                        ]
                    
                    if 'media-src' not in policy:
                        policy['media-src'] = ["'self'", "blob:", "https://storage.googleapis.com"]
                    else:
                        if "blob:" not in policy['media-src']:
                            policy['media-src'].append("blob:")
                
                if 'form-action' in policy:
                    del policy['form-action']
                
                csp_string = '; '.join(
                    f"{section} {' '.join(content)}"
                    for section, content in policy.items()
                )
                response.headers['Content-Security-Policy'] = csp_string
                
            except Exception as e:
                logger.error(f"Erreur lors de la génération de la CSP: {e}")
        
        return response

    def add_security_headers(response):
        response.headers['Permissions-Policy'] = (
            "accelerometer=(), "
            "camera=(), "
            "geolocation=(), "
            "gyroscope=(), "
            "magnetometer=(), "
            "microphone=(self), "
            "payment=(self), "
            "usb=()"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        return response

    @app.route('/politique-de-confidentialite')
    def privacy_policy():
        return render_template('privacy_policy.html')

    @app.route('/analysis/139cfb32-d253-470a-adeb-96a1f02e20fd-1745238504')
    def analysis_temp():
        return render_template('pages/analysis_temp.html')

    @app.route('/analysis/hdjfh7856-d253-8j89-adeb-96a1f02e20fd-1745238504')
    def analysis_temp2():
        return render_template('pages/analysis_temp2.html')

    @app.route('/cookie-policy')
    def cookie_policy():
        return render_template('cookie_policy.html')

    @app.route('/mentions-legales')
    def legal():
        return render_template('legal.html')

    @app.route('/conditions-generales-vente')
    def terms_of_service():
        return render_template('terms_of_service.html')

    @app.route('/about')
    def about():
        return render_template('pages/about.html')

    @app.route('/orientation')
    def orientation():
        """Page orientation avec question hero dynamique"""
        mysql = app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            # Récupérer la première question du quiz orientation (par ranking)
            cursor.execute('''
                SELECT q.question_id, q.question
                FROM quiz_questions qq
                JOIN questions_catalog q ON qq.question_id = q.question_id
                WHERE qq.quiz_id = 'pack_orientation'
                AND qq.is_active = TRUE
                AND q.is_active = TRUE
                ORDER BY qq.question_ranking ASC
                LIMIT 1
            ''')
            hero_question = cursor.fetchone()
            
            return render_template(
                'pages/orientation.html',
                hero_question=hero_question
            )
            
        except Exception as e:
            logger.error(f"Erreur chargement orientation: {str(e)}")
            # Fallback avec valeur par défaut
            return render_template(
                'pages/orientation.html',
                hero_question={'question_id': 52, 'question': "Qu'est-ce qui te passionne, t'ennuie, ou te fait rêver quand tu penses à ton futur métier ?"}
            )
        
        finally:
            cursor.close()

    @app.route('/profils-comme-toi')
    def tilto_gallery():
        return render_template('pages/tilto_gallery.html')

    @app.route('/pro')
    def tilto_pro():
        return render_template('pages/pro.html')

    @app.route('/bilan-carriere-express-<slug_id>')
    def bilan_flash_slug(slug_id):
        """Landing page bilan carrière express avec tracking par variante"""
        
        SLUG_VARIANTS = {
            '9001': {'is_fallback': True,  'source': None, 'variant': None},
            '9002': {'is_fallback': False, 'source': 'facebook', 'variant': 'message_a'},
            '9003': {'is_fallback': False, 'source': 'facebook', 'variant': 'message_b'},
            '9004': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9005': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9006': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9007': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9008': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9009': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9010': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9011': {'is_fallback': False, 'source': 'linkedin',    'variant': 'message_a'},
            '9012': {'is_fallback': False, 'source': 'linkedin_loom',    'variant': 'message_a'},
            '9013': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9014': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9015': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9016': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9017': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'}
        }

        if slug_id not in SLUG_VARIANTS:
            abort(404)

        data = SLUG_VARIANTS[slug_id]
        campaign = request.args.get('campaign', 'none')

        session['bilan_flash_slug'] = slug_id
        session['bilan_flash_meta'] = {
            'variant': data['variant'],
            'source': data['source'],
            'campaign': campaign,
            'is_fallback': data['is_fallback']
        }

        return render_template('pages/bilan-carriere-express.html',
            slug_id=slug_id,
            source=data['source'],
            variant=data['variant'],
            campaign=campaign)


    @app.route('/bilan-carriere-express')
    def bilan_flash():
        return redirect(url_for('bilan_flash_slug', slug_id='9001'))


    @app.route('/coaching-carriere-express-<slug_id>')
    def coaching_flash_slug(slug_id):
        """Landing page bilan carrière express avec tracking par variante"""
        
        SLUG_VARIANTS = {
            '9001': {'is_fallback': True,  'source': None, 'variant': None},
            '9002': {'is_fallback': False, 'source': 'facebook', 'variant': 'message_a'},
            '9003': {'is_fallback': False, 'source': 'facebook', 'variant': 'message_b'},
            '9004': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9005': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9006': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9007': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9008': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9009': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9010': {'is_fallback': False, 'source': 'google_ads',    'variant': 'message_a'},
            '9011': {'is_fallback': False, 'source': 'linkedin',    'variant': 'message_a'},
            '9012': {'is_fallback': False, 'source': 'linkedin_loom',    'variant': 'message_a'},
            '9013': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9014': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9015': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9016': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'},
            '9017': {'is_fallback': False, 'source': 'email',    'variant': 'message_a'}
        }

        if slug_id not in SLUG_VARIANTS:
            abort(404)

        data = SLUG_VARIANTS[slug_id]
        campaign = request.args.get('campaign', 'none')

        session['bilan_flash_slug'] = slug_id
        session['bilan_flash_meta'] = {
            'variant': data['variant'],
            'source': data['source'],
            'campaign': campaign,
            'is_fallback': data['is_fallback']
        }

        return render_template('pages/coaching-carriere-express.html',
            slug_id=slug_id,
            source=data['source'],
            variant=data['variant'],
            campaign=campaign)


    @app.route('/coaching-carriere-express')
    def coaching_flash():
        return redirect(url_for('coaching_flash_slug', slug_id='9001'))


    @app.route('/exemple-livrable-tilto')
    def exemple_livrable_tilto():
        return render_template('pages/exemple-livrable-tilto.html')


    @app.route('/09c9ae9319fd7e99388b')
    def livrable_carine():
        return render_template('pages/livrable_carine.html')

    @app.route('/obtiens-tes-smart-contacts')
    def tilto_smart_contacts_default():
        return redirect(url_for('tilto_smart_contacts', slug_id='8793'))

    @app.route('/obtiens-tes-smart-contacts-<slug_id>')
    def tilto_smart_contacts(slug_id):
        """Landing page smart contacts avec tracking par variante"""
        SLUG_VARIANTS = {
            '8793': {'is_fallback': True,  'source': None, 'variant': None},
            '8794': {'is_fallback': False, 'source': None, 'variant': None},
            '8795': {'is_fallback': False, 'source': None, 'variant': None},
            '8796': {'is_fallback': False, 'source': None, 'variant': None},
            '8797': {'is_fallback': False, 'source': None, 'variant': None},
            '8798': {'is_fallback': False, 'source': None, 'variant': None},
            '8799': {'is_fallback': False, 'source': None, 'variant': None},
            '8800': {'is_fallback': False, 'source': None, 'variant': None},
            '8801': {'is_fallback': False, 'source': None, 'variant': None},
            '8802': {'is_fallback': False, 'source': None, 'variant': None},
        }

        if slug_id not in SLUG_VARIANTS:
            abort(404)

        data = SLUG_VARIANTS[slug_id]
        campaign = request.args.get('campaign', 'none')

        session['smart_contact_slug'] = slug_id
        session['smart_contact_meta'] = {
            'variant': data['variant'],
            'source': data['source'],
            'campaign': campaign,
            'is_fallback': data['is_fallback']
        }

        return render_template('pages/landing_smart_contacts.html',
            slug_id=slug_id,
            source=data['source'],
            variant=data['variant'],
            campaign=campaign)

    @app.route('/demo_smart_contact')
    def tilto_smart_contacts_demo():
        return render_template(
            'pages/demo_smart_contact.html',
            logo_token=current_app.config.get('LOGO_DEV_PUBLIC_KEY')
        )

    @app.route('/demo_smart_contact_nicolas')
    def tilto_smart_contacts_demo_nicolas():
        return render_template(
            'pages/demo_smart_contact_nicolas.html',
            logo_token=current_app.config.get('LOGO_DEV_PUBLIC_KEY')
        )

    @app.route('/decouvre-tilto-<slug_id>')
    def lp_video(slug_id):
        """Landing page vidéo avec tracking par variante de message"""
        
        # Mapping ID → variante de message LinkedIn
        SLUG_VARIANTS = {
            '8789': {'source': 'linkedin', 'variant': 'message_a'},
            '8790': {'source': 'linkedin', 'variant': 'message_b'},
            '8791': {'source': 'linkedin', 'variant': 'message_c'},
            '8792': {'source': 'linkedin', 'variant': 'message_d'},
        }
        
        if slug_id not in SLUG_VARIANTS:
            abort(404)
        
        data = SLUG_VARIANTS[slug_id]
        campaign = request.args.get('campaign', 'none')
        
        return render_template('pages/lp_discover_tilto.html', 
                            source=data['source'],
                            variant=data['variant'],
                            campaign=campaign)

    @app.route('/decouvre-tilto-avis-<slug_id>')
    def lp_video_testimonials(slug_id):
        """Landing page vidéo avec tracking par variante de message"""
        
        # Mapping ID → variante de message LinkedIn
        SLUG_VARIANTS = {
            '8789': {'source': 'linkedin', 'variant': 'message_a'},
            '8790': {'source': 'linkedin', 'variant': 'message_b'},
            '8791': {'source': 'linkedin', 'variant': 'message_c'},
            '8792': {'source': 'linkedin', 'variant': 'message_d'},
        }
        
        if slug_id not in SLUG_VARIANTS:
            abort(404)
        
        data = SLUG_VARIANTS[slug_id]
        campaign = request.args.get('campaign', 'none')
        
        return render_template('pages/lp_discover_tilto_testimonials.html', 
                            source=data['source'],
                            variant=data['variant'],
                            campaign=campaign)

    @app.route('/sitemap.xml')
    def sitemap():
        """Sitemap adapté selon le mode pré-lancement"""
        from datetime import datetime
        
        urls = [
            {
                'loc': url_for('auth.home', _external=True),
                'priority': '1.0',
                'changefreq': 'weekly',
                'lastmod': datetime.now().strftime('%Y-%m-%d')
            },
            {
            'loc': url_for('orientation', _external=True),
            'priority': '0.9',
            'changefreq': 'weekly',
            'lastmod': datetime.now().strftime('%Y-%m-%d')
            },
            {
                'loc': url_for('about', _external=True),
                'priority': '0.8',
                'changefreq': 'monthly',
                'lastmod': datetime.now().strftime('%Y-%m-%d')
            }
            
        ]
        
        legal_urls = [
            {
                'loc': url_for('privacy_policy', _external=True),
                'priority': '0.3',
                'changefreq': 'yearly',
                'lastmod': datetime.now().strftime('%Y-%m-%d')
            },
            {
                'loc': url_for('legal', _external=True),
                'priority': '0.3',
                'changefreq': 'yearly',
                'lastmod': datetime.now().strftime('%Y-%m-%d')
            },
            {
                'loc': url_for('cookie_policy', _external=True),
                'priority': '0.3',
                'changefreq': 'yearly',
                'lastmod': datetime.now().strftime('%Y-%m-%d')
            }
        ]
        
        urls.extend(legal_urls)

        if not app.config.get('PRELAUNCH_MODE', False):
            urls.extend([
                {
                    'loc': url_for('tokens.shop', _external=True),
                    'priority': '0.9',
                    'changefreq': 'daily',
                    'lastmod': datetime.now().strftime('%Y-%m-%d')
                }
            ])

        # ─── Pages SEO programmatiques (métiers + villes) ───
        try:
            from routes.seo import get_all_seo_urls
            base_url = app.config.get('BASE_URL', 'https://tilto.co').rstrip('/')
            for seo_url in get_all_seo_urls(base_url=base_url):
                urls.append({
                    'loc': seo_url['loc'],
                    'priority': seo_url['priority'],
                    'changefreq': seo_url['changefreq'],
                    'lastmod': datetime.now().strftime('%Y-%m-%d'),
                })
        except Exception as seo_err:
            app.logger.warning(f"Sitemap : erreur ajout pages SEO : {seo_err}")
        
        xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'''
        
        for url in urls:
            xml_content += f'''
        <url>
            <loc>{url['loc']}</loc>
            <lastmod>{url['lastmod']}</lastmod>
            <changefreq>{url['changefreq']}</changefreq>
            <priority>{url['priority']}</priority>
        </url>'''
        
        xml_content += '''
    </urlset>'''
        
        from flask import Response
        response = Response(xml_content, mimetype='application/xml')
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response

    @app.route('/admin/security-status')
    def security_status():
        """Vérifier le statut de sécurité du mode pré-lancement"""
        if not (current_user.is_authenticated and current_user.user_status == 'admin'):
            return jsonify({'error': 'Admin access required'}), 403
        
        bypass_token = session.get('prelaunch_bypass_token')
        bypass_timestamp = session.get('prelaunch_bypass_timestamp')
        bypass_ip = session.get('prelaunch_bypass_ip')
        
        status = {
            'prelaunch_mode': app.config.get('PRELAUNCH_MODE', False),
            'current_ip': request.remote_addr,
            'session_id': session.get('_id', 'unknown'),
            'admin_authenticated': current_user.is_authenticated and current_user.user_status == 'admin',
            'two_factor_authenticated': session.get('two_factor_authenticated', False),
            'bypass': {
                'active': bool(bypass_token),
                'ip_match': bypass_ip == request.remote_addr if bypass_ip else None,
                'created_at': bypass_timestamp,
                'age_minutes': round((time.time() - bypass_timestamp) / 60, 1) if bypass_timestamp else None
            }
        }
        
        return jsonify(status)

    @app.route('/admin/clear-bypass')  
    def clear_bypass():
        """Nettoyer manuellement le bypass (sécurité)"""
        if current_user.is_authenticated and current_user.user_status == 'admin':
            session.pop('prelaunch_bypass_token', None)
            session.pop('prelaunch_bypass_timestamp', None) 
            session.pop('prelaunch_bypass_ip', None)
            flash('Bypass supprimé', 'info')
        
        return redirect(url_for('auth.home'))

    app.after_request(add_security_headers)



    @app.route('/test-email')
    def test_email():
        """Route de test pour vérifier l'envoi d'email d'activation"""
        if not app.debug:
            return "Route désactivée en production", 403
        
        from services import send_email, send_invite_email
        import os
        
        result = send_invite_email(
            email="test@example.com",
            name="Test User",
            token="REAL_TEST_TOKEN_789",
            interest="recommendations_metier"
        )
        
        if result:
            return f"✅ Email d'activation envoyé avec succès à {test_email}! Vérifiez votre boîte mail.", 200
        else:
            return "❌ Échec de l'envoi de l'email. Vérifiez les logs dans la console.", 500

    


    return app




# Créer l'instance app pour Gunicorn
app = create_app()

if __name__ == '__main__':
    app.run(debug=not bool(os.getenv('GOOGLE_CLOUD_PROJECT')))