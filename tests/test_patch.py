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


def make_pdf(declared_subtype, descriptor_slot, program_bytes, stream_subtype=None,
             subtype_sep=b"/", fontfile_sep=b" "):
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
        6: b"<</Type/Font/Subtype" + subtype_sep + declared_subtype + b"/BaseFont/TestFont"
           b"/CIDSystemInfo 7 0 R/CIDToGIDMap/Identity/DW 1000/FontDescriptor 8 0 R>>",
        7: b"<</Registry(Adobe)/Ordering(Identity)/Supplement 0>>",
        8: b"<</Type/FontDescriptor/FontName/TestFont/Flags 4/Ascent 800/Descent -200"
           b"/CapHeight 700/ItalicAngle 0/StemV 80/FontBBox[0 -200 1000 800]/"
           + descriptor_slot + fontfile_sep + b"9 0 R>>",
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


def test_whitespace_variants(mod, tmpdir):
    """真实 PDF 常见 /Subtype /CIDFontType2、/FontFile2  9 0 R 等写法，必须同样修复。"""
    variants = [
        ("subtype 单空格", b" /", b" "),
        ("subtype 双空格", b"  /", b"  "),
        ("fontfile 换行", b"/", b"\n"),
    ]
    for name, st_sep, ff_sep in variants:
        src = Path(tmpdir) / ("ws_%s.pdf" % name)
        dst = Path(tmpdir) / ("ws_%s_fixed.pdf" % name)
        src.write_bytes(make_pdf(b"CIDFontType2", b"/FontFile2", b"OTTO" + b"\x00" * 64,
                                 subtype_sep=st_sep, fontfile_sep=ff_sep))
        n, explain = mod.repair_font_declarations(src, dst)
        out = dst.read_bytes()
        assert n == 1, (name, explain)
        assert b"/Subtype/CIDFontType0" in out, name
        assert b"/FontFile3 9 0 R" in out, name
        assert b"CIDFontType2" not in out, name
        assert b"FontFile2" not in out, name
        check_xref(out)
        print("  ✓ 空白变体（%s）正确修复" % name)


def test_xref_fallback_root(mod, tmpdir):
    """没有传统 trailer（交叉引用流）时，应从 /Type/Catalog 兜底找到 Root。"""
    data = make_pdf(b"CIDFontType2", b"/FontFile2", b"\x00\x01\x00\x00" + b"\x00" * 64)
    body = data[:data.rfind(b"xref")]
    objs = mod._find_objects(body)
    out = mod._rebuild_xref(b"", body, objs)
    assert b"/Root 1 0 R" in out
    check_xref(out)
    print("  ✓ 无 trailer 时 xref 重建可兜底 Root")


def test_skip_verify_semantics(mod, tmpdir):
    """--no-verify 的校验结果必须标记 skipped，而不是伪造 ok=true。"""
    v = mod.skipped_verify()
    assert v["skipped"] is True and v["ok"] is None and v["fonts"] is None
    assert mod._verify_passed(v) is True
    assert mod._verify_passed({"ok": True}) is True
    assert mod._verify_passed({"ok": False}) is False
    print("  ✓ --no-verify 语义：skipped 标记正确")


def test_collect_inputs_suffix(mod, tmpdir):
    """目录扫描：大小写 .PDF 都收，且按 --suffix 排除本工具产物。"""
    d = Path(tmpdir) / "collect"
    d.mkdir()
    (d / "a.pdf").write_bytes(b"%PDF-1.4")
    (d / "b.PDF").write_bytes(b"%PDF-1.4")
    (d / "a-print.pdf").write_bytes(b"%PDF-1.4")
    (d / "a-可打印.pdf").write_bytes(b"%PDF-1.4")
    files, _ = mod.collect_inputs([d], False, "-可打印")
    names = sorted(f.name for f in files)
    assert names == ["a.pdf", "b.PDF"], names
    print("  ✓ 目录扫描：.PDF 大小写兼容 + 自定义后缀排除")


