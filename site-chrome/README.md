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

DigestBox's project page is published at `https://archivebox.github.io/DigestBox/`.
The separate live archive at `digestbox.io` keeps its existing routing.

## Fast publishing

ArchiveBox, the browser extension, and the Apple app publish their current website
on each push independently of screenshot capture. Their `screenshots.yml` workflows
retain all real capture and completeness checks, then upload `site-screenshots`
for 90 days. A successful capture triggers another website publish. Each publish
checks out the latest default-branch site source, so an older capture cannot roll
back newer copy or styles. Manual website publishing does not run capture CI;
manually run the capture workflow to refresh images.

Publishers restore the newest successful default-branch capture artifact, or
the manifest and images from the published site after artifact expiry. Screenshot
revision metadata is retained independently of the site revision. ArchiveBox
re-renders the existing gallery content with current presentation. Before the
first complete native capture, the Apple site presents its existing curated README
screenshots without claiming they are a complete automated capture.

The Debian landing page has an independent Pages workflow that preserves the
existing apt repository. The CI dashboard publishes layouts with its existing
data immediately, while its collector refreshes data separately. Other project
sites already build without waiting for application test or release workflows.

The TLSNotary verifier is also included in the shared navigation generator. Its
source is `abx-plugins/abx_plugins/plugins/tlsnotary/server/web`; its strict CSP
uses the generated local `site-chrome.mjs` module instead of an inline script.
After syncing, run the server's `visualization/build.mjs` to refresh stylesheet
cache keys and the archived full-output template. Compact capture thumbnails
keep the navigation hidden. TLSNotary is deployed separately from GitHub Pages
using the gateway container on cabbage; preserve its existing signing state.

## Apps dropdown edits

`apps.html` holds the reviewed static dropdown, including inline platform and integration logos.
Each Pages repository keeps its own local HTML and CSS. Roll menu changes out manually
to the site templates (including Android and Electron) and their gallery header fragments;
do not add cross-repository CI synchronization. Preserve each site's local navigation and footer content.
The ArchiveBox navbar brand always links to `https://archivebox.io/`.
