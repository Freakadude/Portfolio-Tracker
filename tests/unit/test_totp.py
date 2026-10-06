"""Time-based one-time passwords on the standard library (FR-SY-03), against the RFC vectors."""

import base64
from datetime import UTC, datetime

from folio.security import totp

# the RFC's published test secret, the ASCII string 12345678901234567890, in base32 (it is
# made here, not written out, so the secret scan has nothing to mistake for a real key)
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC)


def test_the_hotp_codes_match_rfc_4226() -> None:
    assert [totp.hotp(RFC_SECRET, n) for n in range(5)] == [
        "755224",
        "287082",
        "359152",
        "969429",
        "338314",
    ]


def test_the_totp_codes_match_rfc_6238_with_six_digits() -> None:
    # the RFC lists eight digits (94287082, ...); six digits are the last six of those
    for seconds, expected in (
        (59, "287082"),
        (1111111109, "081804"),
        (1111111111, "050471"),
        (1234567890, "005924"),
        (2000000000, "279037"),
        (20000000000, "353130"),
    ):
        assert totp.code_at(RFC_SECRET, at(seconds)) == expected


def test_a_code_is_good_for_its_own_step_and_one_either_side() -> None:
    now = at(1111111109)
    step = totp.step_of(now)
    for offset, ok in ((-2, False), (-1, True), (0, True), (1, True), (2, False)):
        code = totp.hotp(RFC_SECRET, step + offset)
        assert (totp.verify(RFC_SECRET, code, now) is not None) is ok, offset
    assert totp.verify(RFC_SECRET, totp.hotp(RFC_SECRET, step), now) == step


def test_a_code_is_never_accepted_twice_nor_an_older_one() -> None:
    now = at(1111111109)
    step = totp.step_of(now)
    code = totp.hotp(RFC_SECRET, step)
    assert totp.verify(RFC_SECRET, code, now, last_step=step - 1) == step
    assert totp.verify(RFC_SECRET, code, now, last_step=step) is None  # used
    assert totp.verify(RFC_SECRET, totp.hotp(RFC_SECRET, step - 1), now, last_step=step) is None
    assert totp.verify(RFC_SECRET, totp.hotp(RFC_SECRET, step + 1), now, last_step=step) == step + 1


def test_spaces_and_dashes_are_ignored_and_junk_is_refused() -> None:
    now = at(59)
    code = totp.code_at(RFC_SECRET, now)
    assert totp.verify(RFC_SECRET, f"{code[:3]} {code[3:]}", now) is not None
    assert totp.verify(RFC_SECRET, f"{code[:3]}-{code[3:]}", now) is not None
    for bad in ("", "12345", "1234567", "abcdef", "28708２"):
        assert totp.verify(RFC_SECRET, bad, now) is None


def test_a_new_secret_is_160_random_bits_in_base32_and_can_be_grouped() -> None:
    first, second = totp.new_secret(), totp.new_secret()
    assert (
        first != second
        and len(first) == 32
        and set(first) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
    )
    assert totp.group(first).replace(" ", "") == first and totp.group(first).count(" ") == 7
    assert totp.verify(totp.group(first), totp.code_at(first, at(59)), at(59)) is not None


def test_the_link_for_the_app_names_folio_the_account_and_the_secret() -> None:
    uri = totp.provisioning_uri(RFC_SECRET, "owner")
    assert uri.startswith("otpauth://totp/Folio%3Aowner?")
    assert f"secret={RFC_SECRET}" in uri and "issuer=Folio" in uri
    assert "algorithm=SHA1" in uri and "digits=6" in uri and "period=30" in uri


def test_the_qr_code_is_an_svg_of_the_link() -> None:
    svg = totp.qr_svg(totp.provisioning_uri(RFC_SECRET, "owner"))
    assert svg.startswith("<svg") and "width=" not in svg.split(">")[0]  # sized by the page


def test_recovery_codes_are_twelve_unambiguous_characters_and_all_different() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    for code in codes:
        assert len(code) == 14 and code.count("-") == 2
        assert not set(code.replace("-", "")) & set("01IO")
    assert totp.normalize_recovery(" k7qm-2xpd 9hvt ") == "K7QM2XPD9HVT"
