# GameFlag のビットフィールド構造

`GameFlag`クラスは、スクリプト側の`IF_FLAG`(opcode `0x00000003`)/
`SET_FLAG`(opcode `0x00010004`)から参照される、フラグ用のビット配列を
保持するクラスである。

## type引数による3本の独立したビット配列

`GameFlag::check(this, type, flag_id)` / `GameFlag::set(this, type, flag_id, value)`
の第1引数`type`は、同一`this`インスタンス内にある3種類の独立したビット配列を
選択する。`IF_FLAG`/`SET_FLAG`のスクリプト引数`[param0, flag_id, value]`の
`param0`はこの`type`そのものである。

| type | ビット配列のオフセット（`this`起点） | オンディスク（セーブファイル）換算 |
|---|---|---|
| 0 | `this+0x218` | `0x20 + flag_id//8`（`GameFlag`ブロック先頭からのファイルオフセット） |
| 1 | `this+0x418` | `0x220 + flag_id//8`（type0のバイト列から0x200byteずれた別バイト列） |
| 2 | `this+0x008` | セーブに一切保存されない（後述） |

ビット位置の計算式（3タイプ共通）: `bit = flag_id & 0x1f`, `word = flag_id >> 5`
（メモリ上は32bitワード単位のビット配列として扱われる）。

`GameFlag::set`は`type==3`という特殊値を受け付け、「type0とtype1の両方に
同時に書き込む」処理を行う。一方`GameFlag::check`には`type==3`の分岐が
無く、`check`に`type=3`を渡した場合は常にfalseになる。

## type=2 はセッション限定の一時フラグ

`GameFlag::serialize`（fileoffset `0x243c0c`）は`this+0x208`から`0x250`
(592byte)をそのままセーブデータへコピーする。この範囲は`this+0x208`〜
`this+0x458`であり、type=0のバケット(`+0x218`)とtype=1のバケット(`+0x418`)
はどちらもこの範囲に収まり永続化されるが、type=2のバケット(`+0x008`)は
この範囲より前にあるためセーブファイルには一切含まれない。

`GameFlag::initialize`（fileoffset `0x243b38`）は起動時に`GameFlag::clear(this, 3)`
でビット配列をゼロクリアした後、`this+0x208`〜`+0x458`を改めてmemsetする。
これにより、**type=2のフラグは起動するたびに必ず0に戻る、セッション限定の
一時フラグである**。

## flag_id空間のスコープについて

- type0の大きい値（数千番台）のflag_idは、対応するSCRIPTファイルが
  1ファイルのみで独立に`SET_FLAG`しているケースが多く、グローバルに一意な
  物語進行フラグとして運用されていると見られる。
- type1の小さい値（1桁〜2桁）のflag_idは、多数（数十〜100件以上）の
  異なるSCRIPTファイルで独立に使われている。このため、type1のflag_idは
  グローバルに一意な意味を持つものではなく、各マップのスクリプトが
  自分自身のスコープ内だけで使うマップローカルな一時変数である可能性が
  高い（マップをまたいで同じID=同じ意味、とは限らない）。

## 関連クラス・関数（fileoffset、`code.decompressed.bin`基準）

- `GameFlag::check` : `0x18f998`
- `GameFlag::set` : `0x18b00c`
- `GameFlag::serialize` : `0x243c0c`
- `GameFlag::initialize` : `0x243b38`
