#!/usr/bin/env python3
"""
Simple Streamlit UI that mirrors the terminal session manager exactly
No complex session management, just like running the CLI tool
"""

import streamlit as st
import os
import tempfile
from pathlib import Path
import threading
import time
from datetime import datetime
import pandas as pd

def check_smartscout_auth():
    """Check if SmartScout is authenticated using same method as session manager"""
    try:
        from playwright.sync_api import sync_playwright
        import tempfile
        
        USER_DATA_DIR = "./playwright_user_data"
        SMARTSCOUT_URL = "https://app.smartscout.com/app/tailored-report"
        
        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(
                    USER_DATA_DIR, 
                    headless=True,
                    timeout=15000
                )
                page = context.new_page()
                page.goto(SMARTSCOUT_URL, timeout=15000)
                page.wait_for_load_state("domcontentloaded", timeout=10000)
                
                current_url = page.url
                context.close()
                
                # Check if we reached the tailored-report page (authenticated)
                return "tailored-report" in current_url
                
            except Exception as e:
                try:
                    context.close()
                except:
                    pass
                return False
                
    except Exception as e:
        print(f"Auth check error: {e}")
        return False

def open_smartscout_login():
    """Open SmartScout login page in browser for user authentication"""
    try:
        from playwright.sync_api import sync_playwright
        
        USER_DATA_DIR = "./playwright_user_data"
        LOGIN_URL = "https://app.smartscout.com/sessions/signin"
        
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                USER_DATA_DIR, 
                headless=False,  # Show browser for login
                slow_mo=500
            )
            page = context.new_page()
            page.goto(LOGIN_URL)
            
            st.info("🌐 Browser opened for SmartScout login. Please log in and then close the browser window.")
            
            # Keep the browser open until user closes it
            # We don't need to wait - user will check status manually
            
    except Exception as e:
        st.error(f"❌ Error opening browser: {e}")

def display_session_table(session_manager):
    """Display session progress table like terminal version"""
    if not session_manager.current_session:
        st.warning("No active session")
        return
    
    session = session_manager.current_session
    
    # Create table data
    rows = []
    for name, state in session.brands.items():
        # Handle both enum and string status values
        status = state.status.value if hasattr(state.status, 'value') else state.status
        
        # Status emoji mapping
        status_emoji = {
            'pending': '⏳',
            'collecting': '🔄',
            'no_brand_found': '❌',
            'collected': '📊',
            'analyzing': '⏳', 
            'analyzed': '✅',
            'downloading': '📥',
            'downloaded': '📄',
            'summarizing': '🤖',
            'summarized': '✅',
            'failed': '❌'
        }
        
        rows.append({
            'Brand': name,
            'Status': f"{status_emoji.get(status, '❓')} {status.title().replace('_', ' ')}",
            'Collect': '✅' if state.attempts.get('collect', 0) > 0 else '⏳',
            'Download': '✅' if state.attempts.get('download', 0) > 0 else '⏳', 
            'Summary': '✅' if state.attempts.get('summarize', 0) > 0 else '⏳',
            'Last Update': state.last_attempt.get('summarize', 
                          state.last_attempt.get('download', 
                          state.last_attempt.get('collect', 'Never')))[:10] if state.last_attempt else 'Never'
        })
    
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
        
        # Summary stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total", len(rows))
        with col2:
            completed = sum(1 for row in rows if 'summarized' in row['Status'].lower())
            st.metric("Completed", completed)
        with col3:
            failed = sum(1 for row in rows if 'failed' in row['Status'].lower() or 'not found' in row['Status'].lower())
            st.metric("Failed", failed)
        with col4:
            in_progress = len(rows) - completed - failed
            st.metric("In Progress", in_progress)
    else:
        st.info("No brands in session yet")

