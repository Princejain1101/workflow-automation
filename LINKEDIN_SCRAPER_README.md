# LinkedIn Candidate Email Scraper

A Python script to collect email addresses and contact information from candidates who applied to your LinkedIn job posts.

## Features

- ✅ Automated browser interaction with LinkedIn
- ✅ Persistent login session (login once, reuse session)
- ✅ Extracts candidate information (name, email, profile URL, location)
- ✅ Exports data to CSV format
- ✅ Robust error handling and retry logic
- ✅ User-friendly progress indicators

## Prerequisites

1. **Python 3.8+** installed on your system
2. **LinkedIn account** with active job postings
3. **LinkedIn Recruiter** (recommended for email access)

> **Important Note**: Email addresses are typically only accessible with a LinkedIn Recruiter subscription. Without it, you can still collect names and profile URLs.

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Basic Usage

Run the script:
```bash
python linkedin_candidate_scraper.py
```

The script will:
1. Open a browser window
2. Ask you to log in to LinkedIn (first time only)
3. Prompt you for your job post URL
4. Scrape candidate information
5. Save results to a CSV file

### Example

```bash
$ python linkedin_candidate_scraper.py

============================================================
🔷 LinkedIn Candidate Email Scraper
============================================================

Please enter the URL of your LinkedIn job post:
Example: https://www.linkedin.com/jobs/view/1234567890

Job URL: https://www.linkedin.com/jobs/view/3850394857

🌐 Starting browser with persistent session...
✅ Browser started successfully
🔐 Checking LinkedIn login status...
🔑 Please log in to LinkedIn in the browser window
...
✅ Login successful!
📊 Scraping candidates from job post
...
✅ Collected 15 candidates
💾 Saving candidates to: linkedin_candidates_Software_Engineer_20250127_143022.csv
✅ Saved 15 candidates to linkedin_candidates_Software_Engineer_20250127_143022.csv

📊 Summary:
   Total candidates: 15
   With email: 12
   Without email: 3
```

## Output Format

The script generates a CSV file with the following columns:

| Column | Description |
|--------|-------------|
| Name | Candidate's full name |
| Email | Email address (if available) |
| Phone | Phone number (if available) |
| Profile URL | LinkedIn profile URL |
| Applied Date | Date candidate applied |
| Location | Candidate's location |
| Job Title | Your job posting title |
| Status | Collection status (collected/pending/failed) |

## Configuration

### Headless Mode

To run without showing the browser window, edit `linkedin_candidate_scraper.py`:

```python
self.browser = self.playwright.chromium.launch(
    headless=True,  # Change to True
    slow_mo=100
)
```

### Session Directory

Browser session data is stored in `./linkedin_session_data/` by default. To change:

```python
scraper = LinkedInCandidateScraper(session_dir="./my_custom_session_dir")
```

## Troubleshooting

### "No candidates extracted automatically"

**Causes:**
- LinkedIn changed their HTML structure (happens frequently)
- No applicants to the job post yet
- Need LinkedIn Recruiter for full access

**Solutions:**
- Ensure you're using LinkedIn Recruiter
- Try manually scrolling through applicants in the browser
- Update selectors in `_extract_candidate_from_card()` method

### "Login timeout"

**Solution:**
- Increase timeout in `wait_for_login(timeout=600)` (default 300 seconds)
- Check your internet connection
- Disable 2FA temporarily or complete it faster

### Email addresses not appearing

**Cause:** Email addresses typically require LinkedIn Recruiter subscription

**Solutions:**
- Upgrade to LinkedIn Recruiter
- Use candidate profile URLs to contact them via LinkedIn
- Click on candidate profiles manually to see contact info

## Important Notes

⚠️ **LinkedIn Terms of Service**: This script automates interaction with LinkedIn. Please ensure you:
- Use it responsibly and only for your own job posts
- Respect LinkedIn's rate limits
- Comply with LinkedIn's Terms of Service
- Don't use for bulk scraping or spam

⚠️ **Data Privacy**: Handle candidate data responsibly:
- Store data securely
- Comply with GDPR/privacy regulations
- Only use data for legitimate recruiting purposes
- Delete data when no longer needed

⚠️ **Maintenance**: LinkedIn frequently updates their website structure. The script may need periodic updates to selectors and navigation logic.

## Advanced Usage

### Scraping Multiple Job Posts

To scrape multiple jobs, modify the `main()` function:

```python
job_urls = [
    "https://www.linkedin.com/jobs/view/1111111111",
    "https://www.linkedin.com/jobs/view/2222222222",
    "https://www.linkedin.com/jobs/view/3333333333",
]

with LinkedInCandidateScraper() as scraper:
    if not scraper.check_login():
        scraper.wait_for_login()

    for job_url in job_urls:
        job_post = scraper.scrape_candidates_from_job(job_url)
        if job_post.candidates:
            scraper.save_to_csv(job_post)
```

### Custom CSV Output

```python
# Specify custom output filename
scraper.save_to_csv(job_post, output_file="my_candidates.csv")
```

## Support

If LinkedIn's HTML structure has changed and the script stops working:

1. Open LinkedIn in the browser
2. Right-click on candidate cards → Inspect Element
3. Update the CSS selectors in `_extract_candidate_from_card()` method
4. Common selectors to check:
   - Candidate name: `.applicant-name`, `h3`
   - Email: `a[href^='mailto:']`
   - Profile link: `a[href*='/in/']`

## License

This script is provided as-is for personal use. Use responsibly and at your own risk.
