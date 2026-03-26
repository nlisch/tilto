# routes/audio_capsule.py
from flask import Blueprint, render_template, redirect, url_for, request, abort, jsonify, current_app, g, session, flash, Response
from flask_login import login_required, current_user
from models.audio_capsule import AudioCapsuleModel, UserCapsuleModel
from services.audio_capsule_service import AudioCapsuleService
import logging
import uuid
from werkzeug.utils import secure_filename
import os
from models.user_model import User 
from datetime import datetime, timedelta
from flask_babel import _, lazy_gettext as _l

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du blueprint
audio_capsule_bp = Blueprint('audio_capsule', __name__, url_prefix='/audio-capsule')

# Initialisation du service
audio_service = None

def get_audio_service():
    global audio_service
    if audio_service is None:
        audio_service = AudioCapsuleService()
    return audio_service

@audio_capsule_bp.route('/admin', methods=['GET'])
def admin_dashboard():
    """Page d'administration des capsules audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Initialiser les variables par défaut
        capsules = []
        audio_files = []
        users = []
        assignments = []
        stats = {
            'total': 0,
            'listened_count': 0
        }
        
        # Récupérer toutes les capsules
        capsules = AudioCapsuleModel.get_all_capsules(cursor) or []
        logger.debug("DEBUG admin_dashboard – capsules récupérées : %r", capsules)
        
        # Récupérer la liste des fichiers audio dans le bucket
        audio_service = get_audio_service()
        if audio_service:
            audio_files = audio_service.list_audio_files() or []
            logger.debug("DEBUG admin_dashboard – audio_files récupérés : %r", audio_files)
        
        # Récupérer la liste des utilisateurs
        cursor.execute("""
            SELECT user_id, username, email, access_token
            FROM users 
            ORDER BY username
        """)
        
        users_data = cursor.fetchall()
        if users_data:
            users = [
                {
                    'user_id': row[0],
                    'username': row[1],
                    'email': row[2],
                    'access_token': row[3]
                }
                for row in users_data
            ]
        
        # Paramètre pour filtrer par utilisateur (optionnel)
        user_filter = request.args.get('user_id', None)
        filter_condition = ''
        filter_params = []
        
        if user_filter and user_filter.isdigit():
            filter_condition = 'AND uac.user_id = %s'
            filter_params = [int(user_filter)]
        
        # Récupérer les assignations déjà effectuées
        try:
            cursor.execute(f"""
                SELECT 
                    uac.id, uac.user_id, uac.capsule_id, uac.access_token, 
                    u.username, ac.title, uac.listen_count,
                    uac.sequence_number, uac.signed_url_expiry, uac.signed_url_duration
                FROM user_capsules uac
                JOIN users u ON uac.user_id = u.user_id
                JOIN capsules ac ON uac.capsule_id = ac.capsule_id
                WHERE 1=1 {filter_condition}
                ORDER BY u.username, uac.sequence_number ASC
            """, filter_params)
            
            assignments_data = cursor.fetchall()
            if assignments_data:
                assignments = []
                for row in assignments_data:
                    assignments.append({
                        'id': row[0],
                        'user_id': row[1],
                        'capsule_id': row[2],
                        'access_token': row[3],
                        'username': row[4],
                        'capsule_title': row[5],
                        'listen_count': row[6] or 0,  # Gérer None
                        'sequence_number': row[7],
                        'signed_url_expiry': row[8],
                        'signed_url_duration': row[9],
                        'url': url_for('audio_capsule.view_capsule', token=row[3], _external=True)
                    })
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des assignations: {e}")
            # Continuer avec une liste vide
        
        # Calcul des statistiques pour la page d'admin
        total_capsules = len(capsules)
        listened_count = sum(a.get('listen_count', 0) for a in assignments)
        stats = {
            'total': total_capsules,
            'listened_count': listened_count
        }
        
        # Rendu du template
        return render_template(
            'admin/audio_capsules_handler.html',
            capsules=capsules,
            audio_files=audio_files,
            users=users,
            assignments=assignments,
            stats=stats,               # Stats pour le template
            selected_user=user_filter,
            now=datetime.now()         # pour comparaison d'expiration
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage du dashboard admin: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('auth.dashboard'))
    finally:
        cursor.close()


@audio_capsule_bp.route('/admin/upload', methods=['POST'])
@login_required
def upload_audio():
    """Upload d'un fichier audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    if 'audio_file' not in request.files:
        flash("Aucun fichier sélectionné", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
        
    file = request.files['audio_file']
    if file.filename == '':
        flash("Aucun fichier sélectionné", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    # Vérifier l'extension du fichier
    allowed_extensions = {'mp3', 'wav', 'ogg', 'm4a', 'webm'}
    if not '.' in file.filename or file.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
        flash("Format de fichier non autorisé. Formats acceptés: mp3, wav, ogg, m4a, webm", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    # Récupérer les données du formulaire
    title = request.form.get('title', '')
    personalized_reflection = request.form.get('personalized_reflection')
    duration = request.form.get('duration', '')
    
    # Lire le contenu du fichier pour vérifier sa taille réelle
    file_content = file.read()
    file_size = len(file_content)
    
    # Fichier vide ?
    if file_size == 0:
        flash("Le fichier est vide", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    # Vérifier la taille du fichier (10 MB max)
    max_size = 10 * 1024 * 1024  # 10 MB
    if file_size > max_size:
        flash("Le fichier est trop volumineux (max 10 MB)", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    try:
        # Sécuriser le nom du fichier
        secure_name = secure_filename(file.filename)
        
        # Téléverser le fichier
        audio_service = get_audio_service()
        # Réinitialiser la position du fichier avant de l'envoyer
        file.seek(0)
        filename = audio_service.upload_audio_file(file, secure_name)
        
        # Enregistrer les métadonnées en base
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        try:
            capsule_id = AudioCapsuleModel.create_capsule(
                cursor, title, personalized_reflection, filename, duration
            )
            if capsule_id:
                mysql.connection.commit()
                flash(f"Capsule audio '{title}' créée avec succès", "success")
            else:
                mysql.connection.rollback()
                flash("Erreur lors de la création de la capsule audio", "danger")
        finally:
            cursor.close()
            
        return redirect(url_for('audio_capsule.admin_dashboard'))
    except Exception as e:
        logger.error(f"Erreur lors du téléversement du fichier audio: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))

# Modification de la fonction assign_to_user pour gérer l'option de génération immédiate d'URL
@audio_capsule_bp.route('/admin/assign', methods=['POST'])
def assign_to_user():
    """Assigner une capsule audio à un utilisateur"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    user_id = request.form.get('user_id')
    capsule_id = request.form.get('capsule_id')
    sequence_number = request.form.get('sequence_number')  # Numéro de séquence
    signed_url_duration = request.form.get('signed_url_duration', '1440')  # Durée de l'URL signée, par défaut 24h (1440 minutes)
    generate_url_now = request.form.get('generate_url_now') == 'on'  # Vérifier si la checkbox est cochée
    
    if not user_id or not capsule_id:
        flash("Utilisateur et capsule requis", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    # Convertir en entier
    try:
        user_id = int(user_id)
        capsule_id = int(capsule_id)
        
        # Convertir la durée d'URL signée
        try:
            signed_url_duration = int(signed_url_duration)
            if signed_url_duration < 5:  # Minimum 5 minutes
                signed_url_duration = 5
        except ValueError:
            signed_url_duration = 1440  # Valeur par défaut (24h) si la conversion échoue
        
        # Si le numéro de séquence n'est pas fourni, déterminer automatiquement
        if not sequence_number or not sequence_number.strip():
            # Obtenir le prochain numéro de séquence pour cet utilisateur
            mysql = current_app.mysql
            cursor = mysql.connection.cursor()
            try:
                cursor.execute("""
                    SELECT MAX(sequence_number) 
                    FROM user_capsules 
                    WHERE user_id = %s
                """, (user_id,))
                max_seq = cursor.fetchone()[0]
                sequence_number = (max_seq or 0) + 1
            finally:
                cursor.close()
        else:
            sequence_number = int(sequence_number)
            
    except (ValueError, TypeError):
        flash("Paramètres invalides", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Vérifier que l'utilisateur et la capsule existent
        cursor.execute("SELECT username FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            flash("Utilisateur non trouvé", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Vérifier si une capsule avec ce numéro de séquence existe déjà
        cursor.execute("""
            SELECT uac.id, uac.capsule_id, ac.title 
            FROM user_capsules uac
            JOIN capsules ac ON uac.capsule_id = ac.capsule_id
            WHERE uac.user_id = %s AND uac.sequence_number = %s
        """, (user_id, sequence_number))
        existing_seq = cursor.fetchone()
        
        if existing_seq:
            flash(f"Une capsule existe déjà avec le numéro de séquence {sequence_number} pour cet utilisateur: {existing_seq[2]}", "warning")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Vérifier si la capsule est déjà assignée à cet utilisateur
        cursor.execute("""
            SELECT id, sequence_number FROM user_capsules 
            WHERE user_id = %s AND capsule_id = %s
        """, (user_id, capsule_id))
        existing = cursor.fetchone()
        
        if existing:
            flash(f"Cette capsule est déjà assignée à cet utilisateur avec le numéro de séquence {existing[1]}", "warning")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Récupérer les informations sur la capsule
        cursor.execute("""
            SELECT file_name 
            FROM capsules 
            WHERE capsule_id = %s
        """, (capsule_id,))
        capsule_info = cursor.fetchone()
        if not capsule_info:
            flash("Capsule non trouvée", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
            
        # Générer un token et assigner la capsule
        token = UserCapsuleModel.assign_capsule_to_user(
            cursor, user_id, capsule_id, None, sequence_number
        )
        
        if token:
            # Ajouter la durée d'URL signée à l'assignation
            cursor.execute("""
                UPDATE user_capsules
                SET signed_url_duration = %s
                WHERE access_token = %s
            """, (signed_url_duration, token))
            
            # Si générer l'URL audio immédiatement est demandé
            if generate_url_now:
                file_name = capsule_info[0]
                audio_service = get_audio_service()
                signed_url = audio_service.generate_signed_url(
                    file_name,
                    duration_minutes=signed_url_duration,
                    user_ip=None
                )
                
                # Calculer la date d'expiration
                signed_url_expiry = datetime.now() + timedelta(minutes=signed_url_duration)
                
                # Mettre à jour l'URL signée
                cursor.execute("""
                    UPDATE user_capsules
                    SET signed_url = %s, signed_url_expiry = %s
                    WHERE access_token = %s
                """, (signed_url, signed_url_expiry, token))
                
                # Message de confirmation avec info sur l'URL audio
                audio_message = f" avec URL audio valide pendant {signed_url_duration//60}h{signed_url_duration%60}m"
            else:
                audio_message = " (URL audio non générée)"
            
            mysql.connection.commit()
            # Générer l'URL complète
            capsule_url = url_for('audio_capsule.view_capsule', token=token, _external=True)
            flash(f"Capsule assignée avec succès en position {sequence_number}{audio_message}. URL: {capsule_url}", "success")
        else:
            mysql.connection.rollback()
            flash("Erreur lors de l'assignation de la capsule", "danger")
            
        # Rediriger vers le tableau de bord en gardant le filtre utilisateur
        return redirect(url_for('audio_capsule.admin_dashboard', user_id=user_id))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de l'assignation de la capsule: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/delete/<int:capsule_id>', methods=['POST'])
@login_required
def delete_capsule(capsule_id):
    """Supprimer une capsule audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer les infos de la capsule
        capsule = AudioCapsuleModel.get_capsule_by_id(cursor, capsule_id)
        
        if not capsule:
            flash("Capsule non trouvée", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Supprimer le fichier du bucket
        audio_service = get_audio_service()
        file_deleted = audio_service.delete_audio_file(capsule['file_name'])
        
        # Supprimer la capsule de la base
        db_deleted = AudioCapsuleModel.delete_capsule(cursor, capsule_id)
        
        if db_deleted:
            mysql.connection.commit()
            flash(f"Capsule '{capsule['title']}' supprimée avec succès", "success")
        else:
            mysql.connection.rollback()
            flash("Erreur lors de la suppression de la capsule", "danger")
            
        return redirect(url_for('audio_capsule.admin_dashboard'))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la suppression de la capsule: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/revoke/<int:assignment_id>', methods=['POST'])
@login_required
def revoke_access(assignment_id):
    """Révoquer l'accès à une capsule"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Vérifier que l'assignation existe
        cursor.execute("""
            SELECT uac.id, u.username, ac.title
            FROM user_capsules uac
            JOIN users u ON uac.user_id = u.user_id
            JOIN capsules ac ON uac.capsule_id = ac.capsule_id
            WHERE uac.id = %s
        """, (assignment_id,))
        assignment = cursor.fetchone()
        
        if not assignment:
            flash("Assignation non trouvée", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Supprimer l'assignation
        cursor.execute("DELETE FROM user_capsules WHERE id = %s", (assignment_id,))
        mysql.connection.commit()
        
        flash(f"Accès à la capsule '{assignment[2]}' révoqué pour l'utilisateur '{assignment[1]}'", "success")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la révocation de l'accès: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/<token>', methods=['GET'])
def view_capsule(token):
    """Vue publique d'une capsule audio (accessible par token)"""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer les infos de la capsule
        capsule_data = UserCapsuleModel.get_capsule_by_token(cursor, token)
        
        if not capsule_data:
            # Créer un objet capsule minimal pour éviter les erreurs de template
            error_capsule = {
                'total_capsules': 0,
                'sequence_number': 0,
                'user_capsules': [],
                'duration': '00:00',
                'access_token': '',
                'all_capsules': []
            }
            
            return render_template(
                'pages/capsule_audio.html',
                capsule=error_capsule,
                audio_url=None,
                error_message=_("Capsule non trouvée"),
                listen_session_id="",
                now=datetime.now(),
                total_capsules=0
            )
        
        # Récupérer la clé d'accès au programme complet de l'utilisateur
        cursor.execute("""
            SELECT access_token FROM users WHERE user_id = %s
        """, (capsule_data['user_id'],))
        
        user_token_result = cursor.fetchone()
        programme_token = user_token_result[0] if user_token_result else None
        
        # Paramètre pour forcer l'affichage d'une capsule spécifique
        force_capsule = request.args.get('force', 'false') == 'true'
        
        # Si l'utilisateur a un token de programme et qu'on ne force pas l'affichage de cette capsule spécifique
        if programme_token and not force_capsule:
            # Modifier la redirection pour inclure la référence à la capsule demandée
            return redirect(url_for('audio_capsule.view_programme', 
                                    access_token=programme_token, 
                                    capsule_sequence=capsule_data['sequence_number']))
        
        # Si on arrive ici, on doit afficher la capsule individuelle
        
        # Vérifier si une URL signée valide existe
        audio_url = None
        cursor.execute("""
            SELECT signed_url, signed_url_expiry
            FROM user_capsules
            WHERE access_token = %s
        """, (token,))
        
        url_data = cursor.fetchone()
        if url_data and url_data[0] and url_data[1] and url_data[1] > datetime.now():
            # Une URL signée valide existe
            audio_url = url_data[0]
        
        # Créer une session d'écoute
        listen_session_id = str(uuid.uuid4())
        session['listen_session_id'] = listen_session_id
        
        # Préparer les données pour le template
        capsule_display_data = {
            'user_id': capsule_data['user_id'],
            'username': capsule_data.get('username', ''),
            'total_capsules': 1,  # Affichage d'une seule capsule
            'sequence_number': capsule_data['sequence_number'],
            'user_capsules': [(capsule_data['sequence_number'], capsule_data['is_listened'])],
            'duration': capsule_data['duration'],
            'access_token': capsule_data['access_token'],
            'title': capsule_data['title'],
            'personalized_reflection': capsule_data['personalized_reflection'],
            'all_capsules': [capsule_data],
            'active_capsule': capsule_data
        }
        
        # Message d'erreur si aucune URL signée valide n'est disponible
        error_message = None if audio_url else _("L'accès au fichier audio n'est pas disponible actuellement. Veuillez contacter un administrateur.")
        
        return render_template(
            'pages/capsule_audio.html',
            capsule=capsule_display_data,
            audio_url=audio_url,
            error_message=error_message,
            listen_session_id=listen_session_id,
            now=datetime.now(),
            total_capsules=1,
            program_user={'username': capsule_data.get('username', ''), 'user_id': capsule_data['user_id']},
            current_seq=capsule_data['sequence_number']
        )
        
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage de la capsule: {e}")
        # Objet d'erreur
        error_capsule = {
            'total_capsules': 0,
            'sequence_number': 0,
            'user_capsules': [],
            'duration': '00:00',
            'access_token': '',
            'all_capsules': []
        }
        
        return render_template(
            'pages/capsule_audio.html',
            capsule=error_capsule,
            audio_url=None,
            error_message=_("Une erreur s'est produite lors du chargement de la capsule audio"),
            listen_session_id="",
            now=datetime.now(),
            total_capsules=0
        )
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/create-program', methods=['POST'])
@login_required
def create_program():
    """Crée un programme complet de capsules pour un utilisateur"""
    if current_user.user_status != 'admin':
        abort(403)
        
    user_id = request.form.get('user_id')
    capsule_ids = request.form.getlist('capsule_ids[]')  # Liste ordonnée des capsules
    expiry_days = request.form.get('expiry_days')
    
    if not user_id or not capsule_ids:
        flash("Utilisateur et capsules requis", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    
    try:
        # Vérifier que l'utilisateur existe
        cursor.execute("SELECT username FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            flash("Utilisateur non trouvé", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Assigner chaque capsule avec un numéro de séquence
        assigned_count = 0
        for seq, capsule_id in enumerate(capsule_ids, start=1):
            token = UserCapsuleModel.assign_capsule_to_user(
                cursor, user_id, int(capsule_id), None, seq, 
                expiry_days=int(expiry_days) if expiry_days else None
            )
            
            if token:
                assigned_count += 1
            else:
                mysql.connection.rollback()
                flash(f"Erreur lors de l'assignation de la capsule {capsule_id}", "danger")
                return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Générer ou mettre à jour le token utilisateur pour accéder au programme
        access_token = User.generate_user_access_token(cursor, user_id)
        
        mysql.connection.commit()
        
        program_url = url_for('audio_capsule.view_programme', access_token=access_token, _external=True)
        flash(f"Programme de {assigned_count} capsules créé avec succès. URL: {program_url}", "success")
        
        return redirect(url_for('audio_capsule.admin_dashboard'))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la création du programme: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/api/track-progress', methods=['POST'])
def track_progress():
    """API pour suivre la progression de l'écoute"""
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'Données invalides'}), 400
    
    token = data.get('token')
    current_time = data.get('currentTime', 0)
    duration = data.get('duration', 0)
    listen_session_id = data.get('listenSessionId')
    
    # Vérifier la validité des données
    if not token or not listen_session_id:
        return jsonify({'status': 'error', 'message': 'Paramètres manquants'}), 400
    
    # Vérifier que la session correspond
    if session.get('listen_session_id') != listen_session_id:
        return jsonify({'status': 'error', 'message': 'Session invalide'}), 403
    
    # Calculer le pourcentage d'écoute
    completion_percentage = 0
    if duration > 0:
        completion_percentage = min(100, int((current_time / duration) * 100))
    
    # Enregistrer la progression
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer les infos de la capsule
        capsule_data = UserCapsuleModel.get_capsule_by_token(cursor, token)
        
        if not capsule_data:
            return jsonify({'status': 'error', 'message': 'Capsule non trouvée'}), 404
        
        # Mise à jour de l'événement d'écoute
        event_id = session.get('listen_event_id')
        if event_id:
            cursor.execute("""
                UPDATE capsules_history
                SET duration_seconds = %s,
                    completion_percentage = %s
                WHERE id = %s
            """, (int(current_time), completion_percentage, event_id))
            mysql.connection.commit()
        
        return jsonify({'status': 'success', 'completion': completion_percentage})
    except Exception as e:
        logger.error(f"Erreur lors du suivi de la progression: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()

@audio_capsule_bp.route('/api/feedback', methods=['POST'])
def submit_feedback():
    """API pour soumettre un feedback textuel"""
    data = request.json
    if not data:
        return jsonify({'status': 'error', 'message': 'Données invalides'}), 400

    token = data.get('token')
    rating = data.get('rating')
    feedback_text = data.get('feedback')
    listen_session_id = data.get('listenSessionId')

    # Vérifier les paramètres obligatoires
    if not token or rating is None:
        return jsonify({'status': 'error', 'message': 'Paramètres manquants'}), 400

    # Vérifier la session (on logue seulement)
    if session.get('listen_session_id') != listen_session_id:
        logger.warning(
            f"Session de feedback invalide: attendu {session.get('listen_session_id')}, reçu {listen_session_id}"
        )

    # Valider la note
    try:
        rating = int(rating)
        if rating < 1 or rating > 5:
            return jsonify({'status': 'error', 'message': 'Note invalide (1-5)'}), 400
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Note invalide'}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # 1. Récupérer la capsule associée au token
        capsule_data = UserCapsuleModel.get_capsule_by_token(cursor, token)
        if not capsule_data:
            return jsonify({'status': 'error', 'message': 'Capsule non trouvée'}), 404

        user_id = capsule_data['user_id']
        capsule_id = capsule_data['capsule_id']

        # 2. Créer un événement d'écoute à 100% (pour satisfaire la clé étrangère)
        listen_id = UserCapsuleModel.record_listen_event(
            cursor,
            user_id=user_id,
            capsule_id=capsule_id,
            duration_seconds=0,
            completion_percentage=100,
            user_agent=request.user_agent.string if hasattr(request, 'user_agent') else None,
            ip_address=request.remote_addr
        )
        if not listen_id:
            mysql.connection.rollback()
            return jsonify({'status': 'error', 'message': "Impossible d'enregistrer l'écoute"}), 500

        # 3. Sauvegarder le feedback textuel
        feedback_id = UserCapsuleModel.save_feedback(
            cursor,
            event_id=listen_id,
            rating=rating,
            feedback_text=feedback_text
        )
        if not feedback_id:
            mysql.connection.rollback()
            return jsonify({'status': 'error', 'message': "Impossible de sauvegarder le feedback"}), 500

        # 4. Commit et retour success
        mysql.connection.commit()
        return jsonify({
            'status': 'success',
            'message': 'Feedback enregistré',
            'feedback_id': feedback_id
        })
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de l'enregistrement du feedback: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
    finally:
        cursor.close()


@audio_capsule_bp.route('/api/audio-preview/<filename>', methods=['GET'])
@login_required
def audio_preview(filename):
    """Génère une URL signée pour prévisualiser un fichier audio (admin uniquement)"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    try:
        # Générer une URL signée pour le fichier audio
        audio_service = get_audio_service()
        signed_url = audio_service.generate_signed_url(
            filename, 
            duration_minutes=5,  # Courte durée pour la prévisualisation
            user_ip=request.remote_addr
        )
        
        if not signed_url:
            return jsonify({'error': "Le fichier audio n'existe pas ou n'est pas accessible"}), 404
        
        return jsonify({'url': signed_url})
    except Exception as e:
        logger.error(f"Erreur lors de la génération de l'URL de prévisualisation pour {filename}: {e}")
        return jsonify({'error': f"Erreur: {str(e)}"}), 500

# Code à modifier dans routes/audio_capsule.py

# Modification de l'endpoint dans routes/audio_capsule.py

@audio_capsule_bp.route('/api/admin-audio-stream/<filename>', methods=['GET'])
@login_required
def admin_audio_stream(filename):
    """Diffuse directement un fichier audio aux administrateurs avec configuration améliorée"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        logger.error(f"Accès refusé - User: {current_user.username}, Admin: {current_user.user_status}, 2FA: {session.get('two_factor_authenticated')}")
        abort(403)
        
    try:
        logger.info(f"Tentative de diffusion du fichier {filename}")
        
        # Initialisation du service
        audio_service = get_audio_service()
        bucket = audio_service.bucket
        
        # Vérifier si le blob existe
        blob = bucket.blob(filename)
        exists = blob.exists()
        logger.info(f"Le fichier {filename} existe dans le bucket: {exists}")
        
        if not exists:
            logger.error(f"Le fichier {filename} n'existe pas dans le bucket {bucket.name}")
            return jsonify({'error': 'Fichier non trouvé'}), 404
            
        # Télécharger le contenu en mémoire
        logger.info(f"Téléchargement du contenu du fichier {filename}")
        audio_content = blob.download_as_bytes()
        logger.info(f"Fichier téléchargé avec succès, taille: {len(audio_content)} octets")
        
        # Déterminer le type MIME
        content_type = 'audio/mpeg'  # Par défaut
        if filename.endswith('.wav'):
            content_type = 'audio/wav'
        elif filename.endswith('.ogg'):
            content_type = 'audio/ogg'
        elif filename.endswith('.m4a'):
            content_type = 'audio/mp4'
        elif filename.endswith('.webm'):
            content_type = 'audio/webm'
            
        logger.info(f"Envoi du fichier {filename} avec type MIME: {content_type}")
        
        # Configuration des en-têtes pour une meilleure compatibilité
        headers = {
            'Content-Disposition': f'inline; filename="{os.path.basename(filename)}"',
            'Cache-Control': 'no-cache',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(len(audio_content))
        }
        
        # Gestion des requêtes partielles (range)
        range_header = request.headers.get('Range')
        if range_header:
            try:
                # Par exemple Range: bytes=0-1023
                bytes_range = range_header.replace('bytes=', '').split('-')
                start = int(bytes_range[0]) if bytes_range[0] else 0
                end = int(bytes_range[1]) if len(bytes_range) > 1 and bytes_range[1] else len(audio_content) - 1
                
                if end >= len(audio_content):
                    end = len(audio_content) - 1
                
                length = end - start + 1
                
                # Adapter le contenu
                audio_content = audio_content[start:end+1]
                
                # Configurer la réponse pour une requête partielle
                headers['Content-Range'] = f'bytes {start}-{end}/{len(audio_content)}'
                headers['Content-Length'] = str(length)
                headers['Accept-Ranges'] = 'bytes'
                
                response = Response(
                    audio_content,
                    status=206,  # Partial Content
                    mimetype=content_type,
                    headers=headers
                )
                
                return response
            except Exception as e:
                logger.error(f"Erreur lors du traitement de la requête Range: {e}")
                # On continue avec une réponse normale si le Range est invalide
        
        # Réponse normale (sans Range)
        response = Response(
            audio_content,
            mimetype=content_type,
            headers=headers
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Erreur lors de la diffusion du fichier audio {filename}: {e}", exc_info=True)
        return jsonify({'error': f"Erreur interne: {str(e)}"}), 500
    
@audio_capsule_bp.route('/programme/<access_token>', methods=['GET'])
def view_programme(access_token):
    """Page unique affichant toutes les capsules audio d'un programme donné par token"""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # 1. Vérifier si le token existe et récupérer l'utilisateur associé
        cursor.execute("""
            SELECT user_id, username, email 
            FROM users 
            WHERE access_token = %s
        """, (access_token,))
        user_row = cursor.fetchone()
        
        if not user_row:
            # Aucun programme trouvé pour ce token
            error_capsule = {
                'total_capsules': 0,
                'sequence_number': 0,
                'user_capsules': [],
                'duration': '00:00',
                'access_token': '',
                'all_capsules': []
            }
            return render_template(
                'pages/capsule_audio.html',
                capsule=error_capsule,
                audio_url=None,
                error_message=_("Programme non trouvé"),
                listen_session_id="",
                now=datetime.now(),
                total_capsules=0,
                program_user=None
            )
        
        user_id, username, email = user_row
        # Construire l'objet program_user pour le template
        program_user = {
            'user_id': user_id,
            'username': username,
            'email': email
        }
        
        # 2. Récupérer toutes les capsules assignées à cet utilisateur
        cursor.execute("""
            SELECT uac.id, uac.capsule_id, uac.access_token, uac.sequence_number,
                   uac.is_listened, uac.listen_count, ac.title, ac.personalized_reflection, 
                   ac.file_name, ac.duration, ac.is_active,
                   uac.signed_url, uac.signed_url_expiry
            FROM user_capsules uac
            JOIN capsules ac ON uac.capsule_id = ac.capsule_id
            WHERE uac.user_id = %s AND ac.is_active = TRUE
            ORDER BY uac.sequence_number ASC
        """, (user_id,))
        
        capsules = []
        for row in cursor.fetchall():
            capsules.append({
                'id': row[0],
                'capsule_id': row[1],
                'access_token': row[2],
                'sequence_number': row[3],
                'is_listened': bool(row[4]),
                'listen_count': row[5],
                'title': row[6],
                'personalized_reflection': row[7],
                'file_name': row[8],
                'duration': row[9],
                'is_active': bool(row[10]),
                'signed_url': row[11],
                'signed_url_expiry': row[12]
            })
        
        # 3. Déterminer la capsule "active"
        requested_sequence = request.args.get('capsule_sequence')
        active_capsule = None
        
        if requested_sequence and requested_sequence.isdigit():
            rs = int(requested_sequence)
            for cap in capsules:
                if cap['sequence_number'] == rs:
                    active_capsule = cap
                    break
        
        if active_capsule is None:
            # première non écoutée, ou la dernière si tout écouté
            for cap in capsules:
                if not cap['is_listened']:
                    active_capsule = cap
                    break
            if active_capsule is None and capsules:
                active_capsule = capsules[-1]
        
        current_seq = active_capsule['sequence_number'] if active_capsule else 0

        # 4. Vérifier si une URL signée valide existe pour la capsule active
        audio_url = None
        if active_capsule:
            # Vérifier si l'URL signée est valide
            if (active_capsule.get('signed_url') and active_capsule.get('signed_url_expiry') and 
                active_capsule['signed_url_expiry'] > datetime.now()):
                audio_url = active_capsule['signed_url']
                
            error_message = None if audio_url else _("L'accès au fichier audio n'est pas disponible actuellement. Veuillez contacter un administrateur.")
        else:
            error_message = _("Aucune capsule disponible dans ce programme")
        
        # 5. Session d'écoute
        listen_session_id = str(uuid.uuid4())
        session['listen_session_id'] = listen_session_id
        
        # 6. Préparer les données pour le template
        programme_data = {
            'user_id': user_id,
            'username': username,
            'total_capsules': len(capsules),
            'sequence_number': active_capsule['sequence_number'] if active_capsule else 0,
            'user_capsules': [(c['sequence_number'], c['is_listened']) for c in capsules],
            'duration': active_capsule['duration'] if active_capsule else '00:00',
            'access_token': active_capsule['access_token'] if active_capsule else '',
            'title': active_capsule['title'] if active_capsule else 'Programme Audio',
            'personalized_reflection': active_capsule['personalized_reflection'] if active_capsule else '',
            'all_capsules': capsules,
            'active_capsule': active_capsule
        }
        
        current_app.logger.debug("Capsules pour l'utilisateur %s → %s", user_id, capsules)
        
        return render_template(
            'pages/capsule_audio.html',
            capsule=programme_data,
            audio_url=audio_url,
            error_message=error_message,
            listen_session_id=listen_session_id,
            now=datetime.now(),
            total_capsules=len(capsules),
            program_user=program_user,
            current_seq=current_seq
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage du programme audio: {e}")
        error_capsule = {
            'total_capsules': 0,
            'sequence_number': 0,
            'user_capsules': [],
            'duration': '00:00',
            'access_token': '',
            'all_capsules': []
        }
        return render_template(
            'pages/capsule_audio.html',
            capsule=error_capsule,
            audio_url=None,
            error_message=_("Une erreur s'est produite lors du chargement du programme audio"),
            listen_session_id="",
            now=datetime.now(),
            total_capsules=0,
            program_user=None
        )
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/generate-user-token/<int:user_id>', methods=['POST'])
@login_required
def generate_user_token(user_id):
    """Génère un token d'accès unique pour un utilisateur"""
    if current_user.user_status != 'admin':
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    
    try:
        # Vérifier que l'utilisateur existe
        cursor.execute("SELECT username FROM users WHERE user_id = %s", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            flash("Utilisateur non trouvé", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
        
        # Générer et sauvegarder le token
        access_token = User.generate_user_access_token(cursor, user_id)
        mysql.connection.commit()
        
        # Générer l'URL complète
        programme_url = url_for('audio_capsule.view_programme', access_token=access_token, _external=True)
        
        flash(f"Token généré pour {user[0]}. URL: {programme_url}", "success")
        return redirect(url_for('audio_capsule.admin_dashboard'))
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la génération du token: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()


# Modification de la fonction renew_signed_url pour utiliser 24h par défaut
@audio_capsule_bp.route('/admin/renew-signed-url/<int:assignment_id>', methods=['POST'])
@login_required
def renew_signed_url(assignment_id):
    """Génère ou renouvelle l'URL signée d'une capsule"""
    if current_user.user_status != 'admin':
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    
    try:
        # Récupérer les infos de l'assignation
        cursor.execute("""
            SELECT uac.user_id, uac.capsule_id, uac.access_token, 
                   uac.signed_url_duration, ac.file_name
            FROM user_capsules uac
            JOIN capsules ac ON uac.capsule_id = ac.capsule_id
            WHERE uac.id = %s
        """, (assignment_id,))
        
        assignment = cursor.fetchone()
        if not assignment:
            flash("Assignation non trouvée", "danger")
            return redirect(url_for('audio_capsule.admin_dashboard'))
            
        user_id, capsule_id, access_token, duration, file_name = assignment
        
        # Utiliser la durée existante ou une durée par défaut de 24h (1440 minutes)
        duration = duration or 1440  # 24 heures par défaut
        
        # Générer une nouvelle URL signée
        audio_service = get_audio_service()
        signed_url = audio_service.generate_signed_url(
            file_name,
            duration_minutes=duration,
            user_ip=None
        )
        
        # Calculer la nouvelle date d'expiration
        signed_url_expiry = datetime.now() + timedelta(minutes=duration)
        
        # Mettre à jour l'assignation
        cursor.execute("""
            UPDATE user_capsules
            SET signed_url = %s, signed_url_expiry = %s
            WHERE id = %s
        """, (signed_url, signed_url_expiry, assignment_id))
        
        mysql.connection.commit()
        flash("URL d'accès audio générée avec succès (valide pendant 24h)", "success")
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la génération de l'URL signée: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        
    finally:
        cursor.close()
        
    return redirect(url_for('audio_capsule.admin_dashboard'))

@audio_capsule_bp.route('/api/record-listen', methods=['POST'])
def record_listen():
    """Enregistre l'écoute d'une capsule audio dans l'historique"""
    try:
        data = request.json
        token = data.get('token')
        duration_seconds = data.get('duration_seconds', 0)
        completion_percentage = data.get('completion_percentage', 0)
        listen_session_id = data.get('listenSessionId')
        
        # Vérifier que les données requises sont présentes
        if not token:
            return jsonify({'success': False, 'error': 'Token manquant'}), 400
            
        # Vérifier que la session correspond (facultatif mais recommandé)
        if session.get('listen_session_id') != listen_session_id:
            logger.warning(f"Session d'écoute invalide: attendu {session.get('listen_session_id')}, reçu {listen_session_id}")
            # Ne pas bloquer complètement, car cela pourrait être dû à un rechargement de page
            
        # Obtenir les infos de la capsule à partir du token
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        try:
            # Récupérer l'utilisateur et la capsule associés au token
            capsule = UserCapsuleModel.get_capsule_by_token(cursor, token)
            
            if not capsule:
                return jsonify({'success': False, 'error': 'Capsule non trouvée'}), 404
            
            # Utiliser l'ID de l'utilisateur associé à la capsule
            user_id = capsule['user_id']
            
            # Enregistrer l'écoute dans l'historique
            listen_id = UserCapsuleModel.record_listen_event(
                cursor,
                user_id=user_id,
                capsule_id=capsule['capsule_id'],
                duration_seconds=duration_seconds,
                completion_percentage=completion_percentage,
                user_agent=request.user_agent.string,
                ip_address=request.remote_addr
            )
            
            # Mettre à jour le statut d'écoute de la capsule
            UserCapsuleModel.update_listen_status(cursor, token)
            
            mysql.connection.commit()
            
            # Stocker l'ID de l'événement d'écoute dans la session
            session['listen_event_id'] = listen_id
            
            return jsonify({
                'success': True, 
                'listen_id': listen_id,
                'message': 'Écoute enregistrée avec succès'
            })
            
        except Exception as e:
            mysql.connection.rollback()
            logger.error(f"Erreur lors de l'enregistrement de l'écoute: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
            
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"Erreur dans la route record_listen: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@audio_capsule_bp.route('/submit-feedback-with-audio', methods=['POST'])
def submit_feedback_with_audio():
    """
    Endpoint pour recevoir le feedback vocal et le stocker sur Cloud Storage.
    Permet aux utilisateurs de soumettre plusieurs feedbacks pour une même capsule.
    """
    try:
        token = request.form.get('token')
        rating = request.form.get('rating')
        feedback_text = request.form.get('feedback_text', '')
        
        # Récupérer le temps d'écoute réel depuis le frontend
        current_time = request.form.get('current_time', '0')
        total_duration = request.form.get('total_duration', '0')
        
        # Convertir en entiers (ou utiliser 0 si conversion impossible)
        try:
            current_time = int(float(current_time))
            total_duration = int(float(total_duration))
        except (ValueError, TypeError):
            current_time = 0
            total_duration = 0
        
        # Calculer le pourcentage de complétion réel
        completion_percentage = 0
        if total_duration > 0:
            completion_percentage = min(100, int((current_time / total_duration) * 100))
        
        # Validation de base
        if not token or not rating:
            return jsonify({"error": "Paramètres manquants"}), 400
        
        mysql = current_app.mysql
        cursor = mysql.connection.cursor()
        
        try:
            # Récupérer les informations de la capsule et de l'utilisateur associé
            capsule = UserCapsuleModel.get_capsule_by_token(cursor, token)
            
            if not capsule:
                return jsonify({"error": "Capsule non trouvée"}), 404
            
            # Utiliser l'ID utilisateur associé à la capsule plutôt que current_user
            user_id = capsule['user_id']
            capsule_id = capsule['capsule_id']
            
            # Récupérer le dernier événement d'écoute pour cet utilisateur et cette capsule
            cursor.execute("""
                SELECT id FROM capsules_history 
                WHERE user_id = %s AND capsule_id = %s
                ORDER BY listen_date DESC LIMIT 1
            """, (user_id, capsule_id))
            event = cursor.fetchone()
            
            # S'il n'y a pas d'événement, créer un événement spécial pour le feedback audio
            # sans passer par record_listen_event qui a une condition de 90%
            if not event:
                # Créer directement une entrée dans la table capsules_history
                cursor.execute("""
                    INSERT INTO capsules_history
                    (user_id, capsule_id, duration_seconds, completion_percentage, user_agent, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    user_id, capsule_id, current_time, 
                    completion_percentage, 
                    request.user_agent.string if hasattr(request, 'user_agent') else None,
                    request.remote_addr
                ))
                event_id = cursor.lastrowid
                logger.info(f"Événement d'écoute créé pour feedback audio: ID={event_id}, progression={completion_percentage}%")
            else:
                event_id = event[0]
                
                # Mettre à jour l'événement existant avec les nouvelles informations d'écoute
                cursor.execute("""
                    UPDATE capsules_history
                    SET duration_seconds = %s, completion_percentage = %s
                    WHERE id = %s
                """, (current_time, completion_percentage, event_id))
            
            # Traiter le fichier audio s'il existe
            cloud_storage_filename = None
            if 'audio_feedback' in request.files:
                audio_file = request.files['audio_feedback']
                
                if audio_file and audio_file.filename:
                    # Initialiser le service audio
                    audio_service = get_audio_service()
                    
                    # Téléverser le fichier audio vers Cloud Storage
                    cloud_storage_filename = audio_service.upload_feedback_audio(audio_file, event_id)
            
            # Déterminer le type de feedback
            feedback_type = 'text'
            if cloud_storage_filename and feedback_text:
                feedback_type = 'both'
            elif cloud_storage_filename:
                feedback_type = 'audio'
            
            # Insérer le feedback dans la table capsules_feedback
            cursor.execute("""
                INSERT INTO capsules_feedback
                (listen_history_id, user_id, capsule_id, rating, feedback_text, 
                 audio_feedback_file, feedback_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                event_id, user_id, capsule_id, int(rating), 
                feedback_text, cloud_storage_filename, feedback_type
            ))
            
            feedback_id = cursor.lastrowid
            logger.info(f"Feedback #{feedback_id} enregistré pour l'événement {event_id}")
            
            # Commit les changements
            mysql.connection.commit()
            
            # Si le pourcentage d'écoute est élevé, marquer la capsule comme écoutée
            if completion_percentage >= 90:
                try:
                    UserCapsuleModel.update_listen_status(cursor, token)
                    mysql.connection.commit()
                except Exception as e:
                    logger.warning(f"Impossible de mettre à jour le statut d'écoute: {e}")
            
            return jsonify({
                "success": True,
                "message": "Feedback enregistré avec succès",
                "feedback_id": feedback_id,
                "event_id": event_id,
                "completion": completion_percentage,
                "duration": current_time,
                "audio_file": cloud_storage_filename
            })
            
        except Exception as e:
            mysql.connection.rollback()
            raise e
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du feedback: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@audio_capsule_bp.route('/admin/audio-feedbacks', methods=['GET'])
@login_required
def admin_audio_feedbacks():
    """Page d'administration des feedbacks audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer les feedbacks avec fichiers audio depuis la table capsules_feedback
        cursor.execute("""
            SELECT 
                cf.id, cf.user_id, cf.capsule_id, cf.created_at, 
                cf.rating, cf.feedback_text, cf.audio_feedback_file,
                u.username, c.title
            FROM capsules_feedback cf
            JOIN users u ON cf.user_id = u.user_id
            JOIN capsules c ON cf.capsule_id = c.capsule_id
            WHERE cf.feedback_type IN ('audio', 'both')
            ORDER BY cf.created_at DESC
        """)
        
        feedbacks = []
        for row in cursor.fetchall():
            # S'assurer que created_at/listen_date est correctement formaté pour éviter des erreurs
            created_at = row[3]
            # Si created_at n'est pas un objet datetime, le convertir
            if not isinstance(created_at, datetime):
                try:
                    created_at = datetime.fromisoformat(str(created_at))
                except (ValueError, TypeError):
                    created_at = datetime.now()  # Fallback au cas où
            
            feedbacks.append({
                'id': row[0],
                'user_id': row[1],
                'capsule_id': row[2],
                'listen_date': created_at,  # Utiliser created_at comme listen_date
                'rating': row[4] or 0,  # Éviter les valeurs None
                'text': row[5] or '',    # Éviter les valeurs None
                'audio_file': row[6],
                'username': row[7],
                'capsule_title': row[8]
            })
        
        # Ajouter les statistiques des feedbacks audio
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                ROUND(AVG(rating), 1) as avg_rating
            FROM capsules_feedback
            WHERE feedback_type IN ('audio', 'both')
        """)
        
        stats_row = cursor.fetchone()
        
        # Créer l'objet stats avec des valeurs par défaut
        stats = {
            'total': stats_row[0] if stats_row and stats_row[0] is not None else 0,
            'text_count': 0,  # Pas pertinent ici mais nécessaire pour le template
            'audio_count': stats_row[0] if stats_row and stats_row[0] is not None else 0,
            'avg_rating': stats_row[1] if stats_row and stats_row[1] is not None else 0
        }
        
        return render_template(
            'admin/feedbacks_handler.html',
            feedbacks=feedbacks,
            stats=stats  # Passer les stats au template
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage des feedbacks audio: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/feedbacks', methods=['GET'])
@login_required
def admin_feedbacks():
    """Page d'administration pour tous les feedbacks (texte et audio)"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer tous les feedbacks depuis la table capsules_feedback
        cursor.execute("""
            SELECT 
                cf.id, cf.user_id, cf.capsule_id, cf.listen_history_id, 
                cf.rating, cf.feedback_text, cf.audio_feedback_file, 
                cf.feedback_type, cf.created_at,
                u.username, c.title as capsule_title
            FROM capsules_feedback cf
            JOIN users u ON cf.user_id = u.user_id
            JOIN capsules c ON cf.capsule_id = c.capsule_id
            ORDER BY cf.created_at DESC
        """)
        
        feedbacks = []
        for row in cursor.fetchall():
            # S'assurer que created_at est correctement formaté pour éviter des erreurs
            created_at = row[8]
            # Si created_at n'est pas un objet datetime, le convertir
            if not isinstance(created_at, datetime):
                try:
                    created_at = datetime.fromisoformat(str(created_at))
                except (ValueError, TypeError):
                    created_at = datetime.now()  # Fallback au cas où
            
            # Valider et nettoyer le feedback_type
            feedback_type = row[7]
            if feedback_type not in ('text', 'audio', 'both'):
                if row[6]:  # Si audio_feedback_file existe
                    if row[5]:  # Si feedback_text existe aussi
                        feedback_type = 'both'
                    else:
                        feedback_type = 'audio'
                else:
                    feedback_type = 'text'
            
            feedbacks.append({
                'id': row[0],
                'user_id': row[1],
                'capsule_id': row[2],
                'listen_history_id': row[3],
                'rating': row[4] or 0,  # Éviter les valeurs None
                'feedback_text': row[5] or '',  # Éviter les valeurs None
                'audio_feedback_file': row[6],
                'feedback_type': feedback_type,
                'created_at': created_at,
                'username': row[9] or 'Utilisateur inconnu',
                'capsule_title': row[10] or 'Capsule inconnue'
            })
        
        # Récupérer les statistiques des feedbacks avec COALESCE pour gérer les valeurs NULL
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(CASE WHEN feedback_type = 'text' OR 
                          (feedback_type IS NULL AND audio_feedback_file IS NULL AND feedback_text IS NOT NULL) THEN 1 END) as text_count,
                COUNT(CASE WHEN feedback_type IN ('audio', 'both') OR 
                          (feedback_type IS NULL AND audio_feedback_file IS NOT NULL) THEN 1 END) as audio_count,
                COALESCE(ROUND(AVG(rating), 1), 0) as avg_rating
            FROM capsules_feedback
        """)
        
        stats_row = cursor.fetchone()
        stats = {
            'total': stats_row[0] if stats_row and stats_row[0] is not None else 0,
            'text_count': stats_row[1] if stats_row and stats_row[1] is not None else 0,
            'audio_count': stats_row[2] if stats_row and stats_row[2] is not None else 0,
            'avg_rating': stats_row[3] if stats_row and stats_row[3] is not None else 0
        }
        
        return render_template(
            'admin/feedbacks_handler.html',
            feedbacks=feedbacks,
            stats=stats
        )
    except Exception as e:
        logger.error(f"Erreur lors de l'affichage du dashboard des feedbacks: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_dashboard'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/audio-feedback/<int:feedback_id>', methods=['GET'])
@login_required
def get_audio_feedback(feedback_id):
    """Génère une URL signée pour un fichier de feedback audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer le nom du fichier audio depuis la table capsules_feedback
        cursor.execute("""
            SELECT audio_feedback_file
            FROM capsules_feedback
            WHERE id = %s
        """, (feedback_id,))
        
        result = cursor.fetchone()
        if not result or not result[0]:
            return jsonify({'error': 'Fichier audio non trouvé'}), 404
            
        filename = result[0]
        
        # Générer une URL signée
        audio_service = get_audio_service()
        signed_url = audio_service.generate_signed_url_for_feedback(
            filename,
            duration_minutes=30  # 30 minutes
        )
        
        if not signed_url:
            return jsonify({'error': 'Impossible de générer une URL signée'}), 500
            
        return jsonify({'url': signed_url})
    except Exception as e:
        logger.error(f"Erreur lors de la récupération du feedback audio {feedback_id}: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/delete-audio-feedback/<int:feedback_id>', methods=['POST'])
@login_required
def delete_audio_feedback(feedback_id):
    """Supprime un fichier de feedback audio"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Récupérer le nom du fichier audio depuis capsules_feedback
        cursor.execute("""
            SELECT audio_feedback_file, user_id
            FROM capsules_feedback
            WHERE id = %s
        """, (feedback_id,))
        
        result = cursor.fetchone()
        if not result or not result[0]:
            flash("Fichier audio non trouvé", "danger")
            return redirect(url_for('audio_capsule.admin_audio_feedbacks'))
            
        filename = result[0]
        user_id = result[1]
        
        # Supprimer le fichier de Cloud Storage
        audio_service = get_audio_service()
        deleted = audio_service.delete_feedback_file(filename)
        
        if deleted:
            # Supprimer l'entrée de la base de données
            cursor.execute("""
                DELETE FROM capsules_feedback
                WHERE id = %s
            """, (feedback_id,))
            
            mysql.connection.commit()
            flash("Fichier audio supprimé avec succès", "success")
        else:
            flash("Erreur lors de la suppression du fichier audio", "danger")
            
        # Rediriger vers la liste des feedbacks avec filtre utilisateur
        return redirect(url_for('audio_capsule.admin_audio_feedbacks', user_id=user_id))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la suppression du feedback audio {feedback_id}: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_audio_feedbacks'))
    finally:
        cursor.close()

@audio_capsule_bp.route('/admin/delete-feedback/<int:feedback_id>', methods=['POST'])
@login_required
def delete_feedback(feedback_id):
    """Supprime un feedback (texte ou audio)"""
    if current_user.user_status != 'admin' or not session.get('two_factor_authenticated'):
        abort(403)
        
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    try:
        # Vérifier si le feedback existe et s'il contient un fichier audio
        cursor.execute("""
            SELECT audio_feedback_file, user_id
            FROM capsules_feedback
            WHERE id = %s
        """, (feedback_id,))
        
        result = cursor.fetchone()
        if not result:
            flash("Feedback non trouvé", "danger")
            return redirect(url_for('audio_capsule.admin_feedbacks'))
            
        audio_file = result[0]
        user_id = result[1]
        
        # Si le feedback contient un fichier audio, le supprimer de Cloud Storage
        if audio_file:
            audio_service = get_audio_service()
            deleted = audio_service.delete_feedback_file(audio_file)
            
            if not deleted:
                logger.warning(f"Impossible de supprimer le fichier audio {audio_file} sur Cloud Storage")
        
        # Supprimer le feedback de la base de données
        cursor.execute("""
            DELETE FROM capsules_feedback
            WHERE id = %s
        """, (feedback_id,))
        
        mysql.connection.commit()
        flash("Feedback supprimé avec succès", "success")
        
        # Rediriger vers la liste des feedbacks
        return redirect(url_for('audio_capsule.admin_feedbacks'))
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la suppression du feedback {feedback_id}: {e}")
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('audio_capsule.admin_feedbacks'))
    finally:
        cursor.close()