# Loop state — 手元専用の契約試験を緑にする

## Budget
iteration 上限 6 / no-progress 2

## Baseline (2026-09-20 実測)
- test-project-bootstrap-contract.sh: exit 1, 出力なし（仮の HOME での install.sh --check で落ちる）
- test-registry-contract.sh: PASS=3 FAIL=1（P1_router_peer_writes_pid_start, harness error rc=3）

## Done
(まだ無し)

## Failed / blocked
(まだ無し)

## Next step
仮の HOME を作る bootstrap 試験の準備手順を再現し、`HOME=<tmp> ./install.sh --check` を試験の外で直接実行して、stderr から何が足りないかを特定する。
