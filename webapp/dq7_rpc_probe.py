"""
Azahar(Citra系)のRPCサーバー(UDP:45987, core/rpc/配下、config.iniの
`enable_rpc_server=true`で有効化)経由で、実機/エミュレータ実行中のDQ7プロセスの
メモリを直接読み書きするための最小クライアント + キーファ転職アニメ調査用の
「コードケイブ・プローブ」実装。

背景・経緯は docs/keifa_job_animation_investigation.md を参照。要点:

- Azahar Android版はGDBスタブが無効(Qtビルド限定、azahar-emu/azahar#2086)。
  代わりにRPCサーバー(UDP、ReadMemory/WriteMemory/ProcessList/SetGetProcess の
  4コマンドのみ、ブレークポイント無し)経由でメモリの生読み書きだけができる。
- ブレークポイントが無いため、「ある命令が実行された瞬間のレジスタ値」を
  観測するには、その命令をコードケイブへのジャンプに書き換え、コードケイブ側で
  元の命令を再現しつつレジスタの値をメモリ(リングバッファ)に書き残してから
  元の処理に戻る、という「非破壊的プローブ」パッチをライブメモリに直接
  書き込む必要がある(ロジックは変更しない、副作用として記録するだけ)。

- 【重要な教訓】この用途でアドレスをROM上のファイルオフセットから計算するのは
  信頼できない。ユーザーが過去に作成した実験用パッチ入りCIAが動いているケースが
  あり、そのビルドでは対象関数がベース/1.10アップデートいずれとも異なる位置に
  ずれていた(実測: 想定より+0xE74)。**このモジュールは起動のたびにライブメモリを
  直接スキャンして対象命令列を再特定してからパッチを当てる**設計にしている
  (固定アドレスへの決め打ちはしない)。

対象命令(CharacterObject::getMotionIndexのカテゴリ0x3000000分岐、
docs/keifa_job_animation_investigation.md の「本丸は...0x263b0」節参照):

    ldr r1, [r4, 0x90]!
    mov r2, r6
    ldr r3, [r4, 8]        ; ★ r3 = *(orig_this + 0x98) = "characterキー"
    add sp, sp, 4
    pop {r4, r5, r6, r7, lr}
    b   <job×character×motionType 3段探索関数>

この20byte(最後の`ldr r3,[r4,8]`まで)は呼び出し元のインライン展開部分で、
呼び出し先固有の命令列とは独立して常に同じバイト列で現れる。この直後の
`b`命令の飛び先が「job×character×motionType 3段探索関数」の目印
(`push {r4,r5,r6,r7,r8,sb,sl,fp,ip,lr}; mov r4,r2; mov r8,r0; ...`)で
始まっているかを確認することで、誤検出(同じ20byteパターンを再利用する
無関係な別関数)を排除している。

【2026-09-22実機結果・重要】この位置をフックして得た`[this+0x98]`の値は、
操作キャラ(隊列の先頭)を入れ替えても同じ値(`this`ポインタ・値とも不変)
だった。つまりこの経路の`this`は「操作中スロット」用に使い回される固定の
静的オブジェクトで、`+0x98`はキャラ識別子ではなく別の意味(役割タグ?)を
持つ可能性が高い、という新しい未解決の謎が浮上している。詳細は
docs/keifa_job_animation_investigation.md 参照。
"""

from __future__ import annotations

import itertools
import socket
import struct
import threading
import time

HOST = "127.0.0.1"
PORT = 45987

# --- RPCプロトコル定数 (core/rpc/packet.h) ---
_PKT_READ = 1
_PKT_WRITE = 2
_PKT_PROCESS_LIST = 3
_PKT_SET_GET_PROCESS = 4
_MAX_READ = 1024

_id_counter = itertools.count(1)
_id_lock = threading.Lock()


def _next_id() -> int:
    with _id_lock:
        return next(_id_counter) & 0xFFFFFFFF


