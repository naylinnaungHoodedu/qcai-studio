from dataclasses import dataclass
from pathlib import Path

from docx import Document


@dataclass
class SectionRecord:
    source_id: str
    source_title: str
    heading: str
    level: int
    body: str


def parse_docx_sections(path: Path) -> list[SectionRecord]:
    document = Document(path)
    sections: list[SectionRecord] = []
    current_heading = path.stem
    current_level = 1
    current_paragraphs: list[str] = []

    def flush() -> None:
        if current_paragraphs:
            sections.append(
                SectionRecord(
                    source_id=path.stem.lower().replace(" ", "-"),
                    source_title=path.name,
                    heading=current_heading,
                    level=current_level,
                    body="\n\n".join(current_paragraphs).strip(),
                )
            )

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style_name = paragraph.style.name if paragraph.style else ""
        if style_name.startswith("Heading") or style_name == "Title":
            flush()
            current_heading = text
            digits = "".join(ch for ch in style_name if ch.isdigit())
            current_level = int(digits) if digits else 1
            current_paragraphs = []
            continue
        current_paragraphs.append(text)

    flush()
    return sections
