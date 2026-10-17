# 骨肉相连 Agent (GurouXianglian Agent)

?? **项目主页** | ?? **[使用教程 (TUTORIAL.md)](TUTORIAL.md)**



> 🤖 **AI 参与声明**
> 本项目由人类开发者 **Piannow** 主导设计与需求定义，**AI 模型 DeepSeek V4.1** 辅助完成代码生成、架构评审、文档撰写与调试。开发全程采用 **「Human-in-the-loop（人类在环）」** 协作模式——人类下达指令、校验结果、把控方向，AI 负责方案推演与具体实现。开源应当诚实标注 AI 参与，让协作过程透明可见。

一个运行在 Windows 上的**全能本地开发 / 运维助手**，为「人类在环」协作场景量身打造。它将**命令行执行**、**图形化工具面板**、**AI 指令执行**三种模式集成于一个复古 Win9x 风格的轻量 GUI，让你与 AI 助手一对一配对完成开发与运维任务。

---

## ✨ 主要特性

### 三种执行模式
- **命令行模式**：直接执行 CMD、`ps:` PowerShell、`py:` Python、`bat:` 批处理；长任务实时滚动日志，无需重定向。
- **图形工具面板**：内置文件安全修改工具 `kt`，操作自带备份，支持文本替换、按行号删除、差异比较、一键回滚。
- **AI 指令执行**：粘贴 AI 生成的 JSON 指令，本地解析后调度工具，实现「AI 思考 → 人类审批 → 本地执行」的闭环。

### 安全与可控
- **Human-in-the-loop**：AI 只下发指令，人类手动执行，杜绝网页自动化与脚本抓取。
- **操作自带备份**：`kt` 工具每次改动自动生成 `.bak`，可随时 `diff` / `rollback`。
- **临时文件管控**：任务产生的临时脚本在结束时自动清理。
- **插件隔离保护**：插件与外部命令独立目录，禁止覆盖内置工具 `sys` 与 `kt`。

### 复古与可扩展
- Win9x 风格 UI：`#c0c0c0` 灰底、`Simsun` 宋体、Treeview 文件选择器。
- **插件系统**：`Human_Coupler_Fulcrum_Plugins/` 放 `.py`，实现 `get_tools()` 即注册。
- **外部命令**：`Human_Coupler_Fulcrum_External_Commands/` 放 `.json`，包装任意可执行程序。
- **便携环境**：`Human_Coupler_Fulcrum_Portable_Environment/` 自动挂载至 `PATH`。

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

### 三种模式速览

| 模式 | 输入方式 | 适用场景 |
|------|----------|----------|
| 命令行模式 | `ps:` / `py:` / `bat:` / 直接 CMD | 执行脚本、编译、查看日志 |
| 图形工具面板 | 表单填写 | 安全修改文件、备份回滚 |
| AI 指令执行 | 粘贴 JSON | 接收 AI 助手下发的工具指令 |

> 💡 长任务（Gradle / npm / 编译）直接发纯命令，输出窗口会实时滚动。

---

## 📖 使用指南

### 命令行前缀

- `ps: <PowerShell 代码>` —— 通过 `-EncodedCommand` 执行，UTF-8 输出
- `py: <Python 代码或脚本>` —— 使用当前 Python 解释器，参数经安全校验
- `bat: <批处理内容>` —— 写入临时 `.bat` 后执行，结束后自动清理
- 无前缀 —— 单行直接走 CMD；多行自动转成临时批处理

### 内置工具 kt（文件安全修改）

| 命令 | 说明 | 关键参数 |
|------|------|----------|
| `edit` | 文本替换（自动备份） | `file` `old` `new` |
| `line_delete` | 按行号删除 | `file` `start_line` `end_line` |
| `diff` | 与最近一次备份比较 | `file` |
| `rollback` | 回滚到最近备份 | `file` `bak?` |

每次修改都会在目标文件同级的 `.backups/` 下生成带时间戳的 `.bak`，可随时通过 `diff` 审阅、`rollback` 还原。

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
├── Human_Coupler_Fulcrum_Plugins/               # Python 插件目录
├── Human_Coupler_Fulcrum_External_Commands/     # 外部命令 JSON 定义
├── Human_Coupler_Fulcrum_Portable_Environment/  # 便携工具（自动挂载 PATH）
├── Human_Coupler_Fulcrum_Config.json            # 运行时配置（不入库）
├── last_output.txt                              # 最近输出（不入库）
├── README.md
├── LICENSE
└── .gitignore
```

---

## 🔌 扩展开发

### 编写插件

在 `Human_Coupler_Fulcrum_Plugins/` 下新建 `my_plugin.py`：

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

在 `Human_Coupler_Fulcrum_External_Commands/` 下新建 `my_cmd.json`：

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

<p align="center"><i>骨肉相连 —— 人与 AI，指令与执行，思考与反馈，紧密相连。</i></p>
