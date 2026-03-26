import requests
import json
import logging
import os
from datetime import datetime
from flask import current_app

logger = logging.getLogger('slack_service')

class SlackService:
    """Service pour envoyer des notifications Slack"""
    
    def __init__(self):
        self.webhook_url_leads = None
        self.webhook_url_monitoring = None
        self.webhook_url_chat = None
        self.environment = None
        self.bot_name = None
        self.bot_emoji = None
        self._initialized = False

    def _ensure_initialized(self):
        """Initialise les paramètres depuis la config Flask si pas encore fait"""
        try:
            if current_app:
                # Si déjà chargé depuis current_app, ne pas recharger
                if self._initialized and self.webhook_url_leads and self.webhook_url_monitoring:
                    return
                
                # ✅ Lire depuis current_app.config (prioritaire)
                self.webhook_url_leads = current_app.config.get('SLACK_WEBHOOK_URL_LEADS')
                self.webhook_url_monitoring = current_app.config.get('SLACK_WEBHOOK_URL_MONITORING')
                self.webhook_url_chat = current_app.config.get('SLACK_WEBHOOK_URL_CHAT')  # ⬅️ NOUVEAU
                
                # Environnement
                self.environment = current_app.config.get('ENVIRONMENT', 'production')
                
                self.bot_name = current_app.config.get('SLACK_BOT_NAME', 'tilto Bot')
                self.bot_emoji = current_app.config.get('SLACK_BOT_EMOJI', ':rocket:')
                self._initialized = True
                
                # ✅ LOGS DÉTAILLÉS POUR DEBUG
                logger.info("=" * 80)
                logger.info("🔍 SLACK SERVICE - INITIALISATION")
                logger.info(f"  - Environment: {self.environment}")
                logger.info(f"  - SLACK_WEBHOOK_URL_LEADS configuré: {bool(self.webhook_url_leads)}")
                logger.info(f"  - SLACK_WEBHOOK_URL_MONITORING configuré: {bool(self.webhook_url_monitoring)}")
                logger.info(f"  - SLACK_WEBHOOK_URL_CHAT configuré: {bool(self.webhook_url_chat)}")  # ⬅️ NOUVEAU
                if self.webhook_url_leads:
                    logger.info(f"  - LEADS webhook preview: {self.webhook_url_leads[:50]}...")
                if self.webhook_url_monitoring:
                    logger.info(f"  - MONITORING webhook preview: {self.webhook_url_monitoring[:50]}...")
                if self.webhook_url_chat:  # ⬅️ NOUVEAU
                    logger.info(f"  - CHAT webhook preview: {self.webhook_url_chat[:50]}...")
                logger.info("=" * 80)
                
                if self.webhook_url_leads or self.webhook_url_monitoring or self.webhook_url_chat:  # ⬅️ MODIFIÉ
                    logger.info(f"✅ Service Slack initialisé avec succès - Env: {self.environment}")
                else:
                    logger.warning("⚠️ Aucun webhook Slack configuré")
                    
                return  # ✅ Sortir ici si chargé depuis Flask
                    
        except RuntimeError as e:
            # En dehors du contexte Flask
            logger.debug(f"RuntimeError lors de l'init Slack: {e} - tentative fallback")
            pass
        
        # ✅ Fallback SEULEMENT si current_app non disponible
        if not self._initialized:
            logger.warning("⚠️ Fallback sur os.getenv (développement ou hors contexte Flask)")
            self.webhook_url_leads = os.getenv('SLACK_WEBHOOK_URL_LEADS')
            self.webhook_url_monitoring = os.getenv('SLACK_WEBHOOK_URL_MONITORING')
            self.webhook_url_chat = os.getenv('SLACK_WEBHOOK_URL_CHAT')  # ⬅️ NOUVEAU
            self.environment = os.getenv('ENVIRONMENT', 'development')
            self.bot_name = os.getenv('SLACK_BOT_NAME', 'tilto Bot')
            self.bot_emoji = os.getenv('SLACK_BOT_EMOJI', ':rocket:')
            self._initialized = True
    
    def send_notification(self, message, channel=None, attachments=None):
        """
        Envoie une notification Slack générique
        
        Args:
            message (str): Message principal
            channel (str): Type de canal ('leads', 'monitoring', 'chat')  # ⬅️ MODIFIÉ
            attachments (list): Pièces jointes formatées Slack (optionnel)
        
        Returns:
            bool: True si envoyé avec succès, False sinon
        """
        self._ensure_initialized()

        # Choisir le bon webhook selon le type de canal
        if channel == 'chat':  # ⬅️ NOUVEAU
            webhook_url = self.webhook_url_chat
            # Fallback sur monitoring si chat n'existe pas
            if not webhook_url:
                webhook_url = self.webhook_url_monitoring
                logger.info("Fallback: utilisation du webhook monitoring pour chat")
            # Second fallback sur leads si monitoring n'existe pas non plus
            if not webhook_url:
                webhook_url = self.webhook_url_leads
                logger.info("Fallback: utilisation du webhook leads pour chat")
            channel_name = "support-clients"
            
        elif channel == 'monitoring':
            webhook_url = self.webhook_url_monitoring
            # Fallback sur leads si monitoring n'existe pas
            if not webhook_url:
                webhook_url = self.webhook_url_leads
                logger.info("Fallback: utilisation du webhook leads pour monitoring")
            channel_name = "monitoring"
            
        else:
            # Par défaut: leads
            webhook_url = self.webhook_url_leads
            # Fallback sur monitoring si leads n'existe pas
            if not webhook_url:
                webhook_url = self.webhook_url_monitoring
                logger.info("Fallback: utilisation du webhook monitoring pour leads")
            channel_name = "leads"
        
        if not webhook_url:
            logger.warning(f"Aucun webhook Slack configuré pour {channel_name}")
            return False
        
        try:
            payload = {
                "username": self.bot_name,
                "icon_emoji": self.bot_emoji,
                "text": message
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            response = requests.post(
                webhook_url, 
                data=json.dumps(payload),
                headers={'Content-Type': 'application/json'},
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info(f"Notification Slack envoyée vers {channel_name} (env: {self.environment})")
                return True
            else:
                logger.error(f"Erreur Slack: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de la notification Slack: {str(e)}")
            return False
    

    def notify_new_lead(self, lead_data):
        """
        Notification spécifique pour un nouveau lead
        
        Args:
            lead_data (dict): Données du lead
                - user_id: ID de l'utilisateur
                - email: Email du lead
                - firstname: Prénom
                - lastname: Nom
                - profile: Profil/intérêt
                - nb_accompagnement: Nombre d'accompagnements (optionnel)
                - source: Source du lead
                - phone: Numéro de téléphone (optionnel)
                - has_quiz_answers: Présence de réponses au quiz (optionnel)
                - has_audio_responses: Présence de réponses audio (optionnel)
                - has_analysis_token: Présence d'un token d'analyse (optionnel)
                - newsletter_subscription: Opt-in newsletter (optionnel)
                - partner_consent: Opt-in partenaires (optionnel)
        
        Returns:
            bool: True si envoyé avec succès
        """

        self._ensure_initialized()
        # Message principal
        message = f"🎯 *Nouveau lead enregistré !*"
        
        # Formatage des informations du lead
        user_id = lead_data.get('user_id', 'N/A')
        full_name = f"{lead_data.get('firstname', '')} {lead_data.get('lastname', '')}".strip()
        profile = lead_data.get('profile', 'Non spécifié')
        email = lead_data.get('email', 'Non spécifié')
        phone = lead_data.get('phone', '')
        source = lead_data.get('source', 'tilto_landing')
        nb_accompagnement = lead_data.get('nb_accompagnement')
        lead_interest = lead_data.get('lead_interest', profile)
        
        # Indicateurs quiz/audio
        has_quiz = lead_data.get('has_quiz_answers', False)
        has_audio = lead_data.get('has_audio_responses', False)
        has_token = lead_data.get('has_analysis_token', False)
        
        # Indicateurs opt-in
        newsletter_optin = lead_data.get('newsletter_subscription', False)
        partner_optin = lead_data.get('partner_consent', False)
        
        # Personnalisation selon le profil
        profile_emoji = {
            'particulier': '👤',
            'professionnel_orientation': '🎓',
            'rh_manager': '👔',
            'ceo_fondateur': '👑',
            'commercial': '💼',
            'autre': '🤔',
            'recommendations_metier': '🎯'
        }
        
        profile_display = f"{profile_emoji.get(profile, '📝')} {profile.replace('_', ' ').title()}"
        
        # Construction de l'attachment avec les détails
        attachment = {
            "color": "#A11857",  # Couleur tilto
            "fields": [
                {
                    "title": "🆔 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "👤 Contact",
                    "value": f"*{full_name}*\n✉️ {email}",
                    "short": True
                },
                {
                    "title": "🎯 Profil",
                    "value": profile_display,
                    "short": True
                },
                {
                    "title": "📊 Source",
                    "value": source.replace('_', ' ').title(),
                    "short": True
                },
                {
                    "title": "⏰ Heure",
                    "value": datetime.now().strftime("%d/%m/%Y à %H:%M"),
                    "short": True
                }
            ],
            "footer": "tilto Lead Management",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        # Ajouter nb_accompagnement si présent (pour les professionnels)
        if nb_accompagnement and profile == 'professionnel_orientation':
            attachment["fields"].append({
                "title": "📈 Accompagnements/mois",
                "value": nb_accompagnement,
                "short": True
            })
        
        # Ajouter des indicateurs pour les données collectées
        data_indicators = []
        if has_audio:
            data_indicators.append("🎙️ Réponses audio")
        if has_token:
            data_indicators.append("🔑 Token d'analyse créé")
        
        if data_indicators:
            attachment["fields"].append({
                "title": "📝 Données collectées",
                "value": " | ".join(data_indicators),
                "short": False
            })
        
        # Ajouter les indicateurs d'opt-in
        consent_status = []
        
        # Newsletter
        if newsletter_optin:
            consent_status.append("✅ Newsletter acceptée")
        else:
            consent_status.append("❌ Newsletter refusée")
        
        # Partenaires
        if partner_optin:
            consent_status.append("✅ Contact partenaires accepté")
        else:
            consent_status.append("❌ Contact partenaires refusé")
        
        # Toujours afficher les consentements
        attachment["fields"].append({
            "title": "📋 Consentements marketing",
            "value": "\n".join(consent_status),
            "short": False
        })
        
        return self.send_notification(message, channel='leads', attachments=[attachment])

    
    def notify_lead_converted(self, lead_data):
        """
        Notification lorsqu'un lead active son compte
        
        Args:
            lead_data (dict): Données du lead converti
        
        Returns:
            bool: True si envoyé avec succès
        """

        self._ensure_initialized()
        full_name = f"{lead_data.get('firstname', '')} {lead_data.get('lastname', '')}".strip()
        email = lead_data.get('email', '')
        
        message = f"🎉 *Lead converti en utilisateur !*"
        
        attachment = {
            "color": "good",  # Vert pour succès
            "fields": [
                {
                    "title": "✅ Nouvel utilisateur",
                    "value": f"*{full_name}*\n✉️ {email}",
                    "short": False
                },
                {
                    "title": "⏰ Conversion",
                    "value": datetime.now().strftime("%d/%m/%Y à %H:%M"),
                    "short": True
                }
            ],
            "footer": "tilto Lead Management - Conversion",
            "ts": int(datetime.now().timestamp())
        }
        
        return self.send_notification(message, channel='leads', attachments=[attachment])
    
    def notify_lead_status_update(self, lead_data, old_status, new_status, admin_name=None):
        """
        Notification lorsque le statut d'un lead est modifié
        
        Args:
            lead_data (dict): Données du lead
            old_status (str): Ancien statut
            new_status (str): Nouveau statut
            admin_name (str): Nom de l'admin qui a fait la modification
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        full_name = f"{lead_data.get('firstname', '')} {lead_data.get('lastname', '')}".strip()
        
        # Émojis selon le statut
        status_emoji = {
            'new': '🆕',
            'contacted': '📞',
            'qualified': '✅',
            'converted': '🎉',
            'lost': '❌'
        }
        
        # Couleurs selon le statut
        status_color = {
            'new': '#36a64f',        # Vert
            'contacted': '#ff9500',   # Orange
            'qualified': '#2196F3',   # Bleu
            'converted': '#4CAF50',   # Vert foncé
            'lost': '#f44336'         # Rouge
        }
        
        message = f"📝 *Statut lead modifié*"
        
        attachment = {
            "color": status_color.get(new_status, '#A11857'),
            "fields": [
                {
                    "title": "👤 Lead",
                    "value": full_name,
                    "short": True
                },
                {
                    "title": "📊 Changement de statut",
                    "value": f"{status_emoji.get(old_status, '📝')} {old_status} → {status_emoji.get(new_status, '📝')} {new_status}",
                    "short": True
                }
            ],
            "footer": f"Modifié par {admin_name}" if admin_name else "tilto Lead Management",
            "ts": int(datetime.now().timestamp())
        }
        
        return self.send_notification(message, channel='leads', attachments=[attachment])

    def notify_json_error(self, error_data):
        """
        Notification spécifique pour une erreur JSON lors du parsing
        
        Args:
            error_data (dict): Données de l'erreur JSON
                - user_id: ID de l'utilisateur
                - quiz_id: ID du quiz
                - request_id: ID de la requête
                - error_position: Position de l'erreur dans le JSON
                - error_message: Message d'erreur
                - context: Contexte autour de l'erreur
                - generator_type: Type de générateur (user/admin)
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        
        user_id = error_data.get('user_id', 'N/A')
        quiz_id = error_data.get('quiz_id', 'N/A')
        request_id = error_data.get('request_id', 'N/A')
        error_position = error_data.get('error_position', 0)
        error_message = error_data.get('error_message', 'No message')
        context = error_data.get('context', '')
        generator_type = error_data.get('generator_type', 'user')
        
        # Message principal
        message = f"❌ *ERREUR JSON - Career Path*"
        
        # Construction de l'attachment
        attachment = {
            "color": "danger",
            "fields": [
                {
                    "title": "👤 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "📋 Quiz ID",
                    "value": f"`{quiz_id}`",
                    "short": True
                },
                {
                    "title": "🔍 Request ID",
                    "value": f"`{request_id}`",
                    "short": True
                },
                {
                    "title": "🤖 Generator",
                    "value": f"`{generator_type}`",
                    "short": True
                },
                {
                    "title": "📍 Position erreur",
                    "value": f"Caractère `{error_position}`",
                    "short": True
                },
                {
                    "title": "💬 Message",
                    "value": f"`{error_message}`",
                    "short": True
                },
                {
                    "title": "📄 Contexte",
                    "value": f"```...{context[:300]}...```",
                    "short": False
                }
            ],
            "footer": "tilto Analysis Monitoring",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        return self.send_notification(
            message,
            channel='monitoring',
            attachments=[attachment]
        )

    def notify_api_error(self, error_data):
        """
        Notification spécifique pour une erreur API Anthropic
        
        Args:
            error_data (dict): Données de l'erreur API
                - user_id: ID de l'utilisateur
                - quiz_id: ID du quiz
                - step_id: Étape de l'analyse
                - result_id: ID du résultat
                - request_id: ID de la requête
                - error_type: Type d'erreur
                - error_message: Message d'erreur
                - traceback: Traceback complet
                - generator_type: Type de générateur (user/admin)
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        
        user_id = error_data.get('user_id', 'N/A')
        quiz_id = error_data.get('quiz_id', 'N/A')
        step_id = error_data.get('step_id', 'N/A')
        result_id = error_data.get('result_id', 'N/A')
        request_id = error_data.get('request_id', 'N/A')
        error_type = error_data.get('error_type', 'Unknown')
        error_message = error_data.get('error_message', 'No message')
        traceback_text = error_data.get('traceback', '')
        generator_type = error_data.get('generator_type', 'user')
        
        # Message principal
        message = f"🔥 *ERREUR API ANTHROPIC*"
        
        # Construction de l'attachment
        attachment = {
            "color": "danger",
            "fields": [
                {
                    "title": "⚠️ Type d'erreur",
                    "value": f"`{error_type}`",
                    "short": True
                },
                {
                    "title": "🔍 Request ID",
                    "value": f"`{request_id}`",
                    "short": True
                },
                {
                    "title": "👤 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "📋 Quiz / Step",
                    "value": f"`{quiz_id}` / `{step_id}`",
                    "short": True
                },
                {
                    "title": "🔑 Result ID",
                    "value": f"`{result_id[:20]}...`" if len(result_id) > 20 else f"`{result_id}`",
                    "short": True
                },
                {
                    "title": "🤖 Generator",
                    "value": f"`{generator_type}`",
                    "short": True
                },
                {
                    "title": "💬 Message d'erreur",
                    "value": f"```{error_message[:400]}```",
                    "short": False
                }
            ],
            "footer": "tilto API Monitoring",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        # Ajouter le traceback si disponible
        if traceback_text:
            attachment["fields"].append({
                "title": "🔍 Traceback",
                "value": f"```{traceback_text[:800]}```",
                "short": False
            })
        
        return self.send_notification(
            message,
            channel='monitoring',
            attachments=[attachment]
        )

    def notify_validation_error(self, error_data):
        """
        Notification spécifique pour une erreur de validation de structure
        
        Args:
            error_data (dict): Données de l'erreur de validation
                - user_id: ID de l'utilisateur
                - quiz_id: ID du quiz
                - step_id: Étape de l'analyse (career_path, vision_360, checkup_pro)
                - request_id: ID de la requête
                - error_type: Type d'erreur (missing_field, invalid_structure, etc.)
                - error_message: Message d'erreur détaillé
                - generator_type: Type de générateur (user/admin)
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        
        user_id = error_data.get('user_id', 'N/A')
        quiz_id = error_data.get('quiz_id', 'N/A')
        step_id = error_data.get('step_id', 'N/A')
        request_id = error_data.get('request_id', 'N/A')
        error_type = error_data.get('error_type', 'validation_error')
        error_message = error_data.get('error_message', 'No message')
        generator_type = error_data.get('generator_type', 'user')
        
        # Émojis selon le type d'étape
        step_emoji = {
            'career_path': '🛣️',
            'vision_360': '👁️',
            'checkup_pro': '📋'
        }
        
        # Message principal
        message = f"⚠️ *ERREUR DE VALIDATION - {step_id.replace('_', ' ').title()}*"
        
        # Construction de l'attachment
        attachment = {
            "color": "warning",
            "fields": [
                {
                    "title": f"{step_emoji.get(step_id, '📝')} Étape",
                    "value": f"`{step_id}`",
                    "short": True
                },
                {
                    "title": "🔍 Request ID",
                    "value": f"`{request_id}`",
                    "short": True
                },
                {
                    "title": "👤 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "📋 Quiz ID",
                    "value": f"`{quiz_id}`",
                    "short": True
                },
                {
                    "title": "🤖 Generator",
                    "value": f"`{generator_type}`",
                    "short": True
                },
                {
                    "title": "⚠️ Type d'erreur",
                    "value": f"`{error_type}`",
                    "short": True
                },
                {
                    "title": "💬 Message d'erreur",
                    "value": f"```{error_message[:500]}```",
                    "short": False
                },
                {
                    "title": "💡 Action suggérée",
                    "value": "• Vérifier le prompt système\n• Régénérer l'analyse\n• Contacter l'équipe technique si récurrent",
                    "short": False
                }
            ],
            "footer": "Tilto Analysis Monitoring - Validation",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        return self.send_notification(
            message,
            channel='monitoring',
            attachments=[attachment]
        )

    def notify_validation_failed_after_retries(self, validation_data):
        """
        Notification critique : validation échouée après tous les retries.
        
        QUAND ? Après max_retries tentatives, les recommandations sont toujours invalides.
        
        Args:
            validation_data (dict): Données de l'échec de validation
                - result_id: ID de l'analyse
                - step_id: Étape (career_path, career_path_v1, etc.)
                - user_id: ID utilisateur
                - quiz_id: ID quiz
                - request_id: ID requête
                - attempts: Nombre total de tentatives
                - issues: Liste des problèmes détectés (JSON)
                - generator_type: 'user' ou 'admin'
                - admin_url: URL directe vers l'admin pour correction
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        
        result_id = validation_data.get('result_id', 'N/A')
        step_id = validation_data.get('step_id', 'N/A')
        user_id = validation_data.get('user_id', 'N/A')
        quiz_id = validation_data.get('quiz_id', 'N/A')
        request_id = validation_data.get('request_id', 'N/A')
        attempts = validation_data.get('attempts', 0)
        issues = validation_data.get('issues', [])
        generator_type = validation_data.get('generator_type', 'user')
        admin_url = validation_data.get('admin_url', '')
        
        # Émojis selon le step
        step_emoji = {
            'career_path': '🛣️',
            'career_path_v1': '🛤️',
            'vision_360': '👁️',
            'checkup_pro': '📋'
        }
        
        # Extraire les 3 premiers problèmes les plus critiques
        critical_issues = [
            issue for issue in issues 
            if issue.get('severity') == 'critical'
        ][:3]
        
        # Formater les problèmes pour Slack
        issues_text = []
        for idx, issue in enumerate(critical_issues, 1):
            rec_idx = issue.get('recommendation_index', '?')
            problem = issue.get('problem', 'Unknown')
            
            # ✅ Gérer le cas où rec_idx est "global" ou autre string
            if isinstance(rec_idx, int):
                voie_label = f"Voie {rec_idx + 1}"
            else:
                voie_label = str(rec_idx).upper()  # "GLOBAL", "N/A", etc.
            
            issues_text.append(f"*{idx}. {voie_label}*: {problem}")

        issues_summary = "\n".join(issues_text) if issues_text else "Aucun détail disponible"
        
        # Message principal (alerte critique)
        message = f"🚨 *VALIDATION ÉCHOUÉE - ACTION REQUISE*"
        
        # Construction de l'attachment
        attachment = {
            "color": "danger",  # Rouge vif
            "pretext": f"⚠️ Analyse générée mais validation échouée après *{attempts} tentatives*",
            "fields": [
                {
                    "title": f"{step_emoji.get(step_id, '📝')} Étape",
                    "value": f"`{step_id}`",
                    "short": True
                },
                {
                    "title": "🔄 Tentatives",
                    "value": f"*{attempts}* retries épuisés",
                    "short": True
                },
                {
                    "title": "👤 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "📋 Quiz ID",
                    "value": f"`{quiz_id}`",
                    "short": True
                },
                {
                    "title": "🔑 Result ID",
                    "value": f"`{result_id[:20]}...`" if len(result_id) > 20 else f"`{result_id}`",
                    "short": True
                },
                {
                    "title": "🤖 Generator",
                    "value": f"`{generator_type}`",
                    "short": True
                },
                {
                    "title": "🔍 Request ID",
                    "value": f"`{request_id}`",
                    "short": False
                },
                {
                    "title": f"❌ Problèmes critiques ({len(critical_issues)}/{len(issues)})",
                    "value": issues_summary,
                    "short": False
                },
                {
                    "title": "⚠️ Impact utilisateur",
                    "value": "• Analyse livrée avec voies potentiellement incohérentes\n• Revue manuelle URGENTE recommandée\n• L'utilisateur a reçu l'analyse (fail-safe activé)",
                    "short": False
                },
                {
                    "title": "🔧 Action requise",
                    "value": "1. Ouvrir l'analyse dans l'admin\n2. Corriger manuellement les voies problématiques\n3. Activer la version admin corrigée\n4. Si récurrent : ajuster les prompts de validation",
                    "short": False
                }
            ],
            "footer": "Tilto Analysis Monitoring - VALIDATION CRITIQUE",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        # Ajouter un bouton d'action si URL admin fournie
        if admin_url:
            attachment["actions"] = [
                {
                    "type": "button",
                    "text": "🔧 Ouvrir dans Admin",
                    "url": admin_url,
                    "style": "danger"
                }
            ]
        
        return self.send_notification(
            message,
            channel='monitoring',
            attachments=[attachment]
        )

    def notify_validation_success_after_retry(self, validation_data):
        """
        Notification informative : validation réussie après 1+ retry.
        
        QUAND ? Les recommandations étaient invalides mais ont été corrigées avec succès.
        
        Args:
            validation_data (dict): Données du succès après retry
                - result_id: ID de l'analyse
                - step_id: Étape
                - user_id: ID utilisateur
                - quiz_id: ID quiz
                - request_id: ID requête
                - attempts: Nombre total de tentatives
                - initial_issues_count: Nombre de problèmes détectés initialement
                - fixed_issues_count: Nombre de problèmes corrigés
                - generator_type: 'user' ou 'admin'
        
        Returns:
            bool: True si envoyé avec succès
        """
        self._ensure_initialized()
        
        result_id = validation_data.get('result_id', 'N/A')
        step_id = validation_data.get('step_id', 'N/A')
        user_id = validation_data.get('user_id', 'N/A')
        quiz_id = validation_data.get('quiz_id', 'N/A')
        request_id = validation_data.get('request_id', 'N/A')
        attempts = validation_data.get('attempts', 0)
        initial_issues = validation_data.get('initial_issues_count', 0)
        fixed_issues = validation_data.get('fixed_issues_count', 0)
        generator_type = validation_data.get('generator_type', 'user')
        
        # Émojis selon le step
        step_emoji = {
            'career_path': '🛣️',
            'career_path_v1': '🛤️',
            'vision_360': '👁️',
            'checkup_pro': '📋'
        }
        
        # Message principal (succès)
        message = f"✅ *Validation réussie après correction*"
        
        # Construction de l'attachment
        attachment = {
            "color": "good",  # Vert
            "pretext": f"🔄 Auto-correction réussie après *{attempts}* tentative(s)",
            "fields": [
                {
                    "title": f"{step_emoji.get(step_id, '📝')} Étape",
                    "value": f"`{step_id}`",
                    "short": True
                },
                {
                    "title": "🔄 Retries",
                    "value": f"*{attempts}* tentative(s)",
                    "short": True
                },
                {
                    "title": "👤 User ID",
                    "value": f"`{user_id}`",
                    "short": True
                },
                {
                    "title": "📋 Quiz ID",
                    "value": f"`{quiz_id}`",
                    "short": True
                },
                {
                    "title": "🔑 Result ID",
                    "value": f"`{result_id[:20]}...`" if len(result_id) > 20 else f"`{result_id}`",
                    "short": True
                },
                {
                    "title": "🤖 Generator",
                    "value": f"`{generator_type}`",
                    "short": True
                },
                {
                    "title": "🔍 Request ID",
                    "value": f"`{request_id}`",
                    "short": False
                },
                {
                    "title": "📊 Résultat",
                    "value": f"• Problèmes détectés: *{initial_issues}*\n• Problèmes corrigés: *{fixed_issues}*\n• Statut final: ✅ Validé",
                    "short": False
                },
                {
                    "title": "💡 Info",
                    "value": "• Analyse corrigée automatiquement\n• Livrée à l'utilisateur avec voies validées\n• Aucune action manuelle requise",
                    "short": False
                }
            ],
            "footer": "Tilto Analysis Monitoring - Validation Auto-Corrected",
            "footer_icon": "https://tilto.fr/favicon.ico",
            "ts": int(datetime.now().timestamp())
        }
        
        return self.send_notification(
            message,
            channel='monitoring',
            attachments=[attachment]
        )
# Instance globale du service
slack_service = SlackService()
