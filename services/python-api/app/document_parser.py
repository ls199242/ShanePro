"""个人文档解析。

首版支持 txt、md、pdf，并统一抽取为纯文本。扫描件 OCR、表格结构化和复杂版式保留到后续阶段。
"""

from __future__ import annotations

from pathlib import Path


SUPPORTED_DOCUMENT_SUFFIXES = {".txt", ".md", ".pdf"}


class DocumentParseError(ValueError):
    """文档解析失败。"""


def validate_supported_document(filename: str) -> str:
    """校验文件扩展名并返回小写后缀。"""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_SUFFIXES))
        raise DocumentParseError(f"暂不支持的文档类型: {suffix or 'unknown'}，仅支持 {supported}")
    return suffix


def parse_document(path: Path, filename: str | None = None) -> str:
    """把文档解析为纯文本。

    @param path: 已保存到本地的文件路径。
    @param filename: 原始文件名；为空时使用 path.name。
    @return: 非空纯文本。
    @raises DocumentParseError: 文件类型不支持、解析失败或解析结果为空时抛出。
    """
    suffix = validate_supported_document(filename or path.name)
    if suffix in {".txt", ".md"}:
        text = read_text_file(path)
    else:
        text = read_pdf_file(path)

    normalized = text.strip()
    if not normalized:
        raise DocumentParseError("文档解析后没有可用文本")
    return normalized


def read_text_file(path: Path) -> str:
    """读取 UTF-8 文本文档。"""
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DocumentParseError("文本文档必须使用 UTF-8 编码") from exc


def read_pdf_file(path: Path) -> str:
    """读取 PDF 文本。"""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise DocumentParseError("缺少 pypdf 依赖，无法解析 PDF") from exc

    try:
        reader = PdfReader(str(path))
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise DocumentParseError(f"PDF 解析失败: {exc}") from exc
    return "\n\n".join(page_texts)
