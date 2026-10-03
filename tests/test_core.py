from nayvadius.hash import content_hash
from nayvadius.processor import fallback
def test_hash(): assert content_hash("x") == content_hash("x")
def test_fallback(): assert fallback("T","Apple works with Google.").title == "T"
