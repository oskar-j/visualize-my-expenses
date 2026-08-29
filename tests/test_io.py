"""Reading each supported input format."""

from __future__ import annotations

import datetime as _dt
from decimal import Decimal

import pytest

from vme.io import FORMATS, LoaderError, detect_format, load
from vme.models import INCOME

OFX = """OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS>
<CURDEF>USD
<BANKTRANLIST>
<STMTTRN><TRNTYPE>DIRECTDEP<DTPOSTED>20260801120000<TRNAMT>4200.00<NAME>ACME PAYROLL<MEMO>Salary
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260802<TRNAMT>-1450.00<NAME>PROPERTY MGMT<MEMO>Rent
<STMTTRN><TRNTYPE>POS<DTPOSTED>20260803<TRNAMT>-86.42<NAME>WHOLE FOODS
</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""

QIF = """!Type:Bank
D08/01'26
T2500.00
PEmployer
LIncome:Payroll
^
D08/02'26
T-980.00
PLandlord
LHousing:Rent
^
"""

CAMT = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">
 <BkToCstmrStmt><Stmt>
  <Ntry><Amt Ccy="EUR">2400.00</Amt><CdtDbtInd>CRDT</CdtDbtInd>
   <BookgDt><Dt>2026-08-01</Dt></BookgDt>
   <NtryDtls><TxDtls><RltdPties><Dbtr><Nm>Acme GmbH</Nm></Dbtr></RltdPties></TxDtls></NtryDtls>
  </Ntry>
  <Ntry><Amt Ccy="EUR">890.00</Amt><CdtDbtInd>DBIT</CdtDbtInd>
   <BookgDt><Dt>2026-08-02</Dt></BookgDt>
   <BkTxCd><Prtry><Cd>Rent</Cd></Prtry></BkTxCd>
   <NtryDtls><TxDtls><RltdPties><Cdtr><Nm>Hausverwaltung</Nm></Cdtr></RltdPties></TxDtls></NtryDtls>
  </Ntry>
 </Stmt></BkToCstmrStmt>
</Document>
"""


def write(tmp_path, name, body):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return str(path)


class TestCsv:
    def test_reads_a_plain_file(self, csv_file):
        rows = load(str(csv_file))
        assert len(rows) == 4
        assert rows[0].label == "Salary" and rows[0].kind == INCOME
        assert rows[1].amount == Decimal("2000")

    def test_semicolons_and_a_bom(self, tmp_path):
        path = tmp_path / "pl.csv"
        path.write_text("kategoria;opis;kwota;waluta\n"
                        "Housing;Czynsz;2 400,00;PLN\n", encoding="utf-8-sig")
        rows = load(str(path))
        assert rows[0].category == "Housing"
        assert rows[0].amount == Decimal("2400.00")

    def test_tab_separated(self, tmp_path):
        path = write(tmp_path, "t.tsv", "category\tlabel\tamount\nFood\tLidl\t12.50\n")
        assert load(path)[0].amount == Decimal("12.50")

    def test_a_missing_header_is_reported(self, tmp_path):
        path = write(tmp_path, "h.csv", "Housing,Rent,2000\nFood,Lidl,120\n")
        with pytest.raises(LoaderError, match="no header row"):
            load(path)

    def test_an_empty_file_is_reported(self, tmp_path):
        with pytest.raises(LoaderError, match="empty"):
            load(write(tmp_path, "e.csv", "   \n"))

    def test_a_bad_row_names_its_line_number(self, tmp_path):
        path = write(tmp_path, "b.csv",
                     "category,label,amount\nHousing,Rent,2000\nFood,Lidl,not-a-number\n")
        with pytest.raises(LoaderError, match=r":3:"):
            load(path)


class TestJson:
    def test_array(self, tmp_path):
        path = write(tmp_path, "a.json",
                     '[{"category":"Housing","label":"Rent","amount":2000,'
                     '"currency":"PLN","date":"2026-08-02"}]')
        rows = load(path)
        assert rows[0].date == _dt.date(2026, 8, 2)

    def test_wrapped_in_an_object(self, tmp_path):
        path = write(tmp_path, "w.json",
                     '{"expenses":[{"category":"Food","amount":12.5}]}')
        assert load(path)[0].amount == Decimal("12.5")

    def test_invalid_json_points_at_the_line(self, tmp_path):
        with pytest.raises(LoaderError, match="invalid JSON at line"):
            load(write(tmp_path, "x.json", "[{,}]"))

    def test_an_unexpected_shape_is_explained(self, tmp_path):
        with pytest.raises(LoaderError, match="expected a JSON array"):
            load(write(tmp_path, "n.json", '{"nothing": true}'))

    def test_json_lines(self, tmp_path):
        path = write(tmp_path, "l.jsonl",
                     '{"category":"Food","amount":10}\n\n{"category":"Fuel","amount":20}\n')
        assert [r.amount for r in load(path)] == [Decimal("10"), Decimal("20")]


