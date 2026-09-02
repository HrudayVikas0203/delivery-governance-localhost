import sqlite3
import json

conn = sqlite3.connect("storage/delivery_governance.db")
cursor = conn.cursor()
cursor.execute("SELECT fields FROM weekly_statuses")
rows = cursor.fetchall()
for row in rows:
    data = json.loads(row[0])
    print(f"Risk: {data.get('risks')}")
    print(f"Next Steps: {data.get('nextWeekPlan')}")
    print("---")
