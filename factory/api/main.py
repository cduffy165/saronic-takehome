"""FastAPI entrypoint for the app factory's orchestration API."""

from fastapi import FastAPI

app = FastAPI(title="app-factory-api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
