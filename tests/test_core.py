import json
from datetime import date
from pathlib import Path

import pytest

from recall_watch.gtin import check_digit, extract, is_valid, item_from_case, normalize
from recall_watch.match import find_matches
from recall_watch.products import ProductError, brand_from_name, load_products
from recall_watch.sources import Recall, load_recorded, parse_enforcement, parse_press_rss
from recall_watch.state import load_state, mark, save_state

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def ean(body):
    return body + str(check_digit(body))


# --- barcodes -------------------------------------------------------------------------

def test_check_digit_and_validity():
    assert is_valid("012345678905") and is_valid("4006381333931") and is_valid("96385074")
    assert not is_valid("012345678900") and not is_valid("12345")


def test_normalize():
    assert normalize("0 12345 67890 5") == "00012345678905"
    assert normalize("4006381333931.0") == "04006381333931"
    assert normalize("012345678900") is None


def test_extract_handles_spacing_and_rejects_lot_numbers():
    text = "Cheese pie UPC 0 12345 67890 5, lot 8699999000999, call 1-800-555-0100, UPC 4006381333931"
    assert extract(text) == ["00012345678905", "04006381333931"]


def test_extract_trailing_and_leading_groups():
    # a valid code followed or preceded by an unrelated digit group
    assert extract("UPC 012345678905 1234") == ["00012345678905"]
    assert extract("lot 77 012345678905") == ["00012345678905"]


def test_item_from_case():
    unit = ean("869999900001")
    case = ean("1" + unit[:12])
    assert item_from_case(case) == unit.zfill(14)
    assert item_from_case(unit.zfill(14)) is None  # indicator 0


# --- products -------------------------------------------------------------------------

def test_brand_from_name():
    assert brand_from_name("Golden Hive, Blossom Honey, 350 g") == "Golden Hive"
    assert brand_from_name("Plain Grape Molasses 700 g") == ""


def test_load_example_products():
    products = load_products(EXAMPLES / "products.csv")
    assert len(products) == 6
    honey = products[0]
    assert honey.brand == "Golden Hive" and honey.sku == "DM-001"
    assert len(honey.gtins) == 2  # unit + case (whose item equals the unit, deduplicated)


def test_odoo_style_export(tmp_path):
    unit = ean("869999900009")
    path = tmp_path / "odoo.csv"
    path.write_text(
        "Product,Internal Reference,Barcode,Box Barcode,Brand\n"
        f'"[X1] Bahar Gida, Lentils, 1 kg",X1,{unit},{ean("1" + unit[:12])} (Units),\n'
        f"[X2] Something,X2,not-a-code,,Acme Foods\n",
        encoding="utf-8",
    )
    a, b = load_products(path)
    assert a.name == "Bahar Gida, Lentils, 1 kg" and a.brand == "Bahar Gida"
    assert unit.zfill(14) in a.gtins and len(a.gtins) == 2  # note "(Units)" after the box code is ignored
    assert b.gtins == [] and b.brand == "Acme Foods"


def test_turkish_semicolon_csv(tmp_path):
    path = tmp_path / "urunler.csv"
    path.write_bytes("Ürün Adı;Marka;Barkod\nSüzme Bal;Çiçek;{}\n".format(ean("869999900005")).encode("cp1254"))
    [p] = load_products(path)
    assert p.brand == "Çiçek" and p.gtins


def test_product_errors(tmp_path):
    with pytest.raises(ProductError):
        load_products(tmp_path / "missing.csv")
    bad = tmp_path / "bad.csv"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(ProductError, match="need at least"):
        load_products(bad)


# --- sources --------------------------------------------------------------------------

def test_parse_enforcement_example():
    recalls = load_recorded(EXAMPLES / "enforcement.json")
    assert [r.id for r in recalls][:2] == ["H-0901-2027", "H-0902-2027"]
    r = recalls[0]
    assert r.date == "2026-10-21" and r.extra["initiated"] == "2026-09-29"
    assert r.classification == "Class I" and "recall_number" in r.url
    assert "Lot SC-0424" in r.text  # code_info is searched too


