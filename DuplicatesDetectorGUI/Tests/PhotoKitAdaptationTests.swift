import Foundation
import Photos
import Testing

@testable import DuplicatesDetector

// MARK: - D1: fetchAssets 3-tuple return type

@Suite("D1: fetchAssets return type")
struct FetchAssetsReturnTypeTests {

    @Test("MockPhotoKitBridge conforms to PhotoKitBridgeProtocol")
    func mockConformsToProtocol() async {
        // The mock must satisfy the protocol, including the 3-tuple
        // return shape of scanLibrary. A compilation success here
        // verifies that the protocol is satisfied.
        let bridge = MockPhotoKitBridge()
        let status = await bridge.requestAuthorization()
        #expect(status == .authorized)
    }

    @Test("PhotoAssetMetadata stores albumNames field")
    func assetMetadataHasAlbumNames() {
        let asset = PhotoKitBridgeTests.makeAsset(id: "test-1", filename: "IMG_001.jpg")
        // Default factory creates empty albumNames
        #expect(asset.albumNames.isEmpty)
    }
}

// MARK: - D5: collectFilePaths filters photos:// URIs

@Suite("D5: collectFilePaths filters Photos URIs")
struct CollectFilePathsFilterTests {

    /// Build a minimal envelope with the given pairs.
    private static func makeEnvelope(pairs: [PairResult]) -> ScanEnvelope {
        ScanEnvelope(
            version: "1.0.0",
            generatedAt: "2025-01-01T00:00:00Z",
            args: ScanArgs(
                directories: ["/photos"],
                threshold: 50,
                content: false,
                weights: nil,
                keep: nil,
                action: "trash",
                group: false,
                sort: "score",
                mode: "auto",
                embedThumbnails: false
            ),
            stats: ScanStats(
                filesScanned: 10,
                filesAfterFilter: 10,
                totalPairsScored: 5,
                pairsAboveThreshold: pairs.count,
                scanTime: 1.0,
                extractTime: 1.0,
                filterTime: 0.1,
                contentHashTime: 0.0,
                scoringTime: 1.0,
                totalTime: 3.0
            ),
            content: .pairs(pairs)
        )
    }

    private static func makePair(
        fileA: String,
        fileB: String,
        score: Double = 85.0
    ) -> PairResult {
        PairResult(
            fileA: fileA,
            fileB: fileB,
            score: score,
            breakdown: ["filename": 40.0],
            detail: [:],
            fileAMetadata: FileMetadata(fileSize: 1_000_000),
            fileBMetadata: FileMetadata(fileSize: 900_000),
            fileAIsReference: false,
            fileBIsReference: false,
            keep: "a"
        )
    }

    @Test("minimumDisplayElapsed excludes photos:// URIs from file monitor paths")
    func photosURIsExcludedFromFileMonitor() {
        // When results contain photos:// URIs, collectFilePaths (called
        // during the .results transition) must filter them out because
        // FSEventStream cannot monitor synthetic Photos URIs.
        let pairs = [
            Self.makePair(fileA: "photos://asset/ABC-123/L0/001", fileB: "/videos/b.mp4"),
            Self.makePair(fileA: "/videos/c.mp4", fileB: "photos://asset/DEF-456/L0/001"),
        ]

        var session = Session(phase: .scanning)
        session.lastScanConfig = SessionConfig()
        var scan = ScanProgress()
        scan.isFinalizingResults = true
        scan.timing.scanPhaseStartTime = Date()
        session.scan = scan
        session.results = ResultsSnapshot(envelope: Self.makeEnvelope(pairs: pairs))

        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .minimumDisplayElapsed
        )
        #expect(newState.phase == .results)

        // Extract paths from the checkFileStatuses and startFileMonitor effects
        let checkPaths = effects.compactMap { effect -> [String]? in
            if case .checkFileStatuses(let paths) = effect { return paths }
            return nil
        }.flatMap { $0 }

