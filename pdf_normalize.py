#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pdf-normalize —— 把「一打印就乱码」的 PDF 规范成任何打印机都能出的文件。

背景（为什么不直接修字体）：
  很多中文 PDF（WPS / Quartz / 各类导出工具生成）会把 OpenType-CFF 字体
  （PingFang、思源黑体等）塞进 TrueType 的字体槽位，声明成 CIDFontType2 +
  FontFile2。屏幕上的阅读器都容错，看着完全正常；但打印机 RIP、尤其是
  「远程桌面 / 云桌面打印重定向」这类链路的渲染器会严格按声明解析，于是
  打成乱码。仅把声明改对（--mode fix）能救一部分宽松渲染器，但救不了
  解析不了 CFF 字体程序的严格 RIP。

  所以本工具的主力模式是让 PDF 里「一个字体都不剩」：
    --mode outline  文字转矢量轮廓（Ghostscript -dNoOutputFonts），零字体、
                    任意 DPI 清晰、体积小；
    --mode image    整页栅格化（pdftocairo + JPEG），零字体、绝对兼容；
    --mode fix      只修字体声明，保留可选中文字（兼容性有限，作辅助）。

用法：
    pdf-normalize 简历.pdf                       # 默认 outline，输出 简历-print.pdf
    pdf-normalize --mode image --dpi 300 简历.pdf
    pdf-normalize --mode both 简历.pdf 合同.pdf   # 批量
    pdf-normalize --mode check 简历.pdf           # 只诊断，不写文件
    pdf-normalize -r 某个目录/                     # 递归处理目录下所有 PDF
    pdf-normalize --doctor                        # 检查依赖环境

退出码：0 全部成功；1 用法/环境错误；2 校验未通过；3 部分文件失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

VERSION = "1.0.1"
DEFAULT_DPI = 300
DEFAULT_SUFFIX = "-print"
PASSWORD_ENV = "PDF_NORMALIZE_PASSWORD"
VERIFY_DPI = 110

# 校验阈值：blur 后灰度差的均值 / 差异像素比例（>40/255）
VERIFY_LIMITS = {
    "outline": (4.0, 1.5),
    "image": (20.0, 25.0),
    "fix": (1.0, 0.1),
}

EXIT_OK, EXIT_USAGE, EXIT_VERIFY, EXIT_PARTIAL = 0, 1, 2, 3

# 版本下限：低于这些版本的核心参数不可用（见 DEPENDENCIES.md）
MIN_GS = (9, 55)        # -dNoOutputFonts / -dPreserveAnnots
MIN_POPPLER = (0, 60)   # pdftocairo -jpegopt


# --------------------------------------------------------------------------
# 基础工具
# --------------------------------------------------------------------------
def sh(cmd, timeout=900):
    """执行命令，返回 (returncode, stdout, stderr)，全部解码为文本。"""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        return 127, "", "命令不存在: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "命令超时: %s" % " ".join(map(str, cmd))
    return (
        p.returncode,
        p.stdout.decode("utf-8", "replace"),
        p.stderr.decode("utf-8", "replace"),
    )


def have(cmd):
    return shutil.which(cmd) is not None


def tool_version(cmd, flag="--version"):
    if not have(cmd):
        return None
    rc, out, err = sh([cmd, flag])
    text = (out + err).strip().splitlines()
    return text[0].strip() if text else "?"


def parse_version(text):
    """从版本字符串里取 (major, minor[, patch])，取不到返回 None。"""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
    if not m:
        return None
    return tuple(int(g) for g in m.groups() if g is not None)


def version_ok(current, minimum):
    if current is None:
        return None
    return tuple(current[:len(minimum)]) >= tuple(minimum)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


# --------------------------------------------------------------------------
# PDF 信息读取
# --------------------------------------------------------------------------
def pdfinfo(path, password=None):
    """读取 pdfinfo 的关键字段（字符串）。加密 PDF 用 password 解锁。"""
    cmd = ["pdfinfo"]
    if password:
        cmd += ["-upw", password]
    cmd.append(str(path))
    rc, out, err = sh(cmd)
    if rc != 0:
        msg = err.strip() or out.strip()
        if "password" in msg.lower():
            msg += "（该 PDF 已加密：用 --password 或环境变量 %s 提供密码）" % PASSWORD_ENV
        raise RuntimeError("pdfinfo 失败: %s" % msg)
    info = {}
    for line in out.splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def page_size_pt(info):
    """从 pdfinfo 输出解析页面尺寸（pt）。"""
    m = re.search(r"([\d.]+)\s+x\s+([\d.]+)\s+pts", info.get("Page size", ""))
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def pdffonts_scan(path, password=None):
    """返回 (字体行列表, 字体类型错配条数, 原始输出)。加密 PDF 用 password 解锁。"""
    cmd = ["pdffonts"]
    if password:
        cmd += ["-upw", password]
    cmd.append(str(path))
    rc, out, err = sh(cmd)
    text = out + "\n" + err
    mismatch = text.count("Mismatch between font type and embedded font file")
    rows = []
    for line in out.splitlines():
        s = line.strip()
        if not s or s.startswith("name ") or set(s) <= set("- "):
            continue
        rows.append(line)
    return rows, mismatch, text


