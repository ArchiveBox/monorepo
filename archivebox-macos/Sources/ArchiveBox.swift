import AppKit
import WebKit
import SwiftUI

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSToolbarDelegate {
    let runtime = Runtime()
    var window: NSWindow!
    var web: WKWebView!
    var status: NSTextField!
    var archiveView: NSView!
    var settingsView: NSHostingView<SettingsView>!
    var settings: SettingsModel!
    var tabs: NSSegmentedControl!
    var startup: Task<Void, Never>?

    func applicationDidFinishLaunching(_ notification: Notification) {
        settings = SettingsModel(runtime: runtime)
        let menu = NSMenu()
        let item = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "Settings…", action: #selector(showSettings), keyEquivalent: ",")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit ArchiveBox", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        item.submenu = appMenu
        menu.addItem(item)
        let viewItem = NSMenuItem(title: "View", action: nil, keyEquivalent: "")
        let viewMenu = NSMenu(title: "View")
        viewMenu.addItem(withTitle: "Archive", action: #selector(showArchive), keyEquivalent: "1")
        viewMenu.addItem(withTitle: "Settings", action: #selector(showSettings), keyEquivalent: "2")
        viewMenu.addItem(withTitle: "Admin", action: #selector(showAdmin), keyEquivalent: "3")
        viewMenu.addItem(withTitle: "Back", action: #selector(goBack), keyEquivalent: "[")
        viewMenu.addItem(withTitle: "Reload", action: #selector(reload), keyEquivalent: "r")
        viewMenu.addItem(withTitle: "Open Data Folder", action: #selector(openData), keyEquivalent: "")
        viewItem.submenu = viewMenu
        menu.addItem(viewItem)
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let editMenu = NSMenu(title: "Edit")
        editMenu.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = editMenu
        menu.addItem(editItem)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1180, height: 850),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "ArchiveBox"
        window.minSize = NSSize(width: 820, height: 760)
        window.toolbarStyle = .unified
        let toolbar = NSToolbar(identifier: "Navigation")
        toolbar.delegate = self
        toolbar.displayMode = .iconOnly
        toolbar.centeredItemIdentifiers = [.init("tabs")]
        window.toolbar = toolbar
        window.center()
        archiveView = NSView(frame: window.contentView!.bounds)
        archiveView.autoresizingMask = [.width, .height]
        web = WKWebView(frame: archiveView.bounds)
        web.autoresizingMask = [.width, .height]
        web.isHidden = true
        archiveView.addSubview(web)
        status = NSTextField(wrappingLabelWithString: "Starting ArchiveBox…")
        status.frame = NSRect(x: 32, y: 40, width: 1100, height: 700)
        status.autoresizingMask = [.width, .height]
        status.font = .systemFont(ofSize: 18)
        archiveView.addSubview(status)
        settingsView = NSHostingView(rootView: SettingsView(model: settings))
        window.contentView = archiveView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startup = Task {
            do {
                try await Task.detached { [runtime] in
                    try await runtime.start { text in
                        Task { @MainActor in self.status.stringValue = text }
                    }
                }.value
                settings.didStart()
                status.isHidden = true
                web.isHidden = false
                web.load(URLRequest(url: runtime.address))
            } catch {
                settings.didStart(error: error.localizedDescription)
                status.stringValue = "ArchiveBox could not start.\n\n\(error.localizedDescription)\n\nLog: \(runtime.home.appendingPathComponent("desktop.log").path)"
            }
        }
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] { [.flexibleSpace, .init("tabs")] }
    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] { [.flexibleSpace, .init("tabs"), .flexibleSpace] }
    func toolbar(_ toolbar: NSToolbar, itemForItemIdentifier id: NSToolbarItem.Identifier, willBeInsertedIntoToolbar: Bool) -> NSToolbarItem? {
        guard id.rawValue == "tabs" else { return nil }
        let item = NSToolbarItem(itemIdentifier: id)
        tabs = NSSegmentedControl(labels: ["Archive", "Settings"], trackingMode: .selectOne, target: self, action: #selector(changeTab))
        tabs.segmentStyle = .automatic
        tabs.selectedSegment = 0
        tabs.setWidth(115, forSegment: 0)
        tabs.setWidth(115, forSegment: 1)
        item.view = tabs
        item.label = "Screen"
        return item
    }

    func selectTab(_ index: Int) {
        tabs.selectedSegment = index
        let size = window.contentView!.frame.size
        let view: NSView = index == 0 ? archiveView : settingsView
        view.frame = NSRect(origin: .zero, size: size)
        window.contentView = view
        if index == 1 { settings.monitor() } else { settings.pauseMonitoring() }
    }
    @objc func changeTab() { selectTab(tabs.selectedSegment) }
    @objc func showArchive() { selectTab(0) }
    @objc func showSettings() { selectTab(1); window.makeKeyAndOrderFront(nil) }
    @objc func showAdmin() { selectTab(0); web.load(URLRequest(url: runtime.address.appendingPathComponent("admin/"))) }
    @objc func goBack() { web.goBack() }
    @objc func reload() { web.reload() }
    @objc func openData() { NSWorkspace.shared.open(runtime.home.appendingPathComponent("data")) }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        settings.shutdown()
        Task {
            await startup?.value
            await Task.detached { [runtime] in runtime.stop() }.value
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}

@main
struct ArchiveBoxMain {
    @MainActor static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
    }
}
