"""No test makes a network call (Phase 5 spec 13.2, conflict 32; design E12). Not a test module.

conftest.py installs this before the application is imported, so it covers the whole session (evaluation/tests too
when it runs with the API suite). It patches socket.socket.connect and connect_ex, socket.create_connection and
socket.getaddrinfo to refuse any host that is not loopback: 127.0.0.0/8, ::1, "localhost", the empty host and AF_UNIX
sockets pass (Windows socketpair and asyncio's self-pipe connect to 127.0.0.1, and the test PostgreSQL listens
there). A refused attempt raises NetworkBlocked before any packet is sent and is recorded, and conftest's autouse
fixture fails the test that made it, even when the code under test caught the exception.
"""

from __future__ import annotations

import ipaddress
import socket
import threading

LOCAL_NAMES = frozenset({"", "localhost", "localhost.localdomain"})
_blocked: list[str] = []
_lock = threading.Lock()
_installed = False
_original = {}


class NetworkBlocked(RuntimeError):
    """A test tried to reach a non-loopback host (no test may touch the network)."""


def _is_local(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = str(host).strip().lower().strip("[]")
    if host in LOCAL_NAMES or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def _refuse(what: str) -> None:
    with _lock:
        _blocked.append(what)
    raise NetworkBlocked(f"no test may touch the network: {what}")


def _host_of(address) -> object:
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return address


def take_blocked() -> list[str]:
    """The attempts refused since the last call (the autouse fixture reads and clears them)."""
    with _lock:
        taken = list(_blocked)
        _blocked.clear()
    return taken


def install() -> None:
    global _installed
    if _installed:
        return
    _installed = True
    _original.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                     create_connection=socket.create_connection, getaddrinfo=socket.getaddrinfo)

    def connect(self, address):
        if self.family != getattr(socket, "AF_UNIX", object()) and not _is_local(_host_of(address)):
            _refuse(f"connect {_host_of(address)!s}")
        return _original["connect"](self, address)

    def connect_ex(self, address):
        if self.family != getattr(socket, "AF_UNIX", object()) and not _is_local(_host_of(address)):
            _refuse(f"connect_ex {_host_of(address)!s}")
        return _original["connect_ex"](self, address)

    def create_connection(address, *args, **kwargs):
        if not _is_local(_host_of(address)):
            _refuse(f"create_connection {_host_of(address)!s}")
        return _original["create_connection"](address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        if not _is_local(host):
            _refuse(f"getaddrinfo {host!s}")
        return _original["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
