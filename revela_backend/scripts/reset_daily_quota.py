"""
Script to immediately reset the daily geocoding quota counters in the database.
Run with: python scripts/reset_daily_quota.py
"""
import sys
import os

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app, mysql
from api.registry.service import reset_geocode_daily_quota, get_geocode_remaining_today, get_geocode_remaining_month

app = create_app()

with app.app_context():
    print("Previous remaining count today:", get_geocode_remaining_today())
    reset_geocode_daily_quota()
    print("Reset successfully completed!")
    print("New remaining count today:", get_geocode_remaining_today())
