# パーティ変更系メニューの内部構造（ExeFS側）

対象クラス: `CmdOpenPartyChangeMenu`（スクリプトVMのコマンド実装クラス）、
`PartyChangeMenu`、`TownFormationMenu`（いずれもFuncSearch.txtのシンボルから特定）。
file offsetはベースゲーム基準（32bit ARM固定長命令）。

## 前提・確度についての注記

`CmdOpenPartyChangeMenu`がスクリプト側の特定opcodeのハンドラであるという対応関係は、
クラス名・引数構造の一致という状況証拠に基づくもので、opcode番号から当該関数への
実行時ディスパッチ経路そのものを直接確認できてはいない。一方、以下で述べる
`CmdOpenPartyChangeMenu`・`PartyChangeMenu::onOpen`・`PartyChangeMenu::onResult`の
3関数が同一の構造体（同じ`this`ポインタ、同じフィールドオフセット）を一貫して
読み書きしていることは、デコンパイル結果から直接確認済みであり、これらが一体の
機能であること自体は内部的に整合している。

## `CmdOpenPartyChangeMenu::initialize`（file offset `0x220274`）

7個のパラメータ `[p0, p1, p2, p3, p4, p5, p6]` を受け取り、固定アドレスのシングルトン
構造体（`0x45b05c`経由）へ以下のようにコピーする:

```
singleton.field_0xa1c = params[2]
singleton.field_0xa20 = params[3]
singleton.field_0xa24 = params[4]
singleton.field_0xa28 = params[5]
singleton.field_0xa2c = params[6]
```

`params[0]`は後続のメッセージキューイング処理（file offset `0x14fa30`）の「開始ID」、
`params[1]`は「連続して積むページ数」として使われる（0以下なら即return、正なら
その回数だけIDをインクリメントしながらキューに積むループ）。

## `CmdOpenPartyChangeMenu::isEnd`相当（file offset `0x220314`）

シングルトンの状態バイトを見て完了判定を行い、完了していれば固定アドレス
`0x541730`（フラグ管理構造体）に対し `type=2, id=singleton.field_0xa30` の値で
フラグセットを行う。`field_0xa30`は`initialize`が書き込んだ5フィールド
（`0xa1c`〜`0xa2c`）とは別の、選択結果を格納する6個目のフィールド。

## `PartyChangeMenu::onOpen`（候補リスト構築、file offset `0x1073cc`系統）

```c
void PartyChangeMenu::onOpen(this) {
    party = PlayerParty::getInstance();
    this->a08 = party->b8;              // 生きているパーティの人数
    this->a1c = this->a20 = this->a24 = this->a28 = this->a2c = this->a30 = 0;
    this->a0c = this->a10 = this->a14 = this->a18 = 0;  // 候補リスト(4要素)初期化

    for (i = 0; i < this->a08; i++) {
        charId = <隊列スロットiからキャラIDを取得>;
        if (charId != 1) {               // 主人公(キャラID1)のみ除外
            candidate[compact_idx++] = charId;  // 4要素バッファに詰める（境界チェック無し）
        }
    }
}
```

要点:
- 除外されるのはキャラID1（主人公）のみ。他のキャラIDに対する除外条件は存在しない。
- 候補リストを格納するバッファ（`a0c`/`a10`/`a14`/`a18`）は物理的に4要素しかなく、
  5個目以降の候補を弾く境界チェックが存在しない。5個目を詰めようとした場合、
  バッファ直後に隣接するフィールド（`a1c`、本来は選択結果flag ID格納用）を上書きする。

## `PartyChangeMenu::onResult`（選択結果処理、file offset `0x107734`）

```c
void PartyChangeMenu::onResult(this, result_code) {
    cursor = this->a9a0;                 // 現在のカーソル位置
    if (result_code == 0) return;        // 未確定
    if (result_code == 1) {              // 決定
        tag = this->a0c[cursor];         // 候補配列から選択されたキャラIDを取得
        if (tag == 2) this->a30 = this->a1c;
        else if (tag == 4) this->a30 = this->a20;
        else if (tag == 5) this->a30 = this->a24;
        else if (tag == 6) this->a30 = this->a28;
        // tagが上記4値のいずれでもない場合、a30はこの分岐では更新されない
        if (this->a08 - 1 == cursor) {   // カーソルが候補リストの最後の位置と一致するなら
            this->a30 = this->a2c;       // 無条件で上書き
        }
    } else if (result_code == 2) {       // キャンセル
        this->a30 = this->a2c;
    } else if (result_code == 4) {
        <別の共通処理へ、詳細未解析>;
    }
}
```

