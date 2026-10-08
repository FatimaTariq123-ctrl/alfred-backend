"""
Stage 1: Filing Indexer (§4.1)

Maintains a complete issuer filing index from official market sources (SEC EDGAR).
Indexes amendments (10-K/A, 10-Q/A) as first-class records linked to base filing lineage.
Enforces stable identifiers: CIK, Accession Number, Form Type, Filing Date, Report Period.
Fails closed on EDGAR query failure — no synthetic or mock fallbacks allowed (§17).
"""

import logging
import re
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple

from config.settings import init_edgar_identity
from schema.models import Issuer, Filing
from storage.db import DatabaseManager

from common.rate_limiter import SEC_LIMITER

logger = logging.getLogger(__name__)


_ITEM_RE = re.compile(r"\b(\d{1,2}\.\d{2})\b")


def parse_sec_items(value: Any) -> List[str]:
    """
    Turns the EDGAR 'items' metadata ("2.02,9.01", "Item 5.02", ["2.02", "9.01"], None) into a de-duplicated,
    ordered list of item numbers. Anything that is not an item number is ignored.
    """
    if value is None:
        return []
    text = ",".join(str(v) for v in value) if isinstance(value, (list, tuple, set)) else str(value)
    seen: List[str] = []
    for m in _ITEM_RE.finditer(text):
        item = m.group(1)
        if item not in seen:
            seen.append(item)
    return seen


