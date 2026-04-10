import Foundation

/// Standalone formatting utilities, decoupled from any store.
enum DDFormatters {

    nonisolated static func formatFileSize(_ bytes: Int) -> String {
        let units = ["B", "KB", "MB", "GB", "TB"]
        var value = Double(bytes)
        var unitIndex = 0
        while value >= 1024 && unitIndex < units.count - 1 {
            value /= 1024
            unitIndex += 1
        }
        if unitIndex == 0 {
            return "\(bytes) B"
        }
        return String(format: "%.1f %@", value, units[unitIndex])
    }

    nonisolated static func formatDuration(_ seconds: Double) -> String {
        if seconds < 60 {
            return String(format: "%.1fs", seconds)
        }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        if mins < 60 {
            return String(format: "%d:%02d", mins, secs)
        }
        let hours = mins / 60
        let remainMins = mins % 60
        return String(format: "%d:%02d:%02d", hours, remainMins, secs)
    }

    nonisolated static func formatResolution(width: Int?, height: Int?) -> String? {
        guard let w = width, let h = height else { return nil }
        return "\(w)\u{00D7}\(h)"
    }

    nonisolated static func truncateMiddle(_ path: String, maxLength: Int = 50) -> String {
        guard path.count > maxLength else { return path }
        let half = (maxLength - 3) / 2
        let prefix = path.prefix(half)
        let suffix = path.suffix(half)
        return "\(prefix)\u{2026}\(suffix)"
    }

    nonisolated static func formatBitrate(_ bps: Int) -> String {
        if bps >= 1_000_000 {
            return String(format: "%.1f Mbps", Double(bps) / 1_000_000)
        }
        return String(format: "%d Kbps", bps / 1000)
    }

    nonisolated static func formatFramerate(_ fps: Double) -> String {
        String(format: "%.2f fps", fps)
    }

    nonisolated static func formatAudioChannels(_ count: Int) -> String {
        switch count {
        case 1: "mono"
        case 2: "stereo"
        case 6: "5.1"
        case 8: "7.1"
        default: "\(count) ch"
        }
    }

    private nonisolated(unsafe) static let relativeFormatter: RelativeDateTimeFormatter = {
        let f = RelativeDateTimeFormatter()
        f.unitsStyle = .short
        return f
    }()

    nonisolated static func formatRelativeDate(_ timestamp: Double) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        return relativeFormatter.localizedString(for: date, relativeTo: Date())
    }
}
