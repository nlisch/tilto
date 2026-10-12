"""
Tilto Pro : comptes coachs, dossiers clients et fichiers associés.

Un compte Pro est rattaché à un compte Tilto existant (table users) via
pro_accounts. Chaque dossier client (pro_clients) contient la fiche d'identité,
l'audio et le CV déposés par le coach, puis l'analyse HTML déposée par l'admin.

Les fichiers sont stockés dans le bucket audio du quiz, sous le préfixe pro/.
L'audio et le CV sont supprimés 30 jours après la livraison de l'analyse.
"""
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import current_app
from google.cloud import storage
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from google.oauth2 import service_account
from MySQLdb.cursors import DictCursor

logger = logging.getLogger(__name__)

FILES_RETENTION_DAYS = 30
WELCOME_LINK_VALIDITY = timedelta(days=7)
LOGIN_LINK_VALIDITY = timedelta(hours=24)

# Enregistrement : audio ou vidéo (Zoom, Teams, Meet, Loom, téléphone…). L'audio des
# vidéos est extrait à la main avant l'analyse.
AUDIO_EXTENSIONS = {'.mp3', '.m4a', '.wav', '.ogg', '.aac', '.flac', '.opus', '.amr', '.weba'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.webm', '.mkv', '.avi', '.m4v', '.3gp', '.wmv'}
RECORDING_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
RECORDING_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 Go, envoyé directement dans le stockage
# Au-delà, le navigateur envoie le fichier directement dans GCS (URL signée) : une
# requête vers Cloud Run est limitée à 32 Mo.
SERVER_UPLOAD_MAX_BYTES = 30 * 1024 * 1024
CV_EXTENSIONS = {'.pdf', '.doc', '.docx', '.odt', '.rtf'}
CV_MAX_BYTES = 8 * 1024 * 1024
# Transcription (Teams, Zoom, Meet) à la place de l'enregistrement
TRANSCRIPT_EXTENSIONS = {'.vtt', '.srt', '.txt'}
TRANSCRIPT_MAX_BYTES = 8 * 1024 * 1024
UPLOAD_KINDS = ('audio', 'cv', 'transcript')  # colonnes {kind}_path / {kind}_filename
UPLOAD_LINK_VALIDITY = timedelta(hours=2)

# Relances automatiques tant que le dossier offert n'est pas envoyé (jours après l'inscription)
NUDGE_DAYS = (3, 10)

# « fiche » et « audio » : dossier en cours de préparation (on ne distingue plus les deux)
DRAFT_STATUSES = ('fiche', 'audio')
STATUS_LABELS = {
    'fiche': 'À envoyer',
    'audio': 'À envoyer',
    'analyse': 'En analyse',
    'pret': 'Prêt',
}

# Point de départ choisi par le coach
KINDS = ('moi', 'client', 'enregistrement')
KIND_LABELS = {
    'moi': 'Dossier test (moi-même)',
    'client': 'Enregistré dans la page',
    'enregistrement': 'Fichier ou lien déposé',
}
DEFAULT_LABELS = ("Mon premier client", "Mon dossier test")

# Fiche : clé, libellé, obligatoire (le prénom est stocké dans pro_clients.label)
FICHE_FIELDS = [
    ('age', "Âge", True),
    ('localisation', "Ville", True),
    ('mobilite', "Mobilité", False),
    ('salaire_souhaite', "Salaire souhaité", False),
    ('statut', "Statut recherché", False),
    ('remarques', "Remarques", False),
    ('contexte', "Cette personne est", False),
]


def _cursor():
    return current_app.mysql.connection.cursor(DictCursor)


def _commit():
    current_app.mysql.connection.commit()


# ─── Comptes ────────────────────────────────────────────────────────────────

def get_account_by_user(user_id):
    cur = _cursor()
    try:
        cur.execute("SELECT * FROM pro_accounts WHERE user_id = %s", (user_id,))
        return cur.fetchone()
    finally:
        cur.close()


def is_pro_user(user_id):
    try:
        return get_account_by_user(user_id) is not None
    except Exception as e:  # table absente avant migration : on ne casse pas le site
        logger.warning(f"is_pro_user indisponible: {e}")
        return False


def has_personal_analysis(user_id):
    """Vrai si le compte a aussi une analyse Tilto perso (parcours B2C)."""
    cur = _cursor()
    try:
        cur.execute("SELECT 1 FROM result_user WHERE user_id = %s LIMIT 1", (user_id,))
        return cur.fetchone() is not None
    finally:
        cur.close()


def get_user_by_email(email):
    cur = _cursor()
    try:
        cur.execute("SELECT user_id, email, firstname FROM users WHERE email = %s", (email,))
        return cur.fetchone()
    finally:
        cur.close()


def create_user(email):
    """Crée un compte Tilto sans mot de passe (connexion par lien magique)."""
    cur = _cursor()
    try:
        cur.execute("""
            INSERT INTO users (email, user_status, country_code, onboarding_stage, lead_source)
            VALUES (%s, 'user', 'FR', 'invited', 'tilto_pro')
        """, (email,))
        _commit()
        return cur.lastrowid
    finally:
        cur.close()


def create_account(user_id, source, company=None):
    """Crée le compte Pro et son premier dossier offert. Retourne l'id du compte.

    Idempotent : si le compte existe déjà (double clic, requêtes simultanées),
    on le retourne sans recréer de dossier offert.
    """
    cur = _cursor()
    try:
        cur.execute(
            "INSERT IGNORE INTO pro_accounts (user_id, credits, source, company) VALUES (%s, 0, %s, %s)",
            (user_id, source, company),
        )
        if cur.rowcount == 0:
            if company:  # compte existant qui demande un pilote cabinet
                cur.execute("UPDATE pro_accounts SET company = %s WHERE user_id = %s", (company, user_id))
                _commit()
            cur.execute("SELECT id FROM pro_accounts WHERE user_id = %s", (user_id,))
            return cur.fetchone()['id']
        account_id = cur.lastrowid
        cur.execute("""
            INSERT INTO pro_clients (pro_account_id, label, is_free)
            VALUES (%s, %s, TRUE)
        """, (account_id, "Mon premier client"))
        _commit()
        return account_id
    finally:
        cur.close()


def record_lead(email, source, ip_address, activite=None, notes=None):
    """Garde la trace commerciale dans pro_leads (une ligne par email)."""
    cur = _cursor()
    try:
        cur.execute("SELECT id FROM pro_leads WHERE email = %s LIMIT 1", (email,))
        if cur.fetchone():
            cur.execute("UPDATE pro_leads SET status = 'converted' WHERE email = %s AND status = 'new'", (email,))
            if notes:
                cur.execute("""
                    UPDATE pro_leads SET activite = COALESCE(%s, activite),
                           notes = CONCAT_WS('\n', notes, %s)
                    WHERE email = %s
                """, (activite, notes, email))
        else:
            cur.execute("""
                INSERT INTO pro_leads (firstname, lastname, email, activite, source, status, notes, ip_address)
                VALUES ('', '', %s, %s, %s, 'converted', %s, %s)
            """, (email, activite, source, notes, ip_address))
        _commit()
    finally:
        cur.close()


def _access_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='tilto-pro-access')


