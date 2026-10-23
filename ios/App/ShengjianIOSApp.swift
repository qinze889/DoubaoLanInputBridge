import SwiftUI
import UniformTypeIdentifiers
import PhotosUI
import CoreTransferable
import ShengjianClient

private typealias ViewState<Value> = SwiftUI.State<Value>

@main struct ShengjianIOSApp: App {
    @StateObject private var store = ConnectionStore()
    var body: some Scene { WindowGroup { HomeView().environmentObject(store) } }
}

struct HomeView: View {
    @EnvironmentObject var store: ConnectionStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @ViewState private var text = ""
    @ViewState private var enter = true
    @ViewState private var addDevice = false
    @ViewState private var importFile = false
    @ViewState private var pasteFiles = true
    @ViewState private var tab = 0
    @ViewState private var photo: PhotosPickerItem?
    @ViewState private var shareURL: URL?
    @ViewState private var showShare = false
    var body: some View {
        TabView(selection: $tab) {
            NavigationStack {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        if let selected = store.selected {
                            HStack(spacing: 12) { Image(systemName: "desktopcomputer").font(.title2).foregroundStyle(.blue); VStack(alignment: .leading, spacing: 4) { Text(selected.name).font(.headline); Text(selected.isFixedRelay ? "固定公网连接" : selected.baseURL.scheme == "https" ? "Cloudflare 公网连接" : "局域网连接").font(.caption).foregroundStyle(.secondary) }; Spacer(); Image(systemName: "lock.shield").foregroundStyle(.green) }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 22))
                            VStack(alignment: .leading, spacing: 16) {
                                Text("想说什么？").font(.title3.bold())
                                TextEditor(text: $text).font(.body).frame(minHeight: 170).scrollContentBackground(.hidden).padding(12).background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16)).accessibilityLabel("发送到 Mac 的文字")
                                Toggle("发送后回车", isOn: $enter).font(.subheadline)
                                Button { Task { if await store.send(text, enter: enter) { text = "" } } } label: { HStack { Spacer(); if store.busy { ProgressView().tint(.white) } else { Label("发送到 Mac", systemImage: "arrow.up") }; Spacer() }.font(.headline).padding(.vertical, 8) }.buttonStyle(.borderedProminent).buttonBorderShape(.roundedRectangle(radius: 16)).disabled(store.busy || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                            }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 24))
                            VStack(spacing: 16) {
                                HStack { Label("照片与文件", systemImage: "photo.on.rectangle").font(.headline); Spacer() }
                                Toggle("上传后粘贴到 Mac", isOn: $pasteFiles).font(.subheadline)
                                HStack {
                                    PhotosPicker(selection: $photo, matching: .any(of: [.images, .videos])) { Label("照片 / 视频", systemImage: "photo") }.buttonStyle(.bordered)
                                    Spacer()
                                    Button { importFile = true } label: { Label("选择文件", systemImage: "folder") }.buttonStyle(.bordered)
                                }.disabled(store.busy)
                            }.padding(20).background(.background, in: RoundedRectangle(cornerRadius: 24))
                        } else {
                            VStack(spacing: 20) { Image(systemName: "iphone.radiowaves.left.and.right").font(.system(size: 56, weight: .light)).foregroundStyle(.blue); Text("把手机和 Mac 连起来").font(.title2.bold()); Text("扫描声笺上的二维码，\n在外面也能把想法送到 Mac。").multilineTextAlignment(.center).foregroundStyle(.secondary); Button("连接一台 Mac") { addDevice = true }.buttonStyle(.borderedProminent).controlSize(.large) }.frame(maxWidth: .infinity).padding(.vertical, 60)
                        }
                    }.padding(20)
                }.background(Color(.systemGroupedBackground)).navigationTitle("声笺")
                  .toolbar { ToolbarItem(placement: .topBarTrailing) { Button { addDevice = true } label: { Image(systemName: "qrcode.viewfinder") } } }
            }.tabItem { Label("发送", systemImage: "paperplane") }.tag(0)
            NavigationStack {
                List {
                    ForEach(store.shared) { item in
                        if item.type == "text" {
                            Button { UIPasteboard.general.string = item.text; store.completed("已复制文字") } label: { VStack(alignment: .leading, spacing: 8) { Text(item.text ?? "").foregroundStyle(.primary); Label("点击复制", systemImage: "doc.on.doc").font(.caption).foregroundStyle(.secondary) }.padding(.vertical, 8) }
                        } else {
                            Button { Task { if let url = await store.download(item) { shareURL = url; showShare = true } } } label: { Label(item.name ?? "文件", systemImage: "doc") }.disabled(store.busy)
                        }
                    }
                    if store.shared.isEmpty { ContentUnavailableView("还没有分享内容", systemImage: "tray", description: Text("在 Mac 点击分享后，内容会出现在这里。")) }
                }.navigationTitle("来自 Mac").refreshable { await store.refresh() }.task { await store.refresh() }
            }.tabItem { Label("来自 Mac", systemImage: "tray.and.arrow.down") }.tag(1)
            NavigationStack {
                List {
                    Section("已连接的机器") {
                        ForEach(store.connections) { connection in
                            Button { store.selectedID = connection.id; Task { await store.refresh() } } label: { HStack { Label(connection.name, systemImage: "desktopcomputer").foregroundStyle(.primary); Spacer(); if connection.id == store.selectedID { Image(systemName: "checkmark.circle.fill").foregroundStyle(.blue) } } }
                        }.onDelete { offsets in let ids = offsets.map { store.connections[$0].id }; for id in ids { store.remove(id) } }
                        Button { addDevice = true } label: { Label("添加另一台 Mac", systemImage: "plus.circle") }
                    }
                    Section { Link("设备、任务与语音对话", destination: URL(string: "https://test.xjiaoai.com/shengjian/api/v2/console")!) }
                    Section { Text("支持固定公网和 Cloudflare 连接。临时域名变化后，请重新扫码更新连接。").font(.footnote).foregroundStyle(.secondary) }
                }.navigationTitle("设备")
            }.tabItem { Label("设备", systemImage: "laptopcomputer.and.iphone") }.tag(2)
        }.tint(.blue).sensoryFeedback(.success, trigger: store.success)
          .overlay(alignment: .top) { if !store.notice.isEmpty { Label(store.notice, systemImage: "checkmark.circle.fill").font(.subheadline.weight(.medium)).padding(14).background(.regularMaterial, in: Capsule()).padding(.top, 4).transition(.move(edge: .top).combined(with: .opacity)) } }
          .animation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.82), value: store.notice)
          .sheet(isPresented: $addDevice) { AddDeviceView().environmentObject(store) }
          .sheet(isPresented: $showShare, onDismiss: { if let shareURL { try? FileManager.default.removeItem(at: shareURL.deletingLastPathComponent()) }; shareURL = nil }) { if let shareURL { SystemShare(items: [shareURL]) } }
          .fileImporter(isPresented: $importFile, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in if case .success(let files) = result { Task { await store.upload(files, paste: pasteFiles) } } }
          .onChange(of: photo) { _, value in Task { await uploadPhoto(value) } }
          .onChange(of: store.selectedID) { _, _ in Task { await store.refresh() } }
          .alert("连接提示", isPresented: Binding(get: { !store.error.isEmpty }, set: { if !$0 { store.error = "" } })) { Button("知道了") { store.error = "" } } message: { Text(store.error) }
    }
    func uploadPhoto(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        do {
            guard let media = try await item.loadTransferable(type: ImportedMedia.self) else { return }
            await store.upload([media.url], paste: pasteFiles)
            try? FileManager.default.removeItem(at: media.url.deletingLastPathComponent())
        } catch { store.error = "无法读取所选媒体，请改用文件选择器。" }
        photo = nil
    }
}
struct AddDeviceView: View {
    @EnvironmentObject var store: ConnectionStore
    @Environment(\.dismiss) private var dismiss
    @ViewState private var link = ""
    @ViewState private var name = "我的 Mac"
    @ViewState private var scanner = false
    var body: some View {
        NavigationStack {
            Form {
                Section { Button { scanner = true } label: { Label("扫描 Mac 连接二维码", systemImage: "qrcode.viewfinder") } }
                Section("或粘贴连接链接") { TextField("设备名称", text: $name); TextField("https://…/?key=…", text: $link).textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL).privacySensitive() }
                Section { Button { Task { if await store.add(link: link, name: name) { dismiss() } } } label: { HStack { Text("验证并连接"); Spacer(); if store.busy { ProgressView() } } }.disabled(store.busy || link.isEmpty) }
                Section { Text("配对信息存入本机 Keychain，不通过 iCloud 同步。").font(.footnote).foregroundStyle(.secondary) }
            }.navigationTitle("连接 Mac").toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
              .sheet(isPresented: $scanner) { QRScanner { value in link = value; scanner = false }.ignoresSafeArea() }
              .alert("连接提示", isPresented: Binding(get: { !store.error.isEmpty }, set: { if !$0 { store.error = "" } })) { Button("知道了") { store.error = "" } } message: { Text(store.error) }
        }
    }
}
struct SystemShare: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct ImportedMedia: Transferable {
    let url: URL
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .data) { received in
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let target = folder.appendingPathComponent(received.file.lastPathComponent)
            try FileManager.default.copyItem(at: received.file, to: target)
            return ImportedMedia(url: target)
        }
    }
}
