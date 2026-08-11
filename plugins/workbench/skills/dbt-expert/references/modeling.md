# dbt Modeling Patterns

Reference for model types, materializations, DAG organization, naming conventions, and Jinja patterns in dbt Core.

## Model Types and Materializations

dbt supports four materialization strategies. Choose based on data volume, query frequency, and freshness requirements.

### view (default)

A database view re-created on each `dbt run`. No data stored — the query executes at read time.

- **Use when**: Data volume is small, transformation is lightweight, or the model is rarely queried directly
- **Trade-off**: Zero storage cost but slower reads on large datasets

### table

A physical table dropped and re-created on each `dbt run`.

- **Use when**: The model is queried frequently or the transformation is expensive
- **Trade-off**: Faster reads but full rebuild every run

### incremental

Only processes new or changed rows on subsequent runs. Requires an `is_incremental()` block.

- **Use when**: Source data is append-only or has a reliable `updated_at`, and full rebuilds are too slow
- **Trade-off**: Fastest production runs but more complex logic; use `--full-refresh` to rebuild from scratch

```sql
{{ config(materialized='incremental', unique_key='event_id') }}

select *
from {{ source('raw', 'events') }}
{% if is_incremental() %}
  where updated_at > (select max(updated_at) from {{ this }})
{% endif %}
```

### ephemeral

A CTE injected into downstream models. Never materialized in the warehouse.

- **Use when**: Pure transformation step used by one or two downstream models only
- **Trade-off**: No storage overhead, but invisible in warehouse and harder to debug

## ref() and source()

**Never hardcode table names.** These two functions are the foundation of dbt's DAG.

### ref()

References another dbt model. dbt resolves the schema and builds dependency edges automatically.

```sql
select * from {{ ref('stg_orders') }}
```

- Creates a DAG edge (stg_orders runs before this model)
- Handles schema/database resolution across environments
- Cross-project: `{{ ref('project_name', 'model_name') }}`

### source()

References a raw table declared in a `sources:` YAML block — points to data that already exists.

```sql
select * from {{ source('stripe', 'payments') }}
```

Source declarations:

```yaml
sources:
  - name: stripe
    schema: raw_stripe
    tables:
      - name: payments
        loaded_at_field: _etl_loaded_at
        freshness:
          warn_after: { count: 12, period: hour }
          error_after: { count: 24, period: hour }
```

## DAG Layer Organization

Organize models into layers from raw to business-ready. Each layer has a clear responsibility.

### staging (`stg_`)

One model per source table. Light transformations only: rename, cast, filter.

```sql
-- models/staging/stripe/stg_stripe__payments.sql
{{ config(materialized='view') }}

select
    id as payment_id,
    amount::numeric(12, 2) as payment_amount,
    created::timestamp as created_at,
    status as payment_status
from {{ source('stripe', 'payments') }}
where status != 'test'
```

**Rules**: one model per source table, naming `stg_{source}__{table}`, materialized as views, no joins.

### intermediate (`int_`)

Business logic that combines staging models. Not exposed to end users.

```sql
-- models/intermediate/finance/int_payments_pivoted.sql
select
    order_id,
    sum(case when payment_method = 'credit_card' then amount else 0 end) as credit_card_amount,
    sum(case when payment_method = 'bank_transfer' then amount else 0 end) as bank_transfer_amount
from {{ ref('stg_stripe__payments') }}
group by 1
```

**Rules**: naming `int_{description}`, consumed only by marts, group by business domain in subdirectories.

### marts (`fct_`, `dim_`)

Business-ready datasets for BI tools, analysts, and downstream systems.

- **`fct_` (facts)**: Event/transaction grain, one row per event
- **`dim_` (dimensions)**: Entity grain, one row per entity

```sql
-- models/marts/finance/fct_orders.sql
{{ config(materialized='table') }}

select
    o.order_id, o.customer_id, o.order_date,
    p.credit_card_amount, p.bank_transfer_amount,
    p.credit_card_amount + p.bank_transfer_amount as total_amount
from {{ ref('stg_shopify__orders') }} o
left join {{ ref('int_payments_pivoted') }} p using (order_id)
```

## Naming Conventions Summary

| Layer | Prefix | Example | Materialization |
|-------|--------|---------|-----------------|
| Staging | `stg_` | `stg_stripe__payments` | view |
| Intermediate | `int_` | `int_payments_pivoted` | view or ephemeral |
| Fact | `fct_` | `fct_orders` | table or incremental |
| Dimension | `dim_` | `dim_customers` | table |

## Materialization Strategy by Environment

### Development

- All layers as **views** for fast iteration
- Use `dbt show --select my_model --limit 50` to preview without materializing
- Use `--defer --state path/to/prod/artifacts` to reuse production tables you have not modified

### Production

- Staging: **view** (always reflects latest source data)
- Intermediate: **view** or **ephemeral** (depending on reuse)
- Marts: **table** or **incremental** (fast BI queries, predictable performance)
- Run `dbt build --full-refresh` periodically to rebuild incremental models from scratch

## Jinja Patterns

### config()

Set model-level configuration at the top of any `.sql` file:

```sql
{{ config(materialized='incremental', unique_key='event_id', schema='analytics', tags=['daily']) }}
```

### Conditional logic

```sql
{% if target.name == 'prod' %}
    complex_expensive_calculation as metric
{% else %}
    null as metric  -- skip in dev for speed
{% endif %}
```

### Macros

Reusable SQL snippets in the `macros/` directory:

```sql
-- macros/cents_to_dollars.sql
{% macro cents_to_dollars(column_name) %}
    ({{ column_name }}::numeric / 100)::numeric(12, 2)
{% endmacro %}

-- Usage: {{ cents_to_dollars('amount_cents') }} as amount_dollars
```

### set and for loops

```sql
{% set methods = ['credit_card', 'bank_transfer', 'gift_card'] %}
select
    order_id,
    {% for m in methods %}
        sum(case when payment_method = '{{ m }}' then amount else 0 end) as {{ m }}_amount
        {% if not loop.last %},{% endif %}
    {% endfor %}
from {{ ref('stg_payments') }}
group by 1
```

## Cost Management

- **Development**: Use `LIMIT` in CTEs or `dbt show --limit` when exploring data
- **Production**: Prefer incremental models for large tables to avoid full-table scans
- **Selection**: Always use `--select` to run only what you need
- **Profiling**: Run counts and aggregations with `dbt show` before materializing expensive models

## Data Handling Safeguards

- **NEVER** run `DROP`, `DELETE`, or `TRUNCATE` outside dbt's materialization process
- dbt manages table lifecycle — manual DDL/DML bypasses the DAG and breaks reproducibility
- To remove data, add a `WHERE` filter in model SQL and let dbt rebuild
- To drop a table, remove the model file and run `dbt run`
