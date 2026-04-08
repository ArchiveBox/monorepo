# Group `Ready` Gating Plan For `abx-plugins`

codex resume 'abx-plugins readyness gating based on explicit groups'

## Goal

Keep hooks independently useful as standalone commands, keep filesystem-based hook discovery, and add a generic DAG/barrier mechanism that does **not** require `abx-dl` to know plugin-specific concepts like Chrome, OCR, redirects, or headers.

This plan uses:

- root scheduler events such as `BinaryRequest`, `CrawlSetup`, and `Snapshot`
- optional per-hook target groups encoded directly in hook filenames
- synthetic `<Root><Group>Ready` events emitted generically by `abx-dl`
- terminal `...Completed` events emitted only at the true end of a root lifecycle after background hooks have exited or been killed

This plan does **not** introduce:

- central YAML DAG definitions
- sidecar metadata files per hook
- a shared aggregate `derived.env`
- plugin-specific scheduler logic in `abx-dl`
- replacement of useful debugging/state files like `cdp_url.txt` and `target_id.txt`

## Design Constraints

The implementation must preserve these properties:

- hooks remain black-box executables
- `.finite.bg` and `.daemon.bg` remain human hints only; runtime behavior only distinguishes fg vs bg
- hooks can still be run directly by users with explicit env vars / CLI args and by polling the canonical files or artifacts they already understand
- canonical files and artifacts stay available for debugging and crash inspection:
  - `chrome/cdp_url.txt`
  - `chrome/target_id.txt`
  - `chrome/navigation.json`
  - `chrome/extensions.json`
  - output files like PDFs, PNGs, HTML, OCR text, JSONL indexes, sockets, etc.
- plugin ordering remains readable from the filesystem alone

## Core Scheduler Model

### 1. Hook filename grammar

Keep plain hooks:

- `on_<Event>__<order>_<name>.<ext>`

Add grouped hooks:

- `on_<Event>__<TargetGroup>__<order>_<name>.<ext>`

Examples:

- `on_Snapshot__02_ytdlp.finite.bg.py`
- `on_Snapshot__ChromeStart__09_chrome_launch.daemon.bg.js`
- `on_SnapshotChromeAttachReady__PreNav__21_consolelog.daemon.bg.js`
- `on_SnapshotPreNavReady__Navigate__30_chrome_navigate.js`
- `on_SnapshotNavigateReady__PostNav__51_screenshot.js`

Rules:

- `<Event>` must remain a valid identifier string in Python/JS terms: letters, numbers, underscores, starting with a letter/underscore
- `<TargetGroup>` uses the same identifier-safe rule
- `<order>` stays as the current numeric tie-breaker
- if `<TargetGroup>` is omitted, the hook behaves exactly like a normal current hook triggered directly by `<Event>`

