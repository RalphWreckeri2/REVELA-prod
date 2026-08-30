"""Firebase Cloud Messaging delivery for inspector inspection assignments."""
import logging
import os

from api.models.user import get_fcm_token

logger = logging.getLogger(__name__)


def _messaging_client():
    """Initialise Firebase Admin once from the configured service-account credentials."""
    try:
        import glob
        import json
        import firebase_admin
        from firebase_admin import credentials, messaging
    except ImportError:
        logger.error("[FCM DISPATCH ERROR: firebase-admin is not installed]")
        return None

    if not firebase_admin._apps:
        cred = None
        # 1. Direct JSON string in environment variable (ideal for cloud/docker)
        service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        if service_account_json:
            try:
                cert_dict = json.loads(service_account_json)
                if isinstance(cert_dict, dict) and "private_key" in cert_dict:
                    if isinstance(cert_dict["private_key"], str):
                        cert_dict["private_key"] = cert_dict["private_key"].replace("\\n", "\n")
                cred = credentials.Certificate(cert_dict)
                logger.info(
                    "[FCM DISPATCH] Initialized Firebase Admin from FIREBASE_SERVICE_ACCOUNT_JSON for project=%s (client=%s)",
                    cert_dict.get("project_id"),
                    cert_dict.get("client_email"),
                )
            except Exception as exc:
                logger.error("[FCM DISPATCH ERROR: Invalid FIREBASE_SERVICE_ACCOUNT_JSON: %s]", exc)

        # 2. File path configured via environment variable
        if cred is None:
            service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "").strip()
            if service_account_path and os.path.isfile(service_account_path):
                try:
                    cred = credentials.Certificate(service_account_path)
                except Exception as exc:
                    logger.error("[FCM DISPATCH ERROR: Failed loading service account from %s: %s]", service_account_path, exc)

        # 3. Local fallback discovery for development
        if cred is None:
            backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            candidates = glob.glob(os.path.join(backend_dir, "*firebase-adminsdk*.json"))
            if candidates:
                try:
                    cred = credentials.Certificate(candidates[0])
                    logger.info("[FCM DISPATCH] Initialized Firebase Admin from local key: %s", os.path.basename(candidates[0]))
                except Exception as exc:
                    logger.error("[FCM DISPATCH ERROR: Failed loading discovered key %s: %s]", candidates[0], exc)

        if cred is None:
            logger.error("[FCM DISPATCH ERROR: No valid Firebase service account found. Configure FIREBASE_SERVICE_ACCOUNT_PATH or FIREBASE_SERVICE_ACCOUNT_JSON.]")
            return None

        try:
            firebase_admin.initialize_app(cred)
        except Exception as exc:
            logger.exception("[FCM DISPATCH ERROR: Firebase Admin initialization error: %s]", exc)
            return None

    return messaging


def send_inspection_dispatch_push(report_id, inspector_user_id, business_name):
    """Send a visible, high-priority FCM alert to an assigned inspector."""
    inspector_fcm_token = get_fcm_token(inspector_user_id)
    if not inspector_fcm_token:
        logger.error(
            "[FCM DISPATCH ERROR: inspector %s has no saved fcm_token for report %s]",
            inspector_user_id,
            report_id,
        )
        return False

    messaging = _messaging_client()
    if messaging is None:
        return False

    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title="New Inspection Assigned",
                body=f"Task dispatched for {business_name}",
            ),
            data={
                "click_action": "FLUTTER_NOTIFICATION_CLICK",
                "type": "dispatch",
                "report_id": str(report_id),
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="revela_inspection_alerts",
                    priority="high",
                    visibility="public",
                    default_sound=True,
                    default_vibrate_timings=True,
                ),
            ),
            token=inspector_fcm_token,
        )
        message_id = messaging.send(message)
        logger.info(
            "[FCM DISPATCH SENT] report_id=%s inspector_id=%s message_id=%s",
            report_id,
            inspector_user_id,
            message_id,
        )
        return True
    except Exception as exc:
        logger.exception(
            "[FCM DISPATCH ERROR: report_id=%s inspector_id=%s details=%s]",
            report_id,
            inspector_user_id,
            exc,
        )
        return False
