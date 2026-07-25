"""
Exploration notebook template.
Use for EDA, prototyping, and analysis before integration.
"""

# Imports
import pandas as pd
import numpy as np
import duckdb
from config.settings import DUCKDB_FILE
from src.database.database_manager import DatabaseManager

# Initialize database manager
db = DatabaseManager()

# ============================================================================
# 1. EXPLORE RAW DATA
# ============================================================================

# Load sample of raw CSV
df_raw = pd.read_csv('data/raw/SGJobData.csv', nrows=5000)
print("Raw data shape:", df_raw.shape)
print("\\nColumns:", df_raw.columns.tolist())
print("\\nData types:\\n", df_raw.dtypes)
print("\\nMissing values:\\n", df_raw.isnull().sum())

# ============================================================================
# 2. EXPLORE PROCESSED DATA IN DUCKDB
# ============================================================================

# Query jobs table
jobs_sample = db.query("SELECT * FROM jobs LIMIT 10")
print("\\nJobs sample:")
print(jobs_sample)

# Get summary statistics
summary = db.query("""
    SELECT 
        COUNT(*) as total_jobs,
        COUNT(DISTINCT company) as unique_companies,
        COUNT(DISTINCT title) as unique_titles,
        COUNT(DISTINCT sector) as unique_sectors,
        AVG(salary_max) as avg_max_salary,
        MIN(salary_min) as min_entry_salary,
        MAX(salary_max) as max_top_salary
    FROM jobs
""")
print("\\nSummary Statistics:")
print(summary)

# ============================================================================
# 3. SALARY ANALYSIS
# ============================================================================

salary_by_role = db.query("""
    SELECT 
        title,
        COUNT(*) as count,
        ROUND(AVG(salary_min)::numeric, 0) as avg_entry,
        ROUND(AVG(salary_max)::numeric, 0) as avg_market_rate,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_max)::numeric, 0) as median
    FROM jobs
    GROUP BY title
    HAVING COUNT(*) > 20
    ORDER BY avg_market_rate DESC
    LIMIT 20
""")
print("\\nTop 20 Roles by Salary:")
print(salary_by_role)

# ============================================================================
# 4. SECTOR ANALYSIS
# ============================================================================

sector_analysis = db.query("""
    SELECT 
        sector,
        COUNT(*) as postings,
        COUNT(DISTINCT company) as companies,
        ROUND(AVG(salary_max)::numeric, 0) as avg_salary
    FROM jobs
    WHERE sector IS NOT NULL
    GROUP BY sector
    ORDER BY postings DESC
""")
print("\\nSector Analysis:")
print(sector_analysis)

# ============================================================================
# 5. SKILLS ANALYSIS
# ============================================================================

# Note: This query may need adjustment based on your skills format
skills_demand = db.query("""
    SELECT 
        skill,
        COUNT(*) as demand_count,
        ROUND(AVG(salary_max)::numeric, 0) as avg_salary
    FROM (
        SELECT UNNEST(string_split(skills, ',')) as skill, salary_max
        FROM jobs
        WHERE skills IS NOT NULL AND skills != 'Not Specified'
    )
    GROUP BY skill
    HAVING COUNT(*) > 50
    ORDER BY demand_count DESC
    LIMIT 20
""")
print("\\nTop Skills in Demand:")
print(skills_demand)

# ============================================================================
# 6. EXPERIENCE LEVEL DISTRIBUTION
# ============================================================================

exp_analysis = db.query("""
    SELECT 
        experience_level,
        COUNT(*) as count,
        ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) as percentage,
        ROUND(AVG(salary_max)::numeric, 0) as avg_salary
    FROM jobs
    WHERE experience_level IS NOT NULL
    GROUP BY experience_level
    ORDER BY count DESC
""")
print("\\nExperience Level Distribution:")
print(exp_analysis)

# ============================================================================
# 7. LOCATION ANALYSIS
# ============================================================================

location_analysis = db.query("""
    SELECT 
        location,
        COUNT(*) as postings,
        ROUND(AVG(salary_max)::numeric, 0) as avg_salary
    FROM jobs
    WHERE location IS NOT NULL
    GROUP BY location
    ORDER BY postings DESC
    LIMIT 15
""")
print("\\nTop Locations:")
print(location_analysis)

# ============================================================================
# 8. CUSTOM ANALYSIS (Your ideas here!)
# ============================================================================

# Example: Fastest growing skills
growth_skills = db.query("""
    SELECT 
        title,
        COUNT(*) as total_postings,
        ROUND(100.0 * COUNT(DISTINCT sector) / (SELECT COUNT(DISTINCT sector) FROM jobs), 1) as sector_diversity
    FROM jobs
    WHERE is_growth_role = 1
    GROUP BY title
    ORDER BY total_postings DESC
    LIMIT 10
""")
print("\\nFastest Growing Roles:")
print(growth_skills)
