#!/usr/bin/env python3
"""
LinkedIn Candidate Email Scraper

This script automates the collection of email addresses from candidates
who applied to your LinkedIn job posts.

Requirements:
- Playwright (browser automation)
- pandas (CSV handling)

Usage:
    python linkedin_candidate_scraper.py
"""

import os
import time
import json
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from enum import Enum
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
import pandas as pd


class CandidateStatus(Enum):
    """Status of candidate data collection"""
    PENDING = "pending"
    COLLECTED = "collected"
    FAILED = "failed"


@dataclass
class Candidate:
    """Represents a job candidate"""
    name: str
    profile_url: str
    email: Optional[str] = None
    phone: Optional[str] = None
    applied_date: Optional[str] = None
    job_title: Optional[str] = None
    location: Optional[str] = None
    status: CandidateStatus = CandidateStatus.PENDING
    error_message: Optional[str] = None


@dataclass
class JobPost:
    """Represents a LinkedIn job posting"""
    job_title: str
    job_url: str
    candidates: List[Candidate] = field(default_factory=list)


class LinkedInCandidateScraper:
    """Scraper for collecting candidate emails from LinkedIn job posts"""

    def __init__(self, session_dir: str = "./linkedin_session_data"):
        """
        Initialize the LinkedIn scraper with persistent session

        Args:
            session_dir: Directory to store browser session data
        """
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def __enter__(self):
        """Context manager entry"""
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()

    def start_browser(self):
        """Start browser with persistent session"""
        print("🌐 Starting browser with persistent session...")

        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=False,  # Set to True for headless mode
            slow_mo=100  # Slow down actions for stability
        )

        # Use persistent context to maintain login session
        self.context = self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )

        self.page = self.context.new_page()
        print("✅ Browser started successfully")

    def close(self):
        """Close browser and cleanup"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if hasattr(self, 'playwright'):
            self.playwright.stop()
        print("👋 Browser closed")

    def check_login(self) -> bool:
        """
        Check if user is logged into LinkedIn

        Returns:
            True if logged in, False otherwise
        """
        print("🔐 Checking LinkedIn login status...")

        try:
            self.page.goto("https://www.linkedin.com/feed/", timeout=30000)
            time.sleep(2)

            # Check if we're on the feed page (logged in)
            if "feed" in self.page.url:
                print("✅ Already logged in to LinkedIn")
                return True
            else:
                print("❌ Not logged in to LinkedIn")
                return False

        except Exception as e:
            print(f"⚠️ Error checking login: {e}")
            return False

    def wait_for_login(self, timeout: int = 300):
        """
        Wait for user to manually log in to LinkedIn

        Args:
            timeout: Maximum time to wait in seconds
        """
        print("\n" + "="*60)
        print("🔑 Please log in to LinkedIn in the browser window")
        print("="*60)
        print("Waiting for you to complete login...")
        print(f"Timeout: {timeout} seconds")

        self.page.goto("https://www.linkedin.com/login")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if we're logged in by looking for feed URL
                if "feed" in self.page.url:
                    print("\n✅ Login successful!")
                    time.sleep(2)
                    return True

                time.sleep(2)

            except Exception as e:
                print(f"⚠️ Error during login wait: {e}")

        raise TimeoutError("Login timeout - please try again")

    def navigate_to_recruiting(self):
        """Navigate to LinkedIn Recruiting/Jobs section"""
        print("📋 Navigating to Jobs/Recruiting section...")

        try:
            # Try to go to recruiter if available
            self.page.goto("https://www.linkedin.com/talent/home", timeout=30000)
            time.sleep(3)

            # If no access to recruiter, try regular jobs
            if "talent" not in self.page.url:
                print("ℹ️ No LinkedIn Recruiter access, trying job postings...")
                self.page.goto("https://www.linkedin.com/my-items/posted-jobs/", timeout=30000)
                time.sleep(3)

            print("✅ Navigated to jobs section")

        except Exception as e:
            print(f"⚠️ Error navigating to recruiting: {e}")
            raise

    def get_job_posts(self) -> List[JobPost]:
        """
        Get list of active job posts

        Returns:
            List of JobPost objects
        """
        print("🔍 Finding your job posts...")

        job_posts = []

        try:
            # This will vary based on whether user has Recruiter or not
            # For now, we'll provide a manual input option
            print("\n" + "="*60)
            print("JOB POST SELECTION")
            print("="*60)
            print("Please provide the URL of your job post to scrape candidates from.")
            print("Example: https://www.linkedin.com/jobs/view/1234567890")

            # In a real implementation, you might want to use input() here
            # For now, we'll make it easy to specify

            return job_posts

        except Exception as e:
            print(f"⚠️ Error getting job posts: {e}")
            return job_posts

    def scrape_candidates_from_job(self, job_url: str) -> JobPost:
        """
        Scrape candidate information from a specific job posting

        Args:
            job_url: URL of the LinkedIn job posting

        Returns:
            JobPost object with candidate data
        """
        print(f"\n{'='*60}")
        print(f"📊 Scraping candidates from job post")
        print(f"{'='*60}")

        candidates = []

        try:
            # Navigate to job post
            self.page.goto(job_url, timeout=30000)
            time.sleep(5)  # Increased wait time for page to load

            # Detect page type
            is_recruiter = "talent/hire" in self.page.url or "recruiter" in self.page.url
            is_applicants_page = "applicants" in self.page.url or "jobId" in self.page.url

            if is_recruiter:
                print("✅ LinkedIn Recruiter page detected")
            elif is_applicants_page:
                print("✅ Applicants page detected")
            else:
                print("⚠️ Warning: This doesn't look like an applicants page")
                print(f"   Current URL: {self.page.url}")
                print("   Expected URL to contain 'applicants' or 'talent/hire'")

            # Get job title
            job_title = "Job Post"
            try:
                # Try multiple selectors for job title
                title_selectors = [
                    "h1.job-details-jobs-unified-top-card__job-title",
                    "h1.jobs-unified-top-card__job-title",
                    "h2.job-title",
                    "h1",
                    ".job-details-jobs-unified-top-card__job-title"
                ]
                for selector in title_selectors:
                    title_elem = self.page.query_selector(selector)
                    if title_elem:
                        title_text = title_elem.inner_text().strip()
                        if title_text and title_text.lower() != "sign in":
                            job_title = title_text
                            break
            except:
                pass

            print(f"📝 Job Title: {job_title}")

            if job_title.lower() == "sign in":
                print("\n❌ ERROR: Looks like you're not on the right page or not logged in")
                print("   The page title is 'Sign in' which means:")
                print("   1. You need to log in to LinkedIn, OR")
                print("   2. The URL you provided is incorrect")
                print("\n💡 Please make sure you're logged in and using the APPLICANTS page URL")
                return JobPost(job_title=job_title, job_url=job_url, candidates=[])

            # Now scrape the applicants list
            print("📥 Collecting candidate data...")
            print("⏳ Waiting for page to fully load...")
            time.sleep(3)

            # Try different selectors based on page type
            if is_recruiter:
                # LinkedIn Recruiter specific selectors
                print("🔍 Using LinkedIn Recruiter selectors...")
                candidate_cards = self.page.query_selector_all(
                    ".artdeco-list__item, .hiring-applicant-list-item, [data-test-hiring-applicant-list-item], .reusable-search__result-container"
                )
            else:
                # Regular LinkedIn selectors
                print("🔍 Using regular LinkedIn selectors...")
                candidate_cards = self.page.query_selector_all(
                    ".jobs-search-results__list-item, .scaffold-layout__list-item, .job-card-container, li.artdeco-list__item"
                )

            if not candidate_cards:
                print("⚠️ No candidate cards found with initial selectors")
                print("🔄 Trying alternative selectors...")

                # Try more generic selectors
                candidate_cards = self.page.query_selector_all(
                    "li.artdeco-list__item, .list-style-none li, [role='listitem']"
                )

            if candidate_cards:
                print(f"✅ Found {len(candidate_cards)} potential candidate elements")
            else:
                print("❌ No candidate elements found")
                print("\n💡 Debugging info:")
                print("   1. Make sure you're on the applicants page")
                print("   2. Try scrolling down in the browser to load candidates")
                print("   3. Press Enter after scrolling to let the script try again...")
                input()

                # Try one more time after user scrolls
                candidate_cards = self.page.query_selector_all(
                    "li.artdeco-list__item, .artdeco-list__item, [role='listitem']"
                )

            # Try to extract from whatever is on the page
            for i, card in enumerate(candidate_cards, 1):
                try:
                    candidate = self._extract_candidate_from_card(card)
                    if candidate and candidate.name != "Unknown":
                        candidates.append(candidate)
                        print(f"  ✓ {i}. {candidate.name} - {candidate.email or 'No email'}")

                except Exception as e:
                    print(f"  ⚠️ Error extracting candidate {i}: {e}")

            if not candidates:
                print("\n⚠️ No candidates extracted automatically.")
                print("💡 This could mean:")
                print("   1. No applicants to this job yet")
                print("   2. LinkedIn's HTML structure has changed (very common)")
                print("   3. You're not on the applicants page")
                print("   4. Candidates haven't loaded yet - try scrolling")
                print("\nℹ️ Note: Email addresses are typically only available with LinkedIn Recruiter")

            job_post = JobPost(
                job_title=job_title,
                job_url=job_url,
                candidates=candidates
            )

            print(f"\n✅ Collected {len(candidates)} candidates")
            return job_post

        except Exception as e:
            print(f"❌ Error scraping candidates: {e}")
            return JobPost(job_title="Unknown", job_url=job_url, candidates=candidates)

    def _extract_candidate_from_card(self, card) -> Optional[Candidate]:
        """
        Extract candidate information from a candidate card element

        Args:
            card: Playwright element locator for candidate card

        Returns:
            Candidate object or None
        """
        try:
            # Name - try multiple selectors
            name = "Unknown"
            name_selectors = [
                # Recruiter selectors
                ".hiring-applicant__name",
                ".artdeco-entity-lockup__title a",
                ".artdeco-entity-lockup__title",
                # Regular selectors
                ".applicant-name",
                ".job-applicant-name",
                "[data-test-applicant-name]",
                # Generic selectors
                "h3 a",
                "h3",
                "h4 a",
                "h4",
                ".t-16 strong",
                "strong a"
            ]
            for selector in name_selectors:
                elem = card.query_selector(selector)
                if elem:
                    name_text = elem.inner_text().strip()
                    # Filter out non-name text
                    if name_text and len(name_text) > 2 and name_text != "Unknown":
                        name = name_text
                        break

            # Profile URL - try to find any LinkedIn profile link
            profile_url = ""
            profile_selectors = [
                "a[href*='/in/']",
                "a[href*='linkedin.com/in/']",
                "[data-control-name*='actor'] a"
            ]
            for selector in profile_selectors:
                link = card.query_selector(selector)
                if link:
                    href = link.get_attribute("href")
                    if href and "/in/" in href:
                        # Clean up the URL
                        profile_url = href.split("?")[0]  # Remove query params
                        break

            # Email (usually only available with Recruiter)
            email = None
            email_selectors = [
                # Recruiter selectors
                "[data-test-hiring-applicant-email]",
                ".hiring-applicant__email",
                "a[href^='mailto:']",
                "[data-test-applicant-email]",
                ".applicant-email",
                # Try to find any text containing @
                "div:has-text('@')",
                "span:has-text('@')"
            ]
            for selector in email_selectors:
                try:
                    elem = card.query_selector(selector)
                    if elem:
                        # Try to get email from href first (mailto:)
                        href = elem.get_attribute("href")
                        if href and "mailto:" in href:
                            email = href.replace("mailto:", "").strip()
                            break

                        # Otherwise try inner text
                        email_text = elem.inner_text().strip()
                        if email_text and "@" in email_text and "." in email_text:
                            email = email_text
                            break
                except:
                    continue

            # Phone
            phone = None
            phone_selectors = [
                "[data-test-hiring-applicant-phone]",
                ".hiring-applicant__phone",
                "a[href^='tel:']",
                "[data-test-applicant-phone]"
            ]
            for selector in phone_selectors:
                try:
                    elem = card.query_selector(selector)
                    if elem:
                        href = elem.get_attribute("href")
                        if href and "tel:" in href:
                            phone = href.replace("tel:", "").strip()
                            break

                        phone_text = elem.inner_text().strip()
                        if phone_text:
                            phone = phone_text
                            break
                except:
                    continue

            # Applied date
            applied_date = None
            date_selectors = [
                "[data-test-applicant-date]",
                "[data-test-hiring-applicant-date]",
                ".applicant-date",
                "time",
                ".time-badge"
            ]
            for selector in date_selectors:
                elem = card.query_selector(selector)
                if elem:
                    date_text = elem.inner_text().strip()
                    if date_text:
                        applied_date = date_text
                        break

            # Location
            location = None
            location_selectors = [
                ".applicant-location",
                "[data-test-applicant-location]",
                ".hiring-applicant__location",
                ".artdeco-entity-lockup__subtitle",
                ".t-14.t-black--light"
            ]
            for selector in location_selectors:
                elem = card.query_selector(selector)
                if elem:
                    loc_text = elem.inner_text().strip()
                    if loc_text and loc_text != name:  # Make sure it's not the name
                        location = loc_text
                        break

            # Only return candidate if we at least got a name
            if name == "Unknown" or not name:
                return None

            candidate = Candidate(
                name=name,
                profile_url=profile_url or "",
                email=email,
                phone=phone,
                applied_date=applied_date,
                location=location,
                status=CandidateStatus.COLLECTED if email else CandidateStatus.PENDING
            )

            return candidate

        except Exception as e:
            print(f"    ⚠️ Error extracting candidate data: {e}")
            return None

    def save_to_csv(self, job_post: JobPost, output_file: str = None):
        """
        Save candidate data to CSV file

        Args:
            job_post: JobPost object with candidates
            output_file: Output CSV filename (auto-generated if None)
        """
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c for c in job_post.job_title if c.isalnum() or c in (' ', '-', '_'))[:50]
            output_file = f"linkedin_candidates_{safe_title}_{timestamp}.csv"

        print(f"\n💾 Saving candidates to: {output_file}")

        # Convert to DataFrame
        data = []
        for candidate in job_post.candidates:
            data.append({
                "Name": candidate.name,
                "Email": candidate.email or "",
                "Phone": candidate.phone or "",
                "Profile URL": candidate.profile_url,
                "Applied Date": candidate.applied_date or "",
                "Location": candidate.location or "",
                "Job Title": job_post.job_title,
                "Status": candidate.status.value
            })

        df = pd.DataFrame(data)
        df.to_csv(output_file, index=False)

        print(f"✅ Saved {len(data)} candidates to {output_file}")

        # Print summary
        with_email = sum(1 for c in job_post.candidates if c.email)
        print(f"\n📊 Summary:")
        print(f"   Total candidates: {len(job_post.candidates)}")
        print(f"   With email: {with_email}")
        print(f"   Without email: {len(job_post.candidates) - with_email}")


def main():
    """Main execution function"""
    print("="*60)
    print("🔷 LinkedIn Candidate Email Scraper")
    print("="*60)
    print()

    # Provide clear instructions
    print("📋 INSTRUCTIONS:")
    print("   This script needs the URL of your APPLICANTS page, not just the job post.")
    print()
    print("   Choose one of the following options:")
    print()
    print("   Option 1: I'll help you navigate (Recommended)")
    print("   Option 2: I already have the applicants page URL")
    print()

    choice = input("Enter your choice (1 or 2): ").strip()

    # Start scraper
    with LinkedInCandidateScraper() as scraper:
        # Check/wait for login
        if not scraper.check_login():
            scraper.wait_for_login()

        job_url = None

        if choice == "1":
            # Guided navigation
            print("\n" + "="*60)
            print("📍 GUIDED NAVIGATION")
            print("="*60)
            print()
            print("I'll open LinkedIn and help you navigate to the applicants page.")
            print()
            print("Steps:")
            print("1. I'll open your LinkedIn job postings page")
            print("2. You click on your job post")
            print("3. You click 'View applicants' or 'Applicants'")
            print("4. Copy the URL and paste it here")
            print()
            input("Press Enter to open LinkedIn jobs page...")

            # Try to open the jobs page
            try:
                # First try recruiter
                scraper.page.goto("https://www.linkedin.com/talent/home", timeout=30000)
                time.sleep(2)

                if "talent" not in scraper.page.url:
                    # Not a recruiter account, try regular jobs
                    print("ℹ️ Opening regular job postings page...")
                    scraper.page.goto("https://www.linkedin.com/my-items/posted-jobs/", timeout=30000)
                    time.sleep(2)
                else:
                    print("✅ LinkedIn Recruiter detected - opening jobs...")

            except Exception as e:
                print(f"⚠️ Error opening jobs page: {e}")
                print("Please navigate to your jobs manually in the browser.")

            print()
            print("="*60)
            print("NOW FOLLOW THESE STEPS IN THE BROWSER:")
            print("="*60)
            print("1. Click on your job posting")
            print("2. Click 'View applicants' or 'Applicants' button")
            print("3. Copy the URL from the address bar")
            print()
            print("Expected URL formats:")
            print("   • Recruiter: https://www.linkedin.com/talent/hire/XXXXX/applicants")
            print("   • Regular: https://www.linkedin.com/jobs/collections/applicants?jobId=XXXXX")
            print()

            job_url = input("Paste the applicants page URL here: ").strip()

        else:
            # Direct URL input
            print("\n" + "="*60)
            print("📍 DIRECT URL INPUT")
            print("="*60)
            print()
            print("Please enter the URL of your applicants page.")
            print()
            print("Expected URL formats:")
            print("   • Recruiter: https://www.linkedin.com/talent/hire/XXXXX/applicants")
            print("   • Regular: https://www.linkedin.com/jobs/collections/applicants?jobId=XXXXX")
            print()
            print("⚠️ Note: This should be the APPLICANTS page, not the job post page")
            print()

            job_url = input("Applicants page URL: ").strip()

        if not job_url:
            print("❌ No URL provided. Exiting...")
            return

        # Scrape candidates
        job_post = scraper.scrape_candidates_from_job(job_url)

        # Save to CSV
        if job_post.candidates:
            scraper.save_to_csv(job_post)
        else:
            print("\n⚠️ No candidates to save")
            print("\n💡 Troubleshooting:")
            print("   1. Make sure you're on the APPLICANTS page (not the job post)")
            print("   2. The URL should contain 'applicants' or 'jobId'")
            print("   3. Try scrolling down in the browser to load candidates")
            print("   4. Some job posts may have no applicants yet")

    print("\n✅ Script completed!")
    print("\n💡 Important Notes:")
    print("   • Email addresses typically require LinkedIn Recruiter subscription")
    print("   • LinkedIn frequently changes their HTML structure")
    print("   • For best results, use LinkedIn Recruiter and manually verify data")
    print("   • Always respect LinkedIn's Terms of Service and rate limits")


if __name__ == "__main__":
    main()
