// swift-tools-version: 5.9
import PackageDescription
let package = Package(
    name: "ShengjianClient", platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "ShengjianClient", targets: ["ShengjianClient"])],
    targets: [.target(name: "ShengjianClient"), .executableTarget(name: "ClientChecks", dependencies: ["ShengjianClient"], path: "Checks"), .testTarget(name: "ShengjianClientTests", dependencies: ["ShengjianClient"])])
