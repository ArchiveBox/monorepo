#!/usr/bin/env -S uv run --active --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "pydantic-settings",
#   "jambo",
#   "rich-click",
#   "abx-plugins",
# ]
# ///
#
# MOCKUP — IMAP mailbox fan-out plugin.
#
# Takes an imap:// or imaps:// URL pointing at a mailbox and fans out one
# child Snapshot per message. For each message the plugin saves both:
#   - <UIDVALIDITY>.<UID>.eml   raw RFC822 (provenance, future re-parse)
#   - <UIDVALIDITY>.<UID>.html  rendered body + headers (the snapshot URL)
# The child Snapshot URL points at the .html so existing downstream
# extractors (chrome/singlefile/screenshot/title/parse_html_urls) have
# something they can actually render. The .eml stays as a sidecar.
#
# Inline URLs found in message bodies are also emitted as http(s) child
# Snapshots, so the normal extractors pick them up at depth+1.
#
# ─── URL shape ─────────────────────────────────────────────────────────
#
#   imap[s]://[user@]host[:port]/MAILBOX[?query=...]
#
#   MAILBOX  required; "INBOX", "[Gmail]/All Mail", etc. (URL-encoded)
#   query params (all optional, RFC-5092-ish):
#     since=YYYY-MM-DD      only messages on/after this date
#     before=YYYY-MM-DD     only messages before this date
#     from=alice@x.com      RFC822 FROM filter
#     subject=foo           SUBJECT substring
#     limit=N               max messages to fetch (default 500)
#     unseen=1              only unread
#     uid_min=NNNN          only UIDs >= NNNN (resume marker)
#
#   Examples:
#     imaps://me@imap.fastmail.com/INBOX?since=2026-01-01&limit=200
#     imaps://me@imap.gmail.com/%5BGmail%5D%2FAll%20Mail?from=stripe.com
#
# ─── Auth ──────────────────────────────────────────────────────────────
#
# Password is NOT in the URL (it would leak into logs/db). Resolution
# order at fetch time:
#   1. env var ARCHIVEBOX_IMAP_PASSWORD_<HOST_UPPER>  (e.g. _IMAP_GMAIL_COM)
#   2. env var ARCHIVEBOX_IMAP_PASSWORD               (single-account fallback)
#   3. macOS Keychain via `security find-internet-password` (TODO)
#   4. fail with status=failed, stderr asking user to set the env var
#
# OAuth/XOAUTH2 (Gmail, Office 365) is out of scope for the mockup but
# would slot in here as a 5th lookup that calls a refresh-token helper.
#
# ─── Fan-out model ─────────────────────────────────────────────────────
#
# This plugin runs *on* a Snapshot whose URL is the imap:// mailbox URL.
# It produces:
#   - SNAP_DIR/parse_imap_urls/messages/<UIDVALIDITY>.<UID>.eml      raw RFC822
#   - SNAP_DIR/parse_imap_urls/seen_uids.jsonl                       resume log
#   - SNAP_DIR/parse_imap_urls/urls.jsonl                            child manifest
#   - one Snapshot record per .eml (URL = file:///abs/path/<...>.eml)
#   - one Snapshot record per inline http(s) URL found in bodies
#   - Tag records: mailbox name, each sender domain
#   - one ArchiveResult record summarising the run
#
# Why render to .html during fan-out instead of emitting the .eml directly:
# Most downstream plugins (chrome/singlefile/screenshot/title/parse_html_urls)
# are HTML-shaped — they expect chrome to navigate to a renderable doc.
# Pointing them at a .eml just produces "Return-Path:..." text dumps. By
# rendering an HTML view here, the IMAP scheme stays contained to this
# plugin and no downstream plugin needs to learn what IMAP (or .eml) is.
# The raw .eml is preserved alongside so future re-parses or attachment
# extraction don't lose fidelity.
#
# ─── Caveats / what's stubbed ──────────────────────────────────────────
#
# - For archivebox proper (not abx-dl), archivebox/misc/util.py:validate_url
#   currently rejects non-http(s) schemes. The mailbox URL has to either
#   pass that gate (allowlist imap/imaps) or be intercepted as a pure
#   seed that never becomes a Snapshot. See ../README for design context.
# - No IMAP IDLE / incremental sync — re-running the plugin diffs against
#   seen_uids.jsonl, but it always re-issues SEARCH.
# - HTML body URL extraction is a regex; a real implementation should use
#   the shared `parse_html_urls` helpers via an embedded subprocess so
#   relative URLs resolve against the message's base href.
# - Attachments are left inside the .eml. A follow-up could explode them
#   to file:// children too.

