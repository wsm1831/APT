from collect import build, diff_new, row_of
from rtms import Complex


def item(apt, umd, amount, ym=(2026, 8, 8), area="84.97", floor="10", cancel=""):
    y, m, d = ym
    return {"aptNm": apt, "umdNm": umd, "dealAmount": amount, "dealYear": str(y), "dealMonth": str(m),
            "dealDay": str(d), "excluUseAr": area, "floor": floor, "cdealType": cancel}


class FakeClient:
    def __init__(self, data):
        self.data = data

    def collect(self, kind, lawd, months):
        return self.data.get((lawd, kind), [])


OWN = Complex("ian", "이안센트럴D", "대구 동구 신암동", "27140", "신암동", ["이안센트럴"],
              nearby=[{"lawd_cd": "27140", "umd": "신천동"}])


def test_row_of_filters_area_and_wolse():
    assert row_of("매매", item("A", "신암동", "70,000")) == ["2026-08-08", "매매", 70000, 10, 84.97, False]
    assert row_of("매매", item("A", "신암동", "50,000", area="59.9")) is None
    rent = {"aptNm": "A", "umdNm": "신암동", "deposit": "40,000", "monthlyRent": "0", "dealYear": "2026",
            "dealMonth": "9", "dealDay": "1", "excluUseAr": "84.9", "floor": "3"}
    assert row_of("전월세", rent)[1:3] == ["전세", 40000]
    assert row_of("전월세", {**rent, "monthlyRent": "100"}) is None


def test_build_groups_neighbors():
    sale = [item("이안센트럴D", "신암동", "76,000")]
    sale += [item("센트럴시티자이", "신천동", "70,000", ym=(2026, 9, d)) for d in (1, 2, 3)]
    sale += [item("드문단지", "신천동", "50,000")]                      # 거래 3건 미만 → 제외
    sale += [item("다른동단지", "효목동", "60,000", ym=(2026, 9, d)) for d in (1, 2, 3)]  # 인근 동 아님
    data = build(FakeClient({("27140", "매매"): sale}), [OWN], 60)
    names = [c["name"] for c in data["groups"][0]["complexes"]]
    assert names == ["이안센트럴D", "센트럴시티자이"]
    assert data["trades"]["own-ian"][0][2] == 76000


def test_diff_new_detects_added_and_cancelled():
    old = build(FakeClient({("27140", "매매"): [item("이안센트럴D", "신암동", "76,000")]}), [OWN], 60)
    assert diff_new({}, old) == []
    new = build(FakeClient({("27140", "매매"): [
        item("이안센트럴D", "신암동", "76,000", cancel="O"),
        item("이안센트럴D", "신암동", "77,000", ym=(2026, 10, 1)),
    ]}), [OWN], 60)
    ev = diff_new(old, new)
    assert [(e["price"], e["cancelled"]) for e in ev] == [(76000, True), (77000, False)]
    assert all(e["own"] for e in ev)