def _last_login_marker(user_id):
    cur = _cursor()
    try:
        cur.execute("SELECT last_login FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return row['last_login'].isoformat() if row and row['last_login'] else ''
    finally:
        cur.close()


def make_access_token(user_id, validity):
    """Lien d'accès Tilto Pro signé.

    Indépendant de users.invite_token (partagé avec les invitations, achats et
    réinitialisations de mot de passe) : on n'écrase donc rien. Le jeton devient
    invalide dès la connexion suivante (last_login change) et après `validity`.
    """
    payload = {'u': user_id, 'l': _last_login_marker(user_id), 'm': int(validity.total_seconds())}
    return _access_serializer().dumps(payload)


def read_access_token(token):
    """Retourne l'user_id si le jeton est valide, sinon None."""
    try:
        data = _access_serializer().loads(token, max_age=int(WELCOME_LINK_VALIDITY.total_seconds()))
        _, issued_at = _access_serializer().loads(token, return_timestamp=True)
    except (BadSignature, SignatureExpired):
        return None
    if datetime.now(issued_at.tzinfo) - issued_at > timedelta(seconds=data.get('m', 0)):
        return None
    if _last_login_marker(data['u']) != data.get('l'):
        return None  # déjà utilisé (une connexion a eu lieu depuis l'envoi)
    return data['u']


def mark_logged_in(user_id):
    """Connexion via le lien : l'email est vérifié et le lien devient invalide."""
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE users SET last_login = NOW(),
                   onboarding_stage = IF(onboarding_stage = 'invited', 'email_verified', onboarding_stage)
            WHERE user_id = %s
        """, (user_id,))
        _commit()
    finally:
        cur.close()


def get_coach_email(account_id):
    cur = _cursor()
    try:
        cur.execute("""
            SELECT u.email FROM pro_accounts a JOIN users u ON u.user_id = a.user_id WHERE a.id = %s
        """, (account_id,))
        row = cur.fetchone()
        return row['email'] if row else None
    finally:
        cur.close()


def add_credits(account_id, amount):
    """Ajoute des dossiers et clôt la demande en attente. Retourne True si une demande
    du coach était en attente."""
    cur = _cursor()
    try:
        cur.execute("SELECT credit_requested_at FROM pro_accounts WHERE id = %s", (account_id,))
        row = cur.fetchone()
        cur.execute(
            "UPDATE pro_accounts SET credits = credits + %s, credit_requested_at = NULL WHERE id = %s",
            (amount, account_id),
        )
        _commit()
        return bool(row and row['credit_requested_at'])
    finally:
        cur.close()


def request_credit(account_id):
    """Enregistre la demande de dossier. Retourne False si une demande est déjà en attente."""
    cur = _cursor()
    try:
        cur.execute(
            "UPDATE pro_accounts SET credit_requested_at = NOW() WHERE id = %s AND credit_requested_at IS NULL",
            (account_id,),
        )
        _commit()
        return cur.rowcount > 0
    finally:
        cur.close()


def list_accounts():
    cur = _cursor()
    try:
        cur.execute("""
            SELECT a.*, u.email, u.last_login,
                   (SELECT COUNT(*) FROM pro_clients c WHERE c.pro_account_id = a.id) AS nb_clients,
                   (SELECT c.status FROM pro_clients c WHERE c.pro_account_id = a.id AND c.is_free LIMIT 1) AS free_status
            FROM pro_accounts a JOIN users u ON u.user_id = a.user_id
            ORDER BY a.created_at DESC
        """)
        accounts = cur.fetchall()
        for a in accounts:
            free = {'status': a['free_status']} if a['free_status'] else None
            a['nudge'] = nudge_status(a, free)
        return accounts
    finally:
        cur.close()


def get_account_for_admin(account_id):
    """Compte coach avec son compte Tilto et ses traces commerciales (pro_leads)."""
    cur = _cursor()
    try:
        cur.execute("""
            SELECT a.*, u.email, u.firstname, u.lastname, u.last_login, u.created_at AS user_created_at,
                   u.lead_source AS user_lead_source,
                   EXISTS(SELECT 1 FROM result_user r WHERE r.user_id = u.user_id) AS has_personal_analysis
            FROM pro_accounts a JOIN users u ON u.user_id = a.user_id
            WHERE a.id = %s
        """, (account_id,))
        account = cur.fetchone()
        if account:
            cur.execute("""
                SELECT source, activite, status, notes, created_at FROM pro_leads
                WHERE email = %s ORDER BY created_at
            """, (account['email'],))
            account['leads'] = cur.fetchall()
            cur.execute("SELECT status FROM pro_clients WHERE pro_account_id = %s AND is_free LIMIT 1", (account_id,))
            account['nudge'] = nudge_status(account, cur.fetchone())
        return account
    finally:
        cur.close()


# ─── Dossiers clients ───────────────────────────────────────────────────────

def list_clients(account_id):
    cur = _cursor()
    try:
        cur.execute("""
            SELECT * FROM pro_clients WHERE pro_account_id = %s
            ORDER BY created_at DESC, id DESC
        """, (account_id,))
        return [_hydrate(c) for c in cur.fetchall()]
    finally:
        cur.close()


def get_client(client_id, account_id=None):
    """Retourne le dossier ; si account_id est fourni, vérifie qu'il appartient au coach."""
    cur = _cursor()
    try:
        if account_id is None:
            cur.execute("SELECT * FROM pro_clients WHERE id = %s", (client_id,))
        else:
            cur.execute(
                "SELECT * FROM pro_clients WHERE id = %s AND pro_account_id = %s",
                (client_id, account_id),
            )
        row = cur.fetchone()
        return _hydrate(row) if row else None
    finally:
        cur.close()


def list_clients_for_admin(account_id=None):
    cur = _cursor()
    try:
        cur.execute(f"""
            SELECT c.*, u.email AS coach_email, a.company AS coach_company
            FROM pro_clients c
            JOIN pro_accounts a ON a.id = c.pro_account_id
            JOIN users u ON u.user_id = a.user_id
            {'WHERE a.id = %s' if account_id else ''}
            ORDER BY FIELD(c.status, 'analyse', 'audio', 'fiche', 'pret'), c.submitted_at, c.created_at DESC
        """, (account_id,) if account_id else ())
        return [_hydrate(c) for c in cur.fetchall()]
    finally:
        cur.close()


def _hydrate(row):
    row['fiche'] = json.loads(row['fiche_json']) if row.get('fiche_json') else {}
    # Enregistrement en plusieurs parties : la 1re dans audio_path, les suivantes ici
    row['audio_extra'] = json.loads(row['audio_extra_json']) if row.get('audio_extra_json') else []
    row['audio_parts'] = (1 if row.get('audio_path') else 0) + len(row['audio_extra'])
    row['status_label'] = STATUS_LABELS.get(row['status'], row['status'])
    return row


def create_client(account_id):
    """Consomme un crédit et crée un dossier. Retourne l'id ou None si plus de crédit."""
    cur = _cursor()
    try:
        cur.execute(
            "UPDATE pro_accounts SET credits = credits - 1 WHERE id = %s AND credits > 0",
            (account_id,),
        )
        if cur.rowcount == 0:
            return None
        cur.execute("""
            SELECT COUNT(*) AS n FROM pro_clients WHERE pro_account_id = %s
        """, (account_id,))
        n = cur.fetchone()['n'] + 1
        cur.execute(
            "INSERT INTO pro_clients (pro_account_id, label) VALUES (%s, %s)",
            (account_id, f"Client {n}"),
        )
        _commit()
        return cur.lastrowid
    finally:
        cur.close()


def read_fiche(form):
    """Lit le prénom et la fiche saisis, sans contrôle (brouillon)."""
    label = (form.get('label') or '').strip()[:80]
    fiche = {key: (form.get(key) or '').strip()[:2000] for key, _, _ in FICHE_FIELDS}
    return label, fiche


def fiche_errors(client, label, fiche):
    """Ce qui manque pour envoyer le dossier en analyse."""
    errors = []
    if not label:
        errors.append("Indiquez votre prénom." if client.get('kind') == 'moi'
                      else "Indiquez le prénom ou les initiales de votre client.")
    for key, title, required in FICHE_FIELDS:
        if required and not fiche.get(key):
            errors.append(f"Indiquez : {title.lower()}.")
    return errors


def save_fiche(client, label, fiche):
    """Enregistre le brouillon (seulement tant que le dossier n'est pas parti en analyse)."""
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET label = %s, fiche_json = %s
            WHERE id = %s AND status IN ('fiche', 'audio')
        """, (label or client['label'], json.dumps(fiche, ensure_ascii=False), client['id']))
        _commit()
    finally:
        cur.close()


def set_kind(client, kind):
    cur = _cursor()
    try:
        label = client['label']
        if kind == 'moi' and label in DEFAULT_LABELS:
            label = "Mon dossier test"
        elif kind != 'moi' and label == "Mon dossier test":
            label = "Mon premier client"
        cur.execute("""
            UPDATE pro_clients SET kind = %s, label = %s
            WHERE id = %s AND status IN ('fiche', 'audio')
        """, (kind, label, client['id']))
        _commit()
    finally:
        cur.close()


def classify_upload(filename):
    """Range un fichier déposé dans la zone unique : « audio » (enregistrement audio ou
    vidéo), « transcript » ou « cv ». None si le format n'est pas accepté.

    Un .docx / .pdf est un CV, sauf si son nom évoque une transcription
    (« Transcription réunion.docx », export Teams « …transcript.docx »).
    """
    name = (filename or '').lower()
    ext = os.path.splitext(name)[1]
    if ext in RECORDING_EXTENSIONS:
        return 'audio'
    if ext in TRANSCRIPT_EXTENSIONS:
        return 'transcript'
    if ext in CV_EXTENSIONS:
        return 'transcript' if re.search(r'transcri|verbatim', name) else 'cv'
    return None


def max_bytes_for(kind):
    return {'audio': RECORDING_MAX_BYTES, 'cv': CV_MAX_BYTES, 'transcript': TRANSCRIPT_MAX_BYTES}[kind]


def _check_upload(filename, size):
    """Retourne (kind, erreur)."""
    kind = classify_upload(filename)
    if not kind:
        return None, (f"{filename} : format non accepté. Déposez un enregistrement (audio ou vidéo), "
                      "une transcription ou un CV (PDF, Word).")
    if not size:
        return kind, f"{filename} : le fichier est vide."
    limit = max_bytes_for(kind)
    if size > limit:
        human = f"{limit // (1024 ** 3)} Go" if limit >= 1024 ** 3 else f"{limit // (1024 * 1024)} Mo"
        return kind, f"{filename} : fichier trop lourd (maximum {human})."
    return kind, None


def _new_path(client, kind, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"pro/{client['pro_account_id']}/{client['id']}/{kind}-{uuid.uuid4().hex[:8]}{ext}"


def _attach(client, kind, path, filename, append=False, seconds=None):
    """Rattache un fichier déjà stocké au dossier. Retourne une erreur ou None.

    Enregistrement (kind « audio ») : `append` ajoute une partie à la suite des
    précédentes ; sinon le nouvel enregistrement remplace toutes les parties.
    `seconds` : durée connue (enregistrement fait dans la page), cumulée.

    Verrou de ligne : deux envois simultanés ou un envoi pendant « Envoyer en analyse »
    ne doivent ni écraser un dossier parti en analyse, ni laisser de fichier orphelin.
    """
    assert kind in UPLOAD_KINDS  # nom de colonne : liste fermée
    seconds = int(seconds) if seconds else None
    cur = _cursor()
    try:
        cur.execute(
            f"SELECT {kind}_path AS old_path, audio_extra_json, audio_seconds FROM pro_clients "
            "WHERE id = %s AND status IN ('fiche', 'audio') FOR UPDATE",
            (client['id'],),
        )
        row = cur.fetchone()
        if not row:
            current_app.mysql.connection.rollback()
            _delete_blob(path)
            return "Le dossier est parti en analyse : les fichiers ne sont plus modifiables."
        old_paths = []
        if kind == 'audio' and append and row['old_path']:
            extra = json.loads(row['audio_extra_json']) if row['audio_extra_json'] else []
            extra.append({'p': path, 'f': filename[:255], 's': seconds})
            total = (row['audio_seconds'] or 0) + (seconds or 0) if (row['audio_seconds'] or seconds) else None
            cur.execute(
                "UPDATE pro_clients SET audio_extra_json = %s, audio_seconds = %s WHERE id = %s",
                (json.dumps(extra, ensure_ascii=False), total, client['id']),
            )
        else:
            if row['old_path']:
                old_paths.append(row['old_path'])
            if kind == 'audio':
                old_paths += [e['p'] for e in (json.loads(row['audio_extra_json']) if row['audio_extra_json'] else [])]
                cur.execute(
                    "UPDATE pro_clients SET audio_path = %s, audio_filename = %s, audio_extra_json = NULL, "
                    "audio_seconds = %s WHERE id = %s",
                    (path, filename[:255], seconds, client['id']),
                )
            else:
                cur.execute(
                    f"UPDATE pro_clients SET {kind}_path = %s, {kind}_filename = %s WHERE id = %s",
                    (path, filename[:255], client['id']),
                )
        _commit()
    finally:
        cur.close()
    for old in old_paths:
        if old != path:
            _delete_blob(old)
    return None


def save_upload(client, file_storage, append=False, seconds=None):
    """Petit fichier envoyé au serveur (≤ 30 Mo). Retourne (kind, erreur)."""
    filename = file_storage.filename or ''
    data = file_storage.read()
    kind, error = _check_upload(filename, len(data))
    if error:
        return kind, error
    if len(data) > SERVER_UPLOAD_MAX_BYTES:
        return kind, f"{filename} : fichier trop lourd pour cet envoi. Réessayez depuis la page du dossier."
    path = _new_path(client, kind, filename)
    _bucket().blob(path).upload_from_string(data, content_type=file_storage.mimetype or 'application/octet-stream')
    return kind, _attach(client, kind, path, filename, append=append, seconds=seconds)


def _upload_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='tilto-pro-upload')


def start_direct_upload(client, filename, size, content_type, append=False, seconds=None):
    """Gros fichier (vidéo…) : URL signée pour l'envoyer directement dans GCS, et jeton
    signé à renvoyer une fois l'envoi terminé. Retourne (infos, erreur)."""
    filename = os.path.basename(filename or '')[:255]
    kind, error = _check_upload(filename, size)
    if error:
        return None, error
    path = _new_path(client, kind, filename)
    content_type = content_type or 'application/octet-stream'
    url = _bucket().blob(path).generate_signed_url(
        version='v4', expiration=UPLOAD_LINK_VALIDITY, method='PUT', content_type=content_type,
    )
    token = _upload_serializer().dumps({'c': client['id'], 'k': kind, 'p': path, 'f': filename,
                                        'a': bool(append), 's': int(seconds) if seconds else None})
    return {'url': url, 'token': token, 'kind': kind, 'content_type': content_type}, None


def finish_direct_upload(client, token):
    """Vérifie que le fichier est bien arrivé dans GCS puis le rattache au dossier.
    Retourne (kind, filename, erreur)."""
    try:
        data = _upload_serializer().loads(token, max_age=int(UPLOAD_LINK_VALIDITY.total_seconds()))
    except (BadSignature, SignatureExpired):
        return None, None, "L'envoi a expiré. Déposez à nouveau le fichier."
    if data.get('c') != client['id'] or data.get('k') not in UPLOAD_KINDS:
        return None, None, "Envoi invalide."
    blob = _bucket().blob(data['p'])
    try:
        blob.reload()
        size = blob.size
    except Exception:
        size = None
    if not size:
        return data['k'], data['f'], f"{data['f']} : le fichier n'est pas arrivé. Réessayez."
    if size > max_bytes_for(data['k']):
        _delete_blob(data['p'])
        return data['k'], data['f'], f"{data['f']} : fichier trop lourd."
    return data['k'], data['f'], _attach(client, data['k'], data['p'], data['f'],
                                         append=data.get('a', False), seconds=data.get('s'))


def save_recording_url(client, url):
    """Lien de partage (Loom, Drive, Teams…). Chaîne vide : on retire le lien."""
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET recording_url = %s
            WHERE id = %s AND status IN ('fiche', 'audio')
        """, (url or None, client['id']))
        _commit()
    finally:
        cur.close()


def clean_recording_url(value):
    """Retourne (url, erreur). Accepte les liens collés sans « https:// »."""
    value = (value or '').strip()
    if not value:
        return '', None
    if not re.match(r'^https?://', value, re.I):
        value = 'https://' + value
    if len(value) > 500 or not re.match(r'^https?://[^\s/$.?#][^\s]*\.[^\s]+$', value, re.I):
        return value, "Le lien de l'enregistrement n'est pas valide. Copiez le lien de partage complet."
    return value, None


def has_recording(client):
    return bool(client.get('audio_path') or client.get('transcript_path') or client.get('recording_url'))


def submit_for_analysis(client, consent):
    """Passe le dossier en analyse si l'enregistrement est là (fichier, lien ou
    transcription). Retourne True si changé. La fiche est contrôlée avant l'appel."""
    if client['status'] not in DRAFT_STATUSES or not has_recording(client):
        return False
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET status = 'analyse', submitted_at = NOW(),
                   consent_at = IF(%s, NOW(), NULL)
            WHERE id = %s AND status IN ('fiche', 'audio')
              AND (audio_path IS NOT NULL OR transcript_path IS NOT NULL OR recording_url IS NOT NULL)
        """, (bool(consent), client['id']))
        _commit()
        return cur.rowcount > 0
    finally:
        cur.close()


def save_analysis(client, html_bytes):
    path = f"pro/{client['pro_account_id']}/{client['id']}/analyse-{uuid.uuid4().hex[:8]}.html"
    _bucket().blob(path).upload_from_string(html_bytes, content_type='text/html; charset=utf-8')
    old_path = client.get('analysis_path')
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET analysis_path = %s, status = 'pret', delivered_at = NOW()
            WHERE id = %s
        """, (path, client['id']))
        _commit()
    finally:
        cur.close()
    if old_path:
        _delete_blob(old_path)


