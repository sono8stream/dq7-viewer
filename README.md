# DQ7 Viewer

ニンテンドー3DS版『ドラゴンクエストVII エデンの戦士たち』のROMフォーマットを
リバースエンジニアリングして作ったWebベースのビュアー・エディタです。

## これは何か

- `webapp/`: 抽出したRomFS/ExeFSのデータを閲覧・編集するためのローカルWebアプリ
  （Python標準ライブラリの`http.server`ベース、依存は最小限）
- `docs/formats/`: リバースエンジニアリングで判明した、各種データ/バイナリ
  フォーマットの構造仕様（オフセット・フィールド定義・アルゴリズム）

## これは何でないか

- **ROM・CIA・セーブデータそのものは一切含まれていません。** このリポジトリは
  解析ツールと解析結果（構造の事実）のみを公開するものです。
- `docs/formats/`配下のドキュメントは、調査の試行錯誤の過程やゲーム内の会話文・
  メッセージ本文の引用を含まない、構造的事実のみの技術仕様書として書き起こして
  います。

## 使い方

本ビュアーを動かすには、**あなた自身が合法的に所有するROM**から抽出した
RomFS/ExeFSのデータが別途必要です。このリポジトリにはその抽出手順・ツールは
含まれていません（手元の正規ROMから抽出したデータを`rom/`以下に配置する前提の
設計です）。

```
cd webapp
python3 server.py
```

詳細な起動オプション・APIについては`webapp/server.py`を参照してください。

## フォーマットドキュメント一覧

`docs/formats/`配下の各ファイルが対象とする構造:

| ファイル | 対象 |
|---|---|
| `bcmdl_format.md` | 3DモデルフォーマットCGFX(BCRES) / `.bcmdl` |
| `canm_format.md` | 骨格アニメーション(CANM)フォーマット |
| `character_identity.md` | モデル番号⇔キャラID対応 |
| `character_job_assets.md` | キャラクタービジュアルアセットの配置規則 |
| `character_status_data.md` | キャラクターステータス関連データファイル |
| `camera_and_encounter_data.md` | フィールドカメラ・エンカウントデータ |
| `debug_data_tables.md` | 開発者向けデバッグ関連データ |
| `exefs_master_structures.md` | ExeFS内フィールド/エンカウント関連構造 |
| `exefs_symbol_recovery.md` | ExeFSの関数シンボル情報 |
| `face_expression_textures.md` | 表情差分テクスチャの格納形式 |
| `gameflag_bitfield.md` | GameFlagのビットフィールド構造 |
| `image_containers.md` | 画像コンテナ形式(bctex/bcmdl/dmp/fpt) |
| `mamono_master_classes.md` | モンスターがなつくシーケンスのバトルタスク構造 |
| `map_code_naming.md` | マップファイルID⇔地名の対応構造 |
| `motion_index_manager.md` | モーション解決パイプライン |
| `party_change_menu.md` | パーティ変更系メニューの内部構造 |
| `partytalk_format.md` | partytalk系LEVELDATAファイルのフォーマット |
| `play_time_field.md` | プレイ時間フィールド |
| `player_party_layout.md` | パーティ関連メモリ/セーブ構造 |
| `save_data_structures.md` | セーブデータ全体構造 |
| `save_player_data_container.md` | PlayerDataContainerとNCCH/ExeFSコンテナ構造 |
| `script_opcodes.md` | SCRIPTファイル(イベントスクリプト)フォーマット |
| `scriptgroup_chapter_flags.md` | 章番号とイベントフラグの更新構造 |
| `symbol_notes.md` | フィールドシンボル関連データの構造メモ |

## ライセンス・法的な位置づけについて

本リポジトリが公開するのは、リバースエンジニアリングによって判明したデータ
構造に関する事実の記述と、それを閲覧するための自作ツールのソースコードのみです。
ゲームの著作物（ROM本体、テキスト、画像、音声等）やその複製物は一切含みません。
本ツールの利用にあたっては、自身が適法に所有するソフトウェアからのみデータを
抽出してください。
