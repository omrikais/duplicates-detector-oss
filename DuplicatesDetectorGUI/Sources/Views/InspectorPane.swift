import SwiftUI

// MARK: - Inspector Pane (Pair Mode)

/// Right pane for pair mode: both files stacked vertically with full metadata,
/// keep recommendation, and action buttons for each file.
struct PairInspectorPane: View {
    let pair: PairResult
    let activeAction: ActionType
    @Environment(\.ddColors) private var ddColors
    var resolution: PairResolutionStatus = .active
    var onAction: (PairAction) -> Void

    nonisolated static func metadataRowAccessibilityText(label: String, value: String) -> String {
        "\(label): \(value)"
    }

    @State private var clipboardFeedback: [String: ClipboardFeedback] = [:]
    @State private var clipboardFeedbackResetTasks: [String: Task<Void, Never>] = [:]

    private enum ClipboardFeedback {
        case path
        case both
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DDSpacing.md) {
                fileSection(
                    path: pair.fileA,
                    meta: pair.fileAMetadata,
                    isReference: pair.fileAIsReference,
                    isKeep: pair.keepPath == pair.fileA
                )

                Divider()
                    .padding(.vertical, DDSpacing.sm)

                fileSection(
                    path: pair.fileB,
                    meta: pair.fileBMetadata,
                    isReference: pair.fileBIsReference,
                    isKeep: pair.keepPath == pair.fileB
                )
            }
            .padding(DDDensity.regular)
        }
        .background(DDColors.surface1)
        .onChange(of: pair.fileA) { _, _ in
            resetTransientState()
        }
        .onChange(of: pair.fileB) { _, _ in
            resetTransientState()
        }
        .onDisappear { resetTransientState() }
    }

    // MARK: - File Section

    private func fileSection(
        path: String, meta: FileMetadata,
        isReference: Bool, isKeep: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: DDSpacing.md) {
            InspectorIdentitySection(
                path: path,
                thumbnailBase64: meta.thumbnail,
                isKeep: isKeep,
                isReference: isReference,
                modificationDate: meta.mtime.map { Date(timeIntervalSince1970: $0) },
                albumNames: meta.albumNames
            )

            Divider()

            InspectorMetadataGrid(
                fileSize: meta.fileSize,
                duration: meta.duration,
                width: meta.width,
                height: meta.height,
                codec: meta.codec,
                bitrate: meta.bitrate,
                framerate: meta.framerate,
                audioChannels: meta.audioChannels,
                mtime: meta.mtime,
                tagTitle: meta.tagTitle,
                tagArtist: meta.tagArtist,
                tagAlbum: meta.tagAlbum
            )

            if pair.keepPath != nil {
                Divider()
                KeepRecommendationBadge(isKeep: isKeep)
            }

            Divider()

            // Actions
            actionsSection(path: path, isKeep: isKeep, isReference: isReference)
        }
        .accessibilityElement(children: .contain)
        .accessibilityLabel("File details for \(path.fileName)")
    }

    // MARK: - Actions

    private var isResolved: Bool {
        if case .active = resolution { return false }
        return true
    }

    private func actionsSection(path: String, isKeep: Bool, isReference: Bool) -> some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Actions")
                .font(DDTypography.sectionTitle)
                .foregroundStyle(ddColors.textPrimary)

            InspectorFileButtons(
                path: path,
                copyPathLabel: copyPathLabel(for: path),
                copyBothLabel: copyBothLabel(for: path),
                onCopyPath: { handleCopyPath(for: path) },
                onCopyBoth: { handleCopyBoth(for: path) },
                onAction: onAction
            )

            if !isResolved {
                HStack(spacing: DDSpacing.sm) {
                    InspectorFileActionButton(
                        path: path,
                        activeAction: activeAction,
                        isKeep: isKeep,
                        isReference: isReference,
                        onAction: onAction
                    )
                    .controlSize(.small)

                    Button { onAction(.ignorePair(pair.fileA, pair.fileB)) } label: {
                        Label("Ignore Pair", systemImage: "xmark.circle")
                    }
                    .controlSize(.small)
                    .help("Add this pair to the ignore list so it won't appear in future scans")
                }
            }
        }
    }

    // MARK: - Clipboard Feedback

    private func copyPathLabel(for path: String) -> String {
        clipboardFeedback[path] == .path ? "Copied!" : "Copy Path"
    }

    private func copyBothLabel(for path: String) -> String {
        clipboardFeedback[path] == .both ? "Copied!" : "Copy Both"
    }

    private func handleCopyPath(for path: String) {
        onAction(.copyPath(path))
        setClipboardFeedback(.path, for: path)
    }

    private func handleCopyBoth(for path: String) {
        onAction(.copyPaths(pair.fileA, pair.fileB))
        setClipboardFeedback(.both, for: path)
    }

    private func setClipboardFeedback(_ feedback: ClipboardFeedback, for path: String) {
        clipboardFeedback[path] = feedback
        clipboardFeedbackResetTasks[path]?.cancel()
        clipboardFeedbackResetTasks[path] = Task { @MainActor in
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            clipboardFeedback[path] = nil
            clipboardFeedbackResetTasks[path] = nil
        }
    }

    private func resetTransientState() {
        clipboardFeedback.removeAll()
        for task in clipboardFeedbackResetTasks.values { task.cancel() }
        clipboardFeedbackResetTasks.removeAll()
    }

}

