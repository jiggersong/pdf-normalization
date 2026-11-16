# pdf-normalize 方案设计文档

> 版本：1.0.0 ｜ 状态：已实现并验证 ｜ 适用：中文 PDF（WPS / Quartz / 各类导出工具生成）
> 打印乱码的规范化处理

---

## 1. 背景与问题定义

用户从招聘平台下载的简历 PDF，在 macOS 上预览完全正常，但打印出来整页乱码；
换成「整页图片版 PDF」后可以正常打印。

由此可以先把问题限定为：**PDF 的**内容**没有问题，出问题的是**字体**——屏幕阅读器
（macOS 预览 / Chrome / WPS / poppler / MuPDF）对字体格式都容错，打印链路上的 RIP
（光栅图像处理器）不一定是容错的。

本工具要解决的就是这一类「**屏幕正常、打印乱码**」的 PDF，把它转换成
**任何打印链路都能输出的文件**，且**内容与版式不变**。

---

## 2. 根因分析

### 2.1 直接证据

对出问题的简历执行 `pdffonts`：

```
name                       type              encoding    emb sub uni
ELNWFV+PingFangSC-Regular  CID Type 0C (OT)  Identity-H  yes yes yes
QUOZGE+PingFangSC-Semibold CID Type 0C (OT)  Identity-H  yes yes yes
DCUOFF+STSongti-SC-Regular CID TrueType      Identity-H  yes yes yes
Helvetica                  Type 1            WinAnsi     no  no  no

Syntax Warning: Mismatch between font type and embedded font file   ← 8 处
```

再解剖字体对象，可以看到错配的物理形态：

| 项目 | 实际情况 |
|---|---|
| 字体声明 | `/Subtype /CIDFontType2` + `/FontFile2`（**TrueType 槽位**） |
| 内嵌程序 | 文件头 `OTTO`，即 **OpenType / CFF** 轮廓 |
| 嵌入体积 | `Length1 = 12,259,924` 字节 ≈ **整个字体文件**，未做子集化 |
| 其余字体 | 同文件里的 STSongti（TrueType）声明正确，说明不是「所有字体都错」 |

即：**CFF 字体被塞进了 TrueType 的槽位，而且是整包嵌入、没有子集化。**

### 2.2 责任链定位（重要，避免误判）

结论：缺陷发生在**生成 PDF 的导出工具链**，不是招聘平台水印处理。

证据来自内部脱敏测试语料（732 份简历）的横向比对：

| 观察 | 数据 |
|---|---|
| 有字体类型错配的文件 | 15 / 732（约 2%） |
| 其中由 WPS 导出 | 14 份（WPS 文字 / WPS 演示） |
| 其中由 pdf-lib 生成 | 1 份 |
| 平台自建模板（Creator 为平台自身） | 78 份，**全部干净** |
| 经 iText 处理（平台/ATS 水印）的文件 | 583 份，其中仅 14 份有缺陷 |
| 对照组：无 iText、无平台水印的纯 Quartz 导出（已匿名） | **同样缺陷** |

对照组是关键：该文件 Producer 只有 `macOS 15.4.1 Quartz PDFContext`，没有任何
平台处理痕迹，但 PingFang 同样是 `CIDFontType2 + FontFile2 + OTTO + 12.5MB`。
因此错配在候选人的 Mac 导出 PDF（WPS → CoreGraphics）这一步就已经存在，
平台的 iText 水印工序只是**原样复制字体对象**，并未制造、也没能修复该缺陷。

补充：同一批文件里多个不同文档的字体子集前缀完全相同（`ELNWFV+`、`QUOZGE+`…），
这是 Apple 端按字体名生成子集标签的指纹；再结合「每个字体都是整包嵌入」，
可以判断是 macOS CoreGraphics 在无法子集化特殊系统字体（PingFang）时走了
「整包嵌入 + TrueType 描述模板」的回退路径。

### 2.3 为什么「只是声明错」也会乱码

- 屏幕阅读器：`poppler`/`MuPDF`/CoreGraphics 都实现了「嗅探真实字体格式」的容错，
  即使声明是 CIDFontType2，也能识别出 OTTO 并按 CFF 渲染 → 屏幕正常。
- 打印链路：任务离开应用后，通常会被打印机驱动/RIP 重新解析一次。
  遇到严格实现（只认声明、或根本无法解析 12MB 的 CID-keyed CFF）时，
  字形索引全部错位，输出就是乱码/方块。
- 用户环境的特殊之处：默认打印机是 `RDPrinter`，设备 `IBackend:`，
  属于**远程桌面 / 云桌面的打印重定向**——作业由远端/客户端渲染器接管，
  比本地 CUPS 更严格。这也解释了「图片版能打、矢量字体版不能打」：
  图片不涉及任何字体解析。