class RPCError(Exception):
    pass


def _rpc(packet_type: int, arg1: int, arg2: int, extra: bytes = b"", timeout: float = 1.5, retries: int = 4) -> bytes:
    """1リクエスト送って対応するreply(id一致)を待つ。無関係な遅延reply
    (別リクエストの取り違え)は捨てて待ち続ける。screen off/バックグラウンド化で
    エミュレータ側が応答を止めることがあるため、タイムアウトしたら短いidで
    再送する。"""
    last_err: Exception | None = None
    for _ in range(retries):
        req_id = _next_id()
        payload = struct.pack("<II", arg1, arg2) + extra
        header = struct.pack("<IIII", 1, req_id, packet_type, len(payload))
        pkt = header + payload
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        try:
            s.sendto(pkt, (HOST, PORT))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    data, _addr = s.recvfrom(2048)
                except socket.timeout:
                    break
                if len(data) < 16:
                    continue
                _rver, rid, rtype, rsize = struct.unpack("<IIII", data[:16])
                if rid == req_id and rtype == packet_type:
                    return data[16:16 + rsize]
                # 別リクエスト宛の遅延replyなので無視して待ち続ける
        except OSError as e:
            last_err = e
        finally:
            s.close()
    raise RPCError(f"RPC timeout (type={packet_type} addr={hex(arg1)})") from last_err


def read_memory(addr: int, size: int) -> bytes:
    out = bytearray()
    off = 0
    while off < size:
        chunk = min(_MAX_READ, size - off)
        out += _rpc(_PKT_READ, addr + off, chunk)
        off += chunk
    return bytes(out)


def write_memory(addr: int, data: bytes) -> None:
    # WriteMemoryは1回のパケットでMAX_PACKET_DATA_SIZE(1024)-8byte以下という
    # 制約があるが、このモジュールが書くコードケイブは高々数百byteなので
    # 分割せず1回で送る前提(呼び出し側で大きすぎるデータを渡さないこと)。
    if len(data) > 900:
        raise RPCError("write_memory: payload too large for a single RPC packet")
    _rpc(_PKT_WRITE, addr, len(data), extra=data)


def process_list() -> list[dict]:
    raw = _rpc(_PKT_PROCESS_LIST, 0, 16)
    if len(raw) < 4:
        return []
    (count,) = struct.unpack_from("<I", raw, 0)
    out = []
    off = 4
    for _ in range(count):
        pid, title_id = struct.unpack_from("<IQ", raw, off)
        name = raw[off + 12:off + 20].split(b"\x00", 1)[0].decode("ascii", "replace")
        out.append({"process_id": pid, "title_id": title_id, "process_name": name})
        off += 0x14
    return out


def select_process(pid: int) -> None:
    _rpc(_PKT_SET_GET_PROCESS, 1, pid)


def ping(timeout: float = 1.0) -> bool:
    try:
        _rpc(_PKT_PROCESS_LIST, 0, 1, timeout=timeout, retries=1)
        return True
    except RPCError:
        return False


def ensure_process_selected() -> dict | None:
    """CtrApp(DQ7)プロセスを探してSetGetProcessする。見つかった情報を返す。"""
    procs = process_list()
    for p in procs:
        if p["process_name"].startswith("CtrApp"):
            select_process(p["process_id"])
            return p
    return None


# ---------------------------------------------------------------------------
# ARM32命令エンコーダ(最小限、このプローブが使う命令だけ)
# ---------------------------------------------------------------------------

def _enc_dp_imm(cond: int, opcode: int, S: int, Rn: int, Rd: int, imm: int, rot: int = 0) -> int:
    return (cond << 28) | (1 << 25) | (opcode << 21) | (S << 20) | (Rn << 16) | (Rd << 12) | (rot << 8) | (imm & 0xFF)


