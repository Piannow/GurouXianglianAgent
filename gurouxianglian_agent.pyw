import os, sys, shutil, locale, difflib, threading, subprocess, datetime, string, base64, queue, tempfile, importlib.util, traceback, json, glob, re, time, signal, codecs, shlex, hashlib, math
import ctypes, ctypes.wintypes
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog, ttk
from tkinter import font as tkfont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIOA_DIR = os.path.join(BASE_DIR, "MiOa")
TEMP_A_DIR = os.path.join(MIOA_DIR, "a")
TEMP_B_DIR = os.path.join(MIOA_DIR, "b")
os.makedirs(MIOA_DIR, exist_ok=True)
os.makedirs(TEMP_A_DIR, exist_ok=True)
os.makedirs(TEMP_B_DIR, exist_ok=True)

# ================= 拗口防重名目录 (统一收纳至 MiOa) =================
PLUGINS_DIR = os.path.join(MIOA_DIR, "Human_Coupler_Fulcrum_Plugins")
EXTERNALS_DIR = os.path.join(MIOA_DIR, "Human_Coupler_Fulcrum_External_Commands")
PORTABLE_DIR = os.path.join(MIOA_DIR, "Human_Coupler_Fulcrum_Portable_Environment")
CONFIG_FILE = os.path.join(MIOA_DIR, "Human_Coupler_Fulcrum_Config.json")
# ===========================================================

LAST_OUTPUT = os.path.join(MIOA_DIR, "last_output.txt")
CLIPBOARD_FILE = os.path.join(MIOA_DIR, "剪切板.txt")
os.makedirs(PLUGINS_DIR, exist_ok=True)
os.makedirs(EXTERNALS_DIR, exist_ok=True)
os.makedirs(PORTABLE_DIR, exist_ok=True)

sys.path.insert(0, PLUGINS_DIR)

# =========================================================
# 全局配置与编码处理
# =========================================================
def prepare_white_icon():
    """把你放的图片强行垫一层白底，防止任务栏变黑糊"""
    ico_path = os.path.join(MIOA_DIR, "awa.ico")
    png_path = os.path.join(MIOA_DIR, "awa.png")
    out_ico = os.path.join(MIOA_DIR, "awa_white.ico")
    
    try:
        from PIL import Image
        src_img = None
        if os.path.exists(ico_path):
            src_img = Image.open(ico_path).convert("RGBA")
        elif os.path.exists(png_path):
            src_img = Image.open(png_path).convert("RGBA")
            
        if src_img:
            # 缩放到高清 256x256
            src_img = src_img.resize((256, 256), Image.Resampling.LANCZOS)
            # 创建纯白底
            bg = Image.new("RGBA", (256, 256), (255, 255, 255, 255))
            # 把图片叠上去
            bg.paste(src_img, (0, 0), src_img)
            # 保存为带多尺寸的标准 ICO
            bg.save(out_ico, format="ICO", sizes=[(16,16), (32,32), (48,48), (256,256)])
            return out_ico
    except Exception:
        pass
    return ico_path

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return {}

def save_config(config):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception: pass

def mount_portable_env():
    current_path = os.environ.get("PATH", "")
    paths = current_path.split(os.pathsep)
    paths_to_add = [PORTABLE_DIR]
    try:
        if os.path.exists(PORTABLE_DIR):
            for item in os.scandir(PORTABLE_DIR):
                if item.is_dir():
                    bin_path = os.path.join(item.path, "bin")
                    if os.path.isdir(bin_path): paths_to_add.append(bin_path)
                    if os.path.basename(item.name).lower() == "bin": paths_to_add.append(item.path)
    except Exception: pass

    for p in reversed(paths_to_add):
        if p not in paths:
            paths.insert(0, p)
    os.environ["PATH"] = os.pathsep.join(paths)

def _decodes_as(data: bytes, enc: str, allow_truncated_tail: bool = True) -> bool:
    """严格判断 data 能否用 enc 解码；allow_truncated_tail 兼容流式读取被截断的多字节尾部"""
    try:
        data.decode(enc)
        return True
    except UnicodeDecodeError as e:
        return allow_truncated_tail and e.start >= len(data) - 3
    except LookupError:
        return False

def _detect_encoding(head: bytes) -> str:
    if not head: return "utf-8"
    if head.startswith(codecs.BOM_UTF32_LE) or head.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if head.startswith(codecs.BOM_UTF8): return "utf-8-sig"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)): return "utf-16"
    # 依次严格探测：UTF-8 → GB18030（GBK 超集，可无损还原 GBK 文件）→ 系统编码
    # 不能直接信 locale.getpreferredencoding(False)：UTF-8 模式下它返回 "utf-8"，
    # 会把 GBK 文件误判成 UTF-8（见 issue #1）
    for cand in ("utf-8", "gb18030"):
        if _decodes_as(head, cand):
            return cand
    pref = locale.getpreferredencoding(False) or "utf-8"
    if pref.lower().replace("_", "-") in ("utf-8", "utf8"):
        return "gb18030"
    if _decodes_as(head, pref):
        return pref
    return "gb18030"

def _decode_output(b: bytes) -> str:
    if not b: return ""
    enc = _detect_encoding(b)
    # 依次严格尝试：探测结果 → UTF-8 → GB18030 → 系统编码
    # 这里只用于界面显示日志，最后才允许替换字符兜底
    for cand in (enc, "utf-8", "gb18030", locale.getpreferredencoding(False)):
        if not cand:
            continue
        try:
            return b.decode(cand)
        except (UnicodeDecodeError, LookupError):
            continue
    return b.decode(enc, errors="replace")

def _is_binary(raw: bytes) -> bool:
    """检测二进制文件：先放行带 BOM 的 UTF-16/32 文本，再用 NUL 与不可打印字符比例兜底"""
    if not raw:
        return False
    # UTF-16/32 文本天然含 NUL，先按 BOM 放行
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE,
                       codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        return False
    if b"\x00" in raw[:8192]:
        return True
    sample = raw[:8192]
    text_like = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b < 127 or b >= 128)
    return text_like / len(sample) < 0.90

# =========================================================
# 内置工具区
# =========================================================
def read_text(path):
    if not os.path.isfile(path): raise ValueError(f"文件不存在: {path}")
    with open(path, "rb") as f:
        raw = f.read()
    if not raw: return "", "utf-8"

    if _is_binary(raw):
        raise ValueError(f"文件可能是二进制（{path}），已拒绝文本操作")

    enc = _detect_encoding(raw)
    try:
        text = raw.decode(enc)
    except UnicodeDecodeError as e:
        # 绝不能用 errors="replace" 的结果继续写回：那会把中文永久变成 U+FFFD
        raise ValueError(f"无法按 {enc} 解码（第 {e.start} 字节），已取消操作以免损坏文件")

    return text, enc

def write_text(path, text, encoding):
    try:
        with open(path, "w", encoding=encoding, newline="") as f: f.write(text)
    except Exception as e: raise ValueError(f"写入失败: {e}")

def _bak_dir(file_path, override=None):
    # 默认将所有备份文件存放在 MiOa/backups 目录下，避免污染用户的源码目录
    d = os.path.abspath(override) if override else os.path.join(MIOA_DIR, "backups")
    os.makedirs(d, exist_ok=True); return d

def _bak_list(file_path, backup_dir):
    name = os.path.basename(file_path); items = []
    if not os.path.isdir(backup_dir): return items
    for f in os.listdir(backup_dir):
        if f.startswith(name + ".") and f.endswith(".bak"):
            full = os.path.join(backup_dir, f); items.append((os.path.getmtime(full), f, full))
    items.sort(reverse=True); return items

def _make_backup(path, backup_dir):
    bd = _bak_dir(path, backup_dir)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    bak = os.path.join(bd, f"{os.path.basename(path)}.{stamp}.bak")
    shutil.copy2(path, bak); return bak

def _check_line_endings(content, reject_mixed=False, reject_lone_cr=False):
    """返回 (is_crlf, has_bare_lf, has_lone_cr)"""
    is_crlf = "\r\n" in content
    no_crlf = content.replace("\r\n", "")
    has_bare_lf = "\n" in no_crlf
    has_lone_cr = "\r" in no_crlf
    if reject_lone_cr and has_lone_cr:
        raise ValueError("文件包含孤立 \\r（老 Mac 行尾），无法安全处理")
    if reject_mixed and is_crlf and has_bare_lf:
        raise ValueError("文件包含混合行尾，无法安全处理")
    return is_crlf, has_bare_lf, has_lone_cr

def _safe_replace(content, old, new):
    """安全替换：精确匹配优先，归一化匹配兜底，保留原行尾风格"""
    cnt = content.count(old)
    if cnt > 0:
        return content.replace(old, new), cnt

    old_norm = old.replace("\r\n", "\n")
    new_norm = new.replace("\r\n", "\n")
    content_norm = content.replace("\r\n", "\n")
    cnt = content_norm.count(old_norm)
    if cnt == 0:
        return content, 0

    is_crlf, has_bare_lf, has_lone_cr = _check_line_endings(content, reject_lone_cr=True)
    if is_crlf and has_bare_lf:
        raise ValueError("文件包含混合行尾，无法安全替换（请先统一行尾）")

    new_content_norm = content_norm.replace(old_norm, new_norm)
    if is_crlf:
        return new_content_norm.replace("\n", "\r\n"), cnt
    else:
        return new_content_norm, cnt

def kt_edit(file, old, new="", backup_dir=None, save_to=None):
    try:
        path = os.path.abspath(file)
        if not old: return "[错误] old 不能为空"

        content, enc = read_text(path)
        new_content, count = _safe_replace(content, old, new)

        if count == 0: return "[警告] 未找到目标字符串，未做修改。"

        bak = _make_backup(path, backup_dir)

        target = os.path.abspath(save_to) if save_to else path
        if save_to:
            d = os.path.dirname(target)
            if d: os.makedirs(d, exist_ok=True)

        write_text(target, new_content, enc)
        return f"[成功] 备份: {bak}\n写入: {target}\n替换 {count} 处。"
    except Exception as e: return f"[错误] {str(e)}"

def kt_write(file, content="", backup_dir=None):
    try:
        path = os.path.abspath(file)
        target_dir = os.path.dirname(path)
        if target_dir: os.makedirs(target_dir, exist_ok=True)

        existed = os.path.isfile(path)
        bak_msg = ""
        note = ""
        if existed:
            try:
                _, enc = read_text(path)
            except ValueError as e:
                if "二进制" in str(e):
                    # 二进制文件没有可信的文本编码，沿用旧行为按 utf-8 覆盖并提示
                    enc = "utf-8"
                    note = "[提示] 原文件疑似二进制，已按 utf-8 覆盖\n"
                else:
                    # 解码失败时拒绝覆盖，避免把 GBK / 其他编码内容写成乱码
                    return f"[错误] 拒绝覆盖: {e}"
            bak = _make_backup(path, backup_dir)
            bak_msg = f"备份: {bak}\n"
        else:
            enc = "utf-8"

        write_text(path, content, enc)
        action = "覆盖" if existed else "新建"
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        return f"[成功] {action}文件: {path}\n{bak_msg}{note}长度: {len(content)} 字符, {line_count} 行, 编码: {enc}"
    except Exception as e: return f"[错误] 写入失败: {str(e)}"

def line_delete(file, start_line, end_line, backup_dir=None):
    try:
        path = os.path.abspath(file)
        try:
            start, end = int(start_line), int(end_line)
        except (TypeError, ValueError):
            return "[错误] 行号必须是数字"
        if start < 1: return "[错误] 起始行号必须 >= 1"
        if end < 1: return "[错误] 结束行号必须 >= 1"

        content, enc = read_text(path)
        is_crlf, has_bare_lf, has_lone_cr = _check_line_endings(
            content, reject_mixed=True, reject_lone_cr=True)

        norm = content.replace("\r\n", "\n")
        has_trailing = norm.endswith("\n")
        if has_trailing:
            norm = norm[:-1]

        lines = norm.split("\n")

        if start > len(lines):
            return f"[错误] 起始行 {start} 越界（文件共 {len(lines)} 行）"
        if end > len(lines):
            end = len(lines)
        if start > end:
            return "[错误] 起始行不能大于结束行"

        bak = _make_backup(path, backup_dir)

        del lines[start-1:end]
        new_content = "\n".join(lines)
        if has_trailing and lines:
            new_content += "\n"

        if is_crlf:
            new_content = new_content.replace("\n", "\r\n")

        write_text(path, new_content, enc)
        return f"[成功] 备份: {bak}\n已删除 {start} 到 {end} 行。"
    except Exception as e:
        return f"[错误] {str(e)}"

def kt_diff(file, backup_dir=None):
    try:
        path = os.path.abspath(file)
        bd = _bak_dir(path, backup_dir)
        items = _bak_list(path, bd)
        if not items: return "[提示] 无备份。"
        latest = items[0][2]
        c1, _ = read_text(latest)
        c2, _ = read_text(path)
        diff = list(difflib.unified_diff(
            c1.splitlines(), c2.splitlines(),
            fromfile="Backup", tofile="Current", lineterm=""))
        return "\n".join(diff) if diff else "[提示] 无差异。"
    except Exception as e: return f"[错误] 比对失败: {str(e)}"

def kt_rollback(file, backup_dir=None, save_to=None, bak=None):
    try:
        path = os.path.abspath(file)
        bd = _bak_dir(path, backup_dir)
        if bak:
            bak = os.path.basename(bak)
            src = os.path.join(bd, bak)
            if not os.path.isfile(src): return f"[错误] 找不到指定备份: {src}"
        else:
            items = _bak_list(path, bd)
            if not items: return "[错误] 无备份可回滚。"
            src = items[0][2]
        target = os.path.abspath(save_to) if save_to else path
        if save_to:
            d = os.path.dirname(target)
            if d: os.makedirs(d, exist_ok=True)
        shutil.copy2(src, target)
        return f"[成功] 回滚: {src} -> {target}"
    except Exception as e: return f"[错误] 回滚失败: {str(e)}"

TOOLS = {
    "sys": {
        "desc": "系统工具",
        "commands": {
            "list_tools": {"desc": "获取工具清单", "func": lambda: "[提示] 请使用 AI 指令执行页的 [sys] -> [list_tools] 触发", "args": []}
        }
    },
    "kt": {
        "desc": "文件安全修改 (内置工具，自带备份)",
        "commands": {
            "edit": {"desc": "文本替换", "func": kt_edit, "args": [
                {"name": "file", "desc": "目标文件", "type": "file", "required": True, "pos": 0},
                {"name": "old", "desc": "旧字符串", "required": True, "pos": 1, "multiline": True},
                {"name": "new", "desc": "新字符串", "required": False, "pos": 2, "multiline": True},
                {"name": "backup_dir", "desc": "备份目录", "type": "dir", "key": "backup_dir"},
                {"name": "save_to", "desc": "保存到", "type": "file", "key": "save_to"},
            ]},
            "write": {"desc": "新建或覆盖文件", "func": kt_write, "args": [
                {"name": "file", "desc": "目标文件", "type": "file", "required": True, "pos": 0},
                {"name": "content", "desc": "文件内容", "required": True, "pos": 1, "multiline": True},
                {"name": "backup_dir", "desc": "备份目录", "type": "dir", "key": "backup_dir"},
            ]},
            "line_delete": {"desc": "按行号删除", "func": line_delete, "args": [
                {"name": "file", "desc": "目标文件", "type": "file", "required": True, "pos": 0},
                {"name": "start_line", "desc": "起始行号", "required": True, "pos": 1, "default": "1"},
                {"name": "end_line", "desc": "结束行号", "required": True, "pos": 2, "default": "1"},
                {"name": "backup_dir", "desc": "备份目录", "type": "dir", "key": "backup_dir"},
            ]},
            "diff": {"desc": "与最新备份比较", "func": kt_diff, "args": [
                {"name": "file", "desc": "目标文件", "type": "file", "required": True, "pos": 0},
                {"name": "backup_dir", "desc": "备份目录", "type": "dir", "key": "backup_dir"},
            ]},
            "rollback": {"desc": "回滚到最新备份", "func": kt_rollback, "args": [
                {"name": "file", "desc": "目标文件", "type": "file", "required": True, "pos": 0},
                {"name": "save_to", "desc": "保存到", "type": "file", "key": "save_to"},
                {"name": "bak", "desc": "备份文件名", "key": "bak"},
                {"name": "backup_dir", "desc": "备份目录", "type": "dir", "key": "backup_dir"},
            ]}
        },
    },
}

PROTECTED_TOOLS = ("sys", "kt")
LOAD_WARNINGS = []

# =========================================================
# 版本控制（类 git：任务=分支，每次改文件=一次提交，可回退）
#   - 数据目录：Human_Coupler_Fulcrum_VCS/{vcs.json,snap.json,blobs/}
#   - 提交名 = 文件名 +新增/-删除（如 main.py +12/-3）
#   - 读命令（dir/type/cat…）与只读工具不产生提交
# =========================================================
VCS_DIR = os.path.join(MIOA_DIR, "Human_Coupler_Fulcrum_VCS")
VCS_STATE = os.path.join(VCS_DIR, "vcs.json")
VCS_SNAP = os.path.join(VCS_DIR, "snap.json")
VCS_BLOBS = os.path.join(VCS_DIR, "blobs")

VCS_IGNORE_DIRS = {".git", ".hg", ".svn", "__pycache__", "node_modules", ".idea", ".vscode",
                   ".venv", "venv", "env", "build", "dist", ".backups", ".mypy_cache",
                   "Human_Coupler_Fulcrum_VCS", "Human_Coupler_Fulcrum_Portable_Environment"}
VCS_IGNORE_SUFFIX = (".pyc", ".pyo", ".bak", ".log", ".tmp", ".swp")
VCS_MAX_FILE = 2 * 1024 * 1024      # 单文件 2MB 上限
VCS_MAX_FILES = 4000                # 单次扫描文件数上限
VCS_BLOB_BUDGET = 200 * 1024 * 1024  # 基线缓存内容上限 200MB，超出只记 hash

_READONLY_SHELL = ("dir", "ls", "type", "cat", "more", "echo", "cd", "pwd", "where",
                   "findstr", "grep", "head", "tail", "tree", "ipconfig", "netstat",
                   "whoami", "ver", "cls", "chcp", "ffprobe",
                   "git status", "git log", "git diff", "git branch", "git show")
_READONLY_TOOL_CMDS = {("sys", "list_tools"), ("kt", "diff")}


def _is_readonly_shell(raw):
    """判断 shell 命令是否只读（只读命令不记录提交）。"""
    t = (raw or "").strip().lower()
    if not t:
        return True
    if t.startswith("bat:") or t.startswith("py:"):
        return False          # 脚本可能写文件，按可写处理
    if t.startswith("ps:"):
        t = t[3:].strip()
    for c in _READONLY_SHELL:
        if t == c or t.startswith(c + " "):
            return True
    return False


def _blob_put(data):
    """内容寻址存储：返回 sha1，已存在则复用。"""
    os.makedirs(VCS_BLOBS, exist_ok=True)
    h = hashlib.sha1(data).hexdigest()
    fp = os.path.join(VCS_BLOBS, h)
    if not os.path.exists(fp):
        with open(fp, "wb") as f:
            f.write(data)
    return h


def _blob_get(h):
    if not h:
        return b""
    try:
        with open(os.path.join(VCS_BLOBS, h), "rb") as f:
            return f.read()
    except Exception:
        return b""


def _line_stats(before, after):
    """统计新增/删除行数（用于提交名 +A/-D）。"""
    try:
        a = (before or b"").decode("utf-8", "replace").splitlines()
        b = (after or b"").decode("utf-8", "replace").splitlines()
    except Exception:
        return 0, 0
    add = dele = 0
    for line in difflib.unified_diff(a, b, lineterm="", n=0):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            add += 1
        elif line.startswith("-"):
            dele += 1
    return add, dele


