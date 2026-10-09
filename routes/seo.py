"""
Routes SEO programmatiques — pages métiers et villes.

Chaque page :
- A son propre URL canonique indexable Google (ex: /reconversion/commercial)
- Hérite du base.html (header, footer, SEO meta blocks)
- Cible une requête long-tail spécifique
- Contient un CTA vers le diagnostic Tilto
- Référence d'autres pages SEO en interne (linking pour autorité)

Volume actuel : 10 métiers + 10 villes = 20 pages indexables.
À étendre avec data/seo_data.py si besoin.
"""

from flask import Blueprint, render_template, abort
import logging

from data.seo_data import METIERS, VILLES

logger = logging.getLogger(__name__)

seo_bp = Blueprint('seo', __name__)


@seo_bp.route('/reconversion/<metier_slug>')
def metier_page(metier_slug: str):
    """Page programmatique pour un métier en reconversion."""
    metier = METIERS.get(metier_slug)
    if not metier:
        abort(404)

    # Liens internes : 4 autres métiers + 3 villes pour booster le maillage SEO
    related_metiers = [
        m for s, m in METIERS.items() if s != metier_slug
    ][:4]
    featured_villes = list(VILLES.values())[:3]

    return render_template(
        'pages/seo/metier.html',
        metier=metier,
        related_metiers=related_metiers,
        featured_villes=featured_villes,
    )


@seo_bp.route('/orientation/<ville_slug>')
def ville_page(ville_slug: str):
    """Page programmatique pour une ville / bassin d'emploi."""
    ville = VILLES.get(ville_slug)
    if not ville:
        abort(404)

    related_villes = [
        v for s, v in VILLES.items() if s != ville_slug
    ][:4]
    featured_metiers = list(METIERS.values())[:3]

    return render_template(
        'pages/seo/ville.html',
        ville=ville,
        related_villes=related_villes,
        featured_metiers=featured_metiers,
    )


def get_all_seo_urls(base_url: str = 'https://tilto.co') -> list:
    """
    Retourne la liste de toutes les URLs SEO programmatiques pour le sitemap.
    Utilisé par /sitemap.xml dans app.py.
    """
    urls = []
    for slug in METIERS:
        urls.append({
            'loc': f'{base_url}/reconversion/{slug}',
            'priority': '0.7',
            'changefreq': 'monthly',
        })
    for slug in VILLES:
        urls.append({
            'loc': f'{base_url}/orientation/{slug}',
            'priority': '0.7',
            'changefreq': 'monthly',
        })
    return urls
