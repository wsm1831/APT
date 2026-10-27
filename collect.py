"""기준 단지와 비교 단지의 전용 84㎡ 실거래(매매, 전세)를 모아 대시보드용 JSON으로 저장한다.

GitHub Actions에서 매일 실행된다. 인증키는 환경변수 DATA_GO_KR_KEY(또는 RTMS_SERVICE_KEY).

    python collect.py                 # docs/data/market.json 갱신, 새 거래는 data/new_trades.md에 기록
    python collect.py --months 24     # 수집 기간 조정
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from rtms import ApiError, Complex, RtmsClient, _norm, _num, load_complexes, matches

ROOT = Path(__file__).parent
OUT = ROOT / "docs" / "data" / "market.json"
ALERT = ROOT / "data" / "new_trades.md"
KST = timezone(timedelta(hours=9))

# 실거래 자료의 전용면적은 84.97, 84.357처럼 들어오므로 범위로 '84㎡ 타입'을 정한다.
AREA_MIN, AREA_MAX = 83.0, 86.0


def row_of(kind: str, it: dict) -> list | None:
    """API item → [계약일, 구분, 금액(만원), 층, 전용면적, 해제여부, 동, 등기일, 직거래여부].

    84㎡ 매매/전세가 아니면 None. 동·등기일은 매매에만 있고, 등기일은 등기 후에야 채워진다."""
    area = _num(it.get("excluUseAr"))
    if area is None or not AREA_MIN <= area < AREA_MAX:
        return None
    if kind == "전월세":
        if (_num(it.get("monthlyRent")) or 0) > 0:
            return None
        kind, price = "전세", _num(it.get("deposit"))
    else:
        price = _num(it.get("dealAmount"))
    y, m, d = (int(_num(it.get(k)) or 0) for k in ("dealYear", "dealMonth", "dealDay"))
    if not (y and price):
        return None
    return [f"{y}-{m:02d}-{max(d, 1):02d}", kind, int(price), int(_num(it.get("floor")) or 0), area,
            bool((it.get("cdealType") or "").strip()), (it.get("aptDong") or "").strip(),
            rgst_date(it.get("rgstDate")), (it.get("dealingGbn") or "").strip() == "직거래"]


def rgst_date(text: str | None) -> str:
    """API 등기일자('24.05.20')를 '2024-05-20'으로. 없으면 빈 문자열."""
    m = re.fullmatch(r"(\d{2})\.(\d{1,2})\.(\d{1,2})", (text or "").strip())
    return f"20{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else ""


def complex_key(lawd_cd: str, umd: str, apt: str) -> str:
    return f"{lawd_cd}-{_norm(umd)}-{_norm(apt)}"


def build(client: RtmsClient, owned: list[Complex], months: int) -> dict:
    items: dict[tuple[str, str], list[dict]] = {}
    missing: set[str] = set()
    for lawd in sorted({cx.lawd_cd for cx in owned} | {c["lawd_cd"] for cx in owned for c in cx.compare}):
        for kind in ("매매", "전월세"):
            print(f"수집: {lawd} {kind} {months}개월", flush=True)
            try:
                items[(lawd, kind)] = client.collect(kind, lawd, months)
            except (ApiError, requests.HTTPError) as e:
                # 전월세 API는 활용신청을 따로 해야 한다. 없으면 매매만이라도 수집한다.
                if kind == "매매":
                    raise
                print(f"경고: {kind} 수집 실패, 건너뜀 ({e})", file=sys.stderr, flush=True)
                missing.add("전세")

    groups, trades = [], {}
    for cx in owned:
        targets = [(f"own-{cx.id}", cx, True)] + [
            (complex_key(c["lawd_cd"], c["umd"], c["name"]),
             Complex(id=c["name"], name=c["name"], region="", lawd_cd=c["lawd_cd"], umd=c["umd"], keywords=c["keywords"]),
             False)
            for c in cx.compare
        ]
        members = []
        for key, t, own in targets:
            rows = [
                row for (lawd, kind), its in items.items() if lawd == t.lawd_cd
                for it in its if matches(it, t) and (row := row_of(kind, it)) is not None
            ]
            if not rows:
                # 단지명이 실거래 자료와 다르게 적혀 있을 때 고칠 수 있도록 같은 동의 단지명을 남긴다.
                names = sorted({it.get("aptNm", "") for (lawd, _), its in items.items() if lawd == t.lawd_cd
                                for it in its if _norm(it.get("umdNm")) == _norm(t.umd)})
                print(f"경고: {t.name}({t.umd}) 84㎡ 거래 없음. 같은 동 단지명: {', '.join(names)}", file=sys.stderr)
            members.append({"key": key, "name": t.name, "umd": t.umd, "own": own})
            trades[key] = sorted(rows)
        groups.append({
            "id": cx.id, "name": cx.name, "region": cx.region, "completed": cx.completed,
            "naver_url": cx.naver_url, "complexes": members,
        })
    return {"groups": groups, "trades": trades, "missing": sorted(missing)}


def diff_new(old: dict, new: dict) -> list[dict]:
    """이전 실행에 없던 거래(해제 신고 포함)를 찾는다."""
    if not old.get("trades"):
        return []  # 첫 실행이면 전부 새 거래라 알림하지 않는다
    names = {c["key"]: c["name"] for g in new["groups"] for c in g["complexes"]}
    own = {c["key"] for g in new["groups"] for c in g["complexes"] if c["own"]}
    # 이전 실행에서 못 받은 구분(예: 전월세 API 신청 전의 전세)은 과거 거래 전체가 새로 들어오므로 알림하지 않는다
    skip_kinds = set(old.get("missing", [])) - set(new.get("missing", []))
    out = []
    for key, rows in new["trades"].items():
        if key not in old["trades"]:
            continue  # 비교 단지를 새로 추가했을 때 과거 거래 전체를 알림하지 않는다
        # 등기일은 나중에 채워지므로 앞 6개 항목(계약일~해제여부)만으로 같은 거래인지 본다
        seen = Counter(tuple(r[:6]) for r in old["trades"].get(key, []))
        for r in rows:
            if r[1] in skip_kinds:
                continue
            t = tuple(r[:6])
            if seen[t]:
                seen[t] -= 1
                continue
            out.append({"key": key, "name": names[key], "own": key in own, "date": r[0], "kind": r[1],
                        "price": r[2], "floor": r[3], "area": r[4], "cancelled": r[5]})
    return sorted(out, key=lambda e: (not e["own"], e["name"], e["date"]))


def fmt_won(manwon: int) -> str:
    eok, rest = divmod(int(manwon), 10000)
    return f"{eok}억 {rest:,}" if eok and rest else f"{eok}억" if eok else f"{rest:,}만"


def alert_markdown(events: list[dict], dashboard_url: str) -> str:
    lines = [f"새로 신고된 84㎡ 실거래 {len(events)}건입니다.", ""]
    lines += ["| 단지 | 구분 | 거래일 | 금액 | 층 | 비고 |", "|---|---|---|---|---|---|"]
    for e in events:
        name = f"**{e['name']}**" if e["own"] else e["name"]
        lines.append(f"| {name} | {e['kind']} | {e['date']} | {fmt_won(e['price'])} | {e['floor']} | {'해제' if e['cancelled'] else ''} |")
    if dashboard_url:
        lines += ["", f"대시보드: {dashboard_url}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=60)
    args = ap.parse_args()

    key = os.environ.get("DATA_GO_KR_KEY") or os.environ.get("RTMS_SERVICE_KEY")
    if not key:
        print("인증키가 없습니다. 환경변수 DATA_GO_KR_KEY를 설정하세요.", file=sys.stderr)
        return 2

    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    try:
        data = build(RtmsClient(key), load_complexes(), args.months)
    except (ApiError, requests.HTTPError) as e:
        print(f"실거래가 API 오류: {e}", file=sys.stderr)
        return 1

    events = diff_new(old, data)
    # 최근 변화 목록은 대시보드에도 보여 준다. 오래된 것은 100건까지만 남긴다.
    found = datetime.now(KST).strftime("%Y-%m-%d")
    history = [{**e, "found": found} for e in events] + old.get("events", [])
    data = {"updated": datetime.now(KST).isoformat(timespec="minutes"), **data, "events": history[:100]}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    ALERT.unlink(missing_ok=True)
    if events:
        ALERT.parent.mkdir(parents=True, exist_ok=True)
        ALERT.write_text(alert_markdown(events, os.environ.get("DASHBOARD_URL", "")), encoding="utf-8")

    for g in data["groups"]:
        print(f"[{g['name']}] " + ", ".join(f"{c['name']}({len(data['trades'][c['key']])})" for c in g["complexes"]))
    print(f"새 거래 {len(events)}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