EXAMPLE_PATH = 'pro/exemple/dossier.html'
_example_cache = {'at': None, 'exists': False}


def has_example():
    """Un exemple de dossier a-t-il été déposé ? (mis en cache 5 min : appelé à chaque page)"""
    now = datetime.now()
    if _example_cache['at'] and now - _example_cache['at'] < timedelta(minutes=5):
        return _example_cache['exists']
    try:
        exists = _bucket().blob(EXAMPLE_PATH).exists()
    except Exception as e:
        logger.warning(f"Exemple de dossier Tilto Pro indisponible: {e}")
        exists = False
    _example_cache.update(at=now, exists=exists)
    return exists


def save_example(html_bytes):
    _bucket().blob(EXAMPLE_PATH).upload_from_string(html_bytes, content_type='text/html; charset=utf-8')
    _example_cache.update(at=datetime.now(), exists=True)


def read_example():
    return _bucket().blob(EXAMPLE_PATH).download_as_bytes().decode('utf-8', errors='replace')


# ─── Transcription automatique (admin) ──────────────────────────────────────

def set_transcript_status(client_id, status, error=None):
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET auto_transcript_status = %s, auto_transcript_error = %s,
                   auto_transcript_at = NOW() WHERE id = %s
        """, (status, error, client_id))
        _commit()
    finally:
        cur.close()


def save_transcript(client_id, text):
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET auto_transcript = %s, auto_transcript_status = 'pret',
                   auto_transcript_error = NULL, auto_transcript_at = NOW() WHERE id = %s
        """, (text, client_id))
        _commit()
    finally:
        cur.close()


