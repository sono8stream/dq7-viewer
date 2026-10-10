"""
Web port of script/script_viewer.py (the tkinter GUI script inspector).

Termux has no display server, so the original tkinter app can't be shown
here. This serves the same script -> scriptgroup -> scriptobject ->
procedure -> block -> command tree, plus resolved MESS dialogue text for
message-display commands, over HTTP so it can be viewed from a phone
browser. Stdlib only (http.server) - no extra pip installs required.

Reuses script/script_viewer.py's structural parsing functions
(parse_script, parse_group_objects_header, parse_object) directly, with
`tkinter` stubbed out before import since it isn't installed/usable here
and the GUI class at the bottom of that file is never instantiated by
this server.

Message-ID resolution is a fresh, direct FPT0 parser (not
script_viewer.py's slower whole-repo-filesystem-walk heuristic) - see
mess/README.md for the format. Bucket = (msgid // 1000) * 1000 ->
MESS/#{bucket:06d}.fpt, entry named f'#{msgid:06d}.txt'. This was
cross-validated extensively during this session's investigation.

Usage:
  python3 webapp/server.py [--port 8000]
Then open http://<device-ip-or-localhost>:8000/ in a browser.
"""

import argparse
import base64
import datetime
import functools
import http.server
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import types
import urllib.parse

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Changes every server start - appended as a ?v=... query string to local
# <script src>/<link href> references in served HTML (see Handler.do_GET's
# .html branch) so browsers can never reuse a cached JS/CSS response from
# a previous run of this dev server. Cache-Control: no-store (below)
# handles *future* fetches; this handles the case a browser skips the
# network entirely via heuristic freshness and never asks the server at
# all - the actual bug hit this session (button existed from a fresh
# index.html fetch, but app.js was still served from a stale in-browser
# cache with no request ever reaching the server).
_ASSET_VERSION = str(int(time.time()))
_SCRIPT_DIR = os.path.join(_ROOT, 'script')
# rom/ の実体は環境変数 DQ7_ROM_DIR で差し替え可能（未指定時は <リポジトリ直下>/rom）。
# 複数のチェックアウト(作業用/公開用)で同じ抽出済みROMデータを共有したい場合に使う。
_ROM_DIR = os.environ.get('DQ7_ROM_DIR') or os.path.join(_ROOT, 'rom')
_ROMFS_DIR = os.path.join(_ROM_DIR, 'extracted')
_SCRIPT_FILES_DIR = os.path.join(_ROMFS_DIR, 'SCRIPT')
_SCRIPT_EDIT_BACKUP_DIR = os.path.join(_ROM_DIR, 'script_edit_backups')
_MESS_DIR = os.path.join(_ROMFS_DIR, 'MESS')
_LEVELDATA_DIR = os.path.join(_ROMFS_DIR, 'LEVELDATA')
_STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')


def _stub_tkinter() -> None:
    """Make script_viewer.py importable without a real tkinter install."""
    if 'tkinter' in sys.modules:
        return
    tkmod = types.ModuleType('tkinter')

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def __getattr__(self, item):
            return _Stub

        def __call__(self, *a, **k):
            return _Stub()

    def _mod_getattr(name):
        return _Stub

    tkmod.__getattr__ = _mod_getattr
    tkmod.Tk = object
    tkmod.Toplevel = object
    sys.modules['tkinter'] = tkmod
    for name in ('ttk', 'filedialog', 'messagebox'):
        m = types.ModuleType(name)
        m.__getattr__ = _mod_getattr
        sys.modules[f'tkinter.{name}'] = m
        setattr(tkmod, name, m)


_stub_tkinter()
sys.path.insert(0, _SCRIPT_DIR)
import script_viewer as sv  # noqa: E402
import save_editor  # noqa: E402
import splice_procedure as sp  # noqa: E402
import bcmdl  # noqa: E402  (LZ11 + CGFX .bcmdl model reader for the モデル viewer)
import dq7_rpc_probe as rpc_probe  # noqa: E402  (Azahar RPCサーバー経由のライブメモリプローブ、docs/keifa_job_animation_investigation.md)
import imagebrowser  # noqa: E402  (RomFS-wide image enumeration/decode for the 画像 viewer)


# ---------------------------------------------------------------------------
# MESS text resolution

_FPT_CACHE: dict = {}

# Opcode low-byte values observed to carry a [msgID u32][count u32] pair as
# their first two trailing params - see script/README.md for 0x09, and this
# session's investigation notes for 0x0a/0x0b/0x0d/0x0e.
#
# 【確定 2026-08-28】0x07と0x09の違い: ユーザーが実プレイで確認したところ、
# 両方ともメッセージ表示コマンドである点は同じだが、0x09は話者(NPC)が
# プレイヤーキャラの方を向く、0x07は向かない、という違いがある。全ROM
# スキャンでも0x00030007が1468件・0x00030009が11771件、両方とも
# param=[msgID, count]の2個で完全に一致する形をしていることを確認済み
# (script/README.mdの[msgID,count]慣習と一致)。0x0a/0x0b/0x0d/0x0eに
# 同種の派生形があるかは未調査。
_MESSAGE_OPCODE_LO = {0x07, 0x09, 0x0a, 0x0b, 0x0d, 0x0e}
# 上記のうち「話者がプレイヤーの方を向くかどうか」が確定しているのは
# 0x07(向かない)/0x09(向く)のペアのみ。
_MESSAGE_TURN_TO_PLAYER_LO = {0x07: False, 0x09: True}

# 【確定 2026-08-28】0x00010009と0x00030009の違い: ユーザーが実プレイで確認
# したところ、opcodeの上位16bit(バイト列で言うと3バイト目)が0x0001か0x0003
# かで実行頻度が変わる - 0x00030009は話しかけるたびに毎回再生されるのに対し、
# 0x00010009は「画面を切り替えるまで1度しか実行されない」。全ROMスキャンでも
# MSGファミリー(低byteが上記_MESSAGE_OPCODE_LOのいずれか)の上位16bitは例外
# なく0x0001か0x0003のどちらかで、両方の値を取る低byteが複数存在する
# (0x07/0x09/0x0a/0x0b全てで両方の上位16bit値が観測された。0x0d/0x0eは
# サンプル内では0x0001のみ)。上位16bitとメッセージの向き(turn_to_player)は
# 独立した別軸のフラグである(例: 0x00030007と0x00010007は両方とも
# 「向かない」だが再生頻度が異なる)。
#
# なお、この「0x0001 vs 0x0003」という上位16bitの分岐パターンは、以前
# 別のオペコードファミリーでも観測されていた(本ドキュメント
# docs/party_add_remove_command_investigation.mdの「op_00010004(分岐内の
# 汎用フラグ書き込み) vs op_00030004(分岐を閉じる"done"マーカー)」の節)。
#
# 【2026-10-03訂正】上記は「このコマンド単体の実行頻度」という理解だったが、
# 複数パターンの検証用NPCを実機で動かした結果、これは誤りだったと判明した。
# 正しくは: **if/elseifブロック内で物理的に最後に置かれたコマンドの上位16bit
# だけが意味を持ち、そのブロックに属する兄弟コマンド全員の完了状態を、
# ブロック終了時にまとめてリセットするかどうかを決める**。最後のコマンドが
# 0x0003ならブロック全体が毎回最初から再実行され(途中にある0x0001のコマンド
# も含めて)、最後のコマンドが0x0001ならブロック全体が1度きりで二度と
# 実行されない(途中にあった0x0003のコマンドも道連れになる)。つまり下記の
# `repeat_mode`は「このコマンド単体の性質」ではなく「このコマンドがブロック
# の最後に置かれていた場合にそのブロック全体がどうなるか」としてのみ
# 正しく解釈できる値であり、ブロック途中のコマンドに付いている場合はその
# コマンド自身の再実行可否には影響しない。ビュアーはこのコマンドが実際に
# ブロックの最後かどうかまでは判定していないため、`repeat_mode`の表示は
# あくまで生のopcode値の参考情報として扱うこと。
_MSG_REPEAT_MODE_HI16 = {0x0001: 'once_until_scene_change', 0x0003: 'repeats_every_time'}

# 【2026-09-30訂正】当初"JOIN_BANNER"(character joined the party専用)と
# 呼んでいたが、全ROMスキャンでmsgid別の実テキストを解決したところ、
# 「仲間になった」(style=36、52/52件)だけでなく、「{I_NAME}を手に入れた」
# 「〇〇を見つけた」のようなアイテム入手・イベント演出テキスト(style=44/45,
# 325件中270件以上)にも使われていることが判明した。すなわちこれは
# party-join専用コマンドではなく、**ジングル(効果音)付きの汎用「特殊演出
# メッセージ」コマンド**であり、「仲間になった」はそのうちの一用途に過ぎない。
# 96 00 01 00 [msgID][count=1][style][0][0][1]
# style: 36=仲間加入、44/45=アイテム入手/イベント演出、46=未分類(1件のみ)。
# docs/party_add_remove_command_investigation.md「JOIN_BANNERは実は仲間追加
# 専用ではなくアイテム入手等でも使われる汎用ジングルメッセージだった」節参照。
FANFARE_MSG_OPCODE = 0x00010096
# 後方互換のためのエイリアス(過去のコード/docsが参照している可能性がある)
JOIN_BANNER_OPCODE = FANFARE_MSG_OPCODE

# style値からこのコマンドの実際の用途をおおまかに分類する(全ROMスキャンで
# 確認した傾向。厳密な仕様ではなく観測に基づく目安)。
_FANFARE_MSG_STYLE_HINT = {
    36: 'party_join',   # 「〇〇が仲間にくわわった！」(52/52件で一致)
    44: 'item_or_event',
    45: 'item_or_event',
    46: 'item_or_event',  # 観測1件のみ(「生きうめにされた！」)、未確定
}

# "if" statement: reads a flag, paired with block1's if/elseif nesting
# depth (see script/README.md and
# docs/party_add_remove_command_investigation.md). Params: [flag_type,
# flag_id, expected_value]. Observed pattern: value=0 checks "not yet
# done", value=1 marks "done" after running that branch - a common
# one-shot-event idiom.
#
# 【確定 2026-09-27、docs/costa_npc_visibility_investigation.md参照】
# param0(旧"unk_param0") = **GameFlag::check(this, type, flag_id)の
# `type`引数**であることをヘッドレスGhidraなしのr2直接デコンパイルで確定した
# (base-game code.decompressed.bin、`GameFlag::check`のfileoffset 0x18f998):
#   type==0: this+0x218 のビット配列を参照（word=flag_id>>5, bit=flag_id&0x1f）
#   type==1: this+0x418 のビット配列を参照
#   type==2: this+0x008 のビット配列を参照
#   それ以外: 常にfalse
# `GameFlag::serialize`はthis+0x208から0x250(592)byteをそのままセーブへ
# コピーするため、**type0(+0x218)とtype1(+0x418)はセーブに永続化されるが、
# type2(+0x8)はコピー範囲(+0x208~+0x458)より前にあるため一切セーブされない
# (=起動のたびに`GameFlag::initialize`のゼロクリアに戻る、非永続の一時フラグ)**。
# オンディスク換算: type0 flag_id → file 0x20+id//8 (`FLAGS_REGION_BASE`と
# 完全一致、既存の`save_editor.place_visit()`はtype0のみを前提にしていた点に
# 注意)、type1 flag_id → file **0x220**+id//8 (type0とは0x200byteずれた別の
# バイト列！)。過去のアドホックな「type1のフラグを立てる」実験でtype0と
# 同じ`0x20+id//8`の式を使っていた場合、それは全く別のtype0側ビットを
# 誤って書き換えていたことになる(要再検証)。
IF_FLAG_OPCODE = 0x00000003

# 【確定 2026-09-27】op_00010004 = **GameFlag::set(this, type, flag_id, value)**
# である可能性が高い。`GameFlag::set`(fileoffset 0x18b00c)は同じ
# type0=+0x218 / type1=+0x418 / type2=+0x8 のバケット構造にビットを立てる
# (type==3は type0とtype1の両方に同時に立てる特殊値、CHECK側にtype3は存在
# しない)。IF_FLAGと同じ(type,id)アドレス空間を共有しているとみられる
# ((type,id,value)という3パラメータの形も一致)。上のIF_FLAG_OPCODEのコメント
# にある「type1は0x220+id//8、type2は非永続」という換算がSET側にもそのまま
# 適用できる。
SET_FLAG_OPCODE = 0x00010004

# 【確定 2026-08-28】"talked to" branch: user confirmed this is the branch
# condition that becomes true when the player talks to this scriptobject.
# Full-ROM scan (2026-08-28, ad-hoc): 9044 occurrences, ALL as command #0
# of an 'execute' procedure (i.e. this is the near-universal entry gate
# of an NPC's talk handler), ALWAYS exactly 1 param - value is 0 in 8548
# occurrences, 1 in 258, 2 in 238 (meaning of the non-zero values
# unconfirmed - possibly distinguishes talk/examine/push-style
# interactions, or a per-scene variant). Same if/elseif-nesting-depth
# idiom as IF_FLAG: the branch body (e.g. the MSG command actually shown
# when talked to) sits at indent+1 immediately after this command.
TALKED_TO_OPCODE = 0x0000000f

# 【確定 2026-09-29、ユーザー確認】"is KO'd" branch condition: params=
# [character_id, mode]. mode==1: branch taken when the character is
# incapacitated (戦闘不能/KO'd). mode==0: branch taken when the character
# is alive. Previously mis-tagged in docs/party_add_remove_command_
# investigation.md and docs/script_object_insertion.md as an "actor
# window open/close bracket" based on its frequent [N,0]/[N,1] paired
# appearance around dialogue - that guess is superseded by this
# confirmation (the [N,0]/[N,1] pairs were simply "branch if alive" /
# "branch if KO'd" checks on the same character, not open/close brackets).
IF_KO_STATUS_OPCODE = 0x00000070

# 【2026-10-03に「戦闘開始コマンド」と確定したが、2026-10-04に誤りと判明、
# 訂正】当初このopcodeのハンドラが`script::cmdEncountSetFlag`
# (file offset 0x21b3c0)を呼ぶと記録していたが、これは取り違いだった。
# low16=0x1b(27)の下位16bitディスパッチャ(index 0x1b → VA 0x316aac、
# file offset 0x216aac)を改めてr2で逆アセンブルし直すと、実際に呼んでいる
# のはfile offset 0x21cc04(`script::cmdSetMapObjNumber`, VA 0x31cc04)
# ——「マップ上のオブジェクト数設定」であり、戦闘とは無関係。
# `script::cmdEncountSetFlag`(0x21b3c0)を実際に呼んでいるのは
# opcode 0x24の方だった(`ENCOUNT_SET_FLAG_OPCODE`参照)。
# 本opcode(0x1b)の実際の役割(`cmdSetMapObjNumber`が何をするか)は未調査。
# 詳細な訂正の経緯は`docs/battle_start_opcode_investigation.md`
# 「【重大な訂正】」節を参照。
SET_MAP_OBJ_NUMBER_OPCODE = 0x0000001b

# 【確定 2026-10-04】`script::cmdEncountSetFlag`(file offset 0x21b3c0,
# VA 0x31b3c0)を呼ぶ本体。全ROM横断スキャンで136件発見、全て
# params=[1, flag_id, type, value]という4パラメータ形式(params[0]は
# 観測範囲内では常に1)。r2での完全な関数逆アセンブル(pdf)で各paramの
# 使われ方を確認した:
#   - params[0]: 関数内で一度も読まれていない(未使用、常に1)。
#   - params[1](flag_id): 特殊分岐判定(==0x11d(285)なら全く別の処理、
#     パーティ関連らしきグローバル構造体操作)に使われたあと、通常パスでは
#     グローバルなエンカウント状態構造体(0x541184付近、複数フィールド)の
#     flag_id系フィールドへ格納される。観測値は164〜268という狭い範囲に
#     集中しており、固定サイズテーブルへのインデックスの可能性が高い。
#   - params[2](type): バイトマスク(&0xff)されたうえで`fcn.00126140`
#     (エンカウントレコードらしきものを操作する関数、引数:
#     ベースアドレス0x541bec, type, value, 定数2, 定数9999(0x270f))の
#     第2引数として渡される。観測値は0・1・2のみ。
#   - params[3](value): fcn.00126140の第3引数(マスクなし)。観測値は
#     5〜2091と幅広く、おそらく実際に使うモンスターグループID等の
#     本体的な値だと推測される(これまでSTART_BATTLEの唯一の引数だと
#     誤認していた値はおそらくこれに近い)。
#   - この後、fcn.00126140呼び出しの直後に無条件(params由来ではない固定の
#     r0=0xf, r1=0)でfcn.0012a870(推定PartUtility::startBattle)を呼んで
#     いる。固定引数のため、「どの戦闘が始まるか」はこの呼び出し自体では
#     なく、直前のfcn.00126140呼び出しで登録された内容がエンジン側で
#     後から参照される、という間接的な構造になっている可能性が高い。
#
# 【実機検証済み 2026-10-05】m01nk1f1.binにIF_TALKED_TO等を一切介さず
# このコマンド単体(params=[1,237,1,10]、m29nout.binの実在イベントの値を
# そのまま流用)を無条件initializeに置いたところ、実機でマップ読み込み
# 直後に実際に戦闘が開始することを確認した。これにより「0x1bではなく
# 0x24が本物の戦闘開始コマンドである」という訂正が実証された。
# 詳細・今後の調査方針は`docs/battle_start_opcode_investigation.md`参照。
ENCOUNT_SET_FLAG_OPCODE = 0x00000024

# 【確定 2026-09-29、`script::cmdIsPartyMember`(file offset 0x219c44)の
# r2逆アセンブルで確定】"is currently a living party member" branch
# condition: params=[character_id]（modeパラメータ無し、常に「該当キャラが
# 現在の生存パーティにいるか」の1択）。中身は`PlayerParty`相当の配列を
# 走査して`character_id`と一致する要素を探すだけの素直な線形探索
# （`PartyChangeMenu::onOpen`の候補構築ループと全く同じアクセサパターン）。
# 一致すれば分岐成立(true)、しなければ不成立。
# `docs/party_add_remove_command_investigation.md`「原因判明:
# op_0000006fの正体」節参照。過去に「実行すると対象キャラの表示状態に
# 副作用(消失)」と誤解されていたが、それは単にこの命令が実はIF_FLAGと
# 同じ「if/elseifネスト深さ」の条件分岐オペコードであり、対応する
# ネスト先コマンドを用意せず単独の"アクション"として誤挿入したことによる
# 構造崩れが原因だったと判明した。
IF_IS_PARTY_MEMBER_OPCODE = 0x0000006f

# "Add/remove party member" - confirmed on real hardware (2026-08-22, see
# docs/party_add_remove_command_investigation.md): inserting
# `0x00010022 [character_id, 0]` into a script actually adds that
# character to the save's Party array (turtle-insect/DQ7 save editor:
# 6 fixed slots at 0x0510) and the "XXXが仲間にくわわった" banner then
# plays for real. 0x00010023 is the same shape but used by a different
# subset of characters (Melvin/Hank observed) - the 0x22 vs 0x23 split is
# not understood yet. NOTE: this alone does not populate the character's
# stats slot (Charactors array, 6 slots at 0x0C80) - the character is
# added to the party roster but does not show up on the status screen or
# animate in battle without also going through PARTY_SLOT_ACTIVATE below.
#
# 【確定 2026-09-23、docs/party_add_remove_command_investigation.md参照】
# ヘッドレスGhidra(rom/exefs/code.decompressed.bin)で`CmdPartyJoin::initialize`
# (file offset 0xf638)を解析した結果、params[1](従来「常に0の予備フラグ」と
# 見なしていた値)は実は**add/removeの動作モード切り替え**であることが確定した:
#   - params[1]をbool変換した結果が偽(0、実在スクリプトで常に観測される値)
#     → `PlayerManager::addPlayer(character_id)`を呼ぶ(=ADD)
#   - 真(0以外) → `PlayerManager::delPlayerIndex(character_id)`を
#     tail-callする(=REMOVE)。この関数は内部で`PlayerParty::delMember`
#     (file offset 0x9fec、指定キャラIDをParty配列から探して削除し、
#     隙間を前方の非0要素で詰めるロジック)を呼んでおり、完全に動作する
#     削除処理であることも確認した。
# **すなわちこのコマンドは単なる「追加専用」ではなく、真の「Add/Remove両用」
# コマンドである。params[1]を0以外(例えば1)にするだけで、既存のパーティ
# メンバーを外す処理として使える見込みが高い(ユーザー提供の情報により確定、
# 実機での動作確認は別途必要)。**
ADD_PARTY_MEMBER_OPCODES = {0x00010022, 0x00010023}

