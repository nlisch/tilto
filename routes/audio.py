from flask import Blueprint, request, jsonify
from flask_login import login_required
import os
import uuid
import tempfile
from werkzeug.datastructures import FileStorage
import logging
from services.audio_service import AudioService
from decorators import ajax_login_required

logger = logging.getLogger(__name__)

audio_bp = Blueprint('audio', __name__)


@audio_bp.route('/api/init-audio-upload', methods=['POST'])
@login_required
@ajax_login_required
def init_audio_upload():
    """Initialise une session d'upload audio et retourne un identifiant de session"""
    try:
        # Générer un ID de session unique
        session_id = str(uuid.uuid4())
        
        # Créer un répertoire temporaire pour cette session si nécessaire
        temp_dir = os.path.join(tempfile.gettempdir(), 'audio_uploads', session_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        logger.info(f"Session d'upload audio initialisée: {session_id}")
        
        return jsonify({"session_id": session_id, "status": "initialized"}), 200
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de l'upload audio: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@audio_bp.route('/api/upload-audio-chunk', methods=['POST'])
@login_required
def upload_audio_chunk():
    """Reçoit et stocke un morceau de fichier audio"""
    try:
        session_id = request.form.get('session_id')
        chunk_index = request.form.get('chunk_index')
        chunk = request.files.get('chunk')
        
        if not all([session_id, chunk_index, chunk]):
            return jsonify({"error": "Données manquantes"}), 400
        
        # Créer le répertoire pour cette session si nécessaire
        temp_dir = os.path.join(tempfile.gettempdir(), 'audio_uploads', session_id)
        os.makedirs(temp_dir, exist_ok=True)
        
        # Sauvegarder le chunk dans un fichier temporaire
        chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index}.webm")
        chunk.save(chunk_path)
        
        logger.info(f"Chunk {chunk_index} sauvegardé pour la session {session_id}")
        
        return jsonify({
            "status": "chunk_received", 
            "chunk_index": chunk_index,
            "session_id": session_id
        }), 200
    except Exception as e:
        logger.error(f"Erreur lors de l'upload du chunk: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@audio_bp.route('/api/finalize-audio-upload', methods=['POST'])
@login_required
def finalize_audio_upload():
    """Finalise l'upload et lance la transcription"""
    try:
        session_id = request.form.get('session_id')
        
        if not session_id:
            return jsonify({"error": "ID de session manquant"}), 400
        
        # Répertoire contenant les chunks
        temp_dir = os.path.join(tempfile.gettempdir(), 'audio_uploads', session_id)
        
        if not os.path.exists(temp_dir):
            return jsonify({"error": "Session non trouvée"}), 404
        
        # Fusionner les chunks en un seul fichier audio
        chunks = sorted([f for f in os.listdir(temp_dir) if f.startswith('chunk_')],
                        key=lambda x: int(x.split('_')[1].split('.')[0]))
        
        if not chunks:
            return jsonify({"error": "Aucun chunk trouvé"}), 400
        
        # Fichier final fusionné
        final_audio_path = os.path.join(temp_dir, "final_audio.webm")
        
        with open(final_audio_path, 'wb') as outfile:
            for chunk_file in chunks:
                with open(os.path.join(temp_dir, chunk_file), 'rb') as infile:
                    outfile.write(infile.read())
        
        logger.info(f"Fusion des chunks terminée pour la session {session_id}")
        
        # Créer un objet fichier à partir du chemin
        with open(final_audio_path, 'rb') as audio_file:
            file_storage = FileStorage(
                stream=audio_file,
                filename="final_audio.webm",
                content_type="audio/webm"
            )
            
            # Utiliser le service de transcription
            result = AudioService.transcribe_with_whisper(file_storage)
        
        # Nettoyer les fichiers temporaires après traitement
        try:
            for chunk_file in chunks:
                os.remove(os.path.join(temp_dir, chunk_file))
            os.remove(final_audio_path)
            os.rmdir(temp_dir)
            logger.info(f"Nettoyage des fichiers temporaires terminé pour la session {session_id}")
        except Exception as cleanup_error:
            logger.warning(f"Erreur lors du nettoyage des fichiers: {cleanup_error}")
        
        if result.get('success'):
            return jsonify({
                "status": "completed", 
                "transcript": result.get('transcript', '')
            }), 200
        else:
            return jsonify({
                "status": "error", 
                "error": result.get('error', "Erreur inconnue lors de la transcription")
            }), 500
            
    except Exception as e:
        logger.error(f"Erreur lors de la finalisation de l'upload: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@audio_bp.route('/api/save-quiz-audios', methods=['POST'])
@login_required
@ajax_login_required
def save_quiz_audios():
    """Sauvegarde les audios du quiz et retourne les URLs avec gestion dev/prod"""
    try:
        quiz_id = request.form.get('quiz_id')
        audio_files = request.files
        
        if not quiz_id:
            return jsonify({"error": "Quiz ID manquant"}), 400
        
        # Déterminer l'environnement pour les logs
        env = 'production' if bool(current_app.config.get('GOOGLE_CLOUD_PROJECT')) else 'development'
        logger.info(f"Sauvegarde des audios quiz en environnement: {env}")
        
        audio_results = {}
        
        # Traiter chaque fichier audio
        for field_name, audio_file in audio_files.items():
            if field_name.startswith('audio_q'):
                question_id = field_name.replace('audio_q', '')
                
                logger.info(f"Traitement audio question {question_id}, taille: {audio_file.content_length}")
                
                # Lire le contenu du fichier
                audio_blob = audio_file.read()
                
                # Sauvegarder dans le cloud avec gestion dev/prod
                result = AudioService.save_quiz_audio_to_cloud(
                    audio_blob, quiz_id, question_id, current_user.id
                )
                
                if result['success']:
                    audio_results[question_id] = {
                        'url': result['url'],
                        'filename': result['filename'],
                        'environment': result['environment']
                    }
                    logger.info(f"Audio Q{question_id} sauvegardé avec succès en {result['environment']}")
                else:
                    logger.error(f"Erreur sauvegarde audio Q{question_id}: {result['error']}")
                    audio_results[question_id] = None
        
        return jsonify({
            'success': True,
            'audio_urls': audio_results,
            'environment': env,
            'total_saved': len([r for r in audio_results.values() if r is not None])
        }), 200
        
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde des audios du quiz: {str(e)}")
        return jsonify({"error": str(e)}), 500