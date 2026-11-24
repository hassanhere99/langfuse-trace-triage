#!/usr/bin/env python3
"""Fetch one Langfuse trace (with observations and scores) and write it as JSON.

Read-only: every request is an HTTP GET. Standard library only.

Docs used (checked 2026-11-24):
  - Public API overview, auth (HTTP Basic: public key = user, secret key = password),
    regional base URLs, Observations API v2, Scores API v3:
    https://langfuse.com/docs/api-and-data-platform/features/public-api
  - Deprecated endpoint mapping (GET /api/public/traces/{traceId} is deprecated and
    Langfuse Cloud stopped serving it on 2026-11-16; use GET /api/public/v2/observations
    with traceId and rebuild the trace client-side):
    https://langfuse.com/faq/all/deprecated-api-migration
  - Single trace export via API:
    https://langfuse.com/faq/all/export-single-trace-or-session
  - API reference / OpenAPI spec (v2 observations params, field groups, v3 scores):
    https://api.reference.langfuse.com
    https://cloud.langfuse.com/generated/api/openapi.yml

Endpoints used:
  1. GET {host}/api/public/v2/observations?traceId=<id>&fields=...&limit=1000[&cursor=...]
     (Langfuse Cloud and self-hosted v4). Rows are grouped into a trace object.
  2. GET {host}/api/public/traces/{traceId}
     Fallback only, for self-hosted Langfuse v3, which has no v2 endpoints. Returns
     the TraceWithFullDetails body as is.
  3. GET {host}/api/public/v3/scores?traceId=<id>&fields=details,subject
     (falls back to GET /api/public/v2/scores?traceId=<id> on older servers).

Output shape: the TraceWithFullDetails shape (id, timestamp, name, input, output,
metadata, tags, userId, sessionId, observations[], scores[]). With the v2 API there
are no trace-level fields, so name, input, output and metadata come from the root
observation and timestamp is the earliest observation start time. That is noted in
the "reconstructedFrom" key.

Exit codes:
  0 ok
  2 bad command line usage
  3 missing LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
  4 authentication failed (HTTP 401 or 403)
  5 trace not found (HTTP 404 / no observations)
  6 network error (DNS, connection refused, timeout, TLS)
  7 other HTTP error (4xx/5xx, redirects)
  8 unexpected response body (not JSON)
"""

import argparse
import base64
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_MISSING_KEYS = 3
EXIT_AUTH = 4
EXIT_NOT_FOUND = 5
EXIT_NETWORK = 6
EXIT_HTTP = 7
EXIT_BAD_RESPONSE = 8

DEFAULT_HOST = "https://cloud.langfuse.com"
TIMEOUT_SECONDS = 30
OBSERVATION_FIELDS = "core,basic,time,io,metadata,model,usage,trace_context"
MAX_PAGES = 200


class FetchError(Exception):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class _NotFound(Exception):
    def __init__(self, path, detail=""):
        super().__init__(path)
        self.path = path
        self.detail = detail


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not follow redirects: urllib would forward the Authorization header."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def load_env_file(path):
    """Parse a simple KEY=VALUE file. Supports comments, `export`, and quotes."""
    values = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].lstrip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            if key:
                values[key] = value
    return values


def get_credentials(env):
    public = (env.get("LANGFUSE_PUBLIC_KEY") or "").strip()
    secret = (env.get("LANGFUSE_SECRET_KEY") or "").strip()
    missing = [
        name
        for name, val in (("LANGFUSE_PUBLIC_KEY", public), ("LANGFUSE_SECRET_KEY", secret))
        if not val
    ]
    if missing:
        raise FetchError(
            "Missing environment variable(s): %s. Set them (Langfuse project settings, "
            "API keys) or pass --env-file. See .env.example." % ", ".join(missing),
            EXIT_MISSING_KEYS,
        )
    host = (env.get("LANGFUSE_HOST") or DEFAULT_HOST).strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        raise FetchError(
            "LANGFUSE_HOST must start with http:// or https:// (got %r)." % host,
            EXIT_USAGE,
        )
    return public, secret, host


def _error_detail(exc):
    if exc.code in (301, 302, 303, 307, 308):
        return " Redirect to %s was not followed." % exc.headers.get("Location", "?")
    try:
        text = exc.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""
    return (" Response: " + text[:300]) if text else ""


