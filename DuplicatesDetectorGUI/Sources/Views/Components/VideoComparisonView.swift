import AVFoundation
import AVKit
import SwiftUI

/// Synchronized dual-player video comparison with shared transport controls.
struct VideoComparisonView: View {
    let pathA: String
    let pathB: String
    var labelA: String = "File A"
    var labelB: String = "File B"
    @Environment(\.ddColors) private var ddColors

    @State private var playerA: AVPlayer?
    @State private var playerB: AVPlayer?
    @State private var isPlaying = false
    @State private var currentTimeA: Double = 0
    @State private var currentTimeB: Double = 0
    @State private var durationA: Double = 0
    @State private var durationB: Double = 0
    @State private var scrubberPosition: Double = 0
    @State private var isScrubbing = false
    @State private var playbackSpeed: Float = 1.0
    @State private var muteA = false
    @State private var muteB = false
    @State private var isSettingUpA = true
    @State private var isSettingUpB = true

    var body: some View {
        VStack(spacing: 0) {
            playerArea
            Divider()
            transportBar
        }
        .task(id: "\(pathA)|\(pathB)") {
            resetTransportState()
            async let a: Void = setupPlayer(path: pathA, isA: true)
            async let b: Void = setupPlayer(path: pathB, isA: false)
            _ = await (a, b)
        }
        .onDisappear { tearDownPlayers() }
    }

    // MARK: - Player Area

    private var playerArea: some View {
        HStack(spacing: DDSpacing.hairline) {
            ZStack(alignment: .topLeading) {
                if playerA != nil {
                    PlayerRepresentable(player: playerA,
                                        isLeader: true,
                                        onTimeUpdate: handleLeaderTimeUpdate)
                } else if isSettingUpA {
                    DDColors.surface0
                    ProgressView()
                        .controlSize(.small)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ContentUnavailableView("Video Unavailable",
                                           systemImage: "film",
                                           description: Text(labelA))
                }
                if playerA != nil { playerLabel(labelA) }
            }
            .accessibilityLabel("Video preview for \(labelA)")
            .accessibilityAddTraits(.startsMediaSession)

            Divider()

            ZStack(alignment: .topLeading) {
                if playerB != nil {
                    PlayerRepresentable(player: playerB,
                                        isLeader: false,
                                        onTimeUpdate: handleFollowerTimeUpdate)
                } else if isSettingUpB {
                    DDColors.surface0
                    ProgressView()
                        .controlSize(.small)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ContentUnavailableView("Video Unavailable",
                                           systemImage: "film",
                                           description: Text(labelB))
                }
                if playerB != nil { playerLabel(labelB) }
            }
            .accessibilityLabel("Video preview for \(labelB)")
            .accessibilityAddTraits(.startsMediaSession)
        }
    }

    private func playerLabel(_ label: String) -> some View {
        DDMediaLabel(text: label)
            .padding(DDSpacing.sm)
    }

    // MARK: - Transport Bar