import email
import email.utils
import html as html_lib
import imaplib
import json
import os
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from abx_plugins.plugins.base.url_cleaning import sanitize_extracted_url
from abx_plugins.plugins.base.utils import (
    emit_archive_result_record,
    emit_snapshot_record,
    emit_tag_record,
    get_extra_context,
    load_config,
    write_text_atomic,
)

import rich_click as click

PLUGIN_NAME = "parse_imap_urls"
PLUGIN_DIR = Path(__file__).resolve().parent.name
CONFIG = load_config()
SNAP_DIR = Path(CONFIG.SNAP_DIR or ".").resolve()
OUTPUT_DIR = SNAP_DIR / PLUGIN_DIR
MESSAGES_DIR = OUTPUT_DIR / "messages"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(OUTPUT_DIR)

URLS_FILE = Path("urls.jsonl")
SEEN_FILE = Path("seen_uids.jsonl")
DEFAULT_LIMIT = 500
NORESULTS_OUTPUT = "0 messages fetched"

URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'\]\}]+", re.IGNORECASE)


# ───────────────────────────── URL parsing ─────────────────────────────


def parse_imap_url(url: str) -> dict:
    """Crack imap[s]://user@host:port/MAILBOX?... into a dict."""
    parsed = urlparse(url)
    if parsed.scheme not in ("imap", "imaps"):
        raise ValueError(f"expected imap:// or imaps://, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise ValueError("IMAP URL must include a hostname")

    mailbox = unquote(parsed.path.lstrip("/")) or "INBOX"
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port or (993 if parsed.scheme == "imaps" else 143),
        "user": unquote(parsed.username) if parsed.username else None,
        "mailbox": mailbox,
        "since": query.get("since"),
        "before": query.get("before"),
        "from_": query.get("from"),
        "subject": query.get("subject"),
        "unseen": query.get("unseen") == "1",
        "uid_min": int(query["uid_min"]) if query.get("uid_min") else None,
        "limit": int(query.get("limit", DEFAULT_LIMIT)),
        "tls": parsed.scheme == "imaps",
    }


# ───────────────────────────── auth lookup ─────────────────────────────


def resolve_password(host: str) -> str:
    host_key = host.upper().replace(".", "_").replace("-", "_")
    candidates = [
        f"ARCHIVEBOX_IMAP_PASSWORD_{host_key}",
        "ARCHIVEBOX_IMAP_PASSWORD",
    ]
    for env_var in candidates:
        value = os.environ.get(env_var)
        if value:
            return value
    # TODO: macOS Keychain via `security find-internet-password -s host -a user -w`
    raise RuntimeError(
        f"no IMAP password found; set one of: {', '.join(candidates)}",
    )


# ─────────────────────────── IMAP interaction ──────────────────────────


def build_search_criteria(meta: dict) -> list[str]:
    """Translate parsed query params into an IMAP SEARCH expression."""
    criteria: list[str] = []
    if meta["unseen"]:
        criteria.append("UNSEEN")
    if meta["since"]:
        dt = datetime.fromisoformat(meta["since"])
        criteria += ["SINCE", dt.strftime("%d-%b-%Y")]
    if meta["before"]:
        dt = datetime.fromisoformat(meta["before"])
        criteria += ["BEFORE", dt.strftime("%d-%b-%Y")]
    if meta["from_"]:
        criteria += ["FROM", meta["from_"]]
    if meta["subject"]:
        criteria += ["SUBJECT", meta["subject"]]
    if meta["uid_min"]:
        criteria += ["UID", f"{meta['uid_min']}:*"]
    return criteria or ["ALL"]


def connect_imap(meta: dict, password: str) -> imaplib.IMAP4:
    """Open a TLS-or-plaintext IMAP connection and LOGIN."""
    timeout = float(getattr(CONFIG, "TIMEOUT", 60))
    if meta["tls"]:
        ctx = ssl.create_default_context()
        client = imaplib.IMAP4_SSL(
            host=meta["host"], port=meta["port"], ssl_context=ctx, timeout=timeout,
        )
    else:
        client = imaplib.IMAP4(host=meta["host"], port=meta["port"], timeout=timeout)
    client.login(meta["user"], password)
    return client


