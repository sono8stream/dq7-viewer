# モーション解決パイプライン（`MotionIndexManager` / `MotionIndexJobManager`）

フィールド・戦闘中のキャラクターが「どの`.pack.lz`内クリップを再生するか」を
解決する仕組み。ARM32コード(`code.decompressed.bin`)の静的解析と、修正パッチの
実機検証によって確定した構造。

## 全体ディスパッチ: `CharacterObject::getMotionIndex` (file offset `0x1853dc`)

`CharacterObject`の`+0x94`にある「カテゴリタグ」で分岐する:

```c
int CharacterObject::getMotionIndex(this, motionType) {
    switch (this->+0x94) {
    case 0x1000000: // person(プレイアブル)
    case 0x3000000: // person variant(操作中スロット等)
        slot = this->+0x8c;
        if (slot < 7)
            return MotionIndexJobManager::getInstance()
                     ->getJobCharacterMotionIndex(*(this+0x90), motionType, *(this+0x98));
        else
            return MotionIndexManager::getInstance()
                     ->getCharacterMotionIndex(*(this+0x90), motionType);

    case 0x2000000: // NPC/モンスター(戦闘寄りの扱い)
        idx = this->+0x8c;
        if (idx < 7 || idx == 0x34)
            return MotionIndexJobManager::getInstance()->getJobBattleMotionIndex(
                     motionType, 0xc, *(this+0x9c) ?: 0);
        else if (idx > 1000)
            return MotionIndexManager::getInstance()->getMonsterJobIndex(
                     motionType, (this->+0x98==0x34 ? 0x36 : this->+0x98), *(this+0x9c) ?: 0);
        else if (38 <= idx <= 45)
            return MotionIndexManager::getInstance()->getMonsterMotionIndex(
                     motionType, character_init_data[idx].field_0x68);
        else
            return MotionIndexManager::getInstance()->getBattleMotionIndex(motionType, idx);

    case 0x4000000: // モンスター
        return MotionIndexManager::getInstance()->getMonsterMotionIndex(
                 motionType, LevelDataUtility::getBaseMonsterNo(this->+0x8c));

    default:
        return -1;
    }
}
```

関連シンボル（file offset、素のROMベース）:

| file offset | シンボル |
|---|---|
| `0x184ac8` | `MotionIndexJobManager::getInstance` |
| `0x185000` | `MotionIndexManager::getInstance` |
| `0x184c04` | `LevelDataUtility::getBaseMonsterNo` |
| `0x26214` | `MotionIndexJobManager::getJobBattleMotionIndex` |
| `0x23ad8` | `MotionIndexManager::getMonsterJobIndex` |
| `0x184b30` | `MotionIndexManager::getMonsterMotionIndex` |
| `0x23c88` | `MotionIndexManager::getBattleMotionIndex` |
| `0x23e38` | `MotionIndexManager::getCharacterMotionIndex` |
| `0x263b0` | `MotionIndexJobManager::getJobCharacterMotionIndex` |
| `0x18390c` | `MotionIndexManager::readFile` |
| `0x1949d8` | `ExcelBinaryData::getRecordDynamic`（汎用レコード引き） |
| `0x194990` / `0x1949ac` | `HaveJob::getJobLevel` / `HaveJob::setJobLevel` |
| `0x123880` | `HaveJob::change` |

`MotionIndexJobManager`（job関連探索専用）と`MotionIndexManager`（汎用・モンスター含む）は
別クラスだが、いずれも内部のテーブル探索に`ExcelBinaryData::getRecordDynamic`を共通で使う。

## ファイル読み込みパターン

`MotionIndexManager::readFile`は`"%s.idx"`という書式でパスを組み立てる。候補文字列:

```
CHARACTER/person   → CHARACTER/person.idx
MONSTER/enemy      → MONSTER/enemy.idx
BATTLE/battle      → BATTLE/battle.idx
WEAPON/weapon      → WEAPON/weapon.idx
GOODS/goods        → GOODS/goods.idx
```

`CHARACTER/`配下には`person.idx`以外に`person.jidx`（job variant用）、
`person.matidx`、`person.jmatidx`という兄弟ファイルも存在する。
`BATTLE/`配下には同様に`battle.jidx`が存在する。

## `person.jidx` / `battle.jidx` の確定構造

両ファイルとも同一レイアウト（`battle.jidx`は`MotionIndexJobManager::getJobBattleMotionIndex`
(`0x26214`)が読む、戦闘用の対応物）:

```
header: u16 count
record (6byte, count件):
  +0x00 u16 characterId   (1=主人公, 2=マリベル, 3=キーファ, 4=ガボ, 5=メルビン, 6=アイラ)
  +0x02 u16 jobId         (0=無職 〜 20)
  +0x04 u16 subOffset     (ファイル先頭=header直後からの絶対オフセット)

サブブロック（各recordのsubOffsetが指す先）:
  {u16 motionKey, u16 result} の配列
  motionKeyは dq7_motion_list.dat のモーションタイプID、resultは
  .pack.lz内アニメクリップの解決に使われる最終的なモーションIndex
```