### 2.4 为什么「把声明改对」不够

第一版修复（`--mode fix`）只把 `CIDFontType2 → CIDFontType0`、
`FontFile2 → FontFile3`，`pdffonts` 不再报 mismatch，渲染也逐像素一致；
但在用户的远程打印链路上**依然乱码**。

原因：严格 RIP 的问题不只是「声明与程序不一致」，而是**它解析不了这个体积的
CID-keyed CFF 字体程序**。声明改对只是让它有资格去解析，解析失败依旧乱码。

→ 设计结论：**唯一稳妥的做法是让 PDF 里没有任何字体**。

---

## 3. 设计目标与非目标

### 目标

1. **可打印**：输出在严格 RIP（含远程打印重定向）下不依赖字体解析；
2. **内容与版式不变**：页数、页面尺寸、文字内容、图片、分栏、水印位置保持一致，
   并有可量化的自动校验兜底；
3. **一个命令可用**：`pdf-normalize 文件.pdf` 即可，无需查参数；
4. **可批量 / 可自动化**：支持目录递归、多文件、`--json`、退出码；
5. **不破坏源文件**：只读输入，输出另存，默认不覆盖；
6. **可诊断**：能一眼看出某个 PDF 是否有乱码风险（`--mode check`）。

### 非目标

- 不保证输出 **保留可选中文字**（`outline`/`image` 会把文字变成图形/位图；
  需要可选中时用 `--mode fix`，但兼容性有限）；
- 不保留 **元数据 / 书签**（Ghostscript 重写会丢 Title/Author 等，打印无影响）；
- 不修复 **源 PDF 的字体声明之外** 的结构问题（如损坏的 xref）；
- 不做「原件修复后仍可编辑」的语义级重建；
- 不提供 GUI。

---

## 4. 方案选型

| 方案 | 原理 | 打印兼容性 | 清晰度 | 体积 | 文字可选中 | 结论 |
|---|---|---|---|---|---|---|
| **A. 只修声明**（fix） | 改正 `/Subtype`、`/FontFile*` | 中（宽松 RIP 可，严格 RIP 仍失败） | 原样 | 不变 | ✅ | 辅助能力，保留 |
| **B. 矢量轮廓**（outline） | 文字转填充路径，`-dNoOutputFonts` | **高**（无字体） | **任意 DPI 清晰** | 小（≈原文件） | ❌ | **默认方案** |
| **C. 整页栅格**（image） | 每页渲染成 300dpi JPEG，重新打包 PDF | **最高**（纯图片） | 300dpi | 中 | ❌ | 保底方案 |
| D. 转 PostScript/其他格式 | 格式转换 | 低（更依赖 RIP） | — | — | ❌ | 排除 |
| E. 子集化重嵌字体 | 重新做子集、修正声明 | 中高 | 原样 | 小 | ✅ | 依赖 fontTools 与 CFF 处理，复杂度高，留作后续 |

最终产品化：**B 为默认，C 为保底，A 为辅助，另提供 auto（B 失败自动降级 C）与 both（B+C 同时产出）**。

---

## 5. 架构设计

```
                       ┌──────────────────────────────────────────┐
                       │              CLI（argparse）              │
                       │  模式/参数/密码/输出目录/JSON/退出码      │
                       └───────────────────┬──────────────────────┘
                                           │
                       ┌───────────────────▼──────────────────────┐
                       │        输入收集 collect_inputs           │
                       │  文件/目录/递归/去重/跳过本工具产物      │
                       └───────────────────┬──────────────────────┘
                                           │ 每个 PDF
              ┌────────────────────────────▼───────────────────────────┐
              │                     process_one                         │
              │                                                        │
              │  ┌──────────┐   ┌───────────────────────────────────┐  │
              │  │ diagnose │   │          转换器（Converter）        │  │
              │  │ pdfinfo  │   │  outline : gs -dNoOutputFonts     │  │
              │  │ pdffonts │   │  image   : pdftocairo + 自建 PDF  │  │
              │  │ 风险判定 │   │  fix     : 字体声明修复 + xref 重建│  │
              │  └────┬─────┘   └───────────────┬───────────────────┘  │
              │       │                         │                      │
              │       └────────────┬────────────┘                      │
              │                    ▼                                   │
              │        ┌───────────────────────────┐                   │
              │        │   verify（自动校验）       │                   │
              │        │ 页数 / 字体数 / 渲染比对   │                   │
              │        └───────────┬───────────────┘                   │
              │                    │ 失败(仅 auto) ──► 降级为 image      │
              └────────────────────┼───────────────────────────────────┘
                                   ▼
                        ┌──────────────────────┐
                        │ 报告（文本 / JSON）   │
                        │ 成功/失败/退出码      │
                        └──────────────────────┘
```

### 模块职责

