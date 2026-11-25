"""Record complete HTTP exchanges on demand and replay exact repeats for CI."""

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qsl, urlsplit

from mitmproxy import http

LOG = logging.getLogger(__name__)
DAY = 24 * 60 * 60
BUFFER_SIZE = 4 * 1024 * 1024
MAX_BUFFERED_REQUEST = 32 * 1024 * 1024
MAX_OBJECT = 1024 * 1024 * 1024
CACHE_SIZE = 45_000_000_000
CLIENT_NETS = tuple(
    ipaddress.ip_network(value)
    for value in ("127.0.0.0/8", "192.168.0.0/23", "172.16.0.0/16", "100.64.0.0/10", "::1/128")
)
HOP_HEADERS = {
    b"connection", b"keep-alive", b"proxy-connection", b"proxy-authorization",
    b"proxy-authenticate", b"te", b"trailer", b"transfer-encoding", b"upgrade",
}
REQUEST_CACHE_IGNORED = {b"cache-control", b"pragma", b"content-length"}
SINGLE_RANGE = re.compile(r"bytes=([0-9]{0,19})-([0-9]{0,19})", re.I)
CACHE_AGE = re.compile(r'(?:^|,)\s*(?:s-maxage|max-age)\s*=\s*"?([0-9]{1,12})', re.I)
IDENTITY_HEADERS = {b"cookie", b"authorization"}
REPRESENTATION_HEADERS = {
    b"accept", b"accept-encoding", b"accept-language", b"available-dictionary", b"content-type",
    b"content-encoding", b"range", b"origin", b"if-match", b"if-none-match", b"if-modified-since",
    b"if-unmodified-since", b"if-range", b"access-control-request-method", b"access-control-request-headers",
}
BROWSER_HEADERS = {
    b"user-agent", b"referer", b"priority", b"sec-fetch-dest", b"sec-fetch-mode", b"sec-fetch-site",
    b"sec-fetch-user", b"sec-ch-ua", b"sec-ch-ua-mobile", b"sec-ch-ua-platform", b"sec-ch-ua-full-version-list",
    b"sec-ch-ua-arch", b"sec-ch-ua-bitness", b"sec-ch-ua-platform-version", b"sec-ch-ua-model",
}
SHARED_CACHE_IGNORED = REQUEST_CACHE_IGNORED | BROWSER_HEADERS | {b"cookie"}


def public_target(request: http.Request) -> bool:
    if request.port not in (80, 443):
        return False
    hostname = request.host.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal", ".home.arpa")):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        # The bridge firewall also filters the address actually dialed after DNS.
        return True
    return address.is_global and not address.is_multicast


def allowed(flow: http.HTTPFlow) -> bool:
    address = ipaddress.ip_address(flow.client_conn.peername[0])
    return any(address in network for network in CLIENT_NETS) and public_target(flow.request)


def header_fields(headers, ignored=frozenset()):
    connection_fields = {item.strip().lower().encode("latin-1") for item in headers.get("Connection", "").split(",")}
    return [
        (name.lower(), value)
        for name, value in headers.fields
        if name.lower() not in HOP_HEADERS | connection_fields | ignored
    ]


def fingerprint(request: http.Request, ignored=REQUEST_CACHE_IGNORED) -> str:
    # HTTP framing and client cache directives do not select a representation.
    # Keep all other headers, especially cookies, credentials, and conditionals.
    headers = sorted(
        header_fields(request.headers, ignored),
        key=lambda field: field[0],
    )
    key = hashlib.sha256()
    for field in (request.method.encode(), request.url.encode(), request.raw_content or b"", repr(headers).encode()):
        key.update(len(field).to_bytes(8, "big"))
        key.update(field)
    return key.hexdigest()


def public_asset_key(request: http.Request) -> str:
    return "shared:" + fingerprint(request, SHARED_CACHE_IGNORED)


def range_bounds(byte_range, size):
    start, end = byte_range.groups()
    if not start:
        suffix = int(end or "0")
        return (max(0, size - suffix), size - 1) if size and suffix else None
    first = int(start)
    last = min(int(end), size - 1) if end else size - 1
    return (first, last) if first <= last else None


