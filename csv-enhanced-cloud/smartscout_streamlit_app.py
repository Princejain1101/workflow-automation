#!/usr/bin/env python3
"""
SmartScout Brand Analyzer - Streamlit UI
A user-friendly interface for automated SmartScout brand data collection and analysis.
"""

import streamlit as st
import pandas as pd
import hashlib
import os
import time
import webbrowser
from pathlib import Path
from datetime import datetime
import tempfile
import threading
from typing import Optional, Dict, Any

# Import existing session manager
from smartscout_session_manager import SessionManager
from smartscout_csv_downloader import collect_brand_data

# Configure Streamlit page
st.set_page_config(
    page_title="SmartScout Brand Analyzer",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

class StreamlitSessionManager:
    """Wrapper around the existing SessionManager for Streamlit UI"""
    
    def __init__(self):
        self.working_dir = Path(tempfile.gettempdir()) / "smartscout_sessions"
        self.working_dir.mkdir(exist_ok=True)
        # Pass the working directory to SessionManager
        self.session_manager = SessionManager(str(self.working_dir))
    
    def generate_session_name(self, csv_file) -> str:
        """Generate consistent session name from CSV file"""
        if csv_file is None:
            return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Create hash from file content for consistency
        file_content = csv_file.read()
        csv_file.seek(0)  # Reset file pointer
        
        file_hash = hashlib.md5(file_content).hexdigest()[:8]
        filename = csv_file.name.replace('.csv', '').replace(' ', '_')
        
        return f"{filename}_{file_hash}"
    
    def check_existing_session(self, session_name: str) -> Optional[Dict[str, Any]]:
        """Check if session already exists and return its status"""
        session_folder = self.working_dir / session_name
        if session_folder.exists():
            try:
                if self.session_manager.load_session(str(session_name)):
                    return self.get_session_status()
            except Exception:
                pass
        return None
    
    def get_session_status(self) -> Dict[str, Any]:
        """Get current session status for display"""
        if not self.session_manager.current_session:
            return {}
        
        session = self.session_manager.current_session
        status_counts = {}
        
        for brand_state in session.brands.values():
            status = brand_state.status.value if hasattr(brand_state.status, 'value') else brand_state.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            'session_name': session.config.session_name,
            'total_brands': session.total_brands,
            'status_counts': status_counts,
            'brands': session.brands,
            'completed_at': session.completed_at
        }

def check_smartscout_authentication() -> bool:
    """Check if user is authenticated with SmartScout"""
    try:
        from playwright.sync_api import sync_playwright
        import os
        
        # Use same browser data directory as CLI version
        user_data_dir = "./playwright_user_data"
        
        # Check if browser data directory exists (basic check)
        if not os.path.exists(user_data_dir):
            print("Browser data directory not found - user needs to login")
            return False
        
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                args=['--no-sandbox', '--disable-web-security']
            )
            page = browser.new_page()
            
            try:
                # Try to navigate to SmartScout app
                print("Checking SmartScout authentication...")
                page.goto("https://app.smartscout.com/app/tailored-report", timeout=20000)
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                
                current_url = page.url
                print(f"Current URL: {current_url}")
                
                # Check if we're redirected to signin page
                if "signin" in current_url.lower() or "login" in current_url.lower():
                    print("Redirected to signin page - not authenticated")
                    browser.close()
                    return False
                
                # If we're on the tailored-report page, we're likely authenticated
                if "tailored-report" in current_url:
                    print("Successfully reached tailored-report page")
                    browser.close()
                    return True
                    
                print(f"Unexpected URL: {current_url}")
                browser.close()
                return False
                
            except Exception as e:
                print(f"Error during auth check: {e}")
                browser.close()
                return False
                
    except Exception as e:
        print(f"Auth check failed: {e}")
        return False

def open_smartscout_login():
    """Open SmartScout login page for user authentication"""
    import webbrowser
    webbrowser.open("https://app.smartscout.com/sessions/signin")