Suggested parser shape for [`../abx-dl/abx_dl/models.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/models.py):

```python
^on_(\w+)__(?:(\w+)__)?(?:(\d+)_)?(.+)$
```

And `Hook` should gain:

- `event: str`
- `target_group: str | None`
- `order: int`
- `is_background: bool`

Nothing else about hooks should be inferred.

### 2. What a group means

A grouped hook contributes to a generic settle barrier for that group.

Example:

- `on_SnapshotChromeAttachReady__PreNav__21_consolelog.daemon.bg.js`

means:

- trigger when `SnapshotChromeAttachReady` happens
- this hook contributes to the `PreNav` barrier
- once all hooks triggered for the same root scope and contributing to `PreNav` have settled, `abx-dl` emits `SnapshotPreNavReady`

### 3. `Ready` semantics

For a grouped barrier:

- fg hooks settle when the process exits
- bg hooks settle when they emit their **first stdout line** or when they exit, whichever comes first

This is the key generic primitive that makes pre-navigation barriers work without `abx-dl` knowing about specific plugins.

Implications:

- stdout is a machine-significant channel
- stderr is for human logs
- a grouped bg hook must not write to stdout until it is actually ready for downstream work
- grouped bg hooks should flush stdout immediately after the first line

Group settlement and failure policy are separate concerns:

- settlement decides when the barrier may advance
- normal process failure / abort policy still decides whether the crawl or snapshot should continue
- `abx-dl` should not overload group settlement with plugin-specific success rules

### 4. Synthetic `Ready` event naming

For a root scheduler scope:

- `Snapshot` + group `ChromeStart` -> `SnapshotChromeStartReady`
- `Snapshot` + group `ChromeAttach` -> `SnapshotChromeAttachReady`
- `Snapshot` + group `PreNav` -> `SnapshotPreNavReady`
- `Snapshot` + group `Navigate` -> `SnapshotNavigateReady`
- `Snapshot` + group `PostNav` -> `SnapshotPostNavReady`
- `Snapshot` + group `TextExtract` -> `SnapshotTextExtractReady`
- `Snapshot` + group `Parse` -> `SnapshotParseReady`
- `Snapshot` + group `Index` -> `SnapshotIndexReady`
- `Snapshot` + group `Finalize` -> `SnapshotFinalizeReady`

For crawl setup:

- `CrawlSetup` + group `ChromeStart` -> `CrawlSetupChromeStartReady`
- `CrawlSetup` + group `Setup` -> `CrawlSetupReady`

`abx-dl` does not need to know what those names mean. It only needs:

- the root scope name
- the opaque target group string

### 5. `Completed` semantics

`Completed` events are only emitted at the true end of a root lifecycle, after all background hooks in that root have exited or been killed.

Use:

- `SnapshotCompleted`
- `CrawlCompleted`

Do **not** emit group-level `...Completed` events as normal scheduler barriers.

`CrawlSetupReady` is the end of the setup DAG.
`SnapshotFinalizeReady` is the end of the snapshot work DAG.
`SnapshotCompleted` happens later, after internal cleanup of remaining bg hooks.

### 6. Standalone hook contract

Grouped scheduling must not remove standalone usefulness.

Hooks should continue to work like this:

1. explicit CLI args / env vars win
2. otherwise read canonical shared files or artifacts
3. poll/retry if needed
4. hard fail if required state never appears

This is important for commands like:

```bash
URL=https://example.com \
CDP_URL=ws://127.0.0.1:9222/devtools/browser/... \
TARGET_ID=ABC123 \
./abx_plugins/plugins/screenshot/on_SnapshotNavigateReady__PostNav__51_screenshot.js \
  --url=https://example.com
```

The grouped `Ready` system is scheduler-side orchestration only. It does not replace hook-local state validation.

## Runtime Rules For `abx-dl`

### Scheduler ownership

`abx-dl` should own only:

- hook discovery from filenames
- event routing by string
- per-group settle tracking
- synthetic `<Root><Group>Ready` emission
- root terminal completion events
- background process cleanup at the end of a root lifecycle

`abx-dl` must not own:

- plugin-specific readiness semantics
- Chrome-specific event classes
- OCR-specific fan-in logic
- per-plugin file formats

### Event routing ownership

Use root-scope ownership by prefix:

- `BinaryRequest*` -> Binary service
- `CrawlSetup*` -> Crawl setup service
- `Snapshot*` -> Snapshot service

This keeps routing generic while still letting services remain scoped.

### Group settle tracking

For each emitted scheduler event `E` inside a root scope:

1. discover all hooks subscribed to `E`
2. split them by `target_group`
3. launch them in filename order
4. track grouped hook settlement
5. when all contributors to one group settle, emit `<Root><Group>Ready`

Conventions to keep this simple:

- group names should be unique within a root scope unless a deliberate fan-in is desired
- each group should normally be produced once per root lifecycle
- the group graph must be acyclic

### Ready payload

Synthetic `Ready` events should carry the same root event context as normal scheduler events:

- `url`
- `snapshot_id` where applicable
- `output_dir`
- `depth` if relevant

That way hooks on `SnapshotPreNavReady` still receive the normal base CLI args they already expect.

### Background ready signal

The runtime contract for grouped bg hooks is:

- the first line on stdout marks the hook as ready for its group
- the line may be JSONL or plain text
- non-JSON lines still count for readiness even if other services ignore them

This can be implemented entirely from existing [`ProcessStdoutEvent`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/process_service.py) flow. No new special public event type is required.

## `abx-dl` Changes

### 1. [`../abx-dl/abx_dl/models.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/models.py)

Update hook parsing and the `Hook` model:

- parse optional `target_group`
- keep `event` and `target_group` as raw strings
- keep `order` and `is_background`
- do not add any other hook classification

`Plugin.filter_hooks(event_name)` can stay, but callers will now also inspect `hook.target_group`.