def api_get(host, path, params, public, secret):
    """One GET request. Returns parsed JSON. Raises FetchError with a mapped exit code."""
    query = urllib.parse.urlencode([(k, v) for k, v in params if v is not None])
    url = host + path + ("?" + query if query else "")
    token = base64.b64encode(("%s:%s" % (public, secret)).encode("utf-8")).decode("ascii")
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": "Basic " + token,
            "Accept": "application/json",
            "User-Agent": "langfuse-trace-triage-fetch/1.0",
        },
    )
    try:
        with _opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = _error_detail(exc)
        if exc.code in (401, 403):
            raise FetchError(
                "Langfuse rejected the credentials (HTTP %d) for %s. Check that "
                "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY belong to the same project and "
                "that LANGFUSE_HOST matches its region (EU https://cloud.langfuse.com, "
                "US https://us.cloud.langfuse.com, JP https://jp.cloud.langfuse.com)."
                "%s" % (exc.code, host, detail),
                EXIT_AUTH,
            )
        if exc.code == 404:
            raise _NotFound(path, detail)
        raise FetchError(
            "Langfuse returned HTTP %d for GET %s.%s" % (exc.code, path, detail), EXIT_HTTP
        )
    except urllib.error.URLError as exc:
        hint = ""
        if "CERTIFICATE_VERIFY_FAILED" in str(exc.reason):
            hint = (
                " Python cannot find CA certificates. On macOS python.org builds run "
                "'Install Certificates.command', or set SSL_CERT_FILE to a CA bundle "
                "(for example /etc/ssl/cert.pem)."
            )
        raise FetchError(
            "Network error talking to %s: %s.%s" % (host, exc.reason, hint), EXIT_NETWORK
        )
    except (socket.timeout, TimeoutError):
        raise FetchError(
            "Timed out after %ds talking to %s." % (TIMEOUT_SECONDS, host), EXIT_NETWORK
        )
    except OSError as exc:
        raise FetchError("Network error talking to %s: %s" % (host, exc), EXIT_NETWORK)
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise FetchError(
            "Response from GET %s was not valid JSON. Is LANGFUSE_HOST (%s) a Langfuse "
            "server?" % (path, host),
            EXIT_BAD_RESPONSE,
        )


