# 3DモデルフォーマットCGFX(BCRES) / `.bcmdl` 仕様

DQ7(3DS)の3Dモデルは任天堂3DS標準の中間フォーマットCGFX(拡張子`.bcmdl`、一部
`.pack`/`.shp`、いずれもLZ11圧縮の`.lz`形式で格納)。本ドキュメントは実バイナリの
解析で確定した構造のみを記載する(未確認・推定箇所はその旨明記)。

## ファイル配置

| 置き場所 | 拡張子 | 中身 |
| --- | --- | --- |
| `CHARACTER/` | `pXXXX_jNN.bcmdl.lz` | LZ11圧縮のCGFX(モデル本体) |
| `CHARACTER/` | `pXXXX_jNN.pack.lz` | LZ11圧縮の`PackData`コンテナ。中にCGFX(主にスケルタルアニメ) + CANM |
| `MONSTER/` | `eNNN.bcmdl.lz` | LZ11圧縮のCGFX(モデル本体) |
| `MONSTER/` | `eNNN.pack.lz` | LZ11圧縮の`PackData`。中身はCGFX(SkeletalAnims) + CANM |
| `GOODS/` | — | 装備品(帽子等)モデル。本体メッシュとは別ファイルで管理されるケースがある |
| `SHAPE/` | `*.shp.lz` | LZ11圧縮の`PackData`(小さい形状、未調査) |

- LZ11はヘッダbyte0=`0x11`の標準LZ11圧縮。
- `PackData`コンテナ: マジック`'PackData'` / `+0x10` u32 entryCount / `+0x14` u32
  tableOfs。tableOfsから`{u32 absOffset, u32 size}`の配列。エントリの1つが`'CGFX'`。

## CGFX(BCRES)トップレベル構造

全てリトルエンディアン。「offset」系フィールドは原則**自己相対**(フィールドの
絶対位置に値を加算、値0 = null)。

```
0x00 'CGFX'  u16 bom(0xFEFF)  u16 headerLen(0x14)  u32 revision  u32 nBlocks
0x14 'DATA'  u32 len
0x1c 以降: 15組の (u32 count, i32 selfRelPtr) — 各DICTへのポインタ
     順に Models, Textures, LUTS, Materials, Shaders, Cameras, Lights, Fogs,
     Scenes, SkeletalAnims, MaterialAnims, VisAnims, CameraAnims, LightAnims, Emitters
```

### DICT

```
'DICT' u32 byteLen  u32 count
その後 (count+1) 個のノード、各16byte:
  u32 refBit  u16 idxLeft  u16 idxRight  i32 nameSelfRel  i32 dataSelfRel
```
ノード[0]はPatricia木のルートでデータを持たない。`dataSelfRel`が各オブジェクトを指す。

### シリアライズ共通規則

- ポインタは自己相対(フィールド位置 + 読んだ値、値0 = null)。
- 参照フィールド(クラス型) = `[u32 ptr]`。リスト参照 = `[i32 count][u32 ptr]`
  (countが先、ptrが後)。文字列 = `[u32 ptr]`のみ。
- 各オブジェクトは先頭にTypeChoice判別子`u32`を持つ:
  - `0x40000012` = GfxModel
  - `0x40000092` = GfxModelSkeletal
  - `0x10000001` = GfxShape
  - `0x40000002` = InterleavedVertexBuffer
  - `0x40000001` = GfxAttribute
  - `0x80000000` = FixedVertexAttribute
- TypeChoice判別子の直後に`[u32 magic][u32 revision]`(GfxObjectの場合)。
- `bool`はディスク上4バイト(1ワード)。

### GfxObject共通ヘッダ

各オブジェクトは`u32 flags`の直後に4CCマジック(`CMDL` `SOBJ` `MTOB` `TXOB` `SHDR`
等)を持ち、続けて`u32 revision`, `i32 nameSelfRel`, `u32 userDataCount`,
`i32 userDataSelfRel`。ヘッダ終端は判別子位置から`+0x18`。

## CMDL(モデル)

```
+0x24  animGroupCount, +0x28 animGroupDict(selfRel) -> DICT
+0x2c  scale[3] / rot[3] / trans[3] (f32)
+0x50  localMtx 4x3 / worldMtx 4x3
...    meshCount,  i32 meshArraySelfRel  -> i32配列 -> SOBJ(Mesh)
...    shapeCount, i32 shapeArraySelfRel -> i32配列 -> SOBJ(Shape)
```

**GfxModel(TypeChoice判別子基準オフセット)**:
```
+0xc4  shapes.count
+0xc8  shapes.ref (自己相対ptr配列 -> GfxShape)
```

