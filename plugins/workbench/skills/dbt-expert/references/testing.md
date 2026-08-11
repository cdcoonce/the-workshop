# dbt Testing

Reference for generic tests, unit tests, custom tests, test severity, selection, and organization in dbt Core.

## Generic Tests

dbt Core ships four generic tests, declared in YAML schema files on columns:

- **`unique`** — no duplicate values
- **`not_null`** — no NULL values
- **`accepted_values`** — every value belongs to a defined set
- **`relationships`** — referential integrity against another model's column

```yaml
models:
  - name: fct_orders
    columns:
      - name: order_id
        tests:
          - unique
          - not_null
      - name: customer_id
        tests:
          - not_null
          - relationships:
              to: ref('dim_customers')
              field: customer_id
      - name: status
        tests:
          - accepted_values:
              values: ['placed', 'shipped', 'delivered', 'returned']
```

## Unit Tests

Unit tests validate model transformation logic with mock inputs and expected outputs, without querying real warehouse data.

### YAML format

```yaml
unit_tests:
  - name: test_order_total_calculation
    description: "Verify order total sums line items correctly"
    model: fct_orders
    given:
      - input: ref('stg_shopify__orders')
        rows:
          - { order_id: 1, customer_id: 100, order_date: "2024-01-15" }
      - input: ref('int_payments_pivoted')
        rows:
          - { order_id: 1, credit_card_amount: 25.00, bank_transfer_amount: 10.00 }
    expect:
      rows:
        - { order_id: 1, customer_id: 100, total_amount: 35.00 }
```

### Input formats

#### dict (default) — best for small row counts

```yaml
given:
  - input: ref('stg_orders')
    rows:
      - { order_id: 1, status: "placed", amount: 50.00 }
```

#### csv — best for many rows or wide tables

```yaml
given:
  - input: ref('stg_orders')
    format: csv
    rows: |
      order_id,status,amount
      1,placed,50.00
      2,shipped,75.00
```

#### sql — best when mock data requires expressions or type casts

```yaml
given:
  - input: ref('stg_orders')
    format: sql
    rows: |
      select 1 as order_id, 'placed' as status, 50.00::numeric as amount
      union all
      select 2, 'shipped', 75.00
```

### Overriding timestamps

Use `overrides` to freeze time-dependent logic:

```yaml
unit_tests:
  - name: test_days_since_order
    model: fct_orders
    overrides:
      macros:
        dbt.current_timestamp: "cast('2024-06-01 00:00:00' as timestamp)"
    given:
      - input: ref('stg_orders')
        rows:
          - { order_id: 1, order_date: "2024-05-15" }
    expect:
      rows:
        - { order_id: 1, days_since_order: 17 }
```

Provide only the columns you care about in `given` — dbt fills unspecified columns with NULL.

## Custom Tests

Standalone SQL queries in the `tests/` directory. A test **passes** when the query returns **zero rows**.

```sql
-- tests/assert_positive_order_amounts.sql
select order_id, total_amount
from {{ ref('fct_orders') }}
where total_amount < 0
```

Use `{{ ref() }}` in custom tests — dbt resolves dependencies and runs the model first.

**When to use**: Complex business rules spanning multiple columns or models that do not fit a single-column generic test.

## Test Severity

| Level | Behavior | Use for |
|-------|----------|---------|
| `error` (default) | Fails the run | Data integrity rules that must hold |
| `warn` | Reports warning, run continues | Advisory checks, soft expectations |

```yaml
columns:
  - name: order_id
    tests:
      - unique:
          severity: error
          error_if: ">100"
          warn_if: ">10"
```

The `warn_if` / `error_if` thresholds allow a bounded number of failures before escalating.

## Test Selection

```bash
dbt test                              # all tests
dbt test --select fct_orders          # tests for a specific model
dbt test --select tag:nightly         # tests by tag
dbt test --select +fct_orders         # tests for model and its upstream
dbt test --exclude test_name          # skip specific tests
```

`dbt build` runs tests in DAG order alongside models — each model is tested immediately after materialization. Preferred for CI.

## Test Organization

### Generic tests — co-locate with models in YAML

```
models/
  staging/stripe/
    stg_stripe__payments.sql
    _stripe__models.yml          # generic tests for staging models
  marts/finance/
    fct_orders.sql
    _finance__models.yml         # generic tests for mart models
```

### Unit tests — same YAML or dedicated file

```
models/marts/finance/
  fct_orders.sql
  _finance__models.yml           # generic tests
  _finance__unit_tests.yml       # unit tests (optional separation)
```

### Custom tests — `tests/` directory at project root

```
tests/
  assert_positive_order_amounts.sql
  assert_no_orphaned_payments.sql
```

### Naming conventions

- **Generic**: auto-named by dbt (`unique_fct_orders_order_id`)
- **Unit**: descriptive with `test_` prefix (`test_order_total_calculation`)
- **Custom**: `assert_` prefix (`assert_positive_order_amounts`)