def diagnose(path, password=None):
    info = pdfinfo(path, password)
    rows, mismatch, _ = pdffonts_scan(path, password)
    fonts = len(rows)
    has_cff = any("Type 0C" in r for r in rows)
    notes = []
    if mismatch:
        notes.append("检测到 %d 处「字体类型与嵌入程序不一致」——严格 RIP 打印必乱码" % mismatch)
    if fonts and not mismatch:
        notes.append("含 %d 个嵌入字体；若打印链路（尤其远程/云桌面重定向）严格，仍建议转无字体版" % fonts)
    if fonts == 0:
        notes.append("已是无字体 PDF，可直接规范化（统一为 PDF 1.4 / 页面结构）")
    return {
        "path": str(path),
        "pages": int(info.get("Pages", 0) or 0),
        "page_size": page_size_pt(info),
        "size": os.path.getsize(path),
        "fonts": fonts,
        "has_cff": has_cff,
        "mismatch": mismatch,
        "notes": notes,
        "info": {k: info.get(k, "") for k in ("Producer", "Creator", "CreationDate", "ModDate")},
    }


# --------------------------------------------------------------------------
# --mode fix：字体声明修复（保留文字，作辅助手段）
# --------------------------------------------------------------------------
OBJ_RE = re.compile(rb"(?<!\d)(\d+)\s+0\s+obj\b")
STREAM_RE = re.compile(rb"(?<![A-Za-z])stream\r?\n")
FONT_SUBTYPES = (b"CIDFontType0", b"CIDFontType2")
TRUE_TYPE_MAGIC = (b"\x00\x01\x00\x00", b"true", b"ttcf")


def _find_objects(data):
    """扫描顶层对象：num -> (obj_start, dict_start, dict_end)；dict 用配对 << >> 定位。"""
    objs = {}
    for m in OBJ_RE.finditer(data):
        num = int(m.group(1))
        start = m.end()
        i = data.find(b"<<", start)
        dict_start = dict_end = None
        if i != -1 and i - start <= 24:
            depth, j = 0, i
            while j < len(data) - 1:
                if data[j:j + 2] == b"<<":
                    depth += 1
                    j += 2
                elif data[j:j + 2] == b">>":
                    depth -= 1
                    j += 2
                    if depth == 0:
                        dict_start, dict_end = i, j
                        break
                else:
                    j += 1
        objs[num] = (m.start(), dict_start, dict_end)
    return objs


def _stream_program_magic(data, dict_end, limit=16):
    """取对象流解压后的开头几个字节，用于判断字体程序真实格式。"""
    if dict_end is None:
        return None
    m = STREAM_RE.search(data, dict_end, dict_end + 32)
    if not m:
        return None
    start = m.end()
    end = data.find(b"endstream", start)
    if end == -1:
        return None
    raw = data[start:end]
    try:
        return zlib.decompressobj().decompress(raw, limit)
    except zlib.error:
        return raw[:limit]


def _sub_once(text, pattern, repl):
    """只替换一次；未命中返回 (None, False)，避免"报告成功但没改"的静默失败。"""
    new, n = re.subn(pattern, repl, text, count=1)
    return (new if n == 1 else None), n == 1


def _with_open_type_subtype(fdict):
    """FontFile3 流字典补 /Subtype/OpenType（CFF 程序必须如此）。"""
    if b"/Subtype/OpenType" in fdict:
        return None
    if b"/Subtype" in fdict:
        new, ok = _sub_once(fdict, rb"/Subtype\s*/(?:Type1C|CIDFontType0C)", b"/Subtype/OpenType")
        return new if ok else None
    return fdict[:-2] + b"/Subtype/OpenType>>"


def repair_font_declarations(src, dst):
    """修正「CFF 字体被声明成 TrueType 槽位」及反向错配，重建 xref。

    返回 (修复条数, 说明列表)。无法安全处理时抛 RuntimeError。
    """
    data = Path(src).read_bytes()
    if b"/ObjStm" in data:
        raise RuntimeError("字体对象位于压缩对象流(ObjStm)中，无法原位修复声明；请改用 --mode outline 或 --mode image")
    objs = _find_objects(data)
    if not objs:
        raise RuntimeError("未能解析出任何 PDF 对象")

    # 字体描述符：objnum -> (dict_start, dict_end, dict_bytes)
    descriptors = {}
    for num, (_, ds, de) in objs.items():
        if ds is None:
            continue
        d = data[ds:de]
        if re.search(rb"/FontFile[23]\s+\d+\s+0\s+R", d) and b"/FontName" in d:
            descriptors[num] = (ds, de, d)

    edits = []          # (start, end, replacement)
    explanations = []
    skipped = []

    for num, (_, ds, de) in objs.items():
        if ds is None:
            continue
        d = data[ds:de]
        m = re.search(rb"/Subtype\s*/(CIDFontType[02])", d)
        if not m:
            continue
        fd = re.search(rb"/FontDescriptor\s+(\d+)\s+0\s+R", d)
        if not fd:
            continue
        desc_num = int(fd.group(1))
        if desc_num not in descriptors:
            continue
        d_start, d_end, d_text = descriptors[desc_num]
        ff = re.search(rb"/FontFile([23])\s+(\d+)\s+0\s+R", d_text)
        if not ff:
            continue
        slot, fontfile_num = ff.group(1), int(ff.group(2))
        if fontfile_num not in objs:
            continue
        magic = _stream_program_magic(data, objs[fontfile_num][2])
        if not magic:
            continue
        is_cff = magic[:4] == b"OTTO"
        is_tt = magic[:4] in TRUE_TYPE_MAGIC
        declared = m.group(1)

        # 情况 A：声明 TrueType 槽位，实际是 CFF 程序
        if declared == b"CIDFontType2" and slot == b"2" and is_cff:
            new_d, ok1 = _sub_once(d, rb"/Subtype\s*/CIDFontType2", b"/Subtype/CIDFontType0")
            new_desc, ok2 = _sub_once(
                d_text, rb"/FontFile2\s+%d\s+0\s+R" % fontfile_num,
                b"/FontFile3 %d 0 R" % fontfile_num)
            if not (ok1 and ok2):
                skipped.append(num)
                continue
            edits.append((ds, de, new_d))
            edits.append((d_start, d_end, new_desc))
            fdict_start, fdict_end = objs[fontfile_num][1], objs[fontfile_num][2]
            new_fdict = _with_open_type_subtype(data[fdict_start:fdict_end])
            if new_fdict is not None:
                edits.append((fdict_start, fdict_end, new_fdict))
            explanations.append("obj %d: CIDFontType2/FontFile2(OTTO) -> CIDFontType0/FontFile3/OpenType" % num)

        # 情况 B：声明 CFF 槽位，实际是 TrueType 程序
        elif declared == b"CIDFontType0" and slot == b"3" and is_tt:
            new_d, ok1 = _sub_once(d, rb"/Subtype\s*/CIDFontType0", b"/Subtype/CIDFontType2")
            new_desc, ok2 = _sub_once(
                d_text, rb"/FontFile3\s+%d\s+0\s+R" % fontfile_num,
                b"/FontFile2 %d 0 R" % fontfile_num)
            if not (ok1 and ok2):
                skipped.append(num)
                continue
            edits.append((ds, de, new_d))
            edits.append((d_start, d_end, new_desc))
            explanations.append("obj %d: CIDFontType0/FontFile3(TrueType) -> CIDFontType2/FontFile2" % num)

    if skipped:
        raise RuntimeError(
            "字体声明写法无法安全替换（obj %s），已中止以免写出半修复文件；"
            "请改用 --mode outline 或 --mode image" % ", ".join(map(str, skipped)))
    if not edits:
        raise RuntimeError("未发现需要修复的字体声明错配")

    # 从后往前应用编辑，避免偏移失效
    out = bytearray(data)
    for start, end, repl in sorted(edits, key=lambda e: e[0], reverse=True):
        assert start is not None and end is not None
        out[start:end] = repl

    new = bytes(out)
    body_end = max(_object_end(new, num) for num in objs)
    body = new[:body_end]
    Path(dst).write_bytes(_rebuild_xref(data, body, objs))
    return len(explanations), explanations


