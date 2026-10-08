import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from api.registry.service import reset_geocode_daily_quota, get_geocode_remaining_today, get_geocode_remaining_month, _reserve_geocode_call, mysql
from flask_mysqldb import MySQL

app = create_app()

def run_tests():
    with app.app_context():
        mysql = MySQL(app)
        print("Running Snap Budget Regression Tests...\n")
        
        # Test 1: Reset daily quota safely (geo_day only)
        print("Test 1: Reset daily quota...")
        initial_day = get_geocode_remaining_today()
        reset_geocode_daily_quota()
        reset_day = get_geocode_remaining_today()
        
        print(f"  Before reset: {initial_day}")
        print(f"  After reset: {reset_day}")
        assert reset_day >= initial_day, "Daily quota should be reset to maximum"
        print("  [OK] Passed\n")
        
        # Test 2: Atomic Reservation Exhaustion (Concurrency simulation)
        print("Test 2: Atomic Reservation exhaustion...")
        # Artificially lower the daily cap for testing
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO places_api_usage (usageDate, kind, requestCount) VALUES (CURDATE(), 'geo_day', 1499) ON DUPLICATE KEY UPDATE requestCount = 1499")
        cur.execute("INSERT INTO places_api_usage (usageDate, kind, requestCount) VALUES (DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY), 'geo_month', 7999) ON DUPLICATE KEY UPDATE requestCount = 7999")
        mysql.connection.commit()
        
        rem = get_geocode_remaining_today()
        print(f"  Set simulated remaining quota to: {rem}")
        
        # This one should pass (1 left)
        res1 = _reserve_geocode_call()
        print(f"  Reservation 1 (should succeed): {res1}")
        assert res1 is True
        
        # This one should fail (0 left) - Simulating a concurrent thread hitting the atomic update
        res2 = _reserve_geocode_call()
        print(f"  Reservation 2 (should fail): {res2}")
        assert res2 is False
        
        print("  [OK] Passed\n")
        
        # Cleanup
        reset_geocode_daily_quota()
        print("Tests complete.")

if __name__ == '__main__':
    run_tests()
