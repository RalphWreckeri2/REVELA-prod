import io
import sys
import os

# Add parent directory to path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, mysql
from api.registry.service import upload_registry, sync_registry

def run_test():
    app = create_app()
    app.config['MYSQL_USER'] = 'revela_user'
    app.config['MYSQL_PASSWORD'] = 'dalkoman1-9'
    app.config['MYSQL_DB'] = 'revela_db'
    with app.app_context():
        # First, clear the table to ensure a clean test
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM official_registry")
        mysql.connection.commit()
        cur.close()

        print("--- Test 1: Uploading a file with 3 IDENTICAL businesses (same Business ID) ---")
        csv_content = """Business ID,businessName,barangay,businessAddress
B-001,Alfamart,Lumanglipa,123 Main St
B-001,Alfamart,Lumanglipa,123 Main St
B-001,Alfamart,Lumanglipa,123 Main St
""".encode('utf-8')
        file1 = io.BytesIO(csv_content)
        summary, err = upload_registry(file1, ".csv")
        print(f"Result: {summary['inserted']} inserted, {summary['skipped']} skipped, {summary['updated'] if 'updated' in summary else 0} updated.")
        
        print("\n--- Test 2: Uploading the EXACT same file again (Simulating accidental re-upload) ---")
        file2 = io.BytesIO(csv_content)
        summary, err = upload_registry(file2, ".csv")
        print(f"Result: {summary['inserted']} inserted, {summary['skipped']} skipped, {summary['updated'] if 'updated' in summary else 0} updated.")
        
        print("\n--- Test 3: Auto-Syncing a file with 4 businesses (3 identical old branches, 1 new branch) ---")
        csv_content_sync = """Business ID,businessName,barangay,businessAddress
B-001,Alfamart,Lumanglipa,123 Main St
B-001,Alfamart,Lumanglipa,123 Main St
B-001,Alfamart,Lumanglipa,123 Main St
B-002,Alfamart,Lumanglipa,New Branch Address
""".encode('utf-8')
        file3 = io.BytesIO(csv_content_sync)
        summary, err = sync_registry(file3, ".csv")
        print(f"Result: {summary['inserted']} inserted, {summary['skipped']} skipped, {summary['updated']} updated.")

        # Cleanup
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM official_registry")
        mysql.connection.commit()
        cur.close()

if __name__ == "__main__":
    run_test()