# ─── Lien de lecture pour le client du coach ────────────────────────────────

def create_share_link(client):
    """Crée (ou retourne) le lien de lecture du dossier livré."""
    if client.get('share_token'):
        return client['share_token']
    token = secrets.token_urlsafe(24)
    cur = _cursor()
    try:
        cur.execute("""
            UPDATE pro_clients SET share_token = %s, share_views = 0, share_last_view_at = NULL
            WHERE id = %s AND status = 'pret' AND share_token IS NULL
        """, (token, client['id']))
        _commit()
    finally:
        cur.close()
    return token


def disable_share_link(client):
    cur = _cursor()
    try:
        cur.execute("UPDATE pro_clients SET share_token = NULL WHERE id = %s", (client['id'],))
        _commit()
    finally:
        cur.close()


def get_client_by_share_token(token):
    if not token or len(token) > 64:
        return None
    cur = _cursor()
    try:
        cur.execute(
            "SELECT * FROM pro_clients WHERE share_token = %s AND status = 'pret' AND analysis_path IS NOT NULL",
            (token,),
        )
        row = cur.fetchone()
        return _hydrate(row) if row else None
    finally:
        cur.close()


def record_share_view(client_id):
    cur = _cursor()
    try:
        cur.execute(
            "UPDATE pro_clients SET share_views = share_views + 1, share_last_view_at = NOW() WHERE id = %s",
            (client_id,),
        )
        _commit()
    finally:
        cur.close()


