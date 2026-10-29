"""Startet PFERD (ILIAS-Downloader) mit den Anpassungen für das ILIAS der Uni Mannheim.

1. SAML-Login: PFERD ruft {base_url}/shib_login.php auf, Mannheim nutzt saml.php.
   Das Passwort geht nur an https://idp.uni-mannheim.de, egal wohin ILIAS umleitet.
2. Kurse: In "Meine Kurse und Gruppen" steigt PFERD in die Kurse ab (sonst nur auf
   dem Dashboard). Die Einträge dieser Seite werden nach der Kursauswahl gefiltert,
   bekommen ihren kurzen Ordnernamen und werden für sync.py mitgeschrieben.
3. Cookies: liegen im App-Ordner statt im Ausgabeordner.
4. Kein Warten auf Eingaben: fehlt das Passwort oder wird es abgelehnt, bricht
   PFERD sofort mit einer Fehlermeldung ab, statt endlos auf eine Eingabe zu warten.

Die Kursauswahl kommt als JSON-Datei über die Umgebungsvariable ILIAS_SYNC_SELECTION:
{"courses": {...}, "include_new": bool, "list_only": bool, "discovered": "<pfad>"}.
Mit list_only meldet PFERD nur die Kurse und lädt nichts (Login-Prüfung im Assistenten).
"""

import dataclasses
import inspect
import json
import os
import sys
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

import keyring
from PFERD.auth import AuthError
from PFERD.auth.keyring import KeyringAuthenticator
from PFERD.auth.tfa import TfaAuthenticator
from PFERD.__main__ import main
from PFERD.crawl import http_crawler
from PFERD.crawl.crawler import CrawlError
from PFERD.crawl.ilias import ilias_web_crawler, shibboleth_login
from PFERD.crawl.ilias.kit_ilias_html import IliasPage

import courses
from core import APP_DIR

COOKIE_FILE = APP_DIR / "cookies.txt"
LOGIN_HOST = "idp.uni-mannheim.de"
SELECTION = json.loads(Path(os.environ["ILIAS_SYNC_SELECTION"]).read_text(encoding="utf-8"))

# 1. SAML-Einstieg
source = textwrap.dedent(inspect.getsource(shibboleth_login.ShibbolethLogin.login))
if "/shib_login.php" not in source:
    sys.exit("pferd_runner: Diese PFERD-Version passt nicht mehr zum SAML-Patch.")
namespace: dict = {}
exec(source.replace("/shib_login.php", "/saml.php"), vars(shibboleth_login), namespace)
shibboleth_login.ShibbolethLogin.login = namespace["login"]

_original_post = shibboleth_login._post


async def _post_only_to_uni_login(session, url, data):
    # _post schickt die Zugangsdaten (und ggf. den zweiten Faktor)
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname != LOGIN_HOST:
        raise CrawlError(f"Login-Formular zeigt auf {parts.hostname!r} statt {LOGIN_HOST!r}, Passwort nicht gesendet")
    return await _original_post(session, url, data)


shibboleth_login._post = _post_only_to_uni_login

# 2. Kurse
_original_crawl_url = ilias_web_crawler.IliasWebCrawler._crawl_url


async def _crawl_url_into_courses(self, url, expected_id=None, crawl_nested_courses=False):
    crawl_nested_courses = crawl_nested_courses or "baseClass=ilmembershipoverviewgui" in url
    await _original_crawl_url(self, url, expected_id, crawl_nested_courses)


ilias_web_crawler.IliasWebCrawler._crawl_url = _crawl_url_into_courses

_original_children = IliasPage.get_child_elements


def _children_with_course_selection(self):
    elements = _original_children(self)
    if not self._is_course_overview_page():
        return elements
    entries = [{"title": element.name, "url": element.url} for element in elements]
    known = SELECTION["courses"]
    new = courses.suggest(entries, known)
    for settings in new.values():
        settings["sync"] = settings["sync"] and SELECTION["include_new"]
    Path(SELECTION["discovered"]).write_text(
        json.dumps({"entries": entries, "new": new}, ensure_ascii=False), encoding="utf-8"
    )
    if SELECTION["list_only"]:
        return []
    chosen = []
    for element in elements:
        settings = known.get(element.name) or new[element.name]
        if settings["sync"]:
            chosen.append(dataclasses.replace(element, name=settings["name"]))
    return chosen


IliasPage.get_child_elements = _children_with_course_selection

# 3. Cookies
_original_init = http_crawler.HttpCrawler.__init__


def _init_with_private_cookies(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self._cookie_jar_path = COOKIE_FILE


http_crawler.HttpCrawler.__init__ = _init_with_private_cookies

# 4. Nie nach Passwort oder Zwei-Faktor-Code fragen: Im Hintergrund gibt es kein Terminal,
#    PFERD würde auf die Eingabe endlos warten. Stattdessen mit klarer Meldung abbrechen.


async def _credentials_from_keychain(self):
    if self._password_invalidated:
        raise AuthError("ILIAS-Anmeldung abgelehnt: Uni-ID oder Passwort falsch")
    password = keyring.get_password(self._keyring_name, self._username)
    if not password:
        raise AuthError("Kein Passwort im Schlüsselbund")
    self._password = password
    return self._username, password


async def _no_tfa_prompt(self):
    raise AuthError("Der Login verlangt einen zweiten Faktor, das wird nicht unterstützt")


KeyringAuthenticator.credentials = _credentials_from_keychain
TfaAuthenticator.password = _no_tfa_prompt

main()