# Companion opcode observed exclusively in "character rejoins" cutscenes
# (SCRIPT/m01nm2f2.bin's endgame reunion hub): params=[1-based party slot
# index, 1]. Appears immediately after the party-join usage of
# FANFARE_MSG (style=36, formerly called "JOIN_BANNER") in every sampled
# rejoin branch (8/8 samples across 4 characters). Suspected to
# "activate"/link the target party slot, but empirically (2026-08-22
# on-device test) adding this after ADD_PARTY_MEMBER still did not make
# the newly-added character selectable in the formation-change menu -
# so its exact role is still unconfirmed. See docs/ for the ongoing
# investigation.
PARTY_SLOT_ACTIVATE_OPCODE = 0x00010064

# Always observed with the SAME first param as a later
# PARTY_SLOT_ACTIVATE call in the same branch (8/8 samples), but occurs
# many more times per scene (looks like a read/branch-condition check
# rather than a write) - tentative name, not confirmed to have any
# necessary effect.
PARTY_SLOT_QUERY_OPCODE = 0x00010093

# Yes/No confirm choice - tentative name, hypothesis from the user
# (2026-08-23) while debugging why the transplanted Maribel rejoin scene
# (see docs/party_add_remove_command_investigation.md) stalls around
# here. params=[var_type, var_id, cancel_value]: pops a yes/no prompt,
# writes the result into flag(var_type, var_id) (matching the same
# (type,id) pair read immediately afterward by IF_FLAG in every sampled
# occurrence), and cancel_value is what gets written if the player
# backs out without answering. Not yet confirmed on real hardware -
# under active investigation as a possible cause of the stall (a
# real-UI confirm prompt may behave differently / not resolve at all in
# this transplanted, out-of-context scene).
CONFIRM_YESNO_OPCODE = 0x00010025

# Multi-choice "who stays behind" menu - confirmed via a full-ROM scan
# (2026-08-25, script/scan_opcode_0x100c5.py): only 20 occurrences exist
# in the whole game, at 5 call sites (Maribel/Gabo/Melvin/Aira each
# asking "who takes my place?" in the m01nm2f2.bin endgame reunion, plus
# the sister-transplant copy in m01nk1f1.bin), each appearing 4x (the
# "unrolled retry loop" pattern - see docs/). ALL 20 occurrences have
# exactly 7 params: [msgID, count, slot2_flag_or_0, slot3_flag_or_0,
# slot4_flag_or_0, slot5_flag_or_0, slot6_flag_or_0] - one flag id per
# party formation slot 2-6, set to 1 when that slot's character is
# picked. Confirmed pattern: whichever slot the ASKING character
# currently occupies has 0 in their own slot position (can't pick
# yourself) - e.g. Maribel (slot2) has 0 first, Gabo (slot3) has 0
# second, etc.
#
# 【2026-09-23 exefs調査、docs/opcode_0x100c5_exefs_investigation.md参照。
#  ただし「このopcode番号から実際にこの関数群へ分岐する経路」自体は未確認――
#  クラス名・引数の形が一致するという状況証拠のみで、詳細は下記docsの
#  「重要な訂正」節を参照】`CmdOpenPartyChangeMenu`/`PartyChangeMenu::onOpen`/
# `PartyChangeMenu::onResult`という、同じ構造体(固定アドレス0x45b05cの
# シングルトン)を一貫して読み書きする3関数を解析した結果:
#   - params[1](旧称p1)は、msgIDをインクリメントしながらページをキューに
#     積むループの回数として使われており、「msgIDから始まる連続ページ数」で
#     ある可能性が高い(既存のMSGファミリーの[msgID,count,...]慣習と一致)。
#   - params[2..6]はシングルトン構造体の+0xa1c/+0xa20/+0xa24/+0xa28/+0xa2cに
#     コピーされるが、【重要】これらは「隊列スロット2〜6」ではなく
#     **MENULIST/party_menu.txtのキャラID2/4/5/6(マリベル/ガボ/メルビン/
#     アイラ)専用にハードコードされたif-elseif連鎖のインデックス**だった。
#     つまりparams[2]=マリベル用flag, params[3]=ガボ用flag,
#     params[4]=メルビン用flag, params[5]=アイラ用flag。
#   - **params[6](旧称"slot6_flag")は実際には「上記4人のいずれにも一致しない
#     場合、およびメニューをキャンセルした場合」に使われるフォールバック/
#     キャンセル用flag id**(ユーザーの2026-09-23の指摘通り)。表示された
#     候補リストの最後の項目を選んだ場合も、identity判定より優先してこの
#     flagが使われる。
#   - 結論: 候補リストの構築自体(`onOpen`)は生きているパーティを動的に走査
#     しているが、選んだ結果をflagへ変換する処理(`onResult`)がキャラID
#     2/4/5/6の4人決め打ちになっているため、**この経路のままではキーファや
#     マチルダ・ハンクを含む可変パーティ向けの自由入れ替えには使えない**――
#     ユーザーが当初懸念していた「4人固定でないと動かないのでは」は、
#     この特定の識別ロジックに関する限り正しかった。
CHOICE_MENU_OPCODE = 0x000100c5

# Dynamic position-set command - user hypothesis (2026-08-27), not yet
# independently re-verified against other occurrences: the 3 params seen
# in this session's Maribel-transplant test data are u32 bit patterns
# that decode as plausible floats when reinterpreted (e.g. 1065353216 ==
# 0x3F800000 == 1.0f), matching the (x, y, z) shape of the NPC placement
# table's pos_x/pos_y/pos_z fields (see _NPC_PLACEMENT_FIELD_DEFS above,
# all confirmed on real hardware 2026-08-27) - i.e. this command likely
# moves/teleports an actor to a new position at script-runtime, as
# opposed to the placement table's static initial position.
SET_POSITION_OPCODE = 0x00010014

# 【確定 2026-08-30】object有効/無効切り替え - ユーザーが実機で発見・確定。
# params=[target]: 対象は同じgroup内の「(target+1)番目のobject」(0-based
# index target+1)。docs/script_object_insertion.md の「乗っ取りでもobj9だけ
# 表示されない」現象の原因がこれで判明した: m01nk1f1.bin group3のobj0の
# initializeにこの命令(0x10005, param=8)があり、これがobj9(index9=8+1)の
# 表示可否を切り替えていた。実機で0x10005 8を実行するとobj9が表示される
# ことを確認済み。on/offどちらの操作かは未確定(トグルなのか、常にonにする
# ものなのかは今回の検証だけでは分からない)。
OBJECT_TOGGLE_OPCODE = 0x00010005

# 【有力な仮説 2026-08-31】マップ移動(ワープ)命令。全SCRIPT走査
# (script/scan_opcode_0x1001f.py)で1121件、全て'execute'プロシージャ内。
# params = [dst_floor_id, x_f32, y_f32, z_f32, facing, flag5](常に6個):
#   param[0] = 移動先フロアID。LEVELDATA/dq7_floor_list.dat のレコード
#              +0x04(u16)と一致する。例: 407 -> m01nm2f2, 2 -> c01nf1,
#              301 -> h01nout1, 5161 -> wld_n25a(ワールドマップタイル)。
#              ユーザー観測の「407 = m01nm2f2」と完全一致。
#   param[1..3] = 移動先座標(x, y, z)をf32として解釈。SET_POSITION
#              (0x00010014)やNPC配置テーブルのpos_x/pos_y/pos_zと同じ
#              並び・スケール。y(param[2])は890/1121で0.0(地面)、
#              x/zは -393〜+228 の広い範囲で妥当なワールド座標に見える。
#   param[4] = 0..3 の小さな値(0:567 / 2:360 / 1:109 / 3:85)。移動後の
#              向き(4方位)と推測(未確定)。
#   param[5] = 0(1038) か 1(83) のフラグ。意味未確定
#              (フェード有無/カメラ引き継ぎ等の候補)。
# 直前のオペコードは 0x00010004 が圧倒的(738件で2つ前も含めて連続) -
#              画面フェードアウト系の命令ではないかと推測(未調査)。
# 実機でのワープ実行そのものは未検証(IDと座標の対応関係が資料的に
# 裏付けられた段階)。
MAP_WARP_OPCODE = 0x0001001f

_floor_list_full_cache = None
_floor_id_to_name_cache = None
_warp_index_cache = None


def parse_floor_list_full() -> list:
    """Parse LEVELDATA/dq7_floor_list.dat -> ordered list of records.

    Record layout (16 bytes, table starts at 0x20): +0x00 u32 (unused, 0
    in every observed row), +0x04 u16 floor_id (the value opcode
    0x0001001f's param[0] carries), +0x06 u16 group idx, +0x08 char[8]
    mapcode name (e.g. 'm01nm2f2', 'c01nout', 'wld_n25a'). Verified: the
    row named 'm01nm2f2' has floor_id 407, matching the user's
    observation, and 'c01nf1' -> 2, 'h01nout1' -> 301, etc.

    Each returned dict: {rec_index, floor_id, group, mapcode, unk0,
    raw_hex}. Rows with an empty mapcode (blank/padding slots that still
    consume an id) are kept so rec_index stays meaningful.
    """
    global _floor_list_full_cache
    if _floor_list_full_cache is not None:
        return _floor_list_full_cache
    out = []
    path = os.path.join(_LEVELDATA_DIR, 'dq7_floor_list.dat')
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        _floor_list_full_cache = out
        return out
    off = 0x20
    idx = 0
    while off + 16 <= len(data):
        rec = data[off:off + 16]
        unk0 = struct.unpack_from('<I', rec, 0)[0]
        fid = struct.unpack_from('<H', rec, 4)[0]
        grp = struct.unpack_from('<H', rec, 6)[0]
        mapcode = rec[8:16].split(b'\x00')[0].decode('ascii', 'replace')
        # printable mapcodes only - the world-map tail of the table has a
        # few rows whose name bytes aren't clean ascii; skip labelling
        # those but still count the slot.
        if any(ord(c) < 0x20 or ord(c) > 0x7e for c in mapcode):
            mapcode = ''
        out.append({
            'rec_index': idx,
            'floor_id': fid,
            'group': grp,
            'mapcode': mapcode,
            'unk0': unk0,
            'raw_hex': rec.hex(),
        })
        off += 16
        idx += 1
    _floor_list_full_cache = out
    return out


def load_floor_list() -> dict:
    """{floor_id: mapcode_name} view of parse_floor_list_full() - used by
    _decode_command() to label MAP_WARP destinations."""
    global _floor_id_to_name_cache
    if _floor_id_to_name_cache is not None:
        return _floor_id_to_name_cache
    out = {}
    for r in parse_floor_list_full():
        if r['mapcode'] and r['floor_id'] and r['floor_id'] not in out:
            out[r['floor_id']] = r['mapcode']
    _floor_id_to_name_cache = out
    return out


def _f32_from_u32(u: int) -> float:
    return round(struct.unpack('<f', struct.pack('<I', u & 0xFFFFFFFF))[0], 4)


