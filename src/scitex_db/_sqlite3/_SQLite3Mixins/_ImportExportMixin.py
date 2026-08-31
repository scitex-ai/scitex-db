#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Time-stamp: "2024-11-25 01:36:18 (ywatanabe)"
# File: ./scitex_repo/src/scitex/db/_SQLite3Mixins/_ImportExportMixin.py

THIS_FILE = "/home/ywatanabe/proj/scitex_repo/src/scitex/db/_SQLite3Mixins/_ImportExportMixin.py"

from typing import List

import pandas as pd


class _ImportExportMixin:
    """Import/Export functionality"""

    def load_from_csv(
        self,
        table_name: str,
        csv_path: str,
        if_exists: str = "append",
        batch_size: int = 10_000,
        chunk_size: int = 100_000,
    ) -> None:
        with self.transaction():
            try:
                # Determine target table columns so we can drop CSV columns
                # the table doesn't have (e.g. exporting an `id` PRIMARY KEY
                # and importing into a table without that column).
                target_cols = set(self.get_table_schema(table_name)["name"].tolist())
                for chunk in pd.read_csv(csv_path, chunksize=chunk_size):
                    extra = [c for c in chunk.columns if c not in target_cols]
                    if extra:
                        chunk = chunk.drop(columns=extra)
                    chunk.to_sql(
                        table_name,
                        self.conn,
                        if_exists=if_exists,
                        index=False,
                        chunksize=batch_size,
                    )
                    if_exists = "append"
            except FileNotFoundError:
                raise FileNotFoundError(f"CSV file not found: {csv_path}")
            except Exception as err:
                raise ValueError(f"Failed to import from CSV: {err}")

    def save_to_csv(
        self,
        table_name: str,
        output_path: str,
        columns: List[str] = None,
        where: str = None,
        batch_size: int = 10_000,
    ) -> None:
        # When the caller passes ["*"] (or no value), select all columns by
        # leaving columns=None so get_rows emits SELECT * — passing ["*"]
        # would produce SELECT "*" and a CSV with a literal "*" header.
        if columns is None or columns == ["*"]:
            columns = None
        try:
            df = self.get_rows(
                columns=columns,
                table_name=table_name,
                where=where,
                limit=batch_size,
                offset=0,
            )
            df.to_csv(output_path, index=False, mode="w")

            offset = batch_size
            while len(df) == batch_size:
                df = self.get_rows(
                    columns=columns,
                    table_name=table_name,
                    where=where,
                    limit=batch_size,
                    offset=offset,
                )
                if len(df) > 0:
                    df.to_csv(output_path, index=False, mode="a", header=False)
                offset += batch_size
        except PermissionError:
            raise PermissionError(f"Cannot write to: {output_path}")
        except Exception as err:
            raise ValueError(f"Failed to export to CSV: {err}")


# EOF
