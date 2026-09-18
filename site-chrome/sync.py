#!/usr/bin/env -S uv run --no-project python
"""Render shared, crawlable ArchiveBox navigation into independently built sites."""

import argparse
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
FAMILY = WORKSPACE.parent
GROUPS = json.loads((HERE / "links.json").read_text())
LOGO = '<svg class="abx-logo" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="10" fill="#9b2854"/><path d="M10 14h20v17H10z" fill="#fff4ed"/><path d="M8 9h24v6H8z" fill="#fff4ed"/><path d="M16 19h8v3h-8z" fill="#9b2854"/><path d="M12 31V17" stroke="#9b2854" stroke-width="2"/></svg>'
GITHUB = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .75a11.25 11.25 0 0 0-3.56 21.92c.56.1.77-.24.77-.54v-2.1c-3.14.68-3.8-1.33-3.8-1.33-.51-1.3-1.25-1.65-1.25-1.65-1.02-.7.08-.69.08-.69 1.13.08 1.73 1.16 1.73 1.16 1 1.72 2.63 1.22 3.27.93.1-.73.39-1.22.71-1.5-2.5-.28-5.13-1.25-5.13-5.56 0-1.23.44-2.23 1.16-3.02-.12-.28-.5-1.43.11-2.98 0 0 .95-.3 3.1 1.15a10.8 10.8 0 0 1 5.64 0c2.15-1.46 3.1-1.15 3.1-1.15.62 1.55.23 2.7.12 2.98.72.79 1.16 1.8 1.16 3.02 0 4.32-2.64 5.27-5.15 5.55.4.35.76 1.03.76 2.08v3.11c0 .3.2.65.77.54A11.25 11.25 0 0 0 12 .75Z"/></svg>'
SCRIPT = """<script>
(() => {
  const menu = document.querySelector('.abx-apps');
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  document.addEventListener('click', event => { if (menu?.open && !menu.contains(event.target)) menu.open = false; });
  function revealAnchor() {
    let target;
    try { target = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (!target) return;
    let details = target.closest('details');
    let opened = false;
    while (details) { if (!details.open) { details.open = true; opened = true; } details = details.parentElement.closest('details'); }
    if (opened) requestAnimationFrame(() => target.scrollIntoView());
  }
  addEventListener('hashchange', revealAnchor);
  revealAnchor();
})();
</script>"""


def link(label, url, cls=""):
    return f'<a{f" class={chr(34)}{cls}{chr(34)}" if cls else ""} href="{html.escape(url, quote=False)}">{html.escape(label)}</a>'


APPS = [
    ("ArchiveBox Server", "https://archivebox.io/"),
    ("ArchiveBox for macOS & iOS", "https://archivebox.github.io/ios-archivebox/"),
    ("ArchiveBox Browser Extension", "https://archivebox.github.io/archivebox-browser-extension/"),
    ("ArchiveBox Plugin Library", "https://archivebox.github.io/abx-plugins/"),
    ("One-shot abx-dl CLI", "https://archivebox.github.io/abx-dl/"),
    ("More on Github...", "https://github.com/ArchiveBox"),
]


def header(name, home, repo, nav, cta):
    apps = "".join(link(label, url) for label, url in APPS).replace("One-shot abx-dl CLI", "<span>One-shot <code>abx-dl</code> CLI</span>")
    return f'''<header class="abx-header">
  <a class="abx-brand" href="{home}">{LOGO}<span>ArchiveBox</span><span class="abx-subsite">{html.escape(name)}</span></a>
  <nav class="abx-nav" aria-label="Main navigation">
    <details class="abx-apps"><summary>Apps</summary><div class="abx-app-links">{apps}</div></details>
    {"".join(link(*item) for item in nav)}
    {link("GitHub ↗", "https://github.com/ArchiveBox/" + repo)}
    {link(*cta, cls="abx-cta")}
  </nav>
</header>'''


