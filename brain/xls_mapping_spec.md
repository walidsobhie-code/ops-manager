# Data Mapping Specification: XLS Processor -> Dashboard KPI Study

## 1. Data Ingestion Flow
**Source:** XLS/XLSX Files (Ops Manager) $\rightarrow$ `XLSProcessor.parse_xls()` $\rightarrow$ `XLSProcessor.normalize_time_series()` $\rightarrow$ **Triad DB (`xls_sales_aggregates` table)**.

## 2. Mapping Details

| XLS Field (Original) | Normalized Key | DB Column | Type | Description |
| :--- | :--- | :--- | :--- | :--- |
| Product/Item Name | `item` | `item_name` | VARCHAR | Unique identifier for the product |
| Quantity/Sold | `qty` | `quantity` | FLOAT | Total items sold in the specified period |
| Price/Unit Price | `price` | `unit_price` | FLOAT | Price per single unit |
| Total Sales/Revenue | `total` | `total_revenue` | FLOAT | Total revenue for that item in the period |
| File Metadata | `date` | `period_date` | DATE | Aligned date (distributed across the period) |

## 3. KPI Logic Mapping

### A. Actual vs Target
- **XLS Source:** $\sum (\text{qty})$ from `xls_sales_aggregates`.
- **Target Source:** `targets` table in Triad DB.
- **KPI Calculation:** $(\text{Actual} / \text{Target}) \times 100$.

### B. Growth Trends (Weekly/Monthly)
- **XLS Source:** Compare $\sum (\text{qty})$ of `current_period` vs $\sum (\text{qty})$ of `previous_period` where `period_id` differs.
- **Trend:** $\frac{\text{Current} - \text{Previous}}{\text{Previous}} \times 100$.

### C. Volume Analysis
- **Transaction Count:** Estimated by dividing $\sum (\text{qty})$ by `avg_basket_size` (from daily Telegram reports).
- **Product Mix:** Distribution of $\sum (\text{qty})$ across different `item` categories.

## 4. Integration Strategy
To ensure no data loss from granular daily reports:
- Daily reports $\rightarrow$ `daily_sales` (Granular, high-frequency).
- XLS Reports $\rightarrow$ `xls_sales_aggregates` (Period-based, summary).
- **KPI View:** A SQL View that `UNION`s or joins both tables based on date range, treating XLS data as a "truth" baseline for monthly reconciliation.