def load_seen_uids() -> set[tuple[str, str]]:
    if not SEEN_FILE.exists():
        return set()
    seen: set[tuple[str, str]] = set()
    for line in SEEN_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        seen.add((str(rec["uidvalidity"]), str(rec["uid"])))
    return seen


def append_seen(uidvalidity: str, uid: str) -> None:
    with SEEN_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"uidvalidity": uidvalidity, "uid": uid}) + "\n")


# ───────────────────────────── extraction ──────────────────────────────


def render_eml_to_html(msg: EmailMessage) -> str:
    """Render an email to a self-contained HTML doc for the archival pipeline.

    Picks the richest body part available (text/html > text/plain), wraps it
    in a minimal HTML shell with the headers up top so chrome/singlefile/
    screenshot/title produce useful artifacts. Inline images stay as cid:
    references — a follow-up pass should base64-inline them so chrome
    renders them without --allow-file-access-from-files quirks.
    """
    headers = {h: msg.get(h, "") for h in ("From", "To", "Cc", "Date", "Subject")}

    html_part = None
    text_part = None
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "text/html" and html_part is None:
            html_part = part
        elif ctype == "text/plain" and text_part is None:
            text_part = part

    body_html = ""
    if html_part is not None:
        try:
            content = html_part.get_content()
            if isinstance(content, str):
                body_html = content
        except (LookupError, KeyError):
            pass
    if not body_html and text_part is not None:
        try:
            content = text_part.get_content()
            if isinstance(content, str):
                body_html = f"<pre>{html_lib.escape(content)}</pre>"
        except (LookupError, KeyError):
            pass
    if not body_html:
        body_html = "<p><em>(no renderable body)</em></p>"

    header_rows = "".join(
        f"<tr><th align='left'>{html_lib.escape(k)}</th>"
        f"<td>{html_lib.escape(v)}</td></tr>"
        for k, v in headers.items() if v
    )
    title = html_lib.escape(headers.get("Subject") or "(no subject)")
    return (
        "<!doctype html>\n<html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>"
        f"<table>{header_rows}</table><hr>{body_html}"
        "</body></html>"
    )


def extract_body_urls(msg: EmailMessage) -> list[str]:
    """Pull http(s) URLs out of text/plain and text/html parts."""
    found: list[str] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            body = part.get_content()
        except (LookupError, KeyError):
            continue
        if not isinstance(body, str):
            continue
        for match in URL_IN_TEXT.finditer(body):
            cleaned = sanitize_extracted_url(match.group(0))
            if cleaned:
                found.append(cleaned)
    # dedupe, preserve order
    seen, ordered = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def sender_domain(msg: EmailMessage) -> str | None:
    from_ = msg.get("From") or ""
    match = re.search(r"@([\w.-]+)", from_)
    return match.group(1).lower() if match else None


def message_title(msg: EmailMessage) -> str:
    subject = (msg.get("Subject") or "").strip()
    sender = (msg.get("From") or "").strip()
    if subject and sender:
        return f"{subject} — {sender}"
    return subject or sender or "(no subject)"


def message_sent_at(msg: EmailMessage) -> str | None:
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ─────────────────────────── plugin driver ─────────────────────────────


