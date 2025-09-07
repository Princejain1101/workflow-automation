#!/usr/bin/env python3
"""
SmartScout Session Management System

A robust session manager that orchestrates the complete brand processing workflow
with persistent state tracking, retry logic, and intelligent error handling.

Features:
- Persistent session state across interruptions
- Smart retry logic with exponential backoff
- Comprehensive error handling and recovery
- Progress monitoring and reporting
- Session-specific folder management
- Integration with existing SmartScout authentication

Usage:
    # Start new session
    python smartscout_session_manager.py --start brands.csv --session-name "batch-2024"
    
    # Resume existing session
    python smartscout_session_manager.py --resume session_123
    
    # Monitor progress
    python smartscout_session_manager.py --status session_123
    
    # Cleanup and export results
    python smartscout_session_manager.py --finalize session_123
"""

import os
import sys
import json
import time
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import pandas as pd

# Import existing functions from the main script
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from smartscout_csv_downloader import (
        collect_brand_data,
        download_html_only, 
        summarize_html,
        SMARTSCOUT_API_KEY
    )
except ImportError as e:
    print(f"❌ Error importing SmartScout functions: {e}")
    print("Make sure smartscout_csv_downloader.py is in the same directory")
    sys.exit(1)


class BrandStatus(Enum):
    """Brand processing status states"""
    PENDING = "pending"
    COLLECTING = "collecting"
    NO_BRAND_FOUND = "no_brand_found"
    COLLECTED = "collected"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    SUMMARIZING = "summarizing"
    SUMMARIZED = "summarized"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepResult(Enum):
    """Individual step execution results"""
    SUCCESS = "success"
    RETRY = "retry"
    SKIP = "skip"
    FAIL = "fail"


@dataclass
class BrandState:
    """Represents the processing state of a single brand"""
    name: str
    status: BrandStatus = BrandStatus.PENDING
    current_step: str = "collect"
    attempts: Dict[str, int] = None
    last_attempt: Dict[str, str] = None
    errors: List[str] = None
    results: Dict[str, any] = None
    collect_result: str = None
    created_at: str = None
    updated_at: str = None
    
    def __post_init__(self):
        if self.attempts is None:
            self.attempts = {"collect": 0, "download": 0, "summarize": 0}
        if self.last_attempt is None:
            self.last_attempt = {}
        if self.errors is None:
            self.errors = []
        if self.results is None:
            self.results = {}
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()


@dataclass 
class SessionConfig:
    """Session configuration and settings"""
    session_id: str
    session_name: str
    brands_file: str = None
    brands_list: List[str] = None
    html_folder: str = "html"
    summary_folder: str = "summary"
    max_retries: int = 3
    retry_delays: Dict[str, int] = None
    headless: bool = True
    model_provider: str = "gemini"
    model_name: str = None
    force_regenerate: bool = False
    created_at: str = None
    
    def __post_init__(self):
        if self.retry_delays is None:
            # Exponential backoff: collect=60s, download=120s, summarize=30s
            self.retry_delays = {
                "collect": 60,
                "download": 120, 
                "summarize": 30
            }
        if self.created_at is None:
            self.created_at = datetime.now().isoformat()


@dataclass
class SessionState:
    """Complete session state"""
    config: SessionConfig
    brands: Dict[str, BrandState]
    session_folder: str
    started_at: str = None
    completed_at: str = None
    total_brands: int = 0
    completed_brands: int = 0
    failed_brands: int = 0
    
    def __post_init__(self):
        if self.started_at is None:
            self.started_at = datetime.now().isoformat()
        self.total_brands = len(self.brands)


