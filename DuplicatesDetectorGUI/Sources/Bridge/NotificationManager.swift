import Foundation
import UserNotifications

/// Manages macOS notifications for watch-mode duplicate detection with coalesced delivery.
///
/// Alerts are buffered for a 3-second quiet window before delivery. Each new alert resets the
/// timer, so rapid bursts of detections produce a single batch notification. Wraps
/// `UNUserNotificationCenter` and registers a `WATCH_DUPLICATE` category with a "Review"
/// foreground action. The app's `UNUserNotificationCenterDelegate` handles user taps for
/// deep-link routing — no in-process `NotificationCenter` post is needed.
actor WatchNotificationManager {

    // MARK: - Configuration

    /// Duration of the quiet window before delivering coalesced alerts.
    static let quietWindow: TimeInterval = 3.0

    /// Category identifier for watch duplicate notifications.
    static let categoryID = WatchNotificationConstants.categoryID

    /// Action identifier for the "Review" action on notifications.
    private static let reviewActionID = "REVIEW_ACTION"

    // MARK: - State

    /// Whether notification authorization has been granted.
    private(set) var isAuthorized: Bool = false

    /// Alerts waiting to be delivered, keyed by session ID.
    /// Each session coalesces independently so notifications route correctly.
    private(set) var pendingAlerts: [UUID: [DuplicateAlert]] = [:]

    /// Per-session coalescing timers — cancelled and recreated on each new alert.
    private var coalescingTasks: [UUID: Task<Void, Never>] = [:]

    // MARK: - Environment Detection

    /// Whether we are running inside XCTest (skip real UNUserNotificationCenter calls).
    private static var isTestEnvironment: Bool {
        ProcessInfo.processInfo.environment["XCTestBundlePath"] != nil
    }

    // MARK: - Authorization

    /// Requests notification authorization and registers the `WATCH_DUPLICATE` category.
    ///
    /// Safe to call multiple times — subsequent calls are no-ops if already authorized.
    /// Skips actual `UNUserNotificationCenter` calls in XCTest environments.
    func requestAuthorization() async {
        guard !Self.isTestEnvironment else { return }

        let center = UNUserNotificationCenter.current()

        // Register category with "Review" foreground action
        let reviewAction = UNNotificationAction(
            identifier: Self.reviewActionID,
            title: "Review",
            options: .foreground
        )
        let category = UNNotificationCategory(
            identifier: Self.categoryID,
            actions: [reviewAction],
            intentIdentifiers: [],
            options: []
        )
        center.setNotificationCategories([category])

        // Request authorization
        do {
            let granted = try await center.requestAuthorization(options: [.alert, .sound])
            isAuthorized = granted
        } catch {
            isAuthorized = false
        }
    }

    // MARK: - Coalesced Delivery

    /// Schedules a duplicate alert for coalesced delivery.
    ///
    /// Alerts are buffered per session and each session has its own quiet window timer.
    /// When a session's timer expires without new alerts, that session's buffered alerts
    /// are delivered as a single notification with the correct session ID for deep-linking.
    func scheduleDuplicateAlert(_ alert: DuplicateAlert) {
        let sid = alert.sessionID
        pendingAlerts[sid, default: []].append(alert)

        // Cancel existing timer for this session and start a new one
        coalescingTasks[sid]?.cancel()
        coalescingTasks[sid] = Task { [sid] in
            do {
                try await Task.sleep(for: .seconds(Self.quietWindow))
                deliverPendingAlerts(for: sid)
            } catch {
                // Task was cancelled — a new alert arrived and reset the timer
            }
        }
    }

    /// Immediately delivers all pending alerts and clears the buffer.
    ///
    /// Cancels all active coalescing timers and delivers one notification per session.
    func flush() {
        for (_, task) in coalescingTasks { task.cancel() }
        coalescingTasks.removeAll()
        guard !pendingAlerts.isEmpty else { return }
        let allPending = pendingAlerts
        pendingAlerts.removeAll()
        for (_, alerts) in allPending where !alerts.isEmpty {
            deliverBatch(alerts)
        }
    }

    // MARK: - Delivery

    /// Delivers buffered alerts for a specific session as a single notification.
    private func deliverPendingAlerts(for sessionID: UUID) {
        guard let alerts = pendingAlerts.removeValue(forKey: sessionID),
              !alerts.isEmpty else { return }
        coalescingTasks.removeValue(forKey: sessionID)
        deliverBatch(alerts)
    }

    /// Delivers a batch of alerts as a macOS system notification.
    ///
    /// Window activation is handled by `UNUserNotificationCenterDelegate` when the user
    /// taps the notification — no in-process `NotificationCenter` post is needed.
    private func deliverBatch(_ alerts: [DuplicateAlert]) {
        let (title, body) = Self.formatNotification(alerts: alerts)

        guard !Self.isTestEnvironment else { return }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = .default
        content.categoryIdentifier = Self.categoryID
        content.userInfo = Self.notificationUserInfo(alerts: alerts)

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil
        )
        UNUserNotificationCenter.current().add(request) { _ in }
    }

    // MARK: - Formatting (Static, Testable)

    /// Builds notification `userInfo` from a batch of alerts.
    ///
    /// Extracts the session UUID from the first alert so the notification tap handler
    /// can route to the correct watch session's results.
    nonisolated static func notificationUserInfo(alerts: [DuplicateAlert]) -> [String: Any] {
        guard let first = alerts.first else { return [:] }
        return [WatchNotificationConstants.sessionIDKey: first.sessionID.uuidString]
    }

    /// Formats notification content for a batch of alerts.
    ///
    /// - Single alert: "Duplicate Found (85%)" / "video_copy.mp4 matches video.mp4"
    /// - Batch: "3 Duplicates Detected" / "file0.mp4 and 2 other files match existing files"
    ///
    /// - Parameter alerts: One or more duplicate alerts to format.
    /// - Returns: A `(title, body)` tuple suitable for notification content.
    nonisolated static func formatNotification(alerts: [DuplicateAlert]) -> (title: String, body: String) {
        guard let first = alerts.first else {
            return (title: "No Duplicates", body: "")
        }

        if alerts.count == 1 {
            let newName = first.newFile.lastPathComponent
            let matchedName = first.matchedFile.lastPathComponent
            return (
                title: "Duplicate Found (\(first.score)%)",
                body: "\(newName) matches \(matchedName)"
            )
        } else {
            let firstName = first.newFile.lastPathComponent
            let otherCount = alerts.count - 1
            return (
                title: "\(alerts.count) Duplicates Detected",
                body: "\(firstName) and \(otherCount) other files match existing files"
            )
        }
    }
}
