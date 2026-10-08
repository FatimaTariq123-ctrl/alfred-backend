"""
Stage 4: Parser & Fact/Narrative Extractor (§4.1-4.3, §6)

Parses Inline XBRL (iXBRL) and structured text blocks from raw filing assets.
Produces:
1. FactObservation rows (XBRL concept, value, unit, currency, period_start/end, instant_date, dimensions)
2. TextChunk rows (section, text, page/anchor, source_span) for narrative retrieval.

Per-filing XBRL is the primary structured facts input.
Fails closed if facts cannot be extracted — no synthetic/mock facts permitted (§17).
"""

import uuid
import logging
import hashlib
import re
from typing import List, Dict, Any, Tuple, Optional, Set
from datetime import date, datetime

from schema.models import Filing, FilingAsset, FactObservation, TextChunk
from storage.object_store import ObjectStore
from storage.db import DatabaseManager
from config.policy import PolicyConfig, DEFAULT_POLICY
from common.ids import stable_id
from common.rate_limiter import SEC_LIMITER

logger = logging.getLogger(__name__)

_NO_EDGAR_F = object()


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    s = str(v).strip()
    return s in {"", "nan", "NaN", "<NA>", "NaT", "None"}


def _is_true(v: Any) -> bool:
    if _is_missing(v):
        return False
    if isinstance(v, str):
        return v.strip().lower() in {"true", "1"}
    return bool(v)


def _axis_from_column(col: str) -> str:
    raw = col[4:] if col.startswith("dim_") else col
    if "_" in raw:
        parts = raw.split("_", 1)
        return f"{parts[0]}:{parts[1]}"
    return raw


def _parse_date_helper(val: Any) -> Optional[date]:
    if _is_missing(val):
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


FORM_10Q_SECTION_MAP: Dict[str, str] = {
    "Part I, Item 1": "Part I, Item 1. Financial Statements",
    "Part I, Item 2": "Part I, Item 2. Management's Discussion and Analysis of Financial Condition and Results of Operations",
    "Part I, Item 3": "Part I, Item 3. Quantitative and Qualitative Disclosures About Market Risk",
    "Part I, Item 4": "Part I, Item 4. Controls and Procedures",
    "Part II, Item 1": "Part II, Item 1. Legal Proceedings",
    "Part II, Item 1A": "Part II, Item 1A. Risk Factors",
    "Part II, Item 2": "Part II, Item 2. Unregistered Sales of Equity Securities and Use of Proceeds",
    "Part II, Item 3": "Part II, Item 3. Defaults Upon Senior Securities",
    "Part II, Item 4": "Part II, Item 4. Mine Safety Disclosures",
    "Part II, Item 5": "Part II, Item 5. Other Information",
    "Part II, Item 6": "Part II, Item 6. Exhibits"
}


