"""Pro-Request-Authentifizierung für den HTTP-Betrieb.

Modell: Der MCP-Client sendet KSC-Credentials als HTTP-Header mit jedem
Request. Eine Starlette-Middleware (siehe server.py) legt sie pro Request in
einer ContextVar ab; Tools lesen sie über use_client() aus.

Header (eigener Namespace, keine Kollision mit MCP-Layer-Auth):
- X-KSC-Authorization: KSC-Auth-Wert 1:1, also 'KSCBasic user="..", ...'
  oder 'KSCT <token>'. Wird nicht geparst, nur durchgeleitet. Hat Vorrang,
  wenn zusätzlich Komponenten-Header vorhanden sind.
- X-KSC-User / X-KSC-Password (+ opt. X-KSC-Domain, X-KSC-Internal 0/1):
  Roh-Credentials; der Server baut daraus intern per build_ksc_basic() den
  KSCBasic-Wert (UTF-8 -> Base64, byte-identisch zum ENV-Pfad).
- X-KSC-VServer (optional): Base64-codierter Virtual-Server-Name.

Fail-closed: Bei KSC_PER_REQUEST_AUTH=1 führt ein Request ohne (gültige)
Header zu einem klaren MCP-Fehler statt ENV-Fallback. Default 0 = heutiges
Verhalten (ENV-Service-Account). Auf stdio gibt es nie Header (ENV-Pfad).
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass

from .config import build_ksc_basic
from .ksc_client import KscError

AUTH_HEADER = "x-ksc-authorization"
VSERVER_HEADER = "x-ksc-vserver"
USER_HEADER = "x-ksc-user"
PASSWORD_HEADER = "x-ksc-password"
DOMAIN_HEADER = "x-ksc-domain"
INTERNAL_HEADER = "x-ksc-internal"
FLAG_ENV = "KSC_PER_REQUEST_AUTH"
MAX_HEADER_LEN = 8192
MAX_CREDENTIAL_LEN = 512


@dataclass(frozen=True)
class RequestAuth:
    authorization: str
    vserver: str | None = None


# Dict mit Roh-Headern, KscError bei malformed Headern, None wenn abwesend.
_request_auth: ContextVar[dict | KscError | None] = ContextVar(
    "ksc_request_auth", default=None
)


def per_request_auth_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = env if env is not None else os.environ
    return (e.get(FLAG_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


def _check_value(name: str, value: str) -> str:
    v = value.strip()
    if not v:
        raise KscError(message=f"Leerer Auth-Header: {name}")
    if len(v) > MAX_HEADER_LEN:
        raise KscError(message=f"Auth-Header zu lang: {name}")
    try:
        v.encode("ascii")
    except UnicodeEncodeError:
        raise KscError(message=f"Ungueltige Zeichen im Auth-Header: {name}") from None
    return v


def _check_component(name: str, value: str) -> str:
    """Validiert Roh-Credentials (User/Passwort/Domain).

    Bewusst nur druckbares ASCII (0x20-0x7E): Standard-HTTP-Clients (z.B.
    httpx) verweigern nicht-ASCII-Header-Werte bereits clientseitig. Wer
    Nicht-ASCII-Credentials hat, codiert sie selbst Base64 und nutzt die
    Verbatim-Variante (X-KSC-Authorization). Verboten sind zusätzlich
    Steuerzeichen (Header-Injection via \\r\\n), leere Werte, Überlänge.
    """
    v = value.strip()
    if not v:
        raise KscError(message=f"Leerer Auth-Header: {name}")
    if len(v) > MAX_CREDENTIAL_LEN:
        raise KscError(message=f"Auth-Header zu lang: {name}")
    if any(ord(c) < 0x20 or ord(c) > 0x7E for c in v):
        raise KscError(message=f"Ungueltige Zeichen im Auth-Header: {name}")
    return v


def _parse_components(lowered: Mapping[str, str]) -> RequestAuth | None:
    raw_user = lowered.get(USER_HEADER)
    raw_pass = lowered.get(PASSWORD_HEADER)
    if raw_user is None and raw_pass is None:
        return None
    user = _check_component(USER_HEADER, str(raw_user or ""))
    password = _check_component(PASSWORD_HEADER, str(raw_pass or ""))
    raw_domain = lowered.get(DOMAIN_HEADER)
    domain = _check_component(DOMAIN_HEADER, str(raw_domain)) if raw_domain and str(raw_domain).strip() else ""
    raw_internal = (lowered.get(INTERNAL_HEADER) or "").strip().lower()
    internal = raw_internal in ("1", "true", "yes", "on")
    return RequestAuth(
        authorization=build_ksc_basic(user, password, domain, internal),
        vserver=None,
    )


def parse_auth_headers(headers: Mapping[str, str]) -> RequestAuth | None:
    """Extrahiert + validiert Auth aus Request-Headern (Case-insensitiv).

    Präzedenz: X-KSC-Authorization (verbatim) gewinnt über Komponenten-Header.
    Gibt None zurück, wenn keine Auth-Header vorhanden sind. Wirft KscError
    bei malformed Headern. Loggt niemals Werte (nur Ausnahmen, ohne Inhalt).
    """
    lowered = {str(k).lower(): v for k, v in headers.items()}
    raw_auth = lowered.get(AUTH_HEADER)
    raw_vs = lowered.get(VSERVER_HEADER)
    vserver = _check_value(VSERVER_HEADER, str(raw_vs)) if raw_vs and str(raw_vs).strip() else None
    if raw_auth is not None and str(raw_auth).strip():
        return RequestAuth(
            authorization=_check_value(AUTH_HEADER, str(raw_auth)),
            vserver=vserver,
        )
    components = _parse_components(lowered)
    if components is None:
        return None
    return RequestAuth(authorization=components.authorization, vserver=vserver)


def set_request_auth(headers: Mapping[str, str]) -> Token:
    """Legt Roh-Header des Requests in der ContextVar ab (Middleware).

    Bei malformed Headern wird die KscError-Instanz abgelegt, damit sie
    später als sauberer MCP-Fehler im Tool-Kontext auftritt (nicht als 500).
    """
    try:
        parsed = parse_auth_headers(headers)
    except KscError as e:
        return _request_auth.set(e)
    return _request_auth.set(
        {"authorization": parsed.authorization, "vserver": parsed.vserver}
        if parsed is not None
        else None
    )


def reset_request_auth(token: Token) -> None:
    _request_auth.reset(token)


def current_request_auth() -> RequestAuth | None:
    """Gibt Request-Auth zurück (None = keine Header), wirft bei malformed."""
    stored = _request_auth.get()
    if stored is None:
        return None
    if isinstance(stored, KscError):
        raise stored
    return RequestAuth(authorization=stored["authorization"], vserver=stored.get("vserver"))