### 2. [`../abx-dl/abx_dl/events.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/events.py)

Keep the root plugin-facing event types aligned with filenames:

- `BinaryRequest`
- `CrawlSetup`
- `Snapshot`

Do not add typed event classes for every synthetic `Ready` event.

Synthetic `Ready` events should be emitted as `BaseEvent(event_type=...)` with identifier-safe string names like:

- `SnapshotChromeStartReady`
- `SnapshotChromeAttachReady`
- `SnapshotPreNavReady`
- `SnapshotNavigateReady`
- `CrawlSetupReady`

Terminal end-of-root events may remain typed classes if that is convenient:

- `SnapshotCompletedEvent`
- `CrawlCompletedEvent`

### 3. [`../abx-dl/abx_dl/services/process_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/process_service.py)

No new hook-specific logic belongs here.

What must be true:

- every stdout line continues to emit `ProcessStdoutEvent`
- grouped bg readiness can be computed from the first `ProcessStdoutEvent` for that process
- stdout/stderr files continue to be written for debugging

No distinction should be added between `.finite.bg` and `.daemon.bg`.

### 4. [`../abx-dl/abx_dl/services/crawl_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/crawl_service.py)

Replace exact `CrawlSetup` hook handling with generic `CrawlSetup*` scheduler dispatch.

Needed changes:

- collect all hooks whose `event` starts with `CrawlSetup`
- dispatch by exact event string, not only the root `CrawlSetup` event
- track grouped settle state for crawl-setup hooks
- synthesize `CrawlSetup<group>Ready` events generically
- synthesize `CrawlSetupReady` when the final setup group is ready
- start snapshot execution from `CrawlSetupReady`, not from a hand-maintained wait hook

Keep crawl-scoped background cleanup as internal runtime behavior at the end of the whole crawl, followed by `CrawlCompleted`.

### 5. [`../abx-dl/abx_dl/services/snapshot_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/snapshot_service.py)

Replace exact `Snapshot`-only dispatch with generic `Snapshot*` scheduler dispatch.

Needed changes:

- collect all hooks whose `event` starts with `Snapshot`
- dispatch by exact event string
- track grouped settle state for snapshot hooks
- synthesize `Snapshot<group>Ready` events generically
- once the last planned snapshot work group is ready, run internal background cleanup
- emit `SnapshotCompleted` only after bg hooks have exited or been killed

Do **not** special-case Chrome/OCR/parser plugin names.

### 6. [`../abx-dl/abx_dl/services/archive_result_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/archive_result_service.py)

Minimal change only.

Grouped snapshot hook names like:

- `on_SnapshotChromeAttachReady__PreNav__21_consolelog.daemon.bg`
- `on_SnapshotNavigateReady__PostNav__51_screenshot`

still begin with `on_Snapshot`, so current synthetic fallback logic should continue to work for snapshot hooks.

No new scheduler-specific `ArchiveResult` behavior is needed for this plan.

### 7. Non-scheduler stdout records

Keep existing output records like:

- `ArchiveResult`
- `UrlDiscovered`

`UrlDiscovered` should remain the cross-plugin discovery record for parsers/bookmarks/feeds instead of emitting new `Snapshot` records.

Those records are not part of group scheduling.

## Shared Helper Changes In `abx-plugins`

### 1. [`abx_plugins/plugins/base/utils.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/base/utils.js)
### 2. [`abx_plugins/plugins/base/utils.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/base/utils.py)

Add one tiny shared helper for grouped bg hooks:

- `signal_ready()` or `emit_ready_line()`

Requirements:

- write one newline-terminated line to stdout
- flush immediately
- never log casual human output to stdout

This helper is only for the group-ready contract.
Normal JSONL emission helpers remain as-is.

Also centralize:

- explicit env/CLI override precedence
- reading canonical shared files like `cdp_url.txt`, `target_id.txt`, `navigation.json`, `extensions.json`
- polling/wait helpers used by standalone hooks

Do **not** add shared `derived.env` logic.

### 3. [`abx_plugins/plugins/chrome/chrome_utils.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/chrome_utils.js)

Keep and strengthen the helper layer for:

- reading current Chrome state from canonical files
- reconnecting to current `CDP_URL`
- re-reading current `TARGET_ID`
- validating `navigation.json`

Remove orchestration-only logic over time:

