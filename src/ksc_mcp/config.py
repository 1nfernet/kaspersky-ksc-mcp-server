"""ENV-Konfiguration. Unterstützt Basis-Auth und Token-Auth (Token hat Vorrang)."""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass


def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


@dataclass(frozen=True)
class KscConfig:
    host: str
    port: int = 13299
    user: str = ""
    password: str = ""
    domain: str = ""
    internal: bool = False
    token: str = ""
    vserver: str = ""
    verify: str | bool = False
    timeout: float = 30.0

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"

    @property
    def use_token_auth(self) -> bool:
        return bool(self.token and self.token.strip())

    def auth_header(self) -> str:
        if self.use_token_auth:
            return f"KSCT {self.token.strip()}"
        u = _b64(self.user)
        p = _b64(self.password)
        if self.internal or not self.domain:
            return f'KSCBasic user="{u}", pass="{p}", internal="1"' if self.internal else f'KSCBasic user="{u}", pass="{p}", internal="0"'
        d = _b64(self.domain)
        return f'KSCBasic user="{u}", pass="{p}", domain="{d}", internal="0"'

    def vserver_header(self) -> str | None:
        if self.vserver and self.vserver.strip():
            return _b64(self.vserver.strip())
        return None

    @staticmethod
    def _parse_verify(raw: str | None) -> str | bool:
        if raw is None or raw == "":
            return False
        v = raw.strip().lower()
        if v in ("false", "0", "no", "off"):
            return False
        if v in ("true", "1", "yes", "on"):
            return True
        return raw.strip()  # Pfad zur .cer

    @classmethod
    def from_env(cls, env: dict | None = None) -> KscConfig:
        e = env if env is not None else os.environ
        host = (e.get("KSC_HOST") or "").strip()
        if not host:
            raise ValueError("KSC_HOST ist nicht gesetzt (siehe .env.example)")
        try:
            port = int(e.get("KSC_PORT") or 13299)
        except ValueError:
            raise ValueError(f"Ungueltiger KSC_PORT: {e.get('KSC_PORT')!r} (Ganzzahl erwartet)")
        internal_raw = (e.get("KSC_INTERNAL") or "0").strip().lower()
        internal = internal_raw in ("1", "true", "yes", "on")
        try:
            timeout = float(e.get("KSC_TIMEOUT") or 30.0)
        except ValueError:
            raise ValueError(f"Ungueltiger KSC_TIMEOUT: {e.get('KSC_TIMEOUT')!r} (Zahl erwartet)")
        cfg = cls(
            host=host,
            port=port,
            user=e.get("KSC_USER") or "",
            password=e.get("KSC_PASS") or "",
            domain=(e.get("KSC_DOMAIN") or "").strip(),
            internal=internal,
            token=(e.get("KSC_TOKEN") or "").strip(),
            vserver=(e.get("KSC_VSERVER") or "").strip(),
            verify=cls._parse_verify(e.get("KSC_VERIFY")),
            timeout=timeout,
        )
        if not cfg.use_token_auth and not cfg.user:
            raise ValueError("Weder KSC_TOKEN noch KSC_USER gesetzt — eine Auth-Methode ist erforderlich")
        return cfg
