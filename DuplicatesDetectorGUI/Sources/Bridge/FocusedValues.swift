import Foundation
import SwiftUI

/// Focused value key for enabling/disabling the Review command menu.
///
/// Set to `true` by `ScanFlowView` when the coordinator is in the `.results` phase.
public struct ReviewMenuEnabledKey: FocusedValueKey {
    public typealias Value = Bool
}

public extension FocusedValues {
    var isReviewActive: Bool? {
        get { self[ReviewMenuEnabledKey.self] }
        set { self[ReviewMenuEnabledKey.self] = newValue }
    }
}

/// Focused value key that indicates whether the results screen is in group mode.
///
/// Set to `true` by `ResultsScreen` when `effectivePairMode` is false.
/// Used by `CommandMenu("Review")` to show mode-appropriate labels.
public struct ReviewGroupModeKey: FocusedValueKey {
    public typealias Value = Bool
}

public extension FocusedValues {
    var isGroupMode: Bool? {
        get { self[ReviewGroupModeKey.self] }
        set { self[ReviewGroupModeKey.self] = newValue }
    }
}
