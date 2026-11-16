# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.2] - 2026-11-16

### 修复（依据 WorkBuddy 第二轮审查）

- **高** `make test` 在交互终端会被密码提示挂起：冒烟测试隔离 stdin（`exec 0</dev/null`），
  并新增 `--no-input` / `PDF_NORMALIZE_NO_PROMPT=1` 显式关闭交互式提示。
- **中** 加密 PDF 改为「先用 Ghostscript 解密到 0600 临时文件」，后续 `pdfinfo`/`pdffonts`/
  `pdftoppm`/`pdftocairo` 全部免密处理；仅在 gs 缺失或解密失败时回退 poppler `-upw`，
  文档（DESIGN §11 / USAGE §8.4）如实说明残余风险。
- **中** 密码错误时区分提示「密码错误」而不是「未提供密码」。
- **低** `_rebuild_xref()` 的 Root 兜底改为 `_find_catalog_object()` + `root_num`，去掉占位
  `re.match(rb"", b"")` 写法。

### 测试

- 新增「--no-input 禁止交互」「加密 PDF 解密到临时文件并清理」单元测试；
- 冒烟新增「--no-input 下快速失败（不等待输入）」；
- 在伪终端（pty）下执行 `make test` 通过，不再挂起。

## [1.0.1] - 2026-11-16

### 修复（依据 WorkBuddy 代码审查，记录见 `code-review/`）

- **P0** `fix` 模式：字体声明识别与回写统一改用正则，支持 `/Subtype /CIDFontType2`、
  `/FontFile2  9 0 R`、换行等真实写法；无法安全替换时中止并提示，不再“报告修复成功但未改”
  或产生 `CIDFontType2 + FontFile3` 之类的新错配。
- **P1** 校验：ImageMagick 后备分支同时计算灰度均值与显著差异像素占比，不再恒为 0。
- **P1** 加密 PDF：密码支持环境变量 `PDF_NORMALIZE_PASSWORD`；gs 通过临时参数文件传递密码，
  避免出现在进程列表；pdfinfo / pdffonts / pdftoppm 全链路支持密码并给出明确提示。
- **P1** 批量：自定义 `--suffix` 的产物不再被当作输入重复处理。
- **P1** 退出码：改用结构化 `error_kind` 判定；`auto` 两级校验都失败时按文档返回 2。
- **P1** `--no-verify`：JSON 中显式标记 `skipped: true`、`ok/fonts: null`，不再伪造校验通过。
- **P2** 目录扫描支持 `.PDF` 等大写扩展名。
- **P2** 栅格化图片 PDF 改为流式写盘，降低大文档内存占用。
- 额外：无传统 trailer（交叉引用流）时从 `/Type/Catalog` 兜底定位 Root；`auto` 在轮廓化
  进程失败时也会按文档承诺降级为图片。

### 依赖

- Python 要求调整为 **3.10+**（3.8/3.9 已 EOL），与 CI 的 3.10/3.12 矩阵一致。

### 文档

- 更新 `docs/USAGE.md`、`DEPENDENCIES.md`、`README.md`；新增 `code-review/` 审查与修改记录。

## [1.0.0] - 2026-11-16

### 新增

- `pdf-normalize` 命令行工具：把「屏幕正常、打印乱码」的 PDF 规范化成零字体 PDF。
- `--mode outline`：用 Ghostscript `-dNoOutputFonts` 把文字转矢量轮廓（默认，推荐）。
- `--mode image`：用 pdftocairo 栅格化后重新打包 PDF（保底，100% 兼容）。
- `--mode fix`：修正 CFF / TrueType 字体槽位错配（保留可选中文字，兼容性有限）。
- `--mode auto`：轮廓化失败或校验不通过时自动降级为图片版。
- `--mode both`：同时产出 outline 与 image 两份。
- `--mode check`：只诊断不写文件，可配合 `-r` 批量筛查。
- 输出后自动校验：页数、字体数、逐页渲染比对（PIL / ImageMagick，缺失则降级）。
- 批量处理：多文件、目录递归、`--json` 机器可读输出。
- `--doctor` 环境自检（含 Ghostscript / poppler 版本下限检查）。
- `make` 默认显示完整使用说明，另有 `deps / test / unit / smoke / demo / install / uninstall / clean / docs` 目标。
- 单元测试（合成 PDF 覆盖双向字体错配与 xref 正确性）与冒烟测试（现场生成样本跑遍所有模式）。
- 文档：`README.md`、`docs/USAGE.md`、`docs/DESIGN.md`、`DEPENDENCIES.md`、`Brewfile`、`requirements.txt`。
