"""Runs one golden plan through the real Build -> Review -> dockerize pipeline and
asserts the required files exist, the image builds, and the container responds on
its allocated port. Costs real money and takes ~1-2 minutes. Run inside the api
container: `make eval-build`. Cleans up its own container, image, generated
directory, and database rows when done.
"""

import asyncio
import shutil
import sys
import time
import urllib.error
import urllib.request

from factory.agents.build_review_orchestrator import (
    GENERATED_APPS_DIR,
    REQUIRED_FILES,
    run_build_and_review,
    slugify,
)
from factory.agents.container_runtime import (
    get_docker_client,
    get_internal_address,
    stop_and_remove,
)
from factory.registry.db import get_session_factory
from factory.registry.models import Run

GOLDEN_PLAN = {
    "outcome": "proceed",
    "name": "Eval Build Golden App",
    "purpose": "A minimal notes app used only to smoke-test the Build/Review pipeline.",
    "blueprint_id": "streamlit-small",
    "complexity_score": 1,
    "score_justification": {"data_sources": "in-memory only"},
    "capabilities": [
        {"slug": "submit_note", "description": "Submit a short text note."},
        {"slug": "view_notes", "description": "View submitted notes."},
    ],
}


def _wait_for_health(address: str, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://{address}/_stcore/health", timeout=2):
                return True
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(1)
    return False


async def main() -> None:
    session_factory = get_session_factory()
    with session_factory() as session:
        plan_run = Run(kind="plan", outcome="proceed", plan={"result": GOLDEN_PLAN})
        session.add(plan_run)
        session.commit()

        result = await run_build_and_review(session, plan_run)

        ok = True
        details = []

        if not result.success:
            ok = False
            details.append(f"build/review did not succeed: {result.summary}")
        else:
            details.append(f"build/review succeeded in {result.attempts} attempt(s)")

            slug = slugify(GOLDEN_PLAN["name"])
            app_dir = GENERATED_APPS_DIR / slug
            missing = [f for f in REQUIRED_FILES if not (app_dir / f).is_file()]
            if missing:
                ok = False
                details.append(f"missing required files after build: {missing}")
            else:
                details.append("all required files present")

            client = get_docker_client()
            internal_address = get_internal_address(client, slug)
            if _wait_for_health(internal_address):
                details.append(f"container responded at {internal_address}")
            else:
                ok = False
                details.append(f"container did not respond at {internal_address}")

            stop_and_remove(client, slug)
            client.images.remove(f"factory-generated-{slug}", force=True)
            shutil.rmtree(app_dir, ignore_errors=True)

        build_review_run = session.get(Run, result.run_id)
        if build_review_run is not None:
            session.delete(build_review_run)
        session.delete(plan_run)
        session.commit()

    for line in details:
        print(f"- {line}")
    print(f"\n{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
