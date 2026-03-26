from flask import Blueprint, jsonify, request, render_template, flash, redirect, url_for, current_app, Markup, g
from flask_login import login_required, current_user
from services import QuizAnalysisService, PromptData
from utils import generate_request_id, replace_numbers_with_bold
from decorators import check_token_required, admin_required
import logging
import json
import time
import uuid
from flask_babel import Babel, gettext as _, lazy_gettext as _l, gettext
from functools import wraps
from MySQLdb.cursors import DictCursor
from services.analysis_access_service import AnalysisAccessModel
from services.piste_access_service import PisteAccessService
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from extensions import csrf

quiz_analysis_bp = Blueprint('quiz_analysis', __name__, url_prefix='/analysis')
logger = logging.getLogger(__name__)

# ==================== MAPPING DES ANALYSES STATIQUES ====================
# Définition unique - utilisée partout dans le fichier
USER_STATIC_TEMPLATES = {
    1: 'quiz_analysis/static_analysis/user_53.html',
    19: 'quiz_analysis/static_analysis/user_53_test.html',
    54: 'quiz_analysis/static_analysis/user_45.html',
    57: 'quiz_analysis/static_analysis/user_53_test.html',
    9: 'quiz_analysis/static_analysis/user_53_test.html',
    59: 'quiz_analysis/static_analysis/user_17.html',
    15: 'quiz_analysis/static_analysis/user_15.html',
    16: 'quiz_analysis/static_analysis/user_16.html',
    17: 'quiz_analysis/static_analysis/user_17.html',
    23: 'quiz_analysis/static_analysis/user_23.html',
    24: 'quiz_analysis/static_analysis/user_24.html',
    25: 'quiz_analysis/static_analysis/user_25.html',
    26: 'quiz_analysis/static_analysis/user_26.html',
    27: 'quiz_analysis/static_analysis/user_27.html',
    28: 'quiz_analysis/static_analysis/user_28.html',
    31: 'quiz_analysis/static_analysis/user_31.html',
    33: 'quiz_analysis/static_analysis/user_33.html',
    35: 'quiz_analysis/static_analysis/user_35.html',
    36: 'quiz_analysis/static_analysis/user_36.html',
    37: 'quiz_analysis/static_analysis/user_37.html',
    38: 'quiz_analysis/static_analysis/user_38.html',
    91: 'quiz_analysis/static_analysis/user_37.html',
    45: 'quiz_analysis/static_analysis/user_45.html',
    46: 'quiz_analysis/static_analysis/user_46.html',
    48: 'quiz_analysis/static_analysis/user_48.html',
    53: 'quiz_analysis/static_analysis/user_53_test.html'
    
}

def handle_transcription_request(request, cursor):
    """Gère les demandes de transcription audio"""
    try:
        quiz_session_id = int(request.form.get('quiz_session_id'))
        question_id = int(request.form.get('question_id'))
        user_id = int(request.form.get('user_id'))
        quiz_id = request.form.get('quiz_id')
        audio_file_path = request.form.get('audio_file_path')
        
        # Vérifier si une transcription existe déjà
        cursor.execute("""
            SELECT id FROM audio_transcriptions 
            WHERE quiz_session_id = %s AND question_id = %s
        """, (quiz_session_id, question_id))
        
        if cursor.fetchone():
            return {'success': False, 'error': 'Transcription déjà existante'}
        
        # Utiliser le service AudioService existant pour la transcription
        from services.audio_service import AudioService
        
        # Pour l'instant, créer un fichier temporaire depuis l'URL GCS
        # (Dans un cas réel, vous devriez télécharger le fichier depuis GCS)
        
        # Simulation de transcription (à remplacer par un vrai appel)
        transcription_result = {
            'success': True,
            'transcript': '[Transcription simulée - À implémenter avec Whisper]'
        }
        
        if transcription_result['success']:
            # Sauvegarder la transcription
            cursor.execute("""
                INSERT INTO audio_transcriptions 
                (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, transcription, transcription_status)
                VALUES (%s, %s, %s, %s, %s, %s, 'completed')
            """, (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, transcription_result['transcript']))
            
            return {'success': True, 'transcription': transcription_result['transcript']}
        else:
            return {'success': False, 'error': transcription_result.get('error', 'Erreur de transcription')}
            
    except Exception as e:
        logger.error(f"Erreur dans handle_transcription_request: {str(e)}")
        return {'success': False, 'error': str(e)}

