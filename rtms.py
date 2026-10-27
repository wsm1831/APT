"""국토교통부 실거래가 공개 API 수집, 캐시, 단지 필터링."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pandas as pd
import requests

BASE = "https://apis.data.go.kr/1613000"
ENDPOINTS = {
    "매매": f"{BASE}/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
    "전월세": f"{BASE}/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
    "분양권": f"{BASE}/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
}
DB_PATH = Path(__file__).parent / "data" / "rtms.sqlite"
# 신고기한(30일)과 해제 신고 때문에 최근 몇 달은 매번 다시 받는다.
REFRESH_RECENT_MONTHS = 3


class ApiError(RuntimeError):
    pass


@dataclass
class Complex:
    id: str
    name: str
    region: str
    lawd_cd: str
    umd: str
    keywords: list[str]
    completed: str = ""
    naver_complex_id: str = ""
    # 비교 단지를 찾을 인근 법정동. [{"lawd_cd": "27140", "umd": "신천동"}, ...]
    nearby: list[dict] = field(default_factory=list)

    @property
    def naver_url(self) -> str:
        if self.naver_complex_id:
            return f"https://new.land.naver.com/complexes/{self.naver_complex_id}"
        return f"https://m.land.naver.com/search/result/{self.region.split()[0]} {self.name}"


def load_complexes(path: Path | str = Path(__file__).parent / "complexes.json") -> list[Complex]:
    with open(path, encoding="utf-8") as f:
        return [Complex(**c) for c in json.load(f)]


def month_range(months: int, today: date | None = None) -> list[str]:
    """오늘이 속한 달부터 거슬러 올라가 months개의 YYYYMM 목록(과거→현재)."""
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(months):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _num(text: str | None) -> float | None:
    if text is None:
        return None
    text = text.replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_response(xml_text: str) -> tuple[list[dict], int]:
    """API XML 응답을 (item dict 목록, totalCount)로 변환. 오류 응답이면 ApiError."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ApiError(f"응답을 해석할 수 없습니다: {xml_text[:200]}") from e

    # 인증키 오류 등은 OpenAPI_ServiceResponse 형식으로 온다.
    auth_msg = root.findtext(".//returnAuthMsg")
    if auth_msg:
        raise ApiError(f"API 인증 오류: {auth_msg} ({root.findtext('.//returnReasonCode')})")

    code = (root.findtext(".//header/resultCode") or "").strip()
    if code not in ("00", "000"):
        raise ApiError(f"API 오류 {code}: {root.findtext('.//header/resultMsg')}")

    items = [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.iterfind(".//items/item")
    ]
    total = int(_num(root.findtext(".//body/totalCount")) or 0)
    return items, total


class RtmsClient:
    def __init__(self, service_key: str, db_path: Path = DB_PATH, session: requests.Session | None = None):
        # 포털의 Encoding 키를 붙여넣어도 동작하도록 한 번 디코딩한다.
        self.service_key = unquote(service_key.strip())
        self.session = session or requests.Session()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS cache (kind TEXT, lawd_cd TEXT, ym TEXT, items TEXT, "
            "fetched_at TEXT, PRIMARY KEY (kind, lawd_cd, ym))"
        )

    def _fetch_month(self, kind: str, lawd_cd: str, ym: str) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            params = {
                "serviceKey": self.service_key,
                "LAWD_CD": lawd_cd,
                "DEAL_YMD": ym,
                "pageNo": page,
                "numOfRows": 1000,
            }
            for attempt in range(3):
                try:
                    resp = self.session.get(ENDPOINTS[kind], params=params, timeout=20)
                    resp.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise
                    time.sleep(1.5 * (attempt + 1))
            page_items, total = parse_response(resp.text)
            items.extend(page_items)
            if len(items) >= total or not page_items:
                return items
            page += 1

    def get_month(self, kind: str, lawd_cd: str, ym: str, recent: set[str]) -> list[dict]:
        if ym not in recent:
            row = self.db.execute(
                "SELECT items FROM cache WHERE kind=? AND lawd_cd=? AND ym=?", (kind, lawd_cd, ym)
            ).fetchone()
            if row:
                return json.loads(row[0])
        items = self._fetch_month(kind, lawd_cd, ym)
        self.db.execute(
            "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, datetime('now'))",
            (kind, lawd_cd, ym, json.dumps(items, ensure_ascii=False)),
        )
        self.db.commit()
        return items

    def collect(self, kind: str, lawd_cd: str, months: int, progress=None) -> list[dict]:
        yms = month_range(months)
        recent = set(yms[-REFRESH_RECENT_MONTHS:])
        out: list[dict] = []
        for i, ym in enumerate(yms):
            out.extend(self.get_month(kind, lawd_cd, ym, recent))
            if progress:
                progress((i + 1) / len(yms), f"{kind} {ym[:4]}.{ym[4:]}")
        return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def matches(item: dict, cx: Complex) -> bool:
    if cx.umd and _norm(item.get("umdNm")) != _norm(cx.umd):
        return False
    name = _norm(item.get("aptNm"))
    return any(_norm(k) in name for k in cx.keywords)


def to_frame(kind: str, items: list[dict]) -> pd.DataFrame:
    """API item 목록을 앱 공통 컬럼의 DataFrame으로 변환. 금액 단위는 만원."""
    rows = []
    for it in items:
        y, m, d = (int(_num(it.get(k)) or 0) for k in ("dealYear", "dealMonth", "dealDay"))
        if not y:
            continue
        row = {
            "kind": kind,
            "date": pd.Timestamp(y, m, max(d, 1)),
            "apt": it.get("aptNm", ""),
            "area": _num(it.get("excluUseAr")),
            "floor": int(_num(it.get("floor")) or 0),
            "dong": it.get("aptDong", ""),
            "cancelled": bool((it.get("cdealType") or "").strip()),
        }
        if kind == "전월세":
            row["price"] = _num(it.get("deposit"))
            row["monthly_rent"] = _num(it.get("monthlyRent")) or 0
            row["contract"] = it.get("contractType", "")
            # 월세가 0이면 전세, 아니면 월세. 보증금 기준으로만 비교한다.
            row["kind"] = "전세" if row["monthly_rent"] == 0 else "월세"
        else:
            row["price"] = _num(it.get("dealAmount"))
            row["monthly_rent"] = 0
            row["contract"] = it.get("dealingGbn", "")
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=["kind", "date", "apt", "area", "floor", "dong", "cancelled", "price", "monthly_rent", "contract"]
        )
    return df


def collect_complex(client: RtmsClient, cx: Complex, months: int, kinds=("매매", "전월세", "분양권"), progress=None) -> pd.DataFrame:
    frames = []
    for kind in kinds:
        items = client.collect(kind, cx.lawd_cd, months, progress)
        frames.append(to_frame(kind, [it for it in items if matches(it, cx)]))
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values("date").reset_index(drop=True)


def area_type(area: float) -> str:
    """전용면적을 흔히 쓰는 타입 라벨(예: 84.97 → 84㎡)로 묶는다."""
    return f"{int(area)}㎡" if area == area else "-"
