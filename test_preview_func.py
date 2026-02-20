
import sys
import os

# Add current directory to path
sys.path.append(os.getcwd())

try:
    print("Importing app...")
    from app import get_next_application_number_preview
    print("Application imported successfully.")
    
    print("Calling get_next_application_number_preview...")
    result = get_next_application_number_preview()
    print(f"Result: '{result}'")
    
except ImportError as e:
    print(f"Import Error: {e}")
except Exception as e:
    print(f"Runtime Error: {e}")
