"""
Service de génération d'analyses asynchrones via Google Cloud Tasks.

Ce service permet de déléguer la génération d'analyses LLM à un worker
en arrière-plan, évitant ainsi les timeouts sur les requêtes HTTP longues.

Architecture:
1. L'admin clique sur "Générer Async" dans l'interface
2. Un job est créé dans async_analysis_jobs avec status='pending'
3. En DEBUG: thread en arrière-plan | En PROD: tâche Cloud Tasks créée
4. Le worker traite la tâche et met à jour le statut du job
5. L'interface peut poller le statut ou recevoir une notification
"""

import os
import json
import uuid
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from flask import current_app
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2
from google.protobuf import duration_pb2

logger = logging.getLogger(__name__)


class AsyncAnalysisService:
    """Service pour gérer les analyses asynchrones via Cloud Tasks."""
    
    # Statuts possibles
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_ERROR = 'error'
    STATUS_CANCELLED = 'cancelled'
    
    # Configuration Cloud Tasks par défaut
    DEFAULT_QUEUE = 'analysis-generation'
    DEFAULT_TIMEOUT_SECONDS = 600  # 1 minutes
    
    @classmethod
    def get_tasks_client(cls):
        """Retourne un client Cloud Tasks."""
        return tasks_v2.CloudTasksClient()
    
    @classmethod
    def get_queue_path(cls, queue_name: str = None) -> str:
        """Construit le chemin complet de la queue Cloud Tasks."""
        project = current_app.config.get('GCP_PROJECT_ID')
        location = current_app.config.get('GCP_LOCATION', 'europe-west1')
        queue = queue_name or current_app.config.get('CLOUD_TASKS_QUEUE', cls.DEFAULT_QUEUE)
        
        client = cls.get_tasks_client()
        return client.queue_path(project, location, queue)
    
    @classmethod
    def create_async_job(
        cls,
        cursor,
        user_id: int,
        quiz_id: str,
        step_id: str,
        generation_params: Dict[str, Any],
        admin_id: int = None,
        generator_type: str = 'admin',
        order_id: int = None,
        delay_seconds: int = 0
    ) -> str:
        """
        Crée un job d'analyse asynchrone.
        
        En mode DEBUG: lance un thread en arrière-plan (NON-BLOQUANT)
        En mode PROD: crée une tâche Cloud Tasks
        
        Args:
            cursor: Curseur MySQL
            user_id: ID de l'utilisateur pour qui générer l'analyse
            quiz_id: ID du quiz
            step_id: Étape d'analyse (career_path_v2, etc.)
            generation_params: Paramètres de génération (prompts, critères, etc.)
            admin_id: ID de l'admin qui lance le job (optionnel)
            generator_type: 'user' ou 'admin'
            order_id: ID de commande associée (optionnel)
            delay_seconds: Délai avant exécution (optionnel)
            
        Returns:
            str: UUID du job créé
        """
        job_uuid = str(uuid.uuid4())
        result_id = str(uuid.uuid4())
        
        logger.info(f"[ASYNC] Creating job {job_uuid} for user {user_id}, quiz {quiz_id}")
        
        try:
            # 1. Insérer le job dans la BDD
            cursor.execute("""
                INSERT INTO async_analysis_jobs (
                    job_uuid, user_id, quiz_id, result_id, step_id,
                    order_id, generator_type, created_by_admin_id,
                    job_status, generation_params
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                job_uuid,
                user_id,
                quiz_id,
                result_id,
                step_id,
                order_id,
                generator_type,
                admin_id,
                cls.STATUS_PENDING,
                json.dumps(generation_params, ensure_ascii=False)
            ))
            
            job_id = cursor.lastrowid
            logger.info(f"[ASYNC] Job {job_uuid} inserted with ID {job_id}")
            
            # ============================================================
            # MODE DEBUG : Thread en arrière-plan (NON-BLOQUANT)
            # ============================================================
            if current_app.config.get('DEBUG', False):
                logger.info(f"[ASYNC] DEBUG MODE - Launching background thread (non-blocking)")
                
                # IMPORTANT: Commit AVANT de lancer le thread
                # pour que le job soit visible dans la BDD
                cursor.connection.commit()
                
                def process_in_background(app, job_id):
                    """Fonction exécutée dans le thread séparé."""
                    # Délai pour laisser le temps à la requête HTTP de se terminer
                    # et au redirect de se faire
                    time.sleep(2)
                    
                    # Recréer un contexte Flask dans le thread
                    with app.app_context():
                        try:
                            logger.info(f"[THREAD] 🚀 Démarrage traitement job {job_id}")
                            result = cls.process_job(job_id)
                            logger.info(f"[THREAD] ✅ Job {job_id} terminé: success={result.get('success')}")
                        except Exception as e:
                            logger.error(f"[THREAD] ❌ Erreur job {job_id}: {e}", exc_info=True)
                
                # Récupérer l'objet app Flask (pas le proxy)
                app = current_app._get_current_object()
                
                # Lancer le thread
                thread = threading.Thread(
                    target=process_in_background,
                    args=(app, job_uuid),
                    daemon=True  # Se termine si l'app Flask s'arrête
                )
                thread.start()
                
                logger.info(f"[ASYNC] DEBUG MODE - Thread started for job {job_uuid}")
                
                return job_uuid
            
            # ============================================================
            # MODE PRODUCTION : Créer tâche Cloud Tasks
            # ============================================================
            task_name = cls._create_cloud_task(
                job_uuid=job_uuid,
                delay_seconds=delay_seconds
            )
            
            # Mettre à jour le job avec le nom de la tâche
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET cloud_task_name = %s
                WHERE job_uuid = %s
            """, (task_name, job_uuid))
            
            logger.info(f"[ASYNC] Cloud Task created: {task_name}")
            
            return job_uuid
            
        except Exception as e:
            logger.error(f"[ASYNC] Error creating job: {e}", exc_info=True)
            raise
    
    @classmethod
    def _create_cloud_task(cls, job_uuid: str, delay_seconds: int = 0) -> str:
        """
        Crée une tâche Cloud Tasks pour traiter le job.
        
        Args:
            job_uuid: UUID du job à traiter
            delay_seconds: Délai avant exécution
            
        Returns:
            str: Nom complet de la tâche créée
        """
        client = cls.get_tasks_client()
        queue_path = cls.get_queue_path()
        
        # URL du handler - IMPORTANT: doit pointer vers la prod
        base_url = current_app.config.get('BASE_URL', 'https://tilto.co')
        handler_url = f"{base_url}/analysis/async/process"
        
        logger.info(f"[ASYNC] Creating Cloud Task to call: {handler_url}")
        
        # Corps de la requête
        payload = json.dumps({
            'job_uuid': job_uuid
        })
        
        # Configuration de la tâche
        task = {
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': handler_url,
                'headers': {
                    'Content-Type': 'application/json',
                    'X-CloudTasks-Internal': 'true'
                },
                'body': payload.encode()
            }
        }
        
        # Ajouter l'authentification OIDC si configuré
        service_account_email = current_app.config.get('CLOUD_TASKS_SERVICE_ACCOUNT')
        if service_account_email:
            task['http_request']['oidc_token'] = {
                'service_account_email': service_account_email,
                'audience': base_url
            }
        
        # Ajouter un délai si spécifié
        if delay_seconds > 0:
            schedule_time = timestamp_pb2.Timestamp()
            schedule_time.FromDatetime(
                datetime.utcnow() + timedelta(seconds=delay_seconds)
            )
            task['schedule_time'] = schedule_time
        
        # Timeout pour les tâches longues
        task['dispatch_deadline'] = duration_pb2.Duration(seconds=cls.DEFAULT_TIMEOUT_SECONDS)
        
        # Créer la tâche
        response = client.create_task(
            parent=queue_path,
            task=task
        )
        
        return response.name
    
    @classmethod
    def process_job(cls, job_uuid: str) -> Dict[str, Any]:
        """
        Traite un job d'analyse asynchrone.
        Appelé par le handler Cloud Tasks ou directement en mode DEBUG.
        
        Args:
            job_uuid: UUID du job à traiter
            
        Returns:
            dict: Résultat du traitement
        """
        logger.info(f"[ASYNC] Processing job {job_uuid}")
        
        # Créer notre propre curseur DictCursor
        from MySQLdb.cursors import DictCursor
        mysql = current_app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            # 1. Récupérer les infos du job
            cursor.execute("""
                SELECT * FROM async_analysis_jobs
                WHERE job_uuid = %s
            """, (job_uuid,))
            
            job = cursor.fetchone()
            
            if not job:
                logger.error(f"[ASYNC] Job {job_uuid} not found")
                return {'success': False, 'error': 'Job not found'}
            
            if job['job_status'] != cls.STATUS_PENDING:
                logger.warning(f"[ASYNC] Job {job_uuid} already processed (status: {job['job_status']})")
                return {'success': False, 'error': f"Job already {job['job_status']}"}
            
            # 2. Marquer comme en cours
            cls._update_job_status(cursor, job_uuid, cls.STATUS_PROCESSING)
            cursor.connection.commit()
            
            start_time = datetime.now()
            
            # ============================================================
            # 🎙️ ÉTAPE 2.5 : TRANSCRIRE LES AUDIOS AVANT GÉNÉRATION
            # ============================================================
            transcription_success = cls._transcribe_audio_responses(cursor, job)
            
            if not transcription_success:
                logger.warning(f"[ASYNC] Some audio transcriptions failed for job {job_uuid}, continuing anyway")
            
            # 3. Récupérer les paramètres de génération
            generation_params = json.loads(job['generation_params']) if job['generation_params'] else {}
            
            # 4. Importer et utiliser le service d'analyse
            from services.quiz_analysis_service import QuizAnalysisService
            
            analysis_service = QuizAnalysisService(
                cursor=cursor,
                user_id=job['user_id'],
                quiz_id=job['quiz_id']
            )
            
            # 5. Créer ou récupérer le token
            token_id = f"admin_async_{job['result_id'][:8]}"

            cursor.execute("""
                SELECT token_code FROM tokens 
                WHERE token_code = %s
            """, (token_id,))

            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO tokens (token_code, user_id, quiz_id, token_type, is_used, used_at)
                    VALUES (%s, %s, %s, 'free', TRUE, NOW())
                """, (token_id, job['user_id'], job['quiz_id']))
            
            # 6. Générer l'analyse
            result_json, prompt_id, timings = analysis_service._generate_analysis(
                result_id=job['result_id'],
                step_id=job['step_id'],
                request_id=f"async_{job_uuid}",
                prompt_instruction=generation_params.get('instructions', ''),
                prompt_knowledge=generation_params.get('knowledge', ''),
                custom_validation_criteria=generation_params.get('validation_criteria')
            )
            
            # 7. Stocker le résultat
            # ✅ Publier automatiquement si validation réussie (même après retries)
            auto_publish = (timings.get('validation_status', 'success') == 'success')

            analysis_service._store_analysis_result(
                result_id=job['result_id'],
                step_id=job['step_id'],
                result_json=result_json,
                token_id=token_id,
                prompt_id=prompt_id,
                is_active=auto_publish,
                generator_type=job['generator_type'],
                timings=timings
            )

            logger.info(f"[ASYNC] Analysis stored: is_active={auto_publish} "
                        f"(validation: {timings.get('validation_status')}, "
                        f"attempts: {timings.get('validation_attempts', 1)})")
            
            # 8. Mettre à jour le statut du job
            duration = (datetime.now() - start_time).total_seconds()
            
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET job_status = %s,
                    completed_at = NOW(),
                    generation_time_seconds = %s,
                    validation_attempts = %s,
                    validation_status = %s
                WHERE job_uuid = %s
            """, (
                cls.STATUS_COMPLETED,
                duration,
                timings.get('validation_attempts', 1),
                timings.get('validation_status', 'success'),
                job_uuid
            ))
            
            cursor.connection.commit()
            
            logger.info(f"[ASYNC] Job {job_uuid} completed successfully in {duration:.2f}s")
            
            # ============================================================
            # 📧 ENVOYER EMAIL "TON ANALYSE EST PRÊTE" SI PUBLIÉE
            # ============================================================
            if auto_publish:
                cls._send_analysis_ready_email(cursor, job)
            
            # 9. Envoyer notification Slack
            cls._send_completion_notification(cursor, job, auto_publish)
            
            return {
                'success': True,
                'job_uuid': job_uuid,
                'result_id': job['result_id'],
                'duration_seconds': duration,
                'auto_published': auto_publish
            }
            
        except Exception as e:
            logger.error(f"[ASYNC] Job {job_uuid} failed: {e}", exc_info=True)
            
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET job_status = %s,
                    completed_at = NOW(),
                    error_message = %s,
                    error_details = %s
                WHERE job_uuid = %s
            """, (
                cls.STATUS_ERROR,
                str(e)[:1000],
                json.dumps({
                    'type': type(e).__name__,
                    'message': str(e)
                }),
                job_uuid
            ))
            
            cursor.connection.commit()
            
            return {
                'success': False,
                'job_uuid': job_uuid,
                'error': str(e)
            }

        finally:
            cursor.close()


    @classmethod
    def _transcribe_audio_responses(cls, cursor, job: Dict) -> bool:
        """
        Transcrit toutes les réponses audio pour un job avant génération.
        
        Args:
            cursor: Curseur MySQL
            job: Dictionnaire contenant les infos du job
            
        Returns:
            bool: True si toutes les transcriptions ont réussi, False sinon
        """
        logger.info(f"[ASYNC] 🎙️ Checking for audio responses to transcribe for user {job['user_id']}")
        
        all_success = True
        
        try:
            # 1. Récupérer le quiz_session_id
            cursor.execute("""
                SELECT quiz_session_id 
                FROM quiz_user 
                WHERE user_id = %s AND quiz_id = %s
                ORDER BY created_at DESC LIMIT 1
            """, (job['user_id'], job['quiz_id']))
            
            session_row = cursor.fetchone()
            if not session_row:
                logger.warning(f"[ASYNC] No quiz session found for user {job['user_id']}")
                return True  # Pas d'erreur, juste pas de session
            
            quiz_session_id = session_row['quiz_session_id']
            
            # 2. Récupérer les réponses audio (celles qui contiennent une URL GCS)
            cursor.execute("""
                SELECT 
                    au.question_id,
                    au.answer_text,
                    at.transcription_status
                FROM answer_user au
                LEFT JOIN audio_transcriptions at ON (
                    au.quiz_session_id = at.quiz_session_id 
                    AND au.question_id = at.question_id
                )
                WHERE au.quiz_session_id = %s
                AND (
                    au.answer_text LIKE 'gs://%%'
                    OR au.answer_text LIKE '%%tilto_quiz_audios%%'
                )
            """, (quiz_session_id,))
            
            audio_responses = cursor.fetchall()
            
            if not audio_responses:
                logger.info(f"[ASYNC] 🎙️ No audio responses found for user {job['user_id']}")
                return True
            
            logger.info(f"[ASYNC] 🎙️ Found {len(audio_responses)} audio responses to process")
            
            # 3. Transcrire chaque audio
            from services.audio_service import AudioService
            
            for audio in audio_responses:
                question_id = audio['question_id']
                audio_url = audio['answer_text']
                existing_status = audio.get('transcription_status')
                
                # Skip si déjà transcrit
                if existing_status == 'completed':
                    logger.info(f"[ASYNC] 🎙️ Q{question_id} already transcribed, skipping")
                    continue
                
                logger.info(f"[ASYNC] 🎙️ Transcribing Q{question_id}: {audio_url[:60]}...")
                
                try:
                    result = AudioService.transcribe_quiz_audio_from_gcs(audio_url)
                    
                    if result['success']:
                        transcription = result['transcript']
                        
                        # Sauvegarder dans audio_transcriptions
                        cursor.execute("""
                            INSERT INTO audio_transcriptions 
                            (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                            transcription, confidence_score, transcription_status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'completed')
                            ON DUPLICATE KEY UPDATE 
                                transcription = VALUES(transcription),
                                transcription_status = 'completed',
                                confidence_score = VALUES(confidence_score),
                                updated_at = NOW()
                        """, (quiz_session_id, question_id, job['user_id'], job['quiz_id'], 
                            audio_url, transcription, 0.95))
                        
                        # CORRECTION : Mettre à jour answer_user avec la transcription
                        cursor.execute("""
                            UPDATE answer_user 
                            SET answer_text = %s,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE quiz_session_id = %s 
                            AND question_id = %s
                        """, (transcription, quiz_session_id, question_id))
                        
                        cursor.connection.commit()
                        
                        logger.info(f"[ASYNC] 🎙️ ✅ Q{question_id} transcribed: {len(transcription)} chars")
                    else:
                        logger.error(f"[ASYNC] 🎙️ ❌ Q{question_id} transcription failed: {result.get('error')}")
                        
                        # Enregistrer l'échec
                        cursor.execute("""
                            INSERT INTO audio_transcriptions 
                            (quiz_session_id, question_id, user_id, quiz_id, audio_file_path, 
                            transcription, transcription_status, error_message)
                            VALUES (%s, %s, %s, %s, %s, '', 'error', %s)
                            ON DUPLICATE KEY UPDATE 
                                transcription_status = 'error',
                                error_message = VALUES(error_message),
                                updated_at = NOW()
                        """, (quiz_session_id, question_id, job['user_id'], job['quiz_id'], 
                            audio_url, result.get('error', 'Unknown error')[:500]))
                        
                        cursor.connection.commit()
                        all_success = False
                        
                except Exception as trans_error:
                    logger.error(f"[ASYNC] 🎙️ ❌ Q{question_id} transcription exception: {trans_error}")
                    all_success = False
            
            return all_success
            
        except Exception as e:
            logger.error(f"[ASYNC] 🎙️ ❌ Error in _transcribe_audio_responses: {e}", exc_info=True)
            return False


    @classmethod
    def _send_analysis_ready_email(cls, cursor, job: Dict):
        """
        Envoie un email "Ton analyse est prête" à l'utilisateur.
        Vérifie qu'aucun email n'a déjà été envoyé pour cette analyse.
        
        Args:
            cursor: Curseur MySQL
            job: Dictionnaire contenant les infos du job
        """
        try:
            from services.email_service import send_analysis_ready_email
            from flask import url_for
            
            # Récupérer les infos utilisateur
            cursor.execute("""
                SELECT firstname, email
                FROM users
                WHERE user_id = %s
            """, (job['user_id'],))
            
            user_info = cursor.fetchone()
            
            if not user_info or not user_info['email']:
                logger.warning(f"[ASYNC] ⚠️ User {job['user_id']} sans email, skip notification")
                return
            
            # Vérifier si email déjà envoyé (éviter doublons)
            cursor.execute("""
                SELECT 1 FROM analysis_notification_emails 
                WHERE result_id = %s AND step_id = %s AND user_id = %s
                LIMIT 1
            """, (job['result_id'], job['step_id'], job['user_id']))
            
            already_sent = cursor.fetchone()
            
            if already_sent:
                logger.info(f"[ASYNC] 📧 Email déjà envoyé pour cette analyse, skip")
                return
            
            # Générer l'URL du dashboard
            analysis_url = url_for('dashboard.index', _external=True)
            
            # Envoyer l'email
            email_sent = send_analysis_ready_email(
                user_email=user_info['email'],
                firstname=user_info['firstname'] or 'Utilisateur',
                analysis_url=analysis_url
            )
            
            if email_sent:
                # Enregistrer l'envoi
                cursor.execute("""
                    INSERT INTO analysis_notification_emails 
                    (result_id, step_id, user_id, quiz_id, sent_to_email, sent_by_admin_id, sent_at)
                    VALUES (%s, %s, %s, %s, %s, NULL, NOW())
                """, (job['result_id'], job['step_id'], job['user_id'], job['quiz_id'], user_info['email']))
                
                cursor.connection.commit()
                
                logger.info(f"[ASYNC] 📧 Email 'analyse prête' envoyé à {user_info['email']}")
            else:
                logger.error(f"[ASYNC] ❌ Échec envoi email à {user_info['email']}")
                
        except Exception as email_error:
            # Ne pas faire échouer le job si l'email échoue
            logger.error(f"[ASYNC] ❌ Erreur envoi email notification: {email_error}", exc_info=True)


    @classmethod
    def _send_completion_notification(cls, cursor, job: Dict, auto_published: bool = False):
        """
        Envoie une notification Slack quand un job est terminé.
        
        Args:
            cursor: Curseur MySQL
            job: Dictionnaire contenant les infos du job
            auto_published: Si l'analyse a été publiée automatiquement
        """
        try:
            from services import slack_service, SLACK_AVAILABLE
            
            if not SLACK_AVAILABLE or not slack_service:
                return
            
            cursor.execute("""
                SELECT firstname, lastname, email 
                FROM users WHERE user_id = %s
            """, (job['user_id'],))
            
            user = cursor.fetchone()
            user_name = f"{user['firstname']} {user['lastname']}" if user else f"User #{job['user_id']}"
            
            # Message différent selon publication auto ou non
            if auto_published:
                status_msg = "✅ *Analyse générée et publiée automatiquement*"
                footer = "_L'utilisateur a reçu un email de notification._"
            else:
                status_msg = "⚠️ *Analyse générée en brouillon (validation échouée)*"
                footer = "_Review admin nécessaire avant publication._"
            
            slack_service.send_notification(
                f"{status_msg}\n"
                f"• Job: `{job['job_uuid'][:8]}...`\n"
                f"• User: {user_name} ({user['email'] if user else 'N/A'})\n"
                f"• Quiz: `{job['quiz_id']}`\n"
                f"• Step: `{job['step_id']}`\n"
                f"{footer}",
                channel='monitoring'
            )
            
        except Exception as e:
            logger.warning(f"[ASYNC] Failed to send Slack notification: {e}")

    @classmethod
    def _update_job_status(cls, cursor, job_uuid: str, status: str):
        """Met à jour le statut d'un job."""
        if status == cls.STATUS_PROCESSING:
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET job_status = %s, started_at = NOW()
                WHERE job_uuid = %s
            """, (status, job_uuid))
        else:
            cursor.execute("""
                UPDATE async_analysis_jobs 
                SET job_status = %s
                WHERE job_uuid = %s
            """, (status, job_uuid))
    

    @classmethod
    def get_job_status(cls, cursor, job_uuid: str) -> Optional[Dict]:
        """Récupère le statut d'un job."""
        cursor.execute("""
            SELECT 
                job_uuid, user_id, quiz_id, result_id, step_id,
                job_status, created_at, started_at, completed_at,
                error_message, generation_time_seconds, validation_status
            FROM async_analysis_jobs
            WHERE job_uuid = %s
        """, (job_uuid,))
        
        job = cursor.fetchone()
        
        if not job:
            return None
        
        return {
            'job_uuid': job['job_uuid'],
            'user_id': job['user_id'],
            'quiz_id': job['quiz_id'],
            'result_id': job['result_id'],
            'step_id': job['step_id'],
            'status': job['job_status'],
            'created_at': job['created_at'].isoformat() if job['created_at'] else None,
            'started_at': job['started_at'].isoformat() if job['started_at'] else None,
            'completed_at': job['completed_at'].isoformat() if job['completed_at'] else None,
            'error_message': job['error_message'],
            'duration_seconds': float(job['generation_time_seconds']) if job['generation_time_seconds'] else None,
            'validation_status': job['validation_status']
        }
    
    @classmethod
    def get_user_pending_jobs(cls, cursor, user_id: int, quiz_id: str = None) -> list:
        """Récupère les jobs en attente pour un utilisateur."""
        query = """
            SELECT job_uuid, quiz_id, step_id, job_status, created_at
            FROM async_analysis_jobs
            WHERE user_id = %s
            AND job_status IN ('pending', 'processing')
        """
        params = [user_id]
        
        if quiz_id:
            query += " AND quiz_id = %s"
            params.append(quiz_id)
        
        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    
    @classmethod
    def cancel_job(cls, cursor, job_uuid: str) -> bool:
        """Annule un job en attente."""
        cursor.execute("""
            SELECT job_status, cloud_task_name
            FROM async_analysis_jobs
            WHERE job_uuid = %s
        """, (job_uuid,))
        
        job = cursor.fetchone()
        
        if not job or job['job_status'] != cls.STATUS_PENDING:
            return False
        
        # Annuler la tâche Cloud Tasks si possible
        if job['cloud_task_name']:
            try:
                client = cls.get_tasks_client()
                client.delete_task(name=job['cloud_task_name'])
                logger.info(f"[ASYNC] Cloud Task deleted: {job['cloud_task_name']}")
            except Exception as e:
                logger.warning(f"[ASYNC] Could not delete Cloud Task: {e}")
        
        cursor.execute("""
            UPDATE async_analysis_jobs 
            SET job_status = %s, completed_at = NOW()
            WHERE job_uuid = %s
        """, (cls.STATUS_CANCELLED, job_uuid))
        
        logger.info(f"[ASYNC] Job {job_uuid} cancelled")
        return True
    
    @classmethod
    def get_recent_jobs(cls, cursor, limit: int = 50, status: str = None, user_id: int = None) -> list:
        """Récupère les derniers jobs (pour le monitoring admin)."""
        query = """
            SELECT 
                j.job_uuid, j.user_id, j.quiz_id, j.step_id,
                j.job_status, j.created_at, j.started_at, j.completed_at,
                j.generation_time_seconds, j.error_message,
                j.validation_attempts, j.validation_status,
                u.firstname as user_firstname, u.lastname as user_lastname,
                admin.firstname as admin_firstname
            FROM async_analysis_jobs j
            LEFT JOIN users u ON j.user_id = u.user_id
            LEFT JOIN users admin ON j.created_by_admin_id = admin.user_id
            WHERE 1=1
        """
        params = []
        
        if status:
            query += " AND j.job_status = %s"
            params.append(status)
        
        if user_id:
            query += " AND j.user_id = %s"
            params.append(user_id)
        
        query += " ORDER BY j.created_at DESC LIMIT %s"
        params.append(limit)
        
        cursor.execute(query, tuple(params))
        return cursor.fetchall()
    
    # ============================================================
    # MÉTHODES DE NETTOYAGE
    # ============================================================
    
    @classmethod
    def cleanup_old_jobs(cls, cursor, days_to_keep: int = 30) -> Dict[str, int]:
        """
        Supprime les vieux jobs terminés (completed/error/cancelled).
        
        Args:
            cursor: Curseur MySQL
            days_to_keep: Nombre de jours à conserver
            
        Returns:
            dict: Statistiques de suppression
        """
        # Compter avant suppression
        cursor.execute("""
            SELECT job_status, COUNT(*) as count
            FROM async_analysis_jobs
            WHERE job_status IN ('completed', 'error', 'cancelled')
            AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
            GROUP BY job_status
        """, (days_to_keep,))
        
        stats = {row['job_status']: row['count'] for row in cursor.fetchall()}
        
        # Supprimer
        cursor.execute("""
            DELETE FROM async_analysis_jobs
            WHERE job_status IN ('completed', 'error', 'cancelled')
            AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """, (days_to_keep,))
        
        deleted = cursor.rowcount
        
        logger.info(f"[ASYNC] Cleaned up {deleted} old jobs (older than {days_to_keep} days)")
        
        return {
            'deleted_total': deleted,
            'by_status': stats
        }
    
    @classmethod
    def cleanup_stuck_jobs(cls, cursor, stuck_hours: int = 2) -> int:
        """
        Marque comme erreur les jobs bloqués en 'processing' depuis trop longtemps.
        
        Args:
            cursor: Curseur MySQL
            stuck_hours: Heures après lesquelles un job est considéré bloqué
            
        Returns:
            int: Nombre de jobs marqués en erreur
        """
        cursor.execute("""
            UPDATE async_analysis_jobs
            SET job_status = 'error',
                error_message = 'Job stuck - automatically marked as error after %s hours',
                completed_at = NOW()
            WHERE job_status = 'processing'
            AND started_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """, (stuck_hours, stuck_hours))
        
        updated = cursor.rowcount
        
        if updated > 0:
            logger.warning(f"[ASYNC] Marked {updated} stuck jobs as error")
        
        return updated
    
    @classmethod
    def retry_failed_job(cls, cursor, job_uuid: str, admin_id: int = None) -> str:
        """
        Crée un nouveau job à partir d'un job échoué.
        
        Args:
            cursor: Curseur MySQL
            job_uuid: UUID du job échoué
            admin_id: ID de l'admin qui relance
            
        Returns:
            str: UUID du nouveau job
        """
        # Récupérer le job original
        cursor.execute("""
            SELECT user_id, quiz_id, step_id, generation_params, generator_type, order_id
            FROM async_analysis_jobs
            WHERE job_uuid = %s AND job_status IN ('error', 'cancelled')
        """, (job_uuid,))
        
        job = cursor.fetchone()
        
        if not job:
            raise ValueError(f"Job {job_uuid} not found or not in error/cancelled status")
        
        # Parser les params
        generation_params = json.loads(job['generation_params']) if job['generation_params'] else {}
        
        # Créer un nouveau job
        new_job_uuid = cls.create_async_job(
            cursor=cursor,
            user_id=job['user_id'],
            quiz_id=job['quiz_id'],
            step_id=job['step_id'],
            generation_params=generation_params,
            admin_id=admin_id,
            generator_type=job['generator_type'],
            order_id=job['order_id']
        )
        
        logger.info(f"[ASYNC] Retried job {job_uuid} -> new job {new_job_uuid}")
        
        return new_job_uuid
    
    @classmethod
    def get_stats(cls, cursor, hours: int = 24) -> Dict[str, Any]:
        """
        Récupère les statistiques des jobs.
        
        Args:
            cursor: Curseur MySQL
            hours: Période en heures
            
        Returns:
            dict: Statistiques
        """
        # Stats par statut
        cursor.execute("""
            SELECT job_status, COUNT(*) as count
            FROM async_analysis_jobs
            WHERE created_at > DATE_SUB(NOW(), INTERVAL %s HOUR)
            GROUP BY job_status
        """, (hours,))
        
        by_status = {row['job_status']: row['count'] for row in cursor.fetchall()}
        
        # Temps moyen de génération
        cursor.execute("""
            SELECT AVG(generation_time_seconds) as avg_duration,
                   MIN(generation_time_seconds) as min_duration,
                   MAX(generation_time_seconds) as max_duration
            FROM async_analysis_jobs
            WHERE job_status = 'completed'
            AND created_at > DATE_SUB(NOW(), INTERVAL %s HOUR)
        """, (hours,))
        
        duration_stats = cursor.fetchone()
        
        # Jobs en cours
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM async_analysis_jobs
            WHERE job_status IN ('pending', 'processing')
        """)
        
        active = cursor.fetchone()['count']
        
        return {
            'period_hours': hours,
            'by_status': by_status,
            'active_jobs': active,
            'avg_duration_seconds': float(duration_stats['avg_duration']) if duration_stats['avg_duration'] else None,
            'min_duration_seconds': float(duration_stats['min_duration']) if duration_stats['min_duration'] else None,
            'max_duration_seconds': float(duration_stats['max_duration']) if duration_stats['max_duration'] else None
        }