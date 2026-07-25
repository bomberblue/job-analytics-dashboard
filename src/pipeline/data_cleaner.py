"""
Data cleaning pipeline.
Handles missing values, data type conversions, standardization.
"""
import pandas as pd
import re
from datetime import datetime
from config.settings import SALARY_MIN_THRESHOLD, SALARY_MAX_THRESHOLD


class DataCleaner:
    """Clean and preprocess raw job data."""
    
    @staticmethod
    def clean_salary(salary_str):
        """
        Parse salary range from string format.
        Handles formats like: "$3000-5000", "3000 - 5000 SGD", etc.
        
        Returns: (min_salary, max_salary) tuple or (None, None)
        """
        if pd.isna(salary_str):
            return None, None
        
        salary_str = str(salary_str).strip()
        
        # Remove currency symbols and text
        salary_str = re.sub(r'[A-Za-z$\s]', '', salary_str)
        
        # Extract numbers
        numbers = re.findall(r'\d+', salary_str)
        
        if len(numbers) == 2:
            try:
                min_sal = int(numbers[0])
                max_sal = int(numbers[1])
                
                # Filter unrealistic salaries
                if min_sal >= SALARY_MIN_THRESHOLD and max_sal <= SALARY_MAX_THRESHOLD:
                    return min_sal, max_sal
            except:
                pass
        
        return None, None
    
    @staticmethod
    def standardize_experience_level(exp_text):
        """Categorize experience level from text."""
        if pd.isna(exp_text):
            return "Unknown"
        
        exp_text = str(exp_text).lower()
        
        if any(word in exp_text for word in ["junior", "graduate", "fresher", "entry", "intern"]):
            return "Entry Level"
        elif any(word in exp_text for word in ["mid", "senior", "lead", "specialist"]):
            return "Mid Level"
        elif any(word in exp_text for word in ["principal", "director", "manager", "head", "chief"]):
            return "Senior"
        else:
            return "Unknown"
    
    @staticmethod
    def extract_skills(job_desc, job_title):
        """Extract technical skills from job description and title."""
        common_skills = [
            "Python", "Java", "JavaScript", "SQL", "R", "C++", "Go", "Rust",
            "React", "Angular", "Vue", "Django", "Flask", "Spring",
            "AWS", "Azure", "GCP", "Kubernetes", "Docker",
            "Machine Learning", "AI", "Data Science", "Analytics",
            "Salesforce", "SAP", "Oracle", "MySQL", "PostgreSQL",
            "Agile", "Scrum", "DevOps", "CI/CD",
            "Node.js", "Express", "FastAPI",
        ]
        
        text = str(job_desc) + " " + str(job_title)
        text_lower = text.lower()
        
        found_skills = []
        for skill in common_skills:
            if skill.lower() in text_lower:
                found_skills.append(skill)
        
        return ", ".join(found_skills) if found_skills else "Not Specified"
    
    @staticmethod
    def standardize_sector(company_desc, sector_text):
        """Standardize sector classification."""
        if pd.notna(sector_text):
            return str(sector_text).strip()
        
        # Try to infer from company description
        if pd.notna(company_desc):
            desc_lower = str(company_desc).lower()
            if "tech" in desc_lower or "software" in desc_lower:
                return "Technology"
            elif "bank" in desc_lower or "finance" in desc_lower:
                return "Finance"
            elif "health" in desc_lower or "medical" in desc_lower:
                return "Healthcare"
        
        return "Other"
    
    def clean(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Main cleaning function.
        Apply all cleaning steps to raw dataframe.
        """
        print("🧹 Starting data cleaning...")
        df = df.copy()
        
        # Remove duplicates (if columns exist)
        initial_rows = len(df)
        if 'title' in df.columns and 'company' in df.columns:
            df = df.drop_duplicates(subset=['title', 'company'])
            print(f"  ✓ Removed {initial_rows - len(df)} duplicates")
        else:
            print(f"  ⓘ Skipped duplicate removal (title/company columns not found)")
        
        # Clean salary data (handle both combined and separate columns)
        print("  → Parsing salaries...")
        if 'salary' in df.columns:
            salary_data = df['salary'].apply(self.clean_salary)
            df['salary_min'] = salary_data.apply(lambda x: x[0])
            df['salary_max'] = salary_data.apply(lambda x: x[1])
        elif 'salary_min' in df.columns and 'salary_max' in df.columns:
            # Already have min/max from CSV - ensure they're numeric
            df['salary_min'] = pd.to_numeric(df['salary_min'], errors='coerce')
            df['salary_max'] = pd.to_numeric(df['salary_max'], errors='coerce')
            print(f"  ✓ Using salary_min and salary_max from source")
        else:
            # Set defaults if no salary data
            df['salary_min'] = None
            df['salary_max'] = None
        
        # Filter rows with valid salary data
        df = df.dropna(subset=['salary_min', 'salary_max'])
        print(f"  ✓ Retained {len(df)} rows with valid salary data")
        
        # Standardize text fields
        if 'experience' in df.columns:
            df['experience_level'] = df['experience'].apply(self.standardize_experience_level)
        else:
            df['experience_level'] = 'Unknown'
            
        if 'sector' in df.columns:
            df['sector'] = df.apply(
                lambda row: self.standardize_sector(row.get('company_description', ''), row.get('sector', '')),
                axis=1
            )
        else:
            df['sector'] = 'Other'
        
        # Extract and standardize skills
        print("  → Extracting skills...")
        df['skills'] = df.apply(
            lambda row: self.extract_skills(row.get('description', ''), row.get('title', '')),
            axis=1
        )
        
        # Parse dates
        if 'posting_date' in df.columns:
            df['posting_date'] = pd.to_datetime(df['posting_date'], errors='coerce')
        else:
            df['posting_date'] = pd.Timestamp.now()
        
        # Standardize location
        if 'location' in df.columns:
            df['location'] = df['location'].fillna('Not Specified').str.title()
        else:
            df['location'] = 'Singapore'
        
        # Create job_id if not exists
        if 'job_id' not in df.columns:
            df['job_id'] = df.apply(
                lambda row: f"{row['company']}_{row['title']}_{row['posting_date']}"[:100],
                axis=1
            )
        
        print(f"✅ Cleaning complete: {len(df)} rows")
        return df
