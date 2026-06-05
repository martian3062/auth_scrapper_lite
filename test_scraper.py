import os
import json
import subprocess
import sys
import unittest

class TestCTRIScraper(unittest.TestCase):
    def setUp(self):
        self.output_file = "test_results.json"
        self.progress_file = "test_progress.json"
        
        # Clean up existing test output files
        for f in [self.output_file, self.progress_file]:
            if os.path.exists(f):
                os.remove(f)

    def tearDown(self):
        # Clean up test files after runs
        for f in [self.output_file, self.progress_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass

    def test_limited_run(self):
        """Runs the scraper with a limit of 3 records and verifies the output JSON structure."""
        print("\nRunning test execution of CTRIScraper on CTRI with limit of 3 records...")
        
        # Run scraper.py as a subprocess
        cmd = [
            sys.executable, "scraper.py",
            "--keyword", "lung",
            "--max-records", "3",
            "--output", self.output_file,
            "--progress", self.progress_file,
            "--workers", "3"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("Scraper output:")
        print(result.stdout)
        print("Scraper error output (if any):")
        print(result.stderr)
        
        # Ensure it completed with 0 status code
        self.assertEqual(result.returncode, 0, f"Scraper execution failed with code {result.returncode}")
        
        # Verify output file exists
        self.assertTrue(os.path.exists(self.output_file), "Output file was not created by the scraper")
        
        # Load and parse output JSON
        with open(self.output_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        print(f"Scraped records count: {len(data)}")
        self.assertGreater(len(data), 0, "No records were successfully scraped")
        self.assertLessEqual(len(data), 3, f"Scraper returned {len(data)} records, which exceeds the limit of 3")
        
        # Verify schema elements in each record
        for record in data:
            print(f"Verifying record: {record.get('ctri_number')}")
            self.assertIn("ctri_number", record)
            self.assertIn("public_title", record)
            self.assertIn("type_of_trial", record)
            self.assertIn("recruitment_status_india", record)
            
            # Check a few nested schemas if present
            self.assertIn("principal_investigator", record)
            self.assertIn("primary_sponsor", record)
            self.assertIn("inclusion_criteria", record)
            self.assertIn("exclusion_criteria", record)
            self.assertIn("ethics_committees", record)
            
        print("All assertions passed. Test run succeeded!")

if __name__ == "__main__":
    unittest.main()
