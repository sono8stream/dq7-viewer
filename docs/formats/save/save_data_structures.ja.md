# セーブデータ (`save00N.bin`) の構造

## 全体レイアウト

セーブファイルは`SaveDataSerialize`が管理する複数のサブオブジェクトを
連続して並べたコンテナ構造である。各サブオブジェクトは共通して
「4byte ASCIIマジック + version(4byte) + size(4byte) + 予約(4byte)」
という16byteヘッダを持ち、その直後にデータ本体が続く。

6人編成（未パッチの基本フォーマット）の場合の実際のオフセット（実際の
正規セーブファイルを走査して確認済み）:

| オフセット | マジック | サイズ | 内容 |
|---|---|---|---|
| `0x10` | `FLAG` | 592byte | GameFlag（フラグのビット配列） |
| `0x260` | `STGE` | 672byte | StageInfo（現在地・教会復帰情報） |
| `0x500` | `PRTY` | 1904byte | PartyStatus（隊列・所持金・バンク・カジノ・アイテム袋） |
| `0xc70` | `FLAG` | - | PlayerDataContainerのヘッダ（GameFlagとは別の構造・同名マジック） |
| `0xc80`〜 | `DATA`×6 | 各492byte | PlayerData（キャラクター1人分、6人分連続） |
| `0x1810` | `OPTN` | 32byte | 未特定 |
| `0x1830` | `FLAG` | 6496byte | BattleResult（モンスター図鑑・討伐数等の戦績データ。GameFlagとは別インスタンスで、同名マジックを再利用しているだけ） |
| `0x3190` | `STRY` | 176byte | StoryStatus（章番号） |
| `0x3240` | `GAME` | 32byte | 未特定 |
| `0x3260` | `WLDA` | 48byte | WorldAtlas（ワールドマップの現在地・向き・乗り物状態） |
| `0x3290` | `SCRP` | 48byte | 未特定（Script関連と推定） |
| `0x32c0` | `SURE` | 3824byte | すれちがい関連（`DQ7SurechigaiBox`等） |
| `0x41b0` | `IMIN` | 3568byte | イミン村関連（`IminnMenuMain`等） |
| `0x4fa0` | `SILS` | 48byte | 未特定 |

7人化（`matilda_7slot`系の改造パッチ）を適用した場合、`PlayerDataContainer`の
サイズフィールドが`0xB98`→`0xD84`(16+7×0x1EC)に変わり、`DATA`レコードが7件分
(492byte×7)に増えるぶん、それ以降の全ブロックのオフセットが一律+496byte
後ろにずれる。

## PlayerDataContainer / PlayerData（キャラクターレコード）

### コンテナヘッダ

```
+0x00 "FLAG"           magic
+0x04 0x00010000       version
+0x08 size             getSerializeSize()の合計値(6人=0xB98, 7人=0xD84)
+0x0c 0                予約
+0x10 DATAレコード×N   （Nは生存キャラ数、492byte刻み）
```

### PlayerData（1キャラクター分、`DATA`レコード、492byte = 0x1EC）

```
+0x00 "DATA"           magic
+0x04 0x00010000       version
+0x08 0x000001EC       size
+0x0c 0                予約
+0x10〜 本体データ      （ステータス・装備・文字列フィールド等）
```

インメモリ上は、キャラクター1人分のレコードが1064byte刻みで並んでおり、
各レコードの先頭8byteをスキップした位置から0x1EC(492)byteが、ほぼそのまま
オンディスクのレコード本体（上記`+0x10`以降に相当する範囲）と一致する。
文字列フィールド（装備品名等）はインメモリ上は別領域に格納されており、
シリアライズ時に`memcpy_s`で該当フィールドへ詰め替えられる。

## GameFlag

ビットフィールドの詳細仕様は[gameflag_bitfield.md](../exefs/gameflag_bitfield.ja.md)を参照。

- ブロックヘッダ（16byte、ファイルオフセット`0x10`）: `FLAG`+version+size+予約
- データ本体はヘッダ直後のファイルオフセット`0x20`から始まる
  （`FLAGS_REGION_BASE = 0x20`）
- type0のビットは`0x20 + flag_id//8`、type1のビットは`0x220 + flag_id//8`
  （type0のバイト列から0x200byteずれた別バイト列。詳細は上記リンク先）

## StageInfo

- ヘッダ（16byte、ファイルオフセット`0x260`）: `STGE`+version 0x10000+size
  `0x29c`(668)+予約