| 模块 | 位置 | 职责 |
|---|---|---|
| CLI | `build_parser()` / `main()` | 参数解析、依赖检查、批量调度、汇总与退出码 |
| 诊断 | `diagnose()` / `pdffonts_scan()` | 页数、页面尺寸、字体数、类型错配数、CFF 标记、建议 |
| 轮廓转换 | `build_outline()` | 调 Ghostscript，PDF 1.4、无损图片、`-dNoOutputFonts` |
| 栅格转换 | `build_raster()` / `_build_image_pdf()` | pdftocairo 出 JPEG → 按原页尺寸自建无字体 PDF |
| 声明修复 | `repair_font_declarations()` 等 | 扫描对象、探测字体程序真实格式、双向修正、xref 重建 |
| 校验 | `verify_output()` / `_compare()` | 页数、字体数、逐页渲染比对（阈值随模式） |
| 报告 | `print_result()` / `--json` | 人类可读 + 机器可读 |

---

## 6. 关键实现细节

### 6.1 轮廓化（outline）

```
gs -q -dNOPAUSE -dBATCH -dSAFER \
   -sDEVICE=pdfwrite \
   -dCompatibilityLevel=1.4 \          # 兼容老 RIP：无对象流/交叉引用流
   -dNoOutputFonts \                   # 核心：文字 → 填充路径
   -dAutoRotatePages=/None \           # 不擅自旋转页面
   -dDownsample*Images=false \         # 不降采样，保持原始分辨率
   -dAutoFilter*Images=false + /FlateEncode   # 图片无损转存（可用 --lossy-images 放开）
   -dPreserveAnnots=true \
   -sOutputFile=out.pdf in.pdf
```

要点：
- `-dNoOutputFonts` 之后输出 PDF **不含任何字体对象**，`pdffonts` 为空；
- 兼容级别压到 1.4，避免 `ObjStm`/`XRef` 流这类新特性被老 RIP 拒绝；
- 页面尺寸、页面数由 gs 原样保持；
- 默认图片无损（简历类文件体积可控），照片多时可 `--lossy-images` 换体积。

### 6.2 栅格化（image）

1. `pdftocairo -jpeg -r <dpi> -jpegopt quality=<q> in.pdf page` → 每页一张 JPEG；
2. 自建 PDF：每页一个 `DCTDecode` 图像 XObject + 一条 `q w 0 0 h 0 0 cm /Im0 Do Q`；
3. **页面尺寸沿用原文档的 pt 尺寸**（`pdfinfo`），而不是用 `像素 × 72 / dpi`，
   避免出现 595.95pt → 596.16pt 的偏差；多页尺寸不一致时自动逐页换算；
4. 全流程不需要 Pillow（JPEG 宽高由 `jpeg_size()` 解析 SOF 标记）。

### 6.3 声明修复（fix，辅助）

处理两种错配，双向都能修：

| 情况 | 修正 |
|---|---|
| 声明 CIDFontType2 / FontFile2，程序是 `OTTO`(CFF) | → CIDFontType0 / FontFile3 + `/Subtype/OpenType` |
| 声明 CIDFontType0 / FontFile3，程序是 TrueType | → CIDFontType2 / FontFile2 |

技术路线：
- 正则扫描顶层 `N 0 obj`，用 `<<`/`>>` 配对定位字典区间；
- 顺着 `/FontDescriptor` → `/FontFile2|3` → 字体流，`zlib` 解压前 16 字节读文件头；
- 修改后**重建经典 xref 表**（保留 `/Root`、`/Info`、`/ID`），保证偏移正确；
- 局限：对象位于 `ObjStm` 压缩对象流时无法原位改（明确提示改用 outline/image）。

### 6.4 auto 降级

`auto` = 先 outline → 自动校验；若 gs 失败或校验不通过，删除产物、改用 image 重试。
这样用户既拿到最高质量，又不会因为个别异常 PDF 卡住。

---

## 7. 校验策略

| 检查 | 判据 | 不通过处理 |
|---|---|---|
| 页数 | 输出页数 == 源页数且 > 0 | 标记失败 |
| 字体数 | outline/image 必须为 **0**；fix 只要求错配清零 | 标记失败 |
| 渲染内容 | 双方按 110/80/72 dpi 渲染（随页数自适应），高斯模糊 1.2px 后比较灰度差 | 超过阈值标记失败，auto 降级 |

阈值（模糊后）：

| 模式 | 灰度差均值上限 | 显著差异像素上限（>40/255） | 设计理由 |
|---|---|---|---|
| outline | 4.0 | 1.5% | 轮廓化与文字渲染只差字形边缘的抗锯齿，实测 1.6 / 0.03% |
| image | 20.0 | 25% | 栅格化本身有重采样差异，阈值放宽但仍能抓住空白页/错页 |
| fix | 1.0 | 0.1% | 只改声明，理想情况逐像素一致，实测 0.00 |

