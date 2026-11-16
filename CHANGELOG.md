# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
