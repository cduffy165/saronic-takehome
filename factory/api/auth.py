"""Verifies Keycloak-issued bearer tokens on every state-changing API request.

Signature verification (network: fetches Keycloak's JWKS) is kept separate from
claims validation (pure) so the claims logic is unit-testable without a live
Keycloak instance.
"""

from typing import Annotated, Any

import jwt
from fastapi import Header, HTTPException
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keycloak_issuer: str = "http://auth.localhost:8080/realms/factory"
    keycloak_jwks_url: str = (
        "http://auth.localhost:8080/realms/factory/protocol/openid-connect/certs"
    )
    keycloak_client_id: str = "factory-ui"
    """Checked against the token's azp claim. Keycloak's access tokens for this
    realm don't carry an aud claim by default (verified against a live token) —
    only azp identifies the client, so that's what's checked here instead."""


def get_auth_settings() -> AuthSettings:
    return AuthSettings()


def validate_claims(claims: dict[str, Any], settings: AuthSettings) -> str:
    """Pure: given already signature-verified claims, checks issuer and client,
    and returns the subject. Raises ValueError on any mismatch."""
    if claims.get("iss") != settings.keycloak_issuer:
        raise ValueError(f"unexpected issuer: {claims.get('iss')!r}")
    if claims.get("azp") != settings.keycloak_client_id:
        raise ValueError(f"unexpected client: {claims.get('azp')!r}")
    sub = claims.get("sub")
    if not sub:
        raise ValueError("token has no sub claim")
    return sub


_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client(settings: AuthSettings) -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.keycloak_jwks_url)
    return _jwks_client


def _decode_and_verify(token: str, settings: AuthSettings) -> dict[str, Any]:
    signing_key = _get_jwks_client(settings).get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
    )


async def get_verified_sub(authorization: Annotated[str | None, Header()] = None) -> str:
    """FastAPI dependency: the caller's Keycloak subject, verified from a real,
    signature-checked bearer token — never trusted from a client-supplied field."""
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    token = authorization.removeprefix("Bearer ")
    settings = get_auth_settings()
    try:
        claims = _decode_and_verify(token, settings)
        return validate_claims(claims, settings)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
