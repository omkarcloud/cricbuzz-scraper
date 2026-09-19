"""Cricbuzz transport: plain curl_cffi with browser-impersonated TLS. No
browser, no cookies, no proxy needed (validated 2026-09-18 from direct
egress and through a US residential exit; a 40-request burst in one second
answered 200 throughout).

Why the site and not the API every competitor mirrors: the old mobile host
(apiserver.cricbuzz.com, the `/matches/v1/live`, `/mcenter/v1/{id}/scard`
family) no longer resolves, and its successor api.cricbuzz.com sits behind
Akamai and answers 403 to everything, including the `authentication: Bearer
web_…` header the pages leak. www.cricbuzz.com itself is a Next.js App
Router site with two open surfaces:

  * JSON   https://www.cricbuzz.com/api/...
    Route handlers that proxy the internal API and return its raw JSON
    (the same shapes the old mobile API had). PATH params only: a query
    string variant of a path route answers with the 404 HTML page. An
    empty 204 means "no data for this entity/tab" (an upcoming match's
    over list, an unknown match id), never an error. A malformed path can
    hang until the server times out, so every call carries a timeout.

  * PAGES  https://www.cricbuzz.com/<section>/<id>/<slug>
    Server-rendered pages whose data is embedded in the React Server
    Components flight payload (`self.__next_f.push([1,"..."])` chunks,
    decoded by rsc.py). Unknown ids render a 200 "Nothing to show" page,
    detected here and raised as NotFound. A handful of pages (team roster,
    series list, news index, trending players, photo galleries) render
    their data as plain HTML only, parsed with BeautifulSoup in parsers.py.

FALLBACK HOOK: if direct requests AND config.cricbuzz_proxy() both start
failing with CricbuzzBlocked (403/429/challenge HTML), escalate to a browser
the same way g2 does — add a patchright pool with flag "cricbuzz" to
config.CHROME_POOLS, warm it on https://www.cricbuzz.com/ and serve these
same URLs through the in-page driver.get() (patchright_driver.FetchResponse).
Not built now: dead code while plain HTTP works cookie-free.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  CricbuzzUpstreamError  transport failure / 5xx        — retryable
  CricbuzzBlocked        403 / 429 / challenge HTML     — retryable
  CricbuzzBadRequest     upstream 400                   — never retried
  CricbuzzNotFound       404 / "Nothing to show" page   — never retried
"""
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.cricbuzz.com"
IMPERSONATE = "chrome"

JSON_TIMEOUT = 30      # full commentary is ~250 KB; a malformed path hangs, so never unbounded
PAGE_TIMEOUT = 45      # pages are 0.3-1 MB
FANOUT_WORKERS = 4

# The rendered body of the site's 404 component (status is still 200).
NOT_FOUND_MARKER = ">Nothing to show</h2>"

JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-US,en;q=0.9",
    "referer": SITE + "/",
}
PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "upgrade-insecure-requests": "1",
}


class CricbuzzUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class CricbuzzBlocked(CricbuzzUpstreamError, Blocked):
    """403 / 429 or a challenge page where JSON/HTML was expected — retryable."""


class CricbuzzBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class CricbuzzNotFound(NotFound):
    """Entity / page does not exist — never retried."""


# ---- sessions --------------------------------------------------------------------
# One curl session per worker thread (a curl handle must not be shared across
# threads). config.cricbuzz_proxy() is None by default (direct egress).
_local = threading.local()


def _session():
    sess = getattr(_local, "session", None)
    used = getattr(_local, "used", 0)
    if sess is not None and config.CRICBUZZ_REQUESTS_PER_EXIT and used >= config.CRICBUZZ_REQUESTS_PER_EXIT:
        _drop_session()
        sess = None
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = config.cricbuzz_proxy()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
        _local.used = 0
    _local.used = getattr(_local, "used", 0) + 1
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def dump_debug(name, text):
    """Write a raw response to $CRICBUZZ_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("CRICBUZZ_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text)
        except OSError:
            pass


# ---- requests ----------------------------------------------------------------------

def _classify(resp, label):
    status = resp.status_code
    if status == 404:
        raise CricbuzzNotFound(f"{label} not found")
    if status in (401, 403, 429):
        dump_debug("blocked", resp.text)
        raise CricbuzzBlocked(f"HTTP {status} on {label}")
    if status == 400:
        raise CricbuzzBadRequest(f"upstream rejected {label}")
    if status >= 500 or status not in (200, 204):
        raise CricbuzzUpstreamError(f"HTTP {status} on {label}")


def _get(url, *, headers, timeout, label):
    sess = _session()
    try:
        resp = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        raise CricbuzzUpstreamError(f"request failed: {type(e).__name__}: {e}")
    _classify(resp, label)
    return resp


def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except (CricbuzzBlocked, CricbuzzUpstreamError) as e:
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def get_json(path, *, optional=True):
    """GET one /api/... route handler -> parsed JSON, or None when the
    upstream says "nothing here" (204 / empty body).

    The handlers answer an unknown route (or a query-string variant of a
    path route) with the 200 HTML site shell, which is a NotFound here;
    with optional=False an empty body is also a NotFound (endpoints whose
    entity must exist)."""
    url = SITE + path

    def once():
        resp = _get(url, headers=JSON_HEADERS, timeout=JSON_TIMEOUT, label=path)
        body = resp.text or ""
        if resp.status_code == 204 or not body.strip():
            return None
        if not body.lstrip().startswith(("{", "[")):
            dump_debug("nonjson", body)
            if "<html" in body[:400].lower():
                raise CricbuzzNotFound(f"{path} is not a cricbuzz JSON route")
            raise CricbuzzBlocked(f"{path} returned a non-JSON body")
        try:
            return resp.json()
        except Exception:
            dump_debug("badjson", body)
            raise CricbuzzUpstreamError(f"could not parse JSON from {path}")

    data = _retrying(once)
    if data is None and not optional:
        raise CricbuzzNotFound(f"{path} has no data")
    return data


def get_page(path, *, optional=False):
    """GET one cricbuzz.com page -> HTML text. The site renders unknown ids
    as a 200 "Nothing to show" page; that is a NotFound here (or "" with
    optional=True)."""
    url = SITE + path

    def once():
        resp = _get(url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, label=path)
        html = resp.text or ""
        if NOT_FOUND_MARKER in html:
            raise CricbuzzNotFound(f"{path} not found")
        if "<html" not in html[:2000].lower():
            dump_debug("nonhtml", html)
            raise CricbuzzBlocked(f"{path} returned a non-HTML body")
        return html

    try:
        return _retrying(once)
    except CricbuzzNotFound:
        if optional:
            return ""
        raise


def run_parallel(fns):
    """Run zero-arg callables in parallel; results align with `fns`.
    Exceptions propagate from the first failing call."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


def gather(mapping):
    """Run {key: callable} in parallel -> {key: result}; a NotFound or
    BadRequest for one key yields None instead of failing the whole set."""
    keys = list(mapping)

    def guarded(fn):
        def run():
            try:
                return fn()
            except (CricbuzzNotFound, CricbuzzBadRequest):
                return None
        return run

    results = run_parallel([guarded(mapping[k]) for k in keys])
    return dict(zip(keys, results))


if __name__ == "__main__":
    # Smoke test: python cricbuzz/fetch.py [match id]
    target = sys.argv[1] if len(sys.argv) > 1 else "152742"
    data = get_json(f"/api/mcenter/{target}/miniscore")
    print("miniscore:", (data or {}).get("matchHeader", {}).get("status"))
    html = get_page(f"/live-cricket-scores/{target}/x")
    print(f"page: {len(html)} bytes")
