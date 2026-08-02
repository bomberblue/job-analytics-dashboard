"""
Project configuration settings.
Centralized config for database, data paths, and business logic parameters.
"""
import os
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW = PROJECT_ROOT / "data" / "raw"
DATA_PROCESSED = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROJECT_ROOT / "data" / "processed"
DB_FILE = DB_PATH / "jobs.duckdb"

# Ensure directories exist
DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_PROCESSED.mkdir(parents=True, exist_ok=True)

# Data source
RAW_CSV_PATH = DATA_RAW / "SGJobData.csv"

# DuckDB settings
DUCKDB_FILE = str(DB_FILE)

# Sectors commonly found in Singapore job market
MAJOR_SECTORS = [
    "Technology",
    "Finance",
    "Healthcare",
    "Consulting",
    "Manufacturing",
    "Retail",
    "Construction",
    "Hospitality",
    "Education",
    "Public Sector",
]

# Dashboard config
STREAMLIT_CONFIG = {
    "page_title": "Singapore Jobs Analytics",
    "page_icon": "📊",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# Hirer vs Seeker view filters
HIRER_METRICS = ["top_skills_demand", "role_trends", "hiring_pace", "salary_benchmarks"]
SEEKER_METRICS = ["market_opportunities", "skill_premiums", "role_competitiveness", "salary_trends"]
