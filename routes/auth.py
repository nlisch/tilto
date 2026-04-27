from flask import Blueprint, jsonify, request, render_template, flash, redirect, url_for, current_app, g, session, send_file, abort
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from models import User
from forms import LoginForm, RegistrationForm, TwoFactorForm, RequestResetForm, ResetPasswordForm
import logging
from flask_oauthlib.client import OAuth
from flask_babel import _, lazy_gettext as _l
from decorators import admin_required
import qrcode
import io
import base64
import pyotp
from flask_mail import Message
from services import send_email, send_invite_email, send_password_reset_email
from extensions import mail
import time
from MySQLdb.cursors import DictCursor
import secrets
from datetime import datetime, timedelta
from .gallery_data import PROFILS
import json

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)

@auth_bp.route('/')
def home():
    """Homepage avec question hero dynamique"""
    from MySQLdb.cursors import DictCursor
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer la première question du quiz pack_clarte (par ranking)
        cursor.execute('''
            SELECT q.question_id, q.question
            FROM quiz_questions qq
            JOIN questions_catalog q ON qq.question_id = q.question_id
            WHERE qq.quiz_id = 'pack_clarte'
            AND qq.is_active = TRUE
            AND q.is_active = TRUE
            ORDER BY qq.question_ranking ASC
            LIMIT 1
        ''')
        hero_question = cursor.fetchone()

        return render_template(
            'pages/homepage.html',
            hero_question=hero_question
        )

    except Exception as e:
        # Fallback avec valeur par défaut
        return render_template(
            'pages/homepage.html',
            hero_question={'question_id': 65, 'question': "Dis-moi ce qui te manque aujourd'hui dans ton travail et ce qui te ferait vibrer"}
        )
    
    finally:
        cursor.close()

@auth_bp.route('/dashboard')
@login_required
def dashboard():
    logger.debug(f"Dashboard route accessed by user: {current_user.username}")

    if current_user.user_status == 'admin':
        # Vérifier si 2FA est complété
        if not session.get('two_factor_authenticated'):
            logger.debug("Admin user redirected to 2FA")
            flash(_('Veuillez compléter l\'authentification à deux facteurs.'), 'warning')
            return redirect(url_for('auth.two_factor'))

    # Rediriger vers le dashboard blueprint qui gère toute la logique
    return redirect(url_for('dashboard.index'))


