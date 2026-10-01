# 画像コンテナ形式

## 対応している画像コンテナ一覧

| 種類 | 形式 | 置き場所 |
| --- | --- | --- |
| `*.bctex(.lz)` | CGFX(Textures dict の TXOB。1ファイルに複数枚のことも) | `TEXTURE/`(顔), `RISEUP/`, `CASINO/` |
| `*.bcmdl(.lz)` | CGFXモデルに埋め込まれたTXOB | `CHARACTER/` `MONSTER/` `BATTLE/` `WEAPON/` `GOODS/` 他 |
| `*.dmp` | `DMP\0`/`DMP\3` + 4文字フォーマット + WxH + bufWxH、その後8x8スウィズル画素 | `LAYOUTTEX/`(アイコン), `WORLDATLAS/`(世界地図タイル), `MENUTEX/` |
| `LAYOUTTEX/*.fpt` | FPT0アーカイブ。中の`texNNN.dmp`を個別デコード | `LAYOUTTEX/texture.fpt` `system.fpt` |

- `TEXTURE/pXXXX_jNN_face.bctex.lz`は「顔」1枚ではなく、目・口など表情パーツを
  含む十数枚のアトラス。
- DMPの画素はTXOBと同じ8x8 Mortonスウィズル。`bufW/bufH`(2の冪パディング)で
  読んで`WxH`にクロップする。

## DMP ヘッダ

```
off 0: magic "DMP\0" or "DMP\3"
off 4: フォーマット識別子(4文字)
off 8: W (u16?), H
off ?: bufW, bufH（2の冪にパディングされた実バッファサイズ）
```
（フィールドサイズは実装`webapp/ctr_texture.py`参照）

## RGBA8のチャンネル順

3DSのRGBA8はメモリ上リトルエンディアンABGR、すなわちバイト列`[A, B, G, R]`。
正しいデコードは:

```
out.R = raw[io+3]; out.G = raw[io+2]; out.B = raw[io+1]; out.A = raw[io+0]
```

RGB8分岐も同じバイト並び（`R = raw[io+2]`が上位バイト）。

## `.fpt.lz`（type-0x40圧縮）フォーマット

`.lz`拡張子だからといってLZ11/LZ10とは限らない。先頭バイトの上位ニブルで
展開器が分岐する（観測された値: 0x10/0x20/0x30/0x40/0x50/0x80）。
`SCREENTEX/`配下の`.fpt.lz`はtype-0x40（LZ77 + 二重静的Huffman、deflate風）。

### ヘッダ

```
off 0 : u8   type       上位ニブル0x40（下位ニブルは実データの一部）
off 1 : u24  展開後サイズ(LE)。0なら続くu32が真のサイズでペイロードは+4
--- Huffman表1（リテラル/長さ木）---
        u16 LE  count
        (count*4 + 4 - 2) byte の 9bit ビッグエンディアン記号列
        ノードスロット1,2,3,…に格納（最大1023）
--- Huffman表2（距離木）---
        u8   count
        (count*4 + 4 - 1) byte の 5bit BE 記号列。スロット1..63
--- 本体 ---
        MSB-first ビットストリーム
```

### Huffman木のデコード

木1（halfword）: bit0..6 = 子ベースindex、bit7 = 「bit=1側の子は葉」、
bit8 = 「bit=0側の子は葉」。1bit `b`を読み
`child = (base & ~1) + b + 2*(node&0x7F) + 2`。
葉値`< 0x100`→リテラルバイト。`>= 0x100`→マッチ、長さ=`(葉 & 0xFF) + 3`
（3..258、長さの追加ビット無し）。

木2も同形（3bit子フィールド、フラグbit3/bit4）。葉値`S`が距離を表す:
`S==0`→距離1、それ以外は`n = S-1`個の追加ビットを読み
`距離 = (1<<n) + <n bit> + 1`。マッチのコピー元は`出力位置 - 距離`
（重なりコピー可、1byteずつ）。

実装: `webapp/fpt_lz.py`の`decompress_fpt_lz(bytes) -> bytes`。

### 展開後の中身: FPT0コンテナ

展開すると`FPT0`（MESSのテキストFPT0と同じマジック・同じエントリ表構造）。
`SCREENTEX/job`の場合:

```
header: file_count, temp_count
entries (0x20 byte間隔, name[0x10] + [u32 hash][u32 offset][u32 size][u32 0]):
  tex000.dmp .. texNN.dmp   各0x4010 byte = "DMP\3" + 64x64 RGBA8888
  size.dat                   "W,H\r\n"（元画像の縦横px）
data_start = 0x10 + file_count*0x20 + temp_count*0x40
```

`size.dat`に書かれたW×Hの元画像を、64×64の4×4タイル（`SCREENTEX/job`の例）に
分割したもの。`texNNN`が左上から行優先で並ぶ。他のディレクトリも同じ
「texNNN.dmpグリッド + size.dat」構造。

## 実装ノート

「アセットを複製したら画面がまだ落ちる」場合、複製対象の種類（モデル/顔
テクスチャ/転職プレビュー用画像等）が間違っている可能性がある。画面が実際に
開こうとするファイルパスは、ARMコード内の書式文字列（ファイルパスを
`sprintf`的に組み立てている箇所の近く）を確認すると特定できる。
