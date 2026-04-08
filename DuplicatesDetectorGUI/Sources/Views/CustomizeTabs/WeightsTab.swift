import SwiftUI

/// Weights configuration tab: thin wrapper around ``WeightsEditorView``.
struct WeightsTab: View {
    let store: SessionStore

    var body: some View {
        WeightsEditorView(store: store)
            .padding(DDDensity.regular)
    }
}