class VCS:
    """极简版本库：任务(分支) → 提交(文件快照) → 回退。"""

    def __init__(self):
        os.makedirs(VCS_BLOBS, exist_ok=True)
        self.state = {"seq": 0, "current": "", "tasks": {}}
        self._load_state()
        if not self.state.get("tasks"):
            self.new_task("任务1")
        elif self.state.get("current") not in self.state.get("tasks", {}):
            self.state["current"] = next(iter(self.state["tasks"]))
            self._save_state()
        self.snap = {}
        self._load_snap()

    # ---------- 持久化 ----------
    def _load_state(self):
        self.state = {"seq": 0, "current": "", "tasks": {}}
        tasks_dir = os.path.join(VCS_DIR, "tasks")
        os.makedirs(tasks_dir, exist_ok=True)
        state_file = os.path.join(VCS_DIR, "state.json")
        old_vcs_file = os.path.join(VCS_DIR, "vcs.json")

        # 1. 尝试读取 state.json (记录当前序号和焦点)
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                    self.state["seq"] = d.get("seq", 0)
                    self.state["current"] = d.get("current", "")
            except Exception as e:
                print("[VCS] 读取 state.json 失败:", e)
                
        # 2. 旧版兼容迁移：如果旧的大文件还在，且 tasks 目录是空的，帮用户自动拆分迁移
        _migrating = None
        if not os.listdir(tasks_dir) and os.path.exists(old_vcs_file):
            try:
                with open(old_vcs_file, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict) and "tasks" in d:
                    self.state["seq"] = d.get("seq", 0)
                    self.state["current"] = d.get("current", "")
                    _migrating = d["tasks"]
                    print("[VCS] 发现旧版 vcs.json，正在自动迁移至文件夹结构...")
            except Exception:
                pass

        if _migrating is not None:
            self.state["tasks"] = _migrating
            self._save_state() # 强制写盘拆分
            try: os.remove(old_vcs_file) # 迁移完毕删除旧大文件
            except: pass
            print("[VCS] 迁移完毕！")
            return

        # 3. 核心逻辑：扫描 tasks 文件夹，重建所有分支
        for item in os.listdir(tasks_dir):
            t_dir = os.path.join(tasks_dir, item)
            info_file = os.path.join(t_dir, "info.json")
            if os.path.isdir(t_dir) and os.path.isfile(info_file):
                try:
                    with open(info_file, "r", encoding="utf-8") as f:
                        t = json.load(f)
                        self.state["tasks"][item] = t
                except Exception as e:
                    print(f"[VCS] 读取分支 {item} 失败:", e)

    def _save_state(self):
        try:
            os.makedirs(VCS_DIR, exist_ok=True)
            tasks_dir = os.path.join(VCS_DIR, "tasks")
            os.makedirs(tasks_dir, exist_ok=True)
            
            # 保存全局焦点和序号
            state_file = os.path.join(VCS_DIR, "state.json")
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump({"seq": self.state.get("seq", 0), "current": self.state.get("current", "")}, f, ensure_ascii=False, indent=1)
            
            # 遍历并保存每个任务（每个任务生成独立文件夹）
            for tid, t in self.state.get("tasks", {}).items():
                t_dir = os.path.join(tasks_dir, tid)
                os.makedirs(t_dir, exist_ok=True)
                info_file = os.path.join(t_dir, "info.json")
                with open(info_file, "w", encoding="utf-8") as f:
                    json.dump(t, f, ensure_ascii=False, indent=1)
                    
            # 清理已经删除的任务文件夹
            for item in os.listdir(tasks_dir):
                if item not in self.state.get("tasks", {}):
                    try: shutil.rmtree(os.path.join(tasks_dir, item))
                    except: pass
                    
        except Exception as e:
            print("[VCS 保存失败]", e)

    def _load_snap(self):
        try:
            with open(VCS_SNAP, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.snap = d
                return
        except Exception:
            pass
        # 首次运行：建立基线（记录 hash + 缓存内容），不产生提交。
        # 只有记录了 hash，后续第一次修改才有“修改前”可用于计算 +N/-M。
        meta = self._scan_meta()
        snap = {}
        budget = VCS_BLOB_BUDGET
        for p, m in meta.items():
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except Exception:
                continue
            snap[p] = [m[0], m[1], hashlib.sha1(data).hexdigest()]
            if budget > 0 and len(data) <= budget:
                try:
                    _blob_put(data)
                    budget -= len(data)
                except Exception:
                    pass
        self.snap = snap
        self._save_snap()

    def _save_snap(self):
        try:
            with open(VCS_SNAP, "w", encoding="utf-8") as f:
                json.dump(self.snap, f, ensure_ascii=False)
        except Exception:
            pass

    # ---------- 扫描 ----------
    def _scan_meta(self):
        meta = {}
        cnt = 0
        for dp, dns, fns in os.walk(BASE_DIR):
            dns[:] = [d for d in dns if d not in VCS_IGNORE_DIRS]
            for fn in fns:
                if fn.lower().endswith(VCS_IGNORE_SUFFIX):
                    continue
                p = os.path.join(dp, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                if st.st_size > VCS_MAX_FILE:
                    continue
                meta[p] = [st.st_size, st.st_mtime_ns]
                cnt += 1
                if cnt > VCS_MAX_FILES:
                    return meta
        return meta

    # ---------- 任务 ----------
    def tasks(self):
        return self.state.get("tasks", {})

    def current_task(self):
        return self.tasks().get(self.state.get("current", ""))

    def current_name(self):
        t = self.current_task()
        return t.get("name", "(无)") if t else "(无)"

    def new_task(self, name="", parent="", base_commit=""):
        self.state["seq"] = int(self.state.get("seq", 0)) + 1
        tid = "t%d" % self.state["seq"]
        nm = (name or "").strip() or ("任务%d" % self.state["seq"])
        self.state.setdefault("tasks", {})[tid] = {
            "id": tid, "name": nm,
            "created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "commits": [],
            "parent": parent or "",
            "base_commit": base_commit or "",
        }
        self.state["current"] = tid
        
        # 立刻在磁盘上生成对应的物理文件夹
        try:
            t_dir = os.path.join(VCS_DIR, "tasks", tid)
            os.makedirs(t_dir, exist_ok=True)
        except Exception as e:
            print("[VCS] 创建文件夹失败:", e)
            
        self._save_state()
        return tid

    def set_current(self, tid):
        if tid in self.tasks():
            self.state["current"] = tid
            self._save_state()
            return True
        return False

    def delete_task(self, tid):
        self.state.get("tasks", {}).pop(tid, None)
        if self.state.get("current") == tid:
            self.state["current"] = next(iter(self.tasks()), "")
            
        # 删除物理文件夹
        try:
            t_dir = os.path.join(VCS_DIR, "tasks", tid)
            if os.path.isdir(t_dir):
                shutil.rmtree(t_dir)
        except Exception as e:
            print("[VCS] 删除文件夹失败:", e)
            
        self._save_state()

    def find_commit(self, cid):
        for t in self.tasks().values():
            for c in t.get("commits", []):
                if c.get("id") == cid:
                    return t, c
        return None, None

    # ---------- 提交 ----------
    def commit_name(self, cid):
        _t, c = self.find_commit(cid)
        return c.get("name", "") if c else ""

    def add_commit(self, entries, source="", command="", allow_empty=False, label=""):
        """entries: [(path, before_bytes|None, after_bytes|None)]
        allow_empty=True 时，即使无文件变更也记录一次提交（用于“查看”类行为的留痕）。
        label 不为空时，优先用作提交名（AI 自定义的行为名称）。
        """
        task = self.current_task()
        if not task:
            return None
        files, names = [], []
        for path, before, after in entries:
            if before == after:
                continue
            add, dele = _line_stats(before or b"", after or b"")
            files.append({
                "path": path,
                "before": _blob_put(before) if before is not None else "",
                "after": _blob_put(after) if after is not None else "",
                "add": add, "del": dele,
                "existed": before is not None,
            })
            names.append("%s +%d/-%d" % (os.path.basename(path), add, dele))
        if not files and not allow_empty:
            return None
        self.state["seq"] = int(self.state.get("seq", 0)) + 1
        cid = "c%d" % self.state["seq"]
        lbl = (label or "").strip()
        if lbl:
            cname = lbl
        elif names:
            cname = ", ".join(names)
        else:
            brief = (command or "").strip().replace("\n", " ")[:60]
            cname = "%s · %s" % ((source or "操作"), brief) if brief else (source or "操作")
        task.setdefault("commits", []).append({
            "id": cid,
            "name": cname,
            "time": datetime.datetime.now().strftime("%H:%M:%S"),
            "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": source,
            "command": (command or "")[:200],
            "files": files,
        })
        self._save_state()
        return cid

    def scan_commit(self, source="", command="", force=False, label=""):
        """对比上次扫描，把变更写成一次提交；无变更返回 None。
        force=True 时，即使没有文件变更也记录一次空提交（留痕）。
        """
        meta = self._scan_meta()
        entries = []
        new_snap = {}
        for p, m in meta.items():
            prev = self.snap.get(p)
            if prev and len(prev) >= 3 and prev[0] == m[0] and prev[1] == m[1]:
                new_snap[p] = [m[0], m[1], prev[2]]
                continue
            try:
                with open(p, "rb") as f:
                    after = f.read()
            except Exception:
                continue
            new_snap[p] = [m[0], m[1], hashlib.sha1(after).hexdigest()]
            before = None
            if prev and len(prev) >= 3 and prev[2]:
                before = _blob_get(prev[2])
            entries.append((p, before, after))
        for p, prev in self.snap.items():
            if p not in new_snap:
                entries.append((p, _blob_get(prev[2]) if len(prev) >= 3 else None, None))
        self.snap = new_snap
        self._save_snap()
        if not entries and not force:
            return None
        return self.add_commit(entries, source, command, allow_empty=force, label=label)

    def touch(self, paths):
        """工具已精确记录提交后，同步扫描基线，避免下次 shell 重复记账。"""
        for p in paths or []:
            try:
                st = os.stat(p)
                with open(p, "rb") as f:
                    data = f.read()
                if len(data) > VCS_MAX_FILE:
                    continue
                self.snap[p] = [st.st_size, st.st_mtime_ns, hashlib.sha1(data).hexdigest()]
            except Exception:
                self.snap.pop(p, None)
        self._save_snap()

    # ---------- 回退 ----------
    def state_at(self, tid, cid):
        """重建“某个提交完成时”的文件状态：沿父链把各任务的提交按顺序叠加。
        返回 (state, later_paths)：
          state[path] = (是否存在, blob_sha1)
          later_paths = 该任务中位于此提交之后的新增/修改文件（回退时需清理）
        """
        chain = []
        cur_t, cur_c = tid, cid
        guard = 0
        while guard < 500:
            guard += 1
            t = self.tasks().get(cur_t)
            if not t:
                break
            commits = t.get("commits", [])
            idx = len(commits) - 1
            for i, c in enumerate(commits):
                if c.get("id") == cur_c:
                    idx = i
                    break
            chain.append(commits[:idx + 1])
            p = t.get("parent") or ""
            pb = t.get("base_commit") or ""
            if p and pb:
                cur_t, cur_c = p, pb
                continue
            break

        state = {}
        for commits in reversed(chain):
            for c in commits:
                for f in c.get("files", []):
                    if f.get("after"):
                        state[f["path"]] = (True, f["after"])
                    else:
                        state[f["path"]] = (False, "")

        # 目标提交之后（同一任务里）还改动过的文件
        later = set()
        t = self.tasks().get(tid) or {}
        seen = False
        for c in t.get("commits", []):
            if c.get("id") == cid:
                seen = True
                continue
            if seen:
                for f in c.get("files", []):
                    later.add(f["path"])
        return state, later

    def rollback_to(self, cid):
        """回退到某提交完成时的状态，并从该提交分出一个新任务（之后的操作记到新分支）。
        返回 (消息文本, 新任务id)。
        """
        t, c = self.find_commit(cid)
        if not c or not t:
            return "提交不存在", None
        state, later = self.state_at(t["id"], cid)
        msgs = []
        for p, (exists, h) in state.items():
            try:
                if exists:
                    data = _blob_get(h)
                    d = os.path.dirname(p)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    with open(p, "wb") as fh:
                        fh.write(data)
                    msgs.append("还原 " + os.path.basename(p))
                else:
                    if os.path.isfile(p):
                        os.remove(p)
                        msgs.append("删除 " + os.path.basename(p))
            except Exception as e:
                msgs.append("失败 %s: %s" % (os.path.basename(p), e))
        # 清理目标提交之后新增、且回退状态里不存在的文件
        for p in later:
            if p not in state and os.path.isfile(p):
                try:
                    os.remove(p)
                    msgs.append("删除后续新增 " + os.path.basename(p))
                except Exception:
                    pass
        self.touch(list(state.keys()) + list(later))
        # 回退即分叉：新建任务，父=原任务，分叉点=该提交；之后的命令都记到新分支
        nm = "回退-" + (c.get("name", "") or "历史")[:18]
        new_tid = self.new_task(nm, parent=t["id"], base_commit=cid)
        return ("\n".join(msgs) if msgs else "文件已是该提交时的状态"), new_tid

    def rollback_commit(self, cid):
        _t, c = self.find_commit(cid)
        if not c:
            return "提交不存在"
        msgs = []
        for f in c.get("files", []):
            p = f["path"]
            try:
                if f.get("existed"):
                    data = _blob_get(f.get("before"))
                    d = os.path.dirname(p)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    with open(p, "wb") as fh:
                        fh.write(data)
                    msgs.append("还原 " + os.path.basename(p))
                else:
                    if os.path.isfile(p):
                        os.remove(p)
                        msgs.append("删除新建文件 " + os.path.basename(p))
            except Exception as e:
                msgs.append("失败 %s: %s" % (os.path.basename(p), e))
        self.touch([f["path"] for f in c.get("files", [])])
        return "\n".join(msgs) if msgs else "无文件需要还原"

    def commit_diff(self, cid, path=None):
        _t, c = self.find_commit(cid)
        if not c:
            return "提交不存在"
        chunks = []
        for f in c.get("files", []):
            if path and f["path"] != path:
                continue
            before = _blob_get(f.get("before")) if f.get("existed") else b""
            after = _blob_get(f.get("after")) if f.get("after") else b""
            try:
                a = before.decode("utf-8", "replace").splitlines(keepends=True)
                b = after.decode("utf-8", "replace").splitlines(keepends=True)
            except Exception:
                chunks.append("(二进制文件) " + f["path"])
                continue
            d = list(difflib.unified_diff(a, b, fromfile="修改前/" + os.path.basename(f["path"]),
                                          tofile="修改后/" + os.path.basename(f["path"]), lineterm="\n"))
            chunks.append("".join(d) if d else "(无文本差异) " + f["path"])
        return "\n".join(chunks) if chunks else "无可显示差异"


_VCS_SINGLETON = None


def get_vcs():
    global _VCS_SINGLETON
    if _VCS_SINGLETON is None:
        try:
            _VCS_SINGLETON = VCS()
        except Exception as e:
            print("[VCS] 初始化失败:", e)
    return _VCS_SINGLETON


# =========================================================
# 外部工具加载
# =========================================================
def run_external(exe_path, args_def, kwargs):
    if not os.path.isabs(exe_path): exe_path = os.path.normpath(os.path.join(BASE_DIR, exe_path))

    sorted_args = list(args_def)
    if any("pos" in a for a in sorted_args):
        sorted_args.sort(key=lambda x: x.get("pos", 9999))

    cmd_list = [exe_path]
    for a in sorted_args:
        v = kwargs.get(a["name"])
        if v is not None:
            flag = a.get("flag")
            if flag: cmd_list.append(str(flag))
            cmd_list.append(str(v))

    try:
        if exe_path.lower().endswith((".bat", ".cmd")):
            run_cmd = ["cmd.exe", "/c"] + cmd_list
            shell_mode = False
        else:
            run_cmd = cmd_list
            shell_mode = False

        r = subprocess.run(run_cmd, capture_output=True, timeout=300, shell=shell_mode)

        out1 = _decode_output(r.stdout)
        out2 = _decode_output(r.stderr)

        return f"命令: {' '.join(cmd_list)}\n退出码: {r.returncode}\n输出:\n{out1 + out2}"
    except Exception as e: return f"执行失败: {e}"

def load_externals():
    for filename in os.listdir(EXTERNALS_DIR):
        if not filename.endswith(".json"): continue
        try:
            with open(os.path.join(EXTERNALS_DIR, filename), "r", encoding="utf-8") as f: cfg = json.load(f)
            name, exe = cfg["name"], cfg["exe"]
            if name in PROTECTED_TOOLS:
                LOAD_WARNINGS.append(f"[警告] 外部工具 {filename} 尝试覆盖内置工具 '{name}'，已拒绝。")
                continue
            if name in TOOLS:
                LOAD_WARNINGS.append(f"[警告] 工具名 '{name}' 已被占用，外部工具 {filename} 将覆盖它。")
            cmds = {}
            for cname, cargs in cfg.get("commands", {}).items():
                cmds[cname] = {
                    "desc": cargs.get("desc", ""),
                    "func": (lambda exe=exe, cargs=cargs, **kw: run_external(exe, cargs.get("args", []), kw)),
                    "args": cargs.get("args", [])
                }
            TOOLS[name] = {"desc": cfg.get("desc", "外部工具"), "commands": cmds}
        except Exception as e: LOAD_WARNINGS.append(f"[警告] 加载外部工具失败 {filename}: {e}")

def load_plugins():
    for filename in os.listdir(PLUGINS_DIR):
        if not filename.endswith(".py"): continue
        try:
            spec = importlib.util.spec_from_file_location(filename[:-3], os.path.join(PLUGINS_DIR, filename))
            mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
            if hasattr(mod, "get_tools"):
                new_tools = mod.get_tools()
                if not isinstance(new_tools, dict):
                    LOAD_WARNINGS.append(f"[警告] 插件 {filename} 的 get_tools() 未返回 dict，已跳过。")
                    continue
                for name, t in new_tools.items():
                    if name in PROTECTED_TOOLS:
                        LOAD_WARNINGS.append(f"[警告] 插件 {filename} 尝试覆盖内置工具 '{name}'，已拒绝。")
                        continue
                    if name in TOOLS:
                        LOAD_WARNINGS.append(f"[警告] 工具名 '{name}' 已被占用，插件 {filename} 将覆盖它。")
                    TOOLS[name] = t
        except Exception as e: LOAD_WARNINGS.append(f"[警告] 加载插件失败 {filename}: {e}")

def invoke_tool(tool_name, cmd_name, values):
    try:
        cmd = TOOLS[tool_name]["commands"][cmd_name]
        kwargs = {}
        for a in cmd.get("args", []):
            v = values.get(a["name"], "")
            if v == "" and "default" in a:
                v = a["default"]

            if a.get("required") and not str(v).strip():
                return f"[执行错误] 缺少必填参数: {a.get('desc', a['name'])}"

            if v is not None and str(v) != "":
                kwargs[a["name"]] = v

        # --- 版本控制：改前快照（写类工具才记录）---
        targets = []
        for k in ("file", "save_to"):
            v = kwargs.get(k)
            if v:
                try:
                    targets.append(os.path.abspath(v))
                except Exception:
                    pass
        before_map = {}
        record = True  # v1.2.0 更新：所有操作（含查看类）都留痕
        for p in targets:
            try:
                with open(p, "rb") as f:
                    before_map[p] = f.read()
            except Exception:
                before_map[p] = None

        result = cmd["func"](**kwargs)

        if record:
            try:
                vcs = get_vcs()
                entries = []
                for p in targets:
                    try:
                        with open(p, "rb") as f:
                            after = f.read()
                    except Exception:
                        after = None
                    entries.append((p, before_map.get(p), after))
                lbl = (values.get("label") or "").strip()
                cid = vcs.add_commit(entries, source="%s.%s" % (tool_name, cmd_name),
                                     command=json.dumps({k: str(v)[:80] for k, v in kwargs.items()},
                                                        ensure_ascii=False),
                                     allow_empty=True, label=lbl)
                if cid and _APP_REF:
                    # 修复：必须调度回主线程更新 UI，否则会引发 Tkinter 死锁或崩溃
                    _APP_REF.root.after(0, lambda: _APP_REF._append("[版本] 已记录：%s\n" % vcs.commit_name(cid)))
                    _APP_REF.root.after(0, _APP_REF._refresh_vcs_tree)
                vcs.touch(targets)
            except Exception as e:
                print("[VCS] 记录失败:", e)

        return result
    except Exception as e:
        return f"[工具崩溃] {str(e)}\n{traceback.format_exc()}"

# =========================================================
# 动态工具清单
# =========================================================
def generate_ai_schema():
    md = "【本地工具调用规范】\n下发指令格式：\n```json\n{\"tool\": \"工具名\", \"command\": \"命令名\", \"params\": {\"参数\": \"值\"}}\n```\n\n当前可用工具：\n"
    md += "### sys (系统工具)\n- `list_tools`: 获取本清单\n\n"

    for name, t in TOOLS.items():
        if name == "sys": continue
        md += f"### {name} ({t.get('desc', '')})\n"
        for cname, c in t["commands"].items():
            md += f"- `{cname}`: {c.get('desc', '')}\n"
            args = c.get("args", [])
            if args:
                arg_strs = []
                for a in args:
                    req = "" if a.get('required') else "?"
                    d_str = f" 默认:{a['default']}" if "default" in a else ""
                    arg_strs.append(f"{a['name']}{req}({a.get('desc') or a['name']}{d_str})")
                md += f"  参数: {', '.join(arg_strs)}\n"
            else: md += f"  参数: 无\n"
        md += "\n"
    return md

# =========================================================
# 复古 UI 选择器
# =========================================================
class RetroPickerBase(tk.Toplevel):
    def __init__(self, parent, init_path=None, title="选择"):
        super().__init__(parent)
        self.title(title); self.transient(parent); self.grab_set()
        self.result = None
        self.configure(bg="#c0c0c0")
        self.style = ttk.Style(self)
        try: self.style.theme_use('winnative')
        except: pass
        self.style.configure("Treeview", font=("Simsun", 10), rowheight=20, background="white", fieldbackground="white")
        self.style.configure("Treeview.Heading", font=("Simsun", 10))
        self.setup_ui(); self.refresh(); self.bind("<Escape>", lambda e: self.cancel())

    def setup_ui(self):
        top_frame = tk.Frame(self, bg="#c0c0c0"); top_frame.pack(fill="x", padx=4, pady=4)
        tk.Button(top_frame, text="⬆ 上一级", command=self.go_up, bg="#c0c0c0", relief="raised", bd=2).pack(side="left")
        self.path_var = tk.StringVar(value=getattr(self, 'current', ''))
        entry_path = tk.Entry(top_frame, textvariable=self.path_var, bg="white", relief="sunken", bd=2)
        entry_path.pack(side="left", fill="x", expand=True, padx=4)
        entry_path.bind("<Return>", lambda e: self.goto(self.path_var.get()))
        tk.Button(top_frame, text="跳转", command=lambda: self.goto(self.path_var.get()), bg="#c0c0c0", relief="raised", bd=2).pack(side="left")

        drives_frame = tk.Frame(self, bg="#c0c0c0"); drives_frame.pack(fill="x", padx=4, pady=(0, 4))
        tk.Label(drives_frame, text="快速访问:", bg="#c0c0c0").pack(side="left")
        for letter in string.ascii_uppercase:
            p = f"{letter}:\\"
            if os.path.exists(p): tk.Button(drives_frame, text=letter, width=2, command=lambda p=p: self.goto(p), bg="#c0c0c0", relief="raised", bd=2).pack(side="left", padx=1)

        list_frame = tk.Frame(self); list_frame.pack(fill="both", expand=True, padx=4)
        self.tree = ttk.Treeview(list_frame, columns=("name",), show="tree", selectmode="browse")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview); sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-Button-1>", self.on_double_click)
        if hasattr(self, 'on_select'): self.tree.bind("<<TreeviewSelect>>", self.on_select)

    def goto(self, path):
        if os.path.isfile(path): self.current = os.path.dirname(path) or "."
        elif os.path.isdir(path): self.current = os.path.abspath(path)
        else: return
        self.path_var.set(self.current); self.refresh()

    def go_up(self):
        parent = os.path.dirname(self.current)
        if parent and parent != self.current: self.goto(parent)

    def on_double_click(self, event):
        sel = self.tree.selection()
        if not sel: return
        path = sel[0]
        if os.path.isdir(path): self.goto(path)
        elif hasattr(self, 'handle_file_double_click'): self.handle_file_double_click(path)
    def cancel(self): self.result = None; self.destroy()

class DirPicker(RetroPickerBase):
    def __init__(self, parent, init_dir=None, title="选择目录"):
        self.current = os.path.abspath(init_dir or os.path.expanduser("~"))
        if not os.path.isdir(self.current): self.current = os.path.expanduser("~")
        super().__init__(parent, self.current, title); self.geometry("640x520")
    def setup_ui(self):
        super().setup_ui()
        bottom_frame = tk.Frame(self, bg="#c0c0c0"); bottom_frame.pack(fill="x", padx=4, pady=8)
        tk.Button(bottom_frame, text="取消", command=self.cancel, bg="#c0c0c0", relief="raised", bd=2).pack(side="right", padx=4)
        tk.Button(bottom_frame, text="选择此目录", command=self.confirm, bg="#c0c0c0", relief="raised", bd=2).pack(side="right", padx=4)
        tk.Button(bottom_frame, text="新建文件夹", command=self.new_folder, bg="#c0c0c0", relief="raised", bd=2).pack(side="left")
    def refresh(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        try:
            for e in sorted(os.scandir(self.current), key=lambda e: e.name.lower()):
                if e.is_dir(): self.tree.insert("", "end", iid=e.path, text=f"📁  {e.name}")
        except OSError: pass
    def new_folder(self):
        name = simpledialog.askstring("新建文件夹", "请输入文件夹名称:", parent=self)
        if name:
            target = os.path.join(self.current, name)
            try:
                os.makedirs(target, exist_ok=True); self.refresh()
                if target in self.tree.get_children(): self.tree.selection_set(target); self.tree.see(target)
            except Exception as e: messagebox.showerror("错误", str(e), parent=self)
    def confirm(self): self.result = self.tree.selection()[0] if self.tree.selection() else self.current; self.destroy()

class FilePicker(RetroPickerBase):
    def __init__(self, parent, init_file=None, title="选择文件"):
        if init_file and os.path.isfile(init_file):
            start_dir = os.path.dirname(os.path.abspath(init_file)); self._prefill = os.path.basename(init_file)
        else: start_dir = os.path.expanduser("~"); self._prefill = ""
        self.current = os.path.abspath(start_dir)
        super().__init__(parent, self.current, title); self.geometry("700x550")
    def setup_ui(self):
        super().setup_ui()
        bottom_frame = tk.Frame(self, bg="#c0c0c0"); bottom_frame.pack(fill="x", padx=4, pady=4)
        tk.Label(bottom_frame, text="文件名:", bg="#c0c0c0").pack(side="left")
        self.name_var = tk.StringVar(value=self._prefill)
        tk.Entry(bottom_frame, textvariable=self.name_var, bg="white", relief="sunken", bd=2).pack(side="left", fill="x", expand=True, padx=4)
        action_frame = tk.Frame(self, bg="#c0c0c0"); action_frame.pack(fill="x", padx=4, pady=(0, 8))
        tk.Button(action_frame, text="取消", command=self.cancel, bg="#c0c0c0", relief="raised", bd=2).pack(side="right", padx=4)
        tk.Button(action_frame, text="选择文件", command=self.confirm, bg="#c0c0c0", relief="raised", bd=2).pack(side="right", padx=4)
    def refresh(self):
        for item in self.tree.get_children(): self.tree.delete(item)
        try:
            for e in sorted(os.scandir(self.current), key=lambda e: (not e.is_dir(), e.name.lower())):
                if e.is_dir(): self.tree.insert("", "end", iid=e.path, text=f"📁  {e.name}")
                elif e.is_file(): self.tree.insert("", "end", iid=e.path, text=f"📄  {e.name}")
        except OSError: pass
    def on_select(self, event):
        sel = self.tree.selection()
        if sel and os.path.isfile(sel[0]): self.name_var.set(os.path.basename(sel[0]))
    def handle_file_double_click(self, path): self.name_var.set(os.path.basename(path))
    def confirm(self):
        name = os.path.basename(self.name_var.get().strip())
        if name in ("", ".", ".."):
            messagebox.showwarning("提示", "文件名不能为空或非法", parent=self)
            return
        self.result = os.path.join(self.current, name); self.destroy()

def pick_dir(parent, init=None, title="选择目录"):
    dlg = DirPicker(parent, init, title); parent.wait_window(dlg); return dlg.result
def pick_file(parent, init=None, title="选择文件"):
    dlg = FilePicker(parent, init, title); parent.wait_window(dlg); return dlg.result

# =========================================================
# 主界面
# =========================================================

LANE_COLORS = ["#4C8BF5", "#E8710A", "#0F9D58", "#AB47BC", "#00ACC1",
               "#F4511E", "#7CB342", "#5E35B1", "#C2185B", "#00897B"]


class VCSGraphView:
    """分支树（Win98 观感）：灰底、1px 黑线、方块节点；主干居中，子分支左右层层外扩。"""
    LANE_W = 200          # 兼容旧引用（已不用于布局）
    STEP = 168            # 根系：每一层分支的横向间距
    ROW_H = 30
    TOP = 68
    LEFT = 24
    RIGHT = 24
    BOTTOM = 40
    R = 8                 # 主干节点基准半径（越深越小）

    def __init__(self, parent, app):
        self.app = app
        self.vcs = None
        self.sel = ("", "")
        self.collapsed = set()
        self.items = []
        self.pos = {}
        # ---------- 书架视图配置 ----------
        self.page = 0
        self.cols = 4
        self.rows = 2
        self.per_page = self.cols * self.rows
        self.book_size = 90
        self.book_gap = 32
        self.view_mode = "shelf"  # "shelf" 或 "tree"（后续扩展用）
        self.clipboard_branch = None
        self.selected_book_step = None
        self.branch_scroll_x = 0
        self.book_page = 0
        self.book_total_override = None
        self.current_book_tid = ""
        # Win98 风格：凹陷边框 + 灰底画布（不用白底，不用彩色）
        self.holder = tk.Frame(parent, relief="sunken", bd=2, bg="#c0c0c0")
        self.canvas = tk.Canvas(self.holder, bg="#c0c0c0", highlightthickness=0,
                                takefocus=1, bd=0)
        self.vbar = tk.Scrollbar(parent, orient="vertical", command=self.canvas.yview,
                                 relief="sunken", bd=1, width=16)
        self.hbar = tk.Scrollbar(parent, orient="horizontal", command=self.canvas.xview,
                                 relief="sunken", bd=1)
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.holder.grid(row=0, column=0, sticky="nsew")
        self.canvas.pack(fill="both", expand=True)
        self.vbar.grid(row=0, column=1, sticky="ns")
        self.hbar.grid(row=1, column=0, sticky="ew")
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        self._bind_events()

    # ---------- 事件 ----------
    def _bind_events(self):
        c = self.canvas
        def _on_wheel(e):
            # 优先判断是否在分支展开面板内，如果在，则滚轮直接控制分支横向滚动
            if getattr(self, "selected_book_step", None) and hasattr(self, "_branch_panel_bbox"):
                mx, my = c.canvasx(e.x), c.canvasy(e.y)
                px1, py1, px2, py2 = self._branch_panel_bbox
                if px1 <= mx <= px2 and py1 <= my <= py2:
                    if getattr(self, "_branch_max_scroll", 0) > 0:
                        # 加 0.05 秒防抖，防止极高精度鼠标乱飞，保留顺滑
                        _now = time.time()
                        if _now - getattr(self, "_last_wheel_time", 0) < 0.05:
                            return
                        self._last_wheel_time = _now
                        
                        delta = -1 if e.delta > 0 else (1 if e.delta < 0 else 0)
                        if delta != 0:
                            _step = 45 # 回归轻柔步长，平滑展示中间被隐藏的分支
                            self.branch_scroll_x = getattr(self, "branch_scroll_x", 0) + delta * _step
                            self.branch_scroll_x = max(0, min(self.branch_scroll_x, self._branch_max_scroll))
                            self.render()
                        return
                        
            # 按住 Shift 键，左右滚动（用于全局横向查看）
            if e.state & 1:
                c.xview_scroll(int(-e.delta / 120), "units")
                return
                
            if getattr(self, "view_mode", "tree") == "shelf":
                _root_cnt = len([t for t in self.vcs.tasks().values() if not t.get("parent")])
                total_pages = max(1, (_root_cnt + self.per_page - 1) // self.per_page)
                if total_pages > 1:
                    self.page = max(0, min(self.page + (-1 if e.delta > 0 else 1), total_pages - 1))
                    self.render()
            else:
                # 书本和树形模式：默认上下滚动页面
                c.yview_scroll(int(-e.delta / 120), "units")

        def _on_left_key(e):
            if getattr(self, "view_mode", "tree") == "shelf":
                if self.page > 0:
                    self.page -= 1
                    self.render()
            else:
                self._nav_lane(-1)

        def _on_right_key(e):
            if getattr(self, "view_mode", "tree") == "shelf":
                total_pages = max(1, (len(self.vcs.tasks()) + self.per_page - 1) // self.per_page)
                if self.page < total_pages - 1:
                    self.page += 1
                    self.render()
            else:
                self._nav_lane(1)

        c.bind("<MouseWheel>", _on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: c.xview_scroll(int(-e.delta / 120), "units"))
        c.bind("<Left>", _on_left_key)
        c.bind("<Right>", _on_right_key)
        
        def _on_up_key(e):
            if getattr(self, "view_mode", "tree") == "shelf":
                self._nav_item(-1)
            elif getattr(self, "view_mode", "tree") == "book":
                c.yview_scroll(-1, "units")
            else:
                self._nav_item(-1)
                
        def _on_down_key(e):
            if getattr(self, "view_mode", "tree") == "shelf":
                self._nav_item(1)
            elif getattr(self, "view_mode", "tree") == "book":
                c.yview_scroll(1, "units")
            else:
                self._nav_item(1)
                
        c.bind("<Up>", _on_up_key)
        c.bind("<Down>", _on_down_key)
        c.bind("<Return>", lambda e: self.app.vcs_show_diff())
        c.bind("<Button-3>", self._on_right_click)
        c.bind("<Button-1>", self._on_left_click)
        c.bind("<Double-Button-1>", self._on_double_click)
        c.bind("<Control-r>", lambda e: self.app.vcs_rollback())
        c.bind("<Configure>", self._on_configure)

    def _on_configure(self, event=None):
        """窗口/画布尺寸变化 → 重新布局（内容始终水平居中）。"""
        try:
            if getattr(self, "_cfg_job", None):
                self.canvas.after_cancel(self._cfg_job)
        except Exception:
            pass
        try:
            self._cfg_job = self.canvas.after(120, self.render)
        except Exception:
            pass

    def _hit(self, event):
        """返回光标下的 (kind, id)：('commit',cid) / ('task',tid) / ('','')"""
        try:
            # 画布可能已滚动：必须把窗口坐标换成画布坐标，否则点不中
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            items = self.canvas.find_overlapping(x - 4, y - 4, x + 4, y + 4)
        except tk.TclError:
            return "", ""
        for it in reversed(items):
            for tag in self.canvas.gettags(it):
                if tag.startswith("commit:"):
                    return "commit", tag.split(":", 1)[1]
                if tag.startswith("task:"):
                    return "task", tag.split(":", 1)[1]
        return "", ""

    def _on_left_click(self, event):
        try:
            self.canvas.focus_set()
        except tk.TclError:
            pass
        
        # 拦截书本界面（内部点击）
        if getattr(self, "view_mode", "tree") == "book":
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            
            # 如果点中了图标，直接放行让 tag_bind 处理，阻断后续渲染逻辑防止冲突
            for it in self.canvas.find_overlapping(x-2, y-2, x+2, y+2):
                if "doc_icon" in self.canvas.gettags(it):
                    return
            
            # 0. 处理展开区域底部的滑动条点击
            if getattr(self, "selected_book_step", None):
                # 反推当前展开区的坐标（粗略计算）
                tid = getattr(self, "current_book_tid", "")
                sub_branches = [ct for ct in self.vcs.tasks().values() if ct.get("parent") == tid and ct.get("base_commit") == self.selected_book_step]
                
                if sub_branches:
                    # 智能识别轨道/滑块：点轨道按比例跳转，点滑块本身忽略
                    on_thumb = False
                    track_item = None
                    for _it in self.canvas.find_overlapping(x-2, y-2, x+2, y+2):
                        _tags = self.canvas.gettags(_it)
                        if "branch_scroll_thumb" in _tags:
                            on_thumb = True
                        if "branch_scroll_track" in _tags:
                            track_item = _it
                    if track_item is not None:
                        if not on_thumb:
                            if hasattr(self, "_branch_max_scroll"):
                                _max = self._branch_max_scroll
                                _tx1, _tx2 = self._branch_track_bbox
                                _vis = _tx2 - _tx1
                                if _max > 0:
                                    _ratio = max(0.0, min(1.0, (x - _tx1) / max(1, _vis)))
                                    self.branch_scroll_x = int(_ratio * _max)
                                    self.render()
                        return
                    
            # 1. 点击步骤文字：仅判断是否要展开下方区域
            for bx1, by1, bx2, by2, cmid in getattr(self, "book_step_rects", []):
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    # 当前书里的步骤，owner_tid 就是当前打开的书的 tid
                    owner_tid = getattr(self, "current_book_tid", "")
                    
                    has_child = len(self._get_sub_branches(owner_tid, cmid)) > 0
                    
                    if has_child:
                        # 如果点的是当前已经展开的那一步，就收起；否则展开新的
                        if getattr(self, "selected_book_step", None) == cmid:
                            self.selected_book_step = None
                        else:
                            self.selected_book_step = cmid
                        self.branch_scroll_x = 0  # 无论收起还是展开，强制重置滑动条
                    else:
                        self.selected_book_step = None
                        
                    self.render()
                    return
                    
            # 3. 点击底部翻页
            for it in self.canvas.find_overlapping(x-5, y-5, x+5, y+5):
                if "book_page_btn" in self.canvas.gettags(it):
                    bb = self.canvas.bbox("book_page_btn")
                    if bb:
                        w = bb[2] - bb[0]
                        if x < bb[0] + w * 0.3:  # 左侧 30% 区域
                            if self.book_page > 0:
                                self.book_page -= 1
                                self.render()
                            return
                        elif x > bb[2] - w * 0.3:  # 右侧 30% 区域
                            total = getattr(self, "book_total_pages_cached", 1)
                            if self.book_page < total - 1:
                                self.book_page += 1
                                self.render()
                            return
                    # 中间 40% 触发修改数字
                    self._edit_book_page_inplace()
                    return
                    
            return

        # 拦截书架界面的特殊点击（分页符、路径栏、新建按钮）
        if getattr(self, "view_mode", "tree") == "shelf":
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            items = self.canvas.find_overlapping(x-5, y-5, x+5, y+5)
            for it in items:
                tags = self.canvas.gettags(it)
                if "page_btn" in tags:
                    bb = self.canvas.bbox("page_btn")
                    if bb:
                        w = bb[2] - bb[0]
                        if x < bb[0] + w * 0.3:  # 左侧 30% 区域
                            if self.page > 0:
                                self.page -= 1
                                self.render()
                            return
                        elif x > bb[2] - w * 0.3:  # 右侧 30% 区域
                            total = getattr(self, "total_pages_cached", 1)
                            if self.page < total - 1:
                                self.page += 1
                                self.render()
                            return
                    # 中间 40% 触发修改数字
                    self._edit_shelf_page_inplace()
                    return
                pass

        kind, oid = self._hit(event)
        if kind == "commit":
            self.select_commit(oid)
        elif kind == "task":
            self.select_task(oid)

    def _on_double_click(self, event):
        kind, oid = self._hit(event)
        
        if getattr(self, "view_mode", "tree") == "shelf":
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            for it in self.canvas.find_overlapping(x-5, y-5, x+5, y+5):
                if "new_task_btn" in self.canvas.gettags(it):
                    return
                    
            if kind == "task":
                self.sel = ("task", oid)
                self.app.vcs_switch_task(oid)
                self.view_mode = "book"
                self.current_book_tid = oid
                self.book_page = 0
                self.book_total_override = None
                self.selected_book_step = None
                self.branch_scroll_x = 0
                self.render()
            return

        # 书本模式：将双击降级为单击，保证疯狂连点时不丢失任何一次响应
        if getattr(self, "view_mode", "tree") == "book":
            self._on_left_click(event)
            return

        # 树形模式：双击空白处返回书架
        if not kind:
            self.view_mode = "shelf"
            self.render()
            return

        if kind == "commit":
            self.select_commit(oid)
            self.app.vcs_show_diff()
        elif kind == "task":
            self.toggle_collapse(oid)

    def _on_right_click(self, event):
        try:
            self.canvas.focus_set()
        except tk.TclError:
            pass
            
        if getattr(self, "view_mode", "tree") == "book":
            self._on_book_right_click(event)
            return
            
        kind, oid = self._hit(event)
        if not kind:
            return
        self.sel = (kind, oid)
        
        # 书架界面的右键
        if getattr(self, "view_mode", "tree") == "shelf":
            if kind == "task":
                m = tk.Menu(self.canvas, tearoff=0, font=("SimSun", 9))
                t = self.vcs.tasks().get(oid, {})
                m.add_command(label="✏️ 重命名本书", command=lambda: self._rename_current_book(oid))
                m.add_command(label="🗑️ 删除任务", command=lambda: self.app.vcs_delete_task(tid=oid))
                try:
                    m.tk_popup(event.x_root, event.y_root)
                finally:
                    m.grab_release()
            return

        self._draw_selection()
        self._show_info()
        m = tk.Menu(self.canvas, tearoff=0)
        if kind == "commit":
            m.add_command(label="查看差异", command=self.app.vcs_show_diff)
            m.add_command(label="回退到此提交（新分支）", command=self.app.vcs_rollback)
            m.add_command(label="仅撤销这次修改", command=self.app.vcs_undo_commit)
            m.add_separator()
            m.add_command(label="复制提交名", command=lambda: self._copy(self._commit_name(oid)))
        else:
            t = self.vcs.tasks().get(oid, {}) if self.vcs else {}
            m.add_command(label="设为当前任务", command=lambda: self.app.vcs_switch_task(tid=oid))
            m.add_command(label="从该任务新建分支", command=lambda: self.app.vcs_new_task(parent=oid))
            m.add_command(label="折叠/展开", command=lambda: self.toggle_collapse(oid))
            m.add_separator()
            m.add_command(label="删除任务", command=lambda: self.app.vcs_delete_task(tid=oid))
            m.add_command(label="复制任务名", command=lambda: self._copy(t.get("name", oid)))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _on_book_right_click(self, event):
        c = self.canvas
        x = c.canvasx(event.x)
        y = c.canvasy(event.y)
        
        # 检查是否点中了子分支方块
        clicked_branch_tid = None
        for bx1, by1, bx2, by2, btid in getattr(self, "branch_box_rects", []):
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                clicked_branch_tid = btid
                break
                
        if clicked_branch_tid:
            m = tk.Menu(self.canvas, tearoff=0, font=("SimSun", 9))
            m.add_command(label="📂 进入该分支", command=lambda: self._jump_to_branch(clicked_branch_tid))
            m.add_command(label="🗑️ 删除该分支", command=lambda: self.app.vcs_delete_task(tid=clicked_branch_tid))
            try:
                m.tk_popup(event.x_root, event.y_root)
            finally:
                m.grab_release()
            return
            
        # 寻找点击的步骤
        clicked_cmid = None
        for bx1, by1, bx2, by2, cmid in getattr(self, "book_step_rects", []):
            if bx1 <= x <= bx2 and by1 <= y <= by2:
                clicked_cmid = cmid
                break
                
        if not clicked_cmid:
            # 如果没点中具体的步骤，说明点在了空白处，呼出全局操作菜单
            tid = getattr(self, "current_book_tid", "")
            m = tk.Menu(self.canvas, tearoff=0, font=("SimSun", 9))
            
            paste_state = "normal" if getattr(self, "clipboard_branch", None) else "disabled"
            m.add_command(label="📌 粘贴分支到这里", state=paste_state, command=lambda: self._book_ctx_paste_branch(tid, None))
            m.add_separator()
            if self.vcs.tasks().get(tid, {}).get("commits"):
                m.add_command(label="✏️ 重命名本书", command=self._rename_current_book)
            m.add_command(label="↩ 返回书架", command=lambda: (setattr(self, "view_mode", "shelf"), self.render()))
            
            try:
                m.tk_popup(event.x_root, event.y_root)
            finally:
                m.grab_release()
            return
            
        tid = getattr(self, "current_book_tid", "")
        if not tid or not self.vcs:
            return
            
        _t, cm = self.vcs.find_commit(clicked_cmid)
        if not cm:
            return
            
        # 记录选中的提交
        self.sel = ("commit", clicked_cmid)
        
        # 构建 PPT 风格的右键菜单
        m = tk.Menu(self.canvas, tearoff=0, font=("SimSun", 9))
        m.add_command(label="🌿 创建新分支", command=lambda: self._book_ctx_new_branch(tid, clicked_cmid))
        m.add_command(label="📋 复制此支及以下", command=lambda: self._book_ctx_copy_branch(tid, clicked_cmid))
        
        # 粘贴逻辑（依据剪贴板状态亮起）
        paste_state = "normal" if getattr(self, "clipboard_branch", None) else "disabled"
        m.add_command(label="📌 粘贴分支到这里", state=paste_state, command=lambda: self._book_ctx_paste_branch(tid, clicked_cmid))
        
        m.add_command(label="🚚 移动已有子分支", command=lambda: self._book_ctx_move_branch(tid, clicked_cmid))
        m.add_separator()
        m.add_command(label="✏️ 重命名", command=lambda: self._book_ctx_rename(clicked_cmid))
        m.add_command(label="🗑️ 删除", command=lambda: self._book_ctx_delete(tid, clicked_cmid))
        m.add_separator()
        m.add_command(label="🛑 废除该分支", command=lambda: self._book_ctx_abort(tid, clicked_cmid))
        
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _book_ctx_new_branch(self, tid, cmid):
        from tkinter import simpledialog
        name = simpledialog.askstring("新建分支", "请输入新分支的名称：", parent=self.app.root)
        if not name:
            return
        new_tid = self.vcs.new_task(name, parent=tid, base_commit=cmid)
        # 恢复到父级任务，不改变外部当前任务
        self.vcs.set_current(tid)
        self.app._refresh_vcs_tree()
        self.render()
        messagebox.showinfo("成功", f"分支「{name}」已创建，点击下方方块即可进入阅读。", parent=self.app.root)

    def _book_ctx_copy_branch(self, tid, cmid):
        t = self.vcs.tasks().get(tid)
        if not t: return
        
        # 把该提交及之后的所有提交打包存入剪贴板
        commits = t.get("commits", [])
        idx = next((i for i, c in enumerate(commits) if c["id"] == cmid), -1)
        if idx == -1: return
        
        import copy
        self.clipboard_branch = {
            "source_task_name": t.get("name", "任务"),
            "commits": copy.deepcopy(commits[idx:])
        }
        messagebox.showinfo("复制成功", f"已复制 {len(self.clipboard_branch['commits'])} 个步骤及其后续分支到剪贴板。\n请去其他步骤右键点击「粘贴分支」。", parent=self.app.root)

    def _book_ctx_paste_branch(self, tid, cmid):
        cb = getattr(self, "clipboard_branch", None)
        if not cb or not cb.get("commits"): return
        
        # 如果 cmid 为空，说明是在空白处粘贴，自动挂载到最后一步
        if not cmid:
            task = self.vcs.tasks().get(tid)
            if task and task.get("commits"):
                cmid = task["commits"][-1]["id"]
            else:
                cmid = ""
        
        # 从剪贴板提取内容，生成一本全新的书挂载到当前节点
        new_name = cb["source_task_name"] + " 的副本"
        new_tid = self.vcs.new_task(new_name, parent=tid, base_commit=cmid)
        
        new_task = self.vcs.tasks().get(new_tid)
        import copy
        new_task["commits"] = copy.deepcopy(cb["commits"])
        
        # B2 修复：为粘贴的 clone 生成全新且全局唯一的 commit id
        for _cm in new_task["commits"]:
            self.vcs.state["seq"] = int(self.vcs.state.get("seq", 0)) + 1
            _cm["id"] = "c%d" % self.vcs.state["seq"]
            
        self.vcs._save_state()
        self.clipboard_branch = None
        self.selected_book_step = None
        self.branch_scroll_x = 0
        self.book_page = 0
        self.book_total_override = None
        self.current_book_tid = ""  # 粘贴后清空
        self.app._refresh_vcs_tree()
        self.render()
        messagebox.showinfo("成功", f"已创建一个新的分支并挂载到当前步骤下。", parent=self.app.root)

    def _book_ctx_move_branch(self, tid, cmid):
        # 收集所有其他任务
        all_tasks = [(ctid, ct) for ctid, ct in self.vcs.tasks().items() if ctid != tid]
        if not all_tasks:
            messagebox.showinfo("提示", "系统中没有其他的可移动分支。", parent=self.app.root)
            return
            
        win = tk.Toplevel(self.app.root)
        win.title("移动分支")
        win.geometry("300x400")
        win.transient(self.app.root)
        win.grab_set()
        win.configure(bg="#c0c0c0")
        
        tk.Label(win, text="选择要移动并挂载到当前步骤的分支：", bg="#c0c0c0", font=("SimSun", 9)).pack(pady=10)
        lb = tk.Listbox(win, font=("SimSun", 10), bg="#ffffff", relief="sunken", bd=2)
        lb.pack(fill="both", expand=True, padx=10, pady=5)
        
        for _ctid, c in all_tasks:
            lb.insert("end", c.get("name", "未命名"))
            
        def do_move():
            sel = lb.curselection()
            if not sel: return
            target_tid, target_task = all_tasks[sel[0]]
            
            # B4 修复：防止移动到自己的子孙节点造成死循环
            _chk = tid
            while _chk:
                if _chk == target_tid:
                    messagebox.showwarning("错误", "不能将分支移动到自己或其子分支下！", parent=win)
                    return
                _chk = self.vcs.tasks().get(_chk, {}).get("parent", "")
                
            # H1 修复：防止书架全空
            roots = [ct for ct in self.vcs.tasks().values() if not ct.get("parent")]
            if not target_task.get("parent") and len(roots) <= 1:
                messagebox.showwarning("错误", "不能移动唯一的主分支，否则书架将变空！", parent=win)
                return
                
            if target_task.get("parent") == tid and target_task.get("base_commit") == cmid:
                messagebox.showinfo("提示", "该分支已经在此步骤下，无需移动。", parent=win)
                win.destroy()
                return
                
            # 执行物理移动
            target_task["parent"] = tid
            target_task["base_commit"] = cmid
            self.vcs._save_state()
            win.destroy()
            self.app._refresh_vcs_tree()
            self.render()
            messagebox.showinfo("成功", f"分支「{target_task.get('name')}」已移动至此。", parent=self.app.root)
            
        tk.Button(win, text="确认移动", command=do_move, bg="#c0c0c0", relief="raised", bd=2).pack(pady=10)

    def _book_ctx_rename(self, cmid):
        _t, cm = self.vcs.find_commit(cmid)
        if not cm: return
        new_name = tk.simpledialog.askstring("重命名", "请输入新的步骤名称：", initialvalue=cm.get("name", ""), parent=self.app.root)
        if new_name and new_name.strip():
            cm["name"] = new_name.strip()
            self.vcs._save_state()
            self.render()
            self._show_info()

    def _book_ctx_delete(self, tid, cmid):
        task = self.vcs.tasks().get(tid)
        if not task: return
        commits = task.get("commits", [])
        
        if not commits or commits[-1]["id"] != cmid:
            messagebox.showwarning("无法删除", "为了保持版本链完整，只能删除最新的步骤。请先“废除”其后方的分支。", parent=self.app.root)
            return
            
        if messagebox.askyesno("删除", "确定删除最新这一步吗？\n文件将会恢复到该步修改前的状态。", parent=self.app.root):
            self.vcs.rollback_commit(cmid)
            commits.pop()
            self.vcs._save_state()
            self.render()

    def _book_ctx_abort(self, tid, cmid):
        task = self.vcs.tasks().get(tid)
        if not task: return
        commits = task.get("commits", [])
        
        idx = next((i for i, c in enumerate(commits) if c["id"] == cmid), -1)
        if idx == -1 or idx == len(commits) - 1:
            messagebox.showinfo("提示", "这已经是最新步骤，无需废除。", parent=self.app.root)
            return
            
        if messagebox.askyesno("废除分支", f"确定废除「{commits[idx].get('name')}」之后的 {len(commits)-idx-1} 个步骤吗？\n此操作不可逆！", icon="warning", parent=self.app.root):
            task["commits"] = commits[:idx+1]
            self.vcs._save_state()
            self.render()

    def _copy(self, text):
        try:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(text or "")
        except Exception:
            pass

    def _commit_name(self, cid):
        if not self.vcs:
            return ""
        _t, c = self.vcs.find_commit(cid)
        return c.get("name", "") if c else ""

    # ---------- 选择/导航 ----------
    def selected(self):
        return self.sel

    def select_task(self, tid):
        self.sel = ("task", tid)
        if getattr(self, "view_mode", "tree") == "shelf":
            self.render()
        else:
            self._draw_selection()
        self._show_info()

    def select_commit(self, cid):
        self.sel = ("commit", cid)
        if getattr(self, "view_mode", "tree") == "shelf":
            self.render()
        else:
            self._draw_selection()
        self._show_info()

    def _nav_lane(self, d):
        if not self.items:
            return
        cur = ("commit:" + self.sel[1]) if self.sel[0] == "commit" else \
              ("task:" + self.sel[1]) if self.sel[0] == "task" else self.items[0]
        # 按列分组
        lanes = self.lane_items
        idx = 0
        for i, lane in enumerate(lanes):
            if cur in lane:
                idx = i
                break
        idx = max(0, min(len(lanes) - 1, idx + d))
        if lanes and lanes[idx]:
            key = lanes[idx][0]
            self.sel = ("commit", key.split(":", 1)[1])
            self.scroll_to_sel()
            self._draw_selection()
            self._show_info()

    def _nav_item(self, d):
        if getattr(self, "view_mode", "tree") == "shelf":
            return
        if not self.items:
            return
        cur = ("commit:" + self.sel[1]) if self.sel[0] == "commit" else \
              ("task:" + self.sel[1]) if self.sel[0] == "task" else None
        if cur not in self.items:
            self.sel = ("commit", self.items[0].split(":", 1)[1])
        else:
            i = self.items.index(cur)
            i = max(0, min(len(self.items) - 1, i + d))
            self.sel = ("commit", self.items[i].split(":", 1)[1])
        self.scroll_to_sel()
        self._draw_selection()
        self._show_info()

    def toggle_collapse(self, tid):
        if tid in self.collapsed:
            self.collapsed.discard(tid)
        else:
            self.collapsed.add(tid)
        self.render()

    # ---------- 滚动定位 ----------
    def scroll_to(self, tid, vertical=False):
        """定位到某任务：默认只横向移动，纵向保持在顶部（主干不会被切掉）。"""
        p = self.pos.get("task:" + tid)
        if not p:
            return
        y = None
        if vertical:
            commits = (self.vcs.tasks().get(tid) or {}).get("commits", []) if self.vcs else []
            if commits:
                y = self.pos.get("commit:" + commits[-1]["id"], (0, None))[1]
        self._scroll_center(p[0], y)

    def scroll_to_sel(self):
        kind, sid = self.sel
        p = self.pos.get(("%s:%s" % (kind, sid)))
        if p:
            self._scroll_center(p[0], p[1])

    def _scroll_center(self, x, y=None):
        try:
            region = self.canvas.cget("scrollregion").split()
            total_w = float(region[2]) if len(region) > 2 else 0
            total_h = float(region[3]) if len(region) > 3 else 0
            vis_w = max(1, self.canvas.winfo_width())
            vis_h = max(1, self.canvas.winfo_height())
            if total_w > vis_w:
                self.canvas.xview_moveto(max(0.0, min(1.0, (x - vis_w / 2) / (total_w - vis_w))))
            if y is not None and total_h > vis_h:
                self.canvas.yview_moveto(max(0.0, min(1.0, (y - vis_h / 2) / (total_h - vis_h))))
        except Exception:
            pass

    # ---------- 渲染 ----------
    def set_data(self, vcs):
        self.vcs = vcs
        self.render()

    # ---------- 根系布局 ----------
    def _layout(self, viewport_w=0, viewport_h=0):
        """主干居中；子分支按层向左右外扩；越深横向间距不变但节点/线更细。"""
        tasks = list(self.vcs.state.get("tasks", {}).items())
        tmap = dict(tasks)
        children = dict((tid, []) for tid, _ in tasks)
        roots = []
        for tid, t in tasks:
            p = t.get("parent") or ""
            if p and p in children:
                children[p].append(tid)
            else:
                roots.append(tid)
        if not roots:
            roots = [tasks[0][0]]

        next_r = [0]
        next_l = [0]

        def take(side):
            if side > 0:
                next_r[0] += 1
                return next_r[0]
            next_l[0] += 1
            return -next_l[0]

        slot = {roots[0]: 0}
        depth = {roots[0]: 0}
        for i, tid in enumerate(roots[1:], start=1):
            slot[tid] = take(1 if i % 2 == 1 else -1)
            depth[tid] = 0

        def assign(tid, d):
            for i, ch in enumerate(children.get(tid, [])):
                if d == 0:
                    side = 1 if i % 2 == 0 else -1      # 主干的第一层子分支左右交替
                else:
                    side = 1 if slot.get(tid, 0) > 0 else -1   # 之后沿父分支同侧继续外扩
                if slot.get(tid, 0) == 0 and d > 0:
                    side = 1 if i % 2 == 0 else -1
                slot[ch] = take(side)
                depth[ch] = d + 1
                assign(ch, d + 1)

        for tid in roots:
            assign(tid, depth.get(tid, 0))
        for tid, _t in tasks:
            if tid not in slot:
                slot[tid] = take(1)
                depth[tid] = 0

        rows = {}
        row_of_commit = {}

        def place(tid, start):
            commits = tmap[tid].get("commits", [])
            if tid in self.collapsed or not commits:
                rows[tid] = (start, start)
                return
            for i, cm in enumerate(commits):
                row_of_commit[cm["id"]] = start + i
            rows[tid] = (start, start + len(commits) - 1)

        def place_tree(tid):
            p = tmap[tid].get("parent") or ""
            start = 0
            if p in rows:
                base = tmap[tid].get("base_commit") or ""
                if base in row_of_commit:
                    start = row_of_commit[base] + 1
                else:
                    start = rows[p][1] + 1
            place(tid, start)
            for ch in children.get(tid, []):
                place_tree(ch)

        for tid in roots:
            place_tree(tid)

        max_row = max([r[1] for r in rows.values()] + [0])
        span = max([abs(v) for v in slot.values()] + [0])
        content_w = self.LEFT + (2 * span + 1) * self.STEP + self.RIGHT
        content_h = self.TOP + (max_row + 1) * self.ROW_H + self.BOTTOM

        # 内容比视口窄时整体水平居中（否则主干会贴在最左边）
        vw = max(int(viewport_w or 0), 0)
        shift = max(0, (vw - content_w) // 2)
        total_w = max(content_w, vw)
        total_h = max(content_h, int(viewport_h or 0))

        def x_of(tid):
            return shift + self.LEFT + (slot[tid] + span) * self.STEP + self.STEP // 2

        def y_of(row):
            return self.TOP + row * self.ROW_H

        return dict(tasks=tasks, tmap=tmap, children=children, roots=roots,
                    slot=slot, depth=depth, rows=rows, row_of_commit=row_of_commit,
                    x_of=x_of, y_of=y_of, total_w=total_w, total_h=total_h)

    @staticmethod
    def _node_r(d):
        """方块半边长：越深越小（层层递减）。"""
        return 6 if d == 0 else (5 if d == 1 else (4 if d == 2 else 3))

    @staticmethod
    def _node_w(d):
        return 2 if d == 0 else 1

    @staticmethod
    def _node_color(d):
        # Win98：全部黑线，只有粗细区分层级
        return "#000000"

    def render(self):
        # 每次重绘前，强制销毁所有因为就地编辑而残留的输入框
        for w in self.holder.winfo_children():
            if isinstance(w, tk.Entry):
                w.destroy()

        c = self.canvas
        c.delete("all")
        self.items = []
        self.pos = {}
        self.radii = {}
        self.hdr_bbox = {}
        self.lane_items = []
        self.branch_box_rects = []
        
        # 分支树相关的界面设置为纯白背景
        if getattr(self, "view_mode", "tree") in ("shelf", "book"):
            c.config(bg="#ffffff")
        else:
            c.config(bg="#c0c0c0")
            
        if not self.vcs:
            return

        if self.view_mode == "shelf":
            self._render_shelf()
            return
        if self.view_mode == "book":
            self._render_book()
            return

        vw = max(self.canvas.winfo_width(), 1)
        vh = max(self.canvas.winfo_height(), 1)
        if vw <= 1:      # 首帧尚未布局，用窗口宽度兜底，避免一开始贴左边
            vw = max(self.canvas.master.winfo_width(), 480)
        if vh <= 1:
            vh = 220
        lay = self._layout(vw, vh)
        tasks = lay["tasks"]
        if not tasks:
            return
        cur = self.vcs.state.get("current")
        x_of, y_of = lay["x_of"], lay["y_of"]
        rows, slot, depth = lay["rows"], lay["slot"], lay["depth"]
        children = lay["children"]
        tmap = lay["tmap"]

        c.configure(scrollregion=(0, 0, max(lay["total_w"], 420), max(lay["total_h"], 220)))

        # ---------- 分叉连线（先画，压在节点下）----------
        for tid, t in tasks:
            p = t.get("parent") or ""
            if p not in tmap:
                continue
            base = t.get("base_commit") or ""
            pr = lay["row_of_commit"].get(base)
            if pr is None:
                pr = rows[p][1]
            px, py = x_of(p), y_of(pr)
            cx, cy = x_of(tid), y_of(rows[tid][0])
            d = depth.get(tid, 1)
            # 直线折线（Win98 无平滑曲线）：竖→横→竖
            c.create_line(px, py, px, py + 12, cx, py + 12, cx, cy,
                          fill="#000000", width=1,
                          dash=(2, 2) if d > 1 else ())

        # ---------- 每个任务的枝干与节点 ----------
        for tid, t in tasks:
            d = depth.get(tid, 0)
            x = x_of(tid)
            color = self._node_color(d)
            lw = self._node_w(d)
            r = self._node_r(d)
            commits = t.get("commits", [])
            collapsed = tid in self.collapsed
            tag_t = "task:" + tid
            first_y = y_of(rows[tid][0])
            last_y = y_of(rows[tid][1])

            # 枝干竖线
            if rows[tid][1] >= rows[tid][0]:
                c.create_line(x, first_y, x, last_y, fill="#000000", width=lw,
                              dash=(1, 2) if collapsed else ())

            # 任务名：黑字 + 灰底标签牌（遮住穿过的连线，Win98 小标签观感）
            is_cur = (tid == cur)
            name = t.get("name", tid) + (" ★" if is_cur else "")
            ny = first_y - r - 18
            self.pos[tag_t] = (x, ny)
            tid_item = c.create_text(x, ny, text=name, anchor="s",
                                     fill="#000000",
                                     font=("SimSun", 9, "bold" if is_cur else "normal"),
                                     tags=("hdr", tag_t))
            bb = c.bbox(tid_item)
            if bb:
                # 灰底 + 1px 黑框标签牌（Win98 分组标签），先压到文字下方遮住穿过的线。
                # 当前任务只用“文字加粗”区分，焦点框统一由 _draw_selection 画，避免双框。
                plate = c.create_rectangle(bb[0] - 4, bb[1] - 2, bb[2] + 4, bb[3] + 2,
                                           fill="#c0c0c0", outline="#000000", width=1,
                                           tags=("hdr", tag_t))
                c.tag_lower(plate, tid_item)
                self.hdr_bbox[tid] = c.bbox(plate)

            if collapsed:
                c.create_rectangle(x - r, first_y - r, x + r, first_y + r,
                                   fill="#c0c0c0", outline="#000000", width=lw,
                                   tags=("node", tag_t))
                c.create_text(x, first_y, text="+%d" % len(commits),
                              fill="#000000", font=("SimSun", 7), tags=("node", tag_t))
                self.pos[tag_t + "#c"] = (x, first_y)
                self.radii[tag_t] = r
                continue

            lane_list = []
            for cm in commits:
                cid = cm["id"]
                key = "commit:" + cid
                y = y_of(lay["row_of_commit"][cid])
                self.pos[key] = (x, y)
                self.radii[key] = r
                self.items.append(key)
                lane_list.append(key)
                # Win98：方块节点。主干/当前任务实心黑，其余空心黑框
                filled = is_cur or d == 0
                c.create_rectangle(x - r, y - r, x + r, y + r,
                                   fill=("#000000" if filled else "#c0c0c0"),
                                   outline="#000000", width=1,
                                   tags=("node", key, tag_t))
                label = cm.get("name", "")
                maxc = 24 if d == 0 else 14
                if len(label) > maxc:
                    label = label[:maxc - 1] + "…"
                # 右分支标签朝右、左分支朝左，避免压住主干
                if slot[tid] > 0:
                    tx, anchor = x + r + 5, "w"
                elif slot[tid] < 0:
                    tx, anchor = x - r - 5, "e"
                else:
                    tx, anchor = x + r + 5, "w"
                c.create_text(tx, y, text=label, anchor=anchor,
                              fill="#000000" if d == 0 or is_cur else "#404040",
                              font=("SimSun", 9 if d == 0 else 8),
                              tags=("node", key, tag_t))
            self.lane_items.append(lane_list)

        self._draw_selection()

    def _render_shelf(self):
        c = self.canvas
        c.xview_moveto(0)
        vw = max(self.canvas.winfo_width(), 1)
        vh = max(self.canvas.winfo_height(), 1)
        if vw <= 1: vw = 800
        if vh <= 1: vh = 400
        
        # 过滤掉有 parent 的子任务，只显示根节点（主书）
        tasks = [(tid, t) for tid, t in self.vcs.tasks().items() if not t.get("parent")]
        
        bw = self.book_size
        gap_x = 40
        grid_left = 40
        avail_w = max(bw, vw - grid_left * 2)
        calc_cols = max(1, (avail_w + gap_x) // (bw + gap_x))
        self.cols = calc_cols
        self.per_page = self.cols * self.rows
        
        total = len(tasks)
        calc_total = max(1, (total + self.per_page - 1) // self.per_page)
        total_pages = getattr(self, "total_pages_override", calc_total)
        self.total_pages_cached = total_pages
        self.page = max(0, min(self.page, total_pages - 1))
        
        # 绘制当前目录路径（变小，加白底框）
        path_text = getattr(self, "shelf_path", os.path.abspath(BASE_DIR)).replace("\\", "/")
        if len(path_text) > 22:
            path_text = "..." + path_text[-19:]
        t_id = c.create_text(24, 24, text=path_text, anchor="nw", font=("SimSun", 10, "bold"), fill="#000000", tags=("path_base", "path_bar",))
        bb = c.bbox(t_id)
        if bb:
            r_id = c.create_rectangle(bb[0]-6, bb[1]-4, bb[2]+6, bb[3]+4, fill="#ffffff", outline="#000000", width=1, tags=("path_base", "path_bar",))
            c.tag_lower(r_id, t_id)
            pass
        
        # 绘制“新建任务”按钮（立体风格）
        btn_x = vw - 120
        btn_y = 15
        btn_w = 90
        btn_h = 24
        c.create_rectangle(btn_x+2, btn_y+2, btn_x+btn_w+2, btn_y+btn_h+2, fill="#a0a0a0", outline="") # 阴影
        c.create_rectangle(btn_x, btn_y, btn_x+btn_w, btn_y+btn_h, fill="#f4f4f4", outline="#000000", width=2, tags=("new_task_btn",))
        c.create_text(btn_x+btn_w/2, btn_y+btn_h/2, text="+ 新建任务", font=("SimSun", 10, "bold"), fill="#000080", tags=("new_task_btn",))
        c.tag_bind("new_task_btn", "<Button-1>", lambda e: self.app.vcs_new_task(parent=""))
        c.tag_bind("new_task_btn", "<Enter>", lambda e: c.config(cursor="hand2"))
        c.tag_bind("new_task_btn", "<Leave>", lambda e: c.config(cursor=""))

        # 绘制书本网格
        start_idx = self.page * self.per_page
        page_tasks = tasks[start_idx:start_idx + self.per_page]
        
        grid_top = 70
        bh = int(self.book_size * 1.35) # 竖长书本
        gap_y = 30
        
        # 计算整体居中偏移
        total_row_w = self.cols * bw + (self.cols - 1) * gap_x
        start_x = max(grid_left, (vw - total_row_w) // 2)
        
        for i, (tid, t) in enumerate(page_tasks):
            r = i // self.cols
            col = i % self.cols
            
            x1 = start_x + col * (bw + gap_x)
            y1 = grid_top + r * (bh + gap_y)
            x2 = x1 + bw
            y2 = y1 + bh
            
            name = t.get("name", tid)
            is_sel = self.sel == ("task", tid)
            
            # 1. 极简浅灰阴影
            c.create_rectangle(x1+4, y1+4, x2+4, y2+4, fill="#d0d0d0", outline="")
            
            # 2. 纯白书本封面
            c.create_rectangle(x1, y1, x2, y2, fill="#ffffff", outline="#000000", width=2, tags=("node", "task:"+tid))
            
            if len(name) > 6:
                display_name = name[:5] + "…"
            else:
                display_name = name
                
            # 3. 书名居中
            c.create_text((x1+x2)/2, y1+40, text=display_name, font=("SimSun", 12, "bold"), fill="#000000", width=bw-10, tags=("node", "task:"+tid))
            
            # 4. 步数（底部居中）
            commit_cnt = len(t.get("commits", []))
            c.create_text((x1+x2)/2, y1+80, text=f"📄 {commit_cnt} 步", font=("SimSun", 9), fill="#888888", tags=("node", "task:"+tid))
            
            # 7. 选中角标（大 L 框）
            if is_sel:
                d = 8
                L = 24
                w = 3
                c.create_line(x1-d, y1-d, x1-d+L, y1-d, fill="#000000", width=w, tags=("selring",))
                c.create_line(x1-d, y1-d, x1-d, y1-d+L, fill="#000000", width=w, tags=("selring",))
                c.create_line(x2+d, y2+d, x2+d-L, y2+d, fill="#000000", width=w, tags=("selring",))
                c.create_line(x2+d, y2+d, x2+d, y2+d-L, fill="#000000", width=w, tags=("selring",))
                
            self.pos["task:"+tid] = ((x1+x2)/2, (y1+y2)/2)
            self.items.append("task:"+tid)
            
        # 绘制分页符（固定在底部居中，加白底框）
        # 修复：动态计算当前页实际占据的行数，防止只有1本书时强行留出2行高度，导致页码被挤到屏幕外
        _actual_rows = max(1, (len(page_tasks) + self.cols - 1) // self.cols) if page_tasks else 0
        if _actual_rows == 0:
            calc_page_y = grid_top + 20
        else:
            calc_page_y = grid_top + _actual_rows * (bh + gap_y) + 20
        page_y = max(calc_page_y, vh - 30)
        p_text = f"<{self.page + 1}/{total_pages}>"
        pt_id = c.create_text(vw/2, page_y, text=p_text, font=("SimSun", 12, "bold"), fill="#000000", tags=("page_btn",))
        p_bb = c.bbox(pt_id)
        if p_bb:
            pr_id = c.create_rectangle(p_bb[0]-10, p_bb[1]-4, p_bb[2]+10, p_bb[3]+4, fill="#ffffff", outline="#000000", width=1, tags=("page_btn",))
            c.tag_lower(pr_id, pt_id)
        
        # 设置滚动区域
        c.configure(scrollregion=(0, 0, max(1, vw-2), max(vh-2, page_y + 30)))

    def _render_book(self):
        c = self.canvas
        c.xview_moveto(0)          # 每次重绘回到最左，避免上次横向滚动残留
        vw = max(self.canvas.winfo_width(), 1)
        vh = max(self.canvas.winfo_height(), 1)
        if vw <= 1: vw = 800
        if vh <= 1: vh = 400
        
        tid = getattr(self, "current_book_tid", "")
        t = self.vcs.tasks().get(tid, {}) if self.vcs else {}
        tname = t.get("name", "未命名")
        
        # 1. 顶部路径：多段式面包屑导航
        base_path = getattr(self, "shelf_path", os.path.abspath(BASE_DIR)).replace("\\", "/")
        path_parts = []
        curr_p = t.get("parent")
        while curr_p:
            pt = self.vcs.tasks().get(curr_p)
            if pt:
                path_parts.insert(0, (pt.get("name", "未命名"), curr_p))
                curr_p = pt.get("parent")
            else:
                break
        path_parts.append((tname, tid))

        # 绘制基础路径（仅用白底框套住文字）
        cur_x = 24
        cur_y = 29
        base_id = c.create_text(cur_x, cur_y, text=base_path, anchor="w", font=("Microsoft YaHei", 10, "bold"), fill="#000000", tags=("path_base", "path_bar"))
        bb = c.bbox(base_id)
        if bb:
            r_id = c.create_rectangle(bb[0]-6, bb[1]-4, bb[2]+6, bb[3]+4, fill="#ffffff", outline="#000000", width=1, tags=("path_base", "path_bar"))
            c.tag_lower(r_id, base_id)
            cur_x = bb[2] + 4

        # 绘制层级任务名
        for i, (pname, ptid) in enumerate(path_parts):
            # 画斜杠
            slash_id = c.create_text(cur_x, cur_y, text=" / ", anchor="w", font=("SimSun", 10, "bold"), fill="#666666")
            cur_x = c.bbox(slash_id)[2] + 2
            
            # 画任务名
            is_last = (i == len(path_parts) - 1)
            tag_name = f"path_part_{ptid}"
            part_id = c.create_text(cur_x, cur_y, text=pname, anchor="w", font=("Microsoft YaHei", 10, "bold" if is_last else "normal"), fill="#000000", tags=(tag_name,))
            cur_x = c.bbox(part_id)[2] + 4
            
            # 如果不是最后一级，绑定跳转事件
            if not is_last:
                def jump(e, target_tid=ptid):
                    self.current_book_tid = target_tid
                    self.book_page = 0
                    self.book_total_override = None
                    self.selected_book_step = None
                    self.branch_scroll_x = 0
                    self.render()
                c.tag_bind(tag_name, "<Button-1>", jump)
                c.tag_bind(tag_name, "<Enter>", lambda e: c.config(cursor="hand2"))
                c.tag_bind(tag_name, "<Leave>", lambda e: c.config(cursor=""))
        
        # 2. 绘制边框（大 L 角标）
        margin = 40
        left = margin
        top = 60
        right = vw - margin
        bottom = vh - margin
        # 左上角
        c.create_line(left, top, left+40, top, fill="#000000", width=4)
        c.create_line(left, top, left, top+40, fill="#000000", width=4)
        # 右下角在算出本页底部后再画（见下方 page_y）
        
        # 3. 大标题
        c.create_text(left+20, top+20, text=tname, anchor="nw", font=("Microsoft YaHei UI", 22, "bold"), fill="#000000")
        
        # 4. 文本内容区（步骤列表）
        commits = t.get("commits", [])
        
        # 动态计算每页行数，防止被底部遮挡
        avail_h = max(50, (bottom - 40) - (top + 80))
        items_per_page = max(1, avail_h // 50)
        
        calc_total = max(1, (len(commits) + items_per_page - 1) // items_per_page)
        total_pages = getattr(self, "book_total_override", calc_total)
        if total_pages is None:
            total_pages = calc_total
            
        self.book_total_pages_cached = total_pages
        self.book_page = getattr(self, "book_page", 0)
        self.book_page = max(0, min(self.book_page, total_pages - 1))
        
        start_idx = self.book_page * items_per_page
        page_commits = commits[start_idx:start_idx + items_per_page]
        
        self.book_step_rects = []
        
        # 如果这本书没有任何记录，给个明显提示，防止误以为卡死
        if not commits:
            # 限定在页框内换行居中；同时上移让开底部页码，避免重叠
            msg_w = max(120, (right - left) - 40)
            page_y_guess = max(top + 120, bottom - 25)
            msg_y = min(max(top + 110, (top + bottom) // 2 - 10), page_y_guess - 40)
            c.create_text((left + right) / 2, msg_y,
                          text="（这里是一片空白，此分支下还没有任何记录）",
                          font=("SimSun", 12), fill="#888888",
                          width=msg_w, justify="center")
            
        # 确保即使没有记录，底部占位计算也生效
        if not page_commits:
            avail_h = max(50, (bottom - 40) - (top + 80))
            items_per_page = max(1, avail_h // 50)
        
        current_y = top + 80
        for i, cm in enumerate(page_commits):
            sy = current_y
            step_name = cm.get("name", "未命名步骤")
            owner_tid = cm.get("_owner_tid", tid)
            
            # 画文本文档图标，点击它直接弹出详情
            icon_id = c.create_text(left+5, sy, text="📄", anchor="nw", font=("Microsoft YaHei", 12), tags=("doc_icon",))
            c.tag_bind("doc_icon", "<Button-1>", lambda e, cid=cm["id"]: self._show_commit_popup(cid))

            # 画步骤名（向右偏移）
            # 字体改用微软雅黑，数字改为 Consolas 更清晰（这里统一用雅黑）
            c.create_text(left+30, sy, text=step_name, anchor="nw", font=("Microsoft YaHei", 12), fill="#111111")
            
            # 判断这行是否有子分支（精确去原任务里找，绝对不乱查）
            has_child = len(self._get_sub_branches(owner_tid, cm.get("id"))) > 0
            if has_child:
                c.create_line(left+30, sy+24, left+190, sy+24, fill="#000000", width=2)
                c.create_line(left+30, sy+28, left+190, sy+28, fill="#000000", width=1)
                
            # 记录文字点击区域（用于展开下方分支）
            self.book_step_rects.append((left+30, sy-10, right-20, sy+35, cm["id"]))
            
            current_y += 50
            
            # 如果是选中的步骤，就在正下方画出这块区域
            if getattr(self, "selected_book_step", None) == cm["id"]:
                exp_h = self._render_branch_expand(c, cm["id"], owner_tid, left+30, current_y, right-30)
                current_y += exp_h + 20
            
        # 5. 底部居中分页符（动态下移，避免重叠）
        page_y = max(current_y + 40, bottom - 25)
        p_text = f"<{self.book_page + 1}/{total_pages}>"
        pt_id = c.create_text(vw/2, page_y, text=p_text, font=("SimSun", 12, "bold"), fill="#000000", tags=("book_page_btn",))
        p_bb = c.bbox(pt_id)
        if p_bb:
            pr_id = c.create_rectangle(p_bb[0]-10, p_bb[1]-4, p_bb[2]+10, p_bb[3]+4, fill="#ffffff", outline="#000000", width=1, tags=("book_page_btn",))
            c.tag_lower(pr_id, pt_id)
        
        # 右下角 L：始终贴在本页最底部（内容超出一屏时跟随页面，不再停在视口中段），并置于最底层
        frame_bottom = bottom if page_y <= bottom - 5 else page_y + 30
        c.create_line(right, frame_bottom, right-40, frame_bottom, fill="#000000", width=4, tags=("page_corner",))
        c.create_line(right, frame_bottom, right, frame_bottom-40, fill="#000000", width=4, tags=("page_corner",))
        c.tag_lower("page_corner")

        # 顶部路径可能超出一屏：把内容宽度并入滚动区域，横向滚动条即可滑动查看
        content_w = max(vw - 2, cur_x + 10)
        c.configure(scrollregion=(0, 0, max(1, content_w), max(1, page_y + 40, frame_bottom + 10)))
        # 强制更新画布

    def _get_sub_branches(self, tid, cmid):
        # 严格匹配：只找挂载在当前任务当前提交下的子分支，绝不乱认亲戚
        return [ct for ct in self.vcs.tasks().values() if ct.get("parent") == tid and ct.get("base_commit") == cmid]

    def _get_all_sub_branches(self, tid):
        """当前书的全部子孙分支（含更深层），返回 [(task, depth), ...]。
        只列第一层会导致「分支不全」，深层分支必须一并列出。"""
        tasks = self.vcs.tasks() if self.vcs else {}
        out, seen = [], set()

        def walk(parent, depth):
            for ctid, ct in tasks.items():
                if ctid in seen or ct.get("parent") != parent:
                    continue
                seen.add(ctid)
                out.append((ct, depth))
                walk(ctid, depth + 1)

        walk(tid, 0)
        return out

    def _render_branch_expand(self, c, cmid, tid, x1, y1, x2):
        # 列出全部子孙分支，而不是只列直接子分支
        sub_branches = self._get_all_sub_branches(tid)
        
        h = 170
        box_w = 90              # 分支格基准宽，必要时自适应缩小
        box_h = 70
        gap = 24
        step = box_w + gap
        n_box_w = 90            # 右侧「分支 N」占位格固定宽

        n = len(sub_branches)
        min_box_w = 64
        max_panel_w = (x2 + 10) - (x1 - 10)     # 页框允许的面板最大宽度
        max_branch_w = max_panel_w - 125        # 全宽面板里可放格子的最大宽度
        # 先缩格子，尽量把全部分支塞进一排
        if n > 1:
            fit_w = (max_branch_w - (n - 1) * gap) // n
            if fit_w < box_w:
                box_w = max(min_box_w, fit_w)
        step = box_w + gap
        need_w = (n * box_w + (n - 1) * gap) if n else 0

        # 面板按内容收缩：内容少就窄，最多铺满页框
        panel_w = min(need_w + 131, max_panel_w)
        panel_x2 = (x1 - 10) + panel_w

        n_bx2 = panel_x2 - 5
        n_bx1 = n_bx2 - n_box_w
        left_view_x1 = x1 - 6
        left_view_x2 = n_bx1 - gap
        avail_left_w = left_view_x2 - left_view_x1

        if n == 0:
            pad, total_branch_w, max_scroll = 0, 1, 0
        elif need_w <= avail_left_w:
            pad = (avail_left_w - need_w) // 2      # 整排居中，保持自然间距
            total_branch_w = avail_left_w
            max_scroll = 0
        else:
            pad = max(0, (avail_left_w - box_w) // 2)
            total_branch_w = max(1, 2 * pad + n * step - gap)
            max_scroll = max(0, total_branch_w - avail_left_w)
        
        offset_x = getattr(self, "branch_scroll_x", 0)
        offset_x = max(0, min(offset_x, max_scroll))
        self.branch_scroll_x = offset_x  # 回写，保持内外状态一致
        
        # 1. 面板阴影 + 浅灰底板 + 蓝色标题栏
        # 阴影层（向右下偏移4px，与书本保持绝对一致的浅灰）
        c.create_rectangle(x1-10+4, y1-10+4, panel_x2+4, y1+h+4, fill="#d0d0d0", outline="")
        # 主体面板（恢复 2px 黑边）
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+h, fill="#f4f4f4", outline="#000000", width=2)
        # 蓝色标题栏（恢复 2px 黑边）
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+15, fill="#000080", outline="#000000", width=2)
        c.create_text(x1-2, y1+2, text="分支详情 / 子分支列表", anchor="w", fill="#ffffff", font=("SimSun", 10, "bold"))
        
        # 内容区垂直下移，避开标题栏
        cy1 = y1 + 25
        cy2 = cy1 + box_h
        
        # 2. 分支方块（完整绘制，靠遮罩截断）
        self.branch_box_rects = []
        name_font = tkfont.Font(family="SimSun", size=9)
        title_font = ("SimSun", 9, "bold") if box_w < 78 else ("SimSun", 11, "bold")
        max_text_w = box_w - 14
        for i, (cb, depth) in enumerate(sub_branches):
            bx1 = left_view_x1 + pad + i * step - offset_x
            bx2 = bx1 + box_w
            title = f"分支 {i+1}"
            name = cb.get("name", "") or ""
            # 按实际字宽截断，保证名称不超出方块右边框
            label = "名称: " + name
            if name_font.measure(label) > max_text_w:
                while name and name_font.measure("名称: " + name + "…") > max_text_w:
                    name = name[:-1]
                label = ("名称: " + name + "…") if name else "名称: …"

            c.create_rectangle(bx1+3, cy1+3, bx2+3, cy2+3, fill="#a0a0a0", outline="")
            c.create_rectangle(bx1, cy1, bx2, cy2, fill="#ffffff", outline="#000000", width=2)
            c.create_text(bx1+8, cy1+8, text=title, anchor="nw", font=title_font)
            c.create_text(bx1+8, cy1+40, text=label, anchor="nw", font=("SimSun", 9))

            self.branch_box_rects.append((bx1, cy1, bx2, cy2, cb["id"]))
            c.tag_bind(c.create_rectangle(bx1, cy1, bx2, cy2, outline="", fill=""), "<Button-1>", lambda e, target_tid=cb["id"]: self._jump_to_branch(target_tid))

        # 绝对遮罩：严格限制在面板内部（避开左侧和右侧的黑框），高度避开底部滑动条
        c.create_rectangle(x1-8, y1+16, left_view_x1, cy2+30, fill="#f4f4f4", outline="")
        c.create_rectangle(left_view_x2, y1+16, panel_x2+8, cy2+30, fill="#f4f4f4", outline="")

        # ==================== 精确无缝蒙版 ====================
        # 巧妙避开 2px 的黑边框（外扩 11px，内缩 9px），彻底解决灰黑边与漏边问题
        c.create_rectangle(-9999, cy1-15, x1-11, cy2+30, fill="#ffffff", outline="") # 左外白
        c.create_rectangle(x1-9, cy1-15, left_view_x1, cy2+30, fill="#f4f4f4", outline="") # 左内灰
        c.create_rectangle(left_view_x2, cy1-15, panel_x2+9, cy2+30, fill="#f4f4f4", outline="") # 右内灰
        c.create_rectangle(panel_x2+11, cy1-15, 9999, cy2+30, fill="#ffffff", outline="") # 右外白
        
        # 覆盖完毕后，重画面板边框和蓝色标题栏，保证绝对无缝
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+h, fill="", outline="#000000", width=2)
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+15, fill="#000080", outline="#000000", width=2)
        c.create_text(x1-2, y1+2, text="分支详情 / 子分支列表", anchor="w", fill="#ffffff", font=("SimSun", 10, "bold"))

        # 3. 分支 N 方块（常驻右侧）
        bx1 = n_bx1
        bx2 = n_bx2
        if True:
            c.create_rectangle(bx1+3, cy1+3, bx2+3, cy2+3, fill="#a0a0a0", outline="")
            c.create_rectangle(bx1, cy1, bx2, cy2, fill="#ffffff", outline="#000000", width=2, tags=("branch_n_box",))
            c.create_text(bx1+8, cy1+8, text="分支", anchor="nw", font=("SimSun", 11, "bold"), tags=("branch_n_box",))
            c.create_text(bx1+45, cy1+8, text="N", anchor="nw", font=("SimSun", 11, "bold"), tags=("branch_n_box", "branch_n_text"))
            c.create_text(bx1+8, cy1+40, text="名称: ...", anchor="nw", font=("SimSun", 9), tags=("branch_n_box",))
            c.tag_bind("branch_n_box", "<Button-1>", lambda e: self._jump_to_n_branch(tid, cmid))

        # 4. 极简滑动条区域
        p_y1 = cy2 + 40
        p_y2 = p_y1 + 16
        
        # 轨道从左侧可视区起点，画到右侧N方块的边缘
        c.create_rectangle(left_view_x1, p_y1, n_bx2, p_y2, fill="#ffffff", outline="#000000", width=2, tags=("branch_scroll_track",))
        
        track_w = n_bx2 - left_view_x1
        visible_w = max(1, min(total_branch_w, avail_left_w))
        thumb_w = max(30, min(track_w, int(track_w * (visible_w / max(1, total_branch_w)))))
        
        if max_scroll > 0:
            thumb_x = left_view_x1 + int((offset_x / max_scroll) * (track_w - thumb_w))
        else:
            thumb_x = left_view_x1
            
        # 灰色滑块
        c.create_rectangle(thumb_x, p_y1+2, thumb_x+thumb_w, p_y2-2, fill="#c0c0c0", outline="#000000", width=1, tags=("branch_scroll_thumb",))
        
        # 保存交互边界数据
        self._branch_panel_bbox = (x1-10, y1-10, panel_x2, y1+h)
        self._branch_track_bbox = (left_view_x1, n_bx2)
        self._branch_max_scroll = max_scroll
        
        # 绑定拖拽事件（按下时接管鼠标，移动时实时计算比例）
        def _on_drag_start(e):
            self._dragging_thumb = True
            # 使用局部绑定，防止全局绑定干扰其他控件
            c.bind("<B1-Motion>", _on_drag_move)
            c.bind("<ButtonRelease-1>", _on_drag_end)
            
        def _on_drag_move(e):
            mx = c.canvasx(e.x)
            tx1, tx2 = self._branch_track_bbox
            tw = tx2 - tx1
            if tw > 0 and self._branch_max_scroll > 0:
                ratio = (mx - tx1) / tw
                ratio = max(0.0, min(1.0, ratio))
                new_scroll = int(ratio * self._branch_max_scroll)
                if new_scroll != getattr(self, "branch_scroll_x", 0):
                    self.branch_scroll_x = new_scroll
                    self.render()
                    
        def _on_drag_end(e):
            self._dragging_thumb = False
            c.unbind("<B1-Motion>")
            c.unbind("<ButtonRelease-1>")
            self._bind_events() # 恢复原本的鼠标事件
            
            # 取消吸附，直接停在当前拖拽的平滑位置
            self.branch_scroll_x = max(0, min(getattr(self, "branch_scroll_x", 0), self._branch_max_scroll))
            self.render()
            
        c.tag_bind("branch_scroll_thumb", "<Button-1>", _on_drag_start)
        
        # 重新补画面板整体边框，防止被遮罩误伤
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+h, fill="", outline="#000000", width=2)
        # 重新补画标题栏黑框
        c.create_rectangle(x1-10, y1-10, panel_x2, y1+15, fill="", outline="#000000", width=2)
        
        return h

    def _rename_current_book(self, tid=None):
        tid = tid or getattr(self, "current_book_tid", "")
        t = self.vcs.tasks().get(tid)
        if not t: return
        from tkinter import simpledialog
        new_name = simpledialog.askstring("重命名", "请输入新的书名：", initialvalue=t.get("name", ""), parent=self.app.root)
        if new_name and new_name.strip():
            t["name"] = new_name.strip()
            self.vcs._save_state()
            self.app._refresh_vcs_tree()
            self.render()

    def _jump_to_branch(self, target_tid):
        self.current_book_tid = target_tid
        self.book_page = 0
        self.book_total_override = None
        self.selected_book_step = None
        self.branch_scroll_x = 0
        self.render()
        
    def _jump_to_n_branch(self, tid, cmid):
        c = self.canvas
        bb = c.bbox("branch_n_text")
        if not bb: return
        
        # 仅仅隐藏“N”这个字，保留方框和“分支”、“名称”等
        c.itemconfig("branch_n_text", state="hidden")
        
        # 原地创建输入框，精准覆盖在“N”的位置
        entry = tk.Entry(self.holder, font=("SimSun", 11, "bold"), relief="solid", bd=1, bg="#ffffff", justify="center")
        entry.place(x=bb[0] - c.canvasx(0) - 2, y=bb[1] - c.canvasy(0) - 2, width=bb[2]-bb[0]+20, height=bb[3]-bb[1]+6)
        entry.focus_set()
        
        def finish_edit(save=True):
            entry.unbind("<Return>")
            entry.unbind("<Escape>")
            entry.unbind("<FocusOut>")
            if save:
                val = entry.get().strip()
                if val.isdigit():
                    sub_branches = self._get_all_sub_branches(tid)
                    if sub_branches:
                        idx = int(val)
                        idx = max(1, min(idx, len(sub_branches)))
                        target_tid = sub_branches[idx-1][0]["id"]
                        self._jump_to_branch(target_tid)
            entry.destroy()
            self.render()
            
        entry.bind("<Return>", lambda e: finish_edit(True))
        entry.bind("<Escape>", lambda e: finish_edit(False))
        entry.bind("<FocusOut>", lambda e: finish_edit(True))

    def _show_commit_popup(self, cmid):
        if not self.vcs: return
        _t, cm = self.vcs.find_commit(cmid)
        if not cm: return
        
        # 保证只存在一个弹窗
        if getattr(self, "commit_popup_win", None) and self.commit_popup_win.winfo_exists():
            self.commit_popup_win.destroy()
        
        tid = getattr(self, "current_book_tid", "")
        
        sub_branches = []
        for ctid, ct in self.vcs.tasks().items():
            if ct.get("parent") == tid and ct.get("base_commit") == cmid:
                sub_branches.append(ct.get("name", ctid))

        content = f"步骤：{cm.get('name', '')}\n时间：{cm.get('date', '')}\n来源：{cm.get('source', '')}\n\n"
        for f in cm.get("files", []):
            content += f"文件：{os.path.basename(f['path'])}\n改动：+{f.get('add',0)} / -{f.get('del',0)}\n"
            
        if sub_branches:
            content += "\n[此处开出的分支]\n" + "\n".join(["  - " + b for b in sub_branches])

        # 极简卡片式弹窗（带右下角半透明阴影）
        win = tk.Toplevel(self.app.root)
        self.commit_popup_win = win
        win.overrideredirect(True) # 隐藏原生标题栏
        # 尺寸大一点，留出 4px 阴影空间
        win.geometry("404x304")
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.95) # 整体微微透出背后的桌面或主界面
        win.configure(bg="#808080") # 阴影底色变深一点，因为透明后会显得淡
        
        # 居中显示
        self.app.root.update_idletasks()
        rx = self.app.root.winfo_rootx()
        ry = self.app.root.winfo_rooty()
        rw = self.app.root.winfo_width()
        rh = self.app.root.winfo_height()
        x = rx + max(0, (rw - 404) // 2)
        y = ry + max(0, (rh - 304) // 2)
        win.geometry(f"+{x}+{y}")
        
        # 主体卡片面板（往左上偏移，露出右下角的灰色阴影）
        main = tk.Frame(win, bg="#f4f4f4", highlightbackground="#000000", highlightthickness=1)
        main.pack(fill="both", expand=True, padx=(0, 4), pady=(0, 4))
        
        # 深蓝色标题栏
        title_bar = tk.Frame(main, bg="#000080", height=24)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        
        tk.Label(title_bar, text="📄 分支详情", bg="#000080", fg="#ffffff", font=("SimSun", 9, "bold")).pack(side="left", padx=6)
        
        # 极简关闭按钮（没有边框，纯粹靠字符和变色）
        close_btn = tk.Label(title_bar, text=" ✕ ", bg="#000080", fg="#ffffff", font=("SimSun", 10, "bold"), cursor="hand2")
        close_btn.pack(side="right", padx=4)
        
        def _close_popup(e=None):
            self.commit_popup_win = None
            win.destroy()
            
        close_btn.bind("<Button-1>", _close_popup)
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg="#ff0000"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg="#000080"))
        
        def start_drag(event):
            win._drag_x = event.x
            win._drag_y = event.y
        def on_drag(event):
            x = win.winfo_pointerx() - win._drag_x
            y = win.winfo_pointery() - win._drag_y
            win.geometry(f"+{x}+{y}")
        title_bar.bind("<Button-1>", start_drag)
        title_bar.bind("<B1-Motion>", on_drag)
        
        # 内容区：纯白底色，无凹陷，四周留出空隙
        st = tk.Text(main, font=("SimSun", 10), bg="#ffffff", fg="#000000", relief="solid", bd=1, wrap="word")
        st.pack(fill="both", expand=True, padx=6, pady=6)
        st.insert("1.0", content)
        st.configure(state="disabled")

    def _edit_book_page_inplace(self):
        c = self.canvas
        bb = c.bbox("book_page_btn")
        if not bb:
            return
        
        c.itemconfig("book_page_btn", state="hidden")
        
        entry = tk.Entry(self.holder, font=("SimSun", 12, "bold"), relief="solid", bd=1, bg="#ffffff", justify="center")
        w = max(80, bb[2]-bb[0])
        h = max(24, bb[3]-bb[1])
        entry.place(x=bb[0] - c.canvasx(0) - (w-(bb[2]-bb[0]))//2, y=bb[1] - c.canvasy(0), width=w, height=h)
        
        tid = getattr(self, "current_book_tid", "")
        t = self.vcs.tasks().get(tid, {}) if self.vcs else {}
        commits = t.get("commits", [])
        avail_h = max(50, (c.winfo_height() - 40 - 40) - (60 + 80))
        items_per_page = max(1, avail_h // 50)
        calc_total = max(1, (len(commits) + items_per_page - 1) // items_per_page)
        total = getattr(self, "book_total_override", calc_total)
        if total is None or not isinstance(total, int):
            total = calc_total
            self.book_total_override = total
            
        text = f"<{self.book_page+1}/{total}>"
        entry.insert(0, text)
        # 默认选中左尖括号与斜杠之间的当前页数
        slash_idx = text.find("/")
        start_idx = text.find("<") + 1
        if slash_idx != -1 and start_idx > 0:
            entry.selection_range(start_idx, slash_idx)
            entry.icursor(start_idx)
        else:
            entry.selection_range(0, "end")
        entry.focus_set()
        
        def finish_edit(save=True):
            entry.unbind("<Return>")
            entry.unbind("<Escape>")
            entry.unbind("<FocusOut>")
            if save:
                val = entry.get().strip().replace("<", "").replace(">", "")
                if "/" in val:
                    parts = val.split("/")
                    try:
                        p = int(parts[0].strip()) - 1
                        t_pages = int(parts[1].strip())
                        if t_pages > 0:
                            self.book_total_override = t_pages
                            self.book_page = max(0, min(p, t_pages - 1))
                    except ValueError:
                        pass
                elif val.isdigit():
                    self.book_page = max(0, int(val) - 1)
            entry.destroy()
            self.render()
            
        entry.bind("<Return>", lambda e: finish_edit(True))
        entry.bind("<Escape>", lambda e: finish_edit(False))
        entry.bind("<FocusOut>", lambda e: finish_edit(True))

    def _edit_shelf_path_inplace(self):
        c = self.canvas
        bb = c.bbox("path_base")
        if not bb:
            return
        
        # 隐藏所有和路径相关的文字及边框
        c.itemconfig("path_base", state="hidden")
        c.itemconfig("path_bar", state="hidden")
        for it in c.find_all():
            tags = c.gettags(it)
            if any(t.startswith("path_part_") for t in tags):
                c.itemconfig(it, state="hidden")
                
        # 判断当前模式，拼接完整路径字符串
        if getattr(self, "view_mode", "tree") == "book":
            tid = getattr(self, "current_book_tid", "")
            t = self.vcs.tasks().get(tid, {}) if self.vcs else {}
            tname = t.get("name", "未命名")
            base = getattr(self, "shelf_path", os.path.abspath(BASE_DIR)).replace("\\", "/")
            cur_val = f"{base}/{tname}"
        else:
            cur_val = getattr(self, "shelf_path", os.path.abspath(BASE_DIR)).replace("\\", "/")
            
        # 根据字符串长度自适应输入框宽度
        w = max(bb[2]-bb[0]+40, 320)
        if getattr(self, "view_mode", "tree") == "book":
            w = max(w, len(cur_val) * 10 + 40)
            w = min(w, 800)
            
        h = max(bb[3]-bb[1]+8, 26)
        
        # 原地创建输入框
        entry = tk.Entry(self.holder, font=("SimSun", 10, "bold"), relief="solid", bd=2, bg="#ffffff", fg="#000000", selectbackground="#0078D7", selectforeground="#ffffff")
        entry.place(x=bb[0] - c.canvasx(0) - 4, y=bb[1] - c.canvasy(0) - 4, width=w, height=h)
        
        entry.insert(0, cur_val)
        entry.select_range(0, "end")
        entry.icursor("end")
        entry.focus_set()
        
        def finish_edit(save=True):
            entry.unbind("<Return>")
            entry.unbind("<Escape>")
            entry.unbind("<FocusOut>")
            if save:
                new_val = entry.get().strip().replace("\\", "/")
                if new_val:
                    if getattr(self, "view_mode", "tree") == "book":
                        parts = new_val.rsplit("/", 1)
                        if len(parts) == 2:
                            self.shelf_path = parts[0]
                            tid = getattr(self, "current_book_tid", "")
                            if tid and parts[1] and tid in self.vcs.tasks():
                                self.vcs.tasks()[tid]["name"] = parts[1]
                                self.vcs._save_state()
                                if self.app: self.app._refresh_vcs_tree()
                        else:
                            self.shelf_path = new_val
                    else:
                        self.shelf_path = new_val
            entry.destroy()
            self.render()
            
        entry.bind("<Return>", lambda e: finish_edit(True))
        entry.bind("<Escape>", lambda e: finish_edit(False))
        entry.bind("<FocusOut>", lambda e: finish_edit(True))

    def _edit_shelf_page_inplace(self):
        c = self.canvas
        bb = c.bbox("page_btn")
        if not bb:
            return
        
        c.itemconfig("page_btn", state="hidden")
        
        entry = tk.Entry(self.holder, font=("SimSun", 12, "bold"), relief="solid", bd=1, bg="#ffffff", justify="center")
        w = max(80, bb[2]-bb[0])
        h = max(24, bb[3]-bb[1])
        entry.place(x=bb[0] - c.canvasx(0) - (w-(bb[2]-bb[0]))//2, y=bb[1] - c.canvasy(0), width=w, height=h)
        
        tasks = list(self.vcs.tasks().items())
        calc_total = max(1, (len(tasks) + self.per_page - 1) // self.per_page)
        total = getattr(self, "total_pages_override", calc_total)
        text = f"{self.page+1}/{total}"
        entry.insert(0, text)
        # 默认选中左边的当前页数
        slash_idx = text.find("/")
        if slash_idx != -1:
            entry.selection_range(0, slash_idx)
            entry.icursor(0)
        else:
            entry.selection_range(0, "end")
        entry.focus_set()
        
        def finish_edit(save=True):
            entry.unbind("<Return>")
            entry.unbind("<Escape>")
            entry.unbind("<FocusOut>")
            if save:
                val = entry.get().strip().replace("<", "").replace(">", "")
                if "/" in val:
                    parts = val.split("/")
                    try:
                        p = int(parts[0].strip()) - 1
                        t = int(parts[1].strip())
                        if t > 0:
                            self.total_pages_override = t
                            self.page = max(0, min(p, t - 1))
                    except ValueError:
                        pass
                elif val.isdigit():
                    self.page = max(0, int(val) - 1)
            entry.destroy()
            self.render()
            
        entry.bind("<Return>", lambda e: finish_edit(True))
        entry.bind("<Escape>", lambda e: finish_edit(False))
        entry.bind("<FocusOut>", lambda e: finish_edit(True))

    def _draw_selection(self):
        if getattr(self, "view_mode", "tree") == "shelf":
            return
        c = self.canvas
        try:
            c.delete("selring")
        except tk.TclError:
            return
        kind, sid = self.sel
        key = "%s:%s" % (kind, sid)
        p = self.pos.get(key)
        if not p:
            return
        x, y = p
        r = getattr(self, "radii", {}).get(key, self.R)
        if kind == "commit":
            # Win98 选中态：1px 黑色点线框
            c.create_rectangle(x - r - 3, y - r - 3, x + r + 3, y + r + 3,
                               outline="#000000", dash=(1, 1), width=1, tags="selring")
        else:
            bb = getattr(self, "hdr_bbox", {}).get(sid)
            if bb:
                c.create_rectangle(bb[0] - 2, bb[1] - 2, bb[2] + 2, bb[3] + 2,
                                   outline="#000000", dash=(1, 1), width=1, tags="selring")
            else:
                c.create_rectangle(x - 30, y - 8, x + 30, y + 4,
                                   outline="#000000", dash=(1, 1), width=1, tags="selring")

    def _show_info(self):
        kind, sid = self.sel
        text = ""
        if kind == "commit" and self.vcs:
            _t, cm = self.vcs.find_commit(sid)
            if cm:
                files = cm.get("files", [])
                text = "%s　|　来源 %s　|　%s　|　%d 个文件" % (
                    cm.get("name", ""), cm.get("source", "") or "-",
                    cm.get("date", ""), len(files))
                if cm.get("command"):
                    text += "　|　" + cm["command"][:90]
        elif kind == "task" and self.vcs:
            t = self.vcs.tasks().get(sid, {})
            text = "任务「%s」　|　%d 次修改　|　创建于 %s%s" % (
                t.get("name", sid), len(t.get("commits", [])), t.get("created", ""),
                "　|　★当前" if self.vcs.state.get("current") == sid else "")
        try:
            self.app.vcs_info_var.set(text or "提示：单击=选择｜双击节点=查看差异｜右键=更多操作｜方向键可导航")
        except Exception:
            pass


_APP_REF = None


class EyeTracker(tk.Canvas):
    """静态的写实恐怖之眼"""
    def __init__(self, parent, size=80, **kwargs):
        super().__init__(parent, width=size, height=size, bg="#c0c0c0", highlightthickness=0, **kwargs)
        self.size = size
        self.cx = size / 2
        self.cy = size / 2
        
        self.eye_w = size * 0.9
        self.eye_h = size * 0.6
        self.iris_r = size * 0.22
        self.pupil_r = size * 0.08
        
        # 1. 极暗的眼眶底色
        self.create_oval(self.cx - self.eye_w/2, self.cy - self.eye_h/2, 
                         self.cx + self.eye_w/2, self.cy + self.eye_h/2, 
                         fill="#0a0000", outline="#000000", width=3)
                         
        # 2. 惨白死灰的眼白
        self.create_oval(self.cx - self.eye_w/2 + 3, self.cy - self.eye_h/2 + 3, 
                         self.cx + self.eye_w/2 - 3, self.cy + self.eye_h/2 - 3, 
                         fill="#e8e8e8", outline="")
        
        # 3. 密集的充血红血丝
        import random
        for _ in range(35):
            angle = random.uniform(0, math.pi * 2)
            start_r = min(self.eye_w, self.eye_h) / 2 * 0.6
            end_r = min(self.eye_w, self.eye_h) / 2
            x1 = self.cx + math.cos(angle) * start_r
            y1 = self.cy + math.sin(angle) * start_r
            x2 = self.cx + math.cos(angle + random.uniform(-0.4, 0.4)) * end_r
            y2 = self.cy + math.sin(angle + random.uniform(-0.4, 0.4)) * end_r
            self.create_line(x1, y1, x2, y2, fill="#8b0000", width=random.choice([1, 1, 2]))
            
        # 4. 浑浊深邃的虹膜（偏上，三白眼）
        self.create_oval(self.cx - self.iris_r, self.cy - self.iris_r*1.3,
                         self.cx + self.iris_r, self.cy + self.iris_r*0.7,
                         fill="#2b150a", outline="#000000", width=2)
        self.create_oval(self.cx - self.iris_r*0.8, self.cy - self.iris_r*1.0,
                         self.cx + self.iris_r*0.8, self.cy + self.iris_r*0.4,
                         fill="#4a250e", outline="")
                         
        # 5. 深渊般的瞳孔
        self.create_oval(self.cx - self.pupil_r, self.cy - self.pupil_r*1.3,
                         self.cx + self.pupil_r, self.cy + self.pupil_r*0.7,
                         fill="#000000", outline="")
                                       
        # 6. 刺眼的高光反光
        self.create_oval(self.cx - self.pupil_r*0.8, self.cy - self.pupil_r*1.1,
                         self.cx - self.pupil_r*0.1, self.cy - self.pupil_r*0.3,
                         fill="#ffffff", outline="")
                                           
        # 7. 厚重的黑眼圈眼皮
        self.create_oval(self.cx - self.eye_w/2, self.cy - self.eye_h/2 - size*0.4, 
                         self.cx + self.eye_w/2, self.cy + self.eye_h/2 - size*0.4, 
                         fill="#000000", outline="")
        self.create_oval(self.cx - self.eye_w/2, self.cy - self.eye_h/2 + size*0.4, 
                         self.cx + self.eye_w/2, self.cy + self.eye_h/2 + size*0.4, 
                         fill="#000000", outline="")


def force_set_win_icon(root, ico_path):
    """使用 Win32 API 强行替换窗口标题栏图标"""
    if not os.path.exists(ico_path): return
    try:
        # 获取窗口句柄
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        # 加载我们自己的 ico
        LR_LOADFROMFILE = 0x00000010
        IMAGE_ICON = 1
        hicon = ctypes.windll.user32.LoadImageW(None, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hicon:
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            # 强刷大、小图标
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    except Exception as e:
        print("图标替换失败:", e)


class App:
    def __init__(self, root):
        self.root = root; root.title("awa"); root.minsize(400, 200)
        
        # 1. 赋予程序独立的 AppUserModelID，摆脱 pythonw.exe 的默认白纸图标
        try:
            import ctypes
            myappid = 'piannow.awa.agent.v3'
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except Exception:
            pass
        self.config = load_config()
        root.geometry(self.config.get("window_geometry", "950x750"))
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        BG_COLOR = "#c0c0c0"
        root.configure(bg=BG_COLOR)
        root.option_add("*Font", ("Simsun", 9))
        style = ttk.Style(root)
        try: style.theme_use('winnative')
        except: pass
        style.configure("TButton", font=("Simsun", 9), bg="#c0c0c0")
        style.configure("TEntry", font=("Simsun", 10), fieldbackground="white")
        style.configure("Treeview", font=("Simsun", 10), rowheight=20, background="white", fieldbackground="white")

        self.current_proc = None; self.running = False; self.arg_vars = {}; self.cmd_var = tk.StringVar(); self.output_queue = queue.Queue()
        self.task_id = 0
        self.save_timer = None
        self._text_buf = 0
        self._task_temps = {}
        self._file_read_offset = 0
        
        # 每次启动程序自动清空剪切板.txt，保证每次都是一个干净的新面板
        try:
            with open(CLIPBOARD_FILE, "w", encoding="utf-8") as f:
                pass
        except Exception:
            pass
        self._log_file_queue = queue.Queue()
        threading.Thread(target=self._log_writer_worker, daemon=True).start()

        mount_portable_env()

        # 双管齐下：同时强刷标题栏和任务栏图标
        try:
            final_icon = prepare_white_icon()
            if os.path.exists(final_icon):
                # 1. 搞定任务栏：用 Pillow 转换成 PhotoImage 塞给 iconphoto
                try:
                    from PIL import Image, ImageTk
                    img = Image.open(final_icon)
                    self._taskbar_img = ImageTk.PhotoImage(img)
                    self.root.iconphoto(True, self._taskbar_img)
                except Exception:
                    pass
                
                # 2. 搞定标题栏：用原生 API 强刷
                self.root.iconbitmap(final_icon)
                self.root.after(100, lambda: force_set_win_icon(self.root, final_icon))
        except Exception:
            pass

        top = tk.Frame(root, bg=BG_COLOR); top.pack(fill="x", padx=8, pady=4)
        self.topmost_var = tk.BooleanVar(value=True)
        tk.Checkbutton(top, text="窗口置顶", variable=self.topmost_var, command=self._toggle_topmost, bg=BG_COLOR).pack(side="left")
        root.attributes("-topmost", True)

        cfg = tk.Frame(root, bg=BG_COLOR); cfg.pack(fill="x", padx=8, pady=(2, 0))
        tk.Label(cfg, text="全局备份:", bg=BG_COLOR).pack(side="left")
        self.global_bak_dir = tk.StringVar(value=self.config.get("global_bak_dir", ""))
        self.global_bak_dir.trace_add("write", self._on_bak_dir_change)
        tk.Entry(cfg, textvariable=self.global_bak_dir, bg="white", relief="sunken", bd=2).pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(cfg, text="选目录", command=lambda: self.global_bak_dir.set(pick_dir(self.root, self.global_bak_dir.get()) or self.global_bak_dir.get()), bg=BG_COLOR, relief="raised", bd=2).pack(side="left", padx=2)

        # 任务栏：内容超宽时可用鼠标滚轮横向滑动
        mode_wrap = tk.Frame(root, bg=BG_COLOR); mode_wrap.pack(fill="x", padx=8, pady=4)
        self.mode_canvas = tk.Canvas(mode_wrap, bg=BG_COLOR, highlightthickness=0, bd=0, height=24)
        self.mode_canvas.configure(xscrollincrement=24)
        self.mode_canvas.pack(fill="x", expand=True)
        mode = tk.Frame(self.mode_canvas, bg=BG_COLOR)
        self._mode_win = self.mode_canvas.create_window((0, 0), window=mode, anchor="nw")

        def _mode_sync(_e=None):
            h = mode.winfo_reqheight()
            if int(self.mode_canvas.cget("height")) != h:
                self.mode_canvas.configure(height=h)
            self.mode_canvas.configure(
                scrollregion=(0, 0, max(mode.winfo_reqwidth(), self.mode_canvas.winfo_width()), h))

        def _mode_wheel(e):
            self.mode_canvas.xview_scroll(-1 if e.delta > 0 else 1, "units")
            return "break"

        def _bind_mode_wheel(w):
            w.bind("<MouseWheel>", _mode_wheel, add="+")
            for c in w.winfo_children():
                _bind_mode_wheel(c)

        mode.bind("<Configure>", _mode_sync)
        self.mode_canvas.bind("<Configure>", _mode_sync)

        self.mode = tk.StringVar(value="cmd")
        tk.Radiobutton(mode, text="命令行模式", variable=self.mode, value="cmd", command=self.switch_mode, bg=BG_COLOR).pack(side="left")
        tk.Radiobutton(mode, text="图形工具面板", variable=self.mode, value="tool", command=self.switch_mode, bg=BG_COLOR).pack(side="left", padx=10)
        tk.Radiobutton(mode, text="AI 指令执行", variable=self.mode, value="ai", command=self.switch_mode, bg=BG_COLOR).pack(side="left")
        tk.Radiobutton(mode, text="分支书", variable=self.mode, value="vcs", command=self.switch_mode, bg=BG_COLOR).pack(side="left", padx=10)
        self.vcs_cur_var = tk.StringVar(value="当前任务：")
        tk.Label(mode, textvariable=self.vcs_cur_var, bg=BG_COLOR, fg="#000080").pack(side="left", padx=(12, 0))
        _bind_mode_wheel(mode_wrap)

        btn_frame = tk.Frame(root, height=40, bg=BG_COLOR); btn_frame.pack(fill="x", side="bottom", padx=8, pady=8); btn_frame.pack_propagate(False)
        self.run_btn = tk.Button(btn_frame, text="执行 (Ctrl+Enter)", command=self.run_current, bg=BG_COLOR, relief="raised", bd=2); self.run_btn.pack(side="left", fill="y")
        self.copy_btn = tk.Button(btn_frame, text="复制输出", command=self.copy_all, bg=BG_COLOR, relief="raised", bd=2); self.copy_btn.pack(side="left", padx=4, fill="y")
        tk.Button(btn_frame, text="清空输出", command=self.clear_out, bg=BG_COLOR, relief="raised", bd=2).pack(side="left", padx=4, fill="y")
        tk.Button(btn_frame, text="强制结束", command=self.kill_current, bg=BG_COLOR, relief="raised", bd=2).pack(side="left", padx=4, fill="y")

        self.paned = tk.PanedWindow(root, orient=tk.VERTICAL, sashwidth=6, bg=BG_COLOR); self.paned.pack(fill="both", expand=True, padx=8)
        top_wrap = tk.Frame(self.paned, bg=BG_COLOR); self.paned.add(top_wrap, minsize=30)
        self.body = tk.Frame(top_wrap, bg=BG_COLOR); self.body.pack(fill="both", expand=True)

        self.cmd_frame = tk.Frame(self.body, bg=BG_COLOR)
        tk.Label(self.cmd_frame, text="CMD / PowerShell(ps:) / Python(py:) / BAT(bat:)\n(提示: py: 带空格路径请加引号)", bg=BG_COLOR, justify="left").pack(anchor="w", padx=4, pady=(2, 0))
        self.cmd_text = tk.Text(self.cmd_frame, height=6, font=("Consolas", 11), bg="white", relief="sunken", bd=2); self.cmd_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.cmd_text.bind("<Control-Return>", lambda e: (self.run_current(), "break")[1])

        self.tool_frame = tk.Frame(self.body, bg=BG_COLOR)
        self.tool_list = tk.Listbox(self.tool_frame, width=24, bg="white", relief="sunken", bd=2); self.tool_list.pack(side="left", fill="y", padx=4)
        self.tool_list.bind("<<ListboxSelect>>", self.on_tool_select)

        right_wrap = tk.Frame(self.tool_frame, bg=BG_COLOR); right_wrap.pack(side="left", fill="both", expand=True)
        self.tool_canvas = tk.Canvas(right_wrap, highlightthickness=0, bg=BG_COLOR)
        sb = tk.Scrollbar(right_wrap, orient="vertical", command=self.tool_canvas.yview); sb.pack(side="right", fill="y")
        self.tool_canvas.configure(yscrollcommand=sb.set); self.tool_canvas.pack(side="left", fill="both", expand=True)
        self.tool_detail = tk.Frame(self.tool_canvas, bg=BG_COLOR)
        self.tool_canvas_win = self.tool_canvas.create_window((0, 0), window=self.tool_detail, anchor="nw")
        self.tool_detail.bind("<Configure>", lambda e: self.tool_canvas.configure(scrollregion=self.tool_canvas.bbox("all")))
        self.tool_canvas.bind("<Configure>", lambda e: self.tool_canvas.itemconfig(self.tool_canvas_win, width=e.width))

        self.ai_frame = tk.Frame(self.body, bg=BG_COLOR)
        tk.Label(self.ai_frame, text="支持直接粘贴 AI 生成的 JSON 指令：", bg=BG_COLOR).pack(anchor="w", padx=4, pady=(4,0))
        self.ai_text = tk.Text(self.ai_frame, height=12, font=("Consolas", 11), bg="white", relief="sunken", bd=2); self.ai_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.ai_text.bind("<Control-Return>", lambda e: (self.run_ai_command(), "break")[1])
        ai_btn_row = tk.Frame(self.ai_frame, bg=BG_COLOR); ai_btn_row.pack(fill="x", padx=4, pady=(0, 4))
        tk.Button(ai_btn_row, text="▶ 解析并执行此指令", command=self.run_ai_command, bg=BG_COLOR, relief="raised", bd=2).pack(side="left", fill="x", expand=True)
        tk.Button(ai_btn_row, text="清空输入", command=lambda: self.ai_text.delete("1.0", "end"), bg=BG_COLOR, relief="raised", bd=2).pack(side="right", padx=(10, 0))

        # ---------- 分支树（任务/提交） ----------
        self.vcs_frame = tk.Frame(self.body, bg=BG_COLOR)

        gwrap = tk.Frame(self.vcs_frame, bg=BG_COLOR)
        gwrap.pack(fill="both", expand=True, padx=4, pady=(0, 2))
        self.gv = VCSGraphView(gwrap, self)

        # 底部任务信息条已废除（保留变量，避免内部 set() 调用报错）
        self.vcs_info_var = tk.StringVar(value="")

        bottom_wrap = tk.Frame(self.paned, bg=BG_COLOR); self.paned.add(bottom_wrap, minsize=30)
        self.output = scrolledtext.ScrolledText(bottom_wrap, font=("Consolas", 10), bg="black", fg="#00ff00", insertbackground="white")
        self.output.pack(fill="both", expand=True)
        self._start_flush_timer()

        load_externals(); load_plugins()
        for _w in LOAD_WARNINGS:
            self._append(_w + "\n")
        self.tool_names = [name for name in TOOLS.keys() if name != "sys"]

        # 版本库（任务/提交/回退）+ 全局引用（invoke_tool 记录后刷新界面）
        self.vcs = get_vcs()
        self.vcs_skip = False
        self.vcs_cmd_text = ""
        global _APP_REF
        _APP_REF = self

        self.switch_mode(); self.refresh_tool_list()
        self._refresh_vcs_tree()

        if LOAD_WARNINGS:
            self._append("\n" + "\n".join(LOAD_WARNINGS) + "\n\n")

        root.bind("<Control-Return>", lambda e: (self.run_current(), "break")[1])
        # 全局鼠标移动：如果你喜欢，我们可以让图标做一点位移表示“盯着你”
        root.bind("<Motion>", self._on_global_mouse_move)

        self.tool_canvas.bind("<Enter>", lambda e: root.bind_all("<MouseWheel>", self._on_mousewheel))
        self.tool_canvas.bind("<Leave>", lambda e: root.unbind_all("<MouseWheel>"))

    def _load_custom_icon(self):
        ico_path = os.path.join(MIOA_DIR, "awa.ico")
        if os.path.exists(ico_path):
            try:
                # 使用 Pillow 加载图标并放大，让左上角显示清晰的黑红大眼
                from PIL import Image, ImageTk
                img = Image.open(ico_path)
                # 提取最大尺寸的帧（ICO 通常是多尺寸的）
                img = img.resize((32, 32), Image.Resampling.LANCZOS)
                self.tk_icon = ImageTk.PhotoImage(img)
                self.icon_eye.config(image=self.tk_icon)
                return
            except Exception:
                pass
        
        # 兜底：如果没有 Pillow 或 ico 丢失，直接用画布补上（纯黑底红血丝）
        self.icon_eye.destroy()
        self.icon_eye = EyeTracker(top, size=32)
        self.icon_eye.pack(side="left", padx=(0, 5))

    def _on_global_mouse_move(self, event):
        try:
            # 如果是真正的 EyeTracker 画布，用 look_at 转动瞳孔
            if hasattr(self, "icon_eye") and isinstance(self.icon_eye, EyeTracker):
                ex = self.icon_eye.winfo_pointerx() - self.icon_eye.winfo_rootx()
                ey = self.icon_eye.winfo_pointery() - self.icon_eye.winfo_rooty()
                self.icon_eye.look_at(ex, ey)
            # 如果是加载的图片，我们就用轻微的横向位移（左右偏移 2 像素）来模拟它在跟着你
            elif hasattr(self, "icon_eye"):
                offset = 2 if event.x_root > self.root.winfo_rootx() + 100 else -2
                self.icon_eye.pack_configure(padx=(max(0, offset), 5))
        except Exception:
            pass

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _on_bak_dir_change(self, *args):
        self.config["global_bak_dir"] = self.global_bak_dir.get()
        if self.save_timer: self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(500, lambda: save_config(self.config))

    def _on_close(self):
        # 关闭前强制保存 VCS 版本库，防止分支丢失
        if hasattr(self, "vcs") and self.vcs:
            self.vcs._save_state()
            
        if self.save_timer:
            try: self.root.after_cancel(self.save_timer)
            except: pass
            self.save_timer = None
        self.task_id += 1
        if self.current_proc:
            self._kill_proc(self.current_proc, graceful=False)
            self.current_proc = None
        self._cleanup_temp_files()
        self.running = False

        try:
            geo = self.root.geometry()
            m = re.match(r"^(\d+x\d+)([+-]\d+)([+-]\d+)$", geo)
            if m:
                wh, x, y = m.group(1), int(m.group(2)), int(m.group(3))
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                w = int(wh.split('x')[0])
                x = max(0, min(x, sw - w))
                y = max(0, min(y, sh - 100))
                geo = f"{wh}{x:+d}{y:+d}"
            self.config["window_geometry"] = geo
        except: pass

        save_config(self.config)
        self.root.destroy()

    def _kill_proc(self, proc, graceful=True):
        if not proc: return
        if os.name == 'nt':
            if graceful:
                try: proc.send_signal(signal.CTRL_BREAK_EVENT)
                except: pass
                try: proc.wait(timeout=0.3)
                except: pass
            if proc.poll() is None:
                subprocess.run(f"taskkill /F /T /PID {proc.pid}", shell=True, capture_output=True)
        else:
            if proc.poll() is not None: return
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM if graceful else signal.SIGKILL)
            except Exception:
                try: proc.terminate() if graceful else proc.kill()
                except: pass
            try: proc.wait(timeout=0.5 if graceful else 0.1)
            except: pass
            if proc.poll() is None:
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except Exception:
                    try: proc.kill()
                    except: pass
                try: proc.wait(timeout=0.1)
                except: pass

    def _cleanup_temp_files(self):
        for path in list(self._task_temps.values()):
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass
        self._task_temps.clear()

    def _on_mousewheel(self, event):
        self.tool_canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def switch_mode(self):
        self.cmd_frame.pack_forget(); self.tool_frame.pack_forget()
        self.ai_frame.pack_forget(); self.vcs_frame.pack_forget()
        mode = self.mode.get()
        if mode == "cmd":
            self.cmd_frame.pack(fill="both", expand=True)
        elif mode == "tool":
            self.tool_frame.pack(fill="both", expand=True)
        elif mode == "vcs":
            self.vcs_frame.pack(fill="both", expand=True)
            self._refresh_vcs_tree()
            try:
                self.gv.scroll_to(self.vcs.state.get("current", ""), vertical=False)
                self.gv.canvas.yview_moveto(0)
                # 自动把上面的画布拉大一点，占屏幕高度的一半以上，给终端留出合理空间
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                self.paned.sash_place(0, 0, int(h * 0.55))
            except Exception:
                pass
        else:
            self.ai_frame.pack(fill="both", expand=True)

    def refresh_tool_list(self):
        self.tool_list.delete(0, "end")
        for name in self.tool_names:
            self.tool_list.insert("end", f"{name} — {TOOLS[name].get('desc', '')}")

    def on_tool_select(self, event):
        sel = self.tool_list.curselection()
        if sel: self._render_detail(self.tool_names[sel[0]])

    def _render_detail(self, name):
        for w in self.tool_detail.winfo_children(): w.destroy()
        self.arg_vars = {}
        t = TOOLS[name]
        tk.Label(self.tool_detail, text=t.get('desc', ''), font=("Microsoft YaHei", 11, "bold"), bg="#c0c0c0").pack(anchor="w", pady=4)
        cmds = list(t["commands"].keys())
        if not cmds: return

        self.cmd_var.set(cmds[0])
        row = tk.Frame(self.tool_detail, bg="#c0c0c0"); row.pack(fill="x", pady=4)
        tk.Label(row, text="命令:", bg="#c0c0c0").pack(side="left")
        tk.OptionMenu(row, self.cmd_var, *cmds, command=lambda _: self._render_args(name)).pack(side="left")
        self.args_frame = tk.Frame(self.tool_detail, bg="#c0c0c0"); self.args_frame.pack(fill="both", expand=True, pady=4)
        self._render_args(name)

    def _render_args(self, name):
        for w in self.args_frame.winfo_children(): w.destroy()
        self.arg_vars = {}
        cmd_def = TOOLS[name]["commands"][self.cmd_var.get()]
        for a in cmd_def.get("args", []):
            row = tk.Frame(self.args_frame, bg="#c0c0c0"); row.pack(fill="x", pady=2)
            desc = a.get("desc", a["name"])
            tk.Label(row, text=desc, width=12, anchor="w", bg="#c0c0c0").pack(side="left")

            if a.get("multiline"):
                text_widget = tk.Text(row, height=3, font=("Consolas", 10), bg="white", relief="sunken", bd=2)
                text_widget.insert("1.0", a.get("default", ""))
                text_widget.pack(side="left", fill="x", expand=True)
                self.arg_vars[a["name"]] = text_widget
            else:
                var = tk.StringVar(value=a.get("default", ""))
                self.arg_vars[a["name"]] = var
                tk.Entry(row, textvariable=var, bg="white", relief="sunken", bd=2).pack(side="left", fill="x", expand=True)

            if a.get("type") == "file":
                tk.Button(row, text="选文件", command=lambda v=self.arg_vars[a["name"]]: self._set_var(v, pick_file(self.root, self._get_var(v)) or self._get_var(v))).pack(side="left", padx=2)
            elif a.get("type") == "dir":
                tk.Button(row, text="选目录", command=lambda v=self.arg_vars[a["name"]]: self._set_var(v, pick_dir(self.root, self._get_var(v)) or self._get_var(v))).pack(side="left", padx=2)

    def _get_var(self, var):
        return var.get("1.0", "end-1c") if isinstance(var, tk.Text) else var.get()

    def _set_var(self, var, val):
        if isinstance(var, tk.Text):
            var.delete("1.0", "end"); var.insert("1.0", val)
        else: var.set(val)

    def export_schema(self):
        schema = generate_ai_schema()
        self.root.clipboard_clear(); self.root.clipboard_append(schema)

    def run_ai_command(self):
        if self.running: return
        raw = self.ai_text.get("1.0", "end").strip()
        if not raw: return
        # 按下执行就立即清空输入区：无论 JSON 是否合法，避免错误内容残留
        self.ai_text.delete("1.0", "end")
        try:
            data = None
            decoder = json.JSONDecoder()
            for i, char in enumerate(raw):
                if char == '{':
                    try:
                        obj, _ = decoder.raw_decode(raw[i:])
                        if isinstance(obj, dict) and "tool" in obj:
                            data = obj
                            break
                    except json.JSONDecodeError:
                        continue

            if not data: raise ValueError("未找到合法的包含 'tool' 的 JSON 结构")

            tool_name = data.get("tool")
            cmd_name = data.get("command")
            params = data.get("params") or {}
            if not isinstance(params, dict): raise ValueError("params 必须是 JSON 对象")

            if tool_name == "sys" and cmd_name == "list_tools":
                self.export_schema()
                self._append("\n[提示] 已将最新的工具清单复制到剪贴板，请直接粘贴给 AI。\n")
                # v1.2.0 更新：查看工具清单也留痕（空提交）
                try:
                    cid = self.vcs.add_commit([], source="sys.list_tools", command="list_tools", allow_empty=True)
                    if cid:
                        self._append("[版本] 已记录：%s\n" % self.vcs.commit_name(cid))
                        self._refresh_vcs_tree()
                except Exception as e:
                    self._append("[版本] 记录失败: %s\n" % e)
                return

            if not tool_name or not cmd_name: raise ValueError("JSON 必须包含 'tool' 和 'command' 字段")
            if tool_name not in TOOLS: raise ValueError(f"找不到工具: {tool_name}")
            if cmd_name not in TOOLS[tool_name]["commands"]: raise ValueError(f"工具 {tool_name} 下找不到命令: {cmd_name}")

            if "backup_dir" in params and not params["backup_dir"]:
                g = getattr(self, 'global_bak_dir', tk.StringVar()).get().strip()
                if g: params["backup_dir"] = g

            # v1.2.0 更新：AI 自定义行为名（JSON 顶层 label 或 params.label）
            _lbl = (data.get("label") or params.get("label") or "").strip()
            if _lbl:
                params["label"] = _lbl

            self._append(f"\n>>> [AI 指令] 触发工具: {tool_name} / {cmd_name}\n")
            self.running = True; self.run_btn.config(state="disabled")

            def worker():
                res = invoke_tool(tool_name, cmd_name, params)
                self.root.after(0, self._append, str(res) + "\n")
                self.root.after(0, lambda: (self.run_btn.config(state="normal"), setattr(self, 'running', False)))

            threading.Thread(target=worker, daemon=True).start()

        except Exception as e:
            self._append(f"\n[解析/执行错误] {e}\n请检查格式是否为纯 JSON。\n")

    def run_current(self):
        if self.running: return
        if self.mode.get() == "cmd":
            raw = self.cmd_text.get("1.0", "end").strip()
            if not raw: return
            # 按下执行就立即清空输入区：无论命令是否合法、是否被拦截，都不保留残留内容
            self.cmd_text.delete("1.0", "end")

            # v1.2.0 更新：首行 @行为名 → AI 自定义本次提交名称
            self.vcs_label = ""
            if raw.startswith("@"):
                _lines = raw.split("\n", 1)
                self.vcs_label = _lines[0][1:].strip()
                raw = _lines[1].strip() if len(_lines) > 1 else ""
                if not raw:
                    self._append("[错误] 只写了 @行为名，没有实际命令。\n")
                    return

            cmd = ""
            temp_bat = None
            out_enc = None
            try:
                if raw.lower().startswith("bat:"):
                    cmd_body = raw[4:].strip()
                    fd, temp_bat = tempfile.mkstemp(suffix=".bat", text=True)
                    with os.fdopen(fd, "w", encoding="gbk", errors="replace") as f:
                        f.write("@echo off\nchcp 936 >nul\n" + cmd_body)
                    cmd = f'"{temp_bat}"'
                    out_enc = "gbk"
                elif raw.lower().startswith("ps:"):
                    ps_code = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; " + raw[3:]
                    cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {base64.b64encode(ps_code.encode("utf-16-le")).decode("ascii")}'
                    out_enc = "utf-8"
                elif raw.lower().startswith("py:"):
                    py_arg = raw[3:].strip()
                    if os.path.isfile(py_arg):
                        parts = [py_arg]
                    else:
                        parts = shlex.split(py_arg, posix=False)
                        parts = [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'") else p for p in parts]
                    for p in parts:
                        if any(c in p for c in "&|<>^%!"):
                            self._append("[错误] 参数中包含非法字符 & | < > ^ % !，已被拦截。\n（如果路径中合法包含这些字符，请将文件移动到不含这些字符的路径后重试）\n")
                            return
                    cmd = subprocess.list2cmdline([sys.executable] + parts)
                    out_enc = "utf-8"
                else:
                    if '\n' in raw:
                        fd, temp_bat = tempfile.mkstemp(suffix=".bat", text=True)
                        with os.fdopen(fd, "w", encoding="gbk", errors="replace") as f:
                            f.write("@echo off\nchcp 936 >nul\n" + raw)
                        cmd = f'"{temp_bat}"'
                        out_enc = "gbk"
                    else:
                        cmd = f'chcp 65001 >nul && {raw}' if os.name == 'nt' else raw
                        out_enc = "utf-8"
            except Exception as e:
                self._append(f"[错误] 准备命令失败: {e}\n")
                if temp_bat and os.path.exists(temp_bat): os.remove(temp_bat)
                return

            self.vcs_skip = _is_readonly_shell(raw)
            self.vcs_cmd_text = raw
            self._execute_shell(cmd, temp_bat, out_enc)

        elif self.mode.get() == "tool":
            if not self.tool_list.curselection(): return
            tool_name = self.tool_names[self.tool_list.curselection()[0]]
            cmd_name = self.cmd_var.get()

            values = {k: self._get_var(v) for k, v in self.arg_vars.items()}
            if "backup_dir" in values and not values["backup_dir"]:
                g = self.global_bak_dir.get().strip()
                if g: values["backup_dir"] = g

            self._append(f"\n>>> 工具: {tool_name} / {cmd_name}\n"); self.running = True; self.run_btn.config(state="disabled")

            def worker():
                res = invoke_tool(tool_name, cmd_name, values)
                self.root.after(0, self._append, str(res) + "\n")
                self.root.after(0, lambda: (self.run_btn.config(state="normal"), setattr(self, 'running', False)))
            threading.Thread(target=worker, daemon=True).start()

        elif self.mode.get() == "ai": self.run_ai_command()

    def _execute_shell(self, cmd, temp_bat=None, out_enc=None):
        self._cleanup_temp_files()

        while not self.output_queue.empty():
            try: self.output_queue.get_nowait()
            except queue.Empty: break

        self._append(f"\n>>> {cmd}\n"); self.running = True; self.run_btn.config(state="disabled")
        self.task_id += 1
        current_task_id = self.task_id
        if temp_bat: self._task_temps[current_task_id] = temp_bat

        try:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            if os.name == 'nt':
                flags |= subprocess.CREATE_NO_WINDOW

            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            proc = subprocess.Popen(cmd, shell=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags, env=env, start_new_session=(os.name != 'nt'))
            self.current_proc = proc

            def read_stream():
                # 启动时已确定输出编码（bat/多行=gbk，ps/py/chcp65001=utf-8），避免中文乱码
                dec = codecs.getincrementaldecoder(out_enc)(errors="replace") if out_enc else None
                head = b""
                last_t = time.time()
                while True:
                    try:
                        chunk = proc.stdout.read1(1024)
                    except Exception:
                        break
                    if not chunk:
                        break

                    if dec is None:
                        head += chunk
                        if len(head) < 512 and (time.time() - last_t) < 0.2:
                            continue
                        dec = codecs.getincrementaldecoder(_detect_encoding(head))(errors="replace")
                        text = dec.decode(head)
                        head = b""
                    else:
                        text = dec.decode(chunk)

                    last_t = time.time()
                    if self.task_id == current_task_id:
                        self.output_queue.put(text)

                if dec is None and head:
                    dec = codecs.getincrementaldecoder(_detect_encoding(head))(errors="replace")
                    if self.task_id == current_task_id:
                        self.output_queue.put(dec.decode(head))

                if dec is not None and self.task_id == current_task_id:
                    self.output_queue.put(dec.decode(b"", final=True))

                if self.task_id == current_task_id:
                    self.output_queue.put(None)

            threading.Thread(target=read_stream, daemon=True).start()
            self.root.after(50, lambda: self._poll_queue(current_task_id))
        except Exception as e:
            self._append(f"[错误] {e}\n"); self.running = False; self.run_btn.config(state="normal")
            self._cleanup_task_temp(current_task_id)

    def _poll_queue(self, task_id):
        if self.task_id != task_id: return
        batch = []
        finished = False

        for _ in range(100):
            if self.output_queue.empty(): break
            try:
                t = self.output_queue.get_nowait()
            except queue.Empty:
                break

            if t is None:
                finished = True
                break
            batch.append(t)

        combined = "".join(batch)
        if combined:
            combined = combined.replace('\r\n', '\n').replace('\r', '\n')
            self._append(combined)

        if finished and self.output_queue.empty():
            self._finish_task()
            self._cleanup_task_temp(task_id)
            return

        if self.current_proc and self.current_proc.poll() is None or not self.output_queue.empty():
            self.root.after(30, lambda: self._poll_queue(task_id))
        else:
            self._finish_task()
            self._cleanup_task_temp(task_id)

    def _cleanup_task_temp(self, task_id):
        if task_id in self._task_temps:
            path = self._task_temps.pop(task_id)
            if path and os.path.exists(path):
                try: os.remove(path)
                except: pass

    def _finish_task(self):
        if not self.running: return
        if self.current_proc:
            try: self.current_proc.poll()
            except: pass
            code = self.current_proc.returncode
            if code is None: code = "未知(进程可能仍在运行)"
            self._append(f"\n[退出码 {code}]\n")
            self.current_proc = None
        self._vcs_after_shell()
        self.running = False; self.run_btn.config(state="normal")

    # ==================== 分支树 / 任务操作 ====================
    def _refresh_vcs_tree(self):
        try:
            self.vcs_cur_var.set("当前任务：%s" % self.vcs.current_name())
        except Exception:
            pass
        if not hasattr(self, "gv"):
            return
        self.gv.set_data(self.vcs)
        self._rebuild_vcs_strip()

    def _rebuild_vcs_strip(self):
        pass  # 废弃旧版任务按钮条

    def vcs_goto_task(self, tid):
        try:
            self.gv.set_data(self.vcs)
            self.gv.select_task(tid)
            self.gv.scroll_to(tid, vertical=True)
        except Exception as e:
            self._append("[版本] 跳转失败: %s\n" % e)

    def vcs_goto_current(self):
        self.vcs_goto_task(self.vcs.state.get("current", ""))

    def _vcs_selected(self):
        try:
            return self.gv.selected()
        except Exception:
            return ("", "")

    def _sel_or_current_task(self):
        kind, sid = self._vcs_selected()
        if kind == "task" and sid:
            return sid
        return self.vcs.state.get("current", "")

    def vcs_new_task(self, parent=None):
        cur_tid = self.vcs.state.get("current", "")
        parent_tid = parent if parent is not None else cur_tid
        base = ""
        if parent_tid:
            pt = self.vcs.tasks().get(parent_tid) or {}
            commits = pt.get("commits", [])
            if commits:
                base = commits[-1]["id"]
        hint = "从「%s」分出" % (self.vcs.tasks().get(parent_tid, {}).get("name", "当前任务")) \
            if parent_tid else "独立分支"
        name = simpledialog.askstring(
            "新建任务/分支",
            "给新任务起个名字（可留空自动命名）：\n当前分支点：%s" % hint,
            parent=self.root)
        if name is None:
            return
        tid = self.vcs.new_task(name, parent=parent_tid, base_commit=base)
        self._refresh_vcs_tree()
        self.vcs_goto_task(tid)
        self._append("\n[版本] 已新建任务：%s（当前，%s）\n"
                     % (self.vcs.tasks()[tid]["name"], hint))

    def vcs_switch_task(self, tid=None):
        tid = tid or self._sel_or_current_task()
        if not tid or tid not in self.vcs.tasks():
            messagebox.showinfo("提示", "请先选择要切换的任务", parent=self.root)
            return
        self.vcs.set_current(tid)
        self._refresh_vcs_tree()
        self.vcs_goto_task(tid)
        self._append("\n[版本] 已切换到任务：%s\n" % self.vcs.current_name())

    def vcs_delete_task(self, tid=None):
        tid = tid or self._sel_or_current_task()
        task = self.vcs.tasks().get(tid or "")
        if not task:
            messagebox.showinfo("提示", "请先选择要删除的任务", parent=self.root)
            return
        n = len(task.get("commits", []))
        # 统计子分支，提醒时一并说明
        # 找出所有需要级联删除的任务（当前任务及其所有子孙节点）
        to_delete = [tid]
        idx = 0
        while idx < len(to_delete):
            cur = to_delete[idx]
            idx += 1
            for ctid, ct in self.vcs.tasks().items():
                if ct.get("parent") == cur and ctid not in to_delete:
                    to_delete.append(ctid)
                    
        extra = ""
        if len(to_delete) > 1:
            extra = "\n\n⚠️ 警告：它有 %d 个子孙分支，这些分支记录也会被一并彻底删除！" % (len(to_delete) - 1)
            
        if not messagebox.askyesno(
                "删除任务",
                "确定删除任务「%s」吗？\n\n该任务下的 %d 条修改记录将一并删除，且无法恢复。\n"
                "（磁盘上的文件不会被删除）%s" % (task.get("name", tid), n, extra),
                icon="warning", parent=self.root):
            return
            
        for dtid in to_delete:
            self.vcs.delete_task(dtid)
            
        self._refresh_vcs_tree()
        self._append("\n[版本] 已删除任务：%s (及其 %d 个子孙)\n" % (task.get("name", tid), len(to_delete) - 1))

    def vcs_rollback(self):
        """回退到该提交完成时的文件状态，并自动从该提交分出新分支。"""
        kind, sid = self._vcs_selected()
        if kind != "commit":
            messagebox.showinfo("提示", "请先在图中点选一个提交（或右键提交）", parent=self.root)
            return
        _t, c = self.vcs.find_commit(sid)
        if not c:
            return
        ok = messagebox.askyesno(
            "回退到此提交",
            "回退到「%s」吗？\n时间：%s\n\n"
            "· 文件会恢复到这次提交完成时的状态（新建的会被删除，删除的会被恢复）\n"
            "· 会从这次提交自动分出一个新分支并切换过去\n"
            "· 原任务的历史不会被改动，之后执行命令都记到新分支"
            % (c.get("name", ""), c.get("date", "")),
            icon="warning", parent=self.root)
        if not ok:
            return
        msg, new_tid = self.vcs.rollback_to(sid)
        self._refresh_vcs_tree()
        if new_tid:
            self.vcs_goto_task(new_tid)
        self._append("\n[版本] 已回退到 %s\n%s\n[版本] 新分支：%s（当前）\n"
                     % (c.get("name", ""), msg,
                        self.vcs.tasks().get(new_tid, {}).get("name", "-") if new_tid else "-"))

    def vcs_undo_commit(self):
        """只撤销这一次提交的改动，不新建分支。"""
        kind, sid = self._vcs_selected()
        if kind != "commit":
            messagebox.showinfo("提示", "请先点选要撤销的提交", parent=self.root)
            return
        _t, c = self.vcs.find_commit(sid)
        if not c:
            return
        if not messagebox.askyesno(
                "仅撤销这次修改",
                "撤销「%s」这次改动？\n\n只把该次涉及的文件恢复成修改前（新建的删除、删除的恢复），"
                "不新建分支。" % c.get("name", ""),
                icon="warning", parent=self.root):
            return
        msg = self.vcs.rollback_commit(sid)
        self._refresh_vcs_tree()
        self._append("\n[版本] 已撤销 %s\n%s\n" % (c.get("name", ""), msg))

    def vcs_show_diff(self):
        kind, sid = self._vcs_selected()
        if kind != "commit":
            messagebox.showinfo("提示", "请先在图中点选一个提交圆点", parent=self.root)
            return
        text = self.vcs.commit_diff(sid)
        win = tk.Toplevel(self.root)
        win.title("修改差异 - " + self.vcs.commit_name(sid))
        win.geometry("900x600")
        st = scrolledtext.ScrolledText(win, font=("Consolas", 10))
        st.pack(fill="both", expand=True)
        st.insert("1.0", text)
        st.configure(state="disabled")

    def _vcs_after_shell(self):
        # v1.2.0 更新：查看类命令也留痕（空提交），不再跳过；支持 @行为名
        try:
            cid = self.vcs.scan_commit(source="shell",
                                       command=getattr(self, "vcs_cmd_text", "")[:200],
                                       force=True,
                                       label=getattr(self, "vcs_label", ""))
            if cid:
                self._append("[版本] 已记录：%s\n" % self.vcs.commit_name(cid))
                self._refresh_vcs_tree()
        except Exception as e:
            self._append("[版本] 记录失败: %s\n" % e)

    def _log_writer_worker(self):
        """后台线程：将输出队列中的数据批量写入本地 剪切板.txt"""
        while True:
            chunks = []
            try:
                chunks.append(self._log_file_queue.get())
                while len(chunks) < 1000:
                    chunks.append(self._log_file_queue.get_nowait())
            except queue.Empty:
                pass
            if chunks:
                try:
                    with open(CLIPBOARD_FILE, "a", encoding="utf-8") as f:
                        f.write("".join(chunks))
                        f.flush()
                except Exception:
                    pass

    def _start_flush_timer(self):
        # 实时读取剪切板.txt的增量部分并渲染到UI
        try:
            if os.path.exists(CLIPBOARD_FILE):
                current_size = os.path.getsize(CLIPBOARD_FILE)
                if current_size > getattr(self, "_file_read_offset", 0):
                    # 每次最多读 50KB，防止单次插入过多导致主线程卡死
                    read_len = min(current_size - self._file_read_offset, 50 * 1024)
                    with open(CLIPBOARD_FILE, "rb") as f:
                        f.seek(self._file_read_offset)
                        new_bytes = f.read(read_len)
                    self._file_read_offset += read_len
                    
                    text = new_bytes.decode("utf-8", errors="replace")
                    if text:
                        # 判断是否在底部，如果在底部才自动跟随
                        is_at_bottom = self.output.yview()[1] >= 0.99
                        self.output.insert("end", text)
                        # 限制 UI 最大 10000 行，防止 Tkinter 滑动卡顿
                        line_count = int(self.output.index('end-1c').split('.')[0])
                        if line_count > 10000:
                            self.output.delete('1.0', '2000.0')
                        if is_at_bottom:
                            self.output.see("end")
        except Exception:
            pass
        self.root.after(100, self._start_flush_timer)

    def _append(self, text):
        if not text: return
        if hasattr(self, "_log_file_queue"):
            self._log_file_queue.put(text)

    def kill_current(self):
        self.task_id += 1
        if self.current_proc:
            self._kill_proc(self.current_proc, graceful=True)
            self.current_proc = None
        self._cleanup_temp_files()
        self.running = False
        self.run_btn.config(state="normal")

    def clear_out(self):
        self.output.delete("1.0", "end")
        self._file_read_offset = 0
        # 清空写入队列里还没落盘的内容
        while not self._log_file_queue.empty():
            try: self._log_file_queue.get_nowait()
            except: pass
        # 清空本地文件
        try:
            with open(CLIPBOARD_FILE, "w", encoding="utf-8") as f: pass
        except: pass

    def copy_all(self):
        # 1. 先检查文件是否存在
        if not os.path.exists(CLIPBOARD_FILE):
            return
            
        file_size = os.path.getsize(CLIPBOARD_FILE)
        
        # 2. 如果超过 100KB（网页绝对塞不下），直接打开文件夹并复制路径
        if file_size > 100 * 1024:
            try:
                os.startfile(os.path.dirname(CLIPBOARD_FILE))
            except Exception:
                pass
            self.root.clipboard_clear()
            self.root.clipboard_append(CLIPBOARD_FILE)
            messagebox.showinfo("文本过大", f"文本已超过 {file_size//1024} KB，网页无法粘贴。\n\n已为您打开文件夹，并复制了文件路径。请直接拖拽或上传 `剪切板.txt`。", parent=self.root)
            self.copy_btn.config(text="已复制路径", bg="#c8e6c9")
            self.root.after(2000, lambda: self.copy_btn.config(text="复制输出", bg="#c0c0c0"))
            return
            
        # 3. 常规大小正常复制
        text = ""
        try:
            with open(CLIPBOARD_FILE, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            pass
            
        if not text:
            text = self.output.get("1.0", "end").strip()
            
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.copy_btn.config(text="已复制!", bg="#c8e6c9")
            self.root.after(1500, lambda: self.copy_btn.config(text="复制输出", bg="#c0c0c0"))

if __name__ == "__main__":
    import ctypes
    if os.name == 'nt':
        try:
            # 开启 Win32 DPI 感知，彻底解决高分屏下 Tkinter 画布和字体发虚、模糊的问题
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
            
        try:
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                pids = (ctypes.c_ulong * 2)()
                count = kernel32.GetConsoleProcessList(pids, 2)
                if count <= 1:
                    user32.ShowWindow(hwnd, 0)
        except: pass

    root = tk.Tk()
    root.withdraw()
    app = App(root)
    root.deiconify()
    root.mainloop()