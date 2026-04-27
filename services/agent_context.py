"""
AgentContext — couche de contexte partagée entre agents.

Bundle d'état, knowledge base, tool registry, LLM clients et telemetry
consommé de manière uniforme par tous les agents Tilto.

Rationale
─────────
Sans context layer, chaque agent fait ses propres fetches DB, gère sa
propre télémétrie, instancie ses propres clients LLM, et a son propre
format de mémoire. Quand on a 5+ agents, ça devient un bazar :
- duplication de code
- formats de logs incohérents
- coûts API non agrégés
- bugs subtils quand un agent parse une donnée différemment d'un autre

L'AgentContext résout ce problème en exposant **un seul point d'entrée**
pour tout ce qu'un agent consomme :
- user state (profil, localisation, historique conversation)
- knowledge base (prompts, critères de validation, templates)
- tool registry (config web_search, clients HTTP)
- LLM clients (writer Anthropic, critic OpenAI)
- telemetry (tokens, coût USD, audit trail)

Conventions
───────────
- Une instance d'AgentContext = un job d'agent (pas réutilisable entre jobs)
- Les properties lazy fetch la donnée 1 seule fois (cached_property)
- Les méthodes write modifient l'état interne (telemetry surtout)
- Pas de logique métier ici — uniquement plumbing partagé

Comment l'utiliser
──────────────────
    ctx = AgentContext(cursor=cur, user_id=42, quiz_id='pack_clarte')
    profile = ctx.user_profile             # lazy DB fetch
    city, region = ctx.location            # lazy DB fetch
    criteria = ctx.get_validation_criteria('career_path_v4')

    # Telemetry
    ctx.track_usage(
        provider='anthropic', model='claude-sonnet-4-5-20250929',
        input_tokens=2453, output_tokens=2812, web_search_uses=4,
        label='gen[xxx]'
    )

    summary = ctx.get_usage_summary()      # à la fin du job
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Dict, Optional, Tuple

from flask import current_app

logger = logging.getLogger(__name__)


# Pricing public Anthropic / OpenAI (USD per 1M tokens). À ajuster si tarifs changent.
LLM_PRICING: Dict[str, Dict[str, float]] = {
    # Anthropic
    'claude-sonnet-4-5-20250929': {'input': 3.00, 'output': 15.00},
    'claude-sonnet-4-20250514':   {'input': 3.00, 'output': 15.00},
    'claude-haiku-4-5':           {'input': 1.00, 'output': 5.00},
    # OpenAI
    'gpt-4o-mini':                {'input': 0.15, 'output': 0.60},
    'gpt-4o':                     {'input': 2.50, 'output': 10.00},
}

# Tarif outil web_search Anthropic (~10 USD / 1000 recherches)
WEB_SEARCH_COST_PER_USE: float = 0.01


@dataclass
class AgentContext:
    """
    Contexte partagé entre agents Tilto.
    Une instance = un job. Voir docstring de module pour la rationale.
    """
    cursor: Any
    user_id: int
    quiz_id: str

    # Telemetry — état mutable accumulé tout au long du job
    token_usage: Dict[str, Any] = field(default_factory=lambda: {
        'calls': 0,
        'anthropic_input_tokens': 0,
        'anthropic_output_tokens': 0,
        'openai_input_tokens': 0,
        'openai_output_tokens': 0,
        'web_search_uses': 0,
        'cost_usd': 0.0,
        'per_call': []
    })

    # Cache interne pour les LLM clients lazy-init
    _anthropic_client: Optional[Any] = field(default=None, repr=False)
    _openai_client: Optional[Any] = field(default=None, repr=False)

    # ─────────────────────────────────────────────────────────────
    # User state — lazy-loaded depuis la DB
    # ─────────────────────────────────────────────────────────────

    @cached_property
    def location(self) -> Tuple[Optional[str], Optional[str]]:
        """
        Localisation du user (city, region) depuis question_id=26.
        Format DB : answer_value = ["Paris,Île-de-France"] ou ["Paris"].
        """
        try:
            self.cursor.execute("""
                SELECT au.answer_value
                FROM quiz_user qu
                JOIN answer_user au ON qu.quiz_session_id = au.quiz_session_id
                WHERE qu.user_id = %s AND qu.quiz_id = %s AND au.question_id = 26
                ORDER BY qu.updated_at DESC LIMIT 1
            """, (self.user_id, self.quiz_id))
            row = self.cursor.fetchone()
            if not row or not row['answer_value']:
                return (None, None)

            answer_list = json.loads(row['answer_value'])
            if not answer_list:
                return (None, None)

            location_str = answer_list[0]
            if ',' in location_str:
                city, region = location_str.split(',', 1)
                return (city.strip(), region.strip())
            return (location_str.strip(), None)

        except Exception as e:
            logger.error(f"[AgentContext] Erreur location user={self.user_id}: {e}")
            return (None, None)

    # ─────────────────────────────────────────────────────────────
    # Knowledge base — config métier éditable en DB
    # ─────────────────────────────────────────────────────────────

    def get_validation_criteria(self, step_id: str) -> Optional[str]:
        """Critères de validation du critic pour un step donné."""
        try:
            self.cursor.execute("""
                SELECT validation_criteria FROM quiz_result
                WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
            """, (self.quiz_id, step_id))
            row = self.cursor.fetchone()
            return row['validation_criteria'] if row else None
        except Exception as e:
            logger.error(f"[AgentContext] Erreur criteria step={step_id}: {e}")
            return None

    def get_step_config(self, step_id: str) -> Optional[Dict[str, Any]]:
        """
        Configuration complète d'un step : system, instructions, knowledge.
        Utilisé par les writers pour construire leurs prompts.
        """
        try:
            self.cursor.execute("""
                SELECT prompt_system, prompt_instruction, prompt_knowledge,
                       validation_criteria, template_html
                FROM quiz_result
                WHERE quiz_id = %s AND result_step_id = %s AND is_active = TRUE
            """, (self.quiz_id, step_id))
            return self.cursor.fetchone()
        except Exception as e:
            logger.error(f"[AgentContext] Erreur step config step={step_id}: {e}")
            return None

    # ─────────────────────────────────────────────────────────────
    # Tool registry
    # ─────────────────────────────────────────────────────────────

    def build_web_search_tool(self, max_uses: int = 5) -> Dict[str, Any]:
        """
        Construit la config de l'outil web_search Anthropic avec
        géolocalisation injectée depuis location. Retournable directement
        dans api_params['tools'].
        """
        city, region = self.location
        if city and region:
            user_location = {
                "type": "approximate", "city": city, "region": region,
                "country": "FR", "timezone": "Europe/Paris"
            }
        elif city:
            user_location = {
                "type": "approximate", "city": city,
                "country": "FR", "timezone": "Europe/Paris"
            }
        else:
            user_location = {
                "type": "approximate", "country": "FR", "timezone": "Europe/Paris"
            }

        return {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_uses,
            "user_location": user_location,
        }

    # ─────────────────────────────────────────────────────────────
    # LLM clients — lazy-init, partagés entre agents qui partagent un ctx
    # ─────────────────────────────────────────────────────────────

    @property
    def anthropic_client(self):
        if self._anthropic_client is None:
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])
        return self._anthropic_client

    @property
    def openai_client(self):
        if self._openai_client is None:
            api_key = current_app.config.get('OPENAI_API_KEY')
            if not api_key:
                return None
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=api_key)
        return self._openai_client

    # ─────────────────────────────────────────────────────────────
    # Long-term user context — vue 360° persistée
    # ─────────────────────────────────────────────────────────────

    @cached_property
    def user_context_service(self):
        """
        Vue 360° persistée du user (historique bilans, commandes, bookings, etc).
        À distinguer du contexte court-terme (location, conversation) qui est
        directement sur ce AgentContext.

        Lazy : le service est instancié seulement si un agent appelle
        `ctx.user_context_service.get_summary()` ou `.get_full_context()`.
        """
        from services.user_context_service import UserContextService
        return UserContextService(cursor=self.cursor, user_id=self.user_id)

    def get_user_summary(self) -> Dict[str, Any]:
        """Raccourci : résumé condensé du user (5-6 champs clés)."""
        return self.user_context_service.get_summary()

    # ─────────────────────────────────────────────────────────────
    # Telemetry — accumulateur de coût/tokens tout au long du job
    # ─────────────────────────────────────────────────────────────

    def track_usage(self, provider: str, model: str,
                    input_tokens: int, output_tokens: int,
                    web_search_uses: int = 0, label: str = '') -> None:
        """
        Accumule l'usage d'un appel LLM et calcule le coût USD estimé.
        À appeler depuis chaque wrapper LLM (writer, critic, futurs agents).
        """
        pricing = LLM_PRICING.get(model)
        if not pricing:
            logger.warning(f"[AgentContext] Pas de pricing pour {model} — coût=0")
            cost = 0.0
        else:
            cost = (input_tokens * pricing['input'] + output_tokens * pricing['output']) / 1_000_000
        cost += web_search_uses * WEB_SEARCH_COST_PER_USE

        self.token_usage['calls'] += 1
        self.token_usage['cost_usd'] = round(self.token_usage['cost_usd'] + cost, 4)
        if provider == 'anthropic':
            self.token_usage['anthropic_input_tokens'] += input_tokens
            self.token_usage['anthropic_output_tokens'] += output_tokens
        elif provider == 'openai':
            self.token_usage['openai_input_tokens'] += input_tokens
            self.token_usage['openai_output_tokens'] += output_tokens
        self.token_usage['web_search_uses'] += web_search_uses

        self.token_usage['per_call'].append({
            'label': label, 'provider': provider, 'model': model,
            'input_tokens': input_tokens, 'output_tokens': output_tokens,
            'web_search_uses': web_search_uses, 'cost_usd': round(cost, 4),
        })

        logger.info(f"[USAGE] {label or provider} {model} | "
                    f"in={input_tokens} out={output_tokens} "
                    f"web={web_search_uses} | ${cost:.4f}")

    def get_usage_summary(self) -> Dict[str, Any]:
        """Snapshot du coût total + détail par appel pour monitoring."""
        return dict(self.token_usage)
