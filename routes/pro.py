"""
Tilto Pro : inscription depuis la landing, espace coach et back-office.

Le coach s'inscrit avec son email et choisit comment commencer son dossier offert :
en enregistrant un échange dans la page (prospect, client ou lui-même) ou à partir d'un enregistrement
existant. Une page courte (fiche + dépôt des fichiers) mène à « Envoyer en analyse ».
L'analyse (fichier HTML) est déposée à la main depuis /admin/pro.
"""
import logging
import re
from datetime import timedelta
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required, login_user

from decorators import admin_required
from extensions import limiter
from models import User
from services import pro_service
from services.pro_service import DRAFT_STATUSES, FICHE_FIELDS, KIND_LABELS

logger = logging.getLogger(__name__)

pro_bp = Blueprint('pro', __name__)

# Un coach reste connecté 30 jours (il revient déposer l'audio après sa séance)
PRO_REMEMBER = timedelta(days=30)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BLOCKED_DOMAINS = {
    'mailinator.com', 'tempmail.com', 'guerrillamail.com',
    'yopmail.com', 'throwaway.email', 'test.com', 'example.com',
}


def _notify_slack(message, channel='leads'):
    try:
        from services import slack_service, SLACK_AVAILABLE
        if SLACK_AVAILABLE and slack_service:
            slack_service.send_notification(message, channel=channel)
    except Exception as e:
        logger.error(f"Slack Tilto Pro (non bloquant): {e}")


def _alert_tech(context, error):
    """Souci technique côté coach : log + Slack #monitoring (pour réagir vite)."""
    logger.error(f"Tilto Pro · {context} : {error}")
    detail = str(error)[:400]
    who = getattr(current_user, 'email', None) if current_user and current_user.is_authenticated else None
    _notify_slack(f"🚨 *Tilto Pro · {context}*{chr(10) + '📧 ' + who if who else ''}\n```{detail}```", channel='monitoring')


def _alert_email(subject, lines, link=None):
    """Copie par email des alertes importantes (PRO_ALERT_EMAIL, contact@tilto.ai par défaut)."""
    try:
        from markupsafe import escape
        from services.email_service import send_email
        to = current_app.config.get('PRO_ALERT_EMAIL') or 'contact@tilto.ai'
        body = ''.join(f'<p style="margin:0 0 8px;font-size:15px;color:#333;">{escape(l)}</p>' for l in lines)
        if link:
            body += f'<p style="margin:16px 0 0;"><a href="{escape(link)}" style="color:#A11857;font-weight:700;">Ouvrir dans l\'admin</a></p>'
        result = send_email(to_email=to, subject=f"[Tilto Pro] {subject}", html_content=body)
        if not result.get('success', False):
            logger.error(f"Email d'alerte Tilto Pro non envoyé : {result.get('message')}")
    except Exception as e:
        logger.error(f"Email d'alerte Tilto Pro impossible (non bloquant): {e}")


def _alert_recording(dossier, what):
    """Un enregistrement vient d'arriver : Slack + email, pour réagir vite."""
    link = url_for('pro.admin_account', account_id=dossier['pro_account_id'], _external=True)
    coach = pro_service.get_coach_email(dossier['pro_account_id'])
    label = dossier['label'] if dossier['label'] not in pro_service.DEFAULT_LABELS else f"dossier {dossier['id']}"
    _notify_slack(f"🎙️ *Enregistrement reçu* : {what}\n📧 {coach}\n👤 {label} (pas encore envoyé en analyse)\n🔗 {link}")
    _alert_email(f"Enregistrement reçu de {coach}", [f"{what}", f"Coach : {coach}", f"Dossier : {label} (pas encore envoyé en analyse)"], link)


@pro_bp.errorhandler(500)
def _pro_server_error(e):
    """Erreur inattendue dans l'espace Pro : alerte #monitoring, puis la page d'erreur du site."""
    original = getattr(e, 'original_exception', None) or e
    _alert_tech(f"erreur serveur sur {request.method} {request.path}", repr(original))
    return render_template('errors/500.html'), 500


def pro_required(view):
    """Connexion + compte Pro. Le compte est disponible dans g.pro_account."""
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        account = pro_service.get_account_by_user(current_user.id)
        if not account:
            return redirect(url_for('tilto_pro'))
        g.pro_account = account
        return view(*args, **kwargs)
    return wrapper


@pro_bp.app_context_processor
def inject_pro_nav():
    """Nav (base.html) : lien « Espace Pro », et « Mes pistes » seulement si le coach
    a aussi une analyse perso."""
    if not current_user.is_authenticated:
        return {'pro_nav': None}
    if 'pro_nav' not in g:
        is_pro = pro_service.is_pro_user(current_user.id)
        try:
            show_personal = not is_pro or pro_service.has_personal_analysis(current_user.id)
        except Exception:
            show_personal = True
        g.pro_nav = {'is_pro': is_pro, 'show_personal': show_personal}
    return {'pro_nav': g.pro_nav}


# ─── Inscription (landing /pro) ─────────────────────────────────────────────

def _client_ip():
    return (request.headers.get('X-Forwarded-For') or request.remote_addr or '').split(',')[0].strip()[:45]


