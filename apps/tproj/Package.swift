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
        .target(
            name: "TprojLogic",
            path: "Sources/TprojLogic"
        ),
        .executableTarget(
            name: "TprojApp",
            dependencies: ["TprojLogic"],
            path: "Sources/TprojApp"
        ),
        .testTarget(
            name: "TprojLogicTests",
            dependencies: ["TprojLogic"],
            path: "Tests/TprojLogicTests"
        )
    ]
)