class FilingParser:
    def __init__(
        self,
        object_store: Optional[ObjectStore] = None,
        db_manager: Optional[DatabaseManager] = None,
        policy: Optional[PolicyConfig] = None
    ):
        self.store = object_store or ObjectStore()
        self.db = db_manager or DatabaseManager()
        self.policy = policy or DEFAULT_POLICY
        self.parse_report: List[Dict[str, Any]] = []

    def _lookup_filing(self, filing: Filing) -> Tuple[Optional[Any], List[str]]:
        errors: List[str] = []
        try:
            SEC_LIMITER.acquire(tag=f"parser:{filing.accession_number}")
            from edgar import get_by_accession_number
            edgar_f = get_by_accession_number(filing.accession_number)
            if not edgar_f:
                err_msg = f"Could not locate EDGAR filing object for accession {filing.accession_number}"
                logger.warning(err_msg)
                errors.append(err_msg)
                return None, errors
            return edgar_f, errors
        except Exception as e:
            err_msg = f"EDGAR lookup failed for filing {filing.accession_number}: {e}"
            logger.warning(err_msg)
            errors.append(str(e))
            return None, errors

    def _is_priority(self, form_type: str, item_key: str) -> bool:
        base_form = form_type.split('/')[0].upper().strip()
        priority_list = self.policy.priority_sections.get(base_form, [])
        if "*" in priority_list:
            return True
        key_clean = item_key.strip()
        for p in priority_list:
            if key_clean == p or key_clean.startswith(p):
                return True
        return False

    def extract(self, filings: List[Filing], assets: List[FilingAsset]) -> Tuple[List[FactObservation], List[TextChunk]]:
        """
        Parses filing assets and extracts real XBRL facts and text chunks.
        Fails closed if facts cannot be parsed (§17).
        """
        self.parse_report = []
        all_facts: List[FactObservation] = []
        all_chunks: List[TextChunk] = []

        asset_map = {a.filing_id: a for a in assets}

        for filing in filings:
            asset = asset_map.get(filing.filing_id)
            report_entry: Dict[str, Any] = {
                "filing_id": filing.filing_id,
                "accession_number": filing.accession_number,
                "form_type": filing.form_type,
                "facts_kept": 0,
                "facts_skipped_non_numeric": 0,
                "chunks": 0,
                "priority_chunks": 0,
                "sections": [],
                "used_fallback": False,
                "errors": [],
                "required_found": {},
                "required_missing": []
            }

            if not asset:
                report_entry["errors"].append("Missing filing asset")
                self.parse_report.append(report_entry)
                continue

            raw_bytes = self.store.fetch_asset(asset.storage_uri)
            if not raw_bytes:
                report_entry["errors"].append("Failed to fetch raw bytes from object store")
                self.parse_report.append(report_entry)
                continue

            logger.info(f"Parsing facts & narrative for filing {filing.form_type} {filing.accession_number}...")

            # 1. SEC Filing lookup (once per filing)
            edgar_f, lookup_errors = self._lookup_filing(filing)
            if lookup_errors:
                report_entry["errors"].extend(lookup_errors)

            # 2. Extract XBRL facts (skip 8-K and 8-K/A per CHANGE 5)
            facts: List[FactObservation] = []
            skipped_non_numeric = 0
            req_found: Dict[str, int] = {}
            req_missing: List[str] = []

            if filing.form_type in {"8-K", "8-K/A"}:
                logger.info(f"Skipping XBRL facts extraction for cover-page form {filing.form_type} {filing.accession_number}")
            else:
                facts, skipped_non_numeric, req_found, req_missing, extract_errs = self._extract_xbrl_facts(
                    filing, raw_bytes, edgar_f=edgar_f
                )
                if extract_errs:
                    report_entry["errors"].extend(extract_errs)

            report_entry["facts_kept"] = len(facts)
            report_entry["facts_skipped_non_numeric"] = skipped_non_numeric
            report_entry["required_found"] = req_found
            report_entry["required_missing"] = req_missing
            all_facts.extend(facts)

            # 3. Extract narrative text chunks
            chunks, used_fallback, priority_chunks, chunk_sections, chunk_errs = self._extract_narrative_chunks(
                filing, raw_bytes, edgar_f=edgar_f
            )
            if chunk_errs:
                report_entry["errors"].extend(chunk_errs)

            for chunk in chunks:
                chunk.parser_version = self.policy.parser_version

            self.db.save_text_chunks(chunks)
            all_chunks.extend(chunks)

            report_entry["chunks"] = len(chunks)
            report_entry["priority_chunks"] = priority_chunks
            report_entry["sections"] = chunk_sections
            report_entry["used_fallback"] = used_fallback

            self.parse_report.append(report_entry)

        logger.info(f"Extracted {len(all_facts)} real XBRL fact observations and {len(all_chunks)} text chunks across {len(filings)} filings.")
        return all_facts, all_chunks

    @staticmethod
    def _extract_dimensions(row: Any, dim_cols: List[str]) -> Optional[Dict[str, str]]:
        axes: Dict[str, str] = {}
        for col in dim_cols:
            cell = row.get(col)
            if not _is_missing(cell):
                axes[_axis_from_column(col)] = str(cell).strip()
        if axes:
            return axes

        dim = row.get("dimension")
        mem = row.get("member")
        if not _is_missing(dim) and not _is_missing(mem):
            return {str(dim).strip(): str(mem).strip(), "_partial_dimensions": "true"}

        if _is_true(row.get("is_dimensioned")):
            return {"_unparsed_dimension": "true"}

        return None

    @staticmethod
    def _extract_period(row: Any) -> Tuple[Optional[date], Optional[date], Optional[date]]:
        p_instant = _parse_date_helper(row.get("period_instant"))
        p_start = _parse_date_helper(row.get("period_start"))
        p_end = _parse_date_helper(row.get("period_end"))

        if p_instant is not None:
            return (None, None, p_instant)
        if p_start is not None or p_end is not None:
            return (p_start, p_end, None)
        return (None, None, None)

    def _row_to_fact(self, row: Any, filing: Filing, dim_cols: List[str]) -> FactObservation:
        concept = str(row.get("concept", ""))
        val_raw = row.get("numeric_value")
        if _is_missing(val_raw):
            val_raw = row.get("value")

        try:
            val = float(val_raw) if not _is_missing(val_raw) else None
        except (ValueError, TypeError):
            val = None

        # Unit logic: edgartools currency if not missing, else unit_ref if not missing, else USD
        curr_raw = row.get("currency")
        unit_ref_raw = row.get("unit_ref")
        if not _is_missing(curr_raw):
            unit_str = str(curr_raw).strip()
        elif not _is_missing(unit_ref_raw):
            unit_str = str(unit_ref_raw).strip()
        else:
            unit_str = "USD"

        # Currency logic: edgartools currency value if not missing AND matches ^[A-Z]{3}$
        if not _is_missing(curr_raw):
            c_str = str(curr_raw).strip()
            currency_val = c_str if re.match(r"^[A-Z]{3}$", c_str) else None
        else:
            currency_val = None

        p_start, p_end, p_instant = self._extract_period(row)
        dims = self._extract_dimensions(row, dim_cols)

        fp = row.get("fiscal_period")
        fy = row.get("fiscal_year")
        fp_val = str(fp).upper().strip() if not _is_missing(fp) else None
        fy_val = str(fy).strip() if not _is_missing(fy) else None

        ctx_ref = row.get("context_ref")
        context_ref_val = str(ctx_ref).strip() if not _is_missing(ctx_ref) else None

        return FactObservation(
            fact_id=f"fact_{uuid.uuid4().hex[:12]}",
            canonical_fact_key="",  # Hashed in Stage 5 Normalizer
            filing_id=filing.filing_id,
            concept=concept,
            value=val,
            unit=unit_str,
            currency=currency_val,
            period_start=p_start,
            period_end=p_end,
            instant_date=p_instant,
            dimensions=dims,
            fiscal_period=fp_val,
            fiscal_year=fy_val,
            context_ref=context_ref_val,
            parser_version=self.policy.parser_version
        )

    def _facts_and_stats_from_dataframe(
        self,
        df: Any,
        filing: Filing
    ) -> Tuple[List[FactObservation], int, Dict[str, int], List[str]]:
        dim_cols = sorted([str(c) for c in df.columns if str(c).startswith("dim_")])
        facts: List[FactObservation] = []
        skipped_non_numeric = 0
        no_period_count = 0
        no_period_examples: List[str] = []

        # 1. Compute required_found and required_missing BEFORE scope filtering on company-wide numeric facts
        required_counts: Dict[str, int] = {code: 0 for code in self.policy.required_metrics}
        
        # Build tag to metric_code map
        tag_to_metric: Dict[str, str] = {}
        for m_code, m_info in self.policy.required_metrics.items():
            for t in m_info.get("tags", []):
                tag_to_metric[t] = m_code

        # Build list of raw facts
        raw_facts_with_rows = []
        for _, row in df.iterrows():
            fact = self._row_to_fact(row, filing, dim_cols)
            raw_facts_with_rows.append((fact, row))
            if fact.value is None:
                skipped_non_numeric += 1

        # Check required tags for company-wide numeric facts
        for fact, row in raw_facts_with_rows:
            if fact.value is not None and fact.dimensions is None:
                concept = fact.concept
                if ":" in concept:
                    prefix, local_name = concept.split(":", 1)
                    if prefix == "us-gaap" and local_name in tag_to_metric:
                        metric_code = tag_to_metric[local_name]
                        required_counts[metric_code] += 1

        required_found = {k: v for k, v in required_counts.items() if v > 0}
        required_missing = [k for k, v in required_counts.items() if v == 0]

        # 2. Scope filtering and collection (skip numeric_value is None per CHANGE 5)
        fact_scope = self.policy.fact_scope
        for fact, row in raw_facts_with_rows:
            if fact.value is None:
                continue

            # Scope checks
            if fact_scope == "required_company_wide":
                if fact.dimensions is not None:
                    continue
                concept = fact.concept
                matches_tag = False
                if ":" in concept:
                    prefix, local_name = concept.split(":", 1)
                    if prefix == "us-gaap" and local_name in tag_to_metric:
                        matches_tag = True
                if not matches_tag:
                    continue
            elif fact_scope == "required_all_dims":
                concept = fact.concept
                matches_tag = False
                if ":" in concept:
                    prefix, local_name = concept.split(":", 1)
                    if prefix == "us-gaap" and local_name in tag_to_metric:
                        matches_tag = True
                if not matches_tag:
                    continue

            facts.append(fact)
            if fact.period_start is None and fact.period_end is None and fact.instant_date is None:
                no_period_count += 1
                if len(no_period_examples) < 5:
                    context_ref = fact.context_ref
                    ex_str = f"concept={fact.concept}" + (f", context_ref={context_ref}" if context_ref else "")
                    no_period_examples.append(ex_str)

        if no_period_count > 0:
            logger.warning(
                f"Filing {filing.accession_number} contained {no_period_count} facts with no period information. "
                f"Examples: {', '.join(no_period_examples)}"
            )

        return facts, skipped_non_numeric, required_found, required_missing

    def _facts_from_dataframe(self, df: Any, filing: Filing) -> List[FactObservation]:
        return self._facts_and_stats_from_dataframe(df, filing)[0]

    def _extract_xbrl_facts(
        self,
        filing: Filing,
        raw_bytes: bytes,
        edgar_f: Optional[Any] = _NO_EDGAR_F
    ) -> Tuple[List[FactObservation], int, Dict[str, int], List[str], List[str]]:
        """
        Extracts real Inline XBRL facts using edgartools XBRL parser.
        No synthetic baseline fallbacks (§17).
        """
        facts: List[FactObservation] = []
        errors: List[str] = []

        try:
            if edgar_f is _NO_EDGAR_F:
                target_f, lookup_errs = self._lookup_filing(filing)
                if lookup_errs:
                    errors.extend(lookup_errs)
            else:
                target_f = edgar_f

            if not target_f:
                return facts, 0, {}, list(self.policy.required_metrics.keys()), errors

            SEC_LIMITER.acquire(tag=f"parser:xbrl:{filing.accession_number}")
            xbrl = target_f.xbrl()
            if not xbrl:
                logger.info(f"Filing {filing.form_type} {filing.accession_number} has no XBRL payload (edgar_f.xbrl() is None).")
                return facts, 0, {}, list(self.policy.required_metrics.keys()), errors

            if not hasattr(xbrl, "facts") or xbrl.facts is None:
                logger.warning(f"XBRL object for filing {filing.accession_number} has no facts attribute.")
                return facts, 0, {}, list(self.policy.required_metrics.keys()), errors

            df = xbrl.facts.to_dataframe()
            if df is None or df.empty:
                logger.warning(f"XBRL facts dataframe is empty for filing {filing.accession_number}.")
                return facts, 0, {}, list(self.policy.required_metrics.keys()), errors

            f_list, skipped, req_found, req_missing = self._facts_and_stats_from_dataframe(df, filing)
            return f_list, skipped, req_found, req_missing, errors

        except Exception as e:
            err_msg = f"Failed to parse Inline XBRL facts for filing {filing.accession_number}: {e}"
            logger.warning(err_msg)
            errors.append(str(e))

        return facts, 0, {}, list(self.policy.required_metrics.keys()), errors

    def _extract_narrative_chunks(
        self,
        filing: Filing,
        raw_bytes: bytes,
        edgar_f: Optional[Any] = _NO_EDGAR_F
    ) -> Tuple[List[TextChunk], bool, int, List[str], List[str]]:
        """
        Extracts narrative text chunks per section using edgartools structured section access (§6).
        Parses all sections into text_chunk rows tagged by section name.
        Discards nothing: unclassified or unparsed text is retained as 'Unclassified' chunks.
        Fails honestly: falls back to full-text 'Unclassified' chunking if structured extraction fails.
        """
        chunks: List[TextChunk] = []
        errors: List[str] = []
        used_fallback = False
        priority_chunks_count = 0
        sections_seen: Set[str] = set()

        if not raw_bytes:
            return chunks, False, 0, [], errors

        # 1. Structured section extraction via edgartools filing.obj()
        try:
            if edgar_f is _NO_EDGAR_F:
                target_f, lookup_errs = self._lookup_filing(filing)
                if lookup_errs:
                    errors.extend(lookup_errs)
            else:
                target_f = edgar_f

            if target_f:
                SEC_LIMITER.acquire(tag=f"parser:obj:{filing.accession_number}")
                obj = target_f.obj()
                if obj and hasattr(obj, "items") and obj.items:
                    items_list = list(obj.items)
                    for item_key in items_list:
                        try:
                            item_content = obj[item_key]
                            item_text = str(item_content) if item_content is not None else ""
                            if item_text.strip():
                                section_name = self._map_section_name(item_key)
                                sections_seen.add(section_name)
                                section_chunks = self._chunk_text(
                                    filing_id=filing.filing_id,
                                    section_name=section_name,
                                    text=item_text
                                )
                                is_prio = self._is_priority(filing.form_type, item_key)
                                if is_prio:
                                    priority_chunks_count += len(section_chunks)
                                chunks.extend(section_chunks)
                        except Exception as item_err:
                            logger.debug(f"Could not extract item {item_key} for filing {filing.accession_number}: {item_err}")
        except Exception as e:
            err_msg = f"Structured edgartools section extraction failed for filing {filing.accession_number}: {e}"
            logger.warning(err_msg)
            errors.append(str(e))

        # 2. Return structured chunks if successfully extracted
        if chunks:
            return chunks, False, priority_chunks_count, sorted(list(sections_seen)), errors

        # 3. Fallback: Parse raw text and chunk as "Unclassified" (discarding nothing)
        used_fallback = True
        logger.warning(f"Structured parsing unavailable for filing {filing.accession_number}; falling back to Unclassified full-text chunking.")
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        clean_text = self._strip_html_tags(raw_text)

        fb_chunks = self._chunk_text(
            filing_id=filing.filing_id,
            section_name="Unclassified",
            text=clean_text
        )
        if self._is_priority(filing.form_type, "Unclassified"):
            priority_chunks_count = len(fb_chunks)

        return fb_chunks, used_fallback, priority_chunks_count, ["Unclassified"], errors

    @staticmethod
    def _map_section_name(item_key: str) -> str:
        """Maps edgartools item keys to standard descriptive section titles."""
        clean_key = str(item_key).strip()

        # 1. Standard 10-Q sections map
        if clean_key.startswith("Part"):
            if clean_key in FORM_10Q_SECTION_MAP:
                title = FORM_10Q_SECTION_MAP[clean_key]
            else:
                title = clean_key
            return title[:128]

        # 2. Canonical section titles map for 10-K and 8-K priority sections
        section_map = {
            "Item 1": "Item 1. Business",
            "Item 1A": "Item 1A. Risk Factors",
            "Item 1B": "Item 1B. Unresolved Staff Comments",
            "Item 1C": "Item 1C. Cybersecurity",
            "Item 2": "Item 2. Properties",
            "Item 3": "Item 3. Legal Proceedings",
            "Item 4": "Item 4. Mine Safety Disclosures",
            "Item 5": "Item 5. Market for Registrant's Common Equity, Related Stockholder Matters and Issuer Purchases of Equity Securities",
            "Item 6": "Item 6. [Reserved]",
            "Item 7": "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            "Item 7A": "Item 7A. Quantitative and Qualitative Disclosures About Market Risk",
            "Item 8": "Item 8. Financial Statements and Supplementary Data",
            "Item 9": "Item 9. Changes in and Disagreements With Accountants on Accounting and Financial Disclosure",
            "Item 9A": "Item 9A. Controls and Procedures",
            "Item 9B": "Item 9B. Other Information",
            "Item 9C": "Item 9C. Disclosure Regarding Foreign Jurisdictions that Prevent Inspections",
            "Item 10": "Item 10. Directors, Executive Officers and Corporate Governance",
            "Item 11": "Item 11. Executive Compensation",
            "Item 12": "Item 12. Security Ownership of Certain Beneficial Owners and Management and Related Stockholder Matters",
            "Item 13": "Item 13. Certain Relationships and Related Transactions, and Director Independence",
            "Item 14": "Item 14. Principal Accountant Fees and Services",
            "Item 15": "Item 15. Exhibits, Financial Statement Schedules",
            "Item 2.02": "Item 2.02 Results of Operations and Financial Condition",
            "Item 4.01": "Item 4.01 Changes in Registrant's Certifying Accountant",
        }

        if clean_key in section_map:
            title = section_map[clean_key]
        elif len(clean_key) > 10 and clean_key.startswith("Item"):
            title = clean_key
        else:
            title = clean_key if clean_key.startswith("Item") else f"Item {clean_key}"

        return title[:128]

    @staticmethod
    def _chunk_text(
        filing_id: str,
        section_name: str,
        text: str,
        base_offset: int = 0,
        max_chunk_size: int = 3000,
        overlap: int = 200
    ) -> List[TextChunk]:
        """Splits long text into ~3000 character overlapping chunks with source_span character offsets."""
        chunks: List[TextChunk] = []
        if not text or not text.strip():
            return chunks

        text_len = len(text)
        start = 0
        chunk_index = 0
        while start < text_len:
            end = min(start + max_chunk_size, text_len)
            if end < text_len:
                break_point = text.rfind('\n', start + max_chunk_size - 500, end)
                if break_point == -1 or break_point <= start:
                    break_point = text.rfind(' ', start + max_chunk_size - 200, end)
                if break_point > start:
                    end = break_point

            chunk_str = text[start:end].strip()
            if chunk_str:
                chunk_md5 = hashlib.md5(chunk_str.encode("utf-8")).hexdigest()
                chunk = TextChunk(
                    chunk_id=stable_id("chunk", filing_id, section_name, chunk_index, chunk_md5),
                    filing_id=filing_id,
                    section=section_name,
                    text=chunk_str,
                    page_anchor=None,
                    embedding_ref=None,
                    source_span={
                        "char_start": base_offset + start,
                        "char_end": base_offset + end
                    }
                )
                chunks.append(chunk)
                chunk_index += 1

            if end >= text_len:
                break
            start = max(end - overlap, start + 1)

        return chunks

    @staticmethod
    def _strip_html_tags(text: str) -> str:
        """Strips HTML tags to extract clean text for fallback narrative chunking."""
        # Remove <ix:header>...</ix:header>, <script>...</script>, <style>...</style> blocks (case-insensitive, DOTALL)
        text = re.sub(r'<(ix:header|script|style)\b[^>]*>.*?</\1>', '', text, flags=re.IGNORECASE | re.DOTALL)
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean)
        return clean.strip()

    @staticmethod
    def _parse_date(val: Any) -> Optional[date]:
        return _parse_date_helper(val)
