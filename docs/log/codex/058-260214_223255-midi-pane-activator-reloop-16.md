# 指示内容
- DJ機器（Reloop）にある16ボタンで、tproj画面の16個の tmux pane をアクティブ化できるようにする。
- 既存の類似実装 `/Users/usedhonda/projects/Mac/dj_presenter` を参考にする。
- Plan合意内容を実装する。

# 実施内容
- `apps/tproj/Sources/TprojApp/main.swift` に CoreMIDI を統合。
- 追加実装:
  - `MIDIBinding`, `StoredMIDIBinding`, `MIDILearnStore`（UserDefaults永続化）
  - `MIDIPaneActivator`（CoreMIDIクライアント/入力ポート/ソース接続/NoteOn受信/学習/slot発火）
  - `MIDIPacket` bytes 補助 extension
- `AppViewModel` へMIDI統合:
  - `isMIDILearning` 追加
  - 起動時 `startMIDIIfNeeded()` で自動接続
  - `toggleMIDILearn()` 追加
  - `activatePaneForMIDISlot(_:)` 追加
    - `tmux list-panes` で pane_index 存在確認
    - `tmux select-window -t tproj-workspace:dev`
    - `tmux select-pane -t tproj-workspace:dev.<slot>`
- UI追加:
  - Current上部に `Learn` ボタンを追加（状態によりトーン切替）
  - 詳細パネルは追加せず、状態は `statusText` のみ表示
- ビルドと起動確認:
  - `apps/tproj/build-app.sh` 成功
  - `open apps/tproj/dist/tproj.app` 再起動実施、プロセス起動確認（PID 50157）

# 課題、検討事項
- ハードウェア押下の実機確認（ボタン学習→16スロット切替）はユーザー操作で最終確認が必要。
- 初版は Note On（velocity>0）のみ学習/反応対象。必要ならCC対応を拡張可能。
- 接続対象名判定は `reloop` / `ready` 優先、未検出時は全source接続フォールバック。
