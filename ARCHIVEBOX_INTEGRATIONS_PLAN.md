# Official ArchiveBox integrations plan

Research date: 2026-09-20. Planning only: no integrations implemented or marketplace submissions made. Platform requirements below come from current official documentation; product choices are recommendations. “Official” means maintained by ArchiveBox, with marketplace approval tracked separately.

## Recommendation

**Primary objective: ArchiveBox brand reach through useful, publicly discoverable marketplace listings.** A working private connector, GitHub package, or setup guide alone does not count as shipped. Optimize for installable listings whose two core actions work inside the host app; deeper features come after listing readiness.

Package server-side integration handlers as bundled `abx-plugins`, reusing ArchiveBox's existing operations and REST API. Pursue **n8n verification as the quickest listing milestone**, then prove **Claude's direct per-customer directory connection** and the **Google no-relay options**. Slack and standard ChatGPT listing require an explicit decision to operate shared infrastructure; they are not merely plugin-packaging work. Put WhatsApp last because no equivalent plugin marketplace route was verified. This is a recommended release strategy, not a forecast of audience size or guaranteed approval.

**Packaging revision:** no dedicated integrations repository or separately installed server-side clients by default. Extend the existing plugin contract with optional `urls.py`/`views.py`, imported only by ArchiveBox, and one generic namespaced route loader. Keep ordinary hooks and `abx-dl` free of Django imports/dependencies. This is new capability: current plugin discovery does not mount URL modules, and the existing framework-neutral contract must explicitly allow this optional ArchiveBox web surface.

There is already precedent for plugin-owned web behavior: OpenCode owns runtime/proxy logic and templates while `archivebox/opencode` supplies Django routes/authentication; ArchiveWeb.page owns replay helpers called by core views/static serving; Sonic supplies search commands and daemon behavior behind ArchiveBox's search interface. Reuse these boundaries. The proposed change is to make route registration generic, not invent plugin-backed web integrations. Moving these existing integrations is outside this plan's scope.

Bundle official integration plugins and enable their routes by default; account linking activates external actions and subscriptions. Mount routes on the application/API origin, never the archived-content origin. Reuse existing permission checks and operations; do not duplicate add/search implementations. Keep integration routes separate from per-crawl extractor selection. n8n's npm node and marketplace manifests remain required distribution artifacts and can be maintained alongside the plugin code.

**Unresolved architectural decision: will ArchiveBox operate a shared public integration service?** Bundling plugins does not resolve this. Distinguish marketplace requirements from our design choices:

| Platform | Need an ArchiveBox-operated shared service? |
| --- | --- |
| n8n | No. The installed node can call the configured ArchiveBox server directly. |
| Slack | Yes, shared ingress for one official app: events, commands, and interactions arrive at app-configured URLs. Per-installation routing is our responsibility. |
| ChatGPT | Yes for the standard universal-URL listing. Direct customer URL templates need explicit OpenAI approval; arbitrary self-hosted domains are not established as accepted. |
| Claude | Not inherently. Directory listings support per-customer URL patterns with OAuth. Validate arbitrary-domain review acceptance and implement compatible server-local auth before committing to this route. |
| Sheets | An Editor add-on's HTML sidebar can make HTTPS browser requests directly. Validate token-authenticated CORS/preflight and public review; browser-only sync needs the sidebar open. No ArchiveBox relay is inherently required. |
| Drive | The chosen HTTP/card design uses shared hosting. Native Workspace cards cannot run custom browser JavaScript. Apps Script can call known allowlisted servers, but one published add-on accepting arbitrary domains without a relay remains unresolved. |
| WhatsApp | Message/group callbacks can be overridden per institution/number; a shared message relay is optional. App-level events and safe webhook authentication still need a hosting design. |

