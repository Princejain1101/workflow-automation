#!/usr/bin/env python3
"""
Launch script for simple SmartScout Streamlit app
"""

import subprocess
import sys
import os

def main():
    # Get the directory of this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    app_file = os.path.join(script_dir, "smartscout_simple_app.py")
    
    print("🚀 Launching SmartScout Simple App...")
    print("📱 The app will open in your browser automatically")
    print("🔗 Manual URL: http://localhost:8501")
    print("⏹️  Press Ctrl+C to stop")
    
    # Launch streamlit
    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", 
            app_file,
            "--server.port=8501",
            "--server.headless=false"
        ], check=True)
    except KeyboardInterrupt:
        print("\n👋 App stopped by user")
    except Exception as e:
        print(f"❌ Error launching app: {e}")

if __name__ == "__main__":
    main()