@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    form = RegistrationForm()
    if form.validate_on_submit():
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        
        try:
            logger.info("Début de l'inscription d'un nouvel utilisateur")
            logger.info(f"Données reçues - username: {form.username.data}, email: {form.email.data}")
            
            # Vérifier si le champ honeypot est rempli (signe d'un bot)
            if request.form.get('website'):
                logger.warning(f"Tentative de spam détectée - Honeypot rempli")
                # Simuler un succès mais ne rien faire
                flash(_('Inscription réussie. Vérifiez votre email.'), 'success') 
                return redirect(url_for('auth.login'))
            
            # Vérifier le temps de soumission
            submission_time = request.form.get('submission_time')
            if submission_time and int(submission_time) < 2000:
                logger.warning(f"Tentative de spam détectée - Formulaire rempli trop rapidement: {submission_time}ms")
                # Simuler un succès mais ne rien faire
                flash(_('Inscription réussie. Vérifiez votre email.'), 'success')
                return redirect(url_for('auth.login'))
            
            # Vérifier si l'utilisateur existe déjà
            cursor.execute("""
                SELECT user_id FROM users WHERE username = %s OR email = %s
            """, (form.username.data, form.email.data))
            existing_user = cursor.fetchone()
            if existing_user:
                logger.warning(f"Utilisateur existant trouvé avec username ou email")
                flash(_('Nom d\'utilisateur ou email déjà utilisé.'), 'error')
                return redirect(url_for('auth.signup'))
            
            # Vérifier les domaines d'email temporaires côté serveur
            temp_email_domains = ['mailinator.com', 'yopmail.com', 'tempmail.com', 'guerrillamail.com', 'temp-mail.org', 'throwawaymail.com']
            domain = form.email.data.split('@')[-1]
            if domain in temp_email_domains:
                logger.warning(f"Tentative d'inscription avec email temporaire: {domain}")
                flash(_('Les adresses email temporaires ne sont pas acceptées.'), 'error')
                return redirect(url_for('auth.signup'))
            
            # Créer le nouvel utilisateur
            new_user = User(
                user_id=None,
                username=form.username.data,
                email=form.email.data,
                user_status='user',
                country_code='FR'
            )
            
            # Générer et stocker le hash du mot de passe
            password_hash = new_user.set_password(form.password.data)
            logger.info("Hash du mot de passe généré avec succès")
            
            # Insérer l'utilisateur dans la base de données
            insert_query = """
                INSERT INTO users 
                    (username, email, password, user_status, country_code)
                VALUES 
                    (%s, %s, %s, %s, %s)
            """
            values = (
                new_user.username,
                new_user.email,
                password_hash,
                new_user.user_status,
                new_user.country_code,
            )
            
            logger.info(f"Tentative d'insertion - Query: {insert_query}")
            logger.info(f"Valeurs (password masqué): {new_user.username}, {new_user.email}, *****, {new_user.user_status}, {new_user.country_code}, {new_user.two_factor_secret}")
            
            cursor.execute(insert_query, values)
            mysql.connection.commit()
            
            new_user.id = cursor.lastrowid
            logger.info(f"Nouvel utilisateur créé avec ID: {new_user.id}")
            
            flash(_('Inscription réussie. Vous pouvez maintenant vous connecter.'), 'success')
            return redirect(url_for('auth.login'))
            
        except Exception as e:
            mysql.connection.rollback()
            logger.error(f"Erreur lors de l'inscription de l'utilisateur: {e}", exc_info=True)
            flash(_('Une erreur est survenue lors de l\'inscription.'), 'error')
            return redirect(url_for('auth.signup'))
        
        finally:
            cursor.close()
            logger.info("Fin de la tentative d'inscription")
    
    return render_template('auth/signup.html', form=form)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    Page de connexion avec 2 options :
    1. Magic Link (par défaut)
    2. Mot de passe (si configuré)
    """
    form = LoginForm()
    
    # === CAS 1 : Demande de Magic Link ===
    if request.method == 'POST' and 'request_magic_link' in request.form:
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            flash('Veuillez entrer votre email.', 'error')
            return render_template('auth/login.html', form=form)
        
        cursor = current_app.mysql.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT user_id, firstname, onboarding_stage
                FROM users 
                WHERE email = %s
            """, (email,))
            user_data = cursor.fetchone()
            
            # ✅ TOUJOURS envoyer un email (ou faire semblant)
            if user_data:
                # Email existe → Envoyer le Magic Link
                user_id, firstname, onboarding_stage = user_data
                
                # Générer le token
                magic_token = secrets.token_urlsafe(32)
                magic_expiry = datetime.now() + timedelta(minutes=15)
                
                cursor.execute("""
                    UPDATE users 
                    SET invite_token = %s,
                        invite_expiry = %s,
                        updated_at = NOW()
                    WHERE user_id = %s
                """, (magic_token, magic_expiry, user_id))
                
                current_app.mysql.connection.commit()
                
                # Envoyer l'email
                from services import send_magic_link_email
                magic_url = url_for('auth.magic_login', token=magic_token, _external=True)
                
                send_magic_link_email(
                    email=email,
                    firstname=firstname,
                    magic_url=magic_url,
                    expires_in_minutes=15
                )
                
                logger.info(f"✅ Magic Link envoyé à {email}")
            else:
                # ✅ Email n'existe PAS → Ne rien faire (mais ne pas le dire)
                logger.info(f"⚠️ Tentative Magic Link pour email inexistant: {email}")
            
            # ✅ CRITIQUE : Afficher le MÊME message dans les DEUX cas
            cursor.close()
            flash('📧 Si cet email est enregistré, un lien de connexion a été envoyé. Vérifie ta boîte mail (et tes spams).', 'success')
            return render_template('auth/login.html', form=form)
            
        except Exception as e:
            logger.error(f"Erreur Magic Link: {str(e)}", exc_info=True)
            # ✅ Même en cas d'erreur, ne pas révéler d'infos
            cursor.close()
            flash('📧 Si cet email est enregistré, un lien de connexion a été envoyé.', 'success')
            return render_template('auth/login.html', form=form)
            
        except Exception as e:
            logger.error(f"Erreur Magic Link: {str(e)}", exc_info=True)
            flash('Une erreur est survenue.', 'error')
            return render_template('auth/login.html', form=form)
    
    # === CAS 2 : Connexion avec mot de passe ===
    if form.validate_on_submit() and 'submit' in request.form:
        logger.info(f"Tentative de connexion pour l'utilisateur: {form.username.data}")
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()

        try:
            cursor.execute("""
                SELECT user_id, username, email, user_status, country_code, two_factor_secret, password
                FROM users 
                WHERE email = %s
            """, (form.username.data,))
            user_data = cursor.fetchone()
            
            if user_data:
                user = User(
                    user_id=user_data[0],
                    username=user_data[1],
                    email=user_data[2],
                    user_status=user_data[3],
                    country_code=user_data[4],
                    two_factor_secret=user_data[5]
                )
                user.password_hash = user_data[6]
                
                # ✅ Vérifier si un mot de passe existe
                if not user.password_hash:
                    flash('Tu n\'as pas encore créé de mot de passe. Utilise le lien de connexion.', 'warning')
                    cursor.close()
                    return render_template('auth/login.html', form=form)
                
                if user.check_password(form.password.data):
                    login_user(user, remember=form.remember.data)
                    logger.info(f"Connexion réussie pour l'utilisateur: {user.username}")
                    flash('Connexion réussie.', 'success')
                    
                    if user.user_status == 'admin':
                        if not user.two_factor_secret:
                            return redirect(url_for('auth.setup_two_factor'))
                        else:
                            return redirect(url_for('auth.two_factor'))
                    
                    # Redirection post-login (checkout ou dashboard)
                    after_login = session.pop('after_login_redirect', None)
                    if after_login:
                        return redirect(after_login)
                    return redirect(url_for('auth.dashboard'))
                else:
                    flash('Email ou mot de passe incorrect.', 'error')
            else:
                flash('Email ou mot de passe incorrect.', 'error')
        except Exception as e:
            logger.error(f"Erreur lors de la connexion: {e}", exc_info=True)
            flash('Une erreur est survenue.', 'error')
        finally:
            cursor.close()
    
    return render_template('auth/login.html', form=form)

