"""
Database manager for DuckDB operations.
Handles connections, queries, data insertion (raw and processed layers).
"""
import duckdb
import pandas as pd
import json
from config.settings import DUCKDB_FILE, RAW_CSV_PATH
from src.database.schema import JOBS_SCHEMA, initialize_database


class DatabaseManager:
    """Manager for DuckDB operations with raw and processed data layers."""
    
    def __init__(self):
        self.db_path = DUCKDB_FILE
    
    def get_connection(self):
        """Get a DuckDB connection."""
        return duckdb.connect(self.db_path)
    
    def insert_raw_jobs(self, df: pd.DataFrame) -> int:
        """
        Insert raw job data into raw_jobs_flat table for audit trail.
        Maintains lineage before any transformations.
        
        Args:
            df: Raw DataFrame with original columns from CSV
            
        Returns:
            Number of rows inserted
        """
        import uuid
        conn = self.get_connection()
        try:
            df_raw = df.copy()
            
            # Preserve every incoming CSV column and add metadata columns for audit trail
            df_raw['raw_column_count'] = len(df.columns)
            df_raw['raw_null_count'] = df.isnull().sum(axis=1).astype(int)
            df_raw['raw_id'] = [f"raw_{uuid.uuid4().hex[:12]}" for _ in range(len(df_raw))]
            df_raw['loaded_at'] = pd.Timestamp.now()
            
            # Only keep columns that actually exist in raw_jobs_flat's schema — the
            # incoming df may carry extra pipeline-only helper columns (e.g. a
            # synthesized 'salary' field) that would otherwise cause every row to
            # be rejected with a Binder Error.
            table_columns = set(conn.execute("PRAGMA table_info('raw_jobs_flat')").df()['name'])
            preserve_columns = list(df.columns) + ['raw_id', 'loaded_at', 'raw_column_count', 'raw_null_count']
            preserve_columns = [col for col in preserve_columns if col in df_raw.columns and col in table_columns]
            df_raw_insert = df_raw[preserve_columns].copy()
            
            conn.register('df_raw_insert', df_raw_insert)
            col_list = ', '.join(preserve_columns)
            conn.execute(f"INSERT INTO raw_jobs_flat ({col_list}) SELECT {col_list} FROM df_raw_insert")
            inserted = len(df_raw)
            conn.close()
            print(f"✓ Inserted {inserted} raw job records into raw_jobs_flat")
            return inserted
        except Exception as e:
            print(f"✗ Error inserting raw jobs: {e}")
            conn.close()
            return 0
    
    def insert_jobs(self, df: pd.DataFrame) -> int:
        """
        Insert processed job data into the jobs table.
        
        Args:
            df: DataFrame with columns matching jobs schema
            
        Returns:
            Number of rows inserted
        """
        import uuid
        conn = self.get_connection()
        try:
            df_insert = df.copy()
            print(f"  📊 DataFrame shape before insert: {df_insert.shape}")
            print(f"  📋 Available columns: {df_insert.columns.tolist()[:10]}...")
            
            # ALWAYS regenerate job_id with UUIDs (guarantees uniqueness)
            df_insert['job_id'] = [f"job_{uuid.uuid4().hex[:12]}" for _ in range(len(df_insert))]
            print(f"  ✓ Regenerated unique job_ids (sample: {df_insert['job_id'].iloc[0]})")
            
            if 'created_at' not in df_insert.columns:
                df_insert['created_at'] = pd.Timestamp.now()
            
            if 'salary_currency' not in df_insert.columns:
                df_insert['salary_currency'] = 'SGD'
            
            if 'sub_sector' not in df_insert.columns:
                df_insert['sub_sector'] = 'General'
            
            if 'seniority_years' not in df_insert.columns:
                df_insert['seniority_years'] = 0
            
            # Define the columns needed for the jobs table
            columns_order = ['job_id', 'title', 'company', 'sector', 'sub_sector', 'location',
                           'salary_min', 'salary_max', 'salary_currency', 'experience_level',
                           'seniority_years', 'position_level', 'job_type', 'posting_date',
                           'expiry_date', 'views', 'applications', 'vacancies', 'repost_count',
                           'skills', 'description', 'created_at']

            # Filter to available columns only
            available_cols = [col for col in columns_order if col in df_insert.columns]
            print(f"  ✓ Columns to insert: {len(available_cols)} of {len(columns_order)}")

            # Name what went missing. A column quietly absent here lands in the
            # table as all-NULL with no other warning, which is how views,
            # applications and job_type were lost.
            missing = [col for col in columns_order if col not in df_insert.columns]
            if missing:
                print(f"  ⚠ Not in DataFrame, will be NULL: {', '.join(missing)}")

            if not available_cols:
                print("  ✗ No columns available for insertion!")
                return 0

            df_to_insert = df_insert[available_cols].copy()

            # Replace the table instead of appending. The pipeline always reloads
            # from scratch, and appending made every re-run add a second copy of
            # every posting. Done here rather than in initialize_database() so a
            # failed extract can't leave an empty table behind.
            conn.execute("DROP TABLE IF EXISTS jobs")
            conn.execute(JOBS_SCHEMA)

            # Create column list for INSERT statement
            col_list = ', '.join(available_cols)
            conn.execute(f"INSERT INTO jobs ({col_list}) SELECT {col_list} FROM df_to_insert")
            inserted = len(df_insert)
            conn.close()
            print(f"✓ Inserted {inserted} job records")
            return inserted
        except Exception as e:
            print(f"✗ Error inserting jobs: {e}")
            print(f"  DataFrame columns: {df_insert.columns.tolist() if 'df_insert' in locals() else 'N/A'}")
            conn.close()
            return 0
    
    def query(self, sql: str, read_only: bool = False) -> pd.DataFrame:
        """Execute SQL query and return results as DataFrame.

        Closed in a finally: a query that raises must still release the file
        lock, or the caller's next attempt fails for a reason unrelated to the
        one that actually broke.
        """
        conn = self.get_connection(read_only=read_only)
        try:
            return conn.execute(sql).df()
        finally:
            conn.close()
    
    # get_hirer_view() removed: the hirer view is served entirely by
    # src/dashboard/hirer_data_loader.py. Its posting count was a raw COUNT(*),
    # which reported 1,044,587 against that module's deduplicated 1,009,709 --
    # two numbers for one caption. cohort_sizes() is the surviving definition.

    def get_hiring_trends(self, sector: str = None, granularity: str = 'year', year: int = None) -> pd.DataFrame:
        """
        Get hiring trend counts aggregated by year or month, for drill-down.

        Args:
            sector: optional sector filter
            granularity: 'year' or 'month'
            year: when granularity='month', restrict to this year
        """
        conditions = ["posting_date IS NOT NULL"]
        if sector:
            conditions.append(f"sector = '{sector}'")
        if granularity == 'month' and year is not None:
            conditions.append(f"EXTRACT(YEAR FROM posting_date) = {int(year)}")
        where_clause = "WHERE " + " AND ".join(conditions)

        if granularity == 'year':
            period_expr = "EXTRACT(YEAR FROM posting_date)::INTEGER"
        else:
            period_expr = "strftime(posting_date, '%Y-%m')"

        sql = f"""
            SELECT
                {period_expr} as period,
                COUNT(*) as postings
            FROM jobs
            {where_clause}
            GROUP BY period
            ORDER BY period
        """
        return self.query(sql)

    def get_seeker_view(self, experience_level: str = None, sector: str = None) -> dict:
        """
        Get metrics for job seeker view.
        Focused on: opportunities, benchmarks, market competition.
        """
        conn = self.get_connection()

        salary_filter = (
            "salary_min IS NOT NULL AND salary_max IS NOT NULL "
            "AND salary_min >= 500 AND salary_max <= 100000 "
            "AND (seniority_years IS NULL OR seniority_years <= 30)"
        )
        try:
            table_info = conn.execute("PRAGMA table_info('jobs')").fetchall()
            if any(col[1] == 'salary_flag' for col in table_info):
                salary_filter = (
                    "salary_flag = 'ok' AND salary_min IS NOT NULL AND salary_max IS NOT NULL "
                    "AND salary_min >= 500 AND salary_max <= 100000 "
                    "AND (seniority_years IS NULL OR seniority_years <= 30)"
                )
        except Exception:
            pass

        filters = f"WHERE {salary_filter}"
        if experience_level:
            filters += f" AND experience_level = '{experience_level}'"
        if sector:
            filters += f" AND sector = '{sector}'"
        
        metrics = {
            "opportunities": conn.execute(f"""
                SELECT 
                    COUNT(*) as total_opportunities,
                    COUNT(DISTINCT sector) as sectors_hiring,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY (salary_min + salary_max) / 2) as median_salary,
                    MAX(salary_max) as top_salary
                FROM jobs
                {filters}
            """).df(),

            "top_roles": conn.execute(f"""
                SELECT
                    title,
                    COUNT(*) as opportunities,
                    SUM(salary_min + salary_max) / (2 * COUNT(*)) as avg_salary,
                    MIN(salary_min) as min_salary,
                    COUNT(DISTINCT company) as num_companies
                FROM jobs
                {filters}
                GROUP BY title
                ORDER BY opportunities DESC
                LIMIT 10
            """).df(),
            
            "salary_benchmarks": conn.execute(f"""
                SELECT 
                    title,
                    experience_level,
                    MIN(salary_min) as p25,
                    AVG(salary_min) as median_entry,
                    AVG(salary_max) as median_max,
                    MAX(salary_max) as p90,
                    COUNT(*) as count_samples
                FROM jobs
                {filters}
                GROUP BY title, experience_level
                ORDER BY median_max DESC
            """).df(),
            
            "competitive_skills": conn.execute(f"""
                SELECT
                    skill,
                    COUNT(*) as opportunities,
                    SUM(salary_min + salary_max) / (2 * COUNT(*)) as avg_salary
                FROM (
                    SELECT TRIM(UNNEST(string_split(skills, ','))) as skill, salary_min, salary_max
                    FROM jobs
                    {filters}
                )
                WHERE skill NOT IN ('Not Specified', '')
                GROUP BY skill
                HAVING COUNT(*) > 10
                ORDER BY avg_salary DESC
                LIMIT 15
            """).df(),
        }
        
        conn.close()
        return metrics
    
    def get_sector_list(self) -> list:
        """Get list of available sectors."""
        df = self.query("SELECT DISTINCT sector FROM jobs WHERE sector IS NOT NULL ORDER BY sector")
        return df['sector'].tolist()
    
    def get_role_list(self, sector: str = None) -> list:
        """Get list of roles, optionally filtered by sector."""
        sql = "SELECT DISTINCT title FROM jobs"
        if sector:
            sql += f" WHERE sector = '{sector}'"
        sql += " ORDER BY title"
        df = self.query(sql)
        return df['title'].tolist()
    
    # ========================================================================
    # RAW DATA LAYER QUERIES (Audit & Data Quality)
    # ========================================================================
    
    def get_raw_data_quality_report(self) -> pd.DataFrame:
        """Get data quality summary from raw data layer."""
        sql = """
        SELECT 
            COUNT(*) as total_raw_records,
            COUNT(DISTINCT raw_id) as unique_raw_ids,
            AVG(raw_column_count) as avg_columns,
            AVG(raw_null_count) as avg_nulls_per_record,
            MIN(raw_null_count) as min_nulls,
            MAX(raw_null_count) as max_nulls,
            COUNT(CASE WHEN raw_null_count > 5 THEN 1 END) as records_with_many_nulls
        FROM raw_jobs_flat
        """
        return self.query(sql)
    
    def get_raw_sample(self, limit: int = 10) -> pd.DataFrame:
        """Get sample of raw data for inspection."""
        return self.query(f"SELECT * FROM raw_jobs_flat LIMIT {limit}")
    
    def compare_raw_vs_processed(self) -> dict:
        """Compare raw and processed data layers."""
        comparison = {
            'raw_count': self.query("SELECT COUNT(*) as count FROM raw_jobs_flat").iloc[0]['count'],
            'processed_count': self.query("SELECT COUNT(*) as count FROM jobs").iloc[0]['count'],
            'records_lost_in_cleaning': 0,
            'records_enriched': 0
        }
        
        comparison['records_lost_in_cleaning'] = comparison['raw_count'] - comparison['processed_count']
        comparison['cleaning_retention_rate'] = f"{(comparison['processed_count'] / comparison['raw_count'] * 100):.1f}%"
        
        return comparison
    
    def audit_data_lineage(self, raw_id: str) -> dict:
        """Trace a single record from raw to processed layer."""
        raw_record = self.query(f"SELECT * FROM raw_jobs_flat WHERE raw_id = '{raw_id}'")
        
        if raw_record.empty:
            return {'status': 'not_found', 'raw_id': raw_id}
        
        # Find corresponding processed record
        company = raw_record.iloc[0].get('company', '')
        title = raw_record.iloc[0].get('title', '')
        
        processed_records = self.query(f"""
            SELECT * FROM jobs 
            WHERE company = '{company}' AND title = '{title}'
            LIMIT 1
        """)
        
        return {
            'raw_id': raw_id,
            'raw_data': raw_record.to_dict('records')[0] if not raw_record.empty else None,
            'processed_data': processed_records.to_dict('records')[0] if not processed_records.empty else None,
            'transformation_status': 'found' if not processed_records.empty else 'lost_in_processing'
        }
