"""관심 아파트 실거래가 대시보드 (Streamlit MVP)."""
from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rtms import ApiError, RtmsClient, area_type, collect_complex, load_complexes
from sample_data import make_sample

st.set_page_config(page_title="내 아파트 실거래가", layout="wide")

# 시리즈 색: 거래 종류별로 고정 (dataviz 기본 팔레트 1~3번 슬롯)
COLORS = {
    "light": {"매매": "#2a78d6", "전세": "#eb6834", "분양권": "#1baf7a"},
    "dark": {"매매": "#3987e5", "전세": "#d95926", "분양권": "#199e70"},
}
CHART_KINDS = ["매매", "전세", "분양권"]
PYEONG = 3.305785


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


def fmt_won(manwon: float | None) -> str:
    """만원 단위 금액을 '8억 5,000' 형식으로."""
    if manwon is None or pd.isna(manwon):
        return "-"
    manwon = int(round(manwon))
    eok, rest = divmod(manwon, 10000)
    if eok and rest:
        return f"{eok}억 {rest:,}"
    if eok:
        return f"{eok}억"
    return f"{rest:,}만"


def get_service_key() -> str:
    try:
        key = st.secrets.get("RTMS_SERVICE_KEY", "")
    except Exception:
        key = ""
    return key or os.environ.get("RTMS_SERVICE_KEY", "")


@st.cache_resource
def get_client(key: str) -> RtmsClient:
    return RtmsClient(key)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def load_data(key: str, complex_id: str, months: int, use_sample: bool) -> pd.DataFrame:
    cx = next(c for c in load_complexes() if c.id == complex_id)
    if use_sample:
        return make_sample(cx, months)
    bar = st.progress(0.0, text=f"{cx.name} 실거래 데이터를 받는 중")
    try:
        df = collect_complex(get_client(key), cx, months, progress=lambda p, t: bar.progress(p, text=t))
    finally:
        bar.empty()
    return df


# ---------- 사이드바 ----------
complexes = load_complexes()
with st.sidebar:
    st.header("설정")
    key = get_service_key()
    if not key:
        key = st.text_input("공공데이터포털 인증키", type="password", help="Decoding 키를 붙여넣으세요. .streamlit/secrets.toml에 저장해 두면 매번 입력하지 않아도 됩니다.")
    use_sample = not key
    years = st.slider("조회 기간(년)", 1, 10, 10)
    exclude_cancelled = st.checkbox("해제된 거래 제외", value=True)
    if st.button("데이터 새로고침", width="stretch", disabled=use_sample):
        load_data.clear()
    st.caption("처음 조회할 때는 10년치를 받느라 1~2분 걸립니다. 이후에는 캐시에서 바로 열리고 최근 3개월만 다시 받습니다.")

if use_sample:
    st.warning("인증키가 없어 **샘플 데이터(실제 거래 아님)** 로 화면을 보여주고 있습니다. 사이드바에 인증키를 입력하면 실제 실거래가로 바뀝니다.")

tab_detail, tab_compare = st.tabs(["단지 상세", "단지 비교"])
mode = theme_mode()
palette = COLORS[mode]


def load(cx_id: str) -> pd.DataFrame | None:
    try:
        df = load_data(key, cx_id, years * 12, use_sample)
    except ApiError as e:
        st.error(f"실거래가 API 오류: {e}")
        return None
    except Exception as e:  # 네트워크 오류 등
        st.error(f"데이터를 불러오지 못했습니다: {e}")
        return None
    if exclude_cancelled and not df.empty:
        df = df[~df["cancelled"]]
    df = df.copy()
    df["type"] = df["area"].map(area_type)
    return df


