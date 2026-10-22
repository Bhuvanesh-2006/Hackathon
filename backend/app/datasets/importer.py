"""Import CSV / XLSX files into an isolated, versioned DuckDB file per dataset.

Pipeline (each step bounded in memory):
  1. The upload is streamed to a temp file under data/uploads/ with a size limit and SHA-256.
  2. Extension and content must agree: .csv must decode as text (UTF-8, else Windows-1252 with a
     finding); .xlsx must be a ZIP with an Excel workbook part. Nothing in the file is executed.
  3. XLSX: the first worksheet with data is streamed (openpyxl read-only, cached values only) into
     a UTF-8 CSV. Other sheets are reported, not imported.
  4. The header is parsed with the csv module. Empty, duplicate or unsafe headers are mapped to
     sanitised identifiers; every change is reported as a finding.
  5. DuckDB loads all columns as text (malformed rows fail the import with the DuckDB message),
     then each column is profiled: missing values, numeric / integer / boolean / date parse rates.
     A type is applied only when every non-empty value parses; ambiguous day/month dates and
     partly numeric columns stay text and are reported. Empty cells are stored as NULL.
  6. The table is built in <version>.duckdb.tmp and only renamed into place after success, so a
     failed (re-)import never touches the dataset's current version.
"""
from __future__ import annotations

import codecs
import csv
import hashlib
import io
import re
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, BinaryIO

import duckdb

from app.config import get_settings

ALLOWED_EXTENSIONS = {".csv": "csv", ".xlsx": "xlsx"}
DATE_FORMATS = [
    ("%Y-%m-%d", "ymd"), ("%Y-%m-%d %H:%M:%S", "ymd"), ("%Y-%m-%dT%H:%M:%S", "ymd"), ("%Y-%m-%d %H:%M", "ymd"),
    ("%Y/%m/%d", "ymd"), ("%d/%m/%Y", "dmy"), ("%d/%m/%Y %H:%M", "dmy"), ("%d/%m/%Y %H:%M:%S", "dmy"),
    ("%m/%d/%Y", "mdy"), ("%m/%d/%Y %H:%M", "mdy"), ("%m/%d/%Y %H:%M:%S", "mdy"), ("%d-%m-%Y", "dmy"),
    ("%d.%m.%Y", "dmy"),
]
CHUNK = 1024 * 1024


