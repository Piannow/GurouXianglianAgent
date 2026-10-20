import os, sys, shutil, locale, difflib, threading, subprocess, datetime, string, base64, queue, tempfile, importlib.util, traceback, json, glob, re, time, signal, codecs, shlex
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog, filedialog, ttk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ================= 拗口防重名目录 (英文版) =================
PLUGINS_DIR = os.path.join(BASE_DIR, "Human_Coupler_Fulcrum_Plugins")
EXTERNALS_DIR = os.path.join(BASE_DIR, "Human_Coupler_Fulcrum_External_Commands")
PORTABLE_DIR = os.path.join(BASE_DIR, "Human_Coupler_Fulcrum_Portable_Environment")
CONFIG_FILE = os.path.join(BASE_DIR, "Human_Coupler_Fulcrum_Config.json")
# ===========================================================

LAST_OUTPUT = os.path.join(BASE_DIR, "last_output.txt")
os.makedirs(PLUGINS_DIR, exist_ok=True)
os.makedirs(EXTERNALS_DIR, exist_ok=True)
os.makedirs(PORTABLE_DIR, exist_ok=True)

sys.path.insert(0, PLUGINS_DIR)

# =========================================================
# 全局配置与编码处理
# =========================================================
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

def _decodes_as(data: bytes, encoding: str) -> bool:
    try:
        data.decode(encoding)
        return True
    except UnicodeDecodeError as e:
        # 分块读取时末尾可能截断多字节字符，允许最后 3 字节不完整。
        return e.start >= len(data) - 3
    except LookupError:
        return False

def _detect_encoding(head: bytes) -> str:
    if not head: return "utf-8"
    if head.startswith(codecs.BOM_UTF32_LE) or head.startswith(codecs.BOM_UTF32_BE):
        return "utf-32"
    if head.startswith(codecs.BOM_UTF8): return "utf-8-sig"
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)): return "utf-16"
    if _decodes_as(head, "utf-8"): return "utf-8"
    # 无 BOM 的 GBK / GB18030 在旧文件里很常见，先试它再退回系统编码。
    # 不能只信 locale：UTF-8 mode 下 preferred 是 utf-8，GBK 文件会被当成 UTF-8 读出乱码。
    preferred = locale.getpreferredencoding(False)
    for candidate in ("gb18030", preferred):
        if candidate.replace("-", "").lower() in ("utf8", "utf8sig"): continue
        if _decodes_as(head, candidate): return candidate
    return "utf-8"

def _decode_output(b: bytes) -> str:
    enc = _detect_encoding(b)
    try:
        return b.decode(enc)
    except UnicodeDecodeError:
        return b.decode(enc, errors="replace")

# =========================================================
# 内置工具区
# =========================================================
def read_text(path):
    if not os.path.isfile(path): raise ValueError(f"文件不存在: {path}")
    with open(path, "rb") as f:
        raw = f.read()
    if not raw: return "", "utf-8"
    
    enc = _detect_encoding(raw)
    try:
        return raw.decode(enc), enc
    except UnicodeDecodeError as e:
        # 猜错编码时宁可拒绝修改，也不要用替换字符写回把文件弄坏。
        raise ValueError(f"无法按 {enc} 解码 {path}（第 {e.start} 字节），已取消操作以免损坏文件。")

def write_text(path, text, encoding):
    try:
        with open(path, "w", encoding=encoding, newline="") as f: f.write(text)
    except Exception as e: raise ValueError(f"写入失败: {e}")

def _bak_dir(file_path, override=None):
    d = os.path.abspath(override) if override else os.path.join(os.path.dirname(os.path.abspath(file_path)), ".backups")
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

def kt_edit(file, old, new="", backup_dir=None, save_to=None):
    try:
        path = os.path.abspath(file)
        if not old: return "[错误] old 不能为空"
        
        content, enc = read_text(path)
        old_norm = old.replace("\r\n", "\n")
        new_norm = new.replace("\r\n", "\n")
        content_norm = content.replace("\r\n", "\n")
        
        count = content_norm.count(old_norm)
        if count == 0: return "[警告] 未找到目标字符串，未做修改。"
        
        bak = _make_backup(path, backup_dir)
        
        new_content = content_norm.replace(old_norm, new_norm)
        if "\r\n" in content:
            new_content = new_content.replace("\n", "\r\n")
            
        target = os.path.abspath(save_to) if save_to else path
        if save_to:
            d = os.path.dirname(target)
            if d: os.makedirs(d, exist_ok=True)
            
        write_text(target, new_content, enc)
        return f"[成功] 备份: {bak}\n写入: {target}\n替换 {count} 处。"
    except Exception as e: return f"[错误] {str(e)}"