要点:
- 候補配列に入っているキャラIDのうち、`2/4/5/6`という4つの固定値のみが
  `initialize`で受け取った対応するflag ID（`a1c`/`a20`/`a24`/`a28`）への割り当て
  対象になっている。これ以外のキャラID値（候補に含まれ得る他のID）は、このif連鎖
  では処理されない。
- カーソル位置が「候補リストの最後の1枠」と一致する場合は、上記のキャラID判定結果に
  関わらず無条件で`a2c`（フォールバック/キャンセル用flag ID）が採用される。この挙動は
  「キャンセル操作」と「候補リスト末尾の選択」のどちらでも同一のflagが立つことを意味する。
- 選択結果は、スクリプト側からは`isEnd`が立てる`type=2`フラグの状態としてのみ観測できる
  （個別の戻り値レジスタ等は介さない）。

## `TownFormationMenu`（別クラス、汎用実装）

`PartyChangeMenu`とは名称が類似するが実装は独立しており、キャラIDのハードコード
判定を一切含まない。

```c
void TownFormationMenu::onOpen(this) {
    count = PlayerParty::getInstance()->b8;
    this->a0c = count;
    this->a08 = (count >= 1);  // スロット0の「編成に含める」フラグ(bool)
    this->a09 = (count >= 2);
    this->a0a = (count >= 3);
    this->a0b = (count >= 4);
}

void TownFormationMenu::onDraw(this) {
    count = PlayerParty::getInstance()->b8;
    for (i = 0; i < count; i++) {
        if (<スロットiの「編成に含める」フラグが1>) {
            charId = <隊列スロットiのキャラID>;
            <汎用ステータス取得・行描画(スロット単位)>;
        }
    }
}
```

要点:
- 添字`i`は隊列配列のスロット番号であり、キャラIDそのものではない。
- 各スロットの表示可否は、キャラIDに基づく分岐ではなく、スロットごとに独立した
  ON/OFFフラグで決まる。
- `onResult`相当の処理も汎用ユーティリティ経由でスロット位置を操作しており、
  キャラID比較は登場しない。

## 2クラスの設計上の違い（まとめ）

| | `PartyChangeMenu` | `TownFormationMenu` |
|---|---|---|
| 候補/対象の単位 | キャラID（一部ハードコード） | 隊列スロット番号 |
| 選択結果の反映方式 | キャラID値の4パターンif分岐 + フォールバック | スロット単位の汎用ON/OFF |
| 候補バッファの上限 | 4要素固定（境界チェック無し） | 隊列人数に追従 |
| 除外対象 | キャラID1（主人公）固定 | なし（スロット単位で判定） |

## 関連関数（未解析・未確定）

- `TriggerPartyChange::onStart`（file offset `0x18aae4`）: `PlayerManager::getInstance()`
  を呼ぶのみの薄い実装で、実際の起動条件は別途マップ/トリガー関連データの調査が必要。
- `PlayerParty::reorder`（file offset `0x188c4c`）と、それを呼ぶ`fcn.0021a220`
  （file offset `0x21a220`）内の、4つの固定グローバルから値を読み「0でなくかつ7未満」
  のものだけを採用するハードコードされた`id<7`境界チェック。通常のパーティ変更処理とは
  別系統（特殊な強制パーティ構成関連と推定）。

## 未確定・未解明の点

- opcode番号から`CmdOpenPartyChangeMenu::initialize`への実行時ディスパッチ経路そのもの。
- `TownFormationMenu`が実際にどの場面・どの呼び出し経路（スクリプト経由か、C++側の
  直接トリガーか）で開かれるか。
- `Message::SetMacro`相当の呼び出しが選択結果の話者名差し込みにどう使われているかの詳細。
