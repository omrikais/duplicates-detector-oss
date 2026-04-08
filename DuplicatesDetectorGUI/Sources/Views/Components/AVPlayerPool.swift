import AVFoundation

/// Reusable pool of `AVPlayer` instances to avoid repeated allocation/deallocation
/// during rapid pair navigation. Hard-capped at 2 active players.
@MainActor
final class AVPlayerPool {
    static let shared = AVPlayerPool()

    private var available: [AVPlayer] = []
    private let maxPooled = 2

    /// Returns a player loaded with the given URL. Reuses a pooled instance when available.
    func acquire(for url: URL) -> AVPlayer {
        if let reused = available.popLast() {
            reused.replaceCurrentItem(with: AVPlayerItem(url: url))
            return reused
        }
        return AVPlayer(url: url)
    }

    /// Pauses and returns a player to the pool for reuse.
    /// Guards against double-release: if the player is already in the pool, this is a no-op.
    func release(_ player: AVPlayer) {
        guard !available.contains(where: { $0 === player }) else { return }
        player.pause()
        player.replaceCurrentItem(with: nil)
        if available.count < maxPooled {
            available.append(player)
        }
    }
}