Sources: [Slack routing](https://docs.slack.dev/apis/events-api/using-http-request-urls/), [OpenAI URL types](https://developers.openai.com/plugins/deploy/submission), [Claude per-customer URLs](https://claude.com/docs/connectors/building/authentication), [Google browser requests](https://developers.google.com/apps-script/guides/html/restrictions), [Google interface restrictions](https://developers.google.com/workspace/add-ons/guides/workspace-restrictions), [Google fetch allowlists](https://developers.google.com/apps-script/manifest/allowlist-url), [WhatsApp overrides](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/override).

A broker is a maintained multi-tenant service, not just DNS or a redirect. It needs verified installation-to-server mappings, scoped credentials or signed forwarding, revocation, platform request verification, abuse controls, and delivery handling. Requests and search results pass through it; avoiding permanent content storage does not remove that trust boundary. It must not distribute publisher-wide signing secrets to customer servers. A public broker cannot reach LAN-only servers without a separately designed outbound connection/tunnel. Keep this decision open; do not quietly make all integrations depend on it.

| App | Useful listing MVP | Distribution milestone |
| --- | --- | --- |
| Google Sheets | Submit rows, search/import results, manual bidirectional tag/status sync | Approved Google Workspace Marketplace listing |
| Google Drive | Add/search sidebar in the same add-on | Same listing, configured and demonstrated for Drive too |
| Slack | Archive-message shortcut, search/recent cards, opt-in notices | Approved Slack Marketplace listing after eligibility pilot |
| WhatsApp | Institution-owned number; URL intake and search in DMs | No equivalent verified listing route: defer substantial investment |
| n8n | ArchiveBox node + ready-to-use workflows | Verified node discoverable/installable in the node panel; public templates |
| Claude | Small remote MCP connector | Accepted Claude connector-directory listing |
| ChatGPT | MCP-backed plugin | Accepted OpenAI public plugin-directory listing |

**Distribution work is part of the product:** use ArchiveBox-owned publisher identities; recognizable name/icon; a clear “Archive web sources and search your collection” description; host-specific screenshots and examples; a working reviewer/demo archive; support/privacy/terms pages; and install links on ArchiveBox’s site/docs. Follow each store’s branding and review rules. Track submission status, listing URL, installs, successful account linking, and first successful archive/search without logging submitted URLs or queries. Acceptance is external: verify the actual approved listing before announcing availability.

**Setup target:** install → platform consent → ArchiveBox base URL + personal API key → ready. Institutions may prefill the server URL. Selecting a Sheet, export folder, or notification channel happens only when enabling that feature. One-time linking can open a secure setup page; everyday add/search/list stays inside the host app.

**Hosting tradeoff:** favor direct platform-to-server connections where supported. Any hosted broker requires a named operator, operational budget, retention/privacy policy, and a supported reachability model before implementation. Private-network support is additional setup, not automatically solved by a public URL. Direct OAuth can avoid API-key entry but requires server-side OAuth support; it is not provided merely by adding an MCP route.

## Existing API and narrowly scoped gaps

Inspected local `archivebox` on `dev`, commit `e03db54bca4633bd5933fa58802da245e477b8c3`; this is source inspection, not runtime acceptance or a guarantee about installed releases.

| Need | Already available |
| --- | --- |
| Submit URLs with tags | `POST /api/v1/cli/add`: `urls`, `tag`, background execution; returns crawl/snapshot IDs |
| Search/list/status | `GET /api/v1/core/snapshots`: search mode, tag, creator, status, modified-time filters, pagination; detail endpoint for one snapshot |
| Edit tags | `PATCH /api/v1/core/snapshot/{id}` and tag add/remove endpoints |
| Notifications | Existing outbound model webhooks; polling can avoid manual webhook setup |
| Local AI tools | Existing stdio MCP wrapper over CLI; six tools, including administrative operations and `shell` |

Source: [submission](archivebox/archivebox/api/v1_cli.py), [collection API](archivebox/archivebox/api/v1_core.py), [auth](archivebox/archivebox/api/auth.py), [token model](archivebox/archivebox/api/models.py), [webhooks](archivebox/archivebox/api/webhooks.py), [MCP implementation](archivebox/archivebox/mcp/server.py). The MCP README currently disagrees with the curated implementation; use code as the baseline.

Beyond the generic plugin route loader, keep core work to two focused workstreams, extending existing paths:

1. **Integration credentials and authorization — release prerequisite.** Current REST auth requires a superuser and tokens have no operation scopes. Add narrowly scoped per-user credentials for submit/read/tag-edit, denying administrative and unrelated routes. Enforce allowed snapshot access server-side for search, counts, details, tags, and downloads. Start with personal ownership and explicitly authorized shared collections; do not claim arbitrary matter-level ACLs. Creator/tag filters alone are not permissions. If institution isolation requires a larger permission model, defer that use case rather than hide the gap in a gateway filter.
2. **Reliable sync options — implement only as required.** Add stable `(modified_at, id)` cursor ordering and conditional tag writes to existing list/PATCH endpoints; ensure every tag mutation advances the version. Accept a scoped submission idempotency key on the existing add endpoint so a retried delivery cannot enqueue twice. These are proposals, not existing guarantees. Use periodic reconciliation for deletions; defer a durable change-log/tombstone service. Existing webhooks need delivery/authentication evaluation before relying on them for complete notifications.

Keep platform-specific handlers and connection logic in the integration plugins, with shared-installation routing/OAuth state at the official hosted entry point where required. Prefer polling initially; compare saved state to distinguish newly added URLs from capture completion. Never label “queued” or a terminal job with failed outputs as “successfully preserved.”

Direct Sheets browser access additionally needs narrowly scoped token-authenticated CORS/preflight support. Direct remote MCP needs standards-compliant OAuth support, preferably through a maintained library; do not misestimate that as a trivial route declaration. Resolve these feasibility items before committing to implementation scope.

## Google Sheets

**Product:** a sidebar with **Add URLs + tags**, **Search**, **Import results**, and **Sync this tab**. A managed table contains snapshot ID, URL, title, tags, submitter, capture status/time, and archive link. It serves legal matter registers, newsroom source lists, academic datasets, and personal reading lists.

**Bidirectional contract:** new approved rows submit URLs; stable snapshot IDs bind rows after submission. ArchiveBox owns capture facts; tags sync both ways using a last-synced baseline and explicit conflict resolution. Changing a captured URL creates a new submission. Deleting a row stops its sync, never deletes evidence. Deleted or newly inaccessible snapshots are marked unavailable. Notes/review columns stay local. Per-user views use authenticated ArchiveBox identity; a shared Sheet exposes exported rows to its collaborators.

**Build/setup:** first validate a no-relay Sheets Editor add-on using a browser sidebar and direct authenticated requests. Otherwise choose an HTTP-hosted Workspace add-on for Sheets and Drive only with the shared-service decision resolved. Start with **Sync now**; background submissions must have a designated owner, never silently impersonate another editor. Keep keys out of cells and document-shared configuration.

**Marketplace:** public listing review, appropriate OAuth verification, reviewer access, screenshots, privacy/support pages. HTTP hosting avoids the published Apps Script fetch-domain allowlist problem for arbitrary customer servers. Workspace add-ons do not provide generic `onEdit`/installable triggers; do not promise instant sync. [HTTP add-ons](https://developers.google.com/workspace/add-ons/guides/alternate-runtimes), [fetch allowlists](https://developers.google.com/apps-script/manifest/allowlist-url), [trigger limits](https://developers.google.com/workspace/add-ons/concepts/editor-triggers), [publication](https://developers.google.com/workspace/marketplace/how-to-publish).

## Google Drive

**Product:** the same add-on exposes **Add URL**, **Search/Recent**, and **Export selected captures** in Drive’s sidebar. Export existing PDF/screenshot artifacts plus a CSV/JSON index with original URL, capture time, and snapshot ID to a selected case/research folder. ArchiveBox remains canonical; Drive holds deliberately shared copies. Search results live in the sidebar, not Drive’s native search index.

**Build/setup:** reuse Google account linking; request access only to selected/created files (`drive.file`) where possible. Include Drive search/intake in the first Marketplace submission; do not delay that distribution for export features. Validate authenticated artifact download before exports. Users choose a folder only when exporting. Google supports Drive homepage/selection interfaces, but not Drive add-ons on mobile. [Drive surfaces](https://developers.google.com/workspace/add-ons/drive/building-drive-interfaces), [Drive support](https://developers.google.com/workspace/add-ons/drive), [scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

**Boundary:** submitting a private Google document URL does not transfer Google authorization to ArchiveBox. Private-document preservation needs an explicit Google export/download plus ArchiveBox file-ingestion workflow; defer it until validated. Never count an archived sign-in page as the document. A single Marketplace listing can cover both hosts. [Document export](https://developers.google.com/workspace/drive/api/guides/manage-downloads), [combined listing](https://developers.google.com/workspace/marketplace/list-multiple-app-integrations).

## Slack

**Product:** **Archive URL** message shortcut → URL/tags modal; `/archivebox` → Add/Search/Recent. Return private result cards by default. Add explicit `@ArchiveBox` requests later. Approved channels can receive new-URL notices, completion updates, or a digest. This supports team intake without copying Slack conversation history.

**Build/setup:** official OAuth app and shared HTTP service; begin with `commands` and `chat:write`, adding mention access only when implemented. Verify Slack request signatures, acknowledge promptly, and queue work. Bind each Slack user to their own ArchiveBox credentials; check guests/Slack Connect users and destination access. Channel tags organize work but do not establish confidentiality. [Interactivity](https://docs.slack.dev/interactivity/), [HTTP versus Socket Mode](https://docs.slack.dev/apis/events-api/comparing-http-socket-mode/).

**Marketplace gate:** Socket Mode apps cannot be listed. Prepare a fully working public pilot and target at least 10 active workspaces and 10 weekly active users before submission. Slack also flags shared third-party service accounts and message-backup apps as unsuitable: do not design around one shared administrator key or market this as Slack archiving. Include installation/uninstall flows, support/privacy pages, and reviewer access. [Marketplace requirements](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements/), [review process](https://docs.slack.dev/slack-marketplace/slack-marketplace-review-guide/).

## WhatsApp

**Product:** forward a URL or send `archive URL #tags` to an institution’s number; `search`, `recent`, and `status` return compact results. Useful for field reporters and external contributors: allow submit-only intake separately from internal collection search. Opted-in staff can receive digests. Verify account binding; possessing the phone number or joining a chat does not grant archive access.

**Build/setup:** use Meta’s official Cloud API through the shared service. Institution-owned numbers require business/number onboarding and billing beyond ArchiveBox URL + key. Embedded Signup can reduce this work. Supporting customer-owned WhatsApp accounts requires the Tech Provider/app-review route and appropriate advanced permissions. [Provider onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers).

**Limits/distribution:** no equivalent consumer plugin-marketplace route was verified; publish an official install page and messaging link, with partner-directory eligibility a separate possibility. Groups API now exists but requires an Official Business Account and supports at most eight participants; ordinary existing-group attachment and native `@mention` behavior remain unverified. Pilot DMs first, then eligible API-created groups. Proactive messages outside the customer-service window need approved templates and may incur per-recipient charges; support opt-out. [Groups](https://developers.facebook.com/documentation/business-messaging/whatsapp/groups), [policy](https://whatsappbusiness.com/policy/), [pricing](https://whatsappbusiness.com/products/platform-pricing/), [partner ecosystem](https://whatsappbusiness.com/partners/become-a-partner/).

## n8n

**Product:** official ArchiveBox node with **Submit URLs**, **Search**, **List/Get**, and **Edit tags**, plus a polling trigger for **URL added / capture finished**. Credentials are just base URL + API key. Ship templates for Sheet intake, Slack digests, research-feed archiving, and case-register updates using n8n’s existing nodes. Templates complement the native integrations; they are not a substitute for their public listings.

**Build/distribution:** publish `n8n-nodes-archivebox` under ArchiveBox ownership after checking for an existing package. Target verified status, not npm publication alone. Current verification calls for MIT licensing, TypeScript, no runtime dependencies or filesystem/environment access, and npm provenance through GitHub Actions. Use n8n’s credential/HTTP helpers; submit through its Creator Portal. Verification enables node-panel discovery in Cloud and self-hosted installations; templates need separate publication. Polling avoids public callbacks; local n8n can reach private ArchiveBox servers. [Verification](https://docs.n8n.io/connect/create-nodes/build-your-node/reference/verification-guidelines), [publication](https://docs.n8n.io/integrations/community-nodes/building-community-nodes/), [verified installation](https://docs.n8n.io/integrations/community-nodes/installation-and-management/install-verified-community-nodes/).

## Claude

**Product:** one small MCP interface: `add_urls`, `search_snapshots`, `list_snapshots`, `get_snapshot`. Example: “Save these reporting sources tagged election-2026” or “Find the captures used in this literature review.” Return real snapshot IDs, timestamps, capture status, and citations; retrieved content is untrusted data, not tool instructions.

**Build/distribution:** prioritize a thin REST-backed Streamable HTTP connector submitted to the public directory. Current submission requires a Team/Enterprise publisher organization with Directory access, tool metadata/annotations, docs/privacy information, and populated reviewer access. A Claude Code skill or manually installed MCP configuration does not fulfill this distribution goal. Reuse existing API behavior without exposing administrative `shell`/delete operations. [Directory submission](https://claude.com/docs/connectors/building/submission).

**Setup:** prefer direct customer-server URL + local OAuth using CIMD or DCR if the directory accepts the required URL pattern. This needs an OAuth-capable plugin as well as MCP transport; current API keys alone do not provide it. Static-header keys are an admin-configured organization-wide beta, not universal per-user linking. A shared OAuth service is a fallback only after an explicit hosting decision. [Authentication](https://claude.com/docs/connectors/building/authentication).

## ChatGPT

**Product:** reuse the same four-tool MCP adapter; optionally render searchable result cards with capture status and an **Archive these URLs** action. Useful for cited research and batch preservation from a discussion. Avoid uploading the whole collection or fetching archived text unless requested.

**Build/distribution:** target the current OpenAI plugin directory with a remote MCP server. Current documentation routes former Apps SDK material into Plugins. An authenticated MCP integration expects OAuth, not user-supplied custom API-key headers. Use OAuth to the shared service; enter the ArchiveBox key only on its secure linking form. A GPT with Actions can be a separate prototype, but is not the recommended public integration. [Authentication](https://developers.openai.com/plugins/build/auth).

**Marketplace gate:** submit a universal hosted MCP URL, verified publisher/domain information, reviewer access, privacy/support materials, and working flows. Customer-specific URL templates require OpenAI approval; do not assume a listing can simply ask for any self-hosted MCP URL. Private Secure MCP Tunnels are a separate admin-managed option and do not support public plugin submission. [Submission](https://developers.openai.com/plugins/deploy/submission), [private tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).

## Delivery and acceptance

1. **Listing prerequisites + first win:** establish publisher accounts and reviewer requirements; validate real API behavior and scoped access; ship the n8n node and submit for verification.
2. **Resolve direct distribution:** validate Claude customer-URL review/authentication and Sheets browser-side marketplace feasibility. Seek OpenAI template eligibility rather than assume it. Sharing the MCP implementation does not require sharing a hosted endpoint.
3. **Resolve shared-service ownership before dependent builds:** decide whether ArchiveBox will operate the broker needed for Slack and the standard ChatGPT route; document cost, trust, and networking boundaries. If proceeding, build useful MVPs, recruit Slack's eligibility pilot, and submit independently. Choose the combined Google HTTP listing only if its hosting model is accepted; otherwise retain a separate direct Sheets route.
4. **WhatsApp only after a distribution decision:** validate whether a partner listing or another concrete acquisition channel justifies the onboarding/operations cost. A DM pilot may establish demand; it does not satisfy the public-marketplace objective.

**Done means listed and working:** a public listing under ArchiveBox ownership, installation by a fresh eligible account, successful server connection, and both archive-with-tags and search/list inside the app. A submitted or review-pending listing remains incomplete. For n8n also verify node-panel discovery; for Google verify both host surfaces.

Each release must pass real host-app → real server → real archived output checks: add with tags; search/list and pagination; queued versus successful/failed capture; duplicate delivery; expired/revoked key; two users with different access; correct submitter; notification destination. Sheets additionally needs conflicting edits, row deletion, interrupted sync, and multiple editors. Avoid mocks and do not claim marketplace acceptance from local tests.

Across apps, present source URL, stable ID, capture timestamp/status, and available outputs. These support lawyers’ evidence registers, journalists’ source provenance, and academics’ reproducibility; they do not by themselves establish legal admissibility or cryptographic chain of custody. Do not expose confidential titles/URLs in shared channels, Sheets, or AI results beyond the explicitly authorized audience.