def _object_end(data, num):
    m = re.search(rb"(?<!\d)%d\s+0\s+obj\b" % num, data)
    if not m:
        return len(data)
    end = data.find(b"endobj", m.end())
    return end + len(b"endobj") if end != -1 else len(data)


def _rebuild_xref(orig, body, objs):
    """用修复后的对象偏移重建经典 xref 表（保留 Root/Info/ID）。"""
    trailer = b""
    for m in re.finditer(rb"trailer\s*<<(.*?)>>", orig, re.S):
        trailer = m.group(1)
    root = re.search(rb"/Root\s+(\d+)\s+0\s+R", trailer)
    info = re.search(rb"/Info\s+(\d+)\s+0\s+R", trailer)
    ids = re.search(rb"/ID\s*\[(.*?)\]", trailer, re.S)

    # 有些 PDF 使用交叉引用流、没有传统 trailer：从对象里找 /Type/Catalog 兜底
    if not root:
        for num, (_, ds, de) in _find_objects(body).items():
            if ds is not None and b"/Type/Catalog" in body[ds:de]:
                root = re.match(rb"", b"")
                root_num = num
                break
        else:
            raise RuntimeError("无法定位文档 /Root（可能使用特殊结构），已跳过原位修复；"
                               "请改用 --mode outline 或 --mode image")
    else:
        root_num = int(root.group(1))

    offsets = {}
    for m in re.finditer(rb"(?m)^(\d+)\s+0\s+obj\b", body):
        offsets.setdefault(int(m.group(1)), m.start())

    size = max(max(objs) + 1, max(offsets) + 1)
    buf = bytearray(body)
    xref_pos = len(buf)
    buf += b"xref\n0 %d\n" % size
    buf += b"0000000000 65535 f \n"
    for i in range(1, size):
        off = offsets.get(i)
        buf += (b"%010d 00000 n \n" % off) if off is not None else b"0000000000 00000 f \n"

    parts = [b"<</Size %d/Root %d 0 R" % (size, root_num)]
    if info:
        parts.append(b"/Info " + info.group(0).split(b"/Info ")[1])
    if ids:
        parts.append(b"/ID [" + ids.group(1) + b"]")
    parts.append(b">>")
    buf += b"trailer\n" + b"".join(parts) + b"\nstartxref\n%d\n%%%%EOF\n" % xref_pos
    return bytes(buf)


# --------------------------------------------------------------------------
# 密码处理：优先环境变量，gs 用参数文件传递，避免出现在进程列表
# --------------------------------------------------------------------------
def _resolve_password(explicit=None):
    return explicit or os.environ.get(PASSWORD_ENV) or None


def _gs_password_args(password):
    """把密码写进临时参数文件交给 gs，避免在 `ps aux` 里暴露。"""
    if not password:
        return [], None
    try:
        fd, path = tempfile.mkstemp(prefix="pdfnorm-pw-", suffix=".args")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("-sPDFPassword=" + password + "\n")
        os.chmod(path, 0o600)
        return ["@" + path], path
    except Exception:
        return ["-sPDFPassword=" + password], None


def _prompt_password_on_error(err_text, password):
    """仅当错误提示需要密码且终端可交互时，才提示输入一次。"""
    if password or not sys.stdin.isatty():
        return None
    if "password" not in (err_text or "").lower():
        return None
    try:
        import getpass
        return getpass.getpass("该 PDF 需要密码，请输入（不回显）：") or None
    except (EOFError, KeyboardInterrupt):
        return None


