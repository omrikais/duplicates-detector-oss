// Tests/MenuBarManagerTests.swift
import Testing
import Foundation
@testable import DuplicatesDetector

@Suite("MenuBarManager")
struct MenuBarManagerTests {

    @MainActor
    @Test("activate creates status item")
    func activateCreatesItem() {
        let manager = MenuBarManager()
        #expect(!manager.isActive)
        manager.activate()
        #expect(manager.isActive)
        manager.deactivate()
        #expect(!manager.isActive)
    }

    @MainActor
    @Test("updateStats updates stored values")
    func updateStats() {
        let manager = MenuBarManager()
        manager.activate()
        manager.updateStats(duplicates: 5, trackedFiles: 100)
        #expect(manager.lastDuplicates == 5)
        #expect(manager.lastTrackedFiles == 100)
        manager.deactivate()
    }

    @MainActor
    @Test("deactivate is idempotent")
    func deactivateIdempotent() {
        let manager = MenuBarManager()
        manager.deactivate()  // Should not crash
        manager.activate()
        manager.deactivate()
        manager.deactivate()  // Should not crash
        #expect(!manager.isActive)
    }

    @MainActor
    @Test("callbacks are wired")
    func callbacksWired() {
        let manager = MenuBarManager()
        var stopCalled = false
        var showCalled = false
        manager.onStopWatch = { stopCalled = true }
        manager.onShowWindow = { showCalled = true }
        manager.onStopWatch?()
        manager.onShowWindow?()
        #expect(stopCalled)
        #expect(showCalled)
    }
}
