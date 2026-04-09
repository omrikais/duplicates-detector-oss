import SwiftUI

/// Top-level Preferences window (Cmd+,) with four tabs.
public struct SettingsView: View {
    @State private var defaults = ObservableDefaults()

    public init() {}

    public var body: some View {
        TabView {
            Tab("General", systemImage: "gearshape") {
                GeneralSettingsTab()
            }
            Tab("Scanning", systemImage: "magnifyingglass") {
                ScanningSettingsTab()
            }
            Tab("Cache", systemImage: "archivebox") {
                CacheSettingsTab()
            }
            Tab("Advanced", systemImage: "wrench.and.screwdriver") {
                AdvancedSettingsTab()
            }
        }
        .environment(defaults)
        .frame(minWidth: 500, idealWidth: 600, minHeight: 400, idealHeight: 650)
    }
}