- `prenav.json` handling
- marker-file barriers whose only purpose is “this hook is ready”

Keep useful debug artifacts:

- `cdp_url.txt`
- `target_id.txt`
- `extensions.json`
- `navigation.json`

## Canonical State And Artifact Contract

This plan keeps useful per-plugin files and real artifacts.

### Keep as canonical shared state/artifacts

- `chrome/cdp_url.txt`
- `chrome/target_id.txt`
- `chrome/extensions.json`
- `chrome/navigation.json`
- `responses/index.jsonl`
- PDFs, screenshots, DOM dumps, OCR text, sockets, DBs, indexes, etc.

### Remove or demote as orchestration hacks

- `redirects/prenav.json`
- `.twocaptcha_configured`
- `.claudechrome_configured`
- touching an output file only to mean “ready”
- scraping sibling `stdout.log` as a hidden control plane

The refactor target is not “replace files with env vars”.
It is “stop using bespoke files as hidden inter-hook barrier protocols when groups and `Ready` events express that more clearly”.

## Proposed Group Graph

### Crawl setup

Use:

- root event: `CrawlSetup`
- groups:
  - `ChromeStart`
  - `Setup`

Flow:

1. `CrawlSetup`
2. grouped hooks contribute to `ChromeStart`
3. `CrawlSetupChromeStartReady`
4. grouped hooks contribute to `Setup`
5. `CrawlSetupReady`
6. `abx-dl` starts snapshot execution

### Snapshot chrome pipeline

Use:

- root event: `Snapshot`
- groups:
  - `ChromeStart`
  - `ChromeAttach`
  - `PreNav`
  - `Navigate`
  - `PostNav`

Flow:

1. `Snapshot`
2. `SnapshotChromeStartReady`
3. `SnapshotChromeAttachReady`
4. `SnapshotPreNavReady`
5. `SnapshotNavigateReady`
6. `SnapshotPostNavReady`

This solves the main generic Chrome problem:

- `chrome_navigate` waits on `SnapshotPreNavReady`
- it does not know about `headers`, `responses`, `redirects`, `dns`, `consolelog`, etc.
- `abx-dl` does not know about those plugins either
- membership is visible purely from the filesystem

### `CHROME_ISOLATION` handling

The grouped scheduler should work in both browser ownership modes.

If `CHROME_ISOLATION=crawl`:

- `on_CrawlSetup__ChromeStart__90_chrome_launch.daemon.bg.js` owns the long-lived crawl browser
- `CrawlSetupChromeStartReady` exists during crawl setup
- `on_Snapshot__ChromeStart__09_chrome_launch.daemon.bg.js` still participates in the snapshot graph, but it should only ensure snapshot-local browser state is available by reusing the crawl-owned browser
- `SnapshotChromeStartReady` should still be emitted for every snapshot so the rest of the snapshot graph is uniform

If `CHROME_ISOLATION=snapshot`:

- `on_CrawlSetup__ChromeStart__90_chrome_launch.daemon.bg.js` is skipped
- `on_Snapshot__ChromeStart__09_chrome_launch.daemon.bg.js` launches the browser for that snapshot
- `SnapshotChromeStartReady` is emitted after the snapshot-owned browser is ready

This keeps the snapshot-side scheduler graph identical in both modes:

- `Snapshot`
- `SnapshotChromeStartReady`
- `SnapshotChromeAttachReady`
- `SnapshotPreNavReady`
- `SnapshotNavigateReady`
- `SnapshotPostNavReady`

### Future generic late stages

Only add these when the producer set is clear:

- `TextExtract`
- `Parse`
- `Index`
- `Finalize`

That gives these later barriers:

- `SnapshotTextExtractReady`
- `SnapshotParseReady`
- `SnapshotIndexReady`
- `SnapshotFinalizeReady`

This is the right tool for cases like:

- multiple OCR/text-producing hooks
- later parsers that must wait until all text outputs are finished
- later indexers that must wait until all parse outputs are finished

Do not force these groups onto hooks that do not actually need them.

## Concrete Rename Plan

### Delete pure wait hooks

Delete:

- [`abx_plugins/plugins/chrome/on_CrawlSetup__91_chrome_wait.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_CrawlSetup__91_chrome_wait.js)
- [`abx_plugins/plugins/chrome/on_Snapshot__11_chrome_wait.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__11_chrome_wait.js)