def _email_error(email):
    if not EMAIL_RE.match(email) or len(email) > 120:
        return 'Merci de renseigner un email valide.'
    if email.split('@')[-1] in BLOCKED_DOMAINS:
        return 'Merci d\'utiliser votre email professionnel.'
    return None


def _register(email, source, company=None, slack_extra=''):
    """Parcours commun aux landings /pro et /pro/cabinets.

    Email nouveau : compte créé, connexion immédiate, redirection vers l'espace Pro
    (l'email d'accès sert à revenir plus tard). Email déjà connu : on n'ouvre pas de
    session sur la seule foi de l'email, l'espace s'active au clic sur le lien reçu.
    """
    if current_user.is_authenticated:
        # Déjà connecté : pas de bascule silencieuse vers un autre compte
        if (current_user.email or '').lower() != email:
            return jsonify({'success': False, 'message':
                            f"Vous êtes connecté avec {current_user.email}. Déconnectez-vous pour utiliser une autre adresse."}), 400
        is_new_pro = not pro_service.get_account_by_user(current_user.id)
        pro_service.create_account(current_user.id, source, company)
        if is_new_pro:
            _notify_slack(f"🧑‍💼 *Nouveau compte Tilto Pro* (compte Tilto existant)\n📧 {email}\n📍 {source}{slack_extra}")
        return jsonify({'success': True, 'mode': 'redirect',
                        'redirect': url_for('pro.welcome') if is_new_pro else url_for('pro.dashboard')})

    existing = pro_service.get_user_by_email(email)
    if existing:
        user_id = existing['user_id']
        is_new_pro = pro_service.get_account_by_user(user_id) is None
        if company and not is_new_pro:
            pro_service.create_account(user_id, source, company)  # enregistre le cabinet
        _send_access_email(email, user_id, is_new=is_new_pro, source=source)
        return jsonify({'success': True, 'mode': 'check_email'})

    user_id = pro_service.create_user(email)
    pro_service.create_account(user_id, source, company)
    login_user(User.get_by_id(user_id), remember=True, duration=PRO_REMEMBER)
    _send_access_email(email, user_id, is_new=True, source=source)
    _notify_slack(f"🧑‍💼 *Nouveau compte Tilto Pro*\n📧 {email}\n📍 {source}{slack_extra}")
    logger.info(f"Tilto Pro : compte créé pour {email}")
    return jsonify({'success': True, 'mode': 'redirect', 'redirect': url_for('pro.welcome')})


@pro_bp.route('/pro/inscription', methods=['POST'])
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def signup():
    email = (request.form.get('email') or '').strip().lower()
    source = (request.form.get('source') or 'tilto_pro_landing')[:100]

    # Honeypot : on fait comme si tout allait bien
    if (request.form.get('website') or '').strip():
        return jsonify({'success': True, 'mode': 'check_email'})
    error = _email_error(email)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    try:
        try:
            pro_service.record_lead(email, source, _client_ip())
        except Exception as e:
            logger.warning(f"pro_leads non mis à jour pour {email}: {e}")
        return _register(email, source)
    except Exception as e:
        logger.error(f"Inscription Tilto Pro impossible pour {email}: {e}", exc_info=True)
        _alert_tech(f"inscription impossible ({email})", repr(e))
        return jsonify({'success': False, 'message': 'Une erreur est survenue. Réessayez dans un instant.'}), 500


PILOT = {'dossiers': 5, 'price': 149}


@pro_bp.route('/pro/cabinets')
def cabinets():
    """Landing des cabinets d'outplacement : pilote de 5 dossiers."""
    return render_template('pages/pro_cabinets.html', has_example=pro_service.has_example(),
                           pilot=PILOT)


@pro_bp.route('/pro/cabinets/pilote', methods=['POST'])
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def pilot_request():
    """Demande de pilote : compte Pro créé tout de suite, facture envoyée à la main
    (l'admin ajoute les 5 dossiers depuis /admin/pro une fois le paiement reçu)."""
    email = (request.form.get('email') or '').strip().lower()
    company = ' '.join((request.form.get('cabinet') or '').split())[:120]
    source = (request.form.get('source') or 'tilto_pro_cabinets')[:100]

    if (request.form.get('website') or '').strip():
        return jsonify({'success': True, 'mode': 'check_email'})
    if not company:
        return jsonify({'success': False, 'message': 'Indiquez le nom de votre cabinet.'}), 400
    error = _email_error(email)
    if error:
        return jsonify({'success': False, 'message': error}), 400

    try:
        notes = f"Pilote {PILOT['dossiers']} dossiers {PILOT['price']} € HT demandé : {company}"
        try:
            pro_service.record_lead(email, source, _client_ip(), activite='cabinet', notes=notes)
        except Exception as e:
            logger.warning(f"pro_leads non mis à jour pour {email}: {e}")
        _notify_slack(
            f"💼 *Pilote cabinet demandé* ({PILOT['dossiers']} dossiers, {PILOT['price']} € HT) : facture à envoyer\n"
            f"🏢 {company}\n📧 {email}\n➕ Ajouter les dossiers une fois payé : {url_for('pro.admin', _external=True)}"
        )
        response = _register(email, source, company=company, slack_extra=f"\n🏢 {company} (pilote cabinet)")
        if not isinstance(response, tuple) and (response.get_json() or {}).get('mode') == 'redirect':
            flash(f"Demande de pilote reçue pour {company} : nous vous envoyons la facture et le contrat RGPD par email. "
                  "Votre premier dossier est déjà disponible.", 'success')
        return response
    except Exception as e:
        logger.error(f"Demande de pilote impossible pour {email}: {e}", exc_info=True)
        _alert_tech(f"demande de pilote impossible ({email})", repr(e))
        return jsonify({'success': False, 'message': 'Une erreur est survenue. Réessayez dans un instant.'}), 500


