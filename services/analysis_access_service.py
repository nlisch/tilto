# services/analysis_access_service.py
import logging
from datetime import datetime, timedelta
import uuid

logger = logging.getLogger(__name__)

class AnalysisAccessModel:
    """Modèle pour gérer les accès temporaires aux analyses quiz"""
    
    @staticmethod
    def create_access_token(cursor, user_id, quiz_id, result_id=None, expiry_days=7, max_views=None, access_type='free'):
        """
        Crée un token d'accès sécurisé pour une analyse.
        Si un token existe déjà pour ce user/quiz, le renouvelle si expiré.
        """
        try:
            # ✅ ÉTAPE 1 : Vérifier si un token existe déjà pour ce user/quiz
            cursor.execute("""
                SELECT token, result_id, access_type, expires_at
                FROM analysis_access_tokens
                WHERE user_id = %s 
                AND quiz_id = %s 
                AND is_revoked = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id, quiz_id))
            
            existing_token = cursor.fetchone()
            
            # ✅ CAS 1 : Token existe sans result_id ET on veut ajouter le result_id
            if existing_token and existing_token['result_id'] is None and result_id is not None:
                logger.info(f"[AnalysisAccess] Token existant trouvé pour user {user_id}, "
                        f"mise à jour avec result_id={result_id}")
                
                expires_at = None
                if access_type == 'free' and expiry_days:
                    expires_at = datetime.now() + timedelta(days=expiry_days)
                
                cursor.execute("""
                    UPDATE analysis_access_tokens
                    SET result_id = %s, 
                        updated_at = NOW(),
                        expires_at = %s,
                        max_views = %s,
                        access_type = %s
                    WHERE token = %s
                """, (result_id, expires_at, max_views, access_type, existing_token['token']))
                
                logger.info(f"[AnalysisAccess] Token mis à jour : {existing_token['token'][:20]}..., expires_at={expires_at}")
                return existing_token['token']
            
            # ✅ CAS 2 : Token existe déjà avec result_id identique
            # → Vérifier si expiré et renouveler si nécessaire
            if existing_token and existing_token['result_id'] == result_id and result_id is not None:
                current_expires_at = existing_token['expires_at']
                
                # ✅ FIX: Si FREE et expiré (ou expire dans moins de 1 jour), renouveler
                if access_type == 'free':
                    needs_renewal = (
                        current_expires_at is None or 
                        current_expires_at < datetime.now() + timedelta(days=1)
                    )
                    
                    if needs_renewal:
                        new_expires_at = datetime.now() + timedelta(days=expiry_days)
                        cursor.execute("""
                            UPDATE analysis_access_tokens
                            SET expires_at = %s,
                                updated_at = NOW()
                            WHERE token = %s
                        """, (new_expires_at, existing_token['token']))
                        
                        logger.info(f"[AnalysisAccess] Token renouvelé : {existing_token['token'][:20]}..., "
                                   f"nouvelle expiration: {new_expires_at}")
                    else:
                        logger.info(f"[AnalysisAccess] Token existant valide : {existing_token['token'][:20]}..., "
                                   f"expires_at={current_expires_at}")
                else:
                    logger.info(f"[AnalysisAccess] Token PAID existant : {existing_token['token'][:20]}...")
                
                return existing_token['token']
            
            # ✅ CAS 3 : Token existe avec result_id DIFFÉRENT (analyse statique vs dynamique)
            # → Mettre à jour le result_id et renouveler l'expiration
            if existing_token and existing_token['result_id'] != result_id:
                logger.info(f"[AnalysisAccess] Token existant avec result_id différent, mise à jour...")
                
                expires_at = None
                if access_type == 'free' and expiry_days:
                    expires_at = datetime.now() + timedelta(days=expiry_days)
                
                cursor.execute("""
                    UPDATE analysis_access_tokens
                    SET result_id = %s,
                        expires_at = %s,
                        access_type = %s,
                        updated_at = NOW()
                    WHERE token = %s
                """, (result_id, expires_at, access_type, existing_token['token']))
                
                logger.info(f"[AnalysisAccess] Token mis à jour : {existing_token['token'][:20]}..., expires_at={expires_at}")
                return existing_token['token']
            
            # ✅ CAS 4 : Pas de token existant → Créer un nouveau token
            logger.info(f"[AnalysisAccess] Création nouveau token pour user {user_id}, "
                    f"quiz {quiz_id}, result_id={result_id}")
            
            access_token = f"{uuid.uuid4()}_{int(datetime.now().timestamp())}"
            
            expires_at = None
            if access_type == 'free' and expiry_days:
                expires_at = datetime.now() + timedelta(days=expiry_days)
            
            query = """
                INSERT INTO analysis_access_tokens
                (token, user_id, quiz_id, result_id, expires_at, max_views, access_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (access_token, user_id, quiz_id, result_id, expires_at, max_views, access_type))
            
            logger.info(f"[AnalysisAccess] Token créé : {access_token[:20]}..., expires_at={expires_at}")
            
            return access_token
            
        except Exception as e:
            logger.error(f"[AnalysisAccess] Erreur création/mise à jour token: {e}", exc_info=True)
            return None
    
    @staticmethod
    def get_by_token(cursor, token):
        """
        Récupère les infos d'un token.
        Retourne les infos MÊME si expiré (pour afficher page d'expiration).
        Retourne None seulement si token inexistant ou révoqué.
        """
        try:
            logger.info(f"Recherche token: {token[:20]}...")
            
            query = """
                SELECT aat.id, aat.user_id, aat.quiz_id, aat.result_id,
                    aat.expires_at, aat.max_views, aat.view_count,
                    aat.last_viewed_at, aat.is_revoked, aat.access_type,
                    u.firstname, u.lastname, u.email
                FROM analysis_access_tokens aat
                JOIN users u ON aat.user_id = u.user_id
                WHERE aat.token = %s
            """
            cursor.execute(query, (token,))
            result = cursor.fetchone()
            
            if not result:
                logger.warning(f"Token non trouvé en base: {token[:20]}...")
                return None
            
            if result['is_revoked']:
                logger.warning(f"Token révoqué")
                return None
            
            if result['expires_at'] and result['expires_at'] < datetime.now():
                logger.warning(f"Token expiré: {result['expires_at']} < {datetime.now()}")
            else:
                logger.info(f"Token trouvé - User: {result['user_id']}, Expires: {result['expires_at']}, "
                           f"Views: {result['view_count']}/{result['max_views']}, Type: {result['access_type']}")
            
            return {
                'id': result['id'],
                'user_id': result['user_id'],
                'quiz_id': result['quiz_id'],
                'result_id': result['result_id'],
                'expires_at': result['expires_at'],
                'max_views': result['max_views'],
                'view_count': result['view_count'],
                'last_viewed_at': result['last_viewed_at'],
                'is_revoked': result['is_revoked'],
                'access_type': result['access_type'],
                'firstname': result['firstname'],
                'lastname': result['lastname'],
                'email': result['email']
            }
        except Exception as e:
            logger.error(f"Erreur récupération token: {e}", exc_info=True)
            return None
    
    @staticmethod
    def increment_view_count(cursor, token):
        """Incrémente le compteur de vues"""
        try:
            query = """
                UPDATE analysis_access_tokens
                SET view_count = view_count + 1,
                    last_viewed_at = NOW()
                WHERE token = %s
            """
            cursor.execute(query, (token,))
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Erreur incrémentation vues: {e}")
            return False

    @staticmethod
    def upgrade_to_paid(cursor, token):
        """Upgrade un token free vers paid : supprime toutes les limites"""
        try:
            query = """
                UPDATE analysis_access_tokens
                SET access_type = 'paid',
                    expires_at = NULL,
                    max_views = NULL,
                    updated_at = NOW()
                WHERE token = %s
                AND access_type = 'free'
            """
            cursor.execute(query, (token,))
            
            if cursor.rowcount > 0:
                logger.info(f"Token {token[:20]}... upgradé vers PAID (illimité)")
                return True
            else:
                logger.warning(f"Token {token[:20]}... non trouvé ou déjà paid")
                return False
                
        except Exception as e:
            logger.error(f"Erreur upgrade token: {e}")
            return False