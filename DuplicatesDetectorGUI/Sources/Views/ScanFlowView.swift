import SwiftUI

/// Manages the scan lifecycle: setup -> scanning -> results | error.
///
/// Reads `appState.store` -- there is exactly one store for the entire app.
/// Duplicate windows (from macOS state restoration) render the same state;
/// they cannot create independent scan lifecycles.
struct ScanFlowView: View {
    @Environment(AppState.self) private var appState
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var store: SessionStore { appState.store }

    var body: some View {
        Group {
            switch store.phase {
            case .setup:
                ScanSetupView(store: store)
                    .transition(.opacity)
            case .scanning:
                ProgressScreen(store: store)
                    .transition(reduceMotion ? .opacity : .push(from: .trailing))
            case .results:
                if store.session.results?.isEmpty == true {
                    ZeroResultsScreen(store: store)
                        .transition(reduceMotion ? .opacity : .push(from: .trailing))
                } else {
                    ResultsScreen(store: store)
                        .transition(reduceMotion ? .opacity : .push(from: .trailing))
                }
            case .error(let info):
                ErrorScreen(error: info, store: store)
                    .transition(.opacity)
            }
        }
        .animation(reduceMotion ? .none : DDMotion.smooth, value: store.phase)
    }
}

#if DEBUG
#Preview("Configuration Phase") {
    let state = PreviewFixtures.appState()
    let _ = {
        state.hasPassedDependencyCheck = true
        state.dependencyStatus = PreviewFixtures.allAvailableDependencyStatus()
    }()
    ScanFlowView()
        .environment(state)
        .frame(width: 900, height: 700)
}
#endif