def kpi_block(df: pd.DataFrame):
    sale = df[df["kind"] == "매매"]
    jeonse = df[df["kind"] == "전세"]
    c1, c2, c3, c4 = st.columns(4)
    if sale.empty:
        c1.metric("최근 매매가", "-")
    else:
        last = sale.iloc[-1]
        c1.metric("최근 매매가", fmt_won(last["price"]), help=None)
        c1.caption(f"{last['date']:%Y.%m.%d} · {last['floor']}층")

        peak = sale.loc[sale["price"].idxmax()]
        drop = (last["price"] / peak["price"] - 1) * 100
        c2.metric("최고가", fmt_won(peak["price"]))
        c2.caption(f"{peak['date']:%Y.%m.%d} · 최근가는 최고가 대비 {drop:+.1f}%")

        now = sale["date"].max()
        recent = sale[sale["date"] > now - pd.DateOffset(months=6)]["price"].median()
        year_ago = sale[(sale["date"] > now - pd.DateOffset(months=18)) & (sale["date"] <= now - pd.DateOffset(months=12))]["price"].median()
        if pd.notna(year_ago) and year_ago:
            c3.metric("1년 변동", fmt_won(recent), f"{(recent / year_ago - 1) * 100:+.1f}%")
            c3.caption("최근 6개월 중앙값, 1년 전 같은 기간과 비교")
        else:
            c3.metric("1년 변동", "-")
            c3.caption("비교할 1년 전 거래가 없습니다")

        if not jeonse.empty:
            jnow = jeonse[jeonse["date"] > now - pd.DateOffset(months=6)]["price"].median()
            if pd.notna(jnow) and recent:
                c4.metric("전세가율", f"{jnow / recent * 100:.0f}%")
                c4.caption(f"최근 6개월 전세 중앙값 {fmt_won(jnow)}")
                return
        c4.metric("전세가율", "-")


