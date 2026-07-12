#!/usr/bin/env python3
"""PDF 文本提取工具 - 纯文本方式读取财报 PDF，不渲染图片。

为 AI Berkshire Skills 提供财报 PDF 的文本提取能力。当配置的模型为纯文本
模型（如 glm-5.2 via 火山方舟 coding plan）时，必须用本工具读取 PDF，
禁止将 PDF 页面渲染为 PNG 再用 view_image 查看——那会把图片发给纯文本
模型并触发 "Model only support text input" 错误。

依赖 PyMuPDF (fitz)，零网络依赖。

用法（由 Skills 自动调用）：
    python3 tools/pdf_text_extract.py text 财报.pdf                  # 提取全文
    python3 tools/pdf_text_extract.py text 财报.pdf --pages 1-10     # 提取指定页
    python3 tools/pdf_text_extract.py pages 财报.pdf                  # 列出各页字符数概览
    python3 tools/pdf_text_extract.py search 财报.pdf "主要客户"      # 搜索关键词所在页
    python3 tools/pdf_text_extract.py text 财报.pdf --out report.txt # 写入文件

需要 Python >= 3.8 + PyMuPDF。若 PyMuPDF 缺失，回退到 PyPDF2。
"""

import argparse
import sys
from pathlib import Path

_MIN_CHARS = 50  # 视为"有实质文本"的每页最小字符数


def _open_doc(pdf_path):
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        return doc, "pymupdf"
    except ImportError:
        pass
    try:
        from PyPDF2 import PdfReader

        return PdfReader(str(pdf_path)), "pypdf2"
    except ImportError:
        sys.exit(
            "错误：需要 PyMuPDF (pip install pymupdf) 或 PyPDF2 (pip install pypdf2)。"
        )


def _page_text(doc, index, backend):
    if backend == "pymupdf":
        return doc[index].get_text("text")
    # PyPDF2
    page = doc.pages[index]
    return page.extract_text() or ""


def _page_count(doc, backend):
    if backend == "pymupdf":
        return doc.page_count
    return len(doc.pages)


def _parse_pages(spec, total):
    """解析 '1-10,15,20-22' -> set of 0-based indices."""
    if not spec:
        return set(range(total))
    result = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo = int(lo) if lo else 1
            hi = int(hi) if hi else total
            result.update(range(lo - 1, min(hi, total)))
        elif part:
            result.add(int(part) - 1)
    return sorted(i for i in result if 0 <= i < total)


def cmd_text(args):
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"错误：文件不存在: {pdf_path}")
    doc, backend = _open_doc(pdf_path)
    total = _page_count(doc, backend)
    indices = _parse_pages(args.pages, total)
    chunks = []
    for i in indices:
        text = _page_text(doc, i, backend).strip()
        if text:
            chunks.append(f"===== 第 {i + 1} 页 / 共 {total} 页 =====\n{text}")
    output = "\n\n".join(chunks)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"已写入 {args.out}（{len(indices)} 页，{len(output)} 字符）", file=sys.stderr)
    else:
        print(output)


def cmd_pages(args):
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"错误：文件不存在: {pdf_path}")
    doc, backend = _open_doc(pdf_path)
    total = _page_count(doc, backend)
    print(f"文件: {pdf_path.name}  总页数: {total}  后端: {backend}")
    print("-" * 50)
    for i in range(total):
        text = _page_text(doc, i, backend)
        chars = len(text.strip())
        marker = "  <文本稀少/可能为扫描件>" if chars < _MIN_CHARS else ""
        print(f"  第 {i + 1:>4} 页: {chars:>6} 字符{marker}")


def cmd_search(args):
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        sys.exit(f"错误：文件不存在: {pdf_path}")
    doc, backend = _open_doc(pdf_path)
    total = _page_count(doc, backend)
    keyword = args.keyword
    hits = []
    for i in range(total):
        text = _page_text(doc, i, backend)
        if keyword.lower() in text.lower():
            # 取关键词上下文片段
            lower = text.lower()
            pos = lower.find(keyword.lower())
            start = max(0, pos - 40)
            end = min(len(text), pos + len(keyword) + 80)
            snippet = text[start:end].replace("\n", " ").strip()
            hits.append((i + 1, snippet))
    if not hits:
        print(f"未找到关键词 \"{keyword}\"")
        return
    print(f"关键词 \"{keyword}\" 命中 {len(hits)} 页：")
    for page_no, snippet in hits:
        print(f"  第 {page_no} 页: ...{snippet}...")
    if args.extract:
        print("\n--- 命中页文本 ---")
        doc2, _ = _open_doc(pdf_path)
        for page_no, _ in hits:
            print(f"\n===== 第 {page_no} 页 =====")
            print(_page_text(doc2, page_no - 1, backend).strip())


def main():
    parser = argparse.ArgumentParser(
        description="PDF 文本提取工具（纯文本，不渲染图片）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_text = sub.add_parser("text", help="提取 PDF 文本")
    p_text.add_argument("pdf", help="PDF 文件路径")
    p_text.add_argument("--pages", help="页码，如 1-10,15,20-22（默认全部）")
    p_text.add_argument("--out", help="写入文件而非 stdout")
    p_text.set_defaults(func=cmd_text)

    p_pages = sub.add_parser("pages", help="列出各页字符数概览")
    p_pages.add_argument("pdf", help="PDF 文件路径")
    p_pages.set_defaults(func=cmd_pages)

    p_search = sub.add_parser("search", help="搜索关键词所在页")
    p_search.add_argument("pdf", help="PDF 文件路径")
    p_search.add_argument("keyword", help="搜索关键词")
    p_search.add_argument("--extract", action="store_true", help="同时输出命中页文本")
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
