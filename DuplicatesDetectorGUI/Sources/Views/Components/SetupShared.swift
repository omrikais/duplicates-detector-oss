import AppKit
import SwiftUI

// MARK: - Drop Target Overlay

/// ViewModifier providing folder drop-target behavior for setup views.
struct DropTargetOverlay: ViewModifier {
    @Binding var isDropTargeted: Bool
    private let onDrop: (URL) -> Void
    private let disabled: Bool

    /// SessionStore init: dispatches through the reducer.
    init(store: SessionStore, isDropTargeted: Binding<Bool>, disabled: Bool = false) {
        self._isDropTargeted = isDropTargeted
        self.onDrop = { url in store.sendSetup(.addDirectory(url)) }
        self.disabled = disabled
    }

    func body(content: Content) -> some View {
        if disabled {
            content
        } else {
            content
                .overlay {
                    if isDropTargeted {
                        RoundedRectangle(cornerRadius: DDRadius.large)
                            .strokeBorder(DDColors.accent, style: StrokeStyle(lineWidth: DDSpacing.dropTargetStroke, dash: [8, 5]))
                            .background(DDColors.accent.opacity(0.05), in: RoundedRectangle(cornerRadius: DDRadius.large))
                            .allowsHitTesting(false)
                    }
                }
                .dropDestination(for: URL.self) { urls, _ in
                    let folders = urls.filter(\.isExistingDirectory)
                    guard !folders.isEmpty else { return false }
                    for url in folders { onDrop(url) }
                    return true
                } isTargeted: { isDropTargeted = $0 }
        }
    }
}

// MARK: - Profile Management

/// Shared profile management functions used by ScanSetupView.
enum SetupShared {

    /// Result of a save-profile operation. Callers assign fields back to `@State`.
    struct SaveResult {
        var dismiss: Bool
        var error: String?
    }

    // MARK: - SessionStore Profile Management

    @MainActor
    static func refreshProfiles(store: SessionStore) async {
        do {
            store.profiles = try await ProfileManager.shared.listProfiles()
        } catch {
            store.profiles = []
        }
    }

    @MainActor
    static func loadProfile(_ name: String, store: SessionStore) async -> String? {
        do {
            let data = try await ProfileManager.shared.loadProfile(name: name)
            store.sendSetup(.applyProfile(data))
            store.selectedProfileName = name
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    @MainActor
    static func saveProfile(
        name: String,
        store: SessionStore
    ) async -> SaveResult {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard ProfileManager.validateName(trimmed) else {
            return SaveResult(dismiss: false, error: "Invalid profile name.")
        }
        let saveErrors = store.setupState.profileSaveErrors
        guard saveErrors.isEmpty else {
            return SaveResult(dismiss: false, error: saveErrors.first)
        }
        do {
            let data = store.setupState.toProfileData()
            try await ProfileManager.shared.saveProfile(name: trimmed, data: data)
            store.selectedProfileName = trimmed
            await refreshProfiles(store: store)
            return SaveResult(dismiss: true, error: nil)
        } catch {
            return SaveResult(dismiss: false, error: error.localizedDescription)
        }
    }

    /// Profile menu for the Scan setup view (SessionStore).
    @MainActor
    static func profileMenu(
        store: SessionStore,
        activePreset: Binding<ScanPreset?>?,
        profileError: Binding<String?>,
        showSaveProfileSheet: Binding<Bool>,
        saveProfileName: Binding<String>
    ) -> some View {
        Menu {
            Button {
                store.selectedProfileName = nil
                let previousMode = store.setupState.mode
                if activePreset != nil {
                    store.sendSetup(.setBool(.suppressPresetOnModeChange, true))
                }
                store.sendSetup(.reloadDefaults)
                if store.setupState.mode == previousMode {
                    store.sendSetup(.setBool(.suppressPresetOnModeChange, false))
                    if let activePreset {
                        activePreset.wrappedValue = PresetManager.detectPreset(
                            for: store.setupState.mode, from: store.setupState)
                    }
                }
            } label: {
                if store.selectedProfileName == nil {
                    Label("None", systemImage: "checkmark")
                } else {
                    Text("None")
                }
            }

            if !store.profiles.isEmpty {
                Divider()
                ForEach(store.profiles) { profile in
                    Button {
                        Task {
                            profileError.wrappedValue = await loadProfile(profile.name, store: store)
                        }
                    } label: {
                        if store.selectedProfileName == profile.name {
                            Label(profile.name, systemImage: "checkmark")
                        } else {
                            Text(profile.name)
                        }
                    }
                }
            }

            Divider()
            Button("Save as Profile\u{2026}") {
                saveProfileName.wrappedValue = ""
                showSaveProfileSheet.wrappedValue = true
            }
        } label: {
            Label(store.selectedProfileName ?? "Profile", systemImage: "person.crop.rectangle.stack")
                .font(DDTypography.body)
        }
        .buttonStyle(.plain)
        .foregroundStyle(DDColors.textSecondary)
        .help("Load or save a configuration profile")
    }

    /// Save profile sheet content shared between views.
    @MainActor
    static func saveProfileSheet(
        saveProfileName: Binding<String>,
        profileError: String?,
        showSheet: Binding<Bool>,
        onSave: @escaping () -> Void
    ) -> some View {
        VStack(spacing: DDSpacing.lg) {
            Text("Save as Profile")
                .font(DDTypography.heading)

            TextField("Profile name", text: saveProfileName)
                .styledField()

            if let error = profileError {
                Text(error)
                    .font(DDTypography.metadata)
                    .foregroundStyle(DDColors.destructive)
            }

            if !saveProfileName.wrappedValue.isEmpty && !ProfileManager.validateName(saveProfileName.wrappedValue) {
                Text("Use only letters, digits, underscores, hyphens, or dots.")
                    .font(DDTypography.metadata)
                    .foregroundStyle(DDColors.textSecondary)
            }

            HStack {
                Button("Cancel") { showSheet.wrappedValue = false }
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Button("Save") { onSave() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(saveProfileName.wrappedValue.isEmpty || !ProfileManager.validateName(saveProfileName.wrappedValue))
                    .accessibilityHint("Saves the current configuration as a named profile")
            }
        }
        .padding(DDSpacing.lg)
        .frame(width: 350)
    }
}