def setup_smartscout_authentication():
    """Setup SmartScout authentication using Playwright browser"""
    try:
        from playwright.sync_api import sync_playwright
        
        user_data_dir = "./playwright_user_data"
        
        with sync_playwright() as p:
            print("Opening browser for SmartScout authentication...")
            browser = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,  # Always show browser for login
                args=['--no-sandbox', '--disable-web-security']
            )
            page = browser.new_page()
            
            # Navigate to SmartScout signin
            page.goto("https://app.smartscout.com/sessions/signin", timeout=20000)
            
            # Keep browser open for user to login
            st.info("🌐 Browser opened! Please login to SmartScout, then close the browser window when done.")
            st.info("After logging in, click 'Recheck Auth' to verify your authentication.")
            
            # Wait for user to navigate to the app (indicating successful login)
            try:
                # Wait for either successful navigation or timeout
                page.wait_for_url("**/app/**", timeout=60000)  # 1 minute timeout
                st.success("✅ Login detected! You can now close the browser.")
            except:
                st.warning("⚠️ Login timeout reached. Please close the browser manually after logging in.")
            
            browser.close()
            return True
            
    except Exception as e:
        st.error(f"❌ Setup failed: {e}")
        return False

def display_progress_table(brands_dict: Dict):
    """Display the progress table similar to session manager"""
    if not brands_dict:
        return
    
    # Create dataframe for display
    rows = []
    for name, state in brands_dict.items():
        status = state.status.value if hasattr(state.status, 'value') else state.status
        
        # Status emoji mapping
        status_emoji = {
            'pending': '⏳',
            'collecting': '🔄', 
            'collected': '✅',
            'analyzing': '⚡',
            'analyzed': '✅',
            'downloading': '📥',
            'downloaded': '📄',
            'summarizing': '🤖',
            'summarized': '✅',
            'failed': '❌'
        }
        
        rows.append({
            'Brand': name,
            'Status': f"{status_emoji.get(status, '❓')} {status.title()}",
            'Collect': '✅' if state.attempts.get('collect', 0) > 0 else '⏳',
            'Download': '✅' if state.attempts.get('download', 0) > 0 else '⏳',
            'Summary': '✅' if state.attempts.get('summarize', 0) > 0 else '⏳',
            'Updated': state.last_attempt.get('summarize', state.last_attempt.get('download', state.last_attempt.get('collect', 'Never')))[:8] if state.last_attempt else 'Never'
        })
    
    df = pd.DataFrame(rows)
    st.dataframe(df, width="stretch")