def main():
    st.title("🎯 SmartScout Brand Analyzer")
    st.markdown("Simple interface - works exactly like the terminal version")
    st.markdown("---")
    
    # Configuration Section
    st.header("📋 Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Session Name
        session_name = st.text_input(
            "Session Name",
            value="",
            placeholder="my-brands-batch",
            help="Unique name for this processing session (like --session-name in terminal)"
        )
        
        # AI Provider
        ai_provider = st.selectbox(
            "AI Provider",
            ["gemini", "anthropic"],
            help="Choose your AI provider (like --model-provider in terminal)"
        )
    
    with col2:
        # API Key
        if ai_provider == "gemini":
            api_key = st.text_input(
                "Gemini API Key",
                type="password",
                help="Set this as GEMINI_API_KEY environment variable"
            )
        else:
            api_key = st.text_input(
                "Anthropic API Key",
                type="password", 
                help="Set this as ANTHROPIC_API_KEY environment variable"
            )
        
        # Options
        headless = st.checkbox("Headless Mode", value=True, help="Run browser in background")
        force_regenerate = st.checkbox("Force Regenerate", value=False, help="Overwrite existing files")

    # File Upload Section
    st.header("📁 Input")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        uploaded_file = st.file_uploader(
            "Choose CSV file",
            type=['csv'],
            help="CSV file with brand names (like passing CSV path in terminal)"
        )
    
    with col2:
        # Resume option
        resume_mode = st.checkbox(
            "Resume Session", 
            value=False,
            help="Resume existing session with same name (like --resume in terminal)"
        )

    # SmartScout Authentication Check
    st.header("🔐 SmartScout Authentication")
    
    # Check authentication status
    auth_status = check_smartscout_auth()
    
    if auth_status:
        st.success("✅ SmartScout session active")
    else:
        st.warning("⚠️ SmartScout authentication needed")
        st.markdown("""
        **First time setup:**
        1. Click the button below to open SmartScout login
        2. Log into your SmartScout account in the browser window
        3. Come back here and check authentication status
        """)
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🌐 Open SmartScout Login", type="secondary"):
                open_smartscout_login()
        with col2:
            if st.button("🔄 Check Auth Status", type="secondary"):
                st.rerun()
    
    # Validation and Start
    st.markdown("---")
    
    can_start = all([
        session_name.strip(),
        api_key.strip(),
        uploaded_file is not None or resume_mode,
        auth_status  # Add auth requirement
    ])
    
    if not can_start:
        if not session_name.strip():
            st.warning("⚠️ Please enter a session name")
        if not api_key.strip():
            st.warning("⚠️ Please enter your API key")
        if not uploaded_file and not resume_mode:
            st.warning("⚠️ Please upload a CSV file or enable resume mode")
        if not auth_status:
            st.warning("⚠️ Please authenticate with SmartScout first")
    
    # Processing Section
    if can_start:
        st.header("🚀 Execute")
        
        # Initialize session state for this execution
        if 'processor_started' not in st.session_state:
            st.session_state.processor_started = False
        if 'processor_thread' not in st.session_state:
            st.session_state.processor_thread = None
        
        # Start button
        if not st.session_state.processor_started:
            if st.button("▶️ Start Processing", type="primary", use_container_width=True):
                # Set environment variable
                if ai_provider == "gemini":
                    os.environ['GEMINI_API_KEY'] = api_key
                else:
                    os.environ['ANTHROPIC_API_KEY'] = api_key
                
                # Save CSV to temp file if uploaded
                csv_path = None
                if uploaded_file:
                    temp_dir = tempfile.mkdtemp()
                    csv_path = os.path.join(temp_dir, f"{session_name}.csv")
                    with open(csv_path, 'wb') as f:
                        f.write(uploaded_file.read())
                
                # Start processing in background thread
                st.session_state.processor_thread = threading.Thread(
                    target=run_session_manager,
                    args=(session_name, csv_path, ai_provider, headless, force_regenerate, resume_mode)
                )
                st.session_state.processor_thread.start()
                st.session_state.processor_started = True
                st.rerun()
        
        # Processing status
        if st.session_state.processor_started:
            st.subheader("🔄 Processing Status")
            
            # Check if thread is still running
            is_running = (st.session_state.processor_thread and 
                         st.session_state.processor_thread.is_alive())
            
            if is_running:
                st.info("⏳ Processing in progress... Check terminal for detailed logs.")
                
                # Try to show progress table if session exists
                try:
                    from smartscout_session_manager import SessionManager
                    working_dir = os.path.join(tempfile.gettempdir(), "smartscout_sessions")
                    session_manager = SessionManager(working_dir)
                    
                    # Try to load current session to show progress
                    if session_manager.load_session(session_name):
                        st.subheader("📊 Progress Table")
                        display_session_table(session_manager)
                except:
                    pass  # Don't break if we can't load session
                
                # Auto-refresh every 5 seconds while processing
                time.sleep(2)  # Small delay to avoid too frequent refreshes
                st.rerun()
                
            else:
                st.success("✅ Processing completed! Check terminal for results.")
                
                # Look for result CSV
                working_dir = Path(tempfile.gettempdir()) / "smartscout_sessions"
                if working_dir.exists():
                    import glob
                    csv_pattern = str(working_dir / "**" / "*_with_brand_data.csv")
                    csv_files = glob.glob(csv_pattern, recursive=True)
                    
                    if csv_files:
                        # Find the most recent CSV file
                        latest_csv = max(csv_files, key=os.path.getctime)
                        
                        st.subheader("📥 Download Results")
                        
                        try:
                            with open(latest_csv, 'rb') as f:
                                csv_data = f.read()
                            
                            filename = os.path.basename(latest_csv)
                            file_size_kb = len(csv_data) / 1024
                            
                            st.download_button(
                                "📥 Download Results CSV",
                                data=csv_data,
                                file_name=filename,
                                mime='text/csv',
                                type="primary",
                                use_container_width=True
                            )
                            
                            st.info(f"✅ File ready: {filename} ({file_size_kb:.1f} KB)")
                            
                        except Exception as e:
                            st.error(f"❌ Error reading result file: {e}")
                    else:
                        st.warning("⚠️ No result CSV found. Check terminal for errors.")
                
                # Restart button
                if st.button("🔄 Process New File", type="secondary"):
                    # Clear session state to start fresh
                    st.session_state.processor_started = False
                    st.session_state.processor_thread = None
                    st.rerun()


def run_session_manager(session_name, csv_path, ai_provider, headless, force_regenerate, resume_mode):
    """Run the session manager in background thread"""
    try:
        from smartscout_session_manager import SessionManager
        
        # Initialize session manager
        working_dir = os.path.join(tempfile.gettempdir(), "smartscout_sessions")
        session_manager = SessionManager(working_dir)
        
        if resume_mode:
            # Resume existing session
            print(f"🔄 Resuming session: {session_name}")
            success = session_manager.load_session(session_name)
            if not success:
                print(f"❌ Could not load session: {session_name}")
                return
        else:
            # Create new session
            print(f"🚀 Starting new session: {session_name}")
            session_id = session_manager.create_session(
                session_name=session_name,
                brands_source=csv_path,
                headless=headless,
                model_provider=ai_provider,
                force_regenerate=force_regenerate
            )
            print(f"📁 Session created: {session_id}")
        
        # Run the session
        session_manager.run_session()
        print(f"✅ Session completed: {session_name}")
        
    except Exception as e:
        print(f"❌ Session error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()