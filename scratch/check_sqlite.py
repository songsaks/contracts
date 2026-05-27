import sqlite3
import os

db_path = 'd:/projects/contracts/db.sqlite3'
if not os.path.exists(db_path):
    print(f"No sqlite database found at {db_path}")
    sys.exit()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cursor.fetchall()]
print("Tables in SQLite database:")
for t in sorted(tables):
    if 'portfolio' in t or 'briefing' in t or 'user' in t:
        print(f"- {t}")

# Check portfolios
if 'stocks_portfolio' in tables:
    cursor.execute("SELECT COUNT(*) FROM stocks_portfolio;")
    print(f"\nRow count in SQLite stocks_portfolio: {cursor.fetchone()[0]}")
    cursor.execute("SELECT * FROM stocks_portfolio LIMIT 5;")
    print("Sample rows:")
    for row in cursor.fetchall():
        print(row)
else:
    print("\nNo stocks_portfolio table in SQLite.")
    
# Check morning briefings
if 'stocks_morningbriefing' in tables:
    cursor.execute("SELECT COUNT(*) FROM stocks_morningbriefing;")
    print(f"Row count in SQLite stocks_morningbriefing: {cursor.fetchone()[0]}")
    cursor.execute("SELECT id, created_at, report_md FROM stocks_morningbriefing LIMIT 2;")
    for row in cursor.fetchall():
        print(row[0], row[1], row[2][:100] if row[2] else 'None')
else:
    print("No stocks_morningbriefing table in SQLite.")
    
conn.close()