比对工具优先级：Pillow（首选）→ ImageMagick `compare` → 跳过并给出提示。

---

## 8. 错误处理与退出码

| 场景 | 行为 | 退出码 |
|---|---|---|
| 正常完成 | 输出 + 校验报告 | 0 |
| 参数/依赖问题、文件不存在、无法处理 | stderr 提示 | 1 |
| 输出未通过校验 | 报告差异数据 | 2 |
| 批量中部分失败 | 逐个打印失败原因 | 3 |

单文件失败不影响批量其余文件；`--json` 下所有结果（诊断、输出、校验、错误）汇总输出。

---

## 9. 性能与体积

| 场景 | 实测 |
|---|---|
| 4 页简历 outline | gs 约 1–2s，输出 1.5MB，校验渲染约 1s |
| 4 页简历 image@300dpi | 约 2–3s，输出 3.6MB |
| 6 页简历 outline | 输出 3.5MB（图片无损） |
| 数百份批量（check 模式） | 约 5 分钟（受 PDF 解析与字体解压影响） |

体积策略：默认图片无损；`--lossy-images` 可显著缩小照片较多的文件。

---

## 10. 安全与副作用

- `gs -dSAFER`：禁止文件系统写、禁止执行 PostScript 危险操作；
- 不执行 PDF 内 JavaScript（gs 默认不执行）；
- 输入文件只读，输出另存；默认存在同名文件时自动加 `-2`、`-3`，`-f` 才覆盖；
- 支持 `--password` 处理加密 PDF；
- 不联网、不上传任何文件。

---

## 11. 已知限制

1. outline/image 输出的**文字不可选中/搜索**（这是「无字体」的代价）；
2. 元数据、书签会丢失（打印无影响）；
3. `fix` 模式对 `ObjStm` 结构的 PDF 不可用（提示改用 outline/image）；
4. 极端异常的 PDF（损坏 xref、gs 不支持的滤镜）可能两边都失败；
   `fix` 模式对无传统 trailer（交叉引用流）的 PDF 已能兜底定位 Root，但仍不支持对象流（ObjStm）；
5. 颜色空间（专色/CMYK）与出血、装订等印刷级需求不在范围内；
6. 校验的「渲染一致」应理解为**视觉一致**，不是字节级等价；
7. 加密 PDF 的密码在 `--mode image` 下仍会以 argv 传给 `pdftocairo`（poppler 无参数文件机制），
   `--mode outline` 已改用临时参数文件；建议统一用环境变量 `PDF_NORMALIZE_PASSWORD` 传入。

---

## 12. 测试策略

| 层级 | 内容 | 命令 |
|---|---|---|
| 单元测试 | 合成 PDF：CFF→TrueType 槽位、反向错配、无错配、xref 偏移正确性 | `make unit` |
| 冒烟测试 | gs 现造样本，跑遍 check/outline/image/both/fix/json/no-verify，断言产物零字体 | `make smoke` |
| 真实语料回归 | 内部脱敏语料统计、缺陷文件逐一转换与校验 | 手动 / `--mode check -r` |

---

## 13. 后续可扩展方向

1. **批量并发**：多进程处理大目录（当前串行）；
2. **子集化重嵌（方案 E）**：用 fontTools 把 CFF 转 TrueType 子集，保留可选中文字；
3. **与打印链路联调**：输出前自动探测 `lpstat` 打印机类型，给出模式建议；
4. **GUI / Finder 快速操作**：拖拽即转；
5. **ATS 集成**：简历入库时自动规范化，避免再次出现「打印才发现乱码」；
6. **保留元数据/书签**：gs 参数或后处理注入。

---

## 附录 A：本次问题文件的实测数据

| 指标 | 数值 |
|---|---|
| 源文件 | 4 页，595.95×841.95pt，957.3KB，4 字体，8 处类型错配 |
| outline 输出 | 1.5MB，4 页，0 字体，渲染差 均值 1.60 / 差异像素 0.03% |
| image@300dpi 输出 | 3.6MB，4 页，0 字体，渲染差 均值 2.98 / 差异像素 0.17% |
| fix 输出 | 957.3KB，4 字体，错配 8→0，渲染差 0.00 |

## 附录 B：语料统计（内部脱敏语料，732 份）

| 分类 | 数量 |
|---|---|
| 有字体类型错配 | 15 |
| WPS 导出 | 14（其中 WPS 文字 12、WPS 演示 2） |
| pdf-lib 生成 | 1 |
| 平台自建模板 | 78（全部干净） |
| 经 iText 处理 | 583（其中缺陷 14） |
| 纯 Quartz 无平台处理 | 1 份对照组，同样缺陷 |
