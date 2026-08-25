"""Resolves a Keycloak subject (a UUID) to the human name someone recognizes.

This project's realm is a small, fixed fixture (``keycloak/realm-export.json``,
checked into the repo) rather than a live identity provider with a general
directory — so names are resolved by reading that file once, not by calling
the Keycloak Admin API on every page render.
"""

import json
from functools import lru_cache
from pathlib import Path

REALM_EXPORT_PATH = Path(__file__).resolve().parents[2] / "keycloak" / "realm-export.json"


@lru_cache(maxsize=1)
def _names_by_sub() -> dict[str, str]:
    data = json.loads(REALM_EXPORT_PATH.read_text())
    names: dict[str, str] = {}
    for user in data.get("users", []):
        sub = user.get("id")
        if not sub:
            continue
        full_name = f"{user.get('firstName', '')} {user.get('lastName', '')}".strip()
        names[sub] = full_name or user.get("username", sub)
    return names


def display_name(keycloak_sub: str) -> str:
    """Falls back to a shortened form of the raw sub for anything not in the
    fixture realm (a stale test row, say) rather than raising — this is
    display-only and must never block a page from rendering."""
    known = _names_by_sub()
    if keycloak_sub in known:
        return known[keycloak_sub]
    return keycloak_sub[:8] if keycloak_sub else "unknown"
