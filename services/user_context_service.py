"""
UserContextService — vue 360° persistée d'un utilisateur Tilto.

Complément du AgentContext (qui est par-job) : ici on agrège tout ce qui
survit ENTRE les sessions/agents. La donnée est en DB depuis longtemps,
mais elle vivait jusqu'ici dans une route admin Flask qui retournait
un template HTML — donc inconsommable par les agents.

Ce service rend la même agrégation disponible comme objet Python
structuré, consommable par :
- la route admin (admin/user_details) qui hydrate son template
- n'importe quel agent (career, support, meta-analyse, etc.) qui veut
  raisonner sur l'historique d'un user

Architecture
────────────
- Une instance par requête (cursor injecté)
- Une méthode publique principale : `get_full_context()` qui agrège tout
- Méthodes ciblées (`get_quizzes()`, `get_orders()`, etc.) pour fetch
  partiel quand on n'a pas besoin du paquet complet

Conventions
───────────
- Pas de logique métier ici — uniquement requêtes + structuration
- Pas de side effects (read-only)
- Si user inexistant : retourne {} (pas d'exception)
- Limite par défaut sur les listes potentiellement longues (50, 20)
  — surchargeable via paramètres
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class UserContextService:
    """Vue 360° persistée d'un user. Lit la DB, ne mute rien."""

    # Limites par défaut sur les fetches potentiellement longs
    DEFAULT_LIMIT_ANSWERS = 50
    DEFAULT_LIMIT_TRANSCRIPTIONS = 20
    DEFAULT_LIMIT_CONSENT = 20
    DEFAULT_LIMIT_ACTIONS = 50
    DEFAULT_LIMIT_BOOKING_ACTIONS = 20
    DEFAULT_LIMIT_CHAT = 20
    DEFAULT_LIMIT_CAPSULES_HISTORY = 50

    def __init__(self, cursor, user_id: int):
        self.cursor = cursor
        self.user_id = user_id

    # ─────────────────────────────────────────────────────────────
    # Méthode principale : full context
    # ─────────────────────────────────────────────────────────────

    def get_full_context(self) -> Dict[str, Any]:
        """
        Retourne la vue 360° complète du user.
        Si user inexistant : retourne un dict vide.
        """
        user = self.get_user()
        if not user:
            return {}

        quiz_sessions = self.get_quiz_sessions()
        quiz_answers = self.get_quiz_answers()
        analysis_results = self.get_analysis_results()
        analysis_tokens = self.get_analysis_tokens()
        orders = self.get_orders()
        order_products = self.get_order_products()
        product_statuses = self.get_product_statuses()
        bookings = self.get_bookings()
        product_tokens = self.get_product_tokens()
        user_capsules = self.get_user_capsules()
        capsules_history = self.get_capsules_history()
        capsules_feedback = self.get_capsules_feedback()
        audio_transcriptions = self.get_audio_transcriptions()
        consent_history = self.get_consent_history()
        user_actions = self.get_user_actions()
        booking_actions = self.get_booking_actions()
        chat_messages = self.get_chat_messages(user.get('email'))

        stats = self._compute_stats(
            quiz_sessions=quiz_sessions, quiz_answers=quiz_answers,
            analysis_results=analysis_results, analysis_tokens=analysis_tokens,
            orders=orders, bookings=bookings, user_capsules=user_capsules,
            capsules_history=capsules_history, capsules_feedback=capsules_feedback,
            audio_transcriptions=audio_transcriptions,
            consent_history=consent_history, user_actions=user_actions,
            booking_actions=booking_actions, chat_messages=chat_messages,
        )

        return {
            'user': dict(user),
            'quiz_sessions': quiz_sessions,
            'quiz_answers': quiz_answers,
            'analysis_results': analysis_results,
            'analysis_tokens': analysis_tokens,
            'orders': orders,
            'order_products': order_products,
            'product_statuses': product_statuses,
            'bookings': bookings,
            'product_tokens': product_tokens,
            'user_capsules': user_capsules,
            'capsules_history': capsules_history,
            'capsules_feedback': capsules_feedback,
            'audio_transcriptions': audio_transcriptions,
            'consent_history': consent_history,
            'user_actions': user_actions,
            'booking_actions': booking_actions,
            'chat_messages': chat_messages,
            'stats': stats,
        }

    # ─────────────────────────────────────────────────────────────
    # Méthodes ciblées — fetch partiel (quand on n'a pas besoin du tout)
    # ─────────────────────────────────────────────────────────────

    def get_user(self) -> Optional[Dict[str, Any]]:
        """Profil user. Retourne None si introuvable."""
        self.cursor.execute("""
            SELECT
                user_id, username, firstname, lastname, email, phone_number,
                country_code, user_status, address,
                newsletter_subscription, partner_consent, privacy_policy_accepted,
                lead_source, lead_status, lead_interest, lead_notes,
                nb_accompagnement, onboarding_stage,
                is_google_user, profile_picture,
                two_factor_secret, access_token, invite_token, invite_expiry,
                last_login, last_contacted, created_at, updated_at
            FROM users
            WHERE user_id = %s
        """, (self.user_id,))
        return self.cursor.fetchone()

    def get_quiz_sessions(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                qu.quiz_session_id, qu.quiz_id, qc.quiz_type,
                qu.quiz_status, qu.start_time, qu.end_time,
                qu.session_duration, qu.questions_answered_count,
                qu.created_at, qu.updated_at
            FROM quiz_user qu
            LEFT JOIN quiz_catalog qc ON qu.quiz_id = qc.quiz_id
            WHERE qu.user_id = %s
            ORDER BY qu.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_quiz_answers(self, limit: int = DEFAULT_LIMIT_ANSWERS) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                au.quiz_session_id, au.question_id, qcat.question,
                au.answer_value, au.answer_text, au.created_at
            FROM answer_user au
            LEFT JOIN questions_catalog qcat ON au.question_id = qcat.question_id
            WHERE au.quiz_session_id IN (
                SELECT quiz_session_id FROM quiz_user WHERE user_id = %s
            )
            ORDER BY au.created_at DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_analysis_results(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                ru.result_id, ru.result_step_id, ru.quiz_id,
                ru.generator_type, ru.is_active,
                ru.generation_time_seconds, ru.api_call_time_seconds,
                ru.created_at, LENGTH(ru.result_json) as result_size
            FROM result_user ru
            WHERE ru.user_id = %s
            ORDER BY ru.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_analysis_tokens(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                token, quiz_id, result_id, access_type,
                expires_at, max_views, view_count, last_viewed_at,
                is_revoked, created_at, updated_at
            FROM analysis_access_tokens
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_orders(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                o.order_id, o.order_number, o.order_amount, o.discount_amount,
                o.currency, o.status, o.payment_method, o.notes,
                o.discount_code, o.created_at, o.updated_at
            FROM orders o
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_order_products(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                op.order_id, op.product_id, pc.product_name,
                op.quantity, op.product_amount, op.discount_amount, o.created_at
            FROM order_product op
            JOIN orders o ON op.order_id = o.order_id
            JOIN product_catalog pc ON op.product_id = pc.product_id
            WHERE o.user_id = %s
            ORDER BY o.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_product_statuses(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                ps.id, ps.product_id, pc.product_name, ps.status,
                ps.booking_id, ps.livrable_date, ps.created_at, ps.updated_at
            FROM product_status ps
            JOIN product_catalog pc ON ps.product_id = pc.product_id
            WHERE ps.user_id = %s
            ORDER BY ps.updated_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_bookings(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                b.id, b.booking_id, b.product_id, pc.product_name,
                b.booking_date, b.end_date, b.duration_minutes,
                b.attendee_email, b.attendee_name, b.status,
                b.zoom_link, b.created_at, b.updated_at
            FROM bookings b
            JOIN product_catalog pc ON b.product_id = pc.product_id
            WHERE b.user_id = %s
            ORDER BY b.booking_date DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_product_tokens(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                t.token_code, t.product_id, t.quiz_id, t.token_type,
                t.is_used, t.used_at, t.expiration_date, t.created_at
            FROM tokens t
            WHERE t.user_id = %s
            ORDER BY t.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_user_capsules(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                uc.capsule_id, c.title as capsule_title,
                uc.sequence_number, uc.is_listened,
                uc.listen_count, uc.last_listened_at, uc.created_at
            FROM user_capsules uc
            JOIN capsules c ON uc.capsule_id = c.capsule_id
            WHERE uc.user_id = %s
            ORDER BY uc.sequence_number
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_capsules_history(self, limit: int = DEFAULT_LIMIT_CAPSULES_HISTORY) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                ch.capsule_id, c.title as capsule_title,
                ch.listen_date, ch.duration_seconds, ch.completion_percentage
            FROM capsules_history ch
            JOIN capsules c ON ch.capsule_id = c.capsule_id
            WHERE ch.user_id = %s
            ORDER BY ch.listen_date DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_capsules_feedback(self) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                cf.capsule_id, c.title as capsule_title,
                cf.rating, cf.feedback_text, cf.feedback_type, cf.created_at
            FROM capsules_feedback cf
            JOIN capsules c ON cf.capsule_id = c.capsule_id
            WHERE cf.user_id = %s
            ORDER BY cf.created_at DESC
        """, (self.user_id,))
        return self.cursor.fetchall()

    def get_audio_transcriptions(self, limit: int = DEFAULT_LIMIT_TRANSCRIPTIONS) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                at.question_id, qc.question, at.transcription,
                at.confidence_score, at.transcription_status, at.created_at
            FROM audio_transcriptions at
            LEFT JOIN questions_catalog qc ON at.question_id = qc.question_id
            WHERE at.user_id = %s
            ORDER BY at.created_at DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_consent_history(self, limit: int = DEFAULT_LIMIT_CONSENT) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                consent_type, consent_status, changed_at, ip_address, source
            FROM user_consent_history
            WHERE user_id = %s
            ORDER BY changed_at DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_user_actions(self, limit: int = DEFAULT_LIMIT_ACTIONS) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT action, details, ip_address, created_at
            FROM user_actions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_booking_actions(self, limit: int = DEFAULT_LIMIT_BOOKING_ACTIONS) -> List[Dict[str, Any]]:
        self.cursor.execute("""
            SELECT
                product_id, booking_id, action_type, reason,
                old_datetime, new_datetime, created_at
            FROM user_booking_actions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (self.user_id, limit))
        return self.cursor.fetchall()

    def get_chat_messages(self, email: Optional[str] = None,
                          limit: int = DEFAULT_LIMIT_CHAT) -> List[Dict[str, Any]]:
        """Messages chat indexés par user_id OU email (le widget chat homepage logge avant signup)."""
        if email:
            self.cursor.execute("""
                SELECT email, message, context, status, replied_at, created_at
                FROM chat_messages
                WHERE user_id = %s OR email = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (self.user_id, email, limit))
        else:
            self.cursor.execute("""
                SELECT email, message, context, status, replied_at, created_at
                FROM chat_messages
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (self.user_id, limit))
        return self.cursor.fetchall()

    # ─────────────────────────────────────────────────────────────
    # Vues synthétiques pour agents — résumés digestes
    # ─────────────────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """
        Vue ultra-condensée pour qu'un agent comprenne *qui est ce user*
        en 5 lignes — sans avoir à digérer le full context.
        """
        user = self.get_user()
        if not user:
            return {}

        quiz_sessions = self.get_quiz_sessions()
        analysis_results = self.get_analysis_results()
        orders = self.get_orders()
        bookings = self.get_bookings()

        return {
            'user_id': user['user_id'],
            'firstname': user.get('firstname'),
            'email': user.get('email'),
            'lead_source': user.get('lead_source'),
            'created_at': user.get('created_at'),
            'last_login': user.get('last_login'),
            'onboarding_stage': user.get('onboarding_stage'),
            'nb_quiz_completed': len([q for q in quiz_sessions if q['quiz_status'] == 'completed']),
            'nb_analyses': len(analysis_results),
            'last_analysis_at': analysis_results[0]['created_at'] if analysis_results else None,
            'nb_paid_orders': len([o for o in orders if o['status'] == 'paid']),
            'total_spent_eur': sum(o['order_amount'] for o in orders if o['status'] == 'paid') / 100,
            'has_active_booking': any(b['status'] in ('confirmed', 'rescheduled') for b in bookings),
        }

    # ─────────────────────────────────────────────────────────────
    # Stats internes (utilisé par le template admin)
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_stats(*,
                       quiz_sessions, quiz_answers, analysis_results,
                       analysis_tokens, orders, bookings,
                       user_capsules, capsules_history, capsules_feedback,
                       audio_transcriptions, consent_history, user_actions,
                       booking_actions, chat_messages) -> Dict[str, Any]:
        return {
            'total_quiz_sessions': len(quiz_sessions),
            'completed_quizzes': len([q for q in quiz_sessions if q['quiz_status'] == 'completed']),
            'total_answers': len(quiz_answers),
            'total_analysis_results': len(analysis_results),
            'active_tokens': len([t for t in analysis_tokens if not t['is_revoked']]),
            'total_orders': len(orders),
            'paid_orders': len([o for o in orders if o['status'] == 'paid']),
            'total_spent': sum(o['order_amount'] for o in orders if o['status'] == 'paid') / 100,
            'total_bookings': len(bookings),
            'active_bookings': len([b for b in bookings if b['status'] in ['confirmed', 'rescheduled']]),
            'capsules_listened': len([c for c in user_capsules if c['is_listened']]),
            'total_capsule_listens': len(capsules_history),
            'total_capsule_feedback': len(capsules_feedback),
            'total_transcriptions': len(audio_transcriptions),
            'total_consent_changes': len(consent_history),
            'total_actions': len(user_actions),
            'total_booking_actions': len(booking_actions),
            'total_chat_messages': len(chat_messages),
        }