# ─── Relances automatiques du dossier offert ────────────────────────────────

def due_nudges():
    """Coachs dont le dossier offert n'est toujours pas envoyé, 3 puis 10 jours après
    l'inscription. Ignore les relances stoppées."""
    cur = _cursor()
    try:
        cur.execute("""
            SELECT a.id AS account_id, a.user_id, a.nudges_sent, u.email, c.id AS client_id
            FROM pro_accounts a
            JOIN users u ON u.user_id = a.user_id
            JOIN pro_clients c ON c.pro_account_id = a.id AND c.is_free = TRUE
            WHERE a.nudges_stopped_at IS NULL
              AND c.status IN ('fiche', 'audio')
              AND ((a.nudges_sent = 0 AND a.created_at <= NOW() - INTERVAL %s DAY)
                OR (a.nudges_sent = 1 AND a.created_at <= NOW() - INTERVAL %s DAY))
        """, NUDGE_DAYS)
        return cur.fetchall()
    finally:
        cur.close()


def mark_nudge_sent(account_id):
    cur = _cursor()
    try:
        cur.execute(
            "UPDATE pro_accounts SET nudges_sent = nudges_sent + 1, nudge_last_at = NOW() WHERE id = %s",
            (account_id,),
        )
        _commit()
    finally:
        cur.close()