# --------------------------------------------------------------------------
# --mode outline：文字转矢量轮廓（Ghostscript）
# --------------------------------------------------------------------------
def build_outline(src, dst, password=None, lossy=False):
    args = [
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        "-dNoOutputFonts",                 # 文字 -> 矢量轮廓
        "-dAutoRotatePages=/None",
        "-dDownsampleColorImages=false",
        "-dDownsampleGrayImages=false",
        "-dDownsampleMonoImages=false",
        "-dPreserveAnnots=true",
    ]
    if not lossy:
        # 图片默认无损转存，避免二次有损；--lossy-images 可放开（照片多的文件更小）
        args += [
            "-dAutoFilterColorImages=false",
            "-dColorImageFilter=/FlateEncode",
            "-dAutoFilterGrayImages=false",
            "-dGrayImageFilter=/FlateEncode",
        ]
    args += [
        "-sOutputFile=" + str(dst),
    ]
    pw_args, pw_file = _gs_password_args(password)
    args += pw_args
    args.append(str(src))
    try:
        rc, out, err = sh(args)
        if rc != 0 or not Path(dst).exists() or Path(dst).stat().st_size == 0:
            retry = _prompt_password_on_error(err, password)
            if retry:
                return build_outline(src, dst, retry, lossy)
            raise RuntimeError("Ghostscript 轮廓化失败: %s" % (err.strip() or out.strip())[-600:])
    finally:
        if pw_file:
            try:
                os.unlink(pw_file)
            except OSError:
                pass
    return dst


# --------------------------------------------------------------------------
# --mode image：整页栅格化（pdftocairo + JPEG，无需字体）
# --------------------------------------------------------------------------
def jpeg_size(data):
    """从 JPEG 字节流解析宽高。"""
    i = 2
    n = len(data)
    while i < n - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = (data[i + 2] << 8) + data[i + 3]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h = (data[i + 5] << 8) + data[i + 6]
            w = (data[i + 7] << 8) + data[i + 8]
            return w, h
        i += 2 + seg_len
    raise RuntimeError("无法解析 JPEG 尺寸")


def build_raster(src, dst, dpi=DEFAULT_DPI, quality=92, password=None):
    with tempfile.TemporaryDirectory(prefix="pdfnorm-") as td:
        cmd = ["pdftocairo", "-jpeg", "-r", str(dpi),
               "-jpegopt", "quality=%d" % quality]
        if password:
            cmd += ["-upw", password]
        cmd += [str(src), os.path.join(td, "page")]
        rc, out, err = sh(cmd)
        if rc != 0:
            retry = _prompt_password_on_error(err, password)
            if retry:
                return build_raster(src, dst, dpi, quality, retry)
            raise RuntimeError("pdftocairo 栅格化失败: %s" % (err.strip() or out.strip())[-600:])
        jpgs = sorted(Path(td).glob("page-*.jpg"),
                      key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1)))
        if not jpgs:
            raise RuntimeError("pdftocairo 没有产生任何页面图片")
        built = _build_image_pdf(jpgs, dst, dpi, page_size=page_size_pt(pdfinfo(src, password)))
    return built


def _jpeg_dimensions(path):
    """只读文件头附近解析 JPEG 宽高；极端情况才整体读入。"""
    with open(path, "rb") as fh:
        head = fh.read(65536)
    try:
        return jpeg_size(head)
    except RuntimeError:
        return jpeg_size(Path(path).read_bytes())


def _build_image_pdf(jpgs, dst, dpi, page_size=None):
    """把每页 JPEG 流式打包成 PDF（无字体，DCTDecode）。

    逐页写盘，不把全部页面的 JPEG 同时留在内存；页面尺寸优先沿用原文档 pt 尺寸。
    """
    pages = []
    for p in jpgs:
        w, h = _jpeg_dimensions(p)
        pages.append({"path": str(p), "pixels": (w, h), "size": os.path.getsize(p)})

    if page_size:
        size_w, size_h = page_size
        uniform = all(
            abs(w * 72.0 / dpi - size_w) < 3 and abs(h * 72.0 / dpi - size_h) < 3
            for w, h in (pg["pixels"] for pg in pages))
        if not uniform:
            page_size = None

    n = len(pages)
    img_ids = [3 + i for i in range(n)]
    cont_ids = [3 + n + i for i in range(n)]
    page_ids = [3 + 2 * n + i for i in range(n)]
    offsets = {}

    out = open(dst, "wb")
    try:
        out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")

        def write_obj(num, head, stream_path=None):
            offsets[num] = out.tell()
            out.write(b"%d 0 obj\n" % num)
            out.write(head)
            if stream_path is not None:
                out.write(b"stream\n")
                with open(stream_path, "rb") as fh:
                    shutil.copyfileobj(fh, out, 1 << 20)
                out.write(b"\nendstream")
            out.write(b"\nendobj\n")

        write_obj(1, b"<</Type/Catalog/Pages 2 0 R>>")
        kids = b" ".join(b"%d 0 R" % p for p in page_ids)
        write_obj(2, b"<</Type/Pages/Count %d/Kids[%s]>>" % (n, kids))

        for i, pg in enumerate(pages):
            w, h = pg["pixels"]
            if page_size:
                pw, ph = page_size
            else:
                pw, ph = w * 72.0 / dpi, h * 72.0 / dpi
            head = (b"<</Type/XObject/Subtype/Image/Width %d/Height %d"
                    b"/ColorSpace/DeviceRGB/BitsPerComponent 8"
                    b"/Filter/DCTDecode/Length %d>>" % (w, h, pg["size"]))
            write_obj(img_ids[i], head, pg["path"])
            content = b"q %.4f 0 0 %.4f 0 0 cm /Im0 Do Q" % (pw, ph)
            write_obj(cont_ids[i], b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream")
            write_obj(page_ids[i],
                      b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 %.4f %.4f]"
                      b"/Resources<</XObject<</Im0 %d 0 R>>/ProcSet[/PDF/ImageC]>>"
                      b"/Contents %d 0 R>>" % (pw, ph, img_ids[i], cont_ids[i]))

        size = max(offsets) + 1
        xref_pos = out.tell()
        out.write(b"xref\n0 %d\n" % size + b"0000000000 65535 f \n")
        for i in range(1, size):
            out.write((b"%010d 00000 n \n" % offsets[i]) if i in offsets else b"0000000000 00000 f \n")
        out.write(b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_pos))
    finally:
        out.close()
    return dst


