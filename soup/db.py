"""Shared paths and the DuckDB connection the build runs on."""

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
PRIVATE = ROOT / "private"
SOUP = ROOT / "data" / "soup.sqlite"

TSV = "delim='\t', header=true, quote='', escape='', nullstr='\\N', all_varchar=true"

# Title normalisation used by every matcher: lower case, no accents, "&" as
# "and", no leading article, then only letters and digits ("Spider-Man" and
# "Spiderman" are the same key).
# clean_title drops bracketed notes and DVD edition wording
# ("Heat: Special Edition", "Shrek (Full-screen)").
MACROS = r"""
create or replace macro norm(s) as nullif(replace(regexp_replace(
    regexp_replace(
        regexp_replace(lower(strip_accents(replace(s, '&', ' and '))), '[''’`]', '', 'g'),
        '[^a-z0-9]+', ' ', 'g'),
    '^\s*(the|a|an)\s+', ''), ' ', ''), '');
create or replace macro clean_title(s) as regexp_replace(regexp_replace(s,
    '\s*[\[(][^\])]*[\])]', '', 'g'),
    '(?i)\s*[:\-–]\s*(the\s+)?(special|collector''?s|extended|platinum|anniversary|deluxe|ultimate|limited|definitive|unrated|uncut|director''?s|widescreen|full[- ]?screen|remastered|restored|theatrical|\d+(st|nd|rd|th)\s+anniversary)\b.*$', '');
create or replace macro norm_name(s) as nullif(trim(regexp_replace(
    regexp_replace(lower(strip_accents(s)), '[.''’`]', '', 'g'), '[^a-z0-9]+', ' ', 'g')), '');
"""


def connect() -> duckdb.DuckDBPyConnection:
    WORK.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(WORK / "build.duckdb"))
    con.execute(f"""
        set memory_limit = '10GB';
        set threads = 10;
        set temp_directory = '{WORK / "tmp"}';
        set enable_progress_bar = false;
        set preserve_insertion_order = false;
    """)
    con.execute(MACROS)
    return con
