# 章番号とイベントフラグの更新構造

## `GameParameter::setFlagShopParty` の処理内容

`StoryStatus`の章番号と、`day_index`型のtype0イベントフラグ一括セットは、
単一の関数`GameParameter::setFlagShopParty(int recordIndex)`の中で、同じ
テーブルの同じレコードから連続して行われる。

```c
// GameParameter::setFlagShopParty(int recordIndex) の該当部分（擬似コード）
Record* rec = ExcelBinaryData::getRecordDynamic(&g_table, recordIndex, ...);
u8 chapterNibble = rec->byte[0xa1] & 0x0f;            // レコード内の章情報
StoryStatus::setChapter(storyStatusInstance, chapterNibble + 1); // 章番号を更新
some_other_prep(recordIndex);                          // 未解析の前処理
GameParameter::setEventFlag(recordIndex);              // 同じrecordIndexをdayIndexとして
                                                        // type0フラグを一括セット
```

- `GameParameter::setEventFlag`は内部で`GameFlag::initialize`（vtable[5]）を
  呼び、type0/type1/type2のフラグ領域を**一旦全てゼロクリア**してから、
  `recordIndex`行の1レコード分のみを`GameFlag::set(type=0, ...)`で
  再セットする。「1行だけ反映」ではなく「毎回ゼロから作り直す」処理である。
- `GameParameter::setFlagShopParty`は全ROM中で参照箇所が1箇所のみ。
  呼び出し元は`GameParameter::execFlagShop`と`CheckPart::initialize`の
  2箇所。

## 設計上の帰結

章番号と`day_index`型のtype0イベントフラグは、常に同一の`recordIndex`から
セットで更新される設計になっている。そのため「`day_index`側だけ進んでいて
章番号だけ古い」という状態は、正規のコードパス上では発生し得ない組み合わせ
である。

## `StoryStatus`への参照箇所（章番号を読む側）

`StoryStatus`インスタンスへの参照は、確認できた範囲では以下のようなUI/
メニュー系のゲート判定に限られ、マップ/NPC表示系のクラス（`ScriptGroup`・
`ObjectAccess`・`TownSystem`等）からの参照は確認されなかった。

```
BattleExecItem03::setup, BattleExecStealItem01::setup, PartUtility::startTitle,
UserMessageMacroHook::PostProcess, SurechigaiMenuMain::endSurechigaiMessage43,
BankMenuMain::end/start, NameMenuMain::endMessageWindow/end,
TownJobMenu::onUpdate, TownTopMenu::onResult, TownReportMenu::onOpen,
TownTopTacticsMenu::onResult, TownStatusTargetMenu::onResult,
BattleCommandMenu::onResult, ContestMenuMain::endMessageWindow/
endContestMessage7, ContestRankingMenu::onDraw, HaveAction::isType,
GameParameter::setFlagShopParty
```

## ScriptGroupヘッダ構造（章別グループの有無）

SCRIPTファイル内の`ScriptGroup`は複数存在しうるが、ヘッダの`tag`フィールドは
全グループで共通して固定文字列`"scriptgroup"`であり、章やバリエーションを
示す識別子は含まれていない。グループ間の違いは`obj_count`/`header_size`等の
サイズ差のみで観測され、同一NPC群が複数グループに分けて配置されるのは、
章別の切り替えではなく天候/時間帯等のバリエーション単位である可能性が高い
（未確定）。

## 未確定のまま残る点

- `recordIndex`がゲームプレイ中にどう決定されるかの具体的なトリガー条件。
- 章・フラグ更新の間に呼ばれる前処理関数の中身。
- 参照先テーブルの構造・レコード数・各フィールド（offset+0x6,0x8,0xa,0xc,0xe
  はメッセージID群と見られるが未確認）。
- このテーブルと、イベントフラグ定義データ内のday_indexテーブルが同一の
  インデックス空間を指すかどうか。