def test_magick_compare(mod, tmpdir):
    """无 PIL 时 ImageMagick 后备必须同时得出均值与差异像素占比。"""
    import shutil
    import subprocess
    if not shutil.which("magick"):
        print("  - 跳过 ImageMagick 后备测试（未安装 magick）")
        return
    a = Path(tmpdir) / "a.png"
    b = Path(tmpdir) / "b.png"
    subprocess.run(["magick", "-size", "120x80", "xc:white", "-fill", "black",
                    "-draw", "rectangle 10,10 60,60", str(a)], check=True)
    subprocess.run(["magick", "-size", "120x80", "xc:white", "-fill", "black",
                    "-draw", "rectangle 14,14 64,64", str(b)], check=True)
    saved = sys.modules.get("PIL", "missing")
    sys.modules["PIL"] = None  # 让 `from PIL import ...` 失败
    try:
        res = mod._compare([a], [b])
    finally:
        if saved == "missing":
            sys.modules.pop("PIL", None)
        else:
            sys.modules["PIL"] = saved
    assert res is not None
    mean, pct = res
    assert mean > 0 and pct > 0, res
    print("  ✓ ImageMagick 后备：均值 %.2f / 差异像素 %.2f%%" % (mean, pct))


def test_exit_codes(mod, tmpdir):
    """退出码：全部因校验失败 -> 2；部分失败 -> 3。"""
    import io
    from contextlib import redirect_stdout

    d = Path(tmpdir) / "exit"
    d.mkdir()
    pdf = d / "x.pdf"
    pdf2 = d / "y.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    pdf2.write_bytes(b"%PDF-1.4")

    def fail_result(path, opts):
        return {"input": str(path), "ok": False, "error": "校验未通过", "error_kind": "verify",
                "outputs": [], "verify": None, "diagnosis": None}

    def ok_result(path, opts):
        return {"input": str(path), "ok": True, "error": "", "error_kind": "",
                "outputs": [], "verify": None, "diagnosis": None}

    saved = (mod.collect_inputs, mod.process_one)
    try:
        mod.collect_inputs = lambda *a, **k: ([pdf, pdf2], [])
        mod.process_one = fail_result
        with redirect_stdout(io.StringIO()):
            rc = mod.main(["--mode", "outline", str(pdf), str(pdf2)])
        assert rc == mod.EXIT_VERIFY, rc

        calls = {"n": 0}

        def mixed(path, opts):
            calls["n"] += 1
            return ok_result(path, opts) if calls["n"] == 1 else fail_result(path, opts)

        mod.process_one = mixed
        with redirect_stdout(io.StringIO()):
            rc = mod.main(["--mode", "outline", str(pdf), str(pdf)])
        assert rc == mod.EXIT_PARTIAL, rc
    finally:
        mod.collect_inputs, mod.process_one = saved
    print("  ✓ 退出码：全校验失败=2，部分失败=3")


def test_no_input_and_decrypt(mod, tmpdir):
    """--no-input 禁止交互；加密 PDF 可先解密到临时文件供后续工具链免密处理。"""
    import shutil
    import subprocess

    # 1) --no-input 解析与全局开关
    opts = mod.build_parser().parse_args(["--no-input", "x.pdf"])
    assert opts.no_input is True
    mod._resolve_no_prompt(True)
    try:
        assert mod._prompt_password_on_error("This file requires a password", None) is None
    finally:
        mod._resolve_no_prompt(False)
    print("  ✓ --no-input 禁止交互式提示")

    # 2) gs 解密到临时文件（无 gs 则跳过）
    if not (shutil.which("gs") and shutil.which("pdfinfo")):
        print("  - 跳过解密测试（未安装 gs/pdfinfo）")
        return
    plain = Path(tmpdir) / "plain.pdf"
    enc = Path(tmpdir) / "enc.pdf"
    plain.write_bytes(make_pdf(b"CIDFontType2", b"/FontFile2", b"\x00\x01\x00\x00" + b"\x00" * 64))
    rc = subprocess.run([
        "gs", "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=pdfwrite",
        "-sOwnerPassword=owner", "-sUserPassword=user",
        "-dEncryptionR=3", "-dKeyLength=128",
        "-sOutputFile=" + str(enc), str(plain),
    ]).returncode
    if rc != 0:
        print("  - 当前 gs 不支持加密参数，跳过解密测试")
        return
    got = mod._decrypt_source(enc, "user")
    assert got is not None, "解密失败"
    dec_path, cleanup = got
    try:
        mod.pdfinfo(dec_path)  # 无密码应可读
        assert dec_path != enc
    finally:
        Path(cleanup).unlink(missing_ok=True)
    assert not Path(cleanup).exists()
    print("  ✓ 加密 PDF 解密到临时文件并清理")


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
        test_whitespace_variants(mod, td)
        test_xref_fallback_root(mod, td)
        test_skip_verify_semantics(mod, td)
        test_collect_inputs_suffix(mod, td)
        test_exit_codes(mod, td)
        test_no_input_and_decrypt(mod, td)
        test_magick_compare(mod, td)
        test_noop(mod, td)
    print("单元测试全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
