import SwiftUI
import WidgetKit

@main
struct AIQuotaBarHostApp: App {
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // The menu bar app runs `open -g -a AIQuotaBarHost --args --reload-widget`
        // after every fetch. Reload and exit before the WindowGroup below is built,
        // otherwise each refresh leaves a stray window on screen.
        if CommandLine.arguments.contains("--reload-widget") {
            WidgetCenter.shared.reloadAllTimelines()
            Thread.sleep(forTimeInterval: 0.5)  // let the XPC reach chronod
            exit(0)
        }
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .onAppear {
                    // Reload widget timelines whenever the host app opens
                    WidgetCenter.shared.reloadAllTimelines()
                }
        }
        .defaultSize(width: 400, height: 300)
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                WidgetCenter.shared.reloadAllTimelines()
            }
        }
    }
}