def build_warp_index() -> dict:
    """Single read-only pass over every SCRIPT/*.bin collecting every
    MAP_WARP (opcode 0x0001001f) command. Cached after the first call
    (the scan touches ~1300 files and takes a couple of seconds).

    Returns {'by_dst': {floor_id: [entry, ...]},
             'by_file': {filename: [entry, ...]},
             'scanned_files': int, 'total_warps': int}
    where entry = {file, group_idx, obj_idx, obj_tag, proc_tag, cmd_idx,
    dst_map_id, dst_map_name, pos:[x,y,z], facing, flag5, params}.
    """
    global _warp_index_cache
    if _warp_index_cache is not None:
        return _warp_index_cache

    id2name = load_floor_list()
    by_dst = {}
    by_file = {}
    scanned = 0
    total = 0
    try:
        files = sorted(f for f in os.listdir(_SCRIPT_FILES_DIR) if f.endswith('.bin'))
    except OSError:
        files = []

    for fn in files:
        try:
            with open(os.path.join(_SCRIPT_FILES_DIR, fn), 'rb') as f:
                data = f.read()
        except OSError:
            continue
        scanned += 1
        if len(data) < 0x20:
            continue
        try:
            groups = sp._parse_ref_table(data, 0, 0x10, 0x18, sp._read_u32(data, 0x14))
        except (struct.error, IndexError):
            continue
        for g_idx, group in enumerate(groups):
            gs = group['abs_offset']
            if gs + 0x20 > len(data):
                continue
            try:
                objs = sp._parse_ref_table(data, gs, 0x10, 0x18, sp._read_u32(data, gs + 0x14))
            except (struct.error, IndexError):
                continue
            for o_idx, obj in enumerate(objs):
                obs = obj['abs_offset']
                if obs + 0x20 > len(data):
                    continue
                obj_tag = data[obs:obs + 0x10].rstrip(b'\x00').decode('ascii', 'replace')
                try:
                    procs = sp._parse_ref_table(data, obs, 0x10, 0x18, sp._read_u32(data, obs + 0x14))
                except (struct.error, IndexError):
                    continue
                for proc in procs:
                    prs = proc['abs_offset']
                    if prs + 0x20 > len(data):
                        continue
                    proc_tag = data[prs:prs + 0x10].rstrip(b'\x00').decode('ascii', 'replace')
                    try:
                        blocks = sp._parse_ref_table(data, prs, 0x10, 0x18, sp._read_u32(data, prs + 0x14))
                    except (struct.error, IndexError):
                        continue
                    if len(blocks) < 3:
                        continue
                    b2, b3 = blocks[1], blocks[2]
                    if b2['abs_offset'] + b2['size'] > len(data) or b3['abs_offset'] + b3['size'] > len(data):
                        continue
                    offs = [struct.unpack_from('<I', data, b2['abs_offset'] + i * 4)[0]
                            for i in range(b2['size'] // 4)]
                    for cmd_idx in range(len(offs) - 1):
                        s, e = offs[cmd_idx], offs[cmd_idx + 1]
                        if e <= s or e - s < 4:
                            continue
                        a = b3['abs_offset'] + s
                        if a + 4 > len(data):
                            continue
                        if struct.unpack_from('<I', data, a)[0] != MAP_WARP_OPCODE:
                            continue
                        params = []
                        off = a + 4
                        while off + 4 <= b3['abs_offset'] + e:
                            params.append(struct.unpack_from('<I', data, off)[0])
                            off += 4
                        if len(params) < 4:
                            continue
                        entry = {
                            'file': fn,
                            'group_idx': g_idx,
                            'obj_idx': o_idx,
                            'obj_tag': obj_tag,
                            'proc_tag': proc_tag,
                            'cmd_idx': cmd_idx,
                            'dst_map_id': params[0],
                            'dst_map_name': id2name.get(params[0], ''),
                            'pos': [_f32_from_u32(params[1]), _f32_from_u32(params[2]), _f32_from_u32(params[3])],
                            'facing': params[4] if len(params) >= 5 else None,
                            'flag5': params[5] if len(params) >= 6 else None,
                            'params': params,
                        }
                        total += 1
                        by_dst.setdefault(params[0], []).append(entry)
                        by_file.setdefault(fn, []).append(entry)

    _warp_index_cache = {
        'by_dst': by_dst,
        'by_file': by_file,
        'scanned_files': scanned,
        'total_warps': total,
    }
    return _warp_index_cache


def floor_list_overview() -> dict:
    """Payload for the フロア viewer's list pane: every floor_list.dat
    record annotated with whether a matching SCRIPT/<mapcode>.bin exists
    and how many MAP_WARP commands point to / leave from that floor."""
    recs = parse_floor_list_full()
    widx = build_warp_index()
    by_dst = widx['by_dst']
    by_file = widx['by_file']
    try:
        script_names = set(os.listdir(_SCRIPT_FILES_DIR))
    except OSError:
        script_names = set()
    entries = []
    for r in recs:
        script_file = ''
        if r['mapcode'] and f"{r['mapcode']}.bin" in script_names:
            script_file = f"{r['mapcode']}.bin"
        entries.append({
            **r,
            'script_file': script_file,
            'warps_in': len(by_dst.get(r['floor_id'], [])),
            'warps_out': len(by_file.get(script_file, [])) if script_file else 0,
        })
    return {
        'source': 'LEVELDATA/dq7_floor_list.dat',
        'record_count': len(recs),
        'scanned_script_files': widx['scanned_files'],
        'total_warp_commands': widx['total_warps'],
        'entries': entries,
    }


def floor_detail(floor_id: int) -> dict:
    """Detail pane payload for one floor: the record, the SCRIPT file (if
    any), every MAP_WARP that targets this floor (warps_in), and every
    MAP_WARP inside this floor's own SCRIPT file (warps_out)."""
    recs = parse_floor_list_full()
    rec = next((r for r in recs if r['floor_id'] == floor_id), None)
    widx = build_warp_index()
    script_file = ''
    if rec and rec['mapcode']:
        try:
            if f"{rec['mapcode']}.bin" in set(os.listdir(_SCRIPT_FILES_DIR)):
                script_file = f"{rec['mapcode']}.bin"
        except OSError:
            pass
    return {
        'floor_id': floor_id,
        'record': rec,
        'script_file': script_file,
        'warps_in': widx['by_dst'].get(floor_id, []),
        'warps_out': widx['by_file'].get(script_file, []) if script_file else [],
    }


# --- エンカウント (dq7_encount_data.dat) ビュア --------------------------------
# レコード構造の解読は docs/camera_encount_investigation.md
# 「dq7_encount_data.dat レコード構造の解読」を参照。

_TEXT_DIR = os.path.join(_ROMFS_DIR, 'TEXT')
_name_cache: dict = {}


def _load_name_csv(fname: str) -> dict:
    """TEXT/<fname> ( `id,"name"` CSV、name 内の ; は改行 ) -> {id: name}."""
    if fname in _name_cache:
        return _name_cache[fname]
    out: dict = {}
    path = os.path.join(_TEXT_DIR, fname)
    try:
        with open(path, encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if ',' not in line:
                    continue
                a, b = line.split(',', 1)
                try:
                    out[int(a)] = b.strip().strip('"').replace(';', '')
                except ValueError:
                    pass
    except OSError:
        pass
    _name_cache[fname] = out
    return out


_encount_tile_zone_cache = None


def _encount_tile_zone_map() -> dict:
    """{zone_id: [room_code, ...]} — dq7_encount_tile.dat の +0x08/09/0a のゾーンIDから
    その行の部屋コード(+0x0b〜)を逆引き。encount_data レコード i は zone = i//2。"""
    global _encount_tile_zone_cache
    if _encount_tile_zone_cache is not None:
        return _encount_tile_zone_cache
    out: dict = {}
    path = os.path.join(_LEVELDATA_DIR, 'dq7_encount_tile.dat')
    try:
        data = open(path, 'rb').read()
        nrec, rsize = struct.unpack_from('<2i', data, 4)
    except (OSError, struct.error):
        _encount_tile_zone_cache = out
        return out
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        if len(r) < 12:
            continue
        code = bytes(b for b in r[11:] if 32 <= b < 127).decode('latin1', 'replace')
        for z in (r[8], r[9], r[10]):
            if z:
                out.setdefault(z, [])
                if code and code not in out[z]:
                    out[z].append(code)
    _encount_tile_zone_cache = out
    return out


_encount_data_cache = None


def _nibbles_lo_first(bs: bytes) -> list:
    out = []
    for b in bs:
        out.append(b & 0xF)
        out.append(b >> 4)
    return out


def parse_encount_data() -> dict:
    """LEVELDATA/dq7_encount_data.dat (304 x 56) を全レコード解読して返す。"""
    global _encount_data_cache
    if _encount_data_cache is not None:
        return _encount_data_cache
    path = os.path.join(_LEVELDATA_DIR, 'dq7_encount_data.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
    mon = _load_name_csv('MONSTER_NAME.txt')
    zmap = _encount_tile_zone_map()

    def mname(mid: int) -> str:
        if mid == 0:
            return ''
        if 991 <= mid <= 999:
            return f'(特殊コード {mid})'
        return mon.get(mid, f'#{mid}')

    def mname_en(mid: int) -> str:
        # モンスター名自体(mon辞書)はROM内蔵のゲームテキストなので翻訳対象外。
        # 英語で切り替わるのは特殊コードの注記表記のみ。
        if mid == 0:
            return ''
        if 991 <= mid <= 999:
            return f'(special code {mid})'
        return mon.get(mid, f'#{mid}')

    slot_labels = ['A0', 'A1', 'A2', 'A3', 'A4', 'B0', 'B1', 'B2', 'B3', '+1c']
    records = []
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        A = [struct.unpack_from('<H', r, 0x06 + 2 * k)[0] for k in range(5)]
        B = [struct.unpack_from('<H', r, 0x10 + 2 * k)[0] for k in range(4)]
        x1c = struct.unpack_from('<H', r, 0x1c)[0]
        slot_ids = A + B + [x1c]
        w1 = _nibbles_lo_first(r[0x2d:0x32])
        w2 = _nibbles_lo_first(r[0x33:0x38])
        mid = list(r[0x20:0x28])
        is_empty = not any(A)
        is_special = any(991 <= m <= 999 for m in A)
        zone = i // 2
        region = i % 2
        records.append({
            'index': i,
            'zone': zone,
            'region': region,   # 0/1 = そのゾーン内の領域 (南/北 等)
            'maps': zmap.get(zone, []),
            'arrayA': [{'id': m, 'name': mname(m), 'name_en': mname_en(m)} for m in A],
            'arrayB': [{'id': m, 'name': mname(m), 'name_en': mname_en(m)} for m in B],
            'extra_rare': {'id': x1c, 'name': mname(x1c), 'name_en': mname_en(x1c)},   # +0x1c レア客枠
            'flee_level': r[0x1e],
            'x1f': r[0x1f],
            'mid': mid,
            'x28': r[0x28], 'x29': r[0x29], 'x2a': r[0x2a],
            'x2b': r[0x2b], 'x2c': r[0x2c], 'x32': r[0x32],
            'weights1': [
                {'slot': slot_labels[k], 'id': slot_ids[k],
                 'name': mname(slot_ids[k]), 'name_en': mname_en(slot_ids[k]), 'w': w1[k]} for k in range(10)],
            'weights2': [
                {'slot': slot_labels[k], 'id': slot_ids[k],
                 'name': mname(slot_ids[k]), 'name_en': mname_en(slot_ids[k]), 'w': w2[k]} for k in range(10)],
            'is_empty': is_empty,
            'is_special': is_special,
            'raw_hex': r.hex(),
        })
    _encount_data_cache = {
        'source': 'LEVELDATA/dq7_encount_data.dat',
        'record_size': rsize,
        'record_count': nrec,
        'header_ok': nrec == nrec2,
        'field_doc': 'docs/camera_encount_investigation.md '
                     '「dq7_encount_data.dat レコード構造の解読」',
        'records': records,
    }
    return _encount_data_cache


# --- アイテム (dq7_item_list.dat) ビュア --------------------------------------
# 構造の解読は docs/camera_encount_investigation.md
# 「アイテムでエンカウント抑止 … からの手がかり調査」を参照。

_item_list_cache = None

# +0x2c = 効果対象パラメータ種別（ユーザー報告 2026-09-09、実機確認 1〜4 / 2026-09-10）。
# 装備が +0x22 で強化する対象。1〜5 は DQ7 ステータスメニューの並び。
_ITEM_PARAM_KIND = {
    0: '効果なし/欠番',
    1: '攻撃力',
    2: '守備力',
    3: 'すばやさ',
    4: 'かしこさ',
    5: 'うんのよさ/特殊アクセサリ(未確認)',
    6: '消耗品',
    7: 'その他消耗品',
    8: '重要/イベント/カギ',
    9: '石/特殊',
}
_ITEM_PARAM_KIND_EN = {
    0: 'No effect / unused',
    1: 'Attack',
    2: 'Defense',
    3: 'Agility',
    4: 'Wisdom',
    5: 'Luck / special accessory (unconfirmed)',
    6: 'Consumable',
    7: 'Other consumable',
    8: 'Key/event item',
    9: 'Stone/special',
}
# +0x2d = 装備スロット/小分類
_ITEM_SLOT = {
    1: '武器', 2: '体防具', 3: '頭', 4: '脚(?)', 5: 'アクセサリ',
    6: '消耗品', 7: 'カギ', 9: '重要', 11: '重要', 12: '石',
}
_ITEM_SLOT_EN = {
    1: 'Weapon', 2: 'Body armor', 3: 'Head', 4: 'Legs(?)', 5: 'Accessory',
    6: 'Consumable', 7: 'Key item', 9: 'Important', 11: 'Important', 12: 'Stone',
}


def parse_item_list() -> dict:
    """LEVELDATA/dq7_item_list.dat (670 x 52) を全レコード解読して返す。"""
    global _item_list_cache
    if _item_list_cache is not None:
        return _item_list_cache
    path = os.path.join(_LEVELDATA_DIR, 'dq7_item_list.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
    inames = _load_name_csv('ITEM_NAME.txt')

    def u16(r, o):
        return struct.unpack_from('<H', r, o)[0]

    def s16(r, o):
        return struct.unpack_from('<h', r, o)[0]

    records = []
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        pkind, slot = r[0x2c], r[0x2d]
        records.append({
            'index': i,
            'name': inames.get(i, ''),
            'type_flags': u16(r, 0x00),          # +0x00
            'name_id': u16(r, 0x08),             # +0x08 名前文字列ID
            'ptr0c': struct.unpack_from('<I', r, 0x0c)[0],  # +0x0c 0x0c〜セグメントptr
            'buy': u16(r, 0x10),                 # +0x10 買値(0=非売品)
            'sell': u16(r, 0x14),                # +0x14 売値(多くは買値/2)
            'desc_id': u16(r, 0x16),             # +0x16 説明文テキストID
            'effect_id': u16(r, 0x1a),           # +0x1a 効果/カタログID
            'effect_param': u16(r, 0x1c),        # +0x1c 効果パラメータ
            'item_id': r[0x20],                  # +0x20 item ID(=index)
            'param_value': s16(r, 0x22),         # +0x22 param_kind への加算値
            'stat_mod': s16(r, 0x24),            # +0x24 補正値(剣は負値=命中/両手ペナ?)
            'stat_x28': r[0x28],                 # +0x28 追加ステータス
            'param_kind': pkind,                 # +0x2c 効果対象パラメータ種別
            'param_kind_label': _ITEM_PARAM_KIND.get(pkind, f'? ({pkind})'),
            'param_kind_label_en': _ITEM_PARAM_KIND_EN.get(pkind, f'? ({pkind})'),
            'slot': slot,                        # +0x2d 装備スロット/小分類
            'slot_label': _ITEM_SLOT.get(slot, f'? ({slot})'),
            'slot_label_en': _ITEM_SLOT_EN.get(slot, f'? ({slot})'),
            'shop_flags': r[0x33],               # +0x33 ショップ系ビットフィールド
            'raw_hex': r.hex(),
        })
    _item_list_cache = {
        'source': 'LEVELDATA/dq7_item_list.dat',
        'record_size': rsize,
        'record_count': nrec,
        'header_ok': nrec == nrec2,
        'field_doc': 'docs/camera_encount_investigation.md '
                     '「アイテムでエンカウント抑止 … からの手がかり調査」',
        'note': '効果本体(回復量/エンカウント抑止 等)は item_list/apprise_item には '
                '無く ExeFS が item ID または effect_id(+0x1a) でディスパッチする。',
        'records': records,
    }
    return _item_list_cache


# --- 特技/呪文パラメータ (dq7_action_param.dat / dq7_action_type.dat) ビュア ----
# 構造の根拠は docs/action_param_action_type_investigation.md。
# record index(0..247) = TEXT/ACTION_NAME.txt の id とそのまま一致することを
# 既知のMP消費量(ホイミ=2, ベホマ=6, ベホマズン=20 等)で確認済み。248以降は
# 名前を持たないモンスター専用技と推測(未確認)。

_action_param_cache = None
_action_type_cache = None

# LEVELDATA の共通ヘッダは magic/nrec/rsize/nrec/0 の5ワード(20byte)で、レコードは
# ファイル先頭+0x14から始まる(ExcelBinaryData::getRecordDynamic が
# `index*rsize + base + 0x14` で計算している)。以下のオフセットは全てこの
# レコード先頭基準 = ExeFSのデコンパイル結果と同じ基準。
_ACTION_RECORD_BASE = 0x14

# +0x46: 耐性系統。ActionDefence::getEffectValue がこの値で switch し、対象側の
# 系統別耐性レベルを選ぶ。22 は常に等倍(1000‰)を返す case。系統名は
# 同系統の呪文名からの推定ラベル。
_ACTION_ELEMENT_LABEL = {
    0: 'メラ系(炎)', 1: 'ギラ系(光)', 2: 'イオ系(爆発)', 3: 'ヒャド系(氷)',
    4: 'バギ系(風)', 5: 'デイン系(雷)', 6: 'ザキ系(即死)', 8: 'バシルーラ系(強制排除)',
    22: '無属性(耐性判定なし・常に等倍)',
}
_ACTION_ELEMENT_LABEL_EN = {
    0: 'Mera family (fire)', 1: 'Gira family (light)', 2: 'Io family (explosion)',
    3: 'Hyado family (ice)', 4: 'Bagi family (wind)', 5: 'Dein family (thunder)',
    6: 'Zaki family (instant death)', 8: 'Basirura family (banish)',
    22: 'Non-elemental (no resistance check, always x1)',
}

# +0x56 bit5-7: 耐性ランク。ActionDefence::getEffect が (ランク, 対象の耐性レベル)
# から千分率の倍率を返す。ランク3〜8は固定倍率、0〜2/9は確率判定(1000か0)。
_ACTION_RESIST_RANK_TABLE = {
    3: [1000, 750, 400, 0],
    4: [1000, 800, 500, 0],
    5: [1300, 1150, 750, 300],
    6: [750, 500, 250, 0],
    8: [1000, 750, 660, 500, 330, 250, 100, 0],
}

# +0x4c: 計算式タイプ。ActionEffectValue::getEffectValue が通常攻撃ダメージを
# この値で加工する(主なもののみ)。
_ACTION_FORMULA_LABEL = {
    0: ('そのまま(威力ロール側で決まる)', 'unchanged (decided by the power roll)'),
    1: ('通常攻撃と同じ', 'same as a normal attack'),
    3: ('通常攻撃×25%', 'normal attack x25%'),
    4: ('通常攻撃×50%', 'normal attack x50%'),
    5: ('通常攻撃×75%', 'normal attack x75%'),
    6: ('通常攻撃×80%', 'normal attack x80%'),
    7: ('通常攻撃×125%', 'normal attack x125%'),
    8: ('通常攻撃×150%', 'normal attack x150%'),
    9: ('通常攻撃×200%', 'normal attack x200%'),
    0x0b: ('対象フラグ+0xf11で×150%', 'x150% if target flag +0xf11'),
    0x0c: ('対象フラグ+0xf10で×150%', 'x150% if target flag +0xf10'),
    0x0d: ('対象フラグ+0xf0dで×150%', 'x150% if target flag +0xf0d'),
    0x0e: ('対象フラグ+0xf0fで×150%', 'x150% if target flag +0xf0f'),
    0x0f: ('対象フラグ+0xf0eで×150%(+1)', 'x150% (+1) if target flag +0xf0e'),
    0x13: ('複数対象逓減(getMuchiDamage)', 'multi-target falloff (getMuchiDamage)'),
    0x14: ('通常攻撃×170%', 'normal attack x170%'),
    0x2f: ('対象フラグ+0xf10で×125%', 'x125% if target flag +0xf10'),
    0x33: ('通常攻撃×70%', 'normal attack x70%'),
}


def parse_action_param() -> dict:
    """LEVELDATA/dq7_action_param.dat (804 x 92) を解読して返す。"""
    global _action_param_cache
    if _action_param_cache is not None:
        return _action_param_cache
    path = os.path.join(_LEVELDATA_DIR, 'dq7_action_param.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
    anames = _load_name_csv('ACTION_NAME.txt')

    records = []
    for i in range(nrec):
        base = _ACTION_RECORD_BASE + i * rsize
        r = data[base:base + rsize]
        type_byte = r[0]
        # +0x34/+0x36 と +0x38/+0x3a: [min,max] の一様乱数ロール2組。
        # setEffectValueBasic は対象ステータス+0xc==1 のとき B、それ以外で A を採用し、
        # setEffectValue は B を読む(デコンパイルで確認)。+0xc==1 が味方側を指すかは推定。
        roll_a_min, roll_a_max = struct.unpack_from('<2H', r, 0x34)
        roll_b_min, roll_b_max = struct.unpack_from('<2H', r, 0x38)
        elem_id = r[0x46]
        mp_cost = r[0x47]
        formula = r[0x4c]
        # +0x51: bit0=会心判定あり(ActionCheckActor::checkActorKaishin が抽選する)
        crit_flags = r[0x51]
        # +0x52: bit0=複数対象逓減(getMuchiDamage)の対象, bit4=status::isDoubleAction の対象
        gate_flags = r[0x52]
        resist_rank = r[0x56] >> 5
        flabel = _ACTION_FORMULA_LABEL.get(formula)
        records.append({
            'index': i,
            'name': anames.get(i, ''),
            'type_byte': type_byte,                    # +0x00
            'type_category': type_byte >> 3,            # 推定: 上位5bit
            'type_sub': type_byte & 7,                  # 推定: 下位3bit
            'roll_a_min': roll_a_min,                   # +0x34
            'roll_a_max': roll_a_max,                   # +0x36
            'roll_b_min': roll_b_min,                   # +0x38
            'roll_b_max': roll_b_max,                   # +0x3a
            'element_id': elem_id,                      # +0x46 耐性系統
            'element_label': _ACTION_ELEMENT_LABEL.get(elem_id, f'? ({elem_id})'),
            'element_label_en': _ACTION_ELEMENT_LABEL_EN.get(elem_id, f'? ({elem_id})'),
            'mp_cost': mp_cost,                         # +0x47 (255 = メガザルの"MP全消費")
            'formula': formula,                         # +0x4c 計算式タイプ
            'formula_label': flabel[0] if flabel else '',
            'formula_label_en': flabel[1] if flabel else '',
            'crit_flags': crit_flags,                   # +0x51
            'gate_flags': gate_flags,                   # +0x52
            'resist_rank': resist_rank,                 # +0x56 bit5-7
            'resist_rank_table': _ACTION_RESIST_RANK_TABLE.get(resist_rank),
            'raw_hex': r.hex(),
        })
    _action_param_cache = {
        'source': 'LEVELDATA/dq7_action_param.dat',
        'record_size': rsize,
        'record_count': nrec,
        'header_ok': nrec == nrec2,
        'field_doc': 'docs/action_param_action_type_investigation.md',
        'record_base': _ACTION_RECORD_BASE,
        'note': 'オフセットはレコード先頭(ファイル+0x14)基準で、ExeFSのデコンパイル結果と'
                '同じ基準。かえん斬り等の元素斬りは 計算式=通常攻撃と同じ・耐性ランク5 で、'
                '倍率は対象の耐性レベルに応じて ×1.30/×1.15/×0.75/×0.30。'
                '系統名・type_byteの分類名は推定。'
                'record index 248以降は ACTION_NAME.txt に名前が無い'
                '(モンスター専用技と推測、未確認)。',
        'note_en': 'Offsets are relative to the record start (file +0x14), matching the '
                   'decompiled ExeFS code. Elemental slashes such as Frizz Slash use '
                   'formula "same as a normal attack" with resistance rank 5, giving '
                   'x1.30/x1.15/x0.75/x0.30 depending on the target\'s resistance level. '
                   'Family names and type_byte categories are estimates. '
                   'Indices 248+ have no name in ACTION_NAME.txt (likely monster-only, '
                   'unconfirmed).',
        'records': records,
    }
    return _action_param_cache


def parse_action_type() -> dict:
    """LEVELDATA/dq7_action_type.dat (100 x 32) を解読して返す。

    戦闘エフェクト(モデルスケール・アタッチ位置・パーティクル名)のテーブルと
    推測されるが、dq7_action_param.dat とどのキーで紐付くかは未確認。
    """
    global _action_type_cache
    if _action_type_cache is not None:
        return _action_type_cache
    path = os.path.join(_LEVELDATA_DIR, 'dq7_action_type.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)

    records = []
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        key, marker = struct.unpack_from('<HH', r, 0)
        scale = struct.unpack_from('<f', r, 4)[0]
        fa, fb, fc, fd = struct.unpack_from('<4H', r, 8)
        node_id = struct.unpack_from('<H', r, 18)[0]
        name = r[0x16:0x1c].split(b'\x00')[0].decode('ascii', 'replace')
        flags = struct.unpack_from('<H', r, 30)[0]
        records.append({
            'index': i,
            'key': key,                # +0x00 用途未確認(増分パターンあり)
            'marker': marker,          # +0x02 通常 0xFFFF (record0のみ0)
            'scale': scale,            # +0x04 float。1.0 または 0.5 が大半
            'field_a': fa,             # +0x08
            'field_b': fb,             # +0x0a
            'field_c': fc,             # +0x0c
            'field_d': fd,             # +0x0e
            'node_id': node_id,        # +0x12 アタッチ先ボーン/ノードID?(11/12等)
            'particle_name': name,     # +0x16 "null"/"null_b"/"null_c"/空
            'flags': flags,            # +0x1e ビットフラグ(未解読)
            'raw_hex': r.hex(),
        })
    _action_type_cache = {
        'source': 'LEVELDATA/dq7_action_type.dat',
        'record_size': rsize,
        'record_count': nrec,
        'header_ok': nrec == nrec2,
        'field_doc': 'docs/action_param_action_type_investigation.md',
        'note': '戦闘エフェクト(モデルスケール/アタッチ位置/パーティクル名)の'
                'テーブルと推測。dq7_action_param.dat側のどのフィールドで'
                '本テーブルの行を参照しているかは未確認。',
        'records': records,
    }
    return _action_type_cache


# --- キャラクターのステータス成長表 (dq7_player_levelN.dat) ビュア -------------
# 6ファイル(N=1..6) x 100レコード x 40byte。レコード index = レベル(0=ダミー, 1..99)。
# レコード構造(解読 2026-09-09):
#   +0x00 u16 タグ / +0x02 u16 0xFFFF マーカー
#   +0x04 u32 そのレベルに到達する累計EXP
#   +0x08 u16 ちから / +0x0a u16 すばやさ / +0x0c u16 うんのよさ /
#   +0x0e u16 かしこさ / +0x10 u16 さいだいHP / +0x12 u16 さいだいMP
#   +0x14.. 0 埋め
# ファイル番号 -> キャラは推定(スタッツ傾向 + 加入順): 主人公/マリベル/ガボ/メルビン/アイラ/キーファ

_player_stats_cache = None
_PLAYER_FILE_GUESS = {
    1: '主人公', 2: 'マリベル', 3: 'ガボ', 4: 'メルビン', 5: 'アイラ', 6: 'キーファ',
    # 製品ROMには 1..6 しか無い。7 以降は「プレイアブルキャラ増加」実験で
    # 手動追加したファイル (docs/playable_character_expansion_investigation.md)。
    7: 'マチルダ(実験)', 8: 'ハンク(実験)',
}


def parse_player_stats() -> dict:
    global _player_stats_cache
    if _player_stats_cache is not None:
        return _player_stats_cache
    chars = []
    for n in range(1, 9):
        fname = f'dq7_player_level{n}.dat'
        path = os.path.join(_LEVELDATA_DIR, fname)
        try:
            data = open(path, 'rb').read()
            nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
        except (OSError, struct.error):
            continue
        levels = []
        for i in range(nrec):
            r = data[16 + i * rsize:16 + (i + 1) * rsize]
            tag = struct.unpack_from('<H', r, 0)[0]
            if i == 0 and not any(r):
                continue
            u = lambda o: struct.unpack_from('<H', r, o)[0]
            levels.append({
                'level': i,
                'exp': struct.unpack_from('<I', r, 4)[0],
                'str': u(0x08), 'agi': u(0x0a), 'luck': u(0x0c),
                'wis': u(0x0e), 'hp': u(0x10), 'mp': u(0x12),
                'tag': tag,
                'raw_hex': r.hex(),
            })
        chars.append({
            'file': fname,
            'slot': n,
            'name_guess': _PLAYER_FILE_GUESS.get(n, f'#{n}'),
            'record_size': rsize,
            'record_count': nrec,
            'header_ok': nrec == nrec2,
            'levels': levels,
        })
    _player_stats_cache = {
        'source': 'LEVELDATA/dq7_player_level{1..8}.dat (製品ROMは1..6のみ)',
        'field_doc': 'docs/character_status_investigation.md',
        'stat_order': ['str=ちから (+0x08)', 'agi=すばやさ (+0x0a)',
                       'luck=うんのよさ (+0x0c)', 'wis=かしこさ (+0x0e)',
                       'hp=さいだいHP (+0x10)', 'mp=さいだいMP (+0x12)'],
        'note': 'ファイル番号→キャラ名は推定(スタッツ傾向+加入順)。'
                'みのまもりは DQ7 では素早さ/2+装備で導出のため非格納。',
        'characters': chars,
    }
    return _player_stats_cache


# --- キャラクター初期化データ (dq7_character_init_data.dat) ビュア -----------
# 46レコード x 172byte。レコード index = party_menu.txt/PLAYER_NAME.txt の
# キャラID空間そのもの（+0x30の下位u16は常にレコード自身のindexと一致する
# 自己参照値 - 独立したID格納ではない）。
# フィールド解読(2026-09-11, docs/playable_character_expansion_investigation.md
# 「実機結果を反映」「Matilda vs Filia比較」節参照。多くは推定・未確定):
#   +0x00 u16 0x0000 / u16 0xFFFF マーカー（他LEVELDATAテーブルと同じ流儀）
#   +0x04 u32  【確定 2026-09-11】初期EXP。id1-4=0,id5=43439,id6=51912、他0。
#              新規セーブでメルビン/アイラのEXPと完全一致して確定した
#              (docs/playable_character_expansion_investigation.md「実験C」節)
#   +0x08/+0x0c/+0x10 float x3  初期位置 X/Y/Z(推定) - 本編6人+一部ゲストのみ非ゼロ
#   +0x1c/+0x20/+0x24 float x3  向き/スケール(推定、位置と同じ集合で非ゼロ)
#   +0x30 u16 self_index + u16 【確定 2026-09-15】ちから
#   +0x34 u16 【確定】すばやさ + u16 【確定】うんのよさ
#   +0x38 u16 【確定】かしこさ + u16 unk3(id1-4=6,12,14,3、用途不明)
#   +0x3c u16 【確定】HP + u16 unk4(ほぼ常に0)
#              上記5フィールドは docs/guest_character_stats_investigation.md で
#              dq7_player_levelN.dat の Lv1 レコードと4キャラ全員・完全一致することを
#              実バイト比較で確定。旧記述「+0x30=unk1」「+0x34=unk2a/unk2b」
#              「+0x38=用途不明」「+0x3c=999センチネル」は誤りだった。
#              id7-17(ゲスト)はHPが軒並み999という固定値、id38-45(特殊8体)は
#              個別のHP(300-3000)を持つ。このテーブルはお助けキャラの実ステータスの
#              直接の供給源でもある(セーブに専用枠を持たないため)。
#   +0x4c u32  【確定 2026-09-11、ユーザー指摘】性別。271=男性/272=女性/
#              273=その他・非人間。全45レコードを実際の性別と突き合わせて確定
#              (id27「スラっち」=スライムの仲間、id38-45の特殊8体グループ=
#              モデル名なしの非人間キャラが揃って273だったのが決め手)
#   +0x6c u32  レコード生成順らしき連番(情報用途のみ、意味なし)
#   +0x74 u32  【確定 2026-09-11】初期レベル。本編6人(id1-4=1,id5=19,id6=21)は
#              非ゼロ、id38-45の特殊8体グループは全員10、それ以外(ゲスト含む)は0。
#              新規セーブでメルビン=Lv19/アイラ=Lv21が実際に生成され一致して確定
#              (+0x04とセットで、ゲームは新規セーブ時に本編6人分のCharactorsを
#              未加入キャラも含め一括でこのテーブルから埋めていることも判明)。
#              なお、マチルダ(id7)のこの値を0→1に書き換えても新規セーブの
#              Charactors配列は6個のままで7個目は作られなかった
#              （6枠固定はテーブルの中身に依存しない、ExeFS側の定数と判断）
#   +0x78.. ASCII "pNNNN"/"bNNNN" モデル名。直前1byteはモデル番号の10進値そのもの
#            (例: p0050の前が0x32='2'=50)
#   +0x90 u32 上位u16のみ使用。観測値: 0x08(id1のみ)/0x10(id2-5)/0x310(id6)/
#              0x1c(id7-17、配置データを持つNPC)/0x20(id18-37、名前のみの
#              プレースホルダ)/0x28(id38-45、特殊8体グループ)。
#              「キャラ種別」を示すコードらしいが厳密な意味は未確定。
#              マチルダ(0x1c=配置データあり)とフィリア(0x20=プレースホルダ)の
#              違いはこの値に現れる ⇒ 「戦闘に出るか」との相関を疑っている。

_CHAR_INIT_CATEGORY_LABELS = {
    0x08: '主人公(id1)',
    0x10: '本編プレイアブル(id2〜5)',
    0x310: '本編プレイアブル(id6, 追加ビット?)',
    0x1c: '配置データありNPC/ゲスト(id7〜17)',
    0x20: '名前のみプレースホルダ(id18〜37)',
    0x28: '特殊8体グループ(id38〜45)',
}

_CHAR_INIT_CATEGORY_LABELS_EN = {
    0x08: 'Hero (id1)',
    0x10: 'Main playable (id2-5)',
    0x310: 'Main playable (id6, extra bit?)',
    0x1c: 'NPC/guest with placement data (id7-17)',
    0x20: 'Name-only placeholder (id18-37)',
    0x28: 'Special group of 8 (id38-45)',
}

_CHAR_INIT_GENDER_LABELS = {271: '男性', 272: '女性', 273: 'その他・非人間'}
_CHAR_INIT_GENDER_LABELS_EN = {271: 'Male', 272: 'Female', 273: 'Other/non-human'}

# ビュアーから編集可能なフィールド一覧。(offset, size, struct_fmt, name)。
# category_code(+0x92, u16)がプレイアブル初期化と相関している疑い(ユーザー指摘
# 2026-09-11)があるため、実機検証用に書き換えられるようにした。init_level/
# init_exp は既に意味が確定済み(+0x74/+0x04)で、7人目実験の追加検証に使える。
_CHAR_INIT_EDITABLE_FIELDS = {
    'category_code': (0x92, 2, '<H'),   # +0x90 u32の上位u16のみ実質使用(下位は常に0)
    'init_level': (0x74, 4, '<I'),
    'init_exp': (0x04, 4, '<I'),
}


def parse_character_init_data() -> dict:
    path = os.path.join(_LEVELDATA_DIR, 'dq7_character_init_data.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
    names_by_id = {}
    try:
        party_menu_path = os.path.join(_ROMFS_DIR, 'MENULIST', 'party_menu.txt')
        with open(party_menu_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line.startswith('#'):
                    continue
                parts = line[1:].split(',', 2)
                if len(parts) >= 3:
                    try:
                        names_by_id[int(parts[0])] = parts[2]
                    except ValueError:
                        pass
    except OSError:
        pass

    records = []
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        if i == 0 and not any(r):
            continue
        u32 = lambda o: struct.unpack_from('<I', r, o)[0]
        f32 = lambda o: struct.unpack_from('<f', r, o)[0]
        pos = [f32(0x08), f32(0x0c), f32(0x10)]
        scale = [f32(0x1c), f32(0x20), f32(0x24)]
        has_pos = any(pos) or any(scale)
        cat = (u32(0x90) >> 16) & 0xFFFF
        m1 = r[0x78:0x80]
        model = m1[1:].split(b'\x00', 1)[0].decode('ascii', errors='replace') if any(m1) else ''
        records.append({
            'index': i,
            'name': names_by_id.get(i, ''),
            'init_level': u32(0x74),
            'init_exp': u32(0x04),
            'has_placement': has_pos,
            'pos': pos if has_pos else None,
            'scale': scale if has_pos else None,
            'model': model,
            'category_code': cat,
            'category_label': _CHAR_INIT_CATEGORY_LABELS.get(cat, f'不明(0x{cat:x})'),
            'category_label_en': _CHAR_INIT_CATEGORY_LABELS_EN.get(cat, f'Unknown(0x{cat:x})'),
            'gender_code': u32(0x4c),
            'gender_label': _CHAR_INIT_GENDER_LABELS.get(u32(0x4c), f'不明({u32(0x4c)})'),
            'gender_label_en': _CHAR_INIT_GENDER_LABELS_EN.get(u32(0x4c), f'Unknown({u32(0x4c)})'),
            'field_0x6c': u32(0x6c),
            'field_0x74': u32(0x74),
            'base_stats': {
                'str': struct.unpack_from('<H', r, 0x32)[0],
                'agi': struct.unpack_from('<H', r, 0x34)[0],
                'luck': struct.unpack_from('<H', r, 0x36)[0],
                'wis': struct.unpack_from('<H', r, 0x38)[0],
                'hp': struct.unpack_from('<H', r, 0x3c)[0],
            },
            'raw_hex': r.hex(),
        })
    return {
        'source': 'LEVELDATA/dq7_character_init_data.dat',
        'field_doc': 'docs/guest_character_stats_investigation.md',
        'record_count': nrec,
        'record_size': rsize,
        'header_ok': nrec == nrec2,
        'note': '多くのフィールドが推定・未確定(コード内コメント参照)。'
                'index はキャラID空間そのもの(party_menu.txt準拠)。',
        'records': records,
    }


def parse_person_jidx() -> dict:
    """CHARACTER/person.jidx (未解読、docs/keifa_job_animation_investigation.md
    参照) の生バイトを6byteレコード列として2通りの読み方(ヘッダ0byte/2byte)
    両方で提示するビュアー用パーサ。構造は未確定のため、断定的なフィールド名は
    付けず raw な (a,b,c) の組と、その値がどのレコードのオフセットとして
    解釈できるかの相互参照だけを提供する。"""
    path = os.path.join(_ROMFS_DIR, 'CHARACTER', 'person.jidx')
    data = open(path, 'rb').read()
    size = len(data)
    rec_size = 6

    def build_records(header_len: int) -> list:
        recs = []
        body = data[header_len:]
        n = len(body) // rec_size
        for i in range(n):
            off = header_len + i * rec_size
            a, b, c = struct.unpack_from('<HHH', data, off)
            recs.append({'index': i, 'offset': off, 'a': a, 'b': b, 'c': c})
        return recs

    header_u16 = struct.unpack_from('<H', data, 0)[0] if size >= 2 else None
    alignments = {
        'no_header': {'header_len': 0, 'records': build_records(0)},
        'header_2byte': {'header_len': 2, 'records': build_records(2)},
    }

    return {
        'source': 'CHARACTER/person.jidx',
        'field_doc': 'docs/keifa_job_animation_investigation.md',
        'note': '構造未確定。MotionIndexManager::readFile が %s.idx 形式で開く'
                'ジョブ別モーションIndexテーブルの本体と推定(person.idx/person.jidx)。'
                '6byteレコード(a,b,c)が互いのオフセットを指し合う自己参照構造らしいことまで'
                '判明しているが、ヘッダの有無・各フィールドの意味は未確定。',
        'file_size': size,
        'header_u16_at_0': header_u16,
        'divides_evenly_with_2byte_header': (size - 2) % rec_size == 0,
        'record_count_with_2byte_header': (size - 2) // rec_size,
        'alignments': alignments,
    }


_CHAR_INIT_EDIT_BACKUP_DIR = os.path.join(_ROM_DIR, 'leveldata_edit_backups')


def edit_character_init_field(index: int, field: str, value, comment: str = '') -> dict:
    """dq7_character_init_data.dat の1レコード中、1フィールドだけを書き換える。
    _CHAR_INIT_EDITABLE_FIELDS のフィールドはいずれも固定サイズ・固定位置の
    スカラー値で、書き換えてもファイルサイズもレコード境界も一切変わらない
    (edit_npc_placement_field と同じ「単純な定位置パッチ」パターン)。
    バックアップは rom/leveldata_edit_backups/ に専用で置く
    (rom/script_edit_backups/ とは別管理 - SCRIPT編集の履歴と混ぜない)。
    """
    if field not in _CHAR_INIT_EDITABLE_FIELDS:
        raise ValueError(f'invalid field {field!r}')
    rel_off, size, fmt = _CHAR_INIT_EDITABLE_FIELDS[field]

    path = os.path.join(_LEVELDATA_DIR, 'dq7_character_init_data.dat')
    with open(path, 'rb') as f:
        data = f.read()
    nrec, rsize, _ = struct.unpack_from('<3i', data, 4)
    if not (0 <= index < nrec):
        raise ValueError(f'invalid index {index} (nrec={nrec})')

    abs_off = 16 + index * rsize + rel_off
    old_val = struct.unpack_from(fmt, data, abs_off)[0]
    new_raw = struct.pack(fmt, int(value) & ((1 << (size * 8)) - 1))
    new_data = data[:abs_off] + new_raw + data[abs_off + size:]

    os.makedirs(_CHAR_INIT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_CHAR_INIT_EDIT_BACKUP_DIR,
                                f'dq7_character_init_data.dat.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(path, 'wb') as f:
        f.write(new_data)

    history_path = os.path.join(_CHAR_INIT_EDIT_BACKUP_DIR, 'history.jsonl')
    with open(history_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'id': stamp,
            'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
            'index': index, 'field': field,
            'before': old_val, 'after': int(value),
            'comment': comment,
            'backup_path': backup_path,
        }, ensure_ascii=False) + '\n')

    return {
        'ok': True, 'index': index, 'field': field,
        'before': old_val, 'after': int(value),
        'backup_path': backup_path,
    }


# --- 全キャラクター/NPCモデル一覧 (dq7_chara_list.dat) ビュア ----------------
# 927レコード x 84byte。dq7_character_init_data.dat とは別物(全キャラ+全NPC、
# パーティ専用ではない)。中身は主に3Dモデルのバウンディングボックス/スケールら
# しき float 値の並びで、キャラのステータス的な意味を持つフィールドは今のところ
# 見当たらない(2026-09-11 調査、docs/playable_character_expansion_investigation.md
# 「調査したが手がかりなし」節)。+0x00 は0xFFFFマーカー+2byteの資産ID風の値
# (レコードごとにほぼ連番だが同じ値を共有するグループもある=同一モデルの派生?)。
# +0x18/+0x1c は全レコードほぼ非ゼロの小さい整数(種別コード?)。
# +0x4c.. に "pNNNN"/"bNNNN" のモデル名ASCII文字列。

def parse_chara_list() -> dict:
    path = os.path.join(_LEVELDATA_DIR, 'dq7_chara_list.dat')
    data = open(path, 'rb').read()
    nrec, rsize, nrec2 = struct.unpack_from('<3i', data, 4)
    records = []
    for i in range(nrec):
        r = data[16 + i * rsize:16 + (i + 1) * rsize]
        if i == 0 and not any(r):
            continue
        u16 = lambda o: struct.unpack_from('<H', r, o)[0]
        f32 = lambda o: struct.unpack_from('<f', r, o)[0]
        # "pNNNN"/"bNNNN" の位置は先頭2byte(モデル番号を格納した謎の下駄)分だけ
        # ずれる場合があるため、固定オフセット決め打ちではなく素直に部分文字列検索する。
        tail = r[0x48:rsize]
        p_at = tail.find(b'p0')
        model = tail[p_at:p_at + 5].decode('ascii', errors='replace') if p_at >= 0 else ''
        floats = [round(f32(o), 4) for o in range(0x08, 0x48, 4)]
        records.append({
            'index': i,
            'asset_tag': u16(0x00),
            'field_0x18': round(f32(0x18), 4),
            'field_0x1c': round(f32(0x1c), 4),
            'model': model,
            'floats_0x08_0x44': floats,
        })
    return {
        'source': 'LEVELDATA/dq7_chara_list.dat',
        'field_doc': 'docs/playable_character_expansion_investigation.md',
        'record_count': nrec,
        'record_size': rsize,
        'header_ok': nrec == nrec2,
        'note': '主要フィールド未解読。3Dモデルのバウンディングボックス/スケール'
                'らしき float 値が中心で、パーティ所属可否等のフラグは見当たらない。',
        'records': records,
    }


def _parse_fpt(path: str) -> dict:
    """Parse an FPT0 file's entries, keyed by filename (e.g. '#131309.txt').

    CORRECTED offset formula (previously wrong all session - see
    docs/ and the FPT viewer investigation): each entry's message_offset
    field is NOT an absolute file offset. It's relative to `data_start`,
    the position right after the header + file-info table + TEMP-file-info
    table:
        data_start = 0x10 + file_count*0x20 + temp_count*0x40
        true_position = data_start + msg_offset
    Verified directly: at true_position the bytes cleanly begin with a
    "#NNNN\\r\\n" control-code line (a real message start), whereas the old
    (wrong) absolute-offset reading landed mid-sentence inside an unrelated,
    earlier part of the same continuous text stream - which is why "leading
    garbled/mid-word text" seemed like a pervasive, unavoidable format
    quirk. It mostly was not; it was this offset bug.
    """
    if path in _FPT_CACHE:
        return _FPT_CACHE[path]
    result = {}
    try:
        with open(path, 'rb') as f:
            data = f.read()
        if data[:4] == b'FPT0':
            file_count = struct.unpack_from('<I', data, 8)[0]
            temp_count = struct.unpack_from('<I', data, 0xC)[0]
            entries_start = 0x10
            data_start = entries_start + file_count * 0x20 + temp_count * 0x40
            for i in range(file_count):
                off = entries_start + i * 0x20
                if off + 0x20 > len(data):
                    break
                name = data[off:off + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
                msg_off = struct.unpack_from('<I', data, off + 0x14)[0]
                msg_len = struct.unpack_from('<I', data, off + 0x18)[0]
                true_off = data_start + msg_off
                if msg_off < 0 or true_off + msg_len > len(data):
                    continue
                body = data[true_off:true_off + msg_len]
                result[name] = body.decode('utf-8', errors='replace')
    except FileNotFoundError:
        pass
    _FPT_CACHE[path] = result
    return result


def resolve_message(msgid: int) -> str:
    if msgid <= 0:
        return ''
    bucket = (msgid // 1000) * 1000
    path = os.path.join(_MESS_DIR, f'#{bucket:06d}.fpt')
    entries = _parse_fpt(path)
    return entries.get(f'#{msgid:06d}.txt', '')


def list_fpt_files() -> list:
    if not os.path.isdir(_MESS_DIR):
        return []
    files = []
    for name in sorted(os.listdir(_MESS_DIR)):
        if name.endswith('.fpt'):
            full = os.path.join(_MESS_DIR, name)
            files.append({'name': name, 'size': os.path.getsize(full)})
    return files


# --- 3D model (.bcmdl / CGFX) viewer -----------------------------------------

_MODEL_DIRS = ('CHARACTER', 'MONSTER', 'SHAPE', 'BATTLE')
_MODEL_EXTS = ('.bcmdl.lz', '.pack.lz', '.shp.lz', '.bcmdl')


def _model_root() -> str:
    return _ROMFS_DIR


def list_model_files() -> list:
    """Every model-ish file under RomFS CHARACTER/ MONSTER/ SHAPE/ BATTLE/,
    grouped by dir. `kind`: 'model' (.bcmdl - has the actual Models/
    Textures/LUTS dicts, this is the one to view), 'anim' (.pack.lz -
    verified to hold ONLY a SkeletalAnims dict, no geometry of its own;
    naming it 'pack' previously implied the opposite and was wrong -
    see docs/bcmdl_model_viewer.md), 'shape' (.shp.lz). `bcmdl.read_model()`
    transparently redirects a '.pack.lz' path to its '.bcmdl.lz' sibling,
    so either entry can be clicked and still show a real model."""
    root = _model_root()
    out = []
    for sub in _MODEL_DIRS:
        d = os.path.join(root, sub)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.endswith(_MODEL_EXTS):
                continue
            full = os.path.join(d, name)
            if not os.path.isfile(full):
                continue
            kind = ('anim' if name.endswith('.pack.lz')
                    else 'shape' if name.endswith('.shp.lz')
                    else 'model')
            out.append({
                'path': f'{sub}/{name}',
                'dir': sub,
                'name': name,
                'kind': kind,
                'size': os.path.getsize(full),
            })
    return out


def _safe_model_path(rel: str) -> str:
    if not rel or '..' in rel or rel.startswith('/'):
        raise ValueError('invalid path')
    parts = rel.split('/')
    if len(parts) != 2 or parts[0] not in _MODEL_DIRS:
        raise ValueError('invalid path')
    full = os.path.join(_model_root(), parts[0], parts[1])
    if not os.path.isfile(full):
        raise FileNotFoundError(rel)
    return full


def parse_model_file(rel: str) -> dict:
    """rel like 'MONSTER/e001.bcmdl.lz' -> {structure, geometry, textures, ...}."""
    full = _safe_model_path(rel)
    res = bcmdl.read_model(full)
    res['file'] = rel
    return res


def model_texture_png(rel: str, name: str) -> bytes:
    """Decode one embedded TXOB of the model to PNG bytes (or None)."""
    full = _safe_model_path(rel)
    cg = bcmdl.get_cgfx(full)
    return cg.texture_png(name)


def model_animation(rel: str, name: str) -> dict:
    """{name, frames, tracks} for one SkeletalAnims clip - see bcmdl.read_animation."""
    full = _safe_model_path(rel)
    return bcmdl.read_animation(full, name)


def parse_fpt_full(filename: str) -> dict:
    """Full FPT0 parse with per-entry debug fields, for the FPT viewer page.

    Mirrors mess/extract_fpt.py's file_infos fields (addr_info/msg_offset/
    msg_count). CORRECTED offset formula (see _parse_fpt's docstring for
    the full derivation): msg_offset is relative to data_start = 0x10 +
    file_count*0x20 + temp_count*0x40 (the header + file-info table + the
    TEMP-file-info table, e.g. a "TEMP/STEP2" entry), not relative to file
    offset 0. true_offset = data_start + msg_offset. Confirmed directly:
    at true_offset the bytes cleanly begin with a "#NNNN\\r\\n" control
    line, unlike the old absolute-from-0 reading which landed mid-sentence
    in an unrelated earlier part of the same file.
    """
    path = os.path.join(_MESS_DIR, filename)
    with open(path, 'rb') as f:
        data = f.read()

    if data[:4] != b'FPT0':
        raise ValueError(f'not an FPT0 file: {data[:4]!r}')

    file_count = struct.unpack_from('<I', data, 8)[0]
    temp_count = struct.unpack_from('<I', data, 0xC)[0]
    entries_start = 0x10
    data_start = entries_start + file_count * 0x20 + temp_count * 0x40

    entries = []
    prev_end = None
    for i in range(file_count):
        off = entries_start + i * 0x20
        if off + 0x20 > len(data):
            break
        name = data[off:off + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
        addr_info = struct.unpack_from('<I', data, off + 0x10)[0]
        msg_off = struct.unpack_from('<I', data, off + 0x14)[0]
        msg_len = struct.unpack_from('<I', data, off + 0x18)[0]
        true_off = data_start + msg_off
        contiguous = (prev_end is not None and true_off == prev_end)
        text = ''
        if msg_off >= 0 and true_off + msg_len <= len(data):
            text = data[true_off:true_off + msg_len].decode('utf-8', errors='replace')
        entries.append({
            'index': i,
            'filename': name,
            'addr_info': addr_info,
            'msg_offset': msg_off,
            'msg_count': msg_len,
            'true_offset': true_off,
            'contiguous_with_prev': contiguous,
            'text': text,
        })
        prev_end = true_off + msg_len

    return {
        'file': filename,
        'file_size': len(data),
        'header': {'file_count': file_count, 'temp_count': temp_count, 'data_start': data_start},
        'entries': entries,
    }


# ---------------------------------------------------------------------------
# Script tree -> JSON

def _decode_command(raw: bytes) -> dict:
    out = {'hex': raw.hex(), 'size': len(raw)}
    if len(raw) < 4:
        return out
    opcode = struct.unpack_from('<I', raw, 0)[0]
    out['opcode'] = f'0x{opcode:08x}'
    opcode_lo = opcode & 0xFF
    params = []
    off = 4
    while off + 4 <= len(raw):
        params.append(struct.unpack_from('<I', raw, off)[0])
        off += 4
    out['params'] = params

    if opcode == FANFARE_MSG_OPCODE and len(params) >= 3:
        out['name'] = 'FANFARE_MSG'
        out['msgid'] = params[0]
        out['count'] = params[1]
        out['style'] = params[2]
        out['style_hint'] = _FANFARE_MSG_STYLE_HINT.get(params[2], 'unknown')
        text = resolve_message(params[0])
        if text:
            out['text'] = text
    elif opcode == IF_FLAG_OPCODE and len(params) >= 3:
        out['name'] = 'IF_FLAG'
        out['flag_type'] = params[0]
        out['flag_id'] = params[1]
        out['flag_value'] = params[2]
    elif (opcode & 0xFFFF) == (SET_FLAG_OPCODE & 0xFFFF) and len(params) >= 3:
        # 【確定 2026-10-04】以前はSET_FLAG_OPCODE(0x00010004)との完全一致でしか
        # 認識しておらず、high16=0x0003版(分岐ブロック終了マーカー、script_opcodes.md
        # で既に確定済みのはずの定型パターン)が`op_00030004`としてしか表示されて
        # いなかった(OBJECT_TOGGLEで見つかったのと同種のデコード漏れ)。
        out['name'] = 'SET_FLAG'
        out['flag_type'] = params[0]
        out['flag_id'] = params[1]
        out['flag_value'] = params[2]
    elif opcode == TALKED_TO_OPCODE and len(params) >= 1:
        out['name'] = 'IF_TALKED_TO'
        out['variant'] = params[0]
    elif opcode == IF_KO_STATUS_OPCODE and len(params) >= 2:
        out['name'] = 'IF_KO_STATUS'
        out['character_id'] = params[0]
        out['branch_when'] = 'ko' if params[1] != 0 else 'alive'
    elif (opcode & 0xFFFF) == SET_MAP_OBJ_NUMBER_OPCODE and len(params) >= 1:
        # 【訂正 2026-10-04】以前はSTART_BATTLEとして表示していたが誤り
        # だった(SET_MAP_OBJ_NUMBER_OPCODEのコメント参照)。本当の役割は
        # 未調査のため、opcode名のみ付与しparamsはそのまま表示する。
        out['name'] = 'SET_MAP_OBJ_NUMBER'
    elif (opcode & 0xFFFF) == ENCOUNT_SET_FLAG_OPCODE and len(params) >= 4:
        out['name'] = 'ENCOUNT_SET_FLAG'
        out['flag_id'] = params[1]
        out['enc_type'] = params[2]
        out['value'] = params[3]
    elif opcode == IF_IS_PARTY_MEMBER_OPCODE and len(params) >= 1:
        out['name'] = 'IF_IS_PARTY_MEMBER'
        out['character_id'] = params[0]
    elif opcode in ADD_PARTY_MEMBER_OPCODES and len(params) >= 1:
        mode_is_remove = len(params) >= 2 and params[1] != 0
        out['name'] = 'REMOVE_PARTY_MEMBER' if mode_is_remove else 'ADD_PARTY_MEMBER'
        out['character_id'] = params[0]
        out['mode_param'] = params[1] if len(params) >= 2 else None
    elif opcode == PARTY_SLOT_ACTIVATE_OPCODE and len(params) >= 1:
        out['name'] = 'PARTY_SLOT_ACTIVATE'
        out['slot'] = params[0]
    elif opcode == PARTY_SLOT_QUERY_OPCODE and len(params) >= 2:
        out['name'] = 'PARTY_SLOT_QUERY'
        out['slot'] = params[1]
    elif opcode == CONFIRM_YESNO_OPCODE and len(params) >= 3:
        out['name'] = 'CONFIRM_YESNO'
        out['var_type'] = params[0]
        out['var_id'] = params[1]
        out['cancel_value'] = params[2]
    elif opcode == CHOICE_MENU_OPCODE and len(params) >= 2:
        out['name'] = 'CHOICE_MENU'
        out['msgid'] = params[0]
        out['count'] = params[1]  # likely (exe-side, unconfirmed dispatch link): consecutive message page count, like other MSG-family opcodes
        # kept as 'slot_flags' for backward compat, but this is NOT a formation-slot
        # index - see CHOICE_MENU_OPCODE docstring (2026-09-23): index 0-3 are
        # hardcoded to character IDs 2/4/5/6 (Maribel/Gabo/Melvin/Aira), and the
        # 5th entry (index 4) is a cancel/fallback flag, not a "slot6" identity.
        out['slot_flags'] = params[2:]
        out['char_id_flags'] = {2: params[2], 4: params[3], 5: params[4], 6: params[5]} if len(params) >= 6 else None
        out['cancel_or_fallback_flag'] = params[6] if len(params) >= 7 else None
        text = resolve_message(params[0])
        if text:
            out['text'] = text
    elif opcode == SET_POSITION_OPCODE and len(params) >= 3:
        out['name'] = 'SET_POSITION'
        out['pos_x'] = round(struct.unpack('<f', struct.pack('<I', params[0]))[0], 4)
        out['pos_y'] = round(struct.unpack('<f', struct.pack('<I', params[1]))[0], 4)
        out['pos_z'] = round(struct.unpack('<f', struct.pack('<I', params[2]))[0], 4)
    elif (opcode & 0xFFFF) == (OBJECT_TOGGLE_OPCODE & 0xFFFF) and len(params) >= 1:
        # 【確定 2026-10-04】OBJECT_TOGGLEもhigh16(0x0001/0x0003)の対象になりうる
        # ことを実機検証用NPCの作成中に確認した(docs/battle_start_opcode_
        # investigation.mdの「実機検証用テストNPCの設置」節参照) - IF_TALKED_TO
        # 直下の最後のコマンドとして0x00030005を使うと、話しかけ直すたびに毎回
        # OBJECT_TOGGLEが再実行される(=何度でも対象objectを有効化し直せる)。
        # 以前はOBJECT_TOGGLE_OPCODE(0x00010005)との完全一致でしか認識しておらず
        # high16違いが`op_00030005`としてしか表示されなかった。
        out['name'] = 'OBJECT_TOGGLE'
        out['target_object_idx'] = params[0] + 1
    elif opcode == MAP_WARP_OPCODE and len(params) >= 4:
        out['name'] = 'MAP_WARP'
        out['dst_map_id'] = params[0]
        name = load_floor_list().get(params[0])
        if name:
            out['dst_map_name'] = name
        out['pos_x'] = round(struct.unpack('<f', struct.pack('<I', params[1]))[0], 4)
        out['pos_y'] = round(struct.unpack('<f', struct.pack('<I', params[2]))[0], 4)
        out['pos_z'] = round(struct.unpack('<f', struct.pack('<I', params[3]))[0], 4)
        if len(params) >= 5:
            out['facing'] = params[4]
        if len(params) >= 6:
            out['warp_flag5'] = params[5]
    elif opcode_lo in _MESSAGE_OPCODE_LO and len(params) >= 2:
        out['name'] = 'MSG'
        out['msgid'] = params[0]
        out['count'] = params[1]
        if opcode_lo in _MESSAGE_TURN_TO_PLAYER_LO:
            out['turn_to_player'] = _MESSAGE_TURN_TO_PLAYER_LO[opcode_lo]
        opcode_hi16 = (opcode >> 16) & 0xFFFF
        if opcode_hi16 in _MSG_REPEAT_MODE_HI16:
            out['repeat_mode'] = _MSG_REPEAT_MODE_HI16[opcode_hi16]
        # 【確定 2026-10-04】params[1]を無条件に「ページ数」として
        # resolve_message(msgid+i)をその回数だけ呼ぶ実装だったが、全ROM走査
        # したところ、低8bit=0x0a/0x0b/0x0d/0x0e等の一部コマンドでは
        # params[1]が実際には小さいページ数ではなく「別の(近い)msgid」と
        # 見られる値（例: msgid=4372に対してparams[1]=4373、
        # msgid=25213に対してparams[1]=25215等）になっているケースが
        # 809件見つかった。これを「ページ数」として扱うと
        # resolve_message()を数万〜85万回呼び、1コマンドで数十万文字の
        # テキストを連結してしまい、該当ファイルの`/api/parse`が数秒〜に
        # 悪化する原因になっていた（`m05nout.bin`で実測）。
        # 実際に確認できている正規の複数ページ表示(0x00030009等)は
        # count=1〜8程度に収まっており、不自然に大きい値は「ページ数」
        # ではない何か別の意味を持つパラメータだと考えられる(詳細未確定)。
        # 安全策として、明らかに非現実的な大きさの場合はテキスト解決
        # 自体を行わない(countの生値はそのまま出力し、閲覧は妨げない)。
        _MSG_PAGE_COUNT_SANITY_MAX = 20
        count = params[1]
        if 0 <= count <= _MSG_PAGE_COUNT_SANITY_MAX:
            text_parts = []
            for i in range(max(1, count)):
                t = resolve_message(params[0] + i)
                if t:
                    text_parts.append(t)
            if text_parts:
                out['text'] = ''.join(text_parts)
        else:
            out['count_suspicious'] = True
    else:
        out['name'] = f'op_{opcode:08x}'

    return out


def _split_commands(block1: dict, block2: dict, block3: dict) -> list:
    """block1 holds one byte per command: its if/elseif nesting depth (see
    script/README.md - confirmed by cross-referencing this exact byte
    array against a real cascading if-elseif chain in
    SCRIPT/m01nk1f1.bin). Each command's 'indent' field below is that
    depth, used by the frontend to render the branch structure visually.
    """
    if not block2 or not block3:
        return []
    offsets = block2.get('offsets') or []
    code_size = block3.get('size', 0)
    code_raw = block3.get('raw', b'')
    indent_bytes = (block1 or {}).get('raw', b'')
    valid = sorted({o for o in offsets if isinstance(o, int) and 0 <= o <= code_size})
    if not valid or valid[-1] != code_size:
        valid.append(code_size)
    valid = sorted(set(valid))
    commands = []
    for i in range(len(valid) - 1):
        s, e = valid[i], valid[i + 1]
        if e <= s:
            continue
        raw = code_raw[s:e]
        cmd = _decode_command(raw)
        cmd['rel_start'] = s
        cmd['rel_end'] = e
        cmd_idx = len(commands)
        cmd['indent'] = indent_bytes[cmd_idx] if cmd_idx < len(indent_bytes) else None
        commands.append(cmd)
    return commands


# NPC配置情報テーブル: scriptobjectヘッダ直後の0x30byte領域。
# m01nk1f1.bin内の複数グループ・オブジェクトを比較した結果、
# group2/obj2 (v0=2003,v1=182,x=-3.0,z=-4.8) と group3/obj7 (v0=2003,v1=182,
# x=4.0,z=6.5) など、同じ(v0,v1)の組が別グループ(=時間帯/天候違いなどの
# バリエーション)で異なる座標を伴って繰り返し出現することを確認した。
# これは「同一NPCが複数バリエーショングループに同じ定義IDで登場し、
# バリエーションごとに立ち位置だけが違う」という配置テーブルの挙動と一致する。
#
# 【確定 2026-08-23】offset+4(npc_model_id)は実機検証で確定した。
# group3/obj7(シスター)のこの値を182→2(MENULIST/party_menu.txtのマリベルの
# キャラID)に書き換えてCIAを再ビルドし実機テストしたところ、シスターの
# 見た目が実際にマリベルのモデルに変わることを確認した
# (script/patch_m01nk1f1_sister_model_to_maribel.py)。すなわちこのフィールドは
# 表示する3Dモデル/アクターを選択する値であり、ADD_PARTY_MEMBER等が使う
# キャラID空間(1〜6)と同じ値空間を少なくとも部分的に共有している。
# offset+0(unk_instance_id)は依然未解読。「#2003」のような話者制御コードと
# 一致することは分かっているが、model_id変更後もシーン移植テストがフリーズ
# したため、model_idとは独立に何らかのアクター/インスタンス識別に使われて
# いる可能性があり、現在0への書き換えを試験中
# (script/patch_m01nk1f1_sister_instanceid_zero.py)。
# 【確定 2026-08-27】offset+12/16/20(pos_x/pos_y/pos_z)も実機検証で確定した。
# ビュアーのNPC配置情報編集機能(edit_npc_placement_field()、2026-08-27追加)
# でこれらの値を書き換えてCIAを再ビルドし実機テストしたところ、対象NPCの
# 表示位置(X/Y/Z座標)が実際に変化することを確認した。詳細は
# docs/party_add_remove_command_investigation.md「配置情報のビュアー編集
# 機能を追加、pos_x/pos_y/pos_zを実機確定」節を参照。
#
# フィールド定義。offset 24-44 はサンプル上常に0で未解読のため、名前を
# 付けず unk_offsetNN のまま生値(u32/i32/f32/hex)を全て見られるようにしておく。
_NPC_PLACEMENT_FIELD_DEFS = [
    (0, 'unk_instance_id', 'u32', '未解読: 話者制御コード(#2003等)と一致する値。model_id確定後も別NPCモデルへの表示置換だけでは解決しないシーン移植フリーズの原因調査中'),
    (4, 'npc_model_id', 'u32', '【確定・実機検証済み】NPCの表示モデル/アクターID。182→2書き換えでシスターの見た目がマリベルに変化することを確認(2026-08-23)'),
    (8, 'unk_type_flag', 'u32', '仮説: 種別フラグ or 向き'),
    (12, 'pos_x', 'f32', '【確定・実機検証済み】マップ座標X。ビュアーで書き換えてCIA再ビルド・実機テストしたところ表示位置が実際に変化することを確認(2026-08-27)'),
    (16, 'pos_y', 'f32', '【確定・実機検証済み】マップ座標Y（高さ）。ビュアーで書き換えてCIA再ビルド・実機テストしたところ表示位置が実際に変化することを確認(2026-08-27)'),
    (20, 'pos_z', 'f32', '【確定・実機検証済み】マップ座標Z。ビュアーで書き換えてCIA再ビルド・実機テストしたところ表示位置が実際に変化することを確認(2026-08-27)'),
    (24, 'unk_offset24', 'u32', '未解読（サンプルでは常に0）'),
    (28, 'unk_offset28', 'u32', '未解読（サンプルでは常に0）'),
    (32, 'unk_offset32', 'u32', '未解読（サンプルでは常に0）'),
    (36, 'unk_offset36', 'u32', '未解読（サンプルでは常に0）'),
    (40, 'unk_offset40', 'u32', '未解読（サンプルでは常に0）'),
    (44, 'unk_offset44', 'u32', '未解読（サンプルでは常に0）'),
]


def _decode_npc_placement(unknown_area: bytes) -> dict | None:
    if len(unknown_area) < 48:
        return None
    if unknown_area == bytes(48):
        return None

    fields = []
    for off, name, primary_type, note in _NPC_PLACEMENT_FIELD_DEFS:
        u32v = struct.unpack_from('<I', unknown_area, off)[0]
        i32v = struct.unpack_from('<i', unknown_area, off)[0]
        f32v = struct.unpack_from('<f', unknown_area, off)[0]
        fields.append({
            'offset': off,
            'name': name,
            'primary_type': primary_type,
            'note': note,
            'u32': u32v,
            'i32': i32v,
            'f32': round(f32v, 4),
            'hex': unknown_area[off:off + 4].hex(),
        })

    npc_model_id = fields[1]['u32']
    pos_x, pos_y, pos_z = fields[3]['f32'], fields[4]['f32'], fields[5]['f32']
    has_position = not (pos_x == 0.0 and pos_y == 0.0 and pos_z == 0.0)
    return {
        'npc_model_id': npc_model_id,
        'pos_x': pos_x,
        'pos_z': pos_z,
        # 座標が全て0のオブジェクトは、物理的な配置を持たない別種の
        # オブジェクト（ロジック専用トリガー等）で、フィールドの意味が
        # ずれている可能性がある(例: m01nk1f1.bin group3 obj1-5は座標0
        # だがoffset4に2000番台のIDが入っており、他グループのoffset0と
        # 同じ値域)。そのため座標ありのエントリより解釈の確信度が低い。
        'confidence': 'high' if has_position else 'low',
        'fields': fields,
    }


def _locate_npc_placement(data: bytes, path: str, group_idx: int, obj_idx: int):
    """Resolve (abs_offset_of_48byte_block, header_size) for one object's
    NPC placement area, re-deriving it from script_viewer.parse_* the
    same way build_tree() does - kept independent of any already-built
    tree/JSON so the edit endpoint doesn't have to trust client-supplied
    offsets (only client-supplied group_idx/obj_idx/field_offset, all
    re-validated against the live file)."""
    top = sv.parse_script(path)
    groups = top.get('groups', [])
    if not (0 <= group_idx < len(groups)):
        raise ValueError(f'invalid group_idx {group_idx}')
    g = groups[group_idx]
    objs_hdr = sv.parse_group_objects_header(data, g['offset'], g['size'])
    if not (0 <= obj_idx < len(objs_hdr)):
        raise ValueError(f'invalid obj_idx {obj_idx}')
    o_ref = objs_hdr[obj_idx]
    obj = sv.parse_object(data, o_ref['offset'], o_ref['size'])
    header_size = obj.get('header_size')
    unknown_area = obj.get('unknown_area', b'')
    if not header_size or len(unknown_area) < 48:
        raise ValueError('this object has no NPC placement data area')
    return o_ref['offset'] + header_size


def edit_npc_placement_field(filename: str, group_idx: int, obj_idx: int, field_offset: int,
                              value_type: str, value, comment: str = '') -> dict:
    """Patch one 4-byte field of an object's 48-byte NPC placement area
    in place (added 2026-08-27 per user request to make this editable
    from the viewer, alongside the existing script-command editor). Much
    simpler than command editing: this area has a fixed size and isn't
    part of any block1/2/3 ref-table, so overwriting 4 bytes in place
    never changes the file's total size or requires re-running
    verify_script_structure.py - it's a plain byte patch + backup +
    history entry, no splice/offset-propagation logic needed.
    """
    valid_offsets = {d[0] for d in _NPC_PLACEMENT_FIELD_DEFS}
    if field_offset not in valid_offsets:
        raise ValueError(f'invalid field_offset {field_offset}')
    if value_type not in ('u32', 'i32', 'f32'):
        raise ValueError(f'invalid value_type {value_type!r}')

    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    with open(path, 'rb') as f:
        data = f.read()
    placement_abs = _locate_npc_placement(data, path, group_idx, obj_idx)
    abs_pos = placement_abs + field_offset
    if abs_pos + 4 > len(data):
        raise ValueError('field position out of range')

    old_raw = data[abs_pos:abs_pos + 4]
    if value_type == 'f32':
        new_raw = struct.pack('<f', float(value))
    elif value_type == 'i32':
        new_raw = struct.pack('<i', int(value))
    else:
        new_raw = struct.pack('<I', int(value) & 0xFFFFFFFF)
    new_data = data[:abs_pos] + new_raw + data[abs_pos + 4:]

    field_name = next((d[1] for d in _NPC_PLACEMENT_FIELD_DEFS if d[0] == field_offset),
                       f'unk_offset{field_offset}')

    def _summarize_raw(raw: bytes) -> dict:
        return {
            'u32': struct.unpack_from('<I', raw, 0)[0],
            'i32': struct.unpack_from('<i', raw, 0)[0],
            'f32': round(struct.unpack_from('<f', raw, 0)[0], 4),
            'hex': raw.hex(),
        }

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(path, 'wb') as f:
        f.write(new_data)

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'op': 'npc_field_edit',
        'group_idx': group_idx, 'obj_idx': obj_idx,
        'field_offset': field_offset, 'field_name': field_name,
        'before': _summarize_raw(old_raw), 'after': _summarize_raw(new_raw),
        'comment': comment, 'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data), 'new_size': len(new_data),
    })

    return {
        'ok': True, 'old_size': len(data), 'new_size': len(new_data),
        'backup_path': backup_path, 'history_id': stamp, 'field_name': field_name,
        'after': _summarize_raw(new_raw),
    }


def _revert_npc_field_edit(filename: str, entry: dict) -> dict:
    """git-revert-style undo for a single 'npc_field_edit' history entry -
    the npc-placement counterpart to revert_entry_as_new_change() for
    command edits. Same conflict rule: refuses if the live field no
    longer matches what `after` recorded (a later edit already changed
    it), otherwise writes `before` back and appends a new entry rather
    than discarding the original one."""
    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    with open(path, 'rb') as f:
        data = f.read()
    placement_abs = _locate_npc_placement(data, path, entry['group_idx'], entry['obj_idx'])
    abs_pos = placement_abs + entry['field_offset']
    current_hex = data[abs_pos:abs_pos + 4].hex()
    if current_hex != entry['after']['hex']:
        return {
            'ok': False,
            'error': 'revert conflict: a later edit already changed this field',
            'conflicts': [entry],
        }

    new_raw = bytes.fromhex(entry['before']['hex'])
    new_data = data[:abs_pos] + new_raw + data[abs_pos + 4:]

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(path, 'wb') as f:
        f.write(new_data)

    original_comment = entry.get('comment') or entry['id']
    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'op': 'npc_field_edit',
        'group_idx': entry['group_idx'], 'obj_idx': entry['obj_idx'],
        'field_offset': entry['field_offset'], 'field_name': entry.get('field_name'),
        'before': entry['after'], 'after': entry['before'],
        'comment': f'Revert "{original_comment}"', 'result_comment': None,
        'backup_path': backup_path, 'old_size': len(data), 'new_size': len(new_data),
        'reverts_entry_id': entry['id'],
    })

    return {'ok': True, 'old_size': len(data), 'new_size': len(new_data),
            'backup_path': backup_path, 'history_id': stamp}


def build_tree(filename: str) -> dict:
    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    with open(path, 'rb') as f:
        data = f.read()

    top = sv.parse_script(path)
    groups_out = []
    for g_idx, g in enumerate(top.get('groups', [])):
        objs_hdr = sv.parse_group_objects_header(data, g['offset'], g['size'])
        objects_out = []
        for o_idx, o_ref in enumerate(objs_hdr):
            obj = sv.parse_object(data, o_ref['offset'], o_ref['size'])
            procs_out = []
            for proc in obj.get('procedures', []):
                blocks = proc.get('blocks', [])
                commands = []
                if len(blocks) >= 3:
                    commands = _split_commands(blocks[0], blocks[1], blocks[2])
                procs_out.append({
                    'tag': proc.get('tag', '').strip('\x00'),
                    'start': proc.get('start'),
                    'size': proc.get('size'),
                    'block_count': proc.get('block_count'),
                    'commands': commands,
                })
            objects_out.append({
                'index': o_idx,
                'tag': obj.get('tag', '').strip('\x00'),
                'offset': o_ref['offset'],
                'size': o_ref['size'],
                'proc_count': obj.get('proc_count'),
                'npc_placement': _decode_npc_placement(obj.get('unknown_area', b'')),
                'procedures': procs_out,
            })
        groups_out.append({
            'index': g_idx,
            'tag': g.get('tag', '').strip('\x00'),
            'offset': g['offset'],
            'size': g['size'],
            'obj_count': g.get('obj_count'),
            'objects': objects_out,
        })

    return {
        'file': filename,
        'file_size': len(data),
        'header': top.get('header', {}),
        'groups': groups_out,
        'flag_usage': _collect_flag_usage(groups_out),
    }


# opcodes confirmed (or strongly suspected) to read/write a (type, id)
# flag pair as their first two params - see docs/party_add_remove_command_investigation.md.
# Used to build the "used flags" scan requested by the user (2026-08-24)
# to help pick a collision-free flag id when transplanting script
# content: the working theory is that flag ids under a given type are
# map-local variables shared across every object/procedure in the file
# (possibly the whole group), so any transplant needs an id nobody else
# in the target file already uses.
_FLAG_OPCODES = {
    '0x00000003': ('IF_FLAG', 'read'),
    '0x00010004': ('SET_FLAG', 'write'),
    '0x00030004': ('op_00030004', 'write'),
    '0x00010025': ('CONFIRM_YESNO', 'write'),
}


def _collect_flag_usage(groups_out: list) -> list:
    """Scan every command in the already-built tree for the known
    flag-carrying opcodes and return a flat list of
    {type, id, rw, opcode_name, group_idx, obj_idx, proc_tag, cmd_idx}
    records - the raw material for the viewer's "使用フラグ" panel.
    Sorted by (type, id) so gaps (candidate unused ids) are easy to spot
    by eye, matching how this session has been picking flag ids by hand
    so far (e.g. choosing 30 or 99999 as "probably unused").
    """
    usage = []
    for g in groups_out:
        for o in g['objects']:
            for p in o['procedures']:
                for ci, c in enumerate(p['commands']):
                    if c.get('opcode') == f'0x{CHOICE_MENU_OPCODE:08x}':
                        # doesn't fit the (type,id,value) triple shape - it
                        # writes one type=2 flag per party slot (2-6) at once
                        # (see CHOICE_MENU_OPCODE docstring); 0 means "no
                        # flag" (the asker's own slot), so skip those.
                        for slot_flag in (c.get('slot_flags') or []):
                            if slot_flag:
                                usage.append({
                                    'type': 2, 'id': slot_flag,
                                    'rw': 'write', 'opcode_name': 'CHOICE_MENU',
                                    'group_idx': g['index'], 'obj_idx': o['index'],
                                    'proc_tag': p['tag'], 'cmd_idx': ci,
                                })
                        continue
                    entry = _FLAG_OPCODES.get(c.get('opcode'))
                    if not entry:
                        continue
                    params = c.get('params') or []
                    if len(params) < 2:
                        continue
                    name, rw = entry
                    usage.append({
                        'type': params[0], 'id': params[1],
                        'rw': rw, 'opcode_name': name,
                        'group_idx': g['index'], 'obj_idx': o['index'],
                        'proc_tag': p['tag'], 'cmd_idx': ci,
                    })
    usage.sort(key=lambda e: (e['type'], e['id']))
    return usage


def browse_dir(requested: str) -> dict:
    """List a directory's contents for the save-editor's file browser.

    Not sandboxed to a fixed root (unlike list_script_files) - the user's
    save file can live anywhere on the filesystem (SD card mount, Citra
    profile dir, etc.), so this deliberately allows browsing the whole
    accessible filesystem, same as a native file-open dialog would.
    """
    path = os.path.abspath(requested) if requested else os.path.expanduser('~')
    if not os.path.isdir(path):
        path = os.path.dirname(path) if os.path.isfile(path) else os.path.expanduser('~')
    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    size = 0 if is_dir else entry.stat(follow_symlinks=True).st_size
                except OSError:
                    continue
                entries.append({'name': entry.name, 'is_dir': is_dir, 'size': size})
    except PermissionError:
        pass
    entries.sort(key=lambda e: (not e['is_dir'], e['name'].lower()))
    parent = None if path == '/' else os.path.dirname(path)
    return {'path': path, 'parent': parent, 'entries': entries}


def list_script_files() -> list:
    if not os.path.isdir(_SCRIPT_FILES_DIR):
        return []
    files = []
    for name in sorted(os.listdir(_SCRIPT_FILES_DIR)):
        if name.endswith('.bin'):
            full = os.path.join(_SCRIPT_FILES_DIR, name)
            files.append({'name': name, 'size': os.path.getsize(full)})
    return files


def _walk_file_commands_light(data: bytes):
    """Lightweight (no MESS resolution) walk of every command in a SCRIPT
    file's bytes, yielding (g_idx, o_idx, obj_tag, proc_tag, cmd_idx,
    opcode, params). Mirrors script/scan_opcode_0x100c5.py's walk_file -
    deliberately doesn't go through build_tree()/_decode_command() (which
    calls resolve_message() per message command), since a full-ROM scan
    across all ~1300 SCRIPT files needs to stay fast. Used by
    search_message_text() below to find which commands reference a given
    set of message ids, without paying the MESS-resolution cost for every
    command in every file - only the small number of actual hits get
    their text resolved afterward.
    """
    if len(data) < 0x20:
        return
    top_header_size = sp._read_u32(data, 0x14)
    try:
        groups = sp._parse_ref_table(data, 0, 0x10, 0x18, top_header_size)
    except (struct.error, IndexError):
        return

    for g_idx, group in enumerate(groups):
        group_start = group['abs_offset']
        if group_start + 0x20 > len(data):
            continue
        try:
            group_header_size = sp._read_u32(data, group_start + 0x14)
            objects = sp._parse_ref_table(data, group_start, 0x10, 0x18, group_header_size)
        except (struct.error, IndexError):
            continue

        for o_idx, obj in enumerate(objects):
            obj_start = obj['abs_offset']
            if obj_start + 0x20 > len(data):
                continue
            obj_tag = data[obj_start:obj_start + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
            try:
                obj_header_size = sp._read_u32(data, obj_start + 0x14)
                procs = sp._parse_ref_table(data, obj_start, 0x10, 0x18, obj_header_size)
            except (struct.error, IndexError):
                continue

            for proc in procs:
                proc_start = proc['abs_offset']
                if proc_start + 0x20 > len(data):
                    continue
                proc_tag = data[proc_start:proc_start + 0x10].rstrip(b'\x00').decode('ascii', errors='replace')
                try:
                    proc_header_size = sp._read_u32(data, proc_start + 0x14)
                    blocks = sp._parse_ref_table(data, proc_start, 0x10, 0x18, proc_header_size)
                except (struct.error, IndexError):
                    continue
                if len(blocks) < 3:
                    continue
                b2, b3 = blocks[1], blocks[2]
                if b2['abs_offset'] + b2['size'] > len(data) or b3['abs_offset'] + b3['size'] > len(data):
                    continue
                offsets = [struct.unpack_from('<I', data, b2['abs_offset'] + i * 4)[0]
                           for i in range(b2['size'] // 4)]
                for cmd_idx in range(len(offsets) - 1):
                    s, e = offsets[cmd_idx], offsets[cmd_idx + 1]
                    if e <= s or e - s < 4:
                        continue
                    abs_s = b3['abs_offset'] + s
                    if abs_s + 4 > len(data):
                        continue
                    opcode = struct.unpack_from('<I', data, abs_s)[0]
                    params = []
                    off = abs_s + 4
                    while off + 4 <= b3['abs_offset'] + e:
                        params.append(struct.unpack_from('<I', data, off)[0])
                        off += 4
                    yield g_idx, o_idx, obj_tag, proc_tag, cmd_idx, opcode, params


def search_message_text(query: str, limit: int = 300) -> dict:
    """Find every event-script command that displays message text
    containing `query`, across the whole ROM. Two-pass design to stay
    fast (requested 2026-08-27, after this session's earlier lesson that
    a full build_tree() scan of all ~1300 SCRIPT files - which resolves
    MESS text for every single command - is too slow):

    1. Scan every MESS/*.fpt file's already-decoded text (small, cheap)
       for the query, collecting the matching message ids.
    2. Lightweight-scan every SCRIPT file's raw command bytes (no MESS
       resolution) for the opcodes known to carry a msgid param
       (FANFARE_MSG/MSG family/CHOICE_MENU - see _decode_command), and
       keep only the ones whose msgid (or, for MSG, msgid+i for
       i in range(count)) is in the matched set from step 1.

    This mirrors script/scan_opcode_0x100c5.py's separation of "cheap
    structural scan across everything" from "expensive resolution only
    for the few real hits".
    """
    query_norm = query.strip()
    if not query_norm:
        return {'query': query, 'results': [], 'truncated': False}
    query_lower = query_norm.lower()

    matched_ids = {}
    if os.path.isdir(_MESS_DIR):
        for name in sorted(os.listdir(_MESS_DIR)):
            if not name.endswith('.fpt'):
                continue
            entries = _parse_fpt(os.path.join(_MESS_DIR, name))
            for entry_name, text in entries.items():
                if query_lower in text.lower():
                    m = re.match(r'#(\d+)\.txt$', entry_name)
                    if m:
                        matched_ids[int(m.group(1))] = text

    results = []
    truncated = False
    if matched_ids and os.path.isdir(_SCRIPT_FILES_DIR):
        for fn in sorted(os.listdir(_SCRIPT_FILES_DIR)):
            if not fn.endswith('.bin'):
                continue
            with open(os.path.join(_SCRIPT_FILES_DIR, fn), 'rb') as f:
                data = f.read()
            for g_idx, o_idx, obj_tag, proc_tag, cmd_idx, opcode, params in _walk_file_commands_light(data):
                hit_msgid = None
                if opcode == FANFARE_MSG_OPCODE and len(params) >= 1 and params[0] in matched_ids:
                    hit_msgid = params[0]
                elif opcode == CHOICE_MENU_OPCODE and len(params) >= 1 and params[0] in matched_ids:
                    hit_msgid = params[0]
                elif (opcode & 0xFF) in _MESSAGE_OPCODE_LO and len(params) >= 2:
                    # 【確定 2026-10-04】params[1]を無条件に「ページ数」として
                    # params[0]..params[0]+count-1の範囲を全部matched_idsと
                    # 突き合わせていたが、_decode_command()側で見つかった
                    # 同じ不具合(809件、countが実際には別の意味のパラメータで
                    # 数万〜数十万になっている)がここにも存在し、無関係に
                    # ヒットした巨大範囲の中に偶然検索語を含む別のmsgidが
                    # 含まれると、「検索結果の場所に実際に飛んでみても
                    # 検索語が見当たらない」という食い違いの原因になっていた
                    # （`docs/viewer_msg_count_param_perf_bug.md`参照）。
                    # 同じ安全装置(count<=20)をここにも適用する。
                    count = params[1]
                    if 0 <= count <= 20:
                        for i in range(max(1, count)):
                            if params[0] + i in matched_ids:
                                hit_msgid = params[0] + i
                                break
                if hit_msgid is None:
                    continue
                results.append({
                    'file': fn, 'group_idx': g_idx, 'obj_idx': o_idx, 'obj_tag': obj_tag,
                    'proc_tag': proc_tag, 'cmd_idx': cmd_idx, 'opcode': f'0x{opcode:08x}',
                    'msgid': hit_msgid, 'text': matched_ids[hit_msgid],
                })
                if len(results) >= limit:
                    truncated = True
                    break
            if truncated:
                break

    return {'query': query_norm, 'results': results, 'truncated': truncated}


def _encode_command(cmd: dict) -> bytes:
    """cmd = {'indent': int, 'opcode': '0x00030009' or int, 'params': [int, ...]}
    -> raw command bytes (opcode u32 LE + each param u32 LE), same shape
    every command in this format uses (see script/README.md)."""
    opcode = cmd['opcode']
    opcode = int(opcode, 16) if isinstance(opcode, str) else int(opcode)
    raw = struct.pack('<I', opcode)
    for p in cmd.get('params', []):
        raw += struct.pack('<I', int(p) & 0xFFFFFFFF)
    return raw


_HISTORY_FILE = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, 'history.jsonl')


def _find_procedure_commands(tree: dict, group_idx: int, obj_idx: int, proc_tag: str) -> list:
    g = tree['groups'][group_idx]
    o = g['objects'][obj_idx]
    p = next(pr for pr in o['procedures'] if pr['tag'] == proc_tag)
    return p['commands']


def _summarize_commands(commands: list) -> list:
    """Compact {indent, opcode, name, params, text} view of decoded
    commands, for the change-history 'before'/'after' summaries - drops
    rel_start/rel_end/hex, which are absolute-position-dependent and
    meaningless once shown out of context in a history log.

    `indent` IS kept (unlike the original cut of this function) because
    revert_entry_as_new_change() needs it to fully reconstruct a
    command's original bytes when un-doing an edit - opcode+params alone
    isn't enough to re-insert a command, since _encode_command doesn't
    invent an indent value. History entries recorded before this field
    was added won't have it, so old entries can't be revert()'d (see
    revert_entry_as_new_change's check) - only deleted/restored the old
    "clobber everything since" way.
    """
    out = []
    for c in commands:
        out.append({
            'indent': c.get('indent'),
            'opcode': c.get('opcode'),
            'name': c.get('name'),
            'params': c.get('params'),
            'text': (c.get('text') or '')[:60] or None,
        })
    return out


def _append_history(entry: dict) -> None:
    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    with open(_HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def _read_history(filename: str = None) -> list:
    if not os.path.isfile(_HISTORY_FILE):
        return []
    entries = []
    with open(_HISTORY_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if filename is None or entry.get('file') == filename:
                entries.append(entry)
    entries.sort(key=lambda e: e.get('id', ''), reverse=True)
    return entries


def _rewrite_history(entries: list) -> None:
    """Used only by add_history_comment - the log is append-only for new
    edits, but annotating an existing entry with a post-hoc test result
    requires updating that one line in place."""
    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    with open(_HISTORY_FILE, 'w', encoding='utf-8') as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def add_history_comment(entry_id: str, comment: str = None, result_comment: str = None) -> dict:
    """Update an existing history entry's `comment` (the "what/why" note
    made at edit time) and/or `result_comment` (added later, e.g. after
    an on-device test) - either or both may be given; a None means
    "leave that field alone" (so calling this to just add a
    result_comment doesn't blank out the original comment, and vice
    versa)."""
    entries = _read_history()
    found = False
    for e in entries:
        if e.get('id') == entry_id:
            if comment is not None:
                e['comment'] = comment
            if result_comment is not None:
                e['result_comment'] = result_comment
            found = True
    if not found:
        raise ValueError(f'history entry {entry_id!r} not found')
    entries.sort(key=lambda e: e.get('id', ''))
    _rewrite_history(entries)
    return {'ok': True}


def revert_to_history_entry(entry_id: str) -> dict:
    """HARD RESET fallback (like `git reset --hard <before-X>`, not a
    real revert): restores the file to the state it was in right BEFORE
    the given history entry's edit, which discards that edit AND EVERY
    edit made after it (since each entry's backup is a chain of
    consecutive pre-edit snapshots, restoring entry X's backup throws
    away X and everything downstream of it).

    Per user feedback (2026-08-27), this is NOT what "戻す" should do by
    default - see revert_entry_as_new_change() for the git-revert-style
    behavior (undo just the targeted entry's own change, as a new
    history entry, leaving unrelated later edits intact) that the UI
    now offers first. This function is kept as the explicit fallback for
    when that surgical revert reports a conflict and the user really
    does want to discard everything back to a known-good point.

    Verifies the restored file's structure too, since the backup itself
    was already known-good (it passed verify when it was live), but this
    re-check catches e.g. a stale/moved backup path."""
    entries = _read_history()
    entry = next((e for e in entries if e.get('id') == entry_id), None)
    if entry is None:
        raise ValueError(f'history entry {entry_id!r} not found')
    backup_path = entry['backup_path']
    if not os.path.isfile(backup_path):
        raise ValueError(f'backup file missing: {backup_path}')
    filename = entry['file']
    path = os.path.join(_SCRIPT_FILES_DIR, filename)

    with open(backup_path, 'rb') as f:
        backup_data = f.read()
    with open(path, 'rb') as f:
        current_data = f.read()

    # back up the current (about-to-be-discarded) state too, so a revert
    # is itself always undoable.
    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    pre_revert_backup = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(pre_revert_backup, 'wb') as f:
        f.write(current_data)

    with open(path, 'wb') as f:
        f.write(backup_data)

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'op': 'revert',
        'comment': f'revert to state before entry {entry_id}',
        'result_comment': None,
        'backup_path': pre_revert_backup,
        'old_size': len(current_data),
        'new_size': len(backup_data),
    })

    return {'ok': True, 'new_size': len(backup_data), 'pre_revert_backup': pre_revert_backup}


def _entry_sub_ops(entry: dict) -> list:
    """Normalizes a history entry to a list of per-procedure sub-ops
    ({group_idx, obj_idx, proc_tag, start_idx, before, after, comment}),
    whether it's a single edit/insert/delete entry or a 'batch' entry
    with its own `ops` list - so revert_entry_as_new_change() can treat
    both the same way."""
    if 'ops' in entry:
        return entry['ops']
    keys = ('group_idx', 'obj_idx', 'proc_tag', 'start_idx', 'before', 'after', 'comment')
    return [{k: entry[k] for k in keys if k in entry}]


def revert_entry_as_new_change(filename: str, entry_id: str) -> dict:
    """git-revert-style undo (added 2026-08-27, replacing
    revert_to_history_entry as the default "戻す" action): applies the
    INVERSE of just the targeted entry's own change(s) as a brand-new
    history entry, leaving every OTHER edit made since then untouched -
    unlike revert_to_history_entry, which discards everything after the
    target (more like `git reset --hard`).

    For each of the entry's sub-ops, this checks whether the CURRENT
    content at [start_idx, start_idx+len(after)) in that procedure still
    matches what `after` recorded at the time - i.e. whether a LATER
    edit has already touched that same range. If any sub-op's target has
    drifted, the whole revert is refused with a conflict report (mirrors
    a git revert conflict) rather than silently overwriting whatever is
    there now. If everything matches, the inverses are applied in
    REVERSE order - this mirrors how a forward batch's ops build on each
    other, and, within one procedure, undoing higher indices first keeps
    lower indices valid (the same reasoning as the viewer's bulk-delete
    feature) - and written
    as a single new entry.

    Only works on entries recorded after `indent` was added to
    _summarize_commands()'s output (2026-08-27) - older entries don't
    have enough information in `before` to reconstruct the original
    command bytes, and are reported as un-revertable this way (use the
    hard-reset fallback instead).
    """
    entries = _read_history(filename)
    entry = next((e for e in entries if e.get('id') == entry_id), None)
    if entry is None:
        raise ValueError(f'history entry {entry_id!r} not found for {filename!r}')
    if entry.get('op') == 'npc_field_edit':
        return _revert_npc_field_edit(filename, entry)
    if entry.get('op') in ('add_object', 'overwrite_object', 'delete_object'):
        raise ValueError(f"don't know how to revert an entry with op={entry.get('op')!r} - use the hard-reset fallback instead")
    if entry.get('op') not in ('edit', 'insert', 'delete', 'batch', 'revert'):
        raise ValueError(f"don't know how to revert an entry with op={entry.get('op')!r}")

    sub_ops = _entry_sub_ops(entry)
    if not sub_ops:
        raise ValueError('entry has no operations to revert')
    for sub in sub_ops:
        for cmd in (sub.get('before') or []) + (sub.get('after') or []):
            if cmd.get('indent') is None:
                raise ValueError(
                    'this entry predates indent-tracking in the history log and cannot be '
                    'surgically reverted - use the hard-reset (巻き戻す) option instead')

    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    with open(path, 'rb') as f:
        data = f.read()
    tree = build_tree(filename)

    conflicts = []
    for sub in sub_ops:
        after = sub.get('after') or []
        current = _find_procedure_commands(tree, sub['group_idx'], sub['obj_idx'], sub['proc_tag'])
        current_slice = _summarize_commands(current[sub['start_idx']:sub['start_idx'] + len(after)])
        if current_slice != after:
            conflicts.append(sub)
    if conflicts:
        return {
            'ok': False,
            'error': ('revert conflict: a later edit already changed the same command(s) - '
                      'this entry cannot be cleanly undone without also affecting that later edit'),
            'conflicts': conflicts,
        }

    working = data
    new_sub_ops = []
    for sub in reversed(sub_ops):
        before = sub.get('before') or []
        after = sub.get('after') or []
        new_indent_bytes = bytes(int(c['indent']) for c in before)
        parts, offsets, cursor = [], [], 0
        for c in before:
            offsets.append(cursor)
            raw = _encode_command(c)
            parts.append(raw)
            cursor += len(raw)
        working = sp.replace_commands(
            working, group_idx=sub['group_idx'], obj_idx=sub['obj_idx'], proc_tag=sub['proc_tag'],
            start_idx=sub['start_idx'], end_idx=sub['start_idx'] + len(after),
            new_indent_bytes=new_indent_bytes, new_block3_bytes=b''.join(parts), new_cmd_offsets=offsets,
        )
        new_sub_ops.append({
            'group_idx': sub['group_idx'], 'obj_idx': sub['obj_idx'], 'proc_tag': sub['proc_tag'],
            'start_idx': sub['start_idx'], 'end_idx': sub['start_idx'] + len(after),
            'op': 'revert_op',
            'before': after, 'after': before,
            'comment': f"revert: {sub.get('comment') or ''}".strip(),
        })

    # verify via the same short-lived-temp-file trick as preview_edit_script_commands
    tmp_name = f'.reverttmp_{os.getpid()}_{threading.get_ident()}.reverttmp'
    tmp_path = os.path.join(_SCRIPT_FILES_DIR, tmp_name)
    try:
        with open(tmp_path, 'wb') as f:
            f.write(working)
        import importlib.util
        verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
        spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
        verify_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify_mod)
        verify_tree = verify_mod.build_tree(tmp_name)
        anomalies: list = []
        verify_mod.check_commands(verify_tree, anomalies)
        verify_mod.check_block_alignment(tmp_name, anomalies)
        verify_mod.check_hierarchy(verify_tree, len(working), anomalies)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if anomalies:
        return {'ok': False, 'error': 'verify failed - revert was rejected, file untouched', 'anomalies': anomalies}

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(path, 'wb') as f:
        f.write(working)

    original_comment = entry.get('comment') or entry_id
    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'op': 'batch',
        'ops': list(reversed(new_sub_ops)),
        'comment': f'Revert "{original_comment}"',
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(working),
        'reverts_entry_id': entry_id,
    })

    return {'ok': True, 'old_size': len(data), 'new_size': len(working), 'backup_path': backup_path, 'history_id': stamp}


def copy_script_object(dst_filename: str, target_group_idx: int,
                        src_filename: str, src_group_idx: int, src_obj_idx: int,
                        new_tag: str = None, field_overrides: dict = None,
                        at_index: int = None,
                        comment: str = '') -> dict:
    """Clone an existing scriptobject and insert it as a brand-new object
    into target_group_idx's object list in dst_filename, via
    sp.splice_object() - the viewer's "オブジェクトを追加/コピー" feature
    (added 2026-08-29 per user request; see
    docs/script_object_insertion.md). src_filename/src_group_idx/
    src_obj_idx may equal dst_filename/target_group_idx/anything - this
    is exactly how "duplicate this object" works, no special-casing
    needed since splice_object() just reads two independent byte
    buffers.

    at_index (added 2026-08-30) selects where in the object list the new
    object lands (default: appended at the end) - a plain end-append was
    tested first and not picked up by the game on real hardware, so this
    lets the user test whether the game's NPC-spawn logic is sensitive
    to insertion POSITION rather than just structural validity (see
    docs/script_object_insertion.md).

    Follows the same backup-then-verify-then-accept-or-restore workflow
    as edit_script_commands() below: verify_script_structure's checks
    must pass on the result (this catches insertion bugs, not whether
    the game engine will actually invoke the new object at runtime -
    that remains untested/unproven, see docs/script_object_insertion.md).
    """
    if not dst_filename or '/' in dst_filename or '\\' in dst_filename:
        raise ValueError('invalid dst filename')
    if not src_filename or '/' in src_filename or '\\' in src_filename:
        raise ValueError('invalid src filename')
    dst_path = os.path.join(_SCRIPT_FILES_DIR, dst_filename)
    src_path = os.path.join(_SCRIPT_FILES_DIR, src_filename)
    if not os.path.isfile(dst_path):
        raise ValueError('dst file not found')
    if not os.path.isfile(src_path):
        raise ValueError('src file not found')

    with open(dst_path, 'rb') as f:
        data = f.read()
    src_data = data if src_filename == dst_filename else open(src_path, 'rb').read()

    new_data = sp.splice_object(
        data, target_group_idx=target_group_idx,
        src_data=src_data, src_group_idx=src_group_idx, src_obj_idx=src_obj_idx,
        new_tag=new_tag, field_overrides=field_overrides, at_index=at_index,
    )

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{dst_filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(dst_path, 'wb') as f:
        f.write(new_data)

    import importlib.util
    verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
    spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    tree = verify_mod.build_tree(dst_filename)
    anomalies: list = []
    verify_mod.check_commands(tree, anomalies)
    verify_mod.check_block_alignment(dst_filename, anomalies)
    verify_mod.check_hierarchy(tree, len(new_data), anomalies)

    if anomalies:
        with open(dst_path, 'wb') as f:
            f.write(data)
        return {
            'ok': False,
            'error': 'verify failed - object add was rejected and the file was restored to its pre-edit state',
            'anomalies': anomalies,
            'backup_path': backup_path,
        }

    new_obj_idx = at_index if at_index is not None else len(tree['groups'][target_group_idx]['objects']) - 1

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': dst_filename,
        'op': 'add_object',
        'target_group_idx': target_group_idx, 'new_obj_idx': new_obj_idx,
        'src_file': src_filename, 'src_group_idx': src_group_idx, 'src_obj_idx': src_obj_idx,
        'new_tag': new_tag,
        'field_overrides': field_overrides,
        'comment': comment or '',
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(new_data),
    })

    return {
        'ok': True,
        'old_size': len(data),
        'new_size': len(new_data),
        'backup_path': backup_path,
        'verify_pass': True,
        'history_id': stamp,
        'new_obj_idx': new_obj_idx,
    }


def overwrite_script_object(dst_filename: str, target_group_idx: int, target_obj_idx: int,
                             src_filename: str, src_group_idx: int, src_obj_idx: int,
                             new_tag: str = None, field_overrides: dict = None,
                             comment: str = '') -> dict:
    """Overwrite an EXISTING object (target_group_idx/target_obj_idx) with
    a clone of another object, via sp.replace_object() - the "既存object
    の乗っ取り" feature (added 2026-08-30, see
    docs/script_object_insertion.md's "実機検証の結果" section for why:
    appending a brand-new object via copy_script_object() above was not
    picked up by the game at all on real hardware, so the next
    experiment is overwriting an object index the game DOES already
    instantiate). Same backup-then-verify-then-accept-or-restore
    workflow as copy_script_object()/edit_script_commands().
    """
    if not dst_filename or '/' in dst_filename or '\\' in dst_filename:
        raise ValueError('invalid dst filename')
    if not src_filename or '/' in src_filename or '\\' in src_filename:
        raise ValueError('invalid src filename')
    dst_path = os.path.join(_SCRIPT_FILES_DIR, dst_filename)
    src_path = os.path.join(_SCRIPT_FILES_DIR, src_filename)
    if not os.path.isfile(dst_path):
        raise ValueError('dst file not found')
    if not os.path.isfile(src_path):
        raise ValueError('src file not found')

    with open(dst_path, 'rb') as f:
        data = f.read()
    src_data = data if src_filename == dst_filename else open(src_path, 'rb').read()

    new_data = sp.replace_object(
        data, target_group_idx=target_group_idx, target_obj_idx=target_obj_idx,
        src_data=src_data, src_group_idx=src_group_idx, src_obj_idx=src_obj_idx,
        new_tag=new_tag, field_overrides=field_overrides,
    )

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{dst_filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(dst_path, 'wb') as f:
        f.write(new_data)

    import importlib.util
    verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
    spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    tree = verify_mod.build_tree(dst_filename)
    anomalies: list = []
    verify_mod.check_commands(tree, anomalies)
    verify_mod.check_block_alignment(dst_filename, anomalies)
    verify_mod.check_hierarchy(tree, len(new_data), anomalies)

    if anomalies:
        with open(dst_path, 'wb') as f:
            f.write(data)
        return {
            'ok': False,
            'error': 'verify failed - object overwrite was rejected and the file was restored to its pre-edit state',
            'anomalies': anomalies,
            'backup_path': backup_path,
        }

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': dst_filename,
        'op': 'overwrite_object',
        'target_group_idx': target_group_idx, 'target_obj_idx': target_obj_idx,
        'src_file': src_filename, 'src_group_idx': src_group_idx, 'src_obj_idx': src_obj_idx,
        'new_tag': new_tag,
        'field_overrides': field_overrides,
        'comment': comment or '',
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(new_data),
    })

    return {
        'ok': True,
        'old_size': len(data),
        'new_size': len(new_data),
        'backup_path': backup_path,
        'verify_pass': True,
        'history_id': stamp,
    }


def delete_script_object(dst_filename: str, target_group_idx: int, target_obj_idx: int,
                          comment: str = '') -> dict:
    """Delete an EXISTING object (target_group_idx/target_obj_idx) entirely
    from dst_filename, via sp.delete_object() - the "オブジェクトを丸ごと
    削除" feature (added 2026-08-31 per user request; see
    docs/script_object_insertion.md). Same backup-then-verify-then-
    accept-or-restore workflow as copy_script_object()/
    overwrite_script_object() above.
    """
    if not dst_filename or '/' in dst_filename or '\\' in dst_filename:
        raise ValueError('invalid dst filename')
    dst_path = os.path.join(_SCRIPT_FILES_DIR, dst_filename)
    if not os.path.isfile(dst_path):
        raise ValueError('dst file not found')

    with open(dst_path, 'rb') as f:
        data = f.read()

    new_data = sp.delete_object(data, target_group_idx=target_group_idx, target_obj_idx=target_obj_idx)

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{dst_filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)
    with open(dst_path, 'wb') as f:
        f.write(new_data)

    import importlib.util
    verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
    spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    tree = verify_mod.build_tree(dst_filename)
    anomalies: list = []
    verify_mod.check_commands(tree, anomalies)
    verify_mod.check_block_alignment(dst_filename, anomalies)
    verify_mod.check_hierarchy(tree, len(new_data), anomalies)

    if anomalies:
        with open(dst_path, 'wb') as f:
            f.write(data)
        return {
            'ok': False,
            'error': 'verify failed - object delete was rejected and the file was restored to its pre-edit state',
            'anomalies': anomalies,
            'backup_path': backup_path,
        }

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': dst_filename,
        'op': 'delete_object',
        'target_group_idx': target_group_idx, 'target_obj_idx': target_obj_idx,
        'comment': comment or '',
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(new_data),
    })

    return {
        'ok': True,
        'old_size': len(data),
        'new_size': len(new_data),
        'backup_path': backup_path,
        'verify_pass': True,
        'history_id': stamp,
    }


def edit_script_commands(filename: str, group_idx: int, obj_idx: int, proc_tag: str,
                          start_idx: int, end_idx: int, commands: list, comment: str = '') -> dict:
    """Replace commands [start_idx, end_idx) in the given procedure with
    `commands` (list of {'indent', 'opcode', 'params'} dicts, possibly
    empty for deletion) using splice_procedure.replace_commands(), then
    write the result back to the SCRIPT file - covers the viewer's
    edit/insert/delete-command UI in one shared code path. Always backs
    up the pre-edit file first (timestamped, so a run of many small
    edits in one debugging session never loses an earlier state) and
    runs verify_script_structure's checks on the result before
    accepting it, matching this session's established safe-editing
    workflow (see docs/party_add_remove_command_investigation.md).

    Also appends a record to the change-history log (see
    _append_history/_read_history) with the user-supplied `comment`, a
    before/after summary of the affected commands, and a spot for a
    result_comment to be added later (e.g. after an on-device test) via
    add_history_comment() - this is what the viewer's 履歴 panel reads.
    """
    if not filename or '/' in filename or '\\' in filename:
        raise ValueError('invalid filename')
    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    if not os.path.isfile(path):
        raise ValueError('file not found')

    with open(path, 'rb') as f:
        data = f.read()

    before_tree = build_tree(filename)
    before_commands = _find_procedure_commands(before_tree, group_idx, obj_idx, proc_tag)
    before_summary = _summarize_commands(before_commands[start_idx:end_idx])

    new_indent_bytes = bytes(int(c['indent']) for c in commands)
    parts = []
    offsets = []
    cursor = 0
    for c in commands:
        offsets.append(cursor)
        raw = _encode_command(c)
        parts.append(raw)
        cursor += len(raw)
    new_block3_bytes = b''.join(parts)

    new_data = sp.replace_commands(
        data, group_idx=group_idx, obj_idx=obj_idx, proc_tag=proc_tag,
        start_idx=start_idx, end_idx=end_idx,
        new_indent_bytes=new_indent_bytes, new_block3_bytes=new_block3_bytes,
        new_cmd_offsets=offsets,
    )

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)

    with open(path, 'wb') as f:
        f.write(new_data)

    # verify_script_structure.py's build_tree imports this very module
    # (server.py) - importing it lazily here (not at module load time)
    # avoids a circular-import problem, since by the time this function
    # runs, server.py is already fully loaded and sys.modules['server']
    # (or __main__, depending on how this was launched) resolves fine.
    import importlib.util
    verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
    spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    tree = verify_mod.build_tree(filename)
    anomalies: list = []
    verify_mod.check_commands(tree, anomalies)
    verify_mod.check_block_alignment(filename, anomalies)
    verify_mod.check_hierarchy(tree, len(new_data), anomalies)

    if anomalies:
        # never leave a structurally-broken file on disk - the backup we
        # just took is the pre-edit state, so restore it immediately.
        with open(path, 'wb') as f:
            f.write(data)
        return {
            'ok': False,
            'error': 'verify failed - edit was rejected and the file was restored to its pre-edit state',
            'anomalies': anomalies,
            'backup_path': backup_path,
        }

    after_commands = _find_procedure_commands(tree, group_idx, obj_idx, proc_tag)
    after_summary = _summarize_commands(after_commands[start_idx:start_idx + len(commands)])
    op = 'delete' if not commands else ('insert' if start_idx == end_idx else 'edit')

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'group_idx': group_idx, 'obj_idx': obj_idx, 'proc_tag': proc_tag,
        'start_idx': start_idx, 'end_idx': end_idx,
        'op': op,
        'before': before_summary,
        'after': after_summary,
        'comment': comment or '',
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(new_data),
    })

    return {
        'ok': True,
        'old_size': len(data),
        'new_size': len(new_data),
        'backup_path': backup_path,
        'verify_pass': True,
        'history_id': stamp,
    }


