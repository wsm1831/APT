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
              compare=[{"name": "동대구역센트럴시티자이", "lawd_cd": "27140", "umd": "신천동", "keywords": ["센트럴시티자이"]},
                       {"name": "교대역푸르지오트레힐즈", "lawd_cd": "27200", "umd": "이천동", "keywords": ["교대역푸르지오"]}])


def test_row_of_filters_area_and_wolse():
    assert row_of("매매", item("A", "신암동", "70,000")) == ["2026-08-08", "매매", 70000, 10, 84.97, False]
    assert row_of("매매", item("A", "신암동", "50,000", area="59.9")) is None
    rent = {"aptNm": "A", "umdNm": "신암동", "deposit": "40,000", "monthlyRent": "0", "dealYear": "2026",
            "dealMonth": "9", "dealDay": "1", "excluUseAr": "84.9", "floor": "3"}
    assert row_of("전월세", rent)[1:3] == ["전세", 40000]
    assert row_of("전월세", {**rent, "monthlyRent": "100"}) is None


def test_build_uses_compare_list():
    sale = [item("이안센트럴D", "신암동", "76,000")]
    sale += [item("동대구역센트럴시티자이", "신천동", "70,000", ym=(2026, 9, d)) for d in (1, 2, 3)]
    sale += [item("지정안한단지", "신천동", "50,000")]
    data = build(FakeClient({
        ("27140", "매매"): sale,
        ("27200", "매매"): [item("교대역 푸르지오 트레힐즈", "이천동", "80,000")],
    }), [OWN], 60)
    members = data["groups"][0]["complexes"]
    assert [c["name"] for c in members] == ["이안센트럴D", "동대구역센트럴시티자이", "교대역푸르지오트레힐즈"]
    assert [len(data["trades"][c["key"]]) for c in members] == [1, 3, 1]


def test_diff_new_ignores_newly_added_complex():
    old = build(FakeClient({("27140", "매매"): [item("이안센트럴D", "신암동", "76,000")]}), [OWN], 60)
    del old["trades"][old["groups"][0]["complexes"][1]["key"]]
    new = build(FakeClient({("27140", "매매"): [
        item("이안센트럴D", "신암동", "76,000"), item("동대구역센트럴시티자이", "신천동", "70,000")]}), [OWN], 60)
    assert diff_new(old, new) == []


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


def test_build_skips_rent_when_forbidden():
    import requests

    class Partial(FakeClient):
        def collect(self, kind, lawd, months):
            if kind == "전월세":
                raise requests.HTTPError("403 Client Error: Forbidden")
            return super().collect(kind, lawd, months)

    data = build(Partial({("27140", "매매"): [item("이안센트럴D", "신암동", "76,000")]}), [OWN], 60)
    assert data["missing"] == ["전세"] and len(data["trades"]["own-ian"]) == 1