def _enc_dp_reg_shift_imm(cond: int, opcode: int, S: int, Rn: int, Rd: int, Rm: int, shift_amt: int, shift_type: int = 0b00) -> int:
    return (cond << 28) | (opcode << 21) | (S << 20) | (Rn << 16) | (Rd << 12) | (shift_amt << 7) | (shift_type << 5) | Rm


def _enc_ls_imm(cond: int, P: int, U: int, B: int, W: int, L: int, Rn: int, Rd: int, imm12: int) -> int:
    return (cond << 28) | (0b01 << 26) | (P << 24) | (U << 23) | (B << 22) | (W << 21) | (L << 20) | (Rn << 16) | (Rd << 12) | (imm12 & 0xFFF)


def _enc_b(cond: int, from_addr: int, to_addr: int, link: int = 0) -> int:
    offset = to_addr - (from_addr + 8)
    if offset % 4 != 0:
        raise RPCError("branch offset not 4-byte aligned")
    imm24 = (offset // 4) & 0xFFFFFF
    return (cond << 28) | (0b101 << 25) | (link << 24) | imm24


def _w(word: int) -> bytes:
    return struct.pack("<I", word & 0xFFFFFFFF)


# ---------------------------------------------------------------------------
# 対象パターンの定義
# ---------------------------------------------------------------------------

# 呼び出し元(CharacterObject::getMotionIndex カテゴリ0x3000000分岐)の
# 不変20byte: ldr r1,[r4,0x90]! ; mov r2,r6 ; ldr r3,[r4,8](★上書き対象)
# ; add sp,sp,4 ; pop {r4,r5,r6,r7,lr}
_CALLER_SUFFIX = bytes.fromhex("9010b4e50620a0e1083094e504d08de2f040bde8")
_INJECT_REL_OFFSET = 8  # _CALLER_SUFFIXの先頭から「ldr r3,[r4,8]」までのoffset
ORIG_INSTR = bytes.fromhex("083094e5")  # ldr r3,[r4,8]

# 呼び出し先(job×character×motionType 3段探索関数)の目印36byte
_CALLEE_PROLOGUE = bytes.fromhex(
    "f05f2de9"  # push {r4,r5,r6,r7,r8,sb,sl,fp,ip,lr}
    "0240a0e1"  # mov r4, r2
    "0080a0e1"  # mov r8, r0
    "0190a0e1"  # mov sb, r1
    "0370a0e1"  # mov r7, r3
    "040090e5"  # ldr r0, [r0, 4]
    "0660a0e3"  # mov r6, 6
    "0450a0e3"  # mov r5, 4
    "000050e3"  # cmp r0, 0
)

RING_SIZE = 16
RING_ENTRY_SIZE = 16   # this(u32) + charkey(u32) + seq(u32) + reserved(u32)
CODECAVE_SIZE = 0x54 + 8 + RING_SIZE * RING_ENTRY_SIZE  # code+literals+header+ring


def _decode_branch_target(instr: bytes, instr_addr: int) -> int | None:
    if len(instr) != 4 or (instr[3] & 0x0F) != 0x0A:
        return None  # not an unconditional 'b' (cond=AL=0xE, top nibble of byte3=0xA)
    (word,) = struct.unpack("<I", instr)
    imm24 = word & 0xFFFFFF
    if imm24 & 0x800000:
        imm24 -= 0x1000000
    return instr_addr + 8 + (imm24 << 2)


def find_injection_site(dump: bytes, dump_base_vaddr: int) -> dict | None:
    """dump(dump_base_vaddrから読み出したメモリの生バイト列)の中から、
    ldr r3,[r4,8]の実際の場所と、その呼び出し先(3段探索関数)のアドレスを
    特定する。呼び出し先のプロローグまで確認して誤検出を排除する。"""
    idx = 0
    while True:
        idx = dump.find(_CALLER_SUFFIX, idx)
        if idx < 0:
            return None
        branch_off = idx + len(_CALLER_SUFFIX)
        branch_bytes = dump[branch_off:branch_off + 4]
        branch_addr = dump_base_vaddr + branch_off
        target = _decode_branch_target(branch_bytes, branch_addr)
        if target is not None:
            target_off = target - dump_base_vaddr
            if 0 <= target_off and dump[target_off:target_off + len(_CALLEE_PROLOGUE)] == _CALLEE_PROLOGUE:
                inject_addr = dump_base_vaddr + idx + _INJECT_REL_OFFSET
                return {
                    "inject_addr": inject_addr,
                    "return_addr": inject_addr + 4,
                    "callee_addr": target,
                }
        idx += 1


def find_codecave(dump: bytes, dump_base_vaddr: int, min_size: int, search_from_off: int = 0) -> int | None:
    """dump内で min_size byte連続でゼロの領域を探し、その先頭のvaddrを返す。
    NCCH ExHeaderのページアラインパディング(.textと.rodataの間)を狙う想定
    (docs/keifa_job_animation_investigation.md の既存コードケイブと同じ発想)。"""
    zero_run = 0
    for i in range(search_from_off, len(dump)):
        if dump[i] == 0:
            zero_run += 1
            if zero_run >= min_size:
                return dump_base_vaddr + (i - min_size + 1)
        else:
            zero_run = 0
    return None


def build_probe_patch(inject_addr: int, return_addr: int, codecave_addr: int) -> tuple[bytes, bytes]:
    """(codecave_bytes, trampoline_bytes) を返す。挙動は元の`ldr r3,[r4,8]`と
    完全に等価(同じr0-r3を呼び出し先に渡す)なまま、副作用として
    リングバッファに {this, characterキー, seq} を書き残す。

    使用レジスタ: r4,r5,r6,r7,ip(r12)は呼び出し元がこの直後にpopで
    上書きする/AAPCS上caller-savedなので自由に使ってよい(このモジュール
    冒頭のdocstring参照)。r0,r1,r2,r3,sp,lrは変更しない。
    """
    CC = codecave_addr

    code = bytearray()

    def put(word: int) -> None:
        code.extend(_w(word))

    # +0x00 sub r4, r4, #0x90                  ; r4 = orig_this
    put(_enc_dp_imm(0xE, 0b0010, 0, 4, 4, 0x90))
    # +0x04 ldr r5, [pc, #imm]  -> literal A (&write_pos)      [instr@CC+0x04]
    lit_a_off = 0x44
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 1, 15, 5, lit_a_off - (0x04 + 8)))
    # +0x08 ldr r6, [r5]                        ; r6 = write_pos
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 1, 5, 6, 0))
    # +0x0c add r7, r5, #4                        ; r7 = &seq_counter (adjacent word)
    put(_enc_dp_imm(0xE, 0b0100, 0, 5, 7, 4))
    # +0x10 ldr ip, [pc, #imm] -> literal B (&ring_buffer_base)  [instr@CC+0x10]
    lit_b_off = 0x48
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 1, 15, 12, lit_b_off - (0x10 + 8)))
    # +0x14 add ip, ip, r6, lsl #4                 ; ip = buf + write_pos*16
    put(_enc_dp_reg_shift_imm(0xE, 0b0100, 0, 12, 12, 6, 4))
    # +0x18 str r4, [ip]                             ; entry.this = orig_this
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 0, 12, 4, 0))
    # +0x1c ldr r4, [r4, #0x98]                        ; r4 = character key (再計算、値は元の命令と同一)
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 1, 4, 4, 0x98))
    # +0x20 str r4, [ip, #4]                             ; entry.charkey
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 0, 12, 4, 4))
    # +0x24 ldr r4, [r7]                                   ; r4 = seq
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 1, 7, 4, 0))
    # +0x28 str r4, [ip, #8]                                 ; entry.seq
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 0, 12, 4, 8))
    # +0x2c add r4, r4, #1
    put(_enc_dp_imm(0xE, 0b0100, 0, 4, 4, 1))
    # +0x30 str r4, [r7]                                       ; seq更新を保存
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 0, 7, 4, 0))
    # +0x34 add r6, r6, #1
    put(_enc_dp_imm(0xE, 0b0100, 0, 6, 6, 1))
    # +0x38 and r6, r6, #0xF                                     ; wrap 0..15
    put(_enc_dp_imm(0xE, 0b0000, 0, 6, 6, RING_SIZE - 1))
    # +0x3c str r6, [r5]                                           ; write_pos更新を保存
    put(_enc_ls_imm(0xE, 1, 1, 0, 0, 0, 5, 6, 0))
    # +0x40 b RETURN_ADDR
    put(_enc_b(0xE, CC + 0x40, return_addr))

    assert len(code) == 0x44, hex(len(code))
    code += _w(CC + 0x4C)  # literal A: &write_pos  @ CC+0x44
    code += _w(CC + 0x54)  # literal B: &ring_buffer_base @ CC+0x48
    assert len(code) == 0x4C, hex(len(code))
    code += _w(0)  # write_pos, init 0            @ CC+0x4C
    code += _w(0)  # seq_counter, init 0           @ CC+0x50
    code += bytes(RING_SIZE * RING_ENTRY_SIZE)  # ring buffer, zeroed @ CC+0x54

    trampoline = _w(_enc_b(0xE, inject_addr, CC))
    return bytes(code), trampoline