def test_parse_enforcement_skips_records_without_number():
    assert parse_enforcement({"results": [{"product_description": "x"}]}) == []


def test_parse_press_rss_example():
    recalls = load_recorded(EXAMPLES / "press.xml")
    assert len(recalls) == 4
    r = recalls[0]
    assert r.source == "fda-press" and r.date == "2026-10-22"
    assert r.id == "bahar-imports-recalls-anatolia-pantry-red-lentils"
    assert r.url.startswith("https://www.fda.gov/")


def test_parse_press_rss_rejects_garbage():
    from recall_watch.sources import SourceError

    with pytest.raises(SourceError):
        parse_press_rss(b"<not xml")


# --- matching -------------------------------------------------------------------------

@pytest.fixture
def example_matches():
    products = load_products(EXAMPLES / "products.csv")
    recalls = load_recorded(EXAMPLES / "enforcement.json") + load_recorded(EXAMPLES / "press.xml")
    return {m.recall.id: m for m in find_matches(recalls, products)}


def test_barcode_matches(example_matches):
    cheese = example_matches["H-0901-2027"]
    assert cheese.level == "barcode" and [p.sku for p in cheese.products] == ["DM-002"]
    honey = example_matches["H-0902-2027"]  # matched through the case GTIN-14
    assert honey.level == "barcode" and honey.products[0].sku == "DM-001"


def test_brand_match_puts_named_product_first(example_matches):
    lentils = example_matches["H-0903-2027"]
    assert lentils.level == "brand"
    assert [p.sku for p in lentils.products] == ["DM-003", "DM-004"]
    assert any("product named" in e for e in lentils.evidence)


def test_no_false_positives(example_matches):
    assert "H-0904-2027" not in example_matches  # valid UPC not ours, invalid lot number
    assert "H-0905-2027" not in example_matches
    assert "sample-pharmacy-recalls-compounded-eye-drops" not in example_matches


def test_ignore_brand_and_short_brands():
    products = load_products(EXAMPLES / "products.csv")
    recalls = load_recorded(EXAMPLES / "press.xml")
    ids = {m.recall.id for m in find_matches(recalls, products)}
    assert "classic-car-wax-spray-recalled" in ids  # common word: a known false positive
    ids = {m.recall.id for m in find_matches(recalls, products, ignore_brands=["classic"])}
    assert "classic-car-wax-spray-recalled" not in ids


def test_brand_needs_whole_words():
    from recall_watch.products import Product

    p = Product(row=2, name="Hive", brand="Hive")
    r = Recall(source="t", id="1", title="", date="", url="", text="Beehive products recalled")
    assert find_matches([r], [p]) == []
    r.text = "Hive products recalled"
    assert len(find_matches([r], [p])) == 1


def test_barcode_matches_sort_first(example_matches):
    products = load_products(EXAMPLES / "products.csv")
    recalls = load_recorded(EXAMPLES / "press.xml") + load_recorded(EXAMPLES / "enforcement.json")
    levels = [m.level for m in find_matches(recalls, products)]
    assert levels == sorted(levels, key=lambda lv: lv != "barcode")


# --- state ----------------------------------------------------------------------------

def test_state_round_trip_and_expiry(tmp_path):
    path = tmp_path / "s" / "seen.json"
    assert load_state(path) == {}
    seen = {"fda-press:old": "2024-01-01"}
    mark(seen, ["fda-enforcement:H-1"], today=date(2026, 10, 23))
    save_state(path, seen, today=date(2026, 10, 23))
    assert load_state(path) == {"fda-enforcement:H-1": "2026-10-23"}  # old entry dropped
    assert "product" not in path.read_text()  # only IDs and dates are stored
    path.write_text("not json")
    assert load_state(path) == {}
