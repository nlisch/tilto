"""
Service de gestion des accès aux pistes d'analyse.

Ce service gère :
- Le filtrage des données d'analyse selon les pistes débloquées
- La récupération des pistes débloquées pour un utilisateur
- Le déblocage de nouvelles pistes avec tokens
- La vérification des droits d'accès

Empêche l'envoi de données sensibles au client pour les pistes non payées.
"""

import copy
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class PisteAccessService:
    """
    Service de gestion des accès aux pistes d'analyse.
    
    Usage:
        service = PisteAccessService(cursor)
        
        # Récupérer les pistes débloquées
        unlocked = service.get_unlocked_pistes(user_id, quiz_id)
        
        # Filtrer les données d'analyse
        filtered = service.filter_analysis_data(analysis_data, unlocked, step_id)
        
        # Débloquer une piste
        result = service.unlock_piste(user_id, quiz_id, piste_number, token_code)
    """
    
    def __init__(self, cursor):
        """
        Initialise le service.
        
        Args:
            cursor: Curseur MySQL (DictCursor recommandé)
        """
        self.cursor = cursor
    
    # =========================================================================
    # RÉCUPÉRATION DES PISTES DÉBLOQUÉES
    # =========================================================================
    
    def get_unlocked_pistes(self, user_id: int, quiz_id: str) -> List[int]:
        """
        Récupère la liste des pistes débloquées pour un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur
            quiz_id: ID du quiz
        
        Returns:
            Liste des numéros de pistes débloquées [1, 2, 3]
        """
        # 🎯 TEMPORAIRE : Désactiver le système de tokens - toutes les pistes accessibles
        # Pour réactiver : supprimer ces 2 lignes et décommenter le code en dessous
        return [1, 2, 3]
        
        # --- CODE ORIGINAL (désactivé temporairement) ---
        # try:
        #     self.cursor.execute("""
        #         SELECT piste_number 
        #         FROM user_unlocked_pistes 
        #         WHERE user_id = %s AND quiz_id = %s
        #         ORDER BY piste_number
        #     """, (user_id, quiz_id))
        #     
        #     results = self.cursor.fetchall()
        #     
        #     # Extraire les numéros de pistes (compatible dict ou tuple)
        #     unlocked = [
        #         row['piste_number'] if isinstance(row, dict) else row[0] 
        #         for row in results
        #     ]
        #     
        #     logger.debug(f"Pistes débloquées pour user {user_id}, quiz {quiz_id}: {unlocked}")
        #     return unlocked
        #     
        # except Exception as e:
        #     logger.error(f"Erreur récupération pistes débloquées: {e}")
        #     return []

    def is_piste_unlocked(self, user_id: int, quiz_id: str, piste_number: int) -> bool:
        """
        Vérifie si une piste spécifique est débloquée.
        
        Args:
            user_id: ID de l'utilisateur
            quiz_id: ID du quiz
            piste_number: Numéro de la piste (1, 2 ou 3)
        
        Returns:
            True si la piste est débloquée
        """
        try:
            self.cursor.execute("""
                SELECT 1 FROM user_unlocked_pistes 
                WHERE user_id = %s AND quiz_id = %s AND piste_number = %s
                LIMIT 1
            """, (user_id, quiz_id, piste_number))
            
            return self.cursor.fetchone() is not None
            
        except Exception as e:
            logger.error(f"Erreur vérification piste débloquée: {e}")
            return False
    
    def get_unlock_count(self, user_id: int, quiz_id: str) -> int:
        """
        Compte le nombre de pistes débloquées.
        
        Args:
            user_id: ID de l'utilisateur
            quiz_id: ID du quiz
        
        Returns:
            Nombre de pistes débloquées (0-3)
        """
        try:
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM user_unlocked_pistes 
                WHERE user_id = %s AND quiz_id = %s
            """, (user_id, quiz_id))
            
            result = self.cursor.fetchone()
            return result['count'] if isinstance(result, dict) else result[0]
            
        except Exception as e:
            logger.error(f"Erreur comptage pistes débloquées: {e}")
            return 0
    
    # =========================================================================
    # DÉBLOCAGE DE PISTES
    # =========================================================================
    
    def unlock_piste(
        self, 
        user_id: int, 
        quiz_id: str, 
        piste_number: int, 
        token_code: str
    ) -> Dict[str, Any]:
        """
        Débloque une piste en utilisant un token.
        
        Args:
            user_id: ID de l'utilisateur
            quiz_id: ID du quiz
            piste_number: Numéro de la piste à débloquer (1, 2 ou 3)
            token_code: Code du token à utiliser
        
        Returns:
            dict: {
                'success': bool,
                'message': str,
                'error': str (si échec),
                'piste_number': int (si succès),
                'remaining_tokens': int (si succès)
            }
        """
        try:
            # Validation du numéro de piste
            if piste_number not in [1, 2, 3]:
                return {
                    'success': False,
                    'error': 'Numéro de piste invalide (doit être 1, 2 ou 3)'
                }
            
            # Vérifier que le token existe et appartient à l'utilisateur
            self.cursor.execute("""
                SELECT token_code, is_used, token_type
                FROM tokens 
                WHERE token_code = %s AND user_id = %s
            """, (token_code, user_id))
            
            token = self.cursor.fetchone()
            
            if not token:
                return {
                    'success': False,
                    'error': 'Token invalide ou non trouvé'
                }
            
            if token['is_used'] if isinstance(token, dict) else token[1]:
                return {
                    'success': False,
                    'error': 'Ce token a déjà été utilisé'
                }
            
            # Vérifier que la piste n'est pas déjà débloquée
            if self.is_piste_unlocked(user_id, quiz_id, piste_number):
                return {
                    'success': False,
                    'error': 'Cette piste est déjà débloquée'
                }
            
            # Débloquer la piste
            self.cursor.execute("""
                INSERT INTO user_unlocked_pistes 
                (user_id, quiz_id, piste_number, token_code, unlocked_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (user_id, quiz_id, piste_number, token_code))
            
            # Marquer le token comme utilisé
            self.cursor.execute("""
                UPDATE tokens 
                SET is_used = TRUE, 
                    used_at = NOW(), 
                    used_for_piste = %s
                WHERE token_code = %s
            """, (piste_number, token_code))
            
            # Compter les tokens restants
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM tokens 
                WHERE user_id = %s AND is_used = FALSE
            """, (user_id,))
            
            remaining = self.cursor.fetchone()
            remaining_count = remaining['count'] if isinstance(remaining, dict) else remaining[0]
            
            logger.info(f"Piste {piste_number} débloquée pour user {user_id} avec token {token_code}")
            
            return {
                'success': True,
                'message': f'Piste {piste_number} débloquée avec succès !',
                'piste_number': piste_number,
                'remaining_tokens': remaining_count
            }
            
        except Exception as e:
            logger.error(f"Erreur déblocage piste: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }
    
    # =========================================================================
    # FILTRAGE DES DONNÉES D'ANALYSE
    # =========================================================================
    
    def filter_analysis_data(
        self, 
        analysis_data: dict, 
        unlocked_pistes: List[int], 
        step_id: str
    ) -> dict:
        """
        Filtre les données d'analyse pour ne garder que les infos des pistes débloquées.
        
        Les pistes verrouillées sont remplacées par des placeholders génériques
        qui ne contiennent aucune information sensible.
        
        Args:
            analysis_data: Le JSON complet de l'analyse
            unlocked_pistes: Liste des numéros de pistes débloquées [1, 2, 3]
            step_id: L'identifiant de l'étape (career_path_v3, etc.)
        
        Returns:
            dict: L'analyse filtrée avec des placeholders pour les pistes verrouillées
        """
        # Copie profonde pour ne pas modifier l'original
        filtered = copy.deepcopy(analysis_data)
        
        # Appliquer le filtrage selon le type de step
        if step_id in ['career_path_v1', 'career_path_v2', 'career_path_v3', 'career_path_v4']:
            filtered = self._filter_career_path_v1_v2_v3(filtered, unlocked_pistes)
        elif step_id == 'career_path':
            filtered = self._filter_career_path(filtered, unlocked_pistes)
        else:
            logger.warning(f"Step ID non reconnu pour filtrage: {step_id}")
        
        return filtered
    
    def _filter_career_path_v1_v2_v3(
        self, 
        data: dict, 
        unlocked_pistes: List[int]
    ) -> dict:
        """
        Filtre les données pour les formats career_path_v1, v2, v3.
        """
        # Filtrer les voies (détails complets)
        if 'voies' in data and isinstance(data['voies'], list):
            data['voies'] = self._filter_list_by_index(
                data['voies'], 
                unlocked_pistes,
                self._get_locked_voie_placeholder
            )
        
        # Filtrer les options (aperçu sur la page principale)
        if 'options' in data and isinstance(data['options'], list):
            data['options'] = self._filter_options(
                data['options'],
                unlocked_pistes
            )
        
        return data
    
    def _filter_career_path(
        self, 
        data: dict, 
        unlocked_pistes: List[int]
    ) -> dict:
        """
        Filtre les données pour le format career_path (ancien format).
        """
        # Filtrer les stratégies
        if 'strategies' in data and 'items' in data['strategies']:
            data['strategies']['items'] = self._filter_list_by_index(
                data['strategies']['items'],
                unlocked_pistes,
                self._get_locked_strategy_placeholder
            )
        
        # Filtrer les actions
        if 'actions' in data and 'items' in data['actions']:
            data['actions']['items'] = self._filter_list_by_index(
                data['actions']['items'],
                unlocked_pistes,
                self._get_locked_action_placeholder
            )
        
        return data
    
    def _filter_list_by_index(
        self, 
        items: list, 
        unlocked_indices: List[int], 
        placeholder_fn
    ) -> list:
        """
        Filtre une liste en remplaçant les éléments non débloqués par des placeholders.
        """
        result = []
        for i, item in enumerate(items):
            index_1based = i + 1  # Convertir en index 1-based
            
            if index_1based in unlocked_indices:
                # Piste débloquée : garder toutes les données
                # Ajouter is_locked = False pour le template
                if isinstance(item, dict):
                    item['is_locked'] = False
                result.append(item)
            else:
                # Piste verrouillée : remplacer par un placeholder
                result.append(placeholder_fn(index_1based, item))
        
        return result
    
    def _filter_options(
        self, 
        options: list, 
        unlocked_indices: List[int]
    ) -> list:
        """
        Filtre les options (aperçu des pistes sur la page principale).
        On garde le titre et l'icône mais on masque les tags et le why_match
        avec des placeholders visuellement cohérents.
        """
        result = []
        for i, option in enumerate(options):
            index_1based = i + 1
            
            if index_1based in unlocked_indices:
                # Piste débloquée : garder tout + flag
                if isinstance(option, dict):
                    option['is_locked'] = False
                result.append(option)
            else:
                # Piste verrouillée : placeholders visuellement cohérents
                # On garde le titre et l'icône, mais on remplace le reste par des placeholders
                result.append({
                    'number': option.get('number', index_1based),
                    'title': option.get('title', f'Piste {index_1based}'),
                    'icon': option.get('icon', '🔒'),
                    # Placeholders pour les tags (même nombre que l'original ou 3 par défaut)
                    'tags': ['Avantage clé', 'Compétence valorisée', 'Opportunité'],
                    # Placeholder pour le why_match (texte générique engageant)
                    'why_match': '<strong>Cette piste a été sélectionnée</strong> spécifiquement pour ton profil. Débloque-la pour découvrir pourquoi elle correspond à tes aspirations et comment elle valorise ton parcours.',
                    'is_locked': True
                })
        
        return result
    
    # =========================================================================
    # PLACEHOLDERS POUR PISTES VERROUILLÉES
    # =========================================================================
    
    @staticmethod
    def _get_locked_voie_placeholder(index: int, original: dict) -> dict:
        """
        Génère un placeholder pour une voie verrouillée.
        Conserve la structure mais remplace le contenu sensible.
        """
        return {
            'number': index,
            'hero_title': '',
            'quelques_mots': '',
            'avantage_unique': '',
            'warning_text': '',
            'dire_quote': '',
            'warning_evite': '',
            'formations': [],
            'cibles_employeurs': [],
            'dernier_conseil': '',
            'savais_tu': '',
            'resume_avantages': [],
            'resume_duree': '',
            'resume_defis': '',
            'resume_salaire': '',
            'is_locked': True
        }
    
    @staticmethod
    def _get_locked_strategy_placeholder(index: int, original: dict) -> dict:
        """
        Génère un placeholder pour une stratégie verrouillée (format career_path).
        """
        return {
            'number': index,
            'title': original.get('title', f'Stratégie {index}'),
            'icon': original.get('icon', '🔒'),
            'summary': '',
            'details': '',
            'is_locked': True
        }
    
    @staticmethod
    def _get_locked_action_placeholder(index: int, original: dict) -> dict:
        """
        Génère un placeholder pour une action verrouillée (format career_path).
        """
        return {
            'number': index,
            'title': original.get('title', f'Action {index}'),
            'summary': '',
            'steps': [],
            'is_locked': True
        }
    
    # =========================================================================
    # UTILITAIRES
    # =========================================================================
    
    def get_piste_unlock_info(
        self, 
        user_id: int, 
        quiz_id: str, 
        piste_number: int
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère les informations de déblocage d'une piste.
        
        Args:
            user_id: ID de l'utilisateur
            quiz_id: ID du quiz
            piste_number: Numéro de la piste
        
        Returns:
            dict avec token_code et unlocked_at, ou None si non débloquée
        """
        try:
            self.cursor.execute("""
                SELECT token_code, unlocked_at
                FROM user_unlocked_pistes 
                WHERE user_id = %s AND quiz_id = %s AND piste_number = %s
            """, (user_id, quiz_id, piste_number))
            
            result = self.cursor.fetchone()
            
            if result:
                return {
                    'token_code': result['token_code'] if isinstance(result, dict) else result[0],
                    'unlocked_at': result['unlocked_at'] if isinstance(result, dict) else result[1]
                }
            return None
            
        except Exception as e:
            logger.error(f"Erreur récupération info déblocage: {e}")
            return None
    
    def get_user_tokens_count(self, user_id: int) -> int:
        """
        Compte les tokens disponibles (non utilisés) pour un utilisateur.
        
        Args:
            user_id: ID de l'utilisateur
        
        Returns:
            Nombre de tokens disponibles
        """
        try:
            self.cursor.execute("""
                SELECT COUNT(*) as count
                FROM tokens 
                WHERE user_id = %s 
                AND is_used = FALSE
                AND (expiration_date IS NULL OR expiration_date > NOW())
            """, (user_id,))
            
            result = self.cursor.fetchone()
            return result['count'] if isinstance(result, dict) else result[0]
            
        except Exception as e:
            logger.error(f"Erreur comptage tokens: {e}")
            return 0
    
    def can_unlock_any_piste(self, user_id: int, quiz_id: str) -> bool:
        """
        Vérifie si l'utilisateur peut débloquer au moins une piste.
        
        Returns:
            True si l'utilisateur a des tokens ET des pistes non débloquées
        """
        tokens_count = self.get_user_tokens_count(user_id)
        if tokens_count == 0:
            return False
        
        unlocked_count = self.get_unlock_count(user_id, quiz_id)
        return unlocked_count < 3
    
    def get_access_summary(self, user_id: int, quiz_id: str) -> Dict[str, Any]:
        """
        Retourne un résumé complet de l'état d'accès pour un utilisateur.
        
        Returns:
            dict: {
                'unlocked_pistes': [1, 2],
                'locked_pistes': [3],
                'unlocked_count': 2,
                'available_tokens': 1,
                'can_unlock_more': True,
                'all_unlocked': False
            }
        """
        unlocked = self.get_unlocked_pistes(user_id, quiz_id)
        all_pistes = [1, 2, 3]
        locked = [p for p in all_pistes if p not in unlocked]
        tokens = self.get_user_tokens_count(user_id)
        
        return {
            'unlocked_pistes': unlocked,
            'locked_pistes': locked,
            'unlocked_count': len(unlocked),
            'available_tokens': tokens,
            'can_unlock_more': tokens > 0 and len(locked) > 0,
            'all_unlocked': len(unlocked) >= 3
        }