# --------------------------------------------------------------------------
# 校验：页数 + 逐页渲染比对
# --------------------------------------------------------------------------
def _render(pdf, dpi, outdir, password=None):
    cmd = ["pdftoppm", "-r", str(dpi), "-png"]
    if password:
        cmd += ["-upw", password]
    cmd += [str(pdf), os.path.join(outdir, "p")]
    rc, out, err = sh(cmd)
    if rc != 0:
        raise RuntimeError("pdftoppm 渲染失败: %s" % (err.strip() or out.strip())[-400:])
    return sorted(Path(outdir).glob("p-*.png"),
                  key=lambda p: int(re.search(r"(\d+)$", p.stem).group(1)))


def _magick_compare(imgs_a, imgs_b):
    """ImageMagick 后备：difference + blur + threshold，同时给出均值与差异像素占比。"""
    if not have("magick") or len(imgs_a) != len(imgs_b):
        return None
    means, pcts = [], []
    num_re = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")
    for a, b in zip(imgs_a, imgs_b):
        base = [str(a), str(b), "-compose", "difference", "-composite",
                "-colorspace", "Gray", "-blur", "0x1"]
        rc, out, err = sh(["magick"] + base + ["-format", "%[fx:mean*255]", "info:"])
        mean_txt = (out + err).strip()
        if rc != 0 or not num_re.fullmatch(mean_txt):
            return None
        rc, out, err = sh(["magick"] + base + ["-threshold", "15%",
                                               "-format", "%[fx:mean*100]", "info:"])
        pct_txt = (out + err).strip()
        if rc != 0 or not num_re.fullmatch(pct_txt):
            return None
        means.append(float(mean_txt))
        pcts.append(float(pct_txt))
    return sum(means) / len(means), sum(pcts) / len(pcts)


def _compare(imgs_a, imgs_b):
    """返回 (平均灰度差, 显著差异像素占比)。优先 PIL；否则用 ImageMagick。"""
    if len(imgs_a) != len(imgs_b):
        return None
    try:
        from PIL import Image, ImageChops, ImageFilter
        import numpy as np
    except Exception:
        return _magick_compare(imgs_a, imgs_b)
    means, pcts = [], []
    for a, b in zip(imgs_a, imgs_b):
        ia = Image.open(a).convert("L")
        ib = Image.open(b).convert("L")
        if ia.size != ib.size:
            ib = ib.resize(ia.size)
        ia = ia.filter(ImageFilter.GaussianBlur(1.2))
        ib = ib.filter(ImageFilter.GaussianBlur(1.2))
        d = ImageChops.difference(ia, ib)
        arr = np.asarray(d, dtype=np.uint8)
        means.append(float(arr.mean()))
        pcts.append(float((arr > 40).mean() * 100))
    return sum(means) / len(means), sum(pcts) / len(pcts)


def skipped_verify():
    """--no-verify 时的校验结果：显式标记 skipped，不伪造 ok=true。"""
    return {"skipped": True, "ok": None, "pages_ok": None, "fonts": None,
            "reason": "跳过校验（--no-verify）"}


def _verify_passed(v):
    if not isinstance(v, dict):
        return False
    return v.get("skipped") is True or bool(v.get("ok"))


def _verify_dpi(pages):
    if pages <= 10:
        return VERIFY_DPI
    if pages <= 30:
        return 80
    return 72


def verify_output(src, out, mode, expect_fonts=0, src_password=None):
    """校验输出：页数一致、字体数符合预期、渲染内容与原件一致。"""
    res = {"pages_ok": False, "fonts": None, "verify": None, "ok": False, "reason": ""}
    try:
        src_info, out_info = pdfinfo(src, src_password), pdfinfo(out)
        src_pages = int(src_info.get("Pages", 0) or 0)
        out_pages = int(out_info.get("Pages", 0) or 0)
        res["pages_ok"] = src_pages == out_pages and out_pages > 0
        if not res["pages_ok"]:
            res["reason"] = "页数不一致（%s -> %s）" % (src_pages, out_pages)
            return res
        rows, _, _ = pdffonts_scan(out)
        res["fonts"] = len(rows)
        if expect_fonts is not None and res["fonts"] != expect_fonts:
            res["reason"] = "输出字体数 %d，预期 %d，无法保证打印兼容" % (res["fonts"], expect_fonts)
            return res
        if not all(have(t) for t in ("pdftoppm",)):
            res["reason"] = "缺少 pdftoppm，跳过渲染比对"
            res["ok"] = True
            return res
        with tempfile.TemporaryDirectory(prefix="pdfnorm-v-") as ta, \
             tempfile.TemporaryDirectory(prefix="pdfnorm-v-") as tb:
            dpi = _verify_dpi(out_pages)
            ia = _render(src, dpi, ta, src_password)
            ib = _render(out, dpi, tb)
            cmp = _compare(ia, ib)
        if cmp is None:
            res["reason"] = "缺少 PIL/ImageMagick，跳过渲染比对"
            res["ok"] = True
            return res
        mean, pct = cmp
        lim_mean, lim_pct = VERIFY_LIMITS.get(mode, (4.0, 1.5))
        res["verify"] = {"mean": round(mean, 2), "pct": round(pct, 3),
                         "limit_mean": lim_mean, "limit_pct": lim_pct}
        res["ok"] = mean <= lim_mean and pct <= lim_pct
        if not res["ok"]:
            res["reason"] = "渲染内容差异过大（均值 %.2f/%.2f，差异像素 %.2f%%/%.2f%%）" % (
                mean, lim_mean, pct, lim_pct)
        return res
    except Exception as e:  # 校验失败不致命，但要在结果里体现
        res["reason"] = "校验异常: %s" % e
        return res


