#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Timestamp: "2025-07-16 14:00:04 (ywatanabe)"
# File: /ssh:sp:/home/ywatanabe/proj/scitex_repo/src/scitex/db/_sqlite3/_delete_duplicates.py
# ----------------------------------------
import os
import sys

__FILE__ = __file__
__DIR__ = os.path.dirname(__FILE__)
# ----------------------------------------
# Time-stamp: "2024-11-11 14:16:58 (ywatanabe)"

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Union

import pandas as pd
import scitex_logging as slogging

log = slogging.getLogger(__name__)

"""
Functionality:
    - Deletes duplicate entries from an SQLite database table
Input:
    - SQLite database file path, table name, columns to consider for duplicates
Output:
    - Updated SQLite database with duplicates removed
Prerequisites:
    - sqlite3, pandas, tqdm, scitex
"""


def _sort_db(cursor: sqlite3.Cursor, table_name: str, columns: List[str]) -> None:
    """
    Sorts the database table based on the specified columns.

    Parameters
    ----------
    cursor : sqlite3.Cursor
        The cursor object for executing SQL commands.
    table_name : str
        The name of the table to be sorted.
    columns : List[str]
        The list of column names to sort by, in order of priority.

    Example
    -------
    >>> conn = sqlite3.connect('example.db')
    >>> cursor = conn.cursor()
    >>> _sort_db(cursor, 'my_table', ['column1', 'column2'])
    >>> conn.commit()
    >>> conn.close()
    """
    columns_str = ", ".join(columns)
    temp_table = f"{table_name}_temp"

    cursor.execute(
        f"CREATE TABLE {temp_table} AS SELECT * FROM {table_name} ORDER BY {columns_str}"
    )
    cursor.execute(f"DROP TABLE {table_name}")
    cursor.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")


# def _determine_columns(
#     cursor: sqlite3.Cursor,
#     table_name: str,
#     columns: Union[str, List[str]],
#     include_blob: bool,
# ) -> List[str]:
#     cursor.execute(f"PRAGMA table_info({table_name})")
#     table_info = cursor.fetchall()
#     all_columns = [col[1] for col in table_info]
#     column_types = {col[1]: col[2] for col in table_info}

#     if columns == "all":
#         columns = (
#             all_columns
#             if include_blob
#             else [
#                 col
#                 for col in all_columns
#                 if column_types[col].lower() != "blob"
#             ]
#         )
#     elif isinstance(columns, str):
#         columns = [columns]

#     columns_str = ", ".join(columns)
#     print(f"Columns considered for duplicates: {columns_str}")

#     return columns