def set_nudges_stopped(account_id, stopped):
    cur = _cursor()
    try:
        cur.execute(
            "UPDATE pro_accounts SET nudges_stopped_at = IF(%s, NOW(), NULL) WHERE id = %s",
            (bool(stopped), account_id),
        )
        _commit()
    finally:
        cur.close()


def nudge_status(account, free_client):
    """Libellé pour l'admin : où en sont les relances de ce coach."""
    if account.get('nudges_stopped_at'):
        return {'state': 'stopped', 'label': f"Stoppées le {account['nudges_stopped_at']:%d/%m}"}
    if not free_client or free_client['status'] not in DRAFT_STATUSES:
        sent = account.get('nudges_sent') or 0
        return {'state': 'done', 'label': f"Dossier offert envoyé{f' ({sent} relance(s) envoyée(s))' if sent else ''}"}
    sent = account.get('nudges_sent') or 0
    if sent >= len(NUDGE_DAYS):
        return {'state': 'done', 'label': f"{sent}/{len(NUDGE_DAYS)} envoyées, dernière le {account['nudge_last_at']:%d/%m}"}
    next_at = account['created_at'] + timedelta(days=NUDGE_DAYS[sent])
    prefix = f"{sent}/{len(NUDGE_DAYS)} envoyée le {account['nudge_last_at']:%d/%m} · " if sent else ""
    return {'state': 'active', 'label': f"{prefix}prochaine le {next_at:%d/%m}"}


