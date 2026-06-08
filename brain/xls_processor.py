import pandas as pd
import numpy as np
from datetime import datetime
import os
import logging
from typing import List, Dict, Any, Optional

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class XLSProcessor:
    """
    Engine to process and normalize 'sold items' spreadsheets for KPI studies.
    Handles messy XLS/XLSX formats and aligns them to a time-series format.
    """
    
    def __init__(self, db_connection=None):
        self.db = db_connection
        # Mapping of common messy column names to normalized keys
        self.col_map = {
            'item': ['product', 'item name', 'description', 'menu item', 'sku'],
            'qty': ['quantity', 'sold', 'count', 'amount', 'qty'],
            'price': ['unit price', 'price', 'rate'],
            'total': ['total', 'sales', 'revenue', 'amount total']
        }

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Renames columns based on a fuzzy map to ensure consistency."""
        new_cols = {}
        for col in df.columns:
            col_lower = str(col).lower().strip()
            for norm_key, aliases in self.col_map.items():
                if col_lower in aliases:
                    new_cols[col] = norm_key
                    break
        return df.rename(columns=new_cols)

    def parse_xls(self, file_path: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        Extracts data from XLS/XLSX. 
        Handles extremely messy files by searching for keywords (item, qty, quantity) in values 
        if headers are not found in the first few rows.
        """
        logger.info(f"Parsing file: {file_path}")
        try:
            data = pd.read_excel(file_path, sheet_name=sheet_name)
            if isinstance(data, dict):
                for s_name, s_df in data.items():
                    if not s_df.empty:
                        df_raw = s_df
                        break
                else:
                    df_raw = pd.DataFrame()
            else:
                df_raw = data
            
            if df_raw.empty:
                return pd.DataFrame()

            # Basic cleaning
            df = df_raw.dropna(how='all').dropna(axis=1, how='all')

            # HEURISTIC: Find the row that looks like a header
            # We look for rows containing keywords like 'Item', 'Qty', 'Quantity', 'Sold'
            header_row_idx = 0
            found_header = False
            keywords = ['item', 'qty', 'quantity', 'sold', 'product', 'amount']
            
            for i in range(min(20, len(df))):
                row_vals = [str(v).lower() for v in df.iloc[i].values]
                if any(any(kw in val for kw in keywords) for val in row_vals):
                    header_row_idx = i
                    found_header = True
                    break
            
            if found_header:
                df.columns = df.iloc[header_row_idx]
                df = df.iloc[header_row_idx+1:].reset_index(drop=True)
            
            # Normalize columns
            df = self._normalize_columns(df)
            
            # FINAL FALLBACK: If still no 'item' or 'qty', the file is too messy for auto-detection.
            # In operational spreadsheets, often column 0 is item and column 1 is qty.
            if 'item' not in df.columns or 'qty' not in df.columns:
                logger.info("No standard headers found, attempting positional mapping (Col 0=Item, Col 1=Qty)")
                # Only do this if the file has at least 2 columns
                if len(df.columns) >= 2:
                    cols = list(df.columns)
                    cols[0] = 'item'
                    cols[1] = 'qty'
                    df.columns = cols

            required = ['item', 'qty']
            missing = [r for r in required if r not in df.columns]
            if missing:
                logger.warning(f"File {file_path} missing required columns: {missing}. Returning raw df.")
                return df

            df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
            if 'price' in df.columns:
                df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
            if 'total' in df.columns:
                df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)

            return df[['item', 'qty', 'price', 'total']] if 'total' in df.columns else df[['item', 'qty', 'price']] if 'price' in df.columns else df[['item', 'qty']]

        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return pd.DataFrame()

    def normalize_time_series(self, df: pd.DataFrame, period_start: str, period_end: str, frequency: str = 'D') -> pd.DataFrame:
        """
        Converts a-periodic (weekly/monthly) aggregates into a daily-aligned time series.
        frequency: 'D' (Daily), 'W' (Weekly), 'M' (Monthly)
        """
        if df.empty:
            return df
        
        # Create a date range for the period
        dates = pd.date_range(start=period_start, end=period_end, freq=frequency)
        
        # If the data is already a summary for a whole month, we distribute it 
        # (simplified: equal distribution across the period for KPI trend analysis)
        total_qty = df['qty'].sum()
        days_count = len(dates)
        
        # In a real scenario, we would map specific items to dates.
        # For high-level XLS summaries, we create a 'synthetic' daily series
        # that represents the average daily performance of that period.
        normalized_data = []
        for date in dates:
            for _, row in df.iterrows():
                normalized_data.append({
                    'date': date,
                    'item': row['item'],
                    'qty': row['qty'] / days_count,
                    'original_period': f"{period_start} to {period_end}"
                })
        
        return pd.DataFrame(normalized_data)

    def calculate_kpis(self, current_df: pd.DataFrame, target_df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Computes KPI metrics: Growth, Volume, Actual vs Target.
        """
        if current_df.empty:
            return {"error": "No data to calculate KPIs"}

        total_volume = current_df['qty'].sum()
        item_count = current_df['item'].nunique()
        
        # Growth calculation would require a previous period df
        # Here we implement the logic skeleton
        res = {
            "total_sold_items": total_volume,
            "unique_products": item_count,
            "avg_per_product": total_volume / item_count if item_count > 0 else 0,
            "timestamp": datetime.now().isoformat()
        }
        
        if target_df is not None:
            target_vol = target_df['target_qty'].sum()
            res["performance_pct"] = (total_volume / target_vol * 100) if target_vol > 0 else 0
            res["variance"] = total_volume - target_vol

        return res

    def save_to_triad_db(self, df: pd.DataFrame, table_name: str = "xls_sales_aggregates"):
        """
        Integration layer to store XLS data in Postgres.
        Uses a separate table to avoid overwriting granular daily Telegram reports.
        """
        if self.db is None:
            logger.info("DB connection not provided. Skipping database save.")
            return False
        
        try:
            # df.to_sql expects a sqlalchemy engine
            df.to_sql(table_name, self.db, if_exists='append', index=False)
            logger.info(f"Successfully saved data to {table_name}")
            return True
        except Exception as e:
            logger.error(f"DB Save Error: {e}")
            return False