def _send_access_email(email, user_id, is_new, source=None):
    validity = pro_service.WELCOME_LINK_VALIDITY if is_new else pro_service.LOGIN_LINK_VALIDITY
    token = pro_service.make_access_token(user_id, validity)
    access_url = url_for('pro.access', token=token, source=source, _external=True)
    from services.email_service import send_pro_access_email
    if not send_pro_access_email(email, access_url, is_new=is_new):
        _alert_tech("email d'accès non envoyé", f"{email} : le coach ne recevra pas son lien de connexion")


def _coach_link(account_id, next_path):
    """Lien d'email qui connecte le coach et ouvre directement `next_path`."""
    account = pro_service.get_account_for_admin(account_id)
    token = pro_service.make_access_token(account['user_id'], pro_service.WELCOME_LINK_VALIDITY)
    return url_for('pro.access', token=token, next=next_path, _external=True)


def _safe_next(value):
    """Destination après un lien d'accès : une page de l'espace Pro uniquement."""
    value = value or ''
    return value if value.startswith('/pro/') and not value.startswith(('//', '/\\')) else None


@pro_bp.route('/pro/acces/<token>', methods=['GET', 'POST'])
def access(token):
    """Lien reçu par email. GET : écran de confirmation. POST : connexion, et activation
    de l'espace Pro si le compte Tilto n'en avait pas encore (l'email est ainsi vérifié).
    `next` : page de l'espace Pro à ouvrir (lien d'une relance vers le dossier, par exemple)."""
    next_url = _safe_next(request.values.get('next'))
    user_id = pro_service.read_access_token(token)
    # Déjà connecté (lien ouvert deux fois, ou connexion depuis) : on va droit au but
    if current_user.is_authenticated and pro_service.get_account_by_user(current_user.id) \
            and (not user_id or user_id == current_user.id):
        return redirect(next_url or url_for('pro.dashboard'))
    if not user_id:
        flash("Ce lien a expiré ou a déjà été utilisé. Entrez votre email pour en recevoir un nouveau.", 'warning')
        return redirect(url_for('tilto_pro') + '#essai')
    user = User.get_by_id(user_id)
    if not user:
        abort(404)

    if request.method == 'GET':
        return render_template('pro/access_confirm.html', email=user.email, token=token,
                               source=request.args.get('source', ''), next_url=next_url)

    pro_service.mark_logged_in(user_id)
    login_user(user, remember=True, duration=PRO_REMEMBER)
    if not pro_service.get_account_by_user(user_id):
        source = (request.form.get('source') or 'tilto_pro_landing')[:100]
        pro_service.create_account(user_id, source)
        _notify_slack(f"🧑‍💼 *Nouveau compte Tilto Pro* (compte Tilto existant)\n📧 {user.email}\n📍 {source}")
        return redirect(url_for('pro.welcome'))
    return redirect(next_url or url_for('pro.dashboard'))


# ─── Espace coach ───────────────────────────────────────────────────────────

def _get_dossier(client_id):
    dossier = pro_service.get_client(client_id, g.pro_account['id'])
    if not dossier:
        abort(404)
    return dossier


def _wants_json():
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


@pro_bp.route('/pro/bienvenue')
@pro_required
def welcome():
    """Après l'inscription : choix du point de départ du dossier offert."""
    clients = pro_service.list_clients(g.pro_account['id'])
    free = next((c for c in clients if c['is_free']), None)
    if not free or free['status'] not in DRAFT_STATUSES:
        return redirect(url_for('pro.dashboard'))
    return redirect(url_for('pro.start', client_id=free['id']))


@pro_bp.route('/pro/clients/<int:client_id>/commencer', methods=['GET', 'POST'])
@pro_required
def start(client_id):
    dossier = _get_dossier(client_id)
    if dossier['status'] not in DRAFT_STATUSES:
        return redirect(url_for('pro.client', client_id=client_id))
    if request.method == 'POST':
        kind = request.form.get('kind')
        # « Tester sur moi-même » : réservé au dossier offert
        if kind not in KIND_LABELS or (kind == 'moi' and not dossier['is_free']):
            abort(400)
        pro_service.set_kind(dossier, kind)
        return redirect(url_for('pro.client', client_id=client_id))
    return render_template('pro/start.html', dossier=dossier,
                           has_example=pro_service.has_example())