    private var transportBar: some View {
        VStack(spacing: DDSpacing.sm) {
            // Scrubber
            Slider(value: $scrubberPosition, in: 0...1) { editing in
                isScrubbing = editing
            }
            .disabled(!bothPlayersReady)
            .onChange(of: scrubberPosition) { _, newValue in
                if isScrubbing { seekBoth(to: newValue) }
            }

            HStack(spacing: DDSpacing.md) {
                // Play controls
                HStack(spacing: DDSpacing.sm) {
                    Button { stepBackward() } label: {
                        Image(systemName: "backward.frame.fill")
                    }
                    .controlSize(.regular)
                    .disabled(!bothPlayersReady)
                    .help("Step backward one frame")

                    Button { togglePlayPause() } label: {
                        Image(systemName: isPlaying ? "pause.fill" : "play.fill")
                    }
                    .controlSize(.regular)
                    .disabled(!bothPlayersReady)
                    .help(isPlaying ? "Pause" : "Play")
                    .accessibilityLabel(isPlaying ? "Pause" : "Play")
                    .accessibilityHint("Double tap to \(isPlaying ? "pause" : "play") both videos")

                    Button { stepForward() } label: {
                        Image(systemName: "forward.frame.fill")
                    }
                    .controlSize(.regular)
                    .disabled(!bothPlayersReady)
                    .help("Step forward one frame")
                }

                // Speed picker
                Picker("Speed", selection: $playbackSpeed) {
                    Text("0.25\u{00D7}").tag(Float(0.25))
                    Text("0.5\u{00D7}").tag(Float(0.5))
                    Text("1\u{00D7}").tag(Float(1.0))
                    Text("2\u{00D7}").tag(Float(2.0))
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(width: 200)
                .onChange(of: playbackSpeed) { _, newSpeed in
                    if isPlaying {
                        playerA?.rate = newSpeed
                        playerB?.rate = newSpeed
                    }
                }

                Spacer()

                // Mute controls
                HStack(spacing: DDSpacing.sm) {
                    Toggle(isOn: $muteA) {
                        Image(systemName: muteA ? "speaker.slash.fill" : "speaker.wave.2.fill")
                    }
                    .toggleStyle(.button)
                    .controlSize(.small)
                    .help(muteA ? "Unmute A" : "Mute A")
                    .onChange(of: muteA) { _, muted in playerA?.isMuted = muted }

                    Toggle(isOn: $muteB) {
                        Image(systemName: muteB ? "speaker.slash.fill" : "speaker.wave.2.fill")
                    }
                    .toggleStyle(.button)
                    .controlSize(.small)
                    .help(muteB ? "Unmute B" : "Mute B")
                    .onChange(of: muteB) { _, muted in playerB?.isMuted = muted }
                }

                // Time displays
                HStack(spacing: DDSpacing.md) {
                    timeLabel(currentTimeA, durationA, label: "A")
                    timeLabel(currentTimeB, durationB, label: "B")
                }
            }
        }
        .padding(.horizontal, DDSpacing.md)
        .padding(.vertical, DDSpacing.sm)
        .background(DDColors.surface2)
    }

    private func timeLabel(_ current: Double, _ duration: Double, label: String) -> some View {
        Text("\(label): \(Self.formatTime(current)) / \(Self.formatTime(duration))")
            .font(DDTypography.monospaced)
            .foregroundStyle(ddColors.textSecondary)
    }

    // MARK: - Playback Control

    private var bothPlayersReady: Bool { playerA != nil && playerB != nil }

    /// Timeline length covers both videos so the longer tail is always reachable.
    private var effectiveDuration: Double { max(durationA, durationB) }

    private func togglePlayPause() {
        guard bothPlayersReady else { return }
        if isPlaying {
            playerA?.pause()
            playerB?.pause()
        } else {
            // Rewind if at EOF so playback can restart
            let maxTime = max(currentTimeA, currentTimeB)
            if effectiveDuration > 0, maxTime >= effectiveDuration - 0.05 {
                seekBoth(to: 0)
            }
            playerA?.rate = playbackSpeed
            playerB?.rate = playbackSpeed
        }
        isPlaying.toggle()
    }

    private func stepForward() {
        guard bothPlayersReady else { return }
        playerA?.pause()
        playerB?.pause()
        isPlaying = false
        playerA?.currentItem?.step(byCount: 1)
        playerB?.currentItem?.step(byCount: 1)
    }

    private func stepBackward() {
        guard bothPlayersReady else { return }
        playerA?.pause()
        playerB?.pause()
        isPlaying = false
        playerA?.currentItem?.step(byCount: -1)
        playerB?.currentItem?.step(byCount: -1)
    }

    private func seekBoth(to position: Double) {
        let absoluteTime = position * effectiveDuration
        let clampedA = min(absoluteTime, durationA)
        let clampedB = min(absoluteTime, durationB)
        let timeA = CMTime(seconds: clampedA, preferredTimescale: 600)
        let timeB = CMTime(seconds: clampedB, preferredTimescale: 600)
        playerA?.seek(to: timeA, toleranceBefore: .zero, toleranceAfter: .zero)
        playerB?.seek(to: timeB, toleranceBefore: .zero, toleranceAfter: .zero)
        currentTimeA = clampedA
        currentTimeB = clampedB
    }

    // MARK: - Leader Time Update

    private func handleLeaderTimeUpdate(_ time: Double) {
        currentTimeA = time
        // Update follower time
        if let follower = playerB {
            currentTimeB = CMTimeGetSeconds(follower.currentTime())
        }
        // Scrubber tracks the further-along player so the full timeline is covered
        let maxTime = max(currentTimeA, currentTimeB)
        if effectiveDuration > 0 && !isScrubbing {
            scrubberPosition = maxTime / effectiveDuration
        }
        // Detect end of playback — stop when both videos have ended
        if isPlaying, effectiveDuration > 0, maxTime >= effectiveDuration - 0.05 {
            playerA?.pause()
            playerB?.pause()
            isPlaying = false
        }
        // Sync follower if drift exceeds 100ms
        syncFollower()
    }

    /// Drives scrubber and EOF detection when B outlasts A.
    private func handleFollowerTimeUpdate(_ time: Double) {
        currentTimeB = time
        // Only take over transport when A has finished (leader observer stalled)
        guard durationA > 0, currentTimeA >= durationA - 0.05 else { return }
        let maxTime = max(currentTimeA, currentTimeB)
        if effectiveDuration > 0 && !isScrubbing {
            scrubberPosition = maxTime / effectiveDuration
        }
        if isPlaying, effectiveDuration > 0, maxTime >= effectiveDuration - 0.05 {
            playerA?.pause()
            playerB?.pause()
            isPlaying = false
        }
    }

    private func syncFollower() {
        guard isPlaying, let leader = playerA, let follower = playerB else { return }
        let leaderTime = CMTimeGetSeconds(leader.currentTime())
        // Don't seek the follower past its own duration
        guard durationB > 0, leaderTime <= durationB else { return }
        let followerTime = CMTimeGetSeconds(follower.currentTime())
        let drift = abs(leaderTime - followerTime)
        if drift > 0.1 {
            let syncTolerance = CMTime(value: 1, timescale: 10) // 100ms — avoids expensive frame-accurate decode
            follower.seek(to: leader.currentTime(), toleranceBefore: syncTolerance, toleranceAfter: syncTolerance)
        }
    }

    // MARK: - Player Setup / Teardown

    private func resetTransportState() {
        let oldA = playerA
        let oldB = playerB
        playerA = nil
        playerB = nil
        if let oldA { AVPlayerPool.shared.release(oldA) }
        if let oldB { AVPlayerPool.shared.release(oldB) }
        isPlaying = false
        scrubberPosition = 0
        currentTimeA = 0
        currentTimeB = 0
        durationA = 0
        durationB = 0
        muteA = false
        muteB = false
        isSettingUpA = true
        isSettingUpB = true
    }

    @MainActor
    private func setupPlayer(path: String, isA: Bool) async {
        guard !Task.isCancelled else {
            if isA { isSettingUpA = false } else { isSettingUpB = false }
            return
        }
        let url = URL(fileURLWithPath: path)
        let player = AVPlayerPool.shared.acquire(for: url)
        player.isMuted = isA ? muteA : muteB

        if let item = player.currentItem {
            let duration = try? await item.asset.load(.duration)
            guard !Task.isCancelled else {
                AVPlayerPool.shared.release(player)
                if isA { isSettingUpA = false } else { isSettingUpB = false }
                return
            }

            // Detect load failure: if the asset couldn't produce a valid duration,
            // the file is missing, corrupt, or unsupported. Show the fallback UI
            // instead of a blank player. A nil duration means load(.duration) threw
            // (file missing/unreadable) — don't wait for item.status which may
            // still be .unknown at this point.
            guard let duration, CMTimeGetSeconds(duration).isFinite else {
                AVPlayerPool.shared.release(player)
                if isA { isSettingUpA = false } else { isSettingUpB = false }
                return
            }
            let seconds = CMTimeGetSeconds(duration)
            if isA {
                durationA = seconds
            } else {
                durationB = seconds
            }
        } else {
            // No current item at all — file couldn't be opened.
            AVPlayerPool.shared.release(player)
            if isA { isSettingUpA = false } else { isSettingUpB = false }
            return
        }

        guard !Task.isCancelled else {
            AVPlayerPool.shared.release(player)
            if isA { isSettingUpA = false } else { isSettingUpB = false }
            return
        }

        // Prime the player so frame-stepping works immediately
        await player.seek(to: .zero, toleranceBefore: .zero, toleranceAfter: .zero)
        guard !Task.isCancelled else {
            AVPlayerPool.shared.release(player)
            if isA { isSettingUpA = false } else { isSettingUpB = false }
            return
        }

        if isA {
            playerA = player
            isSettingUpA = false
        } else {
            playerB = player
            isSettingUpB = false
        }
        if isPlaying { player.rate = playbackSpeed }
    }

    private func tearDownPlayers() {
        let a = playerA
        let b = playerB
        playerA = nil
        playerB = nil
        isPlaying = false
        if let a { AVPlayerPool.shared.release(a) }
        if let b { AVPlayerPool.shared.release(b) }
    }

    // MARK: - Formatting

    static func formatTime(_ seconds: Double) -> String {
        guard seconds.isFinite && seconds >= 0 else { return "0:00" }
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return "\(mins):\(String(format: "%02d", secs))"
    }
}

// MARK: - AVPlayerView Representable

/// Wraps `AVPlayerView` from AVKit with optional leader time observation.
private struct PlayerRepresentable: NSViewRepresentable {
    let player: AVPlayer?
    var isLeader: Bool = false
    var onTimeUpdate: (@MainActor @Sendable (Double) -> Void)?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> AVPlayerView {
        let view = AVPlayerView()
        view.controlsStyle = .none
        view.player = player
        if onTimeUpdate != nil { installObserver(on: player, coordinator: context.coordinator) }
        return view
    }