def get_latest_analysis(quiz_id: str, user_id: int, step_id: str = 'career_path', request_id: str = None):
    """
    Récupère la dernière analyse JSON stockée pour un utilisateur et un quiz donné.
    
    Args:
        quiz_id (str): Identifiant du quiz
        user_id (int): Identifiant de l'utilisateur
        step_id (str): Identifiant de l'étape (default: 'vision_360')
        request_id (str): Identifiant de la requête pour le logging
    
    Returns:
        tuple: (result_json, result_step_id, result_step_ranking) ou (None, None, None) si non trouvé
        
    Raises:
        ValueError: Si les paramètres sont invalides
        json.JSONDecodeError: Si le JSON stocké est invalide
    """
    logger.info(f"[Request ID: {request_id}] Getting latest analysis for quiz_id: {quiz_id}, step_id: {step_id}, user_id: {user_id}")
    
    # Validation des paramètres
    if not quiz_id or not user_id or not step_id:
        logger.error(f"[Request ID: {request_id}] Invalid parameters: quiz_id={quiz_id}, user_id={user_id}, step_id={step_id}")
        raise ValueError("Invalid parameters provided")
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    try:
        # Vérifier d'abord si le quiz est complété
        cursor.execute("""
            SELECT quiz_status
            FROM quiz_user
            WHERE quiz_id = %s AND user_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (quiz_id, user_id))
        
        quiz_status = cursor.fetchone()
        if not quiz_status or quiz_status['quiz_status'] != 'completed':
            logger.warning(f"[Request ID: {request_id}] Quiz not completed. Status: {quiz_status['quiz_status'] if quiz_status else 'None'}")
            return None, None, None
        
        # Récupérer l'analyse avec validation du token
        cursor.execute("""
            SELECT 
                ru.result_json,
                ru.token_id,
                ru.created_at,
                qr.result_step_id,
                qr.result_step_ranking
            FROM result_user ru
            JOIN quiz_result qr ON ru.result_step_id = qr.result_step_id 
            WHERE ru.quiz_id = %s 
            AND ru.user_id = %s
            AND ru.result_step_id = %s
            AND qr.is_active = TRUE
            AND ru.is_active = TRUE
            ORDER BY ru.created_at DESC
            LIMIT 1
        """, (quiz_id, user_id, step_id))
        
        result = cursor.fetchone()
        if not result:
            logger.warning(f"[Request ID: {request_id}] No analysis found")
            return None, None, None
            
        # Vérifier que le token est bien marqué comme utilisé
        if not result['token_id']:
            logger.error(f"[Request ID: {request_id}] Analysis found but no token associated")
            return None, None, None
        
        logger.info(f"[Request ID: {request_id}] Analysis found:")
        logger.info(f"  - Step ID: {result['result_step_id']}")
        logger.info(f"  - Ranking: {result['result_step_ranking']}")
        logger.info(f"  - Created at: {result['created_at']}")
        logger.info(f"  - Token: {result['token_id']}")
        
        try:
            # Parser le JSON
            result_json = json.loads(result['result_json'])
            
            # Validation selon le step_id
            if not isinstance(result_json, dict):
                logger.error(f"[Request ID: {request_id}] Invalid JSON structure: not a dict")
                return None, None, None
            
            # Validation spécifique au type d'analyse
            if step_id == 'career_path' or step_id == 'career_path_v1':
                # Validation déjà faite dans _validate_career_path_response
                required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
                for key in required_keys:
                    if key not in result_json:  # ✅ UTILISER result_json, PAS analysis_data
                        raise ValueError(f"Invalid career_path structure: missing key '{key}'")
                
                # Vérifier que strategies et actions ont 3 items
                if 'items' not in result_json['strategies'] or len(result_json['strategies']['items']) != 3:
                    raise ValueError(f"Invalid career_path: strategies must have 3 items, got {len(result_json['strategies'].get('items', []))}")
                
                if 'items' not in result_json['actions'] or len(result_json['actions']['items']) != 3:
                    raise ValueError(f"Invalid career_path: actions must have 3 items, got {len(result_json['actions'].get('items', []))}")
                
                logger.info(f"[Request ID: {request_id}] Career path structure validated successfully")
            
            elif step_id == 'vision_360':
                # Ancienne validation pour vision_360
                if 'superpowers' not in result_json:
                    logger.error(f"[Request ID: {request_id}] Invalid JSON structure: missing 'superpowers' key")
                    return None, None, None
                    
                if not isinstance(result_json['superpowers'], list):
                    logger.error(f"[Request ID: {request_id}] Invalid JSON structure: 'superpowers' is not a list")
                    return None, None, None
                
                logger.info(f"[Request ID: {request_id}] JSON validated successfully with {len(result_json['superpowers'])} superpowers")

            elif step_id == 'career_path_v4':
                required_keys = ['welcome', 'pistes', 'section4']
                for key in required_keys:
                    if key not in result_json:
                        raise ValueError(f"Invalid career_path_v4 structure: missing '{key}'")
                
                if not result_json.get('pistes') or len(result_json['pistes']) != 3:
                    raise ValueError("Invalid career_path_v4: pistes must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V4 structure validated")
            
            else:
                logger.warning(f"[Request ID: {request_id}] Unknown step_id for validation: {step_id}")
            
            return result_json, result['result_step_id'], result['result_step_ranking']
            
        except json.JSONDecodeError as e:
            logger.error(f"[Request ID: {request_id}] Invalid JSON in database: {str(e)}", exc_info=True)
            return None, None, None
            
    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Error getting latest analysis: {str(e)}", exc_info=True)
        raise
        
    finally:
        cursor.close()

def process_analysis_data(analysis_data):
    """
    Parcourt récursivement les données d'analyse et applique replace_numbers_with_bold
    uniquement aux éléments dans la classe did-you-know.
    """
    if isinstance(analysis_data, dict):
        processed_data = {}
        for k, v in analysis_data.items():
            # Si on trouve un did-you-know, on applique le remplacement sur son contenu
            if k == 'did_you_know' and isinstance(v, dict) and 'content' in v:
                processed_data[k] = {
                    **v,
                    'content': Markup(replace_numbers_with_bold(v['content']))
                }
            else:
                processed_data[k] = process_analysis_data(v)
        return processed_data
    elif isinstance(analysis_data, list):
        return [process_analysis_data(item) for item in analysis_data]
    else:
        return analysis_data

@quiz_analysis_bp.route('/generate/<string:step_id>', methods=['POST'])
@login_required
@check_token_required
def generate_analysis(step_id: str):
    request_id = generate_request_id()
    start_time = time.time()
    logger.info(f"[Request ID: {request_id}] Starting analysis generation for step_id: {step_id}")
    
    data = request.json
    quiz_id = data.get('quiz_id')
    force_new = data.get('force_new', False)
    token_id = data.get('token_id')  # Récupérer le token_id depuis la requête
    enable_web_search = data.get('enable_web_search', None)

    logger.info(f"[Request ID: {request_id}] Parameters: quiz_id={quiz_id}, step_id={step_id}, "
                f"force_new={force_new}, enable_web_search={enable_web_search}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        analysis_service = QuizAnalysisService(cursor, current_user.id, quiz_id)        
        
        # Récupérer les informations de l'étape
        cursor.execute("""
            SELECT template_html, prompt_instruction, prompt_knowledge, result_step_ranking
            FROM quiz_result
            WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
        """, (quiz_id, step_id))
        
        step_info = cursor.fetchone()
        if not step_info:
            logger.error(f"[Request ID: {request_id}] Step not found or inactive for step_id: {step_id}")
            return jsonify({'error': 'Step not found or inactive'}), 404
            
        prompt_instruction = step_info['prompt_instruction']
        prompt_knowledge = step_info['prompt_knowledge']
        step_ranking = step_info['result_step_ranking']
        
        # Préparation des données
        logger.debug(f"[Request ID: {request_id}] Preparing prompt data...")
        try:
            prompt_data = analysis_service.prepare_prompt_data()
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Error preparing prompt data: {str(e)}")
            return jsonify({'error': 'Error preparing data'}), 500
        
        # Validation du token AVANT de commencer l'analyse
        try:
            token_id = analysis_service.validate_and_get_token(step_id, force_new)
            logger.info(f"[Request ID: {request_id}] Valid token found: {token_id}")
            # Si ce n'est pas la première step (vision_360), on cherche le result_id existant
            result_id = None
            if step_id != 'vision_360':
                cursor.execute("""
                    SELECT ru.result_id
                    FROM result_user ru
                    WHERE ru.quiz_id = %s 
                    AND ru.user_id = %s
                    AND ru.token_id = %s
                    AND ru.result_step_id = 'vision_360'
                    AND ru.is_active = TRUE
                    ORDER BY ru.created_at DESC
                    LIMIT 1
                """, (quiz_id, current_user.id, token_id))
                
                result = cursor.fetchone()
                if result:
                    result_id = result['result_id']
                    logger.info(f"[Request ID: {request_id}] Found existing result_id {result_id} for token {token_id}")

            # Si pas de result_id trouvé ou si c'est vision_360, on en crée un nouveau
            if not result_id:
                result_id = str(uuid.uuid4())
                logger.info(f"[Request ID: {request_id}] Generated new result_id {result_id}")


        except ValueError as e:
            error_msg = str(e)
            if error_msg.startswith('existing_analysis:'):
                try:
                    # Parse the result_id and token_id from the error message
                    parts = error_msg.split(':')
                    if len(parts) != 3:  # Vérification que nous avons les 3 parties attendues
                        raise ValueError("Invalid error message format")
                    _, result_id, token_id = parts
                    return jsonify({
                        'status': 'success',
                        'message': 'Analysis already exists',
                        'redirect_url': url_for('quiz_analysis.view_analysis',
                                              quiz_id=quiz_id,
                                              result_id=result_id,
                                              step_id=step_id,
                                              token_id=token_id,
                                              skip_loading=False)
                    })
                except Exception as split_error:
                    logger.error(f"[Request ID: {request_id}] Error parsing existing analysis info: {str(split_error)}")
                    return jsonify({'error': 'Error processing analysis information'}), 500
            else:
                return jsonify({'error': str(e)}), 403

        # Génération de l'analyse
        logger.info(f"[Request ID: {request_id}] Starting analysis generation...")
        try:
            result_json, prompt_id, timings = analysis_service._generate_analysis(  # ← RÉCUPÉRER timings aussi
                result_id=result_id,
                step_id=step_id,
                request_id=request_id,
                prompt_instruction=prompt_instruction,
                prompt_knowledge=prompt_knowledge,
                enable_web_search=enable_web_search
            )
            
            # Vérification du résultat selon le type d'analyse
            if step_id == 'career_path':
                required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
                for key in required_keys:
                    if key not in result_json:
                        raise ValueError(f"Invalid career_path structure: missing '{key}'")
                
                if not result_json['strategies'].get('items') or len(result_json['strategies']['items']) != 3:
                    raise ValueError("Invalid career_path: strategies must have 3 items")
                
                if not result_json['actions'].get('items') or len(result_json['actions']['items']) != 3:
                    raise ValueError("Invalid career_path: actions must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path structure validated")

            elif step_id == 'career_path_v1':
                # Validation spécifique pour V1
                required_keys = ['cover_quote', 'hero_intro', 'voies', 'transformations', 'atouts']
                for key in required_keys:
                    if key not in result_json:
                        raise ValueError(f"Invalid career_path_v1 structure: missing '{key}'")
                
                if not isinstance(result_json['voies'], list) or len(result_json['voies']) != 3:
                    raise ValueError("Invalid career_path_v1: voies must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V1 structure validated")

            elif step_id == 'career_path_v2':
                if not isinstance(analysis_data, dict):
                    raise ValueError("Invalid career_path_v2 structure: not a dict")
                
                # ✅ Structure V2 (template Nelly - différente de V1)
                required_keys = ['cover_quote', 'intro_text_bloc1', 'intro_text_bloc2', 'transformations', 'options', 'voies']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v2 structure: missing '{key}'")
                
                if not analysis_data.get('voies') or len(analysis_data['voies']) != 3:
                    raise ValueError("Invalid career_path_v2: voies must have 3 items")
                
                if not analysis_data.get('options') or len(analysis_data['options']) != 3:
                    raise ValueError("Invalid career_path_v2: options must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V2 structure validated")

            elif step_id == 'career_path_v3':
                if not isinstance(analysis_data, dict):
                    raise ValueError("Invalid career_path_v3 structure: not a dict")
                
                # ✅ Structure V2 (template Nelly - différente de V1)
                required_keys = ['cover_quote', 'intro_text_bloc1', 'intro_text_bloc2', 'transformations', 'options', 'voies']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v3 structure: missing '{key}'")
                
                if not analysis_data.get('voies') or len(analysis_data['voies']) != 3:
                    raise ValueError("Invalid career_path_v3: voies must have 3 items")
                
                if not analysis_data.get('options') or len(analysis_data['options']) != 3:
                    raise ValueError("Invalid career_path_v3: options must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V2 structure validated")

            elif step_id == 'career_path_v4':
                if not isinstance(result_json, dict):
                    raise ValueError("Invalid career_path_v4 structure: not a dict")
                
                required_keys = ['welcome', 'pistes', 'section4']
                for key in required_keys:
                    if key not in result_json:
                        raise ValueError(f"Invalid career_path_v4 structure: missing '{key}'")
                
                if not result_json.get('pistes') or len(result_json['pistes']) != 3:
                    raise ValueError("Invalid career_path_v4: pistes must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V4 structure validated")

            elif step_id == 'checkup_pro':
                if not isinstance(result_json, dict) or 'blocks' not in result_json or not result_json['blocks']:
                    raise ValueError("Invalid checkup analysis structure")
                    
            elif step_id == 'vision_360':
                if not isinstance(result_json, dict) or 'superpowers' not in result_json:
                    raise ValueError("Invalid vision_360 analysis structure")
                    
            else:
                # Si ce n'est pas un step_id connu, on rejette
                logger.warning(f"[Request ID: {request_id}] Unknown step_id: {step_id}, skipping validation")
            
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Error generating analysis: {str(e)}")
            return jsonify({'error': 'Analysis generation failed'}), 500
        
        # Stockage du résultat
        logger.debug(f"[Request ID: {request_id}] Storing analysis result...")
        try:
            
            analysis_service._store_analysis_result(
                result_id=result_id,
                step_id=step_id,
                result_json=result_json,
                token_id=token_id,
                prompt_id=prompt_id,
                is_active=True,
                generator_type='user',
                timings=timings
            )
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Error storing analysis: {str(e)}")
            return jsonify({'error': 'Error storing analysis'}), 500
        
        # Rechercher l'étape suivante
        next_step = analysis_service.get_remaining_steps(token_id)
        
        # Si c'était la dernière étape, mettre à jour le statut du quiz
        if not next_step or len(next_step) == 0:
            analysis_service.update_quiz_status('completed')
            logger.info(f"[Request ID: {request_id}] All steps completed, marked quiz as completed ")
        
        # Commiter la transaction uniquement après que tout soit OK
        mysql.connection.commit()
        logger.info(f"[Request ID: {request_id}] Transaction committed successfully")
        
        end_time = time.time()
        logger.info(f"[Request ID: {request_id}] Analysis generation completed in {end_time - start_time:.2f} seconds")
        
        # Retourner une réponse JSON avec l'URL de redirection
        response_data = {
            'status': 'success',
            'message': 'Analysis generated successfully',
            'redirect_url': url_for('quiz_analysis.view_analysis', 
                                  quiz_id=quiz_id,
                                  result_id=result_id,
                                  step_id=step_id,
                                  token_id=token_id,
                                  skip_loading=False)
        }
        
        # Ajouter l'étape suivante si elle existe
        if next_step and len(next_step) > 0:
            response_data['next_step'] = next_step[0]['step_id']
            
        return jsonify(response_data)
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[Request ID: {request_id}] Error during analysis generation: {str(e)}", exc_info=True)
        return jsonify({'error': "An error occurred during analysis"}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/get_latest_token/<string:quiz_id>')
@login_required
def get_latest_token(quiz_id: str):
    """Récupère les informations du dernier token utilisé pour une analyse."""
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Fetching latest token for quiz: {quiz_id}, user: {current_user.id}")

    cursor = current_app.mysql.connection.cursor(DictCursor)
    try:
        # 0. Vérifier l'existence du quiz dans le catalogue
        logger.debug(f"[Request ID: {request_id}] Vérification de l'existence du quiz")
        cursor.execute("""
            SELECT quiz_id, quiz_type, is_active
            FROM quiz_catalog
            WHERE quiz_id = %s
        """, (quiz_id,))
        
        quiz = cursor.fetchone()
        if not quiz:
            logger.error(f"[Request ID: {request_id}] Quiz {quiz_id} non trouvé dans le catalogue")
            return jsonify({'error': 'Quiz not found'}), 404
        
        if not quiz['is_active']:
            logger.error(f"[Request ID: {request_id}] Quiz {quiz_id} inactif")
            return jsonify({'error': 'Quiz inactive'}), 403

        # 1. Debug de l'état du quiz dans quiz_user
        logger.debug(f"[Request ID: {request_id}] Vérification du statut du quiz")
        cursor.execute("""
            SELECT qu.quiz_status, qu.questions_answered_count,
                   COUNT(DISTINCT ru.result_id) as analysis_count,
                   qu.quiz_session_id,
                   CASE 
                       WHEN EXISTS (
                           SELECT 1 
                           FROM result_user ru 
                           WHERE ru.quiz_id = qu.quiz_id 
                           AND ru.user_id = qu.user_id
                           AND ru.is_active = TRUE
                       ) THEN TRUE 
                       ELSE FALSE 
                   END as has_analysis
            FROM quiz_user qu
            LEFT JOIN result_user ru ON ru.quiz_id = qu.quiz_id 
                                   AND ru.user_id = qu.user_id
                                   AND ru.is_active = TRUE
            WHERE qu.quiz_id = %s AND qu.user_id = %s
            GROUP BY qu.quiz_session_id, qu.quiz_status, qu.questions_answered_count
            ORDER BY qu.updated_at DESC
            LIMIT 1
        """, (quiz_id, current_user.id))
        
        quiz_info = cursor.fetchone()
        if not quiz_info:
            logger.warning(f"[Request ID: {request_id}] Aucune session de quiz trouvée")
            return jsonify({'error': 'Quiz not started'}), 404

        logger.info(f"[Request ID: {request_id}] État du quiz:")
        logger.info(f"  - Status: {quiz_info['quiz_status']}")
        logger.info(f"  - Questions répondues: {quiz_info['questions_answered_count']}")
        logger.info(f"  - Session ID: {quiz_info['quiz_session_id']}")
        logger.info(f"  - Has analysis: {quiz_info['has_analysis']}")
        logger.info(f"  - Nombre d'analyses: {quiz_info['analysis_count']}")

        if quiz_info['quiz_status'] != 'completed':
            logger.warning(f"[Request ID: {request_id}] Quiz non complété. Status: {quiz_info['quiz_status']}")
            return jsonify({'error': 'Quiz not completed'}), 403

        # 2. Vérifier les réponses
        cursor.execute("""
            SELECT COUNT(*) as answer_count
            FROM answer_user
            WHERE quiz_session_id = %s
        """, (quiz_info['quiz_session_id'],))
        
        answer_count = cursor.fetchone()['answer_count']
        logger.info(f"[Request ID: {request_id}] Nombre de réponses: {answer_count}")

        # 3. Debug des tokens
        logger.debug(f"[Request ID: {request_id}] Vérification des tokens")
        cursor.execute("""
            SELECT token_code, token_type, is_used, used_at, expiration_date
            FROM tokens
            WHERE user_id = %s 
            AND quiz_id = %s
            AND (is_used = TRUE)  -- On cherche spécifiquement les tokens utilisés
            AND (expiration_date IS NULL OR expiration_date > NOW())
            ORDER BY created_at DESC
        """, (current_user.id, quiz_id))
        
        tokens = cursor.fetchall()
        logger.info(f"[Request ID: {request_id}] Tokens trouvés: {len(tokens) if tokens else 0}")
        for token in tokens:
            logger.info(f"  - Token {token['token_code']}: used={token['is_used']}, used_at={token['used_at']}")

        # 4. Vérifier la configuration des étapes d'analyse
        logger.debug(f"[Request ID: {request_id}] Vérification des étapes configurées")
        cursor.execute("""
            SELECT result_step_id, is_active
            FROM quiz_result
            WHERE quiz_id = %s AND is_active = TRUE
        """, (quiz_id,))
        
        steps = cursor.fetchall()
        if not steps:
            logger.error(f"[Request ID: {request_id}] Aucune étape d'analyse configurée")
            return jsonify({'error': 'No analysis steps configured'}), 500

        # 5. Recherche de l'analyse la plus récente avec son token
        logger.debug(f"[Request ID: {request_id}] Recherche de l'analyse la plus récente")
        cursor.execute("""
            WITH LatestResults AS (
                SELECT ru.result_id, ru.token_id, ru.created_at,
                       t.is_used, t.used_at, t.expiration_date
                FROM result_user ru
                JOIN tokens t ON ru.token_id = t.token_code
                WHERE ru.quiz_id = %s 
                AND ru.user_id = %s
                AND ru.result_step_id = 'vision_360'
                AND ru.is_active = TRUE
                ORDER BY ru.created_at DESC
                LIMIT 1
            )
            SELECT lr.*,
                   COUNT(ru.result_step_id) as total_steps_completed
            FROM LatestResults lr
            LEFT JOIN result_user ru ON ru.token_id = lr.token_id AND ru.is_active = TRUE
            GROUP BY lr.result_id, lr.token_id, lr.created_at, lr.is_used, 
                     lr.used_at, lr.expiration_date
        """, (quiz_id, current_user.id))
        
        result = cursor.fetchone()
        if result:
            logger.info(f"[Request ID: {request_id}] Analyse trouvée:")
            logger.info(f"  - Result ID: {result['result_id']}")
            logger.info(f"  - Token: {result['token_id']}")
            logger.info(f"  - Créée le: {result['created_at']}")
            logger.info(f"  - Étapes complétées: {result['total_steps_completed']}")
            
            return jsonify({
                'token_id': result['token_id'],
                'result_id': result['result_id']
            })
        else:
            logger.warning(f"[Request ID: {request_id}] Aucune analyse trouvée")
            return jsonify({'error': 'No analysis found'}), 404

    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/view/<string:quiz_id>')
def view_analysis(quiz_id: str):
    """
    Affiche l'analyse dynamique OU statique.
    Accessible via login OU via token partageable.
    """
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Accessing analysis view for quiz_id: {quiz_id}")

    # Récupération des paramètres URL
    result_id = request.args.get('result_id')
    step_id = request.args.get('step_id', 'career_path')
    skip_loading = request.args.get('skip_loading', 'true').lower() == 'true'
    generator_type = request.args.get('generator_type', None)
    token = request.args.get('token', None)
    
    logger.info(f"[Request ID: {request_id}] Parameters: result_id: {result_id}, step_id: {step_id}, skip_loading: {skip_loading}, generator_type: {generator_type}, token: {token}")

    # Variables partagées entre les deux modes d'accès
    is_token_access = False
    token_user_id = None
    access_badge = None
    token_data = None
    access_info = None  # ✅ Initialiser access_info
    
    # ========== MODE 1 : ACCÈS VIA TOKEN (lien partageable) ==========
    if token:
        cursor = current_app.mysql.connection.cursor(DictCursor)
        try:
            # Vérifier que le token existe et est valide
            cursor.execute("""
                SELECT 
                    user_id,
                    quiz_id,
                    result_id,
                    access_type,
                    expires_at,
                    is_revoked,
                    view_count
                FROM analysis_access_tokens
                WHERE token = %s
                AND is_revoked = FALSE
            """, (token,))
            
            token_data = cursor.fetchone()
            
            if not token_data:
                cursor.close()
                flash("Ce lien d'accès n'existe pas ou a été révoqué.", "danger")
                return redirect(url_for('auth.login'))
            
            # Vérifier si le token FREE a expiré (PAID = illimité)
            if token_data['access_type'] == 'free' and token_data['expires_at']:
                if datetime.now() > token_data['expires_at']:
                    # Récupérer le prénom du propriétaire pour personnaliser
                    cursor.execute("""
                        SELECT firstname FROM users WHERE user_id = %s
                    """, (token_data['user_id'],))
                    owner = cursor.fetchone()
                    
                    cursor.close()
                    return render_template(
                        'quiz_analysis/share_link_expired.html',
                        firstname=owner['firstname'] if owner else None
                    )
            
            # Incrémenter le compteur de vues
            cursor.execute("""
                UPDATE analysis_access_tokens 
                SET view_count = view_count + 1
                WHERE token = %s
            """, (token,))
            current_app.mysql.connection.commit()
            
            # Extraire les infos du token pour la suite
            token_user_id = token_data['user_id']
            quiz_id = token_data['quiz_id']
            result_id = token_data['result_id']
            is_token_access = True
            
            # Si result_id est NULL ou fictif (static_), récupérer depuis result_user
            cursor.execute("""
                SELECT result_id, result_step_id
                FROM result_user
                WHERE user_id = %s AND quiz_id = %s AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
            """, (token_user_id, quiz_id))
            
            active_result = cursor.fetchone()
            if active_result:
                result_id = active_result['result_id']
                step_id = active_result['result_step_id']  # Écrase le step_id par défaut
                logger.info(f"[Request ID: {request_id}] Retrieved from DB: result_id={result_id}, step_id={step_id}")
            
            # ✅ Récupérer access_info via le modèle
            access_info = AnalysisAccessModel.get_by_token(cursor, token)
            
            # Préparer le badge d'accès pour l'affichage
            access_badge = {
                'type': token_data['access_type'].upper(),
                'views': token_data['view_count'] + 1,
                'expires_at': token_data['expires_at'].strftime('%d/%m/%Y') if token_data['expires_at'] else None
            }
            
            logger.info(f"[Request ID: {request_id}] Token access validated for user {token_user_id}")
            
        except Exception as e:
            if cursor:
                cursor.close()
            logger.error(f"[Request ID: {request_id}] Token validation error: {e}")
            flash("Erreur lors de la validation du token.", "danger")
            return redirect(url_for('auth.login'))
        
        # ========== CAS SPÉCIAL : Analyse statique (HTML hardcodé) ==========
        if token_user_id in USER_STATIC_TEMPLATES:
            logger.info(f"[Request ID: {request_id}] User {token_user_id} has static template configured")
            
            # Vérifier si une analyse dynamique active existe
            has_dynamic_analysis = False
            
            if result_id:
                cursor.execute("""
                    SELECT 1 
                    FROM result_user 
                    WHERE result_id = %s 
                    AND user_id = %s
                    AND is_active = TRUE
                    LIMIT 1
                """, (result_id, token_user_id))
                
                has_dynamic_analysis = cursor.fetchone() is not None
                logger.info(f"[Request ID: {request_id}] Dynamic analysis check: has_dynamic_analysis={has_dynamic_analysis}")
            
            # Si pas d'analyse dynamique active → Afficher template statique
            if not has_dynamic_analysis:
                logger.info(f"[Request ID: {request_id}] No active dynamic analysis, rendering static template")
                
                try:
                    # Préparer les variables pour le template statique
                    template_vars = {
                        'firstname': access_info['firstname'] if access_info else None,
                        'lastname': access_info['lastname'] if access_info else None,
                        'email': access_info['email'] if access_info else None,
                        'views_left': None,
                        'days_left': (token_data['expires_at'] - datetime.now()).days if token_data['expires_at'] else None,
                        'token': token,
                        'is_guest_view': True,
                        'is_shared': True,
                        'access_type': token_data['access_type'],
                        'user_id': token_user_id,
                        'quiz_id': quiz_id,
                        'expires_at': token_data['expires_at'],
                        'show_expiration_banner': token_data['expires_at'] is not None,
                        'access_url': url_for('quiz_analysis.access_analysis', token=token, _external=True)
                    }
                    
                    # Récupérer le chemin du template statique
                    template_path = USER_STATIC_TEMPLATES[token_user_id]
                    logger.info(f"[Request ID: {request_id}] Rendering static template: {template_path}")
                    
                    cursor.close()
                    
                    # Afficher le template statique et terminer
                    # Rendre le template
                    rendered_template = render_template(template_path, **template_vars)
                    
                    # === TRAITEMENT SELON ACCESS_TYPE ===
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(rendered_template, 'html.parser')
                    
                    if token_data['access_type'] == 'paid':
                        # MODE PAID : Débloquer tout
                        for overlay in soup.find_all(class_='card-lock-overlay'):
                            overlay.decompose()
                        for overlay in soup.find_all(class_='action-lock-overlay'):
                            overlay.decompose()
                        
                        for card in soup.find_all(class_='locked-card'):
                            card['class'] = [c for c in card['class'] if c != 'locked-card']
                        for card in soup.find_all(class_='locked-action'):
                            card['class'] = [c for c in card['class'] if c != 'locked-action']
                        
                        for button in soup.find_all(class_='upgrade-btn'):
                            button['class'] = [c for c in button.get('class', []) if c != 'upgrade-btn']
                            if 'strategy-cta' in button.get('class', []):
                                button['class'].append('strategy-cta-free')
                            button['data-action'] = 'toggle-details' if 'strategy-cta' in button.get('class', []) else 'toggle-action-details'
                            if button.has_attr('data-source'):
                                del button['data-source']
                            button.clear()
                            text_span = soup.new_tag('span', **{'class': 'cta-text'})
                            text_span.string = 'Voir plus'
                            arrow_span = soup.new_tag('span', **{'class': 'cta-arrow'})
                            arrow_span.string = '→'
                            button.append(text_span)
                            button.append(arrow_span)
                        
                        for main_cta in soup.find_all('div', class_='main-unlock-cta'):
                            main_cta.decompose()
                    
                    else:
                        # MODE FREE : Supprimer contenu premium du HTML
                        for card in soup.find_all(class_='strategy-card'):
                            if 'locked-card' in card.get('class', []) or card.get('data-access') == 'premium':
                                details = card.find(class_='strategy-details')
                                if details:
                                    details.decompose()
                        
                        for card in soup.find_all(class_='action-card'):
                            if 'locked-action' in card.get('class', []) or card.get('data-access') == 'premium':
                                details = card.find(class_='action-card-details')
                                if details:
                                    details.decompose()
                    
                    cursor.close()
                    return str(soup)
                    
                except Exception as e:
                    if cursor:
                        cursor.close()
                    logger.error(f"[Request ID: {request_id}] Static template error: {e}", exc_info=True)
                    flash("Erreur lors de l'affichage de l'analyse.", "danger")
                    return redirect(url_for('auth.dashboard'))
            else:
                logger.info(f"[Request ID: {request_id}] Active dynamic analysis found for result_id={result_id}, will render dynamic template")
        
        # Si on arrive ici, c'est une analyse dynamique via token
        # Fermer le cursor du token, un nouveau sera créé plus bas
        if cursor:
            cursor.close()
    
    # ========== MODE 2 : ACCÈS VIA LOGIN (classique) ==========
    else:
        if not current_user.is_authenticated:
            flash("Vous devez être connecté pour accéder à cette page.", "warning")
            return redirect(url_for('auth.login'))
        
        token_user_id = current_user.id
        
        # ✅ NOUVEAU : Si result_id n'est pas fourni, le récupérer depuis la DB
        if not result_id:
            cursor = current_app.mysql.connection.cursor(DictCursor)
            try:
                cursor.execute("""
                    SELECT result_id, result_step_id
                    FROM result_user
                    WHERE user_id = %s AND quiz_id = %s AND is_active = TRUE
                    ORDER BY created_at DESC LIMIT 1
                """, (token_user_id, quiz_id))
                
                active_result = cursor.fetchone()
                if active_result:
                    result_id = active_result['result_id']
                    step_id = active_result['result_step_id']
                    logger.info(f"[Request ID: {request_id}] Auto-retrieved result_id={result_id}, step_id={step_id} for logged-in user")
            finally:
                cursor.close()
        
        # Récupérer les infos utilisateur depuis la DB
        cursor = current_app.mysql.connection.cursor(DictCursor)
        try:
            cursor.execute("""
                SELECT firstname, lastname, email
                FROM users
                WHERE user_id = %s
            """, (token_user_id,))
            
            user_data = cursor.fetchone()
            
            # ✅ Créer access_info avec les données utilisateur
            if user_data:
                access_info = {
                    'firstname': user_data['firstname'],
                    'lastname': user_data['lastname'],
                    'email': user_data['email'],
                    'user_id': token_user_id,
                    'quiz_id': quiz_id,
                    'access_type': 'free',
                    'expires_at': None,
                    'view_count': 0,
                    'max_views': None
                }
                logger.info(f"[Request ID: {request_id}] User data retrieved: {user_data['firstname']} {user_data['lastname']}")
            else:
                # Fallback si user pas trouvé
                access_info = {
                    'firstname': getattr(current_user, 'firstname', 'Invité'),
                    'lastname': getattr(current_user, 'lastname', ''),
                    'email': getattr(current_user, 'email', ''),
                    'user_id': token_user_id,
                    'quiz_id': quiz_id,
                    'access_type': 'free',
                    'expires_at': None,
                    'view_count': 0,
                    'max_views': None
                }
                logger.warning(f"[Request ID: {request_id}] User not found in DB, using fallback")
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Error fetching user data: {e}", exc_info=True)
            access_info = {
                'firstname': 'Invité',
                'lastname': '',
                'email': '',
                'user_id': token_user_id,
                'quiz_id': quiz_id,
                'access_type': 'free',
                'expires_at': None,
                'view_count': 0,
                'max_views': None
            }
        finally:
            cursor.close()

    # ========== VALIDATION : result_id requis SAUF pour analyses statiques ==========
    if not result_id:
        logger.info(f"[Request ID: {request_id}] result_id is NULL - checking for static analysis")
        
        # ✅ Vérifier si l'utilisateur a une analyse statique
        if token_user_id in USER_STATIC_TEMPLATES:
            logger.info(f"[Request ID: {request_id}] Static analysis found for user {token_user_id}")
            
            # Si accès non-token (login direct), on doit quand même afficher le template statique
            if not is_token_access:
                try:
                    template_vars = {
                        'firstname': access_info['firstname'] if access_info else 'Invité',
                        'lastname': access_info['lastname'] if access_info else '',
                        'email': access_info['email'] if access_info else '',
                        'views_left': None,
                        'days_left': None,
                        'token': None,
                        'is_guest_view': False,
                        'is_shared': False,
                        'access_type': 'free',
                        'user_id': token_user_id,
                        'quiz_id': quiz_id,
                        'expires_at': None,
                        'show_expiration_banner': False,
                        'access_url': None
                    }
                    
                    template_path = USER_STATIC_TEMPLATES[token_user_id]
                    
                    logger.info(f"[Request ID: {request_id}] Rendering static template with firstname: {template_vars['firstname']}")
                    
                    return render_template(template_path, **template_vars)
                    
                except Exception as e:
                    logger.error(f"[Request ID: {request_id}] Error loading static template: {e}", exc_info=True)
                    flash("Erreur lors de l'affichage de l'analyse.", "danger")
                    return redirect(url_for('auth.dashboard'))
        
        # Si on arrive ici : pas de result_id ET pas d'analyse statique
        logger.error(f"[Request ID: {request_id}] Missing result_id and no static analysis for user {token_user_id}")
        flash(_("Analyse introuvable"), 'error')
        return redirect(url_for('auth.dashboard')), 404

    # ========== TRAITEMENT DES ANALYSES DYNAMIQUES (générées par LLM) ==========
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Déterminer si l'utilisateur est admin (peut voir toutes les analyses)
        is_admin = current_user.is_authenticated and current_user.is_admin_user
        
        # Construction de la requête SQL selon les permissions
        if is_admin and not is_token_access:
            user_condition = ""
            user_params = []
        else:
            user_condition = "AND qu.user_id = %s"
            user_params = [token_user_id]
        
        # Vérifier que le quiz existe pour cet utilisateur
        cursor.execute(f"""
            SELECT quiz_status, quiz_session_id, user_id
            FROM quiz_user qu
            WHERE qu.quiz_id = %s 
            {user_condition}
            ORDER BY qu.updated_at DESC
            LIMIT 1
        """, (quiz_id, *user_params))
        
        quiz_status = cursor.fetchone()
        if not quiz_status:
            logger.warning(f"[Request ID: {request_id}] Quiz not found")
            flash(_("Ce quiz n'existe pas"), 'error')
            return redirect(url_for('auth.dashboard')), 404

        quiz_user_id = quiz_status['user_id']

        # Construire la requête pour récupérer l'analyse depuis result_user
        if is_admin and not is_token_access:
            user_condition_result = ""
            user_params_result = []
        else:
            user_condition_result = "AND ru.user_id = %s"
            user_params_result = [token_user_id]

        # Requête principale : récupérer le JSON de l'analyse
        query = f"""
            SELECT ru.token_id, ru.result_json, qr.result_step_ranking, ru.user_id
            FROM result_user ru
            JOIN quiz_result qr 
              ON ru.quiz_id = qr.quiz_id
             AND ru.result_step_id = qr.result_step_id
            WHERE ru.quiz_id = %s 
              {user_condition_result}
              AND ru.result_id = %s 
              AND ru.result_step_id = %s
        """
        query_params = [quiz_id, *user_params_result, result_id, step_id]
        
        # Filtrer par generator_type (user/admin) si spécifié
        if generator_type:
            query += " AND ru.generator_type = %s LIMIT 1"
            query_params.append(generator_type)
        else:
            query += " AND ru.is_active = TRUE LIMIT 1"

        logger.debug(f"[Request ID: {request_id}] Query: {query} with params {query_params}")
        cursor.execute(query, tuple(query_params))
        
        result = cursor.fetchone()
        if not result or not result.get('token_id'):
            logger.error(f"[Request ID: {request_id}] No analysis found or no token")
            flash(_("Cette analyse n'existe pas"), 'error')
            return redirect(url_for('auth.dashboard')), 404

        analysis_user_id = result['user_id']
        token_id = result['token_id']
        logger.info(f"[Request ID: {request_id}] Retrieved token: {token_id} for user: {analysis_user_id}")

        # Parser et valider le JSON de l'analyse
        try:
            analysis_data = json.loads(result['result_json'])
            
            # Validation selon le type d'étape
            if step_id == 'career_path':
                if not isinstance(analysis_data, dict):
                    raise ValueError("Invalid career_path structure: not a dict")
                
                required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path structure: missing '{key}'")
                
                if not analysis_data['strategies'].get('items') or len(analysis_data['strategies']['items']) != 3:
                    raise ValueError("Invalid career_path: strategies must have 3 items")
                
                if not analysis_data['actions'].get('items') or len(analysis_data['actions']['items']) != 3:
                    raise ValueError("Invalid career_path: actions must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path structure validated")

            elif step_id == 'career_path_v1':
                if not isinstance(analysis_data, dict):
                    raise ValueError("Invalid career_path_v1 structure: not a dict")
                
                required_keys = ['cover_quote', 'hero_intro', 'voies', 'transformations', 'atouts']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v1 structure: missing '{key}'")
                
                if not analysis_data.get('voies') or len(analysis_data['voies']) != 3:
                    raise ValueError("Invalid career_path_v1: voies must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V1 structure validated")

            elif step_id == 'career_path_v2':
                # Validation spécifique pour V2 (template Nelly)
                required_keys = ['cover_quote', 'intro_text_bloc1', 'intro_text_bloc2', 'transformations', 'options', 'voies']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v2 structure: missing '{key}'")
                
                if not isinstance(analysis_data['voies'], list) or len(analysis_data['voies']) != 3:
                    raise ValueError("Invalid career_path_v2: voies must have 3 items")
                
                if not isinstance(analysis_data['options'], list) or len(analysis_data['options']) != 3:
                    raise ValueError("Invalid career_path_v2: options must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V2 structure validated")

            elif step_id == 'career_path_v3':
                # Validation spécifique pour V2 (template Nelly)
                required_keys = ['cover_quote', 'intro_text_bloc1', 'intro_text_bloc2', 'transformations', 'options', 'voies']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v3 structure: missing '{key}'")
                
                if not isinstance(analysis_data['voies'], list) or len(analysis_data['voies']) != 3:
                    raise ValueError("Invalid career_path_v3: voies must have 3 items")
                
                if not isinstance(analysis_data['options'], list) or len(analysis_data['options']) != 3:
                    raise ValueError("Invalid career_path_v3: options must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V2 structure validated")

            elif step_id == 'career_path_v4':
                required_keys = ['welcome', 'pistes', 'section4']
                for key in required_keys:
                    if key not in analysis_data:
                        raise ValueError(f"Invalid career_path_v4 structure: missing '{key}'")
                
                if not isinstance(analysis_data['pistes'], list) or len(analysis_data['pistes']) != 3:
                    raise ValueError("Invalid career_path_v4: pistes must have 3 items")
                
                logger.info(f"[Request ID: {request_id}] Career path V4 structure validated")

            elif step_id == 'checkup_pro':
                if not isinstance(analysis_data, dict) or 'blocks' not in analysis_data:
                    raise ValueError("Invalid checkup analysis structure")
            
            elif step_id == 'vision_360':
                if not isinstance(analysis_data, dict) or 'superpowers' not in analysis_data:
                    raise ValueError("Invalid vision_360 analysis structure")
            
            else:
                raise ValueError(f"Unknown step_id: {step_id}")
                
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"[Request ID: {request_id}] Invalid analysis data: {str(e)}")
            flash(_("Données d'analyse invalides"), 'error')
            return redirect(url_for('auth.dashboard')), 500

        # Créer le service d'accès aux pistes
        piste_service = PisteAccessService(cursor)
        
        # Récupérer les pistes débloquées pour cet utilisateur
        unlocked_pistes = piste_service.get_unlocked_pistes(analysis_user_id, quiz_id)
        logger.info(f"[Request ID: {request_id}] Pistes débloquées pour user {analysis_user_id}: {unlocked_pistes}")
        
        # Filtrer les données d'analyse pour ne pas envoyer le contenu des pistes verrouillées
        filtered_analysis = piste_service.filter_analysis_data(
            analysis_data=analysis_data,
            unlocked_pistes=unlocked_pistes,
            step_id=step_id
        )
        
        # Traiter les données filtrées pour le template
        processed_data = process_analysis_data(filtered_analysis)
        
        # Récupérer l'étape suivante (si elle existe)
        cursor.execute("""
            SELECT result_step_id
            FROM quiz_result
            WHERE quiz_id = %s AND result_step_ranking > (
                SELECT result_step_ranking
                FROM quiz_result
                WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
            )
            AND is_active = TRUE
            ORDER BY result_step_ranking
            LIMIT 1
        """, (quiz_id, quiz_id, step_id))
        next_step = cursor.fetchone()

        # Marquer le token comme utilisé (seulement si accès connecté, pas token)
        if not is_token_access and not generator_type and int(result.get('result_step_ranking', 0)) == 1:
            analysis_service = QuizAnalysisService(cursor, analysis_user_id, quiz_id)
            try:
                analysis_service.mark_token_as_used(token_id)
                logger.info(f"[Request ID: {request_id}] Token {token_id} marked as used")
            except Exception as e:
                logger.error(f"[Request ID: {request_id}] Error marking token: {str(e)}")

        # Mettre à jour le statut du quiz à "completed"
        analysis_service = QuizAnalysisService(cursor, analysis_user_id, quiz_id)
        analysis_service.update_quiz_status('completed')

        # ✅ CORRECTION : Récupérer le firstname du PROPRIÉTAIRE de l'analyse (analysis_user_id)
        # Si access_info n'existe pas ou ne correspond pas au bon user, on le récupère
        if not access_info or access_info.get('user_id') != analysis_user_id:
            cursor.execute("""
                SELECT firstname, lastname, email
                FROM users
                WHERE user_id = %s
            """, (analysis_user_id,))
            
            owner_data = cursor.fetchone()
            if owner_data:
                display_firstname = owner_data['firstname']
                logger.info(f"[Request ID: {request_id}] Retrieved firstname from owner user_id={analysis_user_id}: {display_firstname}")
            else:
                display_firstname = 'Invité'
                logger.warning(f"[Request ID: {request_id}] Owner user_id={analysis_user_id} not found, using fallback")
        else:
            display_firstname = access_info['firstname']
            logger.info(f"[Request ID: {request_id}] Using firstname from access_info: {display_firstname}")
        
        # Préparer les données pour le template dynamique
        is_admin_view = (
            current_user.is_authenticated 
            and current_user.is_admin_user 
            and not is_token_access 
            and current_user.id != analysis_user_id
        )

        template_data = {
            'next_step': next_step['result_step_id'] if next_step else None,
            'current_step': step_id,
            'quiz_id': quiz_id,
            'skip_loading': skip_loading,
            'request_id': request_id,
            'analysis': processed_data,
            'firstname': display_firstname,
            'is_shared': is_token_access,
            'access_badge': access_badge,
            'user_id': analysis_user_id,
            'unlocked_pistes': unlocked_pistes,
            'access_info': access_info,
            'is_admin_view': is_admin_view
        }
        
        logger.info(f"[Request ID: {request_id}] Template data prepared with firstname: {template_data['firstname']}")

        # Récupérer le template dynamique à utiliser
        cursor.execute("""
            SELECT template_html
            FROM quiz_result
            WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
            LIMIT 1
        """, (quiz_id, step_id))
        tmpl = cursor.fetchone()
        if not tmpl:
            logger.error(f"[Request ID: {request_id}] Template not found")
            flash(_("Template d'analyse introuvable"), 'error')
            return redirect(url_for('auth.dashboard')), 500

        # Rendre le template avec les données
        template_path = f"quiz_analysis/{tmpl['template_html']}"
        response = render_template(template_path, **template_data)
        mysql.connection.commit()
        return response

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[Request ID: {request_id}] Error: {str(e)}", exc_info=True)
        flash(_("Une erreur est survenue"), 'error')
        return redirect(url_for('auth.dashboard')), 500

    finally:
        cursor.close()


@quiz_analysis_bp.route('/retry-analysis', methods=['GET', 'POST'])
@admin_required
def retry_analysis():
    """Route d'administration permettant de relancer une analyse LLM avec logs détaillés."""
    logger.info("Accès à la page de retry d'analyse")
    
    # ==================== INITIALISATION COMPLÈTE ====================
    result_data = None
    error_message = None
    selected_user_id = None
    users = []
    user_quiz_sessions = []
    token_id = ""
    quiz_id = None
    result_id = None
    step_id = None
    is_initial_generation = False
    
    mysql = current_app.mysql
    cursor = None
    
    try:
        cursor = mysql.connection.cursor(DictCursor)
        
        # ==================== CHARGEMENT UTILISATEURS ====================
        try:
            logger.info("Chargement des utilisateurs")
            cursor.execute("SELECT user_id, firstname, email, created_at FROM users ORDER BY created_at DESC")
            users = cursor.fetchall()
        except Exception as e:
            error_message = f"Erreur lors du chargement des utilisateurs : {str(e)}"
            logger.error(error_message)
        
        # ==================== SÉLECTION UTILISATEUR ====================
        if request.method == 'POST':
            selected_user_id = request.form.get('user_id')
        else:
            selected_user_id = request.args.get('user_id')
        
        # ==================== CHARGEMENT QUIZ SESSIONS ====================
        if selected_user_id:
            try:
                selected_user_id = int(selected_user_id)
                logger.info(f"Utilisateur sélectionné: {selected_user_id}")
                
                cursor.execute("""
                    SELECT DISTINCT
                        qu.quiz_id,
                        qu.quiz_session_id,
                        qu.quiz_status,
                        qu.questions_answered_count,
                        qu.created_at as quiz_created_at,
                        qu.updated_at as quiz_updated_at
                    FROM quiz_user qu
                    WHERE qu.user_id = %s 
                    AND qu.quiz_status = 'completed'
                    ORDER BY qu.updated_at DESC
                """, (selected_user_id,))
                
                completed_quizzes = cursor.fetchall()
                
                for quiz in completed_quizzes:
                    cursor.execute("""
                        SELECT 
                            all_results.result_step_id,
                            all_results.quiz_id,
                            qr.result_step_ranking,
                            
                            MAX(CASE WHEN ru.generator_type = 'user' THEN ru.result_id END) AS user_result_id,
                            MAX(CASE WHEN ru.generator_type = 'admin' THEN ru.result_id END) AS admin_result_id,
                            
                            MAX(CASE WHEN ru.generator_type = 'user' THEN ru.created_at END) AS user_created_at,
                            MAX(CASE WHEN ru.generator_type = 'user' THEN ru.updated_at END) AS user_updated_at,
                            MAX(CASE WHEN ru.generator_type = 'user' THEN ru.is_active END) AS user_is_active,
                            
                            MAX(CASE WHEN ru.generator_type = 'admin' THEN ru.created_at END) AS admin_created_at,
                            MAX(CASE WHEN ru.generator_type = 'admin' THEN ru.updated_at END) AS admin_updated_at,
                            MAX(CASE WHEN ru.generator_type = 'admin' THEN ru.is_active END) AS admin_is_active
                            
                        FROM (
                            SELECT DISTINCT result_step_id, quiz_id
                            FROM result_user
                            WHERE user_id = %s 
                            AND quiz_id = %s
                        ) all_results
                        
                        LEFT JOIN result_user ru 
                            ON ru.result_step_id = all_results.result_step_id
                            AND ru.quiz_id = all_results.quiz_id
                            AND ru.user_id = %s
                        
                        JOIN quiz_result qr 
                            ON all_results.quiz_id = qr.quiz_id 
                            AND all_results.result_step_id = qr.result_step_id
                            AND qr.is_active = TRUE
                        
                        GROUP BY all_results.result_step_id, all_results.quiz_id, qr.result_step_ranking
                        ORDER BY qr.result_step_ranking
                    """, (selected_user_id, quiz['quiz_id'], selected_user_id))
                    
                    analyses = cursor.fetchall()
                    
                    user_quiz_sessions.append({
                        'quiz_id': quiz['quiz_id'],
                        'quiz_session_id': quiz['quiz_session_id'],
                        'quiz_status': quiz['quiz_status'],
                        'questions_answered': quiz['questions_answered_count'],
                        'quiz_created_at': quiz['quiz_created_at'],
                        'quiz_updated_at': quiz['quiz_updated_at'],
                        'analyses': analyses if analyses else []
                    })
                    
            except Exception as e:
                error_message = f"Erreur lors du chargement des résultats utilisateur : {str(e)}"
                logger.error(error_message)
        
        # ========== TEMPLATES STATIQUES ==========
        if selected_user_id in USER_STATIC_TEMPLATES:
            has_dynamic_pack_clarte = any(
                s['quiz_id'] == 'pack_clarte' and s.get('analyses') 
                for s in user_quiz_sessions
            )
            
            user_quiz_sessions.append({
                'quiz_id': 'static_analysis',
                'quiz_session_id': None,
                'quiz_status': 'static_template',
                'questions_answered': 0,
                'quiz_created_at': None,
                'quiz_updated_at': None,
                'analyses': [],
                'is_static_only': True,
                'static_template': USER_STATIC_TEMPLATES[selected_user_id],
                'has_dynamic_override': has_dynamic_pack_clarte
            })
            
            logger.info(f"User {selected_user_id} has static template: {USER_STATIC_TEMPLATES[selected_user_id]}")

        # ==================== GESTION TRANSCRIPTION ====================
        if request.method == 'POST' and request.form.get('action') == 'transcribe':
            try:
                transcribe_result = handle_transcription_request(request, cursor)
                if transcribe_result['success']:
                    flash("Transcription réalisée avec succès.", "success")
                else:
                    flash(f"Erreur de transcription : {transcribe_result['error']}", "danger")
            except Exception as e:
                logger.error(f"Erreur lors de la transcription: {str(e)}")
                flash(f"Erreur : {str(e)}", "danger")
        
        # ==================== GESTION REPLAY/GÉNÉRATION ====================
        if request.method == 'POST' and request.form.get('action') == 'replay':
            try:
                user_id = request.form.get('user_id')
                quiz_id = request.form.get('quiz_id')
                result_id = request.form.get('result_id', '').strip()
                step_id = request.form.get('step_id')
                # Les critères de validation personnalisés sont passés au service


                user_validation_criteria = request.form.get('user_validation_criteria', '').strip() or None
                logger.info(f"Validation criteria from form: {len(user_validation_criteria) if user_validation_criteria else 0} chars (ne déclenche PAS le badge custom)")
                
                logger.info(f"Tentative de relance pour user_id={user_id}, quiz_id={quiz_id}, result_id={result_id}, step_id={step_id}")
                
                if not user_id or not quiz_id or not step_id:
                    raise ValueError("Champs obligatoires manquants dans le formulaire")
                
                user_id = int(user_id)
                quiz_id = quiz_id.strip()
                step_id = step_id.strip()
                
                is_initial_generation = not result_id
                
                if is_initial_generation:
                    result_id = str(uuid.uuid4())
                    logger.info(f"[GÉNÉRATION INITIALE ADMIN] Nouveau result_id créé: {result_id}")
                
                analysis_service = QuizAnalysisService(cursor, user_id, quiz_id)
                
                if is_initial_generation:
                    token_id = f"admin_{result_id[:8]}"
                    cursor.execute("""
                        INSERT INTO tokens (token_code, user_id, quiz_id, product_id, item_id, token_type, is_used, used_at)
                        VALUES (%s, %s, %s, NULL, NULL, 'free', TRUE, NOW())
                    """, (token_id, user_id, quiz_id))
                    logger.info(f"[GÉNÉRATION INITIALE ADMIN] Token free créé et marqué utilisé: {token_id}")
                else:
                    cursor.execute("""
                        SELECT token_id FROM result_user 
                        WHERE result_id = %s 
                        AND result_step_id = %s 
                        AND user_id = %s
                        AND generator_type = 'admin'
                    """, (result_id, step_id, user_id))
                    token_row = cursor.fetchone()
                    if not token_row or not token_row.get("token_id"):
                        raise ValueError("Erreur : Aucun token associé trouvé dans result_user pour ce result_id.")
                    token_id = token_row["token_id"]
                    logger.info(f"Token récupéré depuis result_user: {token_id}")
                
                system_prompt = request.form.get('user_system_prompt', '').strip()
                prompt_instruction = request.form.get('user_instructions', '').strip()
                prompt_knowledge = request.form.get('user_knowledge', '').strip()
                
                user_responses = analysis_service.prepare_prompt_data()
                
                reconstructed_human_prompt = analysis_service._build_human_prompt(
                    prompt_data=user_responses,
                    prompt_instruction=prompt_instruction,
                    prompt_knowledge=prompt_knowledge
                )
                
                prompt_data = PromptData(
                    human_prompt=reconstructed_human_prompt,
                    system_prompt=system_prompt,
                    session_data={'quiz_id': quiz_id, 'user_id': user_id}
                )
                
                # ✅ NOUVEAU : Passer les critères de validation personnalisés
                user_human_prompt = request.form.get('user_human_prompt', '').strip()

                result_json_data, prompt_id, timings = analysis_service._generate_analysis(
                    result_id=result_id,
                    step_id=step_id,
                    request_id=f"{'initial' if is_initial_generation else 'retry'}_{result_id}_{step_id}",
                    prompt_instruction=prompt_instruction,
                    prompt_knowledge=prompt_knowledge,
                    custom_validation_criteria=user_validation_criteria if user_validation_criteria else None,
                    custom_system_prompt=system_prompt if system_prompt else None,
                    custom_human_prompt=user_human_prompt if user_human_prompt else None
                )

                current_is_active = False
                if not is_initial_generation:
                    cursor.execute("""
                        SELECT is_active FROM result_user
                        WHERE result_id = %s 
                        AND result_step_id = %s 
                        AND generator_type = 'admin'
                    """, (result_id, step_id))
                    result = cursor.fetchone()
                    if result:
                        current_is_active = result['is_active']

                analysis_service._store_analysis_result(
                    result_id=result_id,
                    step_id=step_id,
                    result_json=result_json_data,
                    token_id=token_id,
                    prompt_id=prompt_id,
                    is_active=current_is_active,
                    generator_type='admin',
                    timings=timings
                )

                mysql.connection.commit()
                logger.info(f"Transaction committed successfully")

                success_message = "Analyse LLM générée avec succès." if is_initial_generation else "Analyse LLM relancée avec succès."
                flash(success_message, "success")

                return jsonify({
                    'success': True,
                    'message': success_message,
                    'result_id': result_id,
                    'step_id': step_id,
                    'is_initial': is_initial_generation
                }), 200
                
            except Exception as e:
                mysql.connection.rollback()
                error_message = str(e)
                error_type = type(e).__name__
                
                logger.error(f"Erreur lors de la {'génération' if is_initial_generation else 'relance'} d'analyse : {error_message}", exc_info=True)
                
                if "too many values to unpack" in error_message:
                    user_message = "Erreur technique : Format de réponse inattendu. Veuillez réessayer."
                elif "JSONDecodeError" in error_type:
                    user_message = "Erreur : L'IA a généré une réponse invalide. Veuillez relancer l'analyse."
                elif "ValueError" in error_type and "Invalid JSON" in error_message:
                    user_message = "Erreur : Réponse IA mal formatée. Veuillez réessayer avec des prompts plus clairs."
                elif "No valid token" in error_message:
                    user_message = "Erreur : Aucun token valide disponible. Veuillez créer un nouveau token."
                else:
                    user_message = f"Erreur : {error_message}"
                
                flash(user_message, "danger")
                
                return jsonify({
                    'success': False,
                    'error': user_message,
                    'error_type': error_type,
                    'error_details': error_message
                }), 500
    
    except Exception as e:
        logger.error(f"Erreur inattendue dans retry_analysis: {str(e)}", exc_info=True)
        error_message = f"Erreur inattendue : {str(e)}"
    
    finally:
        if cursor:
            cursor.close()
    
    return render_template(
        "admin/retry_analysis.html",
        users=users,
        selected_user_id=selected_user_id,
        user_quiz_sessions=user_quiz_sessions,
        result_data=result_data,
        error_message=error_message,
        generated_quiz_id=quiz_id if quiz_id else '',
        generated_result_id=result_id if result_id else '',
        generated_step_id=step_id if step_id else '',
        token_id=token_id
    )

@quiz_analysis_bp.route('/get_prompt/<string:result_id>/<string:step_id>', methods=['GET'])
@login_required
def get_prompt(result_id, step_id):
    """
    Récupère le prompt stocké pour un Result ID et Step ID donnés.
    Inclut les validation_criteria depuis quiz_result.
    """
    request_id = generate_request_id()
    generator_type = request.args.get('generator_type', None)
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer le user_id et quiz_id de l'analyse
        cursor.execute("""
            SELECT user_id, quiz_id 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s
            LIMIT 1
        """, (result_id, step_id))
        
        result_user = cursor.fetchone()
        if not result_user:
            logger.warning(f"[Request ID: {request_id}] No result found for result_id: {result_id}")
            return jsonify({'error': 'Analyse introuvable'}), 404
        
        analysis_user_id = result_user['user_id']
        quiz_id = result_user['quiz_id']
        
        # Vérifier les permissions
        is_admin = current_user.is_admin_user
        if not is_admin and analysis_user_id != current_user.id:
            logger.warning(f"[Request ID: {request_id}] Access denied for user {current_user.id}")
            return jsonify({'error': 'Accès non autorisé'}), 403
        
        # Construction de la requête SQL avec le filtre generator_type
        query = """
            SELECT p.prompt
            FROM prompt_user p
            JOIN result_user ru ON ru.prompt_id = p.prompt_id
            WHERE ru.result_id = %s 
            AND ru.result_step_id = %s 
            AND ru.user_id = %s
        """
        params = [result_id, step_id, analysis_user_id]

        # Ajouter le filtre generator_type si fourni
        if generator_type:
            query += " AND ru.generator_type = %s"
            params.append(generator_type)
        else:
            query += """
            ORDER BY 
                CASE WHEN ru.is_active = TRUE THEN 0 ELSE 1 END,
                CASE WHEN ru.generator_type = 'admin' THEN 0 ELSE 1 END,
                p.created_at DESC
            """
            
        query += " LIMIT 1"
        
        logger.info(f"[Request ID: {request_id}] Executing query with params: {params}")
        cursor.execute(query, tuple(params))
        
        result = cursor.fetchone()
        
        # Préparer la réponse de base
        formatted_prompt = {
            "system_prompt": '',
            "human_prompt": '',
            "instructions": '',
            "knowledge": '',
            "validation_criteria": ''
        }
        
        # Parser le prompt si trouvé
        if result:
            try:
                prompt_data = json.loads(result['prompt'])
                formatted_prompt["system_prompt"] = prompt_data.get('prompt', {}).get('system', '')
                formatted_prompt["human_prompt"] = prompt_data.get('prompt', {}).get('human', '')
                formatted_prompt["instructions"] = prompt_data.get('system_context', {}).get('instructions', '')
                formatted_prompt["knowledge"] = prompt_data.get('system_context', {}).get('knowledge', '')
            except Exception as e:
                logger.warning(f"[Request ID: {request_id}] Error parsing prompt: {e}")
        
        # ✅ NOUVEAU : Récupérer les validation_criteria depuis quiz_result
        cursor.execute("""
            SELECT validation_criteria
            FROM quiz_result 
            WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
        """, (quiz_id, step_id))
        
        qr_result = cursor.fetchone()
        if qr_result and qr_result.get('validation_criteria'):
            formatted_prompt["validation_criteria"] = qr_result['validation_criteria']
            logger.info(f"[Request ID: {request_id}] Validation criteria loaded: {len(formatted_prompt['validation_criteria'])} chars")
        
        return jsonify(formatted_prompt)
        
    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Erreur lors de la récupération du prompt: {str(e)}", exc_info=True)
        return jsonify({'error': 'Erreur serveur'}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/set-official', methods=['POST'])
@admin_required
def set_official_analysis():
    """Active une analyse admin et désactive l'analyse user UNIQUEMENT pour la step concernée."""
    data = request.json
    result_id = data.get("result_id")
    step_id = data.get("step_id")

    if not result_id or not step_id:
        return jsonify({"error": "Missing result_id or step_id"}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Récupérer le user_id et quiz_id depuis l'analyse admin
        cursor.execute("""
            SELECT user_id, quiz_id
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'admin'
        """, (result_id, step_id))

        admin_row = cursor.fetchone()
        if not admin_row:
            return jsonify({"error": "Admin analysis not found"}), 404

        user_id = admin_row['user_id']
        quiz_id = admin_row['quiz_id']

        # Désactiver TOUTES les analyses user pour ce user/quiz/step (quel que soit le result_id)
        cursor.execute("""
            UPDATE result_user 
            SET is_active = FALSE
            WHERE user_id = %s
            AND quiz_id = %s
            AND result_step_id = %s
            AND generator_type = 'user'
        """, (user_id, quiz_id, step_id))

        # Activer l'analyse admin
        cursor.execute("""
            UPDATE result_user 
            SET is_active = TRUE
            WHERE result_id = %s 
            AND result_step_id = %s
            AND generator_type = 'admin'
        """, (result_id, step_id))

        mysql.connection.commit()
        return jsonify({"success": True})

    except Exception as e:
        mysql.connection.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()

@quiz_analysis_bp.route('/send-notification-email', methods=['POST'])
@admin_required
def send_notification_email():
    """
    Envoie un email de notification à l'utilisateur que son analyse est prête.
    Enregistre l'envoi pour éviter les doublons.
    """
    request_id = generate_request_id()
    data = request.json
    result_id = data.get("result_id")
    step_id = data.get("step_id")
    user_id = data.get("user_id")
    quiz_id = data.get("quiz_id")
    
    if not all([result_id, step_id, user_id, quiz_id]):
        return jsonify({"error": "Missing parameters"}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # 1. Vérifier que l'analyse existe et est active
        cursor.execute("""
            SELECT ru.is_active, ru.generator_type
            FROM result_user ru
            WHERE ru.result_id = %s 
            AND ru.result_step_id = %s
            AND ru.user_id = %s
            AND ru.is_active = TRUE
        """, (result_id, step_id, user_id))
        
        analysis = cursor.fetchone()
        if not analysis:
            return jsonify({"error": "Analysis not found or not active"}), 404
        
        # 2. Vérifier si un email a déjà été envoyé pour cette analyse
        cursor.execute("""
            SELECT sent_at 
            FROM analysis_notification_emails 
            WHERE result_id = %s 
            AND step_id = %s 
            AND user_id = %s
            ORDER BY sent_at DESC 
            LIMIT 1
        """, (result_id, step_id, user_id))
        
        previous_email = cursor.fetchone()
        if previous_email:
            return jsonify({
                "error": f"Email déjà envoyé le {previous_email['sent_at'].strftime('%d/%m/%Y à %H:%M')}",
                "already_sent": True,
                "sent_at": previous_email['sent_at'].isoformat()
            }), 409  # Conflict
        
        # 3. Récupérer les infos utilisateur
        cursor.execute("""
            SELECT firstname, lastname, email
            FROM users
            WHERE user_id = %s
        """, (user_id,))
        
        user = cursor.fetchone()
        if not user or not user['email']:
            return jsonify({"error": "User not found or no email"}), 404
        
        # 4. Générer l'URL de l'analyse
        analysis_url = url_for('dashboard.index', _external=True)
        
        # 5. Envoyer l'email
        from services.email_service import send_analysis_ready_email
        
        email_sent = send_analysis_ready_email(
            user_email=user['email'],
            firstname=user['firstname'] or 'Utilisateur',
            analysis_url=analysis_url
        )
        
        if not email_sent:
            return jsonify({"error": "Failed to send email"}), 500
        
        # 6. Enregistrer l'envoi
        cursor.execute("""
            INSERT INTO analysis_notification_emails 
            (result_id, step_id, user_id, quiz_id, sent_to_email, sent_by_admin_id, sent_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (result_id, step_id, user_id, quiz_id, user['email'], current_user.id))
        
        mysql.connection.commit()
        
        logger.info(f"[{request_id}] Email notification sent for analysis {result_id}/{step_id} to user {user_id}")
        
        return jsonify({
            "success": True,
            "message": f"Email envoyé à {user['email']}",
            "sent_at": datetime.now().isoformat()
        })
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[{request_id}] Error sending notification email: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/set-official-user', methods=['POST'])
@admin_required
def set_official_user():
    """Active l'analyse user et désactive l'analyse admin pour une step spécifique."""
    data = request.json
    result_id = data.get("result_id")
    step_id = data.get("step_id")

    if not result_id or not step_id:
        return jsonify({"error": "Missing result_id or step_id"}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    try:
        # Récupérer le user_id et quiz_id depuis l'analyse user
        cursor.execute("""
            SELECT user_id, quiz_id
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'user'
        """, (result_id, step_id))

        user_row = cursor.fetchone()
        if not user_row:
            return jsonify({"error": "User analysis not found"}), 404

        user_id = user_row['user_id']
        quiz_id = user_row['quiz_id']

        # Désactiver TOUTES les analyses admin pour ce user/quiz/step
        cursor.execute("""
            UPDATE result_user 
            SET is_active = FALSE
            WHERE user_id = %s
            AND quiz_id = %s
            AND result_step_id = %s
            AND generator_type = 'admin'
        """, (user_id, quiz_id, step_id))

        # Activer l'analyse user
        cursor.execute("""
            UPDATE result_user 
            SET is_active = TRUE
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'user'
        """, (result_id, step_id))

        mysql.connection.commit()
        return jsonify({"success": True})
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()

@quiz_analysis_bp.route('/view-user-responses/<string:quiz_id>/<int:user_id>')
@admin_required
def view_user_responses(quiz_id: str, user_id: int):
    """Affiche les réponses brutes d'un utilisateur pour un quiz donné."""
    request_id = generate_request_id()
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que le quiz existe et est complété
        cursor.execute("""
            SELECT quiz_session_id, quiz_status, questions_answered_count
            FROM quiz_user
            WHERE quiz_id = %s AND user_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (quiz_id, user_id))
        
        quiz_session = cursor.fetchone()
        if not quiz_session:
            flash("Session de quiz non trouvée", "error")
            return redirect(url_for('quiz_analysis.retry_analysis'))
        
        # Récupérer les réponses via le service
        analysis_service = QuizAnalysisService(cursor, user_id, quiz_id)
        prompt_data = analysis_service.prepare_prompt_data()
        
        # Formater les données pour l'affichage
        formatted_responses = {
            'quiz_id': quiz_id,
            'user_id': user_id,
            'quiz_status': quiz_session['quiz_status'],
            'questions_answered': quiz_session['questions_answered_count'],
            'responses': []
        }
        
        # Parser le prompt_data pour extraire les questions/réponses
        if hasattr(prompt_data, 'session_data'):
            session_data = prompt_data.session_data
            for question_key, answer_data in session_data.items():
                formatted_responses['responses'].append({
                    'question_id': question_key,
                    'question_text': answer_data.get('question_text', 'N/A'),
                    'answer': answer_data.get('answer', 'N/A'),
                    'answer_label': answer_data.get('answer_label', 'N/A')
                })
        
        return render_template(
            'admin/view_user_responses.html',
            responses=formatted_responses
        )
        
    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Error viewing responses: {str(e)}", exc_info=True)
        flash(f"Erreur: {str(e)}", "error")
        return redirect(url_for('quiz_analysis.retry_analysis'))
    
    finally:
        cursor.close()

@quiz_analysis_bp.route('/get-quiz-responses/<string:quiz_id>/<int:user_id>', methods=['GET'])
@admin_required
def get_quiz_responses(quiz_id: str, user_id: int):
    """Récupère les réponses d'un utilisateur pour un quiz donné en format JSON avec support audio."""
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Fetching responses for quiz: {quiz_id}, user: {user_id}")

    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que le quiz existe et est complété
        cursor.execute("""
            SELECT quiz_session_id, quiz_status, questions_answered_count
            FROM quiz_user
            WHERE quiz_id = %s AND user_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (quiz_id, user_id))
        
        quiz_session = cursor.fetchone()
        if not quiz_session:
            logger.warning(f"[Request ID: {request_id}] Quiz session not found")
            return jsonify({'error': 'Session de quiz non trouvée'}), 404
        
        quiz_session_id = quiz_session['quiz_session_id']
        
        # Récupérer les réponses avec les détails des questions et les transcriptions audio
        cursor.execute("""
            SELECT 
                au.question_id,
                au.answer_value,
                au.answer_text,
                qc.question as question_text,
                qc.question_type,
                at.transcription,
                at.id as transcription_id,
                at.confidence_score
            FROM answer_user au
            JOIN questions_catalog qc ON au.question_id = qc.question_id
            LEFT JOIN audio_transcriptions at ON (
                au.quiz_session_id = at.quiz_session_id 
                AND au.question_id = at.question_id
            )
            WHERE au.quiz_session_id = %s
            ORDER BY au.question_id
        """, (quiz_session_id,))
        
        raw_responses = cursor.fetchall()
        
        logger.info(f"[Request ID: {request_id}] Retrieved {len(raw_responses)} raw responses")
        
        # Formater les réponses pour l'affichage
        responses = []
        for idx, resp in enumerate(raw_responses, 1):
            try:
                answer_value = json.loads(resp['answer_value']) if resp['answer_value'] else []
            except (json.JSONDecodeError, TypeError):
                answer_value = []
            
            # Déterminer le type de réponse
            is_audio_response = (
                isinstance(answer_value, list) 
                and len(answer_value) > 0 
                and answer_value[0] == '[AUDIO_RESPONSE]'
            )
            
            # Pour les réponses non-audio, créer une réponse formatée depuis answer_text
            if not is_audio_response:
                # Si ce n'est pas une réponse audio, utiliser answer_text comme réponse principale
                formatted_answer = resp['answer_text'] if resp['answer_text'] else 'N/A'
            else:
                formatted_answer = 'Réponse audio'
            
            response_data = {
                'question_id': resp['question_id'],
                'question_text': resp['question_text'],
                'question_type': resp['question_type'],
                'answer_value': answer_value,
                'answer_text': formatted_answer,  # Utiliser le texte formaté
                'is_audio_response': is_audio_response,
                'audio_file_path': resp['answer_text'] if is_audio_response else None,
                'has_transcription': bool(resp['transcription']),
                'transcription': resp['transcription'],
                'transcription_id': resp['transcription_id'],
                'confidence_score': float(resp['confidence_score']) if resp['confidence_score'] else None,
                'quiz_session_id': quiz_session_id
            }
            
            responses.append(response_data)
        
        logger.info(f"[Request ID: {request_id}] Formatted {len(responses)} responses with audio support")
        
        result = {
            'quiz_id': quiz_id,
            'user_id': user_id,
            'quiz_session_id': quiz_session_id,
            'quiz_status': quiz_session['quiz_status'],
            'questions_answered': quiz_session['questions_answered_count'],
            'responses': responses
        }
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Error fetching responses: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/transcribe-audio', methods=['POST'])
@admin_required
def transcribe_audio():
    """Transcrit un fichier audio et sauvegarde le résultat"""
    try:
        data = request.json
        quiz_session_id = data.get('quiz_session_id')
        question_id = data.get('question_id')
        user_id = data.get('user_id') 
        quiz_id = data.get('quiz_id')
        audio_file_path = data.get('audio_file_path')
        
        if not all([quiz_session_id, question_id, user_id, quiz_id, audio_file_path]):
            return jsonify({'error': 'Paramètres manquants'}), 400
            
        cursor = current_app.mysql.connection.cursor(DictCursor)
        
        try:
            # Vérifier si une transcription existe déjà
            cursor.execute("""
                SELECT id, transcription, transcription_status FROM audio_transcriptions 
                WHERE quiz_session_id = %s AND question_id = %s
            """, (quiz_session_id, question_id))
            
            existing = cursor.fetchone()
            if existing:
                if existing['transcription_status'] == 'completed':
                    return jsonify({
                        'success': True, 
                        'transcription': existing['transcription'],
                        'message': 'Transcription déjà existante'
                    })
                elif existing['transcription_status'] == 'error':
                    # Supprimer l'ancienne erreur et réessayer
                    cursor.execute("""
                        DELETE FROM audio_transcriptions 
                        WHERE quiz_session_id = %s AND question_id = %s
                    """, (quiz_session_id, question_id))
            
            # Utiliser le service AudioService pour transcrire
            from services.audio_service import AudioService
            
            transcription_result = AudioService.transcribe_quiz_audio_from_gcs(audio_file_path)
            
            if transcription_result['success']:
                transcription_text = transcription_result['transcript']
                confidence_score = 0.95  # Whisper ne fournit pas de score de confiance
                
                # Sauvegarder la transcription
                cursor.execute("""
                    INSERT INTO audio_transcriptions 
                    (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                     transcription, confidence_score, transcription_status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed')
                """, (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                      transcription_text, confidence_score))
                
                current_app.mysql.connection.commit()
                
                return jsonify({
                    'success': True,
                    'transcription': transcription_text,
                    'confidence_score': confidence_score
                })
            else:
                error_message = transcription_result['error']
                
                # Sauvegarder l'erreur seulement si ce n'est pas un rate limit temporaire
                if "Limite de taux" not in error_message:
                    cursor.execute("""
                        INSERT INTO audio_transcriptions 
                        (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                         transcription, transcription_status, error_message)
                        VALUES (%s, %s, %s, %s, %s, %s, 'error', %s)
                    """, (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                          '', error_message))
                    
                    current_app.mysql.connection.commit()
                
                return jsonify({
                    'success': False,
                    'error': error_message
                })
            
        finally:
            cursor.close()
            
    except Exception as e:
        logger.error(f"Erreur transcription audio: {str(e)}")
        return jsonify({'error': str(e)}), 500



@quiz_analysis_bp.route('/get-audio-url', methods=['POST'])
@admin_required
def get_audio_url():
    """Génère une URL signée pour écouter un fichier audio"""
    try:
        data = request.json
        audio_file_path = data.get('audio_file_path')
        
        if not audio_file_path:
            return jsonify({'error': 'Chemin audio manquant'}), 400
            
        # Extraire le nom du fichier depuis le chemin GCS
        if audio_file_path.startswith('gs://'):
            # Exemple: gs://tilto_quiz_audios_dev/pack_clarte/user_28/q43_20250917_145533_66318f43.webm
            # On veut : pack_clarte/user_28/q43_20250917_145533_66318f43.webm
            filename = audio_file_path.replace('gs://tilto_quiz_audios_dev/', '').replace('gs://tilto_quiz_audios_prod/', '')
        else:
            filename = audio_file_path
        
        # Utiliser le service AudioService existant
        from services.audio_service import AudioService
        
        signed_url = AudioService.generate_signed_url_for_quiz_audio(filename, duration_minutes=10)
        
        if signed_url:
            return jsonify({
                'success': True,
                'signed_url': signed_url,
                'expires_in': 10  # minutes
            })
        else:
            return jsonify({'error': 'Impossible de générer l\'URL signée'}), 500
            
    except Exception as e:
        logger.error(f"Erreur génération URL audio: {str(e)}")
        return jsonify({'error': str(e)}), 500

@quiz_analysis_bp.route('/access/<string:token>')
def access_analysis(token):
    """
    Point d'entrée unique - redirige vers la vue appropriée selon access_type
    """
    request_id = generate_request_id()
    logger.info(f"[{request_id}] Accès analyse avec token: {token[:20]}...")
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer les infos du token
        access_info = AnalysisAccessModel.get_by_token(cursor, token)
        
        if not access_info:
            logger.warning(f"[{request_id}] Token invalide ou expiré")
            flash("Ce lien a expiré ou n'est plus valide", 'error')
            return redirect(url_for('auth.home'))
        
        # Rediriger selon access_type
        logger.info(f"[{request_id}] Redirection vers view_analysis avec token")
        return redirect(url_for('quiz_analysis.view_analysis',
                            quiz_id=access_info['quiz_id'],
                            token=token))
        
    except Exception as e:
        logger.error(f"[{request_id}] Erreur: {e}", exc_info=True)
        flash("Une erreur est survenue", 'error')
        return redirect(url_for('auth.home'))
        
    finally:
        cursor.close()


@quiz_analysis_bp.route('/admin/check-access-token/<string:quiz_id>/<int:user_id>', methods=['GET'])
@admin_required
def check_access_token(quiz_id: str, user_id: int):
    """
    Vérifie si un token d'accès existe pour ce quiz/user
    Retourne les infos du token ou permet d'en créer un
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Chercher directement le token (pas besoin de result_id)
        cursor.execute("""
            SELECT token, access_type, expires_at, max_views, view_count, 
                   created_at, is_revoked, result_id
            FROM analysis_access_tokens
            WHERE quiz_id = %s 
            AND user_id = %s 
            AND is_revoked = FALSE
            ORDER BY created_at DESC
            LIMIT 1
        """, (quiz_id, user_id))
        
        token_data = cursor.fetchone()
        
        if token_data:
            return jsonify({
                'exists': True,
                'token': token_data['token'],
                'access_type': token_data['access_type'],
                'expires_at': token_data['expires_at'].isoformat() if token_data['expires_at'] else None,
                'max_views': token_data['max_views'],
                'view_count': token_data['view_count'],
                'created_at': token_data['created_at'].isoformat(),
                'result_id': token_data['result_id'],
                'access_url': url_for('quiz_analysis.access_analysis', token=token_data['token'], _external=True)
            })
        else:
            # Pas de token trouvé
            cursor.execute("""
                SELECT result_id 
                FROM result_user 
                WHERE quiz_id = %s AND user_id = %s AND is_active = TRUE
                ORDER BY created_at DESC LIMIT 1
            """, (quiz_id, user_id))
            
            result = cursor.fetchone()
            
            # ✅ Si pas de result_id ET que c'est une analyse statique, générer un UUID
            if not result and user_id in USER_STATIC_TEMPLATES:
                result_id = f"static_{user_id}_{quiz_id}"  # result_id fictif
            else:
                result_id = result['result_id'] if result else None
            
            return jsonify({
                'exists': False,
                'quiz_id': quiz_id,
                'user_id': user_id,
                'result_id': result_id
            })
            
    except Exception as e:
        logger.error(f"Erreur check token: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@quiz_analysis_bp.route('/admin/create-access-token', methods=['POST'])
@admin_required
def create_access_token_route():
    """
    Crée un nouveau token d'accès pour un user/quiz
    """
    data = request.json
    quiz_id = data.get('quiz_id')
    user_id = data.get('user_id')
    result_id = data.get('result_id')
    
    if not all([quiz_id, user_id, result_id]):
        return jsonify({'error': 'Paramètres manquants'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Créer le token
        token = AnalysisAccessModel.create_access_token(
            cursor, 
            user_id, 
            quiz_id, 
            result_id,
            access_type='free'  # Par défaut en free
        )
        
        current_app.mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'token': token,
            'access_url': url_for('quiz_analysis.access_analysis', token=token, _external=True)
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Erreur création token: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@quiz_analysis_bp.route('/admin/upgrade-token', methods=['POST'])
@admin_required
def upgrade_token_route():
    """
    Upgrade un token free vers paid (accès illimité)
    """
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Token manquant'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        success = AnalysisAccessModel.upgrade_to_paid(cursor, token)
        
        if success:
            current_app.mysql.connection.commit()
            return jsonify({
                'success': True,
                'message': 'Token upgradé en version payante (accès illimité)'
            })
        else:
            return jsonify({'error': 'Token non trouvé ou déjà payant'}), 404
            
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Erreur upgrade token: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()
    
@quiz_analysis_bp.route('/admin/reset-token-expiration', methods=['POST'])
@admin_required
def reset_token_expiration():
    """
    Réinitialise la date d'expiration d'un token (ajoute 7 jours à partir d'aujourd'hui)
    """
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Token manquant'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que le token existe
        cursor.execute("""
            SELECT access_type, expires_at 
            FROM analysis_access_tokens 
            WHERE token = %s AND is_revoked = FALSE
        """, (token,))
        
        token_data = cursor.fetchone()
        
        if not token_data:
            return jsonify({'error': 'Token non trouvé'}), 404
        
        # Calculer la nouvelle date d'expiration (7 jours à partir d'aujourd'hui)
        from datetime import datetime, timedelta
        new_expiration = datetime.now() + timedelta(days=7)
        
        # Mettre à jour la date d'expiration
        cursor.execute("""
            UPDATE analysis_access_tokens 
            SET expires_at = %s, updated_at = NOW()
            WHERE token = %s
        """, (new_expiration, token))
        
        current_app.mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': 'Date d\'expiration réinitialisée (+7 jours)',
            'new_expiration': new_expiration.isoformat()
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Erreur reset expiration token: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/downgrade-token', methods=['POST'])
@admin_required
def downgrade_token_route():
    """
    Downgrade un token paid vers free (accès limité 7 jours)
    """
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Token manquant'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que le token existe et est bien paid
        cursor.execute("""
            SELECT access_type 
            FROM analysis_access_tokens 
            WHERE token = %s AND is_revoked = FALSE
        """, (token,))
        
        token_data = cursor.fetchone()
        
        if not token_data:
            return jsonify({'error': 'Token non trouvé'}), 404
        
        if token_data['access_type'] != 'paid':
            return jsonify({'error': 'Ce token n\'est pas en version paid'}), 400
        
        # Calculer la date d'expiration (7 jours à partir d'aujourd'hui)
        from datetime import datetime, timedelta
        new_expiration = datetime.now() + timedelta(days=7)
        
        # Downgrade le token
        cursor.execute("""
            UPDATE analysis_access_tokens 
            SET access_type = 'free',
                expires_at = %s,
                updated_at = NOW()
            WHERE token = %s
        """, (new_expiration, token))
        
        current_app.mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'message': 'Token repassé en version FREE avec succès',
            'new_expiration': new_expiration.isoformat()
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Erreur downgrade token: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-available-steps/<string:quiz_id>', methods=['GET'])
@admin_required
def get_available_steps(quiz_id: str):
    """Récupère les étapes configurées pour un quiz"""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                result_step_id, 
                result_step_ranking,
                prompt_instruction,
                template_html
            FROM quiz_result
            WHERE quiz_id = %s 
            AND is_active = TRUE
            ORDER BY result_step_ranking
        """, (quiz_id,))
        
        steps = cursor.fetchall()
        
        if not steps:
            return jsonify({'error': 'Aucune étape configurée pour ce quiz'}), 404
        
        return jsonify({
            'steps': [
                {
                    'result_step_id': step['result_step_id'],
                    'result_step_ranking': step['result_step_ranking'],
                    'prompt_instruction': step['prompt_instruction'],
                    'template_html': step['template_html']
                }
                for step in steps
            ]
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération étapes: {e}")
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-default-prompts/<string:quiz_id>/<string:step_id>', methods=['GET'])
@admin_required
def get_default_prompts(quiz_id, step_id):
    """Récupère les prompts par défaut pour une étape de quiz, incluant validation_criteria"""
    request_id = generate_request_id()
    logger.info(f"[{request_id}] Getting default prompts for quiz={quiz_id}, step={step_id}")
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT prompt_system, prompt_instruction, prompt_knowledge, validation_criteria
            FROM quiz_result 
            WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
        """, (quiz_id, step_id))
        
        result = cursor.fetchone()
        
        if not result:
            logger.warning(f"[{request_id}] No config found for {quiz_id}/{step_id}")
            return jsonify({
                'error': f'Aucune configuration trouvée pour {quiz_id}/{step_id}'
            }), 404
        
        logger.info(f"[{request_id}] Config found, validation_criteria length: {len(result.get('validation_criteria') or '')}")
        
        return jsonify({
            'system_prompt': result.get('prompt_system') or '',
            'instructions': result.get('prompt_instruction') or '',
            'knowledge': result.get('prompt_knowledge') or '',
            'validation_criteria': result.get('validation_criteria') or ''
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Error getting default prompts: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/delete-admin-analysis', methods=['POST'])
@admin_required
def delete_admin_analysis():
    """Supprime définitivement une analyse admin."""
    data = request.json
    result_id = data.get("result_id")
    step_id = data.get("step_id")

    if not result_id or not step_id:
        return jsonify({"error": "Missing result_id or step_id"}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que l'analyse admin existe
        cursor.execute("""
            SELECT 1 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'admin'
        """, (result_id, step_id))

        if not cursor.fetchone():
            return jsonify({"error": "Admin analysis not found"}), 404

        # Récupérer le prompt_id avant suppression
        cursor.execute("""
            SELECT prompt_id 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'admin'
        """, (result_id, step_id))
        
        prompt_result = cursor.fetchone()
        prompt_id = prompt_result['prompt_id'] if prompt_result else None

        # Supprimer l'analyse admin
        cursor.execute("""
            DELETE FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'admin'
        """, (result_id, step_id))

        # Supprimer le prompt associé si personne d'autre ne l'utilise
        if prompt_id:
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM result_user 
                WHERE prompt_id = %s
            """, (prompt_id,))
            
            count_result = cursor.fetchone()
            if count_result and count_result['count'] == 0:
                cursor.execute("""
                    DELETE FROM prompt_user 
                    WHERE prompt_id = %s
                """, (prompt_id,))
                logger.info(f"Deleted orphaned prompt {prompt_id}")

        mysql.connection.commit()
        logger.info(f"Admin analysis deleted: result_id={result_id}, step_id={step_id}")
        return jsonify({"success": True})

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error deleting admin analysis: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

    finally:
        cursor.close()

@quiz_analysis_bp.route('/get-json/<string:result_id>/<string:step_id>', methods=['GET'])
@admin_required
def get_json(result_id, step_id):
    """Récupère le JSON de l'analyse pour édition."""
    generator_type = request.args.get('generator_type', 'admin')
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT result_json 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s  # ✅ MODIF : Paramètre dynamique
            ORDER BY created_at DESC
            LIMIT 1
        """, (result_id, step_id, generator_type))  
        
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'error': 'Analyse introuvable'}), 404
        
        result_json = json.loads(result['result_json'])
        
        return jsonify({
            'success': True,
            'result_json': result_json
        })
        
    except Exception as e:
        logger.error(f"Error fetching JSON: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@quiz_analysis_bp.route('/update-json', methods=['POST'])
@admin_required
def update_json():
    """Sauvegarde les modifications du JSON de l'analyse."""
    data = request.json
    result_id = data.get('result_id')
    step_id = data.get('step_id')
    result_json = data.get('result_json')
    generator_type = data.get('generator_type', 'admin') 
    
    if not all([result_id, step_id, result_json]):
        return jsonify({'error': 'Paramètres manquants'}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que l'analyse existe
        cursor.execute("""
            SELECT 1 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s 
        """, (result_id, step_id, generator_type)) 
        
        if not cursor.fetchone():
            return jsonify({'error': 'Analyse introuvable'}), 404
        
        # Validation selon le type d'étape
        if step_id == 'career_path' or step_id == 'career_path_v1':
            required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
            for key in required_keys:
                if key not in result_json:
                    return jsonify({'error': f"Clé manquante dans le JSON : {key}"}), 400
        
        # Mettre à jour le JSON
        cursor.execute("""
            UPDATE result_user 
            SET result_json = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s  
        """, (json.dumps(result_json), result_id, step_id, generator_type))  
        
        mysql.connection.commit()
        logger.info(f"JSON updated for result_id={result_id}, step_id={step_id}")
        
        return jsonify({'success': True})
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error updating JSON: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/unpublish-analysis', methods=['POST'])
@admin_required
def unpublish_analysis():
    """
    Dépublie une analyse active (passe is_active de TRUE à FALSE).
    Permet à l'admin de retirer temporairement une analyse de la vue utilisateur.
    """
    data = request.json
    result_id = data.get("result_id")
    step_id = data.get("step_id")
    generator_type = data.get("generator_type", "admin")
    
    if not result_id or not step_id:
        return jsonify({"error": "Missing result_id or step_id"}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que l'analyse existe et est active
        cursor.execute("""
            SELECT is_active 
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s
        """, (result_id, step_id, generator_type))
        
        analysis = cursor.fetchone()
        
        if not analysis:
            return jsonify({"error": "Analysis not found"}), 404
        
        if not analysis['is_active']:
            return jsonify({"error": "Analysis is already unpublished"}), 400
        
        # Dépublier l'analyse
        cursor.execute("""
            UPDATE result_user 
            SET is_active = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s
        """, (result_id, step_id, generator_type))
        
        mysql.connection.commit()
        
        logger.info(f"Analysis unpublished: result_id={result_id}, step_id={step_id}, generator_type={generator_type}")
        
        return jsonify({"success": True})
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error unpublishing analysis: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/generate-shareable-link', methods=['POST'])
@admin_required
def generate_shareable_link():
    """
    Génère un lien partageable (token) à partir d'une URL d'analyse dynamique.
    
    Request body:
        - quiz_id: ID du quiz
        - result_id: ID du résultat
        - user_id: ID de l'utilisateur (optionnel, récupéré automatiquement)
        - access_type: 'free' ou 'paid' (défaut: 'free')
    
    Returns:
        - shareable_url: URL complète avec token
        - token: Token d'accès
        - access_type: Type d'accès
        - expires_at: Date d'expiration (si free)
    """
    request_id = generate_request_id()
    logger.info(f"[{request_id}] Génération de lien partageable")
    
    data = request.json
    quiz_id = data.get('quiz_id')
    result_id = data.get('result_id')
    user_id = data.get('user_id')  # Optionnel
    access_type = data.get('access_type', 'free')  # 'free' par défaut
    
    if not quiz_id or not result_id:
        return jsonify({'error': 'quiz_id et result_id requis'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Si user_id n'est pas fourni, le récupérer depuis result_user
        if not user_id:
            cursor.execute("""
                SELECT user_id 
                FROM result_user 
                WHERE result_id = %s 
                LIMIT 1
            """, (result_id,))
            
            result = cursor.fetchone()
            if not result:
                return jsonify({'error': 'Impossible de trouver le user_id pour ce result_id'}), 404
            
            user_id = result['user_id']
        
        logger.info(f"[{request_id}] Génération token pour user {user_id}, quiz {quiz_id}, result {result_id}")
        
        # Vérifier si un token existe déjà
        cursor.execute("""
            SELECT token, access_type, expires_at, is_revoked
            FROM analysis_access_tokens
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND result_id = %s
            AND is_revoked = FALSE
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id, quiz_id, result_id))
        
        existing_token = cursor.fetchone()
        
        if existing_token:
            logger.info(f"[{request_id}] Token existant trouvé: {existing_token['token'][:20]}...")
            
            # Si le token existant correspond au type demandé, le retourner
            if existing_token['access_type'] == access_type:
                access_url = url_for('quiz_analysis.view_analysis', 
                                    quiz_id=quiz_id,
                                    token=existing_token['token'],
                                    _external=True)
                
                return jsonify({
                    'success': True,
                    'message': 'Token existant retourné',
                    'shareable_url': access_url,
                    'token': existing_token['token'],
                    'access_type': existing_token['access_type'],
                    'expires_at': existing_token['expires_at'].isoformat() if existing_token['expires_at'] else None
                })
            else:
                # Upgrade/downgrade le token existant
                logger.info(f"[{request_id}] Mise à jour du token existant vers {access_type}")
                
                if access_type == 'paid':
                    AnalysisAccessModel.upgrade_to_paid(cursor, existing_token['token'])
                    new_expiration = None
                else:
                    # Downgrade vers free
                    from datetime import datetime, timedelta
                    new_expiration = datetime.now() + timedelta(days=7)
                    cursor.execute("""
                        UPDATE analysis_access_tokens 
                        SET access_type = 'free',
                            expires_at = %s,
                            updated_at = NOW()
                        WHERE token = %s
                    """, (new_expiration, existing_token['token']))
                
                current_app.mysql.connection.commit()
                
                access_url = url_for('quiz_analysis.view_analysis', 
                                    quiz_id=quiz_id,
                                    token=existing_token['token'],
                                    _external=True)
                
                return jsonify({
                    'success': True,
                    'message': f'Token mis à jour vers {access_type}',
                    'shareable_url': access_url,
                    'token': existing_token['token'],
                    'access_type': access_type,
                    'expires_at': new_expiration.isoformat() if new_expiration else None
                })
        
        # Créer un nouveau token
        logger.info(f"[{request_id}] Création d'un nouveau token {access_type}")
        
        token = AnalysisAccessModel.create_access_token(
            cursor,
            user_id=user_id,
            quiz_id=quiz_id,
            result_id=result_id,
            access_type=access_type
        )
        
        current_app.mysql.connection.commit()
        
        # Récupérer les infos du token créé
        cursor.execute("""
            SELECT expires_at 
            FROM analysis_access_tokens 
            WHERE token = %s
        """, (token,))
        
        token_info = cursor.fetchone()

        access_url = url_for('quiz_analysis.view_analysis', 
                            quiz_id=quiz_id,
                            token=existing_token['token'],
                            _external=True)
        
        logger.info(f"[{request_id}] Token créé avec succès: {access_url}")
        
        return jsonify({
            'success': True,
            'message': 'Token créé avec succès',
            'shareable_url': access_url,
            'token': token,
            'access_type': access_type,
            'expires_at': token_info['expires_at'].isoformat() if token_info and token_info['expires_at'] else None
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[{request_id}] Erreur génération lien: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/share/create', methods=['POST'])
@login_required
def create_share_link():
    """
    Génère un lien de partage temporaire (7 jours).
    - Si user normal : crée pour lui-même
    - Si admin + target_user_id fourni : crée pour l'user cible
    """
    request_id = generate_request_id()
    
    data = request.json
    quiz_id = data.get('quiz_id')
    result_id = data.get('result_id')
    target_user_id = data.get('user_id')  # ✅ Nouveau : user cible (pour admin)
    
    if not quiz_id:
        return jsonify({'error': 'quiz_id requis'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # ✅ Déterminer le user_id cible
        if target_user_id and current_user.is_admin_user:
            # Admin peut créer un lien pour n'importe quel user
            user_id = int(target_user_id)
            logger.info(f"[{request_id}] Admin {current_user.id} crée lien pour user {user_id}")
        elif result_id and current_user.is_admin_user:
            # Admin sans target_user_id → récupérer depuis result_id
            cursor.execute("""
                SELECT user_id FROM result_user 
                WHERE result_id = %s LIMIT 1
            """, (result_id,))
            result = cursor.fetchone()
            if result:
                user_id = result['user_id']
                logger.info(f"[{request_id}] Admin {current_user.id} crée lien pour user {user_id} (depuis result_id)")
            else:
                user_id = current_user.id
        else:
            # User normal → crée pour lui-même
            user_id = current_user.id
        
        logger.info(f"[{request_id}] Création lien de partage pour user {user_id} (appelé par {current_user.id})")
        
        # ✅ ÉTAPE 1 : Chercher d'abord une analyse DYNAMIQUE active pour CE user
        cursor.execute("""
            SELECT result_id, result_step_id
            FROM result_user
            WHERE user_id = %s AND quiz_id = %s AND is_active = TRUE
            ORDER BY created_at DESC LIMIT 1
        """, (user_id, quiz_id))
        
        dynamic_result = cursor.fetchone()
        
        if dynamic_result:
            final_result_id = dynamic_result['result_id']
            analysis_type = 'dynamic'
            logger.info(f"[{request_id}] Analyse DYNAMIQUE trouvée pour user {user_id}: result_id={final_result_id}")
        elif user_id in USER_STATIC_TEMPLATES:
            final_result_id = f"static_{user_id}_{quiz_id}"
            analysis_type = 'static'
            logger.info(f"[{request_id}] Analyse STATIQUE pour user {user_id}: result_id={final_result_id}")
        else:
            return jsonify({'error': f'Aucune analyse trouvée pour user {user_id}'}), 404
        
        # ✅ ÉTAPE 2 : Chercher un token existant pour CE user/quiz
        cursor.execute("""
            SELECT token, result_id, expires_at, access_type
            FROM analysis_access_tokens
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND access_type = 'free'
            AND is_revoked = FALSE
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        existing_token = cursor.fetchone()
        
        if existing_token:
            token = existing_token['token']
            old_result_id = existing_token['result_id']
            old_expires_at = existing_token['expires_at']
            
            needs_renewal = (
                old_expires_at is None or 
                old_expires_at < datetime.now() + timedelta(days=1)
            )
            needs_result_update = (old_result_id != final_result_id)
            
            if needs_renewal or needs_result_update:
                new_expires_at = datetime.now() + timedelta(days=7)
                
                cursor.execute("""
                    UPDATE analysis_access_tokens
                    SET result_id = %s,
                        expires_at = %s,
                        updated_at = NOW()
                    WHERE token = %s
                """, (final_result_id, new_expires_at, token))
                
                current_app.mysql.connection.commit()
                
                logger.info(f"[{request_id}] Token mis à jour pour user {user_id}: expires_at={new_expires_at}")
                
                share_url = url_for('quiz_analysis.access_analysis', 
                                   token=token,
                                   _external=True)
                
                return jsonify({
                    'success': True,
                    'share_url': share_url,
                    'token': token,
                    'expires_at': new_expires_at.isoformat(),
                    'is_new': False,
                    'analysis_type': analysis_type,
                    'user_id': user_id
                })
            else:
                logger.info(f"[{request_id}] Token existant valide pour user {user_id}")
                
                share_url = url_for('quiz_analysis.access_analysis', 
                                   token=token,
                                   _external=True)
                
                return jsonify({
                    'success': True,
                    'share_url': share_url,
                    'token': token,
                    'expires_at': old_expires_at.isoformat() if old_expires_at else None,
                    'is_new': False,
                    'analysis_type': analysis_type,
                    'user_id': user_id
                })
        
        # ✅ ÉTAPE 3 : Créer un nouveau token pour CE user
        logger.info(f"[{request_id}] Création nouveau token pour user {user_id}")
        
        new_expires_at = datetime.now() + timedelta(days=7)
        new_token = f"{uuid.uuid4()}_{int(datetime.now().timestamp())}"
        
        cursor.execute("""
            INSERT INTO analysis_access_tokens
            (token, user_id, quiz_id, result_id, expires_at, access_type)
            VALUES (%s, %s, %s, %s, %s, 'free')
        """, (new_token, user_id, quiz_id, final_result_id, new_expires_at))
        
        current_app.mysql.connection.commit()
        
        share_url = url_for('quiz_analysis.access_analysis', 
                           token=new_token,
                           _external=True)
        
        logger.info(f"[{request_id}] Token créé pour user {user_id}: {new_token[:20]}...")
        
        return jsonify({
            'success': True,
            'share_url': share_url,
            'token': new_token,
            'expires_at': new_expires_at.isoformat(),
            'is_new': True,
            'analysis_type': analysis_type,
            'user_id': user_id
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[{request_id}] Erreur création lien partage: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

def check_user_has_analysis(cursor, user_id, quiz_id='pack_clarte'):
    """
    Vérifie si un utilisateur a une analyse disponible (dynamique OU statique).
    
    Args:
        cursor: Curseur MySQL
        user_id (int): ID de l'utilisateur
        quiz_id (str): ID du quiz (défaut: 'pack_clarte')
    
    Returns:
        dict: {
            'has_analysis': bool,
            'analysis_type': 'dynamic'|'static'|None,
            'result_id': str|None (si dynamique),
            'token': str|None (si dynamique)
        }
    """
    try:
        # 1. Vérifier d'abord si analyse dynamique existe dans result_user
        cursor.execute("""
            SELECT 
                ru.result_id,
                ru.token_id,
                ru.result_step_id
            FROM result_user ru
            WHERE ru.quiz_id = %s 
            AND ru.user_id = %s
            AND ru.is_active = TRUE
            ORDER BY ru.created_at DESC
            LIMIT 1
        """, (quiz_id, user_id))
        
        dynamic_result = cursor.fetchone()
        
        if dynamic_result:
            logger.info(f"User {user_id} has DYNAMIC analysis: {dynamic_result['result_id']}")
            return {
                'has_analysis': True,
                'analysis_type': 'dynamic',
                'result_id': dynamic_result['result_id'],
                'token': dynamic_result['token_id'],
                'step_id': dynamic_result['result_step_id']
            }
        
        # 2. Si pas d'analyse dynamique, vérifier si mapping statique existe
        if user_id in USER_STATIC_TEMPLATES:
            logger.info(f"User {user_id} has STATIC analysis: {USER_STATIC_TEMPLATES[user_id]}")
            return {
                'has_analysis': True,
                'analysis_type': 'static',
                'result_id': None,
                'token': None,
                'template_path': USER_STATIC_TEMPLATES[user_id]
            }
        
        # 3. Aucune analyse trouvée
        logger.info(f"User {user_id} has NO analysis")
        return {
            'has_analysis': False,
            'analysis_type': None,
            'result_id': None,
            'token': None
        }
    
    except Exception as e:
        logger.error(f"Error checking analysis for user {user_id}: {str(e)}", exc_info=True)
        return {
            'has_analysis': False,
            'analysis_type': None,
            'result_id': None,
            'token': None
        }

@quiz_analysis_bp.route('/admin/manual-retry-preview', methods=['POST'])
@admin_required
def manual_retry_preview():
    """
    Génère une prévisualisation des voies corrigées avec feedback admin.
    NE SAUVEGARDE PAS en BDD - retourne le JSON pour validation humaine.
    
    ✅ Supporte validation_criteria personnalisés
    """
    request_id = generate_request_id()
    start_time = time.time()
    logger.info(f"[{request_id}] 🎯 Starting MANUAL retry preview")
    
    data = request.json
    user_id = data.get('user_id')
    quiz_id = data.get('quiz_id')
    result_id = data.get('result_id')
    step_id = data.get('step_id')
    admin_feedback = data.get('admin_feedback', '').strip()
    source_generator_type = data.get('source_generator_type', 'admin')
    selected_voies = data.get('selected_voies', [1, 2, 3])
    # ✅ NOUVEAU : Récupérer les critères de validation personnalisés
    validation_criteria = data.get('validation_criteria', '').strip()
    
    # Validation des paramètres
    if not all([user_id, quiz_id, result_id, step_id]):
        return jsonify({'error': 'Paramètres manquants (user_id, quiz_id, result_id, step_id)'}), 400
    
    if not admin_feedback or len(admin_feedback) < 10:
        return jsonify({'error': 'Le feedback doit contenir au moins 10 caractères'}), 400
    
    if not selected_voies or not isinstance(selected_voies, list):
        selected_voies = [1, 2, 3]
    
    selected_voies = [v for v in selected_voies if v in [1, 2, 3]]
    if not selected_voies:
        return jsonify({'error': 'Sélectionnez au moins une voie à modifier'}), 400
    
    logger.info(f"[{request_id}] 🎯 Selected voies to regenerate: {selected_voies}")
    logger.info(f"[{request_id}] 📝 Custom validation_criteria: {len(validation_criteria)} chars")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        user_id = int(user_id)
        
        # ===== 1. RÉCUPÉRER LE JSON ACTUEL =====
        cursor.execute("""
            SELECT result_json, token_id, prompt_id
            FROM result_user
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (result_id, step_id, source_generator_type))
        
        current_result = cursor.fetchone()
        
        if not current_result:
            other_type = 'user' if source_generator_type == 'admin' else 'admin'
            cursor.execute("""
                SELECT result_json, token_id, prompt_id
                FROM result_user
                WHERE result_id = %s 
                AND result_step_id = %s 
                AND generator_type = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (result_id, step_id, other_type))
            current_result = cursor.fetchone()
            
            if current_result:
                source_generator_type = other_type
                logger.info(f"[{request_id}] Fallback to {other_type} generator_type")
        
        if not current_result:
            return jsonify({'error': f'Analyse introuvable pour result_id={result_id}, step_id={step_id}'}), 404
        
        original_json = json.loads(current_result['result_json'])
        token_id = current_result['token_id']
        original_prompt_id = current_result['prompt_id']
        
        logger.info(f"[{request_id}] ✅ Original JSON retrieved - token: {token_id}, source: {source_generator_type}")
        
        # ===== 2. EXTRAIRE LES RECOMMANDATIONS ACTUELLES =====
        if step_id == 'career_path':
            current_recommendations = original_json.get('strategies', {}).get('items', [])
            field_name = 'strategies'
            recommendations_label = 'stratégies de reconversion'
        elif step_id in ['career_path_v1', 'career_path_v2', 'career_path_v3', 'career_path_v4']:
            if step_id == 'career_path_v4':
                current_recommendations = original_json.get('pistes', [])
                field_name = 'pistes'
                recommendations_label = 'pistes métiers'
            else:
                current_recommendations = original_json.get('voies', [])
                field_name = 'voies'
            recommendations_label = 'voies professionnelles' + (' V2' if step_id == 'career_path_v2' else '')
        else:
            return jsonify({'error': f'Step ID non supporté pour retry manuel: {step_id}'}), 400
        
        if len(current_recommendations) != 3:
            return jsonify({'error': f'JSON invalide: attendu 3 {field_name}, trouvé {len(current_recommendations)}'}), 400
        
        # ===== 3. RÉCUPÉRER LE CONTEXTE USER =====
        user_context = "[Contexte utilisateur non disponible]"
        
        if original_prompt_id:
            cursor.execute("""
                SELECT prompt
                FROM prompt_user
                WHERE prompt_id = %s
            """, (original_prompt_id,))
            
            prompt_row = cursor.fetchone()
            
            if prompt_row:
                try:
                    prompt_data = json.loads(prompt_row['prompt'])
                    original_human_prompt = prompt_data.get('prompt', {}).get('human', '')
                    
                    if "Voici les réponses aux questions du test de profiling:" in original_human_prompt:
                        parts = original_human_prompt.split("Voici les réponses aux questions du test de profiling:")
                        if len(parts) > 1:
                            qa_section = parts[1].split("\n\n\n")[0]
                            user_context = qa_section.strip()
                    else:
                        user_context = original_human_prompt[:2000]
                        
                    logger.info(f"[{request_id}] ✅ User context extracted: {len(user_context)} chars")
                except Exception as e:
                    logger.warning(f"[{request_id}] ⚠️ Error parsing prompt: {e}")
        
        # ===== 4. CONSTRUIRE LE PROMPT DE RÉGÉNÉRATION =====
        voies_a_modifier = ", ".join([f"Voie {v}" for v in selected_voies])
        voies_a_conserver = [v for v in [1, 2, 3] if v not in selected_voies]
        voies_conservees_str = ", ".join([f"Voie {v}" for v in voies_a_conserver]) if voies_a_conserver else "Aucune"
        
        if len(selected_voies) == 3:
            instruction_selection = "RÉGÉNÈRE LES 3 VOIES en appliquant les corrections."
        elif len(selected_voies) == 1:
            instruction_selection = f"""RÉGÉNÈRE UNIQUEMENT LA VOIE {selected_voies[0]} en appliquant les corrections.
⚠️ CONSERVE LES VOIES {voies_conservees_str} EXACTEMENT TELLES QUELLES (copie-les sans modification)."""
        else:
            instruction_selection = f"""RÉGÉNÈRE UNIQUEMENT LES VOIES {voies_a_modifier} en appliquant les corrections.
⚠️ CONSERVE LA {voies_conservees_str} EXACTEMENT TELLE QUELLE (copie-la sans modification)."""
        
        regeneration_prompt = f"""Tu es un expert en reconversion professionnelle. 

CONTEXTE UTILISATEUR (réponses au questionnaire) :
{user_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VERSION ACTUELLE DES {recommendations_label.upper()} :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```json
{json.dumps(current_recommendations, ensure_ascii=False, indent=2)}
```

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 VOIES À MODIFIER : {voies_a_modifier}
🔒 VOIES À CONSERVER : {voies_conservees_str}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 INSTRUCTIONS DE CORRECTION (feedback admin) :
{admin_feedback}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction_selection}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RÈGLES :
✓ Applique EXACTEMENT les corrections demandées pour les voies sélectionnées
✓ Conserve la structure JSON identique (3 éléments dans l'array)
✓ Les voies non sélectionnées doivent être IDENTIQUES à l'original
✓ Commence DIRECTEMENT par [ (JSON array)
✓ ZÉRO texte avant ou après le JSON

GÉNÈRE LE JSON ARRAY (3 éléments) :"""

        # ===== 5. APPEL API CLAUDE =====
        logger.info(f"[{request_id}] 🤖 Calling Claude API for manual retry")
        
        api_start = time.time()
        
        from anthropic import Anthropic
        client = Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])
        
        messages_with_prefill = [
            {"role": "user", "content": regeneration_prompt},
            {"role": "assistant", "content": "["}
        ]
        
        message = client.messages.create(
            model=current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
            max_tokens=8000,
            temperature=0.7,
            messages=messages_with_prefill
        )
        
        api_duration = time.time() - api_start
        
        regenerated_text = message.content[0].text
        
        if not regenerated_text.startswith('['):
            regenerated_text = '[' + regenerated_text
        
        logger.info(f"[{request_id}] ✅ API response received - Duration: {api_duration:.2f}s")
        
        # ===== 6. PARSER ET VALIDER LE JSON =====
        if '```' in regenerated_text:
            regenerated_text = regenerated_text.replace('```json', '').replace('```', '').strip()
        
        try:
            new_recommendations = json.loads(regenerated_text)
        except json.JSONDecodeError as e:
            logger.error(f"[{request_id}] ❌ Invalid JSON from Claude: {e}")
            logger.error(f"[{request_id}] Response preview: {regenerated_text[:500]}")
            return jsonify({
                'error': f'Claude a généré un JSON invalide: {str(e)}',
                'raw_response': regenerated_text[:1000]
            }), 500
        
        if not isinstance(new_recommendations, list):
            return jsonify({'error': 'La réponse n\'est pas un array JSON'}), 500
        
        if len(new_recommendations) != 3:
            return jsonify({'error': f'Attendu 3 {field_name}, reçu {len(new_recommendations)}'}), 500
        
        # ===== 7. FUSIONNER DANS LE JSON COMPLET =====
        merged_json = json.loads(json.dumps(original_json))
        
        if step_id == 'career_path':
            merged_json['strategies']['items'] = new_recommendations
        elif step_id in ['career_path_v1', 'career_path_v2', 'career_path_v3', 'career_path_v4']:
            if step_id == 'career_path_v4':
                merged_json['pistes'] = new_recommendations
            else:
                merged_json['voies'] = new_recommendations
        
        logger.info(f"[{request_id}] ✅ JSON merged successfully")
        
        # ===== 8. DÉTECTER LES VOIES MODIFIÉES =====
        voies_changed = []
        for idx, (orig, new) in enumerate(zip(current_recommendations, new_recommendations)):
            if json.dumps(orig, sort_keys=True) != json.dumps(new, sort_keys=True):
                voies_changed.append(idx + 1)
        
        logger.info(f"[{request_id}] 📊 Voies actually changed: {voies_changed}")
        
        # ===== 9. RETOURNER LA PRÉVISUALISATION =====
        total_duration = time.time() - start_time
        
        return jsonify({
            'success': True,
            'preview': {
                'original_recommendations': current_recommendations,
                'new_recommendations': new_recommendations,
                'merged_json': merged_json,
                'field_name': field_name,
                'step_id': step_id,
                'selected_voies': selected_voies,
                'voies_changed': voies_changed
            },
            'metadata': {
                'request_id': request_id,
                'generation_time_seconds': round(total_duration, 2),
                'api_time_seconds': round(api_duration, 2),
                'source_generator_type': source_generator_type,
                'token_id': token_id,
                'original_prompt_id': original_prompt_id,
                'custom_validation_criteria_used': bool(validation_criteria)
            }
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] ❌ Manual retry preview error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/manual-retry-save', methods=['POST'])
@admin_required
def manual_retry_save():
    """
    Sauvegarde le JSON prévisualisé et validé par l'admin.
    
    - Reçoit le merged_json complet
    - Sauvegarde comme nouvelle version admin
    - Log l'action pour audit
    - PAS de validation sémantique (l'admin a validé visuellement)
    """
    request_id = generate_request_id()
    logger.info(f"[{request_id}] 💾 Saving manually retried analysis")
    
    data = request.json
    user_id = data.get('user_id')
    quiz_id = data.get('quiz_id')
    result_id = data.get('result_id')
    step_id = data.get('step_id')
    merged_json = data.get('merged_json')
    admin_feedback = data.get('admin_feedback', '')  # Pour audit
    original_prompt_id = data.get('original_prompt_id')
    token_id = data.get('token_id')
    
    # Validation
    if not all([user_id, quiz_id, result_id, step_id, merged_json]):
        return jsonify({'error': 'Paramètres manquants'}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        user_id = int(user_id)
        
        # ===== 1. VÉRIFIER QUE LE TOKEN EXISTE =====
        if not token_id:
            # Récupérer le token depuis l'analyse existante
            cursor.execute("""
                SELECT token_id
                FROM result_user
                WHERE result_id = %s AND result_step_id = %s
                LIMIT 1
            """, (result_id, step_id))
            
            token_row = cursor.fetchone()
            if token_row:
                token_id = token_row['token_id']
            else:
                # Créer un token admin
                token_id = f"admin_manual_{result_id[:8]}"
                cursor.execute("""
                    INSERT INTO tokens (token_code, user_id, quiz_id, token_type, is_used)
                    VALUES (%s, %s, %s, 'free', TRUE)
                    ON DUPLICATE KEY UPDATE updated_at = NOW()
                """, (token_id, user_id, quiz_id))
                logger.info(f"[{request_id}] Created admin token: {token_id}")
        
        # ===== 2. STOCKER LE PROMPT DE RETRY (pour audit) =====
        retry_prompt_data = {
            "session_data": {
                "result_id": result_id,
                "step_id": step_id,
                "user_id": user_id,
                "quiz_id": quiz_id,
                "timestamp": datetime.now().isoformat(),
                "is_manual_retry": True
            },
            "prompt": {
                "admin_feedback": admin_feedback,
                "action": "manual_retry_save"
            },
            "api_params": {
                "note": "Prévisualisation validée manuellement par admin"
            }
        }
        
        cursor.execute("""
            INSERT INTO prompt_user (result_id, result_step_id, user_id, prompt)
            VALUES (%s, %s, %s, %s)
        """, (result_id, step_id, user_id, json.dumps(retry_prompt_data, ensure_ascii=False)))
        
        new_prompt_id = cursor.lastrowid
        logger.info(f"[{request_id}] ✅ Retry prompt stored: {new_prompt_id}")
        
        # ===== 3. VÉRIFIER SI UNE VERSION ADMIN EXISTE DÉJÀ =====
        cursor.execute("""
            SELECT 1 FROM result_user
            WHERE result_id = %s 
            AND result_step_id = %s 
            AND generator_type = 'admin'
        """, (result_id, step_id))
        
        admin_exists = cursor.fetchone() is not None
        
        if admin_exists:
            # UPDATE
            cursor.execute("""
                UPDATE result_user
                SET result_json = %s,
                    prompt_id = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE result_id = %s 
                AND result_step_id = %s 
                AND generator_type = 'admin'
            """, (json.dumps(merged_json, ensure_ascii=False), new_prompt_id, result_id, step_id))
            
            logger.info(f"[{request_id}] ✅ Updated existing admin analysis")
        else:
            # INSERT
            cursor.execute("""
                INSERT INTO result_user (
                    quiz_id, user_id, result_id, result_step_id,
                    result_json, token_id, prompt_id, is_active, generator_type
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, 'admin')
            """, (quiz_id, user_id, result_id, step_id, 
                  json.dumps(merged_json, ensure_ascii=False), token_id, new_prompt_id))
            
            logger.info(f"[{request_id}] ✅ Inserted new admin analysis (draft)")
        
        # ===== 4. LOG POUR AUDIT =====
        cursor.execute("""
            INSERT INTO analysis_validation_logs
            (result_id, step_id, user_id, attempt_number, validation_status,
             issues_detected, issues_count, critical_issues_count,
             resolution_type, validation_duration_seconds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            result_id,
            step_id,
            user_id,
            1,  # attempt
            'success',
            json.dumps([{'type': 'manual_retry', 'feedback': admin_feedback[:500]}], ensure_ascii=False),
            0,
            0,
            'manual_review',
            0
        ))
        
        mysql.connection.commit()
        
        logger.info(f"[{request_id}] ✅ Manual retry saved successfully")
        
        return jsonify({
            'success': True,
            'message': 'Analyse mise à jour avec succès',
            'result_id': result_id,
            'step_id': step_id,
            'prompt_id': new_prompt_id,
            'is_new': not admin_exists
        })
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[{request_id}] ❌ Manual retry save error: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/check-notification-status/<string:result_id>/<string:step_id>/<int:user_id>', methods=['GET'])
@admin_required
def check_notification_status(result_id, step_id, user_id):
    """
    Vérifie si un email de notification a déjà été envoyé
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT sent_at, sent_to_email
            FROM analysis_notification_emails 
            WHERE result_id = %s 
            AND step_id = %s 
            AND user_id = %s
            ORDER BY sent_at DESC 
            LIMIT 1
        """, (result_id, step_id, user_id))
        
        email = cursor.fetchone()
        
        if email:
            return jsonify({
                "already_sent": True,
                "sent_at": email['sent_at'].strftime('%d/%m/%Y à %H:%M'),
                "sent_to": email['sent_to_email']
            })
        else:
            return jsonify({"already_sent": False})
            
    except Exception as e:
        logger.error(f"Error checking notification status: {str(e)}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/preview-static/<int:user_id>', methods=['GET'])
@admin_required
def preview_static_template(user_id: int):
    """
    Prévisualise le template statique d'un utilisateur (pour admin uniquement).
    """
    request_id = generate_request_id()
    
    if user_id not in USER_STATIC_TEMPLATES:
        flash("Cet utilisateur n'a pas de template statique", "warning")
        return redirect(url_for('quiz_analysis.retry_analysis'))
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer les infos de l'utilisateur cible
        cursor.execute("""
            SELECT firstname, lastname, email
            FROM users
            WHERE user_id = %s
        """, (user_id,))
        
        user_data = cursor.fetchone()
        
        template_vars = {
            'firstname': user_data['firstname'] if user_data else 'Utilisateur',
            'lastname': user_data['lastname'] if user_data else '',
            'email': user_data['email'] if user_data else '',
            'views_left': None,
            'days_left': None,
            'token': None,
            'is_guest_view': False,
            'access_type': 'paid',  # Admin preview = tout débloqué
            'user_id': user_id,
            'quiz_id': 'pack_clarte',
            'expires_at': None,
            'show_expiration_banner': False,
            'access_url': None,
            'is_admin_preview': True  # Flag pour savoir que c'est une preview admin
        }
        
        template_path = USER_STATIC_TEMPLATES[user_id]
        logger.info(f"[{request_id}] Admin preview of static template for user {user_id}: {template_path}")
        
        return render_template(template_path, **template_vars)
        
    except Exception as e:
        logger.error(f"[{request_id}] Error previewing static template: {e}", exc_info=True)
        flash(f"Erreur: {str(e)}", "danger")
        return redirect(url_for('quiz_analysis.retry_analysis'))
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-analysis-json', methods=['GET'])
@admin_required
def get_analysis_json():
    """Récupère le JSON d'une analyse pour afficher les voies (noms dans le modal)"""
    request_id = generate_request_id()
    
    user_id = request.args.get('user_id')
    result_id = request.args.get('result_id')
    step_id = request.args.get('step_id')
    generator_type = request.args.get('generator_type', 'admin')
    
    if not all([user_id, result_id, step_id]):
        return jsonify({'success': False, 'error': 'Paramètres manquants'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT result_json
            FROM result_user 
            WHERE result_id = %s 
            AND result_step_id = %s
            AND generator_type = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (result_id, step_id, generator_type))
        
        result = cursor.fetchone()
        
        if not result or not result.get('result_json'):
            # Fallback sur l'autre generator_type
            other_type = 'user' if generator_type == 'admin' else 'admin'
            cursor.execute("""
                SELECT result_json
                FROM result_user 
                WHERE result_id = %s 
                AND result_step_id = %s
                AND generator_type = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (result_id, step_id, other_type))
            result = cursor.fetchone()
        
        if not result or not result.get('result_json'):
            return jsonify({
                'success': False,
                'error': 'Analyse non trouvée'
            }), 404
        
        result_json = result['result_json']
        if isinstance(result_json, str):
            result_json = json.loads(result_json)
        
        # Extraire les recommandations selon le step_id
        if step_id == 'career_path':
            recommendations = result_json.get('strategies', {}).get('items', [])
        elif step_id in ['career_path_v1', 'career_path_v2', 'career_path_v3', 'career_path_v4']:
            if step_id == 'career_path_v4':
                recommendations = result_json.get('pistes', [])
            else:
                recommendations = result_json.get('voies', [])
        else:
            recommendations = []
        
        return jsonify({
            'success': True,
            'recommendations': recommendations,
            'step_id': step_id
        })
        
    except Exception as e:
        logger.error(f"[{request_id}] Error getting analysis JSON: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-generation-history/<string:result_id>/<string:step_id>', methods=['GET'])
@admin_required
def get_generation_history(result_id, step_id):
    """
    Récupère l'historique complet de génération d'une analyse.
    Inclut tous les prompts de génération ET de validation.
    Ajoute automatiquement les liens parent/validation si non présents.
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer tous les prompts liés à cette analyse
        cursor.execute("""
            SELECT 
                prompt_id,
                prompt,
                created_at
            FROM prompt_user
            WHERE result_id = %s 
            AND result_step_id = %s
            ORDER BY created_at ASC
        """, (result_id, step_id))
        
        prompts = cursor.fetchall()
        
        if not prompts:
            return jsonify({'success': False, 'error': 'Aucun historique trouvé'}), 404
        
        history = []
        last_generation_prompt_id = None
        
        for p in prompts:
            try:
                prompt_data = json.loads(p['prompt'])
                session_data = prompt_data.get('session_data', {})
                
                prompt_type = session_data.get('prompt_type', 'generation')
                
                # Si c'est une validation sans parent_prompt_id, utiliser le dernier prompt de génération
                if prompt_type == 'validation' and not session_data.get('parent_prompt_id'):
                    session_data['parent_prompt_id'] = last_generation_prompt_id
                
                entry = {
                    'prompt_id': p['prompt_id'],
                    'created_at': p['created_at'].isoformat() if p['created_at'] else None,
                    'prompt_type': prompt_type,
                    'generation_type': session_data.get('generation_type'),
                    'attempt_number': session_data.get('attempt_number'),
                    'parent_prompt_id': session_data.get('parent_prompt_id'),
                    'validation_prompt_id': session_data.get('validation_prompt_id'),
                    'validation_status': session_data.get('validation_status'),
                    'admin_feedback': session_data.get('admin_feedback'),
                    'selected_voies_indices': session_data.get('selected_voies_indices'),
                    'trigger_issues': session_data.get('trigger_issues'),
                    'generation_duration_seconds': session_data.get('generation_duration_seconds'),
                    
                    # Pour les prompts de validation
                    'validation_result': session_data.get('validation_result'),
                    'validation_criteria_source': session_data.get('validation_criteria_source'),
                    'validated_json_preview': session_data.get('validated_json_preview'),
                    'validation_duration_seconds': session_data.get('validation_duration_seconds'),
                    
                    # Aperçu des prompts (tronqués)
                    'system_prompt_preview': (prompt_data.get('prompt', {}).get('system') or '')[:500],
                    'human_prompt_preview': (prompt_data.get('prompt', {}).get('human') or '')[:1000],
                }
                
                # Mémoriser le dernier prompt de génération pour les validations suivantes
                if prompt_type == 'generation':
                    last_generation_prompt_id = p['prompt_id']
                
                history.append(entry)
                
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in prompt_id {p['prompt_id']}")
                continue
        
        # Calculer les stats
        generation_prompts = [h for h in history if h['prompt_type'] == 'generation']
        validation_prompts = [h for h in history if h['prompt_type'] == 'validation']
        
        # Déterminer le statut final (depuis la dernière génération qui a un validation_status)
        # PRIORITÉ 1: Chercher dans les prompts de validation (source de vérité)
        final_status = None
        for val in reversed(validation_prompts):
            if val.get('validation_result'):
                is_valid = val['validation_result'].get('is_valid')
                if is_valid is not None:
                    final_status = 'success' if is_valid else 'failed'
                    break
        
        # PRIORITÉ 2: Si pas de validation, chercher dans les prompts de génération
        if not final_status:
            for gen in reversed(generation_prompts):
                if gen.get('validation_status'):
                    final_status = gen['validation_status']
                    break
        
        # PRIORITÉ 3: Si toujours rien, considérer comme succès (pas d'erreur détectée)
        if not final_status:
            final_status = 'success'
        
        stats = {
            'total_prompts': len(history),
            'generation_prompts': len(generation_prompts),
            'validation_prompts': len(validation_prompts),
            'total_attempts': max([h.get('attempt_number') or 0 for h in generation_prompts], default=0),
            'final_status': final_status,
            'has_manual_retry': any(h.get('generation_type') == 'manual_retry' for h in history),
            'has_custom_criteria': any(h.get('validation_criteria_source') == 'custom' for h in history)
        }
        
        # ========== DEBUG LOGS - AJOUTER ICI ==========
        logger.warning(f"=== DEBUG HISTORY ===")
        logger.warning(f"result_id={result_id}, step_id={step_id}")
        logger.warning(f"generation_prompts: {len(generation_prompts)}")
        logger.warning(f"validation_prompts: {len(validation_prompts)}")
        logger.warning(f"final_status CALCULÉ: {final_status}")
        for idx, val in enumerate(validation_prompts):
            logger.warning(f"validation[{idx}].validation_result = {val.get('validation_result')}")
        logger.warning(f"=== FIN DEBUG ===")

        return jsonify({
            'success': True,
            'result_id': result_id,
            'step_id': step_id,
            'history': history,
            'stats': stats
        })
        
    except Exception as e:
        logger.error(f"Error fetching generation history: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-prompt-detail/<int:prompt_id>', methods=['GET'])
@admin_required
def get_prompt_detail(prompt_id):
    """
    Récupère le détail complet d'un prompt (génération ou validation).
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT prompt_id, result_id, result_step_id, user_id, prompt, created_at
            FROM prompt_user
            WHERE prompt_id = %s
        """, (prompt_id,))
        
        result = cursor.fetchone()
        
        if not result:
            return jsonify({'success': False, 'error': 'Prompt non trouvé'}), 404
        
        prompt_data = json.loads(result['prompt'])
        session_data = prompt_data.get('session_data', {})
        
        # ✅ DEBUG LOGS
        logger.warning(f"=== DEBUG get-prompt-detail #{prompt_id} ===")
        logger.warning(f"validation_criteria_source in session_data: {session_data.get('validation_criteria_source')}")
        logger.warning(f"validation_criteria_custom exists: {bool(prompt_data.get('validation_criteria_custom'))}")
        logger.warning(f"validation_criteria_custom length: {len(prompt_data.get('validation_criteria_custom', '') or '')}")
        logger.warning(f"prompt_type: {session_data.get('prompt_type')}")
        logger.warning(f"=== FIN DEBUG ===")
        
        return jsonify({
            'success': True,
            'prompt_id': result['prompt_id'],
            'result_id': result['result_id'],
            'step_id': result['result_step_id'],
            'user_id': result['user_id'],
            'created_at': result['created_at'].isoformat() if result['created_at'] else None,
            'session_data': session_data,
            'prompt': prompt_data.get('prompt', {}),
            'api_params': prompt_data.get('api_params', {}),
            'validation_criteria_custom': prompt_data.get('validation_criteria_custom')
        })
        
    except Exception as e:
        logger.error(f"Error fetching prompt detail: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/admin/get-prompt-result/<int:prompt_id>', methods=['GET'])
@admin_required
def get_prompt_result(prompt_id):
    """Récupère la réponse LLM brute associée à un prompt."""
    try:
        cursor = current_app.mysql.connection.cursor(DictCursor)
        
        # Récupérer le prompt
        cursor.execute("""
            SELECT prompt, result_id, result_step_id
            FROM prompt_user
            WHERE prompt_id = %s
        """, (prompt_id,))
        
        prompt_row = cursor.fetchone()
        
        if not prompt_row:
            return jsonify({'success': False, 'error': 'Prompt non trouvé'})
        
        prompt_data = json.loads(prompt_row['prompt'])
        
        # Chercher la réponse LLM dans le prompt
        llm_response = prompt_data.get('llm_response')
        
        if llm_response:
            return jsonify({
                'success': True,
                'has_result': True,
                'llm_response': llm_response,
                'truncated': prompt_data.get('llm_response_truncated', False),
                'full_length': prompt_data.get('llm_response_full_length'),
                'api_duration': prompt_data.get('session_data', {}).get('api_duration_seconds'),
                'result_id': prompt_row['result_id'],
                'step_id': prompt_row['result_step_id']
            })
        else:
            return jsonify({
                'success': True,
                'has_result': False,
                'message': 'Réponse LLM non stockée (prompt antérieur à cette fonctionnalité)',
                'result_id': prompt_row['result_id'],
                'step_id': prompt_row['result_step_id']
            })
        
    except Exception as e:
        logger.error(f"Error getting prompt result: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)})

@quiz_analysis_bp.route('/admin/get-user-generation-history/<int:user_id>/<quiz_id>')
@admin_required
def get_user_generation_history(user_id, quiz_id):
    """Récupère tous les prompts d'un user pour un quiz (peu importe le result_id)."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                prompt_id,
                result_id,
                result_step_id,
                prompt,
                created_at
            FROM prompt_user
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 50
        """, (user_id,))
        
        prompts = cursor.fetchall()
        
        history = []
        for p in prompts:
            try:
                prompt_data = json.loads(p['prompt']) if p['prompt'] else {}
                session_data = prompt_data.get('session_data', {})
                
                # Filtrer par quiz_id si présent dans session_data
                if session_data.get('quiz_id') != quiz_id:
                    continue
                
                history.append({
                    'prompt_id': p['prompt_id'],
                    'result_id': p['result_id'],
                    'step_id': p['result_step_id'],
                    'created_at': p['created_at'].isoformat() if p['created_at'] else None,
                    'prompt_type': session_data.get('prompt_type', 'generation'),
                    'generation_type': session_data.get('generation_type', 'unknown'),
                    'attempt_number': session_data.get('attempt_number', 1),
                    'validation_status': session_data.get('validation_status'),
                    'human_prompt_preview': prompt_data.get('prompt', {}).get('human', '')[:200]
                })
            except Exception as e:
                logger.warning(f"Error parsing prompt {p['prompt_id']}: {e}")
                continue
        
        return jsonify({
            'success': True,
            'user_id': user_id,
            'quiz_id': quiz_id,
            'history': history,
            'total': len(history)
        })
        
    except Exception as e:
        logger.error(f"Error getting user generation history: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/use-for-piste', methods=['POST'])
@login_required
def use_token_for_piste():
    """
    Utilise un token pour débloquer une piste.
    Appelé par le JS quand l'utilisateur clique sur "Utiliser 1 crédit".
    """
    request_id = generate_request_id()
    logger.info(f"[{request_id}] Déblocage de piste demandé")
    
    data = request.json
    token_code = data.get('token_code')
    piste_number = data.get('piste_number')
    quiz_id = data.get('quiz_id')
    user_id = data.get('user_id')
    
    # Si user_id non fourni, utiliser l'utilisateur connecté
    if not user_id:
        user_id = current_user.id
    else:
        user_id = int(user_id)
    
    # Validation des paramètres
    if not all([token_code, piste_number, quiz_id]):
        return jsonify({
            'success': False, 
            'error': 'Paramètres manquants (token_code, piste_number, quiz_id)'
        }), 400
    
    piste_number = int(piste_number)
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Utiliser le service pour débloquer la piste
        piste_service = PisteAccessService(cursor)
        result = piste_service.unlock_piste(
            user_id=user_id,
            quiz_id=quiz_id,
            piste_number=piste_number,
            token_code=token_code
        )
        
        if result['success']:
            mysql.connection.commit()
            logger.info(f"[{request_id}] Piste {piste_number} débloquée pour user {user_id}")
            return jsonify(result)
        else:
            mysql.connection.rollback()
            logger.warning(f"[{request_id}] Échec déblocage: {result.get('error')}")
            return jsonify(result), 400
            
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[{request_id}] Erreur déblocage piste: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
    finally:
        cursor.close()


@quiz_analysis_bp.route('/unlocked-pistes/<string:quiz_id>')
def get_unlocked_pistes_route(quiz_id: str):
    """
    Retourne la liste des pistes débloquées pour l'utilisateur courant.
    Utilisé par le JS pour vérifier l'état après un déblocage.
    """
    user_id = request.args.get('user_id')
    
    if not user_id:
        if current_user.is_authenticated:
            user_id = current_user.id
        else:
            return jsonify({
                'success': False, 
                'error': 'Utilisateur non authentifié'
            }), 401
    
    user_id = int(user_id)
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        piste_service = PisteAccessService(cursor)
        unlocked = piste_service.get_unlocked_pistes(user_id, quiz_id)
        
        return jsonify({
            'success': True,
            'unlocked_pistes': unlocked
        })
        
    except Exception as e:
        logger.error(f"Erreur récupération pistes débloquées: {e}")
        return jsonify({
            'success': False, 
            'error': str(e)
        }), 500
        
    finally:
        cursor.close()

@quiz_analysis_bp.route('/get-progress', methods=['GET'])
@csrf.exempt
def get_progress():
    """Récupère la progression et les interactions précédentes de l'utilisateur."""
    user_id = request.args.get('user_id')
    quiz_id = request.args.get('quiz_id')
    
    if not user_id or not quiz_id:
        return jsonify({'max_section_index': 0, 'interactions': []})
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Progression max
        cursor.execute("""
            SELECT MAX(CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.section_index')) AS UNSIGNED)) as max_idx
            FROM user_analysis_interactions
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND interaction_type = 'section_view'
        """, (int(user_id), quiz_id))
        
        result = cursor.fetchone()
        max_idx = int(result['max_idx']) if result and result['max_idx'] is not None else 0
        
        # Récupérer les interactions précédentes (feedbacks, accuracy, booking)
        cursor.execute("""
            SELECT interaction_type, piste_number, payload
            FROM user_analysis_interactions
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND interaction_type IN ('accuracy_feedback', 'piste_feedback', 'booking_request')
            ORDER BY created_at ASC
        """, (int(user_id), quiz_id))
        
        interactions = []
        for row in cursor.fetchall():
            interactions.append({
                'type': row['interaction_type'],
                'piste_number': row['piste_number'],
                'payload': json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            })
        
        return jsonify({
            'max_section_index': max_idx,
            'interactions': interactions
        })
        
    except Exception as e:
        logger.error(f"Error getting progress: {e}")
        return jsonify({'max_section_index': 0, 'interactions': []})
    finally:
        cursor.close()

@quiz_analysis_bp.route('/track-interaction', methods=['POST'])
@csrf.exempt
def track_interaction():
    """Enregistre une interaction utilisateur sur l'analyse (feedback, clic pack, booking)."""
    data = request.json
    
    user_id = data.get('user_id')
    quiz_id = data.get('quiz_id')
    result_id = data.get('result_id')
    piste_number = data.get('piste_number')
    interaction_type = data.get('interaction_type')
    payload = data.get('payload', {})
    source_page = data.get('source_page')
    
    if not all([user_id, quiz_id, interaction_type, payload]):
        return jsonify({'error': 'Paramètres manquants'}), 400
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO user_analysis_interactions 
            (user_id, quiz_id, result_id, piste_number, interaction_type, payload, source_page)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            int(user_id), quiz_id, result_id, 
            int(piste_number) if piste_number else None,
            interaction_type, json.dumps(payload, ensure_ascii=False), source_page
        ))
        
        mysql.connection.commit()
        # ── Notification Slack pour demande de RDV ──
        if interaction_type == 'booking_request':
            try:
                from services import slack_service, SLACK_AVAILABLE
                if SLACK_AVAILABLE and slack_service:
                    slack_service.send_notification(
                        f"📞 *Nouvelle demande d'appel gratuit !*\n"
                        f"👤 {payload.get('firstname', '')} {payload.get('lastname', '')}\n"
                        f"📧 {payload.get('email', '')}\n"
                        f"📱 {payload.get('phone', '')}\n"
                        f"📦 Pack: {payload.get('pack', '–')}",
                        channel="chat"
                    )
            except Exception as slack_err:
                logger.warning(f"Slack booking notification failed: {slack_err}")

        return jsonify({'success': True})
        
    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error tracking interaction: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()