class SessionManager:
    """
    Main session manager class that orchestrates brand processing workflow
    """
    
    def __init__(self, session_folder: str = "sessions"):
        self.sessions_root = session_folder
        self.current_session: Optional[SessionState] = None
        
        # Create sessions directory if it doesn't exist
        os.makedirs(self.sessions_root, exist_ok=True)
        
    def create_session(self, session_name: str, brands_source: str, **kwargs) -> str:
        """
        Create a new processing session or reuse existing one with same name
        
        Args:
            session_name: Human-readable name for the session
            brands_source: CSV file path or comma-separated brand list
            **kwargs: Additional configuration options
            
        Returns:
            session_name: Session name (used as identifier)
        """
        # Use session name as the folder name directly
        session_folder = os.path.join(self.sessions_root, session_name)
        
        # Check if session already exists
        if os.path.exists(session_folder):
            print(f"📁 Found existing session '{session_name}'")
            print("🔄 Will add new brands to existing session...")
            
            # Load existing session
            if self.load_session(session_name):
                # Parse new brands and add to existing session
                new_brands_list = self._parse_brands_source(brands_source)
                added_count = 0
                
                for brand_name in new_brands_list:
                    if brand_name not in self.current_session.brands:
                        self.current_session.brands[brand_name] = BrandState(name=brand_name)
                        added_count += 1
                        
                if added_count > 0:
                    print(f"➕ Added {added_count} new brands to existing session")
                    self.current_session.total_brands = len(self.current_session.brands)
                    self._save_session_state()
                else:
                    print("ℹ️  All brands already exist in this session")
                    
                return session_name
            else:
                print(f"⚠️  Could not load existing session {session_name}, creating new one...")
        
        # Create new session
        print(f"🆕 Creating new session '{session_name}'...")
        
        # Create session directory structure with html and summary inside
        html_folder = os.path.join(session_folder, "html")
        summary_folder = os.path.join(session_folder, "summary")
        logs_folder = os.path.join(session_folder, "logs")
        
        os.makedirs(session_folder, exist_ok=True)
        os.makedirs(html_folder, exist_ok=True)
        os.makedirs(summary_folder, exist_ok=True)
        os.makedirs(logs_folder, exist_ok=True)
        
        # Parse brands from source
        brands_list = self._parse_brands_source(brands_source)
        
        # Create session configuration  
        config = SessionConfig(
            session_id=session_name,
            session_name=session_name,
            brands_file=brands_source if brands_source.endswith(('.csv', '.txt')) else None,
            brands_list=brands_list,
            html_folder=html_folder,
            summary_folder=summary_folder,
            **kwargs
        )
        
        # Initialize brand states
        brands = {
            brand_name: BrandState(name=brand_name)
            for brand_name in brands_list
        }
        
        # Create session state
        self.current_session = SessionState(
            config=config,
            brands=brands,
            session_folder=session_folder
        )
        
        # Save initial state
        self._save_session_state()
        
        print(f"✅ Created session '{session_name}'")
        print(f"📁 Session folder: {session_folder}")
        print(f"📄 HTML folder: {html_folder}")
        print(f"📋 Summary folder: {summary_folder}")
        print(f"🎯 Total brands: {len(brands_list)}")
        
        return session_name
    
    def load_session(self, session_name: str) -> bool:
        """
        Load an existing session from disk
        
        Args:
            session_name: Session name to load
            
        Returns:
            bool: True if session loaded successfully
        """
        session_folder = os.path.join(self.sessions_root, session_name)
        state_file = os.path.join(session_folder, "session_state.json")
        
        if not os.path.exists(state_file):
            print(f"❌ Session '{session_name}' not found")
            return False
            
        try:
            with open(state_file, 'r') as f:
                state_data = json.load(f)
            
            # Reconstruct session state from JSON
            config = SessionConfig(**state_data['config'])
            brands = {
                name: BrandState(**brand_data) 
                for name, brand_data in state_data['brands'].items()
            }
            
            self.current_session = SessionState(
                config=config,
                brands=brands,
                session_folder=session_folder,
                started_at=state_data.get('started_at'),
                completed_at=state_data.get('completed_at'),
                total_brands=state_data.get('total_brands', len(brands)),
                completed_brands=state_data.get('completed_brands', 0),
                failed_brands=state_data.get('failed_brands', 0)
            )
            
            print(f"✅ Loaded session '{config.session_name}'")
            return True
            
        except Exception as e:
            print(f"❌ Error loading session '{session_name}': {e}")
            return False
    
    def _parse_brands_source(self, brands_source: str) -> List[str]:
        """Parse brands from various input formats"""
        if ',' in brands_source:
            # Comma-separated list
            return [brand.strip() for brand in brands_source.split(',') if brand.strip()]
        elif brands_source.endswith('.csv'):
            # CSV file
            try:
                df = pd.read_csv(brands_source)
                # Try common column names
                for col in ['Brand Name', 'Brand', 'brand', 'name', 'Brand_Name']:
                    if col in df.columns:
                        return df[col].dropna().tolist()
                # If no standard column found, use first column
                return df.iloc[:, 0].dropna().tolist()
            except Exception as e:
                print(f"❌ Error reading CSV file: {e}")
                return []
        elif brands_source.endswith('.txt'):
            # Text file (one brand per line)
            try:
                with open(brands_source, 'r') as f:
                    return [line.strip() for line in f if line.strip()]
            except Exception as e:
                print(f"❌ Error reading text file: {e}")
                return []
        else:
            # Single brand name
            return [brands_source]
    
    def _save_session_state(self):
        """Save current session state to disk"""
        if not self.current_session:
            return
            
        state_file = os.path.join(self.current_session.session_folder, "session_state.json")
        
        # Convert session state to JSON-serializable format
        state_data = {
            'config': asdict(self.current_session.config),
            'brands': {
                name: asdict(brand_state) 
                for name, brand_state in self.current_session.brands.items()
            },
            'session_folder': self.current_session.session_folder,
            'started_at': self.current_session.started_at,
            'completed_at': self.current_session.completed_at,
            'total_brands': self.current_session.total_brands,
            'completed_brands': self.current_session.completed_brands,
            'failed_brands': self.current_session.failed_brands
        }
        
        # Convert enums to strings
        for brand_data in state_data['brands'].values():
            if isinstance(brand_data['status'], BrandStatus):
                brand_data['status'] = brand_data['status'].value
            else:
                # Already converted to string in previous save
                pass
        
        try:
            with open(state_file, 'w') as f:
                json.dump(state_data, f, indent=2, default=str)
        except Exception as e:
            print(f"❌ Error saving session state: {e}")
    
    def get_session_status(self) -> Dict:
        """Get comprehensive session status"""
        if not self.current_session:
            return {"error": "No active session"}
        
        status_counts = {}
        for brand_state in self.current_session.brands.values():
            status = brand_state.status.value if isinstance(brand_state.status, BrandStatus) else brand_state.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "session_id": self.current_session.config.session_id,
            "session_name": self.current_session.config.session_name,
            "total_brands": self.current_session.total_brands,
            "status_breakdown": status_counts,
            "completed_brands": self.current_session.completed_brands,
            "failed_brands": self.current_session.failed_brands,
            "started_at": self.current_session.started_at,
            "completed_at": self.current_session.completed_at,
            "session_folder": self.current_session.session_folder
        }
    
    def run_session(self):
        """
        Execute the complete session workflow in batch mode
        """
        if not self.current_session:
            print("❌ No active session")
            return
        
        print(f"\n🚀 Starting session: {self.current_session.config.session_name}")
        print(f"📊 Processing {self.current_session.total_brands} brands in BATCH MODE")
        print(f"🔧 Configuration:")
        print(f"   • Headless mode: {self.current_session.config.headless}")
        print(f"   • Model: {self.current_session.config.model_provider}")
        print("=" * 60)
        
        try:
            # Show initial table
            self.print_session_table()
            
            # Resume logic: Handle incomplete brands from previous session
            self._handle_resume_brands()
            
            # Phase 1: Initial complete pipeline
            print(f"\n📊 PHASE 1: Initial processing pipeline")
            print("=" * 60)
            
            print("  🔄 Step 1a: Collecting data for all brands")
            self._batch_collect_all()
            
            print("  📥 Step 1b: Downloading immediately available reports")
            self._batch_download_all()
            
            print("  🤖 Step 1c: Summarizing downloaded reports")
            self._batch_summarize_all()
            
            self.print_session_table()
            
            # Multi-phase retry system with progressive wait times
            retry_phases = [
                {"wait_minutes": 5, "wait_seconds": 300, "phase_name": "PHASE 2", "description": "First retry after 5 minutes"},
                {"wait_minutes": 10, "wait_seconds": 600, "phase_name": "PHASE 3", "description": "Second retry after 10 minutes"},
                {"wait_minutes": 30, "wait_seconds": 1800, "phase_name": "PHASE 4", "description": "Third retry after 30 minutes"},
                {"wait_minutes": 60, "wait_seconds": 3600, "phase_name": "PHASE 5", "description": "Final retry after 60 minutes"}
            ]
            
            for phase in retry_phases:
                # Check for incomplete brands
                incomplete_brands = self._get_brands_by_status([
                    BrandStatus.PENDING, BrandStatus.COLLECTING, BrandStatus.ANALYZING, 
                    BrandStatus.COLLECTED, BrandStatus.FAILED
                ])
                
                if incomplete_brands:
                    print(f"\n⏳ {phase['phase_name']}: {phase['description']} ({len(incomplete_brands)} brands remaining)")
                    print("=" * 60)
                    print(f"  Brands still processing: {', '.join(incomplete_brands[:5])}{'...' if len(incomplete_brands) > 5 else ''}")
                    
                    # Export progress CSV before waiting
                    print(f"📊 Exporting progress CSV before {phase['wait_minutes']}-minute wait...")
                    self._export_csv_results()
                    
                    self._wait_with_progress(phase['wait_seconds'], f"Waiting {phase['wait_minutes']} minutes for more brands to complete")
                    
                    print(f"  🔄 Step A: Re-checking analysis status")
                    self._batch_recheck_all()
                    
                    print(f"  📥 Step B: Downloading newly ready reports")
                    self._batch_download_all()
                    
                    print(f"  🤖 Step C: Summarizing newly downloaded reports")
                    self._batch_summarize_all()
                    
                    # For the final phase, also retry failed collections
                    if phase['phase_name'] == "PHASE 5":
                        print(f"  🔄 Step D: Final attempt to collect remaining brands")
                        self._batch_collect_all()
                        
                        print(f"  📥 Step E: Download any new reports")
                        self._batch_download_all()
                        
                        print(f"  🤖 Step F: Summarize any new reports")
                        self._batch_summarize_all()
                    
                    self.print_session_table()
                else:
                    print(f"\n✅ All brands completed - skipping {phase['phase_name']}!")
            
            # Mark session as completed
            self.current_session.completed_at = datetime.now().isoformat()
            self._save_session_state()
            
            print(f"\n✅ Batch processing completed!")
            self._show_final_summary()
            
            # Export results to CSV if original input was a CSV file
            self._export_csv_results()
            
        except KeyboardInterrupt:
            print(f"\n⏸️  Session interrupted - state saved")
            print(f"Resume with: python {sys.argv[0]} --resume {self.current_session.config.session_id}")
        except Exception as e:
            print(f"\n❌ Session error: {e}")
            self._save_session_state()

    def _batch_collect_all(self):
        """Collect data for all pending brands"""
        pending_brands = [
            (name, state) for name, state in self.current_session.brands.items()
            if state.status == BrandStatus.PENDING
        ]
        
        if not pending_brands:
            print("ℹ️  No brands need data collection")
            return
            
        print(f"🔄 Starting collection for {len(pending_brands)} brands...")
        
        for i, (brand_name, brand_state) in enumerate(pending_brands, 1):
            print(f"  📊 Collecting {i}/{len(pending_brands)}: {brand_name}")
            brand_state.status = BrandStatus.COLLECTING
            
            try:
                result = self._collect_step_simple(brand_name)
                
                if result == "no_brand_found":
                    brand_state.status = BrandStatus.NO_BRAND_FOUND
                elif result == "collected":
                    brand_state.status = BrandStatus.COLLECTED
                elif result == "analyzing":
                    brand_state.status = BrandStatus.ANALYZING
                elif result == "analyzed":
                    brand_state.status = BrandStatus.ANALYZED
                else:
                    brand_state.status = BrandStatus.FAILED
                    
            except Exception as e:
                print(f"    ❌ Error: {e}")
                brand_state.status = BrandStatus.FAILED
            
            # Update attempts and timestamp
            brand_state.attempts["collect"] = 1
            brand_state.last_attempt["collect"] = datetime.now().isoformat()
            
            # Save progress every 5 brands
            if i % 5 == 0:
                self._save_session_state()
        
        self._save_session_state()

    def _batch_download_all(self):
        """Download HTML for all ready brands"""
        ready_brands = [
            (name, state) for name, state in self.current_session.brands.items()
            if state.status == BrandStatus.ANALYZED  # Only download when report is actually ready
        ]
        
        if not ready_brands:
            print("ℹ️  No brands ready for download")
            return
            
        print(f"📥 Starting download for {len(ready_brands)} brands...")
        
        for i, (brand_name, brand_state) in enumerate(ready_brands, 1):
            print(f"  💾 Downloading {i}/{len(ready_brands)}: {brand_name}")
            brand_state.status = BrandStatus.DOWNLOADING
            
            try:
                result = self._download_step_simple(brand_name)
                
                if result == "downloaded":
                    brand_state.status = BrandStatus.DOWNLOADED
                elif result == "incomplete":
                    print(f"    ⚠️  {brand_name}: File incomplete even after retry - marking as failed")
                    brand_state.status = BrandStatus.FAILED
                else:
                    brand_state.status = BrandStatus.FAILED
                    
            except Exception as e:
                print(f"    ❌ Error: {e}")
                brand_state.status = BrandStatus.FAILED
            
            # Update attempts and timestamp
            brand_state.attempts["download"] = 1
            brand_state.last_attempt["download"] = datetime.now().isoformat()
            
            # Save progress every 5 brands
            if i % 5 == 0:
                self._save_session_state()
        
        self._save_session_state()

    def _batch_summarize_all(self):
        """Generate summaries for all downloaded brands"""
        downloaded_brands = [
            (name, state) for name, state in self.current_session.brands.items()
            if state.status == BrandStatus.DOWNLOADED
        ]
        
        if not downloaded_brands:
            print("ℹ️  No brands ready for summarization")
            return
            
        print(f"🤖 Starting summarization for {len(downloaded_brands)} brands...")
        
        for i, (brand_name, brand_state) in enumerate(downloaded_brands, 1):
            print(f"  📋 Summarizing {i}/{len(downloaded_brands)}: {brand_name}")
            brand_state.status = BrandStatus.SUMMARIZING
            
            try:
                result = self._summarize_step_simple(brand_name)
                
                if result == "summarized":
                    brand_state.status = BrandStatus.SUMMARIZED
                    self.current_session.completed_brands += 1
                else:
                    brand_state.status = BrandStatus.FAILED
                    self.current_session.failed_brands += 1
                    
            except Exception as e:
                print(f"    ❌ Error: {e}")
                brand_state.status = BrandStatus.FAILED
                self.current_session.failed_brands += 1
            
            # Update attempts and timestamp
            brand_state.attempts["summarize"] = 1
            brand_state.last_attempt["summarize"] = datetime.now().isoformat()
            
            # Save progress every 5 brands
            if i % 5 == 0:
                self._save_session_state()
        
        self._save_session_state()

    def _handle_resume_brands(self):
        """Handle incomplete brands from previous session - retry failed, recheck analyzing/collected"""
        failed_brands = []
        recheck_brands = []  # analyzing or collected brands that need status check
        
        for name, state in self.current_session.brands.items():
            # Handle both enum and string status values (from JSON loading)
            status_value = state.status.value if hasattr(state.status, 'value') else state.status
            
            if status_value in ['failed', 'no_brand_found']:
                failed_brands.append((name, state))
            elif status_value in ['analyzing', 'collected']:
                recheck_brands.append((name, state))
        
        if not failed_brands and not recheck_brands:
            return  # Nothing to resume
            
        print(f"\n🔄 RESUME: Handling incomplete brands from previous session")
        print("=" * 60)
        
        # Reset failed and no_brand_found brands to pending for retry
        if failed_brands:
            print(f"♻️  Resetting {len(failed_brands)} failed/not-found brands to retry:")
            for name, state in failed_brands:
                status_display = state.status.value if hasattr(state.status, 'value') else state.status
                print(f"   📍 {name}: {status_display} → pending")
                state.status = BrandStatus.PENDING
                state.errors = []  # Clear previous errors
        
        # Re-check analyzing/collected brands (they might be ready now)
        if recheck_brands:
            print(f"🔍 Re-checking {len(recheck_brands)} incomplete brands:")
            for name, state in recheck_brands:
                status_value = state.status.value if hasattr(state.status, 'value') else state.status
                print(f"   📊 Checking {name} (current: {status_value})...")
                try:
                    result = self._collect_step_simple(name)
                    if result == "analyzed":
                        state.status = BrandStatus.ANALYZED
                        print(f"      ✅ Ready for download!")
                    elif result == "analyzing":
                        state.status = BrandStatus.ANALYZING
                        print(f"      ⏳ Still analyzing...")
                    elif result == "collected":
                        state.status = BrandStatus.COLLECTED
                        print(f"      📊 Collected, waiting for analysis...")
                    else:
                        print(f"      ❓ Status: {result}")
                except Exception as e:
                    print(f"      ❌ Error checking: {e}")
        
        self._save_session_state()
        print()

    def _wait_with_progress(self, seconds: int, message: str):
        """Wait with progress indicator"""
        print(f"⏳ {message} - waiting {seconds//60} minutes...")
        
        for remaining in range(seconds, 0, -30):
            mins, secs = divmod(remaining, 60)
            print(f"    🕐 {mins:02d}:{secs:02d} remaining", end='\r')
            time.sleep(30 if remaining >= 30 else remaining)
        
        print(f"    ✅ Wait complete!                    ")

    def _show_final_summary(self):
        """Show comprehensive final results"""
        status_counts = {}
        for brand_state in self.current_session.brands.values():
            # Handle both enum and string status values
            status = brand_state.status.value if hasattr(brand_state.status, 'value') else brand_state.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        print(f"\n🎯 FINAL RESULTS")
        print("=" * 50)
        
        for status, count in sorted(status_counts.items()):
            emoji = self._get_status_display(BrandStatus(status)).split()[0]
            print(f"{emoji} {status.title()}: {count} brands")
        
        success_rate = (status_counts.get('summarized', 0) / self.current_session.total_brands) * 100
        print(f"\n📈 Success Rate: {success_rate:.1f}% ({status_counts.get('summarized', 0)}/{self.current_session.total_brands})")
        
        # Show folder information
        print(f"\n📁 FOLDER INFORMATION")
        print("=" * 50)
        
        # HTML folder
        html_folder = self.current_session.config.html_folder
        html_size, html_count = self._get_folder_stats(html_folder)
        print(f"📄 HTML Folder: {html_folder}")
        print(f"   Files: {html_count} | Size: {html_size}")
        
        # Summary folder  
        summary_folder = self.current_session.config.summary_folder
        summary_size, summary_count = self._get_folder_stats(summary_folder)
        print(f"📋 Summary Folder: {summary_folder}")
        print(f"   Files: {summary_count} | Size: {summary_size}")
        
        # Session folder
        session_folder = self.current_session.session_folder
        session_size, session_count = self._get_folder_stats(session_folder)
        print(f"🗂️  Session Folder: {session_folder}")
        print(f"   Files: {session_count} | Size: {session_size}")

    def _export_csv_results(self):
        """Export session results back to CSV file if original input was CSV"""
        # Only export if original input was a CSV file
        if not self.current_session.config.brands_file or not self.current_session.config.brands_file.endswith('.csv'):
            return
        
        print(f"\n📊 CSV EXPORT")
        print("=" * 50)
        
        try:
            # Read original CSV file
            original_csv = self.current_session.config.brands_file
            if not os.path.exists(original_csv):
                print(f"⚠️  Original CSV file not found: {original_csv}")
                return
            
            df = pd.read_csv(original_csv)
            print(f"📄 Reading original CSV: {original_csv}")
            print(f"   Rows: {len(df)} | Columns: {len(df.columns)}")
            
            # Find the brand column (same logic as _parse_brands_source)
            brand_column = None
            for col in ['Brand Name', 'Brand', 'brand', 'name', 'Brand_Name']:
                if col in df.columns:
                    brand_column = col
                    break
            
            if not brand_column:
                brand_column = df.columns[0]  # Use first column as fallback
            
            print(f"🏷️  Using brand column: '{brand_column}'")
            
            # Add Brand Data column if it doesn't exist
            if "Brand Data" not in df.columns:
                df["Brand Data"] = ""
            
            # Load summaries from session and match to CSV rows
            summaries_loaded = 0
            for index, row in df.iterrows():
                brand_name = str(row[brand_column]).strip()
                if not brand_name or brand_name.lower() == 'nan':
                    continue
                
                # Try to find matching brand in session (case-insensitive)
                matching_brand = None
                for session_brand in self.current_session.brands.keys():
                    if session_brand.lower() == brand_name.lower():
                        matching_brand = session_brand
                        break
                
                if matching_brand:
                    # Load summary file for this brand
                    summary_filename = f"{matching_brand.replace(' ', '_').lower()}_analysis.txt"
                    summary_path = os.path.join(self.current_session.config.summary_folder, summary_filename)
                    
                    if os.path.exists(summary_path):
                        try:
                            with open(summary_path, 'r', encoding='utf-8') as f:
                                summary_content = f.read().strip()
                            df.at[index, "Brand Data"] = summary_content
                            summaries_loaded += 1
                        except Exception as e:
                            df.at[index, "Brand Data"] = f"Error loading summary: {e}"
                    else:
                        # Check brand status
                        brand_state = self.current_session.brands[matching_brand]
                        status_value = brand_state.status.value if hasattr(brand_state.status, 'value') else brand_state.status
                        df.at[index, "Brand Data"] = f"Summary Status: {status_value}"
                else:
                    df.at[index, "Brand Data"] = "Brand not processed in this session"
            
            # Save to session folder with _with_brand_data suffix
            original_filename = os.path.basename(original_csv)
            output_filename = original_filename.replace('.csv', '_with_brand_data.csv')
            output_path = os.path.join(self.current_session.session_folder, output_filename)
            
            df.to_csv(output_path, index=False)
            
            print(f"✅ CSV export completed!")
            print(f"   📄 Output file: {output_path}")
            print(f"   📊 Summaries loaded: {summaries_loaded}/{len(df)}")
            print(f"   💾 File size: {os.path.getsize(output_path) / 1024:.1f} KB")
            
        except Exception as e:
            print(f"❌ Error exporting CSV: {e}")

    def _get_folder_stats(self, folder_path: str) -> tuple:
        """Get folder statistics: (size_string, file_count)"""
        if not os.path.exists(folder_path):
            return "0 KB", 0
            
        total_size = 0
        file_count = 0
        
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if not file.startswith('.'):  # Skip hidden files
                        file_path = os.path.join(root, file)
                        try:
                            total_size += os.path.getsize(file_path)
                            file_count += 1
                        except OSError:
                            pass  # Skip files that can't be accessed
        except OSError:
            return "Error", 0
            
        # Format size nicely
        if total_size < 1024:
            size_str = f"{total_size} B"
        elif total_size < 1024 * 1024:
            size_str = f"{total_size / 1024:.1f} KB"
        elif total_size < 1024 * 1024 * 1024:
            size_str = f"{total_size / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{total_size / (1024 * 1024 * 1024):.1f} GB"
            
        return size_str, file_count

    def _get_brand_html_size(self, brand_name: str) -> str:
        """Get HTML file size for a specific brand"""
        if not self.current_session or not self.current_session.config.html_folder:
            return "-"
            
        # Generate expected HTML filename
        html_filename = f"{brand_name.replace(' ', '_').lower()}_report.html"
        html_file_path = os.path.join(self.current_session.config.html_folder, html_filename)
        
        try:
            if os.path.exists(html_file_path):
                file_size = os.path.getsize(html_file_path)
                
                # Format size nicely
                if file_size < 1024:
                    return f"{file_size}B"
                elif file_size < 1024 * 1024:
                    return f"{file_size // 1024}KB"
                elif file_size < 1024 * 1024 * 1024:
                    return f"{file_size // (1024 * 1024)}MB"
                else:
                    return f"{file_size // (1024 * 1024 * 1024)}GB"
            else:
                return "-"
        except OSError:
            return "Error"

    def _get_brands_by_status(self, statuses: list) -> list:
        """Get list of brand names with any of the given statuses"""
        return [
            name for name, state in self.current_session.brands.items()
            if state.status in statuses
        ]

    def _batch_recheck_all(self):
        """Re-check collect status for brands that might be ready now"""
        recheck_brands = [
            (name, state) for name, state in self.current_session.brands.items()
            if state.status in [BrandStatus.ANALYZING, BrandStatus.COLLECTED]
        ]
        
        if not recheck_brands:
            print("ℹ️  No brands need status re-check")
            return
            
        print(f"🔄 Re-checking status for {len(recheck_brands)} brands...")
        
        for i, (brand_name, brand_state) in enumerate(recheck_brands, 1):
            print(f"  📊 Re-checking {i}/{len(recheck_brands)}: {brand_name}")
            
            try:
                result = self._collect_step_simple(brand_name)
                
                if result == "analyzed":
                    brand_state.status = BrandStatus.ANALYZED
                    print(f"    ✅ {brand_name} is now ready for download!")
                elif result == "analyzing":
                    brand_state.status = BrandStatus.ANALYZING
                    print(f"    ⏳ {brand_name} still analyzing...")
                # Keep other statuses as they were
                    
            except Exception as e:
                print(f"    ❌ Error re-checking {brand_name}: {e}")
            
            # Save progress every 5 brands
            if i % 5 == 0:
                self._save_session_state()
        
        self._save_session_state()

    def _collect_step_simple(self, brand_name: str) -> str:
        """Execute data collection step without retries"""
        # Set global folder paths for the existing functions
        globals()['_html_folder'] = self.current_session.config.html_folder
        globals()['_summary_folder'] = self.current_session.config.summary_folder
        
        result = collect_brand_data(
            brand_name, 
            return_result=True, 
            headless=self.current_session.config.headless
        )
        
        return result

    def _download_step_simple(self, brand_name: str) -> str:
        """Execute HTML download step without retries"""
        # Set global folder paths (for backward compatibility)
        globals()['_html_folder'] = self.current_session.config.html_folder
        globals()['_summary_folder'] = self.current_session.config.summary_folder
        
        result = download_html_only(
            brand_name,
            headless=self.current_session.config.headless,
            return_result=True,
            html_folder=self.current_session.config.html_folder,
            force_regenerate=self.current_session.config.force_regenerate
        )
        
        return result if result else "failed"

    def _summarize_step_simple(self, brand_name: str) -> str:
        """Execute summary generation step without retries"""
        # Set global folder paths (for backward compatibility)
        globals()['_html_folder'] = self.current_session.config.html_folder
        globals()['_summary_folder'] = self.current_session.config.summary_folder
        
        try:
            summary = summarize_html(
                brand_name,
                model_provider=self.current_session.config.model_provider,
                model_name=self.current_session.config.model_name,
                force_regenerate=self.current_session.config.force_regenerate,
                html_folder=self.current_session.config.html_folder,
                summary_folder=self.current_session.config.summary_folder
            )
            
            return "summarized" if summary and len(summary) > 100 else "failed"
                
        except Exception as e:
            return "failed"

    def _process_brand(self, brand_name: str, brand_state: BrandState):
        """Process a single brand through the complete workflow"""
        
        # Step 1: Collect data
        if brand_state.status == BrandStatus.PENDING:
            brand_state.status = BrandStatus.COLLECTING
            self._save_session_state()
            
            result = self._execute_step("collect", brand_name, brand_state)
            if result == StepResult.SUCCESS:
                # Determine next status based on collect result
                collect_result = getattr(brand_state, 'collect_result', 'collected')
                if collect_result == "no_brand_found":
                    brand_state.status = BrandStatus.NO_BRAND_FOUND
                    return
                elif collect_result == "collected":
                    brand_state.status = BrandStatus.COLLECTED
                elif collect_result == "analyzing":
                    brand_state.status = BrandStatus.ANALYZING
                elif collect_result == "analyzed":
                    brand_state.status = BrandStatus.ANALYZED
            elif result == StepResult.FAIL:
                brand_state.status = BrandStatus.FAILED
                return
        
        # Step 2: Wait for analysis completion and download HTML
        if brand_state.status in [BrandStatus.COLLECTED, BrandStatus.ANALYZING, BrandStatus.ANALYZED]:
            if brand_state.status != BrandStatus.ANALYZED:
                # May need to wait for analysis to complete
                print(f"   ⏳ Waiting for analysis to complete...")
                time.sleep(30)  # Wait before checking download
            
            brand_state.status = BrandStatus.DOWNLOADING
            self._save_session_state()
            
            result = self._execute_step("download", brand_name, brand_state)
            if result == StepResult.SUCCESS:
                brand_state.status = BrandStatus.DOWNLOADED
            elif result == StepResult.FAIL:
                brand_state.status = BrandStatus.FAILED
                return
        
        # Step 3: Generate summary
        if brand_state.status == BrandStatus.DOWNLOADED:
            brand_state.status = BrandStatus.SUMMARIZING
            self._save_session_state()
            
            result = self._execute_step("summarize", brand_name, brand_state)
            if result == StepResult.SUCCESS:
                brand_state.status = BrandStatus.SUMMARIZED
                self.current_session.completed_brands += 1
            elif result == StepResult.FAIL:
                brand_state.status = BrandStatus.FAILED
                self.current_session.failed_brands += 1
    
    def _execute_step(self, step: str, brand_name: str, brand_state: BrandState) -> StepResult:
        """Execute a single processing step with retry logic"""
        
        max_retries = self.current_session.config.max_retries
        retry_delay = self.current_session.config.retry_delays.get(step, 60)
        
        for attempt in range(max_retries + 1):
            if attempt > 0:
                print(f"   🔄 Retry {attempt}/{max_retries} for {step}")
                time.sleep(retry_delay * attempt)  # Exponential backoff
            
            try:
                brand_state.attempts[step] = attempt + 1
                brand_state.last_attempt[step] = datetime.now().isoformat()
                
                if step == "collect":
                    result = self._collect_step(brand_name)
                elif step == "download":
                    result = self._download_step(brand_name)
                elif step == "summarize":
                    result = self._summarize_step(brand_name)
                else:
                    result = StepResult.FAIL
                
                if result == StepResult.SUCCESS:
                    print(f"   ✅ {step} completed")
                    return StepResult.SUCCESS
                elif result == StepResult.SKIP:
                    print(f"   ⏭️  {step} skipped")
                    return StepResult.SUCCESS
                
            except Exception as e:
                error_msg = f"{step} attempt {attempt + 1} failed: {str(e)}"
                brand_state.errors.append(error_msg)
                print(f"   ❌ {error_msg}")
        
        print(f"   💀 {step} failed after {max_retries + 1} attempts")
        return StepResult.FAIL
    
    def _collect_step(self, brand_name: str) -> StepResult:
        """Execute data collection step"""
        print(f"   📊 Collecting data for {brand_name}...")
        
        # Set global folder paths for the existing functions
        os.environ['_html_folder'] = self.current_session.config.html_folder
        
        result = collect_brand_data(
            brand_name, 
            return_result=True, 
            headless=self.current_session.config.headless
        )
        
        # Store the collect result for status determination
        brand_state = self.current_session.brands[brand_name]
        brand_state.collect_result = result
        
        if result in ["collected", "analyzing", "analyzed"]:
            return StepResult.SUCCESS
        elif result == "no_brand_found":
            return StepResult.FAIL  # Don't retry if brand doesn't exist
        else:
            return StepResult.RETRY
    
    def _download_step(self, brand_name: str) -> StepResult:
        """Execute HTML download step"""
        print(f"   📥 Downloading HTML for {brand_name}...")
        
        # Set global folder paths
        globals()['_html_folder'] = self.current_session.config.html_folder
        
        result = download_html_only(
            brand_name,
            headless=self.current_session.config.headless,
            return_result=True
        )
        
        if result == "downloaded":
            return StepResult.SUCCESS
        elif result == "not_found_in_search":
            return StepResult.RETRY
        else:
            return StepResult.RETRY
    
    def _summarize_step(self, brand_name: str) -> StepResult:
        """Execute summary generation step"""
        print(f"   🤖 Generating summary for {brand_name}...")
        
        # Set global folder paths
        globals()['_html_folder'] = self.current_session.config.html_folder
        globals()['_summary_folder'] = self.current_session.config.summary_folder
        
        try:
            summary = summarize_html(
                brand_name,
                model_provider=self.current_session.config.model_provider,
                model_name=self.current_session.config.model_name,
                force_regenerate=self.current_session.config.force_regenerate
            )
            
            if summary and len(summary) > 100:  # Basic validation
                return StepResult.SUCCESS
            else:
                return StepResult.RETRY
                
        except Exception as e:
            print(f"   ❌ Summary error: {e}")
            return StepResult.RETRY
    
    def print_session_summary(self):
        """Print comprehensive session summary"""
        if not self.current_session:
            return
            
        status = self.get_session_status()
        
        print(f"\n📊 SESSION SUMMARY")
        print("=" * 60)
        print(f"Session: {status['session_name']} (ID: {status['session_id']})")
        print(f"Total Brands: {status['total_brands']}")
        print(f"Completed: {status['completed_brands']}")
        print(f"Failed: {status['failed_brands']}")
        print(f"Started: {status['started_at']}")
        print(f"Folder: {status['session_folder']}")
        
        print(f"\n📈 Status Breakdown:")
        for status_name, count in status['status_breakdown'].items():
            print(f"   • {status_name.title()}: {count}")
        
        # Show failed brands
        failed_brands = [
            name for name, brand in self.current_session.brands.items()
            if brand.status == BrandStatus.FAILED
        ]
        
        if failed_brands:
            print(f"\n❌ Failed Brands:")
            for brand in failed_brands[:10]:  # Show first 10
                print(f"   • {brand}")
            if len(failed_brands) > 10:
                print(f"   ... and {len(failed_brands) - 10} more")

    def print_session_table(self):
        """Print comprehensive session table with all brand statuses"""
        if not self.current_session:
            return
            
        # Table headers
        max_brand_width = max(len("Brand Name"), max(len(name) for name in self.current_session.brands.keys()) if self.current_session.brands else 10)
        max_brand_width = min(max_brand_width, 25)  # Cap at 25 chars
        
        status_width = 15
        attempt_width = 8
        size_width = 10
        time_width = 12
        
        # Print table header
        print(f"\n📊 SESSION PROGRESS TABLE")
        print("=" * 95)
        print(f"Session: {self.current_session.config.session_name} ({self.current_session.config.session_id})")
        print("-" * 95)
        
        # Header row
        header_row = (f"{'Brand Name':<{max_brand_width}} | "
                     f"{'Status':<{status_width}} | "
                     f"{'Collect':<{attempt_width}} | "
                     f"{'Download':<{attempt_width}} | "
                     f"{'Summary':<{attempt_width}} | "
                     f"{'HTML Size':<{size_width}} | "
                     f"{'Updated':<{time_width}}")
        print(header_row)
        print("-" * len(header_row))
        
        # Brand rows
        for brand_name, brand_state in self.current_session.brands.items():
            # Truncate brand name if too long
            display_name = brand_name[:max_brand_width-2] + ".." if len(brand_name) > max_brand_width else brand_name
            
            # Format step completion status (simple checkmarks instead of attempt counters)
            collect_status = "✅" if brand_state.attempts.get('collect', 0) > 0 else "⏳"
            download_status = "✅" if brand_state.attempts.get('download', 0) > 0 else "⏳"
            summary_status = "✅" if brand_state.attempts.get('summarize', 0) > 0 else "⏳"
            
            # Format last updated time
            last_updated = "Never"
            if brand_state.last_attempt:
                latest_time = max(brand_state.last_attempt.values()) if brand_state.last_attempt else None
                if latest_time:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(latest_time.replace('Z', '+00:00'))
                        last_updated = dt.strftime("%H:%M:%S")
                    except:
                        last_updated = "Unknown"
            
            # Status with emoji
            status_display = self._get_status_display(brand_state.status)
            
            # Get HTML file size
            html_size = self._get_brand_html_size(brand_name)
            
            row = (f"{display_name:<{max_brand_width}} | "
                  f"{status_display:<{status_width}} | "
                  f"{collect_status:<{attempt_width}} | "
                  f"{download_status:<{attempt_width}} | "
                  f"{summary_status:<{attempt_width}} | "
                  f"{html_size:<{size_width}} | "
                  f"{last_updated:<{time_width}}")
            print(row)
        
        # Summary footer
        print("-" * len(header_row))
        status_counts = {}
        for brand_state in self.current_session.brands.values():
            # Handle both enum and string status values
            status = brand_state.status.value if hasattr(brand_state.status, 'value') else brand_state.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        summary_parts = []
        for status, count in sorted(status_counts.items()):
            summary_parts.append(f"{status}: {count}")
        
        print(f"Summary: {' | '.join(summary_parts)}")
        print("=" * 80)

    def _get_status_display(self, status) -> str:
        """Get status with emoji for display"""
        # Create mappings for both enum and string values
        status_emojis = {
            BrandStatus.PENDING: "⏳ pending",
            "pending": "⏳ pending",
            BrandStatus.COLLECTING: "🔄 collecting",
            "collecting": "🔄 collecting", 
            BrandStatus.NO_BRAND_FOUND: "❌ not found",
            "no_brand_found": "❌ not found",
            BrandStatus.COLLECTED: "✅ collected",
            "collected": "✅ collected",
            BrandStatus.ANALYZING: "⚡ analyzing",
            "analyzing": "⚡ analyzing",
            BrandStatus.ANALYZED: "📊 analyzed",
            "analyzed": "📊 analyzed", 
            BrandStatus.DOWNLOADING: "📥 downloading",
            "downloading": "📥 downloading",
            BrandStatus.DOWNLOADED: "💾 downloaded",
            "downloaded": "💾 downloaded",
            BrandStatus.SUMMARIZING: "🤖 summarizing",
            "summarizing": "🤖 summarizing",
            BrandStatus.SUMMARIZED: "📋 summarized",
            "summarized": "📋 summarized",
            BrandStatus.FAILED: "💥 failed",
            "failed": "💥 failed",
            BrandStatus.SKIPPED: "⏭️ skipped",
            "skipped": "⏭️ skipped"
        }
        
        # Handle both enum and string status values
        status_value = status.value if hasattr(status, 'value') else status
        return status_emojis.get(status, status_emojis.get(status_value, f"❓ {status_value}"))