def footer(name, local=""):
    columns = []
    for group in GROUPS:
        rows = []
        for label, url, *repo in group["links"]:
            source = ""
            if repo:
                source = f'<a class="abx-source" href="https://github.com/ArchiveBox/{repo[0]}" aria-label="{html.escape(label)} source on GitHub" title="View source on GitHub">{GITHUB}</a>'
            rows.append(f"<li>{link(label, url)}{source}</li>")
        columns.append(
            f'<section class="abx-footer-column"><h2>{html.escape(group["title"])}</h2><ul>{"".join(rows)}</ul></section>'
        )
    local_html = ""
    if local:
        if name in ["Plugins & Extractors", "Package Manager"]:
            # Retain every original resource description, link, and anchor.
            local_html = f'<details class="abx-footer-local"><summary>More about {html.escape(name)}</summary><div>{local}</div></details>'
        else:
            local_html = f'<div class="abx-footer-local">{local}</div>'
    return f"""<footer class="abx-footer" aria-label="ArchiveBox ecosystem">
  <div class="abx-footer-intro"><div><a class="abx-brand" href="https://archivebox.io/">{LOGO}<span>ArchiveBox</span></a><p class="abx-tagline">Open-source tools for keeping a lasting copy of the web.<br>Your data. Your devices. Your archive.</p></div><p class="abx-footer-motto">A home for the web<br>you want to keep.</p></div>
  <div class="abx-footer-grid">{"".join(columns)}</div>
  {local_html}
  <div class="abx-footer-bottom"><p>Built in the open. Supported by our community.</p><p><a href="https://github.com/ArchiveBox">GitHub organization</a> · <a href="https://github.com/ArchiveBox/ArchiveBox/wiki/Security-Overview">Security &amp; privacy</a> · <a href="https://archivebox.io">ArchiveBox.io ↗</a></p></div>
</footer>
{SCRIPT}"""


SITES = [
    {
        "key": "tlsnotary",
        "root": WORKSPACE / "abx-plugins",
        "template": "abx_plugins/plugins/tlsnotary/server/web/index.html",
        "css": "abx_plugins/plugins/tlsnotary/server/web/style.css",
        "append_css": True,
        "external_script": "abx_plugins/plugins/tlsnotary/server/web/site-chrome.mjs",
        "name": "TLSNotary",
        "home": "https://tlsnotary.zervice.io/",
        "repo": "abx-plugins",
        "nav": [("How it works", "#guide-title"), ("Self-host", "https://github.com/ArchiveBox/abx-plugins/tree/main/abx_plugins/plugins/tlsnotary/server")],
        "cta": ("Verify a capture", "#status"),
    },
    {
        "key": "archivebox",
        "root": WORKSPACE / "archivebox",
        "template": "publicsite/index.html",
        "css": "publicsite/site-chrome.css",
        "name": "Web Archive",
        "home": "https://archivebox.io/",
        "repo": "ArchiveBox",
        "nav": [
            ("Use cases", "#use-cases"),
            ("Configuration", "#configuration"),
            ("Layout & security", "#layout-security"),
            ("Docs", "https://github.com/ArchiveBox/ArchiveBox/wiki"),
        ],
        "cta": ("Get started", "#install"),
    },
    {
        "key": "plugins",
        "root": WORKSPACE / "abx-plugins",
        "template": "docs/index.html.j2",
        "css": "docs/css/site-chrome.css",
        "name": "Plugins & Extractors",
        "home": "https://archivebox.github.io/abx-plugins/",
        "repo": "abx-plugins",
        "nav": [
            ("Catalog", "#browser"),
            ("Context", "#context"),
            ("Resources", "#resources"),
        ],
        "cta": ("Find a plugin", "#browser"),
    },
    {
        "key": "pkg",
        "root": WORKSPACE / "abxpkg",
        "template": "docs/index.html.j2",
        "css": "docs/css/site-chrome.css",
        "name": "Package Manager",
        "home": "https://abxpkg.archivebox.io/",
        "repo": "abxpkg",
        "nav": [
            ("Providers", "#providers"),
            ("Global Env", "#global-env"),
            ("Resources", "#resources"),
        ],
        "cta": ("Install", "https://pypi.org/project/abxpkg/"),
    },
    {
        "key": "dl",
        "root": WORKSPACE / "abx-dl",
        "template": "website/index.html",
        "css": "website/style.css",
        "append_css": True,
        "name": "Downloader CLI",
        "home": "https://archivebox.github.io/abx-dl/",
        "repo": "abx-dl",
        "nav": [("Documentation", "#readme")],
        "cta": ("Install", "https://archivebox.github.io/abx-dl/#install"),
    },
    {
        "key": "ios",
        "root": FAMILY / "ios-archivebox",
        "template": "docs/site/_layouts/default.html",
        "css": "docs/site/assets/style.scss",
        "append_css": True,
        "name": "Apple Apps",
        "home": "{{ '/' | relative_url }}",
        "repo": "ios-archivebox",
        "nav": [
            ("Screenshots", "{{ '/screenshots/' | relative_url }}"),
            ("Server for Mac", "{{ '/' | relative_url }}#your-server-your-choice"),
        ],
        "cta": ("Get the apps", "{{ '/' | relative_url }}#get-started"),
    },
    {
        "key": "evals",
        "root": WORKSPACE,
        "template": "evals/site/index.html",
        "css": "evals/site/styles.css",
        "append_css": True,
        "name": "CI Observatory",
        "home": "https://archivebox.github.io/monorepo/",
        "repo": "monorepo",
        "nav": [("Collector runs", "https://github.com/ArchiveBox/monorepo/actions")],
        "cta": ("Explore results", "#runsTitle"),
    },
    {
        "key": "digest",
        "root": FAMILY / "DigestBox",
        "template": "index.html",
        "css": "site-chrome.css",
        "name": "DigestBox",
        "home": "https://archivebox.github.io/DigestBox/",
        "repo": "DigestBox",
        "nav": [("About", "https://github.com/ArchiveBox/DigestBox#readme")],
        "cta": ("Share feedback", "https://github.com/ArchiveBox/DigestBox/issues/1"),
    },
    {
        "key": "community",
        "root": FAMILY / "community",
        "template": "_layouts/default.html",
        "css": "assets/site-chrome.css",
        "legacy": True,
        "name": "Community Directory",
        "home": "https://community.archivebox.io/",
        "repo": "community",
        "nav": [("Documentation", "https://github.com/ArchiveBox/ArchiveBox/wiki")],
        "cta": ("Join the chat", "https://zulip.archivebox.io/"),
    },
    {
        "key": "karma",
        "root": FAMILY / "good-karma-kit",
        "template": "_layouts/default.html",
        "css": "assets/site-chrome.css",
        "legacy": True,
        "name": "Good Karma Kit",
        "home": "https://archivebox.github.io/good-karma-kit/",
        "repo": "good-karma-kit",
        "nav": [("Projects", "#content")],
        "cta": ("Get the kit", "https://github.com/ArchiveBox/good-karma-kit#readme"),
    },
    {
        "key": "debian",
        "root": WORKSPACE / "debian-archivebox",
        "template": "website/index.html",
        "css": "website/site-chrome.css",
        "name": "Debian & Ubuntu",
        "home": "https://archivebox.github.io/debian-archivebox/",
        "repo": "debian-archivebox",
        "nav": [
            ("Packages", "./dists/dev/main/binary-amd64/Packages"),
            ("Documentation", "https://github.com/ArchiveBox/debian-archivebox#readme"),
        ],
        "cta": ("Install", "#install"),
    },
]


