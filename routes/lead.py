from flask import Blueprint, request, jsonify, render_template, redirect, url_for, flash, g, current_app, session
from flask_babel import gettext as _
from extensions import mysql, csrf, limiter, mail
from flask_login import login_required, login_user, current_user
from flask_mail import Message
import logging
import os
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import json
import re
from models import User
import secrets
import string
from datetime import datetime, timedelta
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from services import send_email
from extensions import csrf

# Configuration du logger
logger = logging.getLogger('lead_bp')

# Création du blueprint
lead_bp = Blueprint('lead', __name__, url_prefix='/lead')

def generate_unique_token(length=30):
    """Génère un token aléatoire sécurisé"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def send_welcome_email(email, firstname):
    """
    Envoie un email de bienvenue après le quiz avec instructions pour Magic Link
    
    Args:
        email (str): Email du destinataire
        firstname (str): Prénom du destinataire
    
    Returns:
        bool: True si l'email a été envoyé, False sinon
    """
    try:
        subject = "Bienvenue sur Tilto ! Tes résultats arrivent bientôt 🎉"
        
        # URL de connexion
        login_url = url_for('auth.login', _external=True)

        dashboard_url = url_for('dashboard.index', _external=True)
        
        # Données pour le template
        email_data = {
            'firstname': firstname,
            'email': email,
            'login_url': login_url,
            'dashboard_url': dashboard_url,
            'now': datetime.now()
        }
        
        # Générer le contenu HTML via template Jinja2
        html_content = render_template('emails/welcome.html', **email_data)
        
        # Envoyer l'email
        result = send_email(
            to_email=email,
            subject=subject,
            html_content=html_content
        )
        
        if result.get('success', False):
            logger.info(f"✅ Email de bienvenue envoyé à {email}")
            return True
        else:
            logger.error(f"❌ Échec envoi email de bienvenue: {result.get('message', 'Erreur inconnue')}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Erreur envoi email de bienvenue: {str(e)}", exc_info=True)
        return False


@lead_bp.route('/capture', methods=['POST'])
@csrf.exempt
@limiter.limit("7 per minute")
@limiter.limit("10 per hour")
def capture():
    """
    Endpoint pour capturer un nouveau lead depuis le quiz homepage
    Version simplifiée : firstname + email uniquement
    Pas de token d'activation, email de bienvenue avec instructions Magic Link
    AUTO-LOGIN après création du compte pour accès direct au dashboard
    """
    try:
        # Générer un request_id si il n'existe pas
        if not hasattr(g, 'request_id') or not g.request_id:
            g.request_id = str(uuid.uuid4())
        
        honeypot = request.form.get('website', '').strip()
        if honeypot:
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté - honey pot rempli: '{honeypot}'")
            return jsonify({
                'success': True,
                'message': 'Merci pour votre inscription !',
                'quiz_saved': False,
                'audio_saved': False
            }), 200
        
        # Ajout de logs pour debug
        logger.info(f"[{g.request_id}] === DEBUT DEBUG REQUÊTE ===")
        logger.info(f"[{g.request_id}] Tentative de capture lead")
        logger.info(f"[{g.request_id}] Form data: {dict(request.form)}")
        logger.info(f"[{g.request_id}] Content-Type: {request.content_type}")
        logger.info(f"[{g.request_id}] Files présents: {list(request.files.keys())}")
        logger.info(f"[{g.request_id}] === FIN DEBUG REQUÊTE ===")
        
        # ===== RÉCUPÉRATION DES DONNÉES (SIMPLIFIÉ) =====
        email = request.form.get('email', '').strip().lower()
        firstname = request.form.get('firstname', '').strip()
        city = request.form.get('city', '').strip()

        source = request.form.get('lead_source', request.form.get('source', 'quiz_homepage'))
        quiz_answers = request.form.get('quiz_answers', '').strip()

        # ===== CONSENTEMENTS SIMPLIFIÉS =====
        newsletter = False
        partner_consent = False

        # Newsletter optionnelle (checkbox)
        newsletter_value = request.form.get('newsletter_consent', 'no').strip().lower()
        newsletter = (newsletter_value == 'yes')
        
        # Partner consent automatiquement "no"
        partner_consent = False
        
        logger.info(f"[{g.request_id}] Consentements - Newsletter: {newsletter}, Partner: {partner_consent}")
        
        logger.info(f"[{g.request_id}] === DEBUT DEBUG QUIZ ===")
        logger.info(f"[{g.request_id}] Source détectée: '{source}'")
        logger.info(f"[{g.request_id}] Quiz answers présent: {bool(quiz_answers)}")
        if quiz_answers:
            logger.info(f"[{g.request_id}] Quiz answers length: {len(quiz_answers)}")
            logger.info(f"[{g.request_id}] Quiz answers preview: {quiz_answers[:200]}...")
        logger.info(f"[{g.request_id}] === FIN DEBUG QUIZ ===")
        
        logger.info(f"[{g.request_id}] Données extraites - Email: {email}, Firstname: {firstname}")
        
        # ===== VALIDATIONS SIMPLIFIÉES =====
        
        if not email:
            logger.warning(f"[{g.request_id}] Tentative d'enregistrement de lead sans email")
            return jsonify({'success': False, 'message': 'Veuillez fournir une adresse email'}), 400
        
        if not firstname:
            logger.warning(f"[{g.request_id}] Tentative d'enregistrement de lead sans prénom")
            return jsonify({'success': False, 'message': 'Veuillez renseigner votre prénom'}), 400
        
        # Validation de l'email avec regex simple
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({'success': False, 'message': 'Veuillez fournir une adresse email valide'}), 400
        # 🚫 BLOCAGE DOMAINES SUSPECTS
        BLOCKED_DOMAINS = ['hello.com', 'test.com', 'example.com', 'mailinator.com', 'tempmail.com', 'guerrillamail.com', 'yopmail.com', 'throwaway.email']
        email_domain = email.split('@')[-1].lower()
        if email_domain in BLOCKED_DOMAINS:
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté - domaine bloqué: {email_domain}")
            return jsonify({
                'success': True,
                'message': 'Merci pour votre inscription !',
                'quiz_saved': False,
                'audio_saved': False
            }), 200
        
        # Connexion à la base de données
        cursor = mysql.connection.cursor()
        
        try:
            # Vérifier si l'email existe déjà
            cursor.execute("SELECT user_id, user_status, onboarding_stage FROM users WHERE email = %s", (email,))
            existing_user = cursor.fetchone()
            
            if existing_user:
                user_id, user_status, onboarding_stage = existing_user
                logger.info(f"[{g.request_id}] Email existant: user_id={user_id}, status={user_status}, stage={onboarding_stage}")
                
                cursor.close()
                return jsonify({
                    'success': False,
                    'message': 'Un compte existe déjà avec cet email. Connecte-toi ou utilise "Mot de passe oublié".',
                    'error_type': 'email_exists'
                }), 409
            
            # Déterminer le message de succès
            success_message = 'Merci ! Ton compte est créé. Ton analyse personnalisée arrive bientôt.'
            lead_interest = 'quiz_completion'  # Valeur par défaut pour le quiz
            
            logger.info(f"[{g.request_id}] Création d'un nouveau lead")
            
            # Obtenir le lang_code de manière sécurisée
            lang_code = getattr(g, 'lang_code', 'FR').upper()
            
            # Préparer les notes du quiz de manière sécurisée
            lead_notes = None
            if quiz_answers:
                try:
                    quiz_data = json.loads(quiz_answers)
                    if quiz_data and isinstance(quiz_data, dict) and len(quiz_data) > 0:
                        lead_notes = f"Réponses quiz homepage: {json.dumps(quiz_data, ensure_ascii=False)}"
                        logger.info(f"[{g.request_id}] Notes quiz préparées: {len(quiz_data)} réponses")
                    else:
                        logger.info(f"[{g.request_id}] Quiz data vide ou invalide")
                except (json.JSONDecodeError, TypeError, AttributeError) as e:
                    logger.warning(f"[{g.request_id}] Erreur parsing quiz_answers: {str(e)}")

            # ===== INSERTION EN BDD (SIMPLIFIÉ - SANS TOKEN) =====
            cursor.execute("""
                INSERT INTO users (email, password, firstname, 
                                user_status, lead_interest, lead_source, newsletter_subscription, 
                                partner_consent, country_code, onboarding_stage, 
                                privacy_policy_accepted, created_at)
                VALUES (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                email,
                firstname,
                'free_user',  # ✅ Directement free_user
                lead_interest,
                source,
                newsletter,
                partner_consent,
                'FR',
                'email_verified',  # ✅ Directement vérifié
                True  # ✅ Acceptation CGU/Privacy (obligatoire via texte formulaire)
            ))
            
            # Récupérer l'ID du nouveau user
            user_id = cursor.lastrowid
            
            # ===== AUTO-LOGIN DU USER APRÈS CRÉATION =====
            try:
                user = User.get_by_id(user_id)
                if user:
                    login_user(user)
                    logger.info(f"[{g.request_id}] ✅ User auto-connecté après création compte (user_id: {user_id})")
                else:
                    logger.error(f"[{g.request_id}] ❌ Impossible de récupérer le user {user_id} pour auto-login")
            except Exception as login_error:
                logger.error(f"[{g.request_id}] ❌ Erreur auto-login: {str(login_error)}")
                # Ne pas bloquer l'inscription si l'auto-login échoue
            # ===== FIN AUTO-LOGIN =====
            
            # Logger les consentements initiaux dans l'historique
            try:
                ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
                
                # Logger le consentement newsletter
                cursor.execute("""
                    INSERT INTO user_consent_history 
                        (user_id, consent_type, consent_status, ip_address, source)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, 'newsletter', newsletter, ip_address, 'registration'))
                
                # Logger le consentement partner
                cursor.execute("""
                    INSERT INTO user_consent_history 
                        (user_id, consent_type, consent_status, ip_address, source)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, 'partner', partner_consent, ip_address, 'registration'))
                
                # ✅ Logger l'acceptation CGU/Privacy
                cursor.execute("""
                    INSERT INTO user_consent_history 
                        (user_id, consent_type, consent_status, ip_address, source)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, 'privacy_policy', True, ip_address, 'registration'))
                
                logger.info(f"[{g.request_id}] Consentements loggés - Newsletter: {newsletter}, Partner: {partner_consent}, Privacy: True")
                
            except Exception as consent_error:
                logger.error(f"[{g.request_id}] Erreur logging consentements: {str(consent_error)}")
                
            logger.info(f"[{g.request_id}] Nouveau lead créé avec ID: {user_id}, email: {email}, source: {source}")
            
            # ===== SAUVEGARDE DES RÉPONSES QUIZ AVEC AUDIO =====
            quiz_saved = False
            audio_saved = False
            
            if quiz_answers:
                try:
                    logger.info(f"[{g.request_id}] === DEBUT SAUVEGARDE QUIZ AVEC AUDIO ===")
                    quiz_data = json.loads(quiz_answers)
                    
                    if quiz_data and isinstance(quiz_data, dict) and len(quiz_data) > 0:
                        # Detect conversation mode (dynamic coach) vs classic quiz
                        is_conversation_mode = '_conversation' in quiz_data or any(k.startswith('turn_') for k in quiz_data)

                        # Traiter les fichiers audio s'ils existent
                        audio_urls = {}

                        # Vérifier s'il y a des fichiers audio dans la requête
                        for field_name in request.files:
                            if field_name.startswith('audio_q'):
                                question_id = field_name.replace('audio_q', '')
                                audio_file = request.files[field_name]
                                
                                # Détecter le format audio (WebM ou MP4 pour Safari iOS)
                                file_format = None
                                if hasattr(audio_file, 'content_type') and audio_file.content_type:
                                    content_type_lower = audio_file.content_type.lower()
                                    if 'mp4' in content_type_lower:
                                        file_format = '.mp4'
                                    elif 'webm' in content_type_lower:
                                        file_format = '.webm'
                                
                                logger.info(f"[{g.request_id}] Traitement audio Q{question_id}: "
                                          f"taille={audio_file.content_length}, "
                                          f"type={audio_file.content_type}, "
                                          f"format détecté={file_format}")
                                
                                try:
                                    # Sauvegarder l'audio dans le cloud
                                    audio_blob = audio_file.read()
                                    
                                    try:
                                        from services.audio_service import AudioService
                                        
                                        result = AudioService.save_quiz_audio_to_cloud(
                                            audio_blob, 
                                            'pack_clarte', 
                                            question_id, 
                                            user_id,
                                            file_format=file_format
                                        )
                                        
                                        if result['success']:
                                            audio_urls[question_id] = result['url']
                                            audio_saved = True
                                            logger.info(f"[{g.request_id}] Audio Q{question_id} sauvegardé: "
                                                      f"{result['url']} (format: {result.get('format', 'unknown')})")
                                        else:
                                            logger.error(f"[{g.request_id}] Erreur audio Q{question_id}: {result['error']}")
                                            
                                    except ImportError as ie:
                                        logger.error(f"[{g.request_id}] Service AudioService non disponible: {str(ie)}")
                                        
                                except Exception as audio_error:
                                    logger.error(f"[{g.request_id}] Erreur traitement audio Q{question_id}: {str(audio_error)}")
                        
                        # Sauvegarder les réponses avec les URLs audio
                        logger.info(f"[{g.request_id}] Appel save_homepage_quiz_answers_with_audio avec "
                                   f"{len(quiz_data)} réponses et {len(audio_urls)} audios")
                        
                        try:
                            quiz_id = request.form.get('quiz_id', 'pack_clarte')
                            if is_conversation_mode:
                                save_conversation_answers(user_id, quiz_data, audio_urls, cursor, g.request_id, quiz_id, city=city)
                            else:
                                save_homepage_quiz_answers_with_audio(user_id, quiz_data, audio_urls, cursor, g.request_id, quiz_id)
                            quiz_saved = True
                            
                            if audio_saved:
                                success_message = 'Merci ! Vos réponses et enregistrements audio ont été sauvegardés.'
                            else:
                                success_message = 'Merci ! Vos réponses ont été enregistrées.'
                                
                            logger.info(f"[{g.request_id}] Quiz et audio sauvegardés avec succès pour user {user_id}")
                            
                        except Exception as save_error:
                            logger.error(f"[{g.request_id}] Erreur sauvegarde quiz/audio: {str(save_error)}", exc_info=True)
                            quiz_saved = False
                            audio_saved = False
                        
                    else:
                        logger.warning(f"[{g.request_id}] Quiz data vide après parsing")
                        
                    logger.info(f"[{g.request_id}] === FIN SAUVEGARDE QUIZ AVEC AUDIO ===")
                    
                except json.JSONDecodeError as e:
                    logger.error(f"[{g.request_id}] Erreur JSON parsing quiz: {str(e)}")
                except Exception as e:
                    logger.error(f"[{g.request_id}] Erreur sauvegarde quiz: {str(e)}", exc_info=True)
            else:
                logger.info(f"[{g.request_id}] Pas de quiz_answers à sauvegarder")
            
            mysql.connection.commit()
            logger.info(f"[{g.request_id}] Transaction committée avec succès")

            # ===== CRÉATION AUTOMATIQUE DU TOKEN PAID (ACCÈS GRATUIT) =====
            if quiz_saved:
                try:
                    token_cursor = mysql.connection.cursor()
                    
                    # Générer un token_code unique
                    token_code = f"FREE_{user_id}_{secrets.token_hex(8).upper()}"
                    
                    # Créer un token paid pour donner accès à l'analyse
                    quiz_id = request.form.get('quiz_id', 'pack_clarte')
                    token_cursor.execute("""
                        INSERT INTO tokens (
                            token_code, user_id, quiz_id, token_type, 
                            description, country_code, is_used, created_at
                        )
                        VALUES (%s, %s, %s, 'free', %s, 'FR', FALSE, NOW())
                    """, (
                        token_code,
                        user_id,
                        quiz_id,
                        'Accès gratuit - Quiz complété'
                    ))
                    
                    mysql.connection.commit()
                    logger.info(f"[{g.request_id}] ✅ Token FREE créé: {token_code} pour user {user_id}")
                    
                except Exception as token_error:
                    logger.error(f"[{g.request_id}] ❌ Erreur création token paid: {str(token_error)}")
                finally:
                    token_cursor.close()

            # ============================================================
            # 🚀 LANCER L'ANALYSE ASYNC AUTOMATIQUEMENT
            # ============================================================
            if quiz_saved:
                try:
                    from services.async_analysis_service import AsyncAnalysisService
                    
                    async_cursor = mysql.connection.cursor()
                    
                    # Récupérer le quiz_id depuis le formulaire
                    quiz_id = request.form.get('quiz_id', 'pack_clarte')
                    
                    # Déterminer le result_step_id selon le quiz
                    if quiz_id == 'pack_orientation':
                        result_step_id = 'orientation_v1'  # À adapter selon votre config
                    else:
                        result_step_id = 'career_path_v4'
                    
                    # Récupérer les prompts par défaut depuis quiz_result
                    async_cursor.execute("""
                        SELECT prompt_instruction, prompt_knowledge, validation_criteria
                        FROM quiz_result
                        WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
                    """, (quiz_id, result_step_id))
                    
                    step_config = async_cursor.fetchone()
                    
                    if step_config:
                        generation_params = {
                            'instructions': step_config[0] or '',
                            'knowledge': step_config[1] or '',
                            'validation_criteria': step_config[2] or ''
                        }
                        
                        # Créer le job async
                        job_uuid = AsyncAnalysisService.create_async_job(
                            cursor=async_cursor,
                            user_id=user_id,
                            quiz_id=quiz_id,  # ← Utiliser la variable, pas hardcodé
                            step_id=result_step_id,
                            generation_params=generation_params,
                            admin_id=None,
                            generator_type='user',
                            order_id=None
                        )
                        
                        mysql.connection.commit()
                        logger.info(f"[{g.request_id}] 🚀 Async analysis job created: {job_uuid} for user {user_id}, quiz {quiz_id}")
                    else:
                        logger.warning(f"[{g.request_id}] No step config found for {quiz_id}/{result_step_id}, skipping async analysis")
                    
                    async_cursor.close()
                        
                except Exception as async_error:
                    # Ne pas bloquer l'inscription si l'async échoue
                    logger.error(f"[{g.request_id}] Failed to create async analysis job: {async_error}", exc_info=True)

            # ===== ENVOI EMAIL DE BIENVENUE =====
            try:
                send_welcome_email(email, firstname)
                logger.info(f"[{g.request_id}] Email de bienvenue envoyé à {email}")
            except Exception as email_error:
                logger.error(f"[{g.request_id}] Erreur envoi email de bienvenue: {str(email_error)}")
                # Ne pas faire échouer l'inscription si l'email échoue
            
            # Notification Slack pour nouveau lead
            from services import slack_service, SLACK_AVAILABLE
            if SLACK_AVAILABLE and slack_service:
                try:
                    logger.info(f"[{g.request_id}] Tentative d'envoi notification Slack...")
                    slack_data = {
                        'user_id': user_id,
                        'email': email,
                        'firstname': firstname,
                        'lastname': '',
                        'profile': lead_interest,
                        'nb_accompagnement': None,
                        'source': source,
                        'phone': None,
                        'lead_interest': lead_interest,
                        'has_quiz_answers': quiz_saved,
                        'has_audio_responses': audio_saved,
                        'newsletter_subscription': newsletter,
                    }
                    result = slack_service.notify_new_lead(slack_data)
                    logger.info(f"[{g.request_id}] Notification Slack envoyée: {result}")
                except Exception as e:
                    logger.error(f"[{g.request_id}] Erreur notification Slack: {str(e)}")
            else:
                logger.warning(f"[{g.request_id}] Service Slack non disponible - notification ignorée")
            
            logger.info(f"[{g.request_id}] Lead enregistré avec succès: {email}")
            
            success_message = '✅ Compte créé avec succès ! Redirection vers ton espace...'

            # Préparation de la réponse JSON
            response_data = {
                'success': True, 
                'message': success_message,
                'quiz_saved': quiz_saved,
                'audio_saved': audio_saved,
                'redirect_url': '/dashboard'  # ✅ Maintenant le user est connecté !
            }
            
            logger.info(f"[{g.request_id}] === PRÉPARATION RÉPONSE JSON ===")
            logger.info(f"[{g.request_id}] Response data: {response_data}")
            
            # Créer explicitement la réponse JSON avec headers
            response = jsonify(response_data)
            response.status_code = 200
            response.headers['Content-Type'] = 'application/json'
            
            logger.info(f"[{g.request_id}] === RÉPONSE JSON CRÉÉE AVEC SUCCÈS ===")
            
            return response
            
        except Exception as e:
            mysql.connection.rollback()
            logger.error(f"[{g.request_id}] Erreur base de données: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'message': 'Une erreur technique est survenue. Veuillez réessayer.'}), 500
        
        finally:
            cursor.close()
        
    except Exception as e:
        request_id = getattr(g, 'request_id', str(uuid.uuid4()))
        logger.error(f"[{request_id}] Erreur lors de l'enregistrement du lead: {str(e)}", exc_info=True)
        return jsonify({'success': False, 'message': 'Une erreur est survenue. Veuillez réessayer.'}), 500


def save_homepage_quiz_answers_with_audio(user_id, quiz_answers_dict, audio_urls_dict, cursor, request_id, quiz_id='pack_clarte'):

    """
    Sauvegarde les réponses du quiz homepage avec gestion des fichiers audio
    
    Args:
        quiz_id: ID du quiz (pack_clarte ou pack_orientation)
    """
    try:

        logger.info(f"[{request_id}] 🎯 Début sauvegarde quiz avec audio pour user {user_id}, quiz {quiz_id}")
        logger.info(f"[{request_id}] 📊 Données: {len(quiz_answers_dict)} réponses, {len(audio_urls_dict)} audios")
        
        # Vérifier que le quiz existe
        cursor.execute("SELECT quiz_id FROM quiz_catalog WHERE quiz_id = %s", (quiz_id,))
        if not cursor.fetchone():
            logger.error(f"[{request_id}] ❌ Quiz {quiz_id} n'existe pas dans quiz_catalog")
            raise Exception(f"Quiz {quiz_id} non trouvé")
        
        # Créer la session quiz directement
        cursor.execute("""
            INSERT INTO quiz_user (
                quiz_id, user_id, start_time, quiz_status, 
                questions_answered_count, question_history,
                created_at, updated_at
            ) VALUES (%s, %s, CURRENT_TIMESTAMP, 'in_progress', 0, '[]',
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (quiz_id, user_id))
        
        quiz_session_id = cursor.lastrowid
        logger.info(f"[{request_id}] ✅ Session quiz créée: {quiz_session_id}")
        
        # Construire l'historique des questions depuis les réponses
        question_history = []
        
        # Récupérer le nombre total de questions du quiz
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM quiz_questions 
            WHERE quiz_id = %s AND is_active = TRUE
        """, (quiz_id,))
        result = cursor.fetchone()
        total_questions = result[0] if result else 0
        
        logger.info(f"[{request_id}] 📝 Total questions dans le quiz: {total_questions}")
        
        # Récupérer toutes les questions du quiz pour validation
        cursor.execute("""
            SELECT question_id, question_ranking - 1 as question_index
            FROM quiz_questions 
            WHERE quiz_id = %s AND is_active = TRUE
            ORDER BY question_ranking
        """, (quiz_id,))
        valid_questions = {str(row[0]): row[1] for row in cursor.fetchall()}
        
        logger.info(f"[{request_id}] 🔍 Questions valides: {list(valid_questions.keys())}")
        logger.info(f"[{request_id}] 📥 Questions reçues: {list(quiz_answers_dict.keys())}")
        logger.info(f"[{request_id}] 🎙️ Audios reçus: {list(audio_urls_dict.keys())}")
        
        # Sauvegarder chaque réponse
        saved_answers = 0
        for question_id, answer_data in quiz_answers_dict.items():
            try:
                logger.info(f"[{request_id}] 🔄 Traitement question {question_id}")
                
                # Vérifier que la question existe dans le quiz
                # Exception pour Q26 (localisation du lead form)
                if question_id not in valid_questions and question_id != '26':
                    logger.warning(f"[{request_id}] ⚠️ Question {question_id} non trouvée dans le quiz {quiz_id}")
                    continue
                
                # Pour Q26, utiliser un index fictif (ne compte pas dans le quiz)
                if question_id not in valid_questions:
                    question_index = -1
                
                question_id_int = int(question_id)
                question_index = valid_questions[question_id]
                
                if question_index not in question_history:
                    question_history.append(question_index)
                
                # Préparer les données de réponse
                answer_value = answer_data.get('value', [])
                answer_text = answer_data.get('text', '')
                
                # Vérifier s'il y a un audio pour cette question et le traiter
                if question_id in audio_urls_dict and audio_urls_dict[question_id]:
                    audio_url = audio_urls_dict[question_id]
                    
                    # Si c'est une réponse audio pure (marquée [AUDIO_RESPONSE])
                    if answer_value == ['[AUDIO_RESPONSE]']:
                        answer_text = audio_url
                        logger.info(f"[{request_id}] 🎙️ Audio URL pure pour Q{question_id}: {audio_url}")
                    else:
                        # Combiner texte et audio si les deux existent
                        if answer_text and not answer_text.startswith('[Audio'):
                            answer_text = f"{answer_text}\n[AUDIO: {audio_url}]"
                        else:
                            answer_text = audio_url
                        logger.info(f"[{request_id}] 🎙️ Audio URL combinée pour Q{question_id}: {audio_url}")
                
                # S'assurer que answer_value est une liste
                if not isinstance(answer_value, list):
                    answer_value = [answer_value]
                
                answer_value_json = json.dumps(answer_value)
                
                logger.info(f"[{request_id}] 💾 Sauvegarde Q{question_id}: value={answer_value}, text='{answer_text[:100]}{'...' if len(answer_text) > 100 else ''}'")
                
                # Insérer la réponse
                cursor.execute('''
                    INSERT INTO answer_user 
                    (quiz_session_id, question_id, answer_value, answer_text, created_at, updated_at) 
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ''', (quiz_session_id, question_id_int, answer_value_json, answer_text))
                
                saved_answers += 1
                logger.info(f"[{request_id}] ✅ Réponse Q{question_id} sauvegardée")
                
            except (ValueError, KeyError) as e:
                logger.error(f"[{request_id}] ❌ Erreur traitement question {question_id}: {e}")
                continue
            except Exception as e:
                logger.error(f"[{request_id}] ❌ Erreur inattendue question {question_id}: {e}")
                continue
        
        # Trier l'historique
        question_history.sort()
        
        # Déterminer le statut final
        questions_answered = saved_answers
        is_completed = questions_answered >= total_questions and total_questions > 0
        final_status = 'completed' if is_completed else 'in_progress'
        
        logger.info(f"[{request_id}] 📊 Résumé: {questions_answered}/{total_questions} réponses, statut: {final_status}")
        
        # Mettre à jour la session quiz
        if is_completed:
            cursor.execute('''
                UPDATE quiz_user 
                SET questions_answered_count = %s,
                    quiz_status = %s,
                    question_history = %s,
                    end_time = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            ''', (questions_answered, final_status, json.dumps(question_history), quiz_session_id))
        else:
            cursor.execute('''
                UPDATE quiz_user 
                SET questions_answered_count = %s,
                    quiz_status = %s,
                    question_history = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            ''', (questions_answered, final_status, json.dumps(question_history), quiz_session_id))
        
        logger.info(f"[{request_id}] ✅ Quiz session {quiz_session_id} mise à jour avec succès")
        logger.info(f"[{request_id}] 📈 Historique final: {question_history}")
        logger.info(f"[{request_id}] 🎙️ Audios sauvegardés: {len(audio_urls_dict)}")
        
        return quiz_session_id
        
    except Exception as e:
        logger.error(f"[{request_id}] ❌ Erreur critique lors de la sauvegarde du quiz avec audio: {str(e)}", exc_info=True)
        raise


@lead_bp.route('/activate/<token>', methods=['GET'])
def activate_account(token):
    """
    ⚠️ ROUTE CONSERVÉE POUR COMPATIBILITÉ AVEC LES ANCIENS LEADS
    Les nouveaux leads (quiz) n'utilisent plus cette route
    Active le compte SANS mot de passe et redirige vers le dashboard
    """
    try:
        cursor = mysql.connection.cursor()
        
        # Vérifier le token
        cursor.execute("""
            SELECT user_id, email, firstname, lastname, invite_expiry, onboarding_stage
            FROM users 
            WHERE invite_token = %s
        """, (token,))
        
        user_data = cursor.fetchone()
        
        if not user_data:
            flash('Lien d\'activation invalide.', 'error')
            cursor.close()
            return redirect(url_for('dashboard.index'))
        
        user_id, email, firstname, lastname, invite_expiry, onboarding_stage = user_data
        
        # Vérifier expiration
        if invite_expiry and datetime.now() > invite_expiry:
            flash('Ce lien a expiré. Redemande un lien via "Mot de passe oublié".', 'error')
            cursor.close()
            return redirect(url_for('auth.login'))
        
        # Déjà activé
        if onboarding_stage == 'email_verified':
            flash('Compte déjà activé. Connecte-toi.', 'info')
            cursor.close()
            return redirect(url_for('auth.login'))
        
        # ACTIVER LE COMPTE SANS MOT DE PASSE
        cursor.execute("""
            UPDATE users 
            SET user_status = 'free_user',
                onboarding_stage = 'email_verified',
                invite_token = NULL,
                invite_expiry = NULL,
                updated_at = NOW()
            WHERE user_id = %s
        """, (user_id,))
        
        mysql.connection.commit()
        cursor.close()
        
        logger.info(f"✅ Compte activé SANS mot de passe pour user_id: {user_id}")
        
        # AUTO-LOGIN ET REDIRECTION DASHBOARD
        user = User.get_by_id(user_id)
        if user:
            login_user(user)
            flash(f'Bienvenue {firstname} ! Ton compte est activé. 🎉', 'success')
            return redirect(url_for('dashboard.index'))
        
        # Fallback si l'auto-login échoue
        flash('Compte activé ! Connecte-toi.', 'success')
        return redirect(url_for('auth.login'))
        
    except Exception as e:
        logger.error(f"❌ Erreur activation: {str(e)}", exc_info=True)
        flash('Erreur lors de l\'activation.', 'error')
        return redirect(url_for('dashboard.index'))


@lead_bp.route('/manage', methods=['GET'])
@login_required
def manage_leads():
    """
    Interface d'administration des leads (protégée, réservée aux admins)
    """
    # Vérifier si l'utilisateur est administrateur
    if current_user.user_status != 'admin':
        flash(_('Vous n\'avez pas les droits pour accéder à cette page.'), 'error')
        return redirect(url_for('auth.home'))
    
    # Récupérer des statistiques
    cursor = mysql.connection.cursor()
    
    # Nombre total de leads
    cursor.execute("SELECT COUNT(*) FROM users WHERE user_status = 'lead'")
    total_leads = cursor.fetchone()[0]
    
    # Leads par statut
    cursor.execute("""
        SELECT lead_status, COUNT(*) as count 
        FROM users 
        WHERE user_status = 'lead' AND lead_status IS NOT NULL
        GROUP BY lead_status
    """)
    status_stats = cursor.fetchall()
    
    # Leads par intérêt
    cursor.execute("""
        SELECT lead_interest, COUNT(*) as count 
        FROM users 
        WHERE user_status = 'lead' AND lead_interest IS NOT NULL
        GROUP BY lead_interest 
        ORDER BY count DESC
    """)
    interest_stats = cursor.fetchall()
    
    # Leads par source
    cursor.execute("""
        SELECT lead_source, COUNT(*) as count 
        FROM users 
        WHERE user_status = 'lead' AND lead_source IS NOT NULL
        GROUP BY lead_source 
        ORDER BY count DESC
    """)
    source_stats = cursor.fetchall()
    
    # Leads par étape d'onboarding
    cursor.execute("""
        SELECT onboarding_stage, COUNT(*) as count 
        FROM users 
        WHERE user_status = 'lead' AND onboarding_stage IS NOT NULL
        GROUP BY onboarding_stage 
        ORDER BY count DESC
    """)
    onboarding_stats = cursor.fetchall()
    
    # Statistiques nb_accompagnement pour les professionnels en orientation
    cursor.execute("""
        SELECT nb_accompagnement, COUNT(*) as count 
        FROM users 
        WHERE user_status = 'lead' AND lead_interest = 'professionnel_orientation' AND nb_accompagnement IS NOT NULL
        GROUP BY nb_accompagnement 
        ORDER BY count DESC
    """)
    accompagnement_stats = cursor.fetchall()
    
    # Récupérer les leads avec pagination
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    # Filtre optionnel
    status_filter = request.args.get('status', '')
    source_filter = request.args.get('source', '')
    
    # Construire la requête avec filtres
    query = """
        SELECT user_id, username, email, phone_number, lead_interest, lead_status, lead_source, 
            created_at, newsletter_subscription, last_contacted, lead_notes,
            onboarding_stage, nb_accompagnement, firstname, lastname
        FROM users
        WHERE user_status = 'lead'
    """
    params = []
    
    if status_filter:
        query += " AND lead_status = %s"
        params.append(status_filter)
    
    if source_filter:
        query += " AND lead_source = %s"
        params.append(source_filter)
    
    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, offset])
    
    cursor.execute(query, params)
    leads = cursor.fetchall()
    
    # Nombre total pour pagination
    count_query = "SELECT COUNT(*) FROM users WHERE user_status = 'lead'"
    count_params = []
    
    if status_filter:
        count_query += " AND lead_status = %s"
        count_params.append(status_filter)
    
    if source_filter:
        count_query += " AND lead_source = %s"
        count_params.append(source_filter)
    
    cursor.execute(count_query, count_params)
    total_count = cursor.fetchone()[0]
    
    cursor.close()
    
    total_pages = (total_count + per_page - 1) // per_page
    
    return render_template('admin/leads.html', 
                           leads=leads, 
                           total_leads=total_leads,
                           status_stats=status_stats,
                           interest_stats=interest_stats,
                           source_stats=source_stats,
                           onboarding_stats=onboarding_stats,
                           accompagnement_stats=accompagnement_stats,
                           page=page, 
                           total_pages=total_pages,
                           status_filter=status_filter,
                           source_filter=source_filter)


@lead_bp.route('/update/<int:lead_id>', methods=['POST'])
@login_required
def update_lead(lead_id):
    """
    Mettre à jour le statut d'un lead
    """
    # Vérifier si l'utilisateur est administrateur
    if current_user.user_status != 'admin':
        return jsonify({'success': False, 'message': _('Accès non autorisé')}), 403
    
    try:
        data = request.json
        status = data.get('status')
        notes = data.get('notes', '')
        old_status = None
        
        cursor = mysql.connection.cursor()
        
        # Récupérer l'ancien statut pour la notification
        cursor.execute("""
            SELECT lead_status, firstname, lastname, email 
            FROM users 
            WHERE user_id = %s AND user_status = 'lead'
        """, (lead_id,))
        
        lead_info = cursor.fetchone()
        if lead_info:
            old_status = lead_info[0]
        
        if status:
            cursor.execute("""
                UPDATE users 
                SET lead_status = %s, lead_notes = %s, 
                    last_contacted = NOW(), updated_at = NOW()
                WHERE user_id = %s AND user_status = 'lead'
            """, (status, notes, lead_id))
        else:
            cursor.execute("""
                UPDATE users 
                SET lead_notes = %s, updated_at = NOW()
                WHERE user_id = %s AND user_status = 'lead'
            """, (notes, lead_id))
        
        affected_rows = cursor.rowcount
        mysql.connection.commit()
        cursor.close()
        
        if affected_rows == 0:
            return jsonify({'success': False, 'message': _('Lead non trouvé')}), 404
        
        from services import slack_service, SLACK_AVAILABLE
        # Notification Slack pour changement de statut
        if status and old_status and status != old_status and lead_info and SLACK_AVAILABLE and slack_service:
            try:
                logger.info(f"Tentative notification Slack changement statut: {old_status} -> {status}")
                result = slack_service.notify_lead_status_update({
                    'firstname': lead_info[1],
                    'lastname': lead_info[2],
                    'email': lead_info[3]
                }, old_status, status, current_user.username)
                logger.info(f"Notification Slack changement statut envoyée: {result}")
            except Exception as e:
                logger.error(f"Erreur notification Slack changement statut: {str(e)}")
        
        return jsonify({'success': True, 'message': _('Lead mis à jour avec succès')}), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour du lead {lead_id}: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500


@lead_bp.route('/export', methods=['GET'])
@login_required
def export_leads():
    """
    Exporter les leads au format CSV
    """
    # Vérifier si l'utilisateur est administrateur
    if current_user.user_status != 'admin':
        flash(_('Vous n\'avez pas les droits pour accéder à cette page.'), 'error')
        return redirect(url_for('auth.home'))
    
    import csv
    from io import StringIO
    from flask import Response
    
    cursor = mysql.connection.cursor()
    
    # Requête SELECT pour l'export
    cursor.execute("""
        SELECT user_id, username, email, phone_number, lead_interest, lead_status, lead_source, 
            newsletter_subscription, lead_notes, country_code, created_at, updated_at, 
            last_contacted, onboarding_stage, nb_accompagnement, firstname, lastname
        FROM users 
        WHERE user_status = 'lead'
        ORDER BY created_at DESC
    """)
    
    leads = cursor.fetchall()
    cursor.close()
    
    si = StringIO()
    cw = csv.writer(si, quoting=csv.QUOTE_ALL)
    
    # Écrire l'en-tête
    cw.writerow(['ID', 'Nom d\'utilisateur', 'Email', 'Téléphone', 'Intérêt', 'Statut', 'Source', 
                'Newsletter', 'Notes', 'Pays', 'Créé le', 'Mis à jour le', 
                'Dernier contact', 'Étape d\'onboarding', 'Nb Accompagnement', 'Prénom', 'Nom'])
    
    # Écrire les données
    for lead in leads:
        lead_list = list(lead)
        # Convertir les dates en format lisible
        for i in [10, 11, 12]:
            if i < len(lead_list) and lead_list[i]:
                lead_list[i] = lead_list[i].strftime('%Y-%m-%d %H:%M:%S')
        # Convertir le booléen newsletter en chaîne
        if lead_list[7] is not None:
            lead_list[7] = 'Oui' if lead_list[7] else 'Non'
        
        cw.writerow(lead_list)
    
    response = Response(si.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename=leads_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    
    return response


@lead_bp.route('/send-invite/<int:lead_id>', methods=['POST'])
@login_required
def send_invite(lead_id):
    """
    ⚠️ CONSERVÉ POUR COMPATIBILITÉ - Envoyer une invitation à un ancien lead
    Les nouveaux leads (quiz) n'utilisent plus cette fonctionnalité
    """
    # Vérifier si l'utilisateur est administrateur
    if current_user.user_status != 'admin':
        return jsonify({'success': False, 'message': _('Accès non autorisé')}), 403
    
    try:
        cursor = mysql.connection.cursor()
        
        # Récupérer les informations du lead
        cursor.execute("""
            SELECT email, CONCAT(firstname, ' ', COALESCE(lastname, '')) as name, lead_interest, user_status
            FROM users 
            WHERE user_id = %s AND (user_status = 'lead' OR user_status = 'user')
        """, (lead_id,))
        
        lead = cursor.fetchone()
        
        if not lead:
            return jsonify({'success': False, 'message': _('Lead non trouvé')}), 404
        
        email, name, interest, user_status = lead
        
        # Générer un nouveau token d'invitation
        invite_token = generate_unique_token()
        invite_expiry = datetime.now() + timedelta(days=7)
        
        # Mettre à jour le token d'invitation
        cursor.execute("""
            UPDATE users 
            SET invite_token = %s, invite_expiry = %s,
                onboarding_stage = CASE 
                    WHEN onboarding_stage IS NULL THEN 'invited'
                    ELSE onboarding_stage 
                END,
                updated_at = NOW(), last_contacted = NOW()
            WHERE user_id = %s
        """, (invite_token, invite_expiry, lead_id))
        
        mysql.connection.commit()
        cursor.close()
        
        # Envoyer l'email d'invitation (ancienne méthode)
        from services import send_invite_email
        if send_invite_email(email, name, invite_token, interest):
            return jsonify({
                'success': True, 
                'message': _(f'Invitation envoyée à {email} avec succès')
            }), 200
        else:
            return jsonify({
                'success': False, 
                'message': _('Une erreur est survenue lors de l\'envoi de l\'email')
            }), 500
        
    except Exception as e:
        logger.error(f"Erreur lors de l'envoi de l'invitation au lead {lead_id}: {str(e)}")
        return jsonify({'success': False, 'message': str(e)}), 500

@lead_bp.route('/track-video-lp', methods=['POST'])
@csrf.exempt
def track_video_lp():
    """
    Tracker les événements de la landing page vidéo.
    Utilise activity_logs existante - compatible users connectés ET anonymes.
    """
    try:
        data = request.get_json() or {}
        
        # Infos device
        ua = (request.user_agent.string or '').lower()
        device = 'mobile' if any(m in ua for m in ['iphone', 'android', 'mobile']) else 'desktop'
        
        # Session tracking (pour relier les événements d'un même visiteur)
        if 'visitor_id' not in session:
            session['visitor_id'] = str(uuid.uuid4())[:32]
        
        session_id = str(session.get('_id', uuid.uuid4()))[:128]
        
        # User ID si connecté, sinon NULL
        user_id = current_user.id if current_user.is_authenticated else None
        
        cursor = current_app.mysql.connection.cursor()
        cursor.execute('''
            INSERT INTO activity_logs 
            (user_id, session_id, event_type, page_path, referrer, device_type, extra_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (
            user_id,
            session_id,
            data.get('event', 'lp_unknown')[:50],
            data.get('url', '/decouvre-tilto')[:255],
            (request.referrer or '')[:500],
            device,
            json.dumps({
                'visitor_id': session.get('visitor_id'),
                'source': data.get('source', 'direct'),
                'variant': data.get('variant', 'unknown'),  # ← AJOUTÉ
                'campaign': data.get('campaign', 'none'),
                'video_started': data.get('videoStarted', False),
                'video_completed': data.get('videoCompleted', False),
                'watch_time_seconds': data.get('watchTime', 0),
                'timestamp': data.get('timestamp')
            })
        ))
        current_app.mysql.connection.commit()
        cursor.close()
        
        logger.info(f"📊 LP Video: {data.get('event')} | src={data.get('source')} | var={data.get('variant')} | device={device}")
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        logger.error(f"LP Tracking error: {e}")
        return jsonify({'status': 'error'}), 200  # 200 pour pas casser l'UX

@lead_bp.route('/pro-contact', methods=['POST'])
@limiter.limit("2 per minute")
@limiter.limit("3 per hour")
def pro_contact():
    """
    Endpoint pour capturer un lead B2B depuis la landing page Tilto Pro.
    Stocke dans la table pro_leads (séparée des users B2C).
    Envoie une notification Slack.
    """
    try:
        if not hasattr(g, 'request_id') or not g.request_id:
            g.request_id = str(uuid.uuid4())

        # ===== RÉCUPÉRATION =====
        firstname = request.form.get('firstname', '').strip()
        lastname = request.form.get('lastname', '').strip()
        email = request.form.get('email', '').strip().lower()
        activite = request.form.get('activite', '').strip()
        source = request.form.get('source', 'tilto_pro_landing').strip()
        # Honeypot anti-bot
        honeypot = request.form.get('website', '').strip()
        if honeypot:
            logger.warning(f"[{g.request_id}] 🤖 Bot détecté pro-contact - honeypot: '{honeypot}'")
            return jsonify({'success': True, 'message': 'Merci ! On vous recontacte sous 24h.'}), 200

        logger.info(f"[{g.request_id}] Pro lead: {firstname} {lastname} <{email}> — {activite}")

        # ===== VALIDATIONS =====
        if not firstname or not lastname:
            return jsonify({'success': False, 'message': 'Merci de renseigner votre prénom et nom.'}), 400

        if not email:
            return jsonify({'success': False, 'message': 'Merci de renseigner votre email.'}), 400

        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return jsonify({'success': False, 'message': 'Adresse email invalide.'}), 400

        # Blocage domaines jetables
        BLOCKED_DOMAINS = [
            'mailinator.com', 'tempmail.com', 'guerrillamail.com',
            'yopmail.com', 'throwaway.email', 'test.com', 'example.com'
        ]
        email_domain = email.split('@')[-1].lower()
        if email_domain in BLOCKED_DOMAINS:
            logger.warning(f"[{g.request_id}] 🤖 Pro lead bloqué — domaine suspect: {email_domain}")
            return jsonify({'success': True, 'message': 'Merci ! On vous recontacte sous 24h.'}), 200

        # ===== IP =====
        ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
        if ip_address and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()

        # ===== INSERTION BDD =====
        cursor = mysql.connection.cursor()

        try:
            # Vérifier doublon email
            cursor.execute("SELECT id, status FROM pro_leads WHERE email = %s ORDER BY created_at DESC LIMIT 1", (email,))
            existing = cursor.fetchone()

            if existing:
                lead_id, lead_status = existing
                logger.info(f"[{g.request_id}] Pro lead existant: id={lead_id}, status={lead_status}")
                cursor.close()
                return jsonify({
                    'success': False,
                    'message': 'Vous êtes déjà inscrit·e ! On vous recontacte très vite.'
                }), 409
            else:
                # Nouveau lead
                cursor.execute("""
                    INSERT INTO pro_leads (firstname, lastname, email, activite, source, status, ip_address)
                    VALUES (%s, %s, %s, %s, %s, 'new', %s)
                """, (firstname, lastname, email, activite, source, ip_address))
                lead_id = cursor.lastrowid
                mysql.connection.commit()

                logger.info(f"[{g.request_id}] ✅ Nouveau pro lead créé: id={lead_id}, email={email}")

            # ===== NOTIFICATION SLACK =====
            try:
                from services import slack_service, SLACK_AVAILABLE
                if SLACK_AVAILABLE and slack_service:
                    activite_labels = {
                        'coach_independant': 'Coach indépendant·e',
                        'coach_transition': 'Coach transition / reconversion',
                        'bilan': 'Bilan de compétences',
                        'cep': 'CEP',
                        'cabinet': 'Cabinet',
                        'autre': 'Autre',
                    }
                    activite_display = activite_labels.get(activite, activite or 'Non renseigné')

                    slack_message = (
                        f"🏢 *Nouveau lead Tilto Pro*\n"
                        f"👤 {firstname} {lastname}\n"
                        f"📧 {email}\n"
                        f"💼 {activite_display}\n"
                        f"📍 Source: {source}\n"
                        f"{'🔄 (mise à jour)' if existing else '🆕 Nouveau'}"
                    )
                    slack_service.notify_new_lead({
                        'user_id': lead_id,
                        'email': email,
                        'firstname': firstname,
                        'lastname': lastname,
                        'profile': 'pro_lead',
                        'source': source,
                        'lead_interest': activite_display,
                        'has_quiz_answers': False,
                        'has_audio_responses': False,
                        'newsletter_subscription': False,
                    })
                    logger.info(f"[{g.request_id}] Slack notification sent for pro lead")
            except Exception as slack_err:
                logger.error(f"[{g.request_id}] Slack error (non-blocking): {slack_err}")


            return jsonify({
                'success': True,
                'message': 'Merci ! On vous recontacte sous 24h pour planifier votre démo.'
            }), 200

        except Exception as db_err:
            mysql.connection.rollback()
            logger.error(f"[{g.request_id}] DB error pro lead: {db_err}", exc_info=True)
            return jsonify({'success': False, 'message': 'Erreur technique. Veuillez réessayer.'}), 500
        finally:
            cursor.close()

    except Exception as e:
        request_id = getattr(g, 'request_id', str(uuid.uuid4()))
        logger.error(f"[{request_id}] Pro contact error: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'Une erreur est survenue.'}), 500


def save_conversation_answers(user_id, quiz_data, audio_urls, cursor, request_id, quiz_id='pack_clarte', city=None):
    """
    Sauvegarde les réponses du quiz conversationnel (mode coach IA dynamique).
    Stocke la conversation complète dans answer_user en mappant sur les question_ids existants.

    Si `city` est fourni, l'enregistre comme réponse à question_id=26 pour que
    QuizAnalysisService._extract_location_from_quiz puisse géolocaliser le web_search.
    """
    try:
        logger.info(f"[{request_id}] 🎯 Save conversation for user {user_id}, quiz {quiz_id}")

        # Get the full conversation transcript
        conversation_text = quiz_data.get('_conversation', {}).get('text', '')

        # Get valid question IDs from the quiz (to map turns onto)
        cursor.execute("""
            SELECT question_id, question_ranking
            FROM quiz_questions
            WHERE quiz_id = %s AND is_active = TRUE
            ORDER BY question_ranking
        """, (quiz_id,))
        valid_questions = [row[0] for row in cursor.fetchall()]

        if not valid_questions:
            logger.error(f"[{request_id}] No questions found for quiz {quiz_id}")
            return

        # Create quiz session
        cursor.execute("""
            INSERT INTO quiz_user (
                quiz_id, user_id, start_time, end_time, quiz_status,
                questions_answered_count, question_history,
                created_at, updated_at
            ) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'completed', %s, %s,
                     CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (quiz_id, user_id, len(valid_questions), json.dumps(list(range(len(valid_questions))))))

        quiz_session_id = cursor.lastrowid
        logger.info(f"[{request_id}] Session created: {quiz_session_id}")

        # Extract turn answers (turn_0, turn_1, etc.)
        turns = sorted(
            [(k, v) for k, v in quiz_data.items() if k.startswith('turn_')],
            key=lambda x: int(x[0].split('_')[1])
        )

        # Map each turn onto a question_id
        for i, (turn_key, turn_data) in enumerate(turns):
            # Map to existing question_id (cycle if more turns than questions)
            qid = valid_questions[min(i, len(valid_questions) - 1)]
            answer_text = turn_data.get('text', '')
            answer_value = json.dumps(turn_data.get('value', [answer_text]))

            # Check for audio
            turn_idx = turn_key.split('_')[1]
            audio_key = f'turn_{turn_idx}'
            if audio_key in audio_urls:
                answer_text += f"\n[AUDIO: {audio_urls[audio_key]}]"

            cursor.execute("""
                INSERT INTO answer_user
                (quiz_session_id, question_id, answer_value, answer_text, created_at, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    answer_value = CONCAT(COALESCE(answer_value, ''), '\n', VALUES(answer_value)),
                    answer_text = CONCAT(COALESCE(answer_text, ''), '\n---\n', VALUES(answer_text)),
                    updated_at = CURRENT_TIMESTAMP
            """, (quiz_session_id, qid, answer_value, answer_text))

        # Also store full conversation transcript on the first question
        if conversation_text and valid_questions:
            cursor.execute("""
                UPDATE answer_user
                SET answer_text = %s
                WHERE quiz_session_id = %s AND question_id = %s
            """, (conversation_text, quiz_session_id, valid_questions[0]))

        # Save city as question_id=26 so _extract_location_from_quiz can geolocate web_search
        if city:
            cursor.execute("""
                INSERT INTO answer_user
                (quiz_session_id, question_id, answer_value, answer_text, created_at, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                    answer_value = VALUES(answer_value),
                    answer_text = VALUES(answer_text),
                    updated_at = CURRENT_TIMESTAMP
            """, (quiz_session_id, 26, json.dumps([city]), city))
            logger.info(f"[{request_id}] 📍 City saved on question_id=26: {city}")

        logger.info(f"[{request_id}] ✅ Saved {len(turns)} turns for session {quiz_session_id}")

    except Exception as e:
        logger.error(f"[{request_id}] ❌ Error saving conversation: {e}", exc_info=True)