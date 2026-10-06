"""Optional sign-in by Tailscale Serve's identity headers (FR-SY-04).

Tailscale Serve can pass the tailnet login of the person connecting in `Tailscale-User-Login`.
Anyone who can reach Folio directly can write that header, so it is trusted only when the TCP
peer is one of the addresses the owner named in FOLIO_TRUSTED_PROXIES (the machine Tailscale
Serve runs on) and the login equals FOLIO_TAILSCALE_USER. Both must be set; with either missing
it is off. The peer check comes first.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping

from folio.config import Settings

HEADER = "tailscale-user-login"

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


class TailscaleConfigError(ValueError):
    """FOLIO_TRUSTED_PROXIES is not a list of addresses or ranges."""


def networks(settings: Settings) -> list[Network]:
    out: list[Network] = []
    for part in settings.trusted_proxies.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            out.append(ipaddress.ip_network(text, strict=False))
        except ValueError as exc:
            raise TailscaleConfigError(
                f"FOLIO_TRUSTED_PROXIES has {text!r}, which is not an address or a range "
                "such as 172.18.0.1 or 10.0.0.0/8."
            ) from exc
    return out


def enabled(settings: Settings) -> bool:
    return bool(settings.tailscale_user and settings.tailscale_user.strip()) and bool(
        networks(settings)
    )


def identity(settings: Settings, peer: str | None, headers: Mapping[str, str]) -> str | None:
    """The configured tailnet login when this request really comes through Tailscale Serve and
    names that login, else None."""
    if not enabled(settings) or not peer:
        return None
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:  # not an IP at all (a test client, a unix socket)
        return None
    if not any(address in net for net in networks(settings)):
        return None  # anyone else may write the header: it means nothing
    login = headers.get(HEADER, "").strip().lower()
    wanted = (settings.tailscale_user or "").strip().lower()
    return wanted if login and login == wanted else None