    func updateNSView(_ nsView: AVPlayerView, context: Context) {
        guard nsView.player !== player else { return }
        // Remove old observer
        removeObserver(from: nsView.player, coordinator: context.coordinator)
        nsView.player = player
        if onTimeUpdate != nil { installObserver(on: player, coordinator: context.coordinator) }
    }

    static func dismantleNSView(_ nsView: AVPlayerView, coordinator: Coordinator) {
        if let observer = coordinator.timeObserver, let player = nsView.player {
            player.removeTimeObserver(observer)
            coordinator.timeObserver = nil
        }
    }

    private func installObserver(on player: AVPlayer?, coordinator: Coordinator) {
        guard let player else { return }
        let interval = CMTime(value: 1, timescale: 30) // 30Hz
        let callback = onTimeUpdate
        coordinator.timeObserver = player.addPeriodicTimeObserver(
            forInterval: interval,
            queue: .main
        ) { time in
            let seconds = CMTimeGetSeconds(time)
            MainActor.assumeIsolated {
                callback?(seconds)
            }
        }
    }

    private func removeObserver(from player: AVPlayer?, coordinator: Coordinator) {
        if let observer = coordinator.timeObserver, let player {
            player.removeTimeObserver(observer)
            coordinator.timeObserver = nil
        }
    }

    final class Coordinator {
        var timeObserver: Any?
    }
}

#if DEBUG
#Preview("Video Comparison") {
    VideoComparisonView(
        pathA: "/System/Library/Compositions/Fish.mov",
        pathB: "/System/Library/Compositions/Sunset.mov"
    )
    .frame(width: 800, height: 500)
}
#endif
