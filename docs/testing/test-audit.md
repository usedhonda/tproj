# Test audit — 2026-10-22

Implementation follow-up: [F01–F17 remediation](test-audit-remediation.md). The
ledger below remains the original audit snapshot.

## 結論

現行の管理対象テスト **109ファイル / 19,444行**について、検査内容、本番接点、fixture・mock境界、重複、CIからの到達を台帳化した。**17件の改善・誤認防止事項**を特定した。これは17ファイルの削除提案ではない。同じファイルに有用な回帰検査と弱いassertが混在する。

特に優先するのは、**製品を参照しない恒真assert（F02）、製品とは別の式を検査する箇所（F03/F04）、現在は通らないRPCに故障を注入する旧テスト群（F01）**。これらは実行件数が増えても、名目上の故障検出力が増えない。一方、mockを使うこと、短いこと、同じ仕様を別の入口から検査することだけを理由に低価値とはしない。

監査だけを実施し、テスト・製品コードの変更、テスト削除、suite実行、実サービスへのprobe、配布は行っていない。以下の「通ってしまう例」はsourceから導いた反例であり、mutationを実行した結果ではない。実行時間削減量・flake率・coverage率は未測定。

## 台帳と読み方

- [全ファイルの可読台帳](test-audit-files.md)：守るもの、本番ファイル、証拠の限界、重なり、判定。
- [ファイルTSV](test-audit-files.tsv)：並べ替え・分類用。
- [ケース・検査位置TSV](test-audit-cases.tsv)：ファイルID、位置、検査名、assert位置、指摘ID。
- [構造化台帳](test-audit-ledger.json)：source hash、個別assert、helper内assert、本番境界、CI、指摘情報。

`T001`〜`T109`はファイルID。`Txxx-Cxxx`はそのファイル内のメソッドまたは検査位置であり、すべてが独立したテストではない。`F01`〜`F17`は本書の指摘ID。ケースの目的を名前から抽出した箇所は、実際のassertとファイルの境界説明を合わせて読む。旧名が誤解を招く箇所には個別注記を付けた。

| 分類 | 数 | 意味 |
| --- | ---: | --- |
| XCTestメソッド | 45 | 8ファイル。実行時のsubcase数ではない |
| Python unittestメソッド | 519 | メソッド本文・呼び出すhelperのassertを対応付け |
| shell検査位置 | 1,257 | 条件分岐・helper・fixture内検査を含む。独立シナリオ数ではない |
| shell内Python assert位置 | 30 | heredoc内の検査位置 |
| CIに到達するテストファイル | 24 / 109 | 直接16、unittest discovery 7、installerから間接1 |

**1,851 testsとは数えない。** 条件分岐を含む位置数とテストメソッド数の合算に意味はない。`keep`は契約を残す判断であり、完全な網羅性や本番合格を表さない。`strengthen`等のファイル判定も、同ファイル内の全ケースの低価値認定ではない。

## Scope / 方法

基準revision: `7fd654a02b49bd7657db4c7516c141d234c11176`。

1. `git ls-files`のプロジェクト所有テストを列挙し、Python AST / Swiftメソッド / shell検査位置を抽出。109ファイルのhashと行数を保存した。
2. 各ファイルのfixture、assert、helper、製品import・実行・source抽出・コピーを区別し、本番側の対象へ対応付けた。
3. 名前とoracle（合否を決める検査）の不一致、製品を壊しても変わらない検査、同義反復、層の違う検査を区別した。低価値候補ごとに具体的なsourceと反例を示す。
4. `.github/workflows/test.yml`の直接呼出し、discovery、installerの間接呼出しを追跡した。単にimportされるhelperを独立テスト実行とは数えない。
5. 対象テストの現物hash、ケース位置、台帳の参照整合、文書差分を検証する。docs-onlyのためsuiteを追加実行しない。

