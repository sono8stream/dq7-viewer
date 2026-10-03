# セーブデータ: `PlayerDataContainer`とNCCH/ExeFSコンテナ構造

## `PlayerDataContainer`（セーブ内キャラクター配列）

`PlayerDataContainer::serialize`/`deserialize`（ExeFS `.code`内）が、
インメモリの`PlayerData`配列（1レコード1064byte固定）のうち先頭から
一定数だけをセーブへ書き出す/読み込む。

```arm
mov r4, 1
loop:
  ; r0 = base + r4*1064 + 8   (インメモリ構造体1レコード = 1064byte)
  bl PlayerData::serialize
  add r4, r4, 1
  cmp r4, 7        ; ループ継続条件。コード未改造時は r4=1..6 の6回
  add r5, r5, 0x1ec  ; セーブ側の出力ポインタを1レコード分(0x1EC=492byte)進める
  blt loop
```

- `getSerializeSize`はコンテナ全体のサイズを固定値として返す
  （ヘッダ16byte + レコード数×0x1EC。6人分なら`0xB98`）
- `PlayerDataContainer::initialize`は起動時に常に46人分
  （`dq7_character_init_data.dat`のindex 1〜45相当）をインメモリ配列に
  セットアップしている。**インメモリ配列自体には最低46人分の容量が
  既にあり、セーブへの書き出し段階でのみ件数が絞られる**設計

### キャラクターレコードの自己記述ヘッダ（16byte、各レコード共通）

セーブ内の各キャラクターレコードは、先頭にコンテナヘッダと同形式の
自己記述サブヘッダを持つ:

```
+0x00  "DATA" (4byte magic)
+0x04  u32: 0x00010000 (version)
+0x08  u32: 0x000001EC (=492、このレコード自身のサイズ)
+0x0C  u32: 0（予約/パディング）
+0x10  u8:  キャラクター番号（1-indexed連番、record0なら1）
+0x11  u8:  既知レコードでは共通して5（意味未確定）
+0x12  u16: 0固定
+0x14  ここからキャラクター本体のフィールド（exp等）が始まる
```

コンテナ全体（`PlayerDataContainer`）側にも同形式の"FLAG"マジック付き
ヘッダがあり、同じ入れ子構造になっている（コンテナ全体を包むヘッダ＋
各要素ごとの個別ヘッダ、という二重の自己記述構造）。

### `PlayerManager::addPlayer`内のフォーメーション座標配列

パーティの立ち位置（座標/回転）をシフトする処理が、現在人数を参照する
ランタイム変数（`PlayerManagerオブジェクト+0x120`）に対して上限比較を
行っている:

```arm
cmp r0, 6      ; r0 = 現在の隊列人数
bge ...        ; 6以上ならこの座標シフト処理をスキップ
...
cmp r4, 6      ; 同ループの終了条件
```

この配列は`PlayerDataContainer`のセーブ用配列とは別の、パーティ編成UI用の
座標バッファ。実測では7人目を追加してもこの上限由来の不具合は確認されず、
配列自体はセーブの件数制限より余裕を持って確保されている可能性が高い
（詳細未確認）。

### `PlayerManager::setPartyControl`: プレイアブル/AI操作の判定

パーティメンバーごとに「プレイヤーが操作できるキャラ」か「AIが操作する
お助けキャラ」かを行動ノード（ビヘイビアツリー、`fcn.0018fae4`でノード種別
ごとに構築）として組み立てる処理。分岐は、キャラクターの種別を表す
1byte値（ASCIIの`'w'`/`'e'`/`'f'`/`'x'`、`0x82`等）を使っており、この値は
汎用テーブル引きヘルパー（`PlayerData::getJob()`と同一パターンの
`result = *(array) + 0x14 + index * stride`関数）経由で取得される。
参照元テーブルの実体（`dq7_player_job.dat`本体か、キャラ初期化データの
別フィールドか）は未確定。

`dq7_player_job.dat`は55レコード×188byteの職業定義テーブル。

## NCCH / ExeFSコンテナフォーマット（実データから検証済み）

### NCCHヘッダ（マジック`NCCH`基準の相対オフセット）

- `+0xA0` ExeFS offset（media unit、×0x200）
- `+0xA4` ExeFS size（media unit）
- `+0xA8` ExeFS hash region size（media unit）
- `+0xB0`/`+0xB4` RomFS offset/size
- `+0xC0`〜`+0xE0` ExeFSスーパーブロックハッシュ（SHA256, 0x20byte）
- `+0xE0`〜`+0x100` RomFSスーパーブロックハッシュ

ExHeader `+0x200+0xD`のbit0が`CompressExefsCode`フラグ（`.code`がBLZ圧縮
されているかどうか）。

### ExeFSヘッダ（0x200byte）

- `+0x00`〜`+0xA0`: 10エントリ×16byte（name[8] + offset[4] + size[4]）
- `+0xC0`〜`+0x200`: 10×32byte SHA256ハッシュ

**ハッシュは「エントリindex `i`の内容 → 固定10枠中のスロット`9-i`」に
格納される**（ファイル数に応じた相対位置ではなく、常に末尾から埋まる
固定レイアウト）。例えば4ファイル構成（`.code`=idx0, `banner`=idx1,
`icon`=idx2, `logo`=idx3）の場合、ハッシュはスロット9,8,7,6に入り、
スロット0-5は全ゼロになる。

各ファイルデータのオフセットは0x200単位でアラインされる。
全オフセット/サイズ値はmedia unit（×0x200）基準の符号なしu32。
