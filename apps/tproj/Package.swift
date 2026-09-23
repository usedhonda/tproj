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
    dependencies: [
        // v1.5 uses forkpty and has no optional Metal toolchain requirement.
        .package(url: "https://github.com/migueldeicaza/SwiftTerm.git", exact: "1.5.1")
    ],
    targets: [
        .target(
            name: "TprojLogic",
            path: "Sources/TprojLogic"
        ),
        .executableTarget(
            name: "TprojApp",
            dependencies: ["TprojLogic", .product(name: "SwiftTerm", package: "SwiftTerm")],
            path: "Sources/TprojApp"
        ),
        .testTarget(
            name: "TprojLogicTests",
            dependencies: ["TprojLogic"],
            path: "Tests/TprojLogicTests"
        )
    ]
)
