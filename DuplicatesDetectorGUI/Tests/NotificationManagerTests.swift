import Testing
import Foundation
@testable import DuplicatesDetector

@Suite("NotificationManager")
struct NotificationManagerTests {

    @Test("coalescing groups alerts within quiet window per session")
    func coalescingLogic() async {
        let manager = WatchNotificationManager()
        let sid = UUID()
        let alert1 = DuplicateAlert(
            newFile: URL(filePath: "/a.mp4"), matchedFile: URL(filePath: "/b.mp4"),
            score: 80, detail: [:], timestamp: .now, sessionID: sid,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        let alert2 = DuplicateAlert(
            newFile: URL(filePath: "/c.mp4"), matchedFile: URL(filePath: "/d.mp4"),
            score: 90, detail: [:], timestamp: .now, sessionID: sid,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        await manager.scheduleDuplicateAlert(alert1)
        await manager.scheduleDuplicateAlert(alert2)
        let pending = await manager.pendingAlerts
        #expect(pending[sid]?.count == 2)
    }

    @Test("flush clears pending alerts")
    func flushClearsPending() async {
        let manager = WatchNotificationManager()
        let alert = DuplicateAlert(
            newFile: URL(filePath: "/a.mp4"), matchedFile: URL(filePath: "/b.mp4"),
            score: 80, detail: [:], timestamp: .now, sessionID: UUID(),
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        await manager.scheduleDuplicateAlert(alert)
        await manager.flush()
        let pending = await manager.pendingAlerts
        #expect(pending.isEmpty)
    }

    @Test("single notification content formatting")
    func singleNotificationContent() {
        let alert = DuplicateAlert(
            newFile: URL(filePath: "/path/to/video_copy.mp4"),
            matchedFile: URL(filePath: "/path/to/video.mp4"),
            score: 85, detail: [:], timestamp: .now, sessionID: UUID(),
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        let (title, body) = WatchNotificationManager.formatNotification(alerts: [alert])
        #expect(title == "Duplicate Found (85%)")
        #expect(body == "video_copy.mp4 matches video.mp4")
    }

    @Test("batch notification content formatting")
    func batchNotificationContent() {
        let alerts = (0..<3).map { i in
            DuplicateAlert(
                newFile: URL(filePath: "/path/to/file\(i).mp4"),
                matchedFile: URL(filePath: "/path/to/orig\(i).mp4"),
                score: 80 + i, detail: [:], timestamp: .now, sessionID: UUID(),
                newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
            )
        }
        let (title, body) = WatchNotificationManager.formatNotification(alerts: alerts)
        #expect(title == "3 Duplicates Detected")
        #expect(body.contains("file0.mp4"))
        #expect(body.contains("2 other files"))
    }

    @Test("sessionID extracted from alert batch for notification routing")
    func sessionIDFromAlerts() {
        let sid = UUID()
        let alerts = [
            DuplicateAlert(
                newFile: URL(filePath: "/a.mp4"), matchedFile: URL(filePath: "/b.mp4"),
                score: 80, detail: [:], timestamp: .now, sessionID: sid,
                newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
            ),
            DuplicateAlert(
                newFile: URL(filePath: "/c.mp4"), matchedFile: URL(filePath: "/d.mp4"),
                score: 90, detail: [:], timestamp: .now, sessionID: sid,
                newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
            ),
        ]
        let userInfo = WatchNotificationManager.notificationUserInfo(alerts: alerts)
        #expect(userInfo["sessionID"] as? String == sid.uuidString)
    }

    // MARK: - Per-session coalescing

    @Test("alerts from different sessions are coalesced independently")
    func perSessionCoalescing() async {
        let manager = WatchNotificationManager()
        let sessionA = UUID()
        let sessionB = UUID()

        let alertA = DuplicateAlert(
            newFile: URL(filePath: "/a.mp4"), matchedFile: URL(filePath: "/b.mp4"),
            score: 80, detail: [:], timestamp: .now, sessionID: sessionA,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        let alertB = DuplicateAlert(
            newFile: URL(filePath: "/c.mp4"), matchedFile: URL(filePath: "/d.mp4"),
            score: 90, detail: [:], timestamp: .now, sessionID: sessionB,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )

        await manager.scheduleDuplicateAlert(alertA)
        await manager.scheduleDuplicateAlert(alertB)

        let pending = await manager.pendingAlerts
        // Both sessions should have their own pending entry
        #expect(pending.count == 2)
        #expect(pending[sessionA]?.count == 1)
        #expect(pending[sessionB]?.count == 1)
    }

    @Test("flush delivers alerts from all sessions and clears pending")
    func flushDeliversPerSession() async {
        let manager = WatchNotificationManager()
        let sessionA = UUID()
        let sessionB = UUID()

        let alertA1 = DuplicateAlert(
            newFile: URL(filePath: "/a1.mp4"), matchedFile: URL(filePath: "/b1.mp4"),
            score: 80, detail: [:], timestamp: .now, sessionID: sessionA,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        let alertA2 = DuplicateAlert(
            newFile: URL(filePath: "/a2.mp4"), matchedFile: URL(filePath: "/b2.mp4"),
            score: 85, detail: [:], timestamp: .now, sessionID: sessionA,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )
        let alertB1 = DuplicateAlert(
            newFile: URL(filePath: "/c1.mp4"), matchedFile: URL(filePath: "/d1.mp4"),
            score: 90, detail: [:], timestamp: .now, sessionID: sessionB,
            newMetadata: FileMetadata(fileSize: 0), matchedMetadata: FileMetadata(fileSize: 0)
        )

        await manager.scheduleDuplicateAlert(alertA1)
        await manager.scheduleDuplicateAlert(alertA2)
        await manager.scheduleDuplicateAlert(alertB1)

        // Verify both sessions have pending alerts before flush
        let prePending = await manager.pendingAlerts
        #expect(prePending[sessionA]?.count == 2)
        #expect(prePending[sessionB]?.count == 1)

        await manager.flush()

        // After flush, all pending alerts should be cleared
        let postPending = await manager.pendingAlerts
        #expect(postPending.isEmpty)
    }
}