# --------------------------------------------------------------------------
# 输出路径
# --------------------------------------------------------------------------
def output_path(src, outdir, suffix, mode, dpi, force):
    src = Path(src)
    stem = src.stem
    if mode == "outline":
        name = "%s%s.pdf" % (stem, suffix)
    elif mode == "image":
        name = "%s%s-%ddpi.pdf" % (stem, suffix, dpi)
    else:
        name = "%s%s-fix.pdf" % (stem, suffix)
    base = Path(outdir) if outdir else src.parent
    base.mkdir(parents=True, exist_ok=True)
    dst = base / name
    if dst.exists() and not force:
        i = 2
        while True:
            cand = base / ("%s-%d%s" % (dst.stem, i, dst.suffix))
            if not cand.exists():
                dst = cand
                break
            i += 1
    return dst


# --------------------------------------------------------------------------
# 单文件处理
# --------------------------------------------------------------------------
def process_one(path, opts):
    path = Path(path)
    result = {"input": str(path), "ok": False, "mode": opts.mode, "outputs": [],
              "diagnosis": None, "error": "", "error_kind": "", "verify": None}
    try:
        try:
            diag = diagnose(path, opts.password)
        except RuntimeError as e:
            if "password" in str(e).lower() and not opts.password and sys.stdin.isatty():
                retry = _prompt_password_on_error(str(e), None)
                if retry:
                    opts.password = retry
                    diag = diagnose(path, retry)
                else:
                    raise
            else:
                raise
        result["diagnosis"] = diag
        if opts.mode == "check":
            result["ok"] = True
            return result

        skip = skipped_verify() if opts.no_verify else None

        def verified(pdf, mode, expect_fonts):
            if skip is not None:
                return skip
            return verify_output(path, pdf, mode, expect_fonts=expect_fonts,
                                 src_password=opts.password)

        if opts.mode in ("outline", "auto"):
            dst = output_path(path, opts.out, opts.suffix, "outline", opts.dpi, opts.force)
            outline_problem = None
            ver = None
            try:
                build_outline(path, dst, opts.password, opts.lossy_images)
                ver = verified(dst, "outline", 0)
            except RuntimeError as e:
                if opts.mode == "outline":
                    raise
                outline_problem = str(e)
            if ver is not None and _verify_passed(ver):
                result.update(ok=True, mode="outline", outputs=[str(dst)], verify=ver)
                return result
            if opts.mode == "outline":
                if dst.exists():
                    result["outputs"].append(str(dst))
                result["verify"] = ver
                result["error"] = "校验未通过：%s" % (ver.get("reason", "") if ver else outline_problem)
                result["error_kind"] = "verify"
                return result

            # auto：轮廓化抛错或校验不过 -> 降级栅格化
            if dst.exists():
                dst.unlink(missing_ok=True)
            img = output_path(path, opts.out, opts.suffix, "image", opts.dpi, opts.force)
            build_raster(path, img, opts.dpi, opts.jpeg_quality, opts.password)
            ver2 = verified(img, "image", 0)
            result.update(mode="image", outputs=[str(img)], verify=ver2)
            result["ok"] = _verify_passed(ver2)
            if not result["ok"]:
                reasons = []
                if outline_problem:
                    reasons.append("轮廓化失败: %s" % outline_problem)
                elif ver is not None:
                    reasons.append("轮廓化校验未通过: %s" % ver.get("reason", ""))
                reasons.append("栅格化校验未通过: %s" % ver2.get("reason", ""))
                result["error"] = "自动模式：轮廓化与栅格化均未通过（%s）" % "；".join(reasons)
                result["error_kind"] = "verify"
            return result

        if opts.mode == "image":
            dst = output_path(path, opts.out, opts.suffix, "image", opts.dpi, opts.force)
            build_raster(path, dst, opts.dpi, opts.jpeg_quality, opts.password)
            ver = verified(dst, "image", 0)
            result.update(outputs=[str(dst)], verify=ver, ok=_verify_passed(ver))
            if not result["ok"]:
                result["error"] = "校验未通过：%s" % ver.get("reason", "")
                result["error_kind"] = "verify"
            return result

        if opts.mode == "fix":
            dst = output_path(path, opts.out, opts.suffix, "fix", opts.dpi, opts.force)
            try:
                n, explain = repair_font_declarations(path, dst)
            except RuntimeError as e:
                if "未发现需要修复的字体声明错配" in str(e):
                    result["ok"] = True
                    result["note"] = "无需修复：未发现字体类型错配"
                    result["diagnosis"]["notes"].append(result["note"])
                    return result
                raise
            after_rows, after_mismatch, _ = pdffonts_scan(dst)
            result["outputs"].append(str(dst))
            result["fix"] = {"fixed": n, "explanations": explain,
                             "mismatch_before": diag["mismatch"], "mismatch_after": after_mismatch,
                             "fonts_after": len(after_rows)}
            ver = verified(dst, "fix", None)
            result["verify"] = ver
            result["ok"] = after_mismatch == 0 and _verify_passed(ver)
            if after_mismatch:
                result["error"] = "仍存在 %d 处字体错配" % after_mismatch
                result["error_kind"] = "verify"
            elif not _verify_passed(ver):
                result["error"] = "校验未通过：%s" % ver.get("reason", "")
                result["error_kind"] = "verify"
            return result

        if opts.mode == "both":
            dst1 = output_path(path, opts.out, opts.suffix, "outline", opts.dpi, opts.force)
            try:
                build_outline(path, dst1, opts.password, opts.lossy_images)
                ver1 = verified(dst1, "outline", 0)
            except Exception:
                if dst1.exists():
                    dst1.unlink(missing_ok=True)
                raise
            dst2 = output_path(path, opts.out, opts.suffix, "image", opts.dpi, opts.force)
            try:
                build_raster(path, dst2, opts.dpi, opts.jpeg_quality, opts.password)
                ver2 = verified(dst2, "image", 0)
            except Exception:
                if dst2.exists():
                    dst2.unlink(missing_ok=True)
                raise
            result["outputs"] = [str(dst1), str(dst2)]
            result["verify"] = {"outline": ver1, "image": ver2}
            result["ok"] = _verify_passed(ver1) and _verify_passed(ver2)
            if not result["ok"]:
                result["error"] = "部分输出未通过校验"
                result["error_kind"] = "verify"
            return result

        result["error"] = "未知模式: %s" % opts.mode
        result["error_kind"] = "usage"
    except RuntimeError as e:
        result["error"] = str(e)
        result["error_kind"] = "usage"
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
        result["error_kind"] = "usage"
    return result