def _determine_columns(
    cursor: sqlite3.Cursor,
    table_name: str,
    columns: Union[str, List[str]],
    include_blob: bool,
) -> List[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    table_info = cursor.fetchall()
    all_columns = [col[1] for col in table_info]
    column_types = {col[1]: col[2] for col in table_info}
    # PRAGMA columns: (cid, name, type, notnull, dflt_value, pk).
    pk_columns = {col[1] for col in table_info if col[5]}

    if columns == "all":
        # Exclude PK columns — by definition unique, so they prevent any row
        # from matching another and 'all' would silently dedup nothing.
        columns = [col for col in all_columns if col not in pk_columns]
        # Exclude blob columns unless caller opted in.
        if not include_blob:
            columns = [col for col in columns if column_types[col].lower() != "blob"]
        # Exclude timestamp columns (e.g. created_at, updated_at).
        columns = [col for col in columns if not col.endswith("_at")]
    elif isinstance(columns, str):
        columns = [columns]

    columns_str = ", ".join(columns)
    log.info(f"Columns considered for duplicates: {columns_str}")

    return columns


def _fetch_as_df(
    cursor: sqlite3.Cursor, columns: List[str], table_name: str
) -> pd.DataFrame:
    log.info("\nFetching all database entries...")
    columns_str = ", ".join(columns)
    query = f"SELECT {columns_str} FROM {table_name}"
    cursor.execute(query)
    df_entries = cursor.fetchall()
    return pd.DataFrame(df_entries, columns=columns)


def _find_duplicated(df: pd.DataFrame) -> pd.DataFrame:
    df_duplicated = df[df.duplicated(keep="first")].copy()
    duplication_rate = len(df_duplicated) / (len(df) - len(df_duplicated))
    log.info(f"\n{100 * duplication_rate:.2f}% of data was duplicated. Cleaning up...")
    log.debug(f"\nOriginal entries:\n{df.head()}")
    log.debug(f"\nDuplicated entries:\n{df_duplicated.head()}")
    return df_duplicated


def verify_duplicated_index(
    cursor: sqlite3.Cursor,
    duplicated_row: pd.Series,
    table_name: str,
    dry_run: bool,
) -> Tuple[str, bool]:
    """Check if entry to delete is the one intended"""
    columns = list(duplicated_row.index)
    columns_str = ", ".join(columns)

    where_conditions = " AND ".join([f"{col} = ?" for col in columns])
    select_query = f"""
        SELECT {columns_str}
        FROM {table_name}
        WHERE {where_conditions}
    """
    cursor.execute(select_query, tuple(duplicated_row))
    entries = cursor.fetchall()

    is_verified = len(entries) >= 1

    if dry_run:
        # PS-220 exception: --dry-run bodies are machine-readable data
        # transport and stay on stdout (sys.stdout.write is not flagged).
        sys.stdout.write(f"Expected duplicate entry: {tuple(duplicated_row)}\n")
        sys.stdout.write(f"Found entries: {entries}\n")
        sys.stdout.write(
            f"Verification {'succeeded' if is_verified else 'failed'}\n"
        )

    return select_query, is_verified


def _delete_entry(
    cursor: sqlite3.Cursor,
    duplicated_row: pd.Series,
    table_name: str,
    dry_run: bool = True,
) -> None:
    select_query, is_verified = verify_duplicated_index(
        cursor, duplicated_row, table_name, dry_run
    )
    if is_verified:
        # Build DELETE directly: `select_query.replace("SELECT", "DELETE")`
        # produced `DELETE col1, col2 FROM ...` which is not valid SQLite.
        columns = list(duplicated_row.index)
        where_conditions = " AND ".join([f"{col} = ?" for col in columns])
        delete_query = f"DELETE FROM {table_name} WHERE {where_conditions} LIMIT 1"
        if dry_run:
            # PS-220 exception: --dry-run bodies stay on stdout.
            sys.stdout.write(f"[DRY RUN] Would delete entry:\n{duplicated_row}\n")
        else:
            try:
                cursor.execute(delete_query, tuple(duplicated_row))
            except sqlite3.OperationalError:
                # Older SQLite builds compiled without ENABLE_UPDATE_DELETE_LIMIT
                # — fall back to a rowid-based delete that hits one row only.
                cursor.execute(
                    f"DELETE FROM {table_name} WHERE rowid = ("
                    f"SELECT rowid FROM {table_name} WHERE {where_conditions} "
                    f"LIMIT 1)",
                    tuple(duplicated_row),
                )
            log.info(f"Deleted entry:\n{duplicated_row}")
    else:
        log.info(f"Skipping entry (not found or already deleted):\n{duplicated_row}")


def delete_sqlite3_duplicates(
    lpath_db: str,
    table_name: str,
    columns: Union[str, List[str]] = "all",
    include_blob: bool = False,
    chunk_size: int = 10_000,
    dry_run: bool = True,
) -> Tuple[Optional[int], Optional[int]]:
    """Return row and duplicate counts, previewing read-only by default.

    Preview opens an existing SQLite file without rebuilding tables. Apply mode
    deletes duplicate native ROWIDs in one transaction, preserving table schema.
    Apply enables foreign keys and runs normal DELETE triggers/cascade actions.
    Failures are logged and return ``(None, None)``.
    """
    conn = None
    try:
        if dry_run:
            conn = sqlite3.connect(
                Path(lpath_db).absolute().as_uri() + "?mode=ro", uri=True
            )
        else:
            conn = sqlite3.connect(
                Path(lpath_db).absolute().as_uri() + "?mode=rw", uri=True
            )
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
        cursor = conn.cursor()

        columns = _determine_columns(cursor, table_name, columns, include_blob)
        columns_str = ", ".join(columns)

        if dry_run:
            total_rows, total_unique = cursor.execute(
                "SELECT COALESCE(SUM(group_size), 0), COUNT(*) "
                f"FROM (SELECT COUNT(*) AS group_size FROM {table_name} "
                f"GROUP BY {columns_str})"
            ).fetchone()
            total_duplicates = total_rows - total_unique
            # PS-220 exception: --dry-run bodies stay on stdout.
            sys.stdout.write(
                f"[DRY RUN] Would execute deduplication based on: {columns_str}\n"
            )
            log.info(f"Total rows processed: {total_rows}")
            log.info(f"Total unique rows: {total_unique}")
            log.info(f"Total duplicates identified: {total_duplicates}")
            return total_rows, total_duplicates

        with conn:
            table_sql = '"' + table_name.replace('"', '""') + '"'
            target = cursor.execute(
                "SELECT type FROM sqlite_master WHERE name=? COLLATE NOCASE",
                (table_name,),
            ).fetchone()
            if not target or target[0] != "table" or table_name.lower().startswith("sqlite_"):
                raise ValueError("Apply requires an application table with a native ROWID")
            table_info = cursor.execute(f"PRAGMA table_info({table_sql})").fetchall()
            ascii_case = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
            available = {column[1].translate(ascii_case): column[1] for column in table_info}
            if not columns or any(column.translate(ascii_case) not in available for column in columns):
                raise ValueError("Deduplication columns must name existing table columns")
            rowid_alias = next(
                (alias for alias in ("rowid", "_rowid_", "oid") if alias not in available),
                None,
            )
            if rowid_alias is None:
                raise ValueError("Cannot safely address native ROWIDs: all aliases are shadowed")
            # A native lookup rejects WITHOUT ROWID tables before any deletion.
            cursor.execute(f"SELECT {rowid_alias} FROM {table_sql} LIMIT 0")
            group_columns = ", ".join(
                '"' + available[column.translate(ascii_case)].replace('"', '""') + '"'
                for column in columns
            )
            total_rows = cursor.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0]
            cursor.execute(
                f"DELETE FROM {table_sql} WHERE {rowid_alias} NOT IN "
                f"(SELECT MIN({rowid_alias}) FROM {table_sql} GROUP BY {group_columns})"
            )
            total_duplicates = cursor.rowcount
            total_unique = cursor.execute(f"SELECT COUNT(*) FROM {table_sql}").fetchone()[0]

        log.info(f"Total rows processed: {total_rows}")
        log.info(f"Total rows remaining: {total_unique}")
        log.info(f"Total duplicates removed: {total_duplicates}")

        return total_rows, total_duplicates

    except Exception as error:
        log.error(f"An error occurred: {error}")
        return None, None

    finally:
        if conn is not None:
            conn.close()


# EOF
