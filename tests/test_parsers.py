from pathlib import Path

from finance_core.ingestion.parsers import BankTxtStatementParser, DelimitedCardStatementParser


def test_parser_a_reads_card_format(tmp_path: Path):
    p = tmp_path / "card.csv"
    p.write_text(
        """Statement Date~|~16/02/2026
Domestic / International Transactions
Transaction type~|~Primary / Addon Customer Name~|~DATE~|~Description~|~AMT~|~Debit /Credit~|~REWARDS
PURCHASE~|~JOHN~|~01/02/2026 12:30:00~|~APPLE MEDIA SERVICES (Ref# 123)~|~219.00~|~~|~0
""",
        encoding="utf-8",
    )
    parser = DelimitedCardStatementParser()
    out = parser.parse(p)
    assert out.source_type_guess == "credit"
    assert out.metadata["Statement Date"] == "16/02/2026"
    assert len(out.rows) == 1
    assert out.rows[0]["raw_ref"] == "123"
    assert out.rows[0]["direction"] == "outflow"


def test_parser_b_reads_bank_txt(tmp_path: Path):
    p = tmp_path / "bank.txt"
    p.write_text(
        "Date,Narration,Value Dat,Debit Amount,Credit Amount,Chq/Ref Number,Closing Balance\n"
        "01/02/26,UPI-APPLE,01/02/26,219.00,0.00,0000123,222.0\n"
        "02/02/26,SALARY,02/02/26,0.00,1000.00,0000124,1222.0\n",
        encoding="utf-8",
    )
    parser = BankTxtStatementParser()
    out = parser.parse(p)
    assert out.source_type_guess == "debit"
    assert out.rows[0]["direction"] == "outflow"
    assert out.rows[0]["amount"] == 219.0
    assert out.rows[1]["direction"] == "inflow"
    assert out.rows[1]["raw_ref"] == "0000124"