        let monitorPaths = effects.compactMap { effect -> [String]? in
            if case .startFileMonitor(let paths) = effect { return paths }
            return nil
        }.flatMap { $0 }

        // Only filesystem paths should be present
        #expect(checkPaths.contains("/videos/b.mp4"))
        #expect(checkPaths.contains("/videos/c.mp4"))
        #expect(!checkPaths.contains { $0.hasPrefix("photos://") })

        #expect(monitorPaths.contains("/videos/b.mp4"))
        #expect(monitorPaths.contains("/videos/c.mp4"))
        #expect(!monitorPaths.contains { $0.hasPrefix("photos://") })
    }

    @Test("all-Photos results produce empty file monitor paths")
    func allPhotosResultsProduceEmptyPaths() {
        let pairs = [
            Self.makePair(
                fileA: "photos://asset/AAA-111/L0/001",
                fileB: "photos://asset/BBB-222/L0/001"
            ),
        ]

        var session = Session(phase: .scanning)
        session.lastScanConfig = SessionConfig()
        var scan = ScanProgress()
        scan.isFinalizingResults = true
        scan.timing.scanPhaseStartTime = Date()
        session.scan = scan
        session.results = ResultsSnapshot(envelope: Self.makeEnvelope(pairs: pairs))

        let (_, effects) = SessionReducer.reduce(
            state: session, action: .minimumDisplayElapsed
        )

        let checkPaths = effects.compactMap { effect -> [String]? in
            if case .checkFileStatuses(let paths) = effect { return paths }
            return nil
        }.flatMap { $0 }

        #expect(checkPaths.isEmpty)
    }
}

// MARK: - D6: FileMetadata.albumNames

@Suite("D6: FileMetadata albumNames field")
struct FileMetadataAlbumNamesTests {