def _nudge_serializer():
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='tilto-pro-nudges-stop')


def make_nudge_stop_token(account_id):
    return _nudge_serializer().dumps(account_id)


def read_nudge_stop_token(token):
    try:
        return _nudge_serializer().loads(token, max_age=60 * 60 * 24 * 90)
    except (BadSignature, SignatureExpired):
        return None


def read_analysis(client):
    return _bucket().blob(client['analysis_path']).download_as_bytes().decode('utf-8', errors='replace')


def signed_url(path, minutes=30, download_name=None):
    """Lien temporaire. Avec download_name : téléchargement sous le nom d'origine."""
    kwargs = {}
    if download_name:
        ascii_name = re.sub(r'[^A-Za-z0-9._ -]', '_', download_name)[:150] or 'fichier'
        kwargs['response_disposition'] = (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(download_name[:150])}'
        )
    return _bucket().blob(path).generate_signed_url(
        version='v4', expiration=timedelta(minutes=minutes), method='GET', **kwargs
    )


def purge_expired_files():
    """Supprime l'enregistrement, la transcription et le CV des dossiers livrés
    depuis plus de 30 jours (le lien de partage est effacé aussi)."""
    cur = _cursor()
    purged = 0
    try:
        cur.execute("""
            SELECT id, audio_path, audio_extra_json, cv_path, transcript_path FROM pro_clients
            WHERE delivered_at IS NOT NULL AND files_purged_at IS NULL
              AND delivered_at < NOW() - INTERVAL %s DAY
        """, (FILES_RETENTION_DAYS,))
        for row in cur.fetchall():
            extra = [e['p'] for e in json.loads(row['audio_extra_json'])] if row['audio_extra_json'] else []
            for path in [row['audio_path'], row['cv_path'], row['transcript_path']] + extra:
                if path:
                    _delete_blob(path)
            cur.execute("""
                UPDATE pro_clients SET audio_path = NULL, audio_extra_json = NULL, cv_path = NULL, transcript_path = NULL,
                       auto_transcript = NULL, auto_transcript_status = NULL,
                       recording_url = NULL, files_purged_at = NOW()
                WHERE id = %s
            """, (row['id'],))
            purged += 1
        _commit()
    finally:
        cur.close()
    if purged:
        logger.info(f"Tilto Pro : fichiers supprimés pour {purged} dossier(s)")
    return purged


# ─── Stockage ───────────────────────────────────────────────────────────────

def _bucket():
    """Bucket audio du quiz (même configuration que audio_service)."""
    is_prod = bool(current_app.config.get('GOOGLE_CLOUD_PROJECT'))
    bucket_name = os.getenv('QUIZ_AUDIO_BUCKET', 'tilto_quiz_audios_prod' if is_prod else 'tilto_quiz_audios_dev')
    scopes = ["https://www.googleapis.com/auth/devstorage.read_write"]
    key_json = current_app.config.get('GCP_SERVICE_ACCOUNT')
    if key_json:
        info = json.loads(key_json) if isinstance(key_json, str) else key_json
        client = storage.Client(credentials=service_account.Credentials.from_service_account_info(info, scopes=scopes))
    else:
        key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
        if key_path and os.path.exists(key_path):
            client = storage.Client(credentials=service_account.Credentials.from_service_account_file(key_path, scopes=scopes))
        else:
            client = storage.Client()
    return client.bucket(bucket_name)


def _delete_blob(path):
    try:
        _bucket().blob(path).delete()
    except Exception as e:
        logger.warning(f"Suppression GCS impossible ({path}): {e}")