@auth_bp.route('/magic-login/<token>', methods=['GET', 'POST'])
def magic_login(token):
    """
    Magic Link avec écran de confirmation (best practice)
    GET : Affiche écran de confirmation
    POST : Connecte l'utilisateur
    """
    try:
        cursor = current_app.mysql.connection.cursor()
        
        # ✅ Vérifier le token
        cursor.execute("""
            SELECT user_id, email, firstname, invite_expiry
            FROM users 
            WHERE invite_token = %s
        """, (token,))
        
        user_data = cursor.fetchone()
        
        if not user_data:
            cursor.close()
            flash('Lien de connexion invalide ou déjà utilisé.', 'error')
            return redirect(url_for('auth.login'))
        
        user_id, email, firstname, invite_expiry = user_data
        
        # ✅ Vérifier expiration (15 min)
        if invite_expiry and datetime.now() > invite_expiry:
            cursor.close()
            flash('Ce lien a expiré. Demande-en un nouveau.', 'error')
            return redirect(url_for('auth.login'))
        
        # ✅ GET : Afficher l'écran de confirmation
        if request.method == 'GET':
            cursor.close()
            return render_template('auth/magic_login_confirm.html',
                                   token=token,
                                   email=email,
                                   firstname=firstname,
                                   next_url=request.args.get('next', ''))
        
        # ✅ POST : L'utilisateur a confirmé → Connexion
        if request.method == 'POST':
            # Vérifier le token CSRF pour sécurité
            confirmed = request.form.get('confirm') == 'yes'
            
            if not confirmed:
                cursor.close()
                flash('Connexion annulée.', 'info')
                return redirect(url_for('auth.login'))
            
            # ✅ Supprimer le token après utilisation (usage unique)
            cursor.execute("""
                UPDATE users 
                SET invite_token = NULL,
                    invite_expiry = NULL,
                    last_login = NOW()
                WHERE user_id = %s
            """, (user_id,))
            
            current_app.mysql.connection.commit()
            cursor.close()
            
            # ✅ Connecter l'utilisateur
            user = User.get_by_id(user_id)
            if user:
                login_user(user)
                logger.info(f"✅ Connexion Magic Link confirmée: {email}")
                flash(f'Bienvenue {firstname} ! 🎉', 'success')
                
                # Redirection : paramètre next > session > dashboard
                next_url = request.args.get('next')
                if next_url and next_url.startswith('/'):
                    return redirect(next_url)
                after_login = session.pop('after_login_redirect', None)
                if after_login:
                    return redirect(after_login)
                return redirect(url_for('dashboard.index'))
            
            flash('Erreur lors de la connexion.', 'error')
            return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"❌ Erreur Magic Login: {str(e)}", exc_info=True)
        flash('Une erreur est survenue.', 'error')
        return redirect(url_for('auth.login'))

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    # Supprimer la vérification 2FA
    session.pop('two_factor_authenticated', None)
    session.pop('temp_secret', None)
    flash(_('Déconnexion réussie.'), 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-2fa')
@login_required
def reset_2fa():
    """Réinitialise la configuration 2FA en supprimant le secret de la BDD."""
    if current_user.user_status != 'admin':
        flash(_('Accès refusé.'), 'error')
        return redirect(url_for('auth.dashboard'))
        
    try:
        # Supprimer le secret 2FA en BDD
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        
        cursor.execute("""
            UPDATE users SET two_factor_secret = NULL WHERE user_id = %s
        """, (current_user.id,))
        
        mysql.connection.commit()
        cursor.close()
        
        # Réinitialiser l'objet utilisateur
        current_user.two_factor_secret = None
        
        # Nettoyer la session
        session.pop('two_factor_authenticated', None)
        session.pop('temp_secret', None)
        
        flash(_('Configuration 2FA réinitialisée. Vous pouvez maintenant reconfigurer l\'authentification à deux facteurs.'), 'success')
        return redirect(url_for('auth.setup_two_factor'))
        
    except Exception as e:
        logger.error(f"Erreur lors de la réinitialisation 2FA: {e}")
        flash(_('Erreur lors de la réinitialisation. Veuillez réessayer.'), 'error')
        return redirect(url_for('auth.dashboard'))

        

@auth_bp.before_app_request
def enforce_two_factor():
    """Middleware pour vérifier l'authentification à deux facteurs."""
    # Ignorer les requêtes statiques
    if request.path.startswith('/static/') or request.path.startswith('/cookie/'):
        return None
    
    # Log détaillé de chaque requête
    logger.debug(f"[ENFORCE 2FA DEBUG] Requête vers: {request.path}")
    logger.debug(f"[ENFORCE 2FA DEBUG] Méthode: {request.method}")
    logger.debug(f"[ENFORCE 2FA DEBUG] Referrer: {request.referrer}")
    logger.debug(f"[ENFORCE 2FA DEBUG] User Agent: {request.user_agent}")
    
    # Ignorer les utilisateurs non connectés
    if not current_user.is_authenticated:
        logger.debug("[ENFORCE 2FA DEBUG] Utilisateur non authentifié - Ignoré")
        return None
        
    # Log détaillé de l'état de l'utilisateur
    logger.debug(f"[ENFORCE 2FA DEBUG] Utilisateur: {current_user.username}")
    logger.debug(f"[ENFORCE 2FA DEBUG] Statut: {current_user.user_status}")
    logger.debug(f"[ENFORCE 2FA DEBUG] Secret 2FA présent: {bool(current_user.two_factor_secret)}")
    
    # Ignorer les non-admins
    if current_user.user_status != 'admin':
        logger.debug("[ENFORCE 2FA DEBUG] Utilisateur non admin - Ignoré")
        return None

    # État actuel de la session
    logger.debug(f"[ENFORCE 2FA DEBUG] Session actuelle: {session}")
    
    # Chemins autorisés sans vérification
    allowed_paths = ['/setup_two_factor', '/verify_setup', '/qrcode', '/reset-2fa', '/logout']
    
    # SOLUTION ANTI-BOUCLE: Ne jamais rediriger depuis setup_two_factor
    if request.path == '/setup_two_factor':
        logger.debug("[ENFORCE 2FA DEBUG] Sur setup_two_factor - Aucune redirection")
        # Marquer explicitement qu'on est en cours de configuration
        session['setup_in_progress'] = True
        return None
    
    # Si le chemin est autorisé
    if request.path in allowed_paths:
        logger.debug(f"[ENFORCE 2FA DEBUG] Chemin {request.path} autorisé sans vérification")
        return None
    
    # Si l'utilisateur a déjà passé la vérification 2FA
    if session.get('two_factor_authenticated'):
        logger.debug("[ENFORCE 2FA DEBUG] 2FA déjà vérifié - Accès autorisé")
        return None
    
    # Si on est en cours de configuration
    if session.get('setup_in_progress'):
        logger.debug("[ENFORCE 2FA DEBUG] Configuration en cours - Accès autorisé")
        return None
    
    # S'il n'existe aucun secret en base de données
    if not current_user.two_factor_secret:
        logger.debug("[ENFORCE 2FA DEBUG] Pas de secret en BDD - Redirection vers setup_two_factor")
        return redirect(url_for('auth.setup_two_factor'))
    
    # Si l'utilisateur essaie d'accéder à une autre page que two_factor
    if request.path != '/two_factor':
        logger.debug(f"[ENFORCE 2FA DEBUG] Redirection vers two_factor depuis {request.path}")
        return redirect(url_for('auth.two_factor'))
    
    logger.debug("[ENFORCE 2FA DEBUG] Aucune redirection nécessaire")
    return None

# Modification de la route setup_two_factor avec logs détaillés
@auth_bp.route('/setup_two_factor')
@login_required
def setup_two_factor():
    """Affiche la page de configuration 2FA avec le QR code."""
    logger.debug(f"[SETUP 2FA DEBUG] Entrée dans la fonction pour {current_user.username}")
    logger.debug(f"[SETUP 2FA DEBUG] Session au début: {session}")
    
    if current_user.user_status != 'admin':
        logger.debug("[SETUP 2FA DEBUG] Non admin - Redirection vers dashboard")
        flash(_('Accès refusé.'), 'error')
        return redirect(url_for('auth.dashboard'))

    # IMPORTANT: Marquer qu'on est en configuration 2FA
    session['setup_in_progress'] = True
    logger.debug("[SETUP 2FA DEBUG] Flag setup_in_progress activé")
    
    # Vérifier si déjà un secret temporaire
    temp_secret = session.get('temp_secret')
    if temp_secret:
        logger.debug(f"[SETUP 2FA DEBUG] Réutilisation du secret temporaire existant: {temp_secret}")
    else:
        # Générer un nouveau secret
        temp_secret = pyotp.random_base32()
        session['temp_secret'] = temp_secret
        logger.debug(f"[SETUP 2FA DEBUG] Nouveau secret temporaire généré: {temp_secret}")
    
    # Générer le QR code
    totp = pyotp.TOTP(temp_secret)
    uri = totp.provisioning_uri(name=current_user.email, issuer_name="Tilto")
    
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    
    # Convertir en base64
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode()
    
    logger.debug(f"[SETUP 2FA DEBUG] Session avant rendu: {session}")
    
    # IMPORTANT: Inspecter le template rendu pour détecter d'éventuelles redirections
    response = render_template('auth/setup_two_factor.html', qr_code=img_str, secret=temp_secret)
    logger.debug(f"[SETUP 2FA DEBUG] Longueur du template: {len(response)}")
    
    # Chercher des scripts de redirection dans le template
    if "window.location" in response or "document.location" in response:
        logger.warning("[SETUP 2FA DEBUG] Redirection JavaScript détectée dans le template!")
    
    if "<meta http-equiv=\"refresh\"" in response:
        logger.warning("[SETUP 2FA DEBUG] Meta refresh détecté dans le template!")
    
    return response



@auth_bp.route('/verify_setup', methods=['POST'])
@login_required
def verify_setup():
    """Vérifie le code 2FA et enregistre le secret en base de données."""
    if current_user.user_status != 'admin':
        flash(_('Accès refusé.'), 'error')
        return redirect(url_for('auth.dashboard'))

    token = request.form.get('token')
    temp_secret = session.get('temp_secret')

    if not token or not temp_secret:
        flash(_('Code ou secret manquant. Veuillez réessayer.'), 'error')
        return redirect(url_for('auth.setup_two_factor'))

    # Vérifier le code
    totp = pyotp.TOTP(temp_secret)
    if totp.verify(token, valid_window=1):
        try:
            # Enregistrer le secret en BDD
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            
            cursor.execute("""
                UPDATE users 
                SET two_factor_secret = %s 
                WHERE user_id = %s
            """, (temp_secret, current_user.id))
            
            mysql.connection.commit()
            cursor.close()

            # Mise à jour de l'objet utilisateur et marquer comme vérifié
            current_user.two_factor_secret = temp_secret
            session['two_factor_authenticated'] = True
            
            # Nettoyer le secret temporaire
            session.pop('temp_secret', None)
            
            flash(_('Configuration 2FA réussie.'), 'success')
            return redirect(url_for('auth.dashboard'))
            
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde du secret 2FA: {e}")
            flash(_('Une erreur est survenue. Veuillez réessayer.'), 'error')
            return redirect(url_for('auth.setup_two_factor'))
    else:
        flash(_('Code invalide. Veuillez réessayer.'), 'error')
        return redirect(url_for('auth.setup_two_factor'))

@auth_bp.route('/qrcode')
@login_required
def get_qrcode():
    logger.debug(f"Génération du QR code pour: {current_user.username}")
    
    if current_user.user_status != 'admin':
        abort(403)
    
    # Utiliser le secret temporaire s'il existe, sinon le secret permanent
    secret = session.get('temp_2fa_secret') or current_user.two_factor_secret
    
    if not secret:
        logger.error(f"Aucun secret 2FA disponible pour {current_user.username}")
        abort(500)
    
    # Générer l'URI TOTP
    totp = pyotp.totp.TOTP(secret)
    uri = totp.provisioning_uri(name=current_user.email, issuer_name="Tilto")
    
    # Créer le QR code
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill='black', back_color='white')
    
    # Envoyer l'image
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    buffered.seek(0)
    
    return send_file(buffered, mimetype='image/png')

