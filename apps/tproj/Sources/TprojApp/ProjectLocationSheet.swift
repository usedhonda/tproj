import SwiftUI

/// Edits the configured location, not a running pane. A live column must be closed first.
struct ProjectLocationSheet: View {
    @Binding var projects: [WorkspaceProject]
    @Binding var statusText: String
    let livePaths: Set<String>
    let liveProjectKeys: Set<String>
    let save: () async -> Bool
    @Environment(\.dismiss) private var dismiss

    private func location(_ index: Int) -> Binding<String> {
        Binding(
            get: { projects[index].type },
            set: { destination in
                var project = projects[index]
                if project.type == "remote" { project.remotePath = project.path }
                else { project.localPath = project.path }
                project.type = destination
                project.path = destination == "remote" ? project.remotePath : project.localPath
                projects[index] = project
            }
        )
    }

    private func activePath(_ index: Int) -> Binding<String> {
        Binding(
            get: { projects[index].path },
            set: { value in
                projects[index].path = value
                if projects[index].type == "remote" { projects[index].remotePath = value }
                else { projects[index].localPath = value }
            }
        )
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Project locations").font(.headline)
            Text("Local projects run on this Mac. Remote projects keep CC and Cdx on the selected SSH host.")
                .font(.caption)
                .foregroundStyle(.secondary)

            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(projects.indices, id: \.self) { index in
                        let project = projects[index]
                        let live = livePaths.contains(project.path) || liveProjectKeys.contains("\(project.host)|\(project.path)")
                        GroupBox {
                            VStack(alignment: .leading, spacing: 6) {
                                HStack {
                                    TextField("Alias", text: $projects[index].alias)
                                        .frame(width: 130)
                                    Picker("Runs on", selection: location(index)) {
                                        Text("This Mac").tag("local")
                                        Text("SSH host").tag("remote")
                                    }
                                    .pickerStyle(.segmented)
                                }
                                TextField(projects[index].type == "remote" ? "Path on server" : "Path on this Mac", text: activePath(index))
                                    .textFieldStyle(.roundedBorder)
                                if projects[index].type == "remote" {
                                    TextField("SSH host", text: $projects[index].host)
                                        .textFieldStyle(.roundedBorder)
                                }
                                if live {
                                    Text("Close this column before changing its location.")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .disabled(live)
                        }
                    }
                }
            }
            Text(statusText).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            HStack {
                Button("Add project") {
                    projects.append(WorkspaceProject(path: "", type: "local", host: "", alias: "", enabled: false))
                }
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Save") {
                    Task { if await save() { dismiss() } }
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(18)
        .frame(width: 560, height: 480)
    }
}
