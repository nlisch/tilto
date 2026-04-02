from typing import Dict, List, Tuple, Optional, Any
import logging
import json
import time
from datetime import datetime
import anthropic
from anthropic import Anthropic
from flask import current_app, g
import unicodedata
from services import AnonymizationClient
import re
import traceback 
import requests

logger = logging.getLogger(__name__)


class PromptData:
    def __init__(self, human_prompt: str, system_prompt: str, session_data: Dict, 
                 anonymized_human_prompt: Optional[str] = None): 
        self.human_prompt = human_prompt  
        self.system_prompt = system_prompt 
        self.anonymized_human_prompt = anonymized_human_prompt or human_prompt  
        self.session_data = session_data
        self.api_params = self._get_default_api_params()

    def _get_default_api_params(self) -> Dict:
        return {
            "model": current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-5-20250929'),
            "max_tokens": current_app.config.get('ANTHROPIC_MAX_TOKENS', 16384),
            "temperature": current_app.config.get('ANTHROPIC_TEMPERATURE', 0.7)
        }

class QuizAnalysisService:
    def __init__(self, cursor, user_id: int, quiz_id: str):
        self.cursor = cursor
        self.user_id = user_id
        self.quiz_id = quiz_id
        self.client = Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])
        self.anonymizer = current_app.anonymization_service
        self._slack_service = None
        self._slack_available = None

    @property
    def slack_service(self):
        """Lazy import de slack_service pour éviter circular import"""
        if self._slack_service is None:
            try:
                from services import slack_service
                self._slack_service = slack_service
            except ImportError:
                self._slack_service = False  # Marquer comme non disponible
        return self._slack_service if self._slack_service is not False else None

    @property
    def slack_available(self):
        """Lazy import de SLACK_AVAILABLE pour éviter circular import"""
        if self._slack_available is None:
            try:
                from services import SLACK_AVAILABLE
                self._slack_available = SLACK_AVAILABLE
            except ImportError:
                self._slack_available = False
        return self._slack_available

    def _store_analysis_result(self, result_id: str, step_id: str, result_json: Dict, 
                            token_id: str, prompt_id: int,
                            is_active: bool = True, generator_type: str = 'user',
                            timings: Dict = None) -> None:
        """
        Stores or updates an analysis result in the database.
        ✅ Met à jour result_id dans analysis_access_tokens pour TOUTE insertion/update
        """
        logger.info(f"Attempting to store result with timings: {timings}")
        
        try:
            generation_time = timings.get('generation_time_seconds') if timings else None
            api_time = timings.get('api_call_time_seconds') if timings else None
            validation_attempts = timings.get('validation_attempts', 1) if timings else 1
            validation_status = timings.get('validation_status', 'success') if timings else 'success'
            
            # ===== Check if an admin result already exists =====
            if generator_type == 'admin':
                self.cursor.execute("""
                    SELECT 1 FROM result_user 
                    WHERE result_id = %s 
                    AND result_step_id = %s 
                    AND generator_type = 'admin'
                """, (result_id, step_id))
                exists = self.cursor.fetchone() is not None
                
                if exists:
                    # Update existing admin result
                    self.cursor.execute("""
                        UPDATE result_user 
                        SET result_json = %s,
                            token_id = %s,
                            prompt_id = %s,
                            is_active = %s,
                            generation_time_seconds = %s,
                            api_call_time_seconds = %s,
                            validation_attempts = %s,           
                            validation_status = %s,              
                            updated_at = CURRENT_TIMESTAMP
                        WHERE result_id = %s 
                        AND result_step_id = %s 
                        AND generator_type = 'admin'
                    """, (
                        json.dumps(result_json), 
                        token_id, 
                        prompt_id, 
                        is_active, 
                        generation_time, 
                        api_time,
                        validation_attempts,   # ✅ AJOUTÉ
                        validation_status,     # ✅ AJOUTÉ
                        result_id, 
                        step_id
                    ))
                    
                    logger.info(f"✅ Updated existing admin result with validation metrics: "
                            f"{validation_attempts} attempts, status: {validation_status}")
                    
                    # ✅ TOUJOURS mettre à jour analysis_access_tokens
                    self._update_token_result_id(token_id, result_id)
                    
                    return
            
            # ===== Insert new result =====
            self.cursor.execute("""
                INSERT INTO result_user (
                    quiz_id, user_id, result_id, result_step_id,
                    result_json, token_id, prompt_id, is_active, generator_type,
                    generation_time_seconds, api_call_time_seconds,
                    validation_attempts, validation_status              # ✅ AJOUTÉ
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                self.quiz_id,
                self.user_id,
                result_id,
                step_id,
                json.dumps(result_json),
                token_id,
                prompt_id,
                is_active,
                generator_type,
                generation_time,
                api_time,
                validation_attempts,   # ✅ AJOUTÉ
                validation_status      # ✅ AJOUTÉ
            ))
            
            logger.info(f"✅ Inserted new result with validation metrics: "
                    f"{validation_attempts} attempts, status: {validation_status}")
            
            # ===== ✅ TOUJOURS mettre à jour analysis_access_tokens =====
            self._update_token_result_id(token_id, result_id)
            
        except Exception as e:
            logger.error(f"❌ Error storing analysis result: {str(e)}")
            raise


    def _update_token_result_id(self, token_id: str, result_id: str) -> None:
        """
        Met à jour le result_id dans analysis_access_tokens quand une analyse LLM est générée.
        
        Cette fonction est appelée après stockage dans result_user pour synchroniser
        le token de partage temporaire avec le result_id fraîchement créé.
        
        Args:
            token_id: Token depuis result_user (ex: "admin_10547758", "user_token")
            result_id: UUID de l'analyse générée (ex: "10547758-2125-4026-a43f-7ad5af4faddc")
        """
        try:
            logger.info(f"🔄 Synchronisation analysis_access_tokens avec result_id")
            logger.info(f"   User: {self.user_id} | Quiz: {self.quiz_id}")
            logger.info(f"   Result ID: {result_id}")
            
            # ===== IMPORTANT : On ignore token_id (qui vient de tokens) =====
            # On cherche directement le token PARTAGEABLE du user dans analysis_access_tokens
            
            self.cursor.execute("""
                SELECT token, result_id, access_type, expires_at, max_views
                FROM analysis_access_tokens
                WHERE user_id = %s 
                AND quiz_id = %s
                AND is_revoked = FALSE
                ORDER BY created_at DESC
                LIMIT 1
            """, (self.user_id, self.quiz_id))
            
            access_token_data = self.cursor.fetchone()
            
            # CAS 1 : Aucun token partageable trouvé
            if not access_token_data:
                logger.warning(f"⚠️  Aucun token de partage trouvé pour user {self.user_id}, quiz {self.quiz_id}")
                logger.warning(f"   → Le user n'a probablement pas de token analysis_access_tokens")
                logger.warning(f"   → Normal si analyse générée par admin pour user sans inscription lead")
                return
            
            access_token = access_token_data['token']
            current_result_id = access_token_data['result_id']
            access_type = access_token_data['access_type']
            
            logger.info(f"✅ Token de partage trouvé: {access_token[:20]}...")
            logger.info(f"   Access type: {access_type}")
            logger.info(f"   Expires at: {access_token_data['expires_at']}")
            logger.info(f"   Max views: {access_token_data['max_views']}")
            logger.info(f"   Current result_id: {current_result_id or 'NULL'}")
            
            # CAS 2 : result_id déjà renseigné
            if current_result_id is not None:
                if current_result_id == result_id:
                    logger.info(f"✅ Token déjà lié au même result_id")
                else:
                    logger.warning(f"⚠️  Token déjà lié à un autre result_id!")
                    logger.warning(f"   Ancien: {current_result_id}")
                    logger.warning(f"   Nouveau: {result_id}")
                    logger.warning(f"   → Pas de mise à jour pour éviter écrasement")
                return
            
            # CAS 3 : result_id NULL → MISE À JOUR
            logger.info(f"🔄 Mise à jour : result_id NULL → {result_id}")
            
            self.cursor.execute("""
                UPDATE analysis_access_tokens
                SET result_id = %s,
                    updated_at = NOW()
                WHERE token = %s
                AND result_id IS NULL
            """, (result_id, access_token))
            
            rows_updated = self.cursor.rowcount
            
            if rows_updated > 0:
                logger.info(f"✅ Token de partage mis à jour avec succès")
                logger.info(f"   → Token: {access_token[:20]}...")
                logger.info(f"   → Result ID: {result_id}")
                logger.info(f"   → Type: {access_type}")
                logger.info(f"   ℹ️  Le user peut maintenant accéder à son analyse via le lien partageable")
            else:
                logger.warning(f"⚠️  Aucune ligne mise à jour (race condition possible)")
                
        except Exception as e:
            logger.error(f"❌ Erreur synchronisation analysis_access_tokens: {e}", exc_info=True)

    def _store_prompt(self, result_id: str, step_id: str, prompt_data: PromptData, 
                    request_id: str,
                    generation_type: str = 'initial',
                    attempt_number: int = 1,
                    parent_prompt_id: int = None,
                    admin_feedback: str = None,
                    selected_voies_indices: list = None,
                    validation_issues: list = None,
                    custom_validation_criteria: str = None,
                    prompt_type: str = 'generation') -> int:
        """
        Stocke les données du prompt avec contexte complet pour historique.
        
        Args:
            result_id: UUID de l'analyse
            step_id: Étape (career_path_v2, etc.)
            prompt_data: Objet PromptData avec system/human prompts
            request_id: ID de requête pour logs
            generation_type: 'initial' | 'replay' | 'manual_retry' | 'validation_retry'
            attempt_number: Numéro de tentative (1, 2, 3...)
            parent_prompt_id: ID du prompt précédent (pour chaînage)
            admin_feedback: Feedback texte de l'admin (si manual_retry)
            selected_voies_indices: [0, 2] si voies 1 et 3 sélectionnées
            validation_issues: Liste des issues ayant déclenché ce retry
            custom_validation_criteria: Critères custom si utilisés
            prompt_type: 'generation' | 'validation'
        
        Returns:
            int: prompt_id créé
        """
        try:
            storage_data = {
                "session_data": {
                    # Identifiants
                    "result_id": result_id,
                    "step_id": step_id,
                    "user_id": self.user_id,
                    "quiz_id": self.quiz_id,
                    "timestamp": datetime.now().isoformat(),
                    "request_id": request_id,
                    
                    # Type de prompt
                    "prompt_type": prompt_type,  # 'generation' ou 'validation'
                    
                    # Contexte de génération
                    "generation_type": generation_type,
                    "attempt_number": attempt_number,
                    "parent_prompt_id": parent_prompt_id,
                    
                    # Contexte admin (si manual_retry)
                    "admin_feedback": admin_feedback,
                    "selected_voies_indices": selected_voies_indices,
                    
                    # Issues ayant déclenché ce prompt (si retry)
                    "trigger_issues": validation_issues,
                    
                    # Critères custom utilisés
                    "custom_validation_criteria_used": bool(custom_validation_criteria),
                },
                "prompt": {
                    "system": prompt_data.system_prompt,
                    "human": prompt_data.human_prompt
                },
                "api_params": prompt_data.api_params
            }
            
            # Ajouter prompt anonymisé si différent
            if prompt_data.anonymized_human_prompt != prompt_data.human_prompt:
                storage_data["prompt"]["anonymized_human"] = prompt_data.anonymized_human_prompt
                
                if hasattr(self.anonymizer, 'replacement_cache') and self.anonymizer.replacement_cache:
                    storage_data["anonymization_cache"] = self.anonymizer.replacement_cache
            
            prompt_str = json.dumps(storage_data, ensure_ascii=False)

            self.cursor.execute("""
                INSERT INTO prompt_user (
                    result_id,
                    result_step_id,
                    user_id,
                    prompt
                ) VALUES (%s, %s, %s, %s)
            """, (result_id, step_id, self.user_id, prompt_str))

            prompt_id = self.cursor.lastrowid
            logger.info(f"[{request_id}] Prompt stored: ID={prompt_id}, type={prompt_type}, gen_type={generation_type}, attempt={attempt_number}")
            
            return prompt_id

        except Exception as e:
            logger.error(f"[{request_id}] Error storing prompt: {str(e)}")
            raise
        
    def _store_validation_prompt(self, result_id: str, step_id: str, request_id: str,
                                validation_prompt: str, validated_json: dict,
                                validation_result: dict, validation_duration: float,
                                parent_generation_prompt_id: int,
                                validation_criteria_source: str = 'database',
                                custom_criteria: str = None,
                                attempt_number: int = 1) -> int:
        """
        Stocke le prompt de validation pour traçabilité complète.
        
        Args:
            result_id: UUID de l'analyse
            step_id: Étape
            request_id: ID de requête
            validation_prompt: Le prompt envoyé au LLM validator
            validated_json: Le JSON qui a été validé
            validation_result: Réponse du validator {is_valid, issues, assessment}
            validation_duration: Durée de la validation en secondes
            parent_generation_prompt_id: ID du prompt de génération associé
            validation_criteria_source: 'database' | 'custom' | 'fallback'
            custom_criteria: Critères custom si utilisés
        
        Returns:
            int: prompt_id du prompt de validation
        """
        try:
            # Extraire un aperçu du JSON validé (pas tout pour éviter la duplication)
            if step_id in ('career_path_v1', 'career_path_v2', 'career_path_v3', 'career_path_v4'):
                voies = validated_json.get('voies', [])
                json_preview = {
                    "voies_count": len(voies),
                    "voies_titles": [v.get('hero_title') or v.get('title', 'N/A') for v in voies]
                }
            elif step_id == 'career_path':
                items = validated_json.get('strategies', {}).get('items', [])
                json_preview = {
                    "strategies_count": len(items),
                    "strategies_titles": [s.get('title', 'N/A') for s in items]
                }
            else:
                json_preview = {"step_id": step_id}
            
            storage_data = {
                "session_data": {
                    # Identifiants
                    "result_id": result_id,
                    "step_id": step_id,
                    "user_id": self.user_id,
                    "quiz_id": self.quiz_id,
                    "timestamp": datetime.now().isoformat(),
                    "request_id": f"{request_id}_validation",
                    
                    # Type de prompt
                    "prompt_type": "validation",

                    "attempt_number": attempt_number,
                    
                    # Lien vers le prompt de génération
                    "parent_generation_prompt_id": parent_generation_prompt_id,
                    
                    # Ce qu'on a validé (aperçu)
                    "validated_json_preview": json_preview,
                    
                    # Source des critères
                    "validation_criteria_source": validation_criteria_source,
                    
                    # Résultat de la validation
                    "validation_result": validation_result,
                    "validation_duration_seconds": round(validation_duration, 2)
                },
                "prompt": {
                    "system": "",
                    "human": validation_prompt
                },
                "api_params": {
                    "model": current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
                    "temperature": 0.1,
                    "max_tokens": 2000
                }
            }
            
            # Ajouter les critères custom si utilisés
            if validation_criteria_source == 'custom' and custom_criteria:
                storage_data["validation_criteria_custom"] = custom_criteria
            
            prompt_str = json.dumps(storage_data, ensure_ascii=False)

            self.cursor.execute("""
                INSERT INTO prompt_user (
                    result_id,
                    result_step_id,
                    user_id,
                    prompt
                ) VALUES (%s, %s, %s, %s)
            """, (result_id, step_id, self.user_id, prompt_str))

            validation_prompt_id = self.cursor.lastrowid
            
            logger.info(f"[{request_id}] Validation prompt stored: ID={validation_prompt_id}, "
                        f"parent={parent_generation_prompt_id}, result={validation_result.get('is_valid')}")
            
            return validation_prompt_id

        except Exception as e:
            logger.error(f"[{request_id}] Error storing validation prompt: {str(e)}")
            raise

    def _update_prompt_with_validation_link(self, prompt_id: int, validation_prompt_id: int,
                                            validation_status: str, generation_duration: float = None):
        """
        Met à jour le prompt de génération avec le lien vers son prompt de validation.
        
        Args:
            prompt_id: ID du prompt de génération
            validation_prompt_id: ID du prompt de validation associé
            validation_status: 'success' | 'failed'
            generation_duration: Durée totale de génération (optionnel)
        """
        try:
            # Récupérer le prompt actuel
            self.cursor.execute("""
                SELECT prompt FROM prompt_user WHERE prompt_id = %s
            """, (prompt_id,))
            
            result = self.cursor.fetchone()
            if not result:
                logger.warning(f"Prompt {prompt_id} not found for update")
                return
            
            # Parser et mettre à jour
            prompt_data = json.loads(result['prompt'])
            prompt_data['session_data']['validation_prompt_id'] = validation_prompt_id
            prompt_data['session_data']['validation_status'] = validation_status
            
            if generation_duration:
                prompt_data['session_data']['generation_duration_seconds'] = round(generation_duration, 2)
            
            # Sauvegarder
            self.cursor.execute("""
                UPDATE prompt_user 
                SET prompt = %s 
                WHERE prompt_id = %s
            """, (json.dumps(prompt_data, ensure_ascii=False), prompt_id))
            
            logger.info(f"Prompt {prompt_id} updated with validation link: {validation_prompt_id}, status: {validation_status}")
            
        except Exception as e:
            logger.error(f"Error updating prompt with validation link: {e}")

    def _update_prompt_with_llm_response(self, prompt_id: int, llm_response: str, 
                                        response_duration: float = None):
        """
        Met à jour le prompt avec la réponse brute du LLM.
        
        Args:
            prompt_id: ID du prompt à mettre à jour
            llm_response: Réponse brute de Claude (texte complet)
            response_duration: Durée de l'appel API en secondes (optionnel)
        """
        try:
            # Récupérer le prompt actuel
            self.cursor.execute("""
                SELECT prompt FROM prompt_user WHERE prompt_id = %s
            """, (prompt_id,))
            
            result = self.cursor.fetchone()
            if not result:
                logger.warning(f"Prompt {prompt_id} not found for LLM response update")
                return
            
            # Parser et mettre à jour
            prompt_data = json.loads(result['prompt'])
            
            # Ajouter la réponse LLM (tronquée si > 50000 chars pour éviter bloat)
            max_response_length = 50000
            if len(llm_response) > max_response_length:
                prompt_data['llm_response'] = llm_response[:max_response_length]
                prompt_data['llm_response_truncated'] = True
                prompt_data['llm_response_full_length'] = len(llm_response)
            else:
                prompt_data['llm_response'] = llm_response
                prompt_data['llm_response_truncated'] = False
            
            if response_duration:
                prompt_data['session_data']['api_duration_seconds'] = round(response_duration, 2)
            
            # Sauvegarder
            self.cursor.execute("""
                UPDATE prompt_user 
                SET prompt = %s 
                WHERE prompt_id = %s
            """, (json.dumps(prompt_data, ensure_ascii=False), prompt_id))
            
            logger.info(f"Prompt {prompt_id} updated with LLM response ({len(llm_response)} chars)")
            
        except Exception as e:
            logger.error(f"Error updating prompt with LLM response: {e}")

    def get_latest_analysis(self) -> Optional[Dict[str, Any]]:
        """Récupère la dernière analyse pour ce quiz."""
        self.cursor.execute("""
            SELECT result_json
            FROM result_user
            WHERE quiz_id = %s AND user_id = %s
            AND result_step_id = 'vision_360'
            AND is_active = TRUE
            ORDER BY created_at DESC
            LIMIT 1
        """, (self.quiz_id, self.user_id))
        
        result = self.cursor.fetchone()
        return json.loads(result[0]) if result and result[0] else None

    # ===== Gestion des tokens =====
    def validate_and_get_token(self, step_id: str, result_id: str = None, force_new: bool = False) -> str:
        """
        Valide et récupère un token valide pour une étape donnée.
        
        Args:
            step_id (str): Identifiant de l'étape
            result_id (str): Identifiant du résultat (optionnel)
            force_new (bool): Force la génération d'une nouvelle analyse même si une existe déjà
            
        Returns:
            str: Code du token valide
            
        Raises:
            ValueError: Si aucun token valide n'est trouvé ou si une analyse existe déjà
        """
        try:
            logger.info(f"Validating token for step_id: {step_id}, result_id: {result_id}, force_new: {force_new}")
            
            # Débuter une transaction explicite
            self.cursor.connection.begin()
            
            # 1. Vérifier si une analyse existe déjà pour cette étape et ce result_id
            result_id_condition = "AND ru.result_id = %s" if result_id else ""
            result_id_params = (result_id,) if result_id else ()
            
            self.cursor.execute(f"""
                WITH LatestResult AS (
                    SELECT ru.token_id, ru.result_id, MAX(ru.created_at) as last_created_at
                    FROM result_user ru
                    WHERE ru.quiz_id = %s 
                    AND ru.user_id = %s
                    AND ru.is_active = TRUE
                    {result_id_condition}
                    GROUP BY ru.token_id, ru.result_id
                ),
                TokenSteps AS (
                    SELECT 
                        ru.result_id,
                        ru.token_id,
                        ru.result_step_id,
                        ru.generator_type
                    FROM result_user ru
                    JOIN LatestResult lr ON ru.token_id = lr.token_id 
                        AND ru.created_at >= lr.last_created_at
                    WHERE ru.quiz_id = %s 
                    AND ru.user_id = %s
                    AND ru.result_step_id = %s
                    AND ru.is_active = TRUE
                )
                SELECT * FROM TokenSteps
            """, (self.quiz_id, self.user_id, *result_id_params, self.quiz_id, self.user_id, step_id))
            
            existing_result = self.cursor.fetchone()
            
            if existing_result:
                logger.info(f"Found existing step: {existing_result}")
                
                # Permettre une nouvelle analyse si force_new et type admin
                if force_new and existing_result['generator_type'] == 'admin':
                    logger.info("Allowing new analysis generation for admin result")
                else:
                    self.cursor.connection.rollback()  # Rollback avant de raise
                    logger.info("Returning existing analysis")
                    raise ValueError(f"existing_analysis:{existing_result['result_id']}:{existing_result['token_id']}")

            # 2. Chercher un token valide 
            self.cursor.execute("""
                WITH FirstStep AS (
                    SELECT result_step_id
                    FROM quiz_result
                    WHERE quiz_id = %s
                    AND is_active = TRUE
                    AND result_step_ranking = 1
                    LIMIT 1
                ),
                LatestResult AS (
                    SELECT ru.token_id, MAX(ru.created_at) as last_created_at
                    FROM result_user ru
                    WHERE ru.quiz_id = %s 
                    AND ru.user_id = %s
                    AND ru.is_active = TRUE
                    GROUP BY ru.token_id
                )
                SELECT t.token_code
                FROM tokens t
                LEFT JOIN LatestResult lr ON t.token_code = lr.token_id
                CROSS JOIN FirstStep fs
                WHERE t.user_id = %s 
                AND t.quiz_id = %s
                AND (
                    -- Si c'est la première étape, le token ne doit pas être utilisé du tout
                    (
                        %s = fs.result_step_id 
                        AND t.is_used = FALSE
                    )
                    OR
                    -- Si ce n'est pas la première étape, le token doit avoir été utilisé pour la première étape
                    (
                        %s != fs.result_step_id
                        AND EXISTS (
                            SELECT 1
                            FROM result_user ru
                            WHERE ru.token_id = t.token_code
                            AND ru.result_step_id = fs.result_step_id
                            AND ru.is_active = TRUE
                        )
                    )
                )
                AND (t.expiration_date IS NULL OR t.expiration_date > NOW())
                AND NOT EXISTS (
                    SELECT 1
                    FROM result_user ru 
                    WHERE ru.token_id = t.token_code
                    AND ru.result_step_id = %s
                    AND ru.created_at >= COALESCE(lr.last_created_at, '1900-01-01')
                    AND ru.is_active = TRUE
                )
                ORDER BY t.created_at DESC
                LIMIT 1
                FOR UPDATE
            """, (self.quiz_id, self.quiz_id, self.user_id, self.user_id, self.quiz_id, step_id, step_id, step_id))
            
            token = self.cursor.fetchone()
            
            if not token:
                self.cursor.connection.rollback()  # Rollback avant de raise
                logger.error("No valid unused token found for this step")
                raise ValueError("No valid token found")
            
            token_code = token[0] if not isinstance(token, dict) else token['token_code']
            logger.info(f"Selected valid unused token: {token_code}")
            
            # Valider la transaction
            self.cursor.connection.commit()
            return token_code

        except Exception as e:
            # Annuler la transaction en cas d'erreur
            self.cursor.connection.rollback()
            logger.error(f"Error validating token: {str(e)}")
            raise

    def mark_token_as_used(self, token_code: str) -> None:
        """
        Marque un token comme utilisé.
        
        Args:
            token_code (str): Le code du token à marquer comme utilisé
        """
        try:
            # Débuter une transaction explicite
            self.cursor.connection.begin()
            
            self.cursor.execute("""
                SELECT is_used, used_at
                FROM tokens
                WHERE token_code = %s 
                AND user_id = %s
                AND quiz_id = %s
                FOR UPDATE  # Ajout d'un verrou
            """, (token_code, self.user_id, self.quiz_id))
            
            token_status = self.cursor.fetchone()
            if not token_status:
                logger.error(f"Token {token_code} not found")
                self.cursor.connection.rollback()
                return
                    
            if token_status['is_used']:
                logger.warning(f"Token {token_code} already marked as used at {token_status['used_at']}")
                self.cursor.connection.rollback()
                return

            self.cursor.execute("""
                UPDATE tokens 
                SET is_used = TRUE,
                    used_at = CURRENT_TIMESTAMP
                WHERE token_code = %s 
                AND user_id = %s
                AND quiz_id = %s
                AND NOT is_used
            """, (token_code, self.user_id, self.quiz_id))
            
            # Commit si tout s'est bien passé
            self.cursor.connection.commit()
            logger.info(f"Token {token_code} marked as used successfully")

        except Exception as e:
            # Rollback en cas d'erreur
            self.cursor.connection.rollback()
            logger.error(f"Error marking token as used: {str(e)}", exc_info=True)
            raise

    def get_remaining_steps(self, token_code: str) -> list:
        """
        Retourne la liste des étapes restantes à générer pour un token.
        
        Args:
            token_code (str): Le code du token
            
        Returns:
            list: Liste des step_id restants à générer
        """
        try:
            # 1. Récupérer toutes les étapes configurées
            self.cursor.execute("""
                SELECT result_step_id, result_step_ranking
                FROM quiz_result
                WHERE quiz_id = %s 
                AND is_active = TRUE
                ORDER BY result_step_ranking
            """, (self.quiz_id,))
            
            configured_steps = {step['result_step_id']: step['result_step_ranking'] 
                              for step in self.cursor.fetchall()}

            # 2. Récupérer les étapes déjà générées avec ce token
            self.cursor.execute("""
                SELECT DISTINCT result_step_id
                FROM result_user
                WHERE token_id = %s
                AND is_active = TRUE
            """, (token_code,))
            
            completed_steps = {step['result_step_id'] for step in self.cursor.fetchall()}

            # 3. Calculer les étapes restantes
            remaining_steps = []
            for step_id, ranking in configured_steps.items():
                if step_id not in completed_steps:
                    remaining_steps.append({
                        'step_id': step_id,
                        'ranking': ranking
                    })

            return sorted(remaining_steps, key=lambda x: x['ranking'])

        except Exception as e:
            logger.error(f"Error getting remaining steps: {str(e)}", exc_info=True)
            raise

    # ===== Gestion du quiz =====
    def update_quiz_status(self, status: str = 'completed') -> None:
        """Met à jour le statut du quiz."""
        try:
            self.cursor.execute("""
                UPDATE quiz_user 
                SET quiz_status = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE quiz_id = %s AND user_id = %s
            """, (status, self.quiz_id, self.user_id))
        except Exception as e:
            logger.error(f"Error updating quiz status: {str(e)}", exc_info=True)
            raise

     # ===== Préparation des données =====       
    def _prepare_prompt_data(self, step_id: str, prompt_instruction: str, 
                           prompt_knowledge: str) -> PromptData:
        """Prépare les données du prompt de manière structurée avec anonymisation des réponses uniquement."""
        try:
            # Récupérer les réponses utilisateur
            user_responses = self.prepare_prompt_data()
            
            # Récupérer le prompt système
            system_prompt = self._get_system_prompt(step_id)
            
            # Construire le human prompt original
            human_prompt = self._build_human_prompt(
                prompt_data=user_responses,
                prompt_instruction=prompt_instruction,
                prompt_knowledge=prompt_knowledge
            )

            # Récupérer le request_id pour la traçabilité
            request_id = getattr(g, 'request_id', None)
            
            # Anonymiser UNIQUEMENT les réponses des utilisateurs, pas les questions
            anonymized_responses = []
            for item in user_responses:
                anonymized_responses.append({
                    "question": item["question"],  # Ne pas anonymiser la question
                    "answer": self.anonymizer.anonymize_text(item["answer"], request_id)  # Anonymiser uniquement la réponse
                })
            
            # Construire le human prompt anonymisé sans anonymiser les instructions ou connaissances supplémentaires
            anonymized_human_prompt = self._build_human_prompt(
                prompt_data=anonymized_responses,
                prompt_instruction=prompt_instruction,  # Ne pas anonymiser
                prompt_knowledge=prompt_knowledge  # Ne pas anonymiser
            )

            # Préparer les métadonnées de session
            session_data = {
                "quiz_id": self.quiz_id,
                "user_id": self.user_id
            }

            # Créer l'objet PromptData avec la bonne signature
            return PromptData(
                human_prompt=human_prompt,
                system_prompt=system_prompt,
                anonymized_human_prompt=anonymized_human_prompt,
                session_data=session_data
            )

        except Exception as e:
            logger.error(f"Error preparing prompt data: {str(e)}")
            raise

    # ===== Préparation des données =====
    def prepare_prompt_data(self) -> List[Dict]:
        """Prépare les données avec une SEULE requête optimisée."""
        
        start = time.time()
        
        try:
            # 1. Récupérer session
            self.cursor.execute("""
                SELECT quiz_session_id 
                FROM quiz_user 
                WHERE user_id = %s AND quiz_id = %s 
                ORDER BY updated_at DESC 
                LIMIT 1
            """, (self.user_id, self.quiz_id))
            
            session_result = self.cursor.fetchone()
            if not session_result:
                raise ValueError("No quiz session found")

            quiz_session_id = session_result['quiz_session_id']
            
            logger.info(f"⏱️ Get session: {time.time() - start:.3f}s")
            step_start = time.time()

            # 2. UNE SEULE requête pour TOUT récupérer
            self.cursor.execute("""
                SELECT 
                    q.question_id,
                    q.question,
                    q.question_type,
                    au.answer_value,
                    au.answer_text,
                    qq.question_ranking,
                    qc.choices,
                    qc.choice_descriptions,
                    at.transcription,
                    at.confidence_score
                FROM questions_catalog q
                JOIN quiz_questions qq ON q.question_id = qq.question_id
                LEFT JOIN answer_user au ON au.question_id = q.question_id 
                    AND au.quiz_session_id = %s
                LEFT JOIN (
                    SELECT 
                        question_id,
                        JSON_ARRAYAGG(JSON_OBJECT('value', choice_value, 'text', choice_text)) as choices,
                        JSON_ARRAYAGG(choice_description) as choice_descriptions
                    FROM questions_choices
                    GROUP BY question_id
                ) qc ON q.question_id = qc.question_id
                LEFT JOIN audio_transcriptions at ON (
                    at.quiz_session_id = %s
                    AND at.question_id = q.question_id
                    AND at.transcription_status = 'completed'
                )
                WHERE qq.quiz_id = %s
                AND qq.is_active = TRUE
                AND (au.answer_text IS NOT NULL AND au.answer_text != '')
                ORDER BY qq.question_ranking
            """, (quiz_session_id, quiz_session_id, self.quiz_id))

            questions_data = self.cursor.fetchall()
            
            logger.info(f"⏱️ Fetch questions: {time.time() - step_start:.3f}s ({len(questions_data)} questions)")
            
            prompt_data = []
            for q_data in questions_data:
                # Construire le texte de la question
                question_full_text = f"{q_data['question_ranking']}. Question : {q_data['question']}"

                # Ajouter les choix si disponibles
                #if q_data['choices']:
                #    choices = json.loads(q_data['choices'])
                #    descriptions = json.loads(q_data['choice_descriptions'])
                #    
                #    choices_text = "\nChoix :\n"
                #    for choice, description in zip(choices, descriptions):
                #        choice_line = f"● {choice['text']}"
                #        if description:
                #            choice_line += f" – « {description} »"
                #        choices_text += choice_line + "\n"
                #    
                #    question_full_text += choices_text

                # Formater la réponse
                answer_values = []
                if q_data['answer_value']:
                    answer_values = json.loads(q_data['answer_value'])
                    if not isinstance(answer_values, list):
                        answer_values = [answer_values]

                # Détecter si c'est une réponse audio
                is_audio_response = (
                    isinstance(answer_values, list) 
                    and len(answer_values) > 0 
                    and answer_values[0] == '[AUDIO_RESPONSE]'
                )

                # Construire le texte de la réponse
                answer_text_raw = q_data['answer_text'] or ''

                # Detect conversation mode (from dynamic coach)
                is_conversation = '[Claire]' in answer_text_raw and '[Réponse]' in answer_text_raw

                if is_conversation:
                    # Format conversation transcript for the analysis prompt
                    answer_full_text = f"Transcription de l'entretien de coaching :\n{answer_text_raw}"
                    # Use conversation as a single prompt block, skip the DB question text
                    prompt_data.append({
                        "question": "Entretien de coaching vocal (conversation complète)",
                        "answer": answer_full_text
                    })
                    # Skip remaining questions — the conversation covers everything
                    break
                elif is_audio_response and q_data['transcription']:
                    answer_full_text = f"Réponse : {q_data['transcription']}"
                    if q_data['confidence_score']:
                        answer_full_text += f" [Transcription audio, confiance: {q_data['confidence_score']:.2%}]"
                elif is_audio_response:
                    answer_full_text = "Réponse : [Réponse audio non transcrite]"
                    logger.warning(f"Question {q_data['question_id']} a une réponse audio sans transcription")
                else:
                    answer_full_text = f"Réponse : {answer_text_raw}"

                    # Ajouter les descriptions des choix sélectionnés
                    if q_data['choice_descriptions'] and answer_values:
                        descriptions = json.loads(q_data['choice_descriptions'])
                        choices = json.loads(q_data['choices'])
                        for value in answer_values:
                            for choice, desc in zip(choices, descriptions):
                                if str(choice['value']) == str(value) and desc:
                                    answer_full_text += f" – « {desc} »"
                                    break

                if not is_conversation:
                    prompt_data.append({
                        "question": question_full_text,
                        "answer": answer_full_text
                    })

            return prompt_data

        except Exception as e:
            logger.error(f"Error preparing prompt data: {str(e)}", exc_info=True)
            raise

    # ===== Traitement des réponses =====
    def _validate_vision_360_response(self, result_json: Dict, request_id: str) -> Dict:
        """Validation spécifique pour le format vision_360."""
        default_superpower_card = {
            "emoji": "",
            "superpower_title": "",
            "tags_intro": "Pourquoi cette recommandation :",
            "tags": {"tag": ["", ""]}
        }
        
        default_detail_card = {
            "emoji": "",
            "title": "",
            "description": "",
            "did_you_know": {
                "title": "Le savais-tu ?",
                "content": "",
            },
            "action_steps": {
                "emoji": "🎯",
                "action_steps_intro": "",
                "steps": ["", "", ""]
            }
        }

        final_json = {"superpowers": []}
        
        if isinstance(result_json, dict) and 'superpowers' in result_json:
            for i, power in enumerate(result_json['superpowers'], 1):
                valid_power = {
                    'id': str(i),
                    'superpower_card': {**default_superpower_card, **(power.get('superpower_card', {}))},
                    'detail_card': {**default_detail_card, **(power.get('detail_card', {}))}
                }
                
                if (valid_power['superpower_card']['superpower_title'] or 
                    valid_power['detail_card']['title'] or 
                    valid_power['detail_card']['description']):
                    final_json['superpowers'].append(valid_power)
            
            logger.info(f"[Request ID: {request_id}] Found {len(final_json['superpowers'])} valid superpowers")
        else:
            logger.error(f"[Request ID: {request_id}] Invalid JSON structure")
        
        return final_json

    def _process_vision_360_response(self, response_str: str, request_id: str) -> Dict:
        """Traitement spécifique pour l'analyse vision_360."""
        try:
            # Dénonymiser la réponse si elle contient des marqueurs anonymisés
            response_str = self.denonymize_claude_response(response_str, request_id)
            
            json_start = response_str.find('{')
            json_end = response_str.rfind('}') + 1
            
            if json_start == -1 or json_end == -1:
                logger.warning(f"[Request ID: {request_id}] No JSON found in vision_360 response")
                return {"superpowers": []}

            json_str = response_str[json_start:json_end]
            result_json = json.loads(json_str)
            
            return self._validate_vision_360_response(result_json, request_id)
            
        except json.JSONDecodeError as e:
            logger.error(f"[Request ID: {request_id}] JSON parsing error in vision_360: {str(e)}")
            return {"superpowers": []}

    def _process_checkup_response(self, response_str: str, request_id: str) -> Dict:
        """Traitement spécifique pour l'analyse checkup."""
        try:
            # Dénonymiser la réponse si elle contient des marqueurs anonymisés
            response_str = self.denonymize_claude_response(response_str, request_id)
            
            json_start = response_str.find('{')
            json_end = response_str.rfind('}') + 1
            
            if json_start == -1 or json_end == -1:
                logger.warning(f"[Request ID: {request_id}] No JSON found in checkup response")
                return {"blocks": []}

            json_str = response_str[json_start:json_end]
            result_json = json.loads(json_str)
            
            # Validation de la structure
            if not isinstance(result_json, dict) or 'blocks' not in result_json:
                logger.error(f"[Request ID: {request_id}] Invalid JSON structure in checkup response")
                return {"blocks": []}
                
            # Vérification et nettoyage des blocs
            validated_blocks = []
            for block in result_json.get('blocks', []):
                if not isinstance(block, dict) or 'content' not in block:
                    continue
                    
                # Validation spécifique selon le type de bloc
                if block.get('id') == 'initialBlock':
                    # Validation du bloc initial
                    if 'levelInfo' not in block['content']:
                        continue
                
                validated_blocks.append(block)
                
            return {"blocks": validated_blocks}
                
        except json.JSONDecodeError as e:
            logger.error(f"[Request ID: {request_id}] JSON parsing error in checkup: {str(e)}")
            return {"blocks": []}

    def _process_career_path_response(self, response_str: str, request_id: str, step_id: str = None) -> Dict:
        """
        Traitement pour l'analyse career_path avec routage automatique vers la bonne version.
        
        Versions supportées:
        - career_path: V0 legacy (welcome, strategies, actions)
        - career_path_v1: Cécile (avec atouts, transformations negative/positive)
        - career_path_v2: Nelly (avec options, transformations before/after, sans atouts)
        - career_path_v3
        - 'career_path_v4'
        """
        try:
            # Dénonymiser d'abord
            response_str = self.denonymize_claude_response(response_str, request_id)
            
            # ========================================
            # ÉTAPE 1 : NETTOYAGE ET EXTRACTION DU JSON
            # ========================================
            try:
                json_str_cleaned = self._sanitize_json_string(response_str)
            except ValueError as e:
                error_msg = str(e)
                logger.error(f"[{request_id}] {error_msg}")
                
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': step_id,
                            'request_id': request_id,
                            'error_type': 'no_json_structure',
                            'error_message': error_msg,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(error_msg)
            
            # ========================================
            # ÉTAPE 2 : PARSING JSON
            # ========================================
            try:
                result_json = json.loads(json_str_cleaned)
                logger.info(f"[{request_id}] ✅ JSON parsed successfully")
                
            except json.JSONDecodeError as e:
                error_position = e.pos
                context_start = max(0, error_position - 100)
                context_end = min(len(json_str_cleaned), error_position + 100)
                context = json_str_cleaned[context_start:context_end]
                
                logger.error(f"[{request_id}] JSON error at pos {error_position}: {e.msg}")
                logger.error(f"[{request_id}] Context: ...{context}...")
                
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'request_id': request_id,
                            'error_position': error_position,
                            'error_message': e.msg,
                            'context': context,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_json_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(f"Invalid JSON from LLM: {e.msg}")
            
            # ========================================
            # ÉTAPE 3 : ROUTAGE VERS LA BONNE VERSION
            # ========================================
            try:
                if step_id == 'career_path_v2':
                    # V2 - Template Nelly
                    validated_json = self._validate_career_path_v2_response(result_json, request_id)

                elif step_id == 'career_path_v3':
                    # V3 - Template Nelly
                    validated_json = self._validate_career_path_v3_response(result_json, request_id)
                    
                elif step_id == 'career_path_v1':
                    # V1 - Template Cécile
                    validated_json = self._validate_career_path_v1_response(result_json, request_id)
                    
                else:
                    # V0 - Legacy (career_path)
                    validated_json = self._validate_career_path_response(result_json, request_id)
                    
            except ValueError as e:
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': step_id,
                            'request_id': request_id,
                            'error_type': 'structure_validation',
                            'error_message': str(e),
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise
            
            logger.info(f"[{request_id}] ✅ Career path response processed successfully (step: {step_id})")
            return validated_json
            
        except ValueError:
            raise
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unexpected error: {str(e)}", exc_info=True)
            
            if self.slack_available and self.slack_service:
                try:
                    slack_data = {
                        'user_id': self.user_id,
                        'quiz_id': self.quiz_id,
                        'step_id': step_id,
                        'request_id': request_id,
                        'error_type': 'unexpected_error',
                        'error_message': f"{type(e).__name__}: {str(e)}",
                        'generator_type': getattr(self, 'generator_type', 'user')
                    }
                    self.slack_service.notify_validation_error(slack_data)
                except Exception as slack_error:
                    logger.error(f"[{request_id}] Slack error: {slack_error}")
            
            raise ValueError(f"Failed to process career_path response: {str(e)}")

    def _process_career_path_v2_response(self, response_str: str, request_id: str) -> Dict:
        """
        Traitement spécifique pour l'analyse career_path V2 (template Nelly).
        """
        try:
            # Dénonymiser d'abord
            response_str = self.denonymize_claude_response(response_str, request_id)
            
            # ========================================
            # ÉTAPE 1 : NETTOYAGE ET EXTRACTION DU JSON
            # ========================================
            try:
                json_str_cleaned = self._sanitize_json_string(response_str)
            except ValueError as e:
                error_msg = str(e)
                logger.error(f"[Request ID: {request_id}] {error_msg}")
                
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': 'career_path_v2',
                            'request_id': request_id,
                            'error_type': 'no_json_structure',
                            'error_message': error_msg,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(error_msg)
            
            # ========================================
            # ÉTAPE 2 : PARSING JSON
            # ========================================
            try:
                result_json = json.loads(json_str_cleaned)
                logger.info(f"[{request_id}] ✅ JSON V2 parsed successfully")
                
            except json.JSONDecodeError as e:
                error_position = e.pos
                context_start = max(0, error_position - 100)
                context_end = min(len(json_str_cleaned), error_position + 100)
                context = json_str_cleaned[context_start:context_end]
                
                logger.error(f"[{request_id}] JSON error at pos {error_position}: {e.msg}")
                logger.error(f"[{request_id}] Context: ...{context}...")
                
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'request_id': request_id,
                            'error_position': error_position,
                            'error_message': e.msg,
                            'context': context,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_json_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(f"Invalid JSON from LLM: {e.msg}")
            
            # ========================================
            # ÉTAPE 3 : VALIDATION DE LA STRUCTURE V2
            # ========================================
            try:
                validated_json = self._validate_career_path_v2_response(result_json, request_id)
            except ValueError as e:
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': 'career_path_v2',
                            'request_id': request_id,
                            'error_type': 'structure_validation',
                            'error_message': str(e),
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise
            
            logger.info(f"[{request_id}] ✅ Career path V2 response processed successfully")
            return validated_json
            
        except ValueError:
            raise
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unexpected error: {str(e)}", exc_info=True)
            
            if self.slack_available and self.slack_service:
                try:
                    slack_data = {
                        'user_id': self.user_id,
                        'quiz_id': self.quiz_id,
                        'step_id': 'career_path_v2',
                        'request_id': request_id,
                        'error_type': 'unexpected_error',
                        'error_message': f"{type(e).__name__}: {str(e)}",
                        'generator_type': getattr(self, 'generator_type', 'user')
                    }
                    self.slack_service.notify_validation_error(slack_data)
                except Exception as slack_error:
                    logger.error(f"[{request_id}] Slack error: {slack_error}")
            
            raise ValueError(f"Failed to process career_path V2 response: {str(e)}")

    def _process_career_path_v3_response(self, response_str: str, request_id: str) -> Dict:
        """
        Traitement spécifique pour l'analyse career_path V2 (template Nelly).
        """
        try:
            # Dénonymiser d'abord
            response_str = self.denonymize_claude_response(response_str, request_id)
            
            # ========================================
            # ÉTAPE 1 : NETTOYAGE ET EXTRACTION DU JSON
            # ========================================
            try:
                json_str_cleaned = self._sanitize_json_string(response_str)
            except ValueError as e:
                error_msg = str(e)
                logger.error(f"[Request ID: {request_id}] {error_msg}")
                
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': 'career_path_v3',
                            'request_id': request_id,
                            'error_type': 'no_json_structure',
                            'error_message': error_msg,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(error_msg)
            
            # ========================================
            # ÉTAPE 2 : PARSING JSON
            # ========================================
            try:
                result_json = json.loads(json_str_cleaned)
                logger.info(f"[{request_id}] ✅ JSON V3 parsed successfully")
                
            except json.JSONDecodeError as e:
                error_position = e.pos
                context_start = max(0, error_position - 100)
                context_end = min(len(json_str_cleaned), error_position + 100)
                context = json_str_cleaned[context_start:context_end]
                
                logger.error(f"[{request_id}] JSON error at pos {error_position}: {e.msg}")
                logger.error(f"[{request_id}] Context: ...{context}...")
                
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'request_id': request_id,
                            'error_position': error_position,
                            'error_message': e.msg,
                            'context': context,
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_json_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise ValueError(f"Invalid JSON from LLM: {e.msg}")
            
            # ========================================
            # ÉTAPE 3 : VALIDATION DE LA STRUCTURE V3
            # ========================================
            try:
                validated_json = self._validate_career_path_v3_response(result_json, request_id)
            except ValueError as e:
                # Notification Slack
                if self.slack_available and self.slack_service:
                    try:
                        slack_data = {
                            'user_id': self.user_id,
                            'quiz_id': self.quiz_id,
                            'step_id': 'career_path_v3',
                            'request_id': request_id,
                            'error_type': 'structure_validation',
                            'error_message': str(e),
                            'generator_type': getattr(self, 'generator_type', 'user')
                        }
                        self.slack_service.notify_validation_error(slack_data)
                    except Exception as slack_error:
                        logger.error(f"[{request_id}] Slack error: {slack_error}")
                
                raise
            
            logger.info(f"[{request_id}] ✅ Career path V2 response processed successfully")
            return validated_json
            
        except ValueError:
            raise
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Unexpected error: {str(e)}", exc_info=True)
            
            if self.slack_available and self.slack_service:
                try:
                    slack_data = {
                        'user_id': self.user_id,
                        'quiz_id': self.quiz_id,
                        'step_id': 'career_path_v3',
                        'request_id': request_id,
                        'error_type': 'unexpected_error',
                        'error_message': f"{type(e).__name__}: {str(e)}",
                        'generator_type': getattr(self, 'generator_type', 'user')
                    }
                    self.slack_service.notify_validation_error(slack_data)
                except Exception as slack_error:
                    logger.error(f"[{request_id}] Slack error: {slack_error}")
            
            raise ValueError(f"Failed to process career_path V3 response: {str(e)}")

    def _validate_career_path_response(self, result_json: Dict, request_id: str) -> Dict:
        """Validation stricte pour le format career_path avec erreurs explicites."""
        
        if not isinstance(result_json, dict):
            error_msg = f"Invalid JSON structure: not a dict"
            logger.error(f"[Request ID: {request_id}] {error_msg}")
            raise ValueError(error_msg)
        
        # Vérifier les clés obligatoires de premier niveau
        required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
        for key in required_keys:
            if key not in result_json:
                error_msg = f"Missing required top-level key: {key}"
                logger.error(f"[Request ID: {request_id}] {error_msg}")
                raise ValueError(error_msg)
        
        # ============================================================
        # VALIDATION WELCOME (obligatoire et non vide)
        # ============================================================
        welcome = result_json['welcome']
        if not isinstance(welcome, dict):
            raise ValueError(f"[{request_id}] 'welcome' must be a dict")
        
        if 'content' not in welcome or not welcome['content'] or not welcome['content'].strip():
            raise ValueError(f"[{request_id}] 'welcome.content' is required and cannot be empty")
        
        # ============================================================
        # VALIDATION STARTING_POINT
        # ============================================================
        sp = result_json['starting_point']
        if not isinstance(sp, dict):
            raise ValueError(f"[{request_id}] 'starting_point' must be a dict")
        
        # user_quote obligatoire et non vide
        if 'user_quote' not in sp or not sp['user_quote'] or not sp['user_quote'].strip():
            raise ValueError(f"[{request_id}] 'starting_point.user_quote' is required and cannot be empty")
        
        # transformations obligatoire, doit être une liste avec au moins 1 élément
        if 'transformations' not in sp:
            raise ValueError(f"[{request_id}] 'starting_point.transformations' is required")
        if not isinstance(sp['transformations'], list):
            raise ValueError(f"[{request_id}] 'starting_point.transformations' must be a list")
        if len(sp['transformations']) == 0:
            raise ValueError(f"[{request_id}] 'starting_point.transformations' must contain at least 1 transformation")
        
        # Valider chaque transformation
        for idx, trans in enumerate(sp['transformations']):
            if not isinstance(trans, dict):
                raise ValueError(f"[{request_id}] 'starting_point.transformations[{idx}]' must be a dict")
            if 'before_text' not in trans or not trans['before_text'].strip():
                raise ValueError(f"[{request_id}] 'starting_point.transformations[{idx}].before_text' is required")
            if 'after_text' not in trans or not trans['after_text'].strip():
                raise ValueError(f"[{request_id}] 'starting_point.transformations[{idx}].after_text' is required")
        
        # key_insight obligatoire et non vide
        if 'key_insight' not in sp or not sp['key_insight'] or not sp['key_insight'].strip():
            raise ValueError(f"[{request_id}] 'starting_point.key_insight' is required and cannot be empty")
        
        # strengths obligatoire, doit être une liste avec au moins 1 élément
        if 'strengths' not in sp:
            raise ValueError(f"[{request_id}] 'starting_point.strengths' is required")
        if not isinstance(sp['strengths'], list):
            raise ValueError(f"[{request_id}] 'starting_point.strengths' must be a list")
        if len(sp['strengths']) == 0:
            raise ValueError(f"[{request_id}] 'starting_point.strengths' must contain at least 1 strength")
        
        # Valider chaque strength
        for idx, strength in enumerate(sp['strengths']):
            if not isinstance(strength, dict):
                raise ValueError(f"[{request_id}] 'starting_point.strengths[{idx}]' must be a dict")
            if 'title' not in strength or not strength['title'].strip():
                raise ValueError(f"[{request_id}] 'starting_point.strengths[{idx}].title' is required")
            if 'description' not in strength or not strength['description'].strip():
                raise ValueError(f"[{request_id}] 'starting_point.strengths[{idx}].description' is required")
        
        # ============================================================
        # VALIDATION STRATEGIES
        # ============================================================
        strat = result_json['strategies']
        if not isinstance(strat, dict):
            raise ValueError(f"[{request_id}] 'strategies' must be a dict")
        
        # title obligatoire
        if 'title' not in strat or not strat['title'].strip():
            raise ValueError(f"[{request_id}] 'strategies.title' is required and cannot be empty")
        
        # subtitle obligatoire
        if 'subtitle' not in strat or not strat['subtitle'].strip():
            raise ValueError(f"[{request_id}] 'strategies.subtitle' is required and cannot be empty")
        
        # honesty_message obligatoire
        if 'honesty_message' not in strat or not strat['honesty_message'].strip():
            raise ValueError(f"[{request_id}] 'strategies.honesty_message' is required and cannot be empty")
        
        # items obligatoire, doit contenir exactement 3 stratégies
        if 'items' not in strat:
            raise ValueError(f"[{request_id}] 'strategies.items' is required")
        if not isinstance(strat['items'], list):
            raise ValueError(f"[{request_id}] 'strategies.items' must be a list")
        if len(strat['items']) != 3:
            raise ValueError(f"[{request_id}] 'strategies.items' must contain exactly 3 strategies, got {len(strat['items'])}")
        
        # Valider chaque stratégie
        for idx, strategy in enumerate(strat['items']):
            if not isinstance(strategy, dict):
                raise ValueError(f"[{request_id}] 'strategies.items[{idx}]' must be a dict")
            
            # Champs obligatoires d'une stratégie
            required_strategy_fields = [
                'badge_text', 'title', 'subtitle', 'access_type', 
                'preview_items', 'duration', 'salary', 'realism', 
                'detail_content', 'unlock_source'
            ]
            for field in required_strategy_fields:
                if field not in strategy:
                    raise ValueError(f"[{request_id}] 'strategies.items[{idx}].{field}' is required")
                
                # Vérifier que les strings ne sont pas vides
                if isinstance(strategy[field], str) and not strategy[field].strip():
                    raise ValueError(f"[{request_id}] 'strategies.items[{idx}].{field}' cannot be empty")
            
            # access_type doit être 'free' ou 'premium'
            if strategy['access_type'] not in ['free', 'premium']:
                raise ValueError(f"[{request_id}] 'strategies.items[{idx}].access_type' must be 'free' or 'premium'")
            
            # preview_items doit être une liste non vide
            if not isinstance(strategy['preview_items'], list) or len(strategy['preview_items']) == 0:
                raise ValueError(f"[{request_id}] 'strategies.items[{idx}].preview_items' must be a non-empty list")
        
        # ============================================================
        # VALIDATION ACTIONS
        # ============================================================
        act = result_json['actions']
        if not isinstance(act, dict):
            raise ValueError(f"[{request_id}] 'actions' must be a dict")
        
        # subtitle obligatoire
        if 'subtitle' not in act or not act['subtitle'].strip():
            raise ValueError(f"[{request_id}] 'actions.subtitle' is required and cannot be empty")
        
        # strengths_recap obligatoire, liste avec au moins 1 élément
        if 'strengths_recap' not in act:
            raise ValueError(f"[{request_id}] 'actions.strengths_recap' is required")
        if not isinstance(act['strengths_recap'], list):
            raise ValueError(f"[{request_id}] 'actions.strengths_recap' must be a list")
        if len(act['strengths_recap']) == 0:
            raise ValueError(f"[{request_id}] 'actions.strengths_recap' must contain at least 1 strength")
        
        # Valider chaque strength recap
        for idx, strength in enumerate(act['strengths_recap']):
            if not isinstance(strength, dict):
                raise ValueError(f"[{request_id}] 'actions.strengths_recap[{idx}]' must be a dict")
            if 'title' not in strength or not strength['title'].strip():
                raise ValueError(f"[{request_id}] 'actions.strengths_recap[{idx}].title' is required")
            if 'description' not in strength or not strength['description'].strip():
                raise ValueError(f"[{request_id}] 'actions.strengths_recap[{idx}].description' is required")
        
        # items obligatoire, doit contenir exactement 3 actions
        if 'items' not in act:
            raise ValueError(f"[{request_id}] 'actions.items' is required")
        if not isinstance(act['items'], list):
            raise ValueError(f"[{request_id}] 'actions.items' must be a list")
        if len(act['items']) != 3:
            raise ValueError(f"[{request_id}] 'actions.items' must contain exactly 3 actions, got {len(act['items'])}")
        
        # Valider chaque action
        for idx, action in enumerate(act['items']):
            if not isinstance(action, dict):
                raise ValueError(f"[{request_id}] 'actions.items[{idx}]' must be a dict")
            
            # Champs obligatoires d'une action
            required_action_fields = [
                'badge_text', 'icon', 'title', 'subtitle', 
                'access_type', 'preview_text', 'detail_content', 'unlock_source'
            ]
            for field in required_action_fields:
                if field not in action:
                    raise ValueError(f"[{request_id}] 'actions.items[{idx}].{field}' is required")
                
                # Vérifier que les strings ne sont pas vides
                if isinstance(action[field], str) and not action[field].strip():
                    raise ValueError(f"[{request_id}] 'actions.items[{idx}].{field}' cannot be empty")
            
            # access_type doit être 'free' ou 'premium'
            if action['access_type'] not in ['free', 'premium']:
                if action['access_type'] == 'locked':
                    action['access_type'] = 'premium'
                    logger.warning(f"[{request_id}] Normalized 'locked' to 'premium' for actions.items[{idx}]")
                else:
                    raise ValueError(f"[{request_id}] 'actions.items[{idx}].access_type' must be 'free' or 'premium', got '{action['access_type']}'")
        
        logger.info(f"[Request ID: {request_id}] ✅ Career path structure validated successfully")
        return result_json

    def _validate_career_path_v1_response(self, result_json: Dict, request_id: str) -> Dict:
        """
        Validation stricte pour le nouveau format career_path V2.
        Structure selon example_json_to_fill_V1.json
        """
        
        if not isinstance(result_json, dict):
            raise ValueError(f"[{request_id}] Invalid JSON: not a dict")
        
        # ============================================================
        # CLÉS OBLIGATOIRES DE PREMIER NIVEAU
        # ============================================================
        required_keys = [
            'cover_quote', 'hero_intro', 'main_user_quote',
            'citation_insight', 'transformations_count', 'transformations',
            'transformations_recap', 'atouts_count', 'atouts', 'atouts_recap',
            'voies', 'finale_user_quote', 'finale_gender_pronoun'
        ]
        
        for key in required_keys:
            if key not in result_json:
                raise ValueError(f"[{request_id}] Missing required key: '{key}'")
        
        # ============================================================
        # VALIDATION TRANSFORMATIONS
        # ============================================================
        if not isinstance(result_json['transformations'], list):
            raise ValueError(f"[{request_id}] 'transformations' must be a list")
        
        if len(result_json['transformations']) != result_json['transformations_count']:
            raise ValueError(
                f"[{request_id}] transformations_count={result_json['transformations_count']} "
                f"but got {len(result_json['transformations'])} transformations"
            )
        
        for idx, trans in enumerate(result_json['transformations']):
            if not isinstance(trans, dict):
                raise ValueError(f"[{request_id}] transformations[{idx}] must be a dict")
            
            if 'negative' not in trans or not trans['negative'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].negative is required")
            
            if 'positive' not in trans or not trans['positive'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].positive is required")
        
        # ============================================================
        # VALIDATION ATOUTS
        # ============================================================
        if not isinstance(result_json['atouts'], list):
            raise ValueError(f"[{request_id}] 'atouts' must be a list")
        
        if len(result_json['atouts']) != result_json['atouts_count']:
            raise ValueError(
                f"[{request_id}] atouts_count={result_json['atouts_count']} "
                f"but got {len(result_json['atouts'])} atouts"
            )
        
        for idx, atout in enumerate(result_json['atouts']):
            if not isinstance(atout, dict):
                raise ValueError(f"[{request_id}] atouts[{idx}] must be a dict")
            
            required_atout_fields = [
                'icon', 'title', 'description', 'details',
                'pitch_formula', 'pitch_example', 'pitch_avoid'
            ]
            
            for field in required_atout_fields:
                if field not in atout:
                    raise ValueError(f"[{request_id}] atouts[{idx}].{field} is required")
            
            # details doit être une liste
            if not isinstance(atout['details'], list):
                raise ValueError(f"[{request_id}] atouts[{idx}].details must be a list")
        
        # ============================================================
        # VALIDATION VOIES
        # ============================================================
        if not isinstance(result_json['voies'], list):
            raise ValueError(f"[{request_id}] 'voies' must be a list")
        
        if len(result_json['voies']) != 3:
            raise ValueError(
                f"[{request_id}] 'voies' must contain exactly 3 items, "
                f"got {len(result_json['voies'])}"
            )
        
        for idx, voie in enumerate(result_json['voies']):
            if not isinstance(voie, dict):
                raise ValueError(f"[{request_id}] voies[{idx}] must be a dict")
            
            required_voie_fields = [
                'color_class', 'icon', 'label', 'story', 'badge_text',
                'title', 'subtitle', 'projection', 'avantage_unique',
                'premiers_moves', 'insight', 'resume_reality',
                'avantages', 'defis', 'salaire', 'temps_credible', 'conseil'
            ]
            
            for field in required_voie_fields:
                if field not in voie:
                    raise ValueError(f"[{request_id}] voies[{idx}].{field} is required")
            
            # premiers_moves doit être une liste
            if not isinstance(voie['premiers_moves'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].premiers_moves must be a list")
            
            # avantages et defis doivent être des listes
            if not isinstance(voie['avantages'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].avantages must be a list")
            
            if not isinstance(voie['defis'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].defis must be a list")
        
        logger.info(f"[{request_id}] ✅ Career path V2 validated successfully")
        return result_json

    def _validate_career_path_v2_response(self, result_json: Dict, request_id: str) -> Dict:
        """
        Validation stricte pour le nouveau format career_path V2 (template Nelly).
        Structure selon le nouveau JSON avec options, voies simplifiées, etc.
        """
        
        if not isinstance(result_json, dict):
            raise ValueError(f"[{request_id}] Invalid JSON: not a dict")
        
        # ============================================================
        # CLÉS OBLIGATOIRES DE PREMIER NIVEAU
        # ============================================================
        required_keys = [
            'cover_quote', 'cover_date',
            'intro_text_bloc1', 'intro_text_bloc2',
            'section1_quote_verbatim', 'section1_tilto_comprend',
            'transformations_count', 'transformations', 'section2_tilto_comprend',
            'options', 'voies', 'finale_gender_pronoun'
        ]
        
        for key in required_keys:
            if key not in result_json:
                raise ValueError(f"[{request_id}] Missing required key: '{key}'")
        
        # ============================================================
        # VALIDATION STRINGS OBLIGATOIRES NON VIDES
        # ============================================================
        string_fields = [
            'cover_quote', 'cover_date',
            'intro_text_bloc1', 'intro_text_bloc2',
            'section1_quote_verbatim', 'section1_tilto_comprend',
            'section2_tilto_comprend', 'finale_gender_pronoun'
        ]
        
        for field in string_fields:
            if not isinstance(result_json[field], str) or not result_json[field].strip():
                raise ValueError(f"[{request_id}] '{field}' must be a non-empty string")
        
        # ============================================================
        # VALIDATION TRANSFORMATIONS
        # ============================================================
        if not isinstance(result_json['transformations'], list):
            raise ValueError(f"[{request_id}] 'transformations' must be a list")
        
        if len(result_json['transformations']) != result_json['transformations_count']:
            raise ValueError(
                f"[{request_id}] transformations_count={result_json['transformations_count']} "
                f"but got {len(result_json['transformations'])} transformations"
            )
        
        if len(result_json['transformations']) < 3:
            raise ValueError(f"[{request_id}] 'transformations' must have at least 3 items")
        
        for idx, trans in enumerate(result_json['transformations']):
            if not isinstance(trans, dict):
                raise ValueError(f"[{request_id}] transformations[{idx}] must be a dict")
            
            # ⚠️ V2 utilise 'before'/'after' (pas 'negative'/'positive')
            if 'before' not in trans or not trans['before'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].before is required")
            
            if 'after' not in trans or not trans['after'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].after is required")
        
        # ============================================================
        # VALIDATION OPTIONS (nouveau en V2)
        # ============================================================
        if not isinstance(result_json['options'], list):
            raise ValueError(f"[{request_id}] 'options' must be a list")
        
        if len(result_json['options']) != 3:
            raise ValueError(
                f"[{request_id}] 'options' must contain exactly 3 items, "
                f"got {len(result_json['options'])}"
            )
        
        for idx, option in enumerate(result_json['options']):
            if not isinstance(option, dict):
                raise ValueError(f"[{request_id}] options[{idx}] must be a dict")
            
            required_option_fields = ['number', 'icon', 'title', 'tags', 'why_match']  # ✅ AJOUTÉ why_match
            
            for field in required_option_fields:
                if field not in option:
                    raise ValueError(f"[{request_id}] options[{idx}].{field} is required")
            
            # Vérifier que number correspond à l'index + 1
            if option['number'] != idx + 1:
                raise ValueError(f"[{request_id}] options[{idx}].number should be {idx + 1}, got {option['number']}")
            
            # tags doit être une liste non vide
            if not isinstance(option['tags'], list) or len(option['tags']) == 0:
                raise ValueError(f"[{request_id}] options[{idx}].tags must be a non-empty list")
            
            # ✅ AJOUTÉ : why_match doit être une string non vide
            if not isinstance(option['why_match'], str) or not option['why_match'].strip():
                raise ValueError(f"[{request_id}] options[{idx}].why_match must be a non-empty string")
            
            # Vérifier que number correspond à l'index + 1
            if option['number'] != idx + 1:
                raise ValueError(f"[{request_id}] options[{idx}].number should be {idx + 1}, got {option['number']}")
            
            # tags doit être une liste non vide
            if not isinstance(option['tags'], list) or len(option['tags']) == 0:
                raise ValueError(f"[{request_id}] options[{idx}].tags must be a non-empty list")
        
        # ============================================================
        # VALIDATION VOIES (structure V2)
        # ============================================================
        if not isinstance(result_json['voies'], list):
            raise ValueError(f"[{request_id}] 'voies' must be a list")
        
        if len(result_json['voies']) != 3:
            raise ValueError(
                f"[{request_id}] 'voies' must contain exactly 3 items, "
                f"got {len(result_json['voies'])}"
            )
        
        valid_color_classes = ['option-1', 'option-2', 'option-3']
        
        for idx, voie in enumerate(result_json['voies']):
            if not isinstance(voie, dict):
                raise ValueError(f"[{request_id}] voies[{idx}] must be a dict")
            
            # Champs obligatoires V2
            required_voie_fields = [
                'number', 'color_class', 'icon', 'hero_title', 'quelques_mots',
                'avantage_unique', 'dire_quote', 'warning_text', 'warning_evite',
                'formations', 'cibles_employeurs', 'savais_tu',
                'resume_avantages', 'resume_defis', 'resume_salaire', 
                'resume_duree', 'dernier_conseil'
            ]
            
            for field in required_voie_fields:
                if field not in voie:
                    raise ValueError(f"[{request_id}] voies[{idx}].{field} is required")
            
            # Vérifier number
            if voie['number'] != idx + 1:
                raise ValueError(f"[{request_id}] voies[{idx}].number should be {idx + 1}, got {voie['number']}")
            
            # Vérifier color_class
            if voie['color_class'] not in valid_color_classes:
                raise ValueError(
                    f"[{request_id}] voies[{idx}].color_class must be one of {valid_color_classes}, "
                    f"got '{voie['color_class']}'"
                )
            
            # formations et cibles_employeurs doivent être des listes de strings
            if not isinstance(voie['formations'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].formations must be a list")
            
            if len(voie['formations']) == 0:
                raise ValueError(f"[{request_id}] voies[{idx}].formations cannot be empty")
            
            for f_idx, formation in enumerate(voie['formations']):
                if not isinstance(formation, str):
                    raise ValueError(f"[{request_id}] voies[{idx}].formations[{f_idx}] must be a string")
            
            if not isinstance(voie['cibles_employeurs'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs must be a list")
            
            if len(voie['cibles_employeurs']) == 0:
                raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs cannot be empty")
            
            for c_idx, cible in enumerate(voie['cibles_employeurs']):
                if not isinstance(cible, str):
                    raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs[{c_idx}] must be a string")
            
            # resume_avantages doit être une liste
            if not isinstance(voie['resume_avantages'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].resume_avantages must be a list")
            
            if len(voie['resume_avantages']) < 3:
                raise ValueError(f"[{request_id}] voies[{idx}].resume_avantages must have at least 3 items")
            
            # ⚠️ resume_defis est un STRING en V2 (pas une liste)
            if not isinstance(voie['resume_defis'], str):
                raise ValueError(f"[{request_id}] voies[{idx}].resume_defis must be a string (not list)")
            
            if not voie['resume_defis'].strip():
                raise ValueError(f"[{request_id}] voies[{idx}].resume_defis cannot be empty")
            
            # Vérifier les strings obligatoires non vides
            string_voie_fields = [
                'icon', 'hero_title', 'quelques_mots', 'avantage_unique',
                'dire_quote', 'warning_text', 'warning_evite', 'savais_tu',
                'resume_salaire', 'resume_duree', 'dernier_conseil'
            ]
            
            for field in string_voie_fields:
                if not isinstance(voie[field], str) or not voie[field].strip():
                    raise ValueError(f"[{request_id}] voies[{idx}].{field} must be a non-empty string")
        
        logger.info(f"[{request_id}] ✅ Career path V2 validated successfully")
        return result_json

    def _validate_career_path_v3_response(self, result_json: Dict, request_id: str) -> Dict:
        """
        Validation stricte pour le nouveau format career_path V3 (template Nelly).
        Structure selon le nouveau JSON avec options, voies simplifiées, etc.
        """
        
        if not isinstance(result_json, dict):
            raise ValueError(f"[{request_id}] Invalid JSON: not a dict")
        
        # ============================================================
        # CLÉS OBLIGATOIRES DE PREMIER NIVEAU
        # ============================================================
        required_keys = [
            'cover_quote', 'cover_date',
            'intro_text_bloc1', 'intro_text_bloc2',
            'section1_quote_verbatim', 'section1_tilto_comprend',
            'transformations_count', 'transformations', 'section2_tilto_comprend',
            'options', 'voies', 'finale_gender_pronoun'
        ]
        
        for key in required_keys:
            if key not in result_json:
                raise ValueError(f"[{request_id}] Missing required key: '{key}'")
        
        # ============================================================
        # VALIDATION STRINGS OBLIGATOIRES NON VIDES
        # ============================================================
        string_fields = [
            'cover_quote', 'cover_date',
            'intro_text_bloc1', 'intro_text_bloc2',
            'section1_quote_verbatim', 'section1_tilto_comprend',
            'section2_tilto_comprend', 'finale_gender_pronoun'
        ]
        
        for field in string_fields:
            if not isinstance(result_json[field], str) or not result_json[field].strip():
                raise ValueError(f"[{request_id}] '{field}' must be a non-empty string")
        
        # ============================================================
        # VALIDATION TRANSFORMATIONS
        # ============================================================
        if not isinstance(result_json['transformations'], list):
            raise ValueError(f"[{request_id}] 'transformations' must be a list")
        
        if len(result_json['transformations']) != result_json['transformations_count']:
            raise ValueError(
                f"[{request_id}] transformations_count={result_json['transformations_count']} "
                f"but got {len(result_json['transformations'])} transformations"
            )
        
        if len(result_json['transformations']) < 3:
            raise ValueError(f"[{request_id}] 'transformations' must have at least 3 items")
        
        for idx, trans in enumerate(result_json['transformations']):
            if not isinstance(trans, dict):
                raise ValueError(f"[{request_id}] transformations[{idx}] must be a dict")
            
            # ⚠️ V2 utilise 'before'/'after' (pas 'negative'/'positive')
            if 'before' not in trans or not trans['before'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].before is required")
            
            if 'after' not in trans or not trans['after'].strip():
                raise ValueError(f"[{request_id}] transformations[{idx}].after is required")
        
        # ============================================================
        # VALIDATION OPTIONS (nouveau en V2)
        # ============================================================
        if not isinstance(result_json['options'], list):
            raise ValueError(f"[{request_id}] 'options' must be a list")
        
        if len(result_json['options']) != 3:
            raise ValueError(
                f"[{request_id}] 'options' must contain exactly 3 items, "
                f"got {len(result_json['options'])}"
            )
        
        for idx, option in enumerate(result_json['options']):
            if not isinstance(option, dict):
                raise ValueError(f"[{request_id}] options[{idx}] must be a dict")
            
            required_option_fields = ['number', 'icon', 'title', 'tags']
            
            for field in required_option_fields:
                if field not in option:
                    raise ValueError(f"[{request_id}] options[{idx}].{field} is required")
            
            # Vérifier que number correspond à l'index + 1
            if option['number'] != idx + 1:
                raise ValueError(f"[{request_id}] options[{idx}].number should be {idx + 1}, got {option['number']}")
            
            # tags doit être une liste non vide
            if not isinstance(option['tags'], list) or len(option['tags']) == 0:
                raise ValueError(f"[{request_id}] options[{idx}].tags must be a non-empty list")
        
        # ============================================================
        # VALIDATION VOIES (structure V2)
        # ============================================================
        if not isinstance(result_json['voies'], list):
            raise ValueError(f"[{request_id}] 'voies' must be a list")
        
        if len(result_json['voies']) != 3:
            raise ValueError(
                f"[{request_id}] 'voies' must contain exactly 3 items, "
                f"got {len(result_json['voies'])}"
            )
        
        valid_color_classes = ['option-1', 'option-2', 'option-3']
        
        for idx, voie in enumerate(result_json['voies']):
            if not isinstance(voie, dict):
                raise ValueError(f"[{request_id}] voies[{idx}] must be a dict")
            
            # Champs obligatoires V2
            required_voie_fields = [
                'number', 'color_class', 'icon', 'hero_title', 'quelques_mots',
                'avantage_unique', 'dire_quote', 'warning_text', 'warning_evite',
                'formations', 'cibles_employeurs', 'savais_tu',
                'resume_avantages', 'resume_defis', 'resume_salaire', 
                'resume_duree', 'dernier_conseil'
            ]
            
            for field in required_voie_fields:
                if field not in voie:
                    raise ValueError(f"[{request_id}] voies[{idx}].{field} is required")
            
            # Vérifier number
            if voie['number'] != idx + 1:
                raise ValueError(f"[{request_id}] voies[{idx}].number should be {idx + 1}, got {voie['number']}")
            
            # Vérifier color_class
            if voie['color_class'] not in valid_color_classes:
                raise ValueError(
                    f"[{request_id}] voies[{idx}].color_class must be one of {valid_color_classes}, "
                    f"got '{voie['color_class']}'"
                )
            
            # formations et cibles_employeurs doivent être des listes de strings
            if not isinstance(voie['formations'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].formations must be a list")
            
            if len(voie['formations']) == 0:
                raise ValueError(f"[{request_id}] voies[{idx}].formations cannot be empty")
            
            for f_idx, formation in enumerate(voie['formations']):
                if not isinstance(formation, str):
                    raise ValueError(f"[{request_id}] voies[{idx}].formations[{f_idx}] must be a string")
            
            if not isinstance(voie['cibles_employeurs'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs must be a list")
            
            if len(voie['cibles_employeurs']) == 0:
                raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs cannot be empty")
            
            for c_idx, cible in enumerate(voie['cibles_employeurs']):
                if not isinstance(cible, str):
                    raise ValueError(f"[{request_id}] voies[{idx}].cibles_employeurs[{c_idx}] must be a string")
            
            # resume_avantages doit être une liste
            if not isinstance(voie['resume_avantages'], list):
                raise ValueError(f"[{request_id}] voies[{idx}].resume_avantages must be a list")
            
            if len(voie['resume_avantages']) < 3:
                raise ValueError(f"[{request_id}] voies[{idx}].resume_avantages must have at least 3 items")
            
            # ⚠️ resume_defis est un STRING en V2 (pas une liste)
            if not isinstance(voie['resume_defis'], str):
                raise ValueError(f"[{request_id}] voies[{idx}].resume_defis must be a string (not list)")
            
            if not voie['resume_defis'].strip():
                raise ValueError(f"[{request_id}] voies[{idx}].resume_defis cannot be empty")
            
            # Vérifier les strings obligatoires non vides
            string_voie_fields = [
                'icon', 'hero_title', 'quelques_mots', 'avantage_unique',
                'dire_quote', 'warning_text', 'warning_evite', 'savais_tu',
                'resume_salaire', 'resume_duree', 'dernier_conseil'
            ]
            
            for field in string_voie_fields:
                if not isinstance(voie[field], str) or not voie[field].strip():
                    raise ValueError(f"[{request_id}] voies[{idx}].{field} must be a non-empty string")
        
        logger.info(f"[{request_id}] ✅ Career path V2 validated successfully")
        return result_json

    def _get_validation_criteria(self, step_id: str, custom_criteria: str = None) -> str:
        """
        Retourne les critères de validation spécifiques à chaque type d'analyse.
        
        ORDRE DE PRIORITÉ:
        1. custom_criteria (si passé en paramètre - depuis l'interface admin)
        2. validation_criteria en BDD (depuis quiz_result)
        3. Fallback hardcodé (si rien en BDD)
        
        Args:
            step_id: L'identifiant de l'étape (career_path, career_path_v1, career_path_v2, etc.)
            custom_criteria: Critères personnalisés passés depuis l'interface admin (optionnel)
            
        Returns:
            str: Les critères de validation à utiliser
        """
        
        # 1. Si critères personnalisés fournis (depuis interface admin), les utiliser
        if custom_criteria and custom_criteria.strip():
            logger.info(f"[{step_id}] ✅ Utilisation des critères de validation PERSONNALISÉS (admin)")
            return custom_criteria.strip()
        
        # 2. Essayer de récupérer depuis la BDD
        try:
            self.cursor.execute("""
                SELECT validation_criteria
                FROM quiz_result
                WHERE quiz_id = %s 
                AND result_step_id = %s 
                AND is_active = TRUE
            """, (self.quiz_id, step_id))
            
            result = self.cursor.fetchone()
            
            if result and result.get('validation_criteria') and result['validation_criteria'].strip():
                logger.info(f"[{step_id}] ✅ Utilisation des critères de validation depuis BDD")
                return result['validation_criteria'].strip()
            
            logger.warning(f"[{step_id}] ⚠️ Pas de validation_criteria en BDD, utilisation du fallback")
            
        except Exception as e:
            logger.error(f"[{step_id}] ❌ Erreur récupération validation_criteria: {e}")
        
        # 3. Fallback hardcodé (garde le comportement actuel comme backup)
        return self._get_validation_criteria_fallback(step_id)


    def _get_validation_criteria_fallback(self, step_id: str) -> str:
        """
        Fallback hardcodé pour les critères de validation.
        Utilisé uniquement si rien en BDD et pas de critères personnalisés.
        """
        
        if step_id == 'career_path_v2':
            return """

    ## 1️⃣ STRUCTURE OBLIGATOIRE
    - [ ] cover_quote : 15-20 mots résumant le besoin principal
    - [ ] cover_date : Format "MOIS ANNÉE" en majuscules
    - [ ] intro_text_bloc1 : Résumé du parcours (100-150 chars)
    - [ ] intro_text_bloc2 : Annonce des 3 voies (150-200 chars)

    ## 2️⃣ SECTION 1 - VERBATIM
    - [ ] section1_quote_verbatim : Citation DIRECTE avec <span class='hl-jaune'>
    - [ ] section1_tilto_comprend : Synthèse avec <strong> (50-80 mots)

    ## 3️⃣ TRANSFORMATIONS (before/after)
    - [ ] Minimum 3 transformations
    - [ ] Chaque transformation a 'before' et 'after' non vides
    - [ ] Basées sur le questionnaire réel

    ## 4️⃣ OPTIONS (grille de sélection)
    - [ ] Exactement 3 options
    - [ ] Chaque option : number (1-3), icon, title, tags (liste)
    - [ ] Tags pertinents et différenciants

    ## 5️⃣ VOIES (3 voies complètes)
    - [ ] number : 1, 2 ou 3
    - [ ] color_class : "option-1", "option-2" ou "option-3"
    - [ ] hero_title : Métier CONCRET (pas générique)
    - [ ] quelques_mots : Description quotidien (80-120 mots)
    - [ ] avantage_unique : Avec <strong> (80-120 mots)
    - [ ] dire_quote : Citation exemple entretien (60-100 mots)
    - [ ] warning_text : Conseil avec <strong>
    - [ ] warning_evite : Entre apostrophes
    - [ ] formations : Liste de strings (noms précis)
    - [ ] cibles_employeurs : Liste de strings (entreprises RÉELLES)
    - [ ] savais_tu : Fait marché avec <strong> (40-60 mots)
    - [ ] resume_avantages : Liste (min 3 items)
    - [ ] resume_defis : STRING (pas liste) - 30-50 mots
    - [ ] resume_salaire : Format "35-55K€ brut/an (2275-3575€ net)"
    - [ ] resume_duree : Ex: "3-4 mois"
    - [ ] dernier_conseil : Avec <strong> (40-80 mots)

    ## 6️⃣ QUALITÉ DES VOIES (CRITIQUE)
    - [ ] Les 3 métiers RECRUTENT ACTIVEMENT dans la région
    - [ ] Au moins 1-2 voies HORS du domaine actuel
    - [ ] Entreprises citées sont RÉELLES
    - [ ] Salaires RÉALISTES pour la région/métier
    - [ ] Formations EXISTANTES et accessibles

    ## 7️⃣ PERSONNALISATION
    - [ ] Références concrètes au questionnaire
    - [ ] Adaptation géographique
    - [ ] Ton empathique et direct
    """

        elif step_id == 'career_path_v3':
            return """

    ## 1️⃣ STRUCTURE OBLIGATOIRE
    - [ ] cover_quote : 15-20 mots résumant le besoin principal
    - [ ] cover_date : Format "MOIS ANNÉE" en majuscules
    - [ ] intro_text_bloc1 : Résumé du parcours (100-150 chars)
    - [ ] intro_text_bloc2 : Annonce des 3 voies (150-200 chars)

    ## 2️⃣ SECTION 1 - VERBATIM
    - [ ] section1_quote_verbatim : Citation DIRECTE avec <span class='hl-jaune'>
    - [ ] section1_tilto_comprend : Synthèse avec <strong> (50-80 mots)

    ## 3️⃣ TRANSFORMATIONS (before/after)
    - [ ] Minimum 3 transformations
    - [ ] Chaque transformation a 'before' et 'after' non vides
    - [ ] Basées sur le questionnaire réel

    ## 4️⃣ OPTIONS (grille de sélection)
    - [ ] Exactement 3 options
    - [ ] Chaque option : number (1-3), icon, title, tags (liste)
    - [ ] Tags pertinents et différenciants

    ## 5️⃣ VOIES (3 voies complètes)
    - [ ] number : 1, 2 ou 3
    - [ ] color_class : "option-1", "option-2" ou "option-3"
    - [ ] hero_title : Métier CONCRET (pas générique)
    - [ ] quelques_mots : Description quotidien (80-120 mots)
    - [ ] avantage_unique : Avec <strong> (80-120 mots)
    - [ ] dire_quote : Citation exemple entretien (60-100 mots)
    - [ ] warning_text : Conseil avec <strong>
    - [ ] warning_evite : Entre apostrophes
    - [ ] formations : Liste de strings (noms précis)
    - [ ] cibles_employeurs : Liste de strings (entreprises RÉELLES)
    - [ ] savais_tu : Fait marché avec <strong> (40-60 mots)
    - [ ] resume_avantages : Liste (min 3 items)
    - [ ] resume_defis : STRING (pas liste) - 30-50 mots
    - [ ] resume_salaire : Format "35-55K€ brut/an (2275-3575€ net)"
    - [ ] resume_duree : Ex: "3-4 mois"
    - [ ] dernier_conseil : Avec <strong> (40-80 mots)

    ## 6️⃣ QUALITÉ DES VOIES (CRITIQUE)
    - [ ] Les 3 métiers RECRUTENT ACTIVEMENT dans la région
    - [ ] Au moins 1-2 voies HORS du domaine actuel
    - [ ] Entreprises citées sont RÉELLES
    - [ ] Salaires RÉALISTES pour la région/métier
    - [ ] Formations EXISTANTES et accessibles

    ## 7️⃣ PERSONNALISATION
    - [ ] Références concrètes au questionnaire
    - [ ] Adaptation géographique
    - [ ] Ton empathique et direct
    """
        
        elif step_id == 'career_path_v1':
            return """
    # CRITÈRES DE VALIDATION V1 - TEMPLATE CÉCILE

    ## 1️⃣ STRUCTURE OBLIGATOIRE  
    - [ ] cover_quote, hero_intro, main_user_quote, citation_insight
    - [ ] transformations avec negative/positive
    - [ ] atouts avec icon, title, description, details, pitch_*
    - [ ] voies avec color_class rose/jaune/vert

    ## 2️⃣ VOIES
    - [ ] 3 voies distinctes
    - [ ] premiers_moves avec objets {label, items}
    - [ ] avantages et defis en listes
    """
        
        elif step_id == 'career_path':
            return """
    # CRITÈRES DE VALIDATION V0 - LEGACY

    ## STRUCTURE
    - [ ] welcome, starting_point, strategies, actions
    - [ ] strategies.items : 3 stratégies
    - [ ] actions.items : 3 actions
    """
        
        else:
            return "No specific validation criteria configured for this step."
            
    # ===== API Anthropic =====
    def _call_anthropic_api(self, system_prompt: str, human_prompt: str, request_id: str,
                        anonymized_human_prompt: Optional[str] = None,
                        temperature: float = None,
                        max_tokens: int = None,
                        enable_web_search: bool = None) -> str:
        """
        Appelle l'API Anthropic avec retry automatique, web_search et gestion erreurs.
        
        Args:
            system_prompt: Le prompt système
            human_prompt: Le prompt humain original
            request_id: ID de requête pour logging
            anonymized_human_prompt: Version anonymisée du prompt humain (optionnel)
            temperature: Temperature pour l'API (optionnel, sinon utilise config)
            max_tokens: Max tokens pour l'API (optionnel, sinon utilise config)
        
        Returns:
            str: Réponse de Claude (dénonymisée si nécessaire)
        """
        max_retries = 3
        base_retry_delay = 5  # secondes
        
        # Utiliser la version anonymisée du prompt humain si disponible
        human_to_send = anonymized_human_prompt or human_prompt
        
        # Paramètres par défaut si non spécifiés
        temp = temperature if temperature is not None else current_app.config.get('ANTHROPIC_TEMPERATURE', 0.7)
        tokens = max_tokens if max_tokens is not None else current_app.config.get('ANTHROPIC_MAX_TOKENS', 16384)
        
        # Logging des prompts
        logger.info(f"[Request ID: {request_id}] === LOGS AVANT/APRÈS ANONYMISATION ===")
        logger.info("=" * 80)
        logger.info("SYSTEM PROMPT:")
        logger.info("-" * 80)
        logger.info(system_prompt)
        logger.info("=" * 80)

        # Ne logger qu'une fois si pas d'anonymisation
        if human_to_send != human_prompt:
            logger.info("HUMAN PROMPT - ORIGINAL vs ANONYMISÉ:")
            logger.info("-" * 80)
            logger.info(f"ORIGINAL: {human_prompt}")
            logger.info("-" * 80)
            logger.info(f"ANONYMISÉ: {human_to_send}")
        else:
            logger.info("HUMAN PROMPT (pas d'anonymisation):")
            logger.info("-" * 80)
            logger.info(human_to_send)
        logger.info("=" * 80)
        
        # Différences si anonymisation
        if human_to_send != human_prompt:
            original_human_tokens = set(human_prompt.split())
            anonymized_human_tokens = set(human_to_send.split())
            human_diff = original_human_tokens.symmetric_difference(anonymized_human_tokens)
            
            if human_diff:
                logger.info("TOKENS MODIFIÉS PAR L'ANONYMISATION:")
                logger.info(f"Human prompt: {', '.join(list(human_diff)[:20])}" + 
                        ("..." if len(human_diff) > 20 else ""))
                logger.info("-" * 80)
            
            human_diffs = self._analyze_anonymization_diff(human_prompt, human_to_send)
            if human_diffs:
                logger.info("ANALYSE DÉTAILLÉE DES ANONYMISATIONS:")
                logger.info("Dans le human prompt:")
                for i, diff in enumerate(human_diffs[:5], 1):
                    logger.info(f"  {i}. '{diff['original']}' → '{diff['anonymized']}'")
                    logger.info(f"     Contexte: {diff['context']}")
                if len(human_diffs) > 5:
                    logger.info(f"... et {len(human_diffs) - 5} autres remplacements")
                logger.info("-" * 80)
        
        # Boucle de retry
        for attempt in range(max_retries):
            try:
                logger.info(f"[Request ID: {request_id}] Envoi de la requête à l'API Anthropic (tentative {attempt + 1}/{max_retries})...")
                
                # ===== FORCER CLAUDE À COMMENCER PAR JSON AVEC PREFILL =====
                messages_with_prefill = [
                    {"role": "user", "content": human_to_send},
                    {"role": "assistant", "content": "{"}
                ]

                logger.info(f"[{request_id}] ✅ Prefill activé : Claude forcé à générer JSON directement")

                # ===== PRÉPARER L'APPEL API (avec ou sans web_search) =====
                api_params = {
                    "model": current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
                    "max_tokens": tokens,
                    "temperature": temp,
                    "system": system_prompt,
                    "messages": messages_with_prefill
                }

                # ===== DÉTERMINER SI WEB_SEARCH EST ACTIVÉ =====
                # Priorité : argument > config > défaut (True)
                if enable_web_search is None:
                    enable_web_search = current_app.config.get('ENABLE_WEB_SEARCH', True)

                logger.info(f"[{request_id}] 🔧 Web search parameter: {enable_web_search}")

                # ✅ ACTIVER WEB_SEARCH SI NÉCESSAIRE
                if enable_web_search:
                    city, region = self._extract_location_from_quiz()
                    
                    if city and region:
                        user_location = {
                            "type": "approximate",
                            "city": city,
                            "region": region,
                            "country": "FR",
                            "timezone": "Europe/Paris"
                        }
                        logger.info(f"[{request_id}] 🌍 Web search ENABLED: {city}, {region}")
                    elif city:
                        user_location = {
                            "type": "approximate",
                            "city": city,
                            "country": "FR",
                            "timezone": "Europe/Paris"
                        }
                        logger.info(f"[{request_id}] 🏙️ Web search ENABLED: {city}")
                    else:
                        user_location = {
                            "type": "approximate",
                            "country": "FR",
                            "timezone": "Europe/Paris"
                        }
                        logger.info(f"[{request_id}] 🇫🇷 Web search ENABLED: France")
                    
                    api_params["tools"] = [{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": 5,
                        "user_location": user_location
                    }]
                else:
                    logger.warning(f"[{request_id}] 🚫 Web search DISABLED")

                # ===== APPEL API =====
                message = self.client.messages.create(**api_params)

                anonymized_result = message.content[0].text
                
                # ✅ RECONSTITUER LE JSON COMPLET (ajouter le { initial du prefill)
                if not anonymized_result.startswith('{'):
                    anonymized_result = '{' + anonymized_result
                    logger.info(f"[{request_id}] ✅ JSON reconstitué avec prefill")
                
                logger.info(f"[Request ID: {request_id}] === RÉPONSE COMPLÈTE DE CLAUDE (ANONYMISÉE) ===")
                logger.info(f"Réponse brute (anonymisée):")
                logger.info(anonymized_result)
                logger.info("=" * 80)

                # Dénonymisation de la réponse
                result_str = self.denonymize_claude_response(anonymized_result, request_id)
                
                if result_str != anonymized_result:
                    logger.info(f"[Request ID: {request_id}] === RÉPONSE DÉNONYMISÉE DE CLAUDE ===")
                    logger.info(f"Réponse dénonymisée:")
                    logger.info(result_str)
                    logger.info("=" * 80)
                
                # ✅ Succès - envoyer notification si c'était un retry
                if attempt > 0 and self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                                f"✅ *API Anthropic rétablie*\nRequête réussie après {attempt + 1} tentative(s)\nRequest ID: `{request_id}`",
                                channel="monitoring"
                            )
                    except Exception:
                        pass  # Ignore si Slack fail

                return result_str
            
            # ========================================
            # GESTION DES ERREURS AVEC RETRY
            # ========================================
            
            except anthropic.InternalServerError as e:
                error_str = str(e)
                
                if 'Overloaded' in error_str or 'overloaded' in error_str.lower():
                    if attempt < max_retries - 1:
                        wait_time = base_retry_delay * (2 ** attempt)
                        
                        logger.warning(f"[Request ID: {request_id}] 🚦 API SURCHARGÉE - Retry dans {wait_time}s")
                        
                        if attempt == 0 and self.slack_available and self.slack_service:
                            try:
                                self.slack_service.send_notification(
                                        f"🚦 *API Anthropic surchargée*\n"
                                        f"Retry automatique en cours...\n"
                                        f"Request ID: `{request_id}`\n"
                                        f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`",
                                        channel="monitoring"
                                    )
                            except Exception:
                                pass
                        
                        time.sleep(wait_time)
                        continue
                        
                    else:
                        logger.error(
                            f"[Request ID: {request_id}] ❌ API SURCHARGÉE - "
                            f"Échec après {max_retries} tentatives"
                        )

                        if self.slack_available and self.slack_service:
                            try:
                                self.slack_service.send_notification(
                                    f"❌ *API Anthropic - Échec après retries*\n"
                                    f"La génération a échoué après {max_retries} tentatives\n"
                                    f"Erreur: `Overloaded`\n"
                                    f"Request ID: `{request_id}`\n"
                                    f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`\n"
                                    f"_Action requise: Réessayer manuellement dans 10-15 minutes_",
                                    channel="monitoring"
                                )
                            except Exception as slack_error:
                                logger.warning(f"Échec notification Slack: {str(slack_error)}")
                        
                        self._send_anthropic_error_alert(
                            error_type='server_overloaded',
                            error_message=error_str,
                            error_details={
                                'request_id': request_id,
                                'attempts': max_retries,
                                'user_id': self.user_id,
                                'quiz_id': self.quiz_id
                            }
                        )
                        raise
                
                else:
                    logger.error(f"[Request ID: {request_id}] 🔥 ANTHROPIC SERVER ERROR: {error_str}")
                    
                    if self.slack_available and self.slack_service:
                        try:
                            self.slack_service.send_notification(
                                f"🔥 *Erreur serveur Anthropic*\n"
                                f"Erreur 500 (non-overload)\n"
                                f"Message: ```{error_str[:300]}```\n"
                                f"Request ID: `{request_id}`\n"
                                f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`",
                                channel="monitoring"
                            )
                        except Exception as slack_error:
                            logger.warning(f"Échec notification Slack: {str(slack_error)}")
                    
                    self._send_anthropic_error_alert(
                        error_type='server_error',
                        error_message=error_str,
                        error_details={'request_id': request_id}
                    )
                    raise
            
            except anthropic.RateLimitError as e:
                logger.error(f"[Request ID: {request_id}] 🚦 RATE LIMIT: {str(e)}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"🚦 *Rate Limit Anthropic atteint*\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`\n"
                            f"_Action: Augmenter les limites API ou attendre_",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='rate_limit',
                    error_message=str(e),
                    error_details={'request_id': request_id}
                )
                raise
            
            except anthropic.NotFoundError as e:
                configured_model = current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514')
                logger.error(f"[Request ID: {request_id}] ❌ MODÈLE OBSOLÈTE: {configured_model}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"⚠️ *MODÈLE ANTHROPIC OBSOLÈTE*\n"
                            f"Modèle configuré: `{configured_model}`\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"🔧 *Action URGENTE:* Mettre à jour `ANTHROPIC_MODEL` dans la config",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='model_not_found',
                    error_message=str(e),
                    error_details={'model': configured_model, 'request_id': request_id}
                )
                raise
            
            except anthropic.AuthenticationError as e:
                logger.error(f"[Request ID: {request_id}] 🔐 AUTHENTICATION ERROR: {str(e)}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"🔐 *ERREUR D'AUTHENTIFICATION ANTHROPIC*\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"🚨 *Action CRITIQUE:* Vérifier `ANTHROPIC_API_KEY`",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='authentication',
                    error_message=str(e),
                    error_details={'request_id': request_id}
                )
                raise
            
            except anthropic.BadRequestError as e:
                logger.error(f"[Request ID: {request_id}] ❌ INVALID REQUEST: {str(e)}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"❌ *REQUÊTE INVALIDE ANTHROPIC*\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`\n"
                            f"_Vérifier les paramètres: temperature, top_p, max_tokens_",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='invalid_request',
                    error_message=str(e),
                    error_details={'request_id': request_id}
                )
                raise
            
            except anthropic.PermissionDeniedError as e:
                logger.error(f"[Request ID: {request_id}] 💳 BILLING/PERMISSION ERROR: {str(e)}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"💳 *ERREUR DE FACTURATION ANTHROPIC*\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"🚨 *Action URGENTE:* Vérifier les crédits et la carte bancaire",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='billing',
                    error_message=str(e),
                    error_details={'request_id': request_id}
                )
                raise
            
            except anthropic.APIError as e:
                logger.error(f"[Request ID: {request_id}] ❓ ANTHROPIC API ERROR: {str(e)}")
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"❓ *ERREUR API ANTHROPIC*\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                
                self._send_anthropic_error_alert(
                    error_type='unknown',
                    error_message=str(e),
                    error_details={'request_id': request_id}
                )
                raise
            
            except Exception as e:
                logger.error(f"[Request ID: {request_id}] Erreur non-Anthropic lors de l'appel API: {str(e)}", exc_info=True)
                
                if self.slack_available and self.slack_service:
                    try:
                        self.slack_service.send_notification(
                            f"⚠️ *ERREUR INATTENDUE*\n"
                            f"Type: `{type(e).__name__}`\n"
                            f"Message: ```{str(e)[:300]}```\n"
                            f"Request ID: `{request_id}`\n"
                            f"User: `{self.user_id}` | Quiz: `{self.quiz_id}`",
                            channel="monitoring"
                        )
                    except Exception as slack_error:
                        logger.warning(f"Échec notification Slack: {str(slack_error)}")
                raise
        
        # Ce point ne devrait jamais être atteint
        raise Exception(f"[Request ID: {request_id}] Échec après {max_retries} tentatives sans exception capturée")
        
    def _send_anthropic_error_alert(self, error_type: str, error_message: str, error_details: dict = None):
        """Envoie une alerte Slack pour toute erreur Anthropic en production."""
        try:
            # Ne pas envoyer d'alerte en développement
            if current_app.config.get('DEBUG', False):
                return
            
            # Utiliser le service Slack centralisé
            from app.services.slack_service import slack_service, SLACK_AVAILABLE
            
            if not SLACK_AVAILABLE:
                logger.warning("Service Slack non disponible pour l'alerte Anthropic")
                return
            
            # Déterminer la couleur et l'emoji selon le type d'erreur
            error_configs = {
                'model_not_found': {
                    'emoji': '⚠️',
                    'color': 'warning',
                    'title': 'MODÈLE ANTHROPIC OBSOLÈTE',
                    'urgency': 'Action requise',
                    'solution': 'Mettre à jour `ANTHROPIC_MODEL` dans:\n• Dev: `.env`\n• Prod: Secret Manager'
                },
                'billing': {
                    'emoji': '💳',
                    'color': 'danger',
                    'title': 'ERREUR DE FACTURATION ANTHROPIC',
                    'urgency': 'Action URGENTE',
                    'solution': 'Vérifier:\n• Crédits disponibles\n• Carte bancaire valide\n• Limites de compte'
                },
                'rate_limit': {
                    'emoji': '🚦',
                    'color': 'warning',
                    'title': 'LIMITE DE TAUX ANTHROPIC ATTEINTE',
                    'urgency': 'Limitation temporaire',
                    'solution': 'Attendre quelques minutes ou:\n• Augmenter les limites API\n• Implémenter un système de retry'
                },
                'invalid_request': {
                    'emoji': '❌',
                    'color': 'danger',
                    'title': 'REQUÊTE INVALIDE ANTHROPIC',
                    'urgency': 'Erreur de configuration',
                    'solution': 'Vérifier les paramètres:\n• `temperature`/`top_p`\n• `max_tokens`\n• Structure du prompt'
                },
                'authentication': {
                    'emoji': '🔐',
                    'color': 'danger',
                    'title': 'ERREUR D\'AUTHENTIFICATION ANTHROPIC',
                    'urgency': 'Action CRITIQUE',
                    'solution': 'Vérifier `ANTHROPIC_API_KEY` dans:\n• Dev: `.env`\n• Prod: Secret Manager'
                },
                'server_error': {
                    'emoji': '🔥',
                    'color': 'danger',
                    'title': 'ERREUR SERVEUR ANTHROPIC',
                    'urgency': 'Problème côté Anthropic',
                    'solution': 'Vérifier:\n• Status page: https://status.anthropic.com\n• Réessayer plus tard'
                },
                'unknown': {
                    'emoji': '❓',
                    'color': 'danger',
                    'title': 'ERREUR ANTHROPIC INCONNUE',
                    'urgency': 'Investigation requise',
                    'solution': 'Consulter les logs pour plus de détails'
                }
            }
            
            config = error_configs.get(error_type, error_configs['unknown'])
            
            # Construction des champs de base
            fields = [
                {
                    "title": f"{config['emoji']} {config['urgency']}",
                    "value": config['solution'],
                    "short": False
                },
                {
                    "title": "🐛 Message d'erreur",
                    "value": f"```{error_message[:500]}```",
                    "short": False
                }
            ]
            
            # Ajouter les détails supplémentaires si disponibles
            if error_details:
                if 'model' in error_details:
                    fields.insert(0, {
                        "title": "🤖 Modèle",
                        "value": f"`{error_details['model']}`",
                        "short": True
                    })
                if 'request_id' in error_details:
                    fields.append({
                        "title": "🔍 Request ID",
                        "value": f"`{error_details['request_id']}`",
                        "short": True
                    })
            
            # Ajouter le lien documentation
            fields.append({
                "title": "📚 Documentation",
                "value": "<https://docs.anthropic.com|Documentation Anthropic> | "
                        "<https://status.anthropic.com|Status Page>",
                "short": False
            })
            
            # Construction du message et attachment
            message = f"{config['emoji']} *{config['title']}*"
            
            attachment = {
                "color": config['color'],
                "fields": fields,
                "footer": "Anthropic API Monitoring",
                "ts": int(datetime.now().timestamp())
            }
            
            # Envoi via le service Slack centralisé
            success = slack_service.send_notification(
                message=message,
                channel='monitoring',  # ✅ Utilise le canal monitoring
                attachments=[attachment]
            )
            
            if success:
                logger.info(f"Alerte Slack envoyée pour erreur Anthropic: {error_type}")
            else:
                logger.error(f"Échec envoi alerte Slack pour erreur Anthropic: {error_type}")
                
        except Exception as e:
            logger.error(f"Erreur lors de l'envoi de l'alerte Anthropic: {str(e)}")
            
            logger.error(f"Erreur envoi alerte Slack: {str(e)}")

    def _analyze_anonymization_diff(self, original_text: str, anonymized_text: str) -> List[Dict]:
        """
        Analyse en détail les différences entre le texte original et le texte anonymisé.
        
        Args:
            original_text (str): Le texte original
            anonymized_text (str): Le texte anonymisé
            
        Returns:
            List[Dict]: Liste des remplacements effectués, avec contexte
        """
        import difflib
        
        # Création d'un matcher pour comparer les textes
        s = difflib.SequenceMatcher(None, original_text, anonymized_text)
        differences = []
        
        # Analyse des opérations (égal, inséré, supprimé, remplacé)
        for tag, i1, i2, j1, j2 in s.get_opcodes():
            if tag == 'replace':
                # Un remplacement indique probablement une anonymisation
                original_fragment = original_text[i1:i2]
                anonymized_fragment = anonymized_text[j1:j2]
                
                # Récupérer un peu de contexte (10 caractères avant et après)
                context_start = max(0, i1 - 10)
                context_end = min(len(original_text), i2 + 10)
                
                context = original_text[context_start:i1] + "[" + original_fragment + "]" + original_text[i2:context_end]
                
                differences.append({
                    'original': original_fragment,
                    'anonymized': anonymized_fragment,
                    'context': context.replace('\n', ' ')
                })
        
        return differences

    def test_anonymization_logging(self, text: str, request_id: str = None) -> Tuple[str, str]:
        """
        Teste l'anonymisation d'un texte et affiche les différences dans les logs.
        Note: Cette fonction est utilisée pour tester/comparer, donc garde l'anonymisation complète
        pour montrer comment le système fonctionne sur tout le texte.
        """
        if request_id is None:
            request_id = f"test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
        # Anonymiser le texte - ne pas passer request_id à anonymize_text
        anonymized_text = self.anonymizer.anonymize_text(text)
        
        # Logging des textes original et anonymisé pour comparaison
        logger.info(f"[Request ID: {request_id}] === TEST D'ANONYMISATION ===")
        logger.info("=" * 80)
        logger.info("TEXTE - ORIGINAL vs ANONYMISÉ:")
        logger.info("-" * 80)
        logger.info(f"ORIGINAL: {text}")
        logger.info("-" * 80)
        logger.info(f"ANONYMISÉ: {anonymized_text}")
        logger.info("=" * 80)
        
        # Analyse détaillée des différences
        diffs = self._analyze_anonymization_diff(text, anonymized_text)
        
        if diffs:
            logger.info("ANALYSE DÉTAILLÉE DES ANONYMISATIONS:")
            for i, diff in enumerate(diffs, 1):
                logger.info(f"  {i}. '{diff['original']}' → '{diff['anonymized']}'")
                logger.info(f"     Contexte: {diff['context']}")
            logger.info("-" * 80)
        else:
            logger.info("Aucune différence détectée - le texte n'a pas été anonymisé")
            logger.info("-" * 80)
        
        return text, anonymized_text

    # ===== Fonctions principales =====
    def _get_analysis_steps(self) -> List[Tuple]:
        """Récupère les étapes d'analyse définies pour ce quiz."""
        self.cursor.execute("""
            SELECT result_step_id, result_step_ranking, prompt_instruction, prompt_knowledge
            FROM quiz_result
            WHERE quiz_id = %s
            ORDER BY result_step_ranking
        """, (self.quiz_id,))
        
        steps = self.cursor.fetchall()
        if not steps:
            raise ValueError("No quiz result steps found")
        return steps

    def _get_system_prompt(self, step_id: str) -> str:
        """Récupère le prompt système pour un step_id donné."""
        self.cursor.execute("""
            SELECT prompt_system 
            FROM quiz_result 
            WHERE quiz_id = %s AND result_step_id = %s
        """, (self.quiz_id, step_id))
        
        result = self.cursor.fetchone()
        if not result or not result['prompt_system']:
            error_msg = f"No system prompt found for quiz_id={self.quiz_id}, step_id={step_id}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        
        return result['prompt_system']

    def _build_human_prompt(self, prompt_data: List[Dict], 
                          prompt_instruction: Optional[str] = None,
                          prompt_knowledge: Optional[str] = None) -> str:
        """Construit le prompt utilisateur."""
        human_prompt = "Voici les réponses aux questions du test de profiling:\n\n"
        for item in prompt_data:
            human_prompt += f"{item['question']}\n{item['answer']}\n\n"
        
        if prompt_instruction:
            human_prompt += prompt_instruction
            if prompt_knowledge:
                human_prompt += f"\n\nContexte additionnel: {prompt_knowledge}\n\n"
        
        return human_prompt

    def _generate_analysis(self, result_id, step_id, request_id, prompt_instruction, prompt_knowledge, 
                        max_retries=2, enable_web_search=None, custom_validation_criteria=None,
                        custom_system_prompt=None, custom_human_prompt=None):
        """
        Génère une analyse LLM avec validation automatique et retry intelligent.
        
        GARANTIES DE TRAÇABILITÉ:
        - Chaque prompt de génération a TOUJOURS validation_status ('success'/'failed'/'structure_failed')
        - Chaque prompt de génération a TOUJOURS validation_prompt_id associé (si validation sémantique)
        - Chaque validation est loggée dans analysis_validation_logs
        
        NOUVEAU : Si la structure JSON est invalide, on régénère TOUT le JSON (pas juste les voies).
        
        Args:
            result_id (str): UUID de l'analyse
            step_id (str): Étape (career_path, career_path_v1, etc.)
            request_id (str): ID de requête pour traçabilité logs
            prompt_instruction (str): Instructions métier du prompt
            prompt_knowledge (str): Contexte métier du prompt
            max_retries (int): Nombre max de tentatives de correction sémantique (défaut: 2)
            enable_web_search (bool): Activer web search (optionnel)
            custom_validation_criteria (str): Critères de validation personnalisés (optionnel)
            custom_system_prompt (str): System prompt personnalisé (optionnel, depuis interface admin)
            custom_human_prompt (str): Human prompt personnalisé (optionnel, depuis interface admin)
        
        Returns:
            tuple: (result_json, prompt_id, timings)
        """
        
        # ==================== INITIALISATION ====================
        start_time = time.time()
        api_total_duration = 0
        total_validation_attempts = 0
        max_structure_retries = 2  # Max tentatives pour structure invalide
        
        logger.info(f"[{request_id}] 🚀 Starting analysis generation - step: {step_id}")
        
        # ==================== BOUCLE DE GÉNÉRATION (avec retry structure) ====================
        
        result_json = None
        initial_prompt_id = None
        last_prompt_id = None
        structure_valid = False
        
        for gen_attempt in range(1, max_structure_retries + 2):  # +2 car range exclusif + 1 pour tentative initiale
            
            gen_request_id = f"{request_id}_gen{gen_attempt}" if gen_attempt > 1 else request_id
            
            if gen_attempt > 1:
                logger.warning(f"[{request_id}] 🔄 STRUCTURE RETRY {gen_attempt - 1}/{max_structure_retries} - Regenerating full JSON")
            
            try:
                # ==================== ÉTAPE 1 : GÉNÉRATION ====================
                
                logger.info(f"[{gen_request_id}] 📝 Preparing user data (Q1-Q13)")
                
                # 1.1 Préparer les données utilisateur
                prompt_data = self.prepare_prompt_data()
                
                # 1.2 Construire le prompt humain
                # ✅ Utiliser le human_prompt personnalisé s'il est fourni
                if custom_human_prompt and custom_human_prompt.strip():
                    human_prompt = custom_human_prompt
                    logger.info(f"[{gen_request_id}] 📝 Using CUSTOM human prompt ({len(human_prompt)} chars)")
                else:
                    human_prompt = self._build_human_prompt(
                        prompt_data=prompt_data,
                        prompt_instruction=prompt_instruction,
                        prompt_knowledge=prompt_knowledge
                    )
                    logger.info(f"[{gen_request_id}] 📝 Using DEFAULT human prompt ({len(human_prompt)} chars)")

                # 1.3 Récupérer le system prompt
                # ✅ Utiliser le system_prompt personnalisé s'il est fourni
                if custom_system_prompt and custom_system_prompt.strip():
                    system_prompt = custom_system_prompt
                    logger.info(f"[{gen_request_id}] 🔧 Using CUSTOM system prompt ({len(system_prompt)} chars)")
                else:
                    self.cursor.execute("""
                        SELECT prompt_system
                        FROM quiz_result
                        WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
                    """, (self.quiz_id, step_id))
                    
                    result = self.cursor.fetchone()
                    system_prompt = result['prompt_system'] if result else ""
                    logger.info(f"[{gen_request_id}] 🔧 Using DEFAULT system prompt from DB ({len(system_prompt)} chars)")
                
                logger.info(f"[{gen_request_id}] 📦 System prompt: {len(system_prompt)} chars")
                
                # 1.4 Créer l'objet PromptData
                prompt_data_obj = PromptData(
                    human_prompt=human_prompt,
                    system_prompt=system_prompt,
                    session_data={'quiz_id': self.quiz_id, 'user_id': self.user_id}
                )
                
                # 1.5 Stocker le prompt
                generation_type = 'initial' if gen_attempt == 1 else 'structure_retry'
                
                current_prompt_id = self._store_prompt(
                    result_id=result_id,
                    step_id=step_id,
                    prompt_data=prompt_data_obj,
                    request_id=gen_request_id,
                    generation_type=generation_type,
                    attempt_number=gen_attempt,
                    parent_prompt_id=last_prompt_id,  # Lien vers le prompt précédent si retry
                    custom_validation_criteria=custom_validation_criteria
                )
                
                if gen_attempt == 1:
                    initial_prompt_id = current_prompt_id
                
                last_prompt_id = current_prompt_id
                logger.info(f"[{gen_request_id}] 💾 Prompt stored: ID={current_prompt_id}")
                
                # 1.6 Appel API Claude
                api_start = time.time()
                
                response_text = self._call_anthropic_api(
                    system_prompt=system_prompt,
                    human_prompt=human_prompt,
                    request_id=gen_request_id,
                    temperature=1,
                    max_tokens=16000,
                    enable_web_search=enable_web_search
                )
                
                api_duration = time.time() - api_start
                api_total_duration += api_duration
                
                logger.info(f"[{gen_request_id}] ✅ API response: {api_duration:.2f}s")
                
                # Stocker la réponse LLM brute
                self._update_prompt_with_llm_response(current_prompt_id, response_text, api_duration)
                
                # 1.7 Parser la réponse
                if '```json' in response_text:
                    response_text = response_text.replace('```json', '').replace('```', '').strip()
                
                result_json = json.loads(response_text)
                logger.info(f"[{gen_request_id}] ✅ JSON parsed successfully")
                
                # ==================== ÉTAPE 2 : VALIDATION STRUCTURE ====================
                
                logger.info(f"[{gen_request_id}] 🔍 Validating JSON structure")
                
                try:
                    self._validate_json_structure(result_json, step_id, gen_request_id)
                    structure_valid = True
                    logger.info(f"[{gen_request_id}] ✅ Structure validation passed")
                    
                    # ✅ Structure OK → Sortir de la boucle de génération
                    break
                    
                except ValueError as e:
                    structure_valid = False
                    structure_error = str(e)
                    
                    logger.warning(f"[{gen_request_id}] ⚠️ Structure validation failed: {structure_error}")
                    
                    # Logger l'échec de structure
                    self._log_validation_attempt(
                        result_id=result_id,
                        step_id=step_id,
                        attempt=gen_attempt,
                        status='structure_failed',
                        issues=[{
                            'recommendation_index': 'global',
                            'field': 'structure',
                            'severity': 'critical',
                            'problem': f'Structure JSON invalide: {structure_error}',
                            'suggestion': 'Régénérer le JSON complet'
                        }],
                        duration=time.time() - api_start
                    )
                    
                    # Mettre à jour le prompt avec échec structure
                    self._update_prompt_with_validation_link(
                        prompt_id=current_prompt_id,
                        validation_prompt_id=None,
                        validation_status='structure_failed',
                        generation_duration=time.time() - start_time
                    )
                    
                    # Continuer la boucle pour régénérer
                    if gen_attempt <= max_structure_retries:
                        logger.warning(f"[{gen_request_id}] 🔄 Will retry full generation...")
                        continue
                    else:
                        logger.error(f"[{gen_request_id}] ❌ Max structure retries reached")
                        # On continue quand même avec le JSON cassé (fail-safe)
                        break
                    
            except json.JSONDecodeError as e:
                logger.error(f"[{gen_request_id}] ❌ JSON parse error: {str(e)}")
                
                # Logger l'échec de parsing
                self._log_validation_attempt(
                    result_id=result_id,
                    step_id=step_id,
                    attempt=gen_attempt,
                    status='parse_failed',
                    issues=[{
                        'recommendation_index': 'global',
                        'field': 'json',
                        'severity': 'critical',
                        'problem': f'JSON invalide: {str(e)}',
                        'suggestion': 'Régénérer le JSON complet'
                    }],
                    duration=time.time() - api_start if 'api_start' in locals() else 0
                )
                
                # Mettre à jour le prompt avec échec parsing
                if 'current_prompt_id' in locals():
                    self._update_prompt_with_validation_link(
                        prompt_id=current_prompt_id,
                        validation_prompt_id=None,
                        validation_status='parse_failed',
                        generation_duration=time.time() - start_time
                    )
                
                if gen_attempt <= max_structure_retries:
                    logger.warning(f"[{gen_request_id}] 🔄 Will retry full generation...")
                    continue
                else:
                    logger.error(f"[{gen_request_id}] ❌ Max retries reached, raising error")
                    raise
                    
            except Exception as e:
                logger.error(f"[{gen_request_id}] ❌ Generation failed: {str(e)}", exc_info=True)
                raise
        
        # ==================== VÉRIFICATION POST-BOUCLE ====================
        
        if result_json is None:
            raise ValueError(f"[{request_id}] Failed to generate valid JSON after {gen_attempt} attempts")
        
        if not structure_valid:
            logger.warning(f"[{request_id}] ⚠️ Proceeding with invalid structure (fail-safe mode)")
            
            # Retourner le JSON malgré la structure invalide
            total_duration = time.time() - start_time
            timings = {
                'generation_time_seconds': round(total_duration, 2),
                'api_call_time_seconds': round(api_total_duration, 2),
                'validation_attempts': gen_attempt,
                'validation_status': 'structure_failed'
            }
            
            return result_json, last_prompt_id, timings
        
        # ==================== ÉTAPE 3 : VALIDATION SÉMANTIQUE INITIALE ====================
        
        logger.info(f"[{request_id}] 🎯 Validating recommendations quality (attempt 1)")
        
        validation_start = time.time()
        total_validation_attempts = 1
        
        validation_result = self._validate_recommendations_only(
            result_json=result_json,
            step_id=step_id,
            request_id=f"{request_id}_val1",
            prompt_id=last_prompt_id,
            custom_validation_criteria=custom_validation_criteria,
            result_id=result_id,
            attempt_number=1
        )
        
        validation_duration = time.time() - validation_start
        initial_issues = validation_result.get('issues', [])
        initial_is_valid = validation_result.get('is_valid', False)
        initial_validation_status = 'success' if initial_is_valid else 'failed'
        
        # ✅ TOUJOURS mettre à jour le prompt avec son résultat
        self._update_prompt_with_validation_link(
            prompt_id=last_prompt_id,
            validation_prompt_id=validation_result.get('validation_prompt_id'),
            validation_status=initial_validation_status,
            generation_duration=time.time() - start_time
        )
        
        # ✅ TOUJOURS logger dans analysis_validation_logs
        self._log_validation_attempt(
            result_id=result_id,
            step_id=step_id,
            attempt=total_validation_attempts,
            status=initial_validation_status,
            issues=initial_issues,
            duration=validation_duration
        )
        
        logger.info(f"[{request_id}] Validation 1 result: {initial_validation_status} - "
                    f"Issues: {len(initial_issues)} - Duration: {validation_duration:.2f}s")
        
        # ==================== CAS 1 : SUCCÈS DU PREMIER COUP ====================
        
        if initial_is_valid:
            logger.info(f"[{request_id}] ✅ SUCCESS on FIRST attempt - No retry needed")
            
            total_duration = time.time() - start_time
            timings = {
                'generation_time_seconds': round(total_duration, 2),
                'api_call_time_seconds': round(api_total_duration, 2),
                'validation_attempts': 1,
                'validation_status': 'success'
            }
            
            return result_json, last_prompt_id, timings
        
        # ==================== ÉTAPE 4 : BOUCLE DE RETRY SÉMANTIQUE ====================
        
        logger.warning(f"[{request_id}] ⚠️ Validation FAILED - Starting retry loop (max {max_retries})")
        logger.warning(f"[{request_id}] Issues: {json.dumps(initial_issues, ensure_ascii=False)[:500]}")
        
        current_issues = initial_issues
        current_json = result_json
        
        for retry_num in range(1, max_retries + 1):
            total_validation_attempts += 1
            retry_request_id = f"{request_id}_retry{retry_num}"
            
            logger.info(f"[{request_id}] 🔄 RETRY {retry_num}/{max_retries}")
            
            retry_start = time.time()
            retry_prompt_id = None  # Reset pour ce retry
            
            try:
                # 4.1 Régénérer les recommandations
                improved_recommendations, retry_prompt_id = self._regenerate_recommendations_only(
                    original_json=current_json,
                    validation_issues=current_issues,
                    step_id=step_id,
                    request_id=retry_request_id,
                    prompt_id=last_prompt_id,
                    result_id=result_id,
                    enable_web_search=enable_web_search,
                    attempt_number=retry_num
                )
                
                retry_generation_duration = time.time() - retry_start
                api_total_duration += retry_generation_duration
                
                # Échec de régénération
                if improved_recommendations is None or retry_prompt_id is None:
                    logger.error(f"[{request_id}] ❌ Retry {retry_num}: Regeneration FAILED")
                    
                    # ✅ Logger l'échec (pas de validation possible)
                    self._log_validation_attempt(
                        result_id=result_id,
                        step_id=step_id,
                        attempt=total_validation_attempts,
                        status='failed',
                        issues=[{'problem': 'Regeneration failed - no JSON produced', 'severity': 'critical'}],
                        duration=retry_generation_duration
                    )
                    
                    continue  # Passer au retry suivant
                
                # 4.2 Fusionner les nouvelles recommandations
                current_json = self._merge_recommendations(current_json, improved_recommendations, step_id)
                
                # 4.3 Valider les nouvelles recommandations
                logger.info(f"[{request_id}] 🔍 Validating retry {retry_num}")
                
                revalidation_start = time.time()
                
                retry_validation_result = self._validate_recommendations_only(
                    result_json=current_json,
                    step_id=step_id,
                    request_id=f"{retry_request_id}_val",
                    prompt_id=retry_prompt_id,
                    custom_validation_criteria=custom_validation_criteria,
                    result_id=result_id,
                    attempt_number=total_validation_attempts
                )
                
                revalidation_duration = time.time() - revalidation_start
                retry_issues = retry_validation_result.get('issues', [])
                retry_is_valid = retry_validation_result.get('is_valid', False)
                retry_validation_status = 'success' if retry_is_valid else 'failed'
                
                total_retry_duration = time.time() - retry_start
                
                # ✅ TOUJOURS mettre à jour le prompt de retry avec son résultat
                self._update_prompt_with_validation_link(
                    prompt_id=retry_prompt_id,
                    validation_prompt_id=retry_validation_result.get('validation_prompt_id'),
                    validation_status=retry_validation_status,
                    generation_duration=total_retry_duration
                )
                
                # ✅ TOUJOURS logger dans analysis_validation_logs
                self._log_validation_attempt(
                    result_id=result_id,
                    step_id=step_id,
                    attempt=total_validation_attempts,
                    status=retry_validation_status,
                    issues=retry_issues,
                    duration=revalidation_duration
                )
                
                logger.info(f"[{request_id}] Retry {retry_num} validation: {retry_validation_status} - "
                            f"Issues: {len(retry_issues)} - Duration: {revalidation_duration:.2f}s")
                
                # ==================== SUCCÈS APRÈS RETRY ====================
                
                if retry_is_valid:
                    logger.info(f"[{request_id}] ✅ SUCCESS after {retry_num} retry(ies)")
                    
                    # Notification Slack (succès après correction)
                    try:
                        if self.slack_available and self.slack_service:
                            self.slack_service.notify_validation_success_after_retry({
                                'result_id': result_id,
                                'step_id': step_id,
                                'user_id': self.user_id,
                                'quiz_id': self.quiz_id,
                                'request_id': request_id,
                                'attempts': total_validation_attempts,
                                'initial_issues_count': len(initial_issues),
                                'fixed_issues_count': len([i for i in initial_issues if i.get('severity') == 'critical']),
                                'generator_type': 'user'
                            })
                            logger.info(f"[{request_id}] 📢 Slack notification sent")
                    except Exception as slack_error:
                        logger.warning(f"[{request_id}] Slack notification failed: {slack_error}")
                    
                    total_duration = time.time() - start_time
                    timings = {
                        'generation_time_seconds': round(total_duration, 2),
                        'api_call_time_seconds': round(api_total_duration, 2),
                        'validation_attempts': total_validation_attempts,
                        'validation_status': 'success'
                    }
                    
                    return current_json, retry_prompt_id, timings
                
                # Échec de validation - préparer pour le prochain retry
                current_issues = retry_issues
                last_prompt_id = retry_prompt_id
                
                logger.warning(f"[{request_id}] ⚠️ Retry {retry_num} FAILED - "
                            f"Remaining: {max_retries - retry_num}")
                
            except Exception as e:
                logger.error(f"[{request_id}] ❌ Retry {retry_num} exception: {str(e)}", exc_info=True)
                
                # ✅ Logger l'exception
                self._log_validation_attempt(
                    result_id=result_id,
                    step_id=step_id,
                    attempt=total_validation_attempts,
                    status='failed',
                    issues=[{'problem': f'Exception: {str(e)}', 'severity': 'critical'}],
                    duration=time.time() - retry_start
                )
                
                # Si on a un retry_prompt_id, le marquer comme failed
                if retry_prompt_id:
                    try:
                        self._update_prompt_with_validation_link(
                            prompt_id=retry_prompt_id,
                            validation_prompt_id=None,
                            validation_status='failed',
                            generation_duration=time.time() - retry_start
                        )
                    except Exception:
                        pass  # Non bloquant
                
                continue
        
        # ==================== ÉCHEC APRÈS TOUS LES RETRIES ====================
        
        logger.error(f"[{request_id}] ❌ FAILED after {max_retries} retries")
        logger.error(f"[{request_id}] Final issues: {json.dumps(current_issues, ensure_ascii=False)[:500]}")
        
        # Notification Slack CRITIQUE
        try:
            if self.slack_available and self.slack_service:
                base_url = current_app.config.get('BASE_URL', 'https://tilto.co')
                admin_url = f"{base_url}/analysis/retry-analysis?user_id={self.user_id}"
                
                self.slack_service.notify_validation_failed_after_retries({
                    'result_id': result_id,
                    'step_id': step_id,
                    'user_id': self.user_id,
                    'quiz_id': self.quiz_id,
                    'request_id': request_id,
                    'attempts': total_validation_attempts,
                    'issues': current_issues,
                    'generator_type': 'user',
                    'admin_url': admin_url
                })
                logger.info(f"[{request_id}] 🚨 CRITICAL Slack alert sent")
        except Exception as slack_error:
            logger.warning(f"[{request_id}] Slack critical alert failed: {slack_error}")
        
        # Retourner le JSON malgré l'échec (fail-safe)
        total_duration = time.time() - start_time
        timings = {
            'generation_time_seconds': round(total_duration, 2),
            'api_call_time_seconds': round(api_total_duration, 2),
            'validation_attempts': total_validation_attempts,
            'validation_status': 'failed'
        }
        
        logger.warning(f"[{request_id}] ⚠️ Returning JSON DESPITE validation failure (fail-safe)")
        
        return current_json, last_prompt_id, timings

    def _validate_json_structure(self, result_json, step_id, request_id):
        """
        Valide la STRUCTURE du JSON (clés requises, nombre d'items, types).
        Version mise à jour avec support V2.
        """
        
        if not isinstance(result_json, dict):
            raise ValueError("JSON must be a dictionary")
        
        if step_id == 'career_path':
            # V0 - Structure legacy
            required_keys = ['welcome', 'starting_point', 'strategies', 'actions']
            for key in required_keys:
                if key not in result_json:
                    raise ValueError(f"Missing required key: '{key}'")
            
            strategies = result_json.get('strategies', {})
            if not isinstance(strategies, dict):
                raise ValueError("'strategies' must be a dict")
            
            items = strategies.get('items', [])
            if not isinstance(items, list) or len(items) != 3:
                raise ValueError(f"'strategies.items' must have exactly 3 items")
            
            actions = result_json.get('actions', {})
            if not isinstance(actions, dict):
                raise ValueError("'actions' must be a dict")
            
            items = actions.get('items', [])
            if not isinstance(items, list) or len(items) != 3:
                raise ValueError(f"'actions.items' must have exactly 3 items")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (career_path V0)")
        
        elif step_id == 'career_path_v1':
            # V1 - Structure Cécile (avec atouts)
            required_keys = ['cover_quote', 'hero_intro', 'voies', 'transformations', 'atouts']
            for key in required_keys:
                if key not in result_json:
                    raise ValueError(f"Missing required key: '{key}'")
            
            # Vérifier transformations
            transformations = result_json.get('transformations', [])
            if not isinstance(transformations, list) or len(transformations) < 3:
                raise ValueError("'transformations' must have at least 3 items")
            
            # Vérifier atouts
            atouts = result_json.get('atouts', [])
            if not isinstance(atouts, list) or len(atouts) < 3:
                raise ValueError("'atouts' must have at least 3 items")
            
            # Vérifier voies
            voies = result_json.get('voies', [])
            if not isinstance(voies, list) or len(voies) != 3:
                raise ValueError("'voies' must have exactly 3 items")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (career_path_v1)")
        
        elif step_id == 'career_path_v2':
            # V2 - Structure Nelly (sans atouts, avec options)
            required_keys = [
                'cover_quote', 'cover_date', 'intro_text_bloc1', 'intro_text_bloc2',
                'section1_quote_verbatim', 'section1_tilto_comprend',
                'transformations', 'section2_tilto_comprend',
                'options', 'voies', 'finale_gender_pronoun'
            ]
            for key in required_keys:
                if key not in result_json:
                    raise ValueError(f"Missing required key: '{key}'")
            
            # Vérifier transformations (avec before/after)
            transformations = result_json.get('transformations', [])
            if not isinstance(transformations, list) or len(transformations) < 3:
                raise ValueError("'transformations' must have at least 3 items")
            
            # Vérifier options
            options = result_json.get('options', [])
            if not isinstance(options, list) or len(options) != 3:
                raise ValueError("'options' must have exactly 3 items")
            
            # Vérifier voies
            voies = result_json.get('voies', [])
            if not isinstance(voies, list) or len(voies) != 3:
                raise ValueError("'voies' must have exactly 3 items")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (career_path_v2)")

        elif step_id == 'career_path_v3':
            # V2 - Structure Nelly (sans atouts, avec options)
            required_keys = [
                'cover_quote', 'cover_date', 'intro_text_bloc1', 'intro_text_bloc2',
                'section1_quote_verbatim', 'section1_tilto_comprend',
                'transformations', 'section2_tilto_comprend',
                'options', 'voies', 'finale_gender_pronoun'
            ]
            for key in required_keys:
                if key not in result_json:
                    raise ValueError(f"Missing required key: '{key}'")
            
            # Vérifier transformations (avec before/after)
            transformations = result_json.get('transformations', [])
            if not isinstance(transformations, list) or len(transformations) < 3:
                raise ValueError("'transformations' must have at least 3 items")
            
            # Vérifier options
            options = result_json.get('options', [])
            if not isinstance(options, list) or len(options) != 3:
                raise ValueError("'options' must have exactly 3 items")
            
            # Vérifier voies
            voies = result_json.get('voies', [])
            if not isinstance(voies, list) or len(voies) != 3:
                raise ValueError("'voies' must have exactly 3 items")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (career_path_v3)")
        
        elif step_id == 'checkup_pro':
            if 'blocks' not in result_json:
                raise ValueError("Missing required key: 'blocks'")
            
            if not result_json['blocks']:
                raise ValueError("'blocks' cannot be empty")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (checkup_pro)")
        
        elif step_id == 'vision_360':
            if 'superpowers' not in result_json:
                raise ValueError("Missing required key: 'superpowers'")
            
            if not isinstance(result_json['superpowers'], list):
                raise ValueError("'superpowers' must be a list")
            
            logger.info(f"[{request_id}] ✅ Structure validation passed (vision_360)")
        
        else:
            logger.warning(f"[{request_id}] No structure validation configured for step_id: {step_id}")

    def _validate_recommendations_only(self, result_json, step_id, request_id, prompt_id,
                                        custom_validation_criteria: str = None,
                                        result_id: str = None,
                                        attempt_number: int = 1):
        """
        Valide la pertinence des recommandations ET stocke le prompt de validation.
        
        Args:
            result_json: Le JSON généré à valider
            step_id: L'étape (career_path, career_path_v1, career_path_v2)
            request_id: ID de requête pour logs
            prompt_id: ID du prompt de génération (parent)
            custom_validation_criteria: Critères personnalisés (optionnel)
            result_id: UUID de l'analyse (pour stockage)
        
        Returns:
            dict: {
                'is_valid': bool,
                'issues': list,
                'severity': str,
                'assessment': str,
                'validation_prompt_id': int  # ← NOUVEAU
            }
        """
        
        validation_start = time.time()
        
        # Extraire les voies selon le step_id
        if step_id == 'career_path':
            recommendations = result_json.get('strategies', {}).get('items', [])
            field_name = 'strategies'
        elif step_id in ('career_path_v1', 'career_path_v2', 'career_path_v3'):
            recommendations = result_json.get('voies', [])
            field_name = 'voies'
        else:
            logger.warning(f"[{request_id}] No validation configured for {step_id}")
            return {'is_valid': True, 'issues': [], 'severity': 'none', 'assessment': 'Skipped', 'validation_prompt_id': None}
        
        # Vérification du nombre
        if len(recommendations) != 3:
            return {
                'is_valid': False,
                'issues': [{
                    'field': field_name,
                    'problem': f'Expected 3 recommendations, got {len(recommendations)}',
                    'severity': 'critical',
                    'suggestion': 'Ensure exactly 3 recommendations are generated'
                }],
                'severity': 'critical',
                'assessment': 'Invalid number of recommendations',
                'validation_prompt_id': None
            }
        
        # Récupérer le contexte utilisateur
        try:
            self.cursor.execute("""
                SELECT prompt
                FROM prompt_user
                WHERE prompt_id = %s
            """, (prompt_id,))
            
            prompt_row = self.cursor.fetchone()
            
            if not prompt_row:
                user_context = "**Contexte non disponible**"
            else:
                prompt_data = json.loads(prompt_row['prompt'])
                original_human_prompt = prompt_data['prompt']['human']
                
                if "Voici les réponses aux questions du test de profiling:" in original_human_prompt:
                    parts = original_human_prompt.split("Voici les réponses aux questions du test de profiling:")
                    if len(parts) > 1:
                        qa_section = parts[1].split("\n\n\n")[0]
                        user_context = "**Réponses au questionnaire:**\n" + qa_section
                    else:
                        user_context = original_human_prompt
                else:
                    user_context = original_human_prompt
        except Exception as e:
            logger.error(f"[{request_id}] Error retrieving context: {e}")
            user_context = "**Contexte utilisateur non disponible**"
        
        # Adapter le preview selon la version
        if step_id == 'career_path_v2':
            recommendations_preview = []
            for idx, voie in enumerate(recommendations):
                recommendations_preview.append({
                    'index': idx,
                    'title': voie.get('hero_title', 'N/A'),
                    'quelques_mots': voie.get('quelques_mots', 'N/A'),
                    'formations': voie.get('formations', []),
                    'cibles_employeurs': voie.get('cibles_employeurs', []),
                    'salaire': voie.get('resume_salaire', 'N/A')
                })
        elif step_id == 'career_path_v3':
            recommendations_preview = []
            for idx, voie in enumerate(recommendations):
                recommendations_preview.append({
                    'index': idx,
                    'title': voie.get('hero_title', 'N/A'),
                    'quelques_mots': voie.get('quelques_mots', 'N/A'),
                    'formations': voie.get('formations', []),
                    'cibles_employeurs': voie.get('cibles_employeurs', []),
                    'salaire': voie.get('resume_salaire', 'N/A')
                })
        elif step_id == 'career_path_v1':
            recommendations_preview = []
            for idx, voie in enumerate(recommendations):
                recommendations_preview.append({
                    'index': idx,
                    'title': voie.get('title', 'N/A'),
                    'projection': voie.get('projection', 'N/A'),
                    'premiers_moves': voie.get('premiers_moves', []),
                    'salaire': voie.get('salaire', 'N/A')
                })
        else:
            recommendations_preview = recommendations
        
        # Récupérer les critères de validation
        validation_criteria = self._get_validation_criteria(step_id, custom_validation_criteria)
        
        # Déterminer la source des critères
        validation_criteria = self._get_validation_criteria(step_id, custom_validation_criteria)
        
        # Déterminer la source des critères
        self.cursor.execute("""
            SELECT validation_criteria
            FROM quiz_result
            WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
        """, (self.quiz_id, step_id))
        db_result = self.cursor.fetchone()
        criteria_source = 'database' if (db_result and db_result.get('validation_criteria')) else 'fallback'
        
        # Utiliser les critères custom si fournis, sinon ceux de la BDD
        if custom_validation_criteria and custom_validation_criteria.strip():
            validation_criteria = custom_validation_criteria
            logger.info(f"Using custom validation criteria : ({custom_validation_criteria} ")
        
        # ✅ DEBUG LOGS
        logger.warning(f"=== DEBUG criteria_source ===")
        logger.warning(f"custom_validation_criteria provided: {bool(custom_validation_criteria)}")
        logger.warning(f"custom_validation_criteria length: {len(custom_validation_criteria) if custom_validation_criteria else 0}")
        logger.warning(f"criteria_source FINAL: {criteria_source}")
        logger.warning(f"=== FIN DEBUG ===")
        
        # Construire le prompt de validation
        validator_prompt = f"""Tu es un expert QA spécialisé dans les reconversions professionnelles.

    CONTEXTE UTILISATEUR:
    {user_context}

    RECOMMANDATIONS À VALIDER:
    ```json
    {json.dumps(recommendations_preview, ensure_ascii=False, indent=2)}
    ```

    {validation_criteria}

    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    📋 RÉPONSE JSON
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    {{
        "is_valid": true/false,
        "issues": [
            {{
                "recommendation_index": 0,
                "field": "hero_title",
                "severity": "critical",
                "problem": "Description courte",
                "suggestion": "Correction en 1 phrase"
            }}
        ],
        "overall_assessment": "Synthèse en 1 phrase"
    }}

    Maximum 2-3 issues. Réponds UNIQUEMENT avec le JSON."""
        
        # Appel API Claude Validator
        validation_prompt_id = None
        
        try:
            validator_response = self._call_anthropic_api(
                system_prompt="",
                human_prompt=validator_prompt,
                request_id=f"{request_id}_validation",
                temperature=0.1,
                max_tokens=2000,
                enable_web_search=False
            )

            validator_raw_response = validator_response

            if '```json' in validator_response:
                validator_response = validator_response.replace('```json', '').replace('```', '').strip()
            
            validator_json = json.loads(validator_response)
            
            issues = validator_json.get('issues', [])
            has_critical_issues = any(
                issue.get('severity') == 'critical' 
                for issue in issues
            )
            
            validation_result = {
                'is_valid': not has_critical_issues,
                'issues': issues,
                'severity': 'critical' if has_critical_issues else 'minor',
                'assessment': validator_json.get('overall_assessment', '')
            }
            
            validation_duration = time.time() - validation_start
            
            # ===== STOCKER LE PROMPT DE VALIDATION =====
            if result_id:
                try:
                    validation_prompt_id = self._store_validation_prompt(
                        result_id=result_id,
                        step_id=step_id,
                        request_id=request_id,
                        validation_prompt=validator_prompt,
                        validated_json=result_json,
                        validation_result=validation_result,
                        validation_duration=validation_duration,
                        parent_generation_prompt_id=prompt_id,
                        validation_criteria_source=criteria_source,
                        custom_criteria=custom_validation_criteria if criteria_source == 'custom' else None,
                        attempt_number=attempt_number
                    )

                    validation_result['validation_prompt_id'] = validation_prompt_id

                    if validation_prompt_id and validator_raw_response:
                        self._update_prompt_with_llm_response(
                            validation_prompt_id, 
                            validator_raw_response, 
                            validation_duration
                        )
                    
                except Exception as store_error:
                    logger.error(f"[{request_id}] Failed to store validation prompt: {store_error}")
            
            return validation_result
            
        except json.JSONDecodeError as e:
            logger.error(f"[{request_id}] Validator returned invalid JSON: {str(e)}")
            return {
                'is_valid': True,
                'issues': [],
                'severity': 'none',
                'assessment': 'Validator error - accepted by default',
                'validation_prompt_id': None
            }
        
        except Exception as e:
            logger.error(f"[{request_id}] Validator API error: {str(e)}")
            return {
                'is_valid': True,
                'issues': [],
                'severity': 'none',
                'assessment': 'Validator exception - accepted by default',
                'validation_prompt_id': None
            }

    def _regenerate_recommendations_only(self, original_json, validation_issues, step_id, 
                                        request_id, prompt_id, result_id,
                                        enable_web_search=None,
                                        attempt_number: int = 1):
        """..."""
        
        logger.info(f"[{request_id}] 🛠️ Starting targeted regeneration of recommendations")
        
        # ===== ADAPTER LE VOCABULAIRE AU STEP_ID =====
        if step_id == 'career_path':
            current_recommendations = original_json.get('strategies', {}).get('items', [])
            field_name = 'strategies'
            recommendations_label = 'stratégies de reconversion'
        elif step_id == 'career_path_v1':
            current_recommendations = original_json.get('voies', [])
            field_name = 'voies'
            recommendations_label = 'voies professionnelles'
        elif step_id == 'career_path_v2':
            current_recommendations = original_json.get('voies', [])
            field_name = 'voies'
            recommendations_label = 'voies professionnelles'
        elif step_id == 'career_path_v3':
            current_recommendations = original_json.get('voies', [])
            field_name = 'voies'
            recommendations_label = 'voies professionnelles'
        else:
            logger.error(f"[{request_id}] Unknown step_id for regeneration: {step_id}")
            return None, None
        
        # ===== RÉCUPÉRER LE HUMAN PROMPT ORIGINAL =====
        try:
            self.cursor.execute("""
                SELECT prompt
                FROM prompt_user
                WHERE prompt_id = %s
            """, (prompt_id,))
            
            prompt_row = self.cursor.fetchone()
            
            if not prompt_row:
                logger.error(f"[{request_id}] ❌ Prompt ID {prompt_id} not found")
                return None, None
            
            prompt_data = json.loads(prompt_row['prompt'])
            original_human_prompt = prompt_data['prompt']['human']
            
            logger.info(f"[{request_id}] ✅ Original prompt retrieved: {len(original_human_prompt)} chars")
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Error retrieving prompt: {e}", exc_info=True)
            return None, None
        
        # ===== CONSTRUIRE LE FEEDBACK CONCIS =====
        feedback_lines = []

        for idx, issue in enumerate(validation_issues[:5], 1):
            rec_idx = issue.get('recommendation_index', 'N/A')
            problem = issue.get('problem', 'Unknown')
            suggestion = issue.get('suggestion', 'No suggestion')
            
            # ✅ Gérer le cas où rec_idx est "global" ou autre string
            if isinstance(rec_idx, int):
                voie_label = f"{field_name.capitalize()[:-1]} {rec_idx + 1}"
            else:
                voie_label = str(rec_idx).upper()  # "GLOBAL", etc.
            
            feedback_lines.append(f"{idx}. {voie_label}: {problem}")
            feedback_lines.append(f"   Solution: {suggestion}")

        feedback = "\n".join(feedback_lines)

        # 4. Prompt retry : minimaliste + rappels stratégiques
        regeneration_prompt = f"""PREMIÈRE VERSION :
        ```json
        {json.dumps(current_recommendations, ensure_ascii=False)}
        ```

        PROBLÈMES DÉTECTÉS :
        {feedback}

        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        🚨 CORRECTION - JSON STRICT UNIQUEMENT 🚨
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        GÉNÈRE 3 {recommendations_label.upper()} CORRIGÉES :
        ✓ Applique les corrections ci-dessus
        ✓ Recherche des pistes RÉALISTES qui recrutent VRAIMENT dans la région
        ✓ Creuse des voies INSOUPÇONNÉES auxquelles il/elle n'a PAS pensé
        ✓ Vérifie cohérence avec contraintes (horaires, salaire minimum, mobilité)

        FORMAT :
        - Commence par [ directement (ZÉRO texte avant)
        - Structure JSON identique à version initiale
        - ZÉRO commentaire HTML, ZÉRO \n littéral

        GÉNÈRE LE JSON ARRAY :"""
        
        # ===== STOCKER LE PROMPT DE RETRY =====
        try:
            regeneration_prompt_data = PromptData(
                human_prompt=regeneration_prompt,
                system_prompt="",
                session_data={
                    'quiz_id': self.quiz_id,
                    'user_id': self.user_id
                }
            )

            regeneration_prompt_id = self._store_prompt(
                result_id=result_id,
                step_id=step_id,
                prompt_data=regeneration_prompt_data,
                request_id=f"{request_id}_retry",
                generation_type='validation_retry',
                attempt_number=attempt_number,
                parent_prompt_id=prompt_id,
                validation_issues=validation_issues  # ← Les issues qui ont déclenché ce retry
            )
            
            logger.info(f"[{request_id}] 💾 Retry prompt stored: {regeneration_prompt_id}")
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Failed to store retry prompt: {e}")
        
        # ===== APPEL API AVEC PREFILL =====
        try:
            logger.info(f"[{request_id}] 🤖 Calling Claude API with JSON prefill")
            
            # ✅ CRÉER LES MESSAGES AVEC PREFILL
            messages_with_prefill = [
                {"role": "user", "content": regeneration_prompt},
                {"role": "assistant", "content": "["}  # ✅ PREFILL pour forcer JSON array
            ]
            
            # ✅ APPEL API DIRECT (pas via _call_anthropic_api car structure différente)
            api_params = {
                "model": current_app.config.get('ANTHROPIC_MODEL', 'claude-sonnet-4-20250514'),
                "max_tokens": current_app.config.get('ANTHROPIC_MAX_TOKENS', 8000),  # ✅ AJOUTÉ
                "temperature": 0.7,
                "messages": messages_with_prefill
            }
            
            # Ajouter web_search si activé
            if enable_web_search is None:
                enable_web_search = current_app.config.get('ENABLE_WEB_SEARCH', True)
            
            if enable_web_search:
                city, region = self._extract_location_from_quiz()
                
                if city and region:
                    user_location = {
                        "type": "approximate",
                        "city": city,
                        "region": region,
                        "country": "FR",
                        "timezone": "Europe/Paris"
                    }
                elif city:
                    user_location = {
                        "type": "approximate",
                        "city": city,
                        "country": "FR",
                        "timezone": "Europe/Paris"
                    }
                else:
                    user_location = {
                        "type": "approximate",
                        "country": "FR",
                        "timezone": "Europe/Paris"
                    }
                
                api_params["tools"] = [{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                    "user_location": user_location
                }]
            
            # Appel API
            api_start = time.time()
            message = self.client.messages.create(**api_params)
            regenerated_text = message.content[0].text
            api_duration = time.time() - api_start
            
            # ✅ RECONSTITUER LE JSON ARRAY
            if not regenerated_text.startswith('['):
                regenerated_text = '[' + regenerated_text
            
            logger.info(f"[{request_id}] ✅ Response received: {len(regenerated_text)} chars")
            
            # Stocker la réponse LLM brute
            self._update_prompt_with_llm_response(regeneration_prompt_id, regenerated_text, api_duration)
            
            # Nettoyer markdown si présent
            if '```' in regenerated_text:
                regenerated_text = regenerated_text.replace('```json', '').replace('```', '').strip()
            
            # Parser JSON
            improved_recommendations = json.loads(regenerated_text)
            
            # Vérifier structure
            if not isinstance(improved_recommendations, list):
                logger.error(f"[{request_id}] ❌ Not a list")
                return None, None
            
            if len(improved_recommendations) != 3:
                logger.error(f"[{request_id}] ❌ Got {len(improved_recommendations)} items instead of 3")
                return None, None
            
            logger.info(f"[{request_id}] ✅ Regeneration successful")

            return improved_recommendations, regeneration_prompt_id
            
        except json.JSONDecodeError as e:
            logger.error(f"[{request_id}] ❌ Invalid JSON: {str(e)}")
            logger.error(f"[{request_id}] Response: {regenerated_text[:500]}")
            return None, None
            
        except Exception as e:
            logger.error(f"[{request_id}] ❌ Regeneration error: {str(e)}", exc_info=True)
            return None, None

    def _merge_recommendations(self, original_json, new_recommendations, step_id):
        """..."""
        
        if not new_recommendations:
            logger.warning("No new recommendations to merge, returning original JSON")
            return original_json
        
        # Deep copy pour ne pas modifier l'original
        merged_json = json.loads(json.dumps(original_json))
        
        if step_id == 'career_path':
            merged_json['strategies']['items'] = new_recommendations
            logger.info("Merged new recommendations into strategies.items")
        
        elif step_id == 'career_path_v1':
            merged_json['voies'] = new_recommendations
            logger.info("Merged new recommendations into voies (V1)")
        
        elif step_id == 'career_path_v2':
            merged_json['voies'] = new_recommendations
            logger.info("Merged new recommendations into voies (V2)")

        elif step_id == 'career_path_v3':
            merged_json['voies'] = new_recommendations
            logger.info("Merged new recommendations into voies (V2)")     
        else:
            logger.warning(f"Unknown step_id for merging: {step_id}")
        
        return merged_json

    def _log_validation_attempt(self, result_id, step_id, attempt, status, issues, duration):
        """
        Log une tentative de validation en BDD.
        
        POURQUOI LOGGER CHAQUE TENTATIVE ?
        1. Debug : Comprendre pourquoi une validation a échoué
        2. Analytics : Calculer le taux de succès par type de profil
        3. Amélioration continue : Identifier les prompts à améliorer
        
        Args:
            result_id (str): ID de l'analyse
            step_id (str): Type d'analyse
            attempt (int): Numéro de tentative
            status (str): 'success' ou 'failed'
            issues (list): Liste des problèmes détectés
            duration (float): Durée de la tentative en secondes
        """
        
        try:
            # Compter les issues critiques vs mineures
            critical_count = sum(1 for issue in issues if issue.get('severity') == 'critical')
            total_count = len(issues)
            
            # Déterminer la résolution
            if status == 'success' and attempt == 1:
                resolution = 'accepted_as_is'
            elif status == 'success' and attempt > 1:
                resolution = 'auto_fixed'
            else:
                resolution = 'manual_review'
            
            query = """
                INSERT INTO analysis_validation_logs
                (result_id, step_id, user_id, attempt_number, validation_status, 
                issues_detected, issues_count, critical_issues_count, 
                resolution_type, validation_duration_seconds)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            self.cursor.execute(query, (
                result_id,
                step_id,
                self.user_id,
                attempt,
                status,
                json.dumps(issues, ensure_ascii=False),
                total_count,
                critical_count,
                resolution,
                round(duration, 2)
            ))
            
            logger.info(f"[{result_id}] Logged validation attempt {attempt}: {status} - "
                    f"{total_count} issues ({critical_count} critical)")
            
        except Exception as e:
            logger.error(f"Error logging validation attempt: {e}", exc_info=True)

    def denonymize_claude_response(self, response_text: str, request_id: str = None, stored_cache: Dict = None) -> str:
        """
        Dénonymise une réponse de Claude contenant des marqueurs d'anonymisation.
        
        Cette méthode est utile si vous avez envoyé des données anonymisées à Claude
        et que Claude répond en utilisant les mêmes marqueurs anonymisés (comme [PER_1], [LOC_2], etc.)
        
        Args:
            response_text (str): La réponse de Claude pouvant contenir des marqueurs anonymisés
            request_id (str, optional): Identifiant de requête pour le logging
            stored_cache (Dict, optional): Cache d'anonymisation stocké (prioritaire sur le cache en mémoire)
            
        Returns:
            str: La réponse avec les marqueurs anonymisés remplacés par les valeurs originales
        """
        try:
            if not response_text:
                return response_text
                
            # Assurons-nous qu'il y a des marqueurs à dénonymiser
            if not re.search(r'\[(PER|LOC|ORG|DATE|EMAIL|PHONE|MISC)_\d+\]', response_text):
                logger.debug(f"[Request ID: {request_id}] Aucun marqueur d'anonymisation trouvé dans la réponse.")
                return response_text
                
            logger.info(f"[Request ID: {request_id}] Dénonymisation de la réponse de Claude...")
            
            # Priorité au cache stocké s'il est fourni
            replacement_cache = {}
            if stored_cache:
                replacement_cache = stored_cache
                logger.info(f"[Request ID: {request_id}] Utilisation du cache stocké pour la dénonymisation.")
            elif hasattr(self.anonymizer, 'replacement_cache') and self.anonymizer.replacement_cache:
                replacement_cache = self.anonymizer.replacement_cache
                logger.info(f"[Request ID: {request_id}] Utilisation du cache en mémoire pour la dénonymisation.")
            else:
                logger.warning(f"[Request ID: {request_id}] Aucun cache de remplacement disponible pour la dénonymisation.")
                return response_text
                
            # Inverser le dictionnaire de remplacement
            inverted_cache = {}
            for key, value in replacement_cache.items():
                # Clé est au format "TYPE:valeur_originale"
                original_value = key.split(':', 1)[1]
                inverted_cache[value] = original_value
            
            # Compte pour les logs
            replacement_count = 0
            
            # Pattern pour trouver les tags anonymisés
            pattern = r'\[(PER|LOC|ORG|DATE|EMAIL|PHONE|MISC)_(\d+)\]'
            
            # Remplacer les tags anonymisés par leurs valeurs d'origine
            denonymized_text = response_text
            for match in re.finditer(pattern, response_text):
                tag = match.group(0)
                if tag in inverted_cache:
                    denonymized_text = denonymized_text.replace(tag, inverted_cache[tag])
                    replacement_count += 1
            
            if replacement_count > 0:
                logger.info(f"[Request ID: {request_id}] {replacement_count} marqueurs anonymisés remplacés dans la réponse.")
                
                # Log pour debug et traçabilité
                logger.debug(f"[Request ID: {request_id}] === RÉPONSE AVANT/APRÈS DÉNONYMISATION ===")
                logger.debug("=" * 80)
                logger.debug(f"ANONYMISÉ: {response_text[:500]}..." if len(response_text) > 500 else f"ANONYMISÉ: {response_text}")
                logger.debug("-" * 80)
                logger.debug(f"DÉNONYMISÉ: {denonymized_text[:500]}..." if len(denonymized_text) > 500 else f"DÉNONYMISÉ: {denonymized_text}")
                logger.debug("=" * 80)
            
            return denonymized_text
            
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Erreur lors de la dénonymisation: {str(e)}", exc_info=True)
            return response_text  # En cas d'erreur, retourner le texte original
            
        except Exception as e:
            logger.error(f"[Request ID: {request_id}] Erreur lors de la dénonymisation: {str(e)}", exc_info=True)
            return response_text  # En cas d'erreur, retourner le texte original


    def _sanitize_json_string(self, json_str: str) -> str:
        """
        Nettoie et répare une réponse LLM pour en extraire un JSON valide.
        Gère tous les cas : markdown, commentaires, virgules manquantes, formatage.
        """
        logger.info(f"[SANITIZE] 📥 Longueur avant nettoyage: {len(json_str)} caractères")
        
        # ========================================
        # ÉTAPE 1 : NETTOYAGE INITIAL
        # ========================================
        
        # Supprimer BOM et caractères invisibles
        json_str = json_str.replace('\ufeff', '')  # BOM
        json_str = json_str.replace('\u200b', '')  # Zero-width space
        json_str = json_str.replace('\xa0', ' ')   # Non-breaking space
        
        # Supprimer balises markdown
        json_str = re.sub(r'^```(?:json)?\s*', '', json_str, flags=re.MULTILINE)
        json_str = re.sub(r'```\s*$', '', json_str, flags=re.MULTILINE)
        
        # Supprimer commentaires
        json_str = re.sub(r'<!--.*?-->', '', json_str, flags=re.DOTALL)  # HTML
        json_str = re.sub(r'//.*?\n', '\n', json_str)  # JS single line
        json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)  # JS multi line
        
        # Guillemets typographiques → standard
        json_str = json_str.replace('"', '"').replace('"', '"')
        json_str = json_str.replace("'", "'").replace("'", "'")
        json_str = json_str.replace('«', '"').replace('»', '"')
        
        # ========================================
        # ÉTAPE 2 : EXTRACTION DU JSON
        # ========================================
        
        json_start = json_str.find('{')
        json_end = json_str.rfind('}') + 1
        
        if json_start == -1 or json_end == -1:
            logger.error(f"[SANITIZE] ❌ Aucune structure JSON trouvée")
            raise ValueError("No JSON structure found in response")
        
        # Log si texte supprimé
        if json_start > 0:
            removed = json_str[:json_start]
            logger.warning(f"[SANITIZE] ⚠️ Supprimé {len(removed)} chars avant JSON")
        
        json_str = json_str[json_start:json_end]
        
        # ========================================
        # ÉTAPE 3 : NETTOYAGE INTELLIGENT
        # ========================================
        
        # Supprimer \r (Windows)
        json_str = json_str.replace('\r', '')
        
        # Supprimer tabulations
        json_str = json_str.replace('\t', ' ')
        
        # Supprimer espaces multiples (MAIS garder \n dans les strings)
        json_str = re.sub(r' +', ' ', json_str)
        
        # ========================================
        # ÉTAPE 4 : RÉPARATION DES VIRGULES
        # ========================================
        
        # Fix 1: Ajouter virgule après "value" suivi de retour à la ligne et "key"
        # Pattern: "text": "value"\n  "icon" → "text": "value",\n  "icon"
        json_str = re.sub(
            r'("(?:[^"\\]|\\.)*")\s*\n\s*("(?:[^"\\]|\\.)*"\s*:)',
            r'\1,\n\2',
            json_str
        )
        
        # Fix 2: Ajouter virgule après } suivi de \n et "
        json_str = re.sub(r'\}(\s*\n\s*)(")', r'},\1\2', json_str)
        
        # Fix 3: Ajouter virgule après ] suivi de \n et "
        json_str = re.sub(r'\](\s*\n\s*)(")', r'],\1\2', json_str)
        
        # Fix 4: Ajouter virgule après } suivi de \n et {
        json_str = re.sub(r'\}(\s*\n\s*)(\{)', r'},\1\2', json_str)
        
        # Fix 5: Ajouter virgule après ] suivi de \n et {
        json_str = re.sub(r'\](\s*\n\s*)(\{)', r'],\1\2', json_str)
        
        # Fix 6: Ajouter virgule après "value" suivi de whitespace et "key" (sans \n)
        # Cas : "text": "value"  "icon": "x"
        json_str = re.sub(
            r'("(?:[^"\\]|\\.)*")(\s{2,})("(?:[^"\\]|\\.)*"\s*:)',
            r'\1,\2\3',
            json_str
        )
        
        # Fix 7: Supprimer virgules en trop avant } ou ]
        json_str = re.sub(r',(\s*)([}\]])', r'\1\2', json_str)
        
        # Fix 8: Supprimer doubles virgules
        json_str = re.sub(r',\s*,+', ',', json_str)
        
        # ========================================
        # ÉTAPE 5 : VALIDATION STRUCTURE
        # ========================================
        
        json_str = json_str.strip()
        
        if not json_str.startswith('{') or not json_str.endswith('}'):
            logger.error(f"[SANITIZE] ❌ Pas de {{ }} valide")
            logger.error(f"[SANITIZE] Début: {repr(json_str[:100])}")
            logger.error(f"[SANITIZE] Fin: {repr(json_str[-100:])}")
            raise ValueError("JSON doesn't have valid braces")
        
        # Vérifier équilibre accolades/crochets
        open_braces = json_str.count('{')
        close_braces = json_str.count('}')
        open_brackets = json_str.count('[')
        close_brackets = json_str.count(']')
        
        if open_braces != close_braces:
            logger.error(f"[SANITIZE] ❌ Déséquilibre {{}}: {open_braces} vs {close_braces}")
            raise ValueError(f"Unbalanced braces: {open_braces} {{ vs {close_braces} }}")
        
        if open_brackets != close_brackets:
            logger.error(f"[SANITIZE] ❌ Déséquilibre []: {open_brackets} vs {close_brackets}")
            raise ValueError(f"Unbalanced brackets: {open_brackets} [ vs {close_brackets} ]")
        
        logger.info(f"[SANITIZE] ✅ Nettoyage terminé: {len(json_str)} caractères")
        logger.debug(f"[SANITIZE] Début: {repr(json_str[:100])}")
        logger.debug(f"[SANITIZE] Fin: {repr(json_str[-100:])}")
        
        return json_str

    def _extract_location_from_quiz(self) -> tuple:
        """
        Extrait ville ET région en 1 seule requête depuis question_id=26.
        
        Returns:
            tuple: (city, region) ou (None, None) si non trouvé
        
        Exemple:
            ("Paris", "Île-de-France")
        """
        try:
            # Récupérer la session quiz + answer en 1 requête
            self.cursor.execute("""
                SELECT au.answer_value
                FROM quiz_user qu
                JOIN answer_user au ON qu.quiz_session_id = au.quiz_session_id
                WHERE qu.user_id = %s 
                AND qu.quiz_id = %s
                AND au.question_id = 26
                ORDER BY qu.updated_at DESC
                LIMIT 1
            """, (self.user_id, self.quiz_id))
            
            result = self.cursor.fetchone()
            
            if result and result['answer_value']:
                answer_list = json.loads(result['answer_value'])
                
                if answer_list and len(answer_list) > 0:
                    location_str = answer_list[0]  # "Paris,Île-de-France"
                    
                    if ',' in location_str:
                        city, region = location_str.split(',', 1)
                        city = city.strip()
                        region = region.strip()
                        
                        logger.info(f"✅ Extracted location from question 26: {city}, {region}")
                        return (city, region)
                    else:
                        # Cas où il n'y a que la ville sans région
                        city = location_str.strip()
                        logger.info(f"✅ Extracted city from question 26: {city} (no region)")
                        return (city, None)
            
            logger.warning(f"⚠️ No location found in question 26 for user {self.user_id}")
            return (None, None)
            
        except Exception as e:
            logger.error(f"❌ Error extracting location from question 26: {str(e)}", exc_info=True)
            return (None, None)