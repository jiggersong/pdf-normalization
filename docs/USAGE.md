# 使用说明（USAGE）

`pdf-normalize` 把「屏幕上正常、一打印就乱码」的 PDF 转成**任何打印机都能打印**的文件。
本文件是完整使用手册；项目概览见 [README](../README.md)，设计原理见 [DESIGN.md](DESIGN.md)。

---

## 1. 适用范围

### 支持平台

| 平台 | 状态 | 说明 |
|---|---|---|
| macOS | ✅ 支持 | 主要开发与验证环境（macOS 12+ 实测；Ghostscript 从 Homebrew 安装） |
| Linux | ✅ 支持 | Debian/Ubuntu 等发行版实测；`pdf-normalize` 主体与 macOS 完全一致 |
| Windows | ❌ 不支持 | 未适配（安装脚本、Makefile、测试脚本均为 POSIX 脚本）。如自行安装 Ghostscript + poppler，Python 主体理论上可运行，但不在支持范围内，不保证可用 |

### 适用的 PDF

- 中文 PDF（简历、合同、报告、发票、证明等）**打印乱码 / 打出来是方块或乱字符**；
- 嵌入字体体积异常巨大（整包嵌入）的 PDF；
- 需要交给「严格打印机 / 远程桌面打印重定向」输出，但原件打印失败的 PDF。

### 不适用的场景

- 扫描件 PDF（本来就是图片）——转出来还是图片，用 `--mode image` 即可，但没有"修字体"的意义；
- 需要文字可编辑/可搜索的 PDF（`outline`/`image` 会失去文字层；此类需求用 `--mode fix` 但兼容性有限）；
- 印刷级要求（专色、出血、装订、PDF/X）——本工具只保证"打印不乱码、版式不变"。

---

## 2. 安装

### 2.1 安装系统依赖

macOS：

```bash
brew install ghostscript poppler
```

Debian / Ubuntu：

```bash
sudo apt-get update
sudo apt-get install -y ghostscript poppler-utils python3
```

可选（仅用于输出后的渲染校验，缺失会自动跳过）：

```bash
# macOS
brew install imagemagick
pip3 install --user pillow

# Debian/Ubuntu
sudo apt-get install -y imagemagick python3-pil
```

### 2.2 安装本工具

方式 A：项目内安装成命令（推荐）

```bash
cd pdf-normalization
./install.sh            # 软链到 /usr/local/bin 或 ~/.local/bin
```

方式 B：直接用仓库里的脚本，不安装

```bash
./pdf-normalize --help
```

方式 C：用 pipx / pip 安装（需要 Python 3.8+）

```bash
pipx install .          # 或： python3 -m pip install --user .
pdf-normalize --version
```

### 2.3 自检

```bash
pdf-normalize --doctor
```

期望输出（版本号以本机为准）：

```
pdf-normalize 1.0.0 环境自检

  ✓ gs         10.08.0  (最低 9.55)
  ✓ pdftocairo pdftocairo version 26.11.0  (最低 0.60)
  ✓ pdftoppm   pdftoppm version 26.11.0  (最低 0.60)
  ✓ pdffonts   pdffonts version 26.11.0  (最低 0.60)
  ✓ pdfinfo    pdfinfo version 26.11.0  (最低 0.60)
  ✓ PIL 可用（用于渲染比对）
```

版本低于下限会标 `⚠` 并以非 0 退出。

---

## 3. 命令总览

```
pdf-normalize [选项] <文件或目录>...
```

| 选项 | 说明 | 默认 |
|---|---|---|
| `-m, --mode {auto,outline,image,fix,both,check}` | 处理模式 | `auto` |
| `-o, --out DIR` | 输出目录 | 与源文件同目录 |
| `-d, --dpi N` | 栅格化分辨率（仅 image） | `300` |
| `--jpeg-quality N` | 栅格化 JPEG 质量 | `92` |
| `--lossy-images` | 轮廓化时允许图片有损转存（照片多时减小体积） | 关 |
| `-r, --recursive` | 递归处理目录 | 关 |
| `-f, --force` | 允许覆盖已存在的输出 | 关 |
| `--suffix S` | 输出文件名后缀 | `-print` |
| `--no-verify` | 跳过输出后的渲染校验（更快） | 关 |
| `--password PW` | 加密 PDF 的密码 | — |
| `--json` | 以 JSON 输出结果（含诊断与校验数据） | 关 |
| `-q, --quiet` | 只输出错误 | 关 |
| `--doctor` | 环境自检 | — |
| `-V, --version` | 版本号 | — |

