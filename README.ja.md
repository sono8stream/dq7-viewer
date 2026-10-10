[English](README.md)

# DQ7 Viewer

ニンテンドー3DS版『ドラゴンクエストVII エデンの戦士たち』のROMフォーマットを
解析して作ったWebベースのビュアー・エディタです。

🚧 開発中です。粗い部分・未実装の機能があります。

## これは何か

- `webapp/`: 抽出したRomFS/ExeFSのデータを閲覧・編集するためのローカルWebアプリ
  （Python標準ライブラリの`http.server`ベース、依存は最小限）
- `docs/formats/`: 解析で判明した、各種データ/バイナリフォーマットの構造仕様
  （オフセット・フィールド定義・アルゴリズム）。英語版が本体(`.md`)で、日本語版は
  各ファイルと同じフォルダに`.ja.md`として用意しています。

## これは何でないか

- **ROM・CIA・セーブデータそのものは一切含まれていません。** このリポジトリは
  解析ツールと解析結果（構造の事実）のみを公開するものです。
- `docs/formats/`配下のドキュメントは、調査の試行錯誤の過程やゲーム内の会話文・
  メッセージ本文の引用を含まない、構造的事実のみの技術仕様書として書き起こして
  います。

## 使い方

本ビュアーを動かすには、**あなた自身が合法的に所有するROM**から抽出した
RomFSのデータが別途必要です。このリポジトリにはROMの吸い出し・RomFS抽出
手順やツールは含まれていません。

### ROMデータの配置方法

リポジトリ直下（`webapp/`と同じ階層）に`rom/extracted/`というフォルダを作り、
その中にRomFSを展開したときの中身（`SCRIPT/` `MESS/` `LEVELDATA/` `CHARACTER/`
`MONSTER/` `TEXT/` `MENULIST/` `TEXTURE/` `MAP/` 等、RomFS本来のフォルダ名の
まま）をそっくりそのまま配置してください。

```
dq7-viewer/
├── webapp/
└── rom/
    └── extracted/
        ├── SCRIPT/
        ├── MESS/
        ├── LEVELDATA/
        ├── CHARACTER/
        ├── MONSTER/
        ├── TEXT/
        ├── MENULIST/
        ├── TEXTURE/
        ├── MAP/
        └── ...(RomFSの他のフォルダも同様にそのまま)
```

`rom/`フォルダ自体は`.gitignore`で追跡対象外にしてあるので、配置しても誤って
コミットされることはありません。RomFSの吸い出し・展開（CIAからの抽出等）は
GodMode9やCTR系ツールなど、既存の3DS ROMツールを各自利用してください
（本リポジトリはその工程を含みません）。

抽出済みRomFSを別の場所（他のチェックアウトと共有したい場合等）に置きたい場合は、
リポジトリ直下に配置する代わりに環境変数`DQ7_ROM_DIR`でその`rom/`フォルダのパスを
指定できます。

```
DQ7_ROM_DIR=/path/to/your/rom python3 server.py
```

### 起動

```
cd webapp
python3 server.py
```

詳細な起動オプション・APIについては`webapp/server.py`を参照してください。

## フォーマットドキュメント一覧

`docs/formats/`配下はROMの主要な構成要素に対応するサブフォルダに分かれています。

### `exefs/` — ExeFS(`.code`実行コード)内部構造

| ファイル | 対象 |
|---|---|
| `exefs_master_structures.md` | ExeFS内フィールド/エンカウント関連構造 |
| `exefs_symbol_recovery.md` | ExeFSの関数シンボル情報 |
| `save_player_data_container.md` | PlayerDataContainerとNCCH/ExeFSコンテナ構造 |
| `party_change_menu.md` | パーティ変更系メニューの内部構造 |
| `scriptgroup_chapter_flags.md` | 章番号とイベントフラグの更新構造 |
| `symbol_notes.md` | フィールドシンボル関連データの構造メモ |
| `gameflag_bitfield.md` | GameFlagのビットフィールド構造 |

### `save/` — セーブファイル構造

| ファイル | 対象 |
|---|---|
| `save_data_structures.md` | セーブデータ全体構造 |
| `play_time_field.md` | プレイ時間フィールド |
| `player_party_layout.md` | パーティ関連メモリ/セーブ構造 |

### `script/` — SCRIPTバイトコード

| ファイル | 対象 |
|---|---|
| `script_opcodes.md` | SCRIPTファイル(イベントスクリプト)フォーマット |

### `leveldata/` — `LEVELDATA/*.dat`系データテーブル

| ファイル | 対象 |
|---|---|
| `camera_and_encounter_data.md` | フィールドカメラ・エンカウントデータ |
| `character_status_data.md` | キャラクターステータス関連データファイル |
| `character_identity.md` | モデル番号⇔キャラID対応 |
| `partytalk_format.md` | partytalk系LEVELDATAファイルのフォーマット |
| `map_code_naming.md` | マップファイルID⇔地名の対応構造 |
| `mamono_master_classes.md` | モンスターがなつくシーケンスのバトルタスク構造 |
| `debug_data_tables.md` | 開発者向けデバッグ関連データ |
| `motion_index_manager.md` | モーション解決パイプライン |

### `models/` — 3Dモデル・アニメーション・画像

| ファイル | 対象 |
|---|---|
| `bcmdl_format.md` | 3DモデルフォーマットCGFX(BCRES) / `.bcmdl` |
| `canm_format.md` | 骨格アニメーション(CANM)フォーマット |
| `character_job_assets.md` | キャラクタービジュアルアセットの配置規則 |
| `face_expression_textures.md` | 表情差分テクスチャの格納形式 |
| `image_containers.md` | 画像コンテナ形式(bctex/bcmdl/dmp/fpt) |
| `map_pack.md` | マップモデルパック(`MAP/MAPDATA/*.pack.lz`): 部品・配置・コリジョン |

## 注意点

本リポジトリが公開するのは、解析によって判明したデータ構造に関する事実の記述と、
それを閲覧するための自作ツールのソースコードのみです。ゲームの著作物（ROM本体、
テキスト、画像、音声等）やその複製物は一切含みません。本ツールの利用にあたっては、
自身が適法に所有するソフトウェアからのみデータを抽出してください。
