import os
import glob

def cleanup_server():
    print("--- Starting Server Cleanup Routine ---")
    
    # List of patterns to clean up (test files, logs, temp scripts)
    patterns = [
        "test_*.py", 
        "fix_*.py", 
        "seed_*.py", 
        "list_*.py", 
        "debug_*.py", 
        "init_*.py",
        "check_template.py",
        "cleanup_duplicates.py",
        "cleanup_queue.py",
        "update_repair_type_colors.py",
        "update_server_workflow.py",
        "*_log.txt", 
        "*.log", 
        "contracts.session.sql",
        "datadump.json", 
        "news_debug.json", 
        "news_sabina.json",
        "models_list.txt", 
        "test_out.txt", 
        "grep.log",
        "urls_log.txt"
    ]
    
    # CRITICAL: Files to protect from deletion
    protected = ["requirements.txt", "README.md", "manage.py", ".env", "db.sqlite3"]

    removed = 0
    for pattern in patterns:
        for file_path in glob.glob(pattern):
            filename = os.path.basename(file_path)
            
            if filename in protected:
                print(f"Skipping protected file: {filename}")
                continue
            
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    print(f"Removed: {filename}")
                    removed += 1
            except Exception as e:
                print(f"Failed to remove {filename}: {e}")

    print(f"\nSummary: Total {removed} temporary files removed safely.")

if __name__ == "__main__":
    cleanup_server()
