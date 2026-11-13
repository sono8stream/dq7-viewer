# partytalk系 LEVELDATA ファイルのフォーマット

対象: `LEVELDATA/dq7_partytalk_chapter1.dat`〜`_chapter4.dat`、
`_chapter_ending.dat`（それぞれ`_index.dat`付き）、および
`dq7_special_party.dat`（indexなし）。前に誰もいないときの「はなす」で
仲間が話すセリフのデータ。

以下の意味は、表を使うコードから読んだもの:
`PartyTalk::setFloorDataIndex`、`PartyTalk::setPartyTalkData`、
`PartyTalk::checkCondition`、`PartyTalk::setPickMessage`、
`PartyTalk::setMessageData`、`PartyTalk::getPartyTalk`、
`PartyTalk::setPartyTalkMessage`と`PartyTalkData`の関数。

> **訂正（このページの以前の版）:** `+0x18`をフラグID、`+0x14`/`+0x16`を
> フロアIDとしていたが逆だった。`+0x18`がフロアID（索引のキー）で、
> `+0x14`/`+0x16`がフラグ。また全欄をu16として読んでいたため、`+0x10`の
> u32のセリフ番号が「通し番号」（`+0x10`）と「6か9の値」（`+0x12`）に割れていた。

## 共通ヘッダ

全ファイルが固定長配列ヘッダ形式（`ExcelBinaryData`、`getRecordDynamic`
公式: `result = descriptor + 0x14 + index * stride`）に従う。

```
offset 0x00: magic的な値（ファイルごとに異なる）
offset 0x04: レコード数(count)
offset 0x08: ストライド(byte)
offset 0x0c: countの重複
offset 0x14: レコード配列開始 (0x14 + count*stride == ファイルサイズ)
```

## `_index.dat`: フロアID → 本体テーブルの範囲

8byte(u16×4)のレコード: `(floor_id, start_record_idx, record_count, 0xFFFF)`。

`PartyTalk::setFloorDataIndex`（マップに入ったとき）が、各表の索引から
今のフロアIDを探し、`[start, start + count)`を持っておく。読む表は
`chapter1`〜`chapter4`。ベースVA 0x543364のバイトが6なら`chapter_ending`
だけ、1なら何も読まない。

## 本体`.dat`のレコード（chapter1〜4/ending、36byte）

| offset | 型 | 内容 |
|---|---|---|
| 0x00 | u32 | 「直前」条件（`+0x1e`上位4ビット）の値 |
| 0x04 | u32 | 条件1（`+0x1f`下位4ビット）の値 |
| 0x08 | u32 | 条件2（`+0x1f`上位4ビット）の値 |
| 0x0c | u32 | 選ばれたときの動作（`+0x20`下位4ビット）の値 |
| 0x10 | u32 | 最初のセリフのメッセージID |
| 0x14 | u16 | 立っているべき種類0のゲームフラグ（0＝なし） |
| 0x16 | u16 | 立っていてはいけない種類0のゲームフラグ（0＝なし） |
| 0x18 | u16 | フロアID（索引のキー） |
| 0x1a | u16 | 行数（下） |
| 0x1c | u8 | 声のパターンの値（`+0x20`上位4ビット≠0のとき） |
| 0x1d | u8 | 話し手: キャラID（1 主人公〜6） |
| 0x1e | u8 | ビット0: 無効。ビット1〜3: 空にするセリフ枠（`setPickMessage`）。上位4ビット: 「直前」条件 |
| 0x1f | u8 | 下位4ビット: 条件1の種類、上位4ビット: 条件2の種類 |
| 0x20 | u8 | 下位4ビット: 選ばれたときの動作、上位4ビット: 声のパターン |
| 0x21 | u8×3 | `FF FF FF` |

話し手はパーティにいて生きている（または状態4）必要がある。

### 「直前」条件（`+0x1e`上位4ビット、値`+0x00`）

