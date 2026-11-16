# pdf-normalize

> 把「一打印就乱码」的 PDF 规范化成任何打印机都能打印的文件。

很多中文 PDF（WPS、macOS 导出工具等生成）在屏幕上完全正常，打印出来却是乱码：
原因是文件把 **OpenType-CFF 字体**（PingFang、思源黑体等）声明成了 TrueType 槽位，
还整包嵌入了十几 MB 的字体文件。屏幕阅读器都容错，打印机 RIP——尤其是
**远程桌面 / 云桌面的打印重定向**——不容错。

`pdf-normalize` 的处理思路很直接：**让 PDF 里一个字体都不剩**。

- **零字体**：文字转成矢量轮廓（默认），或整页栅格化（保底）；
- **版式不变**：页数、页面尺寸、内容、图片、水印位置全部保留，并有逐页渲染比对兜底；
- **一个命令**：`pdf-normalize 简历.pdf` → `简历-print.pdf`；
- **批量可用**：目录递归、多文件、`--json`、退出码，适合脚本与流水线；
- **本地处理**：不联网、不上传、无遥测，适合处理合同、简历等敏感文档。

---

## 适用范围

| 平台 | 状态 | 说明 |
|---|---|---|
| macOS | ✅ 支持 | 主要开发与验证环境 |
| Linux | ✅ 支持 | Debian / Ubuntu 等发行版；用法与 macOS 相同 |
| Windows | ❌ 不支持 | 未适配（安装脚本、Makefile、测试脚本均为 POSIX 脚本），不在支持范围内 |

---

## 安装

```bash
# 1) 系统依赖（macOS / Linux 二选一）
brew install ghostscript poppler        # macOS
sudo apt-get install -y ghostscript poppler-utils python3   # Debian / Ubuntu

# 2) 本工具
git clone https://github.com/jiggersong/pdf-normalization.git
cd pdf-normalization
./install.sh            # 装成全局命令 pdf-normalize
```

也可以不安装，直接 `./pdf-normalize` 使用；或 `pipx install .`（需要 Python 3.8+）。

```bash
pdf-normalize --doctor   # 自检（含 gs / poppler 版本下限检查）
```

---

## 快速开始

```bash
# 默认：矢量轮廓版（推荐）
pdf-normalize 简历.pdf
#   -> 简历-print.pdf（零字体，约 1.5 MB，页数/尺寸不变）

# 保底：整页图片版（任何打印链路都能打）
pdf-normalize --mode image --dpi 300 简历.pdf
#   -> 简历-print-300dpi.pdf

# 只诊断，不写文件（批量筛查很实用）
pdf-normalize --mode check -r ~/Documents/合同/

# 批量递归处理，输出到指定目录
pdf-normalize -r -o ~/Desktop/打印版 ~/Documents/简历/
```

完整手册（全部参数、模式细节、退出码、JSON、FAQ）见 **[docs/USAGE.md](docs/USAGE.md)**。

---

## 模式

| 模式 | 原理 | 文字可选中 | 体积 | 适用 |
|---|---|---|---|---|
| `auto`（默认） | 先轮廓化，校验不过自动降级为图片 | 否 | 小 | 不确定时的默认选择 |
| `outline` | 文字 → 矢量轮廓（Ghostscript `-dNoOutputFonts`） | 否 | 小 | **首选**，任意 DPI 清晰 |
| `image` | 整页栅格化（pdftocairo + JPEG） | 否 | 中 | 轮廓版仍打不出来时的保底 |
| `fix` | 只修字体声明 | 是 | 不变 | 想保留可选中文字（兼容性有限） |
| `both` | 同时产出 outline + image | 否 | 两份 | 交给别人时一次给两种 |
| `check` | 只诊断 | — | — | 批量筛查风险文件 |

---

## 自动校验

每份输出都会与原件对比，不通过就报错（`auto` 会自动降级重试）：

1. 页数一致；
2. 输出字体数必须为 0（outline / image）；
3. 双方 110 dpi 渲染后逐页比对：模糊 1.2px 后灰度差均值 ≤ 4/255、显著差异像素 ≤ 1.5%。

```
输出: 简历-print.pdf  (1.5 MB)
校验: 页数一致，字体 0 个，渲染差 均值 1.60 / 差异像素 0.03%  ✓
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [docs/USAGE.md](docs/USAGE.md) | 完整使用手册：参数、模式、批量、校验、退出码、JSON、FAQ |
| [docs/DESIGN.md](docs/DESIGN.md) | 方案设计文档：问题根因与证据、方案选型、架构、实现细节、限制 |
| [DEPENDENCIES.md](DEPENDENCIES.md) | 依赖清单、版本要求、macOS / Linux 安装方式、许可说明 |
| [CHANGELOG.md](CHANGELOG.md) | 版本变更记录 |
| [Brewfile](Brewfile) | Homebrew 依赖（ghostscript + poppler） |

终端里执行 `make` 也能直接看到完整用法与实时依赖状态。

---

## 目录结构

```
pdf-normalization/
├── pdf-normalize          # 命令行入口（软链目标）
├── pdf_normalize.py       # 实现（Python 3，仅标准库）
├── install.sh             # 安装到 PATH
├── Makefile               # make：用法/依赖/测试/演示/安装
├── pyproject.toml         # pip / pipx 安装配置
├── README.md
├── CHANGELOG.md
├── LICENSE                # MIT
├── DEPENDENCIES.md
├── Brewfile
├── requirements.txt       # 空：无第三方 Python 依赖
├── .github/workflows/ci.yml
├── docs/
│   ├── USAGE.md
│   └── DESIGN.md
└── tests/
    ├── test_patch.py      # 单元测试（合成 PDF，不依赖真实文件）
    └── smoke.sh           # 端到端冒烟测试（现场生成样本）
```

---

## 开发

```bash
make            # 查看用法（默认目标）
make deps       # 安装/检查依赖
make test       # 单元测试 + 冒烟测试
make unit       # 只跑单元测试
make smoke      # 只跑冒烟测试
make demo       # 生成演示 PDF 并转换到 ./demo-output
make install    # 装成全局命令
make clean      # 清理缓存与演示产物
```

CI 配置见 [.github/workflows/ci.yml](.github/workflows/ci.yml)（Ubuntu + macOS 双平台跑 `make test`）。

---

## 许可证

本项目采用 [MIT License](LICENSE)。

## 第三方依赖许可

本工具把 **Ghostscript**（AGPL-3.0）与 **poppler**（GPL-2.0/3.0）作为**独立命令行程序调用**，
不链接、不修改、不随本项目分发它们，需要用户自行安装；它们各自的许可证不影响本项目代码的 MIT 授权。
商业/闭源场景使用前，请自行评估 AGPL / GPL 工具的使用边界。

## 隐私

所有处理都在本机完成：不联网、不上传文件、无遥测。Ghostscript 以 `-dSAFER` 运行，
并且永远不会修改输入文件（输出另存）。

## 贡献

欢迎 issue / PR。提交前请确保 `make test` 通过；文档改动保持中文、简洁。