    @Test("albumNames decodes as nil from CLI JSON without the field")
    func albumNamesDecodesAsNilWhenMissing() throws {
        // CLI JSON output does not include albumNames — it should decode as nil.
        let json = """
        {
            "file_size": 1024
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let metadata = try decoder.decode(FileMetadata.self, from: Data(json.utf8))
        #expect(metadata.albumNames == nil)
        #expect(metadata.fileSize == 1024)
    }

    @Test("albumNames decodes correctly when present")
    func albumNamesDecodesWhenPresent() throws {
        let json = """
        {
            "file_size": 2048,
            "album_names": ["Vacation", "Favorites"]
        }
        """
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let metadata = try decoder.decode(FileMetadata.self, from: Data(json.utf8))
        #expect(metadata.albumNames == ["Vacation", "Favorites"])
    }

    @Test("albumNames round-trips through encoding/decoding")
    func albumNamesRoundTrips() throws {
        var original = FileMetadata(fileSize: 500)
        original.albumNames = ["Album A", "Album B"]
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(original)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = try decoder.decode(FileMetadata.self, from: data)
        #expect(decoded.albumNames == ["Album A", "Album B"])
    }
}

// MARK: - D6: PhotoAssetMetadata.toFileMetadata passes albums

@Suite("D6: PhotoAssetMetadata.toFileMetadata album pass-through")
struct PhotoAssetMetadataToFileMetadataTests {

    @Test("toFileMetadata passes non-empty albumNames")
    func passesAlbumNames() {
        let asset = PhotoAssetMetadata(
            id: "test-id",
            filename: "IMG_0001.jpg",
            duration: nil,
            width: 4032, height: 3024,
            fileSize: 3_200_000,
            creationDate: nil,
            modificationDate: nil,
            latitude: nil, longitude: nil,
            cameraModel: nil, lensModel: nil,
            albumNames: ["Vacation", "Favorites"],
            mediaType: .image
        )
        let meta = asset.toFileMetadata()
        #expect(meta.albumNames == ["Vacation", "Favorites"])
    }

    @Test("toFileMetadata maps empty albumNames to nil")
    func emptyAlbumNamesMapsToNil() {
        let asset = PhotoAssetMetadata(
            id: "test-id",
            filename: "IMG_0001.jpg",
            duration: nil,
            width: 4032, height: 3024,
            fileSize: 3_200_000,
            creationDate: nil,
            modificationDate: nil,
            latitude: nil, longitude: nil,
            cameraModel: nil, lensModel: nil,
            albumNames: [],
            mediaType: .image
        )
        let meta = asset.toFileMetadata()
        #expect(meta.albumNames == nil)
    }

    @Test("toFileMetadata preserves dimension and size fields")
    func preservesDimensionAndSize() {
        let asset = PhotoAssetMetadata(
            id: "test-id",
            filename: "IMG_0001.jpg",
            duration: 10.5,
            width: 1920, height: 1080,
            fileSize: 5_000_000,
            creationDate: Date(timeIntervalSince1970: 1_700_000_000),
            modificationDate: nil,
            latitude: nil, longitude: nil,
            cameraModel: nil, lensModel: nil,
            albumNames: ["Test"],
            mediaType: .video
        )
        let meta = asset.toFileMetadata()
        #expect(meta.width == 1920)
        #expect(meta.height == 1080)
        #expect(meta.duration == 10.5)
        #expect(meta.fileSize == 5_000_000)
        #expect(meta.mtime == 1_700_000_000)
    }
}

// MARK: - D8: Reducer photosAuthorizationLimited

@Suite("D8: photosAuthorizationLimited reducer")
struct PhotosAuthorizationLimitedReducerTests {

    @Test("photosAuthorizationLimited sets photosLimitedWarning to true")
    func setsLimitedWarning() {
        var session = Session(phase: .scanning)
        session.scan = ScanProgress()
        #expect(session.scan?.photosLimitedWarning == false)

        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthorizationLimited
        )
        #expect(newState.scan?.photosLimitedWarning == true)
        // No side effects expected from this action
        #expect(effects.isEmpty)
    }

    @Test("photosAuthorizationLimited is no-op when scan is nil")
    func noOpWhenScanNil() {
        let session = Session() // phase == .setup, scan == nil
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthorizationLimited
        )
        #expect(newState.scan?.photosLimitedWarning == nil)
        #expect(effects.isEmpty)
    }
}

// MARK: - D10: Reducer photosAuthRevoked

@Suite("D10: photosAuthRevoked reducer")
struct PhotosAuthRevokedReducerTests {

    @Test("photosAuthRevoked during scanning transitions to error and emits cancelCLI")
    func transitionsToErrorDuringScanning() {
        var session = Session(phase: .scanning)
        session.scan = ScanProgress()

        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthRevoked
        )

        // Phase should transition to .error with a denial classification
        if case .error(let info) = newState.phase {
            #expect(info.message.contains("denied") || info.category != .unknown)
        } else {
            Issue.record("Expected .error phase, got \(newState.phase)")
        }

        // Scan state should be cleared
        #expect(newState.scan == nil)

        // Must emit cancelCLI to stop any running subprocess
        let hasCancelCLI = effects.contains { $0 == .cancelCLI }
        #expect(hasCancelCLI)
    }

    @Test("photosAuthRevoked is no-op when not scanning")
    func noOpWhenNotScanning() {
        let session = Session() // phase == .setup
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthRevoked
        )
        #expect(newState.phase == .setup)
        #expect(effects.isEmpty)
    }

    @Test("photosAuthRevoked is no-op when in results phase")
    func noOpWhenInResults() {
        let session = Session(phase: .results)
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthRevoked
        )
        #expect(newState.phase == .results)
        #expect(effects.isEmpty)
    }
}

// MARK: - D9/D10: isStillAuthorized and revealInPhotos

@Suite("D9/D10: PhotoKitBridge static helpers")
struct PhotoKitBridgeStaticHelperTests {

    @Test("isStillAuthorized is callable and returns a Bool")
    func isStillAuthorizedCallable() {
        // Can't test real auth status in unit tests, but verify the static
        // method exists and returns a Bool without crashing.
        let result = PhotoKitBridge.isStillAuthorized()
        // Result depends on test environment's auth state — we just verify it compiles and runs
        #expect(result == true || result == false)
    }

    @Test("revealInPhotos is callable on mock without crashing")
    func revealInPhotosCallableOnMock() {
        let bridge = MockPhotoKitBridge()
        // nonisolated — should not throw or crash
        bridge.revealInPhotos(assetID: "ABC-123/L0/001")
    }
}

// MARK: - D7/Helpers: String.isPhotosAssetURI and displayFileName

@Suite("Photos URI helpers")
struct PhotosURIHelperTests {

    @Test("isPhotosAssetURI returns true for photos:// URIs")
    func isPhotosAssetURITrue() {
        #expect("photos://asset/ABC-123/L0/001".isPhotosAssetURI == true)
    }

    @Test("isPhotosAssetURI returns false for filesystem paths")
    func isPhotosAssetURIFalse() {
        #expect("/videos/a.mp4".isPhotosAssetURI == false)
    }

    @Test("photosAssetID extracts identifier from photos:// URI")
    func photosAssetIDExtraction() {
        let uri = "photos://asset/ABC-123/L0/001"
        #expect(uri.photosAssetID == "ABC-123/L0/001")
    }

    @Test("photosAssetID returns nil for filesystem paths")
    func photosAssetIDNilForFilesystem() {
        #expect("/videos/a.mp4".photosAssetID == nil)
    }

    @Test("displayFileName returns truncated Photo label for photos:// URI")
    func displayFileNameForPhotosURI() {
        let uri = "photos://asset/ABCD1234-5678-9012-3456-789012345678/L0/001"
        let display = uri.displayFileName
        // UUID is 36 chars, > 8, so it should be truncated to first 8 + ellipsis
        #expect(display == "Photo ABCD1234\u{2026}")
    }

    @Test("displayFileName returns short Photo label when UUID is 8 chars or fewer")
    func displayFileNameForShortPhotosURI() {
        let uri = "photos://asset/SHORT123/L0/001"
        let display = uri.displayFileName
        // "SHORT123" is exactly 8 chars
        #expect(display == "Photo SHORT123")
    }

    @Test("displayFileName returns filename for regular filesystem path")
    func displayFileNameForFilesystemPath() {
        #expect("/videos/vacation.mp4".displayFileName == "vacation.mp4")
    }
}

// MARK: - D3: Bulk batch delete partitioning

@Suite("D3: Bulk action Photos partitioning")
struct BulkActionPhotosPartitionTests {

    @Test("MockPhotoKitBridge.deleteAssets records batch call with all IDs")
    func deleteAssetsRecordsBatch() async throws {
        // Verify that the mock can receive a batch of asset IDs,
        // simulating the single-call batch pattern used in executeBulkAction.
        let bridge = MockPhotoKitBridge()
        let ids = ["ABC-123/L0/001", "DEF-456/L0/001", "GHI-789/L0/001"]

        try await bridge.deleteAssets(ids)

        let count = await bridge.deleteCallCount
        let lastIDs = await bridge.lastDeletedIDs
        #expect(count == 1)
        #expect(lastIDs == ids)
    }

    @Test("isPhotosAssetURI correctly partitions mixed paths")
    func mixedPathPartitioning() {
        // The bulk action logic partitions candidates using isPhotosAssetURI.
        // Verify the predicate works on typical mixed inputs.
        let paths = [
            "photos://asset/ABC-123/L0/001",
            "/videos/a.mp4",
            "photos://asset/DEF-456/L0/001",
            "/images/b.jpg",
        ]

        let photosItems = paths.filter { $0.isPhotosAssetURI }
        let fsItems = paths.filter { !$0.isPhotosAssetURI }

        #expect(photosItems.count == 2)
        #expect(fsItems.count == 2)
        #expect(photosItems[0] == "photos://asset/ABC-123/L0/001")
        #expect(fsItems[0] == "/videos/a.mp4")
    }
}

// MARK: - D2: iCloudSkipped in StageEndEvent extras

@Suite("D2: iCloudSkipped propagation")
struct ICloudSkippedPropagationTests {

    @Test("StageEndEvent extras can carry iCloudSkipped count")
    func stageEndEventCarriesICloudSkipped() {
        // The session store passes iCloudSkipped via StageEndEvent extras.
        // Verify the event can carry and retrieve this value.
        let event = StageEndEvent(
            stage: "extract",
            total: 100,
            elapsed: 2.5,
            timestamp: "2025-01-01T00:00:00Z",
            extras: ["iCloudSkipped": 15]
        )
        #expect(event.extras["iCloudSkipped"] == 15)
    }

    @Test("cliStageEnd stores iCloudSkipped in completed stage extras")
    func reducerStoresICloudSkippedInStageExtras() {
        var session = Session(phase: .scanning)
        session.lastScanConfig = SessionConfig()
        var scan = ScanProgress()
        scan.stages = ScanProgress.initialStages(mode: .video, content: false, audio: false)
        scan.timing.scanPhaseStartTime = Date()
        // Mark extract stage as active
        if let idx = scan.stages.firstIndex(where: { $0.id == .extract }) {
            scan.stages[idx].status = .active(current: 50, total: 100)
        }
        session.scan = scan

        let event = StageEndEvent(
            stage: "extract",
            total: 100,
            elapsed: 3.0,
            timestamp: "2025-01-01T00:00:00Z",
            extras: ["iCloudSkipped": 7]
        )

        let (newState, _) = SessionReducer.reduce(
            state: session, action: .cliStageEnd(event)
        )

        // The extract stage should be completed with the extras preserved
        if let extractStage = newState.scan?.stages.first(where: { $0.id == .extract }) {
            if case .completed(_, _, let extras) = extractStage.status {
                #expect(extras["iCloudSkipped"] == 7)
            } else {
                Issue.record("Expected extract stage to be .completed")
            }
        } else {
            Issue.record("Expected extract stage to exist")
        }
    }
}

// MARK: - D4: Export visibility for Photos results

@Suite("D4: SessionMetadata.photosLibraryLabel")
struct SessionMetadataPhotosLabelTests {

    @Test("photosLibraryLabel is the canonical constant")
    func labelConstantValue() {
        #expect(SessionMetadata.photosLibraryLabel == "Photos Library")
    }

    @Test("startPhotosScan sets sourceLabel to photosLibraryLabel")
    func startPhotosScanSetsSourceLabel() {
        let session = Session()
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.metadata.sourceLabel == SessionMetadata.photosLibraryLabel)
    }

    @Test("startScan sets sourceLabel from directory names, not Photos label")
    func startScanSetsDirectoryLabel() {
        let session = Session()
        var config = SessionConfig()
        config.directories = ["/Users/test/Videos"]
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startScan(config)
        )
        #expect(newState.metadata.sourceLabel == "Videos")
        #expect(newState.metadata.sourceLabel != SessionMetadata.photosLibraryLabel)
    }
}

// MARK: - startPhotosScan reducer

@Suite("startPhotosScan reducer")
struct StartPhotosScanReducerTests {

    @Test("startPhotosScan emits runPhotosScan effect with scope and config")
    func emitsRunPhotosScanEffect() {
        let session = Session()
        let config = SessionConfig()
        let (_, effects) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        let hasRunPhotosScan = effects.contains { effect in
            if case .runPhotosScan(.fullLibrary, _) = effect { return true }
            return false
        }
        #expect(hasRunPhotosScan)
    }

    @Test("startPhotosScan produces stages: authorize, extract, filter, score, report")
    func photosStagesIncludeAuthorize() {
        let session = Session()
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        let stageIds = newState.scan?.stages.map(\.id)
        #expect(stageIds == [.authorize, .extract, .filter, .score, .report])
    }

    @Test("startPhotosScan sets lastOriginalEnvelope to nil")
    func clearsOriginalEnvelope() {
        var session = Session()
        // Pre-set an envelope to verify it gets cleared
        session.lastOriginalEnvelope = Data("old-envelope".utf8)
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.lastOriginalEnvelope == nil)
    }

    @Test("startPhotosScan transitions from .setup to .scanning")
    func transitionsFromSetup() {
        let session = Session()
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.phase == .scanning)
        #expect(newState.scan != nil)
        #expect(newState.scanSequence == 1)
    }

    @Test("startPhotosScan transitions from .results to .scanning and tears down")
    func transitionsFromResults() {
        var session = Session(phase: .results)
        session.lastScanConfig = SessionConfig()
        session.scan = ScanProgress()
        let config = SessionConfig()
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.phase == .scanning)
        // From results with no watch, should emit stopFileMonitor
        let hasStopFileMonitor = effects.contains { $0 == .stopFileMonitor }
        #expect(hasStopFileMonitor)
    }

    @Test("startPhotosScan is no-op during .scanning phase")
    func noOpDuringScanning() {
        let session = Session(phase: .scanning)
        let config = SessionConfig()
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        // Should not change phase or emit effects
        #expect(newState.phase == .scanning)
        #expect(effects.isEmpty)
    }

    @Test("startPhotosScan sets metadata mode to .auto and sourceLabel to photosLibraryLabel")
    func setsMetadataForPhotos() {
        let session = Session()
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.metadata.mode == .auto)
        #expect(newState.metadata.sourceLabel == SessionMetadata.photosLibraryLabel)
        #expect(newState.metadata.directories.isEmpty)
    }

    @Test("startPhotosScan stores config as lastScanConfig")
    func storesConfig() {
        let session = Session()
        var config = SessionConfig()
        config.threshold = 75
        config.mode = .image
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.config?.threshold == 75)
        #expect(newState.lastScanConfig?.threshold == 75)
    }

    @Test("startPhotosScan tears down watch state from prior scan")
    func tearsDownWatchState() {
        var session = Session()
        session.watch = WatchState(isActive: true)
        let config = SessionConfig()
        let (newState, effects) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.watch == nil)
        #expect(effects.contains { $0 == .stopWatch })
        #expect(effects.contains { $0 == .stopFileMonitor })
    }

    @Test("startPhotosScan initializes scan timing")
    func initializesTiming() {
        let session = Session()
        let config = SessionConfig()
        let (newState, _) = SessionReducer.reduce(
            state: session, action: .startPhotosScan(.fullLibrary, config)
        )
        #expect(newState.scan?.timing.scanPhaseStartTime != nil)
    }
}

// MARK: - photosAuthRevoked with pauseFile

@Suite("photosAuthRevoked pause file handling")
struct PhotosAuthRevokedPauseFileTests {

    @Test("photosAuthRevoked during scanning does not emit removePauseFile when no pauseFileURL")
    func noRemovePauseFileWhenNoPauseURL() {
        var session = Session(phase: .scanning)
        var scan = ScanProgress()
        scan.pauseFileURL = nil
        session.scan = scan

        let (_, effects) = SessionReducer.reduce(
            state: session, action: .photosAuthRevoked
        )

        // Should not contain removePauseFile
        let hasRemovePauseFile = effects.contains { effect in
            if case .removePauseFile = effect { return true }
            return false
        }
        #expect(!hasRemovePauseFile)
        // But should still cancel CLI
        #expect(effects.contains { $0 == .cancelCLI })
    }

    @Test("photosAuthRevoked clears scan state completely")
    func clearsScanState() {
        var session = Session(phase: .scanning)
        var scan = ScanProgress()
        scan.stages = [
            ScanProgress.StageState(id: .authorize, displayName: "Authorizing"),
            ScanProgress.StageState(id: .extract, displayName: "Extracting metadata"),
        ]
        session.scan = scan

        let (newState, _) = SessionReducer.reduce(
            state: session, action: .photosAuthRevoked
        )

        #expect(newState.scan == nil)
        if case .error = newState.phase {
            // Expected
        } else {
            Issue.record("Expected .error phase, got \(newState.phase)")
        }
    }
}
