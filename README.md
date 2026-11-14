# 骨肉相连 Agent (GurouXianglian Agent)

🏠 **项目主页** | 📖 **[使用教程 (TUTORIAL.md)](TUTORIAL.md)** | 🚀 **[在线交互演示](https://piannow.github.io/GurouXianglianAgent/)**

> 🎮 **不想看枯燥的代码？** 我们为你准备了一个沉浸式的 [在线全流程交互演示](https://piannow.github.io/GurouXianglianAgent/)，无需配置任何环境，直接在浏览器里体验“网页 AI 生成指令 -> 本地工具安全执行”的震撼闭环！



> 🤖 **AI 参与声明**
> 本项目由人类开发者 **Piannow** 主导设计与需求定义，**AI 模型 DeepSeek V4.1** 辅助完成代码生成、架构评审、文档撰写与调试。开发全程采用 **「Human-in-the-loop（人类在环）」** 协作模式——人类下达指令、校验结果、把控方向，AI 负责方案推演与具体实现。开源应当诚实标注 AI 参与，让协作过程透明可见。

一个运行在 Windows 上的 **PowerShell 执行面板 + 带备份的文件修改器 + 可视化版本控制台**。

它没有任何宏大的底层架构，实质上就是一个集成了 `CMD`、`PowerShell`、`Python` 快捷执行功能的界面，外加一个支持自动备份、差异对比和一键回滚的文件文本替换工具，以及一套纯 Python 手搓的类 Git 版本控制系统。

**它解决什么问题？** 当你用网页 AI 生成了代码或替换指令，你不需要手动去命令行里敲，也不需要小心翼翼地用记事本改文件。你只需要把代码粘贴进来执行，如果不小心改错了，随时一键回滚；如果改得太多，随时打开「分支书」翻看历史快照。

---

## ✨ 主要特性

### 四种执行模式
- **命令行模式**：直接执行 CMD、`ps:` PowerShell、`py:` Python、`bat:` 批处理；长任务实时滚动日志，无需重定向。
- **图形工具面板**：内置文件安全修改工具 `kt`，操作自带备份，支持文本替换、按行号删除、差异比较、一键回滚。
- **AI 指令执行**：粘贴 AI 生成的 JSON 指令，本地解析后调度工具，实现「AI 思考 → 人类审批 → 本地执行」的闭环。
- **分支书** (v1.3.0 新增)：可视化浏览所有任务（书架视图）与历史提交（书本视图），支持子分支展开、分支复制/粘贴、任意提交回退。

### 安全与可控
- **Human-in-the-loop**：AI 只下发指令，人类手动执行，杜绝网页自动化与脚本抓取。
- **MiOa 沙盒** (v1.3.0 新增)：插件、外部命令、便携环境、VCS、备份、配置、临时文件、输出，全部收纳至 `MiOa/` 目录，源码目录永远干净。
- **操作自带备份**：`kt` 工具每次改动自动在 `MiOa/backups/` 下生成带时间戳的 `.bak`，可随时 `diff` / `rollback`。
- **内置 VCS** (v1.3.0 重构)：类似 Git 的版本控制，每次修改文件自动记录 `+A/-D` 快照，支持查看类命令留痕，可通过 `@行为名` 自定义提交名称。回退时自动分叉新分支，绝不覆盖原有历史。
- **插件隔离保护**：插件与外部命令独立目录，禁止覆盖内置工具 `sys` 与 `kt`。

### 复古与可扩展
- Win9x 风格 UI：`#c0c0c0` 灰底、`Simsun` 宋体、Treeview 文件选择器。
- **插件系统**：`MiOa/Human_Coupler_Fulcrum_Plugins/` 放 `.py`，实现 `get_tools()` 即注册。
- **外部命令**：`MiOa/Human_Coupler_Fulcrum_External_Commands/` 放 `.json`，包装任意可执行程序。
- **便携环境**：`MiOa/Human_Coupler_Fulcrum_Portable_Environment/` 自动挂载至 `PATH`。

---

## 🚀 快速开始

### 环境要求
- Windows 10 / 11
- Python 3.8+（含 `tkinter`，官方安装包自带）

### 运行

```bat
python gurouxianglian_agent.pyw
```

或直接双击 `gurouxianglian_agent.pyw`（`.pyw` 后缀不弹控制台）。

### 模式速览

| 模式 | 输入方式 | 适用场景 |
|------|----------|----------|
| 命令行模式 | `ps:` / `py:` / `bat:` / 直接 CMD | 执行脚本、编译、查看日志 |
| 图形工具面板 | 表单填写 | 安全修改文件、备份回滚 |
| AI 指令执行 | 粘贴 JSON | 接收 AI 助手下发的工具指令 |
| 分支书 | 鼠标点击 | 浏览历史、分支管理、回退快照 |

> 💡 长任务（Gradle / npm / 编译）直接发纯命令，输出窗口会实时滚动。

---

## 📖 使用指南

### 命令行前缀

- `ps: <PowerShell 代码>` —— 通过 `-EncodedCommand` 执行，UTF-8 输出
- `py: <Python 代码或脚本>` —— 使用当前 Python 解释器，参数经安全校验
- `bat: <批处理内容>` —— 写入临时 `.bat` 后执行，结束后自动清理
- `@<行为名>` (v1.3.0 新增) —— 可选前缀，自定义本次操作在版本历史中的提交名称
- 无前缀 —— 单行直接走 CMD；多行自动转成临时批处理

### 内置工具 kt（文件安全修改）

| 命令 | 说明 | 关键参数 |
|------|------|----------|
| `write` | 新建或覆盖文件 | `file` `content` |
| `edit` | 文本替换（自动备份） | `file` `old` `new` |
| `line_delete` | 按行号删除 | `file` `start_line` `end_line` |
| `diff` | 与最近一次备份比较 | `file` |
| `rollback` | 回滚到最近备份 | `file` `bak?` |

每次修改都会在 `MiOa/backups/` 下生成带时间戳的 `.bak`，可随时通过 `diff` 审阅、`rollback` 还原。

### AI 指令格式

```json
{"tool": "kt", "command": "edit", "params": {"file": "C:\\path\\a.txt", "old": "foo", "new": "bar"}}
```

粘贴到「AI 指令执行」页后回车即可解析执行；`sys/list_tools` 会把最新的工具清单复制到剪贴板，便于回传给 AI。

---

## 📂 目录结构

```
GurouXianglianAgent/
├── gurouxianglian_agent.pyw                     # 主程序
├── MiOa/                                        # 运行时沙盒 (v1.3.0 新增)
│   ├── Human_Coupler_Fulcrum_Plugins/           # Python 插件目录
│   ├── Human_Coupler_Fulcrum_External_Commands/ # 外部命令 JSON 定义
│   ├── Human_Coupler_Fulcrum_Portable_Environment/ # 便携工具（自动挂载 PATH）
│   ├── Human_Coupler_Fulcrum_VCS/               # 版本控制数据
│   ├── backups/                                 # 默认备份目录
│   ├── a/  b/                                   # 临时目录
│   ├── 剪切板.txt                                # 输出持久化
│   ├── last_output.txt                          # 最近输出
│   └── Human_Coupler_Fulcrum_Config.json        # 运行时配置
├── README.md
├── LICENSE
└── .gitignore
```

---

## 🔌 扩展开发

### 编写插件

在 `MiOa/Human_Coupler_Fulcrum_Plugins/` 下新建 `my_plugin.py`：

```python
def get_tools():
    return {
        "mytool": {
            "desc": "示例工具",
            "commands": {
                "hello": {
                    "desc": "打个招呼",
                    "args": [{"name": "who", "desc": "对象", "required": True}],
                    "func": lambda who: f"Hello, {who}!",
                }
            },
        }
    }
```

启动后「图形工具面板」会自动出现 `mytool`。

### 编写外部命令

在 `MiOa/Human_Coupler_Fulcrum_External_Commands/` 下新建 `my_cmd.json`：

```json
{
  "name": "mycmd",
  "desc": "包装外部程序",
  "exe": "C:/Tools/hello.exe",
  "commands": {
    "run": {
      "desc": "运行",
      "args": [{"name": "input", "desc": "输入文件", "flag": "--in", "required": true}]
    }
  }
}
```

> ⚠️ 插件与外部命令**不能**覆盖内置的 `sys` 与 `kt`，加载时会给出警告并拒绝。

---

## 🤝 贡献

欢迎通过 Issue 反馈问题、通过 Pull Request 提交改进。提交前请：

1. 保持「Human-in-the-loop」风格：AI 可以参与，但人类必须审阅与担责；
2. 涉及文件的改动优先使用 `kt` 工具并保留备份；
3. 新功能同步更新 README。

---

## 📜 开源协议

本项目采用 [MIT License](LICENSE) 开源。

---

## 🙏 致谢

- **AI 协作伙伴**：[DeepSeek V4.1](https://www.deepseek.com/) —— 本项目开发过程中的核心 AI 助手，参与代码生成、架构评审与文档撰写。
- 致每一位把 AI 当**协作者**而非**替代品**的开发者。
- 致敬 Win9x 时代的复古界面 —— 简洁、直接、可预期。

---

<p align="center"><i>骨肉相连 —— 人与喵娘，压抑与恶堕，肥鱼与Token，紧密相连。</i></p>