def preview_edit_script_commands(data: bytes, group_idx: int, obj_idx: int, proc_tag: str,
                                  start_idx: int, end_idx: int, commands: list) -> dict:
    """Same core splice as edit_script_commands, but pure: takes raw bytes
    instead of a filename, and never touches the real SCRIPT file, the
    backup dir, or the change-history log. Backs the viewer's "staged
    changes" editing flow (POST /api/script/edit_preview) - the user can
    make several edits in a row that only exist in the browser's own
    working buffer (see save() in app.js), re-rendering the tree from
    the preview result each time, and only actually write to disk (via
    a sequence of real edit_script_commands calls, replayed in the same
    order so history stays fully granular) when they click 保存. This
    was added (2026-08-25) because saving - and the resulting full tree
    reload - on every single micro-edit made multi-step edits tedious
    and kept collapsing the tree's expand/collapse state.

    Structural verification still runs here (via a short-lived temp
    file in _SCRIPT_FILES_DIR, since verify_script_structure.py's checks
    are filename-based, not bytes-based - see its module docstring), so
    a broken edit is rejected immediately during staging rather than
    only surfacing at final save time.
    """
    new_indent_bytes = bytes(int(c['indent']) for c in commands)
    parts = []
    offsets = []
    cursor = 0
    for c in commands:
        offsets.append(cursor)
        raw = _encode_command(c)
        parts.append(raw)
        cursor += len(raw)
    new_block3_bytes = b''.join(parts)

    new_data = sp.replace_commands(
        data, group_idx=group_idx, obj_idx=obj_idx, proc_tag=proc_tag,
        start_idx=start_idx, end_idx=end_idx,
        new_indent_bytes=new_indent_bytes, new_block3_bytes=new_block3_bytes,
        new_cmd_offsets=offsets,
    )

    # not ".bin" so it never shows up in list_script_files()'s dropdown,
    # even if a request landed mid-write (ThreadingHTTPServer).
    tmp_name = f'.previewtmp_{os.getpid()}_{threading.get_ident()}.previewtmp'
    tmp_path = os.path.join(_SCRIPT_FILES_DIR, tmp_name)
    try:
        with open(tmp_path, 'wb') as f:
            f.write(new_data)

        import importlib.util
        verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
        spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
        verify_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify_mod)

        tree = verify_mod.build_tree(tmp_name)
        anomalies: list = []
        verify_mod.check_commands(tree, anomalies)
        verify_mod.check_block_alignment(tmp_name, anomalies)
        verify_mod.check_hierarchy(tree, len(new_data), anomalies)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    if anomalies:
        return {'ok': False, 'error': 'verify failed', 'anomalies': anomalies}

    return {'ok': True, 'data': new_data, 'tree': tree}


