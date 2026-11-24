"""Tests for fetch_trace.py against a local fake Langfuse server. No real network calls."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

import fetch_trace as ft

OBS_ROWS = [
    {"id": "o2", "traceId": "t1", "type": "TOOL", "name": "tool:search_books", "startTime": "2026-03-02T10:00:01Z",
     "parentObservationId": "o1", "input": "{\"query\": \"x\"}", "output": "[]", "traceName": "bookstore-support"},
    {"id": "o1", "traceId": "t1", "type": "SPAN", "name": "agent-run", "startTime": "2026-03-02T10:00:00Z",
     "parentObservationId": None, "isRootObservation": True, "input": "\"hi\"", "output": "plain answer",
     "metadata": "{\"scenario_id\": \"s1\"}", "traceName": "bookstore-support", "tags": ["demo"], "userId": "u1"},
]


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        Handler.seen.append((self.command, url.path, qs, self.headers.get("Authorization")))
        if url.path == "/api/public/v2/observations":
            if qs["traceId"][0] == "missing":
                return self.send(200, {"data": [], "meta": {}})
            if "cursor" not in qs:
                return self.send(200, {"data": OBS_ROWS[:1], "meta": {"cursor": "c1"}})
            return self.send(200, {"data": OBS_ROWS[1:], "meta": {}})
        if url.path == "/api/public/v3/scores":
            return self.send(200, {"data": [{"id": "s1", "name": "q", "value": 1, "subject": {"kind": "trace", "traceId": "t1"}}], "meta": {}})
        if url.path.startswith("/api/public/traces/"):
            return self.send(404, {"message": "not found"})
        if url.path == "/boom":
            return self.send(500, {})
        self.send(404, {})

    def send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture()
def server():
    Handler.seen = []
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % srv.server_port
    srv.shutdown()


def env_for(host):
    return {"LANGFUSE_PUBLIC_KEY": "pk-lf-fake", "LANGFUSE_SECRET_KEY": "sk-lf-fake", "LANGFUSE_HOST": host}


def test_missing_keys():
    with pytest.raises(ft.FetchError) as exc:
        ft.fetch_trace("t1", {})
    assert exc.value.code == ft.EXIT_MISSING_KEYS


def test_fetch_rebuilds_trace_from_v2_pages_and_adds_scores(server):
    trace = ft.fetch_trace("t1", env_for(server))
    assert trace["id"] == "t1"
    assert trace["name"] == "bookstore-support"
    assert trace["input"] == "hi"
    assert trace["output"] == "plain answer"
    assert trace["metadata"] == {"scenario_id": "s1"}
    assert [o["id"] for o in trace["observations"]] == ["o1", "o2"]
    assert trace["observations"][1]["input"] == {"query": "x"}
    assert trace["timestamp"] == "2026-03-02T10:00:00Z"
    assert trace["scores"][0]["traceId"] == "t1"
    assert all(method == "GET" for method, *_ in Handler.seen)
    assert Handler.seen[0][3].startswith("Basic ")


def test_not_found_has_ingestion_hint(server):
    with pytest.raises(ft.FetchError) as exc:
        ft.fetch_trace("missing", env_for(server))
    assert exc.value.code == ft.EXIT_NOT_FOUND
    assert "ingestion" in str(exc.value)


def test_other_http_error(server):
    with pytest.raises(ft.FetchError) as exc:
        ft.api_get(server, "/boom", [], "a", "b")
    assert exc.value.code == ft.EXIT_HTTP


def test_network_error():
    with pytest.raises(ft.FetchError) as exc:
        ft.fetch_trace("t1", env_for("http://127.0.0.1:9"))
    assert exc.value.code == ft.EXIT_NETWORK


def test_env_file_parser(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nLANGFUSE_PUBLIC_KEY=pk\nexport LANGFUSE_SECRET_KEY=\"sk\"\nLANGFUSE_HOST=https://x.example # note\n\n")
    assert ft.load_env_file(str(f)) == {
        "LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk", "LANGFUSE_HOST": "https://x.example"}
