# ArchiveBox Desktop prototype

Self-contained ARM64 macOS app using Apple's **unmodified Container 1.4.1 binaries**,
a bundled Linux kernel, bundled guest init, and the published ArchiveBox OCI image.
No Docker, OrbStack, Homebrew, global CLI install, or manual Linux setup is needed.

## Run

Open `dist/ArchiveBox.app`. First launch imports the bundled images, starts the VM,
and opens the Archive tab. The Settings tab is also available through
ArchiveBox → Settings… (Cmd-comma). It shows live container state, CPU usage,
RAM usage, process count, and the collection's allocated disk usage and absolute
path, with an Open in Finder button. Resource statistics update about every five
seconds while Settings is visible; disk usage refreshes every 30 seconds and on demand.

Choose Connect in Settings to open the embedded SwiftTerm terminal. It opens a
real interactive shell inside the container as the image's ArchiveBox user in
`/data`. For initial account creation, run:

```bash
archivebox manage createsuperuser
```

Terminal input/output is not written to the launcher log. Sessions and the web
page remain intact when switching tabs. Cmd-1 selects Archive, Cmd-2 selects
Settings, and Cmd-3 opens the web admin. The View menu also opens the data folder.
Closing the window or quitting stops the
container and its runtime. Reopening keeps the collection and account.

Requires Apple silicon and macOS 26+. Tested locally on macOS 27.0.
The local prototype is ad-hoc signed; distribution signing and notarization are
not done. This is not yet a public release.

## Build

With Xcode's Swift toolchain installed:

```bash
bash prepare.sh
bash build.sh
```

An optional first argument to `build.sh` selects a different output `.app` path,
so a new build can be staged without replacing a running app. The build pins
SwiftTerm 1.19.0 with SwiftPM. It uses SwiftPM's native build backend and bundles
SwiftTerm's shader source, avoiding a separate Metal toolchain download.

Preparation downloads Apple's signed package and extracts it without installing
anything in `/usr/local`. It temporarily starts the runtime in `.runtime`, pulls
the pinned ARM64 ArchiveBox image and guest init, and exports them into the bundle.
The normal app imports those local resources automatically.

Pinned ArchiveBox index digest:
`sha256:26cf885e6ea791df15147cad4e07cc390d552926108bfcb5b827da5ffe5aad96`

ARM64 manifest digest:
`sha256:af6b75a1bef801c4caa8c5661fece5a8fcff044b1e83da31b123f43ec677bbe8`

## Storage and lifecycle

- Collection: `~/Library/Application Support/ArchiveBox Desktop/data`
- Runtime: `~/Library/Application Support/ArchiveBox Desktop/runtime`
- Launcher logs: `~/Library/Application Support/ArchiveBox Desktop/desktop.log`
- Web address: `http://localhost:5797`; host forwarding binds to `127.0.0.1`.
- VM budget: 4 CPUs / 4 GiB as an initial working configuration, not a measured minimum.

The app bundle stays immutable; imports and captured data live outside it.
The current container is `archivebox-desktop-5797`, with host and guest both using
port 5797. A stopped legacy `archivebox-desktop` container is retained; the new
container reuses the same collection. Quit the previous prototype before opening
this version. Current image unpacks to approximately 2 GiB. Size optimization is deferred.

## Known prototype limitations

- Apple's stock CLI uses shared `com.apple.container.*` launchd service names.
  This prototype refuses to take over a different running installation. Do not
  manage unrelated containers with this app's runtime: quitting stops that runtime.
- Port 5797 is fixed. Port conflicts are reported in the startup error/log.
- No image upgrade/migration UI, crash recovery UI, or notarized release yet.
- No minimum-memory benchmark or macOS 26 acceptance test yet.
- The runtime exposes running/stopped state but no exit reason. A container that
  disappears after startup is labelled “Crashed / stopped unexpectedly”; this does
  not assert that an external stop was a crash. Unavailable metrics show a dash.
- CPU uses differences between cumulative runtime samples (100% = one core).
  RAM is the runtime's container memory accounting, not total host VM overhead.
- Full offline first-launch acceptance still needs a network-isolated test,
  although the kernel and both OCI images are bundled and imported locally.

## Reuse decisions

- Apple Container: https://github.com/apple/container — Apache 2.0; ships the
  OCI handling, VM lifecycle, networking, guest init integration, and launchd management.
- SwiftTerm: https://github.com/migueldeicaza/SwiftTerm — MIT; supplies the native
  terminal emulator and host PTY. The container CLI provides the guest TTY.
- MacLinuxKit: https://github.com/jankammerath/MacLinuxKit — relevant self-contained
  app example, but an early proof of concept requiring a separate LinuxKit image build.
- Contained: https://github.com/tdeverx/contained-app — useful desktop packaging
  reference, but a UI for the Container CLI rather than a ready-made ArchiveBox appliance.

The only original runtime glue is subprocess orchestration and a small AppKit/WKWebView
window. No custom hypervisor, Virtio driver, disk-image implementation, or OCI parser.


## Integrating into the official app

Read [HANDOFF.md](HANDOFF.md) for the complete technical handoff and proposed
optional “Download ArchiveBox Toolset” flow, including progress, local connection
selection, runtime ownership and the limits of the existing acceptance evidence.