class TestOfx:
    def test_reads_transactions(self, tmp_path):
        rows = load(write(tmp_path, "s.ofx", OFX))
        assert len(rows) == 3
        assert rows[0].kind == INCOME and rows[0].amount == Decimal("4200.00")
        assert rows[0].date == _dt.date(2026, 8, 1)
        assert all(row.currency == "USD" for row in rows)

    def test_amounts_are_unsigned_with_a_direction(self, tmp_path):
        rows = load(write(tmp_path, "s.qfx", OFX))
        assert rows[1].amount == Decimal("1450.00") and rows[1].is_expense

    def test_a_file_without_transactions_is_reported(self, tmp_path):
        with pytest.raises(LoaderError, match="STMTTRN"):
            load(write(tmp_path, "x.ofx", "OFXHEADER:100\n<OFX></OFX>"))


class TestQif:
    def test_reads_records(self, tmp_path):
        rows = load(write(tmp_path, "b.qif", QIF))
        assert len(rows) == 2
        assert rows[0].kind == INCOME
        assert rows[0].category == "Income" and rows[0].label == "Payroll"
        assert rows[1].category == "Housing" and rows[1].label == "Rent"

    def test_a_file_without_records_is_reported(self, tmp_path):
        with pytest.raises(LoaderError, match="no QIF transactions"):
            load(write(tmp_path, "e.qif", "!Type:Bank\n"))


class TestCamt:
    def test_reads_entries(self, tmp_path):
        rows = load(write(tmp_path, "s.xml", CAMT), fmt="camt")
        assert len(rows) == 2
        assert rows[0].kind == INCOME and rows[0].label == "Acme GmbH"
        assert rows[1].is_expense and rows[1].category == "Rent"
        assert rows[1].currency == "EUR"

    def test_invalid_xml_is_reported(self, tmp_path):
        with pytest.raises(LoaderError, match="invalid XML"):
            load(write(tmp_path, "x.xml", "<Document>"), fmt="camt")

    def test_xml_without_entries_is_reported(self, tmp_path):
        with pytest.raises(LoaderError, match="camt"):
            load(write(tmp_path, "x.xml", "<Document><Other/></Document>"), fmt="camt")


class TestExcel:
    def test_reads_the_first_sheet(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.append(["Date", "Category", "Label", "Amount", "Currency"])
        sheet.append(["2026-08-01", "Housing", "Rent", -2600, "PLN"])
        book.save(path)
        rows = load(str(path))
        assert rows[0].category == "Housing" and rows[0].amount == Decimal("-2600")

    def test_a_missing_sheet_lists_what_exists(self, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        path = tmp_path / "book.xlsx"
        book = openpyxl.Workbook()
        book.active.append(["category", "amount"])
        book.active.append(["Food", 10])
        book.save(path)
        with pytest.raises(LoaderError, match="available"):
            load(str(path), sheet="Nope")


class TestDetection:
    @pytest.mark.parametrize("name,expected", [
        ("a.csv", "csv"), ("a.tsv", "csv"), ("a.json", "json"), ("a.jsonl", "jsonl"),
        ("a.ofx", "ofx"), ("a.qfx", "ofx"), ("a.qif", "qif"), ("a.xlsx", "excel"),
    ])
    def test_by_extension(self, tmp_path, name, expected):
        assert detect_format(write(tmp_path, name, "x")) == expected

    def test_by_content_when_the_extension_says_nothing(self, tmp_path):
        path = write(tmp_path, "statement.dat", OFX)
        assert detect_format(path) == "ofx"

    def test_an_unknown_file_asks_for_the_flag(self, tmp_path):
        with pytest.raises(LoaderError, match="--format"):
            detect_format(write(tmp_path, "mystery.dat", "\x00\x01binary"))

    def test_an_unknown_format_name_lists_the_choices(self, csv_file):
        with pytest.raises(LoaderError, match="unknown format"):
            load(str(csv_file), fmt="lotus123")


def test_every_registered_format_is_described():
    for name, fmt in FORMATS.items():
        assert fmt.description and fmt.extensions, name