**GfxModelSkeletal**: `+0xE0`にスケルトンへの参照(下記)。

## SOBJ(Shape) / GfxShape

```
+0x2c  subMeshes
+0x38  vertexBuffers
+0x1c  boundingBox
+0x34  vertexBufferCount, +0x38 i32 selfRel -> i32配列 -> VertexBufferオブジェクト
```
`vertexBuffers`の要素は2種類:
- `InterleavedVertexBuffer`(typeFlag `0x40000002`)
- `FixedVertexAttribute`(typeFlag `0x80000000`。boneIndex用途などで固定値を持つ)

Shapeは`PositionOffset`(`+0x20`)を持ち、最終頂点位置に加算する。

### InterleavedVertexBuffer

```
+0x00  typeFlag 0x40000002
+0x14  i32 selfRel -> 頂点ストリーム本体
+0x18  u32 ストリームのバイト長
+0x24  stride
+0x28  attrCount, +0x30.. selfRel配列 -> 属性ディスクリプタ(GfxAttribute)
```

### GfxAttribute(属性ディスクリプタ)

```
+0x00  typeFlag 0x40000001
+0x04  usage (0=position, 1=normal, 4=uv0, 5=uv1, 8=boneWeight; boneIndexは別途FixedVertexAttribute経由)
+0x24  format (GL enum: 0x1406=FLOAT, 0x1401=UBYTE, 0x1402=SHORT, 0x1403=USHORT)
+0x28  elements(componentCount; position=3, uv=2, boneWeight=4)
+0x2c  scale (f32)
+0x30  offset
```
最終値 = raw × scale。

### GfxSubMesh / 頂点影響(スキニング)

```
GfxSubMesh:
  +0x00  boneIndices (list, サブメッシュが参照するボーンのグローバルindex配列)
  +0x08  skinning (0/1=rigid系, 2=smooth)
  +0x0c  faces -> GfxFace
GfxFace:
  +0x00  faceDescriptors -> GfxFaceDescriptor
GfxFaceDescriptor:
  +0x00  format (0x1403=u16インデックス、それ以外=u8インデックス)
  +0x08  idx.len
  +0x0c  idx.ref (インデックスバッファ本体)
```

頂点ごとのボーン影響(最大4件)は2パターンで表現される:
1. `boneIndex`頂点属性(byte、サブメッシュの`boneIndices`配列へのローカルindex)と
   `boneWeight`属性の組。
2. `boneIndex`属性が無い場合、`boneWeight`の各コンポーネント順が`boneIndices`配列の
   並びにそのまま対応する(positional correspondence)。

ウェイトの合計は常に≈1.0。

## スケルトン・バインドポーズ

- `GfxModelSkeletal`(typeId `0x40000092`)の`+0xE0`がスケルトン参照
  (`GfxSkeleton`、typeId `0x02000000`)。Bones dictはスケルトン基準`+0x1C`。
- ボーンレコード: stride `0xE0`。`+0x08` Index、`+0x0C` ParentIndex、
  `+0x44` LocalTransform(Matrix3x4)、`+0x74` WorldTransform(Matrix3x4)。
  **`WorldTransform`は全ゼロで出荷されており使用不可**。world行列は
  `LocalTransform`と`ParentIndex`から親チェーンを自前で合成する必要がある。
- `Matrix3x4`はディスク上12個のf32が
  `M11,M21,M31,M41, M12,M22,M32,M42, M13,M23,M33,M43`の順(row-major 3x4
  アフィン、平行移動は各行の4列目)。`x' = x*f0 + y*f1 + z*f2 + f3`等。
- スキニング適用規則(サブメッシュ単位):
  - `skinning != 2`(rigid/単一ボーン): 代表ボーン
    (`boneIndices[ 頂点のboneIndex属性[0] ]`、属性が無ければindex 0)の
    world行列で position/normal を変換。
  - `skinning == 2`(smooth): 複数ボーンのworld行列を上記の影響(index,weight)で
    ブレンドして変換。

## テクスチャ(TXOB)

```
+0x18  H(高さ)
+0x1C  W(幅)
+0x34  HwFormat (PICA200テクスチャフォーマットID)
+0x38  Image ref -> ImageData
         ImageData: +0x08 raw.len / +0x0C raw.ref (生ピクセルデータ)
```

### フォーマットとチャンネル順

DQ7で使用が確認されているフォーマット: RGBA5551(最多)/ RGB565 / ETC1 / ETC1A4 /
RGBA4、少数のL8/HiLo8/RGB8/LA8。

