import sqlite3

conn = sqlite3.connect("backend/storage/delivery_governance.db")
cursor = conn.cursor()
cursor.execute("SELECT fields FROM weekly_statuses")
for row in cursor.fetchall():
    print(row[0])