def commit_batch_edits(filename: str, new_data: bytes, ops: list, comment: str = '') -> dict:
    """Write the fully-staged result of a sequence of preview_edit_script_commands()
    calls to the real SCRIPT file in ONE disk write, and record ONE
    change-history entry covering the whole batch (per user request,
    2026-08-26: staging several edits before saving should leave a
    single history entry, not one per staged op - the earlier "replay
    each op through edit_script_commands" approach kept full per-op
    granularity but cluttered the log).

    `ops` is the client's pendingEdits list - each already carries its
    own before/after command summaries (computed client-side from the
    tree snapshots at staging time, in app.js:stageEdit - see
    _summarize_commands for the shape) and per-op comment, which are
    preserved inside this one entry's `ops` field so the 履歴 panel can
    still show what individual operations were included.
    """
    if not filename or '/' in filename or '\\' in filename:
        raise ValueError('invalid filename')
    path = os.path.join(_SCRIPT_FILES_DIR, filename)
    if not os.path.isfile(path):
        raise ValueError('file not found')

    with open(path, 'rb') as f:
        data = f.read()

    os.makedirs(_SCRIPT_EDIT_BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_path = os.path.join(_SCRIPT_EDIT_BACKUP_DIR, f'{filename}.{stamp}.bak')
    with open(backup_path, 'wb') as f:
        f.write(data)

    with open(path, 'wb') as f:
        f.write(new_data)

    import importlib.util
    verify_mod_path = os.path.join(_SCRIPT_DIR, 'verify_script_structure.py')
    spec = importlib.util.spec_from_file_location('verify_script_structure', verify_mod_path)
    verify_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify_mod)

    tree = verify_mod.build_tree(filename)
    anomalies: list = []
    verify_mod.check_commands(tree, anomalies)
    verify_mod.check_block_alignment(filename, anomalies)
    verify_mod.check_hierarchy(tree, len(new_data), anomalies)

    if anomalies:
        with open(path, 'wb') as f:
            f.write(data)
        return {
            'ok': False,
            'error': 'verify failed - batch was rejected and the file was restored to its pre-batch state',
            'anomalies': anomalies,
            'backup_path': backup_path,
        }

    combined_comment = comment or '; '.join(o.get('comment') or '' for o in ops if o.get('comment'))

    _append_history({
        'id': stamp,
        'timestamp': datetime.datetime.now().isoformat(timespec='seconds'),
        'file': filename,
        'op': 'batch',
        'ops': ops,
        'comment': combined_comment,
        'result_comment': None,
        'backup_path': backup_path,
        'old_size': len(data),
        'new_size': len(new_data),
    })

    return {
        'ok': True,
        'old_size': len(data),
        'new_size': len(new_data),
        'backup_path': backup_path,
        'verify_pass': True,
        'history_id': stamp,
    }


