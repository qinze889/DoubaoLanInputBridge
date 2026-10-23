import AppKit
import UniformTypeIdentifiers

@objc(ShengjianShareViewController)
final class ShareViewController: NSViewController {
    private let status = NSTextField(wrappingLabelWithString: "正在添加到声笺…")
    private var started = false
    private var task: Task<Void, Never>?

    override func loadView() {
        let title = NSTextField(labelWithString: "发送到声笺")
        title.font = .systemFont(ofSize: 19, weight: .semibold)
        status.textColor = .secondaryLabelColor
        let cancel = NSButton(title: "取消", target: self, action: #selector(cancelShare))
        let stack = NSStackView(views: [title, status, cancel])
        stack.orientation = .vertical
        stack.spacing = 16
        stack.edgeInsets = NSEdgeInsets(top: 24, left: 24, bottom: 24, right: 24)
        stack.frame = NSRect(x: 0, y: 0, width: 340, height: 160)
        view = stack
        preferredContentSize = stack.frame.size
    }

    override func viewDidAppear() {
        super.viewDidAppear()
        guard !started else { return }
        started = true
        task = Task { await receive() }
    }

    @objc private func cancelShare() {
        task?.cancel()
        extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
    }

    private func receive() async {
        do {
            let items = extensionContext?.inputItems.compactMap { $0 as? NSExtensionItem } ?? []
            let providers = items.flatMap { $0.attachments ?? [] }
            guard !providers.isEmpty else { throw ShareImport.Failure.invalidFile }
            guard providers.count <= ShareImport.maximumFiles else { throw ShareImport.Failure.tooManyFiles }
            let cache = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            let folder = try ShareImport.makeBatch(in: cache.appendingPathComponent("ShengjianShareInbox"))
            var files: [URL] = []
            do {
                for provider in providers {
                    try Task.checkCancellation()
                    files.append(try await receive(provider, into: folder))
                }
                try Task.checkCancellation()
                let app = Bundle.main.bundleURL.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
                guard Bundle(url: app)?.bundleIdentifier == Bundle.main.bundleIdentifier?.replacingOccurrences(of: ".share", with: "") else { throw ShareImport.Failure.invalidFile }
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                    NSWorkspace.shared.open(files, withApplicationAt: app, configuration: NSWorkspace.OpenConfiguration()) { _, error in
                        if let error { continuation.resume(throwing: error) }
                        else { continuation.resume() }
                    }
                }
            } catch {
                try? FileManager.default.removeItem(at: folder)
                throw error
            }
            // Keep the copies until the containing app has consumed the open-file event.
            extensionContext?.completeRequest(returningItems: [], completionHandler: nil)
        } catch is CancellationError {
            return
        } catch {
            status.stringValue = "无法添加：\(error.localizedDescription)"
        }
    }

    private func receive(_ provider: NSItemProvider, into folder: URL) async throws -> URL {
        if let identifier = provider.registeredTypeIdentifiers.first(where: { UTType($0)?.conforms(to: .image) == true }) {
            let suggestedName = provider.suggestedName ?? "截屏"
            return try await withCheckedThrowingContinuation { continuation in
                provider.loadFileRepresentation(forTypeIdentifier: identifier) { url, error in
                    do {
                        guard let url else { throw error ?? ShareImport.Failure.invalidFile }
                        let ext = UTType(identifier)?.preferredFilenameExtension ?? url.pathExtension
                        let stem = (suggestedName as NSString).deletingPathExtension
                        let name = stem + "." + ext
                        continuation.resume(returning: try ShareImport.copy(url, into: folder, suggestedName: name))
                    } catch { continuation.resume(throwing: error) }
                }
            }
        }
        guard provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) else { throw ShareImport.Failure.invalidFile }
        return try await withCheckedThrowingContinuation { continuation in
            provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { value, error in
                do {
                    guard let url = value as? URL else { throw error ?? ShareImport.Failure.invalidFile }
                    continuation.resume(returning: try ShareImport.copy(url, into: folder))
                } catch { continuation.resume(throwing: error) }
            }
        }
    }
}
