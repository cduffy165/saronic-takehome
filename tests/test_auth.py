import pytest

from factory.api.auth import AuthSettings, validate_claims

SETTINGS = AuthSettings(
    keycloak_issuer="http://auth.localhost:8080/realms/factory",
    keycloak_client_id="factory-ui",
)


def test_validate_claims_accepts_matching_issuer_and_client() -> None:
    claims = {
        "iss": "http://auth.localhost:8080/realms/factory",
        "azp": "factory-ui",
        "sub": "11111111-1111-1111-1111-111111111111",
    }

    assert validate_claims(claims, SETTINGS) == "11111111-1111-1111-1111-111111111111"


def test_validate_claims_rejects_wrong_issuer() -> None:
    claims = {
        "iss": "http://evil.example.com/realms/factory",
        "azp": "factory-ui",
        "sub": "x",
    }

    with pytest.raises(ValueError, match="issuer"):
        validate_claims(claims, SETTINGS)


def test_validate_claims_rejects_wrong_client() -> None:
    claims = {
        "iss": "http://auth.localhost:8080/realms/factory",
        "azp": "some-other-client",
        "sub": "x",
    }

    with pytest.raises(ValueError, match="client"):
        validate_claims(claims, SETTINGS)


def test_validate_claims_rejects_missing_sub() -> None:
    claims = {
        "iss": "http://auth.localhost:8080/realms/factory",
        "azp": "factory-ui",
    }

    with pytest.raises(ValueError, match="sub"):
        validate_claims(claims, SETTINGS)