def line_delete(file, start_line, end_line, backup_dir=None):
    try:
        path = os.path.abspath(file)
        start, end = int(start_line), int(end_line)
        if start < 1: return "[错误] 起始行号必须 >= 1"
        
        content, enc = read_text(path)
        is_crlf = "\r\n" in content
        lines = content.replace("\r\n", "\n").split("\n")
        
        if start > len(lines): return f"[错误] 起始行 {start} 越界 (文件共 {len(lines)} 行)"
        if end > len(lines): end = len(lines)
        if start > end: return "[错误] 起始行不能大于结束行"
        
        bak = _make_backup(path, backup_dir)
        
        del lines[start-1:end]
        new_content = "\n".join(lines)
        
        if is_crlf:
            new_content = new_content.replace("\n", "\r\n")
            
        write_text(path, new_content, enc)
        return f"[成功] 备份: {bak}\n已删除 {start} 到 {end} 行。"
    except ValueError: return "[错误] 行号必须是数字"
    except Exception as e: return f"[错误] {str(e)}"

def kt_diff(file, backup_dir=None):
    try:
        path = os.path.abspath(file)
        bd = _bak_dir(path, backup_dir)
        items = _bak_list(path, bd)
        if not items: return "[提示] 无备份。"
        latest = items[0][2]
        c1, _ = read_text(latest)
        c2, _ = read_text(path)
        diff = list(difflib.unified_diff(c1.splitlines(keepends=True), c2.splitlines(keepends=True), fromfile="Backup", tofile="Current", lineterm=""))
        return "".join(diff) if diff else "[提示] 无差异。"
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
        return cmd["func"](**kwargs)
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
class App:
    def __init__(self, root):
        self.root = root; root.title("全能开发助手 (本地执行端)"); root.minsize(400, 200)
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

        mount_portable_env()

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

        mode = tk.Frame(root, bg=BG_COLOR); mode.pack(fill="x", padx=8, pady=4)
        self.mode = tk.StringVar(value="cmd")
        tk.Radiobutton(mode, text="命令行模式", variable=self.mode, value="cmd", command=self.switch_mode, bg=BG_COLOR).pack(side="left")
        tk.Radiobutton(mode, text="图形工具面板", variable=self.mode, value="tool", command=self.switch_mode, bg=BG_COLOR).pack(side="left", padx=10)
        tk.Radiobutton(mode, text="AI 指令执行", variable=self.mode, value="ai", command=self.switch_mode, bg=BG_COLOR).pack(side="left")

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

        bottom_wrap = tk.Frame(self.paned, bg=BG_COLOR); self.paned.add(bottom_wrap, minsize=30)
        self.output = scrolledtext.ScrolledText(bottom_wrap, font=("Consolas", 10), bg="black", fg="#00ff00", insertbackground="white")
        self.output.pack(fill="both", expand=True)

        load_externals(); load_plugins()
        self.tool_names = [name for name in TOOLS.keys() if name != "sys"]
        
        self.switch_mode(); self.refresh_tool_list()
        
        if LOAD_WARNINGS:
            self._append("\n" + "\n".join(LOAD_WARNINGS) + "\n\n")

        root.bind("<Control-Return>", lambda e: (self.run_current(), "break")[1])
        
        self.tool_canvas.bind("<Enter>", lambda e: root.bind_all("<MouseWheel>", self._on_mousewheel))
        self.tool_canvas.bind("<Leave>", lambda e: root.unbind_all("<MouseWheel>"))

    def _toggle_topmost(self):
        self.root.attributes("-topmost", self.topmost_var.get())

    def _on_bak_dir_change(self, *args):
        self.config["global_bak_dir"] = self.global_bak_dir.get()
        if self.save_timer: self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(500, lambda: save_config(self.config))

    def _on_close(self):
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
        self.config["window_geometry"] = self.root.geometry()
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
        self.cmd_frame.pack_forget(); self.tool_frame.pack_forget(); self.ai_frame.pack_forget()
        mode = self.mode.get()
        if mode == "cmd": self.cmd_frame.pack(fill="both", expand=True)
        elif mode == "tool": self.tool_frame.pack(fill="both", expand=True)
        else: self.ai_frame.pack(fill="both", expand=True)

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
                self.export_schema(); self.ai_text.delete("1.0", "end")
                self._append("\n[提示] 已将最新的工具清单复制到剪贴板，请直接粘贴给 AI。\n")
                return
            
            if not tool_name or not cmd_name: raise ValueError("JSON 必须包含 'tool' 和 'command' 字段")
            if tool_name not in TOOLS: raise ValueError(f"找不到工具: {tool_name}")
            if cmd_name not in TOOLS[tool_name]["commands"]: raise ValueError(f"工具 {tool_name} 下找不到命令: {cmd_name}")
                
            if "backup_dir" in params and not params["backup_dir"]:
                g = getattr(self, 'global_bak_dir', tk.StringVar()).get().strip()
                if g: params["backup_dir"] = g

            self._append(f"\n>>> [AI 指令] 触发工具: {tool_name} / {cmd_name}\n")
            self.running = True; self.run_btn.config(state="disabled")
            
            def worker():
                res = invoke_tool(tool_name, cmd_name, params)
                self.root.after(0, self._append, str(res) + "\n")
                self.root.after(0, lambda: (self.run_btn.config(state="normal"), setattr(self, 'running', False)))
                self.root.after(0, lambda: self.ai_text.delete("1.0", "end"))
                
            threading.Thread(target=worker, daemon=True).start()
            
        except Exception as e:
            self._append(f"\n[解析/执行错误] {e}\n请检查格式是否为纯 JSON。\n")

    def run_current(self):
        if self.running: return
        if self.mode.get() == "cmd":
            raw = self.cmd_text.get("1.0", "end").strip()
            if not raw: return
            
            cmd = ""
            temp_bat = None
            try:
                if raw.lower().startswith("bat:"): 
                    cmd_body = raw[4:].strip()
                    fd, temp_bat = tempfile.mkstemp(suffix=".bat", text=True)
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write("@echo off\nchcp 65001 >nul\n" + cmd_body)
                    cmd = f'"{temp_bat}"'
                elif raw.lower().startswith("ps:"): 
                    ps_code = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; $ProgressPreference='SilentlyContinue'; " + raw[3:]
                    cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {base64.b64encode(ps_code.encode("utf-16-le")).decode("ascii")}'
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
                else: 
                    if '\n' in raw:
                        fd, temp_bat = tempfile.mkstemp(suffix=".bat", text=True)
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write("@echo off\nchcp 65001 >nul\n" + raw)
                        cmd = f'"{temp_bat}"'
                    else:
                        cmd = f'chcp 65001 >nul && {raw}' if os.name == 'nt' else raw
            except Exception as e:
                self._append(f"[错误] 准备命令失败: {e}\n")
                if temp_bat and os.path.exists(temp_bat): os.remove(temp_bat)
                return
            
            # ✅ 执行前清空输入框
            self.cmd_text.delete("1.0", "end")
            self._execute_shell(cmd, temp_bat)
            
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

    def _execute_shell(self, cmd, temp_bat=None):
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
                dec = None
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
        self.running = False; self.run_btn.config(state="normal")

    def _append(self, text):
        if not text: return
        try:
            self.output.insert("end", text)
            self.output.see("end")
            self._text_buf += len(text)
            if self._text_buf > 200000:
                self._text_buf = 0
                if int(self.output.index('end-1c').split('.')[0]) > 5000:
                    self.output.delete('1.0', '1000.0')
        except tk.TclError:
            pass

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
        self._text_buf = 0

    def copy_all(self):
        text = self.output.get("1.0", "end").strip()
        if text: 
            self.root.clipboard_clear(); self.root.clipboard_append(text)
            self.copy_btn.config(text="已复制!", bg="#c8e6c9"); self.root.after(1500, lambda: self.copy_btn.config(text="复制输出", bg="#c0c0c0"))

if __name__ == "__main__":
    import ctypes
    if os.name == 'nt':
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