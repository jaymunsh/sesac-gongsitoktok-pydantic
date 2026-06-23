"""OpenDART 연동 — 공시 목록 조회 + 원문(XML) 다운로드.

기존(gongsi-agent)과의 차이: 원문을 **평문으로 뭉개지 않고 raw XML로 반환**한다.
표 구조 보존은 파서(parser.py)가 담당한다. 여기서는 다운로드/해제/인코딩만.
"""
from __future__ import annotations

import io
import json
import os
import xml.etree.ElementTree as ET
import zipfile

import httpx

from app.config import get_settings

BASE = "https://opendart.fss.or.kr/api"
_CORPCODE_CACHE = "./data/corpcode.json"


class DartError(RuntimeError):
    pass


def _api_key() -> str:
    key = get_settings().dart_api_key
    if not key:
        raise DartError("DART_API_KEY 가 설정되지 않았습니다 (.env 확인).")
    return key


def list_disclosures(
    *,
    corp_code: str | None = None,
    bgn_de: str | None = None,
    end_de: str | None = None,
    pblntf_ty: str | None = None,
    page_no: int = 1,
    page_count: int = 100,
) -> dict:
    """공시 목록 조회. 전체 응답(list/total_count/total_page 포함)."""
    params: dict = {"crtfc_key": _api_key(), "page_no": page_no, "page_count": page_count}
    if corp_code:
        params["corp_code"] = corp_code
    if bgn_de:
        params["bgn_de"] = bgn_de
    if end_de:
        params["end_de"] = end_de
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty

    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{BASE}/list.json", params=params)
        resp.raise_for_status()
        data = resp.json()
    status = data.get("status")
    if status not in ("000", "013"):  # 013 = 데이터 없음
        raise DartError(f"DART list 오류: {status} {data.get('message')}")
    return data


def download_corp_codes() -> list[dict]:
    """전체 기업 고유번호 목록(캐시 우선). data/corpcode.json 재사용."""
    if os.path.exists(_CORPCODE_CACHE):
        with open(_CORPCODE_CACHE, encoding="utf-8") as f:
            return json.load(f)
    params = {"crtfc_key": _api_key()}
    with httpx.Client(timeout=60) as client:
        resp = client.get(f"{BASE}/corpCode.xml", params=params)
        resp.raise_for_status()
        content = resp.content
    if content[:2] != b"PK":
        raise DartError(f"corpCode 다운로드 실패: {content[:200]!r}")
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        xml = zf.read(zf.namelist()[0])
    rows: list[dict] = []
    root = ET.fromstring(xml)
    for el in root.iter("list"):
        rows.append(
            {
                "corp_code": (el.findtext("corp_code") or "").strip(),
                "corp_name": (el.findtext("corp_name") or "").strip(),
                "stock_code": (el.findtext("stock_code") or "").strip(),
            }
        )
    os.makedirs(os.path.dirname(_CORPCODE_CACHE), exist_ok=True)
    with open(_CORPCODE_CACHE, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows


def find_corp_code(name: str, *, listed_only: bool = True) -> list[dict]:
    """회사명으로 corp_code 후보 찾기(부분 일치, 상장사 우선)."""
    rows = download_corp_codes()
    name = name.strip()
    hits = [r for r in rows if name in r["corp_name"]]
    if listed_only:
        listed = [r for r in hits if r["stock_code"]]
        if listed:
            return listed
    return hits


# 보고서 코드: 사업보고서=11011, 반기=11012, 1분기=11013, 3분기=11014
def fetch_financials(corp_code: str, bsns_year: str, reprt_code: str = "11011") -> list[dict]:
    """단일회사 주요계정(fnlttSinglAcnt) — 매출·영업이익·순이익 등 정형 수치.

    각 행은 당기/전기/전전기 금액과 연결(CFS)/별도(OFS) 구분 포함. 데이터 없음(013)→빈 리스트.
    """
    params = {
        "crtfc_key": _api_key(),
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }
    with httpx.Client(timeout=20) as client:
        resp = client.get(f"{BASE}/fnlttSinglAcnt.json", params=params)
        resp.raise_for_status()
        data = resp.json()
    status = data.get("status")
    if status == "013":
        return []
    if status != "000":
        raise DartError(f"DART 재무제표 오류: {status} {data.get('message')}")
    return data.get("list", [])


def fetch_document_xml(rcept_no: str) -> str:
    """접수번호로 공시 원문 ZIP을 받아 **raw XML(태그 보존)** 로 반환.

    document.xml API → ZIP(내부 XML 1개 이상). 표/섹션 태그를 그대로 살려
    파서가 구조를 읽을 수 있게 한다. (평문 변환은 하지 않음)
    """
    if not rcept_no or not rcept_no.isdigit():
        raise DartError(f"잘못된 접수번호: {rcept_no!r}")
    params = {"crtfc_key": _api_key(), "rcept_no": rcept_no}
    with httpx.Client(timeout=120) as client:
        resp = client.get(f"{BASE}/document.xml", params=params)
        resp.raise_for_status()
        content = resp.content
    if content[:2] != b"PK":
        raise DartError(f"문서 다운로드 실패(ZIP 아님): {content[:200]!r}")
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for name in zf.namelist():
            parts.append(_decode(zf.read(name)))
    return "\n".join(parts)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")
