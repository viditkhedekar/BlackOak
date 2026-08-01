"""Class-share ticker translation at the Alpaca boundary.

Alpaca rejects the hyphen form outright, and because intraday bars are fetched in one
batched request, a single untranslated ticker fails all 500 symbols with it.
"""

from app.adapters.alpaca_market_data import _from_alpaca, _to_alpaca


def test_class_shares_translate_to_dot_notation() -> None:
    assert _to_alpaca("BRK-B") == "BRK.B"
    assert _to_alpaca("BF-B") == "BF.B"


def test_ordinary_symbols_are_untouched() -> None:
    for symbol in ("AAPL", "MSFT", "SPY"):
        assert _to_alpaca(symbol) == symbol
        assert _from_alpaca(symbol) == symbol


def test_translation_round_trips_to_our_canonical_form() -> None:
    for symbol in ("BRK-B", "BF-B", "AAPL"):
        assert _from_alpaca(_to_alpaca(symbol)) == symbol
