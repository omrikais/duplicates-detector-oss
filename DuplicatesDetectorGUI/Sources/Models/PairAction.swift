import Foundation

/// Actions the user can perform on a duplicate pair or individual file.
enum PairAction: Sendable {
    case revealInFinder(String)
    case quickLook(String)
    case trash(String)
    case permanentDelete(String)
    case moveTo(String)
    case copyPath(String)
    case copyPaths(String, String)
    case ignorePair(String, String)
    case bulkAction
}