# ---------------------------------------------------------------------------
# CIA repack + deploy - see docs/repack_and_test_workflow.md. This is the
# same repack -> verify -> copy-to-Downloads sequence run by hand many
# times this session, wired up as a button so edits made in the viewer
# can go straight to an installable CIA without a separate terminal step
# (per CLAUDE.md: this workflow is Claude's job to run through to
# completion, and now the user's too via this endpoint).

_REPACK_TITLE_ID_MARKER = '0004000000065E00'  # DQ7's 3DS title ID, used to
# pick out the original CIA from rom/ (which also accumulates repack
# test outputs) without hardcoding a full filename.
_REPACK_OUTPUT = os.path.join(_ROM_DIR, 'webapp_repack_output.cia')
_DOWNLOADS_DIR = os.path.expanduser('~/storage/downloads/dq7')
_DOWNLOADS_TARGET = os.path.join(_DOWNLOADS_DIR, 'game_test.cia')
# 【確定 2026-10-04】cia_repack.py自体はこのリポジトリに同梱されていない
# (公開物ではなくROM/CIAを扱うビルドツールのため)。このビューアを、
# DQ7_ROM_DIRで実際のROMデータを指す別のチェックアウトから起動している
# 場合、cia_repack.pyはこのビューアのルート(_ROOT)ではなく、そのROMデータ
# が置かれているリポジトリの直下にある。_ROOTに見つからない場合は
# DQ7_ROM_DIRの親ディレクトリも探す(見つからなければ元の_ROOT基準の
# パスのままにしておき、エラーメッセージで気づけるようにする)。
def _resolve_cia_repack_script() -> str:
    candidate = os.path.join(_ROOT, 'cia_repack.py')
    if os.path.isfile(candidate):
        return candidate
    rom_dir_env = os.environ.get('DQ7_ROM_DIR')
    if rom_dir_env:
        alt = os.path.join(os.path.dirname(os.path.abspath(rom_dir_env)), 'cia_repack.py')
        if os.path.isfile(alt):
            return alt
    return candidate