# =============================================================================
# FONCTION UTILITAIRE POUR USAGE SIMPLE (rétrocompatibilité)
# =============================================================================

def filter_analysis_by_unlocked_pistes(
    analysis_data: dict, 
    unlocked_pistes: list, 
    step_id: str
) -> dict:
    """
    Fonction utilitaire pour filtrer les données sans instancier le service.
    
    Utile pour les cas simples où on n'a pas besoin du cursor.
    
    Args:
        analysis_data: Le JSON complet de l'analyse
        unlocked_pistes: Liste des numéros de pistes débloquées [1, 2, 3]
        step_id: L'identifiant de l'étape
    
    Returns:
        dict: L'analyse filtrée
    """
    # Créer une instance temporaire sans cursor (juste pour le filtrage)
    service = PisteAccessService(cursor=None)
    return service.filter_analysis_data(analysis_data, unlocked_pistes, step_id)


def get_unlocked_pistes_for_user(cursor, user_id: int, quiz_id: str) -> list:
    """
    Fonction utilitaire pour récupérer les pistes débloquées.
    
    Args:
        cursor: Curseur MySQL
        user_id: ID de l'utilisateur
        quiz_id: ID du quiz
    
    Returns:
        Liste des numéros de pistes débloquées
    """
    service = PisteAccessService(cursor)
    return service.get_unlocked_pistes(user_id, quiz_id)