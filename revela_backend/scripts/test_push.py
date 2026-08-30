"""
Test and diagnostic script for FCM Push Notifications.
Run with: python scripts/test_push.py [inspector_id_or_email]
"""
import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app, mysql
from api.models.user import get_fcm_token
from api.notifications.fcm import send_inspection_dispatch_push, _messaging_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

app = create_app()

with app.app_context():
    print("=" * 60)
    print("REVELA FCM PUSH NOTIFICATION DIAGNOSTIC TOOL")
    print("=" * 60)

    # 1. Check Firebase Admin SDK Credentials
    print("\n[STEP 1] Checking Firebase Admin SDK credentials...")
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    sa_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()

    if sa_json:
        print("  ✓ FIREBASE_SERVICE_ACCOUNT_JSON environment variable is set.")
    elif sa_path:
        print(f"  ✓ FIREBASE_SERVICE_ACCOUNT_PATH: {sa_path}")
        if os.path.isfile(sa_path):
            print("    ✓ Service account file exists.")
        else:
            print("    ✗ ERROR: Service account file not found at this path!")
    else:
        import glob
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        keys = glob.glob(os.path.join(backend_dir, "*firebase-adminsdk*.json"))
        if keys:
            print(f"  ✓ Found local key file: {os.path.basename(keys[0])}")
        else:
            print("  ✗ ERROR: No Firebase service account key found!")
            print("    Please set FIREBASE_SERVICE_ACCOUNT_PATH, FIREBASE_SERVICE_ACCOUNT_JSON, or place a *firebase-adminsdk*.json file in revela_backend/.")

    messaging = _messaging_client()
    if messaging is None:
        print("  ✗ Firebase Messaging client could NOT be initialized.\n")
    else:
        print("  ✓ Firebase Messaging client initialized successfully!")

    # 2. Check Database for Inspectors and Tokens
    print("\n[STEP 2] Checking Inspector FCM tokens in database...")
    cur = mysql.connection.cursor()
    cur.execute("SELECT userID, fullName, email, userRole, fcm_token FROM users WHERE userRole = 'Inspector' OR userRole LIKE '%Inspector%'")
    inspectors = cur.fetchall() or []
    cur.close()

    if not inspectors:
        print("  No inspector accounts found in database.")
    else:
        print(f"  Found {len(inspectors)} inspector account(s):")
        for ins in inspectors:
            token = ins.get("fcm_token")
            token_preview = f"{token[:25]}...{token[-10:]}" if token else "None (NO TOKEN SAVED)"
            print(f"    - ID: {ins['userID']} | {ins['fullName']} ({ins['email']})")
            print(f"      FCM Token: {token_preview}")

    # 3. Test sending a push if requested
    target = sys.argv[1] if len(sys.argv) > 1 else None
    if target:
        print(f"\n[STEP 3] Sending test push notification to target: {target}...")
        cur = mysql.connection.cursor()
        if target.isdigit():
            cur.execute("SELECT userID, fullName, email, fcm_token FROM users WHERE userID = %s", (int(target),))
        else:
            cur.execute("SELECT userID, fullName, email, fcm_token FROM users WHERE email = %s", (target,))
        user = cur.fetchone()
        cur.close()

        if not user:
            print(f"  ✗ User not found: {target}")
        elif not user.get("fcm_token"):
            print(f"  ✗ User {user['fullName']} (ID {user['userID']}) has NO saved FCM token in database.")
            print("    Make sure the inspector has opened the mobile app and logged in.")
        else:
            print(f"  Sending test push to {user['fullName']} (ID: {user['userID']})...")
            success = send_inspection_dispatch_push(
                report_id=99999,
                inspector_user_id=user["userID"],
                business_name="TEST Business Inspection Alert"
            )
            if success:
                print("  ✓ Test push notification sent successfully!")
            else:
                print("  ✗ Failed to send push notification. Check logs above for details.")
    else:
        print("\nTip: To send a test push to a specific inspector, run:")
        print("  python scripts/test_push.py <inspector_id_or_email>")
    print("\n" + "=" * 60)