_CIA_REPACK_SCRIPT = _resolve_cia_repack_script()


def _find_original_cia() -> str:
    rom_dir = _ROM_DIR
    for name in sorted(os.listdir(rom_dir)):
        if name.endswith('.cia') and _REPACK_TITLE_ID_MARKER in name:
            return name
    raise FileNotFoundError(
        f"original CIA not found in rom/ (expected a .cia filename containing '{_REPACK_TITLE_ID_MARKER}')")


def repack_and_deploy() -> dict:
    """Repack rom/extracted/ into a CIA, verify it, and copy it to the
    fixed Downloads path - subprocess-based (not an in-process import of
    cia_repack.py) so this HTTP server's cwd never has to change, which
    would be unsafe under ThreadingHTTPServer's concurrent requests.
    Always writes to the SAME output filename (rom/webapp_repack_output.cia)
    rather than a fresh name per call - each output is ~1.4GB, and this
    project's own convention (see docs/repack_and_test_workflow.md) is a
    fixed, overwritten filename precisely to avoid accumulating multiple
    GB of redundant build artifacts every time this runs.
    """
    if not os.path.isdir(_ROMFS_DIR):
        raise FileNotFoundError(f'{_ROMFS_DIR} not found - extract the RomFS first')

    original_cia_name = _find_original_cia()
    entries = sorted(e for e in os.listdir(_ROMFS_DIR) if not e.startswith('.'))

    def run(args, timeout):
        return subprocess.run(
            ['python3', _CIA_REPACK_SCRIPT, *args],
            cwd=_ROMFS_DIR, capture_output=True, text=True, timeout=timeout,
        )

    original_cia_rel = os.path.join('..', original_cia_name)
    output_rel = os.path.join('..', os.path.basename(_REPACK_OUTPUT))

    repack_proc = run(['repack', original_cia_rel, output_rel, *entries], timeout=900)
    if repack_proc.returncode != 0:
        return {
            'ok': False, 'stage': 'repack',
            'stdout': repack_proc.stdout, 'stderr': repack_proc.stderr,
        }

    verify_proc = run(['verify', output_rel, *entries], timeout=300)
    if verify_proc.returncode != 0 or 'VERIFY PASS' not in verify_proc.stdout:
        return {
            'ok': False, 'stage': 'verify',
            'stdout': repack_proc.stdout + '\n' + verify_proc.stdout,
            'stderr': verify_proc.stderr,
        }

    os.makedirs(_DOWNLOADS_DIR, exist_ok=True)
    shutil.copyfile(_REPACK_OUTPUT, _DOWNLOADS_TARGET)

    return {
        'ok': True,
        'stdout': repack_proc.stdout + '\n' + verify_proc.stdout,
        'target': _DOWNLOADS_TARGET,
        'size': os.path.getsize(_DOWNLOADS_TARGET),
    }