@pro_bp.route('/pro/dashboard')
@pro_required
def dashboard():
    clients = pro_service.list_clients(g.pro_account['id'])
    return render_template('pro/dashboard.html', clients=clients, account=g.pro_account,
                           has_example=pro_service.has_example())


@pro_bp.route('/pro/clients/nouveau', methods=['POST'])
@pro_required
def new_client():
    client_id = pro_service.create_client(g.pro_account['id'])
    if not client_id:
        flash("Vous n'avez plus de dossier disponible. Demandez-en un nouveau ci-dessous.", 'warning')
        return redirect(url_for('pro.dashboard') + '#debloquer')
    return redirect(url_for('pro.start', client_id=client_id))


def _render_client(dossier, errors=None, status=200):
    return render_template(
        'pro/client.html', dossier=dossier, errors=errors or [],
        fiche_fields=FICHE_FIELDS, kind_labels=KIND_LABELS,
        upload_rules={
            'audio': sorted(pro_service.RECORDING_EXTENSIONS),
            'transcript': sorted(pro_service.TRANSCRIPT_EXTENSIONS),
            'cv': sorted(pro_service.CV_EXTENSIONS),
            'max': {k: pro_service.max_bytes_for(k) for k in pro_service.UPLOAD_KINDS},
            'server_max': pro_service.SERVER_UPLOAD_MAX_BYTES,
        },
        accept=','.join(sorted(pro_service.RECORDING_EXTENSIONS | pro_service.TRANSCRIPT_EXTENSIONS
                               | pro_service.CV_EXTENSIONS)) + ',audio/*,video/*',
    ), status


@pro_bp.route('/pro/clients/<int:client_id>')
@pro_required
def client(client_id):
    dossier = _get_dossier(client_id)
    if dossier['status'] in DRAFT_STATUSES and not dossier.get('kind'):
        return redirect(url_for('pro.start', client_id=client_id))
    return _render_client(dossier)


@pro_bp.route('/pro/clients/<int:client_id>/brouillon', methods=['POST'])
@pro_required
def autosave(client_id):
    """Enregistrement automatique de la fiche (appel JS à chaque saisie)."""
    dossier = _get_dossier(client_id)
    if dossier['status'] not in DRAFT_STATUSES:
        return jsonify({'success': False, 'message': "Le dossier est parti en analyse."}), 409
    # La fiche et le lien de partage sont enregistrés séparément (deux appels distincts)
    if 'label' in request.form:
        label, fiche = pro_service.read_fiche(request.form)
        pro_service.save_fiche(dossier, label, fiche)
    if 'recording_url' in request.form:
        url, error = pro_service.clean_recording_url(request.form['recording_url'])
        if error:
            return jsonify({'success': False, 'field': 'recording_url', 'message': error}), 400
        pro_service.save_recording_url(dossier, url)
        if url and url != dossier.get('recording_url'):
            _alert_recording(dossier, f"lien de l'enregistrement : {url}")
        return jsonify({'success': True, 'recording_url': url})
    return jsonify({'success': True})


def _upload_options():
    """Envoi depuis la page : « à la suite » de l'enregistrement existant, et durée."""
    try:
        seconds = max(0, min(int(float(request.form.get('duration') or 0)), 6 * 3600)) or None
    except ValueError:
        seconds = None
    return {'append': request.form.get('append') == '1', 'seconds': seconds}


def _save_files(dossier, files, append=False, seconds=None):
    """Range chaque fichier déposé (enregistrement, transcription ou CV) d'après son
    nom. Retourne les erreurs."""
    errors = []
    for file in files:
        if not file or not file.filename:
            continue
        try:
            kind, error = pro_service.save_upload(dossier, file, append=append, seconds=seconds)
        except Exception as e:
            logger.error(f"Upload Tilto Pro impossible (dossier {dossier['id']}): {e}", exc_info=True)
            _alert_tech(f"dépôt de fichier impossible (dossier {dossier['id']})", repr(e))
            kind, error = None, f"{file.filename} : l'envoi a échoué. Réessayez dans un instant."
        if error:
            errors.append(error)
        else:
            dossier = pro_service.get_client(dossier['id'])
            if kind in ('audio', 'transcript'):
                _alert_recording(dossier, _recording_what(dossier, kind, file.filename, append, seconds))
    return errors


def _recording_what(dossier, kind, filename, append, seconds):
    if kind == 'transcript':
        return f"transcription déposée ({filename})"
    duration = f", {round(seconds / 60)} min" if seconds and seconds >= 60 else (", moins d'1 min" if seconds else '')
    part = f"partie {dossier['audio_parts']}" if append and dossier['audio_parts'] > 1 else 'enregistrement'
    return f"{part} : {filename}{duration}"


@pro_bp.route('/pro/clients/<int:client_id>/fichiers', methods=['POST'])
@pro_required
def upload(client_id):
    dossier = _get_dossier(client_id)
    if dossier['status'] not in DRAFT_STATUSES:
        message = "Le dossier est parti en analyse : les fichiers ne sont plus modifiables."
        if _wants_json():
            return jsonify({'success': False, 'errors': [message]}), 409
        flash(message, 'warning')
        return redirect(url_for('pro.client', client_id=client_id))

    errors = _save_files(dossier, request.files.getlist('files'), **_upload_options())
    if _wants_json():
        return jsonify(dict(_files_state(client_id), success=not errors, errors=errors)), (200 if not errors else 400)
    for e in errors:
        flash(e, 'error')
    return redirect(url_for('pro.client', client_id=client_id) + '#fichiers')