- 8x8 Mortonスウィズル配置。
- RGB565 / RGBA5551 / RGBA4 の各ビットフィールドは **Rが上位ビット**
  (`GL_UNSIGNED_SHORT_5_6_5`=0x8363 / `..._5_5_5_1`=0x8034相当の標準GL順)。
- ETC1 / ETC1A4 は4x4ブロック圧縮(標準ETC1規則)。
- ミップマップはmip0のみデコード対象(高次ミップは別途生成が必要な場合あり)。

### マテリアル(MTOB)のテクスチャ参照

- モデルのMaterials dict: `model+0xBC count` / `+0xC0 ref` -> MTOB配列。
- MTOB内のテクスチャ名文字列への参照オフセット(固定): `+0x33c`(主/ステージ0)、
  `+0x3c8`、`+0x454`(追加ステージ、最大3ステージ)。
- Shape→Material解決: `GfxMesh`の`+0x18 ShapeIndex` / `+0x1C MaterialIndex`。

### UVチャンネル対応(`GfxTextureCoord.SourceCoordIndex`)

マテリアルの各テクスチャステージが実際にどの頂点UV属性(uv0/uv1/uv2)を使うかは、
ステージ番号と同一とは**限らない**。実際の対応はマテリアル内の
`GfxTextureCoord.SourceCoordIndex`フィールドで指定される。

オフセット導出(フィールド宣言順からの積み上げ。TypeChoice判別子位置基準):
```
GfxObjectヘッダ終端                         : +0x18
Flags/TexCoordConfig/Translucency(3xu32)   : +0x24
Colors(GfxMaterialColor, 11xVector4 + 11xRGBA + CommandCache = 0xE0) : +0x104
Rasterization(GfxRasterization, 0x14)      : +0x118
FragmentOperation(GfxFragOp, 0x50)         : +0x168 (UsedTextureCoordsCount)
TextureCoords[3]開始                        : +0x16C
  各GfxTextureCoordは0x58バイト固定長
  SourceCoordIndex = +0x16C + k*0x58 (kはステージ番号 0..2)
```
値は0/1/2のいずれか(使用するUVチャンネル番号)。

## PICA200生コマンド構造(AlphaTest / CullMode / TexEnv)

MTOBの一部フィールドは、PICA200 GPUコマンドをほぼそのままの形でシリアライズして
持っている。固定のコマンドヘッダ定数でマテリアルレコード内をバイト列スキャンする
ことで、位置計算をせずに値を取り出せる。

### AlphaTest

2ワード(u32×2)のraw dump:
```
word0 = Param  (bit0=Enabled, bits4-6=Function(PICATestFunc), bits8-15=Reference 0-255)
word1 = header = 0x000F0104 (固定定数。GPUREG_FRAGOP_ALPHA_TEST(0x0104) | mask(0xf)<<16)
```
`word1`が全MTOB共通の固定値であることを利用し、4byte刻みでこの値を探索すれば
直前のwordがAlphaTestのParamになる。

確認済みのFunction値: `Always`(無効時)、`Greater`(閾値以上を残す)。
`Notequal`/`Lequal`等の他のPICATestFunc値を使うマテリアルは実機データでは
未確認。

### CullMode(片面/両面描画)

2ワードのraw dump、固定ヘッダ定数`0x00010040`
(`GPUREG_FACECULLING_CONFIG(0x0040) | mask(1)<<16`)で同様にスキャン可能。
値: `0`=両面描画(Never)、`1`=表面カリング(裏面のみ描画)、`2`=裏面カリング
(表面のみ描画。通常の片面描画)。

### TexEnv(テクスチャコンバイナ)

マテリアルは最大6ステージのテクスチャコンバイナ設定を持つ。各ステージは
6ワードのConsecutiveコマンドブロックとしてシリアライズされる:
```
word0 = Source      (Color/AlphaそれぞれにつきConstant/Texture0-2/Previous/FragPrimary/FragSecondary等、3スロット)
word1 = header       = GPUREG_TEXENV<N>_SOURCE(0xC0 + N*8) | mask(0xf)<<16 | extraParams(4)<<20 | Consecutive(1)<<31
word2 = Operand
word3 = Combiner     (Color/AlphaそれぞれのPICATextureCombinerMode: Modulate/Interpolate/Add/AddSigned/MultAdd等)
word4 = Color        (定数色RGBA)
word5 = Scale
```
`word1`のヘッダはステージ番号N(0〜5)ごとに決まる固定定数(8刻み)なので、AlphaTest
と同じスキャン手法が使える。

