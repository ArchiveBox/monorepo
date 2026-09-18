# Shared ArchiveBox website header and footer

`links.json` owns the organization-wide directory. `chrome.css` owns the scoped
header and footer styles. `sync.py` renders accessible static HTML into the
Pages source of all 11 Pages-enabled ArchiveBox repositories; the main site and
browser extension also use it for their screenshot galleries.

From a standard monorepo checkout (with the Apple apps, extension, DigestBox,
community, and Good Karma Kit checked out beside the monorepo):

```sh
uv run --no-project python site-chrome/sync.py
uv run --no-project python site-chrome/sync.py --check
```

Commit the generated changes in each affected repository. Builds never fetch
shared navigation from the network: static links, SVG logos, styles, and the
small progressive-enhancement script are included locally. The Apps menu works
without JavaScript. The script adds Escape/outside-click dismissal and reveals
collapsed details when following anchors.

`local-footers/` retains each site's original resource links, descriptions,
provenance, and anchor IDs. The two long reference footers remain in expandable
sections. Do not remove unique details while updating the shared directory.

The Debian landing page is copied into the existing `gh-pages` apt repository
by its normal publish workflow; package files and apt metadata are unchanged.
Legacy README sites keep their original Markdown and use a local Jekyll layout.
DigestBox is labeled a concept because its README describes a design mockup.

Validation should build each site's real template pipeline, compare existing
anchor IDs and content links, check Apps with keyboard/no JavaScript, and inspect
the header and footer at desktop and narrow widths. Shared classes use the
`abx-` prefix to isolate them from each site's content styles.

Run the browser verification after building the sites:

```sh
node site-chrome/verify.mjs
# Include a locally generated ArchiveBox screenshot gallery if available:
ARCHIVEBOX_GALLERY=/path/to/generated/screenshots node site-chrome/verify.mjs
```

The verifier uses the browser extension's existing Playwright installation. Its
legacy Jekyll preview roots are `/tmp/archivebox-chrome-preview/community` (build
with `--baseurl /community`) and `/tmp/archivebox-chrome-preview/good-karma-kit`.
Apple and extension builds use their normal repository base paths. No backend
or native application behavior is changed or substituted during these checks.
