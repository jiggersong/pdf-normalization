#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""字体声明修复逻辑的单元测试（合成 PDF，不依赖任何真实文件）。

覆盖：
  1. CFF 程序被塞进 TrueType 槽位 -> 修复为 CIDFontType0 / FontFile3 / OpenType
  2. 反向错配（TrueType 程序塞进 CFF 槽位）-> 修复为 CIDFontType2 / FontFile2
  3. 没有错配时明确报「无需修复」
  4. 修复后 xref 偏移仍然正确（逐项校验）
"""

import re
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def load_module():
    """从仓库根目录导入实现模块（无需安装）。"""
    import pdf_normalize

    return pdf_normalize


def make_pdf(declared_subtype, descriptor_slot, program_bytes, stream_subtype=None):
    """拼一个结构完整的最小 PDF（含 type0 字体 + 字体程序流 + 正确 xref）。"""
    prog = zlib.compress(program_bytes)
    fontfile_dict = b"<</Filter/FlateDecode/Length %d/Length1 %d>>" % (len(prog), len(program_bytes))
    if stream_subtype:
        fontfile_dict = fontfile_dict[:-2] + b"/Subtype/" + stream_subtype + b">>"

    objs = {
        1: b"<</Type/Catalog/Pages 2 0 R>>",
        2: b"<</Type/Pages/Count 1/Kids[3 0 R]>>",
        3: b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]"
           b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        4: b"<</Type/Font/Subtype/Type0/BaseFont/TestFont/Encoding/Identity-H"
           b"/DescendantFonts[6 0 R]>>",
        5: None,  # content stream
        6: b"<</Type/Font/Subtype/" + declared_subtype + b"/BaseFont/TestFont"
           b"/CIDSystemInfo 7 0 R/CIDToGIDMap/Identity/DW 1000/FontDescriptor 8 0 R>>",
        7: b"<</Registry(Adobe)/Ordering(Identity)/Supplement 0>>",
        8: b"<</Type/FontDescriptor/FontName/TestFont/Flags 4/Ascent 800/Descent -200"
           b"/CapHeight 700/ItalicAngle 0/StemV 80/FontBBox[0 -200 1000 800]/"
           + descriptor_slot + b" 9 0 R>>",
        9: None,  # font program stream
    }
    content = b"q Q\n"
    objs[5] = b"<</Length %d>>stream\n" % len(content) + content + b"endstream"
    objs[9] = fontfile_dict + b"stream\n" + prog + b"\nendstream"

    buf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = {}
    for num in sorted(objs):
        offs[num] = len(buf)
        buf += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref = len(buf)
    buf += b"xref\n0 %d\n0000000000 65535 f \n" % (max(offs) + 1)
    for i in range(1, max(offs) + 1):
        buf += b"%010d 00000 n \n" % offs[i]
    buf += (b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
            % (max(offs) + 1, xref))
    return bytes(buf)


def check_xref(data):
    """逐项校验 xref 偏移是否真的指向对应对象。"""
    i = data.rfind(b"startxref")
    assert i != -1, "缺少 startxref"
    pos = int(re.match(rb"startxref\s+(\d+)", data[i:]).group(1))
    assert data[pos:pos + 4] == b"xref", "startxref 指向的不是 xref 表"
    head = re.match(rb"xref\s+0\s+(\d+)\s+", data[pos:])
    size = int(head.group(1))
    table = data[pos + head.end():]
    for n in range(1, size):
        entry = table[n * 20:(n + 1) * 20]
        off = int(entry[:10])
        prefix = b"%d 0 obj" % n
        if off == 0 or entry[17:18] == b"f":
            continue
        assert data[off:off + len(prefix)] == prefix, "对象 %d 的 xref 偏移错误" % n


def test_cff_in_truetype_slot(mod, tmpdir):
    src = Path(tmpdir) / "cff_in_tt.pdf"
    dst = Path(tmpdir) / "cff_fixed.pdf"
    src.write_bytes(make_pdf(b"CIDFontType2", b"/FontFile2", b"OTTO" + b"\x00" * 64))
    n, explain = mod.repair_font_declarations(src, dst)
    out = dst.read_bytes()
    assert n == 1, explain
    assert b"/Subtype/CIDFontType0" in out
    assert b"/FontFile3 9 0 R" in out
    assert b"/Subtype/OpenType" in out
    assert b"/FontFile2 9 0 R" not in out
    check_xref(out)
    print("  ✓ CFF 塞进 TrueType 槽位 -> 正确修复")


def test_truetype_in_cff_slot(mod, tmpdir):
    src = Path(tmpdir) / "tt_in_cff.pdf"
    dst = Path(tmpdir) / "tt_fixed.pdf"
    src.write_bytes(make_pdf(b"CIDFontType0", b"/FontFile3", b"\x00\x01\x00\x00" + b"\x00" * 64))
    n, explain = mod.repair_font_declarations(src, dst)
    out = dst.read_bytes()
    assert n == 1, explain
    assert b"/Subtype/CIDFontType2" in out
    assert b"/FontFile2 9 0 R" in out
    check_xref(out)
    print("  ✓ TrueType 塞进 CFF 槽位 -> 正确修复")


def test_noop(mod, tmpdir):
    src = Path(tmpdir) / "ok.pdf"
    dst = Path(tmpdir) / "ok_fixed.pdf"
    src.write_bytes(make_pdf(b"CIDFontType2", b"/FontFile2", b"\x00\x01\x00\x00" + b"\x00" * 64))
    try:
        mod.repair_font_declarations(src, dst)
    except RuntimeError as e:
        assert "未发现" in str(e)
        print("  ✓ 无错配时报「无需修复」")
    else:
        raise AssertionError("应当抛出「无需修复」")


def main():
    if not (HERE / "pdf_normalize.py").exists():
        print("找不到 %s" % (HERE / "pdf_normalize.py"))
        return 1
    mod = load_module()
    with tempfile.TemporaryDirectory(prefix="pdfnorm-test-") as td:
        test_cff_in_truetype_slot(mod, td)
        test_truetype_in_cff_slot(mod, td)
        test_noop(mod, td)
    print("单元测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
