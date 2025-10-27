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
            time.sleep(3)

            # Get job title
            job_title = "Job Post"
            try:
                title_elem = self.page.query_selector("h1")
                if title_elem:
                    job_title = title_elem.inner_text().strip()
            except:
                pass

            print(f"📝 Job Title: {job_title}")

            # Try to navigate to applicants
            # This varies based on whether it's a regular job post or recruiter
            print("🔄 Looking for applicants section...")

            # Look for "View applicants" or similar button
            applicants_selectors = [
                "text=View applicants",
                "text=Applicants",
                "text=See applicants",
                "[aria-label*='applicant']"
            ]

            clicked = False
            for selector in applicants_selectors:
                try:
                    button = self.page.query_selector(selector)
                    if button:
                        button.click()
                        clicked = True
                        time.sleep(3)
                        print("✅ Found applicants section")
                        break
                except:
                    continue

            if not clicked:
                print("⚠️ Could not automatically find applicants section.")
                print("Please manually navigate to the applicants list in the browser.")
                print("Press Enter when ready to continue...")
                # input()  # Uncomment for interactive mode

            # Now scrape the applicants list
            print("📥 Collecting candidate data...")

            # This selector will need to be adjusted based on LinkedIn's current HTML
            # LinkedIn frequently changes their DOM structure
            candidate_cards = self.page.query_selector_all(
                ".job-applicant-card, .applicant-card, [data-test-job-applicant-card]"
            )

            if not candidate_cards:
                print("⚠️ No candidate cards found with standard selectors")
                print("ℹ️ LinkedIn's HTML structure may have changed")
                print("\nℹ️ Manual extraction mode:")
                print("   Please scroll through the applicants list.")
                print("   The script will try to extract visible data.")

            # Try to extract from whatever is on the page
            for i, card in enumerate(candidate_cards, 1):
                try:
                    candidate = self._extract_candidate_from_card(card)
                    if candidate:
                        candidates.append(candidate)
                        print(f"  ✓ {i}. {candidate.name} - {candidate.email or 'No email'}")

                except Exception as e:
                    print(f"  ⚠️ Error extracting candidate {i}: {e}")

            if not candidates:
                print("\n⚠️ No candidates extracted automatically.")
                print("💡 This could mean:")
                print("   1. No applicants yet")
                print("   2. LinkedIn's HTML has changed (common)")
                print("   3. You need LinkedIn Recruiter for email access")
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
            # Name
            name = "Unknown"
            name_selectors = [
                ".applicant-name",
                ".job-applicant-name",
                "[data-test-applicant-name]",
                "h3",
                ".artdeco-entity-lockup__title"
            ]
            for selector in name_selectors:
                elem = card.query_selector(selector)
                if elem:
                    name = elem.inner_text().strip()
                    break

            # Profile URL
            profile_url = ""
            link = card.query_selector("a[href*='/in/']")
            if link:
                profile_url = link.get_attribute("href")

            # Email (usually only available with Recruiter)
            email = None
            email_selectors = [
                "[data-test-applicant-email]",
                "a[href^='mailto:']",
                ".applicant-email"
            ]
            for selector in email_selectors:
                elem = card.query_selector(selector)
                if elem:
                    email_text = elem.inner_text() if not elem.get_attribute("href") else elem.get_attribute("href")
                    if email_text and "@" in email_text:
                        email = email_text.replace("mailto:", "").strip()
                        break

            # Applied date
            applied_date = None
            date_elem = card.query_selector("[data-test-applicant-date], .applicant-date, time")
            if date_elem:
                applied_date = date_elem.inner_text().strip()

            # Location
            location = None
            location_elem = card.query_selector(".applicant-location, [data-test-applicant-location]")
            if location_elem:
                location = location_elem.inner_text().strip()

            candidate = Candidate(
                name=name,
                profile_url=profile_url or "",
                email=email,
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

    # Get job URL from user
    print("Please enter the URL of your LinkedIn job post:")
    print("Example: https://www.linkedin.com/jobs/view/1234567890")
    print()
    job_url = input("Job URL: ").strip()

    if not job_url:
        print("❌ No URL provided. Exiting...")
        return

    # Start scraper
    with LinkedInCandidateScraper() as scraper:
        # Check/wait for login
        if not scraper.check_login():
            scraper.wait_for_login()

        # Scrape candidates
        job_post = scraper.scrape_candidates_from_job(job_url)

        # Save to CSV
        if job_post.candidates:
            scraper.save_to_csv(job_post)
        else:
            print("\n⚠️ No candidates to save")

    print("\n✅ Script completed!")
    print("\n💡 Important Notes:")
    print("   • Email addresses typically require LinkedIn Recruiter subscription")
    print("   • LinkedIn frequently changes their HTML structure")
    print("   • For best results, use LinkedIn Recruiter and manually verify data")
    print("   • Always respect LinkedIn's Terms of Service and rate limits")


if __name__ == "__main__":
    main()
