import Foundation

/// A lightweight representation of a CLI profile TOML file for list display.
struct ProfileEntry: Identifiable, Sendable, Comparable {
    var id: String { name }
    let name: String
    let url: URL
    let lastModified: Date

    static func < (lhs: ProfileEntry, rhs: ProfileEntry) -> Bool {
        lhs.name.localizedStandardCompare(rhs.name) == .orderedAscending
    }
}
