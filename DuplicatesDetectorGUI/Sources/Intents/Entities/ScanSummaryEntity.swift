import AppIntents

/// Transient entity representing a scan summary returned by `ScanDirectoryIntent`.
struct ScanSummaryEntity: TransientAppEntity {
    nonisolated(unsafe) static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Scan Summary")

    @Property(title: "Pair Count")
    var pairCount: Int

    @Property(title: "Files Scanned")
    var filesScanned: Int

    @Property(title: "Top Score")
    var topScore: Double

    @Property(title: "Scan Duration")
    var scanDuration: Double

    var displayRepresentation: DisplayRepresentation {
        DisplayRepresentation(
            title: "\(pairCount) duplicate pairs found",
            subtitle: "\(filesScanned) files scanned in \(String(format: "%.1f", scanDuration))s"
        )
    }

    init() {
        self.pairCount = 0
        self.filesScanned = 0
        self.topScore = 0
        self.scanDuration = 0
    }

    init(pairCount: Int, filesScanned: Int, topScore: Double, scanDuration: Double) {
        self.pairCount = pairCount
        self.filesScanned = filesScanned
        self.topScore = topScore
        self.scanDuration = scanDuration
    }
}