class ImportFailed(ValueError):
    def __init__(self, message: str, findings: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.findings = findings or []


# ----------------------------------------------------------------------------- upload handling
def save_upload(stream: BinaryIO, filename: str) -> tuple[Path, int, str, str]:
    """Stream to a unique temp path. Returns (path, size, sha256, format)."""
    settings = get_settings()
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ImportFailed(f"Unsupported file type '{ext or 'none'}'. Supported: .csv, .xlsx.")
    limit = settings.max_upload_mb * 1024 * 1024
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.uploads_dir / f"upload_{uuid.uuid4().hex}{ext}"
    digest = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise ImportFailed(f"File exceeds the {settings.max_upload_mb} MB upload limit.")
                digest.update(chunk)
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise ImportFailed("The file is empty.")
    return dest, size, digest.hexdigest(), ALLOWED_EXTENSIONS[ext]


def _to_utf8_csv(src: Path, findings: list[str]) -> Path:
    """Verify the CSV decodes as UTF-8 (streaming); otherwise transcode from Windows-1252."""
    head = src.read_bytes()[:4096] if src.stat().st_size < 4096 else open(src, "rb").read(4096)
    if b"\x00" in head:
        raise ImportFailed("The file does not look like text (it contains binary data). Is it really a CSV?")
    if head.startswith(b"PK\x03\x04"):
        raise ImportFailed("The file is a ZIP/Excel file with a .csv extension. Upload it as .xlsx.")
    decoder = codecs.getincrementaldecoder("utf-8-sig")()
    try:
        with open(src, "rb") as f:
            while chunk := f.read(CHUNK):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return src
    except UnicodeDecodeError:
        findings.append("The file is not valid UTF-8; it was decoded as Windows-1252. Check accented characters.")
        out = src.with_suffix(".utf8.csv")
        with open(src, "r", encoding="cp1252", errors="replace", newline="") as fin, \
                open(out, "w", encoding="utf-8", newline="") as fout:
            shutil.copyfileobj(fin, fout, CHUNK)
        return out


def _xlsx_to_csv(src: Path, findings: list[str]) -> Path:
    settings = get_settings()
    with open(src, "rb") as f:
        if f.read(4) != b"PK\x03\x04":
            raise ImportFailed("The file has an .xlsx extension but is not an Excel workbook.")
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            if "xl/workbook.xml" not in names:
                raise ImportFailed("The ZIP file is not an Excel workbook (xl/workbook.xml missing).")
            if any(n.lower().endswith("vbaproject.bin") for n in names):
                raise ImportFailed("Workbooks with macros are not accepted.")
            if sum(i.file_size for i in z.infolist()) > settings.max_upload_mb * 1024 * 1024 * 20:
                raise ImportFailed("The workbook expands to an unexpectedly large size and was rejected.")
    except zipfile.BadZipFile as exc:
        raise ImportFailed("The Excel file is corrupted or not a valid .xlsx.") from exc

    import openpyxl

    try:
        wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    except Exception as exc:
        raise ImportFailed(f"The Excel file could not be read: {type(exc).__name__}.") from exc
    out = src.with_suffix(".sheet.csv")
    try:
        chosen = None
        for ws in wb.worksheets:
            first = next(ws.iter_rows(values_only=True, max_row=1), None)
            if first and any(v not in (None, "") for v in first):
                chosen = ws
                break
        if chosen is None:
            raise ImportFailed("The workbook has no worksheet with data.")
        others = [ws.title for ws in wb.worksheets if ws is not chosen]
        if others:
            findings.append(f"Imported worksheet '{chosen.title}'. Other worksheets were not imported: {', '.join(others)}.")
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            for row in chosen.iter_rows(values_only=True):
                w.writerow(["" if v is None else (v.isoformat(sep=" ") if hasattr(v, "isoformat") and not isinstance(v, str) else v)
                            for v in row])
    finally:
        wb.close()
    return out


# ----------------------------------------------------------------------------- identifiers
_RESERVED: set[str] | None = None


def _reserved() -> set[str]:
    global _RESERVED
    if _RESERVED is None:
        con = duckdb.connect()
        try:
            _RESERVED = {r[0].lower() for r in con.execute(
                "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'").fetchall()}
        finally:
            con.close()
    return _RESERVED


def safe_identifier(name: str, index: int) -> str:
    s = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip()).strip("_").lower()[:60]
    if not s:
        s = f"column_{index + 1}"
    if s[0].isdigit():
        s = "c_" + s
    if s in _reserved():
        s = s + "_col"
    return s


def map_headers(headers: list[str], findings: list[str]) -> list[dict[str, str]]:
    used: set[str] = set()
    seen_original: dict[str, int] = {}
    out = []
    for i, raw in enumerate(headers):
        original = (raw or "").strip()
        if not original:
            findings.append(f"Column {i + 1} has an empty header; it was named column_{i + 1}.")
        key = original.lower()
        if original and key in seen_original:
            findings.append(f"Duplicate column header '{original}' (columns {seen_original[key] + 1} and {i + 1}); "
                            "the later one was renamed with a numeric suffix.")
        seen_original.setdefault(key, i)
        base = safe_identifier(original, i)
        name, n = base, 2
        while name in used:
            name = f"{base}_{n}"
            n += 1
        used.add(name)
        if original and name != original:
            pass  # recorded per column as original_name; not every case is a problem worth a finding
        out.append({"name": name, "original_name": original or f"column_{i + 1}"})
    return out