def _files_state(client_id):
    dossier = pro_service.get_client(client_id)
    state = {kind: (dossier.get(f'{kind}_filename') if dossier.get(f'{kind}_path') else None)
             for kind in pro_service.UPLOAD_KINDS}
    state.update(audio_parts=dossier['audio_parts'], audio_seconds=dossier.get('audio_seconds'))
    return state


@pro_bp.route('/pro/clients/<int:client_id>/fichiers/demarrer', methods=['POST'])
@pro_required
def upload_start(client_id):
    """Gros fichier (vidéo…) : le navigateur l'envoie directement dans le stockage."""
    dossier = _get_dossier(client_id)
    if dossier['status'] not in DRAFT_STATUSES:
        return jsonify({'success': False, 'errors': ["Le dossier est parti en analyse : les fichiers ne sont plus modifiables."]}), 409
    try:
        size = int(request.form.get('size') or 0)
    except ValueError:
        size = 0
    try:
        info, error = pro_service.start_direct_upload(
            dossier, request.form.get('filename'), size, request.form.get('content_type'), **_upload_options())
    except Exception as e:
        logger.error(f"URL d'envoi Tilto Pro impossible (dossier {client_id}): {e}", exc_info=True)
        _alert_tech(f"envoi direct impossible à démarrer (dossier {client_id})", repr(e))
        info, error = None, "L'envoi n'a pas pu démarrer. Réessayez dans un instant."
    if error:
        return jsonify({'success': False, 'errors': [error]}), 400
    return jsonify(dict(info, success=True))


@pro_bp.route('/pro/clients/<int:client_id>/fichiers/terminer', methods=['POST'])
@pro_required
def upload_finish(client_id):
    dossier = _get_dossier(client_id)
    try:
        kind, filename, error = pro_service.finish_direct_upload(dossier, request.form.get('token') or '')
    except Exception as e:
        logger.error(f"Fin d'envoi Tilto Pro impossible (dossier {client_id}): {e}", exc_info=True)
        _alert_tech(f"fin d'envoi direct impossible (dossier {client_id})", repr(e))
        kind, filename, error = None, None, "L'envoi a échoué. Réessayez dans un instant."
    if error:
        if "n'est pas arrivé" in error or 'trop lourd' in error:
            _alert_tech(f"envoi direct non abouti (dossier {client_id})", error)
        return jsonify({'success': False, 'errors': [error]}), 400
    if kind in ('audio', 'transcript'):
        dossier = pro_service.get_client(client_id)
        _alert_recording(dossier, _recording_what(dossier, kind, filename, dossier['audio_parts'] > 1, dossier.get('audio_seconds')))
    return jsonify(dict(_files_state(client_id), success=True, errors=[]))


@pro_bp.route('/pro/clients/<int:client_id>/envoyer', methods=['POST'])
@pro_required
def submit(client_id):
    """Le formulaire unique : fiche + fichiers (sans JavaScript) + accord, puis envoi."""
    dossier = _get_dossier(client_id)
    if dossier['status'] not in DRAFT_STATUSES:
        return redirect(url_for('pro.client', client_id=client_id))

    label, fiche = pro_service.read_fiche(request.form)
    pro_service.save_fiche(dossier, label, fiche)
    errors = _save_files(dossier, request.files.getlist('files'))
    if 'recording_url' in request.form:
        url, url_error = pro_service.clean_recording_url(request.form['recording_url'])
        if url_error:
            errors.append(url_error)
        else:
            pro_service.save_recording_url(dossier, url)
    dossier = pro_service.get_client(client_id)

    consent = request.form.get('consent') == '1'
    errors += pro_service.fiche_errors(dossier, label, fiche)
    if not pro_service.has_recording(dossier):
        errors.append("Déposez l'enregistrement (audio ou vidéo) ou collez son lien de partage.")
    if not consent:
        errors.append("Cochez la case « J'ai l'accord de la personne enregistrée ».")

    if errors or not pro_service.submit_for_analysis(dossier, consent):
        return _render_client(dossier, errors or ["Le dossier n'a pas pu être envoyé. Réessayez."], 400)

    recording = ('vidéo/audio : ' + dossier['audio_filename'] if dossier.get('audio_path')
                 else 'lien : ' + dossier['recording_url'] if dossier.get('recording_url')
                 else 'transcription : ' + (dossier.get('transcript_filename') or ''))
    _notify_slack(
        f"🎧 *Dossier Tilto Pro à analyser*\n📧 {current_user.email}\n👤 {dossier['label']} (dossier {dossier['id']})"
        f" · {KIND_LABELS.get(dossier['kind'], '')}{' · offert' if dossier['is_free'] else ''}"
        f"{' · ' + dossier['fiche']['contexte'] if dossier['fiche'].get('contexte') else ''}"
        f"\n🎬 {recording}"
        f"\n🔗 {url_for('pro.admin_account', account_id=dossier['pro_account_id'], _external=True)}"
    )
    _alert_email(f"Dossier à analyser : {dossier['label']}", [
        f"Coach : {current_user.email}", f"Dossier : {dossier['label']} ({KIND_LABELS.get(dossier['kind'], '')})",
        f"Enregistrement : {recording}", "À livrer sous 48 h."],
        url_for('pro.admin_account', account_id=dossier['pro_account_id'], _external=True))
    if dossier.get('audio_path'):
        # Transcription Whisper en arrière-plan, pour préparer l'analyse
        try:
            from services import pro_transcription
            pro_transcription.start(client_id)
        except Exception as e:
            logger.error(f"Transcription non lancée (dossier {client_id}): {e}", exc_info=True)
    return redirect(url_for('pro.sent', client_id=client_id))


