from datetime import date

import pytest

from rtms import ApiError, Complex, matches, month_range, parse_response, to_frame

TRADE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
<body><items>
<item><aptNm>이안센트럴D</aptNm><umdNm>신암동</umdNm><dealAmount>  52,500</dealAmount><dealYear>2024</dealYear>
<dealMonth>3</dealMonth><dealDay>15</dealDay><excluUseAr>84.97</excluUseAr><floor>12</floor><cdealType> </cdealType></item>
<item><aptNm>더샵 리비테르 2차</aptNm><umdNm>대봉동</umdNm><dealAmount>61,000</dealAmount><dealYear>2024</dealYear>
<dealMonth>4</dealMonth><dealDay>2</dealDay><excluUseAr>84.93</excluUseAr><floor>7</floor><cdealType>O</cdealType></item>
<item><aptNm>더샵리비테르1차</aptNm><umdNm>대봉동</umdNm><dealAmount>58,000</dealAmount><dealYear>2024</dealYear>
<dealMonth>4</dealMonth><dealDay>9</dealDay><excluUseAr>84.9</excluUseAr><floor>3</floor></item>
</items><numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>3</totalCount></body></response>"""

RENT_XML = """<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header><body><items>
<item><aptNm>이안센트럴D</aptNm><umdNm>신암동</umdNm><deposit>30,000</deposit><monthlyRent>0</monthlyRent>
<dealYear>2024</dealYear><dealMonth>5</dealMonth><dealDay>1</dealDay><excluUseAr>84.97</excluUseAr><floor>5</floor><contractType>신규</contractType></item>
<item><aptNm>이안센트럴D</aptNm><umdNm>신암동</umdNm><deposit>5,000</deposit><monthlyRent>120</monthlyRent>
<dealYear>2024</dealYear><dealMonth>5</dealMonth><dealDay>3</dealDay><excluUseAr>59.98</excluUseAr><floor>9</floor></item>
</items><totalCount>2</totalCount></body></response>"""

IAN = Complex("ian", "이안센트럴D", "대구 동구 신암동", "27140", "신암동", ["이안센트럴"])
LIB2 = Complex("lib2", "더샵리비테르2차", "대구 중구 대봉동", "27110", "대봉동", ["리비테르2"])


def test_parse_and_match():
    items, total = parse_response(TRADE_XML)
    assert total == 3 and len(items) == 3
    assert [i["aptNm"] for i in items if matches(i, IAN)] == ["이안센트럴D"]
    # 띄어쓰기가 달라도 2차만 잡고 1차는 제외
    assert [i["aptNm"] for i in items if matches(i, LIB2)] == ["더샵 리비테르 2차"]


def test_to_frame_trade():
    items, _ = parse_response(TRADE_XML)
    df = to_frame("매매", items)
    assert df.loc[0, "price"] == 52500
    assert df.loc[0, "date"].strftime("%Y-%m-%d") == "2024-03-15"
    assert not df.loc[0, "cancelled"] and df.loc[1, "cancelled"]


def test_to_frame_rent_splits_jeonse_wolse():
    items, _ = parse_response(RENT_XML)
    df = to_frame("전월세", items)
    assert list(df["kind"]) == ["전세", "월세"]
    assert df.loc[1, "monthly_rent"] == 120


def test_auth_error():
    xml = "<OpenAPI_ServiceResponse><cmmMsgHeader><returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"
    with pytest.raises(ApiError, match="SERVICE_KEY"):
        parse_response(xml)


def test_month_range():
    assert month_range(3, date(2026, 2, 10)) == ["202512", "202601", "202602"]
    assert len(month_range(120, date(2026, 10, 1))) == 120