def read_ring_log(codecave_addr: int) -> list[dict]:
    """コードケイブに書き込んだリングバッファを読み出し、seq昇順に整列して返す。
    seq==0のエントリ(まだ一度も書かれていない枠)は除外する。"""
    header_addr = codecave_addr + 0x4C
    header = read_memory(header_addr, 8)
    write_pos, seq_counter = struct.unpack("<II", header)
    buf_addr = codecave_addr + 0x54
    raw = read_memory(buf_addr, RING_SIZE * RING_ENTRY_SIZE)
    entries = []
    for i in range(RING_SIZE):
        this_ptr, charkey, seq, _reserved = struct.unpack_from("<IIII", raw, i * RING_ENTRY_SIZE)
        if seq == 0 and this_ptr == 0:
            continue
        entries.append({"slot": i, "this": this_ptr, "char_key": charkey, "seq": seq})
    entries.sort(key=lambda e: e["seq"])
    return entries


# ---------------------------------------------------------------------------
# 高レベルAPI: パッチ適用の状態管理
# ---------------------------------------------------------------------------

# 直近で見つけた/適用したパッチの場所を覚えておく(セッション内キャッシュ。
# プロセス再起動やazahar再起動をまたいだ永続化はしない - アドレスはビルド
# ごとに変わりうるため、毎回ライブメモリから再検証するのが安全)。
_state: dict = {"inject_addr": None, "codecave_addr": None, "status": "unknown"}

