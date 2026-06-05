import os
import re
import sys
import json
import time
import base64
import argparse
from io import BytesIO
import requests
import urllib3
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from groq import Groq
from dotenv import load_dotenv
from schema import (
    ClinicalTrial, SecondaryID, ContactDetails, Sponsor, SecondarySponsor,
    SiteOfStudy, EthicsCommittee, RegulatoryClearance, HealthCondition,
    Intervention, InclusionCriteria, ExclusionCriteria, Outcome,
    TargetSampleSize, TrialDuration
)

# Disable SSL verification warnings for CTRI website
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

def clean_captcha_text(text):
    return re.sub(r'[^a-zA-Z0-9]', '', text or '').strip()

def get_groq_api_keys(api_key=None):
    keys = []
    for value in [
        api_key,
        os.environ.get("GROQ_API_KEY"),
        os.environ.get("GROQ_API_KEY_FALLBACK"),
    ]:
        if value and value not in keys:
            keys.append(value)

    for value in os.environ.get("GROQ_API_KEYS", "").split(","):
        value = value.strip()
        if value and value not in keys:
            keys.append(value)

    return keys

class CTRIScraper:
    def __init__(self, keyword="lung", max_records=None, output_file="ctri_results.json",
                 progress_file="ctri_progress.json", workers=5, delay=0.5, api_key=None):
        self.keyword = keyword
        self.max_records = max_records
        self.output_file = output_file
        self.progress_file = progress_file
        self.workers = workers
        self.delay = delay
        self.groq_api_keys = get_groq_api_keys(api_key)
        self.captcha_solvers = [
            solver.strip().lower()
            for solver in os.environ.get("CAPTCHA_SOLVERS", "groq,tesseract,manual").split(",")
            if solver.strip()
        ]
        
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        
        # State tracking
        self.trials_list = []
        self.scraped_data = {}
        
    def load_progress(self):
        """Loads progress from the checkpoint file if it exists and matches parameters."""
        if os.path.exists(self.progress_file):
            try:
                with open(self.progress_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("keyword") == self.keyword:
                    self.trials_list = state.get("trials_list", [])
                    self.scraped_data = state.get("scraped_data", {})
                    # Load cookies if they were saved
                    cookies = state.get("session_cookies", {})
                    if cookies:
                        self.session.cookies.update(cookies)
                    print(f"Loaded progress: {len(self.scraped_data)} of {len(self.trials_list)} trials already scraped.")
                    return True
            except Exception as e:
                print(f"Warning: Failed to load progress file: {e}. Starting fresh.")
        return False

    def save_progress(self):
        """Saves current state to progress file."""
        state = {
            "keyword": self.keyword,
            "session_cookies": self.session.cookies.get_dict(),
            "trials_list": self.trials_list,
            "scraped_data": self.scraped_data
        }
        try:
            with open(self.progress_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save progress: {e}")

    def _solve_captcha_with_groq(self, base64_image):
        if not self.groq_api_keys:
            print("No Groq API keys configured; skipping Groq CAPTCHA solver.")
            return None

        last_error = None
        for idx, groq_api_key in enumerate(self.groq_api_keys, start=1):
            try:
                client = Groq(api_key=groq_api_key)
                response = client.chat.completions.create(
                    model="meta-llama/llama-4-scout-17b-16e-instruct",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "This is a CAPTCHA image. Please output ONLY the exact 6 characters visible in this image (letters and numbers, case sensitive), with no spaces, punctuation, explanation or other text."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ]
                )
                captcha_text = clean_captcha_text(response.choices[0].message.content)
                if captcha_text:
                    print(f"Groq solved CAPTCHA with key {idx}/{len(self.groq_api_keys)}: '{captcha_text}'")
                    return captcha_text
            except Exception as e:
                last_error = e
                print(f"Groq key {idx}/{len(self.groq_api_keys)} failed: {e}")

        print(f"All Groq API keys failed. Last error: {last_error}")
        return None

    def _solve_captcha_with_tesseract(self, captcha_bytes):
        try:
            from PIL import Image
            import pytesseract

            image = Image.open(BytesIO(captcha_bytes)).convert("L")
            captcha_text = clean_captcha_text(
                pytesseract.image_to_string(
                    image,
                    config="--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                )
            )
            if captcha_text:
                print(f"Tesseract solved CAPTCHA: '{captcha_text}'")
                return captcha_text
            print("Tesseract returned an empty CAPTCHA result.")
        except Exception as e:
            print(f"Tesseract CAPTCHA fallback failed: {e}")
        return None

    def _solve_captcha_manually(self):
        if not sys.stdin.isatty():
            print("Manual CAPTCHA fallback skipped because stdin is not interactive.")
            return None

        captcha_text = clean_captcha_text(input("Enter CAPTCHA text from the current CTRI image: "))
        if captcha_text:
            print("Manual CAPTCHA fallback received input.")
            return captcha_text
        return None

    def solve_captcha(self):
        """Downloads CAPTCHA and solves it with configured fallback solvers."""
        url_main = "https://ctri.nic.in/Clinicaltrials/advancesearchmain.php"
        url_captcha = "https://ctri.nic.in/Clinicaltrials/advancesearch.php?action=captcha"
        
        print("Fetching advancesearchmain.php for tokens...")
        r_main = self.session.get(url_main, verify=False)
        if r_main.status_code != 200:
            raise Exception(f"Failed to load search page: {r_main.status_code}")
            
        soup = BeautifulSoup(r_main.text, 'html.parser')
        
        # Extract hidden inputs
        csrf_token_tag = soup.find('input', {'name': 'csrf_token'})
        csrf_token = csrf_token_tag['value'] if csrf_token_tag else ''
        
        ncforminfo_tag = soup.find('input', {'name': '__ncforminfo'})
        ncforminfo = ncforminfo_tag['value'] if ncforminfo_tag else ''
        
        if not csrf_token:
            print("Warning: csrf_token not found in page HTML.")
            
        print("Downloading CAPTCHA image...")
        r_captcha = self.session.get(url_captcha, verify=False)
        if r_captcha.status_code != 200:
            raise Exception(f"Failed to download captcha image: {r_captcha.status_code}")
            
        base64_image = base64.b64encode(r_captcha.content).decode('utf-8')

        captcha_text = None
        for solver in self.captcha_solvers:
            print(f"Trying CAPTCHA solver: {solver}")
            if solver == "groq":
                captcha_text = self._solve_captcha_with_groq(base64_image)
            elif solver == "tesseract":
                captcha_text = self._solve_captcha_with_tesseract(r_captcha.content)
            elif solver == "manual":
                captcha_text = self._solve_captcha_manually()
            else:
                print(f"Unknown CAPTCHA solver '{solver}', skipping.")

            if captcha_text:
                break

        if not captcha_text:
            raise Exception(f"Failed to solve CAPTCHA with configured solvers: {', '.join(self.captcha_solvers)}")
        
        return csrf_token, ncforminfo, captcha_text

    def execute_search(self):
        """Performs form submission and retrieves the list of trial records."""
        url_search = "https://ctri.nic.in/Clinicaltrials/advsearch.php"
        url_main = "https://ctri.nic.in/Clinicaltrials/advancesearchmain.php"
        
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            print(f"\n--- Search Attempt {attempt}/{max_attempts} ---")
            try:
                csrf_token, ncforminfo, captcha_text = self.solve_captcha()
                
                # Setup parameters to query all trials matching the keyword
                post_data = {
                    "csrf_token": csrf_token,
                    "pros": "0",  # ALL
                    "stid": "0",  # ALL
                    "month": "0", # ALL
                    "year": "0",  # ALL
                    "study": "0",
                    "sdid": "0",
                    "phaseid": "0",
                    "psponsor": "0",
                    "recid": "0",
                    "state": "0",
                    "district": "0",
                    "searchword": self.keyword,
                    "T9": captcha_text,
                    "btt": "Search",
                    "__ncforminfo": ncforminfo
                }
                
                headers = {
                    "Referer": url_main,
                    "Origin": "https://ctri.nic.in",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                print(f"Submitting search form for keyword '{self.keyword}'...")
                r_search = self.session.post(url_search, data=post_data, headers=headers, verify=False)
                
                if "Please Enter Security Code in the TextBox" in r_search.text or "Security Code" in r_search.text and "TextBox" in r_search.text:
                    print("CAPTCHA verification failed on server side. Retrying...")
                    time.sleep(1)
                    continue
                    
                # Parse list of trials
                soup = BeautifulSoup(r_search.text, 'html.parser')
                text_content = soup.get_text()
                
                records_found = "0"
                match_rec = re.search(r'Total\s+Records\s+Found\s*=\s*"([^"]+)"', text_content, re.IGNORECASE)
                if match_rec:
                    records_found = match_rec.group(1).strip()
                
                # Check for "Total Records Found"
                print(f"Server response indicates: '{records_found}' records found.")
                
                # Find trial table rows
                self.trials_list = []
                rows = soup.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 8:
                        # Extract the view link javascript
                        links = row.find_all('a')
                        detail_url = None
                        for link in links:
                            href = link.get('href', '')
                            if "pmaindet2.php" in href:
                                # javascript:newwin2('pmaindet2.php?EncHid=MTg5&Enc=&userName=lung')
                                match_url = re.search(r"'(pmaindet2\.php[^']+)'", href)
                                if match_url:
                                    detail_url = "https://ctri.nic.in/Clinicaltrials/" + match_url.group(1)
                                    break
                        
                        if detail_url:
                            ctri_no = cells[0].get_text(strip=True)
                            # Verify if it looks like a CTRI number
                            if "CTRI/" in ctri_no:
                                self.trials_list.append({
                                    "ctri_number": ctri_no,
                                    "public_title": cells[1].get_text(strip=True),
                                    "type_of_trial": cells[2].get_text(strip=True),
                                    "recruitment_status": cells[3].get_text(strip=True),
                                    "health_condition": cells[4].get_text(strip=True),
                                    "detail_url": detail_url
                                })
                
                print(f"Extracted {len(self.trials_list)} trial links from result table.")
                if not self.trials_list and int(records_found.split()[0]) > 0:
                    print("Warning: Found records but failed to extract rows. Search page format may have changed.")
                
                self.save_progress()
                return
                
            except Exception as e:
                print(f"Error during search attempt {attempt}: {e}")
                time.sleep(2)
                
        raise Exception(f"Failed to submit search successfully after {max_attempts} attempts.")

    # Detail page table parsing helpers
    def _parse_contact_table(self, inner_table):
        data = {}
        if not inner_table:
            return None
        for tr in inner_table.find_all('tr', recursive=False):
            tds = tr.find_all('td', recursive=False)
            if len(tds) == 2:
                k = tds[0].get_text(strip=True).lower()
                v = tds[1].get_text(strip=True)
                # Clean value
                v = re.sub(r'\s+', ' ', v).strip()
                if v.endswith('&nbsp') or v.endswith(u'\xa0'):
                    v = v[:-5].strip()
                if "name" in k:
                    data["name"] = v
                elif "designation" in k:
                    data["designation"] = v
                elif "affiliation" in k:
                    data["affiliation"] = v
                elif "address" in k:
                    data["address"] = v
                elif "phone" in k:
                    data["phone"] = v
                elif "fax" in k:
                    data["fax"] = v
                elif "email" in k:
                    data["email"] = v
        return ContactDetails(**data) if data else None

    def _parse_columns_table(self, inner_table):
        rows_data = []
        if not inner_table:
            return rows_data
        trs = inner_table.find_all('tr', recursive=False)
        if not trs:
            return rows_data
            
        # Skip header if first row looks like a header
        start_idx = 0
        header_tds = trs[0].find_all('td', recursive=False)
        if header_tds:
            first_text = header_tds[0].get_text(strip=True)
            if first_text in ["Secondary ID", "Name of Principal Investigator", "Name of Committee", 
                              "Status", "Health Type", "Type", "Outcome", "Name of Principal\nInvestigator"]:
                start_idx = 1
                
        for tr in trs[start_idx:]:
            tds = []
            for td in tr.find_all('td', recursive=False):
                txt = td.get_text(strip=True)
                txt = re.sub(r'\s+', ' ', txt).strip()
                tds.append(txt)
            if tds:
                rows_data.append(tds)
        return rows_data

    def parse_detail_html(self, html_content, ctri_number):
        """Parses a detailed trial popup HTML page and constructs a ClinicalTrial dictionary."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        def get_table_nesting_depth(element):
            count = 0
            p = element.parent
            while p:
                if p.name == 'table':
                    count += 1
                p = p.parent
            return count
            
        trial_data = {"ctri_number": ctri_number}
        
        # Extract row by row for top-level rows (nesting depth 1 or 2)
        for tr in soup.find_all('tr'):
            if get_table_nesting_depth(tr) not in [1, 2]:
                continue
            tds = tr.find_all('td', recursive=False)
            if len(tds) != 2:
                continue
                
            label = tds[0].get_text(strip=True).replace(u'\xa0', ' ').replace(':', '').strip()
            # Clean duplicate whitespaces
            label = re.sub(r'\s+', ' ', label)
            
            value_td = tds[1]
            value_text = value_td.get_text(strip=True).replace(u'\xa0', ' ').strip()
            value_text = re.sub(r'\s+', ' ', value_text)
            
            if not label:
                continue
                
            # Parse based on label string matching
            if "CTRI Number" in label:
                # Value contains "CTRI/2013/10/004108 [Registered on: 29/10/2013] Trial Registered Retrospectively"
                trial_data["retrospective_registration"] = "Retrospectively" in value_text
                match_date = re.search(r'Registered\s+on:\s*(\d{2}/\d{2}/\d{4})', value_text, re.IGNORECASE)
                if match_date:
                    trial_data["registration_date"] = match_date.group(1)
            elif "Last Modified On" in label:
                trial_data["last_modified_on"] = value_text
            elif "Post Graduate Thesis" in label:
                trial_data["post_graduate_thesis"] = value_text
            elif "Type of Trial" in label:
                trial_data["type_of_trial"] = value_text
            elif "Type of Study" in label:
                trial_data["type_of_study"] = value_text
            elif "Study Design" in label:
                trial_data["study_design"] = value_text
            elif "Public Title of Study" in label:
                trial_data["public_title"] = value_text
            elif "Scientific Title of Study" in label:
                trial_data["scientific_title"] = value_text
            elif "Trial Acronym" in label:
                trial_data["trial_acronym"] = value_text
            elif "Secondary IDs if Any" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["secondary_ids"] = [
                    SecondaryID(secondary_id=r[0], identifier=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Details of Principal Investigator" in label:
                inner_table = value_td.find('table')
                trial_data["principal_investigator"] = self._parse_contact_table(inner_table)
            elif "Details of Contact Person" in label and "Scientific Query" in label:
                inner_table = value_td.find('table')
                trial_data["contact_person_scientific"] = self._parse_contact_table(inner_table)
            elif "Details of Contact Person" in label and "Public Query" in label:
                inner_table = value_td.find('table')
                trial_data["contact_person_public"] = self._parse_contact_table(inner_table)
            elif "Source of Monetary or Material Support" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["sources_of_monetary_support"] = [r[0] for r in rows if r]
            elif "Primary Sponsor" in label:
                inner_table = value_td.find('table')
                if inner_table:
                    s_data = {}
                    for s_tr in inner_table.find_all('tr'):
                        s_tds = s_tr.find_all('td')
                        if len(s_tds) == 2:
                            s_k = s_tds[0].get_text(strip=True).lower()
                            s_v = s_tds[1].get_text(strip=True)
                            if "name" in s_k:
                                s_data["name"] = s_v
                            elif "address" in s_k:
                                s_data["address"] = s_v
                            elif "type" in s_k:
                                s_data["type_of_sponsor"] = s_v
                    trial_data["primary_sponsor"] = Sponsor(**s_data) if s_data else None
            elif "Details of Secondary Sponsor" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["secondary_sponsors"] = [
                    SecondarySponsor(name=r[0], address=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Countries of Recruitment" in label:
                countries = [c.strip() for c in value_text.split(',') if c.strip()]
                trial_data["countries_of_recruitment"] = countries
            elif "Sites of Study" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["sites_of_study"] = [
                    SiteOfStudy(
                        pi_name=r[0] if len(r) > 0 else None,
                        site_name=r[1] if len(r) > 1 else None,
                        site_address=r[2] if len(r) > 2 else None,
                        contact_details=r[3] if len(r) > 3 else None
                    )
                    for r in rows if len(r) >= 1
                ]
            elif "Details of Ethics Committee" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["ethics_committees"] = [
                    EthicsCommittee(committee_name=r[0] if len(r) > 0 else None, approval_status=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Regulatory Clearance Status from DCGI" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                if rows:
                    trial_data["regulatory_clearance_dcgi"] = RegulatoryClearance(status=rows[0][0])
            elif "Health Condition" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["health_conditions"] = [
                    HealthCondition(health_type=r[0] if len(r) > 0 else None, condition=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Intervention" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["interventions"] = [
                    Intervention(
                        type=r[0] if len(r) > 0 else None,
                        name=r[1] if len(r) > 1 else None,
                        details=r[2] if len(r) > 2 else None
                    )
                    for r in rows if len(r) >= 1
                ]
            elif "Inclusion Criteria" in label:
                inner_table = value_td.find('table')
                if inner_table:
                    inc_data = {}
                    for inc_tr in inner_table.find_all('tr'):
                        inc_tds = inc_tr.find_all('td')
                        if len(inc_tds) == 2:
                            inc_k = inc_tds[0].get_text(strip=True).lower()
                            inc_v = inc_tds[1].get_text(strip=True)
                            if "age from" in inc_k:
                                inc_data["age_from"] = inc_v
                            elif "age to" in inc_k:
                                inc_data["age_to"] = inc_v
                            elif "gender" in inc_k:
                                inc_data["gender"] = inc_v
                            elif "details" in inc_k:
                                inc_data["details"] = inc_v
                    trial_data["inclusion_criteria"] = InclusionCriteria(**inc_data) if inc_data else None
            elif "ExclusionCriteria" in label or "Exclusion Criteria" in label:
                inner_table = value_td.find('table')
                if inner_table:
                    exc_data = {}
                    for exc_tr in inner_table.find_all('tr'):
                        exc_tds = exc_tr.find_all('td')
                        if len(exc_tds) == 2:
                            exc_k = exc_tds[0].get_text(strip=True).lower()
                            exc_v = exc_tds[1].get_text(strip=True)
                            if "details" in exc_k:
                                exc_data["details"] = exc_v
                    # fallback: if no subtable format but plain text
                    if not exc_data:
                        txt = inner_table.get_text(strip=True)
                        if txt:
                            exc_data["details"] = txt
                    trial_data["exclusion_criteria"] = ExclusionCriteria(**exc_data) if exc_data else None
            elif "Method of Generating Random Sequence" in label:
                trial_data["method_random_sequence"] = value_text
            elif "Method of Concealment" in label:
                trial_data["method_concealment"] = value_text
            elif "Blinding/Masking" in label:
                trial_data["blinding_masking"] = value_text
            elif "Primary Outcome" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["primary_outcomes"] = [
                    Outcome(outcome=r[0] if len(r) > 0 else None, timepoints=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Secondary Outcome" in label:
                inner_table = value_td.find('table')
                rows = self._parse_columns_table(inner_table)
                trial_data["secondary_outcomes"] = [
                    Outcome(outcome=r[0] if len(r) > 0 else None, timepoints=r[1] if len(r) > 1 else None)
                    for r in rows if len(r) >= 1
                ]
            elif "Target Sample Size" in label:
                # total_sample_size, sample_size_india, final_enrollment_total, final_enrollment_india
                total_sz = re.search(r'Total\s+Sample\s+Size\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                india_sz = re.search(r'Sample\s+Size\s+from\s+India\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                final_total = re.search(r'Final\s+Enrollment\s+numbers\s+achieved\s*\(Total\)\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                final_india = re.search(r'Final\s+Enrollment\s+numbers\s+achieved\s*\(India\)\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                trial_data["target_sample_size"] = TargetSampleSize(
                    total_sample_size=total_sz.group(1).strip() if total_sz else None,
                    sample_size_india=india_sz.group(1).strip() if india_sz else None,
                    final_enrollment_total=final_total.group(1).strip() if final_total else None,
                    final_enrollment_india=final_india.group(1).strip() if final_india else None
                )
            elif "Phase of Trial" in label:
                trial_data["phase"] = value_text
            elif "Date of First Enrollment (India)" in label:
                trial_data["first_enrollment_date_india"] = value_text
            elif "Date of Study Completion (India)" in label:
                trial_data["study_completion_date_india"] = value_text
            elif "Date of First Enrollment (Global)" in label:
                trial_data["first_enrollment_date_global"] = value_text
            elif "Date of Study Completion (Global)" in label:
                trial_data["study_completion_date_global"] = value_text
            elif "Estimated Duration of Trial" in label:
                years = re.search(r'Years\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                months = re.search(r'Months\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                days = re.search(r'Days\s*=\s*"([^"]*)"', value_text, re.IGNORECASE)
                trial_data["duration"] = TrialDuration(
                    years=years.group(1).strip() if years else None,
                    months=months.group(1).strip() if months else None,
                    days=days.group(1).strip() if days else None
                )
            elif "Recruitment Status of Trial (Global)" in label:
                trial_data["recruitment_status_global"] = value_text
            elif "Recruitment Status of Trial (India)" in label:
                trial_data["recruitment_status_india"] = value_text
            elif "Publication Details" in label:
                trial_data["publication_details"] = value_text
            elif "Individual Participant Data (IPD) Sharing Statement" in label:
                # Text usually spans across nested divs/tables
                trial_data["ipd_sharing_statement"] = value_text
            elif "Brief Summary" in label:
                trial_data["summary"] = value_text

        # Validate using Pydantic model
        trial_model = ClinicalTrial(**trial_data)
        return trial_model.model_dump()

    def scrape_single_detail(self, trial_info):
        """Fetches and parses a single trial detail page."""
        ctri_number = trial_info["ctri_number"]
        detail_url = trial_info["detail_url"]
        
        # If already scraped, skip
        if ctri_number in self.scraped_data:
            return ctri_number, self.scraped_data[ctri_number], True
            
        time.sleep(self.delay)
        
        try:
            r = self.session.get(detail_url, verify=False)
            if r.status_code != 200:
                raise Exception(f"HTTP error {r.status_code}")
                
            parsed_dict = self.parse_detail_html(r.text, ctri_number)
            return ctri_number, parsed_dict, False
        except Exception as e:
            print(f"Error scraping trial {ctri_number}: {e}")
            return ctri_number, None, False

    def scrape_details(self):
        """Scrapes all detail pages concurrently using a ThreadPoolExecutor."""
        to_scrape = self.trials_list
        if self.max_records:
            to_scrape = self.trials_list[:self.max_records]
            print(f"Limiting scraping to the first {self.max_records} records.")
            
        print(f"Starting detailed page extraction for {len(to_scrape)} records using {self.workers} workers...")
        
        completed_count = 0
        save_counter = 0
        
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            # Submit all tasks
            futures = {executor.submit(self.scrape_single_detail, trial): trial for trial in to_scrape}
            
            for future in as_completed(futures):
                trial = futures[future]
                ctri_number, parsed_data, was_cached = future.result()
                
                if parsed_data:
                    self.scraped_data[ctri_number] = parsed_data
                    completed_count += 1
                    save_counter += 1
                    
                    if not was_cached:
                        print(f"[{completed_count}/{len(to_scrape)}] Scraped and parsed {ctri_number}")
                    
                    # Auto-save checkpoint every 10 parsed pages
                    if save_counter >= 10:
                        self.save_progress()
                        save_counter = 0
                else:
                    print(f"Failed to scrape details for {ctri_number}")
                    
        # Final checkpoint save
        self.save_progress()
        print("Scraping completed successfully.")

    def export_results(self):
        """Writes the final results into a JSON file."""
        final_list = list(self.scraped_data.values())
        
        # Limit to max_records if necessary (in case more were loaded from progress)
        if self.max_records and len(final_list) > self.max_records:
            final_list = final_list[:self.max_records]
            
        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(final_list, f, indent=2, ensure_ascii=False)
            print(f"Exported {len(final_list)} validated records to {self.output_file}")
            
            # Remove checkpoint file upon successful full completion
            if len(final_list) >= len(self.trials_list) and os.path.exists(self.progress_file):
                os.remove(self.progress_file)
                print("Cleaned up progress checkpoint file.")
        except Exception as e:
            print(f"Error exporting results to {self.output_file}: {e}")

    def run(self):
        """Starts the full scraper sequence."""
        # 1. Try to load progress
        has_progress = self.load_progress()
        
        # 2. If no progress, execute the search
        if not has_progress or not self.trials_list:
            print("No existing progress found. Initiating CTRI search...")
            self.execute_search()
            
        # 3. Scrape detail pages
        if self.trials_list:
            self.scrape_details()
            
        # 4. Save results to output JSON
        self.export_results()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CTRI Clinical Trial Registry - India Web Scraper")
    parser.add_argument("--keyword", type=str, default="lung", help="Search keyword (default: lung)")
    parser.add_argument("--max-records", type=int, default=None, help="Maximum number of trial detail records to scrape")
    parser.add_argument("--output", type=str, default="ctri_results.json", help="Output JSON file path")
    parser.add_argument("--progress", type=str, default="ctri_progress.json", help="Checkpoint file path")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent scraper workers")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to sleep between request (politeness factor)")
    parser.add_argument("--api-key", type=str, default=None, help="Groq API Key (falls back to GROQ_API_KEY environment var)")
    parser.add_argument("--no-resume", action="store_true", help="Do not resume from progress checkpoint file")
    
    args = parser.parse_args()
    
    if args.no_resume and os.path.exists(args.progress):
        try:
            os.remove(args.progress)
            print(f"Removed progress file '{args.progress}' as requested by --no-resume")
        except Exception as e:
            print(f"Error removing progress file: {e}")
            
    scraper = CTRIScraper(
        keyword=args.keyword,
        max_records=args.max_records,
        output_file=args.output,
        progress_file=args.progress,
        workers=args.workers,
        delay=args.delay,
        api_key=args.api_key
    )
    
    start_time = time.time()
    scraper.run()
    elapsed = time.time() - start_time
    print(f"\nExecution finished in {elapsed:.2f} seconds.")
