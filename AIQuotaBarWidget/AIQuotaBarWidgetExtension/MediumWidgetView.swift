import SwiftUI
import WidgetKit

struct MediumWidgetView: View {
    let entry: QuotaEntry

    var body: some View {
        if let snap = entry.snapshot {
            contentView(snap)
                .opacity(entry.isStale ? 0.55 : 1)
                .overlay(alignment: .topTrailing) {
                    if entry.isStale { StaleBadge(writtenAt: entry.writtenAt) }
                }
                .containerBackground(.fill.tertiary, for: .widget)
        } else {
            noDataView
                .containerBackground(.fill.tertiary, for: .widget)
        }
    }

    // One horizontal row per provider, providers stacked vertically.
    private func contentView(_ snap: UsageSnapshot) -> some View {
        let providers = entry.providers
        let compact = providers.count > 3

        return VStack(spacing: 0) {
            ForEach(Array(providers.enumerated()), id: \.offset) { idx, provider in
                if idx > 0 {
                    Rectangle()
                        .fill(.quaternary)
                        .frame(height: 1)
                }
                providerRow(snap: snap, provider: provider, showReset: !compact)
                    .frame(maxHeight: .infinity)
            }
        }
    }

    private func providerRow(snap: UsageSnapshot, provider: AIProvider, showReset: Bool) -> some View {
        let data = provider.displayData(from: snap)
        return HStack(alignment: .center, spacing: 12) {
            HStack(spacing: 6) {
                providerIcon(provider, size: 16)
                Text(provider.displayName)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(provider.color)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .frame(width: 90, alignment: .leading)

            if let error = data.error {
                Text(error)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if data.isConfigured {
                ForEach(data.rows.prefix(2), id: \.label) { row in
                    limitSegment(row, accent: provider.color, showReset: showReset)
                }
            } else {
                Text("Not set up")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(.vertical, 4)
    }

    private func limitSegment(_ row: LimitRow, accent: Color, showReset: Bool) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(alignment: .firstTextBaseline) {
                // Cursor's dollar labels ("$2,505/$3,500") are much wider than
                // "5H"/"7D" and would otherwise truncate in the shared segment.
                Text(row.label)
                    .font(.system(size: 10))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
                Spacer(minLength: 3)
                Text("\(row.pct)%")
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .foregroundStyle(colorForPct(row.pct, accent: accent))
            }
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule().fill(.quaternary)
                    Capsule()
                        .fill(colorForPct(row.pct, accent: accent).opacity(0.85))
                        .frame(width: max(2, geo.size.width * CGFloat(row.pct) / 100))
                }
            }
            .frame(height: 3)
            if showReset && !row.resetStr.isEmpty {
                Text(row.resetStr)
                    .font(.system(size: 8))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder
    private func providerIcon(_ provider: AIProvider, size: CGFloat) -> some View {
        if provider.iconNeedsTemplate {
            Image(provider.iconName)
                .renderingMode(.template)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: size, height: size)
                .foregroundStyle(provider.color)
        } else {
            Image(provider.iconName)
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: size, height: size)
        }
    }

    private var noDataView: some View {
        VStack(spacing: 6) {
            Image(systemName: "chart.bar")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text("Run AIQuotaBar to see usage")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func colorForPct(_ pct: Int, accent: Color) -> Color {
        if pct >= 95 { return .red }
        if pct >= 80 { return .orange }
        return accent
    }
}

// MARK: - Stale badge

/// Shown when the cache stopped being updated (app quit, or the reload nudge
/// broke). Without it the widget renders week-old numbers that look current.
struct StaleBadge: View {
    let writtenAt: Date?

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: "exclamationmark.arrow.trianglehead.2.clockwise.rotate.90")
                .font(.system(size: 8, weight: .semibold))
            if let date = writtenAt {
                Text(date, style: .relative) + Text(" old")
            } else {
                Text("stale")
            }
        }
        .font(.system(size: 8))
        .foregroundStyle(.orange)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(Capsule().fill(.orange.opacity(0.15)))
    }
}