@pro_bp.route('/pro/clients/<int:client_id>/envoye')
@pro_required
def sent(client_id):
    dossier = _get_dossier(client_id)
    if dossier['status'] in DRAFT_STATUSES:
        return redirect(url_for('pro.client', client_id=client_id))
    return render_template('pro/sent.html', dossier=dossier, account=g.pro_account,
                           has_example=pro_service.has_example())


def _sandboxed_html(html, back_url, back_label="Retour à mon espace"):
    """Affiche un dossier HTML (analyse ou exemple) avec la barre « Retour / Télécharger en PDF »."""
    # Chaîne simple (pas Markup) : sinon « </body> » serait échappé lors de la concaténation
    toolbar = str(render_template('pro/_analysis_toolbar.html', back_url=back_url, back_label=back_label))
    if re.search(r'</body>', html, re.I):
        html = re.sub(r'(?i)</body>', lambda m: toolbar + m.group(0), html, count=1)
    else:
        html += toolbar

    response = current_app.response_class(html, mimetype='text/html')
    # Le fichier embarque ses propres styles et scripts : on remplace la CSP à nonce du site.
    # « sandbox » sans allow-same-origin : la page s'exécute dans une origine isolée, sans
    # accès aux cookies ni aux routes du site (le contenu peut reprendre du texte saisi
    # par le coach). allow-modals : impression ; allow-top-navigation : lien « Retour ».
    g.pop('nonce', None)
    response.headers['Content-Security-Policy'] = (
        "sandbox allow-scripts allow-modals allow-popups allow-popups-to-escape-sandbox "
        "allow-top-navigation-by-user-activation allow-downloads; "
        "default-src 'self' https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@pro_bp.route('/pro/clients/<int:client_id>/analyse')
@login_required
def analysis(client_id):
    if current_user.user_status == 'admin':
        dossier = pro_service.get_client(client_id)
        back_url = url_for('pro.admin')
    else:
        account = pro_service.get_account_by_user(current_user.id)
        dossier = pro_service.get_client(client_id, account['id']) if account else None
        back_url = url_for('pro.client', client_id=client_id)
    if not dossier or not dossier.get('analysis_path'):
        abort(404)
    return _sandboxed_html(pro_service.read_analysis(dossier), back_url)


@pro_bp.route('/pro/clients/<int:client_id>/partage', methods=['POST'])
@pro_required
def share(client_id):
    """Lien de lecture à envoyer au client (créé ou désactivé par le coach)."""
    dossier = _get_dossier(client_id)
    if dossier['status'] != 'pret':
        abort(400)
    if request.form.get('action') == 'disable':
        pro_service.disable_share_link(dossier)
        flash("Lien désactivé : il ne permet plus d'ouvrir le dossier.", 'success')
    else:
        pro_service.create_share_link(dossier)
    return redirect(url_for('pro.client', client_id=client_id) + '#partage')


@pro_bp.route('/dossier/<token>')
def shared_analysis(token):
    """Le dossier tel que le lit le client du coach : lecture seule, sans compte."""
    dossier = pro_service.get_client_by_share_token(token)
    if not dossier:
        abort(404)
    # Le coach (ou l'admin) qui vérifie son lien ne compte pas comme une ouverture
    viewer_is_owner = current_user.is_authenticated and (
        current_user.user_status == 'admin'
        or (pro_service.get_account_by_user(current_user.id) or {}).get('id') == dossier['pro_account_id'])
    if not viewer_is_owner:
        pro_service.record_share_view(dossier['id'])
    response = _sandboxed_html(pro_service.read_analysis(dossier), None)
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@pro_bp.route('/pro/exemple-dossier')
def example():
    """Exemple de dossier complet (déposé depuis /admin/pro). Public : les coachs le
    montrent à leurs prospects, et les landings /pro et /pro/cabinets y renvoient."""
    if not pro_service.has_example():
        abort(404)
    back = request.referrer if (request.referrer or '').startswith(request.host_url) else None
    default = url_for('pro.dashboard') if current_user.is_authenticated else url_for('tilto_pro')
    return _sandboxed_html(pro_service.read_example(), back or default, back_label="Retour")


@pro_bp.route('/pro/guide-entretien')
@pro_required
def guide():
    dossier = None
    if request.args.get('dossier', '').isdigit():
        dossier = pro_service.get_client(int(request.args['dossier']), g.pro_account['id'])
    return render_template('pro/guide.html', dossier=dossier)


@pro_bp.route('/pro/dossiers/demande', methods=['POST'])
@limiter.limit("5 per hour")
@pro_required
def request_credit():
    """« Débloquer un dossier » : demande enregistrée (la carte du tableau de bord
    l'affiche), email de confirmation au coach, alerte Slack pour envoyer la facture."""
    if pro_service.request_credit(g.pro_account['id']):
        company = g.pro_account.get('company')
        _notify_slack(
            f"💳 *Demande de dossier Tilto Pro* : facture de 49 € HT à envoyer\n📧 {current_user.email}"
            f"{chr(10) + '🏢 ' + company if company else ''}\n"
            f"Crédits restants : {g.pro_account['credits']} · Ajouter le dossier une fois payé : "
            f"{url_for('pro.admin_account', account_id=g.pro_account['id'], _external=True)}"
        )
        from services.email_service import send_pro_credit_request_email
        send_pro_credit_request_email(current_user.email, url_for('pro.dashboard', _external=True))
    return redirect(url_for('pro.dashboard') + '#debloquer')


# ─── Back-office ────────────────────────────────────────────────────────────

@pro_bp.route('/admin/pro')
@login_required
@admin_required
def admin():
    try:
        pro_service.purge_expired_files()
    except Exception as e:
        logger.error(f"Purge Tilto Pro impossible: {e}", exc_info=True)
    return render_template(
        'admin/pro.html',
        accounts=pro_service.list_accounts(),
        clients=pro_service.list_clients_for_admin(),
        fiche_fields=FICHE_FIELDS, kind_labels=KIND_LABELS,
        has_example=pro_service.has_example(),
    )


@pro_bp.route('/admin/pro/comptes/<int:account_id>')
@login_required
@admin_required
def admin_account(account_id):
    """Tout ce qui concerne un coach : compte, cabinet, origine, dossiers et fichiers."""
    account = pro_service.get_account_for_admin(account_id)
    if not account:
        abort(404)
    return render_template(
        'admin/pro_account.html', account=account,
        clients=pro_service.list_clients_for_admin(account_id),
        fiche_fields=FICHE_FIELDS, kind_labels=KIND_LABELS,
    )


def _admin_back():
    """Retour à la page admin d'où vient l'action (liste ou fiche coach)."""
    back = request.form.get('next') or ''
    return back if back.startswith('/admin/pro') and not back.startswith('//') else url_for('pro.admin')


@pro_bp.route('/admin/pro/clients/<int:client_id>/fichier/<kind>')
@login_required
@admin_required
def admin_file(client_id, kind):
    """Téléchargement d'un fichier du dossier (?partie=2… pour les suites d'enregistrement)."""
    dossier = pro_service.get_client(client_id)
    if not dossier or kind not in pro_service.UPLOAD_KINDS or not dossier.get(f'{kind}_path'):
        abort(404)
    path, name = dossier[f'{kind}_path'], dossier.get(f'{kind}_filename') or f'{kind}-{client_id}'
    part = request.args.get('partie', type=int) or 1
    if kind == 'audio' and part > 1:
        if part - 2 >= len(dossier['audio_extra']):
            abort(404)
        extra = dossier['audio_extra'][part - 2]
        path, name = extra['p'], f"partie {part} - {extra['f']}"
    elif kind == 'audio' and dossier['audio_parts'] > 1:
        name = f"partie 1 - {name}"
    # Préfixé par le prénom du client pour retrouver le fichier dans les téléchargements
    return redirect(pro_service.signed_url(path, download_name=f"{dossier['label']} - {name}"))


@pro_bp.route('/admin/pro/clients/<int:client_id>/transcrire', methods=['POST'])
@login_required
@admin_required
def admin_transcribe(client_id):
    dossier = pro_service.get_client(client_id)
    if not dossier or not dossier.get('audio_path'):
        abort(404)
    from services import pro_transcription
    pro_transcription.start(client_id)
    flash(f"Transcription lancée pour « {dossier['label']} » : rechargez la page dans quelques minutes.", 'success')
    return redirect(_admin_back())


@pro_bp.route('/admin/pro/clients/<int:client_id>/transcription.txt')
@login_required
@admin_required
def admin_transcript(client_id):
    dossier = pro_service.get_client(client_id)
    if not dossier or not dossier.get('auto_transcript'):
        abort(404)
    from urllib.parse import quote
    name = f"{dossier['label']} - transcription.txt"
    response = current_app.response_class(dossier['auto_transcript'], mimetype='text/plain; charset=utf-8')
    response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(name)}"
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@pro_bp.route('/admin/pro/clients/<int:client_id>/analyse', methods=['POST'])
@login_required
@admin_required
def admin_upload_analysis(client_id):
    dossier = pro_service.get_client(client_id)
    if not dossier:
        abort(404)
    file = request.files.get('file')
    if not file or not (file.filename or '').lower().endswith(('.html', '.htm')):
        flash("Déposez un fichier .html.", 'error')
        return redirect(_admin_back())

    first_delivery = dossier['status'] != 'pret'
    pro_service.save_analysis(dossier, file.read())

    if first_delivery:
        coach = pro_service.get_coach_email(dossier['pro_account_id'])
        from services.email_service import send_pro_analysis_ready_email
        send_pro_analysis_ready_email(
            coach, dossier['label'], _coach_link(dossier['pro_account_id'], url_for('pro.client', client_id=client_id))
        )
        _notify_slack(f"✅ *Analyse Tilto Pro livrée*\n📧 {coach}\n👤 {dossier['label']} (dossier {dossier['id']})")
    flash(f"Analyse déposée pour « {dossier['label']} »" + (" et coach prévenu." if first_delivery else " (mise à jour)."), 'success')
    return redirect(_admin_back())