- ステージ0(mapper 0)は常にベースメッシュのテクスチャとして描画する。
- ステージ1以降が`Texture1`/`Texture2`としてColor/Alphaいずれかのソースに
  登場するかどうかで、そのテクスチャが実際に固定機能コンバイナへ寄与するか
  どうかが確定できる(登場しないテクスチャは別シェーダ(SHDR、法線マップ等の
  非固定機能経路)専用の入力である可能性が高い)。
- 登場する場合のコンバイナモードは `Interpolate`→アルファブレンド、
  `Modulate`→乗算合成、`Add`/`AddSigned`/`MultAdd`等→加算系合成、に対応する。

**各モードは3つのソーススロットのうち実際に読む数が異なる**(SPICAのGLSL
生成コード(`FragmentShaderGenerator.cs`)で確認済みの対応): `Replace`はスロット0
のみ(1入力)、`Modulate`/`Add`/`AddSigned`/`Subtract`/`DotProduct3Rgb`/
`DotProduct3Rgba`はスロット0-1(2入力)、`Interpolate`/`MultAdd`/`AddMult`は
3スロット全て(3入力)を読む。モードの入力数を超えたスロットにも生のワード上は
値(余ったテクスチャID等)が残っているが、実際には評価されない。「Texture1/
Texture2のIDが3つのソースnibbleのどこかに出現するか」だけを見て、モードの
実入力数で切り詰めずに判定すると、未使用スロットのテクスチャを誤って
別ステージ/役割に帰属させてしまう。(`MONSTER/e001.bcmdl.lz`の`Material`で
実際に確認: ステージ0は`Modulate(Texture2, Texture0)`という2入力モードだが、
そのステージの未使用な3番目のColorソーススロットに`Texture1`のIDが残っている。
`Texture1`の本当の用途はステージ1の`MultAdd(Previous, FragmentPrimaryColor,
Texture1)`という3入力モードで、そこでは正真正銘の加算項として使われている。)

## CANM(スケルタルアニメーション)

スケルタルアニメは`.bcmdl`ではなく隣接する`.pack`の`SkeletalAnims` dictに格納。

### ボーンエントリの判別

CANMのボーンentryは`+0x08`の`GfxPrimitiveType`で格納形式が分岐する:
- `8` = `GfxAnimQuatTransform`: 1フレーム1サンプルの生配列形式。
- `5` = `GfxAnimTransform`: X/Y/Z各軸独立のHermite/StepLinear量子化圧縮カーブ
  (Euler角)形式。

### GfxAnimQuatTransform

- ボーンFlagsワードの`Inexistent`ビットでチャンネル(Rotation/Translation/Scale)の
  有無を判定。
- `bo+0x0c` / `+0x10` / `+0x14` の3ポインタがRotation/Translation/Scaleの
  チャンネルを直接指す。
- 各チャンネルは`IsConstant`フラグ(チャンネル自身のヘッダに格納)を持つ。
  `IsConstant=1`の場合、クリップ全体で1個の固定値のみを持つ。

### GfxAnimTransform

X/Y/Z軸ごとに独立したHermite補間またはStepLinear補間の量子化キーフレーム列。
Euler角として格納され、Euler→クォータニオン合成順はこのゲーム固有(標準的な
XYZ/ZYX合成とは異なる非標準の合成順。詳細な係数導出は実装参照)。Scaleチャンネルは
値が恒等スケール(1.0)付近でも実際のScaleトラックでありうるため、Translationとの
判別は形状(バイト長・値域)だけでは不確定な場合がある。

### フレーム数0(固定ポーズ)クリップ

`frames=0`のクリップは、1個の固定値(`IsConstant=1`のQuatTransformチャンネル)で
全フレーム同一の姿勢を表す。

## 既知の未解明事項

- 一部のCHARACTERモデル(`.pack`を持つもの536件中213件程度)で、特定のアニメ
  クリップ(`_idle`等)のボーンデータ領域に既知のどのヘッダパターン
  (`GfxAnimTransform`/`GfxAnimQuatTransform`とも)もマッチせず、トラック0件に
  なる現象が確認されている。原因・別フォーマットの有無は未解明。
- 同一スケルトン共有の仕組み上、1つのアニメーションクリップのボーントラックに、
  再生先モデルのスケルトンに存在しないボーン名(帽子・マント等ジョブ依存の
  装飾パーツ用)が含まれるケースがある。これはDQ7側の資産再利用の仕様であり、
  バグではない(欠損ではなく「元々そのモデルには無いボーン」)。