// MARK: - Inspector Pane (Group Mode)

/// Right pane for group mode: full metadata for a selected group member file.
struct GroupInspectorPane: View {
    let file: GroupFile
    @Environment(\.ddColors) private var ddColors
    let isKeep: Bool
    let hasKeepStrategy: Bool
    let activeAction: ActionType
    var resolvedPaths: Set<String> = []
    var onAction: (PairAction) -> Void

    @State private var didCopyPath = false
    @State private var clipboardFeedbackResetTask: Task<Void, Never>?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: DDSpacing.md) {
                // GroupFile doesn't carry albumNames — Photos scans produce pairs, not groups.
                // Falls back to "Photos Library" label in the identity section.
                InspectorIdentitySection(
                    path: file.path,
                    thumbnailBase64: file.thumbnail,
                    isKeep: isKeep,
                    isReference: file.isReference,
                    modificationDate: file.mtime.map { Date(timeIntervalSince1970: $0) }
                )

                Divider()

                InspectorMetadataGrid(
                    fileSize: file.fileSize,
                    duration: file.duration,
                    width: file.width,
                    height: file.height,
                    codec: file.codec,
                    bitrate: file.bitrate,
                    framerate: file.framerate,
                    audioChannels: file.audioChannels,
                    mtime: file.mtime,
                    tagTitle: file.tagTitle,
                    tagArtist: file.tagArtist,
                    tagAlbum: file.tagAlbum
                )

                if isKeep || hasKeepStrategy {
                    Divider()
                    KeepRecommendationBadge(isKeep: isKeep)
                }

                Divider()

                VStack(alignment: .leading, spacing: DDSpacing.sm) {
                    Text("Actions")
                        .font(DDTypography.sectionTitle)
                        .foregroundStyle(ddColors.textPrimary)

                    InspectorFileButtons(
                        path: file.path,
                        copyPathLabel: copyPathLabel,
                        onCopyPath: { handleCopyPath() },
                        onAction: onAction
                    )

                    if !resolvedPaths.contains(file.path) {
                        InspectorFileActionButton(
                            path: file.path,
                            activeAction: activeAction,
                            isKeep: isKeep,
                            isReference: file.isReference,
                            onAction: onAction
                        )
                        .controlSize(.small)
                    }
                }
            }
            .padding(DDDensity.regular)
            .accessibilityElement(children: .contain)
            .accessibilityLabel("File details for \(file.path.fileName)")
        }
        .background(DDColors.surface1)
        .onChange(of: file.path) { _, _ in
            resetTransientState()
        }
        .onDisappear { resetTransientState() }
    }

    private var copyPathLabel: String {
        didCopyPath ? "Copied!" : "Copy Path"
    }

    private func handleCopyPath() {
        onAction(.copyPath(file.path))
        didCopyPath = true
        clipboardFeedbackResetTask?.cancel()
        clipboardFeedbackResetTask = Task { @MainActor in
            try? await Task.sleep(for: .seconds(1.5))
            guard !Task.isCancelled else { return }
            didCopyPath = false
            clipboardFeedbackResetTask = nil
        }
    }

    private func resetTransientState() {
        didCopyPath = false
        clipboardFeedbackResetTask?.cancel()
        clipboardFeedbackResetTask = nil
    }

}

// MARK: - Keep Recommendation Badge

private struct KeepRecommendationBadge: View {
    let isKeep: Bool
    @Environment(\.ddColors) private var ddColors