@pro_bp.route('/admin/pro/exemple', methods=['POST'])
@login_required
@admin_required
def admin_upload_example():
    file = request.files.get('file')
    if not file or not (file.filename or '').lower().endswith(('.html', '.htm')):
        flash("Déposez un fichier .html.", 'error')
        return redirect(_admin_back())
    pro_service.save_example(file.read())
    flash("Exemple de dossier mis en ligne pour les coachs.", 'success')
    return redirect(_admin_back())


@pro_bp.route('/admin/pro/comptes/<int:account_id>/credits', methods=['POST'])
@login_required
@admin_required
def admin_add_credit(account_id):
    if not pro_service.get_coach_email(account_id):
        abort(404)
    try:
        amount = max(1, min(50, int(request.form.get('amount', 1))))
    except ValueError:
        amount = 1
    had_request = pro_service.add_credits(account_id, amount)
    coach = pro_service.get_coach_email(account_id)
    from services.email_service import send_pro_credit_added_email
    send_pro_credit_added_email(coach, amount, _coach_link(account_id, url_for('pro.dashboard')))
    flash(f"{amount} dossier(s) ajouté(s), coach prévenu par email"
          + (" (sa demande est close)." if had_request else "."), 'success')
    return redirect(_admin_back())


def _send_nudges():
    """Relances automatiques du dossier offert (3 et 10 jours après l'inscription)."""
    from services.email_service import send_pro_nudge_email
    sent_count = 0
    for row in pro_service.due_nudges():
        number = row['nudges_sent'] + 1
        try:
            ok = send_pro_nudge_email(
                row['email'], number,
                _coach_link(row['account_id'], url_for('pro.client', client_id=row['client_id'])),
                url_for('pro.nudges_stop', token=pro_service.make_nudge_stop_token(row['account_id']), _external=True),
            )
        except Exception as e:
            logger.error(f"Relance Tilto Pro impossible (compte {row['account_id']}): {e}", exc_info=True)
            ok = False
        if not ok:
            _alert_tech("relance non envoyée", f"{row['email']} (compte {row['account_id']})")
        if ok:
            pro_service.mark_nudge_sent(row['account_id'])
            sent_count += 1
    return sent_count