---

## 4. 模式详解

### 4.1 `outline`（默认推荐）：文字转矢量轮廓

原理：Ghostscript `-dNoOutputFonts` 把每个字转成填充路径，输出 PDF **不含任何字体**。
产物：`原名-print.pdf`。

```bash
pdf-normalize 简历.pdf
```

适合：几乎所有需要打印的 PDF。任意 DPI 都清晰，体积通常比原件还小。
限制：文字不可选中/搜索；元数据、书签会丢失。

### 4.2 `image`（保底）：整页栅格化

原理：pdftocairo 把每页渲染成 JPEG，再重新打包成 PDF（页面尺寸沿用原文档）。
产物：`原名-print-300dpi.pdf`。

```bash
pdf-normalize --mode image --dpi 300 简历.pdf
```

适合：打印机 / 打印链路连矢量都处理不好的极端情况（例如远程桌面打印重定向）。
限制：文字不可选中；体积较大（4 页约 3–4 MB）；清晰度受 dpi 限制。

### 4.3 `auto`（默认）：先轮廓化，失败自动降级

```bash
pdf-normalize 合同.pdf
```

先按 `outline` 处理并校验；若 Ghostscript 失败或校验不通过，自动删除产物、改用 `image` 重试。

### 4.4 `both`：两份都出

产物：`原名-print.pdf` + `原名-print-300dpi.pdf`。适合一次给同事/HR 两种格式。

### 4.5 `fix`（辅助）：只修字体声明

修正「CFF 字体被塞进 TrueType 槽位」等错配，**保留文字可选中**，但不改变字体本身。
产物：`原名-print-fix.pdf`。

```bash
pdf-normalize --mode fix 简历.pdf
```

限制：若打印链路无法解析 CFF 字体程序，修完照样乱码（这时请用 `outline`/`image`）；
对象位于压缩对象流（ObjStm）的 PDF 无法原位改，会提示改用 `outline`/`image`。

### 4.6 `check`：只诊断

```bash
pdf-normalize --mode check 简历.pdf
pdf-normalize --mode check -r 简历目录/
```

输出页数、页面尺寸、字体数、字体类型错配数、风险提示，**不写任何文件**。
适合批量筛查"哪些 PDF 打印有风险"。

---

## 5. 批量与输出

```bash
# 多文件
pdf-normalize a.pdf b.pdf c.pdf

# 整个目录（不递归）
pdf-normalize -o 打印版/ 合同/

# 递归 + 指定输出目录
pdf-normalize -r -o 打印版/ ~/Documents/简历/

# 覆盖已存在的输出
pdf-normalize -f 简历.pdf

# 自定义后缀
pdf-normalize --suffix -可打印 简历.pdf     # 简历-可打印.pdf
```

规则：

- 输入文件**永远不会被修改**；
- 默认输出到源文件所在目录，同名文件已存在时自动加 `-2`、`-3`（`-f` 强制覆盖）；
- 目录扫描只处理 `*.pdf`，并自动跳过本工具生成的文件（`-print`、`-print-300dpi`、`-print-fix`）。

---

## 6. 自动校验

每份输出默认都会与原件对比：

1. **页数**必须一致；
2. **字体数**：`outline`/`image` 必须为 0；`fix` 要求类型错配清零；
3. **渲染比对**：双方按 110 dpi 渲染（页数多时自动降到 80/72 dpi），高斯模糊 1.2px 后比较灰度差。

阈值（模糊后）：

| 模式 | 灰度差均值上限 | 显著差异像素上限 |
|---|---|---|
| outline | 4.0 / 255 | 1.5% |
| image | 20 / 255 | 25% |
| fix | 1.0 / 255 | 0.1% |

校验通过会打印 `校验: 页数一致，字体 0 个，渲染差 均值 1.60 / 差异像素 0.03% ✓`。
不通过则以非 0 退出码结束（`auto` 会自动降级重试）。
只信页数/字体数、不在意渲染比对时可用 `--no-verify` 提速。

---

## 7. 退出码与 `--json`

| 退出码 | 含义 |
|---|---|
| 0 | 全部成功 |
| 1 | 用法错误 / 缺少依赖 |
| 2 | 输出未通过校验 |
| 3 | 批量中部分文件失败 |

