"""Fetches real access tokens for the fixture users, so evals exercise the same
bearer-token auth path the UI uses — not a bypass of it."""

import os

import httpx

KEYCLOAK_URL = os.environ.get("KEYCLOAK_INTERNAL_URL", "http://auth.localhost:8080")
REALM = "factory"
CLIENT_ID = "factory-ui"
CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "factory-ui-dev-secret")

FIXTURE_USERNAMES = {
    "11111111-1111-1111-1111-111111111111": "alice",
    "22222222-2222-2222-2222-222222222222": "bob",
    "33333333-3333-3333-3333-333333333333": "carol",
    "44444444-4444-4444-4444-444444444444": "dave",
}


def get_access_token(requester_sub: str) -> str:
    username = FIXTURE_USERNAMES[requester_sub]
    response = httpx.post(
        f"{KEYCLOAK_URL}/realms/{REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": username,
            "password": username,  # dev-only realm fixture: password == username
            "scope": "openid",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()["access_token"]