### Crawl setup renames

- [`abx_plugins/plugins/chrome/on_CrawlSetup__90_chrome_launch.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_CrawlSetup__90_chrome_launch.daemon.bg.js)
  -> `on_CrawlSetup__ChromeStart__90_chrome_launch.daemon.bg.js`

- [`abx_plugins/plugins/twocaptcha/on_CrawlSetup__95_twocaptcha_config.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/twocaptcha/on_CrawlSetup__95_twocaptcha_config.js)
  -> `on_CrawlSetupChromeStartReady__Setup__95_twocaptcha_config.js`

- [`abx_plugins/plugins/claudechrome/on_CrawlSetup__96_claudechrome_config.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/claudechrome/on_CrawlSetup__96_claudechrome_config.js)
  -> `on_CrawlSetupChromeStartReady__Setup__96_claudechrome_config.js`

### Snapshot chrome bootstrap renames

- [`abx_plugins/plugins/chrome/on_Snapshot__09_chrome_launch.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__09_chrome_launch.daemon.bg.js)
  -> `on_Snapshot__ChromeStart__09_chrome_launch.daemon.bg.js`

- [`abx_plugins/plugins/chrome/on_Snapshot__10_chrome_tab.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__10_chrome_tab.daemon.bg.js)
  -> `on_SnapshotChromeStartReady__ChromeAttach__10_chrome_tab.daemon.bg.js`

### Snapshot pre-nav renames

- [`abx_plugins/plugins/ublock/on_Snapshot__12_ublock.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/ublock/on_Snapshot__12_ublock.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__12_ublock.daemon.bg.js`

- [`abx_plugins/plugins/istilldontcareaboutcookies/on_Snapshot__13_istilldontcareaboutcookies.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/istilldontcareaboutcookies/on_Snapshot__13_istilldontcareaboutcookies.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__13_istilldontcareaboutcookies.daemon.bg.js`

- [`abx_plugins/plugins/twocaptcha/on_Snapshot__14_twocaptcha.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/twocaptcha/on_Snapshot__14_twocaptcha.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__14_twocaptcha.daemon.bg.js`

- [`abx_plugins/plugins/modalcloser/on_Snapshot__15_modalcloser.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/modalcloser/on_Snapshot__15_modalcloser.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__15_modalcloser.daemon.bg.js`

- [`abx_plugins/plugins/consolelog/on_Snapshot__21_consolelog.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/consolelog/on_Snapshot__21_consolelog.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__21_consolelog.daemon.bg.js`

- [`abx_plugins/plugins/dns/on_Snapshot__22_dns.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/dns/on_Snapshot__22_dns.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__22_dns.daemon.bg.js`

- [`abx_plugins/plugins/sslcerts/on_Snapshot__23_sslcerts.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/sslcerts/on_Snapshot__23_sslcerts.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__23_sslcerts.daemon.bg.js`

- [`abx_plugins/plugins/responses/on_Snapshot__24_responses.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/responses/on_Snapshot__24_responses.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__24_responses.daemon.bg.js`

- [`abx_plugins/plugins/redirects/on_Snapshot__25_redirects.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/redirects/on_Snapshot__25_redirects.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__25_redirects.daemon.bg.js`

- [`abx_plugins/plugins/headers/on_Snapshot__27_headers.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/headers/on_Snapshot__27_headers.daemon.bg.js)
  -> `on_SnapshotChromeAttachReady__PreNav__27_headers.daemon.bg.js`

### Snapshot navigation rename

- [`abx_plugins/plugins/chrome/on_Snapshot__30_chrome_navigate.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__30_chrome_navigate.js)
  -> `on_SnapshotPreNavReady__Navigate__30_chrome_navigate.js`

### Snapshot post-nav renames

- [`abx_plugins/plugins/seo/on_Snapshot__38_seo.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/seo/on_Snapshot__38_seo.js)
  -> `on_SnapshotNavigateReady__PostNav__38_seo.js`

- [`abx_plugins/plugins/accessibility/on_Snapshot__39_accessibility.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/accessibility/on_Snapshot__39_accessibility.js)
  -> `on_SnapshotNavigateReady__PostNav__39_accessibility.js`

- [`abx_plugins/plugins/infiniscroll/on_Snapshot__45_infiniscroll.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/infiniscroll/on_Snapshot__45_infiniscroll.js)
  -> `on_SnapshotNavigateReady__PostNav__45_infiniscroll.js`