    var body: some View {
        if isKeep {
            Label("Recommended to keep", systemImage: "checkmark.circle.fill")
                .font(DDTypography.body)
                .foregroundStyle(DDColors.success)
                .ddGlassPill(size: .medium, tint: DDColors.success.opacity(0.15))
        } else {
            Label("Candidate for removal", systemImage: "minus.circle")
                .font(DDTypography.body)
                .foregroundStyle(ddColors.textSecondary)
                .ddGlassPill(size: .medium)
        }
    }
}

// MARK: - Inspector Reveal/Open/Copy Buttons

private struct InspectorFileButtons: View {
    let path: String
    let copyPathLabel: String
    var copyBothLabel: String? = nil
    var onCopyPath: () -> Void
    var onCopyBoth: (() -> Void)? = nil
    var onAction: (PairAction) -> Void

    var body: some View {
        HStack(spacing: DDSpacing.sm) {
            if path.isPhotosAssetURI {
                Button { onAction(.revealInFinder(path)) } label: {
                    Label("Reveal in Photos", systemImage: "photo.on.rectangle")
                }
            } else {
                Button { onAction(.revealInFinder(path)) } label: {
                    Label("Reveal", systemImage: "folder")
                }

                Button { onAction(.quickLook(path)) } label: {
                    Label("Open", systemImage: "arrow.up.forward.app")
                }
            }

            Button { onCopyPath() } label: {
                Label(copyPathLabel, systemImage: "doc.on.clipboard")
            }

            if let onCopyBoth, let label = copyBothLabel {
                Button { onCopyBoth() } label: {
                    Label(label, systemImage: "doc.on.doc")
                }
            }
        }
        .controlSize(.small)
    }
}

// MARK: - Shared File-Private Components

/// Identity header block: thumbnail + badges + filename + full path.
/// For Photos Library assets, shows album pills (or "Photos Library" fallback) instead of the file path.
private struct InspectorIdentitySection: View {
    @Environment(\.ddColors) private var ddColors
    let path: String
    let thumbnailBase64: String?
    let isKeep: Bool
    let isReference: Bool
    var modificationDate: Date? = nil
    var albumNames: [String]? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            ThumbnailView(
                path: path,
                base64: thumbnailBase64,
                maxWidth: DDSpacing.thumbnailDetailWidth,
                maxHeight: DDSpacing.thumbnailDetailHeight,
                contentMode: .fit,
                modificationDate: modificationDate
            )

            HStack(spacing: DDSpacing.xs) {
                FileBadges(isKeep: isKeep, isReference: isReference)
                Text(path.fileName)
                    .font(DDTypography.monospaced)
                    .foregroundStyle(ddColors.textPrimary)
                    .lineLimit(2)
                    .truncationMode(.middle)
            }

            if path.isPhotosAssetURI {
                if let albums = albumNames, !albums.isEmpty {
                    HStack(spacing: DDSpacing.xxs) {
                        ForEach(albums, id: \.self) { name in
                            Text(name)
                                .font(DDTypography.label)
                                .padding(.horizontal, DDSpacing.xs)
                                .padding(.vertical, 2)
                                .background(DDColors.accent.opacity(0.15), in: Capsule())
                                .foregroundStyle(DDColors.accent)
                        }
                    }
                } else {
                    Label("Photos Library", systemImage: "photo.on.rectangle")
                        .font(DDTypography.metadata)
                        .foregroundStyle(ddColors.textMuted)
                }
            } else {
                Text(path)
                    .font(DDTypography.metadata)
                    .foregroundStyle(ddColors.textMuted)
                    .lineLimit(3)
                    .truncationMode(.middle)
                    .textSelection(.enabled)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(path.isPhotosAssetURI ? "Photos Library asset" : path)\(isKeep ? ", kept file" : "")\(isReference ? ", reference file" : "")")
    }
}

/// Metadata section with title and optional rows for all file properties.
private struct InspectorMetadataGrid: View {
    @Environment(\.ddColors) private var ddColors
    let fileSize: Int
    var duration: Double?
    var width: Int?
    var height: Int?
    var codec: String?
    var bitrate: Int?
    var framerate: Double?
    var audioChannels: Int?
    var mtime: Double?
    var tagTitle: String?
    var tagArtist: String?
    var tagAlbum: String?

