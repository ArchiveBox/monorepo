// swift-tools-version: 6.0
import PackageDescription
let package = Package(
    name: "ArchiveBoxDesktop",
    platforms: [.macOS(.v15)],
    dependencies: [.package(url: "https://github.com/migueldeicaza/SwiftTerm.git", exact: "1.19.0")],
    targets: [.executableTarget(name: "ArchiveBox", dependencies: [.product(name: "SwiftTerm", package: "SwiftTerm")], path: "Sources")],
    swiftLanguageModes: [.v5]
)
