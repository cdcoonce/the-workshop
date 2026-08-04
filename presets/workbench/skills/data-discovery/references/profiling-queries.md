# Profiling Queries

Reusable SQL patterns for live profiling. These run against the target Snowflake schema to gather real numbers for the discovery doc.

## Table-Level Stats

```sql
-- Row count and byte size for all tables in a schema
SELECT
    table_name,
    row_count,
    bytes,
    ROUND(bytes / 1024 / 1024, 2) AS size_mb,
    last_altered
FROM {database}.INFORMATION_SCHEMA.TABLES
WHERE table_schema = '{schema}'
  AND table_type IN ('BASE TABLE', 'VIEW')
ORDER BY row_count DESC;
```

## Column Metadata

```sql
-- All columns with types for a specific table
DESCRIBE TABLE {database}.{schema}.{table};
```

## Date Range and Freshness

```sql
-- MIN/MAX for date and timestamp columns
SELECT
    MIN({date_column}) AS earliest,
    MAX({date_column}) AS latest,
    DATEDIFF('day', MIN({date_column}), MAX({date_column})) AS span_days,
    DATEDIFF('hour', MAX({date_column}), CURRENT_TIMESTAMP()) AS hours_since_latest
FROM {database}.{schema}.{table};
```

## Categorical Breakdown

```sql
-- Distinct values and counts for a categorical column
-- Only use on columns with < 50 distinct values
SELECT
    {category_column},
    COUNT(*) AS row_count
FROM {database}.{schema}.{table}
GROUP BY {category_column}
ORDER BY row_count DESC;
```

## Multi-Dimension Summary

```sql
-- Combined breakdown of key dimensions
SELECT
    {dim1},
    {dim2},
    COUNT(*) AS row_count,
    ROUND(SUM({metric})) AS total_{metric}
FROM {database}.{schema}.{table}
GROUP BY {dim1}, {dim2}
ORDER BY row_count DESC
LIMIT 20;
```

## Distinct Value Count Check

```sql
-- Quickly determine if a column is categorical (worth profiling) or high-cardinality (skip)
SELECT
    COUNT(DISTINCT {column}) AS distinct_count,
    COUNT(*) AS total_rows,
    ROUND(COUNT(DISTINCT {column}) * 100.0 / NULLIF(COUNT(*), 0), 1) AS cardinality_pct
FROM {database}.{schema}.{table};
```

## Null Rate

```sql
-- Check null rates across all columns (useful for data quality notes)
SELECT
    COUNT(*) AS total_rows,
    COUNT({column}) AS non_null,
    ROUND((1 - COUNT({column}) / NULLIF(COUNT(*), 0)::FLOAT) * 100, 1) AS null_pct
FROM {database}.{schema}.{table};
```

## Freshness by Source

```sql
-- When each source/partition was last loaded (for multi-source tables)
SELECT
    {source_column},
    MAX({timestamp_column}) AS last_loaded,
    DATEDIFF('hour', MAX({timestamp_column}), CURRENT_TIMESTAMP()) AS hours_ago
FROM {database}.{schema}.{table}
GROUP BY {source_column}
ORDER BY last_loaded DESC;
```

## Sample Rows

```sql
-- Quick sample to understand what the data looks like
SELECT *
FROM {database}.{schema}.{table}
LIMIT 5;
```

---

## Usage Notes

- **Column selection for profiling**: Use `INFORMATION_SCHEMA.COLUMNS` to identify which columns to profile:
  - Date/timestamp columns → run date range query
  - VARCHAR columns → check distinct count first; if < 50, run categorical breakdown
  - Numeric columns → note them as potential metrics for the summary query
- **Budget awareness**: On tables with > 1M rows, avoid full-table GROUP BY on non-indexed columns. Use `TABLESAMPLE` or add a recent-date filter.
- **Batch where possible**: Multiple tables can often be profiled with a single `INFORMATION_SCHEMA` query for row counts, then targeted per-table queries for interesting columns only.
