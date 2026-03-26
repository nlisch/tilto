"""
Cron : Envoie les emails "analyse prête" le lendemain entre 13h-16h.
Exécuter via Cloud Scheduler : */15 13-15 * * *
"""

import random
import time
import logging

logger = logging.getLogger(__name__)


def send_pending_analysis_notifications(app):
    from MySQLdb.cursors import DictCursor
    from services.email_service import send_analysis_ready_email
    from flask import url_for
    
    with app.app_context():
        mysql = app.mysql
        cursor = mysql.connection.cursor(DictCursor)
        
        try:
            cursor.execute("""
                SELECT 
                    ru.result_id, ru.result_step_id, ru.user_id, ru.quiz_id,
                    u.email, u.firstname
                FROM result_user ru
                JOIN users u ON ru.user_id = u.user_id
                LEFT JOIN analysis_notification_emails ane ON (
                    ane.result_id = ru.result_id 
                    AND ane.step_id = ru.result_step_id 
                    AND ane.user_id = ru.user_id
                )
                WHERE ru.is_active = TRUE
                AND ane.id IS NULL
                
                AND DATE(u.created_at) < CURDATE()
                AND u.created_at >= '2025-02-12'
                AND u.email IS NOT NULL
                ORDER BY u.created_at ASC
                LIMIT 20
            """)
            
            pending = cursor.fetchall()
            
            if not pending:
                logger.info("[CRON] Aucune notification en attente")
                return 0
            
            logger.info(f"[CRON] {len(pending)} notifications à envoyer")
            sent = 0
            
            for notif in pending:
                try:
                    time.sleep(random.randint(0, 60))
                    
                    analysis_url = url_for('dashboard.index', _external=True)
                    
                    ok = send_analysis_ready_email(
                        user_email=notif['email'],
                        firstname=notif['firstname'] or 'Utilisateur',
                        analysis_url=analysis_url
                    )
                    
                    if ok:
                        cursor.execute("""
                            INSERT INTO analysis_notification_emails 
                            (result_id, step_id, user_id, quiz_id, sent_to_email, sent_by_admin_id, sent_at)
                            VALUES (%s, %s, %s, %s, %s, NULL, NOW())
                        """, (notif['result_id'], notif['result_step_id'], 
                              notif['user_id'], notif['quiz_id'], notif['email']))
                        mysql.connection.commit()
                        sent += 1
                        logger.info(f"[CRON] ✅ Email envoyé à {notif['email']}")
                    
                except Exception as e:
                    logger.error(f"[CRON] ❌ Erreur user {notif['user_id']}: {e}")
                    continue
            
            # ✅ Notification Slack de résumé
            try:
                from services import slack_service, SLACK_AVAILABLE
                if SLACK_AVAILABLE and slack_service and sent > 0:
                    # Vérifier si on a déjà envoyé une notif Slack aujourd'hui
                    cursor2 = mysql.connection.cursor(DictCursor)
                    cursor2.execute("""
                        SELECT COUNT(*) as cnt FROM cron_slack_log
                        WHERE cron_name = 'analysis_notifications'
                        AND DATE(sent_at) = CURDATE()
                    """)
                    already_sent = cursor2.fetchone()['cnt'] > 0
                    cursor2.close()

                    if not already_sent:
                        slack_service.send_notification(
                            f"📧 *Cron notifications analyse*\n"
                            f"• {sent} email(s) envoyé(s) aujourd'hui",
                            channel='monitoring'
                        )
                        cursor3 = mysql.connection.cursor()
                        cursor3.execute("""
                            INSERT INTO cron_slack_log (cron_name, sent_at)
                            VALUES ('analysis_notifications', NOW())
                        """)
                        mysql.connection.commit()
                        cursor3.close()
            except Exception as slack_error:
                logger.warning(f"[CRON] Slack notification failed: {slack_error}")
            
            logger.info(f"[CRON] Terminé : {sent}/{len(pending)}")
            return sent
            
        except Exception as e:
            logger.error(f"[CRON] Erreur globale : {e}", exc_info=True)
            return 0
        finally:
            cursor.close()


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    send_pending_analysis_notifications(app)