def _coerce_date(value: Any) -> Optional[date]:
    """date / datetime / 'YYYY-MM-DD...' -> date, or None when it is not a usable date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    """datetime / ISO string -> naive UTC datetime, or None."""
    if value is None or value == "":
        return None
    try:
        dt_val = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt_val.tzinfo is not None:
        from datetime import timezone
        dt_val = dt_val.astimezone(timezone.utc).replace(tzinfo=None)
    return dt_val


def _is_amendment(form: str) -> bool:
    return str(form).upper().endswith("/A")


def _base_form(form: str) -> str:
    clean_form = str(form).upper()
    return clean_form[:-2] if _is_amendment(clean_form) else clean_form


def _clean_fiscal_year_end(value: Any) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    if len(s) != 4 or not s.isdigit():
        return None
    mm, dd = int(s[:2]), int(s[2:])
    if 1 <= mm <= 12 and 1 <= dd <= 31:
        return s
    return None


def _derive_fiscal_year_end(filings: List[Filing]) -> Optional[str]:
    ten_ks = [f for f in filings if f.form_type == "10-K"]
    if not ten_ks:
        return None
    latest_10k = max(ten_ks, key=lambda f: f.report_period)
    return latest_10k.report_period.strftime("%m%d")


class FilingIndexer:
    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        self.db = db_manager or DatabaseManager()
        self.skipped: List[Dict[str, Any]] = []
        init_edgar_identity()

    def _report_period(self, item: Any, accession: str, filing_date_val: date) -> date:
        """
        Report period of one filing. The EDGAR index already carries it (reportDate), so no download is needed.
        Only when the index has none, the filing's own header is read (a network call); if that fails the filing is
        KEPT with its filing date and a warning, instead of being dropped.
        """
        from_index = _coerce_date(getattr(item, "report_date", None))
        if from_index:
            return from_index
        try:
            from_header = _coerce_date(getattr(item, "period_of_report", None))
            if from_header:
                return from_header
        except Exception as e:
            logger.warning(f"Report period of {accession} could not be read ({type(e).__name__}: {e}); using the filing date.")
        return filing_date_val

    def get_full_filing_index(self, ticker_or_cik: str, as_of_date: Optional[date] = None) -> Tuple[Issuer, List[Filing]]:
        """
        Queries SEC EDGAR filing inventory for target issuer up to as_of_date.
        Builds complete filing inventory before selective window filtering.
        Fails closed if SEC EDGAR cannot be queried.
        """
        as_of = as_of_date or date.today()
        logger.info(f"Indexing SEC EDGAR filings for issuer {ticker_or_cik} as of {as_of.isoformat()}...")

        try:
            SEC_LIMITER.acquire(tag=f"indexer:{ticker_or_cik}")
            from edgar import Company
            company = Company(ticker_or_cik)
            if not company:
                raise RuntimeError(f"Could not locate company '{ticker_or_cik}' on SEC EDGAR.")

            issuer_id = f"issuer_US_{ticker_or_cik.upper()}"
            cik_str = str(company.cik) if hasattr(company, "cik") and company.cik else (ticker_or_cik if str(ticker_or_cik).isdigit() else "")

            initial_fye = _clean_fiscal_year_end(getattr(company, "fiscal_year_end", None))

            issuer = Issuer(
                issuer_id=issuer_id,
                market="US",
                legal_name=getattr(company, "name", None) or f"Issuer ({ticker_or_cik.upper()})",
                ticker=ticker_or_cik.upper(),
                cik=cik_str,
                fiscal_year_end=initial_fye
            )
            self.db.save_issuer(issuer)

            edgar_filings = company.get_filings()
            if not edgar_filings:
                raise RuntimeError(f"No filing inventory returned from SEC EDGAR for issuer {ticker_or_cik}.")

            try:
                raw_list = list(edgar_filings)
            except Exception as list_err:
                logger.warning(f"Error converting filing inventory to list for {ticker_or_cik}: {type(list_err).__name__}: {str(list_err)}")
                raw_list = []

            if not raw_list:
                raise RuntimeError(f"No parseable filing entries found for issuer {ticker_or_cik}.")

            # One pass over the EDGAR index. Every record is read ONCE; a record is never dropped silently:
            # if it really cannot be used, it is listed in self.skipped and logged as a WARNING with the accession and the reason.
            self.skipped = []
            parsed: List[Tuple[Any, str, str, date, date]] = []
            for item in raw_list:
                accession = None
                try:
                    form_raw = getattr(item, "form", None)
                    accession_raw = getattr(item, "accession_number", None)
                    accession = str(accession_raw) if accession_raw else None
                    if not form_raw or not accession:
                        self.skipped.append({"accession": accession, "reason": "record has no form or no accession number"})
                        continue
                    form = str(form_raw).upper()

                    filing_date_val = _coerce_date(getattr(item, "filing_date", None))
                    if filing_date_val is None:
                        self.skipped.append({"accession": accession, "reason": "record has no valid filing date"})
                        continue
                    if filing_date_val > as_of:
                        continue                      # filed after the analysis date: not an error

                    report_period_val = self._report_period(item, accession, filing_date_val)
                    parsed.append((item, form, accession, filing_date_val, report_period_val))
                except Exception as item_err:
                    self.skipped.append({"accession": accession, "reason": f"{type(item_err).__name__}: {item_err}"})

            if self.skipped:
                logger.warning(f"Indexer skipped {len(self.skipped)} EDGAR record(s) for {ticker_or_cik} "
                               f"(first 5: {self.skipped[:5]})")

            # Lookup dict for amendment linkage: (base_form_type, report_period) -> base_filing_id
            base_filing_lookup: Dict[Tuple[str, date], str] = {}
            for _item, form, accession, _fd, report_period_val in parsed:
                if not _is_amendment(form):
                    base_filing_lookup[(form, report_period_val)] = f"filing_{accession.replace('-', '_')}"

            all_records: List[Filing] = []
            for item, form, accession, filing_date_val, report_period_val in parsed:
                is_amendment = _is_amendment(form)
                filing_id = f"filing_{accession.replace('-', '_')}"
                base_filing_id = base_filing_lookup.get((_base_form(form), report_period_val)) if is_amendment else None
                all_records.append(Filing(
                    filing_id=filing_id,
                    issuer_id=issuer_id,
                    accession_number=accession,
                    form_type=form,
                    filing_date=filing_date_val,
                    report_period=report_period_val,
                    amendment_flag=is_amendment,
                    base_filing_id=base_filing_id,
                    source_uri=f"https://www.sec.gov/Archives/edgar/data/{issuer.cik}/{accession.replace('-', '')}/{accession}.txt",
                    source_hash="",
                    sec_items=parse_sec_items(getattr(item, "items", None)) if form.startswith("8-K") else None,
                    accepted_at=_coerce_datetime(getattr(item, "acceptance_datetime", None)) if form.startswith("8-K") else None
                ))

            # Save filings in two passes to satisfy foreign key constraints
            filings: List[Filing] = []
            saved_filing_ids = set()

            # Pass 1: base (non-amendment) records
            base_records = [r for r in all_records if not r.amendment_flag]
            self.db.save_filings(base_records)
            for record in base_records:
                filings.append(record)
                saved_filing_ids.add(record.filing_id)

            # Pass 2: amendment records (reset base_filing_id when base was not saved)
            amendment_records = [r for r in all_records if r.amendment_flag]
            for record in amendment_records:
                if record.base_filing_id and record.base_filing_id not in saved_filing_ids:
                    record.base_filing_id = None
            self.db.save_filings(amendment_records)
            for record in amendment_records:
                filings.append(record)
                saved_filing_ids.add(record.filing_id)

            if not filings:
                raise RuntimeError(f"No valid filings could be saved for issuer {ticker_or_cik}.")

            # Derive / verify fiscal_year_end
            derived_fye = _derive_fiscal_year_end(filings)
            if issuer.fiscal_year_end is None:
                issuer.fiscal_year_end = derived_fye

            if issuer.fiscal_year_end is None:
                logger.warning(f"Fiscal year end unknown for issuer {issuer.ticker}; period labels may be wrong.")
            elif initial_fye and derived_fye and initial_fye[:2] != derived_fye[:2]:
                logger.warning(
                    f"Fiscal year end month mismatch for issuer {issuer.ticker}: "
                    f"company '{initial_fye}' vs 10-K '{derived_fye}'. Keeping company value."
                )

            self.db.save_issuer(issuer)

            logger.info(f"Indexed {len(filings)} total filings from SEC EDGAR for issuer {issuer.ticker}")
            return issuer, filings

        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Filing indexer encountered unhandled failure for ticker '{ticker_or_cik}': {type(e).__name__}: {str(e)}")
            raise RuntimeError(f"Indexing failed for ticker '{ticker_or_cik}': {type(e).__name__}: {str(e)}") from e

