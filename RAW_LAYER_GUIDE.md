# Raw Data Layer Documentation

## Overview

The pipeline now implements a **two-layer data architecture** for data governance:

```
CSV (raw input)
    ↓
[load_raw()]  → raw_jobs_flat (RAW LAYER - audit trail, data quality metrics)
    ↓
[transform()] → Clean & Engineer features
    ↓
[load_processed()] → jobs table (PROCESSED LAYER - analytical queries)
```

---

## Architecture

### Layer 1: RAW DATA LAYER (`raw_jobs_flat` table)

**Purpose:** Maintain original data for audit, lineage, and data quality tracking

**Schema:**
```sql
CREATE TABLE raw_jobs_flat (
    raw_id VARCHAR PRIMARY KEY,          -- Unique identifier for raw record
    title VARCHAR,                        -- Original title (unmodified)
    company VARCHAR,                      -- Original company (unmodified)
    salary VARCHAR,                       -- Original salary string (e.g., "$3000-5000")
    experience VARCHAR,                   -- Original experience text
    sector VARCHAR,                       -- Original sector
    location VARCHAR,                     -- Original location
    job_type VARCHAR,                     -- Original job type
    posting_date VARCHAR,                 -- Original date format
    skills VARCHAR,                       -- Original skills text
    description TEXT,                     -- Original job description
    requirements TEXT,                    -- Original requirements
    loaded_at TIMESTAMP,                  -- When inserted into raw layer
    raw_column_count INTEGER,             -- Total columns in original CSV
    raw_null_count INTEGER                -- Count of NULL values in this record
)
```

**Features:**
- ✅ 100% original data preserved
- ✅ No transformations applied
- ✅ Data quality metrics included
- ✅ Audit trail with timestamps
- ✅ Enables data lineage tracking

---

### Layer 2: PROCESSED DATA LAYER (`jobs` table)

**Purpose:** Transformed, enriched data optimized for analytics

**Key Changes:**
- ✓ Salary parsed: `salary: "$3000-5000"` → `salary_min: 3000, salary_max: 5000`
- ✓ Experience standardized: Any text → `"Entry Level"`, `"Mid Level"`, `"Senior"`
- ✓ Features engineered: `salary_band`, `seniority_years`, `competitiveness_score`, etc.
- ✓ Skills extracted: Job description → structured skill list
- ✓ Duplicates removed: Clean dataset
- ✓ Invalid records filtered: Unrealistic salaries removed

---

## Pipeline Flow

### Stage 1: Extract & Load Raw
```python
df_raw = pipeline.extract(csv_path)           # Load CSV
pipeline.load_raw(df_raw)                     # Store in raw_jobs_flat
```

### Stage 2: Transform
```python
df_cleaned = pipeline.cleaner.clean(df_raw)   # Clean & standardize
df_enriched = pipeline.engineer.engineer_features(df_cleaned)  # Add features
```

### Stage 3: Load Processed
```python
pipeline.load_processed(df_enriched)          # Store in jobs table
```

---

## Data Quality Monitoring

### Query: Data Quality Report
```python
from src.database.database_manager import DatabaseManager
db = DatabaseManager()

quality_report = db.get_raw_data_quality_report()
print(quality_report)
```

**Output columns:**
- `total_raw_records` — How many raw records loaded
- `avg_nulls_per_record` — Average missing fields
- `records_with_many_nulls` — Count of suspicious records

---

### Query: Cleaning Impact
```python
comparison = db.compare_raw_vs_processed()
print(f"Raw records: {comparison['raw_count']}")
print(f"Processed records: {comparison['processed_count']}")
print(f"Records lost: {comparison['records_lost_in_cleaning']}")
print(f"Retention rate: {comparison['cleaning_retention_rate']}")
```

**Example output:**
```
Raw records: 50000
Processed records: 48500
Records lost: 1500 (duplicate or invalid salaries)
Retention rate: 97.0%
```

---

### Query: Data Lineage Audit
```python
# Trace a single record from raw to processed
lineage = db.audit_data_lineage('raw_xyz123')
print(lineage)
```

**Output:**
```python
{
    'raw_id': 'raw_xyz123',
    'raw_data': {
        'company': 'Tech Corp',
        'title': 'Senior Engineer',
        'salary': '$5000-7000 SGD',
        'raw_null_count': 3
    },
    'processed_data': {
        'company': 'Tech Corp',
        'title': 'Senior Engineer',
        'salary_min': 5000,
        'salary_max': 7000,
        'salary_band': 'Senior ($5-8k)',
        'experience_level': 'Senior',
        'competitiveness_score': 72.5
    },
    'transformation_status': 'found'
}
```

---

## Use Cases

