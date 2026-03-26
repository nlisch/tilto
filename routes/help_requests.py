from flask import Blueprint, jsonify, request, current_app, render_template,Response
from flask_login import login_required, current_user
from MySQLdb.cursors import DictCursor
from decorators import admin_required
from utils import generate_request_id
import logging
from datetime import datetime,timedelta
import json


help_requests_bp = Blueprint('help_requests', __name__, url_prefix='/help-requests')
logger = logging.getLogger(__name__)


# ==================== ROUTES PISTE INTEREST (NOUVEAU) ====================

@help_requests_bp.route('/piste-interest/submit', methods=['POST'])
@login_required
def submit_piste_interest():
    """
    Soumet un intérêt pour une piste.
    RÈGLE : 1 seul intérêt actif par user/quiz (recruiter_connection OU coach_session).
    Si déjà un intérêt actif, on le passe en 'cancelled' et on crée le nouveau.
    """
    request_id = generate_request_id()
    data = request.json
    
    # Récupérer le user_id cible
    target_user_id = data.get('user_id')
    if target_user_id and current_user.user_status in ('admin', 'coach'):
        user_id_for_request = int(target_user_id)
    else:
        user_id_for_request = current_user.id
    
    # Validation
    quiz_id = data.get('quiz_id')
    piste_number = data.get('piste_number')
    piste_title = data.get('piste_title', '')
    interest_type = data.get('interest_type')  # 'recruiter_connection' ou 'coach_session'
    
    if not quiz_id or not piste_number or not interest_type:
        return jsonify({'success': False, 'error': 'quiz_id, piste_number et interest_type sont requis'}), 400
    
    # Types autorisés pour l'intérêt piste
    valid_interest_types = ['recruiter_connection', 'coach_session']
    if interest_type not in valid_interest_types:
        return jsonify({'success': False, 'error': f'Type invalide. Autorisés: {valid_interest_types}'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # 1. Vérifier s'il existe déjà un intérêt actif (peu importe la piste)
        cursor.execute("""
            SELECT id, piste_number, piste_title, request_type
            FROM user_help_requests
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND request_type IN ('recruiter_connection', 'coach_session')
            AND status IN ('pending', 'contacted', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id_for_request, quiz_id))
        
        existing = cursor.fetchone()
        
        replaced_info = None
        
        if existing:
            # Si c'est exactement le même choix (même piste + même type) → rien à faire
            if existing['piste_number'] == int(piste_number) and existing['request_type'] == interest_type:
                logger.info(f"[{request_id}] Same interest already exists: {existing['id']}")
                return jsonify({
                    'success': True,
                    'message': 'Ton choix est déjà enregistré',
                    'request_id': existing['id'],
                    'is_same': True,
                    'current_choice': {
                        'piste_number': existing['piste_number'],
                        'piste_title': existing['piste_title'],
                        'interest_type': existing['request_type']
                    }
                })
            
            # Sinon, annuler l'ancien choix
            cursor.execute("""
                UPDATE user_help_requests
                SET status = 'cancelled',
                    admin_notes = CONCAT(COALESCE(admin_notes, ''), '\n[AUTO] Remplacé le ', NOW(), ' par piste ', %s, ' - ', %s),
                    updated_at = NOW()
                WHERE id = %s
            """, (piste_number, interest_type, existing['id']))
            
            replaced_info = {
                'old_piste_number': existing['piste_number'],
                'old_piste_title': existing['piste_title'],
                'old_interest_type': existing['request_type']
            }
            
            logger.info(f"[{request_id}] Cancelled previous interest {existing['id']} (piste {existing['piste_number']}) for user {user_id_for_request}")
        
        # 2. Créer le nouveau choix
        cursor.execute("""
            INSERT INTO user_help_requests (
                user_id, quiz_id, result_id,
                piste_number, piste_title,
                request_type, initial_interest, request_details,
                source_page, source_action,
                status, priority
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s, 'yes', %s,
                %s, %s,
                'pending', 'normal'
            )
        """, (
            user_id_for_request,
            quiz_id,
            data.get('result_id'),
            int(piste_number),
            piste_title,
            interest_type,
            None,  # request_details
            'analysis_view',
            'piste_interest_submit'
        ))
        
        new_request_id = cursor.lastrowid
        current_app.mysql.connection.commit()
        
        logger.info(f"[{request_id}] Piste interest created: {new_request_id} for user {user_id_for_request} (piste {piste_number}, type {interest_type})")
        
        # Message de confirmation
        type_labels = {
            'recruiter_connection': 'mise en relation recruteur',
            'coach_session': 'échange avec un coach'
        }
        
        response_data = {
            'success': True,
            'message': f'C\'est noté ! On te recontacte pour ta demande de {type_labels.get(interest_type, interest_type)}.',
            'request_id': new_request_id,
            'is_same': False,
            'current_choice': {
                'piste_number': int(piste_number),
                'piste_title': piste_title,
                'interest_type': interest_type
            }
        }
        
        if replaced_info:
            response_data['replaced'] = replaced_info
            response_data['message'] = f'Ton choix a été mis à jour ! On te recontacte pour ta demande de {type_labels.get(interest_type, interest_type)}.'
        
        return jsonify(response_data)
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[{request_id}] Error submitting piste interest: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/piste-interest/current', methods=['GET'])
@login_required
def get_current_piste_interest():
    """
    Récupère l'intérêt actif actuel pour un user/quiz.
    """
    user_id = request.args.get('user_id', current_user.id, type=int)
    quiz_id = request.args.get('quiz_id')
    
    # Vérification des droits
    if user_id != current_user.id and current_user.user_status not in ('admin', 'coach'):
        return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403
    
    if not quiz_id:
        return jsonify({'success': False, 'error': 'quiz_id requis'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT id, piste_number, piste_title, request_type, status, created_at
            FROM user_help_requests
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND request_type IN ('recruiter_connection', 'coach_session')
            AND status IN ('pending', 'contacted', 'in_progress')
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        current_interest = cursor.fetchone()
        
        if current_interest:
            return jsonify({
                'success': True,
                'has_interest': True,
                'current_choice': {
                    'request_id': current_interest['id'],
                    'piste_number': current_interest['piste_number'],
                    'piste_title': current_interest['piste_title'],
                    'interest_type': current_interest['request_type'],
                    'status': current_interest['status'],
                    'created_at': current_interest['created_at'].isoformat() if current_interest['created_at'] else None
                }
            })
        else:
            return jsonify({
                'success': True,
                'has_interest': False,
                'current_choice': None
            })
        
    except Exception as e:
        logger.error(f"Error fetching current piste interest: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()


# ==================== ROUTES UTILISATEUR ====================

@help_requests_bp.route('/submit', methods=['POST'])
@login_required
def submit_request():
    """
    Soumet une nouvelle demande d'accompagnement.
    """
    request_id = generate_request_id()
    
    data = request.json
    
    # ✅ Récupérer le user_id cible (celui de l'analyse)
    # Si fourni et que l'utilisateur actuel est admin/coach, utiliser le user_id fourni
    # Sinon, utiliser current_user.id
    target_user_id = data.get('user_id')
    
    if target_user_id and current_user.user_status in ('admin', 'coach'):
        # Admin/coach peut créer une demande pour un autre utilisateur
        user_id_for_request = int(target_user_id)
        logger.info(f"[{request_id}] Admin {current_user.id} creating help request for user {user_id_for_request}")
    else:
        # Utilisateur normal crée pour lui-même
        user_id_for_request = current_user.id
        logger.info(f"[{request_id}] User {current_user.id} creating help request for self")
    
    # Validation des champs requis
    quiz_id = data.get('quiz_id')
    request_type = data.get('request_type')
    
    if not quiz_id or not request_type:
        return jsonify({'error': 'quiz_id et request_type sont requis'}), 400
    
    # Types de demandes autorisés
    valid_types = [
        'action_followup',
        'recruiter_connection', 
        'analysis_refinement',
        'coach_session',
        'cv_review',
        'interview_prep',
        'training_info',
        'networking_help',
        'other'
    ]
    
    if request_type not in valid_types:
        return jsonify({'error': f'Type de demande invalide. Types autorisés: {valid_types}'}), 400
    
    # Champs optionnels
    result_id = data.get('result_id')
    piste_number = data.get('piste_number')
    piste_title = data.get('piste_title')
    request_details = data.get('request_details', '').strip()
    source_page = data.get('source_page', 'analysis_view')
    source_action = data.get('source_action', 'help_option_click')
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # ✅ Utiliser user_id_for_request au lieu de current_user.id
        cursor.execute("""
            SELECT id, status, created_at
            FROM user_help_requests
            WHERE user_id = %s 
            AND quiz_id = %s 
            AND request_type = %s
            AND status IN ('pending', 'contacted', 'in_progress')
            AND created_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
            ORDER BY created_at DESC
            LIMIT 1
        """, (user_id_for_request, quiz_id, request_type))
        
        existing = cursor.fetchone()
        
        if existing:
            logger.info(f"[{request_id}] Duplicate request found: {existing['id']}")
            return jsonify({
                'success': True,
                'message': 'Votre demande a déjà été enregistrée',
                'request_id': existing['id'],
                'is_duplicate': True,
                'created_at': existing['created_at'].isoformat() if existing['created_at'] else None
            })
        
        # ✅ Utiliser user_id_for_request au lieu de current_user.id
        cursor.execute("""
            INSERT INTO user_help_requests (
                user_id, quiz_id, result_id,
                piste_number, piste_title,
                request_type, request_details,
                source_page, source_action,
                status, priority
            ) VALUES (
                %s, %s, %s,
                %s, %s,
                %s, %s,
                %s, %s,
                'pending', 'normal'
            )
        """, (
            user_id_for_request,  # ✅ CHANGÉ ICI
            quiz_id, result_id,
            piste_number, piste_title,
            request_type, request_details if request_details else None,
            source_page, source_action
        ))
        
        new_request_id = cursor.lastrowid
        current_app.mysql.connection.commit()
        
        logger.info(f"[{request_id}] Help request created: {new_request_id} for user {user_id_for_request}")
        
        # Labels pour le message de confirmation
        type_labels = {
            'action_followup': 'suivi des actions',
            'recruiter_connection': 'mise en relation recruteurs',
            'analysis_refinement': 'approfondissement de l\'analyse',
            'coach_session': 'session coaching',
            'cv_review': 'relecture CV',
            'interview_prep': 'préparation entretien',
            'training_info': 'informations formations',
            'networking_help': 'aide networking',
            'other': 'autre demande'
        }
        
        return jsonify({
            'success': True,
            'message': f'Votre demande de {type_labels.get(request_type, request_type)} a été enregistrée',
            'request_id': new_request_id,
            'is_duplicate': False
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[{request_id}] Error submitting help request: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/my-requests', methods=['GET'])
@login_required
def get_my_requests():
    """
    Récupère les demandes de l'utilisateur connecté.
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                id,
                quiz_id,
                piste_number,
                piste_title,
                request_type,
                request_details,
                status,
                created_at,
                contacted_at,
                completed_at
            FROM user_help_requests
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """, (current_user.id,))
        
        requests = cursor.fetchall()
        
        # Formater les dates
        for req in requests:
            if req['created_at']:
                req['created_at'] = req['created_at'].isoformat()
            if req['contacted_at']:
                req['contacted_at'] = req['contacted_at'].isoformat()
            if req['completed_at']:
                req['completed_at'] = req['completed_at'].isoformat()
        
        return jsonify({
            'success': True,
            'requests': requests,
            'total': len(requests)
        })
        
    except Exception as e:
        logger.error(f"Error fetching user requests: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


# ==================== ROUTES ADMIN ====================

@help_requests_bp.route('/admin/list', methods=['GET'])
@admin_required
def admin_list_requests():
    """
    Liste toutes les demandes (interface admin).
    Supporte filtres et pagination.
    """
    # Paramètres de filtrage
    status = request.args.get('status')
    request_type = request.args.get('type')
    priority = request.args.get('priority')
    assigned_to = request.args.get('assigned_to')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    
    offset = (page - 1) * per_page
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Construction de la requête avec filtres
        where_clauses = ["1=1"]
        params = []
        
        if status:
            where_clauses.append("hr.status = %s")
            params.append(status)
        
        if request_type:
            where_clauses.append("hr.request_type = %s")
            params.append(request_type)
        
        if priority:
            where_clauses.append("hr.priority = %s")
            params.append(priority)
        
        if assigned_to:
            if assigned_to == 'unassigned':
                where_clauses.append("hr.assigned_to IS NULL")
            else:
                where_clauses.append("hr.assigned_to = %s")
                params.append(int(assigned_to))
        
        where_sql = " AND ".join(where_clauses)
        
        # Compter le total
        cursor.execute(f"""
            SELECT COUNT(*) as total
            FROM user_help_requests hr
            WHERE {where_sql}
        """, tuple(params))
        
        total = cursor.fetchone()['total']
        
        # Récupérer les demandes avec infos utilisateur ET localisation
        cursor.execute(f"""
            SELECT 
                hr.id,
                hr.user_id,
                hr.quiz_id,
                hr.result_id,
                hr.piste_number,
                hr.piste_title,
                hr.request_type,
                hr.request_details,
                hr.status,
                hr.priority,
                hr.assigned_to,
                hr.admin_notes,
                hr.source_page,
                hr.created_at,
                hr.updated_at,
                hr.contacted_at,
                hr.completed_at,
                u.firstname,
                u.lastname,
                u.email,
                u.phone_number,
                admin.firstname as admin_firstname,
                admin.lastname as admin_lastname,
                loc.answer_text as user_location
            FROM user_help_requests hr
            JOIN users u ON hr.user_id = u.user_id
            LEFT JOIN users admin ON hr.assigned_to = admin.user_id
            LEFT JOIN (
                SELECT au.answer_text, qu.user_id
                FROM answer_user au
                JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
                WHERE au.question_id = 26
                AND au.created_at = (
                    SELECT MAX(au2.created_at)
                    FROM answer_user au2
                    JOIN quiz_user qu2 ON au2.quiz_session_id = qu2.quiz_session_id
                    WHERE qu2.user_id = qu.user_id AND au2.question_id = 26
                )
            ) loc ON loc.user_id = hr.user_id
            WHERE {where_sql}
            ORDER BY 
                CASE hr.priority 
                    WHEN 'urgent' THEN 1 
                    WHEN 'high' THEN 2 
                    WHEN 'normal' THEN 3 
                    WHEN 'low' THEN 4 
                END,
                hr.created_at DESC
            LIMIT %s OFFSET %s
        """, tuple(params) + (per_page, offset))
        
        requests = cursor.fetchall()
        
        # Formater les dates
        for req in requests:
            for date_field in ['created_at', 'updated_at', 'contacted_at', 'completed_at']:
                if req.get(date_field):
                    req[date_field] = req[date_field].isoformat()
        
        # Stats rapides
        cursor.execute("""
            SELECT 
                status,
                COUNT(*) as count
            FROM user_help_requests
            GROUP BY status
        """)
        
        stats_by_status = {row['status']: row['count'] for row in cursor.fetchall()}
        
        return jsonify({
            'success': True,
            'requests': requests,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page
            },
            'stats': stats_by_status
        })
        
    except Exception as e:
        logger.error(f"Error listing help requests: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/admin/update/<int:request_id>', methods=['POST'])
@admin_required
def admin_update_request(request_id):
    """
    Met à jour une demande (statut, priorité, notes, assignation).
    """
    log_id = generate_request_id()
    logger.info(f"[{log_id}] Admin {current_user.id} updating request {request_id}")
    
    data = request.json
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier que la demande existe
        cursor.execute("""
            SELECT id, status, assigned_to, priority
            FROM user_help_requests
            WHERE id = %s
        """, (request_id,))
        
        existing = cursor.fetchone()
        
        if not existing:
            return jsonify({'error': 'Demande introuvable'}), 404
        
        # Construire la mise à jour
        updates = []
        params = []
        changes = []
        
        # Mise à jour du statut
        if 'status' in data and data['status'] != existing['status']:
            new_status = data['status']
            valid_statuses = ['pending', 'contacted', 'in_progress', 'completed', 'cancelled']
            
            if new_status not in valid_statuses:
                return jsonify({'error': f'Statut invalide. Valeurs autorisées: {valid_statuses}'}), 400
            
            updates.append("status = %s")
            params.append(new_status)
            changes.append(f"Statut: {existing['status']} → {new_status}")
            
            # Mettre à jour les timestamps selon le statut
            if new_status == 'contacted' and not existing.get('contacted_at'):
                updates.append("contacted_at = NOW()")
            elif new_status == 'completed':
                updates.append("completed_at = NOW()")
        
        # Mise à jour de la priorité
        if 'priority' in data and data['priority'] != existing['priority']:
            new_priority = data['priority']
            valid_priorities = ['low', 'normal', 'high', 'urgent']
            
            if new_priority not in valid_priorities:
                return jsonify({'error': f'Priorité invalide'}), 400
            
            updates.append("priority = %s")
            params.append(new_priority)
            changes.append(f"Priorité: {existing['priority']} → {new_priority}")
        
        # Assignation
        if 'assigned_to' in data:
            new_assigned = data['assigned_to'] if data['assigned_to'] else None
            
            if new_assigned != existing['assigned_to']:
                updates.append("assigned_to = %s")
                params.append(new_assigned)
                changes.append(f"Assigné à: {new_assigned or 'Non assigné'}")
        
        # Notes admin
        if 'admin_notes' in data:
            updates.append("admin_notes = %s")
            params.append(data['admin_notes'])
            changes.append("Notes mises à jour")
        
        if not updates:
            return jsonify({'success': True, 'message': 'Aucune modification'})
        
        # Exécuter la mise à jour
        params.append(request_id)
        cursor.execute(f"""
            UPDATE user_help_requests
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE id = %s
        """, tuple(params))
        
        current_app.mysql.connection.commit()
        
        logger.info(f"[{log_id}] Request {request_id} updated: {', '.join(changes)}")
        
        return jsonify({
            'success': True,
            'message': 'Demande mise à jour',
            'changes': changes
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[{log_id}] Error updating request: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    """
    Statistiques globales des demandes.
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Stats par statut
        cursor.execute("""
            SELECT status, COUNT(*) as count
            FROM user_help_requests
            GROUP BY status
        """)
        by_status = {row['status']: row['count'] for row in cursor.fetchall()}
        
        # Stats par type de demande (exclure les annulées)
        cursor.execute("""
            SELECT request_type, COUNT(*) as count
            FROM user_help_requests
            WHERE status != 'cancelled'
            GROUP BY request_type
            ORDER BY count DESC
        """)
        by_type = cursor.fetchall()
        
        # Stats par piste
        cursor.execute("""
            SELECT piste_number, COUNT(*) as count
            FROM user_help_requests
            WHERE piste_number IS NOT NULL
            GROUP BY piste_number
            ORDER BY piste_number
        """)
        by_piste = cursor.fetchall()
        
        # Demandes récentes (7 derniers jours)
        cursor.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM user_help_requests
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        recent_trend = cursor.fetchall()
        
        # Formater les dates
        for item in recent_trend:
            if item['date']:
                item['date'] = item['date'].isoformat()
        
        # Temps moyen de traitement (pending → completed)
        cursor.execute("""
            SELECT AVG(TIMESTAMPDIFF(HOUR, created_at, completed_at)) as avg_hours
            FROM user_help_requests
            WHERE status = 'completed' AND completed_at IS NOT NULL
        """)
        avg_processing = cursor.fetchone()
        
        return jsonify({
            'success': True,
            'stats': {
                'by_status': by_status,
                'by_type': by_type,
                'by_piste': by_piste,
                'recent_trend': recent_trend,
                'avg_processing_hours': round(avg_processing['avg_hours'] or 0, 1),
                'total_pending': by_status.get('pending', 0) + by_status.get('contacted', 0) + by_status.get('in_progress', 0)
            }
        })
        
    except Exception as e:
        logger.error(f"Error fetching stats: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/admin/view', methods=['GET'])
@admin_required
def admin_view():
    """
    Page d'administration des demandes (rendu HTML).
    """
    return render_template('admin/help_requests.html')

@help_requests_bp.route('/user-requests/<int:user_id>', methods=['GET'])
@login_required
def get_user_requests(user_id):
    """
    Récupère les demandes d'un utilisateur spécifique.
    - Si user connecté = user_id demandé → OK
    - Si user connecté = admin → OK
    - Sinon → Forbidden
    """
    # Vérification des droits
    if current_user.id != user_id and current_user.user_status not in ('admin', 'coach'):
        return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403
    
    quiz_id = request.args.get('quiz_id')
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        query = """
            SELECT 
                id,
                quiz_id,
                piste_number,
                piste_title,
                request_type,
                request_details,
                status,
                priority,
                created_at,
                contacted_at,
                completed_at
            FROM user_help_requests
            WHERE user_id = %s
        """
        params = [user_id]
        
        if quiz_id:
            query += " AND quiz_id = %s"
            params.append(quiz_id)
        
        query += " ORDER BY created_at DESC LIMIT 20"
        
        cursor.execute(query, tuple(params))
        requests_list = cursor.fetchall()
        
        # Formater les dates
        for req in requests_list:
            if req['created_at']:
                req['created_at'] = req['created_at'].isoformat()
            if req['contacted_at']:
                req['contacted_at'] = req['contacted_at'].isoformat()
            if req['completed_at']:
                req['completed_at'] = req['completed_at'].isoformat()
        
        return jsonify({
            'success': True,
            'requests': requests_list,
            'total': len(requests_list)
        })
        
    except Exception as e:
        logger.error(f"Error fetching user requests: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()


@help_requests_bp.route('/admin/analysis-stats', methods=['GET'])
@admin_required
def admin_analysis_stats():
    """Statistiques des analyses avec funnel et stats device."""
    
    start_date = datetime(2026, 1, 12, 0, 0, 0)
    device_filter = request.args.get('device', '')  # '', 'mobile', 'desktop'
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # =============================================================
        # 1. FUNNEL STATS PAR DEVICE
        # =============================================================
        
        def get_device_condition(alias='al'):
            if device_filter == 'mobile':
                return f"AND {alias}.device_type = 'mobile'"
            elif device_filter == 'desktop':
                return f"AND {alias}.device_type = 'desktop'"
            return ""
        
        device_cond = get_device_condition('al')
        
        # QUIZ RÉALISÉS
        if device_filter:
            cursor.execute(f'''
                SELECT COUNT(DISTINCT qu.user_id) as count
                FROM quiz_user qu
                JOIN activity_logs al ON al.user_id = qu.user_id 
                    AND al.created_at BETWEEN DATE_SUB(qu.end_time, INTERVAL 10 MINUTE) 
                    AND DATE_ADD(qu.end_time, INTERVAL 10 MINUTE)
                    AND al.page_path LIKE '%%quiz%%'
                WHERE qu.quiz_status = 'completed'
                AND qu.end_time >= %s
                {device_cond}
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT COUNT(DISTINCT user_id) as count
                FROM quiz_user
                WHERE quiz_status = 'completed'
                AND end_time >= %s
            ''', (start_date,))
        total_quiz_completed = cursor.fetchone()['count'] or 0
        
        # ANALYSES GÉNÉRÉES
        if device_filter:
            cursor.execute(f'''
                SELECT COUNT(DISTINCT ru.user_id) as count
                FROM result_user ru
                INNER JOIN quiz_user qu ON ru.user_id = qu.user_id
                JOIN activity_logs al ON al.user_id = ru.user_id 
                    AND al.created_at BETWEEN DATE_SUB(ru.created_at, INTERVAL 10 MINUTE) 
                    AND DATE_ADD(ru.created_at, INTERVAL 10 MINUTE)
                WHERE ru.is_active = 1
                AND ru.result_step_id = 'career_path_v3'
                AND qu.quiz_status = 'completed'
                AND qu.end_time >= %s
                {device_cond}
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT COUNT(DISTINCT ru.user_id) as count
                FROM result_user ru
                INNER JOIN quiz_user qu ON ru.user_id = qu.user_id
                WHERE ru.is_active = 1
                AND ru.result_step_id = 'career_path_v3'
                AND qu.quiz_status = 'completed'
                AND qu.end_time >= %s
            ''', (start_date,))
        total_analyses = cursor.fetchone()['count'] or 0
        
        # DÉBLOCAGES
        if device_filter:
            cursor.execute(f'''
                SELECT COUNT(DISTINCT t.token_code) as count
                FROM tokens t
                INNER JOIN users u ON t.user_id = u.user_id
                JOIN activity_logs al ON al.user_id = t.user_id 
                    AND al.created_at BETWEEN DATE_SUB(t.used_at, INTERVAL 5 MINUTE) 
                    AND DATE_ADD(t.used_at, INTERVAL 5 MINUTE)
                    AND al.page_path LIKE '%%analysis%%'
                WHERE t.used_at IS NOT NULL 
                AND t.used_for_piste IS NOT NULL
                AND t.used_at >= %s
                {device_cond}
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM tokens t
                INNER JOIN users u ON t.user_id = u.user_id
                WHERE t.used_at IS NOT NULL 
                AND t.used_for_piste IS NOT NULL
                AND t.used_at >= %s
            ''', (start_date,))
        total_unlocks = cursor.fetchone()['count'] or 0
        
        # DEMANDES D'ACCOMPAGNEMENT
        if device_filter:
            cursor.execute(f'''
                SELECT COUNT(DISTINCT hr.id) as count
                FROM user_help_requests hr
                JOIN activity_logs al ON al.user_id = hr.user_id 
                    AND al.created_at BETWEEN DATE_SUB(hr.created_at, INTERVAL 5 MINUTE) 
                    AND DATE_ADD(hr.created_at, INTERVAL 5 MINUTE)
                WHERE hr.created_at >= %s
                AND hr.status != 'cancelled'
                {device_cond}
            ''', (start_date,))
        else:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM user_help_requests
                WHERE created_at >= %s
                AND status != 'cancelled'
            ''', (start_date,))
        total_requests = cursor.fetchone()['count'] or 0
        
        # =============================================================
        # 2. STATS DEVICE GLOBALES - DÉBLOCAGES (1 device par token)
        # =============================================================
        cursor.execute('''
            SELECT device, COUNT(*) as unlock_count
            FROM (
                SELECT t.token_code,
                    COALESCE(
                        (SELECT al.device_type 
                        FROM activity_logs al 
                        WHERE al.user_id = t.user_id 
                        AND al.created_at BETWEEN DATE_SUB(t.used_at, INTERVAL 5 MINUTE) 
                        AND DATE_ADD(t.used_at, INTERVAL 5 MINUTE)
                        AND al.page_path LIKE '%%analysis%%'
                        ORDER BY ABS(TIMESTAMPDIFF(SECOND, al.created_at, t.used_at))
                        LIMIT 1
                        ), 'unknown'
                    ) as device
                FROM tokens t
                INNER JOIN users u ON t.user_id = u.user_id
                WHERE t.used_at IS NOT NULL 
                AND t.used_for_piste IS NOT NULL
                AND t.used_at >= %s
            ) sub
            GROUP BY device
        ''', (start_date,))
        device_unlocks = {'mobile': 0, 'desktop': 0, 'unknown': 0}
        for row in cursor.fetchall():
            device = row['device'] if row['device'] in device_unlocks else 'unknown'
            device_unlocks[device] = row['unlock_count']

        # =============================================================
        # 3. STATS DEVICE GLOBALES - DEMANDES (1 device par demande)
        # =============================================================
        cursor.execute('''
            SELECT device, COUNT(*) as request_count
            FROM (
                SELECT hr.id,
                    COALESCE(
                        (SELECT al.device_type 
                        FROM activity_logs al 
                        WHERE al.user_id = hr.user_id 
                        AND al.created_at BETWEEN DATE_SUB(hr.created_at, INTERVAL 5 MINUTE) 
                        AND DATE_ADD(hr.created_at, INTERVAL 5 MINUTE)
                        ORDER BY ABS(TIMESTAMPDIFF(SECOND, al.created_at, hr.created_at))
                        LIMIT 1
                        ), 'unknown'
                    ) as device
                FROM user_help_requests hr
                WHERE hr.created_at >= %s
                AND hr.status != 'cancelled'
            ) sub
            GROUP BY device
        ''', (start_date,))
        device_requests = {'mobile': 0, 'desktop': 0, 'unknown': 0}
        for row in cursor.fetchall():
            device = row['device'] if row['device'] in device_requests else 'unknown'
            device_requests[device] = row['request_count']

        # =============================================================
        # 4. QUIZ SANS ANALYSE - AVEC DÉTAILS USERS
        # Users avec quiz completed MAIS sans analyse ACTIVE
        # =============================================================
        cursor.execute('''
            SELECT 
                qu.user_id,
                u.firstname,
                u.lastname,
                u.email,
                MAX(qu.end_time) as quiz_completed_at
            FROM quiz_user qu
            JOIN users u ON qu.user_id = u.user_id
            WHERE qu.quiz_status = 'completed'
            AND qu.end_time >= %s
            AND qu.user_id NOT IN (
                SELECT ru.user_id 
                FROM result_user ru 
                WHERE ru.result_step_id = 'career_path_v3'
                AND ru.is_active = 1
            )
            GROUP BY qu.user_id, u.firstname, u.lastname, u.email
            ORDER BY quiz_completed_at DESC
        ''', (start_date,))
        users_no_analysis = []
        for row in cursor.fetchall():
            users_no_analysis.append({
                'user_id': row['user_id'],
                'firstname': row['firstname'],
                'lastname': row['lastname'],
                'email': row['email'],
                'quiz_completed_at': row['quiz_completed_at'].isoformat() if row['quiz_completed_at'] else None
            })

        quiz_no_analysis = len(users_no_analysis)
        
        # =============================================================
        # 5. UTILISATEURS AVEC ANALYSE (pour le tableau)
        # =============================================================
        # Dans admin_analysis_stats, remplacer la requête des users_with_analysis par :

        cursor.execute('''
            SELECT 
                ru.user_id,
                u.firstname,
                u.lastname,
                u.email,
                ru.result_id,
                ru.created_at as analysis_date,
                ru.result_json,
                loc.answer_text as user_location
            FROM result_user ru
            JOIN users u ON ru.user_id = u.user_id
            LEFT JOIN (
                SELECT au.answer_text, qu.user_id
                FROM answer_user au
                JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
                WHERE au.question_id = 26
                AND au.created_at = (
                    SELECT MAX(au2.created_at)
                    FROM answer_user au2
                    JOIN quiz_user qu2 ON au2.quiz_session_id = qu2.quiz_session_id
                    WHERE qu2.user_id = qu.user_id AND au2.question_id = 26
                )
            ) loc ON loc.user_id = ru.user_id
            WHERE ru.is_active = 1
            AND ru.result_step_id = 'career_path_v3'
            AND ru.created_at >= %s
            ORDER BY ru.created_at DESC
        ''', (start_date,))
        users_with_analysis = cursor.fetchall()
        
        seen_users = set()
        unique_users = []
        for user in users_with_analysis:
            if user['user_id'] not in seen_users:
                seen_users.add(user['user_id'])
                unique_users.append(user)
        
        # =============================================================
        # 6. DÉTAILS PAR USER
        # =============================================================
        users_data = []
        piste_1_count = 0
        piste_2_count = 0
        piste_3_count = 0
        free_unlocks_count = 0
        paid_unlocks_count = 0
        
        for user in unique_users:
            user_id = user['user_id']
            
            cursor.execute('''
                SELECT DISTINCT used_for_piste, token_type
                FROM tokens
                WHERE user_id = %s AND used_at IS NOT NULL AND used_for_piste IS NOT NULL
                ORDER BY used_for_piste
            ''', (user_id,))
            unlocked_pistes_raw = cursor.fetchall()
            unlocked_piste_numbers = [p['used_for_piste'] for p in unlocked_pistes_raw]
            
            for p in unlocked_pistes_raw:
                if p['used_for_piste'] == 1:
                    piste_1_count += 1
                elif p['used_for_piste'] == 2:
                    piste_2_count += 1
                elif p['used_for_piste'] == 3:
                    piste_3_count += 1
                if p['token_type'] == 'free':
                    free_unlocks_count += 1
                else:
                    paid_unlocks_count += 1
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM tokens
                WHERE user_id = %s AND (is_used = 0 OR is_used IS NULL)
            ''', (user_id,))
            tokens_available = cursor.fetchone()['count'] or 0
            
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM tokens
                WHERE user_id = %s AND token_type = 'paid'
                AND created_at >= %s
            ''', (user_id, start_date))
            has_paid_token = (cursor.fetchone()['count'] or 0) > 0
            
            unlocked_pistes = []
            try:
                result_json = user['result_json']
                if isinstance(result_json, str):
                    result_json = json.loads(result_json)
                voies = result_json.get('voies', [])
                for piste_num in unlocked_piste_numbers:
                    if 0 < piste_num <= len(voies):
                        voie = voies[piste_num - 1]
                        unlocked_pistes.append({
                            'number': piste_num,
                            'title': voie.get('hero_title', f'Piste {piste_num}')
                        })
                    else:
                        unlocked_pistes.append({'number': piste_num, 'title': f'Piste {piste_num}'})
            except:
                unlocked_pistes = [{'number': p, 'title': f'Piste {p}'} for p in unlocked_piste_numbers]
            
            cursor.execute('''
                SELECT request_type, status, piste_number
                FROM user_help_requests
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 5
            ''', (user_id,))
            help_requests = cursor.fetchall()
            
            users_data.append({
                            'user_id': user_id,
                            'firstname': user['firstname'],
                            'lastname': user['lastname'],
                            'email': user['email'],
                            'user_location': user['user_location'], 
                            'analysis_date': user['analysis_date'].isoformat() if user['analysis_date'] else None,
                            'pistes_count': len(unlocked_piste_numbers),
                            'unlocked_pistes': unlocked_pistes,
                            'tokens_available': tokens_available,
                            'has_paid_token': has_paid_token,
                            'help_requests': [{'request_type': h['request_type'], 'status': h['status'], 'piste_number': h['piste_number']} for h in help_requests]
                        })
        
        # =============================================================
        # 7. STATS FINALES
        # =============================================================
        analyses_0 = sum(1 for u in users_data if u['pistes_count'] == 0)
        analyses_1 = sum(1 for u in users_data if u['pistes_count'] == 1)
        analyses_2 = sum(1 for u in users_data if u['pistes_count'] == 2)
        analyses_3 = sum(1 for u in users_data if u['pistes_count'] >= 3)
        users_paid = sum(1 for u in users_data if u['has_paid_token'])
        users_tokens_dispo = sum(1 for u in users_data if u['tokens_available'] > 0)
        
        mobile_unlocks = device_unlocks.get('mobile', 0)
        mobile_requests = device_requests.get('mobile', 0)
        desktop_unlocks = device_unlocks.get('desktop', 0)
        desktop_requests = device_requests.get('desktop', 0)
        mobile_ratio = round((mobile_requests / mobile_unlocks * 100), 1) if mobile_unlocks > 0 else 0
        desktop_ratio = round((desktop_requests / desktop_unlocks * 100), 1) if desktop_unlocks > 0 else 0
        
        return jsonify({
            'success': True,
            'current_filter': device_filter or 'all',
            'stats': {
                'funnel': {
                    'quiz_completed': total_quiz_completed,
                    'analyses_generated': total_analyses,
                    'unlocks': total_unlocks,
                    'requests': total_requests,
                    'quiz_to_analysis_rate': round((total_analyses / total_quiz_completed * 100), 1) if total_quiz_completed > 0 else 0,
                    'analysis_to_unlock_rate': round((total_unlocks / total_analyses * 100), 1) if total_analyses > 0 else 0,
                    'unlock_to_request_rate': round((total_requests / total_unlocks * 100), 1) if total_unlocks > 0 else 0,
                },
                'total_analyses': len(users_data),
                'analyses_0_piste': analyses_0,
                'analyses_1_piste': analyses_1,
                'analyses_2_pistes': analyses_2,
                'analyses_3_pistes': analyses_3,
                'piste_1_unlocks': piste_1_count,
                'piste_2_unlocks': piste_2_count,
                'piste_3_unlocks': piste_3_count,
                'free_unlocks': free_unlocks_count,
                'paid_unlocks': paid_unlocks_count,
                'quiz_no_analysis': quiz_no_analysis,
                'users_paid': users_paid,
                'users_tokens_dispo': users_tokens_dispo,
                'device_stats': {
                    'mobile': {'unlocks': mobile_unlocks, 'requests': mobile_requests, 'ratio': mobile_ratio},
                    'desktop': {'unlocks': desktop_unlocks, 'requests': desktop_requests, 'ratio': desktop_ratio},
                    'unknown': {'unlocks': device_unlocks.get('unknown', 0), 'requests': device_requests.get('unknown', 0)}
                }
            },
            'users': users_data,
            'users_no_analysis': users_no_analysis  # ✅ NOUVEAU : liste des users sans analyse
        })
        
    except Exception as e:
        logger.error(f"Error fetching analysis stats: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/admin/user-analysis/<int:user_id>', methods=['GET'])
@admin_required
def admin_user_analysis_detail(user_id):
    """Détail des analyses et pistes d'un utilisateur."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Infos user
        cursor.execute('SELECT user_id, firstname, lastname, email, phone_number FROM users WHERE user_id = %s', (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404
        
        # Tokens (pistes débloquées)
        cursor.execute('''
            SELECT token_code, token_type, used_for_piste, used_at
            FROM tokens WHERE user_id = %s AND used_at IS NOT NULL AND used_for_piste IS NOT NULL
            ORDER BY used_at DESC
        ''', (user_id,))
        tokens = cursor.fetchall()
        
        # Demandes d'aide
        cursor.execute('''
            SELECT id, piste_number, piste_title, request_type, status, created_at
            FROM user_help_requests WHERE user_id = %s ORDER BY created_at DESC
        ''', (user_id,))
        help_requests = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'user': {
                'user_id': user['user_id'],
                'firstname': user['firstname'],
                'lastname': user['lastname'],
                'email': user['email'],
                'phone_number': user['phone_number']
            },
            'tokens': [{
                'piste_number': t['used_for_piste'],
                'token_type': t['token_type'],
                'used_at': t['used_at'].isoformat() if t['used_at'] else None
            } for t in tokens],
            'help_requests': [{
                'id': h['id'],
                'piste_number': h['piste_number'],
                'request_type': h['request_type'],
                'status': h['status']
            } for h in help_requests]
        })
    except Exception as e:
        logger.error(f"Error fetching user analysis: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/admin/pistes-list', methods=['GET'])
@admin_required
def pistes_list():
    """Liste des pistes débloquées avec localisation."""
    
    start_date = datetime(2026, 1, 12, 0, 0, 0)
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute('''
            SELECT DISTINCT
                t.user_id,
                u.firstname,
                u.lastname,
                u.email,
                JSON_UNQUOTE(JSON_EXTRACT(
                    ru.result_json, 
                    CONCAT('$.voies[', t.used_for_piste - 1, '].hero_title')
                )) as piste_title,
                t.used_for_piste as piste_number,
                loc.answer_text as user_location
            FROM tokens t
            JOIN users u ON t.user_id = u.user_id
            JOIN result_user ru ON t.user_id = ru.user_id 
                AND ru.result_step_id = 'career_path_v3' 
                AND ru.is_active = 1
            LEFT JOIN (
                SELECT au.answer_text, qu.user_id
                FROM answer_user au
                JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
                WHERE au.question_id = 26
                AND au.created_at = (
                    SELECT MAX(au2.created_at)
                    FROM answer_user au2
                    JOIN quiz_user qu2 ON au2.quiz_session_id = qu2.quiz_session_id
                    WHERE qu2.user_id = qu.user_id AND au2.question_id = 26
                )
            ) loc ON loc.user_id = t.user_id
            WHERE t.used_at IS NOT NULL 
            AND t.used_for_piste IS NOT NULL
            AND t.used_at >= %s
            ORDER BY piste_title, loc.answer_text
        ''', (start_date,))
        
        rows = cursor.fetchall()
        
        return jsonify({
            'success': True,
            'pistes': [{
                'user_id': r['user_id'],
                'firstname': r['firstname'],
                'lastname': r['lastname'],
                'email': r['email'],
                'piste_title': r['piste_title'] or '',
                'piste_number': r['piste_number'],
                'user_location': r['user_location'] or ''
            } for r in rows]
        })
        
    except Exception as e:
        logger.error(f"Error fetching pistes: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/admin/engagement-stats', methods=['GET'])
@admin_required
def admin_engagement_stats():
    """Statistiques d'engagement (vues fiches, impressions) - UNIQUES par user."""
    
    start_date = datetime(2026, 1, 15, 0, 0, 0)
    period = request.args.get('period', '30')
    device_filter = request.args.get('device', '')
    
    # Filtre période
    if period == 'all':
        date_filter = "AND al.created_at >= %s"
        date_params = [start_date]
    else:
        date_filter = "AND al.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)"
        date_params = [int(period)]
    
    device_cond = ""
    if device_filter == 'mobile':
        device_cond = "AND al.device_type = 'mobile'"
    elif device_filter == 'desktop':
        device_cond = "AND al.device_type = 'desktop'"
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # =============================================================
        # 1. FUNNEL ENGAGEMENT
        # =============================================================
        
        # Total analyses - filtré par device si demandé
        if device_filter:
            cursor.execute(f'''
                SELECT COUNT(DISTINCT ru.user_id) as count
                FROM result_user ru
                JOIN activity_logs al ON al.user_id = ru.user_id 
                    AND al.created_at BETWEEN DATE_SUB(ru.created_at, INTERVAL 10 MINUTE) 
                    AND DATE_ADD(ru.created_at, INTERVAL 10 MINUTE)
                WHERE ru.is_active = 1
                AND ru.result_step_id = 'career_path_v3'
                {device_cond}
            ''')
        else:
            cursor.execute('''
                SELECT COUNT(DISTINCT ru.user_id) as count
                FROM result_user ru
                WHERE ru.is_active = 1
                AND ru.result_step_id = 'career_path_v3'
            ''')
        total_analyses = cursor.fetchone()['count'] or 0
        
        # Users UNIQUES ayant vu au moins 1 fiche
        cursor.execute(f'''
            SELECT COUNT(DISTINCT al.user_id) as count
            FROM activity_logs al
            WHERE al.event_type = 'piste_view'
            {date_filter}
            {device_cond}
        ''', tuple(date_params))
        total_users_viewed = cursor.fetchone()['count'] or 0
        
        # Users UNIQUES ayant imprimé
        cursor.execute(f'''
            SELECT COUNT(DISTINCT al.user_id) as count
            FROM activity_logs al
            WHERE al.event_type = 'piste_print'
            {date_filter}
            {device_cond}
        ''', tuple(date_params))
        total_users_printed = cursor.fetchone()['count'] or 0
        
        # Demandes (même logique)
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM user_help_requests
            WHERE created_at >= %s AND status != 'cancelled'
        ''', (start_date,))
        total_requests = cursor.fetchone()['count'] or 0
        
        # =============================================================
        # 2. STATS VUES PAR PISTE (USERS UNIQUES)
        # =============================================================
        cursor.execute(f'''
            SELECT 
                JSON_UNQUOTE(JSON_EXTRACT(al.extra_data, '$.piste_number')) as piste,
                COUNT(DISTINCT al.user_id) as unique_users
            FROM activity_logs al
            WHERE al.event_type = 'piste_view'
            AND JSON_EXTRACT(al.extra_data, '$.piste_number') IS NOT NULL
            {date_filter}
            {device_cond}
            GROUP BY piste
        ''', tuple(date_params))
        
        views_by_piste = {'1': 0, '2': 0, '3': 0}
        for row in cursor.fetchall():
            piste = str(row['piste'])
            if piste in views_by_piste:
                views_by_piste[piste] = row['unique_users']
        
        # =============================================================
        # 3. STATS DEVICE
        # =============================================================
        cursor.execute(f'''
            SELECT 
                COALESCE(al.device_type, 'unknown') as device,
                COUNT(DISTINCT al.user_id) as unique_users
            FROM activity_logs al
            WHERE al.event_type = 'piste_view'
            {date_filter}
            GROUP BY device
        ''', tuple(date_params))
        
        device_views = {'mobile': 0, 'desktop': 0, 'unknown': 0}
        for row in cursor.fetchall():
            device = row['device'] if row['device'] in device_views else 'unknown'
            device_views[device] = row['unique_users']
        
        cursor.execute(f'''
            SELECT 
                COALESCE(al.device_type, 'unknown') as device,
                COUNT(DISTINCT al.user_id) as unique_users
            FROM activity_logs al
            WHERE al.event_type = 'piste_print'
            {date_filter}
            GROUP BY device
        ''', tuple(date_params))
        
        device_prints = {'mobile': 0, 'desktop': 0, 'unknown': 0}
        for row in cursor.fetchall():
            device = row['device'] if row['device'] in device_prints else 'unknown'
            device_prints[device] = row['unique_users']
        
        # =============================================================
        # 4. DONNÉES PAR UTILISATEUR (pour le tableau)
        # On prend TOUS les users avec analyse (pas de filtre date)
        # car on veut tracker l'engagement même sur anciennes analyses
        # =============================================================
        # Dans admin_engagement_stats, remplacer la requête des users_with_analysis par :

        cursor.execute('''
            SELECT 
                ru.user_id,
                u.firstname,
                u.lastname,
                u.email,
                ru.created_at as analysis_date,
                loc.answer_text as user_location
            FROM result_user ru
            JOIN users u ON ru.user_id = u.user_id
            LEFT JOIN (
                SELECT au.answer_text, qu.user_id
                FROM answer_user au
                JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
                WHERE au.question_id = 26
                AND au.created_at = (
                    SELECT MAX(au2.created_at)
                    FROM answer_user au2
                    JOIN quiz_user qu2 ON au2.quiz_session_id = qu2.quiz_session_id
                    WHERE qu2.user_id = qu.user_id AND au2.question_id = 26
                )
            ) loc ON loc.user_id = ru.user_id
            WHERE ru.is_active = 1
            AND ru.result_step_id = 'career_path_v3'
            ORDER BY ru.created_at DESC
        ''')
        users_with_analysis = cursor.fetchall()
        
        # Dédupliquer
        seen_users = set()
        unique_users = []
        for user in users_with_analysis:
            if user['user_id'] not in seen_users:
                seen_users.add(user['user_id'])
                unique_users.append(user)
        
        users_data = []
        for user in unique_users:
            user_id = user['user_id']
            
            # Vues par piste pour ce user
            cursor.execute('''
                SELECT 
                    JSON_UNQUOTE(JSON_EXTRACT(extra_data, '$.piste_number')) as piste,
                    COUNT(*) as view_count
                FROM activity_logs
                WHERE user_id = %s 
                AND event_type = 'piste_view'
                AND JSON_EXTRACT(extra_data, '$.piste_number') IS NOT NULL
                GROUP BY piste
            ''', (user_id,))
            
            user_views = {'1': 0, '2': 0, '3': 0}
            for row in cursor.fetchall():
                piste = str(row['piste'])
                if piste in user_views:
                    user_views[piste] = row['view_count']
            
            # A imprimé ?
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM activity_logs
                WHERE user_id = %s AND event_type = 'piste_print'
            ''', (user_id,))
            has_printed = (cursor.fetchone()['count'] or 0) > 0
            
            # Requête 1 : Le dernier choix positif actif
            cursor.execute('''
                SELECT request_type, status, piste_number, piste_title, initial_interest
                FROM user_help_requests
                WHERE user_id = %s
                AND initial_interest != 'no'
                AND status NOT IN ('cancelled', 'completed')
                ORDER BY created_at DESC
                LIMIT 1
            ''', (user_id,))
            active_choice = cursor.fetchone()

            # Requête 2 : Les déclins (dernier par piste)
            cursor.execute('''
                SELECT hr1.request_type, hr1.status, hr1.piste_number, hr1.piste_title, hr1.initial_interest
                FROM user_help_requests hr1
                WHERE hr1.user_id = %s
                AND hr1.initial_interest = 'no'
                AND hr1.created_at = (
                    SELECT MAX(hr2.created_at)
                    FROM user_help_requests hr2
                    WHERE hr2.user_id = hr1.user_id
                    AND hr2.piste_number = hr1.piste_number
                    AND hr2.initial_interest = 'no'
                )
                ORDER BY hr1.piste_number
            ''', (user_id,))
            declines = cursor.fetchall()

            # Combiner : choix actif + déclins (sauf piste du choix actif)
            user_requests = []
            active_piste = active_choice['piste_number'] if active_choice else None

            if active_choice:
                user_requests.append(active_choice)

            for decline in declines:
                if decline['piste_number'] != active_piste:
                    user_requests.append(decline)
            
            # Nombre de fiches DIFFÉRENTES vues (pas le total des vues)
            fiches_vues = sum(1 for v in [user_views['1'], user_views['2'], user_views['3']] if v > 0)
            
            # Récupérer les titres des pistes depuis result_json
            piste_titles = {1: 'Piste 1', 2: 'Piste 2', 3: 'Piste 3'}
            try:
                cursor.execute('''
                    SELECT result_json FROM result_user 
                    WHERE user_id = %s AND result_step_id = 'career_path_v3' AND is_active = 1
                    LIMIT 1
                ''', (user_id,))
                result_row = cursor.fetchone()
                if result_row and result_row['result_json']:
                    result_json = result_row['result_json']
                    if isinstance(result_json, str):
                        result_json = json.loads(result_json)
                    voies = result_json.get('voies', [])
                    for i, voie in enumerate(voies[:3], 1):
                        piste_titles[i] = voie.get('hero_title', f'Piste {i}')
            except:
                pass
            
            # Construire la liste des pistes vues avec leurs titres
            viewed_pistes = []
            if user_views['1'] > 0:
                viewed_pistes.append({'number': 1, 'title': piste_titles[1], 'views': user_views['1']})
            if user_views['2'] > 0:
                viewed_pistes.append({'number': 2, 'title': piste_titles[2], 'views': user_views['2']})
            if user_views['3'] > 0:
                viewed_pistes.append({'number': 3, 'title': piste_titles[3], 'views': user_views['3']})
            
            users_data.append({
                'user_id': user_id,
                'firstname': user['firstname'],
                'lastname': user['lastname'],
                'email': user['email'],
                'user_location': user['user_location'],
                'analysis_date': user['analysis_date'].isoformat() if user['analysis_date'] else None,
                'views_p1': user_views['1'],
                'views_p2': user_views['2'],
                'views_p3': user_views['3'],
                'fiches_vues': fiches_vues,
                'viewed_pistes': viewed_pistes,
                'piste_titles': piste_titles,
                'has_printed': has_printed,
                'help_requests': [{
                    'request_type': r['request_type'],
                    'status': r['status'],
                    'piste_number': r['piste_number'],
                    'piste_title': r['piste_title'] or piste_titles.get(r['piste_number'], ''),
                    'initial_interest': r['initial_interest']
                } for r in user_requests]
            })
        
        # =============================================================
        # 5. STATS CALCULÉES (basées sur fiches DIFFÉRENTES vues)
        # =============================================================
        users_with_views = sum(1 for u in users_data if u['fiches_vues'] > 0)
        engagement_rate = round((users_with_views / len(users_data) * 100), 1) if users_data else 0
        
        # Piste favorite (plus de users uniques)
        popular_piste = max(views_by_piste, key=views_by_piste.get) if any(views_by_piste.values()) else None
        
        # Calculer users avec demande parmi ceux qui ont vu
        users_viewed_ids = set(u['user_id'] for u in users_data if u['fiches_vues'] > 0)
        users_with_request_ids = set(u['user_id'] for u in users_data if len(u['help_requests']) > 0)
        users_viewed_with_request = len(users_viewed_ids & users_with_request_ids)
        
        viewed_to_request_rate = round((users_viewed_with_request / len(users_viewed_ids) * 100), 1) if users_viewed_ids else 0
        mobile_views = device_views.get('mobile', 0)
        mobile_prints = device_prints.get('mobile', 0)
        desktop_views = device_views.get('desktop', 0)
        desktop_prints = device_prints.get('desktop', 0)
        mobile_ratio = round((mobile_prints / mobile_views * 100), 1) if mobile_views > 0 else 0
        desktop_ratio = round((desktop_prints / desktop_views * 100), 1) if desktop_views > 0 else 0
        
        return jsonify({
            'success': True,
            'mode': 'engagement',
            'stats': {
                'funnel': {
                    'analyses_generated': total_analyses,
                    'users_viewed': total_users_viewed,
                    'users_printed': total_users_printed,
                    'users_with_request': users_viewed_with_request,
                    'analysis_to_view_rate': round((total_users_viewed / total_analyses * 100), 1) if total_analyses > 0 else 0,
                    'view_to_print_rate': round((total_users_printed / total_users_viewed * 100), 1) if total_users_viewed > 0 else 0,
                    'view_to_request_rate': viewed_to_request_rate,
                },
                'total_analyses': len(users_data),
                'users_0_views': sum(1 for u in users_data if u['fiches_vues'] == 0),
                'users_1_view': sum(1 for u in users_data if u['fiches_vues'] == 1),
                'users_2_views': sum(1 for u in users_data if u['fiches_vues'] == 2),
                'users_3plus_views': sum(1 for u in users_data if u['fiches_vues'] >= 3),
                'views_p1': views_by_piste['1'],
                'views_p2': views_by_piste['2'],
                'views_p3': views_by_piste['3'],
                'users_printed': total_users_printed,
                'engagement_rate': engagement_rate,
                'popular_piste': popular_piste,
                'popular_piste_views': views_by_piste.get(popular_piste, 0) if popular_piste else 0,
                'device_stats': {
                    'mobile': {'views': mobile_views, 'prints': mobile_prints, 'ratio': mobile_ratio},
                    'desktop': {'views': desktop_views, 'prints': desktop_prints, 'ratio': desktop_ratio},
                    'unknown': {'views': device_views.get('unknown', 0), 'prints': device_prints.get('unknown', 0)}
                }
            },
            'users': users_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching engagement stats: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/piste-interest/decline', methods=['POST'])
@login_required
def decline_piste_interest():
    """Enregistre un 'Pas trop' pour une piste."""
    data = request.json
    
    target_user_id = data.get('user_id')
    if target_user_id and current_user.user_status in ('admin', 'coach'):
        user_id_for_request = int(target_user_id)
    else:
        user_id_for_request = current_user.id
    
    quiz_id = data.get('quiz_id')
    piste_number = data.get('piste_number')
    piste_title = data.get('piste_title', '')
    
    if not quiz_id or not piste_number:
        return jsonify({'success': False, 'error': 'quiz_id et piste_number requis'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            INSERT INTO user_help_requests (
                user_id, quiz_id, piste_number, piste_title,
                request_type, initial_interest,
                source_page, source_action, status, priority
            ) VALUES (%s, %s, %s, %s, 'piste_interest', 'no', 'analysis_view', 'piste_decline', 'completed', 'low')
        """, (user_id_for_request, quiz_id, int(piste_number), piste_title))
        
        current_app.mysql.connection.commit()
        
        return jsonify({'success': True, 'message': 'Réponse enregistrée'})
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"Error in decline_piste_interest: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/user-location/<int:user_id>', methods=['GET'])
@login_required
def get_user_location(user_id):
    """
    Récupère la localisation (ville/région) d'un utilisateur depuis sa réponse au quiz.
    La question de localisation est la question 26.
    """
    # Vérification des droits
    if current_user.id != user_id and current_user.user_status not in ('admin', 'coach'):
        return jsonify({'success': False, 'error': 'Accès non autorisé'}), 403
    
    quiz_id = request.args.get('quiz_id', 'pack_clarte')
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Récupérer la réponse à la question de localisation (question 26)
        cursor.execute("""
            SELECT 
                au.answer_value,
                au.answer_text,
                au.created_at
            FROM answer_user au
            JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
            WHERE qu.user_id = %s 
            AND qu.quiz_id = %s
            AND au.question_id = 26
            ORDER BY au.created_at DESC
            LIMIT 1
        """, (user_id, quiz_id))
        
        location_answer = cursor.fetchone()
        
        if not location_answer:
            return jsonify({
                'success': True,
                'has_location': False,
                'location': None,
                'message': 'Aucune localisation trouvée pour cet utilisateur'
            })
        
        # Parser la réponse
        location_data = {
            'raw_value': location_answer['answer_value'],
            'display_text': location_answer['answer_text'],
            'answered_at': location_answer['created_at'].isoformat() if location_answer['created_at'] else None
        }
        
        # Essayer de parser le JSON si c'est un objet structuré
        try:
            if location_answer['answer_value']:
                import json
                parsed = json.loads(location_answer['answer_value']) if isinstance(location_answer['answer_value'], str) else location_answer['answer_value']
                
                if isinstance(parsed, list) and len(parsed) > 0:
                    # Format attendu: ["Ville, Région"] ou ["Ville"]
                    location_string = parsed[0]
                    parts = location_string.split(', ')
                    
                    location_data['city'] = parts[0] if len(parts) > 0 else None
                    location_data['region'] = parts[1] if len(parts) > 1 else None
                elif isinstance(parsed, dict):
                    location_data['city'] = parsed.get('name') or parsed.get('city')
                    location_data['region'] = parsed.get('region')
                    location_data['display_name'] = parsed.get('display_name')
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(f"Could not parse location JSON for user {user_id}: {e}")
            # Fallback: utiliser answer_text directement
            if location_answer['answer_text']:
                parts = location_answer['answer_text'].split(', ')
                location_data['city'] = parts[0] if len(parts) > 0 else location_answer['answer_text']
                location_data['region'] = parts[1] if len(parts) > 1 else None
        
        return jsonify({
            'success': True,
            'has_location': True,
            'location': location_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching user location: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
        
    finally:
        cursor.close()

@help_requests_bp.route('/admin/v4-tracking-stats', methods=['GET'])
@login_required
def v4_tracking_stats():
    """Stats du tracking V4 (user_analysis_interactions)."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # ── Funnel de progression ──
        # Total users ayant vu la page
        cursor.execute("""
            SELECT COUNT(DISTINCT user_id) as total
            FROM user_analysis_interactions
            WHERE interaction_type = 'section_view' AND JSON_UNQUOTE(JSON_EXTRACT(payload, '$.section_index')) = '0'
        """)
        users_welcome = cursor.fetchone()['total']
        
        # Users ayant atteint chaque section (max section_index)
        cursor.execute("""
            SELECT user_id, MAX(CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.section_index')) AS UNSIGNED)) as max_section
            FROM user_analysis_interactions
            WHERE interaction_type = 'section_view'
            GROUP BY user_id
        """)
        progress_rows = cursor.fetchall()
        
        users_section = {0: 0, 1: 0, 2: 0, 3: 0}
        for row in progress_rows:
            max_s = int(row['max_section']) if row['max_section'] is not None else 0
            for s in range(max_s + 1):
                users_section[s] = users_section.get(s, 0) + 1
        
        total_users = len(progress_rows)
        
        # ── Feedbacks accuracy ──
        cursor.execute("""
            SELECT 
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.rating')) as rating,
                COUNT(*) as cnt
            FROM user_analysis_interactions
            WHERE interaction_type = 'accuracy_feedback'
            GROUP BY rating
        """)
        accuracy_stats = {r['rating']: r['cnt'] for r in cursor.fetchall()}
        
        # ── Feedbacks pistes (dernier feedback par user/piste) ──
        cursor.execute("""
            SELECT t.user_id as user_id, t.piste_number as piste_number, 
                   JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.interested')) as interested
            FROM user_analysis_interactions t
            WHERE t.id IN (
                SELECT MAX(id) FROM user_analysis_interactions
                WHERE interaction_type = 'piste_feedback'
                GROUP BY user_id, piste_number
            )
        """)
        piste_feedback_rows = cursor.fetchall()
        
        piste_stats = {}
        for row in piste_feedback_rows:
            pn = row['piste_number']
            if pn not in piste_stats:
                piste_stats[pn] = {'interested': 0, 'not_interested': 0}
            if row['interested'] == 'true':
                piste_stats[pn]['interested'] += 1
            else:
                piste_stats[pn]['not_interested'] += 1
        
        # ── Pack interest ──
        cursor.execute("""
            SELECT 
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.action')) as action,
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.product_id')) as product_id,
                COUNT(DISTINCT user_id) as users
            FROM user_analysis_interactions
            WHERE interaction_type = 'pack_interest'
            GROUP BY action, product_id
        """)
        pack_stats = [{'action': r['action'], 'product_id': r['product_id'], 'users': r['users']} for r in cursor.fetchall()]
        
        # ── Booking requests ──
        cursor.execute("""
            SELECT user_id, payload, created_at
            FROM user_analysis_interactions
            WHERE interaction_type = 'booking_request'
            ORDER BY created_at DESC
        """)
        booking_rows = cursor.fetchall()
        
        bookings = []
        for row in booking_rows:
            payload = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            bookings.append({
                'user_id': row['user_id'],
                'firstname': payload.get('firstname', ''),
                'lastname': payload.get('lastname', ''),
                'email': payload.get('email', ''),
                'phone': payload.get('phone', ''),
                'created_at': row['created_at'].isoformat() if row['created_at'] else None
            })
        
        # ── Liste des users avec leur progression ──
        cursor.execute("""
            SELECT 
                i.user_id as user_id,
                u.firstname,
                u.lastname,
                u.email,
                MAX(CAST(JSON_UNQUOTE(JSON_EXTRACT(i.payload, '$.section_index')) AS UNSIGNED)) as max_section,
                MIN(i.created_at) as first_visit,
                MAX(i.created_at) as last_visit
            FROM user_analysis_interactions i
            LEFT JOIN users u ON i.user_id = u.user_id
            WHERE i.interaction_type = 'section_view'
            GROUP BY i.user_id, u.firstname, u.lastname, u.email
            ORDER BY last_visit DESC
        """)
        user_rows = cursor.fetchall()
        
        # Enrichir avec feedbacks par user
        cursor.execute("""
            SELECT t.user_id as user_id, t.piste_number as piste_number, 
                   JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.interested')) as interested
            FROM user_analysis_interactions t
            WHERE t.id IN (
                SELECT MAX(id) FROM user_analysis_interactions
                WHERE interaction_type = 'piste_feedback'
                GROUP BY user_id, piste_number
            )
        """)
        user_feedbacks = {}
        for row in cursor.fetchall():
            uid = row['user_id']
            if uid not in user_feedbacks:
                user_feedbacks[uid] = {}
            user_feedbacks[uid][row['piste_number']] = row['interested'] == 'true'
        
        # Enrichir avec accuracy par user
        cursor.execute("""
            SELECT t.user_id as user_id, JSON_UNQUOTE(JSON_EXTRACT(t.payload, '$.rating')) as rating
            FROM user_analysis_interactions t
            WHERE t.id IN (
                SELECT MAX(id) FROM user_analysis_interactions
                WHERE interaction_type = 'accuracy_feedback'
                GROUP BY user_id
            )
        """)
        user_accuracy = {r['user_id']: r['rating'] for r in cursor.fetchall()}
        
        # Enrichir avec booking par user
        user_bookings = {}
        for b in bookings:
            user_bookings[b['user_id']] = True

        # Enrichir avec action_count + days_active par user
        cursor.execute("""
            SELECT user_id,
                COUNT(*) as action_count,
                COUNT(DISTINCT DATE(created_at)) as days_active
            FROM user_analysis_interactions
            GROUP BY user_id
        """)
        user_activity = {r['user_id']: {'action_count': r['action_count'], 'days_active': r['days_active']} for r in cursor.fetchall()}

        # Enrichir avec pack_clicks par user
        cursor.execute("""
            SELECT user_id,
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.action')) as action,
                JSON_UNQUOTE(JSON_EXTRACT(payload, '$.product_id')) as product_id
            FROM user_analysis_interactions
            WHERE interaction_type = 'pack_interest'
            ORDER BY created_at ASC
        """)
        user_pack_clicks = {}
        for r in cursor.fetchall():
            uid = r['user_id']
            if uid not in user_pack_clicks:
                user_pack_clicks[uid] = []
            user_pack_clicks[uid].append({'action': r['action'], 'product_id': r['product_id']})
        
        users = []
        for row in user_rows:
            uid = row['user_id']
            users.append({
                'user_id': uid,
                'firstname': row['firstname'],
                'lastname': row['lastname'],
                'email': row['email'],
                'max_section': int(row['max_section']) if row['max_section'] is not None else 0,
                'first_visit': row['first_visit'].isoformat() if row['first_visit'] else None,
                'last_visit': row['last_visit'].isoformat() if row['last_visit'] else None,
                'accuracy': user_accuracy.get(uid),
                'feedbacks': user_feedbacks.get(uid, {}),
                'has_booking': user_bookings.get(uid, False),
                'action_count': user_activity.get(uid, {}).get('action_count', 0),
                'days_active': user_activity.get(uid, {}).get('days_active', 0),
                'pack_clicks': user_pack_clicks.get(uid, []),
            })
        
        return jsonify({
            'success': True,
            'stats': {
                'funnel': {
                    'total_users': total_users,
                    'welcome': users_section.get(0, 0),
                    'diagnostic': users_section.get(1, 0),
                    'pistes': users_section.get(2, 0),
                    'suite': users_section.get(3, 0),
                    'rates': {
                        'welcome_to_diagnostic': round(users_section.get(1, 0) / users_section.get(0, 1) * 100) if users_section.get(0, 0) > 0 else 0,
                        'diagnostic_to_pistes': round(users_section.get(2, 0) / users_section.get(1, 1) * 100) if users_section.get(1, 0) > 0 else 0,
                        'pistes_to_suite': round(users_section.get(3, 0) / users_section.get(2, 1) * 100) if users_section.get(2, 0) > 0 else 0,
                    }
                },
                'accuracy': accuracy_stats,
                'piste_feedbacks': {str(k): v for k, v in piste_stats.items()},
                'pack_interest': pack_stats,
                'bookings_count': len(bookings),
            },
            'bookings': bookings,
            'users': users
        })
        
    except Exception as e:
        logger.error(f"Error getting V4 tracking stats: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()

@help_requests_bp.route('/admin/v4-tracking')
@login_required
def admin_v4_tracking():
    return render_template('admin/admin_v4_tracking.html')


@help_requests_bp.route('/admin/user-recap/<int:user_id>', methods=['GET'])
@admin_required
def admin_user_recap(user_id):
    """Recap complet d'un user pour Claire : profil, réponses, interactions V4, JSON analyse."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # 1. Infos user
        cursor.execute('SELECT user_id, firstname, lastname, email, phone_number, created_at FROM users WHERE user_id = %s', (user_id,))
        user = cursor.fetchone()
        if not user:
            return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404
        for df in ['created_at']:
            if user.get(df):
                user[df] = user[df].isoformat()

        # 2. Localisation
        cursor.execute("""
            SELECT au.answer_text
            FROM answer_user au
            JOIN quiz_user qu ON au.quiz_session_id = qu.quiz_session_id
            WHERE qu.user_id = %s AND au.question_id = 26
            ORDER BY au.created_at DESC LIMIT 1
        """, (user_id,))
        loc_row = cursor.fetchone()
        user['location'] = loc_row['answer_text'] if loc_row else None

        # 3. Questions & réponses — même logique que get_quiz_responses dans views.py
        cursor.execute("""
            SELECT qu.quiz_id, qu.quiz_session_id
            FROM quiz_user qu
            WHERE qu.user_id = %s AND qu.quiz_status = 'completed'
            ORDER BY qu.end_time DESC LIMIT 1
        """, (user_id,))
        session_row = cursor.fetchone()
        
        quiz_id = session_row['quiz_id'] if session_row else None
        quiz_session_id = session_row['quiz_session_id'] if session_row else None
        
        questions = []
        if quiz_session_id:
            cursor.execute("""
                SELECT 
                    au.question_id,
                    au.answer_value,
                    au.answer_text,
                    qc.question as question_text,
                    qc.question_type,
                    at2.transcription
                FROM answer_user au
                JOIN questions_catalog qc ON au.question_id = qc.question_id
                LEFT JOIN audio_transcriptions at2 ON (
                    au.quiz_session_id = at2.quiz_session_id 
                    AND au.question_id = at2.question_id
                )
                WHERE au.quiz_session_id = %s
                ORDER BY au.question_id
            """, (quiz_session_id,))
            
            for row in cursor.fetchall():
                # Détecter réponse audio (même logique que get_quiz_responses)
                is_audio = False
                try:
                    av = json.loads(row['answer_value']) if row['answer_value'] else []
                    is_audio = isinstance(av, list) and len(av) > 0 and av[0] == '[AUDIO_RESPONSE]'
                except (json.JSONDecodeError, TypeError):
                    pass
                
                if is_audio and row['transcription']:
                    answer = row['transcription']
                else:
                    answer = row['answer_text'] or '[Non répondu]'
                
                questions.append({
                    'question': row['question_text'],
                    'answer': answer
                })

        # 4. Interactions V4
        interactions = {
            'accuracy': None,
            'accuracy_comment': None,
            'piste_feedbacks': {},
            'pack_interests': [],
            'booking': None,
            'max_section': 0,
            'first_visit': None,
            'last_visit': None
        }
        
        # Progression
        cursor.execute("""
            SELECT 
                MAX(CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.section_index')) AS UNSIGNED)) as max_section,
                MIN(created_at) as first_visit,
                MAX(created_at) as last_visit
            FROM user_analysis_interactions
            WHERE user_id = %s AND interaction_type = 'section_view'
        """, (user_id,))
        prog = cursor.fetchone()
        if prog and prog['max_section'] is not None:
            interactions['max_section'] = int(prog['max_section'])
            interactions['first_visit'] = prog['first_visit'].isoformat() if prog['first_visit'] else None
            interactions['last_visit'] = prog['last_visit'].isoformat() if prog['last_visit'] else None

        # Accuracy
        cursor.execute("""
            SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.rating')) as rating,
                   JSON_UNQUOTE(JSON_EXTRACT(payload, '$.comment')) as comment
            FROM user_analysis_interactions
            WHERE user_id = %s AND interaction_type = 'accuracy_feedback'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        acc = cursor.fetchone()
        if acc:
            interactions['accuracy'] = acc['rating']
            interactions['accuracy_comment'] = acc['comment'] if acc['comment'] and acc['comment'] != 'null' else None

        # Piste feedbacks
        cursor.execute("""
            SELECT COALESCE(piste_number, JSON_UNQUOTE(JSON_EXTRACT(payload, '$.piste_number'))) as pn,
                   JSON_UNQUOTE(JSON_EXTRACT(payload, '$.interested')) as interested
            FROM user_analysis_interactions
            WHERE user_id = %s AND interaction_type = 'piste_feedback'
            ORDER BY created_at DESC
        """, (user_id,))
        seen_pistes = set()
        for row in cursor.fetchall():
            pn = row['pn']
            if pn is None or pn in seen_pistes:
                continue
            seen_pistes.add(pn)
            interactions['piste_feedbacks'][int(pn)] = str(row['interested']).lower() in ('true', '1')

        # Pack interest
        cursor.execute("""
            SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.action')) as action,
                   JSON_UNQUOTE(JSON_EXTRACT(payload, '$.product_id')) as product_id,
                   created_at
            FROM user_analysis_interactions
            WHERE user_id = %s AND interaction_type = 'pack_interest'
            ORDER BY created_at DESC
        """, (user_id,))
        for row in cursor.fetchall():
            interactions['pack_interests'].append({
                'action': row['action'],
                'product_id': row['product_id'],
                'date': row['created_at'].isoformat() if row['created_at'] else None
            })

        # Booking
        cursor.execute("""
            SELECT payload, created_at
            FROM user_analysis_interactions
            WHERE user_id = %s AND interaction_type = 'booking_request'
            ORDER BY created_at DESC LIMIT 1
        """, (user_id,))
        booking_row = cursor.fetchone()
        if booking_row:
            bp = json.loads(booking_row['payload']) if isinstance(booking_row['payload'], str) else booking_row['payload']
            interactions['booking'] = {
                'firstname': bp.get('firstname', ''),
                'lastname': bp.get('lastname', ''),
                'email': bp.get('email', ''),
                'phone': bp.get('phone', ''),
                'pack': bp.get('pack', ''),
                'date': booking_row['created_at'].isoformat() if booking_row['created_at'] else None
            }

        # 5. JSON de l'analyse (V4 d'abord, sinon V3)
        analysis_json = None
        for step in ['career_path_v4', 'career_path_v3']:
            cursor.execute("""
                SELECT result_json, generator_type, created_at
                FROM result_user
                WHERE user_id = %s AND result_step_id = %s AND is_active = 1
                ORDER BY FIELD(generator_type, 'admin', 'user'), created_at DESC
                LIMIT 1
            """, (user_id, step))
            result_row = cursor.fetchone()
            if result_row:
                rj = result_row['result_json']
                if isinstance(rj, str):
                    rj = json.loads(rj)
                analysis_json = {
                    'step': step,
                    'generator_type': result_row['generator_type'],
                    'created_at': result_row['created_at'].isoformat() if result_row['created_at'] else None,
                    'data': rj
                }
                break
            
        # 6. Timeline complète
        cursor.execute("""
            SELECT interaction_type, piste_number, payload, created_at
            FROM user_analysis_interactions
            WHERE user_id = %s
            ORDER BY created_at ASC
        """, (user_id,))
        timeline = []
        for row in cursor.fetchall():
            p = json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload']
            timeline.append({
                'type': row['interaction_type'],
                'piste_number': row['piste_number'],
                'payload': p,
                'time': row['created_at'].isoformat() if row['created_at'] else None
            })

        return jsonify({
            'success': True,
            'user': user,
            'quiz_id': quiz_id,
            'questions': questions,
            'interactions': interactions,
            'analysis': analysis_json,
            'timeline': timeline
        })
        
    except Exception as e:
        logger.error(f"Error in user recap: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()