- 本体には現在のマップID(2byte)・x/y/z座標(各4byte)に加えて、教会復帰用の
  インデックス(2byte)、および各マップのNPC・家具オブジェクトの表示状態を
  管理する`SymbolFlag`/`FurnFlag`ビット配列が同居している。
- 現在地・座標のフィールドは、実際にセーブ処理が呼ばれた瞬間の値を書き込む
  ためのものであり、他のタイミングで読んだ値をそのまま使うと不正な値に
  なりうる。
- `StageInfo::loadChurch`/`returnChurch`は、教会復帰インデックスから
  `LEVELDATA/dq7_map_church.dat`テーブルの該当レコードを引き、実際の
  マップID・座標を逆算して復帰先を決定する。

### `dq7_map_church.dat`（教会テーブル）フォーマット

```
offset 0x00: 固定値(0x5302、意味未解明)
offset 0x04: レコード数 (89)
offset 0x08: ストライド (0x20 = 32byte)
offset 0x0c: レコード数の重複フィールド
offset 0x14: レコード配列開始
```

各レコード(32byte):

```
+0x04 (4byte)  未特定
+0x08 (8byte)  座標系の値
+0x10 (2byte)  マップID
+0x18 (2byte)  向き
+0x1b (1byte)  乗り物種別
```

## PartyStatus

- ヘッダ（16byte、ファイルオフセット`0x500`）: `PRTY`+version+size+予約
- 本体（ファイルオフセット`0x510`起点）に、隊列編成（u32×6の配列、生存
  キャラIDを格納。空き枠は0）・所持金・バンク残高・カジノコイン・アイテム袋
  （アイテムID配列+個数配列）が含まれる。
- 隊列配列は「先頭から詰めて格納し、空き枠は末尾に0を並べる」形式で、
  実際の正規セーブファイルでも6枠全部が埋まった状態は観測されていない
  （＝全滅した隊列スロットがない状態は仕様上あり得ないとみられる）。

## StoryStatus（章番号）

- ヘッダ（16byte、ファイルオフセット`0x3190`）: `STRY`+version 0x20000+size
  176+予約
- ヘッダ直後+0x14の位置に、現在の章番号を1byteで保持する。
- `StoryStatus::setChapter(chapter)`は、章番号を更新するほか、`chapter==9`
  （エンディング後と見られる特殊値）への遷移時のみ、直前の章番号を
  ヘッダ+0x15（`prevChapter`相当）に退避し、別のグローバルフラグも
  同時に立てる。

## BattleResult（モンスター図鑑・戦績データ）

- ヘッダ（16byte、ファイルオフセット`0x1830`）: `FLAG`+version+size
  `0x1960`(6496)+予約（`GameFlag`とマジックを共有するが別インスタンス・
  別クラス）
- モンスターごとの遭遇数・獲得ゴールド・獲得経験値・アイテム取得状況・
  討伐済み(「スタンプ」)判定などを保持する、モンスター図鑑・戦績専用の
  データブロック。街のNPC表示や物語進行フラグとは無関係。

## チェックサム

セーブファイル先頭4byteに格納された符号付き整数は、ファイルオフセット
`0x10`以降、ファイル末尾までの全バイトを符号付きバイト単位で加算した
合計値と一致している必要がある。

```
sum = signed_byte_sum(buf[0x10:])
ok  = (stored_checksum == sum)
```

## ロード時の検証ロジック（`SaveData::deserialize`）

セーブ読み込み時、以下のいずれかの条件に該当すると「壊れている」と
判定されてロードが拒否される:

| 戻り値 | 原因 |
|---|---|
| 1 | ファイルが開けない |
| 2 | 読み込めたバイト数がファイルサイズと不一致 |
| 4 | ファイルサイズが0 |
| 5 | 全体チェックサム不一致 |
| 6 | いずれかのサブオブジェクトの`deserialize()`がエラーを返した |
| 0 | 成功 |

戻り値6の主要因の一つが、`PlayerDataContainer`のヘッダ照合である:

```
magicが"FLAG"と一致しない        -> エラー1
versionが0x10000系でない         -> エラー2
sizeが現在の.codeのgetSerializeSize()と不一致 -> エラー3
```

すなわち、セーブファイル内の`PlayerDataContainer`のsizeフィールドは、
読み込み側の`.code`が「何人分のキャラクタースロットを持つビルドか」
（6人用=`0xB98`、7人化パッチ適用済み=`0xD84`）と厳密に一致している
必要がある。`GameFlag`自身のヘッダには、同種のmagic/version/size照合は
実装されていない。

## 関連ファイル（`webapp/`での実装参照）

- `webapp/save_editor.py` の `compute_checksum()`（`CHECKSUM_START=0x10`）