_SCAN_SIZE = 0x400000  # コード領域を広めに(4MB)スキャンする
_SCAN_BASE = 0x100000  # PROCESS_IMAGE_VADDR


def status() -> dict:
    """現在の接続状況・パッチ適用状況を返す(読み取りのみ、副作用なし)。"""
    if not ping():
        return {"connected": False}

    out = {"connected": True}
    inject_addr = _state.get("inject_addr")
    codecave_addr = _state.get("codecave_addr")
    if inject_addr is None:
        out["patched"] = False
        out["message"] = "まだ注入位置を特定していません(applyを呼んでください)"
        return out

    try:
        current = read_memory(inject_addr, 4)
    except RPCError as e:
        out["error"] = str(e)
        return out

    if current == ORIG_INSTR:
        out["patched"] = False
        out["message"] = "注入位置は分かっているがまだパッチ未適用"
    else:
        out["patched"] = True
    out["inject_addr"] = hex(inject_addr)
    out["codecave_addr"] = hex(codecave_addr) if codecave_addr else None
    return out


def apply(force_rescan: bool = False) -> dict:
    """ライブメモリをスキャンして注入位置を特定し、まだパッチが無ければ適用する。
    既にこのアドレスにパッチ済みならそのまま(idempotent)。"""
    if not ping():
        return {"ok": False, "error": "RPCに接続できません(Azaharが起動していない/バックグラウンドの可能性)"}

    ensure_process_selected()

    inject_addr = _state.get("inject_addr")
    codecave_addr = _state.get("codecave_addr")

    if inject_addr is not None and not force_rescan:
        try:
            current = read_memory(inject_addr, 4)
        except RPCError:
            current = None
        if current is not None and current != ORIG_INSTR:
            # トランポリンが既に入っている(=前回このプロセスに対して適用済み)
            return {"ok": True, "already_patched": True, "inject_addr": hex(inject_addr), "codecave_addr": hex(codecave_addr)}
        if current == ORIG_INSTR:
            pass  # 位置は合っているがまだ未パッチ、以下で適用する
        else:
            inject_addr = None  # 位置がズレている、再スキャンする

    if inject_addr is None:
        dump = read_memory(_SCAN_BASE, _SCAN_SIZE)
        site = find_injection_site(dump, _SCAN_BASE)
        if site is None:
            return {"ok": False, "error": "対象命令列が見つかりませんでした(ビルドが想定と大きく異なる可能性)"}
        inject_addr = site["inject_addr"]
        # コードケイブは対象関数のすぐ後方付近から探す(近いほど探索が速い)
        search_from = max(0, site["callee_addr"] - _SCAN_BASE)
        codecave_addr = find_codecave(dump, _SCAN_BASE, CODECAVE_SIZE + 16, search_from_off=search_from)
        if codecave_addr is None:
            codecave_addr = find_codecave(dump, _SCAN_BASE, CODECAVE_SIZE + 16)
        if codecave_addr is None:
            return {"ok": False, "error": "空きコードケイブが見つかりませんでした"}
        _state["inject_addr"] = inject_addr
        _state["codecave_addr"] = codecave_addr

    codecave_addr = _state["codecave_addr"]
    return_addr = inject_addr + 4

    current = read_memory(inject_addr, 4)
    if current != ORIG_INSTR:
        return {"ok": True, "already_patched": True, "inject_addr": hex(inject_addr), "codecave_addr": hex(codecave_addr)}

    cave_check = read_memory(codecave_addr, CODECAVE_SIZE)
    if not all(b == 0 for b in cave_check):
        return {"ok": False, "error": f"コードケイブ({hex(codecave_addr)})が空でありません、他の用途で使用中の可能性"}

    codecave_bytes, trampoline_bytes = build_probe_patch(inject_addr, return_addr, codecave_addr)

    write_memory(codecave_addr, codecave_bytes)
    verify = read_memory(codecave_addr, len(codecave_bytes))
    if verify != codecave_bytes:
        return {"ok": False, "error": "コードケイブ書き込みの検証に失敗しました(パッチ未適用)"}

    write_memory(inject_addr, trampoline_bytes)
    verify2 = read_memory(inject_addr, 4)
    if verify2 != trampoline_bytes:
        return {"ok": False, "error": "トランポリン書き込みの検証に失敗しました(コードケイブは書き込み済み、要手動確認)"}

    return {"ok": True, "already_patched": False, "inject_addr": hex(inject_addr), "codecave_addr": hex(codecave_addr)}


def log() -> dict:
    """現在のリングバッファの内容を返す。まだパッチが無ければエラーを返す。"""
    if not ping():
        return {"ok": False, "error": "RPCに接続できません"}
    codecave_addr = _state.get("codecave_addr")
    if codecave_addr is None:
        return {"ok": False, "error": "まだパッチが適用されていません(先にapplyしてください)"}
    try:
        entries = read_ring_log(codecave_addr)
    except RPCError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "entries": entries}
