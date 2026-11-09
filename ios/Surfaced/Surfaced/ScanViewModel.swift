import Foundation

@MainActor
final class ScanViewModel: ObservableObject {
    @Published var website: String = ""
    @Published var backendBase: String
    @Published private(set) var phase: Phase = .idle
    @Published private(set) var outcome: ScanOutcome?

    enum Phase: Equatable {
        case idle
        case loading
        case failed(String)
    }

    private let client: ScanClient
    private var task: Task<Void, Never>?

    init(client: ScanClient = ScanClient(), backendBase: String? = nil) {
        self.client = client
        self.backendBase = backendBase ?? BackendSettings.load()
    }

    var isLoading: Bool { phase == .loading }

    func saveBackend() {
        let trimmed = backendBase.trimmingCharacters(in: .whitespacesAndNewlines)
        backendBase = trimmed
        BackendSettings.save(trimmed)
    }

    func scan() {
        let site = website
        let base = backendBase
        task?.cancel()
        phase = .loading
        outcome = nil
        task = Task {
            do {
                let outcome = try await client.scan(websiteRaw: site, backendBase: base)
                guard !Task.isCancelled else { return }
                self.outcome = outcome
                self.phase = .idle
            } catch is CancellationError {
                return
            } catch let failure as ScanFailure {
                guard !Task.isCancelled else { return }
                self.phase = .failed(failure.message)
            } catch {
                guard !Task.isCancelled else { return }
                self.phase = .failed("The scan could not be completed.")
            }
        }
    }

    func retry() {
        scan()
    }

    func reset() {
        task?.cancel()
        outcome = nil
        phase = .idle
    }
}