def _maybe_json(value):
    """The v2 API returns input/output/metadata as raw strings; parse them when JSON."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def fetch_v2_observations(host, trace_id, public, secret):
    rows = []
    cursor = None
    for _ in range(MAX_PAGES):
        page = api_get(
            host,
            "/api/public/v2/observations",
            [
                ("traceId", trace_id),
                ("fields", OBSERVATION_FIELDS),
                ("limit", "1000"),
                ("cursor", cursor),
            ],
            public,
            secret,
        )
        rows.extend(page.get("data") or [])
        cursor = (page.get("meta") or {}).get("cursor")
        if not cursor:
            break
    return rows


def normalize_observation(row):
    obs = dict(row)
    for key in ("input", "output", "metadata"):
        if key in obs:
            obs[key] = _maybe_json(obs[key])
    return obs


def build_trace_from_observations(trace_id, rows):
    """Rebuild a TraceWithFullDetails-shaped dict from Observations API v2 rows."""
    obs = [normalize_observation(r) for r in rows]
    obs.sort(key=lambda o: o.get("startTime") or "")
    roots = [o for o in obs if o.get("isRootObservation")] or [
        o for o in obs if not o.get("parentObservationId")
    ]
    root = roots[0] if roots else (obs[0] if obs else {})
    first = obs[0] if obs else {}
    return {
        "id": trace_id,
        "timestamp": first.get("startTime"),
        "name": first.get("traceName") or root.get("name"),
        "input": root.get("input"),
        "output": root.get("output"),
        "metadata": root.get("metadata"),
        "tags": first.get("tags") or [],
        "userId": next((o["userId"] for o in obs if o.get("userId")), None),
        "sessionId": next((o["sessionId"] for o in obs if o.get("sessionId")), None),
        "release": first.get("release"),
        "environment": first.get("environment"),
        "observations": obs,
        "scores": [],
        "reconstructedFrom": "GET /api/public/v2/observations (no trace-level fields in v2; "
        "name/input/output/metadata taken from the root observation)",
    }


def fetch_scores(host, trace_id, public, secret):
    """Scores for one trace. Tries Scores API v3, then the older v2 route."""
    scores = []
    cursor = None
    try:
        for _ in range(MAX_PAGES):
            page = api_get(
                host,
                "/api/public/v3/scores",
                [
                    ("traceId", trace_id),
                    ("fields", "details,subject"),
                    ("limit", "100"),
                    ("cursor", cursor),
                ],
                public,
                secret,
            )
            for s in page.get("data") or []:
                s = dict(s)
                subject = s.get("subject") or {}
                s.setdefault("traceId", subject.get("traceId") or trace_id)
                if subject.get("observationId"):
                    s.setdefault("observationId", subject["observationId"])
                scores.append(s)
            cursor = (page.get("meta") or {}).get("cursor")
            if not cursor:
                break
        return scores
    except _NotFound:
        pass
    # Older self-hosted servers: page-based v2 scores endpoint (deprecated, still a GET).
    scores = []
    page_no = 1
    for _ in range(MAX_PAGES):
        try:
            page = api_get(
                host,
                "/api/public/v2/scores",
                [("traceId", trace_id), ("page", str(page_no)), ("limit", "100")],
                public,
                secret,
            )
        except _NotFound:
            return scores
        scores.extend(page.get("data") or [])
        total_pages = (page.get("meta") or {}).get("totalPages") or 1
        if page_no >= total_pages:
            break
        page_no += 1
    return scores


def fetch_legacy_trace(host, trace_id, public, secret):
    """GET /api/public/traces/{id}: only for self-hosted v3 servers without v2 endpoints."""
    quoted = urllib.parse.quote(trace_id, safe="")
    trace = api_get(host, "/api/public/traces/" + quoted, [], public, secret)
    observations = trace.get("observations")
    if not observations or not all(isinstance(o, dict) for o in observations):
        # Some responses list observation ids only. Fetch them via the list endpoint.
        observations = []
        page_no = 1
        for _ in range(MAX_PAGES):
            page = api_get(
                host,
                "/api/public/observations",
                [("traceId", trace_id), ("page", str(page_no)), ("limit", "100")],
                public,
                secret,
            )
            observations.extend(page.get("data") or [])
            if page_no >= ((page.get("meta") or {}).get("totalPages") or 1):
                break
            page_no += 1
        trace["observations"] = observations
    scores = trace.get("scores")
    if not scores or not all(isinstance(s, dict) for s in scores):
        trace["scores"] = fetch_scores(host, trace_id, public, secret)
    return trace


def not_found_error(trace_id, host):
    return FetchError(
        "Trace %r not found at %s. If it was just created, wait a few seconds and retry: "
        "ingestion is asynchronous (data from older SDKs can lag by up to 15 minutes). "
        "Also check that the keys belong to the project that holds the trace and that "
        "LANGFUSE_HOST is the right region." % (trace_id, host),
        EXIT_NOT_FOUND,
    )


def fetch_trace(trace_id, env):
    public, secret, host = get_credentials(env)
    try:
        rows = fetch_v2_observations(host, trace_id, public, secret)
    except _NotFound:
        rows = None  # no v2 route: self-hosted v3
    if rows:
        trace = build_trace_from_observations(trace_id, rows)
        trace["scores"] = fetch_scores(host, trace_id, public, secret)
        return trace
    try:
        return fetch_legacy_trace(host, trace_id, public, secret)
    except _NotFound:
        raise not_found_error(trace_id, host)


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Fetch a Langfuse trace with its observations and scores as JSON "
        "(read-only GET requests)."
    )
    p.add_argument("trace_id", help="Langfuse trace ID")
    p.add_argument("-o", "--output", help="write JSON to this file (default: stdout)")
    p.add_argument(
        "--env-file",
        help="load LANGFUSE_* variables from this .env file (values in the file override "
        "variables already set in the environment)",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    env = dict(os.environ)
    try:
        if args.env_file:
            try:
                env.update(load_env_file(args.env_file))
            except OSError as exc:
                raise FetchError("Cannot read --env-file: %s" % exc, EXIT_USAGE)
        trace = fetch_trace(args.trace_id, env)
        text = json.dumps(trace, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            try:
                with open(args.output, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise FetchError("Cannot write output file: %s" % exc, EXIT_USAGE)
            print(
                "Wrote %s (%d observations, %d scores)"
                % (
                    args.output,
                    len(trace.get("observations") or []),
                    len(trace.get("scores") or []),
                ),
                file=sys.stderr,
            )
        else:
            sys.stdout.write(text)
        return EXIT_OK
    except FetchError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
