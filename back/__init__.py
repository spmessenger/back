from pathlib import Path
import sys


_db_project_root = Path(__file__).resolve().parents[2] / 'db'
if _db_project_root.exists():
    db_path = str(_db_project_root)
    if db_path not in sys.path:
        sys.path.insert(0, db_path)
