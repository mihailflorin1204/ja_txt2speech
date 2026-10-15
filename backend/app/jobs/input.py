"""Long-text job input handling: paste/upload (txt/epub/md) + chapter detection
(spec §FR-7.1, FR-7.2)."""

import re
from pathlib import Path

from pydantic import BaseModel


class Chapter(BaseModel):
    title: str
    text: str


def decode_text(raw: bytes) -> str:
    """UTF-8 / Shift_JIS auto-detection."""
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


_MD_HEADING = re.compile(r"^#{1,3}\s+(.+)$", re.M)
_JP_CHAPTER = re.compile(r"^(第[一二三四五六七八九十百千零〇\d]+[章節部話回].*)$", re.M)


def _split_by_regex(text: str, pattern: re.Pattern, group: int = 1) -> list[Chapter]:
    """Split text at heading matches; each chapter starts at a heading."""
    matches = list(pattern.finditer(text))
    if not matches:
        return [Chapter(title="全文", text=text)]
    chapters: list[Chapter] = []
    if matches[0].start() > 0 and text[: matches[0].start()].strip():
        chapters.append(Chapter(title="冒頭", text=text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapters.append(Chapter(title=m.group(group).strip(), text=text[m.start():end]))
    return chapters


def chapters_from_text(text: str) -> list[Chapter]:
    """Chapter detection for plain text / markdown."""
    if _MD_HEADING.search(text):
        return _split_by_regex(text, _MD_HEADING)
    if _JP_CHAPTER.search(text):
        return _split_by_regex(text, _JP_CHAPTER, group=0)
    return [Chapter(title="全文", text=text)]


def chapters_from_epub(path: Path) -> list[Chapter]:
    """Extract chapters from EPUB TOC/spine via ebooklib."""
    import ebooklib
    from ebooklib import epub
    from lxml import html as lxml_html  # noqa: N813

    book = epub.read_epub(str(path))
    chapters: list[Chapter] = []
    spine_ids = [item[0] for item in book.spine]
    items = {i.get_id(): i for i in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)}

    for idx, sid in enumerate(spine_ids):
        item = items.get(sid)
        if item is None:
            continue
        content = item.get_content()
        try:
            root = lxml_html.fromstring(content)
            text = "\n".join(t.strip() for t in root.itertext() if t.strip())
        except Exception:  # noqa: BLE001
            text = content.decode("utf-8", errors="replace")
        if not text.strip():
            continue
        title = item.get_name() or f"章 {idx + 1}"
        chapters.append(Chapter(title=title, text=text))
    return chapters or [Chapter(title="全文", text="")]


def parse_input(filename: str | None, raw: bytes | None,
                pasted_text: str | None) -> list[Chapter]:
    """Entry point: returns chapter list from upload or pasted text."""
    if pasted_text is not None:
        return chapters_from_text(pasted_text)
    assert raw is not None
    ext = Path(filename or "").suffix.lower()
    if ext == ".epub":
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
            tmp.write(raw)
            tmp_path = Path(tmp.name)
        try:
            return chapters_from_epub(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    return chapters_from_text(decode_text(raw))
