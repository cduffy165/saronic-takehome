"""Deterministic container lifecycle for generated apps — no LLM involved here.

Building and running the generated app's image is plain code, not agent-driven:
an LLM never runs arbitrary shell commands in this pipeline (see
factory/agents/build_session.py). The generated container gets no factory env
vars, no volumes, and a small resource cap.
"""

import os
from pathlib import Path

import docker
from docker import DockerClient

PORT_RANGE = range(9000, 9100)
# Used for both the container name and the image tag — one container per
# image, so a separate prefix for each would just be the same string twice.
NAME_PREFIX = "factory-generated-"
FACTORY_NETWORK = os.environ.get("FACTORY_NETWORK", "factory-generated-net")
"""Generated containers get their own network, isolated from postgres/keycloak
— not the network the trusted services run on. Only the api service bridges
both (see compose.yaml)."""


def get_docker_client() -> DockerClient:
    return docker.from_env()


def _used_host_ports(client: DockerClient) -> set[int]:
    used = set()
    for container in client.containers.list(all=True):
        ports = container.attrs.get("NetworkSettings", {}).get("Ports") or {}
        for bindings in ports.values():
            for binding in bindings or []:
                host_port = binding.get("HostPort")
                if host_port:
                    used.add(int(host_port))
    return used


def allocate_port(client: DockerClient) -> int:
    used = _used_host_ports(client)
    for port in PORT_RANGE:
        if port not in used:
            return port
    raise RuntimeError(f"No free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


def get_internal_address(
    client: DockerClient, slug: str, container_internal_port: int = 8501
) -> str:
    """The generated container's own IP on FACTORY_NETWORK, not the published
    host port. The api service talks to the *host's* docker daemon (socket
    mount), so a sibling container's published port lives on the real host's
    network — unreachable as "localhost" from api's own network namespace.
    Reaching the container directly by its internal IP sidesteps that
    entirely. (Custom-network IPs live under NetworkSettings.Networks.<name>,
    not the flat NetworkSettings.IPAddress field — that field is only
    populated for the default "bridge" network.)"""
    container = client.containers.get(f"{NAME_PREFIX}{slug}")
    ip = container.attrs["NetworkSettings"]["Networks"][FACTORY_NETWORK]["IPAddress"]
    return f"{ip}:{container_internal_port}"


def stop_and_remove(client: DockerClient, slug: str) -> None:
    name = f"{NAME_PREFIX}{slug}"
    try:
        container = client.containers.get(name)
    except docker.errors.NotFound:
        return
    container.stop(timeout=5)
    container.remove()


def build_and_run(client: DockerClient, app_dir: Path, slug: str, port: int) -> str:
    """Builds the generated app's image and runs it. Returns the container id."""
    image_tag = f"{NAME_PREFIX}{slug}"
    client.images.build(path=str(app_dir), tag=image_tag, rm=True)

    stop_and_remove(client, slug)

    container = client.containers.run(
        image_tag,
        name=f"{NAME_PREFIX}{slug}",
        ports={"8501/tcp": port},
        network=FACTORY_NETWORK,
        detach=True,
        environment={},
        volumes={},
        mem_limit="256m",
        privileged=False,
    )
    return container.id
