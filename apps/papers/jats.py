"""Parse JATS XML (Europe PMC) into section records.

Output: list[ParsedSection] in document order, with DoCO labels +
IRIs from papers.doco.
"""

from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from papers.doco import map_jats_sec_type, map_section_heading


@dataclass
class ParsedSection:
    order_index: int
    doco_label: str
    doco_iri: str
    heading: str
    body_text: str


def _strip_ns(tag: object) -> str:
    # lxml yields Comment / ProcessingInstruction nodes whose .tag is a
    # callable, not a string — real PMC JATS contains these. Treat them as
    # non-elements so iteration over tree.iter() never crashes.
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _collect_text(el: etree._Element) -> str:
    """Concatenate all <p> descendants of ``el`` (including sub-sections)."""
    parts: list[str] = []
    for p in el.iter():
        if _strip_ns(p.tag) == "p":
            text = " ".join(p.itertext()).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def parse_jats(xml_bytes: bytes) -> list[ParsedSection]:
    """Return one ParsedSection per top-level <sec> in <body>."""
    tree = etree.fromstring(xml_bytes)  # noqa: S320
    sections: list[ParsedSection] = []
    body_elements = [el for el in tree.iter() if _strip_ns(el.tag) == "body"]
    if not body_elements:
        return []
    body = body_elements[0]
    order = 0
    for sec in body:
        if _strip_ns(sec.tag) != "sec":
            continue
        sec_type = sec.get("sec-type")
        heading = ""
        for child in sec:
            if _strip_ns(child.tag) == "title":
                heading = " ".join(child.itertext()).strip()
                break
        if sec_type:
            label, iri = map_jats_sec_type(sec_type)
        else:
            label, iri = map_section_heading(heading)
        body_text = _collect_text(sec)
        sections.append(
            ParsedSection(
                order_index=order,
                doco_label=label,
                doco_iri=iri,
                heading=heading,
                body_text=body_text,
            )
        )
        order += 1
    return sections
