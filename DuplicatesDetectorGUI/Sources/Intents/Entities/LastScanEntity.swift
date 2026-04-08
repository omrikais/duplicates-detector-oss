import AppIntents

/// Transient entity representing the most recent scan result.
struct LastScanEntity: TransientAppEntity {
    nonisolated(unsafe) static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Last Scan Result")

    @Property(title: "Pair Count")
    var pairCount: Int

    @Property(title: "Scan Date")
    var scanDate: Date

    @Property(title: "Directories")
    var directories: [String]

    @Property(title: "Mode")
    var mode: String

    @Property(title: "Top Pairs")
    var topPairs: [PairSummaryEntity]

    var displayRepresentation: DisplayRepresentation {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        let dateStr = formatter.string(from: scanDate)
        return DisplayRepresentation(
            title: "\(pairCount) pairs found",
            subtitle: "\(mode) scan on \(dateStr)"
        )
    }

    init() {
        self.pairCount = 0
        self.scanDate = Date()
        self.directories = []
        self.mode = "video"
        self.topPairs = []
    }

    init(
        pairCount: Int,
        scanDate: Date,
        directories: [String],
        mode: String,
        topPairs: [PairSummaryEntity]
    ) {
        self.pairCount = pairCount
        self.scanDate = scanDate
        self.directories = directories
        self.mode = mode
        self.topPairs = topPairs
    }
}
