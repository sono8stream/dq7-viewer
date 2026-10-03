# `CANM`（骨格アニメーション）フォーマット

`CHARACTER/*.pack.lz`（LZ11圧縮CGFXパック）内の`SkeletalAnims`辞書に格納される、
magic `CANM`の骨格アニメーションクリップのバイナリ構造。

## トップレベル構造

`SkeletalAnims`辞書の各エントリが指す先:

```
+0x00  4CC "CANM"
+0x04  u32 revision (0x07000001)
+0x08  i32 self-rel ref -> クリップ名文字列（dictキーと一致）
+0x0c  i32 self-rel ref -> 型名文字列 ("SkeletalAnimation" 固定)
+0x10  u32 = 1
+0x14  float  総フレーム数
+0x18  u32 = 24
+0x1c  u32 = 12
+0x20  u32 = 0 (予約)
+0x24  u32 = 0 (予約)
+0x28  'DICT' ヘッダ（既存のDICTパーサでそのまま読める）
       → キー=ボーン名。スケルトンの実ボーン名と一致する
```

## ボーンエントリの2方式

ボーンentry(`bo`)の`+0x08`にある`GfxPrimitiveType`値で、格納方式が2種類に分かれる:

### `PrimitiveType==8`（`GfxAnimQuatTransform`、生サンプル配列）

```
+0x00  u32 flags
+0x04  i32 self-rel ref -> ボーン名文字列
+0x08  u32 = 8
+0x0c  u32 = 12
+0x10  i32 self-rel ref -> サンプル列本体
```

サンプル列本体:

```
+0x00  0 (パディング)
+0x04  float  フレーム数
+0x08  0
+0x0c  0
+0x10〜 20byte刻みで繰り返し:
  [0(pad), qx(float), qy(float), qz(float), qw(float)]  -- クォータニオン、毎フレームの生サンプル
```

サンプル数は `round(frameCount) + 1`（末尾にループ用の閉じフレームを含む）。
移動(Translation)チャンネルの場合は16byte/frame（`[x,y,z,pad]`、クォータニオンの
ノルム判定で回転と区別する）。

`IsConstant`ビットが立っている場合はクリップ全体で1サンプルのみが格納され、
再生時はその1個を全フレームに複製する。

### `PrimitiveType==5`（`GfxAnimTransform`、Euler+Hermite圧縮カーブ）

Scale/Rotation/TranslationをX/Y/Z各軸ごとに独立した圧縮曲線（Hermite/StepLinear量子化
キーフレーム、疎なキーで補間）として持つ、生サンプル配列とは別のレイアウト。

```
ボーンentry Flagsワード: Scale/Rotation/Translation各軸の
  Constant/Inexistentビットを保持（ビット配置は参考実装のGfxAnimTransformFlagsに準拠）

各チャンネル: ヘッダ -> CurveFlags -> キー配列への自己相対ポインタ、の2段階参照
  （GfxFloatKeyFrameGroup形式）
```

量子化形式は8種類（`Hermite128/64/48`, `UnifiedHermite96/48/32`, `StepLinear64/32`）。
実データで確認されているのは`Hermite128`。

ボーンFlagsワードの`IsXConstant`ビットと、実際のチャンネルヘッダの`IsConstant`値は
食い違う場合がある。定数かどうかの判定はチャンネル毎のヘッダを優先し、ボーンFlags
ワードは「チャンネルが存在するか（Inexistent）」の判定にのみ用いる。

Euler→クォータニオンの合成式は一般的なXYZ/ZYX規約とは異なる独自の合成式を使う
（軸ごとの値を評価した後、ゲーム固有の順序で合成する）。

## スケールトラックと移動トラックの判別

16byte/frameのサンプル列は、値が3軸とも1.0から±0.3以内に収まっている場合は
スケールトラック（恒等変形に近い定数）、そうでない場合は移動トラックと判定する。
バイト形状だけでは区別できず、値域からの判定が必要。

## 最終ボーンの範囲

クリップ内最後のボーンのデータ範囲は、次のボーンのオフセットが無い場合
ファイル長でクランプする必要がある（固定長で決め打ちすると、小さいファイルで
範囲外読み取りが発生する）。

## スムーズスキニングの扱い

1頂点が複数ボーンの影響を受ける「スムーズスキニング」の形状は、各頂点が単一の
ボーンに紐づく剛体スキニングとは別のサブメッシュ種別として格納される。
