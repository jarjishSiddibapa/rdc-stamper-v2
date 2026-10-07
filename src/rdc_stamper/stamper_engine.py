import os
import sys
import tempfile
import re
import fitz  # PyMuPDF
import pytesseract
import pandas as pd
from PIL import Image
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QRunnable, QThreadPool, Slot


# ---------------------------------------------------------------------------
# DATE EXTRACTION HELPERS
# ---------------------------------------------------------------------------
_DATE_FORMATS = [
    '%d-%m-%Y', '%d-%m-%y',
    '%d-%b-%Y', '%d-%b-%y',
    '%d-%B-%Y', '%d-%B-%y',
    '%d %b %Y', '%d %b %y',
    '%d %B %Y', '%d %B %y',
    '%b %d %Y', '%b %d %y',
    '%B %d %Y', '%B %d %y',
    '%Y-%m-%d',
]

def _parse_date_str(text):
    """Try to parse a date string in various formats → date object or None."""
    if not text:
        return None
    # Normalize human-friendly forms such as "13th June, 2026" and mixed
    # separators such as "13/06-26" without fuzzy parsing. Fuzzy parsing can
    # mistake invoice or document identifiers for dates.
    cleaned = re.sub(
        r'(?<=\d)(?:st|nd|rd|th)\b', '', str(text).strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r'\s*,\s*', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    normalized_separators = re.sub(r'\s*[-/\.]\s*', '-', cleaned)

    for candidate in dict.fromkeys((cleaned, normalized_separators)):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None

# Explicit matching keeps dates bounded, so an ISO date such as 2026-07-01 can
# never be partially matched as 26-07-01 (which strptime interprets as
# 26 July 2001).
_MONTH_NAME_RE = (
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|'
    r'Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
)
_DATE_SEPARATOR_RE = r'(?:\s*[-/\.]\s*|\s+)'
_DATE_RE = (
    # ISO / year-first numeric date.
    r'(?<!\d)\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}(?!\d)'
    r'|'
    # Day-first numeric date; the two separators may differ (13/06-26).
    r'(?<!\d)\d{1,2}[-/\.]\d{1,2}[-/\.](?:\d{4}|\d{2})(?!\d)'
    r'|'
    # Day-first named month (13th June 2026, 13-Jun-26).
    r'(?<!\d)\d{1,2}(?:st|nd|rd|th)?' + _DATE_SEPARATOR_RE +
    _MONTH_NAME_RE + r'\.?' +
    r'(?:\s*,\s*|' + _DATE_SEPARATOR_RE + r')' +
    r'(?:\d{4}|\d{2})(?!\d)'
    r'|'
    # Month-first named month (Jun 13, 2026, June-13-26).
    r'(?<![A-Za-z0-9])' + _MONTH_NAME_RE + r'\.?' +
    _DATE_SEPARATOR_RE + r'\d{1,2}(?:st|nd|rd|th)?' +
    r'(?:\s*,\s*|' + _DATE_SEPARATOR_RE + r')' +
    r'(?:\d{4}|\d{2})(?!\d)'
)

_INVOICE_DATE_LABEL_RE = re.compile(
    r'\b(?:Tax\s+)?Invoice\s*(?:Date|Dt\.?)\b|'
    r'\bDate\s+of\s+Invoice\b|'
    r'\bInv\.?\s*Date\b',
    re.IGNORECASE,
)

_NEXT_DATE_FIELD_RE = re.compile(
    r'\b(?:Ackno\.?|Acknowledg(?:e)?ment|LC|Posting|DC|Document|Due|EWB)\s*Date\s*:',
    re.IGNORECASE,
)
_NEXT_LINE_FIELD_RE = re.compile(
    r'\n\s*[A-Za-z][A-Za-z0-9 ._()/&\-]{1,48}\s*:',
    re.IGNORECASE,
)


def _first_date_in_text(text):
    """Return the first complete, valid date token in text."""
    for match in re.finditer(_DATE_RE, text, re.IGNORECASE):
        parsed = _parse_date_str(match.group())
        if parsed:
            return parsed
    return None

def _extract_invoice_date_from_page(text):
    """
    Extract the invoice date from page text.
    Tries near the 'Invoice Date' label first; falls back to the first valid date anywhere.
    """
    if not text:
        return None

    # Search a bounded region after every invoice-date label. This tolerates
    # OCR line breaks and two-column PDF extraction while prioritizing the field
    # that is actually being verified.
    labels = list(_INVOICE_DATE_LABEL_RE.finditer(text))
    for label in labels:
        field_text = text[label.end():label.end() + 160].lstrip(' \t:-')
        boundaries = [
            match.start()
            for pattern in (_NEXT_DATE_FIELD_RE, _NEXT_LINE_FIELD_RE)
            if (match := pattern.search(field_text))
        ]
        if boundaries:
            field_text = field_text[:min(boundaries)]
        parsed = _first_date_in_text(field_text)
        if parsed:
            return parsed

    # A visible invoice-date label with an unreadable value must not fall back
    # to another business date such as Ackno.Date, LC Date, or Posting Date.
    if labels:
        return None

    # If OCR lost the label, retain the previous fallback but accept only full,
    # bounded date tokens.
    return _first_date_in_text(text)


# ---------------------------------------------------------------------------
# BUILD TARGETS FROM DATAFRAME
# ---------------------------------------------------------------------------
def build_targets_from_df(df):
    """
    Parse an Excel DataFrame into a targets dict:
        { invoice_no_str: [{"date": date|None}, ...] }

    Rows sharing the same (invoice_no, date) are de-duplicated.
    Returns: (targets_dict, total_rows_processed, duplicate_rows_removed)
    """
    if df is None or df.empty:
        return {}, 0, 0

    # Locate columns by name (case-insensitive, stripped)
    col_map  = {str(c).strip().lower(): c for c in df.columns}
    inv_col  = (col_map.get('invoice no')   or col_map.get('invoice number')
                or col_map.get('invoice_no'))
    date_col = (col_map.get('invoice date') or col_map.get('invoice_date')
                or col_map.get('date'))

    # Fallback: first column as invoice number
    if inv_col is None:
        inv_col = df.columns[0]

    targets    = {}      # inv_no → list of {"date"} dicts
    seen       = set()   # (inv_no, date_str) for dedup
    total_rows = 0
    dup_rows   = 0

    for _, row in df.iterrows():
        raw = row[inv_col]
        if pd.isna(raw):
            continue
        inv_no = str(raw).strip()
        if not inv_no or inv_no.lower() == 'nan':
            continue
        total_rows += 1

        # Parse date
        inv_date = None
        if date_col is not None:
            try:
                raw_d = row[date_col]
                if pd.notna(raw_d):
                    inv_date = pd.to_datetime(raw_d).date()
            except Exception:
                pass

        # De-duplicate by (inv_no, date) tuple
        dedup_key = (inv_no, str(inv_date))
        if dedup_key in seen:
            dup_rows += 1
            continue
        seen.add(dedup_key)

        if inv_no not in targets:
            targets[inv_no] = []
        targets[inv_no].append({"date": inv_date})

    return targets, total_rows, dup_rows


# ---------------------------------------------------------------------------
# WORKER SIGNALS
# ---------------------------------------------------------------------------
class WorkerSignals(QObject):
    update_status = Signal(str)
    progress_total = Signal(int)    # Set total steps
    progress_value = Signal(int)    # Update current step
    match_found    = Signal(int, str)
    finished       = Signal(str)    # success message
    error          = Signal(str)    # error message
    log            = Signal(str)    # log message


# ---------------------------------------------------------------------------
# PAGE ANALYSIS TASK
# ---------------------------------------------------------------------------
class PageAnalysisTask(QRunnable):
    def __init__(self, page_idx, pdf_path, pattern, skip_blank, ocr_enabled):
        super().__init__()
        self.page_idx    = page_idx
        self.pdf_path    = pdf_path
        self.pattern     = pattern
        self.skip_blank  = skip_blank
        self.ocr_enabled = ocr_enabled
        # result = (page_idx, match, status, extracted_date)
        self.result = None

    @Slot()
    def run(self):
        try:
            with fitz.open(self.pdf_path) as doc:
                page   = doc[self.page_idx]
                p_text = page.get_text()

                # 1. Blank check
                if self.skip_blank:
                    if not p_text.strip() or len(p_text.strip()) < 5:
                        self.result = (self.page_idx, None, "SKIPPED_BLANK", None)
                        return

                # 2. Direct text match for invoice number
                first_match = None
                if not self.pattern:
                    first_match = "ALL"
                else:
                    matches = self.pattern.findall(p_text)
                    if matches:
                        first_match = max(matches, key=len)

                # 3. OCR fallback for invoice number (offline Tesseract)
                ocr_text = None
                if not first_match and self.ocr_enabled:
                    try:
                        pix = page.get_pixmap(dpi=200)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        ocr_text = pytesseract.image_to_string(img)
                        if self.pattern:
                            matches = self.pattern.findall(ocr_text)
                            if matches:
                                first_match = max(matches, key=len)
                    except Exception as e:
                        self.result = (self.page_idx, None, f"OCR_ERROR: {e}", None)
                        return

                # 4. Extract Invoice Date (only for real invoice matches)
                extracted_date = None

                if first_match and first_match != "ALL":
                    combined = p_text + ("\n" + ocr_text if ocr_text else "")

                    extracted_date = _extract_invoice_date_from_page(combined)

                    # If still missing, run OCR now (invoice no was found via text,
                    # but the date may be image-only)
                    if extracted_date is None and self.ocr_enabled and ocr_text is None:
                        try:
                            pix = page.get_pixmap(dpi=200)
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            ocr_text = pytesseract.image_to_string(img)
                            combined = p_text + "\n" + ocr_text
                            extracted_date = _extract_invoice_date_from_page(combined)
                        except Exception:
                            pass

                self.result = (
                    self.page_idx, first_match,
                    "MATCH" if first_match else "NO_MATCH",
                    extracted_date
                )

        except Exception as e:
            self.result = (self.page_idx, None, f"ERROR: {e}", None)


# ---------------------------------------------------------------------------
# MAIN ENGINE
# ---------------------------------------------------------------------------
class StamperEngine(QObject):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.pool    = QThreadPool()
        self.stop_requested = False
        self._init_tesseract()

    def _init_tesseract(self):
        """Configure Tesseract path (bundled portable install takes priority)."""
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') \
                            else os.path.dirname(sys.executable)
            else:
                base_path = os.path.dirname(os.path.abspath(__file__))

            tess_path_local = os.path.join(base_path, "tesseract", "tesseract.exe")
            if os.path.exists(tess_path_local):
                pytesseract.pytesseract.tesseract_cmd = tess_path_local
                self.signals.log.emit(f"Using Bundled Tesseract: {tess_path_local}")
            else:
                self.signals.log.emit("Bundled Tesseract not found. Using System PATH.")
        except Exception as e:
            self.signals.log.emit(f"Tesseract Init Warning: {e}")

    def merge_pdfs(self, paths):
        """Merge multiple PDFs into one temp file. Returns path or None on error."""
        try:
            self.signals.update_status.emit("Merging files...")
            paths = sorted(list(paths))
            merged_doc = fitz.open()
            for p in paths:
                try:
                    with fitz.open(p) as f:
                        if f.page_count > 0:
                            merged_doc.insert_pdf(f)
                        else:
                            self.signals.log.emit(f"Skipping empty PDF: {os.path.basename(p)}")
                except Exception as ex:
                    self.signals.error.emit(
                        f"FAILED to merge file:\n{os.path.basename(p)}\n\nError: {ex}")
                    return None

            # Installed applications commonly live under Program Files, which is
            # not writable by a standard user. Keep transient merged documents
            # in the user's temporary directory instead of the launch directory.
            temp_dir = os.path.join(tempfile.gettempdir(), "RDC_Stamper_V2")
            os.makedirs(temp_dir, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix="_merged_temp_", suffix=".pdf", dir=temp_dir
            )
            os.close(fd)
            os.remove(temp_name)  # PyMuPDF expects the destination not to exist.

            merged_doc.save(temp_name, garbage=4, deflate=True)
            merged_doc.close()
            self.signals.log.emit(f"Merged {len(paths)} files to {temp_name}")
            return temp_name
        except Exception as e:
            self.signals.error.emit(f"Merge Error: {e}")
            return None

    def load_excel(self, path):
        """Load CSV or Excel file and return a DataFrame."""
        try:
            # Do not coerce the first column in place.  With pandas 3.x,
            # assigning strings back through ``iloc`` to a numeric column raises
            # a dtype error (for example, the numeric "Co Code" column in the
            # production RDC workbook).  Invoice identifiers are normalized by
            # build_targets_from_df when rows are read, so mutating the source
            # DataFrame here is unnecessary.
            if str(path).lower().endswith('.csv'):
                return pd.read_csv(path)
            return pd.read_excel(path)
        except Exception as e:
            self.signals.error.emit(f"Excel Load Error: {e}")
            return None

    def start_processing(self, job_config):
        orchestrator = JobOrchestrator(self, job_config)
        self.pool.start(orchestrator)

    def cancel(self):
        self.stop_requested = True


# ---------------------------------------------------------------------------
# JOB ORCHESTRATOR
# ---------------------------------------------------------------------------
class JobOrchestrator(QRunnable):
    def __init__(self, engine, config):
        super().__init__()
        self.engine  = engine
        self.config  = config
        self.signals = engine.signals

    @Slot()
    def run(self):
        self.engine.stop_requested = False
        pdf_path    = self.config["pdf_path"]
        save_path   = self.config["save_path"]
        targets     = self.config["targets"]      # dict {inv_no: [{"date"},...]} or {}
        skip_blank  = self.config["skip_blank"]
        ocr_enabled = self.config["ocr_enabled"]
        match_dates = self.config.get("match_dates", False)
        txt_data    = self.config["text_data"]

        try:
            # 1. Compile regex from invoice number keys
            target_pattern = None
            inv_no_set = set(targets.keys()) if targets else set()
            if inv_no_set:
                sorted_keys = sorted(inv_no_set, key=len, reverse=True)
                pattern_str = '|'.join(map(re.escape, sorted_keys))
                target_pattern = re.compile(pattern_str)
                self.signals.log.emit(f"Compiled regex for {len(inv_no_set)} invoice numbers.")

            # 2. Get page count
            with fitz.open(pdf_path) as doc:
                total_pages = len(doc)

            self.signals.progress_total.emit(total_pages)
            self.signals.update_status.emit(f"Analyzing {total_pages} pages...")

            # 3. Parallel page analysis (threaded, fully offline)
            import concurrent.futures

            results = []
            max_workers = min(32, (os.cpu_count() or 1) * 4)

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                def analyze_wrapper(pidx):
                    task = PageAnalysisTask(pidx, pdf_path, target_pattern, skip_blank, ocr_enabled)
                    task.run()
                    return task.result

                future_to_page  = {executor.submit(analyze_wrapper, i): i for i in range(total_pages)}
                completed_count = 0
                for future in concurrent.futures.as_completed(future_to_page):
                    if self.engine.stop_requested: break
                    try:
                        res = future.result()
                        results.append(res)
                        completed_count += 1
                        self.signals.progress_value.emit(completed_count)
                    except Exception as e:
                        self.signals.log.emit(f"Page Error: {e}")

            if self.engine.stop_requested:
                self.signals.update_status.emit("Stopped.")
                self.signals.finished.emit("Process stopped by user.")
                return

            # 4. Sort results by page order
            self.signals.update_status.emit("Verifying invoices...")
            results.sort(key=lambda x: x[0])

            # Tracking state
            seen_tuples      = set()   # (inv_no, date_str) already stamped
            pages_to_keep    = []
            duplicates_count = 0
            report_rows      = []
            found_inv_nos    = set()   # all invoice nos seen anywhere in the PDF

            for page_idx, match, status, pdf_date in results:
                if status == "SKIPPED_BLANK":
                    continue
                if status.startswith("OCR_ERROR") or status.startswith("ERROR"):
                    self.signals.log.emit(f"Page {page_idx + 1}: {status}")
                    continue
                if not match:
                    continue

                # ── No-target mode: stamp every page ──────────────────────
                if match == "ALL":
                    pages_to_keep.append(page_idx)
                    continue

                # ── Target mode ───────────────────────────────────────────
                found_inv_nos.add(match)
                excel_entries = targets.get(match, [])

                # Find the best-matching Excel entry for this page
                matched_entry = None   # (entry_dict, date_ok)

                for entry in excel_entries:
                    e_date = entry.get("date")
                    date_ok = (e_date == pdf_date) if (e_date is not None and pdf_date is not None) else None

                    # Entry passes unless the date is an explicit mismatch
                    if date_ok is not False:
                        matched_entry = (entry, date_ok)
                        if date_ok:
                            break   # Perfect match found — stop searching

                # All entries explicitly failed → pick first to show mismatch detail
                if matched_entry is None and excel_entries:
                    entry   = excel_entries[0]
                    e_date  = entry.get("date")
                    date_ok = (e_date == pdf_date) if (e_date is not None and pdf_date is not None) else None
                    matched_entry = (entry, date_ok)

                if matched_entry is None:
                    # Should not happen in normal flow; stamp defensively
                    pages_to_keep.append(page_idx)
                    continue

                entry, date_ok = matched_entry
                e_date = entry.get("date")

                # Dedup key uses stable Excel values (immune to OCR noise)
                dedup_key = (match, str(e_date))

                if dedup_key in seen_tuples:
                    # ── DUPLICATE ─────────────────────────────────────────
                    duplicates_count += 1
                    report_rows.append({
                        "Invoice No": match,
                        "Excel Date": e_date,
                        "PDF Date":   pdf_date,
                        "Date Match": "DUPLICATE",
                        "Status":     "⚠ Duplicate — Skipped",
                    })
                    continue

                seen_tuples.add(dedup_key)

                date_mismatch = (date_ok is False)

                if date_mismatch and match_dates:
                    # ── DATE MISMATCH, Match Dates enabled — do NOT stamp ─
                    final_status = "✗ Date Mismatch"
                elif date_mismatch:
                    # ── DATE MISMATCH, Match Dates disabled — stamp anyway
                    final_status = "⚠ Stamped (Date Mismatch)"
                    pages_to_keep.append(page_idx)
                else:
                    # ── VERIFIED (or unverifiable date) — stamp ───────────
                    final_status = "✓ Verified" if date_ok else "⚠ Partial (Date?)"
                    pages_to_keep.append(page_idx)

                report_rows.append({
                    "Invoice No": match,
                    "Excel Date": e_date,
                    "PDF Date":   pdf_date,
                    "Date Match": ("✓" if date_ok else ("✗" if date_ok is False else "?")),
                    "Status":     final_status,
                })

            # 5. Add "Not Found" rows for targets missing entirely from the PDF
            if targets:
                for inv_no, entries in targets.items():
                    if inv_no not in found_inv_nos:
                        for entry in entries:
                            report_rows.append({
                                "Invoice No": inv_no,
                                "Excel Date": entry.get("date"),
                                "PDF Date":   None,
                                "Date Match": "N/A",
                                "Status":     "✗ Not Found in PDF",
                            })

            if not pages_to_keep:
                self.signals.error.emit(
                    "No verified matches found. No output PDF generated.\n"
                    "Check the report for mismatch details.")
                # Still save the report so the user can diagnose
                if targets and report_rows:
                    rep_df   = pd.DataFrame(report_rows)
                    rep_path = os.path.splitext(save_path)[0] + "_Report.xlsx"
                    rep_df.to_excel(rep_path, index=False)
                    self.signals.log.emit(f"Report saved: {rep_path}")
                return

            # 6. Stamp matched pages
            self.signals.update_status.emit(f"Stamping {len(pages_to_keep)} pages...")
            self.signals.progress_total.emit(len(pages_to_keep))

            doc       = fitz.open(pdf_path)
            font_helv = fitz.Font("helv")
            stamped_count = 0

            for p_idx in pages_to_keep:
                if self.engine.stop_requested: break
                if txt_data["content"]:
                    page = doc[p_idx]
                    rect = page.cropbox
                    tx   = rect.x0 + (txt_data["rel_x"] * rect.width)
                    ty   = rect.y0 + (txt_data["rel_y"] * rect.height)
                    tb   = ty + (txt_data["fs"] * font_helv.ascender)
                    page.insert_text(
                        fitz.Point(tx, tb),
                        txt_data["content"],
                        fontsize=txt_data["fs"],
                        color=txt_data["color"]
                    )
                stamped_count += 1
                self.signals.progress_value.emit(stamped_count)

            # 7. Save output PDF
            self.signals.update_status.emit("Saving PDF...")
            doc.select(pages_to_keep)
            file_size_mb  = os.path.getsize(pdf_path) / (1024 * 1024)
            garbage_level = 0 if file_size_mb > 100 else 4
            deflate_opt   = False if file_size_mb > 100 else True
            doc.save(save_path, garbage=garbage_level, deflate=deflate_opt)
            doc.close()

            # 8. Save verification report
            if targets and report_rows:
                rep_df   = pd.DataFrame(report_rows)
                rep_path = os.path.splitext(save_path)[0] + "_Report.xlsx"
                rep_df.to_excel(rep_path, index=False)
                self.signals.log.emit(f"Report saved: {rep_path}")

            # Counts for summary
            mismatch_count = sum(
                1 for r in report_rows
                if r["Status"].startswith("✗") and "Not Found" not in r["Status"]
            )
            not_found_count = sum(
                1 for r in report_rows if "Not Found" in r["Status"]
            )

            msg = (
                f"Completed!\n\n"
                f"✓  Stamped:            {len(pages_to_keep)} pages\n"
                f"⚠  Duplicates Skipped: {duplicates_count}\n"
                f"✗  Mismatches:         {mismatch_count}\n"
                f"✗  Not Found in PDF:   {not_found_count}\n\n"
                f"See the _Report.xlsx for full details."
            )
            self.signals.finished.emit(msg)

        except Exception as e:
            self.signals.error.emit(f"Critical Error: {e}")
