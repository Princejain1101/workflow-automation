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
import requests
import urllib.parse
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
    resume_url: Optional[str] = None
    resume_filename: Optional[str] = None
    resume_downloaded: bool = False
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

    def __init__(self, session_dir: str = "./linkedin_session_data", resume_dir: str = "./resumes"):
        """
        Initialize the LinkedIn scraper with persistent session

        Args:
            session_dir: Directory to store browser session data
            resume_dir: Directory to store downloaded resumes
        """
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(exist_ok=True)
        self.resume_dir = Path(resume_dir)
        self.resume_dir.mkdir(exist_ok=True)
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
        """Start browser with persistent session using user data directory"""
        print("🌐 Starting browser with persistent session...")

        self.playwright = sync_playwright().start()

        # Create a persistent user data directory
        user_data_dir = self.session_dir / "chrome_user_data"
        user_data_dir.mkdir(exist_ok=True)

        # Launch browser with persistent context (keeps login session)
        self.context = self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,  # Set to True for headless mode
            slow_mo=100,  # Slow down actions for stability
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor"
            ]
        )

        # Get the first (and only) page from persistent context
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = self.context.new_page()

        print("✅ Browser started with persistent session")
        print(f"📁 Session data stored in: {user_data_dir}")

    def close(self):
        """Close browser and cleanup"""
        if self.context:
            self.context.close()
        if hasattr(self, 'playwright'):
            self.playwright.stop()
        print("👋 Browser closed (session saved)")

    def learn_resume_download_pattern(self, candidate_name: str) -> Optional[str]:
        """
        Interactive learning mode - watches user actions and records the pattern
        """
        print(f"🎓 LEARNING MODE for {candidate_name}")
        print(f"📚 I'll watch what you click and learn the pattern for other candidates")
        print(f"")
        print(f"📝 Instructions:")
        print(f"   1. Click on the candidate to open their profile/details")
        print(f"   2. Click on the resume download button")
        print(f"   3. Wait for the download to complete")
        print(f"")
        print(f"🔍 I'm monitoring for downloads...")

        try:
            with self.page.expect_download(timeout=45000) as download_info:
                download = download_info.value

                # Process the download
                safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).strip()
                safe_name = safe_name.replace(" ", "_")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                original_name = download.suggested_filename
                file_ext = ".pdf"
                if original_name and "." in original_name:
                    file_ext = "." + original_name.split(".")[-1]

                filename = f"{safe_name}_{timestamp}{file_ext}"
                filepath = self.resume_dir / filename

                download.save_as(filepath)
                print(f"✅ Learning successful! Downloaded: {filename}")

                # Now try to learn the pattern by looking for recently appeared elements
                print(f"🧠 Analyzing the page to learn the download pattern...")

                # Look for resume-related elements that appeared
                resume_elements = self.page.query_selector_all(
                    "a[href*='/ambry/'], a[data-view-name*='resume'], a:has-text('Resume'), button:has-text('Resume')"
                )

                for element in resume_elements:
                    try:
                        href = element.get_attribute('href') or ''
                        text = element.inner_text().strip()
                        data_view = element.get_attribute('data-view-name') or ''

                        if '/ambry/' in href or 'resume' in data_view.lower():
                            # Store this pattern for future use
                            self.learned_resume_selectors.append({
                                'selector': f"a[href*='/ambry/']" if '/ambry/' in href else f"a[data-view-name='{data_view}']",
                                'text_pattern': text,
                                'href_pattern': href[:50] if href else '',
                                'success_count': 1
                            })
                            print(f"📖 Learned pattern: {text or 'Resume download link'}")
                            break
                    except Exception as parse_err:
                        continue

                return str(filename)

        except Exception as e:
            print(f"⏰ Learning timeout or error: {e}")
            print(f"💡 Try the steps again, or type 'skip' to move to next candidate")
            return None

    def apply_learned_pattern(self, candidate_name: str) -> Optional[str]:
        """
        Apply previously learned patterns to download resume
        """
        if not self.learned_resume_selectors:
            return None

        print(f"🧠 Applying learned patterns for {candidate_name}...")

        for i, pattern in enumerate(self.learned_resume_selectors):
            try:
                print(f"   Trying pattern {i+1}: {pattern['text_pattern']}")

                # Look for elements matching the learned pattern
                elements = self.page.query_selector_all(pattern['selector'])

                for element in elements:
                    try:
                        href = element.get_attribute('href') or ''

                        # If it's an /ambry/ link, download directly
                        if '/ambry/' in href:
                            print(f"   ✅ Found matching resume link!")
                            return self._download_direct_resume(href, candidate_name)
                        else:
                            # Try clicking the element
                            print(f"   🔄 Clicking learned element...")
                            with self.page.expect_download(timeout=10000) as download_info:
                                element.click()
                                download = download_info.value
                                return self._process_download(download, candidate_name)

                    except Exception as element_err:
                        continue

            except Exception as pattern_err:
                print(f"   ❌ Pattern {i+1} failed: {pattern_err}")
                continue

        print(f"   🤷 No learned patterns worked")
        return None

    def _process_download(self, download, candidate_name: str) -> Optional[str]:
        """
        Process a download and save with proper naming
        """
        try:
            safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(" ", "_")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            original_name = download.suggested_filename
            file_ext = ".pdf"
            if original_name and "." in original_name:
                file_ext = "." + original_name.split(".")[-1]

            filename = f"{safe_name}_{timestamp}{file_ext}"
            filepath = self.resume_dir / filename

            download.save_as(filepath)
            print(f"    ✅ Downloaded: {filename}")
            return str(filename)

        except Exception as e:
            print(f"    ❌ Download failed: {e}")
            return None

    def download_resume(self, resume_url: str, candidate_name: str) -> Optional[str]:
        """
        Download resume from LinkedIn

        Args:
            resume_url: URL of the resume
            candidate_name: Name of the candidate for filename

        Returns:
            Local filename if successful, None otherwise
        """
        try:
            # Clean candidate name for filename
            safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).strip()
            safe_name = safe_name.replace(" ", "_")

            # Determine file extension from URL or use default
            file_ext = ".pdf"  # Default extension
            if ".pdf" in resume_url.lower():
                file_ext = ".pdf"
            elif ".doc" in resume_url.lower():
                file_ext = ".doc"
            elif ".docx" in resume_url.lower():
                file_ext = ".docx"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{safe_name}_{timestamp}{file_ext}"
            filepath = self.resume_dir / filename

            # Get cookies from browser context for authenticated download
            cookies = self.context.cookies()
            cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/msword,*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }

            print(f"    📥 Downloading resume: {filename}")

            response = requests.get(resume_url, cookies=cookie_dict, headers=headers, timeout=30)
            response.raise_for_status()

            with open(filepath, 'wb') as f:
                f.write(response.content)

            print(f"    ✅ Resume downloaded: {filepath}")
            return str(filename)

        except Exception as e:
            print(f"    ❌ Failed to download resume: {e}")
            return None

    def click_resume_link(self, card, candidate_name: str) -> Optional[str]:
        """
        Try to click resume/CV link and get download URL

        Args:
            card: Playwright element for candidate card
            candidate_name: Name of candidate

        Returns:
            Resume filename if downloaded, None otherwise
        """
        try:
            # Look for resume/CV links - Updated for current LinkedIn structure
            resume_selectors = [
                # Specific LinkedIn resume download link with exact class pattern
                "a._669c587e.ab8f5090._84a56982._0b58596c._2bc446a9",
                "a[class*='_669c587e'][class*='ab8f5090']",
                "a[data-view-name='hiring-applicant-view-resume']",
                "a[href*='/ambry/']",
                "a[componentkey*='hiring']",
                # Generic resume indicators
                "a:has(svg[id='download-small'])",
                "a:has(span:has-text('Resume'))",
                "a[target='_blank']:has(span:has-text('Resume'))",
                # Fallback selectors
                "a[href*='resume']",
                "a[href*='cv']",
                "a[aria-label*='resume']",
                "a[aria-label*='CV']",
                "button[aria-label*='resume']",
                "button[aria-label*='CV']",
                "[data-test*='resume']",
                "[data-test*='cv']",
                "text=Resume",
                "text=CV"
            ]

            for selector in resume_selectors:
                try:
                    element = card.query_selector(selector)
                    if element:
                        # Check if it's actually a resume link
                        text = element.inner_text().lower()
                        aria_label = element.get_attribute('aria-label') or ''
                        href = element.get_attribute('href') or ''
                        data_view = element.get_attribute('data-view-name') or ''

                        # Strong indicators this is a resume link
                        is_resume_link = (
                            'hiring-applicant-view-resume' in data_view or
                            '/ambry/' in href or
                            ('resume' in text and 'download' in href) or
                            any(keyword in text + aria_label.lower() + href.lower()
                                for keyword in ['resume', 'cv']) and href.startswith('http')
                        )

                        if is_resume_link:
                            print(f"    🔍 Found resume link: {text or aria_label or 'Resume download'}")
                            print(f"    🔗 URL: {href[:80]}...")

                            # For LinkedIn /ambry/ links, we can download directly
                            if '/ambry/' in href and href.startswith('http'):
                                # Direct download using requests
                                safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).strip()
                                safe_name = safe_name.replace(" ", "_")
                                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                filename = f"{safe_name}_{timestamp}.pdf"
                                filepath = self.resume_dir / filename

                                try:
                                    # Get cookies for authenticated request
                                    cookies = self.context.cookies()
                                    cookie_dict = {cookie['name']: cookie['value'] for cookie in cookies}

                                    headers = {
                                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                                        'Accept': 'application/pdf,*/*',
                                        'Referer': 'https://www.linkedin.com/'
                                    }

                                    print(f"    📥 Downloading resume: {filename}")
                                    response = requests.get(href, cookies=cookie_dict, headers=headers, timeout=30)
                                    response.raise_for_status()

                                    with open(filepath, 'wb') as f:
                                        f.write(response.content)

                                    print(f"    ✅ Resume downloaded: {filename}")
                                    return str(filename)

                                except Exception as download_error:
                                    print(f"    ❌ Direct download failed: {download_error}")
                                    # Fall back to click method
                                    pass

                            # Fallback: Try clicking to trigger download
                            try:
                                with self.page.expect_download(timeout=10000) as download_info:
                                    element.click()
                                    download = download_info.value

                                    # Save the download
                                    safe_name = "".join(c for c in candidate_name if c.isalnum() or c in (' ', '-', '_')).strip()
                                    safe_name = safe_name.replace(" ", "_")
                                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                                    # Get original filename and extension
                                    original_name = download.suggested_filename
                                    file_ext = ".pdf"  # default
                                    if original_name:
                                        file_ext = "." + original_name.split(".")[-1] if "." in original_name else ".pdf"

                                    filename = f"{safe_name}_{timestamp}{file_ext}"
                                    filepath = self.resume_dir / filename

                                    download.save_as(filepath)
                                    print(f"    ✅ Resume downloaded: {filename}")
                                    return str(filename)
                            except Exception as click_error:
                                print(f"    ❌ Click download failed: {click_error}")

                except Exception as e:
                    print(f"    ⚠️ Error with resume selector '{selector}': {e}")
                    continue

            print(f"    ❌ No resume download link found")

            return None

        except Exception as e:
            print(f"    ⚠️ Error looking for resume: {e}")
            return None

    def check_login(self) -> bool:
        """
        Check if user is logged into LinkedIn

        Returns:
            True if logged in, False otherwise
        """
        print("🔐 Checking LinkedIn login status...")

        try:
            self.page.goto("https://www.linkedin.com/feed/", timeout=30000)
            time.sleep(3)

            # Check multiple indicators of being logged in
            current_url = self.page.url
            page_title = self.page.title()

            # Look for login indicators
            if any(indicator in current_url for indicator in ["feed", "mynetwork", "jobs", "messaging"]):
                print("✅ Already logged in to LinkedIn")
                return True
            elif "Sign in" in page_title or "login" in current_url.lower():
                print("❌ Not logged in to LinkedIn")
                return False
            else:
                # Check for navigation elements that indicate login
                nav_element = self.page.query_selector("nav[aria-label*='Primary']") or self.page.query_selector(".global-nav")
                if nav_element:
                    print("✅ Already logged in to LinkedIn (detected nav)")
                    return True
                else:
                    print("❌ Not logged in to LinkedIn")
                    return False

        except Exception as e:
            print(f"⚠️ Error checking login: {e}")
            return False

    def wait_for_login(self, timeout: int = 300):
        """
        Wait for user to manually log in to LinkedIn (DEPRECATED - using simplified flow)
        """
        # This method is kept for compatibility but is no longer used
        pass

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
                # Regular LinkedIn selectors - Updated for current LinkedIn HTML
                print("🔍 Using updated LinkedIn selectors...")
                candidate_cards = self.page.query_selector_all(
                    "div[role='button'][class*='_3e7554fb'][class*='d0cdef3d'], div.bc3ed872 > div[role='list'] > div[role='button']"
                )

            if not candidate_cards:
                print("⚠️ No candidate cards found with initial selectors")
                print("🔄 Trying alternative selectors...")

                # Try more generic selectors based on the HTML structure
                candidate_cards = self.page.query_selector_all(
                    "div[role='button'][tabindex='0'], div.cea52de2._1a1b44f8, div[componentkey='JobPosting.ApplicantListContent'] div[role='button']"
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

                # Try one more time after user scrolls - use most generic approach
                candidate_cards = self.page.query_selector_all(
                    "div[role='button'][aria-label*='View full profile'], div[role='button'][class*='_3e7554fb']"
                )

            # Try to extract from whatever is on the page
            for i, card in enumerate(candidate_cards, 1):
                try:
                    candidate = self._extract_candidate_from_card(card)
                    if candidate and candidate.name != "Unknown":
                        candidates.append(candidate)
                        resume_status = "✅ Resume downloaded" if candidate.resume_downloaded else "❌ No resume"
                        print(f"  ✓ {i}. {candidate.name} - {resume_status}")

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
            # Name - try multiple selectors based on current LinkedIn HTML
            name = "Unknown"
            name_selectors = [
                # Updated selectors for current LinkedIn structure
                "p._75885701._428cbfef.fc87c8f8._4431df24.c67136d7._1edd0d4d._6ccf36e4._33f15b4a.b18cc04a",
                "p._75885701._428cbfef.fc87c8f8._4431df24.c67136d7._1edd0d4d._6ccf36e4._85ce913f._33f15b4a.b18cc04a",
                # Recruiter selectors
                ".hiring-applicant__name",
                ".artdeco-entity-lockup__title a",
                ".artdeco-entity-lockup__title",
                # Generic selectors
                "p[class*='_75885701'][class*='_428cbfef']",
                "p[class*='fc87c8f8'][class*='c67136d7']",
                "h3 a",
                "h3",
                "h4 a",
                "h4"
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
                "[data-control-name*='actor'] a",
                "div[aria-label*='View full profile'] a",
                "div[role='button'][aria-label*='View full profile']"
            ]
            for selector in profile_selectors:
                link = card.query_selector(selector)
                if link:
                    href = link.get_attribute("href")
                    if href and "/in/" in href:
                        # Clean up the URL
                        profile_url = href.split("?")[0]  # Remove query params
                        break

            # Resume download
            resume_filename = None
            resume_url = None

            # Try to find and download resume
            print(f"    📄 Looking for resume for {name}...")

            # Debug: Print all clickable elements in the card
            all_buttons = card.query_selector_all("button, a, [role='button']")
            print(f"    🔍 Found {len(all_buttons)} clickable elements")

            for i, btn in enumerate(all_buttons[:5]):  # Limit to first 5 for debugging
                try:
                    btn_text = btn.inner_text().strip()[:50] if btn.inner_text() else ""
                    btn_aria = btn.get_attribute('aria-label') or ""
                    btn_href = btn.get_attribute('href') or ""
                    print(f"      {i+1}. Text: '{btn_text}' | Aria: '{btn_aria}' | Href: '{btn_href}'")
                except:
                    print(f"      {i+1}. (Error reading element)")

            # First try applying learned patterns
            if hasattr(self, 'learned_resume_selectors') and self.learned_resume_selectors:
                resume_filename = self.apply_learned_pattern(name)
            else:
                resume_filename = self.click_resume_link(card, name)

            # If automated detection fails, offer learning mode
            if not resume_filename:
                print(f"    ❌ Automated resume detection failed for {name}")

                if not hasattr(self, 'learned_resume_selectors') or not self.learned_resume_selectors:
                    # First time - offer learning mode
                    user_choice = input(f"    🎓 Try learning mode? I'll watch what you click and apply it to other candidates (y/n/skip): ").strip().lower()
                    if user_choice == 'y' or user_choice == 'yes':
                        resume_filename = self.learn_resume_download_pattern(name)
                        if resume_filename:
                            print(f"    🎉 Learning complete! Will automatically download other resumes now.")
                    elif user_choice == 'skip':
                        print(f"    ⏭️ Skipping {name}")
                    else:
                        print(f"    ⏭️ Moving to next candidate")
                else:
                    # Learning already done, offer manual download
                    user_choice = input(f"    🤔 Learned patterns didn't work. Try manual download for {name}? (y/n/skip): ").strip().lower()

                if user_choice == 'y' or user_choice == 'yes':
                    print(f"    📝 MANUAL MODE: Please click the resume download button for {name} in the browser")
                    print(f"    ⏰ Waiting 20 seconds for you to click...")

                    try:
                        with self.page.expect_download(timeout=20000) as download_info:
                            download = download_info.value

                            # Process the manual download
                            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip()
                            safe_name = safe_name.replace(" ", "_")
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                            original_name = download.suggested_filename
                            file_ext = ".pdf"
                            if original_name and "." in original_name:
                                file_ext = "." + original_name.split(".")[-1]

                            filename = f"{safe_name}_{timestamp}{file_ext}"
                            filepath = self.resume_dir / filename

                            download.save_as(filepath)
                            print(f"    ✅ Manual download successful: {filename}")
                            resume_filename = str(filename)

                    except Exception:
                        print(f"    ⏳ No download detected - moving to next candidate")

                elif user_choice == 'skip':
                    print(f"    ⏭️ Skipping resume download for {name}")
                else:
                    print(f"    ⏭️ Moving to next candidate")

            # Email (usually only available with Recruiter) - keeping as backup info
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

            # Location - based on current LinkedIn HTML structure
            location = None
            location_selectors = [
                # Updated selectors for location (usually the 3rd p tag in the structure)
                "p._75885701._0e3d90a2._09788675.e19cc933._5a88194c.baa17a46._2b457e06._6694ddd3._85a0c3d2.fc87c8f8._4431df24._75495dd0._1edd0d4d._6ccf36e4._85ce913f._33f15b4a.b18cc04a",
                ".applicant-location",
                "[data-test-applicant-location]",
                ".hiring-applicant__location",
                ".artdeco-entity-lockup__subtitle",
                "p[class*='_0e3d90a2'][class*='_09788675'][class*='e19cc933']"
            ]
            # Get all p elements and try to find location (usually contains country/city)
            p_elements = card.query_selector_all("p[class*='_75885701']")
            for elem in p_elements:
                try:
                    text = elem.inner_text().strip()
                    # Look for text that contains location indicators
                    if text and text != name and (
                        ", India" in text or ", Maharashtra," in text or
                        ", Karnataka," in text or ", Andhra Pradesh," in text or
                        ", Telangana," in text or ", Kerala," in text or
                        ", Tamil Nadu," in text or ", Gujarat," in text or
                        "India" in text or "Area" in text
                    ):
                        location = text
                        break
                except:
                    continue

            # Fallback to original selectors
            if not location:
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
                resume_url=resume_url,
                resume_filename=resume_filename,
                resume_downloaded=bool(resume_filename),
                status=CandidateStatus.COLLECTED if resume_filename else CandidateStatus.PENDING
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
                "Resume Downloaded": "Yes" if candidate.resume_downloaded else "No",
                "Resume Filename": candidate.resume_filename or "",
                "Resume URL": candidate.resume_url or "",
                "Job Title": job_post.job_title,
                "Status": candidate.status.value
            })

        df = pd.DataFrame(data)
        df.to_csv(output_file, index=False)

        print(f"✅ Saved {len(data)} candidates to {output_file}")

        # Print summary
        with_resume = sum(1 for c in job_post.candidates if c.resume_downloaded)
        with_email = sum(1 for c in job_post.candidates if c.email)
        print(f"\n📊 Summary:")
        print(f"   Total candidates: {len(job_post.candidates)}")
        print(f"   Resumes downloaded: {with_resume}")
        print(f"   With email: {with_email}")
        print(f"   Resumes saved to: {self.resume_dir}")


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
            print("\n🔑 Please log in to LinkedIn in the browser window")
            print("\n📝 Instructions:")
            print("   1. The browser will open LinkedIn")
            print("   2. Log in with your credentials")
            print("   3. Once logged in, your session will be saved for future use")
            print("   4. Press Enter here after you've logged in")

            scraper.page.goto("https://www.linkedin.com/login")
            input("\nPress Enter after logging in...")

            # Verify login worked
            if not scraper.check_login():
                print("❌ Login verification failed. Please try again.")
                return
        else:
            print("🎉 Using saved login session!")

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
    print("   • Resume downloads typically require LinkedIn Recruiter subscription")
    print("   • LinkedIn frequently changes their HTML structure")
    print("   • For best results, use LinkedIn Recruiter and manually verify data")
    print("   • Always respect LinkedIn's Terms of Service and rate limits")
    print("   • Resumes are saved in the ./resumes/ directory")


if __name__ == "__main__":
    main()