- [`abx_plugins/plugins/claudechrome/on_Snapshot__47_claudechrome.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/claudechrome/on_Snapshot__47_claudechrome.js)
  -> `on_SnapshotNavigateReady__PostNav__47_claudechrome.js`

- [`abx_plugins/plugins/singlefile/on_Snapshot__50_singlefile.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/singlefile/on_Snapshot__50_singlefile.py)
  -> `on_SnapshotNavigateReady__PostNav__50_singlefile.py`

- [`abx_plugins/plugins/screenshot/on_Snapshot__51_screenshot.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/screenshot/on_Snapshot__51_screenshot.js)
  -> `on_SnapshotNavigateReady__PostNav__51_screenshot.js`

- [`abx_plugins/plugins/pdf/on_Snapshot__52_pdf.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/pdf/on_Snapshot__52_pdf.js)
  -> `on_SnapshotNavigateReady__PostNav__52_pdf.js`

- [`abx_plugins/plugins/dom/on_Snapshot__53_dom.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/dom/on_Snapshot__53_dom.js)
  -> `on_SnapshotNavigateReady__PostNav__53_dom.js`

- [`abx_plugins/plugins/title/on_Snapshot__54_title.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/title/on_Snapshot__54_title.js)
  -> `on_SnapshotNavigateReady__PostNav__54_title.js`

- [`abx_plugins/plugins/parse_dom_outlinks/on_Snapshot__75_parse_dom_outlinks.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_dom_outlinks/on_Snapshot__75_parse_dom_outlinks.js)
  -> `on_SnapshotNavigateReady__PostNav__75_parse_dom_outlinks.js`

### Hooks that should stay unchanged for the first migration

Keep plain `on_Snapshot__...` for now:

- [`abx_plugins/plugins/ytdlp/on_Snapshot__02_ytdlp.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/ytdlp/on_Snapshot__02_ytdlp.finite.bg.py)
- [`abx_plugins/plugins/gallerydl/on_Snapshot__03_gallerydl.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/gallerydl/on_Snapshot__03_gallerydl.finite.bg.py)
- [`abx_plugins/plugins/forumdl/on_Snapshot__04_forumdl.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/forumdl/on_Snapshot__04_forumdl.finite.bg.py)
- [`abx_plugins/plugins/git/on_Snapshot__05_git.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/git/on_Snapshot__05_git.finite.bg.py)
- [`abx_plugins/plugins/wget/on_Snapshot__06_wget.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/wget/on_Snapshot__06_wget.finite.bg.py)
- [`abx_plugins/plugins/archivedotorg/on_Snapshot__08_archivedotorg.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/archivedotorg/on_Snapshot__08_archivedotorg.finite.bg.py)
- [`abx_plugins/plugins/favicon/on_Snapshot__11_favicon.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/favicon/on_Snapshot__11_favicon.finite.bg.py)
- [`abx_plugins/plugins/papersdl/on_Snapshot__66_papersdl.finite.bg.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/papersdl/on_Snapshot__66_papersdl.finite.bg.py)

Also leave these unchanged until their true producer set is clear:

- [`abx_plugins/plugins/readability/on_Snapshot__56_readability.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/readability/on_Snapshot__56_readability.py)
- [`abx_plugins/plugins/mercury/on_Snapshot__57_mercury.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/mercury/on_Snapshot__57_mercury.py)
- [`abx_plugins/plugins/defuddle/on_Snapshot__57_defuddle.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/defuddle/on_Snapshot__57_defuddle.py)
- [`abx_plugins/plugins/htmltotext/on_Snapshot__58_htmltotext.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/htmltotext/on_Snapshot__58_htmltotext.py)
- [`abx_plugins/plugins/claudecodeextract/on_Snapshot__58_claudecodeextract.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/claudecodeextract/on_Snapshot__58_claudecodeextract.py)
- [`abx_plugins/plugins/trafilatura/on_Snapshot__59_trafilatura.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/trafilatura/on_Snapshot__59_trafilatura.py)
- [`abx_plugins/plugins/opendataloader/on_Snapshot__60_opendataloader.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/opendataloader/on_Snapshot__60_opendataloader.py)
- [`abx_plugins/plugins/liteparse/on_Snapshot__61_liteparse.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/liteparse/on_Snapshot__61_liteparse.py)
- [`abx_plugins/plugins/parse_html_urls/on_Snapshot__70_parse_html_urls.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_html_urls/on_Snapshot__70_parse_html_urls.py)
- [`abx_plugins/plugins/search_backend_sqlite/on_Snapshot__90_index_sqlite.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/search_backend_sqlite/on_Snapshot__90_index_sqlite.py)
- [`abx_plugins/plugins/search_backend_sonic/on_Snapshot__91_index_sonic.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/search_backend_sonic/on_Snapshot__91_index_sonic.py)
- [`abx_plugins/plugins/claudecodecleanup/on_Snapshot__92_claudecodecleanup.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/claudecodecleanup/on_Snapshot__92_claudecodecleanup.py)
- [`abx_plugins/plugins/hashes/on_Snapshot__93_hashes.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/hashes/on_Snapshot__93_hashes.py)

