"""
Feature engineering and transformation pipeline.
Creates analytical features for the dashboard.
"""
import pandas as pd
import numpy as np
from config.settings import EXPERIENCE_LEVELS


class FeatureEngineer:
    """Engineer features for analytics and modeling."""
    
    @staticmethod
    def create_salary_band(min_sal, max_sal):
        """Create salary band categories."""
        if pd.isna(max_sal):
            return "Unknown"
        
        if max_sal < 3000:
            return "Entry (< $3k)"
        elif max_sal < 5000:
            return "Mid ($3-5k)"
        elif max_sal < 8000:
            return "Senior ($5-8k)"
        else:
            return "Executive (> $8k)"
    
    @staticmethod
    def calculate_salary_midpoint(min_sal, max_sal):
        """Calculate salary midpoint."""
        if pd.notna(min_sal) and pd.notna(max_sal):
            return (min_sal + max_sal) / 2
        return None
    
    @staticmethod
    def extract_seniority_years(experience_level_text):
        """Extract years of experience from text."""
        if pd.isna(experience_level_text):
            return 0
        
        text = str(experience_level_text).lower()
        
        # Look for patterns like "5 years", "5+ years"
        import re
        match = re.search(r'(\d+)\+?\s*(?:years|yrs)', text)
        if match:
            return int(match.group(1))
        
        # Map experience levels to typical years
        if any(word in text for word in ["entry", "junior", "graduate", "intern"]):
            return 0
        elif any(word in text for word in ["mid", "senior"]):
            return 3
        elif any(word in text for word in ["principal", "director", "manager"]):
            return 8
        
        return 0
    
    @staticmethod
    def get_skill_count(skills_text):
        """Count number of skills required."""
        if pd.isna(skills_text):
            return 0
        return len([s for s in str(skills_text).split(',') if s.strip()])
    
    @staticmethod
    def identify_growth_roles(df_historical):
        """Identify roles with growing demand."""
        if df_historical is None or len(df_historical) < 2:
            return []
        
        role_counts = df_historical.groupby('title').size()
        growth_threshold = role_counts.median() * 0.2  # 20% above median
        
        return role_counts[role_counts > growth_threshold].index.tolist()
    
    @staticmethod
    def calculate_skill_premium(skill_name, df):
        """Calculate salary premium for a specific skill."""
        with_skill = df[df['skills'].str.contains(skill_name, case=False, na=False)]
        without_skill = df[~df['skills'].str.contains(skill_name, case=False, na=False)]
        
        if len(with_skill) == 0 or len(without_skill) == 0:
            return 0
        
        avg_with = with_skill['salary_midpoint'].mean()
        avg_without = without_skill['salary_midpoint'].mean()
        
        if pd.isna(avg_without) or avg_without == 0:
            return 0
        
        return ((avg_with - avg_without) / avg_without * 100)
    
    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Main feature engineering function.
        Create all analytical features.
        """
        print("🔨 Engineering features...")
        df = df.copy()
        
        # Salary features
        df['salary_midpoint'] = df.apply(
            lambda row: self.calculate_salary_midpoint(row['salary_min'], row['salary_max']),
            axis=1
        )
        df['salary_band'] = df.apply(
            lambda row: self.create_salary_band(row['salary_min'], row['salary_max']),
            axis=1
        )
        
        # Experience features. Prefer the numeric years straight from the source;
        # deriving them from the experience_level label loses all resolution.
        if 'min_years_experience' in df.columns:
            df['seniority_years'] = (
                pd.to_numeric(df['min_years_experience'], errors='coerce')
                .fillna(0).astype(int)
            )
        else:
            df['seniority_years'] = df['experience_level'].apply(self.extract_seniority_years)
        
        # Skills features
        df['skill_count'] = df['skills'].apply(self.get_skill_count)
        
        # Demand features (if we have historical data)
        df['is_growth_role'] = df['title'].isin(
            self.identify_growth_roles(df.head(1000))
        ).astype(int)
        
        # Competitiveness score (simple: high salary + high skill count = highly competitive)
        df['competitiveness_score'] = (
            (df['salary_midpoint'] / df['salary_midpoint'].max() * 50) +
            (df['skill_count'] / df['skill_count'].max() * 50)
        ).fillna(25)
        
        # Days since posting (for trend analysis)
        if 'posting_date' in df.columns:
            df['days_posted'] = (pd.Timestamp.now() - df['posting_date']).dt.days
        else:
            df['days_posted'] = 0
        
        print(f"✅ Feature engineering complete")
        return df