@auth_bp.route('/about')
def about():
    return render_template('pages/about.html')

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    """
    Gère à la fois :
    - L'activation de compte (si pas encore activé)
    - La réinitialisation de mot de passe (si déjà activé)
    """
    if request.method == 'GET':
        return render_template('auth/forgot_password.html')
    
    try:
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            flash('Veuillez entrer votre adresse email.', 'error')
            return render_template('auth/forgot_password.html')
        
        cursor = current_app.mysql.connection.cursor(DictCursor)
        
        cursor.execute("""
            SELECT user_id, email, firstname, onboarding_stage
            FROM users 
            WHERE email = %s
        """, (email,))
        
        user_data = cursor.fetchone()
        
        # ✅ Traiter le cas où l'email existe
        if user_data:
            user_id = user_data['user_id']
            user_email = user_data['email']
            firstname = user_data['firstname']
            onboarding_stage = user_data['onboarding_stage']
            
            # Générer un nouveau token
            new_token = secrets.token_urlsafe(32)
            
            cursor.execute("""
                UPDATE users 
                SET invite_token = %s,
                    invite_expiry = DATE_ADD(NOW(), INTERVAL 24 HOUR),
                    updated_at = NOW()
                WHERE user_id = %s
            """, (new_token, user_id))
            
            current_app.mysql.connection.commit()
            
            # Envoyer l'email approprié selon le statut
            if onboarding_stage != 'email_verified':
                # Compte pas encore activé → Email d'activation
                success = send_invite_email(
                    email=user_email,
                    name=firstname,
                    token=new_token
                )
            else:
                # Compte déjà activé → Email de réinitialisation
                reset_url = url_for('auth.reset_password', token=new_token, _external=True)
                success = send_password_reset_email(
                    user_email=user_email,
                    reset_url=reset_url,
                    username=firstname,
                    expires_in_hours=24
                )
            
            if success:
                logger.info(f"✅ Email envoyé à {user_email}")
            else:
                logger.error(f"❌ Erreur envoi email à {user_email}")
        else:
            logger.info(f"⚠️ Tentative reset password pour email inexistant: {email}")
        
        cursor.close()
        flash('📧 Si cet email est enregistré, un lien a été envoyé. Vérifie ta boîte mail (et tes spams).', 'success')
        return render_template('auth/forgot_password.html')
        
    except Exception as e:
        logger.error(f"❌ Erreur forgot password: {str(e)}", exc_info=True)
        # ✅ Même en cas d'erreur, message générique
        flash('📧 Si cet email est enregistré, un lien a été envoyé.', 'success')
        return render_template('auth/forgot_password.html')