trackedのtest/spec/fixture/smoke/acceptance名を持つ実行ソースの追加照合では、一覧外はCI workflow自体だった。workflow先頭のAGENTS文言検査は**文書lint**であり、109ファイルやruntime試験の数に加えない。シェルのヒューリスティック位置抽出は意味解析器ではなく、comment/setup位置を独立ケースに昇格させない。第三者依存、build出力、履歴worktree、sibling repository所有の実装は母数に混ぜない。

## 優先候補一覧

優先度は修正順の提案であって、製品障害の深刻度ではない。**A**は検出力の欠落、**B**は保証の誤認・実行環境、**C**はlint・診断への再分類。いずれも実装は本監査のscope外。

| ID | 優先 | 対象 | 判断 / 推奨 |
| --- | --- | --- | --- |
| F01 | A | T015 formal-task guardの旧RPC系ケース | 現契約名へ改名し、同義なallowケースを整理。retired callbackの独自境界は残す |
| F02 | A | T026 binding集合へのassert | 定数だけのassertを削除候補にし、必要なら実requestを検査 |
| F03 | A | T109 workspace merge部分 | 製品save経路を通す検査へ置換。実lock検査は維持 |
| F04 | A | T016 task-ID生成部分 | 製品generatorを通す。DB解決・migrationの検査は維持 |
| F05 | C | T036 MSG skill文言検査 | 文書lintと明記。runtime coverageに算入しない |
| F06 | C | T089 reload manifest検査 | source順序grepから、実archiveの内容検査への置換候補 |
| F07 | A | T074 reverse replyの1ケース | `queued`だけでなく実recipientを検査 |
| F08 | B | T085 coalescing検査 | 逐次sticky priority検査と呼ぶ。並行性を保証するなら別の競合証拠が必要 |
| F09 | A | T014 nonblockのexpect helper | hook成功と非blockを分離して検査 |
| F10 | B | T037 cross-host検査の前半 | HOME・enrollmentを隔離し、意図したlegacy入口を固定 |
| F11 | B | T055 symlinkの1ケース | 呼出し前symlink拒否へ改名。TOCTOUを検査したとは扱わない |
| F12 | B | T026 list scopeの1ケース | Hostの投影を返すadapter検査へ改名。認可の検証責務はHostへ |
| F13 | C | T052 registry P3 | 非fatal観測とassertを区別。古いRED説明を現況の判定に使わない |
| F14 | B | T086 smokeのparser fallback | timeout不在・異なるparserによる代替成功を明示 |
| F15 | C | T095 image detail literal部分 | 過去の誤置換を防ぐlintとして維持するか、生成requestの検査へ置換 |
| F16 | A | T099 attachのrun helper | ログだけでなくexpected exitを検査。shell側の既存検査は維持 |
| F17 | B | T103 wrapper-match診断部分 | 全体成功ケースと誤認しない。空のskills/allowは別driftを意図的に残している |

### F01 — 通らないRPCに故障を注入している旧ケース群

