"""
Data quality audit utility.
Provides quick checks and reports on raw and processed data layers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.database.database_manager import DatabaseManager
import pandas as pd


class DataAudit:
    """Run audits on raw and processed data layers."""
    
    def __init__(self):
        self.db = DatabaseManager()
    
    def print_header(self, title):
        """Print formatted header."""
        print(f"\n{'='*70}")
        print(f"  {title}")
        print(f"{'='*70}\n")
    
    def print_section(self, title):
        """Print formatted section."""
        print(f"\n  📊 {title}")
        print(f"  {'-'*66}\n")
    
    def audit_raw_layer(self):
        """Audit raw data layer."""
        self.print_header("RAW DATA LAYER AUDIT")
        
        try:
            quality = self.db.get_raw_data_quality_report()
            
            self.print_section("Data Quality Metrics")
            print(f"  Total raw records:        {quality['total_raw_records'].values[0]:,}")
            print(f"  Unique raw IDs:           {quality['unique_raw_ids'].values[0]:,}")
            print(f"  Avg columns per record:   {quality['avg_columns'].values[0]:.1f}")
            print(f"  Avg nulls per record:     {quality['avg_nulls_per_record'].values[0]:.1f}")
            print(f"  Min nulls in record:      {quality['min_nulls'].values[0]:.0f}")
            print(f"  Max nulls in record:      {quality['max_nulls'].values[0]:.0f}")
            print(f"  Records with >5 nulls:    {quality['records_with_many_nulls'].values[0]:,}")
            
            self.print_section("Raw Data Sample")
            sample = self.db.get_raw_sample(limit=3)
            print(sample.to_string(index=False))
            
        except Exception as e:
            print(f"  ✗ Error accessing raw layer: {e}")
    
    def audit_processed_layer(self):
        """Audit processed data layer."""
        self.print_header("PROCESSED DATA LAYER AUDIT")
        
        try:
            # Count records
            jobs_count = self.db.query("SELECT COUNT(*) as count FROM jobs").iloc[0]['count']
            
            self.print_section("Data Volume")
            print(f"  Total processed records:  {jobs_count:,}")
            
            # Experience level distribution
            self.print_section("Experience Level Distribution")
            exp_dist = self.db.query("""
                SELECT 
                    experience_level,
                    COUNT(*) as count,
                    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as percentage
                FROM jobs
                GROUP BY experience_level
                ORDER BY count DESC
            """)
            print(exp_dist.to_string(index=False))
            
            # Salary distribution
            self.print_section("Salary Range (Processed)")
            salary_stats = self.db.query("""
                SELECT 
                    ROUND(MIN(salary_max)) as min_salary,
                    ROUND(AVG(salary_max)) as avg_salary,
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY salary_max)) as median,
                    ROUND(MAX(salary_max)) as max_salary
                FROM jobs
            """)
            print(salary_stats.to_string(index=False))
            
            # Top sectors
            self.print_section("Top Sectors")
            sectors = self.db.query("""
                SELECT 
                    sector,
                    COUNT(*) as count,
                    ROUND(AVG(salary_max)) as avg_salary
                FROM jobs
                WHERE sector IS NOT NULL
                GROUP BY sector
                ORDER BY count DESC
                LIMIT 10
            """)
            print(sectors.to_string(index=False))
            
        except Exception as e:
            print(f"  ✗ Error accessing processed layer: {e}")
    
    def audit_data_transformation(self):
        """Compare raw vs processed layers."""
        self.print_header("DATA TRANSFORMATION AUDIT")
        
        try:
            comparison = self.db.compare_raw_vs_processed()
            
            self.print_section("Transformation Summary")
            print(f"  Raw records:              {comparison['raw_count']:,}")
            print(f"  Processed records:        {comparison['processed_count']:,}")
            print(f"  Records lost:             {comparison['records_lost_in_cleaning']:,}")
            print(f"  Retention rate:           {comparison['cleaning_retention_rate']}")
            
            # Analyze loss
            if comparison['records_lost_in_cleaning'] > 0:
                loss_pct = comparison['records_lost_in_cleaning'] / comparison['raw_count'] * 100
                self.print_section("Analysis")
                if loss_pct < 5:
                    print(f"  ✓ Retention is excellent ({loss_pct:.1f}% loss)")
                elif loss_pct < 10:
                    print(f"  ⚠️  Moderate data loss ({loss_pct:.1f}%)")
                    print(f"     Common causes: Invalid salaries, duplicates, missing fields")
                else:
                    print(f"  ✗ High data loss ({loss_pct:.1f}%)")
                    print(f"     Recommend: Review cleaning logic in data_cleaning.py")
            
        except Exception as e:
            print(f"  ✗ Error comparing layers: {e}")
    
    def audit_lineage_sample(self, sample_size=5):
        """Sample lineage audit - trace records from raw to processed."""
        self.print_header("DATA LINEAGE AUDIT (Sample)")
        
        try:
            raw_sample = self.db.get_raw_sample(limit=sample_size)
            
            self.print_section(f"Tracing {len(raw_sample)} Records")
            
            for idx, row in raw_sample.iterrows():
                raw_id = row['raw_id']
                lineage = self.db.audit_data_lineage(raw_id)
                
                status_symbol = "✓" if lineage['transformation_status'] == 'found' else "✗"
                print(f"  {status_symbol} Record {idx+1}: {raw_id}")
                
                if lineage['raw_data']:
                    company = lineage['raw_data'].get('company', 'N/A')
                    title = lineage['raw_data'].get('title', 'N/A')
                    salary_raw = lineage['raw_data'].get('salary', 'N/A')
                    print(f"     Raw:       {company} - {title} ({salary_raw})")
                
                if lineage['processed_data']:
                    salary_min = lineage['processed_data'].get('salary_min', 'N/A')
                    salary_max = lineage['processed_data'].get('salary_max', 'N/A')
                    exp_level = lineage['processed_data'].get('experience_level', 'N/A')
                    print(f"     Processed: ${salary_min:,}-${salary_max:,} | {exp_level}")
                else:
                    print(f"     Processed: ✗ NOT FOUND (filtered during cleaning)")
                print()
        
        except Exception as e:
            print(f"  ✗ Error tracing lineage: {e}")
    
    def full_audit_report(self):
        """Run complete audit report."""
        print("\n" + "╔" + "="*68 + "╗")
        print("║" + " "*68 + "║")
        print("║" + "  🔍 COMPREHENSIVE DATA QUALITY AUDIT REPORT".center(68) + "║")
        print("║" + " "*68 + "║")
        print("╚" + "="*68 + "╝")
        
        self.audit_raw_layer()
        self.audit_processed_layer()
        self.audit_data_transformation()
        self.audit_lineage_sample()
        
        print("\n" + "="*70)
        print("  ✅ AUDIT COMPLETE")
        print("="*70 + "\n")


def main():
    """Run audit from command line."""
    audit = DataAudit()
    audit.full_audit_report()


if __name__ == "__main__":
    main()
