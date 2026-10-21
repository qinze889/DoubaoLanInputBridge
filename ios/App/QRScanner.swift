import SwiftUI
import AVFoundation

struct QRScanner: UIViewControllerRepresentable {
    var scanned: (String) -> Void
    func makeUIViewController(context: Context) -> CameraController { CameraController(scanned: scanned) }
    func updateUIViewController(_ controller: CameraController, context: Context) {}
    static func dismantleUIViewController(_ controller: CameraController, coordinator: ()) { controller.stop() }
}
final class CameraController: UIViewController, AVCaptureMetadataOutputObjectsDelegate, @unchecked Sendable {
    let session = AVCaptureSession()
    let queue = DispatchQueue(label: "Shengjian.Camera")
    let scanned: (String) -> Void
    var didScan = false
    var stopped = false
    var preview: AVCaptureVideoPreviewLayer?
    let hint = UILabel()
    init(scanned: @escaping (String) -> Void) { self.scanned = scanned; super.init(nibName: nil, bundle: nil) }
    required init?(coder: NSCoder) { fatalError("Not supported") }
    override func viewDidLoad() {
        super.viewDidLoad(); view.backgroundColor = .black
        hint.text = "将 Mac 上的连接二维码放入画面"; hint.textColor = .white; hint.numberOfLines = 0; hint.textAlignment = .center
        hint.translatesAutoresizingMaskIntoConstraints = false; view.addSubview(hint)
        NSLayoutConstraint.activate([hint.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 24), hint.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -24), hint.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -36)])
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: configure()
        case .notDetermined: AVCaptureDevice.requestAccess(for: .video) { allowed in DispatchQueue.main.async { if allowed { self.configure() } else { self.denied() } } }
        default: denied()
        }
    }
    func denied() { hint.text = "请在系统设置中允许相机，或返回使用配对链接。" }
    func configure() {
        guard !stopped else { return }
        guard let camera = AVCaptureDevice.default(for: .video), let input = try? AVCaptureDeviceInput(device: camera), session.canAddInput(input) else { denied(); return }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output); output.setMetadataObjectsDelegate(self, queue: .main); output.metadataObjectTypes = [.qr]
        let layer = AVCaptureVideoPreviewLayer(session: session); layer.videoGravity = .resizeAspectFill
        view.layer.insertSublayer(layer, at: 0); preview = layer
        queue.async { self.session.startRunning() }
    }
    override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); preview?.frame = view.bounds }
    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput metadataObjects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !didScan, let value = (metadataObjects.first as? AVMetadataMachineReadableCodeObject)?.stringValue else { return }
        didScan = true; stop(); scanned(value)
    }
    func stop() { stopped = true; queue.async { self.session.stopRunning() } }
}