def main():
    """Main CLI interface"""
    if len(sys.argv) < 2:
        print_usage()
        return
    
    manager = SessionManager()
    
    command = sys.argv[1]
    
    if command == "--start":
        if len(sys.argv) < 3:
            print("❌ Usage: --start <brands_source> --session-name <name> [options]")
            return
            
        brands_source = sys.argv[2]
        
        # Parse additional arguments
        kwargs = {}
        if "--session-name" in sys.argv:
            idx = sys.argv.index("--session-name")
            if idx + 1 < len(sys.argv):
                kwargs['session_name'] = sys.argv[idx + 1]
            else:
                kwargs['session_name'] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        else:
            kwargs['session_name'] = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        if "--headless" in sys.argv:
            kwargs['headless'] = True
        if "--max-retries" in sys.argv:
            idx = sys.argv.index("--max-retries")
            if idx + 1 < len(sys.argv):
                kwargs['max_retries'] = int(sys.argv[idx + 1])
        
        session_id = manager.create_session(brands_source=brands_source, **kwargs)
        manager.run_session()
        
    elif command == "--resume":
        if len(sys.argv) < 3:
            print("❌ Usage: --resume <session_id>")
            return
            
        session_id = sys.argv[2]
        if manager.load_session(session_id):
            manager.run_session()
    
    elif command == "--status":
        if len(sys.argv) < 3:
            print("❌ Usage: --status <session_id>")
            return
            
        session_id = sys.argv[2]
        if manager.load_session(session_id):
            manager.print_session_summary()
    
    elif command == "--list":
        list_sessions(manager.sessions_root)
    
    elif command == "--help" or command == "-h":
        print_usage()
    
    else:
        print(f"❌ Unknown command: {command}")
        print_usage()


