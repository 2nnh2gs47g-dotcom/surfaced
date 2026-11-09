import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var model = ScanViewModel()
    @State private var showServer = false

    var body: some View {
        NavigationStack {
            Group {
                switch model.outcome {
                case .full(let report):
                    ReportView(report: report)
                case .preview(let preview):
                    PreviewReportView(preview: preview)
                case nil:
                    ScanFormView(model: model)
                }
            }
            .navigationTitle("Surfaced")
            .toolbar {
                if model.outcome != nil {
                    ToolbarItem(placement: .navigationBarLeading) {
                        Button("New scan") { model.reset() }
                            .accessibilityHint("Clears this report and returns to the address field")
                    }
                }
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Server") { showServer = true }
                        .accessibilityHint("Set the HTTPS address of your Surfaced server")
                }
            }
            .sheet(isPresented: $showServer) {
                ServerSettingsView(model: model)
            }
        }
    }
}

private struct ScanFormView: View {
    @ObservedObject var model: ScanViewModel

    var body: some View {
        Form {
            Section {
                TextField("example.com", text: $model.website)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .accessibilityLabel("Website address")
                    .submitLabel(.go)
                    .onSubmit {
                        if !model.isLoading { model.scan() }
                    }
            } header: {
                Text("Website")
            } footer: {
                Text("Checks how well AI assistants can find and quote this site.")
            }

            Section {
                Button(action: model.scan) {
                    if model.isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .accessibilityLabel("Scanning")
                            Text("Scanning")
                        }
                    } else {
                        Text("Scan")
                    }
                }
                .disabled(model.isLoading)
                .accessibilityHint("Starts a scan on your Surfaced server")
            }

            if case .failed(let message) = model.phase {
                Section {
                    Text(message)
                        .foregroundStyle(.red)
                        .accessibilityLabel("Error. \(message)")
                    Button("Retry", action: model.retry)
                        .disabled(model.isLoading)
                }
            }

            Section {
                Text(model.backendBase.isEmpty ? "No server set" : model.backendBase)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                    .accessibilityLabel(
                        model.backendBase.isEmpty
                            ? "No server set"
                            : "Server \(model.backendBase)"
                    )
            } header: {
                Text("Server")
            } footer: {
                Text("Enter the HTTPS origin of a Surfaced server you control. The app calls /api/scan on that host. No server address is built in.")
            }
        }
    }
}

private struct PreviewReportView: View {
    let preview: ScanPreview

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text("This is a preview. The full report is available on the Surfaced website.")
                    .font(.body)
                    .accessibilityAddTraits(.isHeader)

                VStack(alignment: .leading, spacing: 4) {
                    Text("Overall")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("\(preview.scores.overall)")
                        .font(.system(size: 56, weight: .semibold, design: .rounded))
                        .accessibilityLabel("Overall score \(preview.scores.overall) out of 100")
                    Text("Grade \(preview.grade)")
                        .font(.headline)
                    Text(preview.vertical.label)
                        .font(.body)
                    Text(preview.vertical.weighting)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Detected from \(preview.vertical.detectedFrom)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(preview.title)
                        .font(.title3.weight(.semibold))
                    Text(preview.url)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Text("Checked \(preview.checkedAt)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Text("Top fix")
                    .font(.title3.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)

                if let item = preview.topFix {
                    RecommendationRow(item: item)
                } else {
                    Text("The preview did not include a top fix.")
                        .foregroundStyle(.secondary)
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct ReportView: View {
    let report: ScanReport

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Overall")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("\(report.scores.overall)")
                        .font(.system(size: 56, weight: .semibold, design: .rounded))
                        .accessibilityLabel("Overall score \(report.scores.overall) out of 100")
                    Text("Grade \(report.grade)")
                        .font(.headline)
                    Text(report.vertical.label)
                        .font(.body)
                    Text(report.vertical.weighting)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Detected from \(report.vertical.detectedFrom)")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 8) {
                    LabeledScore(name: "GEO", value: report.scores.geo)
                    LabeledScore(name: "AEO", value: report.scores.aeo)
                    LabeledScore(name: "Reviews", value: report.scores.reviews)
                    LabeledScore(name: "Social", value: report.scores.social)
                }
                .accessibilityElement(children: .combine)

                VStack(alignment: .leading, spacing: 6) {
                    Text(report.title)
                        .font(.title3.weight(.semibold))
                    Text(report.url)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                    Text("Checked \(report.checkedAt) · \(report.wordCount) words")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                Text(report.summary)
                    .font(.body)

                if report.javascriptRendered {
                    Text("This page looks JavaScript-rendered, so some content may be missing from the scan.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }

                Text("Prioritized fixes")
                    .font(.title3.weight(.semibold))
                    .accessibilityAddTraits(.isHeader)

                if report.recommendations.isEmpty {
                    Text("The report did not include any prioritized fixes.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(Array(report.recommendations.enumerated()), id: \.offset) { _, item in
                        RecommendationRow(item: item)
                    }
                }
            }
            .padding()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct LabeledScore: View {
    let name: String
    let value: Int

    var body: some View {
        HStack {
            Text(name)
            Spacer()
            Text("\(value)")
                .monospacedDigit()
                .accessibilityLabel("\(name) \(value) out of 100")
        }
        .font(.body)
    }
}

private struct RecommendationRow: View {
    let item: ScanRecommendation

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(item.priority.isEmpty ? "Fix" : item.priority)
                .font(.caption.weight(.semibold))
            Text(item.label)
                .font(.headline)
            Text(item.observed)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Text(item.fix)
                .font(.body)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(item.priority.isEmpty ? "Unspecified" : item.priority) priority. \(item.label). Observed: \(item.observed). Fix: \(item.fix)"
        )
    }
}

private struct ServerSettingsView: View {
    @ObservedObject var model: ScanViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://scan.example.com", text: $model.backendBase)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .accessibilityLabel("Surfaced server origin")
                } footer: {
                    Text("HTTPS only. Use the origin with no path, for example https://scan.example.com. The app requests /api/scan on that origin.")
                }
            }
            .navigationTitle("Server")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        model.saveBackend()
                        dismiss()
                    }
                }
            }
        }
    }
}

#if DEBUG
#Preview("Report sample") {
    NavigationStack {
        ReportView(report: .sample)
    }
}
#endif
