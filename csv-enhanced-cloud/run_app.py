#!/usr/bin/env python3
"""
Launch script for SmartScout Brand Analyzer
"""

import subprocess
import sys
import os
from pathlib import Path

def main():
    """Launch the Streamlit application"""
    
    # Get the directory where this script is located
    app_dir = Path(__file__).parent
    
    # Change to the app directory
    os.chdir(app_dir)
    
    # Launch Streamlit
    try:
        cmd = [
            sys.executable, 
            "-m", "streamlit", "run", 
            "smartscout_streamlit_app.py",
            "--server.headless", "false",
            "--server.port", "8501",
            "--browser.gatherUsageStats", "false"
        ]
        
        print("🚀 Launching SmartScout Brand Analyzer...")
        print("📱 The app will open in your browser automatically")
        print("🔗 If it doesn't open, go to: http://localhost:8501")
        print("⏹️  Press Ctrl+C to stop the application")
        print("-" * 50)
        
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\n👋 SmartScout Brand Analyzer stopped")
    except Exception as e:
        print(f"❌ Error launching app: {e}")
        print("Make sure you have installed the requirements:")
        print("pip install -r requirements.txt")

if __name__ == "__main__":
    main()