@pro_bp.route('/admin/pro/relances', methods=['POST'])
@login_required
@admin_required
def admin_send_nudges():
    """Envoi manuel des relances dues (en attendant une tâche Cloud Scheduler quotidienne)."""
    sent = _send_nudges()
    flash(f"{sent} relance(s) envoyée(s)." if sent else "Aucune relance à envoyer aujourd'hui.", 'success')
    return redirect(url_for('pro.admin') + '#comptes')


@pro_bp.route('/pro/relances/stop/<token>', methods=['GET', 'POST'])
def nudges_stop(token):
    """Lien « Ne plus recevoir ces rappels » des relances. GET : confirmation (un robot
    qui ouvre le lien n'arrête rien) ; POST : arrêt."""
    account_id = pro_service.read_nudge_stop_token(token)
    if not account_id:
        abort(404)
    done = request.method == 'POST'
    if done:
        pro_service.set_nudges_stopped(account_id, True)
        _notify_slack(f"🔕 Relances Tilto Pro arrêtées par le coach : {pro_service.get_coach_email(account_id)}")
    return render_template('pro/nudges_stop.html', token=token, done=done)


@pro_bp.route('/admin/pro/comptes/<int:account_id>/relances', methods=['POST'])
@login_required
@admin_required
def admin_toggle_nudges(account_id):
    stop = request.form.get('action') == 'stop'
    pro_service.set_nudges_stopped(account_id, stop)
    flash("Relances automatiques stoppées." if stop else "Relances automatiques réactivées.", 'success')
    return redirect(_admin_back())


@pro_bp.route('/cron/pro-purge-files')
def cron_purge():
    """Appelé par Cloud Scheduler (quotidien) : supprime les fichiers expirés et envoie
    les relances automatiques du dossier offert."""
    if (not request.headers.get('X-CloudScheduler')
            and not request.headers.get('X-Appengine-Cron')
            and not current_app.debug):
        return jsonify({'error': 'Unauthorized'}), 403
    return jsonify({'purged': pro_service.purge_expired_files(),
                    'nudges': _send_nudges(), 'status': 'ok'})