    var body: some View {
        VStack(alignment: .leading, spacing: DDSpacing.sm) {
            Text("Metadata")
                .font(DDTypography.sectionTitle)
                .foregroundStyle(ddColors.textPrimary)

            Grid(alignment: .leading, horizontalSpacing: DDSpacing.md, verticalSpacing: DDSpacing.sm) {
                metadataRow("Size", DDFormatters.formatFileSize(fileSize))

                if let dur = duration {
                    metadataRow("Duration", DDFormatters.formatDuration(dur))
                }
                if let res = DDFormatters.formatResolution(width: width, height: height) {
                    metadataRow("Resolution", res)
                }
                if let codec {
                    metadataRow("Codec", codec)
                }
                if let br = bitrate {
                    metadataRow("Bitrate", DDFormatters.formatBitrate(br))
                }
                if let fps = framerate {
                    metadataRow("FPS", DDFormatters.formatFramerate(fps))
                }
                if let ch = audioChannels {
                    metadataRow("Audio", DDFormatters.formatAudioChannels(ch))
                }
                if let mt = mtime {
                    metadataRow("Modified", DDFormatters.formatRelativeDate(mt))
                }
                if let title = tagTitle {
                    metadataRow("Title", title)
                }
                if let artist = tagArtist {
                    metadataRow("Artist", artist)
                }
                if let album = tagAlbum {
                    metadataRow("Album", album)
                }
            }
            .accessibilityElement(children: .contain)
        }
    }

    private func metadataRow(_ label: String, _ value: String) -> some View {
        GridRow {
            Text(label)
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
                .frame(width: DDSpacing.inspectorLabelWidth, alignment: .leading)
            Text(value)
                .font(DDTypography.monospaced)
                .foregroundStyle(ddColors.textSecondary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(PairInspectorPane.metadataRowAccessibilityText(label: label, value: value))
    }
}

/// File action button (Trash / Delete / Move) with protection logic for kept/reference files.
private struct InspectorFileActionButton: View {
    @Environment(\.ddColors) private var ddColors
    let path: String
    let activeAction: ActionType
    let isKeep: Bool
    let isReference: Bool
    let onAction: (PairAction) -> Void

    var body: some View {
        let isProtected = isKeep || isReference
        let protectedHelp = isKeep ? "Cannot modify the kept file" : "Cannot modify a reference file"

        let isPhotos = path.isPhotosAssetURI

        switch activeAction {
        case .trash:
            Button { onAction(.trash(path)) } label: {
                Label(isPhotos ? "Photos Trash" : "Move to Trash", systemImage: "trash")
            }
            .disabled(isProtected)
            .help(isProtected ? protectedHelp : isPhotos ? "Move to Recently Deleted in Photos" : "Move to Trash")
            .accessibilityHint(isProtected ? protectedHelp : isPhotos ? "Moves this photo to Recently Deleted" : "Moves this file to the Trash")

        case .delete:
            Button { onAction(.permanentDelete(path)) } label: {
                Label("Delete Permanently", systemImage: "trash.slash")
            }
            .disabled(isProtected)
            .help(isProtected ? protectedHelp : "Permanently delete this file")
            .accessibilityHint(isProtected ? protectedHelp : "Permanently deletes this file from disk")

        case .moveTo:
            Button { onAction(.moveTo(path)) } label: {
                Label("Move To\u{2026}", systemImage: "folder.badge.plus")
            }
            .disabled(isProtected)
            .help(isProtected ? protectedHelp : "Move to destination directory")
            .accessibilityHint(isProtected ? protectedHelp : "Moves this file to a chosen directory")

        case .hardlink, .symlink, .reflink:
            Label("CLI-only action", systemImage: "terminal")
                .font(DDTypography.label)
                .foregroundStyle(ddColors.textMuted)
                .help("File actions for this mode are CLI-only")
        }
    }
}

#if DEBUG
#Preview("Pair Inspector — Stacked") {
    let pair = PreviewFixtures.samplePairResults[0]
    PairInspectorPane(pair: pair, activeAction: .trash) { _ in }
}

#Preview("Group Inspector") {
    let group = PreviewFixtures.sampleGroupResults[0]
    let file = group.files[0]
    GroupInspectorPane(file: file, isKeep: group.keep == file.path,
                       hasKeepStrategy: group.keep != nil, activeAction: .trash) { _ in }
        .frame(width: 300, height: 600)
}

#Preview("Group Inspector — Reference") {
    let group = PreviewFixtures.sampleGroupResults[0]
    let file = group.files[1]
    GroupInspectorPane(file: file, isKeep: false, hasKeepStrategy: group.keep != nil,
                       activeAction: .trash) { _ in }
        .frame(width: 300, height: 600)
}
#endif
