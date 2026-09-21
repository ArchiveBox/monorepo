#!/bin/bash
# Build-machine preparation only. End users receive the completed app bundle.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p vendor payload
version=1.4.1
image='archivebox/archivebox@sha256:26cf885e6ea791df15147cad4e07cc390d552926108bfcb5b827da5ffe5aad96'
if [[ ! -d vendor/package ]]; then
    curl -fL "https://github.com/apple/container/releases/download/$version/container-$version-installer-signed.pkg" -o vendor/container.pkg
    pkgutil --check-signature vendor/container.pkg
    pkgutil --expand-full vendor/container.pkg vendor/package
fi
mkdir -p vendor/container
curl -fsSL "https://raw.githubusercontent.com/apple/container/$version/LICENSE" -o vendor/container/LICENSE
cli="$PWD/vendor/package/Payload/bin/container"
# The stock runtime uses shared launchd labels. Never take over another service.
if launchctl list com.apple.container.apiserver >/dev/null 2>&1; then
    echo 'An Apple Container service is registered. Stop it before preparing the bundle.' >&2
    exit 1
fi
trap '"$cli" system stop' EXIT
"$cli" system start --app-root "$PWD/.runtime" --install-root "$PWD/vendor/package/Payload" --enable-kernel-install
"$cli" image pull --arch arm64 "$image"
"$cli" image tag "$image" archivebox/archivebox:dev
"$cli" image pull --arch arm64 ghcr.io/apple/containerization/vminit:0.45.0
"$cli" image save --arch arm64 -o "$PWD/payload/images.tar" archivebox/archivebox:dev ghcr.io/apple/containerization/vminit:0.45.0
cp .runtime/kernels/vmlinux-6.18.35-197-debug payload/vmlinux