def main():
    st.title("🎯 SmartScout Brand Analyzer")
    st.markdown("---")
    
    # Initialize session state
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    if 'session_manager' not in st.session_state:
        st.session_state.session_manager = StreamlitSessionManager()
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Configuration")
        
        # AI Provider selection
        ai_provider = st.selectbox(
            "AI Provider",
            ["gemini", "anthropic"],
            help="Choose your AI provider for generating summaries"
        )
        
        # API Key input (dynamic based on provider)
        if ai_provider == "gemini":
            api_key = st.text_input(
                "Gemini API Key",
                type="password",
                help="Your Google Gemini API key for generating summaries"
            )
            st.info("💡 Get your Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)")
        else:
            api_key = st.text_input(
                "Anthropic API Key", 
                type="password",
                help="Your Anthropic API key for generating summaries"
            )
            st.info("💡 Get your Anthropic API key from [Anthropic Console](https://console.anthropic.com/)")
        
        # SmartScout authentication status
        st.header("SmartScout Authentication")
        
        # Cache auth status to avoid blocking UI
        if 'auth_status' not in st.session_state:
            st.session_state.auth_status = None
            st.session_state.auth_last_check = 0
        
        # Check auth status periodically (not every refresh) - but not during processing
        import time
        current_time = time.time()
        should_check_auth = (st.session_state.auth_status is None or 
                           current_time - st.session_state.auth_last_check > 60)  # Check every 60 seconds
        
        # Don't check auth during processing to avoid conflicts
        if should_check_auth and not st.session_state.processing:
            with st.spinner("Checking authentication..."):
                st.session_state.auth_status = check_smartscout_authentication()
                st.session_state.auth_last_check = current_time
        
        auth_status = st.session_state.auth_status
        
        if auth_status:
            st.success("✅ SmartScout session active")
            if st.button("🔄 Recheck Authentication"):
                # Force a fresh auth check
                st.session_state.auth_status = None
                st.rerun()
        else:
            st.error("❌ SmartScout authentication needed")
            st.info("💡 Your authentication cookies may have expired. Use 'Setup Auth' to login again.")
            
            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("🔧 Setup Auth"):
                    setup_smartscout_authentication()
            with col2:
                if st.button("🌐 Open Login"):
                    open_smartscout_login()
                    st.info("Login manually, then recheck")
            with col3:
                if st.button("🔄 Recheck"):
                    # Force fresh auth check
                    st.session_state.auth_status = None
                    st.rerun()
        
        # Processing options
        st.header("Processing Options") 
        headless_mode = st.checkbox("Headless Mode", value=True, help="Run browser in background")
        force_regenerate = st.checkbox("Force Regenerate", value=False, help="Regenerate existing summaries")
        
        # Session management
        st.header("Session Management")
        if st.button("🗑️ Clear All Sessions", help="Delete all session data and start fresh"):
            import shutil
            import tempfile
            
            # Clear temp sessions
            temp_sessions = Path(tempfile.gettempdir()) / "smartscout_sessions"
            if temp_sessions.exists():
                try:
                    shutil.rmtree(temp_sessions)
                    st.success("✅ All sessions cleared!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error clearing sessions: {e}")
            else:
                st.info("ℹ️ No sessions found to clear")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.header("📁 CSV File Upload")
        
        uploaded_file = st.file_uploader(
            "Choose a CSV file containing brand names",
            type=['csv'],
            help="CSV should have a column with brand names (Brand Name, Brand, name, etc.)"
        )
        
        if uploaded_file is not None:
            # Generate session name
            session_name = st.session_state.session_manager.generate_session_name(uploaded_file)
            
            # Check for existing session
            existing_session = st.session_state.session_manager.check_existing_session(session_name)
            
            if existing_session:
                st.info(f"📂 Found existing session for this file")
                
                col_resume, col_fresh = st.columns(2)
                with col_resume:
                    resume_session = st.button("🔄 Continue Previous Work", type="primary")
                with col_fresh:
                    fresh_start = st.button("🆕 Start Fresh")
                
                if resume_session:
                    st.session_state.resume_mode = True
                    st.session_state.session_name = session_name
                elif fresh_start:
                    st.session_state.resume_mode = False
                    st.session_state.session_name = session_name
            else:
                # New session
                st.session_state.resume_mode = False
                st.session_state.session_name = session_name
                
            # Show CSV preview
            try:
                df = pd.read_csv(uploaded_file)
                st.subheader("📊 CSV Preview")
                st.write(f"**Rows:** {len(df)} | **Columns:** {len(df.columns)}")
                st.dataframe(df.head(), width="stretch")
                
                # Detect brand column
                brand_column = None
                for col in ['Brand Name', 'Brand', 'brand', 'name', 'Brand_Name']:
                    if col in df.columns:
                        brand_column = col
                        break
                if not brand_column:
                    brand_column = df.columns[0]
                
                st.info(f"🏷️ Using brand column: **{brand_column}**")
                
                # Extract unique brands
                unique_brands = df[brand_column].dropna().unique()
                st.write(f"📈 **{len(unique_brands)} unique brands** found")
                
            except Exception as e:
                st.error(f"Error reading CSV: {e}")
                return
    
    with col2:
        st.header("🚀 Processing Control")
        
        # Start processing button
        can_start = (uploaded_file is not None and 
                    api_key and 
                    auth_status and 
                    not st.session_state.processing)
        
        if st.button("▶️ Start Processing", 
                    disabled=not can_start, 
                    type="primary",
                    use_container_width=True):
            st.session_state.processing = True
            st.rerun()
        
        # Stop processing button
        if st.session_state.processing:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("⏹️ Stop Processing", 
                            type="secondary",
                            use_container_width=True):
                    # Request processor to stop
                    if 'processor' in st.session_state:
                        st.session_state.processor.stop_processing_request()
                    st.session_state.processing = False
                    st.rerun()
            with col2:
                if st.button("🚨 Force Stop", 
                            type="secondary",
                            use_container_width=True,
                            help="Emergency stop - clears all processing state"):
                    # Force clear all processing state
                    if 'processor' in st.session_state:
                        del st.session_state.processor
                    st.session_state.processing = False
                    st.success("🛑 Processing force stopped!")
                    st.rerun()
    
    # Processing section - show if currently processing OR if we have completed processing
    show_processing_section = (st.session_state.processing and uploaded_file is not None) or ('processor' in st.session_state and st.session_state.processor.session_manager.current_session)
    
    if show_processing_section:
        st.markdown("---")
        st.header("🔄 Processing Status")
        
        # Initialize processor if not exists
        if 'processor' not in st.session_state:
            from streamlit_processor import StreamlitProcessor
            st.session_state.processor = StreamlitProcessor(st.session_state.session_manager.working_dir)
        
        processor = st.session_state.processor
        
        # Check if we have a completed session (for showing download after page refresh)
        has_completed_session = processor.session_manager.current_session and processor.session_manager.current_session.completed_at
        
        # Show download immediately if we have completed session (bypasses all processing logic)
        if has_completed_session and not st.session_state.processing:
            st.success("✅ Processing completed!")
            st.subheader("📥 Download Results")
            
            # Find and show CSV download
            result_csv_path = processor.get_result_csv_path()
            if not result_csv_path:
                # Fallback search
                import glob
                csv_pattern = os.path.join(processor.working_dir, "**", "*_with_brand_data.csv")
                csv_files = glob.glob(csv_pattern, recursive=True)
                result_csv_path = csv_files[0] if csv_files else None
            
            if result_csv_path and os.path.exists(result_csv_path):
                try:
                    with open(result_csv_path, 'rb') as f:
                        csv_data = f.read()
                    
                    result_filename = os.path.basename(result_csv_path)
                    
                    st.download_button(
                        "📥 Download Results CSV",
                        data=csv_data,
                        file_name=result_filename,
                        mime='text/csv',
                        type="primary"
                    )
                    
                    file_size_kb = len(csv_data) / 1024
                    st.info(f"✅ CSV ready: {result_filename} ({file_size_kb:.1f} KB)")
                    
                    # Show session stats
                    session_status = processor.get_session_status()
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Brands", session_status.get('total_brands', 0))
                    with col2:
                        st.metric("Completed", session_status.get('completed_brands', 0))
                    with col3:
                        st.metric("Failed", session_status.get('failed_brands', 0))
                    
                except Exception as e:
                    st.error(f"❌ Error reading CSV file: {e}")
            else:
                st.warning("⚠️ CSV file not found.")
            
            # Reset button for new processing
            if st.button("🔄 Process New File", type="secondary"):
                if 'processor' in st.session_state:
                    del st.session_state.processor
                st.session_state.processing = False
                st.rerun()
            
            return  # Exit early, don't show normal processing UI
        
        # Start processing if not already started
        if not processor.is_processing() and st.session_state.processing:
            # Check if we have a completed status already
            status = processor.get_processing_status()
            if status.get('phase') == 'completed':
                # Processing already completed, don't restart
                st.session_state.processing = False
                st.rerun()
            else:
                # Save uploaded file content
                csv_content = uploaded_file.getvalue().decode('utf-8')
                
                # Start processing
                success = processor.start_processing(
                    csv_content=csv_content,
                    session_name=st.session_state.session_name,
                    api_key=api_key,
                    ai_provider=ai_provider,
                    resume_mode=st.session_state.get('resume_mode', False),
                    headless=headless_mode,
                    force_regenerate=force_regenerate
                )
                
                if not success:
                    st.error("Failed to start processing")
                    st.session_state.processing = False
        
        # Display real-time status
        if processor.is_processing():
            # Current status
            status = processor.get_processing_status()
            st.write("🐛 DEBUG: Processing active, status:", status)  # Debug line
            if status:
                
                col1, col2, col3 = st.columns([2, 1, 1])
                with col1:
                    if status.get('current_brand'):
                        st.info(f"🔄 Processing: **{status['current_brand']}** ({status.get('current_stage', 'unknown')})")
                    else:
                        st.info(f"🔄 Phase: {status.get('phase', 'unknown').title()}")
                
                with col2:
                    completed = status.get('completed_brands', 0)
                    total = status.get('total_brands', 1)
                    st.metric("Completed", f"{completed}/{total}")
                
                with col3:
                    progress_pct = status.get('progress', 0) * 100
                    st.metric("Progress", f"{progress_pct:.0f}%")
                
                # Progress bar
                overall_progress = completed / total if total > 0 else 0
                st.progress(overall_progress)
                
                # Last update time
                if status.get('last_update'):
                    st.caption(f"Last update: {status['last_update'][11:19]}")
            
            # Session status table (updated every few seconds)
            if processor.session_manager.current_session:
                session_status = processor.get_session_status()
                
                if session_status.get('brands'):
                    st.subheader("📊 Brand Progress Table")
                    display_progress_table(session_status['brands'])
                    
                    # Status summary
                    status_counts = session_status.get('status_counts', {})
                    if status_counts:
                        cols = st.columns(len(status_counts))
                        for i, (status, count) in enumerate(status_counts.items()):
                            with cols[i]:
                                st.metric(status.title(), count)
            
            # Auto-refresh only if still processing (non-blocking)
            if st.session_state.processing and processor.is_processing():
                # Add a small delay to prevent excessive CPU usage
                # But use a progress bar instead of blocking sleep
                progress_container = st.empty()
                with progress_container.container():
                    st.info("🔄 Processing in progress... Page will auto-update")
                
                # Trigger refresh without blocking
                st.rerun()
            elif st.session_state.processing and not processor.is_processing():
                # Processing finished, update state
                st.write("🐛 DEBUG: Thread finished, updating processing state to False")
                st.session_state.processing = False
                st.rerun()
            
        else:
            # Processing completed or stopped
            status = processor.get_processing_status()
            st.write("🐛 DEBUG: Not processing, status:", status)  # Debug line
            st.write("🐛 DEBUG: Session state processing:", st.session_state.processing)  # Debug line
            
            # Force show completion if processing should be done
            if not status and processor.session_manager.current_session:
                session_status = processor.get_session_status()
                if session_status.get('completed_at'):
                    st.success("✅ Processing completed (detected from session)!")
                    st.write("🐛 DEBUG: Forced completion detection")
                    
                    # Show download section even without proper status
                    st.subheader("📥 Download Results")
                    result_csv_path = processor.get_result_csv_path()
                    
                    if result_csv_path and os.path.exists(result_csv_path):
                        try:
                            with open(result_csv_path, 'rb') as f:
                                csv_data = f.read()
                            
                            result_filename = os.path.basename(result_csv_path)
                            
                            st.download_button(
                                "📥 Download Results CSV",
                                data=csv_data,
                                file_name=result_filename,
                                mime='text/csv',
                                type="primary"
                            )
                            
                            file_size_kb = len(csv_data) / 1024
                            st.info(f"✅ CSV ready: {result_filename} ({file_size_kb:.1f} KB)")
                            
                        except Exception as e:
                            st.error(f"❌ Error reading CSV file: {e}")
                    else:
                        st.warning("⚠️ CSV file not found. Check the processing logs.")
            
            # Fallback completion check - if processing stopped and session has completion timestamp
            if not processor.is_processing() and processor.session_manager.current_session:
                session_status = processor.get_session_status()
                if session_status.get('completed_at') and not status.get('phase') == 'completed':
                    st.write("🐛 DEBUG: Fallback completion detection triggered")
                    
                    st.success("✅ Processing completed successfully!")
                    
                    # Show final results
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("Total Brands", session_status.get('total_brands', 0))
                    with col2:
                        st.metric("Completed", session_status.get('completed_brands', 0))
                    with col3:
                        st.metric("Failed", session_status.get('failed_brands', 0))
                    
                    # Download results
                    st.subheader("📥 Download Results")
                    result_csv_path = processor.get_result_csv_path()
                    
                    if result_csv_path and os.path.exists(result_csv_path):
                        try:
                            with open(result_csv_path, 'rb') as f:
                                csv_data = f.read()
                            
                            result_filename = os.path.basename(result_csv_path)
                            
                            st.download_button(
                                "📥 Download Results CSV",
                                data=csv_data,
                                file_name=result_filename,
                                mime='text/csv',
                                type="primary"
                            )
                            
                            file_size_kb = len(csv_data) / 1024
                            st.info(f"✅ CSV ready: {result_filename} ({file_size_kb:.1f} KB)")
                            
                        except Exception as e:
                            st.error(f"❌ Error reading CSV file: {e}")
                    else:
                        st.warning("⚠️ CSV file not found. Check the processing logs.")
            
            # Ultimate fallback - just check if CSV exists and processing isn't active
            if not processor.is_processing():
                result_csv_path = processor.get_result_csv_path()
                st.write(f"🐛 DEBUG: Processing: {processor.is_processing()}, CSV Path: {result_csv_path}")
                st.write(f"🐛 DEBUG: Path exists: {os.path.exists(result_csv_path) if result_csv_path else 'No path'}")
                
                # Also check temp directory directly for any CSV files (including subdirectories)
                import glob
                temp_csv_pattern = os.path.join(processor.working_dir, "*_with_brand_data.csv")
                temp_csv_files = glob.glob(temp_csv_pattern)
                
                # Also search in session subdirectories  
                session_csv_pattern = os.path.join(processor.working_dir, "**", "*_with_brand_data.csv")
                session_csv_files = glob.glob(session_csv_pattern, recursive=True)
                
                st.write(f"🐛 DEBUG: Temp CSV pattern: {temp_csv_pattern}")
                st.write(f"🐛 DEBUG: Temp CSV files: {temp_csv_files}")
                st.write(f"🐛 DEBUG: Session CSV pattern: {session_csv_pattern}")
                st.write(f"🐛 DEBUG: Session CSV files: {session_csv_files}")
                
                # Combine all found CSV files
                all_csv_files = temp_csv_files + session_csv_files
                
                # Use either method to find CSV - prefer session manager, then any found CSV
                csv_file_to_use = result_csv_path if (result_csv_path and os.path.exists(result_csv_path)) else (all_csv_files[0] if all_csv_files else None)
                
                st.write(f"🐛 DEBUG: Selected CSV file: {csv_file_to_use}")
                
                if csv_file_to_use:
                    st.write("🐛 DEBUG: Ultimate fallback - CSV file found, showing download")
                    
                    st.subheader("📥 Download Results (File Detected)")
                    
                    try:
                        with open(csv_file_to_use, 'rb') as f:
                            csv_data = f.read()
                        
                        result_filename = os.path.basename(csv_file_to_use)
                        
                        st.download_button(
                            "📥 Download Results CSV",
                            data=csv_data,
                            file_name=result_filename,
                            mime='text/csv',
                            type="primary",
                            key="ultimate_fallback_download"  # Unique key to avoid conflicts
                        )
                        
                        file_size_kb = len(csv_data) / 1024
                        st.info(f"✅ CSV ready: {result_filename} ({file_size_kb:.1f} KB)")
                        
                    except Exception as e:
                        st.error(f"❌ Error reading CSV file: {e}")
            
            if status:
                # Debug: Show current status
                st.write(f"🐛 DEBUG: Current status - Phase: {status.get('phase')}, Processing: {processor.is_processing()}")
                st.write(f"🐛 DEBUG: Full status object: {status}")
                
                # Also check processor's internal status
                processor_status = processor.get_processing_status()
                st.write(f"🐛 DEBUG: Processor status: {processor_status}")
                
                if status.get('phase') == 'completed':
                    st.success("✅ Processing completed successfully!")
                    
                    # Show final results
                    if processor.session_manager.current_session:
                        session_status = processor.get_session_status()
                        
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Total Brands", session_status.get('total_brands', 0))
                        with col2:
                            st.metric("Completed", session_status.get('completed_brands', 0))
                        with col3:
                            st.metric("Failed", session_status.get('failed_brands', 0))
                        
                        # Final table
                        if session_status.get('brands'):
                            st.subheader("📊 Final Results")
                            display_progress_table(session_status['brands'])
                    
                    # Download results
                    st.subheader("📥 Download Results")
                    result_csv_path = processor.get_result_csv_path()
                    
                    if result_csv_path and os.path.exists(result_csv_path):
                        try:
                            with open(result_csv_path, 'rb') as f:
                                csv_data = f.read()
                            
                            # Get just the filename for download
                            result_filename = os.path.basename(result_csv_path)
                            
                            st.download_button(
                                "📥 Download Results CSV",
                                data=csv_data,
                                file_name=result_filename,
                                mime='text/csv',
                                type="primary"
                            )
                            
                            # Show file info
                            file_size_kb = len(csv_data) / 1024
                            st.info(f"✅ CSV ready: {result_filename} ({file_size_kb:.1f} KB)")
                            
                        except Exception as e:
                            st.error(f"❌ Error reading CSV file: {e}")
                    else:
                        st.warning("⚠️ CSV file not found. Check the processing logs.")
                    
                    # Reset button for new processing
                    if st.button("🔄 Process New File", type="secondary"):
                        # Reset all processing state
                        if 'processor' in st.session_state:
                            del st.session_state.processor
                        st.session_state.processing = False
                        st.rerun()
                    
                elif status.get('phase') == 'error':
                    st.error(f"❌ Processing error: {status.get('error', 'Unknown error')}")
                
            st.session_state.processing = False

if __name__ == "__main__":
    main()