@auth_bp.route('/two_factor', methods=['GET', 'POST'])
@login_required
def two_factor():
    """Page de vérification du code 2FA."""
    logger.debug(f"[TWO FACTOR DEBUG] Entrée dans la fonction pour {current_user.username}")
    logger.debug(f"[TWO FACTOR DEBUG] Session initiale: {session}")
    logger.debug(f"[TWO FACTOR DEBUG] Secret permanent: '{current_user.two_factor_secret}'")
    logger.debug(f"[TWO FACTOR DEBUG] Secret temporaire: '{session.get('temp_secret')}'")
    
    if current_user.user_status != 'admin':
        logger.debug("[TWO FACTOR DEBUG] Non admin - Redirection vers dashboard")
        return redirect(url_for('auth.dashboard'))

    # Si déjà vérifié
    if session.get('two_factor_authenticated'):
        logger.debug("[TWO FACTOR DEBUG] Déjà vérifié - Redirection vers dashboard")
        return redirect(url_for('auth.dashboard'))

    # Si en cours de configuration, rediriger vers setup
    if session.get('setup_in_progress'):
        logger.debug("[TWO FACTOR DEBUG] En cours de configuration - Redirection vers setup_two_factor")
        return redirect(url_for('auth.setup_two_factor'))

    # Si pas de secret en BDD
    if not current_user.two_factor_secret:
        logger.debug("[TWO FACTOR DEBUG] Pas de secret en BDD - Redirection vers setup_two_factor")
        flash(_('Vous devez d\'abord configurer l\'authentification à deux facteurs.'), 'warning')
        return redirect(url_for('auth.setup_two_factor'))

    # Traitement du formulaire
    form = TwoFactorForm()
    if form.validate_on_submit():
        token = form.token.data
        logger.debug(f"[TWO FACTOR DEBUG] Token soumis: {token}")
        
        # Vérifier le code
        totp = pyotp.TOTP(current_user.two_factor_secret)
        if totp.verify(token):
            session['two_factor_authenticated'] = True
            logger.debug("[TWO FACTOR DEBUG] Token valide - Authentification réussie")
            flash(_('Authentification 2FA réussie.'), 'success')
            return redirect(url_for('auth.dashboard'))
        else:
            logger.debug("[TWO FACTOR DEBUG] Token invalide")
            flash(_('Code 2FA invalide. Réessayez.'), 'error')

    logger.debug("[TWO FACTOR DEBUG] Rendu du template two_factor.html")
    return render_template('auth/two_factor.html', form=form)


