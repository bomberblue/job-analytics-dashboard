"""
Sample unit tests for the data pipeline.
"""
import unittest
import pandas as pd
from src.pipeline.data_cleaner import DataCleaner


class TestDataCleaner(unittest.TestCase):
    """Test data cleaning functions."""
    
    def setUp(self):
        self.cleaner = DataCleaner()
    
    def test_clean_salary_valid_format(self):
        """Test salary parsing with valid format."""
        min_sal, max_sal = self.cleaner.clean_salary("$3000-5000")
        self.assertEqual(min_sal, 3000)
        self.assertEqual(max_sal, 5000)
    
    def test_clean_salary_invalid_format(self):
        """Test salary parsing with invalid format."""
        min_sal, max_sal = self.cleaner.clean_salary("invalid")
        self.assertIsNone(min_sal)
        self.assertIsNone(max_sal)
    
    def test_standardize_experience_level(self):
        """Test experience level standardization."""
        self.assertEqual(self.cleaner.standardize_experience_level("junior developer"), "Entry Level")
        self.assertEqual(self.cleaner.standardize_experience_level("senior engineer"), "Mid Level")
        self.assertEqual(self.cleaner.standardize_experience_level("principal architect"), "Senior")
    
    def test_extract_skills(self):
        """Test skill extraction from text."""
        skills = self.cleaner.extract_skills(
            "Experience with Python and SQL required. AWS/GCP knowledge preferred.",
            "Data Engineer"
        )
        self.assertIn("Python", skills)
        self.assertIn("SQL", skills)


if __name__ == '__main__':
    unittest.main()
