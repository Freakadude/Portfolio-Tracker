"""Sign-in by Tailscale Serve's identity header (FR-SY-04): trusted only from the named address and
only for the named user; off unless both are set."""

import pytest

from folio.config import Settings
from folio.security.tailscale import HEADER, TailscaleConfigError, enabled, identity, networks


def conf(user: str | None = "you@example.com", proxies: str = "172.18.0.1") -> Settings:
    return Settings(  # type: ignore[call-arg]
        secret_key="x" * 40, tailscale_user=user, trusted_proxies=proxies, _env_file=None
    )


H = {HEADER: "you@example.com"}


def test_it_is_off_unless_both_the_user_and_the_proxies_are_set() -> None:
    assert enabled(conf())
    assert not enabled(conf(user=None))
    assert not enabled(conf(user="  "))
    assert not enabled(conf(proxies=""))
    assert not enabled(conf(proxies=" , "))
    assert identity(conf(user=None), "172.18.0.1", H) is None
    assert identity(conf(proxies=""), "172.18.0.1", H) is None


def test_the_named_user_through_the_named_address_is_recognised() -> None:
    assert identity(conf(), "172.18.0.1", H) == "you@example.com"
    assert identity(conf(), "172.18.0.1", {HEADER: "  You@Example.com "}) == "you@example.com"


def test_the_header_from_anywhere_else_means_nothing() -> None:
    for peer in ("172.18.0.2", "10.0.0.5", "127.0.0.1", "203.0.113.9", "::1"):
        assert identity(conf(), peer, H) is None, peer


def test_another_user_or_no_header_is_not_recognised() -> None:
    assert identity(conf(), "172.18.0.1", {HEADER: "someone@else.com"}) is None
    assert identity(conf(), "172.18.0.1", {}) is None
    assert identity(conf(), "172.18.0.1", {HEADER: ""}) is None


def test_a_peer_that_is_not_an_address_is_never_trusted() -> None:
    for peer in (None, "", "testclient", "unix:/run/x.sock"):
        assert identity(conf(), peer, H) is None


def test_ranges_and_several_addresses_are_understood() -> None:
    both = conf(proxies="172.18.0.0/16, 10.1.2.3, fd00::/8")
    assert len(networks(both)) == 3
    assert identity(both, "172.18.44.7", H) == "you@example.com"
    assert identity(both, "10.1.2.3", H) == "you@example.com"
    assert identity(both, "fd12::1", H) == "you@example.com"
    assert identity(both, "10.1.2.4", H) is None


def test_a_typo_in_the_proxy_list_is_named() -> None:
    with pytest.raises(TailscaleConfigError, match=r"'172\.18\.0\.x'"):
        networks(conf(proxies="172.18.0.1, 172.18.0.x"))
