import Foundation

enum ShareImport {
    static let maximumFiles = 16
    static let maximumFileBytes = 256 * 1024 * 1024

    enum Failure: LocalizedError {
        case invalidFile, tooLarge, tooManyFiles
        var errorDescription: String? {
            switch self {
            case .invalidFile: return "只能添加本机的普通文件，请重新选择。"
            case .tooLarge: return "系统分享单个文件上限为 256 MB。"
            case .tooManyFiles: return "一次最多添加 16 个文件。"
            }
        }
    }

    static func makeBatch(in parent: URL) throws -> URL {
        let folder = parent.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true,
                                                attributes: [.posixPermissions: 0o700])
        return folder
    }

    // NSItemProvider URLs may disappear when their callback or extension finishes.
    // Own a private copy before handing the file to another process or a transfer.
    static func copy(_ source: URL, into folder: URL, suggestedName: String? = nil) throws -> URL {
        guard source.isFileURL else { throw Failure.invalidFile }
        let scoped = source.startAccessingSecurityScopedResource()
        defer { if scoped { source.stopAccessingSecurityScopedResource() } }
        let values = try source.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
        guard values.isRegularFile == true, values.isSymbolicLink != true else { throw Failure.invalidFile }
        guard let size = values.fileSize, size <= maximumFileBytes else { throw Failure.tooLarge }
        var name = ((suggestedName ?? source.lastPathComponent) as NSString).lastPathComponent
        if name.isEmpty || name == "." || name == ".." || name.utf8.count > 200 { name = "分享文件-\(UUID().uuidString).\(source.pathExtension.prefix(12))" }
        var target = folder.appendingPathComponent(name)
        var number = 1
        while FileManager.default.fileExists(atPath: target.path) {
            target = folder.appendingPathComponent("\(number)-\(name)"); number += 1
        }
        do {
            try FileManager.default.copyItem(at: source, to: target)
            let copied = try target.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard copied.isRegularFile == true, copied.isSymbolicLink != true else { throw Failure.invalidFile }
            guard let copiedSize = copied.fileSize, copiedSize <= maximumFileBytes else { throw Failure.tooLarge }
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
            return target
        } catch {
            try? FileManager.default.removeItem(at: target)
            throw error
        }
    }
}
