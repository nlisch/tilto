import uuid
import sys
import json
import logging
from MySQLdb.cursors import DictCursor
from datetime import datetime
import re
from flask import current_app
import os

logger = logging.getLogger(__name__)

def generate_request_id():
    return str(uuid.uuid4())

def log_json_size(json_data, request_id):
    json_size = sys.getsizeof(json.dumps(json_data))
    logger.info(f"[Request ID: {request_id}] Taille du résultat JSON : {json_size} bytes")
    if json_size > 1000000:  # Alert if more than 1 MB
        logger.warning(f"[Request ID: {request_id}] Résultat JSON très volumineux : {json_size} bytes")

def get_or_create_quiz_session(cursor, user_id, quiz_id):
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Début get_or_create_quiz_session pour user_id: {user_id}, quiz_id: {quiz_id}")

    if not isinstance(cursor, DictCursor):
        cursor.close()
        cursor = cursor.connection.cursor(DictCursor)

    try:
        # D'abord vérifier s'il existe une session completed
        cursor.execute("""
            SELECT quiz_session_id, quiz_status, updated_at, created_at,
                   questions_answered_count, question_history,
                   (SELECT COUNT(*) FROM result_user 
                    WHERE user_id = qu.user_id 
                    AND quiz_id = qu.quiz_id) as has_analysis
            FROM quiz_user qu
            WHERE user_id = %s 
            AND quiz_id = %s
            AND quiz_status = 'completed'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        completed_session = cursor.fetchone()
        
        if completed_session:
            logger.info(f"[Request ID: {request_id}] Session complétée existante trouvée: {completed_session['quiz_session_id']}")
            # Mettre à jour le timestamp de la dernière consultation
            cursor.execute("""
                UPDATE quiz_user
                SET updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            """, (completed_session['quiz_session_id'],))
            cursor.connection.commit()
            return completed_session['quiz_session_id']

        # Si pas de session completed, vérifier s'il existe une session en cours
        cursor.execute("""
            SELECT quiz_session_id, quiz_status, updated_at, created_at,
                   questions_answered_count, question_history
            FROM quiz_user
            WHERE user_id = %s 
            AND quiz_id = %s
            AND quiz_status NOT IN ('completed')
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        existing_session = cursor.fetchone()
        
        if existing_session:
            logger.info(f"[Request ID: {request_id}] Session existante trouvée: {existing_session['quiz_session_id']}")
            logger.info(f"[Request ID: {request_id}] État de la session: status={existing_session['quiz_status']}, "
                       f"questions_answered={existing_session['questions_answered_count']}")
            
            # Mettre à jour le timestamp
            cursor.execute("""
                UPDATE quiz_user
                SET updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            """, (existing_session['quiz_session_id'],))
            cursor.connection.commit()
            
            return existing_session['quiz_session_id']

        # Récupérer l'historique de la dernière session
        cursor.execute("""
            SELECT question_history, quiz_status
            FROM quiz_user
            WHERE user_id = %s AND quiz_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        last_session = cursor.fetchone()
        initial_history = last_session['question_history'] if last_session else '[]'
        question_count = len(json.loads(initial_history))

        # Nettoyer les anciennes sessions non complétées
        cursor.execute("""
            UPDATE quiz_user
            SET quiz_status = 'completed'
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND quiz_status NOT IN ('completed')
        """, (user_id, quiz_id))

        # Créer une nouvelle session
        current_timestamp = datetime.now()
        cursor.execute("""
            INSERT INTO quiz_user 
            (user_id, quiz_id, quiz_status, questions_answered_count, 
             question_history, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, quiz_id, 
              'answers_review' if last_session and last_session['quiz_status'] == 'answers_review' else 'in_progress',
              question_count,
              initial_history,
              current_timestamp, current_timestamp))
        
        new_session_id = cursor.lastrowid
        cursor.connection.commit()
        
        logger.info(f"[Request ID: {request_id}] Nouvelle session créée: {new_session_id}")
        logger.info(f"[Request ID: {request_id}] Historique préservé: {initial_history}")
        
        return new_session_id

    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Erreur lors de la création/récupération de session: {str(e)}", exc_info=True)
        cursor.connection.rollback()
        raise

    finally:
        logger.info(f"[Request ID: {request_id}] Fin get_or_create_quiz_session")

def replace_numbers_with_bold(text: str) -> str:
    """
    Met en gras les nombres avec pourcentage dans le texte en utilisant des balises HTML.
    Args:
        text (str): Texte à traiter
    Returns:
        str: Texte avec les nombres en balises <strong>
    """
    if not isinstance(text, str):
        return text
        
    # Regex pour matcher les nombres suivis de % et les nombres décimaux
    pattern = r'(\d+(?:,\d+)?%|\d+(?:\.\d+)?%|\d+%|\d+(?:\.\d+)?(?=\s*(?:million|k|fois|mille|euros?\b|€|\$)))'
    
    return re.sub(pattern, r'<strong>\1</strong>', text)

def allowed_audio_file(filename):
    """Vérifie si un fichier audio a une extension autorisée."""
    allowed_extensions = current_app.config.get('ALLOWED_AUDIO_EXTENSIONS', 
                                               {'mp3', 'wav', 'webm', 'm4a', 'ogg'})
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def check_audio_file_size(file):
    """Vérifie si un fichier audio ne dépasse pas la taille maximale autorisée."""
    max_size = current_app.config.get('MAX_AUDIO_SIZE', 10 * 1024 * 1024)  # 10 MB par défaut
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)
    return file_size <= max_size

# 3. Modifications à apporter au service de transcription pour l'intégrer à votre système d'authentification

def get_openai_api_key():
    """Récupère la clé API OpenAI de manière sécurisée."""
    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        logger.error("Clé API OpenAI non configurée")
        raise ValueError("Configuration OpenAI manquante")
    return api_key
