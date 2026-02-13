// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "tproj",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "tproj", targets: ["TprojApp"])
    ],
    targets: [
        .executableTarget(
            name: "TprojApp",
            path: "Sources/TprojApp"
        )
    ]
)