[テスト](../../extensions/hooks/tests/test-formal-task-guard.py#L111)の`keeps_assignment_guard`、`unavailable_denies`、`old_epoch_rejection_denies_post`等は、RPC/configを故障させながら期待値が`allow`。`closes_known`や`context_is_forwarded`も実際には呼出しゼロを検査する。[製品evaluate](../../extensions/hooks/tproj-formal-task-guard#L177)は通常作業をtaskに取り込まず、exact retired callbackだけをlocal journalでfenceする設計であり、これらのRPC故障は名目の経路を通らない。

**反例:** 未呼出しRPCの例外種別・返却値を変えても結果は変わらず、古い「転送・close・拒否」能力の退行を検知しない。**対応:** 通常作業非占有・RPC不呼出しとして小さなmatrixへ整理する。全allowケースを一律削除しない。journal欠損時のpre/post差、exact retired callback、native hook wire、read-only/lifecycle判定は別境界である。特に同ファイルの`test_corrupt_journal_never_means_unassigned`はpost側の`block`も検査しており、単なるallow重複ではない。

### F02 — 製品結果を参照しない恒真assert

[T026の161行](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L155)の`assertNotIn("target", {"service_id", "service_token", "address"})`は定数集合への判定。実際の送信requestを検査していない。

**反例:** requestのfieldを誤って追加・欠落させてもこのassertは常に通る。**対応:** この1assertが最も明確な削除候補。ただしmethod全体にはsubmission ID、thread、service bindingの有用な検査があり、残す。必要な禁止fieldは仕様を確認して実requestへassertする。`target`自体は送信に必要なfieldなので、機械的に実requestへの`assertNotIn("target", ...)`へ置換してはならない。

### F03 — workspace mergeを製品とは別の式で検査

[T109のmerge部分](../../tests/test-workspace-writer-lock.sh#L28)はyq式をテスト側へコピーして実行する。[製品save処理](../../apps/tproj/Sources/TprojApp/TprojApp.swift#L5091)にも同じ構造の式があるが、テストはその処理を呼ばない。

**反例:** 製品を古い全配列置換へ戻してmanual fieldを落としても、コピーした式が残ればこの検査は通る。**対応:** 実save経路か製品の既存seamを通す。前半のlive holder排他・stale recoveryは実helperを呼ぶ有効な検査なので維持。これはworkspace lockの試験であり、Gitの`index.lock`再発防止の証拠ではない。

### F04 — task-IDのinjective encodingがテスト側コピー

[T016の553行以降](../../extensions/hooks/tests/test-inbox-check.sh#L553)はテスト内`tt_tok`で4つのIDを作り、製品sourceに`od`の文字列があるかだけを見る。[製品generator](../../extensions/messaging/tproj-msg#L4413)の実出力は取得しない。

**反例:** 製品が別分岐でtargetを正規化して衝突しても、未使用の`od`文字列が残れば通り得る。**対応:** 製品generator/入口に同じ4入力を渡す検査へ置換。後段の実`tproj-task`解決、owner分離、DB migrationは別の有用な検査であり、削らない。

### F05 — MSG skillは文書lintであって通信試験ではない

[T036](../../extensions/messaging/tests/test-chatgpt-msg-skill-contract.sh#L9)はtool名・単語・定型句の`grep -Fq`のみ。

**反例:** 語が否定文・無関係な段落に移っても通り、認証・ACK-after-consumption・配送が壊れても検出しない。**対応:** 文書lintとして区別し、意味を保つ言い換えを不必要に拒否しない粒度へ整理する候補。MailboxTools/Conversation/Hostの動的component検査を代替したとは扱わない。

### F06 — reload manifestは固定順序のsource grep

[T089](../../tests/test-kai-msg-reload-manifest.sh#L6)はsyntax、固定順序のtar文字列、sourceの存在を検査する。[reload製品](../../bin/tproj-msg-reload)のarchiveやremote配置を実行していない。

**反例:** 文字列が未使用経路に残り、実archiveが別集合を使っても通り得る。一方、同じ集合の順序変更だけで落ちる。**対応:** 隔離先に出すarchiveのentry集合を検査する候補。loaded反映はさらに別の証拠。helpの依存なし動作を検査するT091とは重複しない。

### F07 — reverse replyのpinをassertしていない

[T074の`test_reverse_reply_is_pinned`](../../extensions/messaging/tests/test-unified-hub.py#L851)はreply submitの`state == queued`だけを検査する。

**反例:** 誤ったendpointへqueuedされても通る。**対応:** 保存されたrecipient endpoint・元senderとの結合、必要なら別endpointでのclaim拒否をassertする。隣のservice restartケースは保存先とnative旧sender拒否も見るため、同じ「reply」という名前だけで統合しない。

### F08 — coalescingの「concurrent」は実際には逐次呼出し

[T085](../../extensions/persona/test-tproj-pane-bg-sync-coalescing.sh#L23)はlockを先に作り、full、fastを順番に実行。後半はclaim/promotion helperを直接呼ぶ。

**反例:** 実際の同時read/modify/writeだけで起きるlost updateは、この順序では発生しない。**対応:** sticky priorityとpromotion準備の有用性は残す。並行性の証拠が必要な場合のみ、同期点のある2writer試験へ発展させる。現状を競合再現済みとしない。

### F09 — 「block文字列がない」だけではhook正常完了を区別できない

[T014のexpect helper](../../extensions/hooks/tests/test-completion-guard-consult.sh#L177)は出力に`"decision":"block"`があるかで判定し、hookの終了値を検査しない。protocol上、空出力の正常allowは有効だが、異常終了も同じ非blockに見える。

**反例:** 一部event分岐だけがtracebackで落ちても、そのnegative-onlyケースは通り得る。後段のreflection log検査は全体的な破損を一部検出するが、個々の非blockケースの正常完了を保証しない。**対応:** 正常exitと許容出力を別々に確認する。現行のadvisory非blocking仕様を、昔の相談待ちgateへ戻さない。

### F10 — cross-hostテスト前半が実HOMEのenrollmentに依存

[T037のreject helper](../../extensions/messaging/tests/test-cross-mac-host-chat.sh#L17)はPATHだけ差替え、前半の呼出しにはHOME隔離がない。[製品冒頭](../../extensions/messaging/tproj-msg#L5)はHOME下のenrollment latch/configでunified/legacyを選び、active configならlatchも更新する。

**反例:** 同じsourceでも実ユーザーがenrolledかどうかで、期待したlegacyのエラーより前にunifiedの拒否へ分岐する。**対応:** 最初から隔離HOME/configを使ってnever-enrolled fixtureを明示する。ここでは環境依存をsourceから特定したのであり、現端末でfailureを実行確認したとは主張しない。後半のUDS/relayやstdin検査の価値とは別問題。

### F11 — symlinkの交換タイミングが名前と違う

[T055の126行](../../extensions/messaging/tests/test-repo-access.py#L126)はsymlinkを作った**後**にreadを呼ぶ。名前にある「tracked check後の交換」を同期点で再現していない。

**反例:** checkからopenまでの間だけにあるTOCTOU（確認と使用の間の競合）が壊れても、呼出し前symlinkの拒否だけなら通る。**対応:** 現検査はtracked fileがsymlinkへ置換された場合の拒否として維持し改名。製品がTOCTOU脆弱だと断定する指摘ではない。

### F12 — scope filteringではなくHost結果のprojection

[T026の`test_list_filters_to_authorized_scope`](../../extensions/messaging/external/kai-mcp/test_mailbox_tools.py#L265)はstubが返す両addressを期待する。[adapter](../../extensions/messaging/external/kai-mcp/mailbox_tools.py#L251)は表示fieldの投影を行い、実scope filteringは[Host](../../extensions/messaging/unified/host.py#L765)が担う。

**反例:** Host側filterがなくなっても、このstub主体のケースは変化しない。**対応:** adapterのprojection検査として改名し、Hostのpolicy検査と責務を分ける。adapterに重複filterを足す提案ではなく、現sourceから認可漏れを断定するものでもない。

### F13 — registryの非fatal観測を合格保証に数えない

[T052のP3](../../extensions/messaging/tests/test-registry-contract.sh#L265)は複数候補の結果を`OBSERVE`として表示するだけでFAILへ加算しない。先頭の「現在RED」説明も歴史的な文脈。

**反例:** P3の選択結果が変わってもsuiteのexitは変わらない。**対応:** 診断として残すならnon-gatingと明記。P1/P2の実producer→consumer境界は保持する。P3を恒久契約にするかは別判断であり、今回勝手にgateを追加しない。

### F14 — smokeのbounded / parser保証の条件

[T086のrun_bounded](../../tests/smoke-bin.sh#L33)はtimeout/gtimeout不在なら直接実行。zsh timeout後はbash parser成功をPASSとする。

**反例:** timeoutツールのない環境ではhangを打ち切れない。代替bashのPASSはzsh parser完走を証明しない。**対応:** smoke自体は残し、必要依存とdegraded判定を明示する候補。構文確認と代表CLI呼出しであり、全テストや全GUI動作を実行したとは数えない。

### F15 — image detailのliteral検査は局所的lint

[T095末尾](../../tests/test-pane-bg-style-layers.sh#L80)は`"detail": "auto"`の出現数と誤置換文字列の不在を見る。

**反例:** 正しいliteralがコメント・未使用経路に残っても通り得る。**対応:** 過去の語彙一括置換を防ぐlintとしては価値がある。本当にAPI requestを守るなら、生成payloadをfake clientで受け取って検査する候補。前半の実style-layer優先順テストとは分離する。

### F16 — attachの失敗exitをログ検査が隠す

[T099のrun](../../tests/test-remote-client-mosh.sh#L12)はCLIのexitを`|| true`で捨て、SSH/moshログのみを検査する。

**反例:** 正しいtransportを起動した直後にCLIが異常終了しても、必要なログがあればpositiveケースは通る。**対応:** attachの期待exitを保存・検査する。`hostB`ケースはmosh不使用だけでなくSSH使用も見る候補。後半shellケースは`set -e`下で直接実行しており、同じ欠落を全体へ広げない。

### F17 — wrapper-matchを全体no-drift成功と誤認しない

[T103のmatch fixture](../../tests/test-remote-setup-topology.sh#L15)はwrapper digest等を一致させる一方、skillsとallowを空にする。[製品check](../../bin/tproj-remote-setup#L61)はそれらを別driftとして扱う。45行の`|| true`は、wrapper行が出ないことだけを見るための部分診断であり、必ずしも誤りではない。

**反例:** 全体checkが失敗しても、この局所検査は予定どおり通る。**対応:** 「wrapper一致の部分診断」と明示。全体成功を守る必要があればskills/allowも揃えたfixtureを追加する。今のtestに無条件exit 0を要求するだけでは、fixtureの意味を壊す。単純な低価値削除候補からは除外する。

## 重複の裁定

519 Pythonメソッドの本文について、位置情報を除いたASTの完全一致は**0組**。これは意味上の重複がないという意味ではなく、変数名・fixture・payloadの違いを正規化した重複率でもない。

| クラスター | 重なり | 裁定 |
| --- | --- | --- |
| formal task | T015、T031、T033、T064〜T067、T079、T107/T108 | F01内の旧RPC/allow反復は整理候補。他はapproval、CLI、authority DB、native witness、binding releaseという別入口。まとめて削らない |
| legacy task / hook | T014/T016/T019/T020/T058/T065 | 同じtask-IDやfreezeでもnotice、DB移行、操作拒否、report closureが別。F04/F09の弱い部分だけ切り出す |
| native delivery | T038/T042〜T046/T076 | receipt parser、notice provenance、consumer本文予約、publisher順序、SDK wireは別段階。人工transcriptを共有しても同義ではない |
| identity / registry | T035/T052/T063/T072/T075 | producerがpid_startを出すかと、consumerが拒否するかは別。T052の独自価値を「legacyだから」で捨てない |
| repository access | T053〜T057/T026 | policy、path/content、write/revert、federation、Host/adapterの引数制約が別。F11の名前だけを根拠に競合coverageへ算入しない |
| installer / reload | T011/T012/T018/T059〜T061/T081/T082/T087〜T092 | 設定merge、canonical drift、mixed-version保全、配布bytes、help、tar集合は違う。共通setupの再利用とテスト削除は別判断 |
| workspace / GUI | T007/T008/T093/T106/T109 | command作成、location guard、pane geometry、GUI path選別、writer排他は別。F03だけが製品との分離問題 |
| cache / poke | T005/T009/T010/T013/T098 | 候補選択、観測、送信直前のfreshness/draft、remote tickは別。送信直前の再検証を重複扱いしない |
| remote lifecycle | T096/T099〜T105 | ledger順序、transport、PTY復元、実隔離tmux、既存session限定attach、配置driftは別。F16/F17を区別する |

共通fixtureやsetupの長さだけでテストの価値を判定しない。特にpublicationはconsumerの`setUp`を借用していても、consumerテストmethod自体を継承実行しているわけではない。

## 本番経路との距離 / 未証明の境界

| 領域 | 台帳で確認できるもの | そこから言えないこと |
| --- | --- | --- |
| native MSG | 実Hub/Host/SQLite、one-shot予約、取消、世代、人工native記録との結合 | 実provider/SDK更新後の通知到達、下書き維持、CC adapter本番統合、実Goal carry、両host全matrix |
| KAI / federation | 認証・scope・durable queue・HTTP/SSH代替の契約 | 実接続、購読、外部recipientの消費、運用時の反映 |
| legacy MSG | 実CLI + fake tmux/bridge/SSH、draft guardとsender認証 | enrolled native経路の合格。入口が違うため代替証拠にしない |
| GUI / process | Swift純関数、実shell子timeout、argv、隔離tmux/PTY | live GUIのリサイズ、drag/drop、画像品質、実ネットワーク切替、全zombie不在 |
| installer | 隔離HOME、byte/config/hash、mock trust response | 実承認、loaded process世代、実remote配布後の機能 |
| reader / locks | repo accessの限定read、workspace writer lock | 別reader executorのwrite/network制約、Git index.lockの作成原因・再発防止 |

以前の実機記録が存在しても、本監査で再実行・現revisionへ再認証したわけではない。source、installed、loaded、actual-resultを混ぜない。テストの不足を、製品で既に障害が実証されたという主張に置き換えない。

## CIの到達と欠落

正本は[test workflow](../../.github/workflows/test.yml)。16ファイルを直接実行し、KAI MCPの7ファイルをdiscovery、runtime installerからcompatibilityの1ファイルを間接実行する。各ファイルの正確な区分は台帳の`ci`列を参照。

**85 / 109ファイルはこのworkflowの実行対象ではない。** その中にはSwift全8ファイル、Hub/Host/identityの独立suite、repo-access、formal-task、remote lifecycle等がある。native consumer等から製品の一部が実行されることと、これらのtest methodが走ることは別である。CI外でも手動実行され得るため、「誰も実行していない」とは言わない。

registry/bootstrapの2suiteはsibling checkout依存によりCI外とする明示コメントがある。その他について、現workflowから実行の保証は得られない。今回CIへ全部追加する変更はしない。将来の整理では、まず保護すべきcontractと対応suiteを選び、file countを増やすための全追加は避ける。

## Local fixtureの別枠棚卸し

ignored local領域の候補522スクリプトは、主台帳の109ファイルとは分けた。分類結果は生成runtime/dependency/shell snapshot 349、生成fixture child 63、assertを持つharness 61、操作・観測・harness候補27、runtime source snapshot22。これは**522個の独立テスト**でも、**61件の本番合格**でもない。

private台帳には全候補のpath、分類、assert位置を保持する。native queue/publicationの隔離harness、receipt crash/restart、CC channel/preprompt観測にはtracked unit testとは異なる役割がある。一方、deployment script内の`returncode == 0`は、それだけで独立した回帰suiteではない。生成child・旧sourceコピーを現行テストの重複削除候補に混ぜず、履歴証拠として保持する。

これらを再実行すると配布・provider・GUI操作を伴うものがあるため、本監査では実行していない。privateな実行結果・endpoint・端末情報は公開台帳へ転記しない。旧harnessの成功を現在の製品完成度へ加算しない。

## 推奨する次の変更単位

1. **oracleの修復:** F02の恒真assert、F03/F04の製品分離、F07/F09/F16の欠けた合否条件をそれぞれ既存ケース内で直す。機械的な期待値変更にしない。
2. **意味と層の整理:** F01の同義反復を小さくし、F08/F11/F12/F17の名前・説明を実際の保証へ合わせる。文書lintと観測はF05/F06/F13/F15として区別する。
3. **実行条件の固定:** F10の環境隔離、F14のtimeout/parser保証を明示する。その後、重要contractのCI到達を選定する。

いずれも本書は候補と根拠を示すもの。テスト削除・production変更・新しいrelease gate・live probeの実行を承認済みとみなさない。監査成果物は文書であり、runtimeへの反映・再起動は不要。
