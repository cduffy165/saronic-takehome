import uuid

from fastapi.testclient import TestClient

from factory.api.main import app


def test_create_plan_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.post("/plans", json={"message": "hello"})
    assert response.status_code == 401


def test_continue_plan_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.post(f"/plans/{uuid.uuid4()}/messages", json={"message": "hello"})
    assert response.status_code == 401


def test_get_plan_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.get(f"/plans/{uuid.uuid4()}")
    assert response.status_code == 401


def test_approve_plan_requires_bearer_token() -> None:
    client = TestClient(app)
    response = client.post(f"/plans/{uuid.uuid4()}/approve")
    assert response.status_code == 401


def test_malformed_authorization_header_rejected() -> None:
    client = TestClient(app)
    response = client.post(
        "/plans", json={"message": "hello"}, headers={"Authorization": "not-a-bearer-token"}
    )
    assert response.status_code == 401