def list_sessions(sessions_root: str):
    """List all available sessions"""
    if not os.path.exists(sessions_root):
        print("📁 No sessions found")
        return
    
    sessions = []
    for session_dir in os.listdir(sessions_root):
        session_path = os.path.join(sessions_root, session_dir)
        state_file = os.path.join(session_path, "session_state.json")
        
        if os.path.isdir(session_path) and os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    state = json.load(f)
                sessions.append({
                    'id': session_dir,
                    'name': state['config']['session_name'],
                    'total_brands': state.get('total_brands', 0),
                    'completed_brands': state.get('completed_brands', 0),
                    'created': state['config']['created_at']
                })
            except:
                continue
    
    if not sessions:
        print("📁 No valid sessions found")
        return
    
    print("📊 Available Sessions:")
    print("-" * 80)
    for session in sorted(sessions, key=lambda x: x['created'], reverse=True):
        print(f"ID: {session['id']}")
        print(f"Name: {session['name']}")
        print(f"Progress: {session['completed_brands']}/{session['total_brands']} brands")
        print(f"Created: {session['created']}")
        print("-" * 80)


def print_usage():
    """Print CLI usage information"""
    print("""
🎯 SmartScout Session Manager

USAGE:
  Start new session:
    python smartscout_session_manager.py --start <brands_source> --session-name <name>
    
  Resume session:
    python smartscout_session_manager.py --resume <session_id>
    
  Check status:
    python smartscout_session_manager.py --status <session_id>
    
  List sessions:
    python smartscout_session_manager.py --list
    
OPTIONS:
  --headless              Run in background (default: true)
  --max-retries <n>       Maximum retry attempts (default: 3)
  --session-name <name>   Human-readable session name

EXAMPLES:
  python smartscout_session_manager.py --start brands.csv --session-name "Q4-Analysis"
  python smartscout_session_manager.py --start "Brand1,Brand2,Brand3" --session-name "Test-Run"
  python smartscout_session_manager.py --resume session_abc12345
""")


if __name__ == "__main__":
    main()