"""Public web pages (no sign-in): /privacy, /terms, /support and /delete-account, in English, French and Arabic.

The stores link to them (privacy policy URL, account-deletion URL) and the apps open them from More.
The language comes from ``?lang=en|fr|ar``, else the Accept-Language header. Texts: app/legal.py.
"""
from __future__ import annotations

from flask import Blueprint, g, render_template, request
from markupsafe import Markup, escape

from app.i18n import normalize
from app.legal import CONTACT_EMAIL, NAV, PAGES, UPDATED

bp = Blueprint("legal", __name__)

# Official public pages on the QuadraLens website.
SUPPORT_URL = "https://quadralens.tn/product/farmivo/"


def _with_contact(text: str) -> Markup:
    """Escape a text and turn ``{email}`` into a mailto link."""
    link = Markup(f'<a href="mailto:{CONTACT_EMAIL}" dir="ltr">{CONTACT_EMAIL}</a>')
    return escape(text).replace("{email}", link)


@bp.app_template_filter("contact")
def contact_filter(text: str) -> Markup:
    """Jinja filter used by legal/page.html."""
    return _with_contact(text)


def render(page_key: str):
    """Render one public page in the requested language."""
    lang = normalize(request.args.get("lang")) or g.get("lang") or "en"
    return render_template("legal/page.html", lang=lang, page=PAGES[page_key][lang], nav=NAV[lang],
                           current=page_key, updated=UPDATED[lang], email=CONTACT_EMAIL)


PRIVACY_URL = "https://quadralens.tn/product/farmivo-privacy/"


@bp.get("/privacy")
def privacy():
    """GET /privacy - the privacy policy is QuadraLens' official Farmivo page: permanent redirect there."""
    from flask import redirect

    return redirect(PRIVACY_URL, code=301)


@bp.get("/terms")
def terms():
    """GET /terms - the terms of use are on QuadraLens' Farmivo product page: permanent redirect there."""
    from flask import redirect

    return redirect(SUPPORT_URL, code=301)


@bp.get("/support")
def support():
    """GET /support - help and support live on QuadraLens' Farmivo product page: permanent redirect there."""
    from flask import redirect

    return redirect(SUPPORT_URL, code=301)


@bp.get("/delete-account")
def delete_account():
    """GET /delete-account - account deletion is explained on QuadraLens' Farmivo product page: redirect there."""
    from flask import redirect

    return redirect(SUPPORT_URL, code=301)
