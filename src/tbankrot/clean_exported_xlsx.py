from pathlib import Path
from typing import Union

import pandas as pd


def clean_exported_xlsx(
    input_path: Union[str, Path] = "debug/lot_export2.xlsx",
    output_path: Union[str, Path] = None,
) -> str:
    """
    Clean the exported XLSX file by removing specific rows and columns.

    Args:
        input_path: Path to the input XLSX file
        output_path: Path to save the cleaned file. If None, uses input_path with '_cleaned' suffix.

    Returns:
        Path to the cleaned file
    """
    # Read the Excel file
    print(f"Reading file: {input_path}")
    df = pd.read_excel(input_path)
    
    # Diagnostic logging
    print(f"Original DataFrame shape: {df.shape}")
    print(f"Original columns: {list(df.columns)}")
    
    # Check for markers and financials columns specifically
    if 'markers' in df.columns:
        non_empty_markers = df['markers'].notna() & (df['markers'] != '')
        print(f"Markers column - non-empty rows: {non_empty_markers.sum()}/{len(df)}")
    else:
        print("Markers column not found")
        
    if 'financials' in df.columns:
        non_empty_financials = df['financials'].notna() & (df['financials'] != '')
        print(f"Financials column - non-empty rows: {non_empty_financials.sum()}/{len(df)}")
    else:
        print("Financials column not found")
    
    # Log first few rows of problematic columns for inspection
    problematic_cols = ['markers', 'financials']
    for col in problematic_cols:
        if col in df.columns:
            print(f"\nFirst 3 values in {col} column:")
            for i, val in enumerate(df[col].head(3)):
                print(f"  Row {i}: type={type(val)}, value={repr(val)[:100]}...")

    # Filter out rows where auction_status is "Прием заявок завершен" or "Торги закончились"
    before_filter_rows = len(df)
    df = df[~df["auction_status"].isin(["Прием заявок завершен", "Торги закончились"])]
    print(f"After auction_status filter: {len(df)} rows (removed {before_filter_rows - len(df)} rows)")
    
    # Check markers and financials after filtering
    if 'markers' in df.columns:
        non_empty_markers_after = df['markers'].notna() & (df['markers'] != '')
        print(f"Markers after filtering - non-empty: {non_empty_markers_after.sum()}/{len(df)}")
    if 'financials' in df.columns:
        non_empty_financials_after = df['financials'].notna() & (df['financials'] != '')
        print(f"Financials after filtering - non-empty: {non_empty_financials_after.sum()}/{len(df)}")

    # Drop specified columns if they exist
    columns_to_drop = [
        "individuals",
        "empty_inn_but_nonempty_orgn",
        "empty_individuals_but_no_inn_orgn",
    ]
    cols_dropped = [col for col in columns_to_drop if col in df.columns]
    print(f"Dropping columns: {cols_dropped}")
    if cols_dropped:
        df = df.drop(columns=cols_dropped)
    
    # Final check before saving
    print(f"Final DataFrame shape: {df.shape}")
    if 'markers' in df.columns:
        final_markers_count = df['markers'].notna() & (df['markers'] != '')
        print(f"Final markers non-empty: {final_markers_count.sum()}/{len(df)}")
    if 'financials' in df.columns:
        final_financials_count = df['financials'].notna() & (df['financials'] != '')
        print(f"Final financials non-empty: {final_financials_count.sum()}/{len(df)}")

    # Determine output path
    if output_path is None:
        output_path = Path(input_path).parent / f"{Path(input_path).stem}_cleaned.xlsx"
    else:
        output_path = Path(output_path)

    # Save the cleaned DataFrame
    print(f"Saving to: {output_path}")
    df.to_excel(output_path, index=False)
    print("File saved successfully")

    return str(output_path)


def filter_mismatch_rows(
    input_path: Union[str, Path] = "debug/lot_export2.xlsx",
    output_path: Union[str, Path] = None,
) -> str:
    """
    Filter the exported XLSX file to keep only rows where either
    empty_individuals_but_no_inn_orgn OR empty_inn_but_nonempty_orgn is True/TRUE/1.

    Args:
        input_path: Path to the input XLSX file
        output_path: Path to save the filtered file. If None, uses input_path with '_filtered' suffix.

    Returns:
        Path to the filtered file
    """
    # Read the Excel file
    df = pd.read_excel(input_path)

    # Define the columns to check
    col1 = "empty_individuals_but_no_inn_orgn"
    col2 = "empty_inn_but_nonempty_orgn"

    # Check if columns exist
    if col1 not in df.columns or col2 not in df.columns:
        raise ValueError(f"Required columns {col1} and {col2} not found in the file.")

    # Create a mask for rows where either column evaluates to True
    # Handle True, TRUE, 1 as truthy values
    mask1 = df[col1].astype(str).str.upper().isin(["TRUE", "1"]) | (df[col1] == True)
    mask2 = df[col2].astype(str).str.upper().isin(["TRUE", "1"]) | (df[col2] == True)

    # Keep rows where either condition is true
    filter_mask = mask1 | mask2
    df_filtered = df[filter_mask]

    # Determine output path
    if output_path is None:
        output_path = Path(input_path).parent / f"{Path(input_path).stem}_filtered.xlsx"
    else:
        output_path = Path(output_path)

    # Save the filtered DataFrame
    df_filtered.to_excel(output_path, index=False)

    return str(output_path)


if __name__ == "__main__":
    cleaned_path = clean_exported_xlsx("debug/lot_export2_filtered.xlsx")
    # cleaned_path = filter_mismatch_rows()
    print(f"Cleaned file saved to: {cleaned_path}")