def fetch_and_persist(client: imaplib.IMAP4, meta: dict, depth: int) -> tuple[list[dict], set[str]]:
    """SEARCH the mailbox, FETCH new UIDs, write .eml files, return child records."""
    typ, data = client.select(meta["mailbox"], readonly=True)
    if typ != "OK":
        raise RuntimeError(f"SELECT {meta['mailbox']!r} failed: {data!r}")

    typ, uidv_data = client.response("UIDVALIDITY")
    uidvalidity = (uidv_data[0] or b"0").decode() if uidv_data else "0"

    typ, search_data = client.uid("SEARCH", *build_search_criteria(meta))
    if typ != "OK":
        raise RuntimeError(f"SEARCH failed: {search_data!r}")
    uid_list = (search_data[0] or b"").decode().split()
    uid_list = uid_list[-meta["limit"]:] if len(uid_list) > meta["limit"] else uid_list

    seen = load_seen_uids()
    child_records: list[dict] = []
    sender_domains: set[str] = set()

    for uid in uid_list:
        if (uidvalidity, uid) in seen:
            continue
        typ, fetch_data = client.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not fetch_data or not isinstance(fetch_data[0], tuple):
            click.echo(f"WARN: FETCH UID {uid} failed, skipping", err=True)
            continue
        raw_rfc822: bytes = fetch_data[0][1]
        msg: EmailMessage = email.message_from_bytes(raw_rfc822, policy=policy.default)  # type: ignore[assignment]

        stem = f"{uidvalidity}.{uid}"
        eml_path = MESSAGES_DIR / f"{stem}.eml"
        html_path = MESSAGES_DIR / f"{stem}.html"
        eml_path.write_bytes(raw_rfc822)
        # Render to HTML so chrome/singlefile/screenshot/title/parse_html_urls
        # actually have something they can process. The .eml stays as a
        # sidecar artifact in the same dir.
        html_path.write_text(render_eml_to_html(msg), encoding="utf-8")
        append_seen(uidvalidity, uid)

        child_records.append({
            "url": html_path.as_uri(),
            "plugin": PLUGIN_NAME,
            "depth": depth + 1,
            "title": message_title(msg),
            "bookmarked_at": message_sent_at(msg),
            "tags": ",".join(filter(None, [meta["mailbox"], sender_domain(msg)])),
        })

        domain = sender_domain(msg)
        if domain:
            sender_domains.add(domain)

        for url in extract_body_urls(msg):
            child_records.append({
                "url": url,
                "plugin": PLUGIN_NAME,
                "depth": depth + 1,
                "tags": f"imap-body,{meta['mailbox']}",
            })

    return child_records, sender_domains


def emit_result(status: str, output_str: str) -> None:
    emit_archive_result_record(status, output_str)
    if output_str:
        click.echo(output_str, err=True)


@click.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option("--url", required=True, help="imap:// or imaps:// mailbox URL")
@click.option("--depth", type=int, default=0, help="Current depth level")
def main(url: str, depth: int = 0):
    """Fan an IMAP mailbox out into one child Snapshot per message."""
    extra_context = get_extra_context()
    if "snapshot_depth" in extra_context:
        depth = int(extra_context["snapshot_depth"])

    try:
        meta = parse_imap_url(url)
    except ValueError as exc:
        emit_result("noresults", f"not an IMAP URL: {exc}")
        sys.exit(0)

    if not meta["user"]:
        emit_result("failed", "IMAP URL missing username (use imap://user@host/...)")
        sys.exit(1)

    try:
        password = resolve_password(meta["host"])
    except RuntimeError as exc:
        emit_result("failed", str(exc))
        sys.exit(1)

    click.echo(f"connecting to {meta['scheme']}://{meta['host']}:{meta['port']}", err=True)
    try:
        client = connect_imap(meta, password)
    except (imaplib.IMAP4.error, ssl.SSLError, socket.gaierror, OSError) as exc:
        emit_result("failed", f"IMAP connect/login failed: {exc}")
        sys.exit(1)

    try:
        child_records, sender_domains = fetch_and_persist(client, meta, depth)
    except (imaplib.IMAP4.error, RuntimeError) as exc:
        emit_result("failed", f"IMAP fetch failed: {exc}")
        sys.exit(1)
    finally:
        try:
            client.logout()
        except imaplib.IMAP4.error:
            pass

    for tag in sorted({meta["mailbox"], *sender_domains}):
        if tag:
            emit_tag_record(tag)

    for record in child_records:
        emit_snapshot_record(record)

    if child_records:
        write_text_atomic(
            URLS_FILE,
            "\n".join(json.dumps(r) for r in child_records) + "\n",
        )
        msg_count = sum(1 for r in child_records if r["url"].endswith(".html"))
        url_count = len(child_records) - msg_count
        output_str = f"{msg_count} messages rendered, {url_count} inline URLs queued"
        emit_result("succeeded", output_str)
    else:
        URLS_FILE.unlink(missing_ok=True)
        emit_result("noresults", NORESULTS_OUTPUT)

    sys.exit(0)


if __name__ == "__main__":
    main()
