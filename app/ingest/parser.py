"""표-인식 파싱 — DART 공시 raw XML → 구조 보존 Block 리스트.

기존(gongsi-agent)은 모든 태그를 공백으로 치환해 표를 plaintext로 뭉갰다(행·열 소실).
여기서는 BeautifulSoup으로 트리를 순회하며:
  - <TABLE>  → Markdown 표로 변환(행·열·헤더 보존, COLSPAN 패딩)
  - <P>      → 본문 텍스트 블록
  - <TITLE>/<SECTION-*> → 섹션 경로(section_path) 추적
표 셀 태그는 TD/TH/TE/TU 4종(TU는 기간·단위 값) — 모두 셀로 취급한다.

DART 문서는 root가 여러 개(<DOCUMENT> 3개: 감사보고서·재무제표·본보고서)라
관대한 'lxml' HTML 파서를 쓴다(태그는 소문자화됨).
"""
from __future__ import annotations

import re
import warnings

from bs4 import BeautifulSoup, Tag
from bs4 import XMLParsedAsHTMLWarning

from app.schemas.ingest import Block

# 다중 root SGML 문서는 관대한 HTML 파서로 읽는 게 더 안정적 — 의도된 선택
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_CELL_TAGS = {"td", "th", "te", "tu"}
_TITLE_TAGS = {"title"}
_TEXT_TAGS = {"p"}
_SKIP_TAGS = {"image", "img", "img-caption", "pgbrk", "formula-version"}


def parse_document(xml: str) -> list[Block]:
    """raw XML을 표-인식 Block 리스트로 변환."""
    soup = BeautifulSoup(xml, "lxml")
    root = soup.body or soup
    blocks: list[Block] = []
    path: list[str] = []
    text_buf: list[str] = []

    def flush_text() -> None:
        if not text_buf:
            return
        joined = _clean("\n".join(text_buf))
        text_buf.clear()
        if joined:
            blocks.append(Block(kind="text", text=joined, section_path=list(path)))

    def walk(node: Tag, depth: int) -> None:
        for child in node.children:
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in _SKIP_TAGS:
                continue
            if name in _TITLE_TAGS:
                flush_text()
                heading = _first_line(child.get_text("\n"))
                if heading:
                    # 섹션 머리표(I., 1., 가.)면 새 경로, 아니면 단순 제목
                    _push_heading(path, heading, depth)
                continue
            if name == "table":
                flush_text()
                blk = _table_to_block(child, list(path))
                if blk:
                    blocks.append(blk)
                continue  # 표 내부로 재귀하지 않음
            if name in _TEXT_TAGS:
                txt = child.get_text(" ").strip()
                if txt:
                    text_buf.append(txt)
                continue
            # section-1/section-2/table-group/그 외 컨테이너 → 재귀
            walk(child, depth + 1)

    walk(root, 0)
    flush_text()
    return _merge_short(blocks)


# ── 표 → Markdown ────────────────────────────────────────────
def _table_to_block(table: Tag, path: list[str]) -> Block | None:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        cells: list[str] = []
        for cell in tr.find_all(_CELL_TAGS, recursive=False) or tr.find_all(_CELL_TAGS):
            txt = _clean_cell(cell.get_text(" "))
            span = _int(cell.get("colspan"), 1)
            cells.append(txt)
            for _ in range(span - 1):
                cells.append("")  # COLSPAN → 빈 칸 패딩(열 정렬 유지)
        if any(c for c in cells):
            rows.append(cells)
    if not rows:
        return None

    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    md = _rows_to_markdown(rows)
    title = _table_caption(table)
    return Block(
        kind="table",
        text=md,
        section_path=path,
        table_title=title,
        n_rows=len(rows),
        n_cols=width,
    )


def _rows_to_markdown(rows: list[list[str]]) -> str:
    header = rows[0]
    body = rows[1:]
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for r in body:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _table_caption(table: Tag) -> str | None:
    """표 바로 앞 형제 텍스트(캡션) 추정."""
    prev = table.find_previous_sibling()
    hops = 0
    while prev is not None and hops < 3:
        if isinstance(prev, Tag):
            txt = _first_line(prev.get_text(" "))
            if txt and len(txt) <= 80:
                return txt
        prev = prev.find_previous_sibling() if prev else None
        hops += 1
    return None


# ── 섹션 경로 추적 ───────────────────────────────────────────
# I. / 1. / 가. / (1) 등 공시 머리표
_LV1 = re.compile(r"^[IVXⅠⅡⅢⅣⅤ]+\.")          # I. II. ...
_LV2 = re.compile(r"^\d+\.")                      # 1. 2. ...
_LV3 = re.compile(r"^[가-힣]\.")                  # 가. 나. ...


def _push_heading(path: list[str], heading: str, depth: int) -> None:
    h = heading.strip()
    if _LV1.match(h):
        path[:] = [h]
    elif _LV2.match(h):
        path[:] = path[:1] + [h]
    elif _LV3.match(h):
        path[:] = path[:2] + [h]
    else:
        # 머리표 없는 제목 — 현재 깊이 끝에 치환
        if path:
            path[-1] = h
        else:
            path.append(h)


# ── 텍스트 정리 ──────────────────────────────────────────────
def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_cell(text: str) -> str:
    s = re.sub(r"\s+", " ", text.replace("\xa0", " ").replace("|", "/")).strip()
    return _despace(s)


# DART는 제목·라벨을 자간으로 띄움("매 출 액", "주 석", "당 기").
# 자간 런 = 앞뒤가 한글이 아닌(독립) '한글+공백' 반복 + 한글. 이 런만 붙인다.
# 경계 검사로 "가전 및 모바일" 같은 1글자 단어 혼재 문장은 건드리지 않는다.
_LETTERSPACED = re.compile(r"(?<![가-힣])((?:[가-힣] )+[가-힣])(?![가-힣])")


def _despace(s: str) -> str:
    return _LETTERSPACED.sub(lambda m: m.group(1).replace(" ", ""), s)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        s = re.sub(r"[ \t]+", " ", line).strip()  # 자간 정규화 전 다중공백 정리
        if s:
            return _despace(s)
    return ""


def _int(v, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _merge_short(blocks: list[Block], min_chars: int = 40) -> list[Block]:
    """아주 짧은 연속 text 블록을 합쳐 청크 파편화를 줄인다(표는 건드리지 않음)."""
    out: list[Block] = []
    for b in blocks:
        if (
            b.kind == "text"
            and out
            and out[-1].kind == "text"
            and out[-1].section_path == b.section_path
            and len(out[-1].text) < min_chars
        ):
            out[-1] = out[-1].model_copy(update={"text": out[-1].text + "\n" + b.text})
        else:
            out.append(b)
    return out
