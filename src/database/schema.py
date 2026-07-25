"""
DuckDB schema definitions and database initialization.
Defines the structure for processed job data with raw data layer for lineage.
"""
import duckdb
from config.settings import DUCKDB_FILE

# Raw data layer - stores original data as-is for audit and lineage
RAW_JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_jobs (
    raw_id VARCHAR PRIMARY KEY,
    source_row_id VARCHAR,  -- Original row identifier from CSV
    raw_data JSON,          -- Complete original record as JSON
    loaded_at TIMESTAMP DEFAULT current_timestamp,
    data_quality_score FLOAT,  -- Percentage of non-null fields
    processing_status VARCHAR DEFAULT 'pending'  -- pending, processed, failed
)
"""

# Alternative raw table - flattened columns (if JSON not preferred)
RAW_JOBS_FLAT_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_jobs_flat (
    raw_id VARCHAR PRIMARY KEY,
    categories VARCHAR,
    employmentTypes VARCHAR,
    metadata_expiryDate VARCHAR,
    metadata_isPostedOnBehalf VARCHAR,
    metadata_jobPostId VARCHAR,
    metadata_newPostingDate VARCHAR,
    metadata_originalPostingDate VARCHAR,
    metadata_repostCount VARCHAR,
    metadata_totalNumberJobApplication VARCHAR,
    metadata_totalNumberOfView VARCHAR,
    minimumYearsExperience VARCHAR,
    numberOfVacancies VARCHAR,
    occupationId VARCHAR,
    positionLevels VARCHAR,
    postedCompany_name VARCHAR,
    salary_maximum VARCHAR,
    salary_minimum VARCHAR,
    salary_type VARCHAR,
    status_id VARCHAR,
    status_jobStatus VARCHAR,
    title VARCHAR,
    average_salary VARCHAR,
    loaded_at TIMESTAMP DEFAULT current_timestamp,
    raw_column_count INTEGER,
    raw_null_count INTEGER
)
"""

# Main jobs table schema (processed/denormalized)
JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id VARCHAR PRIMARY KEY,
    title VARCHAR NOT NULL,
    company VARCHAR NOT NULL,
    sector VARCHAR,
    sub_sector VARCHAR,
    location VARCHAR,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_currency VARCHAR,
    experience_level VARCHAR,  -- 'entry', 'mid', 'senior'
    seniority_years INTEGER,
    job_type VARCHAR,  -- 'Full-time', 'Part-time', 'Contract', etc.
    posting_date DATE,
    skills TEXT,  -- comma-separated skills
    description TEXT,
    requirements TEXT,
    created_at TIMESTAMP DEFAULT current_timestamp
)
"""

# Summary tables for analytics
ROLE_STATISTICS_SCHEMA = """
CREATE TABLE IF NOT EXISTS role_statistics (
    role_name VARCHAR PRIMARY KEY,
    sector VARCHAR,
    total_postings INTEGER,
    avg_salary INTEGER,
    min_salary INTEGER,
    max_salary INTEGER,
    top_skills VARCHAR,
    experience_level VARCHAR,
    avg_experience_years FLOAT,
    last_updated TIMESTAMP DEFAULT current_timestamp
)
"""

SALARY_BENCHMARKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS salary_benchmarks (
    benchmark_id VARCHAR PRIMARY KEY,
    role VARCHAR,
    experience_level VARCHAR,
    sector VARCHAR,
    salary_p25 INTEGER,
    salary_p50 INTEGER,
    salary_p75 INTEGER,
    salary_p90 INTEGER,
    count_samples INTEGER,
    last_updated TIMESTAMP DEFAULT current_timestamp
)
"""

MARKET_TRENDS_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_trends (
    trend_id VARCHAR PRIMARY KEY,
    trend_date DATE,
    sector VARCHAR,
    role VARCHAR,
    posting_count INTEGER,
    avg_salary INTEGER,
    skill_demand VARCHAR,
    experience_level VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp
)
"""

SKILLS_DEMAND_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills_demand (
    skill_id VARCHAR PRIMARY KEY,
    skill_name VARCHAR NOT NULL UNIQUE,
    total_postings INTEGER,
    avg_salary INTEGER,
    sectors VARCHAR,
    experience_levels VARCHAR,
    trend_direction VARCHAR,  -- 'up', 'down', 'stable'
    last_updated TIMESTAMP DEFAULT current_timestamp
)
"""


def initialize_database():
    """Initialize DuckDB database with all required schemas."""
    conn = duckdb.connect(DUCKDB_FILE)
    
    # Create RAW data layer (audit trail & lineage)
    print("📝 Creating raw data layer...")
    conn.execute("DROP TABLE IF EXISTS raw_jobs")
    conn.execute("DROP TABLE IF EXISTS raw_jobs_flat")
    conn.execute(RAW_JOBS_SCHEMA)
    conn.execute(RAW_JOBS_FLAT_SCHEMA)
    
    # Create processed tables (denormalized for analytics)
    print("📊 Creating processed/analytical tables...")
    conn.execute(JOBS_SCHEMA)
    conn.execute(ROLE_STATISTICS_SCHEMA)
    conn.execute(SALARY_BENCHMARKS_SCHEMA)
    conn.execute(MARKET_TRENDS_SCHEMA)
    conn.execute(SKILLS_DEMAND_SCHEMA)
    
    conn.close()
    print(f"✓ Database initialized at {DUCKDB_FILE}")
    print(f"  ├─ Raw layer: raw_jobs, raw_jobs_flat")
    print(f"  └─ Analytical layer: jobs, role_statistics, salary_benchmarks, market_trends, skills_demand")


if __name__ == "__main__":
    initialize_database()