# ---------------------------------------------------------------------------
# HTTP server

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=_STATIC_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # This static content (app.js/style.css/index.html) gets edited and
        # the server restarted constantly during development - without this,
        # browsers can keep serving a stale cached JS file after a restart
        # (SimpleHTTPRequestHandler sends Last-Modified/conditional-GET
        # headers by default, which is exactly the caching behavior that
        # causes it), silently making newly-added buttons/features look
        # broken. Local single-user dev tool, so unconditionally disabling
        # caching has no real downside.
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html_with_asset_version(self, url_path: str) -> bool:
        """Serve an .html file (or '/' -> index.html) with ?v=_ASSET_VERSION
        appended to every local <script src> / <link href>, so each server
        restart forces browsers to fetch fresh JS/CSS even if they'd
        otherwise reuse a cached copy without ever contacting the server
        (heuristic freshness - the Cache-Control header in end_headers()
        only helps once a request actually reaches us). Returns False (and
        does nothing) for anything that isn't a real file under
        _STATIC_DIR, so the caller can fall through to normal handling
        (e.g. a 404) for bad paths.
        """
        name = 'index.html' if url_path in ('/', '') else os.path.basename(url_path)
        full = os.path.join(_STATIC_DIR, name)
        if not os.path.isfile(full):
            return False
        with open(full, encoding='utf-8') as f:
            html = f.read()

        def add_version(m):
            attr, url = m.group(1), m.group(2)
            if '://' in url or url.startswith('//'):
                return m.group(0)
            sep = '&' if '?' in url else '?'
            return f'{attr}="{url}{sep}v={_ASSET_VERSION}"'

        html = re.sub(r'(src|href)="([^"]+\.(?:js|css))"', add_version, html)
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path in ('/', '') or parsed.path.endswith('.html'):
            served = self._serve_html_with_asset_version(parsed.path)
            if served:
                return

        if parsed.path == '/api/files':
            self._send_json(list_script_files())
            return

        if parsed.path == '/api/search_text':
            query = (qs.get('q') or [''])[0]
            try:
                result = search_message_text(query)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/parse':
            filename = (qs.get('file') or [''])[0]
            if not filename or '/' in filename or '\\' in filename:
                self._send_json({'error': 'invalid file'}, status=400)
                return
            full = os.path.join(_SCRIPT_FILES_DIR, filename)
            if not os.path.isfile(full):
                self._send_json({'error': 'not found'}, status=404)
                return
            try:
                tree = build_tree(filename)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(tree)
            return

        if parsed.path == '/api/script/raw':
            filename = (qs.get('file') or [''])[0]
            if not filename or '/' in filename or '\\' in filename:
                self._send_json({'error': 'invalid file'}, status=400)
                return
            full = os.path.join(_SCRIPT_FILES_DIR, filename)
            if not os.path.isfile(full):
                self._send_json({'error': 'not found'}, status=404)
                return
            with open(full, 'rb') as f:
                data = f.read()
            self._send_json({'data_b64': base64.b64encode(data).decode('ascii')})
            return

        if parsed.path == '/api/fpt_files':
            self._send_json(list_fpt_files())
            return

        if parsed.path == '/api/fpt_parse':
            filename = (qs.get('file') or [''])[0]
            if not filename or '/' in filename or '\\' in filename:
                self._send_json({'error': 'invalid file'}, status=400)
                return
            full = os.path.join(_MESS_DIR, filename)
            if not os.path.isfile(full):
                self._send_json({'error': 'not found'}, status=404)
                return
            try:
                result = parse_fpt_full(filename)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/model_files':
            self._send_json(list_model_files())
            return

        if parsed.path == '/api/model':
            rel = (qs.get('file') or [''])[0]
            try:
                self._send_json(parse_model_file(rel))
            except FileNotFoundError:
                self._send_json({'error': 'not found'}, status=404)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
            return

        if parsed.path == '/api/img/tree':
            try:
                self._send_json(imagebrowser.build_tree())
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
            return

        if parsed.path == '/api/img/list':
            p = (qs.get('path') or [''])[0]
            try:
                self._send_json(imagebrowser.list_images(p))
            except FileNotFoundError:
                self._send_json({'error': 'not found'}, status=404)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
            return

        if parsed.path == '/api/img/png':
            p = (qs.get('path') or [''])[0]
            name = (qs.get('name') or [''])[0]
            try:
                png = imagebrowser.image_png(p, name)
            except FileNotFoundError:
                self._send_json({'error': 'not found'}, status=404)
                return
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
                return
            if not png:
                self._send_json({'error': 'not decodable'}, status=404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return

        if parsed.path == '/api/model/texture':
            rel = (qs.get('file') or [''])[0]
            name = (qs.get('name') or [''])[0]
            try:
                png = model_texture_png(rel, name)
            except FileNotFoundError:
                self._send_json({'error': 'not found'}, status=404)
                return
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
                return
            if not png:
                self._send_json({'error': 'texture not decodable'}, status=404)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'image/png')
            self.send_header('Content-Length', str(len(png)))
            self.end_headers()
            self.wfile.write(png)
            return

        if parsed.path == '/api/model/anim':
            rel = (qs.get('file') or [''])[0]
            name = (qs.get('name') or [''])[0]
            try:
                self._send_json(model_animation(rel, name))
            except FileNotFoundError:
                self._send_json({'error': 'not found'}, status=404)
            except KeyError:
                self._send_json({'error': 'clip not found'}, status=404)
            except ValueError as e:
                self._send_json({'error': str(e)}, status=400)
            except Exception as e:
                self._send_json({'error': f'{type(e).__name__}: {e}'}, status=500)
            return

        if parsed.path == '/api/floor_list':
            try:
                self._send_json(floor_list_overview())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/floor_detail':
            try:
                fid = int((qs.get('id') or ['0'])[0])
            except ValueError:
                self._send_json({'error': 'invalid id'}, status=400)
                return
            try:
                self._send_json(floor_detail(fid))
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/encount_data':
            try:
                self._send_json(parse_encount_data())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/item_list':
            try:
                self._send_json(parse_item_list())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/action_param':
            try:
                self._send_json(parse_action_param())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/action_type':
            try:
                self._send_json(parse_action_type())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/player_stats':
            try:
                self._send_json(parse_player_stats())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/character_init_data':
            try:
                self._send_json(parse_character_init_data())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/chara_list':
            try:
                self._send_json(parse_chara_list())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/person_jidx':
            try:
                self._send_json(parse_person_jidx())
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
            return

        if parsed.path == '/api/text':
            try:
                msgid = int((qs.get('id') or ['0'])[0])
            except ValueError:
                self._send_json({'error': 'invalid id'}, status=400)
                return
            self._send_json({'id': msgid, 'text': resolve_message(msgid)})
            return

        if parsed.path == '/api/keifa_probe/status':
            try:
                result = rpc_probe.status()
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/keifa_probe/log':
            try:
                result = rpc_probe.log()
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/save/load':
            path = (qs.get('path') or [''])[0]
            device = int((qs.get('device') or ['0'])[0])
            if not path:
                self._send_json({'error': 'missing path'}, status=400)
                return
            if not os.path.isfile(path):
                self._send_json({'error': 'not found'}, status=404)
                return
            try:
                result = save_editor.read_save(path, device_type=device)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/browse':
            requested = (qs.get('path') or [''])[0]
            try:
                result = browse_dir(requested)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/script/history':
            filename = (qs.get('file') or [None])[0]
            try:
                result = _read_history(filename)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/api/keifa_probe/apply':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8')) if body.strip() else {}
            except Exception:
                payload = {}
            try:
                result = rpc_probe.apply(force_rescan=bool(payload.get('force_rescan')))
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/edit':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = edit_script_commands(
                    filename=payload['file'],
                    group_idx=int(payload['group_idx']),
                    obj_idx=int(payload['obj_idx']),
                    proc_tag=payload['proc_tag'],
                    start_idx=int(payload['start_idx']),
                    end_idx=int(payload['end_idx']),
                    commands=payload.get('commands', []),
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/npc_field/edit':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = edit_npc_placement_field(
                    filename=payload['file'],
                    group_idx=int(payload['group_idx']),
                    obj_idx=int(payload['obj_idx']),
                    field_offset=int(payload['field_offset']),
                    value_type=payload['value_type'],
                    value=payload['value'],
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/character_init_data/edit':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = edit_character_init_field(
                    index=int(payload['index']),
                    field=payload['field'],
                    value=payload['value'],
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/object/add':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            field_overrides = None
            if payload.get('field_overrides'):
                field_overrides = {
                    int(k): (v['type'], v['value'])
                    for k, v in payload['field_overrides'].items()
                }
            try:
                result = copy_script_object(
                    dst_filename=payload['dst_file'],
                    target_group_idx=int(payload['target_group_idx']),
                    src_filename=payload.get('src_file') or payload['dst_file'],
                    src_group_idx=int(payload['src_group_idx']),
                    src_obj_idx=int(payload['src_obj_idx']),
                    new_tag=payload.get('new_tag') or None,
                    field_overrides=field_overrides,
                    at_index=int(payload['at_index']) if payload.get('at_index') not in (None, '') else None,
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/object/delete':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = delete_script_object(
                    dst_filename=payload['dst_file'],
                    target_group_idx=int(payload['target_group_idx']),
                    target_obj_idx=int(payload['target_obj_idx']),
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/object/replace':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            field_overrides = None
            if payload.get('field_overrides'):
                field_overrides = {
                    int(k): (v['type'], v['value'])
                    for k, v in payload['field_overrides'].items()
                }
            try:
                result = overwrite_script_object(
                    dst_filename=payload['dst_file'],
                    target_group_idx=int(payload['target_group_idx']),
                    target_obj_idx=int(payload['target_obj_idx']),
                    src_filename=payload.get('src_file') or payload['dst_file'],
                    src_group_idx=int(payload['src_group_idx']),
                    src_obj_idx=int(payload['src_obj_idx']),
                    new_tag=payload.get('new_tag') or None,
                    field_overrides=field_overrides,
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/edit_preview':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
                data = base64.b64decode(payload['data_b64'])
            except Exception:
                self._send_json({'error': 'invalid request body'}, status=400)
                return
            try:
                result = preview_edit_script_commands(
                    data,
                    group_idx=int(payload['group_idx']),
                    obj_idx=int(payload['obj_idx']),
                    proc_tag=payload['proc_tag'],
                    start_idx=int(payload['start_idx']),
                    end_idx=int(payload['end_idx']),
                    commands=payload.get('commands', []),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            if not result.get('ok'):
                self._send_json(result, status=409)
                return
            self._send_json({
                'ok': True,
                'data_b64': base64.b64encode(result['data']).decode('ascii'),
                'tree': result['tree'],
            })
            return

        if parsed.path == '/api/script/commit_batch':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
                new_data = base64.b64decode(payload['data_b64'])
            except Exception:
                self._send_json({'error': 'invalid request body'}, status=400)
                return
            try:
                result = commit_batch_edits(
                    filename=payload['file'],
                    new_data=new_data,
                    ops=payload.get('ops', []),
                    comment=payload.get('comment', ''),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/history/comment':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = add_history_comment(
                    payload['entry_id'],
                    comment=payload.get('comment'),
                    result_comment=payload.get('result_comment'),
                )
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/script/history/revert_op':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = revert_entry_as_new_change(payload['file'], payload['entry_id'])
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 409)
            return

        if parsed.path == '/api/script/history/revert':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            try:
                result = revert_to_history_entry(payload['entry_id'])
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/repack':
            try:
                result = repack_and_deploy()
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result, status=200 if result.get('ok') else 500)
            return

        if parsed.path == '/api/save/write':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except Exception:
                self._send_json({'error': 'invalid JSON body'}, status=400)
                return
            path = payload.get('path')
            device = int(payload.get('device_type', 0))
            if not path or not os.path.isfile(path):
                self._send_json({'error': 'not found'}, status=404)
                return
            try:
                result = save_editor.write_save(path, device, payload)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/save/parse_upload':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
                data = base64.b64decode(payload['data_b64'])
                device = int(payload.get('device_type', 0))
            except Exception:
                self._send_json({'error': 'invalid request body'}, status=400)
                return
            try:
                result = save_editor.parse_buffer(data, device_type=device)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self._send_json(result)
            return

        if parsed.path == '/api/save/build_download':
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
                data = base64.b64decode(payload['data_b64'])
                device = int(payload.get('device_type', 0))
            except Exception:
                self._send_json({'error': 'invalid request body'}, status=400)
                return
            try:
                new_bytes = save_editor.apply_patch(data, device, payload)
            except Exception as e:
                self._send_json({'error': str(e)}, status=500)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', 'attachment; filename="save_edited.bin"')
            self.send_header('Content-Length', str(len(new_bytes)))
            self.end_headers()
            self.wfile.write(new_bytes)
            return

        self._send_json({'error': 'not found'}, status=404)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()

    if not os.path.isdir(_SCRIPT_FILES_DIR):
        print(f"Warning: {_SCRIPT_FILES_DIR} not found - extract the RomFS first "
              f"(see docs/repack_and_test_workflow.md).")

    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving on http://{args.host}:{args.port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
