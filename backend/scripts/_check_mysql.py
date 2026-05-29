"""Check MySQL connectivity and figurines."""
import os
import sys
from pathlib import Path

# Load the .env that server.py actually uses
env_file = Path(__file__).parent.parent.parent / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(str(env_file), override=True)
    print(f".env loaded from: {env_file}")
else:
    print(f"No .env at {env_file}")

host = os.getenv("MYSQL_HOST", "localhost")
user = os.getenv("MYSQL_USER", "root")
password = os.getenv("MYSQL_PASSWORD", "")
database = os.getenv("MYSQL_DATABASE", "ZebbieDb")
port = int(os.getenv("MYSQL_PORT", 3306))

print(f"MySQL config: {user}@{host}:{port}/{database} (password={'***' if password else ''})")

import pymysql
try:
    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=database, charset="utf8mb4", connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute("SELECT FigurineId, Name FROM ZebFigurineInfo WHERE IsDelete = 0 ORDER BY CharacterName LIMIT 5")
    rows = cur.fetchall()
    print(f"OK - Found {len(rows)} figurines:")
    for r in rows:
        print(f"  {r[0]} = {r[1]}")
    cur.close()
    conn.close()
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
