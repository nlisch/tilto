"""
Routes Flask pour la génération d'analyses asynchrones.

Blueprint: async_analysis_bp
URL Prefix: /analysis/async

Routes:
- POST /create - Créer un job async (admin)
- POST /process - Handler Cloud Tasks (appelé par GCP)
- POST /process-manual/<uuid> - Traiter manuellement un job (admin, debug)
- GET /status/<uuid> - Statut d'un job
- POST /cancel/<uuid> - Annuler un job pending
- POST /retry/<uuid> - Relancer un job échoué
- GET /jobs - Liste des jobs (admin)
- GET /pending/<user_id>/<quiz_id> - Jobs en attente pour un user
- GET /monitor - Page de monitoring (admin)
- POST /cleanup - Nettoyer les vieux jobs (admin)
- GET /stats - Statistiques (admin)
"""

from flask import Blueprint, jsonify, request, current_app, render_template
from flask_login import login_required, current_user
from decorators import admin_required
from MySQLdb.cursors import DictCursor
from datetime import datetime
import logging
import hmac
import json
from extensions import csrf

logger = logging.getLogger(__name__)

# Blueprint
async_analysis_bp = Blueprint('async_analysis', __name__, url_prefix='/analysis/async')


def verify_cloud_tasks_request():
    """Vérifie que la requête provient bien de Cloud Tasks."""
    # Header ajouté par notre code
    if request.headers.get('X-CloudTasks-Internal') == 'true':
        return True
    
    # Headers ajoutés par Cloud Tasks
    if request.headers.get('X-CloudTasks-QueueName'):
        return True
    
    # Secret partagé (optionnel)
    secret = current_app.config.get('CLOUD_TASKS_SECRET')
    if secret:
        provided = request.headers.get('X-CloudTasks-Secret')
        if provided and hmac.compare_digest(secret, provided):
            return True
    
    return False


# ============================================================
# ROUTE: Créer un job async (depuis interface admin)
# ============================================================

