from flask import Blueprint, jsonify, request, render_template, flash, redirect, url_for, current_app, g, session
from flask_login import login_required, current_user
from services import QuizAnalysisService, AudioService
from utils import generate_request_id, log_json_size, get_or_create_quiz_session
from decorators import check_token_required 
import logging
import json
import time
import uuid
from flask_babel import Babel, gettext as _, lazy_gettext as _l, gettext
import requests
from urllib.parse import quote
from functools import wraps
import os
from MySQLdb.cursors import DictCursor
from datetime import datetime
from extensions import csrf

quiz_bp = Blueprint('quiz', __name__)
logger = logging.getLogger(__name__)

@quiz_bp.route('/check-token/<string:quiz_id>', methods=['GET'])
@login_required
def check_token(quiz_id):
    """
    Vérifie si l'utilisateur possède un token valide ou non pour un quiz spécifique.
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute("""
            SELECT token_code, expiration_date 
            FROM tokens 
            WHERE user_id = %s AND quiz_id = %s 
        """, (current_user.id, quiz_id))
        
        token = cursor.fetchone()
        if token:
            token_code = token['token_code']
            expiration_date = token['expiration_date']  
            return jsonify({
                'has_token': True,
                'expiration_date': expiration_date.isoformat() if expiration_date else None,
                'token_code': token_code
            }), 200
            
        return jsonify({'has_token': False}), 200

    except Exception as e:
        logger.error(f"Error checking token: {str(e)}")
        return jsonify({'error': _('An error occurred while checking the token')}), 500

    finally:
        cursor.close()


@quiz_bp.route('/check-dashboard-state/<string:quiz_id>', methods=['GET'])
@login_required
def check_dashboard_state(quiz_id):
    """
    Vérifie l'état actuel du quiz et des tokens pour gérer l'affichage du dashboard
    """
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # 1. Vérifier si l'utilisateur a un token valide
        cursor.execute("""
            SELECT token_code 
            FROM tokens 
            WHERE user_id = %s AND quiz_id = %s 
            AND is_used = FALSE 
            AND (expiration_date IS NULL OR expiration_date > NOW())
        """, (current_user.id, quiz_id))
        has_token = bool(cursor.fetchone())

        # 2. Vérifier l'état du quiz et l'existence d'une analyse
        cursor.execute("""
            SELECT qu.quiz_status,
                   (EXISTS (
                       SELECT 1
                       FROM result_user ru
                       WHERE ru.quiz_id = qu.quiz_id
                       AND ru.user_id = qu.user_id
                       AND ru.is_active = TRUE
                   )) as has_analysis
            FROM quiz_user qu
            WHERE qu.user_id = %s AND qu.quiz_id = %s
            ORDER BY qu.updated_at DESC 
            LIMIT 1
        """, (current_user.id, quiz_id))
        
        quiz_state = cursor.fetchone()
        
        response = {
            'has_token': has_token,
            'state': {
                'quiz_status': quiz_state['quiz_status'] if quiz_state else 'not_started',
                'has_analysis': bool(quiz_state['has_analysis']) if quiz_state else False
            }
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error checking dashboard state: {str(e)}")
        return jsonify({'error': str(e)}), 500

    finally:
        cursor.close()

@quiz_bp.route('/quiz')
@login_required
@check_token_required
def display_quiz():
    quiz_id = request.args.get('quiz_id')
    resume = request.args.get('resume', 'false').lower() == 'true'
    show_recap = request.args.get('show_recap', 'false').lower() == 'true'
    request_id = generate_request_id()
    
    logger.info(f"[Request ID: {request_id}] Début display_quiz - quiz_id: {quiz_id}, resume: {resume}, show_recap: {show_recap}")
    
    if not quiz_id:
        logger.warning(f"[Request ID: {request_id}] Quiz ID manquant")
        flash(_("Quiz ID is required"), 'error')
        return redirect(url_for('auth.dashboard'))

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer la session existante ou en créer une nouvelle
        quiz_session_id = get_or_create_quiz_session(cursor, current_user.id, quiz_id)
        logger.info(f"[Request ID: {request_id}] Session ID: {quiz_session_id}")

        # Vérifier si le quiz est déjà complété
        cursor.execute("""
            SELECT quiz_status, questions_answered_count, question_history, updated_at
            FROM quiz_user 
            WHERE quiz_session_id = %s
        """, (quiz_session_id,))
        current_session = cursor.fetchone()

        # Si le quiz est complété et qu'on ne demande pas de récap, rediriger
        if current_session and current_session['quiz_status'] == 'completed' and not show_recap:
            logger.info(f"[Request ID: {request_id}] Quiz déjà complété, redirection vers dashboard")
            flash(_("This quiz is already completed"), 'info')
            return redirect(url_for('auth.dashboard'))

        if resume:
            # Récupérer les informations de la session
            cursor.execute("""
                SELECT quiz_status, questions_answered_count, question_history,
                    EXISTS (
                        SELECT 1 
                        FROM result_user 
                        WHERE user_id = %s AND quiz_id = %s AND is_active = TRUE
                    ) as has_analysis
                FROM quiz_user
                WHERE quiz_session_id = %s
            """, (current_user.id, quiz_id, quiz_session_id))
            
            session_info = cursor.fetchone()
            logger.info(f"[Request ID: {request_id}] Session info: {session_info}")
            
            if session_info and session_info['question_history']:
                try:
                    question_history = json.loads(session_info['question_history'])
                    if question_history:
                        # Mettre à jour le compteur de questions répondues
                        new_count = len(question_history)
                        cursor.execute("""
                            UPDATE quiz_user 
                            SET questions_answered_count = %s,
                                quiz_status = 'in_progress',
                                updated_at = CURRENT_TIMESTAMP
                            WHERE quiz_session_id = %s
                        """, (new_count, quiz_session_id))
                        mysql.connection.commit()
                        logger.info(f"[Request ID: {request_id}] Mise à jour compteur: {new_count} questions")
                except json.JSONDecodeError as e:
                    logger.error(f"[Request ID: {request_id}] Erreur décodage historique: {e}")

        # Récupérer les questions du quiz
        cursor.execute("""
            SELECT quiz_type, description 
            FROM quiz_catalog 
            WHERE quiz_id = %s
        """, (quiz_id,))
        quiz = cursor.fetchone()
        
        if not quiz:
            logger.warning(f"[Request ID: {request_id}] Quiz non trouvé: {quiz_id}")
            flash(_("Quiz not found"), 'error')
            return redirect(url_for('auth.dashboard'))

        # Récupérer la dernière session avec analyse
        cursor.execute("""
            SELECT qu.quiz_id, ru.created_at IS NOT NULL as has_analysis
            FROM quiz_user qu
            LEFT JOIN result_user ru ON qu.quiz_id = ru.quiz_id AND qu.user_id = ru.user_id AND ru.is_active = TRUE
            WHERE qu.user_id = %s AND qu.quiz_status = 'completed'
            ORDER BY qu.updated_at DESC
            LIMIT 1
        """, (current_user.id,))
        last_completed = cursor.fetchone()

        # Compter le nombre total de questions
        cursor.execute("""
            SELECT COUNT(*) as total_questions
            FROM quiz_questions
            WHERE quiz_id = %s
        """, (quiz_id,))
        total_questions = cursor.fetchone()['total_questions']

        logger.info(f"[Request ID: {request_id}] Rendu template avec resume={resume}, show_recap={show_recap}")
        return render_template(
            'quiz/quiz.html',
            quiz_id=quiz_id,
            quiz_type=quiz.get('quiz_type'),
            description=quiz.get('description'),
            resume=resume,
            show_recap=show_recap,
            session_info=session_info if resume else None,
            last_completed_quiz=last_completed,
            total_questions=total_questions
        )

    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Erreur: {str(e)}", exc_info=True)
        mysql.connection.rollback()
        flash(_("An error occurred while loading the quiz"), 'error')
        return redirect(url_for('auth.dashboard'))
    
    finally:
        cursor.close()


@quiz_bp.route('/get_questions/')
@login_required
@check_token_required
def get_questions():
    quiz_id = request.args.get('quiz_id')
    if not quiz_id:
        logger.warning("Quiz ID manquant dans la requête /get_questions/")
        return jsonify({"error": "Quiz ID is required"}), 400
    logger.info(f"Début de la requête /get_questions/ pour quiz_id: {quiz_id}")
    logger.info(f"User: {current_user.id} - {current_user.username}")

    mysql = current_app.mysql
    cursor = mysql.connection.cursor()

    try:
        logger.info("Exécution de la requête principale...")
        cursor.execute('''
            SELECT q.question_id, q.question, q.media_type, q.media_url, q.country_code, 
                q.question_type, q.max_choices, q.min_choices, 
                q.parent_question_id, q.is_conditional, q.condition_value, q.hint,
                q.question_description
            FROM quiz_questions qq
            JOIN questions_catalog q ON qq.question_id = q.question_id
            WHERE qq.quiz_id = %s
            AND qq.is_active = TRUE
            AND q.is_active = TRUE
            ORDER BY qq.question_ranking
        ''', (quiz_id,))
        questions = cursor.fetchall()
        if not questions:
            logger.warning(f"Aucune question trouvée pour le quiz {quiz_id}")
            return jsonify({"error": "Aucune question trouvée"}), 404

        logger.info(f"Récupéré {len(questions)} questions")

        formatted_questions = []
        for i, q in enumerate(questions):
            try:
                logger.info(f"Traitement de la question {i+1}/{len(questions)} (ID: {q[0]})")

                cursor.execute('''
                    SELECT choice_value, choice_text, choice_media_type, choice_media_url, 
                        max_character_input, next_question_id, choice_description
                    FROM questions_choices
                    WHERE question_id = %s
                ''', (q[0],))
                choices = cursor.fetchall()
                logger.info(f"Récupéré {len(choices)} choix pour la question {q[0]}")

                # Décodage de condition_value avec gestion d'erreur
                condition_value = None
                if q[10]:
                    try:
                        condition_value = json.loads(q[10])
                        logger.info(f"condition_value décodé pour question {q[0]}: {condition_value}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Erreur de décodage JSON pour condition_value de la question {q[0]}: {e}")

                # Pour les questions de type free_text
                max_character_input = None
                if q[5] == 'free_text' and choices:
                    max_character_input = choices[0][4]
                    logger.info(f"max_character_input pour question free_text {q[0]}: {max_character_input}")

                formatted_question = {
                    "id": q[0],
                    "question": q[1],
                    "media_type": q[2],
                    "media_url": q[3],
                    "country_code": q[4],
                    "question_type": q[5],
                    "max_choices": q[6],
                    "min_choices": q[7],
                    "parent_question_id": q[8],
                    "is_conditional": bool(q[9]),
                    "condition_value": condition_value,
                    "question_description": q[12] if len(q) > 12 else None,
                    "max_character_input": max_character_input,
                    "choices": [{
                        "value": str(c[0]),
                        "text": c[1],
                        "choice_media_type": c[2],
                        "choice_media_url": c[3].strip('"') if c[3] else None,
                        "max_character_input": c[4],
                        "next_question_id": c[5],
                        "choice_description": c[6] if len(c) > 6 else None
                    } for c in choices]
                }

                formatted_questions.append(formatted_question)
                logger.info(f"Question {q[0]} formatée avec succès")

            except Exception as e:
                logger.error(f"Erreur lors du traitement de la question {q[0]}: {str(e)}", exc_info=True)
                raise

        response_data = {"questions": formatted_questions}
        logger.info(f"Envoi de la réponse avec {len(formatted_questions)} questions formatées")

        # Log de la taille de la réponse
        response_size = len(json.dumps(response_data))
        logger.info(f"Taille de la réponse: {response_size} octets")

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Erreur critique dans get_questions pour quiz {quiz_id}: {str(e)}", exc_info=True)
        return jsonify({
            "error": "Une erreur est survenue lors de la récupération des questions",
            "details": str(e) if os.getenv('FLASK_DEBUG') == 'True' else None
        }), 500

    finally:
        cursor.close()
        logger.info("Fin de get_questions - Connexion fermée")


@quiz_bp.route('/update_quiz_progress', methods=['POST'])
@login_required
@check_token_required
def update_quiz_progress():
    data = request.json
    logger.info(f"Données reçues: {data}")

    quiz_id = data.get('quiz_id')
    current_question_index = data.get('current_question_index')
    answer = data.get('answer')
    is_completed = data.get('is_completed', False)
    is_reviewing = data.get('is_reviewing', False)

    if not all([quiz_id, isinstance(current_question_index, int), answer]):
        logger.error("Données manquantes dans la requête")
        return jsonify({"error": _("Missing required data")}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        quiz_session_id = get_or_create_quiz_session(cursor, current_user.id, quiz_id)
        logger.info(f"Session ID obtenue/créée: {quiz_session_id}")

        # D'abord récupérer l'historique actuel
        cursor.execute('''
            SELECT question_history
            FROM quiz_user
            WHERE quiz_session_id = %s
        ''', (quiz_session_id,))
        
        current_history = cursor.fetchone()
        history = json.loads(current_history['question_history'] if current_history and current_history['question_history'] else '[]')

        if not is_reviewing:
            new_questions_answered = max(current_question_index + 1, len(history))
            new_status = 'answers_review' if is_completed else 'in_progress'
            
            # Ajouter l'index actuel à l'historique s'il n'y est pas déjà
            if current_question_index not in history:
                history.append(current_question_index)
            
            # Mise à jour avec le nouvel historique
            cursor.execute('''
                UPDATE quiz_user 
                SET questions_answered_count = %s, 
                    quiz_status = %s,
                    question_history = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            ''', (new_questions_answered, new_status, json.dumps(history), quiz_session_id))

        answer_value = answer.get('value')
        if not isinstance(answer_value, list):
            answer_value = [answer_value]

        answer_value_json = json.dumps(answer_value)
        answer_text = answer.get('text', '')

        # Mettre à jour ou insérer la réponse
        cursor.execute('''
            INSERT INTO answer_user 
            (quiz_session_id, question_id, answer_value, answer_text) 
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                answer_value = VALUES(answer_value),
                answer_text = VALUES(answer_text),
                updated_at = CURRENT_TIMESTAMP
        ''', (quiz_session_id, answer.get('question_id'), answer_value_json, answer_text))

        mysql.connection.commit()
        logger.info(f"answer_user mis à jour pour la session {quiz_session_id}")
        logger.info(f"Historique mis à jour: {history}")

        # Récupérer toutes les réponses mises à jour
        cursor.execute('''
            SELECT au.question_id, au.answer_value, au.answer_text, qc.question_type
            FROM answer_user au
            JOIN questions_catalog qc ON au.question_id = qc.question_id
            WHERE au.quiz_session_id = %s
        ''', (quiz_session_id,))

        answers = {}
        for row in cursor.fetchall():
            try:
                if row['question_type'] == 'free_text':
                    answer_value = [row['answer_text']] if row['answer_text'] else []
                else:
                    answer_value = json.loads(row['answer_value']) if row['answer_value'] else []

                answers[str(row['question_id'])] = {
                    'value': answer_value,
                    'text': row['answer_text']
                }
            except json.JSONDecodeError:
                logger.error(f"Erreur décodage JSON pour question {row['question_id']}")
                continue

        return jsonify({
            "message": _("Answer updated successfully"),
            "answers": answers
        }), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Erreur lors de la mise à jour: {str(e)}", exc_info=True)
        return jsonify({"error": _("An error occurred while updating")}), 500

    finally:
        cursor.close()


@quiz_bp.route('/update_quiz_history', methods=['POST'])
@login_required
@check_token_required
def update_quiz_history():
    """
    Met à jour l'historique des questions (question_history) pour une session de quiz spécifique.
    L'historique contient les indices des questions plutôt que leurs IDs.
    """
    data = request.json
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Données reçues pour la mise à jour de l'historique: {data}")

    quiz_id = data.get('quiz_id')
    question_history = data.get('question_history', [])

    if not quiz_id or not isinstance(question_history, list):
        logger.error(f"[Request ID: {request_id}] Données manquantes ou incorrectes")
        return jsonify({"error": _("Invalid data provided")}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        quiz_session_id = get_or_create_quiz_session(cursor, current_user.id, quiz_id)
        logger.info(f"[Request ID: {request_id}] Session ID obtenue/créée: {quiz_session_id}")

        # Récupérer le nombre total de questions pour le quiz
        cursor.execute('''
            SELECT COUNT(*) as question_count
            FROM quiz_questions 
            WHERE quiz_id = %s
        ''', (quiz_id,))
        total_questions = cursor.fetchone()['question_count']

        # Récupérer l'historique existant
        cursor.execute('''
            SELECT question_history
            FROM quiz_user
            WHERE quiz_session_id = %s
        ''', (quiz_session_id,))
        existing = cursor.fetchone()
        existing_history = json.loads(existing['question_history'] or '[]') if existing else []

        # Fusionner les historiques sans doublon
        merged_history = existing_history.copy()
        for q_index in question_history:
            if q_index not in merged_history and isinstance(q_index, int) and 0 <= q_index < total_questions:
                merged_history.append(q_index)

        logger.info(f"[Request ID: {request_id}] Historique existant: {existing_history}")
        logger.info(f"[Request ID: {request_id}] Nouvel historique: {question_history}")
        logger.info(f"[Request ID: {request_id}] Historique fusionné: {merged_history}")

        # Mettre à jour l'historique
        cursor.execute('''
            UPDATE quiz_user 
            SET question_history = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE quiz_session_id = %s
        ''', (json.dumps(merged_history), quiz_session_id))

        mysql.connection.commit()
        logger.info(f"[Request ID: {request_id}] Historique final mis à jour: {merged_history}")

        return jsonify({
            "message": _("Quiz history updated successfully"),
            "question_history": merged_history
        }), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[Request ID: {request_id}] Erreur lors de la mise à jour de l'historique: {str(e)}", exc_info=True)
        return jsonify({"error": _("An error occurred while updating the quiz history")}), 500

    finally:
        cursor.close()
        
def shouldShowConditionalQuestion(cursor, parent_question_id, quiz_session_id):
    """Vérifie si une question conditionnelle doit être affichée."""
    try:
        cursor.execute('''
            SELECT answer_value
            FROM answer_user
            WHERE quiz_session_id = %s AND question_id = %s
        ''', (quiz_session_id, parent_question_id))
        
        result = cursor.fetchone()
        if not result or not result['answer_value']:
            return False
            
        # Vérifier si la réponse correspond aux conditions
        parent_answer = json.loads(result['answer_value'])
        
        cursor.execute('''
            SELECT condition_value
            FROM questions_catalog
            WHERE parent_question_id = %s
        ''', (parent_question_id,))
        
        condition = cursor.fetchone()
        if not condition or not condition['condition_value']:
            return False
            
        condition_value = json.loads(condition['condition_value'])
        
        # Si la condition est un tableau
        if isinstance(condition_value, list):
            return any(str(value) in parent_answer for value in condition_value)
        
        # Si la condition est une valeur simple
        return str(condition_value) in parent_answer
        
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Error checking conditional question: {str(e)}")
        return False

@quiz_bp.route('/get_quiz_progress/<string:quiz_id>')
@login_required
@check_token_required
def get_quiz_progress(quiz_id):
    request_id = generate_request_id()
    logger.info(f"[Request ID: {request_id}] Récupération progression quiz: {quiz_id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Obtenir la session de quiz la plus récente
        cursor.execute('''
            SELECT 
                qu.quiz_session_id,
                qu.questions_answered_count,
                qu.quiz_status,
                qu.question_history,
                qu.updated_at,
                EXISTS (
                    SELECT 1
                    FROM result_user ru
                    WHERE ru.quiz_id = qu.quiz_id
                    AND ru.user_id = qu.user_id
                    AND ru.is_active = TRUE
                ) as has_analysis
            FROM quiz_user qu
            WHERE qu.quiz_id = %s AND qu.user_id = %s
            ORDER BY qu.updated_at DESC 
            LIMIT 1
        ''', (quiz_id, current_user.id))

        result = cursor.fetchone()
        logger.info(f"[Request ID: {request_id}] Session trouvée: {result}")

        if not result:
            logger.info(f"[Request ID: {request_id}] Pas de session existante, renvoi état initial")
            return jsonify({
                "progress": {
                    'questions_answered_count': 0,
                    'quiz_status': 'not_started',
                    'has_analysis': False,
                    'question_history': []
                },
                "answers": {},
                "quiz_completed": False
            }), 200

        quiz_session_id = result['quiz_session_id']
        question_history = json.loads(result['question_history'] or '[]')

        # Assurer la cohérence entre l'historique et le compteur
        if len(question_history) != result['questions_answered_count']:
            new_count = len(question_history)
            cursor.execute("""
                UPDATE quiz_user
                SET questions_answered_count = %s
                WHERE quiz_session_id = %s
            """, (new_count, quiz_session_id))
            mysql.connection.commit()
            result['questions_answered_count'] = new_count

        # Récupérer les réponses
        cursor.execute('''
            SELECT 
                au.question_id,
                au.answer_value,
                au.answer_text,
                qc.question_type
            FROM answer_user au
            JOIN questions_catalog qc ON au.question_id = qc.question_id
            WHERE au.quiz_session_id = %s
        ''', (quiz_session_id,))

        answers = {}
        for row in cursor.fetchall():
            try:
                if row['question_type'] == 'free_text':
                    answer_value = [row['answer_text']] if row['answer_text'] else []
                else:
                    answer_value = json.loads(row['answer_value']) if row['answer_value'] else []

                answers[str(row['question_id'])] = {
                    'value': answer_value,
                    'text': row['answer_text']
                }
            except json.JSONDecodeError:
                logger.error(f"[Request ID: {request_id}] Erreur décodage JSON pour question {row['question_id']}")
                continue

        response_data = {
            "progress": {
                'questions_answered_count': result['questions_answered_count'],
                'quiz_status': result['quiz_status'],
                'has_analysis': bool(result['has_analysis']),
                'question_history': question_history
            },
            "answers": answers,
            "quiz_completed": result['quiz_status'] in ['completed', 'answers_review']
        }

        logger.info(f"[Request ID: {request_id}] Données de progression: {response_data}")
        return jsonify(response_data), 200

    except Exception as e:
        logger.error(f"[Request ID: {request_id}] Erreur: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred while retrieving quiz progress"}), 500

    finally:
        cursor.close()

@quiz_bp.route('/api/cities')
def get_cities():
    search_term = request.args.get('search', '').strip()
    if len(search_term) < 3:
        return jsonify([])
        
    try:
        url = "https://nominatim.openstreetmap.org/search"
        
        params = {
            'q': search_term,
            'format': 'jsonv2',  # Changé pour format jsonv2 qui est plus stable
            'addressdetails': 1,
            'countrycodes': 'fr',
            'limit': 5,
            'featuretype': 'city'
        }
        
        headers = {
            'User-Agent': 'tilto-QuizApp/1.0 (contact@tilto.ai)',
            'Accept': 'application/json',
            'Accept-Language': 'fr'
        }

        timeout = current_app.config.get('API_TIMEOUT', 5)

        response = requests.get(
            url, 
            params=params, 
            headers=headers,
            timeout=timeout
        )
        response.raise_for_status()

        # Vérification du content-type
        content_type = response.headers.get('Content-Type', '')
        if 'application/json' not in content_type:
            logger.error(f"Réponse non-JSON reçue: {content_type}")
            return jsonify([])

        results = response.json()
        
        formatted_results = []
        for result in results:
            if not isinstance(result, dict):
                continue

            address = result.get('address', {})
            city_name = address.get('city') or address.get('town') or address.get('village')
            
            if city_name:
                formatted_results.append({
                    'name': city_name,
                    'region': address.get('state', ''),
                    'display_name': result.get('display_name', ''),
                    'lat': result.get('lat'),
                    'lon': result.get('lon')
                })
        
        return jsonify(formatted_results)
        
    except requests.Timeout:
        logger.error("Timeout lors de la requête à Nominatim")
        return jsonify([])
    except requests.RequestException as e:
        logger.error(f"Erreur lors de la requête à Nominatim: {str(e)}")
        return jsonify([])
    except Exception as e:
        logger.error(f"Erreur lors de la recherche des villes: {str(e)}")
        return jsonify([])


@quiz_bp.route('/quiz-recap/<string:quiz_id>')
@login_required
@check_token_required
def quiz_recap(quiz_id):
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        # Vérifier la session et récupérer l'historique réel des questions répondues
        cursor.execute('''
            SELECT qu.quiz_session_id, qu.questions_answered_count, qu.quiz_status,
                   qu.question_history,
                   (SELECT COUNT(*) FROM answer_user au WHERE au.quiz_session_id = qu.quiz_session_id) as actual_answers_count
            FROM quiz_user qu
            WHERE qu.quiz_id = %s AND qu.user_id = %s
            ORDER BY qu.updated_at DESC
            LIMIT 1
        ''', (quiz_id, current_user.id))
        
        session = cursor.fetchone()
        
        if not session:
            logger.warning(f"No quiz session found for user {current_user.id} and quiz {quiz_id}")
            flash(_("Aucune session de quiz n'a été trouvée."), 'warning')
            return redirect(url_for('auth.dashboard'))

        # Si le statut n'est pas 'completed' ou 'answers_review', rediriger vers le quiz
        if session['quiz_status'] not in ['completed', 'answers_review']:
            return redirect(url_for('quiz.display_quiz', 
                                  quiz_id=quiz_id, 
                                  resume='true'))

        # **Ajout de la Mise à Jour du Statut à 'answers_review'**
        if session['quiz_status'] != 'answers_review':
            cursor.execute('''
                UPDATE quiz_user
                SET quiz_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quiz_session_id = %s
            ''', ('answers_review', session['quiz_session_id']))
            mysql.connection.commit()
            logger.info(f"Statut du quiz mis à jour à 'answers_review' pour la session {session['quiz_session_id']}")

            # Mettre à jour la variable locale pour refléter le nouveau statut
            session['quiz_status'] = 'answers_review'

        question_history = json.loads(session['question_history'] or '[]')
        
        # Vérifier si le quiz est réellement terminé en se basant sur les réponses et l'historique
        if session['quiz_status'] != 'completed' and len(question_history) > 0:
            # Trouver la dernière question répondue
            last_question_index = question_history[-1]
            
            # Rediriger vers cette question si ce n'est pas la dernière possible
            cursor.execute('''
                SELECT q.question_id, q.is_conditional, q.parent_question_id
                FROM quiz_questions qq
                JOIN questions_catalog q ON qq.question_id = q.question_id
                WHERE qq.quiz_id = %s
                ORDER BY qq.question_ranking DESC
                LIMIT 1
            ''', (quiz_id,))
            
            last_possible_question = cursor.fetchone()
            
            if last_possible_question and last_possible_question['question_id'] != last_question_index:
                # Vérifier s'il reste des questions non conditionnelles ou des questions conditionnelles applicables
                if not last_possible_question['is_conditional'] or (
                    last_possible_question['is_conditional'] and 
                    shouldShowConditionalQuestion(cursor, last_possible_question['parent_question_id'], session['quiz_session_id'])
                ):
                    logger.warning(f"Quiz not completed. Redirecting to question {last_question_index}")
                    return redirect(url_for('quiz.display_quiz', 
                                         quiz_id=quiz_id, 
                                         resume='true'))

        # Récupérer uniquement les questions qui ont été répondues
        cursor.execute('''
            SELECT DISTINCT q.question_id, q.question, q.question_type
            FROM quiz_questions qq
            JOIN questions_catalog q ON qq.question_id = q.question_id
            JOIN answer_user au ON q.question_id = au.question_id
            WHERE qq.quiz_id = %s AND au.quiz_session_id = %s
            ORDER BY qq.question_ranking
        ''', (quiz_id, session['quiz_session_id']))
        
        questions = cursor.fetchall()
        
        if not questions:
            flash(_("Aucune réponse n'a été trouvée."), 'warning')
            return redirect(url_for('quiz.display_quiz', quiz_id=quiz_id))

        # Récupérer les choix pour chaque question répondue
        questions_with_choices = []
        for q in questions:
            cursor.execute('''
                SELECT choice_value, choice_text
                FROM questions_choices
                WHERE question_id = %s
            ''', (q['question_id'],))
            choices = cursor.fetchall()
            q['choices'] = {str(c['choice_value']): c['choice_text'] for c in choices}
            questions_with_choices.append(q)

        # Récupérer les réponses de l'utilisateur
        cursor.execute('''
            SELECT au.question_id, au.answer_value, au.answer_text
            FROM answer_user au
            WHERE au.quiz_session_id = %s
        ''', (session['quiz_session_id'],))
        
        user_answers = {}
        for answer in cursor.fetchall():
            try:
                answer_value = json.loads(answer['answer_value']) if answer['answer_value'] else []
                if isinstance(answer_value, str):
                    answer_value = [answer_value]
                elif not isinstance(answer_value, list):
                    answer_value = list(answer_value)
            except (json.JSONDecodeError, TypeError):
                answer_value = [answer['answer_value']] if answer['answer_value'] else []
                
            user_answers[answer['question_id']] = {
                'value': answer_value,
                'text': answer['answer_text']
            }

        return render_template(
            'quiz/quiz-recap.html',
            questions=questions_with_choices,
            user_answers=user_answers,
            quiz_id=quiz_id,
            quiz_status=session['quiz_status']  # Utiliser le statut mis à jour
        )

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"Error displaying quiz recap: {str(e)}", exc_info=True)
        flash(_("Une erreur est survenue lors du chargement du récapitulatif."), 'error')
        return redirect(url_for('auth.dashboard'))

    finally:
        cursor.close()

@quiz_bp.route('/check-token-status/<string:quiz_id>', methods=['GET'])
@login_required
def check_token_status(quiz_id):
    logger.info(f"=== DÉBUT CHECK TOKEN STATUS ===")
    logger.info(f"Quiz ID: {quiz_id}")
    logger.info(f"User ID: {current_user.id}")
    
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)
    
    try:
        # 1. Vérifier s'il existe des tokens disponibles
        cursor.execute("""
            SELECT COUNT(*) as token_count
            FROM tokens
            WHERE user_id = %s 
              AND quiz_id = %s
              AND is_used = FALSE
              AND (expiration_date IS NULL OR expiration_date > NOW())
        """, (current_user.id, quiz_id))
        
        token_count_result = cursor.fetchone()
        token_count = token_count_result['token_count'] if token_count_result else 0

        # Récupérer les détails du premier token disponible si existe
        available_token = None
        if token_count > 0:
            cursor.execute("""
                SELECT token_code, token_type, expiration_date
                FROM tokens
                WHERE user_id = %s 
                  AND quiz_id = %s
                  AND is_used = FALSE
                  AND (expiration_date IS NULL OR expiration_date > NOW())
                ORDER BY created_at DESC
                LIMIT 1
            """, (current_user.id, quiz_id))
            available_token = cursor.fetchone()

        logger.info(f"Nombre de tokens disponibles: {token_count}")

        # 2. Vérifier s'il existe une analyse
        cursor.execute("""
        WITH FirstStep AS (
            SELECT result_step_id
            FROM quiz_result
            WHERE quiz_id = %s
            AND is_active = TRUE
            AND result_step_ranking = 1
            LIMIT 1
        ),
        AnalysisSteps AS (
            SELECT DISTINCT
                ru.result_id,
                ru.token_id,
                ru.created_at,
                fs.result_step_id,
                (
                    SELECT COUNT(*) 
                    FROM quiz_result 
                    WHERE quiz_id = %s 
                    AND is_active = TRUE
                ) as total_steps,
                (
                    SELECT COUNT(*) 
                    FROM result_user ru2 
                    WHERE ru2.token_id = ru.token_id
                    AND ru2.is_active = TRUE
                ) as completed_steps,
                t.is_used as token_used,
                CASE 
                    WHEN t.is_used = TRUE AND (
                        SELECT COUNT(*) 
                        FROM result_user ru2 
                        WHERE ru2.token_id = ru.token_id
                        AND ru2.is_active = TRUE
                    ) < (
                        SELECT COUNT(*) 
                        FROM quiz_result 
                        WHERE quiz_id = %s 
                        AND is_active = TRUE
                    ) THEN TRUE
                    ELSE FALSE
                END as token_incorrectly_used
            FROM result_user ru
            JOIN tokens t ON ru.token_id = t.token_code
            CROSS JOIN FirstStep fs
            WHERE ru.quiz_id = %s 
            AND ru.user_id = %s
            AND ru.is_active = TRUE
            AND ru.result_step_id = fs.result_step_id
        )
            SELECT * 
            FROM AnalysisSteps
            WHERE completed_steps > 0
            ORDER BY created_at DESC
            LIMIT 1
        """, (quiz_id, quiz_id, quiz_id, quiz_id, current_user.id))
        
        analysis = cursor.fetchone()
        logger.info(f"Analyse trouvée: {analysis}")

        response_data = {}
        buttons = []

        if analysis and analysis.get('token_incorrectly_used'):
            response_data['warning_message'] = _('Un problème a été détecté avec votre token. Veuillez contacter le support.')

        # Toujours ajouter le bouton "Revenir aux réponses"
        buttons.append({
            'label': _('Revenir aux réponses'),
            'url': url_for('quiz.display_quiz', quiz_id=quiz_id, show_recap='true'),
            'type': 'secondary'
        })

        if analysis:
            is_complete = analysis['completed_steps'] == analysis['total_steps']
            logger.info(f"Analyse {'complète' if is_complete else 'en cours'} - "
                       f"Steps: {analysis['completed_steps']}/{analysis['total_steps']}")

            if is_complete:
                # Analyse complète
                buttons.append({
                    'label': _('Voir mon analyse'),
                    'url': url_for('quiz_analysis.view_analysis',
                                 quiz_id=quiz_id,
                                 result_id=analysis['result_id'],
                                 step_id=analysis['result_step_id']),
                    'type': 'primary'
                })

                if available_token:
                    buttons.append({
                        'label': _('Générer une nouvelle analyse'),
                        'url': '#',
                        'type': 'secondary'
                    })
                    info_message = _('Il vous reste %(count)d analyse(s) disponible(s).', count=token_count)
                else:
                    buttons.append({
                        'label': _('Aller à la boutique'),
                        'url': url_for('tokens.shop'),
                        'type': 'secondary'
                    })
                    info_message = _('Pour générer une nouvelle analyse, rendez-vous dans la boutique.')

                response_data = {
                    'has_token': available_token is not None,
                    'token_in_progress': False,
                    'primary_message': _('Votre dernière analyse est prête.'),
                    'message_type': 'success',
                    'info_message': info_message,
                    'token_code': analysis['token_id'],
                    'view_analysis_url': url_for('quiz_analysis.view_analysis',
                                               quiz_id=quiz_id,
                                               result_id=analysis['result_id'],
                                               step_id=analysis['result_step_id']),
                    'buttons': buttons
                }
            else:
                # Analyse en cours
                remaining_steps = analysis['total_steps'] - analysis['completed_steps']

                if available_token:
                    buttons.extend([
                        {
                            'label': _('Générer une nouvelle analyse'),
                            'url': '#',
                            'type': 'secondary'
                        },
                        {
                            'label': _('Poursuivre mon analyse en cours'),
                            'url': url_for('quiz_analysis.view_analysis',
                                        quiz_id=quiz_id,
                                        result_id=analysis['result_id'],
                                        step_id=analysis['result_step_id']),
                            'type': 'primary'
                        }
                    ])
                else:
                    buttons.extend([
                        {
                            'label': _('Aller à la boutique'),
                            'url': url_for('tokens.shop'),
                            'type': 'secondary'
                        },
                        {
                            'label': _('Poursuivre mon analyse en cours'),
                            'url': url_for('quiz_analysis.view_analysis',
                                        quiz_id=quiz_id,
                                        result_id=analysis['result_id'],
                                        step_id=analysis['result_step_id']),
                            'type': 'primary'
                        }
                    ])

                response_data = {
                    'has_token': available_token is not None,
                    'token_in_progress': True,
                    'primary_message': _('Il vous reste une analyse en cours avec %(remaining)d étape(s) à générer', 
                                     remaining=remaining_steps),
                    'message_type': 'info',
                    'info_message': _('Il vous reste %(count)d analyse(s) disponible(s).', count=token_count) if available_token else None,
                    'token_code': analysis['token_id'],
                    'buttons': buttons,
                    'steps_info': {
                        'completed': analysis['completed_steps'],
                        'total': analysis['total_steps']
                    }
                }

        elif available_token:
            # Pas d'analyse mais token disponible
            analyse_word = 'analyse' if token_count == 1 else 'analyses'
            response_data = {
                'has_token': True,
                'token_in_progress': False,
                'primary_message': _('Il vous reste %(count)d %(word)s disponible%(plural)s', 
                                  count=token_count, 
                                  word=analyse_word,
                                  plural='s' if token_count > 1 else ''),
                'message_type': 'success',
                'buttons': buttons + [{
                    'label': _('Lancer l\'analyse'),
                    'url': '#',
                    'type': 'primary'
                }]
            }

        else:
            # Ni analyse ni token
            response_data = {
                'has_token': False,
                'token_in_progress': False,
                'primary_message': _('Vous n\'avez pas d\'analyse disponible.'),
                'message_type': 'warning',
                'info_message': _('Rendez-vous dans la boutique pour obtenir une nouvelle analyse.'),
                'shop_url': url_for('tokens.shop'),
                'buttons': buttons + [{
                    'label': _('Aller à la boutique'),
                    'url': url_for('tokens.shop'),
                    'type': 'primary'
                }]
            }

        return jsonify(response_data), 200

    except Exception as e:
        logger.error("=== ERREUR CHECK TOKEN STATUS ===")
        logger.error(f"Type d'erreur: {type(e).__name__}")
        logger.error(f"Message d'erreur: {str(e)}")
        logger.error("Stack trace:", exc_info=True)
        return jsonify({'error': _('Une erreur est survenue lors de la vérification du statut')}), 500
        
    finally:
        cursor.close()

@quiz_bp.route('/api/transcribe-whisper', methods=['POST'])
@csrf.exempt
def transcribe_whisper():
    """
    Endpoint pour transcrire un fichier audio en texte en utilisant OpenAI Whisper API.
    """
    if 'audio' not in request.files:
        return jsonify({'error': _('Aucun fichier audio fourni')}), 400
    
    audio_file = request.files['audio']
    result = AudioService.transcribe_with_whisper(audio_file)
    
    if result.get('success'):
        return jsonify({
            'success': True,
            'transcript': result.get('transcript')
        })
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', _('Erreur lors de la transcription'))
        }), 500



@quiz_bp.route('/get_questions_homepage/', methods=['GET'])
def get_questions_homepage():
    """Version non-authentifiée pour la homepage"""
    
    # Vérification de debug pour s'assurer que la route est appelée
    logger.info("=== ROUTE get_questions_homepage APPELÉE ===")
    
    quiz_id = request.args.get('quiz_id', 'pack_clarte')
    logger.info(f"Quiz ID reçu: {quiz_id}")
    
    # Vérification de la connexion MySQL
    if not hasattr(current_app, 'mysql') or not current_app.mysql:
        logger.error("Connexion MySQL non disponible")
        return jsonify({"error": "Database connection not available"}), 500
    
    mysql = current_app.mysql
    
    # Test de la connexion
    try:
        cursor = mysql.connection.cursor()
    except Exception as e:
        logger.error(f"Erreur de connexion MySQL: {str(e)}")
        return jsonify({"error": "Database connection failed"}), 500

    try:
        logger.info("Exécution de la requête principale...")
        
        # Test simple d'abord
        cursor.execute("SELECT 1 as test")
        test_result = cursor.fetchone()
        logger.info(f"Test de connexion DB: {test_result}")
        
        cursor.execute('''
            SELECT q.question_id, q.question, q.media_type, q.media_url, q.country_code, 
                q.question_type, q.max_choices, q.min_choices, 
                q.parent_question_id, q.is_conditional, q.condition_value, q.hint,
                q.question_description
            FROM quiz_questions qq
            JOIN questions_catalog q ON qq.question_id = q.question_id
            WHERE qq.quiz_id = %s
            AND qq.is_active = TRUE
            AND q.is_active = TRUE
            ORDER BY qq.question_ranking
        ''', (quiz_id,))
        
        questions = cursor.fetchall()
        logger.info(f"Nombre de questions trouvées: {len(questions) if questions else 0}")
        
        if not questions:
            logger.warning(f"Aucune question trouvée pour le quiz {quiz_id}")
            # Vérifier si le quiz existe
            cursor.execute("SELECT quiz_id FROM quiz_catalog WHERE quiz_id = %s", (quiz_id,))
            quiz_exists = cursor.fetchone()
            if not quiz_exists:
                logger.error(f"Le quiz {quiz_id} n'existe pas dans quiz_catalog")
                return jsonify({"error": f"Quiz '{quiz_id}' not found in database"}), 404
            else:
                logger.error(f"Le quiz {quiz_id} existe mais n'a pas de questions dans quiz_questions")
                return jsonify({"error": f"No questions found for quiz '{quiz_id}'"}), 404

        formatted_questions = []
        for i, q in enumerate(questions):
            try:
                logger.info(f"Traitement de la question {i+1}/{len(questions)} (ID: {q[0]})")

                cursor.execute('''
                    SELECT choice_value, choice_text, choice_media_type, choice_media_url, 
                        max_character_input, next_question_id, choice_description
                    FROM questions_choices
                    WHERE question_id = %s
                ''', (q[0],))
                choices = cursor.fetchall()
                logger.info(f"Récupéré {len(choices)} choix pour la question {q[0]}")

                # Décodage de condition_value avec gestion d'erreur
                condition_value = None
                if q[10]:
                    try:
                        condition_value = json.loads(q[10])
                        logger.info(f"condition_value décodé pour question {q[0]}: {condition_value}")
                    except json.JSONDecodeError as e:
                        logger.error(f"Erreur de décodage JSON pour condition_value de la question {q[0]}: {e}")

                # Pour les questions de type free_text
                max_character_input = None
                if q[5] == 'free_text' and choices:
                    max_character_input = choices[0][4]
                    logger.info(f"max_character_input pour question free_text {q[0]}: {max_character_input}")

                # Log du hint pour debug
                logger.info(f"Hint pour question {q[0]}: '{q[11]}'")

                formatted_question = {
                    "id": q[0],
                    "question": q[1],
                    "media_type": q[2],
                    "media_url": q[3],
                    "country_code": q[4],
                    "question_type": q[5],
                    "max_choices": q[6],
                    "min_choices": q[7],
                    "parent_question_id": q[8],
                    "is_conditional": bool(q[9]),
                    "condition_value": condition_value,
                    "hint": q[11],
                    "question_description": q[12] if len(q) > 12 else None,
                    "max_character_input": max_character_input,
                    "choices": [{
                        "value": str(c[0]),
                        "text": c[1],
                        "choice_media_type": c[2],
                        "choice_media_url": c[3].strip('"') if c[3] else None,
                        "max_character_input": c[4],
                        "next_question_id": c[5],
                        "choice_description": c[6] if len(c) > 6 else None
                    } for c in choices]
                }

                formatted_questions.append(formatted_question)
                logger.info(f"Question {q[0]} formatée avec succès")

            except Exception as e:
                logger.error(f"Erreur lors du traitement de la question {q[0]}: {str(e)}", exc_info=True)
                raise

        response_data = {"questions": formatted_questions}
        logger.info(f"Préparation de la réponse avec {len(formatted_questions)} questions formatées")

        # Headers pour s'assurer que c'est bien du JSON
        response = jsonify(response_data)
        response.headers['Content-Type'] = 'application/json'
        response.headers['Cache-Control'] = 'no-cache'
        
        logger.info("=== RÉPONSE JSON ENVOYÉE AVEC SUCCÈS ===")
        return response

    except Exception as e:
        logger.error("=== ERREUR CRITIQUE ===")
        logger.error(f"Type d'erreur: {type(e).__name__}")
        logger.error(f"Message d'erreur: {str(e)}")
        logger.error("Stack trace complète:", exc_info=True)
        
        return jsonify({
            "error": "Une erreur est survenue lors de la récupération des questions",
            "error_type": type(e).__name__,
            "details": str(e) if os.getenv('FLASK_DEBUG') == 'True' else None
        }), 500

    finally:
        if 'cursor' in locals():
            cursor.close()
        logger.info("=== FIN DE get_questions_homepage ===")


@quiz_bp.route('/get_questions_smart_contact/')
@login_required
def get_questions_smart_contact():
    """Version Smart Contact : authentifiée mais sans token."""
    quiz_id = request.args.get('quiz_id', 'smart_contact')
    logger.info(f"[SC] get_questions_smart_contact quiz_id={quiz_id}, user={current_user.id}")

    mysql = current_app.mysql
    cursor = mysql.connection.cursor()

    try:
        cursor.execute('''
            SELECT q.question_id, q.question, q.media_type, q.media_url, q.country_code, 
                q.question_type, q.max_choices, q.min_choices, 
                q.parent_question_id, q.is_conditional, q.condition_value, q.hint,
                q.question_description
            FROM quiz_questions qq
            JOIN questions_catalog q ON qq.question_id = q.question_id
            WHERE qq.quiz_id = %s
            AND qq.is_active = TRUE
            AND q.is_active = TRUE
            ORDER BY qq.question_ranking
        ''', (quiz_id,))
        questions = cursor.fetchall()

        if not questions:
            return jsonify({"error": "Aucune question trouvée"}), 404

        formatted_questions = []
        for q in questions:
            cursor.execute('''
                SELECT choice_value, choice_text, choice_media_type, choice_media_url, 
                    max_character_input, next_question_id, choice_description
                FROM questions_choices
                WHERE question_id = %s
            ''', (q[0],))
            choices = cursor.fetchall()

            condition_value = None
            if q[10]:
                try:
                    condition_value = json.loads(q[10])
                except json.JSONDecodeError:
                    pass

            max_character_input = None
            if q[5] == 'free_text' and choices:
                max_character_input = choices[0][4]

            formatted_questions.append({
                "id": q[0],
                "question": q[1],
                "media_type": q[2],
                "media_url": q[3],
                "country_code": q[4],
                "question_type": q[5],
                "max_choices": q[6],
                "min_choices": q[7],
                "parent_question_id": q[8],
                "is_conditional": bool(q[9]),
                "condition_value": condition_value,
                "hint": q[11],
                "question_description": q[12] if len(q) > 12 else None,
                "max_character_input": max_character_input,
                "choices": [{
                    "value": str(c[0]),
                    "text": c[1],
                    "choice_media_type": c[2],
                    "choice_media_url": c[3].strip('"') if c[3] else None,
                    "max_character_input": c[4],
                    "next_question_id": c[5],
                    "choice_description": c[6] if len(c) > 6 else None
                } for c in choices]
            })

        return jsonify({"questions": formatted_questions})

    except Exception as e:
        logger.error(f"[SC] Erreur: {str(e)}", exc_info=True)
        return jsonify({"error": "Erreur serveur"}), 500
    finally:
        cursor.close()

@quiz_bp.route('/get_smart_contact_progress/<string:quiz_id>')
@login_required
def get_smart_contact_progress(quiz_id):
    """Progression Smart Contact, sans token."""
    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        cursor.execute('''
            SELECT qu.quiz_session_id, qu.questions_answered_count,
                   qu.quiz_status, qu.question_history
            FROM quiz_user qu
            WHERE qu.quiz_id = %s AND qu.user_id = %s
            ORDER BY qu.updated_at DESC LIMIT 1
        ''', (quiz_id, current_user.id))

        result = cursor.fetchone()
        if not result:
            return jsonify({"progress": {"questions_answered_count": 0, "quiz_status": "not_started", "question_history": []}, "answers": {}}), 200

        quiz_session_id = result['quiz_session_id']
        question_history = json.loads(result['question_history'] or '[]')

        cursor.execute('''
            SELECT au.question_id, au.answer_value, au.answer_text, qc.question_type
            FROM answer_user au
            JOIN questions_catalog qc ON au.question_id = qc.question_id
            WHERE au.quiz_session_id = %s
        ''', (quiz_session_id,))

        answers = {}
        for row in cursor.fetchall():
            try:
                if row['question_type'] == 'free_text':
                    av = [row['answer_text']] if row['answer_text'] else []
                else:
                    av = json.loads(row['answer_value']) if row['answer_value'] else []
                answers[str(row['question_id'])] = {'value': av, 'text': row['answer_text']}
            except json.JSONDecodeError:
                continue

        return jsonify({
            "progress": {
                "questions_answered_count": result['questions_answered_count'],
                "quiz_status": result['quiz_status'],
                "question_history": question_history
            },
            "answers": answers
        }), 200

    except Exception as e:
        logger.error(f"[SC] Erreur get_smart_contact_progress: {str(e)}", exc_info=True)
        return jsonify({"error": "Server error"}), 500
    finally:
        cursor.close()
        
@quiz_bp.route('/update_smart_contact_progress', methods=['POST'])
@login_required
@csrf.exempt
def update_smart_contact_progress():
    """Sauvegarde réponses Smart Contact, sans token. Supporte JSON et multipart (audio)."""

    # ── Supporter JSON ET multipart (pour audio) ──
    if request.content_type and 'multipart' in request.content_type:
        data = json.loads(request.form.get('data', '{}'))
    else:
        data = request.json

    quiz_id = data.get('quiz_id', 'smart_contact')
    current_question_index = data.get('current_question_index')
    answer = data.get('answer')
    is_completed = data.get('is_completed', False)

    if not all([quiz_id, isinstance(current_question_index, int), answer]):
        return jsonify({"error": "Missing required data"}), 400

    mysql = current_app.mysql
    cursor = mysql.connection.cursor(DictCursor)

    try:
        quiz_session_id = get_or_create_quiz_session(cursor, current_user.id, quiz_id)

        cursor.execute('SELECT question_history FROM quiz_user WHERE quiz_session_id = %s', (quiz_session_id,))
        current_history = cursor.fetchone()
        history = json.loads(current_history['question_history'] if current_history and current_history['question_history'] else '[]')

        new_questions_answered = max(current_question_index + 1, len(history))
        new_status = 'completed' if is_completed else 'in_progress'

        if current_question_index not in history:
            history.append(current_question_index)

        cursor.execute('''
            UPDATE quiz_user 
            SET questions_answered_count = %s, quiz_status = %s,
                question_history = %s, updated_at = CURRENT_TIMESTAMP
            WHERE quiz_session_id = %s
        ''', (new_questions_answered, new_status, json.dumps(history), quiz_session_id))

        answer_value = answer.get('value')
        if not isinstance(answer_value, list):
            answer_value = [answer_value]

        answer_text = answer.get('text', '')

        # ═══════════════════════════════════════════════════════════
        # 🎙️ GESTION AUDIO : upload cloud + transcription Whisper
        # ═══════════════════════════════════════════════════════════
        audio_file = request.files.get('audio') if request.files else None
        if audio_file:
            question_id = str(answer.get('question_id', ''))
            logger.info(f"[SC] 🎙️ Audio reçu pour Q{question_id}, "
                        f"type={audio_file.content_type}, user={current_user.id}")

            # Détecter le format
            file_format = None
            if hasattr(audio_file, 'content_type') and audio_file.content_type:
                ct = audio_file.content_type.lower()
                if 'mp4' in ct:
                    file_format = '.mp4'
                elif 'webm' in ct:
                    file_format = '.webm'

            audio_url = None

            try:
                # 1) Upload dans le cloud
                audio_blob = audio_file.read()
                try:
                    upload_result = AudioService.save_quiz_audio_to_cloud(
                        audio_blob, quiz_id, question_id, current_user.id,
                        file_format=file_format
                    )
                    if upload_result.get('success'):
                        audio_url = upload_result['url']
                        logger.info(f"[SC] ✅ Audio Q{question_id} uploadé: {audio_url}")
                    else:
                        logger.error(f"[SC] ❌ Audio upload failed: {upload_result.get('error')}")
                except Exception as upload_err:
                    logger.error(f"[SC] ❌ Audio upload error: {upload_err}")

                # 2) Transcription Whisper
                audio_file.seek(0)
                try:
                    transcription = AudioService.transcribe_with_whisper(audio_file)
                    if transcription.get('success') and transcription.get('transcript'):
                        whisper_text = transcription['transcript']
                        logger.info(f"[SC] 🎙️ Transcription Q{question_id}: {whisper_text[:100]}...")

                        # Combiner : transcription + lien audio
                        parts = []
                        if answer_text and answer_text not in ('[AUDIO_RESPONSE]', '', '[Audio]'):
                            parts.append(answer_text)
                        parts.append(whisper_text)
                        if audio_url:
                            parts.append(f"[AUDIO: {audio_url}]")
                        answer_text = '\n'.join(parts)
                    else:
                        logger.warning(f"[SC] ⚠️ Whisper pas de transcription pour Q{question_id}")
                        if audio_url:
                            answer_text = audio_url if not answer_text or answer_text.startswith('[AUDIO') else f"{answer_text}\n[AUDIO: {audio_url}]"
                except Exception as whisper_err:
                    logger.error(f"[SC] ❌ Whisper error: {whisper_err}")
                    if audio_url:
                        answer_text = audio_url if not answer_text or answer_text.startswith('[AUDIO') else f"{answer_text}\n[AUDIO: {audio_url}]"

            except Exception as audio_err:
                logger.error(f"[SC] ❌ Audio processing error: {audio_err}", exc_info=True)
        # ═══════════════════════════════════════════════════════════

        cursor.execute('''
            INSERT INTO answer_user 
            (quiz_session_id, question_id, answer_value, answer_text) 
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
                answer_value = VALUES(answer_value),
                answer_text = VALUES(answer_text),
                updated_at = CURRENT_TIMESTAMP
        ''', (quiz_session_id, answer.get('question_id'), json.dumps(answer_value), answer_text))

        mysql.connection.commit()

        # Récupérer toutes les réponses
        cursor.execute('''
            SELECT au.question_id, au.answer_value, au.answer_text, qc.question_type
            FROM answer_user au
            JOIN questions_catalog qc ON au.question_id = qc.question_id
            WHERE au.quiz_session_id = %s
        ''', (quiz_session_id,))

        answers = {}
        for row in cursor.fetchall():
            try:
                if row['question_type'] == 'free_text':
                    av = [row['answer_text']] if row['answer_text'] else []
                else:
                    av = json.loads(row['answer_value']) if row['answer_value'] else []
                answers[str(row['question_id'])] = {'value': av, 'text': row['answer_text']}
            except json.JSONDecodeError:
                continue

        return jsonify({"message": "Answer saved", "answers": answers}), 200

    except Exception as e:
        mysql.connection.rollback()
        logger.error(f"[SC] Erreur update_smart_contact_progress: {str(e)}", exc_info=True)
        return jsonify({"error": "Server error"}), 500
    finally:
        cursor.close()