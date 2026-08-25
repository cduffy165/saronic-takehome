from factory.agents.container_runtime import PORT_RANGE, _used_host_ports, allocate_port


class _FakeContainer:
    def __init__(self, ports: dict) -> None:
        self.attrs = {"NetworkSettings": {"Ports": ports}}


class _FakeClient:
    def __init__(self, containers: list[_FakeContainer]) -> None:
        self._containers = containers
        self.containers = self

    def list(self, all: bool = False) -> list[_FakeContainer]:  # noqa: A002
        return self._containers


def test_used_host_ports_empty_when_no_containers() -> None:
    client = _FakeClient([])

    assert _used_host_ports(client) == set()


def test_used_host_ports_collects_bound_ports() -> None:
    client = _FakeClient(
        [
            _FakeContainer({"8501/tcp": [{"HostPort": "9000"}]}),
            _FakeContainer({"8501/tcp": [{"HostPort": "9001"}]}),
        ]
    )

    assert _used_host_ports(client) == {9000, 9001}


def test_used_host_ports_ignores_unbound_ports() -> None:
    client = _FakeClient([_FakeContainer({"8501/tcp": None})])

    assert _used_host_ports(client) == set()


def test_allocate_port_returns_first_free_port_in_range() -> None:
    client = _FakeClient([_FakeContainer({"8501/tcp": [{"HostPort": str(PORT_RANGE.start)}]})])

    assert allocate_port(client) == PORT_RANGE.start + 1


def test_allocate_port_raises_when_range_exhausted() -> None:
    containers = [_FakeContainer({"8501/tcp": [{"HostPort": str(port)}]}) for port in PORT_RANGE]
    client = _FakeClient(containers)

    try:
        allocate_port(client)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
