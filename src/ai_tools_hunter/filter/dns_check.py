"""S3 DNS presence layer: is the domain actually resolving?

Cheap one-shot DNS check per domain. The signal is binary-ish:
a registered domain that does not resolve at all is likely parked,
squatted, or a placeholder — not a live newborn site.

Uses only the standard library (``socket.getaddrinfo``) so the filter
layer stays dependency-free. DNS failures (NXDOMAIN, timeouts) are
treated as "no A record" rather than errors, because for our purpose
a non-resolving domain is exactly the signal we want to surface.

``getaddrinfo`` takes no timeout argument, so the lookup runs on a daemon
thread and the caller stops waiting after ``timeout`` seconds. Without that
the ``timeout`` parameter was accepted and silently ignored, and a single
hanging lookup could hold a filter worker for as long as the OS resolver
felt like it.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DnsResult:
    """DNS presence result for one domain."""

    domain: str
    has_a: bool
    addresses: tuple[str, ...]
    error: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "domain": self.domain,
            "has_a": self.has_a,
            "addresses": list(self.addresses),
            "error": self.error,
        }


class DnsLookupTimeout(TimeoutError):
    """Raised when one lookup exceeds the caller-supplied timeout."""


def _getaddrinfo_with_timeout(
    domain: str, family: int, timeout: float | None
) -> list[tuple]:
    """Resolve ``domain``, giving up after ``timeout`` seconds.

    ``timeout`` of ``None`` or ``0`` disables the bound and resolves inline.
    """
    if timeout is None or timeout <= 0:
        return socket.getaddrinfo(
            domain, None, family=family, type=socket.SOCK_STREAM
        )

    box: dict[str, object] = {}

    def resolve() -> None:
        try:
            box["infos"] = socket.getaddrinfo(
                domain, None, family=family, type=socket.SOCK_STREAM
            )
        except BaseException as error:  # noqa: BLE001 - re-raised on the caller
            box["error"] = error

    # Daemon thread on purpose: a resolver that never returns must not keep the
    # interpreter alive at shutdown.
    worker = threading.Thread(target=resolve, name=f"dns-{domain}", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise DnsLookupTimeout(f"lookup for {domain!r} exceeded {timeout:g}s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["infos"]  # type: ignore[return-value]


def check_dns(
    domains: Iterable[str],
    *,
    timeout: float | None = 5.0,
    family: int = socket.AF_UNSPEC,
) -> dict[str, DnsResult]:
    """Resolve A/AAAA records for each domain. One shot per domain."""
    results: dict[str, DnsResult] = {}
    for domain in domains:
        domain = domain.rstrip(".").lower()
        try:
            infos = _getaddrinfo_with_timeout(domain, family, timeout)
            addresses = tuple(sorted({info[4][0] for info in infos}))
            results[domain] = DnsResult(
                domain=domain, has_a=True, addresses=addresses
            )
        except DnsLookupTimeout as exc:
            results[domain] = DnsResult(
                domain=domain, has_a=False, addresses=(), error=str(exc)
            )
        except socket.gaierror as exc:
            results[domain] = DnsResult(
                domain=domain, has_a=False, addresses=(), error=str(exc)
            )
        except OSError as exc:
            results[domain] = DnsResult(
                domain=domain, has_a=False, addresses=(), error=str(exc)
            )
    return results
