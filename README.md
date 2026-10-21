# init_your_proj

> 多工程可复用的 git 基础设施：一条命令完成项目初始化（AGENTS.md + .gitignore），一条命令在提交前拦住密钥与隐私泄漏。Python 3.11+，零第三方依赖，完全离线。

---

## ✨ 核心特性

- 🚀 **init 一站式初始化**：指定项目路径 → 复制 AGENTS.md / README.md 双模板 → 交互式生成个性化 `.gitignore` → 自动 `git init` →（可选）生成用户增量配置。
- 🔍 **check 提交前卡点**：扫描密钥、数据库凭证、Cookie、IPv4（含公网，白名单除外）、MAC 地址、本机用户名/路径/主机名等敏感内容；`--stage` 放进 `.git/hooks/pre-commit` 作为提交最后关口。
- 🧠 **动态本机指纹**：运行时探测本机用户名、家目录、主机名、局域网 IP，生成精确匹配规则——换台机器依然有效，不会把文档里的举例误判成泄漏。
- 🎯 **IP 白名单（CIDR）**：任意 IPv4 默认命中（公网也报）；回环/常见 DNS/探测到的本机 IP 在默认白名单，用户可追加（支持 `192.168.0.0/24` 网段）。
- 📋 **白名单承载人工判定**：形状匹配的命中（如数据库连接串示例）改文字躲不开，正确做法是子串白名单；报告里写明了操作要点。
- 📦 **零依赖零网络**：纯 Python 标准库，不访问任何外部服务，clone 到固定位置即可用；支持 [pre-commit](https://pre-commit.com) 框架集成。

---

## 🚀 快速上手

### 环境依赖

- Python >= 3.11（仅标准库，无需安装任何包）
- git

### 安装

clone 到一个**固定位置**（任意你存放工具的目录），之后两种用法（见下节「使用方式」）：

```bash
git clone <本仓库地址> /path/to/init_your_proj
```

## 🔧 使用方式（两种）

### 方式一：绝对路径手动使用（不加环境变量）

直接用工具的绝对路径调用，在哪都能跑：

```bash
/path/to/init_your_proj/iyp init /path/to/my-proj
/path/to/init_your_proj/iyp check /path/to/my-proj
```

### 方式二：加入环境变量（推荐，之后直接用 `iyp` 命令）

**Linux / macOS：**

用 `echo $SHELL` 查看当前 shell，把配置写进对应的 rc 文件（不确定就都写）：

| Shell | 配置文件 | 写入方式 |
| --- | --- | --- |
| bash | `~/.bashrc` | `echo 'export PATH="/path/to/init_your_proj:$PATH"' >> ~/.bashrc` |
| zsh | `~/.zshrc` | `echo 'export PATH="/path/to/init_your_proj:$PATH"' >> ~/.zshrc` |
| fish | `~/.config/fish/config.fish` | `fish_add_path /path/to/init_your_proj` |

写入后重开终端，或 `source` 对应文件生效。

**Windows（PowerShell，当前会话）：**

```powershell
$env:PATH = "D:\tools\init_your_proj;$env:PATH"
iyp init D:\projects\my-proj
```

**Windows（永久生效）：**

```powershell
# 方式 1：setx（当前用户，新开的终端生效）
setx PATH "D:\tools\init_your_proj;$env:PATH"

# 方式 2：图形界面——系统设置 → 高级系统设置 → 环境变量 → 用户变量 Path → 新建 → 填 D:\tools\init_your_proj
```

### 用法一：手动使用

```bash
iyp init /path/to/my-proj     # 初始化项目（模板 + .gitignore + git init + 配置）
iyp check /path/to/my-proj    # 递归扫描目录下所有文本文件（默认 --dir）
iyp check --stage .           # 提交前卡点：只查本次暂存文件
```

### 用法二：pre-commit 框架（推荐）

在用户项目根创建 `.pre-commit-config.yaml`：

```yaml
repos:
  - repo: https://github.com/Fishskys/init_your_proj
    rev: v0.1.0                        # 使用最新发布 tag
    hooks:
      - id: iyp-check
```

然后安装并生效：

```bash
pip install pre-commit      # 或 pipx install pre-commit / brew install pre-commit
pre-commit install          # 在用户项目根执行，写入 .git/hooks/pre-commit
```

之后每次 `git commit` 自动执行 `iyp check --stage --strict`，命中阻断级问题返回非零退出码让 Git 取消提交。手动全量跑一遍：`pre-commit run --all-files`。

> hook 的完整定义在工具仓库的 `.pre-commit-hooks.yaml` 清单里（`entry: iyp check --stage --strict`、零交互、输出脱敏），用户侧只需写 `repo` / `rev` / `id` 三行；`rev` 须指向仓库真实存在的 tag。
> `check --stage` 专为提交卡点设计：只查本次暂存文件、零交互、不修改文件、不写白名单，命中值默认脱敏。

> 项目路径由用户指定：`iyp init .`、`iyp check /path/to/proj`；不填则使用当前工作目录。

---

## 📖 使用指南

### `iyp init [path]`

项目路径由用户指定（`iyp init .`、`iyp init /path/to/proj`）；不填则使用当前工作目录。

1. 复制 `templates/` 下的模板到项目根：`AGENTS_template.md` → `AGENTS.md`、`README_template.md` → `README.md`（已存在时询问覆盖，默认 n）。
2. 交互式问答生成个性化 `.gitignore`（已有则按分组去重追加：同名分组补行，新分组带注释追加，不覆盖原内容）：
   - 语言菜单：python / node / rust / go / java / c_cpp / dotnet / html_css / lua / ruby（默认不选）。
   - 固定加入、不询问的五段：编辑器垃圾文件 / 密钥文件（.env）/ 临时文件（tmp、temp）/ 日志文件 / `init_your_proj/` 工具自身。
   - 单独询问：是否把 AI agent 工具目录加入（`.hermes/` 等，默认 n）。
3. 检测项目是否已 git 初始化：没有则自动 `git init`。
4. 询问是否在用户项目根创建 `init_your_proj.toml` 增量配置（默认 n）；选 y 会生成模板并自动加入 `.gitignore`。

模板更新方式：直接编辑 `templates/` 下的模板文件并提交。

### `iyp check [path] [--dir|--stage|--git|--tracked] [--strict] [--raw]`

敏感信息检查：零交互、零修改。

**扫描范围（互斥，默认 `--dir`）：**

| 参数 | 范围 | 典型场景 |
| --- | --- | --- |
| `--dir`（默认） | 递归扫描目录下所有文本文件（无需 git 仓库） | 全目录体检 |
| `--stage` | 本次暂存文件 | pre-commit 钩子 |
| `--git` | 全部历史提交内容 | 排查已入库的泄漏（命中会提示需用 git filter-repo/BFG 重写历史） |
| `--tracked` | 全部被 git 跟踪的文件 | 全库体检（当前工作区状态） |
| `--raw` | （输出参数）命中值完整展示，不脱敏 | 默认脱敏，需看原文时用 |

**阻断与输出：**

- 零交互：不调用 input()，不要求选择处置动作；零修改：不改文件、不移除跟踪、不写白名单。
- 命中输出：文件:行号 + 规则名称 + 风险等级 + 命中值。默认脱敏（首尾 2 字符保留，中间 `***`）；**`--raw` 完整展示原文**。
- 默认 `high`/`medium` 阻断（非零退出码让 Git 取消提交），`low` 仅警告；**`--strict` 时 `low` 也阻断**。
- `--git` 命中时额外提示：泄漏已入库，需修改当前内容 + git filter-repo/BFG 重写历史。
- `--dir` 自动跳过 `.git`/`node_modules`/`__pycache__`/`.venv` 等垃圾目录与二进制文件。
- 误报处置：把特征子串加入 `init_your_proj.toml` 的 `check.whitelist_strings`（子串匹配）或 `ip_whitelist`（IP 类，支持 CIDR）。
- 检测内容 = 内置默认 + 工具根本机配置 + 用户项目根增量 toml（见配置说明）。

---

## ⚙️ 配置说明

配置分三层，合并顺序：**内置默认 → 工具根 `init_your_proj.toml`（本机值）→ 用户项目根 `init_your_proj.toml`（用户增量）**：

1. **内置默认**：17 组关键词（含动态本机值）+ 默认 IP 白名单，永远生效，无需任何文件。
2. **工具根本机配置**（`init_your_proj/init_your_proj.toml`）：clone 后**首次使用自动生成**（全量展开内置默认，含本机动态值），已被本仓库 `.gitignore` 排除；可在此改本机相关的 pattern、停用组。
3. **用户项目根增量**（可选）：init 时询问是否创建（默认 n），也可随时手动创建；只写想改的部分，check 时增量合并。若选择创建，会自动把该文件加入项目 `.gitignore`。

| 用户增量配置项 | 默认 | 作用描述 |
| --- | --- | --- |
| `[keywords].disable` | `[]` | 停用内置关键词组（写组名，如 `"github_pat"`） |
| `[keywords].extra` | `[]` | 追加自定义组：`{ name, pattern(正则), description, severity }` |
| `[check].whitelist_files` | `[]` | 整文件跳过（相对路径，支持 fnmatch 通配）——**追加到默认** |
| `[check].whitelist_strings` | `[]` | **子串白名单**：命中行包含任一字符串即不报——**追加到默认** |
| `[check].ip_whitelist` | `[]` | 在默认（`127.0.0.1`/`0.0.0.0`/常见公共 DNS/探测到的本机局域网 IP）之外追加；支持 CIDR 网段（如 `192.168.0.0/24`） |
| `[check].placeholder` | `<REDACTED:{name}>` | 覆盖默认占位符（当前版本 check 不做替换，预留给手动流程） |
| `[check].skip_files` | `[]` | 额外按文件名跳过（锁文件等默认已跳过）——**追加到默认** |

### 增量配置示例

```toml
[keywords]
disable = ["github_pat"]          # 本项目没有 GitHub token，停用该组
extra = [
  { name = "my_server", pattern = '10\.0\.0\.99', description = "内网服务器 IP", severity = "medium" },
]

[check]
ip_whitelist = ["192.168.31.53"]  # 文档里出现的这个内网地址不算命中
whitelist_strings = [
  "postgres://user:***@db/db",    # 脱敏示例特征子串（子串匹配）
]
```

### 常用操作

- **停用某组**：`[keywords].disable` 加组名。
- **新增组**：`[keywords].extra` 加一个块，`pattern` 写正则（TOML 双引号字符串，反斜杠需写成 `\\`）。
- **换机器**：本机用户名/路径/主机名/局域网 IP 均为运行时探测，换机器自动更新，无需手动改。
- **误报处理**：db_url 等**形状匹配**组的命中，改写文字躲不开（它认的是 DSN 结构）——正确处置是把示例特征子串加入 `whitelist_strings`，让白名单承载人工判定。

> IP 白名单是唯一 IP 排除机制：`ipv4` 组对**任意 IPv4（含公网）**都命中，只有 `ip_whitelist` 里的地址（精确或 CIDR 网段）不报。想让某公网 IP 不报就加进白名单，想监控它就移出白名单。

---

## 🗺️ 路线图

* [x] init / check 双子命令（check 四种扫描范围 + `--strict`/`--raw`）
* [x] 动态本机指纹（用户名/路径/主机名/局域网 IP）
* [x] 全量 IPv4 检测 + CIDR 白名单 + 脱敏示例过滤 + 二进制文件跳过
* [x] PATH 安装（IYP_HOME）与 pre-commit 钩子集成
* [x] 三层配置：内置默认 + 工具根本机 toml + 用户项目根增量 toml
* [ ] 更多语言/框架的 .gitignore 段

---

## 🤝 参与贡献

欢迎提交 Issue 与 Pull Request！

1. Fork 本仓库并新建特性分支 (`git checkout -b feature/AmazingFeature`)。
2. 新增关键词组请同步更新 `scripts/defaults.py` 与本 README 的配置说明。
3. 提交代码变更 (`git commit -m 'feat: add some amazing feature'`)。
4. 推送至分支并提交 Pull Request。

---

## 📄 文件结构

```
init_your_proj/
├── iyp                   # 可执行入口（仓库根与 scripts/ 各一份）
├── AGENTS.md             # 本仓库自身的协作准则（由 init 模板生成后按项目改写）
├── init_your_proj.toml   # 工具根本机配置（首次使用自动生成，已 gitignore）
├── templates/            # AGENTS.md / README.md 模板
├── scripts/
│   ├── __main__.py       # 入口
│   ├── cli.py            # 子命令分发与 help（init / check）
│   ├── common.py         # IYP_HOME 定位、三层配置合并、IP CIDR 白名单、终端工具
│   ├── agents_init.py    # init（确认路径 + 复制模板 + gitignore 问答 + git init + 配置）
│   ├── gitignore_gen.py  # .gitignore 问答树
│   ├── checker.py        # check（dir/stage/git/tracked 四种范围 + 白名单 + 脱敏）
│   └── defaults.py       # 默认关键词组 + 动态本机关键词生成
└── README.md
```
