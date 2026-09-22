import WidgetKit

struct QuotaEntry: TimelineEntry {
    let date: Date
    let snapshot: UsageSnapshot?
    let isStale: Bool
    let providers: [AIProvider]
    /// When the cache was written -- drives the "stale" badge's age text.
    var writtenAt: Date? = nil

    static let placeholder = QuotaEntry(
        date: .now,
        snapshot: UsageSnapshot(
            version: 1,
            updatedAt: ISO8601DateFormatter().string(from: .now),
            claude: ClaudeUsage(
                session: LimitRow(label: "5H", pct: 36, resetStr: "resets in 2h 14m"),
                weeklyAll: LimitRow(label: "7D", pct: 83, resetStr: "resets Wed 23:00"),
                weeklySonnet: nil,
                scoped: nil,
                overagesEnabled: false
            ),
            chatgpt: ChatGPTUsage(
                rows: [LimitRow(label: "7D", pct: 12, resetStr: "resets Thu 05:38")],
                error: nil
            ),
            claudeCode: ClaudeCodeUsage(todayMessages: 42, weekMessages: 312),
            cursor: nil,
            copilot: nil,
            activeProviders: ["chatgpt", "cursor"],
            barProviders: nil
        ),
        isStale: false,
        providers: [.chatgpt, .cursor]
    )

    static let empty = QuotaEntry(
        date: .now,
        snapshot: nil,
        isStale: false,
        providers: [.chatgpt, .cursor]
    )
}
