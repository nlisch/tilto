# models/audio_capsule.py
import logging
from flask import current_app
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class AudioCapsuleModel:
    """Modèle pour gérer les capsules audio en base de données"""
    
    @staticmethod
    def create_capsule(cursor, title, personalized_reflection, file_name, duration=None):
        """
        Crée une nouvelle capsule audio
        
        Args:
            cursor: Curseur MySQL
            title (str): Titre de la capsule
            personalized_reflection (str):Réflexion personnalisée
            file_name (str): Nom du fichier dans le bucket
            duration (str, optional): Durée de la capsule au format MM:SS
            
        Returns:
            int: ID de la capsule créée ou None en cas d'erreur
        """
        try:
            query = """
                INSERT INTO capsules 
                (title, personalized_reflection, file_name, duration) 
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (title, personalized_reflection, file_name, duration))
            capsule_id = cursor.lastrowid
            logger.info(f"Capsule audio créée avec ID: {capsule_id}")
            return capsule_id
        except Exception as e:
            logger.error(f"Erreur lors de la création de la capsule audio: {e}")
            return None
    
    @staticmethod
    def get_all_capsules(cursor):
        """
        Récupère toutes les capsules audio
        
        Args:
            cursor: Curseur MySQL
            
        Returns:
            list: Liste des capsules audio
        """
        try:
            query = """
                SELECT capsule_id, title, personalized_reflection, file_name, duration, 
                       capsule_order, is_active, created_at, updated_at
                FROM capsules
                ORDER BY capsule_order ASC, created_at DESC
            """
            cursor.execute(query)
            capsules = cursor.fetchall()
            
            # Convertir en liste de dictionnaires
            result = []
            for capsule in capsules:
                result.append({
                    'capsule_id': capsule[0],
                    'title': capsule[1],
                    'personalized_reflection': capsule[2],
                    'file_name': capsule[3],
                    'duration': capsule[4],
                    'capsule_order': capsule[5],
                    'is_active': bool(capsule[6]),
                    'created_at': capsule[7],
                    'updated_at': capsule[8]
                })
            
            return result
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des capsules audio: {e}")
            return []
    
    @staticmethod
    def get_capsule_by_id(cursor, capsule_id):
        """
        Récupère une capsule audio par son ID
        
        Args:
            cursor: Curseur MySQL
            capsule_id (int): ID de la capsule
            
        Returns:
            dict: Données de la capsule ou None si non trouvée
        """
        try:
            query = """
                SELECT capsule_id, title, personalized_reflection, file_name, duration, 
                       capsule_order, is_active, created_at, updated_at
                FROM capsules
                WHERE capsule_id = %s
            """
            cursor.execute(query, (capsule_id,))
            capsule = cursor.fetchone()
            
            if not capsule:
                return None
                
            return {
                'capsule_id': capsule[0],
                'title': capsule[1],
                'personalized_reflection': capsule[2],
                'file_name': capsule[3],
                'duration': capsule[4],
                'capsule_order': capsule[5],
                'is_active': bool(capsule[6]),
                'created_at': capsule[7],
                'updated_at': capsule[8]
            }
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la capsule audio {capsule_id}: {e}")
            return None
    
    @staticmethod
    def update_capsule(cursor, capsule_id, title=None, personalized_reflection=None, 
                      file_name=None, duration=None, capsule_order=None, is_active=None):
        """
        Met à jour une capsule audio
        
        Args:
            cursor: Curseur MySQL
            capsule_id (int): ID de la capsule à mettre à jour
            title (str, optional): Nouveau titre
            personalized_reflection (str, optional): Nouvelle personalized_reflection
            file_name (str, optional): Nouveau nom de fichier
            duration (str, optional): Nouvelle durée
            capsule_order (int, optional): Nouvel ordre
            is_active (bool, optional): Nouveau statut
            
        Returns:
            bool: True si mise à jour réussie, False sinon
        """
        try:
            # Construire dynamiquement la requête en fonction des paramètres fournis
            update_parts = []
            params = []
            
            if title is not None:
                update_parts.append("title = %s")
                params.append(title)
                
            if personalized_reflection is not None:
                update_parts.append("personalized_reflection = %s")
                params.append(personalized_reflection)
                
            if file_name is not None:
                update_parts.append("file_name = %s")
                params.append(file_name)
                
            if duration is not None:
                update_parts.append("duration = %s")
                params.append(duration)
                
            if capsule_order is not None:
                update_parts.append("capsule_order = %s")
                params.append(capsule_order)
                
            if is_active is not None:
                update_parts.append("is_active = %s")
                params.append(is_active)
                
            if not update_parts:
                logger.warning("Aucun paramètre à mettre à jour pour la capsule audio")
                return False
                
            query = f"""
                UPDATE capsules
                SET {', '.join(update_parts)}
                WHERE capsule_id = %s
            """
            params.append(capsule_id)
            
            cursor.execute(query, params)
            affected_rows = cursor.rowcount
            
            logger.info(f"Capsule audio {capsule_id} mise à jour, {affected_rows} ligne(s) affectée(s)")
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour de la capsule audio {capsule_id}: {e}")
            return False
    
    @staticmethod
    def delete_capsule(cursor, capsule_id):
        """
        Supprime une capsule audio
        
        Args:
            cursor: Curseur MySQL
            capsule_id (int): ID de la capsule à supprimer
            
        Returns:
            bool: True si suppression réussie, False sinon
        """
        try:
            query = "DELETE FROM capsules WHERE capsule_id = %s"
            cursor.execute(query, (capsule_id,))
            affected_rows = cursor.rowcount
            
            logger.info(f"Capsule audio {capsule_id} supprimée, {affected_rows} ligne(s) affectée(s)")
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Erreur lors de la suppression de la capsule audio {capsule_id}: {e}")
            return False

class UserCapsuleModel:
    """Modèle pour gérer les associations utilisateur-capsule"""
    
    @staticmethod
    def assign_capsule_to_user(cursor, user_id, capsule_id, access_token=None, sequence_number=1, expiry_days=None):
        try:
            # Générer un token si non fourni
            if not access_token:
                access_token = f"{uuid.uuid4()}_{int(datetime.now().timestamp())}"
            query = """
                INSERT INTO user_capsules
                (user_id, capsule_id, access_token, sequence_number)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(query, (user_id, capsule_id, access_token, sequence_number))
            
            logger.info(f"Capsule {capsule_id} assignée à l'utilisateur {user_id} avec token: {access_token}, séquence: {sequence_number}")
            return access_token
        except Exception as e:
            logger.error(f"Erreur lors de l'assignation de la capsule {capsule_id} à l'utilisateur {user_id}: {e}")
            return None
    
    @staticmethod
    def get_user_capsules(cursor, user_id):
        """
        Récupère toutes les capsules assignées à un utilisateur
        
        Args:
            cursor: Curseur MySQL
            user_id (int): ID de l'utilisateur
            
        Returns:
            list: Liste des capsules assignées à l'utilisateur
        """
        try:
            query = """
                SELECT uac.id, uac.user_id, uac.capsule_id, uac.access_token, 
                       uac.expiry_date, uac.is_listened, uac.listen_count, 
                       uac.last_listened_at, ac.title, ac.personalized_reflection, 
                       ac.file_name, ac.duration, ac.is_active
                FROM user_capsules uac
                JOIN capsules ac ON uac.capsule_id = ac.capsule_id
                WHERE uac.user_id = %s AND ac.is_active = TRUE
                ORDER BY ac.capsule_order ASC, ac.created_at DESC
            """
            cursor.execute(query, (user_id,))
            capsules = cursor.fetchall()
            
            # Convertir en liste de dictionnaires
            result = []
            for c in capsules:
                # Vérifier si le token a expiré
                is_expired = False
                if c[4] is not None and c[4] < datetime.now():
                    is_expired = True
                    
                result.append({
                    'id': c[0],
                    'user_id': c[1],
                    'capsule_id': c[2],
                    'access_token': c[3],
                    'expiry_date': c[4],
                    'is_listened': bool(c[5]),
                    'listen_count': c[6],
                    'last_listened_at': c[7],
                    'title': c[8],
                    'personalized_reflection': c[9],
                    'file_name': c[10],
                    'duration': c[11],
                    'is_active': bool(c[12]),
                    'is_expired': is_expired
                })
            
            return result
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des capsules de l'utilisateur {user_id}: {e}")
            return []
    
    @staticmethod
    def get_capsule_by_token(cursor, access_token):
        try:
            query = """
                SELECT uac.id, uac.user_id, uac.capsule_id, uac.access_token, 
                    uac.is_listened, uac.listen_count, 
                    uac.last_listened_at, ac.title, ac.personalized_reflection, 
                    ac.file_name, ac.duration, ac.is_active, u.username,
                    uac.sequence_number
                FROM user_capsules uac
                JOIN capsules ac ON uac.capsule_id = ac.capsule_id
                JOIN users u ON uac.user_id = u.user_id
                WHERE uac.access_token = %s AND ac.is_active = TRUE
            """
            cursor.execute(query, (access_token,))
            capsule = cursor.fetchone()
            
            if not capsule:
                return None
                
            # Supprimer la vérification d'expiration
            # if capsule[4] is not None and capsule[4] < datetime.now():
            #     logger.warning(f"Token d'accès expiré: {access_token}")
            #     return None
                
            return {
                'id': capsule[0],
                'user_id': capsule[1],
                'capsule_id': capsule[2],
                'access_token': capsule[3],
                'is_listened': bool(capsule[4]),
                'listen_count': capsule[5],
                'last_listened_at': capsule[6],
                'title': capsule[7],
                'personalized_reflection': capsule[8],
                'file_name': capsule[9],
                'duration': capsule[10],
                'is_active': bool(capsule[11]),
                'username': capsule[12],
                'sequence_number': capsule[13]
            }
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la capsule par token {access_token}: {e}")
            return None
    
    @staticmethod
    def update_listen_status(cursor, access_token, increment=True):
        """
        Met à jour le statut d'écoute d'une capsule
        
        Args:
            cursor: Curseur MySQL
            access_token (str): Token d'accès
            increment (bool): Si True, incrémente le compteur d'écoutes
            
        Returns:
            bool: True si mise à jour réussie, False sinon
        """
        try:
            if increment:
                query = """
                    UPDATE user_capsules
                    SET is_listened = TRUE,
                        listen_count = listen_count + 1,
                        last_listened_at = NOW()
                    WHERE access_token = %s
                """
            else:
                query = """
                    UPDATE user_capsules
                    SET is_listened = TRUE,
                        last_listened_at = NOW()
                    WHERE access_token = %s
                """
                
            cursor.execute(query, (access_token,))
            affected_rows = cursor.rowcount
            
            logger.info(f"Statut d'écoute mis à jour pour le token {access_token}, {affected_rows} ligne(s) affectée(s)")
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour du statut d'écoute pour le token {access_token}: {e}")
            return False
    
    @staticmethod
    def record_listen_event(cursor, user_id, capsule_id, duration_seconds=0, 
                        completion_percentage=0, user_agent=None, ip_address=None):
        """
        Enregistre un événement d'écoute seulement si le pourcentage d'écoute est suffisant
        """
        try:
            # On n'enregistre que si l'utilisateur a écouté au moins 90% de la capsule
            if completion_percentage >= 90:
                query = """
                    INSERT INTO capsules_history
                    (user_id, capsule_id, duration_seconds, completion_percentage, user_agent, ip_address)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """
                cursor.execute(query, (
                    user_id, capsule_id, duration_seconds, 
                    completion_percentage, user_agent, ip_address
                ))
                event_id = cursor.lastrowid
                
                logger.info(f"Événement d'écoute enregistré: ID={event_id}, User={user_id}, Capsule={capsule_id}")
                return event_id
            else:
                logger.info(f"Écoute non enregistrée: progression insuffisante ({completion_percentage}%)")
                return None
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement de l'événement d'écoute: {e}")
            return None
    
    @staticmethod
    def save_feedback(cursor, event_id, rating, feedback_text=None, audio_feedback_file=None):
        """
        Enregistre le feedback d'un utilisateur dans la table capsules_feedback
        
        Args:
            cursor: Curseur MySQL
            event_id (int): ID de l'événement d'écoute
            rating (int): Note de satisfaction (1-5)
            feedback_text (str, optional): Commentaire textuel
            audio_feedback_file (str, optional): Nom du fichier audio de feedback
            
        Returns:
            int: ID du feedback créé ou None en cas d'erreur
        """
        try:
            # Récupérer l'utilisateur et la capsule associés à cet événement
            cursor.execute("""
                SELECT user_id, capsule_id 
                FROM capsules_history
                WHERE id = %s
            """, (event_id,))
            
            result = cursor.fetchone()
            if not result:
                logger.error(f"Événement d'écoute {event_id} introuvable")
                return None
                
            user_id, capsule_id = result
            
            # Déterminer le type de feedback
            feedback_type = 'text'
            if audio_feedback_file and feedback_text:
                feedback_type = 'both'
            elif audio_feedback_file:
                feedback_type = 'audio'
            
            # Insérer le feedback dans la table capsules_feedback
            query = """
                INSERT INTO capsules_feedback 
                (listen_history_id, user_id, capsule_id, rating, feedback_text, 
                audio_feedback_file, feedback_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                event_id, user_id, capsule_id, rating, feedback_text,
                audio_feedback_file, feedback_type
            ))
            
            feedback_id = cursor.lastrowid
            logger.info(f"Feedback enregistré pour l'événement {event_id} - ID: {feedback_id}")
            return feedback_id
        except Exception as e:
            logger.error(f"Erreur lors de l'enregistrement du feedback pour l'événement {event_id}: {e}")
            return None