@async_analysis_bp.route('/create', methods=['POST'])
@admin_required
def create_async_job():
    """
    Crée un job de génération d'analyse asynchrone.
    
    En mode DEBUG: traitement direct
    En mode PROD: crée une tâche Cloud Tasks
    """
    data = request.json
    
    user_id = data.get('user_id')
    quiz_id = data.get('quiz_id')
    step_id = data.get('step_id', 'career_path_v3')
    
    if not user_id or not quiz_id:
        return jsonify({'success': False, 'error': 'user_id et quiz_id requis'}), 400
    
    generation_params = {
        'system_prompt': data.get('system_prompt', ''),
        'human_prompt': data.get('human_prompt', ''),
        'instructions': data.get('instructions', ''),
        'knowledge': data.get('knowledge', ''),
        'validation_criteria': data.get('validation_criteria', '')
    }
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        # Vérifier qu'il n'y a pas déjà un job pending
        existing = AsyncAnalysisService.get_user_pending_jobs(cursor, int(user_id), quiz_id)
        if existing:
            return jsonify({
                'success': False,
                'error': 'Un job est déjà en cours pour cet utilisateur',
                'existing_job': existing[0]['job_uuid']
            }), 409
        
        # Créer le job
        job_uuid = AsyncAnalysisService.create_async_job(
            cursor=cursor,
            user_id=int(user_id),
            quiz_id=quiz_id,
            step_id=step_id,
            generation_params=generation_params,
            admin_id=current_user.id,
            generator_type='admin'
        )
        
        current_app.mysql.connection.commit()
        
        # En mode DEBUG, le job est déjà traité
        is_debug = current_app.config.get('DEBUG', False)
        
        logger.info(f"[ASYNC] Job {job_uuid} created by admin {current_user.id} (debug={is_debug})")
        
        return jsonify({
            'success': True,
            'job_uuid': job_uuid,
            'status': 'completed' if is_debug else 'pending',
            'message': 'Job traité directement (mode DEBUG)' if is_debug else 'Job créé, traitement en arrière-plan'
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Error creating job: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Handler Cloud Tasks (appelé par GCP)
# ============================================================

@async_analysis_bp.route('/process', methods=['POST'])
@csrf.exempt
def process_async_job():
    """
    Handler appelé par Cloud Tasks pour traiter un job.
    Ne nécessite pas d'auth utilisateur mais vérifie l'origine.
    """
    # Vérifier l'origine (sauf en DEBUG)
    if not current_app.config.get('DEBUG', False):
        if not verify_cloud_tasks_request():
            logger.warning("[ASYNC] Unauthorized request to /process")
            return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.json or {}
    job_uuid = data.get('job_uuid')
    
    if not job_uuid:
        return jsonify({'error': 'job_uuid requis'}), 400
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        result = AsyncAnalysisService.process_job(job_uuid)  # ← Plus de cursor
        current_app.mysql.connection.commit()
        
        # Toujours retourner 200 pour éviter les retries Cloud Tasks
        return jsonify(result), 200
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Handler error for job {job_uuid}: {e}", exc_info=True)
        # 500 pour que Cloud Tasks retry
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Traiter manuellement un job (pour tests/debug)
# ============================================================

@async_analysis_bp.route('/process-manual/<string:job_uuid>', methods=['POST'])
@admin_required
def process_job_manual(job_uuid: str):
    """
    Traite manuellement un job (pour tests ou débloquer un job stuck).
    Utile quand Cloud Tasks a échoué.
    """
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        # Vérifier que le job existe
        cursor.execute("SELECT job_status FROM async_analysis_jobs WHERE job_uuid = %s", (job_uuid,))
        job = cursor.fetchone()
        
        if not job:
            return jsonify({'success': False, 'error': 'Job non trouvé'}), 404
        
        # Si le job n'est pas pending, le forcer à pending d'abord
        if job['job_status'] != 'pending':
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET job_status = 'pending', started_at = NULL, completed_at = NULL, error_message = NULL
                WHERE job_uuid = %s
            """, (job_uuid,))
            current_app.mysql.connection.commit()
            logger.info(f"[ASYNC] Job {job_uuid} reset to pending for manual processing")
        
        # Traiter
        result = AsyncAnalysisService.process_job(job_uuid)
        current_app.mysql.connection.commit()
        
        return jsonify(result)
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Manual processing error for {job_uuid}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Statut d'un job
# ============================================================

@async_analysis_bp.route('/status/<string:job_uuid>', methods=['GET'])
def get_job_status(job_uuid: str):
    """Récupère le statut détaillé d'un job."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        cursor.execute("""
            SELECT 
                j.*,
                u.firstname as user_firstname,
                u.email as user_email
            FROM async_analysis_jobs j
            LEFT JOIN users u ON j.user_id = u.user_id
            WHERE j.job_uuid = %s
        """, (job_uuid,))
        
        job = cursor.fetchone()
        
        if not job:
            return jsonify({'success': False, 'error': 'Job non trouvé'}), 404
        
        # Parser JSON
        generation_params = None
        error_details = None
        
        if job.get('generation_params'):
            try:
                generation_params = json.loads(job['generation_params'])
            except:
                generation_params = job['generation_params']
        
        if job.get('error_details'):
            try:
                error_details = json.loads(job['error_details'])
            except:
                error_details = job['error_details']
        
        # Calculer elapsed si processing
        elapsed_seconds = None
        if job['job_status'] == 'processing' and job.get('started_at'):
            elapsed_seconds = (datetime.now() - job['started_at']).total_seconds()
        
        return jsonify({
            'success': True,
            'job_uuid': job['job_uuid'],
            'status': job['job_status'],
            'user_id': job['user_id'],
            'user_firstname': job.get('user_firstname'),
            'quiz_id': job['quiz_id'],
            'result_id': job['result_id'],
            'step_id': job['step_id'],
            'generator_type': job['generator_type'],
            'created_at': job['created_at'].isoformat() if job.get('created_at') else None,
            'started_at': job['started_at'].isoformat() if job.get('started_at') else None,
            'completed_at': job['completed_at'].isoformat() if job.get('completed_at') else None,
            'duration_seconds': float(job['generation_time_seconds']) if job.get('generation_time_seconds') else None,
            'elapsed_seconds': elapsed_seconds,
            'error': job.get('error_message'),
            'error_details': error_details,
            'validation_status': job.get('validation_status'),
            'validation_attempts': job.get('validation_attempts'),
            'generation_params': generation_params
        })
        
    except Exception as e:
        logger.error(f"[ASYNC] Error getting status for {job_uuid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Annuler un job pending
# ============================================================

@async_analysis_bp.route('/cancel/<string:job_uuid>', methods=['POST'])
@admin_required
def cancel_job(job_uuid: str):
    """Annule un job en attente."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        success = AsyncAnalysisService.cancel_job(cursor, job_uuid)
        
        if success:
            current_app.mysql.connection.commit()
            return jsonify({'success': True, 'message': 'Job annulé'})
        else:
            return jsonify({'success': False, 'error': 'Job non trouvé ou déjà traité'}), 400
            
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Error cancelling {job_uuid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Relancer un job échoué
# ============================================================

@async_analysis_bp.route('/retry/<string:job_uuid>', methods=['POST'])
@admin_required
def retry_job(job_uuid: str):
    """Relance un job échoué en créant un nouveau job."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        new_job_uuid = AsyncAnalysisService.retry_failed_job(
            cursor, job_uuid, admin_id=current_user.id
        )
        
        current_app.mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'original_job': job_uuid,
            'new_job_uuid': new_job_uuid,
            'message': 'Nouveau job créé'
        })
        
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Error retrying {job_uuid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Liste des jobs (admin monitoring)
# ============================================================

@async_analysis_bp.route('/jobs', methods=['GET'])
@admin_required
def get_jobs():
    """Liste des jobs avec filtres et stats."""
    limit = request.args.get('limit', 50, type=int)
    status = request.args.get('status', '')
    user_id = request.args.get('user_id', type=int)
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        # Récupérer les jobs
        jobs = AsyncAnalysisService.get_recent_jobs(
            cursor, limit=limit, status=status or None, user_id=user_id
        )
        
        # Formatter les dates
        for job in jobs:
            for key in ['created_at', 'started_at', 'completed_at']:
                if job.get(key):
                    job[key] = job[key].isoformat()
        
        # Stats
        stats = AsyncAnalysisService.get_stats(cursor, hours=24)
        
        return jsonify({
            'success': True,
            'jobs': jobs,
            'stats': stats.get('by_status', {}),
            'total': len(jobs)
        })
        
    except Exception as e:
        logger.error(f"[ASYNC] Error getting jobs: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Vérifier jobs pending pour un user
# ============================================================

@async_analysis_bp.route('/pending/<int:user_id>/<string:quiz_id>', methods=['GET'])
@admin_required
def check_pending_jobs(user_id: int, quiz_id: str):
    """Vérifie s'il y a des jobs en attente pour un user/quiz."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        pending = AsyncAnalysisService.get_user_pending_jobs(cursor, user_id, quiz_id)
        
        return jsonify({
            'has_pending': len(pending) > 0,
            'pending_jobs': [
                {
                    'job_uuid': job['job_uuid'],
                    'status': job['job_status'],
                    'step_id': job['step_id'],
                    'created_at': job['created_at'].isoformat() if job['created_at'] else None
                }
                for job in pending
            ]
        })
        
    except Exception as e:
        logger.error(f"[ASYNC] Error checking pending: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Page de monitoring (admin)
# ============================================================

@async_analysis_bp.route('/monitor')
@admin_required
def monitor_page():
    """Page de monitoring des jobs async."""
    return render_template('admin/async_jobs_monitor.html')


# ============================================================
# ROUTE: Nettoyer les vieux jobs
# ============================================================

@async_analysis_bp.route('/cleanup', methods=['POST'])
@admin_required
def cleanup_jobs():
    """
    Nettoie les vieux jobs et les jobs bloqués.
    
    Body (optionnel):
        - days_to_keep: int (défaut: 30)
        - stuck_hours: int (défaut: 2)
    """
    data = request.json or {}
    days_to_keep = data.get('days_to_keep', 30)
    stuck_hours = data.get('stuck_hours', 2)
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        # Nettoyer les jobs bloqués
        stuck_cleaned = AsyncAnalysisService.cleanup_stuck_jobs(cursor, stuck_hours)
        
        # Nettoyer les vieux jobs
        old_cleaned = AsyncAnalysisService.cleanup_old_jobs(cursor, days_to_keep)
        
        current_app.mysql.connection.commit()
        
        return jsonify({
            'success': True,
            'stuck_jobs_cleaned': stuck_cleaned,
            'old_jobs_cleaned': old_cleaned
        })
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Error cleaning up: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Statistiques
# ============================================================

@async_analysis_bp.route('/stats', methods=['GET'])
@admin_required
def get_stats():
    """Récupère les statistiques des jobs."""
    hours = request.args.get('hours', 24, type=int)
    
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        from services.async_analysis_service import AsyncAnalysisService
        
        stats = AsyncAnalysisService.get_stats(cursor, hours=hours)
        
        return jsonify({
            'success': True,
            **stats
        })
        
    except Exception as e:
        logger.error(f"[ASYNC] Error getting stats: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()


# ============================================================
# ROUTE: Supprimer un job spécifique
# ============================================================

@async_analysis_bp.route('/delete/<string:job_uuid>', methods=['DELETE'])
@admin_required
def delete_job(job_uuid: str):
    """Supprime un job (seulement si completed/error/cancelled)."""
    cursor = current_app.mysql.connection.cursor(DictCursor)
    
    try:
        # Vérifier le statut
        cursor.execute("""
            SELECT job_status FROM async_analysis_jobs WHERE job_uuid = %s
        """, (job_uuid,))
        
        job = cursor.fetchone()
        
        if not job:
            return jsonify({'success': False, 'error': 'Job non trouvé'}), 404
        
        if job['job_status'] in ('pending', 'processing'):
            return jsonify({
                'success': False, 
                'error': 'Impossible de supprimer un job en cours. Annulez-le d\'abord.'
            }), 400
        
        # Supprimer
        cursor.execute("DELETE FROM async_analysis_jobs WHERE job_uuid = %s", (job_uuid,))
        current_app.mysql.connection.commit()
        
        return jsonify({'success': True, 'message': 'Job supprimé'})
        
    except Exception as e:
        current_app.mysql.connection.rollback()
        logger.error(f"[ASYNC] Error deleting {job_uuid}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        cursor.close()