# --------------------------------------------------------------------------
# 文件收集 / 报告
# --------------------------------------------------------------------------
def _generated_patterns(suffix):
    """本工具可能生成的文件名模式（扫描目录时跳过，避免把产物当输入）。"""
    patterns = []
    for sfx in {suffix, DEFAULT_SUFFIX}:
        if not sfx:
            continue
        patterns.append(re.compile(r"%s(?:-fix|-\d+dpi)?(?:-\d+)?$" % re.escape(sfx)))
    return patterns


def collect_inputs(paths, recursive, suffix=DEFAULT_SUFFIX):
    files, errors = [], []
    for p in paths:
        p = Path(p).expanduser()
        if not p.exists():
            errors.append("文件不存在: %s" % p)
        elif p.is_dir():
            candidates = p.glob("**/*") if recursive else p.glob("*")
            found = sorted(x for x in candidates if x.is_file() and x.suffix.lower() == ".pdf")
            if not found:
                errors.append("目录下没有 PDF: %s" % p)
            files.extend(found)
        else:
            files.append(p)
    generated = _generated_patterns(suffix)
    seen, out = set(), []
    for f in files:
        rp = f.resolve()
        if rp in seen:
            continue
        if f.suffix.lower() != ".pdf":
            errors.append("跳过非 PDF 文件: %s" % f)
            continue
        if any(pat.search(f.stem) for pat in generated):
            continue
        seen.add(rp)
        out.append(f)
    return out, errors


def fmt_diag(d):
    bits = ["%d 页" % d["pages"]]
    if d["page_size"]:
        bits.append("%.0fx%.0fpt" % d["page_size"])
    bits.append("%s" % human_size(d["size"]))
    bits.append("%d 字体" % d["fonts"])
    if d["mismatch"]:
        bits.append("⚠ %d 处类型错配" % d["mismatch"])
    if d["has_cff"]:
        bits.append("含 CFF 字体")
    return "，".join(bits)


def _print_verify(label, v):
    prefix = (" " + label) if label else ""
    if v.get("skipped"):
        print("  校验%s: 跳过（--no-verify）" % prefix)
        return
    if v.get("verify"):
        vv = v["verify"]
        print("  校验%s: 页数%s，字体 %s 个，渲染差 均值 %.2f / 差异像素 %.2f%%  %s"
              % (prefix,
                 "一致" if v.get("pages_ok") else "不一致", v.get("fonts"),
                 vv["mean"], vv["pct"], "✓" if v["ok"] else "✗"))
    elif v.get("reason"):
        print("  校验%s: %s" % (prefix, v["reason"]))


def print_result(r, opts):
    path = Path(r["input"]).name
    if r.get("diagnosis"):
        print("  诊断: %s" % fmt_diag(r["diagnosis"]))
        for n in r["diagnosis"]["notes"]:
            print("        · %s" % n)
    if r.get("fix"):
        f = r["fix"]
        print("  修复: %d 处声明；错配 %d -> %d；字体数 %d"
              % (f["fixed"], f["mismatch_before"], f["mismatch_after"], f["fonts_after"]))
    for o in r.get("outputs", []):
        print("  输出: %s  (%s)" % (o, human_size(os.path.getsize(o))))
    v = r.get("verify")
    if isinstance(v, dict) and "outline" in v:
        for name, sub in v.items():
            if isinstance(sub, dict):
                _print_verify("%s 版" % name, sub)
    elif isinstance(v, dict):
        _print_verify("", v)
    if r.get("error"):
        print("  错误: %s" % r["error"])


def doctor():
    checks = [
        ("gs", ["--version"], "Ghostscript（轮廓化必需）"),
        ("pdftocairo", ["-v"], "poppler-utils（栅格化/诊断）"),
        ("pdftoppm", ["-v"], "poppler-utils（校验渲染）"),
        ("pdffonts", ["-v"], "poppler-utils（字体诊断）"),
        ("pdfinfo", ["-v"], "poppler-utils（页面信息）"),
    ]
    ok = True
    print("pdf-normalize %s 环境自检\n" % VERSION)
    for cmd, flag, desc in checks:
        if have(cmd):
            ver_text = tool_version(cmd, flag[0]) or ""
            ver = parse_version(ver_text)
            floor = MIN_GS if cmd == "gs" else (MIN_POPPLER if cmd.startswith("pdf") or cmd == "pdftocairo" else None)
            note = ""
            if floor:
                if ver and not version_ok(ver, floor):
                    note = "  ⚠ 低于最低要求 %s" % ".".join(map(str, floor))
                    ok = False
                elif floor:
                    note = "  (最低 %s)" % ".".join(map(str, floor))
            print("  ✓ %-10s %s%s" % (cmd, ver_text, note))
        else:
            ok = False
            print("  ✗ %-10s 缺失 —— %s" % (cmd, desc))
    try:
        import PIL  # noqa: F401
        print("  ✓ PIL 可用（用于渲染比对）")
    except Exception:
        print("  ! PIL 不可用：校验时会尝试 ImageMagick，否则跳过渲染比对")
    print("\n提示：macOS 上 `brew install ghostscript poppler` 可补齐依赖。")
    return EXIT_OK if ok else EXIT_USAGE


