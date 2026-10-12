"""
Tilto Pro : transcription automatique des enregistrements (Whisper), pour l'admin.

ffmpeg lit chaque partie directement depuis le stockage (URL signée, sans tout
télécharger : une vidéo peut faire 2 Go et Cloud Run n'a que 1 Go de mémoire), en
extrait un audio mono léger découpé en morceaux de 20 minutes (bien sous la limite
de 25 Mo de Whisper), puis Whisper transcrit chaque morceau.

Lancée en arrière-plan à l'envoi du dossier ; relançable depuis /admin/pro.
"""
import glob
import logging
import os
import subprocess
import tempfile
import threading
import time

import requests
from flask import current_app

from services import pro_service

logger = logging.getLogger(__name__)

CHUNK_SECONDS = 20 * 60          # mp3 mono 32 kb/s : ~4,8 Mo par morceau
FFMPEG_TIMEOUT = 30 * 60
WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"


def _source_for(path):
    """Ce que lit ffmpeg : une URL signée vers la partie stockée (remplaçable en test)."""
    return pro_service.signed_url(path, minutes=60)


def _to_chunks(source, workdir):
    """Audio ou vidéo → morceaux mp3 mono 16 kHz de 20 minutes."""
    pattern = os.path.join(workdir, 'morceau%03d.mp3')
    subprocess.run(
        ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-xerror', '-y', '-i', source,
         '-vn', '-ac', '1', '-ar', '16000', '-b:a', '32k',
         '-f', 'segment', '-segment_time', str(CHUNK_SECONDS), '-reset_timestamps', '1', pattern],
        check=True, timeout=FFMPEG_TIMEOUT, capture_output=True,
    )
    # Le découpage peut laisser un dernier morceau vide : Whisper le refuserait
    chunks = [c for c in sorted(glob.glob(os.path.join(workdir, 'morceau*.mp3'))) if os.path.getsize(c) > 2000]
    if not chunks:
        raise RuntimeError("aucune piste audio trouvée dans le fichier")
    return chunks


def _whisper(path):
    """Transcrit un morceau, avec nouvelles tentatives si OpenAI limite le débit."""
    api_key = current_app.config.get('OPENAI_API_KEY')
    if not api_key:
        raise RuntimeError("clé OpenAI non configurée")
    for attempt in range(4):
        with open(path, 'rb') as audio:
            response = requests.post(
                WHISPER_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={'file': (os.path.basename(path), audio, 'audio/mpeg'),
                       'model': (None, 'whisper-1'), 'language': (None, 'fr'),
                       'response_format': (None, 'json')},
                timeout=300,
            )
        if response.status_code == 429 and attempt < 3:
            time.sleep(2 ** attempt * 5)
            continue
        if not response.ok:
            logger.error(f"Whisper (Tilto Pro) {response.status_code} : {response.text[:500]}")
            raise RuntimeError(f"Whisper a répondu {response.status_code}")
        return (response.json().get('text') or '').strip()
    raise RuntimeError("limite de débit OpenAI atteinte")


def transcribe(client_id):
    """Transcrit toutes les parties de l'enregistrement du dossier et enregistre le texte."""
    client = pro_service.get_client(client_id)
    if not client or not client.get('audio_path'):
        return
    parts = [client['audio_path']] + [e['p'] for e in client['audio_extra']]
    pro_service.set_transcript_status(client_id, 'en_cours')
    try:
        texts = []
        for number, path in enumerate(parts, start=1):
            with tempfile.TemporaryDirectory() as workdir:
                text = ' '.join(_whisper(c) for c in _to_chunks(_source_for(path), workdir))
            texts.append(f"--- Partie {number} ---\n{text}" if len(parts) > 1 else text)
        pro_service.save_transcript(client_id, '\n\n'.join(texts))
        logger.info(f"Tilto Pro : transcription prête (dossier {client_id})")
        from routes.pro import _notify_slack
        _notify_slack(f"📝 Transcription prête : {client['label']} (dossier {client_id})")
    except Exception as e:
        logger.error(f"Transcription Tilto Pro impossible (dossier {client_id}): {e}", exc_info=True)
        message = e.stderr.decode(errors='replace')[-200:] if isinstance(e, subprocess.CalledProcessError) and e.stderr else str(e)
        pro_service.set_transcript_status(client_id, 'erreur', message[:250])
        from routes.pro import _notify_slack
        _notify_slack(f"🚨 *Tilto Pro · transcription échouée* : {client['label']} (dossier {client_id})\n```{message[:300]}```", channel='monitoring')


def start(client_id):
    """Lance la transcription en arrière-plan (le coach n'attend pas)."""
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            transcribe(client_id)

    pro_service.set_transcript_status(client_id, 'en_cours')
    threading.Thread(target=run, daemon=True, name=f'pro-transcription-{client_id}').start()