# ----------------------------------------------------------------------------- import
def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def build_dataset(csv_path: Path, target: Path, findings: list[str]) -> dict[str, Any]:
    settings = get_settings()
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(65536)
    if not sample.strip():
        raise ImportFailed("The file is empty.")
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    header = next(csv.reader(io.StringIO(sample), delimiter=delim), [])
    if not header or all(not h.strip() for h in header):
        raise ImportFailed("No header row was found.")
    if len(header) > settings.max_import_columns:
        raise ImportFailed(f"The file has {len(header)} columns; the limit is {settings.max_import_columns}.")
    if len(header) == 1 and delim == ",":
        findings.append("Only one column was detected. If the file uses another separator, check the preview.")
    cols = map_headers(header, findings)

    tmp = target.with_suffix(".duckdb.tmp")
    tmp.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        col_struct = "{" + ", ".join(f"'{c['name']}': 'VARCHAR'" for c in cols) + "}"
        path_lit = "'" + str(csv_path).replace("'", "''") + "'"
        delim_lit = "'" + ("\\t" if delim == "\t" else delim.replace("'", "''")) + "'"
        try:
            con.execute(f"""CREATE TABLE raw AS SELECT * FROM read_csv({path_lit}, header = false, skip = 1,
                            delim = {delim_lit}, quote = '"', escape = '"', columns = {col_struct},
                            auto_detect = false, strict_mode = true, null_padding = false)""")
        except duckdb.Error as exc:
            msg = str(exc).strip().splitlines()[0][:300]
            raise ImportFailed(f"The file could not be parsed: {msg}") from exc
        total = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
        if total == 0:
            raise ImportFailed("The file has a header but no data rows.")

        profiles = []
        for c in cols:
            q = _q(c["name"])
            v = f"NULLIF(TRIM({q}), '')"
            date_exprs = ", ".join(f"COUNT(TRY_STRPTIME({v}, '{fmt}'))" for fmt, _ in DATE_FORMATS)
            row = con.execute(f"""SELECT COUNT({v}), COUNT(*) FILTER (WHERE regexp_full_match({v}, '[+-]?[0-9]{{1,18}}')),
                                  COUNT(TRY_CAST({v} AS DOUBLE)),
                                  COUNT(*) FILTER (WHERE lower({v}) IN ('true','false','yes','no')),
                                  COUNT(*) FILTER (WHERE regexp_full_match({v}, '0[0-9]+')),
                                  approx_count_distinct({v}), {date_exprs} FROM raw""").fetchone()
            nonempty, int_ok, dbl_ok, bool_ok, leading_zero, distinct = row[:6]
            date_ok = row[6:]
            samples = [r[0] for r in con.execute(f"SELECT DISTINCT {v} FROM raw WHERE {v} IS NOT NULL LIMIT 3").fetchall()]
            missing = total - nonempty
            col_type, expr, role, notes = "VARCHAR", f"NULLIF({q}, '')", "text", []
            if nonempty == 0:
                notes.append("empty column")
            elif int_ok == nonempty and leading_zero == 0:
                col_type, expr, role = "BIGINT", f"CAST({v} AS BIGINT)", "numeric"
            elif dbl_ok == nonempty and leading_zero == 0:
                col_type, expr, role = "DOUBLE", f"CAST({v} AS DOUBLE)", "numeric"
            elif bool_ok == nonempty:
                col_type, expr, role = "BOOLEAN", f"lower({v}) IN ('true','yes')", "boolean"
            else:
                full = [(fmt, order) for (fmt, order), ok in zip(DATE_FORMATS, date_ok) if ok == nonempty]
                orders = {o for _, o in full}
                if full and not ({"dmy", "mdy"} <= orders):
                    fmt = full[0][0]
                    has_time = "%H" in fmt
                    col_type = "TIMESTAMP" if has_time else "DATE"
                    expr = f"CAST(STRPTIME({v}, '{fmt}') AS {col_type})"
                    role = "date"
                    notes.append(f"parsed as {col_type.lower()} using format {fmt}")
                elif full:
                    notes.append("dates are ambiguous (day/month order cannot be determined); kept as text")
                    role = "date (ambiguous, text)"
                    findings.append(f"Column '{c['original_name']}': dates such as {samples[0]!r} could be day-first or "
                                    "month-first, so they were kept as text.")
                elif leading_zero and int_ok == nonempty:
                    notes.append("numbers with leading zeros (likely codes); kept as text")
                elif dbl_ok and dbl_ok >= 0.5 * nonempty:
                    bad = [r[0] for r in con.execute(f"SELECT DISTINCT {v} FROM raw WHERE {v} IS NOT NULL AND TRY_CAST({v} AS DOUBLE) IS NULL LIMIT 3").fetchall()]
                    findings.append(f"Column '{c['original_name']}' is {100 * dbl_ok / nonempty:.0f}% numeric but {nonempty - dbl_ok:,} values are not numbers "
                                    f"(e.g. {', '.join(repr(b) for b in bad)}); it was kept as text.")
                    notes.append("mostly numeric; kept as text")
                elif max(date_ok) and max(date_ok) >= 0.5 * nonempty:
                    findings.append(f"Column '{c['original_name']}' looks like a date but {nonempty - max(date_ok):,} values do not "
                                    "parse; it was kept as text.")
                    notes.append("mostly dates; kept as text")
            if missing:
                findings.append(f"Column '{c['original_name']}': {missing:,} missing values ({100 * missing / total:.1f}%).")
            profiles.append({**c, "type": col_type, "role": role, "missing": missing,
                             "missing_pct": round(100 * missing / total, 2), "approx_distinct": distinct,
                             "samples": [str(s)[:60] for s in samples], "notes": notes, "_expr": expr})

        select = ", ".join(f"{p['_expr']} AS {_q(p['name'])}" for p in profiles)
        con.execute(f"CREATE TABLE data AS SELECT {select} FROM raw")
        con.execute("DROP TABLE raw")
        dupes = con.execute("SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM data)) FROM data").fetchone()[0]
        if dupes:
            findings.append(f"{dupes:,} rows are exact duplicates of another row (kept as imported).")
        con.execute("CHECKPOINT")
    except ImportFailed:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        con.close()
        tmp.unlink(missing_ok=True)
        raise ImportFailed(f"Import failed: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}") from exc
    con.close()
    tmp.replace(target)  # atomic swap into the new version path
    for p in profiles:
        p.pop("_expr")
    return {"row_count": total, "column_count": len(profiles), "columns": profiles, "support": analysis_support(profiles)}


