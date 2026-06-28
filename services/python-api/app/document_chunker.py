"""个人文档切分。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentChunk:
    """切分后的文档片段。"""

    chunk_index: int
    content: str


def split_document_text(text: str, chunk_size: int, chunk_overlap: int) -> list[DocumentChunk]:
    """把纯文本切成适合向量化的 chunks。"""
    normalized = text.strip()
    if not normalized:
        raise ValueError("text cannot be empty")

    chunks = split_text_by_separators(normalized, chunk_size, chunk_overlap)

    return [
        DocumentChunk(chunk_index=index, content=chunk.strip())
        for index, chunk in enumerate(chunks)
        if chunk.strip()
    ]


def split_text_by_separators(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """按优先级分隔文本，并在片段之间保留少量重叠。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap cannot be negative")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be less than chunk_size")

    chunks: list[str] = []
    current = ""
    for segment in split_large_segment(text, chunk_size):
        candidate = f"{current}{segment}" if current else segment
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        overlap_text = current[-chunk_overlap:] if chunk_overlap and current else ""
        current = f"{overlap_text}{segment}"

        while len(current) > chunk_size:
            chunks.append(current[:chunk_size])
            current = current[chunk_size - chunk_overlap :]

    if current:
        chunks.append(current)
    return chunks


def split_large_segment(text: str, chunk_size: int) -> list[str]:
    """递归按自然分隔符切分超长文本。"""
    segments = [text]
    for separator in ["\n\n", "\n", "。", "！", "？", ". ", " ", ""]:
        next_segments: list[str] = []
        for segment in segments:
            if len(segment) <= chunk_size:
                next_segments.append(segment)
                continue
            next_segments.extend(split_segment(segment, separator, chunk_size))
        segments = next_segments
    return segments


def split_segment(text: str, separator: str, chunk_size: int) -> list[str]:
    """使用单个分隔符切分文本，分隔符会保留在前一段。"""
    if not separator:
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]

    parts = text.split(separator)
    segments: list[str] = []
    current = ""
    for index, part in enumerate(parts):
        suffix = separator if index < len(parts) - 1 else ""
        piece = f"{part}{suffix}"
        candidate = f"{current}{piece}" if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            segments.append(current)
        current = piece
    if current:
        segments.append(current)
    return segments
