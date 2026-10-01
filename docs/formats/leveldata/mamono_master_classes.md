# 「モンスターがなつく」シーケンスのバトルタスク構造

戦闘後、倒したモンスターを「モンスターパーク」の所有モンスターリストに
追加（テイム）する演出を実装するクラス群。徒歩パーティへの直接加入ではなく、
モンスターパークの所有モンスターリストへの追加に相当する。

## クラス構成: `BattleTaskMamonoMaster` + `BattleExecMamonoMaster00/01/02`

DQ7のバトルタスクは「1つの`BattleTaskXxx`が複数の`BattleExecXxx`（サブ状態）を
順に実行する」という設計（他のバトルタスクにも共通するパターン）。このシーケンスは
3ステートで構成される。

| クラス | 役割 |
|---|---|
| `BattleExecMamonoMaster00` | システムメッセージ1件を表示。表示文言は、対象モンスターの属性バイト(`+0x84`の上位3bit)で単数/複数等の言い回しを切り替える文法バリエーション選択を伴う |
| `BattleExecMamonoMaster01` | Yes/No確認のシステムメッセージを表示。表示後、グローバルflag配列への書き込みヘルパー関数を呼ぶ |
| `BattleExecMamonoMaster02` | プレイヤーの回答（グローバルの1byteフラグ）を見て分岐。Yes側では`BattleResult::setMonsterAttach`を呼んでテイム成立を確定し対応するメッセージを表示。No側では別のメッセージを表示するのみ |

`BattleResult::setMonsterAttach`という関数名から、テイム成立時にモンスターが
`BattleResult`（戦闘結果構造体）へ「同行モンスター」として紐付けられ、戦闘終了後に
モンスターパークへ登録される、という流れと推測される（関連シンボル
`BattleResult::setMonsterAttachCount`, `MonsterParkUtility::getMonsterParkHouseCount`
も存在）。

`BattleTaskMamonoMaster`自体（`initializeUser`）は3つのサブ状態を登録する
だけで、このタスクをそもそも起動するかどうかの判定はさらに外側（戦闘終了
処理）にある。候補関数として`MonsterPartyUtility::isEnableCallMonster`・
`status::isEnableCallMonster`が存在し、生存中のモンスターを1体ずつ走査する
ループ構造までは確認されているが、判定条件自体（なつきやすさ・確率抽選等）
は未解読。

## 未解決点

- `isEnableCallMonster`系の条件式（「なつく」確率・条件）。
- `BattleResult::setMonsterAttach`呼び出し後の実際のモンスターパーク登録処理。
- モンスターの属性バイト`+0x84`（上位3bit、文法バリエーション分岐に使用）が
  モンスターパラメータテーブルのどのフィールドに対応するか。

## 調査手法のメモ

戦闘システム内蔵の固定メッセージ（SCRIPTファイルを経由せず、ExeFS側が直接
メッセージIDを保持するケース）は、メッセージIDの32bit整数リテラルをExeFS
全体でバイト検索することで発見できる。「SCRIPT検索で見つからない」からと
いって当該メッセージが存在しないとは限らない。
