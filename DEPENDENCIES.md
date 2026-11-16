# 依赖清单（DEPENDENCIES）

## 0. 支持平台

| 平台 | 状态 | 说明 |
|---|---|---|
| macOS | ✅ 支持 | 主要开发与验证环境 |
| Linux | ✅ 支持 | Debian / Ubuntu 等发行版；命令与 macOS 相同 |
| Windows | ❌ 不支持 | 安装脚本、Makefile、测试脚本均为 POSIX；不在支持范围内 |

本工具的实现（`pdf_normalize.py`）是**单文件 Python 脚本**，不依赖任何第三方 Python 包，
全部功能由标准库 + 系统命令行工具完成。
校验阶段的渲染比对会用到 Pillow（可选，缺失时自动退回 ImageMagick，再缺失则跳过比对）。

---

## 1. 运行时依赖

| 依赖 | 用途 | 必需 | 实测版本 | 最低要求 |
|---|---|---|---|---|
| Python 3 | 运行主程序 | ✅ 必需 | 3.14.4 | 3.10+（仅用标准库） |
| Ghostscript（`gs`） | `--mode outline` 文字转矢量轮廓（`-dNoOutputFonts`） | ✅ 供 outline/auto/both | 10.08.0 | 9.55+（`-dPreserveAnnots` 参数） |
| poppler：`pdftocairo` | `--mode image` 整页栅格化 | ✅ 供 image/auto/both | 26.11.0 | 0.60+ |
| poppler：`pdftoppm` | 输出校验时渲染比对 | ✅ 校验用 | 26.11.0 | 0.60+ |
| poppler：`pdffonts` | 字体诊断、类型错配检测 | ✅ 一直用 | 26.11.0 | 0.60+ |
| poppler：`pdfinfo` | 页数 / 页面尺寸 | ✅ 一直用 | 26.11.0 | 0.60+ |
| Pillow（PIL） | 校验时图片比对 | ⭕ 可选 | 12.2.0 | 8.0+ |
| Python 版本策略 | — | — | — | 3.8/3.9 已 EOL，项目支持 3.10+；CI 覆盖 3.10/3.12 |
| GNU make / bash | `make` 与测试脚本（开发/安装便利） | ⭕ 可选 | make 3.81 / bash 3.2 | — |
| ImageMagick（`magick`） | Pillow 缺失时的比对后备 | ⭕ 可选 | — | 7.x |

> 说明：`gs` 缺失时仍可用 `--mode image`；`pdftocairo` 缺失时仍可用 `--mode outline`。
> 两者都缺时只能用 `--mode fix`（辅助能力）。

---

## 2. 安装

### macOS（推荐）

```bash
# 方式 A：用项目自带的 Brewfile（make deps 会调用）
brew bundle --file=Brewfile

# 方式 B：直接装
brew install ghostscript poppler
```

Python 用系统自带或 Homebrew 的即可：

```bash
python3 --version        # 3.10+ 即可
```

### Ubuntu / Debian

```bash
sudo apt-get update
sudo apt-get install -y ghostscript poppler-utils python3
# 可选：sudo apt-get install -y python3-pil imagemagick
```

### 安装后自检

```bash
make deps          # 或：./pdf-normalize --doctor
```

期望输出：

```
pdf-normalize 1.0.0 环境自检

  ✓ gs         10.08.0  (最低 9.55)
  ✓ pdftocairo pdftocairo version 26.11.0  (最低 0.60)
  ✓ pdftoppm   pdftoppm version 26.11.0  (最低 0.60)
  ✓ pdffonts   pdffonts version 26.11.0  (最低 0.60)
  ✓ pdfinfo    pdfinfo version 26.11.0  (最低 0.60)
  ✓ PIL 可用（用于渲染比对）
```

---

## 3. Python 依赖

**无第三方运行时依赖。** 只用标准库：

| 标准库 | 用途 |
|---|---|
| `argparse` | 命令行参数 |
| `subprocess` | 调用 gs / poppler |
| `zlib` | 解析 PDF 字体流、生成图片 PDF 的压缩流 |
| `re` | PDF 对象扫描 |
| `json` | `--json` 输出 |
| `tempfile` | 临时渲染目录 |
| `pathlib` / `os` / `shutil` | 路径与文件操作 |

`requirements.txt` 为空（仅注释），保留它是为了让 `pip install -r requirements.txt` 这类自动化流程不报错。

---

## 4. 版本兼容性说明

| 工具 | 低版本风险 | 处理方式 |
|---|---|---|
| Ghostscript < 9.55 | 不识别 `-dPreserveAnnots`，会报错退出 | 升级；或从 `pdf-normalize` 的 `build_outline()` 里删掉该参数 |
| Ghostscript < 9.05 | 没有 `-dNoOutputFonts`（核心能力） | 必须升级到 9.55+ |
| poppler < 0.60 | `pdftocairo` 可能不支持 `-jpegopt` | 升级 poppler |
| Pillow 缺失 | 校验退化为 ImageMagick；再缺失则跳过渲染比对（只校验页数/字体数） | 可接受，不影响转换 |

---

## 5. 无网络 / 离线环境

本工具**不联网、不上传文件**，所有处理在本机完成。
离线机器只需要预装上表中的命令行工具即可；Python 标准库随 Python 自带。

---

## 6. 一键检查脚本

```bash
# 项目内
make deps

# 或直接
./pdf-normalize --doctor
```

`make deps` 会：检测 Homebrew → 用 `Brewfile` 安装缺失依赖 → 再跑一次自检。

---

## 7. 第三方工具许可

| 工具 | 许可证 | 本项目如何使用 |
|---|---|---|
| Ghostscript | AGPL-3.0 | 以**独立进程**方式调用（`subprocess`），不链接、不修改、不随项目分发 |
| poppler | GPL-2.0 / GPL-3.0 | 同上，独立进程调用 |
| Pillow | MIT-CMU | 可选，Python 库方式导入，仅用于校验比对 |
| ImageMagick | ImageMagick License | 可选，独立进程调用 |

因此本项目的代码以 MIT 许可证发布；上面这些工具需要使用者**自行安装**，
其许可证义务由使用者按各自场景评估（尤其是 AGPL 工具的商用边界）。
