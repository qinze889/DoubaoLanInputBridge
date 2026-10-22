import Foundation

@main struct ShareImportChecks {
    static func main() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("shengjian-share-check-" + UUID().uuidString)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: root) }
        let input = root.appendingPathComponent("截屏 😀.png")
        let content = Data([0, 1, 2, 3, 255])
        try content.write(to: input)
        let batch = try ShareImport.makeBatch(in: root.appendingPathComponent("inbox"))
        let a = try ShareImport.copy(input, into: batch)
        let b = try ShareImport.copy(input, into: batch)
        precondition(a != b && a.lastPathComponent == input.lastPathComponent)
        try fm.removeItem(at: input)
        let aData = try Data(contentsOf: a), bData = try Data(contentsOf: b)
        let fileAttributes = try fm.attributesOfItem(atPath: a.path)
        let folderAttributes = try fm.attributesOfItem(atPath: batch.path)
        precondition(aData == content && bData == content)
        precondition((fileAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
        precondition((folderAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700)
        let link = root.appendingPathComponent("link.png")
        try fm.createSymbolicLink(at: link, withDestinationURL: a)
        for invalid in [root, link, URL(string: "https://example.com/screenshot.png")!] {
            do { _ = try ShareImport.copy(invalid, into: batch); fatalError("Accepted invalid file") }
            catch ShareImport.Failure.invalidFile { }
        }
        let huge = root.appendingPathComponent("huge.bin")
        _ = fm.createFile(atPath: huge.path, contents: nil)
        let handle = try FileHandle(forWritingTo: huge)
        try handle.truncate(atOffset: UInt64(ShareImport.maximumFileBytes + 1))
        try handle.close()
        do { _ = try ShareImport.copy(huge, into: batch); fatalError("Accepted oversized file") }
        catch ShareImport.Failure.tooLarge { }
        print("Shared-file checks passed: temporary-file ownership, Unicode, collisions, permissions, unsafe inputs and size limit.")
    }
}
