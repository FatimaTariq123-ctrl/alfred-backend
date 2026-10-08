import pytest
from pipeline.parser import FilingParser
from config.policy import PolicyConfig


def test_10q_section_name_mapping():
    # Standard 10-Q keys
    assert FilingParser._map_section_name("Part I, Item 1") == "Part I, Item 1. Financial Statements"
    assert FilingParser._map_section_name("Part I, Item 2") == "Part I, Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations"
    assert FilingParser._map_section_name("Part I, Item 3") == "Part I, Item 3. Quantitative and Qualitative Disclosures About Market Risk"
    assert FilingParser._map_section_name("Part I, Item 4") == "Part I, Item 4. Controls and Procedures"
    assert FilingParser._map_section_name("Part II, Item 1") == "Part II, Item 1. Legal Proceedings"
    assert FilingParser._map_section_name("Part II, Item 1A") == "Part II, Item 1A. Risk Factors"
    assert FilingParser._map_section_name("Part II, Item 2") == "Part II, Item 2. Unregistered Sales of Equity Securities and Use of Proceeds"
    assert FilingParser._map_section_name("Part II, Item 3") == "Part II, Item 3. Defaults Upon Senior Securities"
    assert FilingParser._map_section_name("Part II, Item 4") == "Part II, Item 4. Mine Safety Disclosures"
    assert FilingParser._map_section_name("Part II, Item 5") == "Part II, Item 5. Other Information"
    assert FilingParser._map_section_name("Part II, Item 6") == "Part II, Item 6. Exhibits"


def test_10k_and_8k_section_name_mapping():
    assert FilingParser._map_section_name("Item 1") == "Item 1. Business"
    assert FilingParser._map_section_name("Item 1A") == "Item 1A. Risk Factors"
    assert FilingParser._map_section_name("Item 7") == "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations"
    assert FilingParser._map_section_name("Item 8") == "Item 8. Financial Statements and Supplementary Data"
    assert FilingParser._map_section_name("Item 2.02") == "Item 2.02 Results of Operations and Financial Condition"
    assert FilingParser._map_section_name("Item 4.01") == "Item 4.01 Changes in Registrant's Certifying Accountant"


def test_unknown_and_part_keys():
    # Unknown key starting with Part must not prepend Item
    res_part = FilingParser._map_section_name("Part III, Item 9")
    assert not res_part.startswith("Item Part")
    assert res_part == "Part III, Item 9"

    # Unknown key starting with Item
    assert FilingParser._map_section_name("Item 99") == "Item 99"
    # Unknown key not starting with Item
    assert FilingParser._map_section_name("SpecialSection") == "Item SpecialSection"


def test_section_name_length_limit():
    long_key = "Item " + "A" * 200
    mapped = FilingParser._map_section_name(long_key)
    assert len(mapped) <= 128


def test_is_priority_helper():
    policy = PolicyConfig()
    parser = FilingParser(policy=policy)

    # 10-K priority sections
    assert parser._is_priority("10-K", "Item 1") is True
    assert parser._is_priority("10-K", "Item 1A") is True
    assert parser._is_priority("10-K", "Item 2") is False

    # 10-K/A priority sections (stripped form /A)
    assert parser._is_priority("10-K/A", "Item 7") is True

    # 10-Q priority sections
    assert parser._is_priority("10-Q", "Part I, Item 1") is True
    assert parser._is_priority("10-Q", "Part II, Item 2") is False

    # 8-K priority sections (* matches every item)
    assert parser._is_priority("8-K", "Item 2.02") is True
    assert parser._is_priority("8-K", "AnyRandomItem") is True