def build_parser():
    p = argparse.ArgumentParser(
        prog="pdf-normalize",
        description="把打印乱码的 PDF 规范化成任何打印机都能出的文件（零字体版）。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  pdf-normalize 简历.pdf                     # 默认轮廓化，输出 简历-print.pdf
  pdf-normalize --mode image -d 300 简历.pdf # 输出 300dpi 纯图版
  pdf-normalize --mode both -o out/ 简历.pdf # 同时产出两种
  pdf-normalize --mode check 简历.pdf        # 只诊断
  pdf-normalize -r 简历目录/                 # 递归批量
  pdf-normalize --doctor                     # 环境自检
""")
    p.add_argument("inputs", nargs="*", help="PDF 文件或目录")
    p.add_argument("-m", "--mode", default="auto",
                   choices=["auto", "outline", "image", "fix", "both", "check"],
                   help="auto=轮廓化(失败自动降级为图片)；outline=矢量轮廓(默认推荐)；"
                        "image=整页栅格；fix=只修字体声明；both=两种都出；check=只诊断")
    p.add_argument("-o", "--out", help="输出目录（默认与原文件同目录）")
    p.add_argument("-d", "--dpi", type=int, default=DEFAULT_DPI, help="栅格化 DPI，默认 300")
    p.add_argument("--jpeg-quality", type=int, default=92, help="栅格化的 JPEG 质量，默认 92")
    p.add_argument("-r", "--recursive", action="store_true", help="递归处理目录")
    p.add_argument("-f", "--force", action="store_true", help="允许覆盖已存在的输出")
    p.add_argument("--suffix", default=DEFAULT_SUFFIX, help="输出文件名后缀，默认 -print")
    p.add_argument("--no-verify", action="store_true", help="跳过输出后的渲染校验（更快）")
    p.add_argument("--lossy-images", action="store_true",
                   help="轮廓化时允许图片有损转存（照片多的文件体积更小）")
    p.add_argument("--password",
                   help="加密 PDF 的密码（也可用环境变量 %s，避免进入 shell 历史）" % PASSWORD_ENV)
    p.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p.add_argument("-q", "--quiet", action="store_true", help="只输出错误")
    p.add_argument("--doctor", action="store_true", help="检查依赖环境")
    p.add_argument("-V", "--version", action="version", version="pdf-normalize %s" % VERSION)
    return p


def main(argv=None):
    opts = build_parser().parse_args(argv)

    if opts.doctor:
        return doctor()

    if not opts.inputs:
        build_parser().print_help()
        return EXIT_USAGE

    missing = [c for c in ("pdfinfo", "pdffonts") if not have(c)]
    if missing:
        print("缺少依赖: %s（macOS: brew install poppler）" % ", ".join(missing), file=sys.stderr)
        return EXIT_USAGE
    if opts.mode in ("outline", "auto", "both") and not have("gs"):
        print("缺少 Ghostscript（轮廓化必需）：brew install ghostscript\n"
              "也可以改用 --mode image（纯图片版，只需 poppler）。", file=sys.stderr)
        return EXIT_USAGE
    if opts.mode in ("image", "both") and not have("pdftocairo"):
        print("缺少 pdftocairo（栅格化必需）：brew install poppler", file=sys.stderr)
        return EXIT_USAGE
    if opts.mode in ("outline", "auto", "both"):
        gs_ver = parse_version(tool_version("gs", "--version"))
        if gs_ver and not version_ok(gs_ver, MIN_GS):
            print("警告：Ghostscript 版本 %s 低于建议的 %s，-dNoOutputFonts 可能不可用；"
                  "建议升级（brew install ghostscript）。" % (".".join(map(str, gs_ver)),
                                                          ".".join(map(str, MIN_GS))),
                  file=sys.stderr)

    opts.password = _resolve_password(opts.password)
    files, errors = collect_inputs(opts.inputs, opts.recursive, opts.suffix)
    for e in errors:
        print("警告: %s" % e, file=sys.stderr)
    if not files:
        print("没有找到可处理的 PDF。", file=sys.stderr)
        return EXIT_USAGE

    results = []
    for i, f in enumerate(files, 1):
        if not opts.quiet and not opts.json:
            print("[%d/%d] %s" % (i, len(files), f))
        results.append(process_one(f, opts))
        if not opts.quiet and not opts.json:
            print_result(results[-1], opts)
            print()

    failed = [r for r in results if not r["ok"]]
    if opts.json:
        print(json.dumps({"version": VERSION, "mode": opts.mode,
                          "results": results,
                          "summary": {"total": len(results), "ok": len(results) - len(failed),
                                      "failed": len(failed)}}, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("完成：%d 个文件，成功 %d，失败 %d" % (len(results), len(results) - len(failed), len(failed)))
        for r in failed:
            print("  ✗ %s —— %s" % (r["input"], r["error"] or "校验未通过"))

    if not failed:
        return EXIT_OK
    kinds = {r.get("error_kind") or "usage" for r in failed}
    if len(failed) == len(results):
        return EXIT_VERIFY if kinds == {"verify"} else EXIT_USAGE
    return EXIT_PARTIAL


if __name__ == "__main__":
    sys.exit(main())
