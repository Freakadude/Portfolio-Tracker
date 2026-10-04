"""Container healthcheck: `python -m folio.healthcheck http://localhost:8080/healthz`."""

import sys
import urllib.request


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else "http://localhost:8080/healthz"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (fixed local URL)
            return 0 if resp.status == 200 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
