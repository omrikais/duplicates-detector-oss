// Sources/Bridge/MenuBarManager.swift
import AppKit

/// Manages an NSStatusItem in the macOS menu bar, showing aggregated watch-mode
/// stats and per-session controls. Provides icon state (outline/filled) based on
/// whether duplicates have been found.
@MainActor final class MenuBarManager {

    // MARK: - State

    private var statusItem: NSStatusItem?
    private var menuTarget: MenuTarget?

    private(set) var isActive = false
    private(set) var lastDuplicates = 0
    private(set) var lastTrackedFiles = 0

    // MARK: - Callbacks

    var onStopWatch: (() -> Void)?
    var onShowWindow: (() -> Void)?

    // MARK: - Session Items

    struct SessionMenuItem: Sendable {
        let id: UUID
        let label: String
    }

    private var sessionItems: [SessionMenuItem] = []

    /// Retained references for in-place title updates (avoids full menu rebuild on stats tick).
    private var trackedFilesItem: NSMenuItem?
    private var duplicatesItem: NSMenuItem?

    // MARK: - Lifecycle

    func activate() {
        guard statusItem == nil else { return }

        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = item.button {
            button.image = NSImage(
                systemSymbolName: "eye",
                accessibilityDescription: "Watching for duplicates"
            )
        }

        let target = MenuTarget()
        target.onStop = { [weak self] in self?.onStopWatch?() }
        target.onShow = { [weak self] in
            self?.onShowWindow?()
        }
        self.statusItem = item
        self.menuTarget = target
        self.isActive = true
        rebuildMenu()
    }

    func deactivate() {
        if let item = statusItem {
            NSStatusBar.system.removeStatusItem(item)
        }
        statusItem = nil
        menuTarget = nil
        isActive = false
        lastDuplicates = 0
        lastTrackedFiles = 0
        sessionItems = []
        trackedFilesItem = nil
        duplicatesItem = nil
    }

    // MARK: - Updates

    func updateStats(duplicates: Int, trackedFiles: Int) {
        lastDuplicates = duplicates
        lastTrackedFiles = trackedFiles

        if let button = statusItem?.button {
            let symbolName = duplicates > 0 ? "eye.fill" : "eye"
            button.image = NSImage(
                systemSymbolName: symbolName,
                accessibilityDescription: "Watching for duplicates"
            )
        }

        // Update existing menu items in-place when possible (avoids full
        // menu rebuild on each 2-second stats refresh).
        if let item = trackedFilesItem {
            item.title = "\(trackedFiles) files tracked"
            duplicatesItem?.title = "\(duplicates) duplicates found"
        } else {
            rebuildMenu()
        }
    }

    func updateSessions(_ sessions: [SessionMenuItem]) {
        self.sessionItems = sessions
        rebuildMenu()
    }

    // MARK: - Menu Construction

    private func rebuildMenu() {
        guard let target = menuTarget else { return }
        let menu = NSMenu()

        // Stats (disabled info items) — retained for in-place updates
        let statsItem = NSMenuItem(
            title: "\(lastTrackedFiles) files tracked",
            action: nil,
            keyEquivalent: ""
        )
        statsItem.isEnabled = false
        menu.addItem(statsItem)
        self.trackedFilesItem = statsItem

        let dupsItem = NSMenuItem(
            title: "\(lastDuplicates) duplicates found",
            action: nil,
            keyEquivalent: ""
        )
        dupsItem.isEnabled = false
        menu.addItem(dupsItem)
        self.duplicatesItem = dupsItem

        // Per-session info items (disabled labels)
        if !sessionItems.isEmpty {
            menu.addItem(.separator())
            for session in sessionItems {
                let item = NSMenuItem(
                    title: session.label,
                    action: nil,
                    keyEquivalent: ""
                )
                item.isEnabled = false
                menu.addItem(item)
            }
        }

        menu.addItem(.separator())

        // Stop All
        let stopAll = NSMenuItem(
            title: "Stop All",
            action: #selector(MenuTarget.handleStop),
            keyEquivalent: ""
        )
        stopAll.target = target
        menu.addItem(stopAll)

        // Show Window
        let show = NSMenuItem(
            title: "Show Window",
            action: #selector(MenuTarget.handleShow),
            keyEquivalent: ""
        )
        show.target = target
        menu.addItem(show)

        statusItem?.menu = menu
    }

    // MARK: - Target-Action Bridge

    /// NSObject subclass bridging AppKit target-action to Swift closures.
    private class MenuTarget: NSObject {
        var onStop: (() -> Void)?
        var onShow: (() -> Void)?

        @objc func handleStop() { onStop?() }
        @objc func handleShow() { onShow?() }
    }
}
