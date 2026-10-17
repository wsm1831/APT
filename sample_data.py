"""API 키 없이 화면을 확인하기 위한 합성 데이터. 실제 거래가 아니다."""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from rtms import Complex

# 단지별 합성 파라미터: (전용면적 목록, 84㎡ 기준 시작가(만원))
_PROFILE = {
    "ian-central-d": ([59.98, 84.97, 101.9], 52000),
    "thesharp-libiter-2": ([84.93, 104.8, 126.28], 61000),
}


def make_sample(cx: Complex, months: int = 120, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(zlib.crc32(cx.id.encode()) + seed)
    areas, base = _PROFILE.get(cx.id, ([84.9], 50000))
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(months=months)
    completed = pd.Timestamp(cx.completed + "-01") if cx.completed else start

    days = pd.date_range(start, end, freq="D")
    t = np.linspace(0, 1, len(days))
    # 상승 후 조정되는 완만한 추세
    trend = 1 + 0.35 * np.sin(np.pi * np.clip(t * 1.4, 0, 1)) - 0.12 * t

    rows = []
    for i, day in enumerate(days):
        for kind, p in (("매매", 0.035), ("분양권", 0.05), ("전세", 0.03)):
            if kind == "분양권" and day >= completed:
                continue
            if kind != "분양권" and day < completed:
                continue
            if rng.random() > p:
                continue
            area = rng.choice(areas)
            level = base * trend[i] * (area / 84.9) ** 0.9
            if kind == "분양권":
                level *= 0.82
            if kind == "전세":
                level *= 0.58
            rows.append({
                "kind": kind,
                "date": day,
                "apt": cx.name,
                "area": float(area),
                "floor": int(rng.integers(2, 26)),
                "dong": "",
                "cancelled": bool(rng.random() < 0.03),
                "price": float(round(level * rng.normal(1, 0.04), -2)),
                "monthly_rent": 0.0,
                "contract": "",
            })
    return pd.DataFrame(rows)
