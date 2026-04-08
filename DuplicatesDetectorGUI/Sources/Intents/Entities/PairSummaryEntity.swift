import AppIntents

/// Transient entity representing a single duplicate pair summary.
struct PairSummaryEntity: TransientAppEntity {
    nonisolated(unsafe) static var typeDisplayRepresentation = TypeDisplayRepresentation(name: "Pair Summary")

    @Property(title: "File A")
    var fileA: String

    @Property(title: "File B")
    var fileB: String

    @Property(title: "Score")
    var score: Double

    var displayRepresentation: DisplayRepresentation {
        let aName = (fileA as NSString).lastPathComponent
        let bName = (fileB as NSString).lastPathComponent
        return DisplayRepresentation(
            title: "\(aName) \u{2194} \(bName)",
            subtitle: "Score: \(Int(score))"
        )
    }

    init() {
        self.fileA = ""
        self.fileB = ""
        self.score = 0
    }

    init(fileA: String, fileB: String, score: Double) {
        self.fileA = fileA
        self.fileB = fileB
        self.score = score
    }
}
