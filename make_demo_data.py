"""Generate synthetic statement files for both supported formats."""
from __future__ import annotations

from pathlib import Path

OUT = Path("data/uploads")
OUT.mkdir(parents=True, exist_ok=True)

card_text = """Statement Date~|~16/02/2026
Card Number~|~XXXX1234
Domestic / International Transactions
Transaction type~|~Primary / Addon Customer Name~|~DATE~|~Description~|~AMT~|~Debit /Credit~|~REWARDS
PURCHASE~|~JOHN DOE~|~01/02/2026 12:30:00~|~APPLE MEDIA SERVICES (Ref# 09991)~|~219.00~|~~|~0
PURCHASE~|~JOHN DOE~|~02/02/2026~|~KFC MG ROAD (Ref# 09992)~|~450.00~|~~|~0
REFUND~|~JOHN DOE~|~03/02/2026~|~REVERSAL KFC MG ROAD Ref# 09992~|~450.00~|~Credit~|~0
"""

bank_text = """Date,Narration,Value Dat,Debit Amount,Credit Amount,Chq/Ref Number,Closing Balance
01/02/26,UPI-APPLE MEDIA SERVICES-123,01/02/26,219.00,0.00,0000102594010423,222764.99
05/02/26,CREDIT CARD PAYMENT HDFC,05/02/26,669.00,0.00,0000102594010424,222095.99
06/02/26,TRANSFER FROM SAVINGS,06/02/26,0.00,2000.00,0000102594010425,224095.99
"""

(OUT / "demo_card.csv").write_text(card_text, encoding="utf-8")
(OUT / "demo_bank.txt").write_text(bank_text, encoding="utf-8")
print("Generated demo statements in", OUT)
