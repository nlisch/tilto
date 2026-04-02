"""
Service de coaching conversationnel dynamique.
Claude mène l'entretien comme un vrai coach : questions simples,
adaptées aux réponses, couvre les thèmes naturellement.
"""

import json
import re
import logging
from flask import current_app
from anthropic import Anthropic

logger = logging.getLogger(__name__)

COACH_SYSTEM_PROMPT = """Tu es Claire, coach bilan de compétences chez Tilto. Tu mènes un entretien vocal pour comprendre en profondeur la situation pro de quelqu'un.

THÈMES À COUVRIR (tu dois récolter des infos sur au moins 3 de ces 4) :
- SITUATION : parcours, poste actuel, secteur
- RESSENTI : ce qui plaît, ce qui pèse, pourquoi la personne est là
- ASPIRATIONS : envies, rêves, ce qui ferait vibrer
- CONTRAINTES : géo, salaire, disponibilité

TECHNIQUE :
1. PREMIÈRE QUESTION (déjà posée pour toi) : "Qu'est-ce qui t'amène aujourd'hui ?" — la personne parle de ce qu'elle veut. ÉCOUTE.
2. QUESTIONS SUIVANTES : Rebondis TOUJOURS sur ce que la personne vient de dire. Puis élargis vers un thème non couvert.
   → "Tu parles de [X], ça m'intéresse. Et si tu devais décrire [angle concret lié à un thème manquant] ?"
   → Formule des questions qui invitent à RACONTER : "Raconte-moi...", "Décris-moi...", "Parle-moi de..."
   → JAMAIS de question fermée (oui/non)
   → Si la réponse est courte (< 2 phrases), relance avec un angle différent au lieu de changer de sujet
3. INTELLIGENCE : Avant chaque réponse, analyse mentalement quels thèmes tu as déjà couverts et lesquels manquent. Oriente ta question vers ce qui manque.

QUAND TERMINER :
- Dès que tu as couvert 3 thèmes avec des réponses suffisantes → done=true
- Maximum 5 échanges total. Sois efficace, pas bavarde.
- Si la personne donne une réponse riche qui couvre plusieurs thèmes d'un coup, avance plus vite

TONALITÉ :
- Professionnelle mais chaleureuse — comme un vrai coach bilan de compétences
- Tutoie mais avec respect. INTERDICTION ABSOLUE d'utiliser ces mots : kiffer, kiffe, bouffe, taff, galère, péter un câble, craquer, relou, chiant, naze, merdique, vénère, ouf, trop bien, stylé, grave. Jamais d'argot.
- Vocabulaire posé : "ce qui te pèse", "ce qui t'anime", "ce qui te donne de l'énergie", "ce qui t'attire", "ce qui compte pour toi"
- NE RÉPÈTE PAS les mots familiers de la personne — reformule avec un vocabulaire professionnel
- L'insight montre que tu as COMPRIS quelque chose de personnel (pas "merci", pas générique)
- Le summary reprend les points clés concrets avec des mots de la personne

FORMAT JSON strict :
{"question": "ta question (max 2 phrases)", "insight": "feedback personnel 10 mots max", "done": false, "covered": ["PARCOURS", "RESSENTI"], "nudges": ["angle 1 en 3-5 mots", "angle 2", "angle 3"]}

Les nudges sont 3 angles concrets et personnalisés que la personne pourrait aborder dans sa réponse. Ils apparaissent progressivement pendant qu'elle parle pour l'aider à développer. Exemples :
- Si tu demandes sur le ressenti : ["Ce qui te pèse le plus", "Un moment positif récent", "Ce qui manque"]
- Si tu demandes sur les aspirations : ["Ton métier rêvé", "Ce qui te fait vibrer", "Un domaine qui t'attire"]
- Adapte-les au contexte de la conversation — utilise les mots de la personne

Quand c'est fini :
{"question": null, "insight": "dernier feedback", "done": true, "summary": "résumé 2-3 phrases avec les mots de la personne", "covered": ["PARCOURS", "RESSENTI", "ASPIRATIONS", "FORCES"]}"""