def analysis_support(columns: list[dict[str, Any]]) -> list[str]:
    numeric = [c for c in columns if c["role"] == "numeric"]
    dates = [c for c in columns if c["role"] == "date"]
    text = [c for c in columns if c["role"] == "text" and c.get("approx_distinct", 0) > 1]
    out = ["Row counts and filtering on any column"]
    if numeric:
        out.append(f"Totals, averages, minimum/maximum of numeric columns ({', '.join(c['name'] for c in numeric[:5])})")
    if numeric and text:
        out.append("Rankings and breakdowns of numeric columns by text categories")
    if dates:
        out.append(f"Trends over time using date columns ({', '.join(c['name'] for c in dates[:3])})")
    names = {c["name"] for c in columns}
    money = [n for n in names if re.search(r"(revenue|sales|amount|total|price|spend)", n)]
    out.append("Monetary metrics only from existing columns: " + (", ".join(sorted(money)) if money else
               "none detected, so revenue/profit questions cannot be answered"))
    return out


def import_upload(raw_path: Path, file_format: str, target: Path, file_size: int, fingerprint: str) -> dict[str, Any]:
    findings: list[str] = []
    work: list[Path] = []
    try:
        csv_path = _xlsx_to_csv(raw_path, findings) if file_format == "xlsx" else _to_utf8_csv(raw_path, findings)
        if csv_path != raw_path:
            work.append(csv_path)
        meta = build_dataset(csv_path, target, findings)
    except ImportFailed as exc:
        exc.findings = findings + exc.findings
        raise
    finally:
        for p in work:
            p.unlink(missing_ok=True)
    meta.update(findings=findings, fingerprint=fingerprint, file_size_bytes=file_size)
    return meta


def preview(db_path: Path, limit: int = 50) -> dict[str, Any]:
    from app.database.connection import run_query

    res = run_query(f"SELECT * FROM data LIMIT {int(limit)}", db_path=db_path, max_rows=limit)
    return {"columns": res.columns, "column_types": res.column_types, "rows": res.rows}