`--json` 输出结构（节选）：

```json
{
  "version": "1.0.0",
  "mode": "outline",
  "results": [
    {
      "input": "/path/简历.pdf",
      "ok": true,
      "mode": "outline",
      "outputs": ["/path/简历-print.pdf"],
      "diagnosis": {"pages": 4, "fonts": 4, "mismatch": 8, "notes": ["..."]},
      "verify": {"pages_ok": true, "fonts": 0,
                 "verify": {"mean": 1.6, "pct": 0.03, "ok": true}}
    }
  ],
  "summary": {"total": 1, "ok": 1, "failed": 0}
}
```

---

## 8. 典型工作流

### 8.1 打印前自检（推荐）

```bash
pdf-normalize --mode check 简历.pdf
# 有「⚠ 类型错配」→ 直接转
pdf-normalize 简历.pdf
```

### 8.2 简历 / 合同 / 证明

```bash
pdf-normalize -o ~/Desktop/打印版 简历.pdf
# 打印 ~/Desktop/打印版/简历-print.pdf
```

### 8.3 扫描件（本来就没字体的 PDF）

```bash
pdf-normalize --mode image --dpi 200 扫描件.pdf   # 200 dpi 足够，体积更小
```

### 8.4 加密 PDF

```bash
pdf-normalize --password 你的密码 加密文件.pdf
```

### 8.5 把结果交给别人

```bash
pdf-normalize --mode both -o 输出/ 文件.pdf
# 同时给矢量版（清晰）和图片版（保底）
```

### 8.6 与脚本集成

```bash
# 只处理有风险的 PDF
pdf-normalize --json -r 目录/ | python3 -c '
import json,sys
d=json.load(sys.stdin)
for r in d["results"]:
    if r["diagnosis"]["mismatch"]:
        print(r["input"])
'
```

---

## 9. 常见问题

**Q1：转换后还是乱码？**
A：先用 `--mode image`（纯图片，不涉及任何字体解析）。仍乱码说明问题不在 PDF 字体，
而在打印驱动/打印机本身（例如驱动损坏、纸张设置、RIP 内存不足）。

**Q2：输出文件比原件大？**
A：`outline` 默认图片无损转存，照片多的 PDF 会变大，可加 `--lossy-images`；
`image` 版体积随 dpi 上升，200–300 dpi 通常够用。

**Q3：文字不能选中/搜索了？**
A：`outline`/`image` 的设计代价。需要可选中用 `--mode fix`（兼容性有限），
或先保留一份原件用于存档。

**Q4：`fix` 提示「字体对象位于压缩对象流(ObjStm)中」？**
A：这种 PDF 无法原位改声明，直接用默认 `outline`/`image` 即可（不依赖改声明）。

**Q5：Ghostscript / poppler 版本太老？**
A：`--doctor` 会给出下限提示；升级 `gs` 到 9.55+、poppler 到 0.60+。

**Q6：中文文件名 / 带空格路径？**
A：支持。Linux 若出现编码问题，设置 `LANG=zh_CN.UTF-8` 或 `LC_ALL=en_US.UTF-8`。

**Q7：源 PDF 用了未嵌入的 base-14 字体（如 Helvetica）会怎样？**
A：Ghostscript 会用自带的 URW 字体替代，字形可能与原件略有差异；校验会体现在
「渲染差」数值上，超过阈值会判失败并提示改用 `image`。

**Q8：能批量把一个目录里所有"有问题"的 PDF 都转掉吗？**
A：可以，先用 `--mode check -r` 筛出 `mismatch > 0` 的，再单独转换。

---

## 10. 性能参考

| 场景 | 耗时 | 输出体积 |
|---|---|---|
| 4 页简历 outline | gs 约 1–2 s + 校验约 1 s | 约 1.5 MB |
| 4 页简历 image@300dpi | 约 2–3 s | 约 3.6 MB |
| 6 页简历 outline | 约 2–4 s | 约 3.5 MB |
| 数百份批量 check | 每分钟约 100–150 份 | — |

---

## 11. 安全与隐私

- 全程**本地处理**，不联网、不上传、无遥测；
- Ghostscript 以 `-dSAFER` 运行，禁止文件系统写入与危险 PostScript 操作；
- 不改动源文件；输出另存；
- 不主动移除源 PDF 的水印/DRM（内容原样保留）。