These may later move into `TextExtract`, `Parse`, `Index`, or `Finalize` groups, but they should not be regrouped until the actual producer/consumer boundaries are agreed.

### Hooks that need deeper refactors, not just renames

- [`abx_plugins/plugins/staticfile/on_Snapshot__26_staticfile.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/staticfile/on_Snapshot__26_staticfile.daemon.bg.js)
  - mixed-role today
  - likely needs to be split into a pre-nav probe and a later capture/decision step

- [`abx_plugins/plugins/parse_txt_urls/on_Snapshot__71_parse_txt_urls.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_txt_urls/on_Snapshot__71_parse_txt_urls.py)
- [`abx_plugins/plugins/parse_rss_urls/on_Snapshot__72_parse_rss_urls.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_rss_urls/on_Snapshot__72_parse_rss_urls.py)
- [`abx_plugins/plugins/parse_netscape_urls/on_Snapshot__73_parse_netscape_urls.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_netscape_urls/on_Snapshot__73_parse_netscape_urls.py)
- [`abx_plugins/plugins/parse_jsonl_urls/on_Snapshot__74_parse_jsonl_urls.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/parse_jsonl_urls/on_Snapshot__74_parse_jsonl_urls.py)
  - these currently parse their direct source input, not late generated outputs
  - do not move them into grouped late stages until that behavior is intentionally changed

## Hook Logic That Gets Simpler

### Chrome wait barriers

Delete both wait scripts entirely:

- [`abx_plugins/plugins/chrome/on_CrawlSetup__91_chrome_wait.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_CrawlSetup__91_chrome_wait.js)
- [`abx_plugins/plugins/chrome/on_Snapshot__11_chrome_wait.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__11_chrome_wait.js)

### `chrome_navigate`

In [`abx_plugins/plugins/chrome/on_Snapshot__30_chrome_navigate.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__30_chrome_navigate.js):

- remove `prenav.json` polling entirely
- start only from `SnapshotPreNavReady`
- keep local validation of required state like `cdp_url.txt` / `target_id.txt`

### Snapshot Chrome launch

