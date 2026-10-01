# partytalk系LEVELDATAファイルのフォーマット

対象: `LEVELDATA/dq7_partytalk_chapter1.dat`〜`_chapter4.dat`,
`_chapter_ending.dat`（各`_index.dat`あり）, `dq7_special_party.dat`
（indexなし）。パーティメンバーが街中で話しかけると聞ける会話データ。

## 共通ヘッダ

固定長配列ヘッダ形式（`ExcelBinaryData`、`getRecordDynamic`公式:
`result = descriptor + 0x14 + index * stride`）に全ファイルが従う。

```
offset 0x00: magic的な値（ファイルごとに異なる、用途未解明）
offset 0x04: レコード数(count)
offset 0x08: ストライド(byte)
offset 0x0c: countの重複
offset 0x14: レコード配列開始（0x14 + count*stride == ファイルサイズ）
```

## `_index.dat`: flag_id → 本体テーブル範囲のルックアップ

8byte(u16×4)レコード: `(flag_id, start_record_idx, record_count, 0xFFFF)`。
末尾の`0xFFFF`は固定のパディング/終端マーカー。

本体テーブルの各レコードのオフセット`+0x18`（flag_idフィールド、下記）と
indexの`flag_id`が一致する。本体テーブルはflag_idの昇順にグループ化されて
連続配置されており、`_index.dat`はそのグループの開始/件数を引く索引。

## 本体`.dat`レコード構造（chapter1〜4/ending共通、36byte、u16×18）

| フィールド | offset | 内容 | 確度 |
|---|---|---|---|
| idx0 | 0x00 | メッセージID | 確定 |
| idx1〜idx7 | 0x02〜0x0F | 常に0（予約領域） | - |
| idx8 | 0x10 | レコード通し番号的な値（メッセージIDではない） | 用途未確定 |
| idx9 | 0x12 | `6`または`9`の2値のみ観測 | 用途未確定（テーブル種別/カテゴリの可能性） |
| idx10 | 0x14 | floor_id | 確定（floor_id自体であること） |
| idx11 | 0x16 | floor_id（別マップを指すことが多い） | 確定（floor_idの値域であること）。idx10との関係（範囲/独立条件）は未確定 |
| idx12 | 0x18 | flag_id（`_index.dat`のキーと一致） | 確定 |
| idx13 | 0x1A | 小さい整数（1〜4,11〜14,21,22,31,110〜122,191,211,212等） | 用途未確定 |
| idx14 | 0x1C | 256の倍数が主体、まれに端数 | 用途未確定（ビットフィールドの可能性） |
| idx15 | 0x1E | 多数の値（2の累乗の組み合わせが多い） | 用途未確定（ビットフィールドの可能性） |
| idx16 | 0x20 | 常に`65280`(0xFF00) | パディング/センチネル |
| idx17 | 0x22 | 常に`65535`(0xFFFF) | パディング/センチネル |

`idx14`/`idx15`は複数のブール条件をビットORしたフラグ用フィールドである
可能性が高い。`idx13`は一の位・十の位に規則性があるように見えるが、
「キャラクター番号×バリエーション番号」のような複合コードかどうかは未確定。

## `dq7_special_party.dat`: 別フォーマット

`magic=0x4607, count=137, stride=12`（u16×6）。chapter系とはレコード長・
フィールド構成が異なる。

- idx0（先頭u16）はレコードの通し番号(0,1,2,...136)と一致し、この値が
  暗黙的にメッセージIDそのものとして使われる（chapter系のような明示的な
  msgidフィールドではない）。
- `_index.dat`が存在しないのは、flag_idによる範囲検索ではなく、スクリプト
  側からレコード番号を直接指定してアクセスされる設計のためと推測される
  （未検証）。
- 残り5つのu16フィールド(idx1〜idx5)は値域がテーブル自身のレコード数を
  超えるため自己参照ではなく、chapter系のidx13〜idx15と同種のflag_id候補
  /ビットマスク条件である可能性があるが未確定。

## 未検証・未解決の点

- idx12(flag_id)の値域がセーブ内GameFlagのビット数に収まるか（別空間の
  可能性もある）。
- idx10/idx11の2つのfloor_idが「範囲」か「独立条件」かの切り分け。
- idx13/idx14/idx15の正体（ExeFS側の関連クラスを解析すれば分かる可能性）。
- `dq7_special_party.dat`のidx1〜idx5の正体、chapter系との関係。
- 本仕様の解析は静的解析・データ照合のみで、実機での動作検証は未実施。