def observe(request: http.Request) -> dict:
    """Log enough to count duplicate requests without logging URLs or headers."""
    url = urlsplit(request.url)
    body = request.raw_content or b""
    base = hashlib.sha256(request.method.encode() + b"\0" + request.url.encode() + b"\0")
    path = hashlib.sha256((url.scheme + "://" + url.netloc + url.path).encode()).hexdigest()[:16]
    request_url = base.hexdigest()[:16]
    base.update(body)
    payload = base.hexdigest()[:16]
    headers = sorted(header_fields(request.headers, REQUEST_CACHE_IGNORED), key=lambda field: field[0])
    base.update(repr([pair for pair in headers if pair[0] in IDENTITY_HEADERS]).encode())
    identity = base.hexdigest()[:16]
    base.update(repr([pair for pair in headers if pair[0] in REPRESENTATION_HEADERS]).encode())
    representation = base.hexdigest()[:16]
    base.update(repr([pair for pair in headers if pair[0].startswith(b"if-") or pair[0] not in BROWSER_HEADERS]).encode())
    return {
        "path": path, "url": request_url, "payload": payload, "identity": identity,
        "representation": representation, "without_browser": base.hexdigest()[:16],
        "cookie_present": any(k == b"cookie" for k, _ in headers),
        "no_store": any(item.strip().lower() == "no-store" for item in request.headers.get("Cache-Control", "").split(",")),
        "query": sorted({key for key, _ in parse_qsl(url.query, keep_blank_values=True) if re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,32}", key)})[:12],
    }


def freshness(response: http.Response) -> int:
    ages = CACHE_AGE.findall(response.headers.get("Cache-Control", ""))
    age = response.headers.get("Age", "")
    remaining = max((int(value) for value in ages), default=0) - (int(age) if age.isdecimal() else 0)
    expires = response.headers.get("Expires")
    if expires:
        try:
            when = parsedate_to_datetime(expires)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            remaining = max(remaining, int(when.timestamp() - time.time()))
        except (ValueError, TypeError, OverflowError):
            pass
    return max(DAY, remaining)


def shared_asset(response: http.Response) -> bool:
    cache_control = response.headers.get("Cache-Control", "")
    directives = {item.partition("=")[0].strip().lower() for item in cache_control.split(",")}
    vary = {item.strip().lower() for item in response.headers.get("Vary", "").split(",") if item.strip()}
    # Only a response that permits shared reuse can ignore browser metadata,
    # and any header named in Vary must remain part of its cache key.
    return (
        response.status_code == 200
        and ("public" in directives or any(int(age) >= DAY for age in CACHE_AGE.findall(cache_control)))
        and not directives & {"no-cache", "no-store", "private"}
        and "*" not in vary and not any(field.encode("latin-1") in SHARED_CACHE_IGNORED for field in vary)
        and "Set-Cookie" not in response.headers
    )


def result(flow: http.HTTPFlow, outcome: str) -> None:
    host, method = flow.metadata.get("destination", (flow.request.host, flow.request.method))
    status = flow.response.status_code if flow.response else 0
    summary = {
        "result": outcome, "host": host, "method": method, "status": status,
        "listener_port": flow.client_conn.sockname[1],
    }
    summary.update(flow.metadata.get("observation", {}))
    if flow.metadata.get("range_from_full"):
        summary["range_from_full"] = True
    if flow.metadata.get("shared_asset"):
        summary["shared_asset"] = True
    if flow.response is not None:
        summary["vary"] = sorted(field.lower().strip() for field in flow.response.headers.get("Vary", "").split(",") if field.strip())
        summary["public"] = bool(re.search(r"(?:^|,)\s*public(?:\s*,|\s*$)", flow.response.headers.get("Cache-Control", ""), re.I))
    LOG.info("proxy_cache %s", json.dumps(summary, separators=(",", ":")))


class ReplayCache:
    def running(self) -> None:
        self.replay_port = int(os.environ.get("PROXY_REPLAY_PORT", "0"))
        self.root = Path(os.environ["PROXY_CACHE_DIR"])
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.objects = self.root / "objects"
        self.objects.mkdir(mode=0o700, exist_ok=True)
        self.db = sqlite3.connect(self.root / "index.sqlite3", isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                key TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
                expires INTEGER NOT NULL, used INTEGER NOT NULL, response TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS entries_used ON entries (used)")
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS public_assets (
                key TEXT PRIMARY KEY REFERENCES entries(key) ON DELETE CASCADE,
                cookie_free_key TEXT NOT NULL
            )
        """)
        self.db.execute("CREATE INDEX IF NOT EXISTS public_assets_cookie_free ON public_assets (cookie_free_key)")
        self.pending = {}
        self.relays = {}
        self.latest_cleanup = 0
        self.total = self.db.execute("SELECT COALESCE(SUM(size), 0) FROM entries").fetchone()[0]
        valid = {name for (name,) in self.db.execute("SELECT name FROM entries")}
        cutoff = time.time() - 600
        for path in self.objects.iterdir():
            # mitmproxy can reload the addon while the previous instance is writing.
            if path.name not in valid:
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except FileNotFoundError:
                    pass
        self.evict(int(time.time()), 0)
        self.relay = ThreadingHTTPServer(("127.0.0.1", 0), self.make_relay_handler())
        Thread(target=self.relay.serve_forever, daemon=True).start()

    def make_relay_handler(self):
        cache = self

        class Relay(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, format, *args):
                pass

            def do_GET(self):
                entry = cache.relays.pop(self.path, None)
                if entry is None:
                    self.send_error(404)
                    return
                body, status, reason, fields, size = entry
                with body:
                    self.send_response_only(status, reason)
                    for name, value in fields:
                        if name != "content-length":
                            self.send_header(name, value)
                    self.send_header("Content-Length", str(size))
                    self.end_headers()
                    try:
                        remaining = size
                        while remaining:
                            chunk = body.read(min(remaining, 256 * 1024))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        return Relay

    def discard(self, key, name, size):
        self.db.execute("DELETE FROM entries WHERE key=?", (key,))
        (self.objects / name).unlink(missing_ok=True)
        self.total -= size

    def evict(self, now, incoming):
        if now - self.latest_cleanup >= 60:
            for row in self.db.execute("SELECT key, name, size FROM entries WHERE expires<=?", (now,)).fetchall():
                self.discard(*row)
            self.latest_cleanup = now
        while self.total + incoming > CACHE_SIZE:
            row = self.db.execute("SELECT key, name, size FROM entries ORDER BY used LIMIT 1").fetchone()
            if row is None:
                break
            self.discard(*row)

    def lookup(self, flow, key, byte_range=None):
        now = int(time.time())
        row = self.db.execute("""
            SELECT name, size, expires, used, response, cookie_free_key
            FROM entries LEFT JOIN public_assets USING (key) WHERE key=?
        """, (key,)).fetchone()
        if row is None:
            return False
        name, object_size, expires, used, metadata, stored_public_key = row
        if expires <= now:
            self.discard(key, name, object_size)
            return False
        status, reason, fields, trailers = json.loads(metadata)
        public_key = flow.metadata.get("public_asset_key")
        if status == 200 and not trailers and public_key and key == flow.metadata.get("cache_key") and stored_public_key != public_key:
            # Upgrade existing exact matches without fetching their bodies again.
            cached = http.Response.make(status)
            cached.headers = http.Headers([(k.encode("latin-1"), v.encode("latin-1")) for k, v in fields])
            if shared_asset(cached):
                self.db.execute("""
                    INSERT INTO public_assets VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET cookie_free_key=excluded.cookie_free_key
                """, (key, public_key))
        offset, size = 0, object_size
        if byte_range:
            # ZIP and WACZ readers fetch many small slices. A fresh complete
            # representation can answer single ranges without another origin request.
            headers = dict(fields)
            vary = {item.strip().lower() for name, value in fields if name == "vary" for item in value.split(",")}
            if (
                status != 200 or trailers or "content-range" in headers
                or headers.get("content-encoding", "identity").lower() != "identity"
                or headers.get("accept-ranges", "").lower() == "none" or vary & {"range", "*"}
            ):
                return False
            bounds = range_bounds(byte_range, size)
            if bounds is None:
                return False
            offset, end = bounds
            status, reason = 206, "Partial Content"
            fields = [(name, value) for name, value in fields
                      if name not in ("content-length", "content-md5", "content-digest")]
            fields.append(("content-range", f"bytes {offset}-{end}/{object_size}"))
            size = end - offset + 1
            fields.append(("content-length", str(size)))
        try:
            body = (self.objects / name).open("rb")
        except FileNotFoundError:
            self.discard(key, name, object_size)
            return False
        body.seek(offset)
        if now - used >= 60:
            self.db.execute("UPDATE entries SET used=? WHERE key=?", (now, key))
        flow.metadata["hit"] = True
        if byte_range:
            flow.metadata["range_from_full"] = True
        if size <= BUFFER_SIZE or trailers:
            with body:
                content = body.read(size)
            loaded = http.Response.make(status, content)
            loaded.reason = reason
            loaded.headers = http.Headers([(k.encode("latin-1"), v.encode("latin-1")) for k, v in fields])
            if trailers:
                loaded.trailers = http.Headers([(k.encode("latin-1"), v.encode("latin-1")) for k, v in trailers])
            flow.response = loaded
        else:
            # Synthetic mitmproxy responses require a bytes object. Serve large
            # cached bodies over a private loopback connection to stream them.
            endpoint = "/" + uuid.uuid4().hex
            self.relays[endpoint] = (body, status, reason, fields, size)
            flow.metadata["relay"] = endpoint
            flow.request = http.Request.make("GET", f"http://127.0.0.1:{self.relay.server_port}{endpoint}")
        return True

    def lookup_public_asset(self, flow, cookie_free_key):
        row = self.db.execute("""
            SELECT entries.key FROM public_assets JOIN entries USING (key)
            WHERE cookie_free_key=? AND expires>?
            ORDER BY expires DESC LIMIT 1
        """, (cookie_free_key, int(time.time()))).fetchone()
        if row and self.lookup(flow, row[0]):
            flow.metadata["shared_asset"] = True
            return True
        return False

    def replay_only(self, client) -> bool:
        return client.sockname[1] == self.replay_port

    def refuse_replay_miss(self, flow) -> None:
        flow.metadata["replay_miss"] = True
        flow.response = http.Response.make(502, b"No recorded response for this request.\n", {"x-ci-cache": "REPLAY-MISS"})

    def server_connect(self, data) -> None:
        # Guard the socket as well as the HTTP request, including raw CONNECT traffic.
        if self.replay_only(data.client) and data.server.address != ("127.0.0.1", self.relay.server_port):
            data.server.error = "Upstream connections are disabled on the replay-only port."

    def http_connect(self, flow: http.HTTPFlow) -> None:
        if not allowed(flow):
            flow.response = http.Response.make(403, b"Public web destinations only.\n")
            result(flow, "blocked")

    def requestheaders(self, flow: http.HTTPFlow) -> None:
        if not allowed(flow):
            flow.response = http.Response.make(403, b"Public web destinations only.\n")
        else:
            try:
                size = int(flow.request.headers.get("Content-Length", "0"))
            except ValueError:
                size = 0
            if size > MAX_BUFFERED_REQUEST:
                # The request hook needs a bounded body to match a POST in full.
                flow.request.stream = True

    async def request(self, flow: http.HTTPFlow) -> None:
        flow.metadata["destination"] = (flow.request.host, flow.request.method)
        if flow.response is not None:
            flow.metadata["blocked"] = True
            return
        if flow.request.raw_content is None or flow.request.headers.get("Upgrade"):
            if self.replay_only(flow.client_conn):
                self.refuse_replay_miss(flow)
            return
        key = fingerprint(flow.request)
        flow.metadata["cache_key"] = key
        flow.metadata["observation"] = {"key": key[:16], **observe(flow.request)}
        byte_range = SINGLE_RANGE.fullmatch(flow.request.headers.get("Range", "").strip())
        complete = (
            fingerprint(flow.request, REQUEST_CACHE_IGNORED | {b"range"})
            if byte_range and flow.request.method == "GET"
            and not any(name.lower().startswith("if-") for name in flow.request.headers)
            else None
        )
        headers = flow.request.headers
        if (
            flow.request.method == "GET" and "Authorization" not in headers
            and "Range" not in headers and not any(name.lower().startswith("if-") for name in headers)
        ):
            flow.metadata["public_asset_key"] = public_asset_key(flow.request)
        try:
            while not self.lookup(flow, key):
                if complete and self.lookup(flow, complete, byte_range):
                    return
                public_key = flow.metadata.get("public_asset_key")
                if public_key and self.lookup_public_asset(flow, public_key):
                    return
                if self.replay_only(flow.client_conn):
                    self.refuse_replay_miss(flow)
                    return
                other = self.pending.get(key)
                if other is None:
                    future = asyncio.get_running_loop().create_future()
                    self.pending[key] = future
                    flow.metadata["leader"] = True
                    return
                await asyncio.wait_for(asyncio.shield(other), timeout=120)
        except (OSError, ValueError, sqlite3.Error, TimeoutError):
            LOG.warning("Cache lookup unavailable")
            flow.metadata.pop("cache_key", None)
            if self.replay_only(flow.client_conn):
                self.refuse_replay_miss(flow)

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        response = flow.response
        if flow.metadata.get("relay"):
            response.stream = True
            response.headers["x-ci-cache"] = "HIT"
            return
        if response.status_code == 101 or flow.request.method == "HEAD":
            return
        size = response.headers.get("Content-Length")
        if size and size.isdecimal() and int(size) <= BUFFER_SIZE:
            return
        if not flow.metadata.get("leader"):
            response.stream = True
            return
        if size and size.isdecimal() and int(size) > MAX_OBJECT:
            response.stream = True
            return
        try:
            path = self.objects / (".tmp-" + uuid.uuid4().hex)
            stream = path.open("xb")
        except OSError:
            response.stream = True
            return
        flow.metadata["writer"] = (path, stream)

        def write_chunk(chunk):
            if stream.closed:
                return chunk
            try:
                if stream.tell() + len(chunk) > MAX_OBJECT:
                    stream.close()
                    path.unlink(missing_ok=True)
                else:
                    stream.write(chunk)
            except OSError:
                stream.close()
                path.unlink(missing_ok=True)
            return chunk

        response.stream = write_chunk
        response.headers["x-ci-cache"] = "MISS"

    def store(self, flow):
        response = flow.response
        writer = flow.metadata.get("writer")
        if response.status_code < 200:
            return False
        if writer:
            path, stream = writer
            if stream.closed:
                return False
            size = stream.tell()
            stream.close()
        elif response.raw_content is not None:
            size = len(response.raw_content)
            if size > MAX_OBJECT:
                return False
            path = self.objects / (".tmp-" + uuid.uuid4().hex)
            flow.metadata["buffered_path"] = path
            path.write_bytes(response.raw_content)
        else:
            return False
        now = int(time.time())
        key = flow.metadata["cache_key"]
        previous = self.db.execute("SELECT key, name, size FROM entries WHERE key=?", (key,)).fetchone()
        if previous is not None:
            self.discard(*previous)
        self.evict(now, size)
        if self.total + size > CACHE_SIZE:
            return False

        def encode(fields):
            return [(name.decode("latin-1"), value.decode("latin-1")) for name, value in fields]

        fields = encode(header_fields(response.headers, {b"x-ci-cache"}))
        trailers = encode(header_fields(response.trailers)) if response.trailers else []
        if size > BUFFER_SIZE and trailers:
            return False
        metadata = json.dumps((response.status_code, response.reason, fields, trailers))
        public_key = flow.metadata.get("public_asset_key")
        public = public_key and not trailers and shared_asset(response)
        name = uuid.uuid4().hex
        object_path = self.objects / name
        path.rename(object_path)
        try:
            if public:
                self.db.execute("BEGIN")
            self.db.execute("INSERT INTO entries VALUES (?,?,?,?,?,?)", (key, name, size, now + freshness(response), now, metadata))
            if public:
                self.db.execute("INSERT INTO public_assets VALUES (?,?)", (key, public_key))
                self.db.execute("COMMIT")
        except sqlite3.Error:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            object_path.unlink(missing_ok=True)
            raise
        self.total += size
        return True

    def finish(self, flow):
        writer = flow.metadata.pop("writer", None)
        if writer:
            path, stream = writer
            stream.close()
            path.unlink(missing_ok=True)
        path = flow.metadata.pop("buffered_path", None)
        if path:
            path.unlink(missing_ok=True)
        relay = self.relays.pop(flow.metadata.get("relay"), None)
        if relay:
            relay[0].close()
        if flow.metadata.pop("leader", False):
            future = self.pending.pop(flow.metadata["cache_key"], None)
            if future and not future.done():
                future.set_result(None)

    def response(self, flow: http.HTTPFlow) -> None:
        try:
            if flow.metadata.get("blocked"):
                result(flow, "blocked")
            elif flow.metadata.get("replay_miss"):
                result(flow, "replay_miss")
            elif flow.metadata.get("hit"):
                flow.response.headers["x-ci-cache"] = "HIT"
                result(flow, "hit")
            else:
                stored = flow.metadata.get("leader") and self.store(flow)
                flow.response.headers["x-ci-cache"] = "MISS" if stored else "BYPASS"
                result(flow, "miss" if stored else "bypass")
        except (OSError, ValueError, sqlite3.Error):
            result(flow, "store_error")
        finally:
            self.finish(flow)

    def error(self, flow: http.HTTPFlow) -> None:
        result(flow, "replay_error" if flow.metadata.get("hit") else "upstream_error")
        self.finish(flow)


addons = [ReplayCache()]