FIRST_QUESTION = "Qu'est-ce qui t'amène aujourd'hui ?"


class ConversationCoachService:
    """Coach IA qui mène l'entretien dynamiquement."""

    @staticmethod
    def next_step(conversation: list) -> dict:
        """
        Génère la prochaine question du coach basée sur l'historique.

        Args:
            conversation: [{role: 'coach'|'user', text: '...'}]

        Returns:
            {"question": "...", "insight": "...", "done": false}
            ou {"question": null, "insight": "...", "done": true, "summary": "..."}
        """
        if not conversation:
            return {
                "question": FIRST_QUESTION,
                "insight": None,
                "done": False,
                "nudges": ["Ta situation actuelle", "Ce qui te tracasse", "Ce que tu cherches"]
            }

        try:
            client = Anthropic(api_key=current_app.config['ANTHROPIC_API_KEY'])

            # Build messages from conversation history
            messages = []
            for msg in conversation:
                role = "assistant" if msg.get("role") == "coach" else "user"
                messages.append({"role": role, "content": msg["text"]})

            # JSON prefill
            messages.append({"role": "assistant", "content": "{"})

            response = client.messages.create(
                model=current_app.config.get('CONVERSATION_EVAL_MODEL', 'claude-haiku-4-5-20251001'),
                max_tokens=400,
                temperature=0.6,
                system=COACH_SYSTEM_PROMPT,
                messages=messages
            )

            raw = "{" + response.content[0].text.strip()
            logger.info(f"[Coach] Raw: {raw[:300]}")

            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if not json_match:
                logger.warning(f"[Coach] No JSON in: {raw[:200]}")
                return _fallback()

            result = json.loads(json_match.group())

            if "done" not in result:
                return _fallback()

            user_msgs = sum(1 for m in conversation if m.get("role") == "user")
            covered = result.get("covered", [])
            covered_count = len(covered) if isinstance(covered, list) else 0

            # Don't let Claude finish too early — need 4+ themes covered
            if result.get("done") and covered_count < 3 and user_msgs < 5:
                logger.info(f"[Coach] Overriding done=true, only {covered_count} themes covered")
                result["done"] = False
                result["question"] = result.get("question") or "Et si on parlait de ce qui te ferait vraiment vibrer ?"

            # Safety cap at 7 exchanges
            if user_msgs >= 5 and not result.get("done"):
                result["done"] = True
                result["question"] = None
                if not result.get("summary"):
                    result["summary"] = "Merci pour cet échange riche !"

            # Clean slang from question/insight (safety net)
            BANNED = ['kiffer', 'kiffe', 'kiffé', 'bouffe', 'taff', 'galère', 'relou', 'chiant', 'merdique', 'vénère', 'péter']
            for field in ('question', 'insight', 'summary'):
                if result.get(field):
                    for word in BANNED:
                        if word in result[field].lower():
                            # Replace with professional equivalent
                            result[field] = result[field].replace(word, 'apprécier' if 'kif' in word else 'travail' if word == 'taff' else 'difficulté')
                            logger.info(f"[Coach] Cleaned banned word '{word}' from {field}")

            # Nudge closed questions to be open
            if result.get("question") and not result["done"]:
                q_lower = result["question"].lower().strip()
                if q_lower.startswith(("est-ce que", "est ce que", "tu aimes", "tu veux", "c'est ", "ça te")):
                    result["question"] = result["question"].rstrip("?") + " ? Raconte-moi un peu."

            logger.info(f"[Coach] done={result.get('done')}, question={str(result.get('question') or '')[:50]}")
            return result

        except json.JSONDecodeError as e:
            logger.error(f"[Coach] JSON error: {e}")
            return _fallback()

        except Exception as e:
            logger.error(f"[Coach] Error: {e}", exc_info=True)
            return _fallback()


def _fallback():
    """Fallback si Claude échoue — on termine proprement."""
    return {
        "question": None,
        "insight": "Merci pour ce partage !",
        "done": True,
        "summary": "Merci pour cet échange !"
    }