- `characterId`×`jobId`の組み合わせでレコードを引き、見つからなければ`-1`を返す
  （＝そのキャラクターは該当ジョブのモーションが一切紐付かない）。
- 素のROMでは、本編プレイアブル6人のうち5人（主人公・マリベル・ガボ・メルビン・アイラ）は
  `jobId=0〜20`の全21レコードが揃っているが、**キーファ(characterId=3)だけ
  `jobId=0`（無職）のレコード1件のみ**で、`jobId=1`以降のレコードが存在しない
  （転職を想定しないキャラクターとして開発されたことの直接的なデータ上の反映）。
- `getJobCharacterMotionIndex`(`0x263b0`)は`record[+0]`(characterId)を
  `*(CharacterObject+0x90)`経由の導出値と比較し、`record[+2]`(jobId)を
  `[CharacterObject+0x98]`の生値と比較する2軸一致探索。

## `CharacterObject::setMotion` のモーションタイプエイリアス

`setMotion(this, motionType, ...)`内でコード側にハードコードされた置換ロジック:

```c
if (motionType == 100 /*idle*/) motionType = 0;
if (motionType == 119 /*turn_l*/ || motionType == 120 /*turn_r*/) motionType = 101 /*run*/;
else if (motionType == 130 /*dash2*/) motionType = 102 /*dash*/;
idx = getMotionIndex(this, motionType);
```

## `LEVELDATA/dq7_motion_list.dat`（モーションタイプの「ID→名前」対応表）

```
header: u32 magic, u32 nrec(228), u32 rsize(28), u32 nrec_dup(228), u32 reserved  ; 計20byte
record (28byte):
  +0x00 u32 self_index
  +0x07 char[20] 名前(NUL終端)
  +0x1B u8  flag(0/1、意味未確定)
```

既知の対応（主要なもの）: `100=idle`, `101=run`, `102=dash`, `103=pop`, `104=out`, `130=dash2`。

## `CHARACTER/MotionListTable.dat`（キャラ非依存の共通テーブル）

```
header: u16 count(224)
record (4byte): u16 a(dq7_motion_list.datのID), u16 b(クリップ実体の参照先)
```

ほぼ全件`b==a`（自己参照）。例外3件（`idle(100)→0`, `pop(103)→2`, `out(104)→3`）は
バトル用の同名モーションをフィールド版が使い回すエイリアス。

## `HaveJob`（ランタイムオブジェクト、キャラごとの職業状態）

```
HaveJob
+0x04  u8     currentJob（現在の職業ID）
+0x05  u8[55] jobLevel[job_id]（職業ごとの習熟度・星0〜8、job_id=0〜54）
```

`HaveJob::change(this, jobId)`は`currentJob`を書き換えるだけで、転職可否の判定は
行わない（存在するなら`jobLevel[jobId]`が0の場合に1へ底上げするのみ）。

`dq7_player_job.dat`: 55レコード×188byte。`ExcelBinaryData::getRecordDynamic`
(`0x1949d8`)は直接インデックスアクセス: `record = job_id × recordSize + (header_ptr + 0x14)`
（`recordSize`は静的ディスクリプタの`+8`）。

## セーブデータ内の職業別starレベル配列

キャラクターレコード内、`job`（現在職業、相対`+0x0038`）の直後`+0x0039`から
`55byte`の配列が存在し、`job_id`をそのまま添字とする「職業別starレベル」を保持する
（`webapp/save_editor.py`の`CHAR_JOB_LEVELS_OFFSET=0x0039`/`CHAR_JOB_LEVELS_COUNT=55`）。

## フィールドとバトルで参照系統が異なる点

同一のキャラクター識別子・モデル差し替えでも、フィールド表示とバトル表示は
別の参照経路を通る（`getMotionIndex`のカテゴリ`0x1000000`/`0x3000000`がフィールド寄り、
`0x2000000`が戦闘寄り）。RomFSのモデル/アニメファイルを差し替える検証をする際は、
フィールド・バトルの両方を個別に確認する必要がある。

## `.pack.lz`内クリップ選択は名前ではなく位置インデックスで行われる

`SkeletalAnims`辞書は文字列キー付きだが、実際の再生時のクリップ選択は
辞書内の**並び順（インデックス番号）**に基づく。`person.jidx`/`battle.jidx`の
`result`フィールド（モーションIndex）は、このクリップリスト内の位置を指定する
インデックスとして使われる。このため、クリップ構成・並び順が異なるデータ同士を
入れ替えると、名前が一致していても全く別のモーションが再生される場合がある。
