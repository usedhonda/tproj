import Foundation
import Darwin

/// Retains only the files used by the current view. Metadata checks belong on the
/// refresh path; asking for a value while laying out a view never touches disk.
/// Confine an instance to its owner's executor (the GUI uses the main actor).
public final class FileResourceCache<Value> {
    private struct Revision: Equatable {
        let modificationSeconds: Int
        let modificationNanoseconds: Int
        let size: off_t
        let device: dev_t
        let fileNumber: ino_t
    }

    private struct Entry {
        let revision: Revision?
        let value: Value?
    }

    private var entries: [String: Entry] = [:]
    private let load: (String) -> Value?

    public init(load: @escaping (String) -> Value?) {
        self.load = load
    }

    /// Returns whether file membership or a file revision changed. Failed loads
    /// are retained too: a corrupt file is retried when it is replaced or edited.
    @discardableResult
    public func refresh(paths: Set<String>) -> Bool {
        var changed = Set(entries.keys) != paths
        if changed { entries = entries.filter { paths.contains($0.key) } }
        for path in paths {
            let revision = fileRevision(atPath: path)
            if let entry = entries[path], entry.revision == revision { continue }
            entries[path] = Entry(revision: revision, value: revision == nil ? nil : load(path))
            changed = true
        }
        return changed
    }

    public func value(atPath path: String) -> Value? {
        entries[path]?.value
    }

    /// Matches file-existence filtering even when a present image cannot decode.
    public func containsFile(atPath path: String) -> Bool {
        entries[path]?.revision != nil
    }

    public func removeAll() {
        entries.removeAll()
    }

    private func fileRevision(atPath path: String) -> Revision? {
        // One fstatat follows image symlinks without walking the path in user space
        // or allocating an attribute dictionary on every geometry poll.
        var info = stat()
        let result = path.withCString { Darwin.fstatat(AT_FDCWD, $0, &info, 0) }
        guard result == 0 else { return nil }
        return Revision(
            modificationSeconds: info.st_mtimespec.tv_sec,
            modificationNanoseconds: info.st_mtimespec.tv_nsec,
            size: info.st_size,
            device: info.st_dev,
            fileNumber: info.st_ino
        )
    }
}
