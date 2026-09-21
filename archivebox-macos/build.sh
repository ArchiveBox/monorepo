#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
app="${1:-$PWD/dist/ArchiveBox.app}"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
ditto vendor/package/Payload "$app/Contents/Resources/runtime"
cp payload/images.tar payload/vmlinux "$app/Contents/Resources/"
cp vendor/container/LICENSE "$app/Contents/Resources/APPLE-CONTAINER-LICENSE"
swift build --build-system native -c release
cp .build/release/ArchiveBox "$app/Contents/MacOS/ArchiveBox"
ditto .build/release/SwiftTerm_SwiftTerm.bundle "$app/Contents/Resources/SwiftTerm_SwiftTerm.bundle"
cp .build/checkouts/SwiftTerm/LICENSE "$app/Contents/Resources/SWIFTTERM-LICENSE"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>io.archivebox.desktop</string>
<key>CFBundleName</key><string>ArchiveBox</string>
<key>CFBundleExecutable</key><string>ArchiveBox</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>26.0</string>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST
codesign --force --sign - "$app"
echo "$app"
