from pathlib import Path
import pandas as pd


def find_file(raw_dir: str | Path, prefix: str) -> Path:
    raw_dir = Path(raw_dir)
    matches = list(raw_dir.glob(f"{prefix}*.xlsx"))
    if not matches:
        raise FileNotFoundError(f"Cannot find Excel file with prefix: {prefix} in {raw_dir}")
    return matches[0]


def read_excel_by_prefix(raw_dir: str | Path, prefix: str) -> pd.DataFrame:
    file_path = find_file(raw_dir, prefix)
    return pd.read_excel(file_path)