@auth_bp.route('/checkout-auth', methods=['GET', 'POST'])
def checkout_auth():
    """Page spéciale de connexion/inscription pour le processus d'achat."""
    # Générer un request_id pour le tracking
    if not hasattr(g, 'request_id') or not g.request_id:
        g.request_id = str(uuid.uuid4())
    
    # Récupération des informations du produit et du coupon depuis les arguments d'URL ou la session
    product_id = request.args.get('product_id') or session.get('checkout_product_id')
    coupon_code = request.args.get('coupon_code') or session.get('checkout_coupon_code', '')
    
    # Sauvegarder dans la session pour les conserver entre les requêtes
    if product_id:
        session['checkout_product_id'] = product_id
    if coupon_code:
        session['checkout_coupon_code'] = coupon_code
    
    # Si déjà connecté, rediriger vers le checkout
    if current_user.is_authenticated:
        return redirect(url_for('tokens.checkout_continue'))
    
    # Vérifier si un produit est sélectionné
    if not product_id:
        flash(_("Votre session d'achat a expiré. Veuillez réessayer."), "error")
        return redirect(url_for('tokens.shop'))
    
    # ==================== FORMULAIRES ====================
    login_form = LoginForm()
    register_form = RegistrationForm()
    
    # ==================== TRAITEMENT CONNEXION ====================
    if login_form.validate_on_submit() and 'login-submit' in request.form:
        logger.info(f"[{g.request_id}] Tentative de connexion checkout")
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        
        try:
            cursor.execute("""
                SELECT user_id, username, email, user_status, country_code, two_factor_secret, password
                FROM users 
                WHERE email = %s
            """, (login_form.username.data,))
            user_data = cursor.fetchone()
            
            if user_data:
                user = User(
                    user_id=user_data[0],
                    username=user_data[1],
                    email=user_data[2],
                    user_status=user_data[3],
                    country_code=user_data[4],
                    two_factor_secret=user_data[5]
                )
                user.password_hash = user_data[6]
                
                if user.check_password(login_form.password.data):
                    login_user(user, remember=login_form.remember.data)
                    logger.info(f"[{g.request_id}] Connexion checkout réussie: {user.username}")
                    flash(_('Connexion réussie.'), 'success')
                    
                    # Conserver le coupon et le produit depuis le formulaire si présents
                    form_product_id = request.form.get('product_id')
                    form_coupon_code = request.form.get('coupon_code')
                    if form_product_id:
                        session['checkout_product_id'] = form_product_id
                    if form_coupon_code:
                        session['checkout_coupon_code'] = form_coupon_code
                    
                    return redirect(url_for('tokens.checkout_continue'))
                else:
                    logger.warning(f"[{g.request_id}] Mot de passe incorrect pour: {login_form.username.data}")
                    flash(_('Email ou mot de passe incorrect.'), 'error')
            else:
                logger.warning(f"[{g.request_id}] Aucun utilisateur trouvé: {login_form.username.data}")
                flash(_('Email ou mot de passe incorrect.'), 'error')
                
        except Exception as e:
            logger.error(f"[{g.request_id}] Erreur connexion checkout: {e}", exc_info=True)
            flash(_('Une erreur est survenue lors de la connexion.'), 'error')
        finally:
            cursor.close()
    
    # ==================== TRAITEMENT INSCRIPTION ====================
    if register_form.validate_on_submit() and 'register-submit' in request.form:
        logger.info(f"[{g.request_id}] === DEBUT INSCRIPTION CHECKOUT ===")
        logger.info(f"[{g.request_id}] Form data: {dict(request.form)}")
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        
        try:
            # ==================== HONEYPOT ====================
            honeypot = request.form.get('website', '').strip()
            if honeypot:
                logger.warning(f"[{g.request_id}] 🤖 Bot détecté - honeypot rempli: '{honeypot}'")
                flash(_('Inscription réussie.'), 'success')
                return redirect(url_for('auth.login'))
            
            # ==================== RÉCUPÉRATION DES DONNÉES ====================
            firstname = request.form.get('firstname', '').strip()
            lastname = request.form.get('lastname', '').strip()
            email = register_form.email.data.strip().lower()
            phone = request.form.get('phone', '').strip() or None
            password = register_form.password.data
            
            # Consentements (obligatoires)
            partner_consent_value = request.form.get('partner_consent', '').strip().lower()
            newsletter_consent_value = request.form.get('newsletter_consent', '').strip().lower()
            
            logger.info(f"[{g.request_id}] Données extraites - Email: {email}, Firstname: {firstname}, Lastname: {lastname}")
            logger.info(f"[{g.request_id}] Consentements - Partner: {partner_consent_value}, Newsletter: {newsletter_consent_value}")
            
            # ==================== VALIDATIONS ====================
            if not firstname:
                logger.warning(f"[{g.request_id}] Prénom manquant")
                return jsonify({'success': False, 'message': 'Veuillez renseigner votre prénom.'}), 400

            if not email:
                logger.warning(f"[{g.request_id}] Email manquant")
                return jsonify({'success': False, 'message': 'Veuillez fournir une adresse email.'}), 400

            # Validation de l'email avec regex
            if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
                logger.warning(f"[{g.request_id}] Email invalide: {email}")
                return jsonify({'success': False, 'message': 'Veuillez fournir une adresse email valide.'}), 400
            
            
            # Validation des consentements
            # Partner consent est automatiquement "no" depuis le front
            partner_consent = (partner_consent_value == 'yes') if partner_consent_value else False

            # Newsletter est optionnelle
            newsletter = (newsletter_consent_value == 'yes') if newsletter_consent_value else False

            logger.info(f"[{g.request_id}] ✅ Consentements - Newsletter: {newsletter}, Partner: {partner_consent}")
            
            partner_consent = (partner_consent_value == 'yes')
            newsletter = (newsletter_consent_value == 'yes')
            
            logger.info(f"[{g.request_id}] ✅ Consentements - Newsletter: {newsletter}, Partner: {partner_consent}")
            
            # ==================== VÉRIFIER SI L'UTILISATEUR EXISTE ====================
            cursor.execute("""
                SELECT user_id, onboarding_stage FROM users WHERE email = %s
            """, (email,))
            existing_user = cursor.fetchone()

            if existing_user:
                user_id, onboarding_stage = existing_user
                logger.warning(f"[{g.request_id}] Email existant: user_id={user_id}, stage={onboarding_stage}")
                
                # ✅ Retourner une erreur JSON au lieu de redirection
                response = jsonify({
                    'success': False,
                    'message': 'Un compte existe déjà avec cet email. Connecte-toi ou utilise "Mot de passe oublié".',
                    'error_type': 'email_exists'
                })
                response.status_code = 409
                return response
            
            # ==================== CRÉER L'UTILISATEUR ====================
            new_user = User(
                user_id=None,
                username=username,
                email=email,
                user_status='user',
                country_code='FR'
            )
            
            # Générer et stocker le hash du mot de passe
            password_hash = new_user.set_password(password)
            logger.info(f"[{g.request_id}] Hash du mot de passe généré")
            
            # Insérer l'utilisateur dans la base de données
            insert_query = """
                INSERT INTO users 
                    (username, email, password, firstname, lastname, phone_number,
                    user_status, lead_source, newsletter_subscription, partner_consent,
                    country_code, onboarding_stage, privacy_policy_accepted, created_at)
                VALUES 
                    (%s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            values = (
                username,
                email,
                firstname,
                lastname or 'User',  # ✅ Valeur par défaut si pas de lastname
                None,  # ✅ phone = NULL (optionnel)
                'free_user',  # ✅ Statut free_user au lieu de lead
                'quiz_homepage',
                newsletter,
                partner_consent,
                'FR',
                'email_verified',  # ✅ Déjà vérifié (pas besoin d'email d'activation)
                True
            )
            
            logger.info(f"[{g.request_id}] Insertion utilisateur...")
            cursor.execute(insert_query, values)
            new_user.id = cursor.lastrowid
            logger.info(f"[{g.request_id}] Nouvel utilisateur créé avec ID: {new_user.id}")
            
            # ==================== LOGGER LES CONSENTEMENTS ====================
            try:
                ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
                
                # Logger le consentement newsletter
                cursor.execute("""
                    INSERT INTO user_consent_history 
                        (user_id, consent_type, consent_status, ip_address, source)
                    VALUES (%s, %s, %s, %s, %s)
                """, (new_user.id, 'newsletter', newsletter, ip_address, 'checkout_registration'))
                
                # Logger le consentement partner
                cursor.execute("""
                    INSERT INTO user_consent_history 
                        (user_id, consent_type, consent_status, ip_address, source)
                    VALUES (%s, %s, %s, %s, %s)
                """, (new_user.id, 'partner', partner_consent, ip_address, 'checkout_registration'))
                
                logger.info(f"[{g.request_id}] Consentements loggés dans l'historique")
                
            except Exception as consent_error:
                logger.error(f"[{g.request_id}] Erreur logging consentements: {str(consent_error)}")
            
            # ==================== COMMIT ====================
            mysql.connection.commit()
            logger.info(f"[{g.request_id}] Transaction committée avec succès")
            
            # ==================== NOTIFICATION SLACK ====================
            from services import slack_service, SLACK_AVAILABLE
            if SLACK_AVAILABLE and slack_service:
                try:
                    slack_data = {
                        'user_id': new_user.id,
                        'email': email,
                        'firstname': firstname,
                        'lastname': lastname,
                        'profile': 'checkout_customer',
                        'source': 'checkout_direct',
                        'phone': phone,
                        'product_id': product_id,
                        'coupon_code': coupon_code,
                        'newsletter_subscription': newsletter,
                        'partner_consent': partner_consent
                    }
                    slack_service.notify_new_lead(slack_data)
                    logger.info(f"[{g.request_id}] Notification Slack envoyée")
                except Exception as e:
                    logger.error(f"[{g.request_id}] Erreur notification Slack: {str(e)}")
            
            # ==================== CONNECTER L'UTILISATEUR ====================
            login_user(new_user)
            logger.info(f"[{g.request_id}] Utilisateur connecté automatiquement")
            flash(_('Compte créé avec succès !'), 'success')
            
            # ==================== CONSERVER PRODUCT ET COUPON ====================
            form_product_id = request.form.get('product_id')
            form_coupon_code = request.form.get('coupon_code')
            if form_product_id:
                session['checkout_product_id'] = form_product_id
            if form_coupon_code:
                session['checkout_coupon_code'] = form_coupon_code
            
            logger.info(f"[{g.request_id}] === FIN INSCRIPTION CHECKOUT - REDIRECTION ===")
            
            # Rediriger vers la continuation du checkout
            return redirect(url_for('tokens.checkout_continue'))
            
        except Exception as e:
            mysql.connection.rollback()
            logger.error(f"[{g.request_id}] Erreur inscription checkout: {str(e)}", exc_info=True)
            flash(_('Une erreur est survenue lors de l\'inscription.'), 'error')
            return redirect(url_for('auth.checkout_auth', product_id=product_id, coupon_code=coupon_code))
        
        finally:
            cursor.close()
            logger.info(f"[{g.request_id}] Cursor fermé")
    
    # ==================== AFFICHAGE DU FORMULAIRE ====================
    return render_template(
        'auth/checkout_auth.html',
        login_form=login_form,
        register_form=register_form,
        product_id=product_id,
        coupon_code=coupon_code
    )


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """
    Réinitialise le mot de passe d'un utilisateur existant
    """
    try:
        logger.info(f"[reset_password] Tentative de réinitialisation avec token: {token[:10]}...")
        
        # Récupérer l'utilisateur avec ce token
        cursor = current_app.mysql.connection.cursor(DictCursor)
        cursor.execute("""
            SELECT user_id, email, firstname, lastname, invite_expiry, user_status
            FROM users 
            WHERE invite_token = %s
        """, (token,))
        
        user_data = cursor.fetchone()
        
        if not user_data:
            logger.warning(f"[reset_password] Token invalide: {token}")
            flash("Lien de réinitialisation invalide ou expiré.", "error")
            cursor.close()
            return redirect(url_for('auth.login'))
        
        # Vérifier l'expiration du token
        if user_data['invite_expiry'] and user_data['invite_expiry'] < datetime.now():
            logger.warning(f"[reset_password] Token expiré pour {user_data['email']}")
            cursor.close()
            flash("Ce lien a expiré. Veuillez demander un nouveau lien.", "error")
            return redirect(url_for('auth.forgot_password'))
        
        # === MÉTHODE GET : Afficher le formulaire ===
        if request.method == 'GET':
            cursor.close()
            logger.info(f"[reset_password] Affichage du formulaire pour {user_data['email']}")
            return render_template('auth/reset_password.html', 
                                 email=user_data['email'],
                                 firstname=user_data['firstname'],
                                 token=token)
        
        # === MÉTHODE POST : Traiter la soumission ===
        new_password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        # Validations
        if not new_password or not confirm_password:
            flash("Veuillez renseigner les deux champs de mot de passe.", "error")
            cursor.close()
            return render_template('auth/reset_password.html',
                                 email=user_data['email'],
                                 firstname=user_data['firstname'],
                                 token=token)
        
        if new_password != confirm_password:
            flash("Les mots de passe ne correspondent pas.", "error")
            cursor.close()
            return render_template('auth/reset_password.html',
                                 email=user_data['email'],
                                 firstname=user_data['firstname'],
                                 token=token)
        
        if len(new_password) < 8:
            flash("Le mot de passe doit contenir au moins 8 caractères.", "error")
            cursor.close()
            return render_template('auth/reset_password.html',
                                 email=user_data['email'],
                                 firstname=user_data['firstname'],
                                 token=token)
        
        # Hacher le nouveau mot de passe
        hashed_password = generate_password_hash(new_password)
        
        # Mettre à jour le mot de passe et supprimer le token
        cursor.execute("""
            UPDATE users 
            SET password = %s,
                invite_token = NULL,
                invite_expiry = NULL,
                updated_at = NOW()
            WHERE user_id = %s
        """, (hashed_password, user_data['user_id']))
        
        current_app.mysql.connection.commit()
        cursor.close()
        
        logger.info(f"[reset_password] ✅ Mot de passe réinitialisé pour {user_data['email']}")
        
        # Auto-login après reset password
        user = User.get_by_id(user_data['user_id'])
        if user:
            login_user(user)
            logger.info(f"[reset_password] Auto-login après reset pour {user_data['email']}")
            flash("Mot de passe réinitialisé et connecté ! 🎉", "success")
            
            after_login = session.pop('after_login_redirect', None)
            if after_login:
                return redirect(after_login)
            return redirect(url_for('dashboard.index'))
        
        flash("Ton mot de passe a été réinitialisé avec succès ! Tu peux maintenant te connecter. 🎉", "success")
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"[reset_password] Erreur: {str(e)}", exc_info=True)
        flash("Une erreur est survenue. Veuillez réessayer.", "error")
        return redirect(url_for('auth.forgot_password'))

@auth_bp.route('/profils-comme-toi')
def gallery():
    print(f"=== DEBUG PROFILS ===")
    print(f"Nombre de profils: {len(PROFILS)}")
    if PROFILS:
        print(f"Premier: {PROFILS[0].get('name', 'pas de name')}")
    else:
        print("PROFILS EST VIDE !")
    print(f"=====================")
    
    return render_template('pages/tilto_gallery.html',
        profils=PROFILS,
        profils_json=json.dumps(PROFILS, ensure_ascii=False)
    )