| 種類 | 成り立つとき |
|---|---|
| 0 | 常に |
| 1 | `+0x00`が前回の「はなす」以後に聞いたセリフの中にある（`PartyTalkData::isPreMessageNo`）。`CmdMessage1`/`CmdMessage2`/`CmdSpeakToPlayer1`/`CmdSpeakToPlayer2`とその`WaitClosing`版が一覧を消してから、表示する全セリフを足す（16個まで）。マップ移動でも消える |
| 2 | `+0x00`が最後に手に入れた道具（`PartyTalkData::setPreItem`: `CmdSetItem`、`TaskSearch`） |
| 3 | `+0x00`が最後に使った道具（`PartyTalkData::setUseItem`） |
| 4 | `+0x00`が`PartyTalkData::setAddPlayer`の一覧にある |
| 5 | `+0x00`が`TaskSearch`の入れる`PartyTalk+0x18c`の値 |
| 6 / 8 | 全体のバイト（+0xed / +0xf0）が0でない |
| 9 / 10 | `PartyTalk+0x146`が0でない（到着時に`setExitNo`が立てる） |

### 条件の種類（`+0x1f`、`PartyTalk::checkCondition`）

| 種類 | 成り立つとき |
|---|---|
| 1 / 2 | 種類0のフラグ`値`が立っている / いない |
| 3 / 4 | 種類1のフラグが立っている / いない |
| 5 / 6 | 種類2のフラグが立っている / いない |
| 7 / 8 | 道具`値`を誰も持っていない / 誰か（またはふくろ）が持っている |
| 9 / 10 | キャラ`値`がパーティにいて生きている / 死んでいる |
| 11 | `PlayerParty::getInitPlayerIndex(値) == 0` |
| 12 | マップに入った出口が`値` |

### 行数（`+0x1a`）と選ばれたときの動作（`+0x20`下位4ビット）

`n = +0x1a % 1000`。
- 動作7（はい/いいえ）: 百の位＝行数、十の位＝「はい」の後の行数、
  一の位＝「いいえ」の後の行数（0なら「はい」の行を「いいえ」でも出す）。
- それ以外: 十の位＝行数、一の位＝追加の行数。十の位が0なら一の位が行数。
  追加の行は動作が成り立つときに出る:

| 動作 | 効果 |
|---|---|
| 1〜6 | 選ばれたら種類0/1/2のフラグ（`+0x0c`）を立てる/消す |
| 7 | はい/いいえ（上） |
| 8 / 9 | 種類0のフラグ`+0x0c`が立っている / いないなら追加の行 |
| 10 / 11 | 道具`+0x0c`を持っている / いないなら追加の行 |
| 12 | キャラ`+0x0c`がパーティにいて生きていれば追加の行 |
| 13 | 別のメッセージ表示モード（`setMessageData`がモード5にする） |

セリフは`+0x10`からの連続したメッセージID。各セリフの本文は
`#<話し手のID>\r\n`で始まり、話し手の名前のマクロが続く。

### 記録の選び方

`PartyTalk::setPartyTalkData`（「はなす」のたび）が、そのフロアの条件を
満たす記録を表ごとに**30**件の配列と、`PartyTalk+0x90`の一覧（6byte×30、
全表で共有、範囲チェックなし）に集める。`PartyTalk::getPartyTalk`は
聞いた回数（記録ごと、最大3）が一番少ないものに絞り、「直前」条件つきを
優先して、前回と違うものをランダムに選ぶ。

## `dq7_special_party.dat`: 別フォーマット

`magic=0x4607, count=137, stride=12`（u16×6）。chapter系とはレコード長・
フィールド構成が異なる。

- idx0（先頭u16）はレコードの通し番号（0,1,2,...136）と一致し、この値が
  そのままメッセージIDとして使われる。
- `_index.dat`が無いのは、スクリプト側からレコード番号を直接指定して
  参照するためと推測（未検証）。
- 残り5つのu16（idx1〜idx5）は未解読。