def price_chart(df: pd.DataFrame, kinds: list[str]):
    fig = go.Figure()
    for kind in kinds:
        part = df[df["kind"] == kind]
        if part.empty:
            continue
        color = palette[kind]
        fig.add_trace(go.Scattergl(
            x=part["date"], y=part["price"] / 10000, mode="markers", name=f"{kind} 개별 거래",
            legendgroup=kind, showlegend=False,
            marker=dict(size=8, color=color, opacity=0.5 if mode == "dark" else 0.35, line=dict(width=0)),
            customdata=list(zip(part["price"].map(fmt_won), part["area"], part["floor"])),
            hovertemplate=f"<b>{kind}</b> %{{x|%Y.%m.%d}}<br>%{{customdata[0]}}<br>전용 %{{customdata[1]}}㎡ · %{{customdata[2]}}층<extra></extra>",
        ))
        # 거래가 드문 달의 튐을 줄이려고 월 중앙값을 3개월 이동 중앙값으로 다듬는다.
        monthly = part.set_index("date")["price"].resample("MS").median().dropna().rolling(3, min_periods=1).median()
        fig.add_trace(go.Scatter(
            x=monthly.index, y=monthly / 10000, mode="lines", name=kind, legendgroup=kind,
            line=dict(color=color, width=2), connectgaps=True,
            hovertemplate=f"<b>{kind}</b> 추세 %{{x|%Y.%m}}<br>%{{y:.2f}}억<extra></extra>",
        ))
    fig.update_layout(
        height=440, margin=dict(l=8, r=8, t=8, b=8), hovermode="closest",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis=dict(ticksuffix="억", gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, width="stretch", theme="streamlit")
    st.caption("점은 개별 거래, 선은 월별 중앙값의 3개월 이동 중앙값입니다. 전세는 보증금 기준이며 월세 거래는 표에서만 보입니다.")


def trade_table(df: pd.DataFrame):
    show = df.sort_values("date", ascending=False).copy()
    show["거래일"] = show["date"].dt.strftime("%Y.%m.%d")
    show["금액"] = show["price"].map(fmt_won)
    show["월세"] = show["monthly_rent"].map(lambda v: f"{int(v):,}만" if v else "")
    show["평당가"] = (show["price"] / (show["area"] / PYEONG)).map(lambda v: f"{v:,.0f}만")
    show["해제"] = show["cancelled"].map(lambda v: "해제" if v else "")
    st.dataframe(
        show[["거래일", "kind", "type", "area", "floor", "금액", "월세", "평당가", "contract", "해제"]].rename(
            columns={"kind": "구분", "type": "타입", "area": "전용㎡", "floor": "층", "contract": "비고"}
        ),
        width="stretch", hide_index=True, height=380,
    )


with tab_detail:
    names = {c.id: c.name for c in complexes}
    cx_id = st.segmented_control("단지", options=list(names), format_func=names.get, default=complexes[0].id, label_visibility="collapsed")
    cx = next(c for c in complexes if c.id == (cx_id or complexes[0].id))

    head, link = st.columns([3, 1], vertical_alignment="bottom")
    head.subheader(cx.name)
    head.caption(f"{cx.region} · 사용승인 {cx.completed}" if cx.completed else cx.region)
    link.link_button("네이버 부동산 호가 보기", cx.naver_url, width="stretch", type="primary")

    df = load(cx.id)
    if df is not None:
        if df.empty:
            st.info("조회 기간 안에 이 단지로 확인된 거래가 없습니다. complexes.json의 keywords와 umd(법정동)가 실거래 데이터의 단지명과 맞는지 확인하세요.")
        else:
            f1, f2 = st.columns([2, 1])
            types = sorted(df["type"].unique(), key=lambda s: float(s.rstrip("㎡")))
            # 면적이 섞이면 가격 추세가 흐려지므로 거래가 가장 많은 타입 하나로 시작한다.
            main_type = df.loc[df["kind"] != "월세", "type"].mode().iloc[0]
            pick_types = f1.pills("전용면적", types, selection_mode="multi", default=[main_type], key=f"types-{cx.id}")
            pick_kinds = f2.pills("구분", CHART_KINDS, selection_mode="multi", key=f"kinds-{cx.id}", default=[k for k in CHART_KINDS if k in set(df["kind"])])
            view = df[df["type"].isin(pick_types or types)]
            kpi_block(view)
            price_chart(view, pick_kinds or CHART_KINDS)
            with st.expander(f"거래 내역 {len(view):,}건", expanded=False):
                trade_table(view)

with tab_compare:
    st.caption("면적이 다른 단지를 비교하기 위해 3.3㎡(평)당 매매가의 월별 중앙값(3개월 이동)으로 비교합니다.")
    fig = go.Figure()
    order = [palette["매매"], palette["전세"]]  # 단지 2개까지 슬롯 1, 2
    summary = []
    for i, c in enumerate(complexes):
        d = load(c.id)
        if d is None:
            continue
        sale = d[d["kind"].isin(["매매", "분양권"])]
        if sale.empty:
            continue
        ppp = (sale["price"] / (sale["area"] / PYEONG)).groupby(sale["date"].dt.to_period("M")).median()
        ppp.index = ppp.index.to_timestamp()
        ppp = ppp.rolling(3, min_periods=1).median()
        color = order[i % len(order)]
        fig.add_trace(go.Scatter(
            x=ppp.index, y=ppp.values, mode="lines", name=c.name, line=dict(color=color, width=2),
            hovertemplate=f"<b>{c.name}</b> %{{x|%Y.%m}}<br>평당 %{{y:,.0f}}만<extra></extra>",
        ))
        summary.append({"단지": c.name, "최근 6개월 평당가(중앙값)": f"{ppp.tail(6).median():,.0f}만", "최고 월 평당가": f"{ppp.max():,.0f}만", "거래 건수": len(sale)})
    fig.update_layout(
        height=420, margin=dict(l=8, r=8, t=8, b=8), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis=dict(ticksuffix="만", gridcolor="rgba(128,128,128,0.15)", zeroline=False),
        xaxis=dict(showgrid=False),
    )
    st.plotly_chart(fig, width="stretch", theme="streamlit")
    if summary:
        st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    st.caption("준공 전 구간은 분양권 거래, 이후는 매매 거래입니다.")