In [`abx_plugins/plugins/chrome/on_Snapshot__09_chrome_launch.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/chrome/on_Snapshot__09_chrome_launch.daemon.bg.js):

- always participate in the snapshot `ChromeStart` group
- in crawl isolation, reuse the existing crawl-owned browser and publish any snapshot-local state it needs
- in snapshot isolation, launch the snapshot-owned browser
- signal ready only when the snapshot can proceed to tab attachment

### Pre-nav bg hooks

In:

- [`abx_plugins/plugins/consolelog/on_Snapshot__21_consolelog.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/consolelog/on_Snapshot__21_consolelog.daemon.bg.js)
- [`abx_plugins/plugins/dns/on_Snapshot__22_dns.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/dns/on_Snapshot__22_dns.daemon.bg.js)
- [`abx_plugins/plugins/sslcerts/on_Snapshot__23_sslcerts.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/sslcerts/on_Snapshot__23_sslcerts.daemon.bg.js)
- [`abx_plugins/plugins/responses/on_Snapshot__24_responses.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/responses/on_Snapshot__24_responses.daemon.bg.js)
- [`abx_plugins/plugins/redirects/on_Snapshot__25_redirects.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/redirects/on_Snapshot__25_redirects.daemon.bg.js)
- [`abx_plugins/plugins/headers/on_Snapshot__27_headers.daemon.bg.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/headers/on_Snapshot__27_headers.daemon.bg.js)

simplify by:

- calling `signal_ready()` once listeners are attached
- removing fake “ready” marker files
- removing readiness-by-empty-output-file conventions
- keeping real output files and logs only when they are actual products

### Crawl extension config

In:

- [`abx_plugins/plugins/twocaptcha/on_CrawlSetup__95_twocaptcha_config.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/twocaptcha/on_CrawlSetup__95_twocaptcha_config.js)
- [`abx_plugins/plugins/claudechrome/on_CrawlSetup__96_claudechrome_config.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/claudechrome/on_CrawlSetup__96_claudechrome_config.js)

remove:

- `.twocaptcha_configured`
- `.claudechrome_configured`

These hooks should simply run inside the `Setup` group after `CrawlSetupChromeStartReady`.

## Rollout Order

### Phase 1: Runtime support in `abx-dl`

1. add grouped hook filename parsing
2. add generic group tracking and `<Root><Group>Ready` emission
3. make grouped bg hooks settle on first stdout line
4. add `CrawlSetupReady` handoff to snapshot execution
5. keep terminal `SnapshotCompleted` / `CrawlCompleted` after internal cleanup

### Phase 2: Chrome pipeline migration

1. rename/delete Chrome wait hooks
2. move crawl setup config hooks into grouped setup flow
3. move snapshot Chrome bootstrap into grouped flow
4. move all true pre-nav hooks into `PreNav`
5. move `chrome_navigate` onto `SnapshotPreNavReady`
6. move screenshot/pdf/dom/title/etc. onto `SnapshotNavigateReady`
7. remove `prenav.json` and other orchestration-only marker files

### Phase 3: Optional later stage grouping

Only after the producer sets are explicit:

1. define `TextExtract`
2. define `Parse`
3. define `Index`
4. define `Finalize`
5. move only the hooks that truly participate in those barriers

## Regression Tests To Add

### `abx-dl`

- grouped fg hooks cause `<Root><Group>Ready` only after exit
- grouped bg hooks cause `<Root><Group>Ready` only after first stdout line, not merely process start
- `SnapshotPreNavReady` membership is discovered purely from filenames
- `SnapshotCompleted` is emitted only after grouped bg hooks have been cleaned up
- `CrawlSetupReady` can start snapshot execution without any plugin-name special cases

### `abx-plugins`

- pre-nav hooks emit a ready line only after listeners are attached
- `chrome_navigate` no longer polls `prenav.json`
- screenshot/pdf/dom/title still work when launched directly with explicit `CDP_URL` / `TARGET_ID` and `--url`
- crawl config hooks succeed without `.configured` marker files

## Repo Summary

### `abx-dl` changes

- extend hook discovery in [`../abx-dl/abx_dl/models.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/models.py) to parse `target_group`
- add generic group settle tracking in [`../abx-dl/abx_dl/services/crawl_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/crawl_service.py) and [`../abx-dl/abx_dl/services/snapshot_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/snapshot_service.py)
- keep using [`../abx-dl/abx_dl/services/process_service.py`](/Users/squash/Local/Code/archiveboxes/new/abx-dl/abx_dl/services/process_service.py) stdout lines as the generic bg ready signal surface
- emit identifier-safe synthetic `Ready` events with `BaseEvent(event_type=...)`
- keep `Completed` events terminal-only

### `abx-plugins` changes

- rename hooks into grouped scheduler filenames where barriers matter
- delete Chrome wait hooks
- remove `prenav.json` and `.configured` marker file control-plane logic
- add a tiny shared `signal_ready()` helper in [`abx_plugins/plugins/base/utils.js`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/base/utils.js) and [`abx_plugins/plugins/base/utils.py`](/Users/squash/Local/Code/archiveboxes/new/abx-plugins/abx_plugins/plugins/base/utils.py)
- keep standalone hooks self-gating on canonical files/artifacts

### `archivebox` changes

- no plugin-name-specific scheduler knowledge should be added there
- if ArchiveBox consumes discovered URLs, it should prefer `UrlDiscovered` records rather than expecting parser hooks to emit nested `Snapshot` records
- snapshot/crawl lifecycle integration should consume `CrawlSetupReady`, `SnapshotCompleted`, and `CrawlCompleted` instead of hand-maintained wait hooks