def block(kind, value):
    return f"<!-- BEGIN ARCHIVEBOX {kind} — generated by monorepo/site-chrome/sync.py -->\n{value}\n<!-- END ARCHIVEBOX {kind} -->"


def replace_block(text, kind, value, initial_pattern):
    pattern = rf"<!-- BEGIN ARCHIVEBOX {kind} .*?<!-- END ARCHIVEBOX {kind} -->"
    if not re.search(pattern, text, re.DOTALL):
        pattern = initial_pattern
    updated, count = re.subn(
        pattern, lambda _: block(kind, value), text, count=1, flags=re.DOTALL
    )
    if count != 1:
        raise ValueError(f"Cannot locate {kind} block")
    return updated


LEGACY = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{{ page.title | default: site.title }} · ArchiveBox</title><meta name="description" content="{{ site.description | escape }}"><link rel="canonical" href="{{ page.url | absolute_url }}"><link rel="stylesheet" href="{{ '/assets/site-chrome.css' | relative_url }}"><style>body{margin:0;background:#fcfaf7;color:#28252a;font:16px/1.75 system-ui,sans-serif}main{max-width:1060px;margin:auto;padding:40px 24px;overflow-wrap:anywhere}main img{max-width:100%;height:auto}main a{color:#9b2854}main pre{overflow:auto;background:#f0e8eb;padding:18px;border-radius:8px}main table{display:block;overflow:auto}main h1,main h2,main h3{line-height:1.25}main a:focus-visible{outline:3px solid #9b2854;outline-offset:3px}</style></head><body><header></header><main id="content">{{ content }}</main><footer></footer></body></html>"""


def render(check=False):
    changed = []

    def write(path, text):
        if path.parent.name == "templates" and path.name.startswith("screenshots-"):
            text = text.rstrip() + "\n"
        if path.exists() and path.read_text() == text:
            return
        changed.append(str(path))
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    css = (HERE / "chrome.css").read_text()
    for site in SITES:
        path = site["root"] / site["template"]
        text = (
            path.read_text() if path.exists() else LEGACY if site.get("legacy") else ""
        )
        if not text:
            raise ValueError(f"Missing site template: {path}")
        local_path = HERE / "local-footers" / f"{site['key']}.html"
        if local_path.exists():
            local = local_path.read_text()
        else:
            old = re.search(r"<footer\b([^>]*)>(.*?)</footer>", text, re.DOTALL)
            local = old[2].strip() if old else ""
            if old and 'id="resources"' in old[1]:
                local = f'<div id="resources">{local}</div>'
            write(local_path, local)
        if site["key"] == "evals" and "BEGIN ARCHIVEBOX HEADER" not in text:
            status = re.search(r'<div class="topbar-meta">.*?</div>', text, re.DOTALL)[
                0
            ]
            text = text.replace("<main>", "<main>\n" + status, 1)
        if site["key"] == "digest" and "BEGIN ARCHIVEBOX HEADER" not in text:
            old_header = re.search(r"<header\b[^>]*>(.*?)</header>", text, re.DOTALL)[1]
            text = text.replace(
                '<main class="flex-1 p-4 md:p-8">',
                '<main class="flex-1 p-4 md:p-8">' + old_header,
                1,
            )
        text = replace_block(
            text,
            "HEADER",
            header(**{k: site[k] for k in ["name", "home", "repo", "nav", "cta"]}),
            r"<header\b.*?</header>",
        )
        footer_html = footer(site["name"], local)
        if site.get("external_script"):
            script_path = site["root"] / site["external_script"]
            write(script_path, SCRIPT.removeprefix("<script>\n").removesuffix("\n</script>") + "\n")
            footer_html = footer_html.replace(SCRIPT, f'<script type="module" src="{script_path.name}"></script>').replace("\n  \n", "\n\n")
        text = replace_block(
            text, "FOOTER", footer_html, r"<footer></footer>" if site["key"] == "tlsnotary" else r"<footer\b.*?</footer>"
        )
        if site.get("append_css"):
            css_path = site["root"] / site["css"]
            old_css = css_path.read_text()
            old_css = re.sub(
                r"\n?/\* BEGIN ARCHIVEBOX CHROME \*/.*?/\* END ARCHIVEBOX CHROME \*/\n?",
                "",
                old_css,
                flags=re.DOTALL,
            )
            write(
                css_path,
                old_css.rstrip()
                + "\n\n/* BEGIN ARCHIVEBOX CHROME */\n"
                + css
                + "/* END ARCHIVEBOX CHROME */\n",
            )
        else:
            write(site["root"] / site["css"], css)
            if not site.get("legacy") and "site-chrome.css" not in text:
                href = (
                    "css/site-chrome.css"
                    if site["key"] in ["plugins", "pkg"]
                    else "site-chrome.css"
                )
                text = text.replace(
                    "</head>", f'<link rel="stylesheet" href="{href}">\n</head>', 1
                )
        write(path, text)
    # Generator-owned galleries use the same rendered fragments at build time.
    write(
        WORKSPACE / "archivebox/bin/templates/screenshots-header.html",
        header(
            "UI Screenshots",
            "https://archivebox.io/",
            "ArchiveBox",
            [
                ("Screenshots", "https://archivebox.io/screenshots/"),
                ("Docs", "https://github.com/ArchiveBox/ArchiveBox/wiki"),
            ],
            ("Get started", "https://archivebox.io/#install"),
        ),
    )
    write(
        WORKSPACE / "archivebox/bin/templates/screenshots-footer.html",
        footer("UI Screenshots"),
    )
    ext = FAMILY / "archivebox-browser-extension/docs/site"
    write(
        ext / "header.html",
        header(
            "Browser Extensions",
            "__BASE__",
            "archivebox-browser-extension",
            [("Screenshots", "__BASE__screenshots/")],
            ("Get the extension", "__BASE__#get-the-extension"),
        ),
    )
    write(
        ext / "footer.html",
        footer(
            "Browser Extensions",
            '<a href="https://github.com/ArchiveBox/archivebox-browser-extension/blob/__REVISION__/README.md">README source</a> · <a href="__BASE__screenshots/manifest.json">Screenshot manifest</a>',
        ),
    )
    old_css = re.sub(
        r"\n?/\* BEGIN ARCHIVEBOX CHROME \*/.*?/\* END ARCHIVEBOX CHROME \*/\n?",
        "",
        (ext / "style.css").read_text(),
        flags=re.DOTALL,
    )
    write(
        ext / "style.css",
        old_css.rstrip()
        + "\n\n/* BEGIN ARCHIVEBOX CHROME */\n"
        + css
        + "/* END ARCHIVEBOX CHROME */\n",
    )
    if check and changed:
        raise SystemExit("Out-of-date generated chrome:\n" + "\n".join(changed))
    print(
        f"{'Checked' if check else 'Updated'} shared chrome: {len(changed)} changed files"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    render(parser.parse_args().check)
