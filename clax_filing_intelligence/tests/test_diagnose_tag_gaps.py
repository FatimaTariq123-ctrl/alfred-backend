"""Pure-logic test for scripts/diagnose_tag_gaps.py's keyword extraction (no database)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("diagnose_tag_gaps", Path(__file__).resolve().parent.parent / "scripts" / "diagnose_tag_gaps.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_shared_word_found_across_two_tags():
    assert "receivable" in mod.keywords_from_tags(["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"])


def test_generic_words_are_excluded():
    kws = mod.keywords_from_tags(["LongTermDebtCurrent", "DebtCurrent"])
    assert "current" not in kws and "debt" in kws


def test_single_tag_falls_back_to_its_own_words():
    kws = mod.keywords_from_tags(["AccountsReceivableNetCurrent"])
    assert "receivable" in kws and "accounts" in kws and "net" not in kws and "current" not in kws


def test_no_shared_word_falls_back_to_first_tag_words_not_empty():
    kws = mod.keywords_from_tags(["Revenues", "CostOfGoodsAndServicesSold"])
    assert kws  # falls back to something, never empty (an empty pattern would match nothing usefully)
