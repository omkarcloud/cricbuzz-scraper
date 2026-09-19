"""Configuration for the Cricbuzz Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT             port the API listens on (default 8000)
    CRICBUZZ_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                     (default: none — direct). Cricbuzz runs no anti-bot on the
                     pages this scraper reads and did not rate-limit a 40-request
                     burst from one IP, so you very likely don't need this. Set it
                     only if you start seeing failures at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Rotate the HTTP session after N requests. 0 keeps one session for the life
# of the thread, which is what you want without a rotating proxy.
CRICBUZZ_REQUESTS_PER_EXIT = 0

CRICBUZZ_PROXY = os.environ.get("CRICBUZZ_PROXY") or None


def cricbuzz_proxy():
    """The proxy every request goes through (None = direct)."""
    return CRICBUZZ_PROXY