### 1. Data Quality Checks (QA)
```python
# Check for data quality issues
quality = db.get_raw_data_quality_report()
if quality['records_with_many_nulls'] > 100:
    print("⚠️  Warning: Many records with missing fields")
```

### 2. Debugging Data Anomalies
```python
# Find a specific record in raw layer
raw_sample = db.get_raw_sample(limit=5)
print(raw_sample[['company', 'title', 'salary', 'raw_null_count']])
```

### 3. Validating Transformations
```python
# Confirm a record survived cleaning
lineage = db.audit_data_lineage('raw_abc456')
if lineage['transformation_status'] == 'found':
    print("✓ Record successfully transformed")
else:
    print("✗ Record was filtered during cleaning")
```

### 4. Tracing Data Loss
```python
# Understand why records were dropped
comparison = db.compare_raw_vs_processed()
lost_count = comparison['records_lost_in_cleaning']
print(f"Records dropped: {lost_count}")
print(f"Likely reasons: Invalid salaries, duplicates, missing critical fields")
```

---

## Best Practices

### ✅ DO:
- Query `raw_jobs_flat` for data quality checks
- Use raw layer for audit trails and compliance
- Compare raw vs processed for retention metrics
- Keep raw layer for ~30 days for debugging

### ❌ DON'T:
- Use raw layer for analytical queries (use `jobs` table)
- Delete raw data immediately after processing
- Modify raw layer records (it's read-only after loading)

---

## SQL Examples

### List all raw records with high null count
```sql
SELECT raw_id, company, title, raw_null_count
FROM raw_jobs_flat
WHERE raw_null_count > 5
ORDER BY raw_null_count DESC
LIMIT 20;
```

### Compare salary formats before transformation
```sql
SELECT 
    salary,
    COUNT(*) as count
FROM raw_jobs_flat
GROUP BY salary
HAVING COUNT(*) > 100
ORDER BY count DESC
LIMIT 10;
```

### Find records where transformation failed
```sql
-- Records in raw but NOT in processed
SELECT r.raw_id, r.company, r.title
FROM raw_jobs_flat r
LEFT JOIN jobs j ON r.company = j.company AND r.title = j.title
WHERE j.job_id IS NULL
LIMIT 50;
```

---

## Maintenance

### Archiving Old Raw Data
```sql
-- Archive raw data older than 30 days
DELETE FROM raw_jobs_flat 
WHERE loaded_at < current_timestamp - INTERVAL '30 days';
```

### Raw Data Disk Usage
```sql
SELECT 
    'raw_jobs_flat' as table_name,
    COUNT(*) as row_count,
    SUM(LENGTH(description) + LENGTH(skills)) / (1024*1024) as approx_size_mb
FROM raw_jobs_flat;
```

---

## Pipeline Visualization

```
┌─────────────────────────────────────────────────────┐
│  Stage 1: Extract from CSV                          │
│  df = pd.read_csv('SGJobData.csv')                  │
└────────────────────┬────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────┐
│  Stage 1.5: Load RAW Layer (audit trail)            │
│  → raw_jobs_flat (original data, unchanged)         │
│  ✓ Data quality metrics: null_count, column_count   │
│  ✓ Timestamp: loaded_at                             │
│  ✓ Unique ID: raw_id for lineage tracing            │
└────────────────────┬────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────┐
│  Stage 2: Transform                                 │
│  • clean_dataset() — salary parsing, text std       │
│  • feature_enrichment() — enrich                    │
│  (1500 records dropped: invalid/duplicates)         │
└────────────────────┬────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────┐
│  Stage 3: Load PROCESSED Layer (analytics)          │
│  → jobs (clean, denormalized, enriched)             │
│  ✓ Salary parsed: min/max integers                  │
│  ✓ Experience standardized: Entry/Mid/Senior        │
│  ✓ Features: salary_band, competitiveness_score    │
│  ✓ 48,500 records ready for analysis                │
└─────────────────────────────────────────────────────┘
```

---

## Summary

| Aspect | Raw Layer | Processed Layer |
|--------|-----------|-----------------|
| **Purpose** | Audit trail & data quality | Analytics & reporting |
| **Data State** | Original, unchanged | Cleaned & enriched |
| **Table** | `raw_jobs_flat` | `jobs` |
| **Records** | 50,000 (example) | 48,500 (example) |
| **Use For** | Debugging, compliance, lineage | Dashboards, queries, ML |
| **Update** | Write-once | Read-only |
| **Retention** | 30+ days | Indefinite |

---

## Questions?

- **"How do I check data quality?"** → `db.get_raw_data_quality_report()`
- **"Why were records dropped?"** → `db.compare_raw_vs_processed()`
- **"Can I trace a record?"** → `db.audit_data_lineage(raw_id)`
- **"Can I fix transformed data?"** → Delete from `jobs` table, re-extract from raw
