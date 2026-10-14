import os
import socket
import unittest
from unittest.mock import MagicMock, patch

from config import Config


QA_SETTINGS = {
    "REVELA_QA_MODE": "1",
    "REVELA_QA_DB_HOST": "127.0.0.1",
    "REVELA_QA_DB_PORT": "3306",
    "REVELA_QA_DB_NAME": "revela_test_mobile_phase72",
    "REVELA_QA_DB_USER": "revela_mobile_qa",
    "REVELA_QA_DB_PASSWORD": "synthetic-qa-db-password",
}


class QaDatabaseConfigurationTests(unittest.TestCase):
    def test_qa_mode_is_disabled_by_default(self):
        settings = Config.resolve_database_settings({})

        self.assertFalse(settings["REVELA_QA_MODE"])
        self.assertEqual(settings["MYSQL_DB"], Config.MYSQL_DB)
        self.assertEqual(settings["MYSQL_HOST"], Config.MYSQL_HOST)

    def test_qa_mode_requires_an_explicit_boolean_value(self):
        with self.assertRaisesRegex(RuntimeError, "exactly 1 or 0"):
            Config.resolve_database_settings({"REVELA_QA_MODE": "true"})

    def test_qa_requires_all_explicit_database_settings(self):
        for missing in (
            "REVELA_QA_DB_HOST",
            "REVELA_QA_DB_PORT",
            "REVELA_QA_DB_NAME",
            "REVELA_QA_DB_USER",
            "REVELA_QA_DB_PASSWORD",
        ):
            with self.subTest(missing=missing):
                environment = dict(QA_SETTINGS)
                del environment[missing]
                with self.assertRaisesRegex(RuntimeError, "requires"):
                    Config.resolve_database_settings(environment)

    def test_qa_rejects_regular_and_unexpected_database_names(self):
        for name in ("revela_db", "revela_test_other"):
            with self.subTest(name=name):
                environment = dict(QA_SETTINGS, REVELA_QA_DB_NAME=name)
                with self.assertRaisesRegex(RuntimeError, "permits only"):
                    Config.resolve_database_settings(environment)

    def test_qa_rejects_non_loopback_hosts_and_unresolvable_aliases(self):
        for host in ("192.0.2.10", "db.internal", "0.0.0.0"):
            with self.subTest(host=host):
                environment = dict(QA_SETTINGS, REVELA_QA_DB_HOST=host)
                with self.assertRaises(RuntimeError):
                    Config.resolve_database_settings(environment)

    def test_qa_requires_a_dedicated_qa_named_database_user(self):
        for username in ("root", "revela_user", "revela_mobile"):
            with self.subTest(username=username):
                environment = dict(QA_SETTINGS, REVELA_QA_DB_USER=username)
                with self.assertRaisesRegex(RuntimeError, "ending in '_qa'"):
                    Config.resolve_database_settings(environment)

    def test_localhost_must_resolve_only_to_loopback_addresses(self):
        with patch("config.socket.getaddrinfo") as resolve:
            resolve.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 3306))
            ]
            environment = dict(QA_SETTINGS, REVELA_QA_DB_HOST="localhost")
            self.assertTrue(
                Config.resolve_database_settings(environment)["REVELA_QA_MODE"]
            )

        with patch("config.socket.getaddrinfo") as resolve:
            resolve.return_value = [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 3306)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.8", 3306)),
            ]
            environment = dict(QA_SETTINGS, REVELA_QA_DB_HOST="localhost")
            with self.assertRaisesRegex(RuntimeError, "exclusively"):
                Config.resolve_database_settings(environment)

    def test_qa_rejects_unsafe_inherited_connector_aliases(self):
        unsafe_aliases = (
            {"MYSQLHOST": "db.railway.internal"},
            {"DB_HOST": "203.0.113.20"},
            {"MYSQLDATABASE": "revela_db"},
            {"DB_NAME": "revela_db"},
            {"MYSQLUSER": "revela_user"},
            {"DB_PASSWORD": "different-secret"},
            {"MYSQLPASSWORD": "different-secret"},
            {"DB_PORT": "3307"},
        )
        for alias in unsafe_aliases:
            with self.subTest(alias=tuple(alias)):
                with self.assertRaises(RuntimeError) as raised:
                    Config.resolve_database_settings(dict(QA_SETTINGS, **alias))
                self.assertNotIn("synthetic-qa-db-password", str(raised.exception))

    def test_qa_accepts_only_the_explicit_local_test_identity(self):
        settings = Config.resolve_database_settings(dict(QA_SETTINGS))

        self.assertEqual(
            settings,
            {
                "REVELA_QA_MODE": True,
                "MYSQL_HOST": "127.0.0.1",
                "MYSQL_PORT": 3306,
                "MYSQL_DB": "revela_test_mobile_phase72",
                "MYSQL_USER": "revela_mobile_qa",
                "MYSQL_PASSWORD": "synthetic-qa-db-password",
            },
        )

    def test_inherited_matching_aliases_do_not_override_explicit_qa_values(self):
        environment = dict(
            QA_SETTINGS,
            DB_HOST="127.0.0.1",
            MYSQLHOST="127.0.0.1",
            DB_PORT="3306",
            MYSQLPORT="3306",
            DB_NAME="revela_test_mobile_phase72",
            MYSQLDATABASE="revela_test_mobile_phase72",
            DB_USER="revela_mobile_qa",
            MYSQLUSER="revela_mobile_qa",
            DB_PASSWORD="synthetic-qa-db-password",
            MYSQLPASSWORD="synthetic-qa-db-password",
        )
        settings = Config.resolve_database_settings(environment)
        self.assertEqual(settings["MYSQL_DB"], "revela_test_mobile_phase72")


class QaAppStartupTests(unittest.TestCase):
    def test_invalid_qa_settings_fail_before_database_extension_initialization(self):
        import app as app_module

        with patch.dict(os.environ, {"REVELA_QA_MODE": "1"}, clear=True):
            with patch.object(app_module.mysql, "init_app") as init_mysql:
                with self.assertRaisesRegex(RuntimeError, "requires"):
                    app_module.create_app()
        init_mysql.assert_not_called()

    def test_valid_qa_app_does_not_start_scheduler(self):
        import app as app_module

        with patch.dict(os.environ, QA_SETTINGS, clear=True):
            with self.assertLogs("app", level="INFO") as captured:
                with (
                    patch.object(app_module.Config, "JWT_SECRET_KEY", "synthetic-jwt"),
                    patch.object(app_module.mysql, "init_app"),
                    patch.object(app_module.jwt, "init_app"),
                    patch.object(app_module, "_start_permit_expiry_scheduler") as start_scheduler,
                    patch.object(
                        app_module.cors_config,
                        "build_allowed_origins",
                        wraps=app_module.cors_config.build_allowed_origins,
                    ) as build_origins,
                ):
                    app = app_module.create_app()

        self.assertTrue(app.config["REVELA_QA_MODE"])
        self.assertEqual(app.config["MYSQL_DB"], "revela_test_mobile_phase72")
        start_scheduler.assert_not_called()
        build_origins.assert_not_called()
        self.assertNotIn(
            QA_SETTINGS["REVELA_QA_DB_PASSWORD"],
            "\n".join(captured.output),
        )

    def test_scheduler_guard_refuses_qa_even_when_called_directly(self):
        import app as app_module

        flask_app = MagicMock()
        flask_app.config = {"REVELA_QA_MODE": True}

        self.assertIsNone(app_module._start_permit_expiry_scheduler(flask_app))
        flask_app.logger.info.assert_called_once()

    def test_normal_app_still_requests_scheduler_setup(self):
        import app as app_module

        with patch.dict(os.environ, {"REVELA_QA_MODE": "0"}, clear=False):
            with (
                patch.object(app_module.Config, "JWT_SECRET_KEY", "synthetic-jwt"),
                patch.object(app_module.mysql, "init_app"),
                patch.object(app_module.jwt, "init_app"),
                patch.object(app_module, "_start_permit_expiry_scheduler") as start_scheduler,
            ):
                app_module.create_app()

        start_scheduler.assert_called_once()


class QaExternalSideEffectTests(unittest.TestCase):
    def test_detection_and_google_services_are_blocked_before_transport(self):
        from api.flags import service as flags_service
        from api.registry import places_resolver, service as registry_service

        with patch.dict(os.environ, {"REVELA_QA_MODE": "1"}, clear=False):
            with (
                patch.object(flags_service, "_run_detection_cycle") as scan,
                patch.object(flags_service.http, "post") as nearby_post,
                patch.object(flags_service.http, "get") as places_get,
                patch.object(places_resolver.requests, "post") as text_search_post,
                patch.object(places_resolver.requests, "get") as geocode_get,
                patch.object(registry_service.http, "get") as registry_geocode_get,
            ):
                result, error = flags_service.run_detection()
                self.assertIsNone(result)
                self.assertIn("disabled", error)
                scan.assert_not_called()

                with self.assertRaisesRegex(RuntimeError, "disabled"):
                    flags_service._new_nearby_request(1.0, 1.0, 100)
                with self.assertRaisesRegex(RuntimeError, "disabled"):
                    places_resolver._text_search(
                        "synthetic", "", "", post=text_search_post
                    )
                with self.assertRaisesRegex(RuntimeError, "disabled"):
                    places_resolver._geocode_fallback(
                        "synthetic", "", get=geocode_get
                    )
                with self.assertRaisesRegex(RuntimeError, "disabled"):
                    registry_service._geocode("synthetic", "")

            nearby_post.assert_not_called()
            places_get.assert_not_called()
            text_search_post.assert_not_called()
            geocode_get.assert_not_called()
            registry_geocode_get.assert_not_called()

    def test_fcm_email_and_sms_transports_are_blocked(self):
        from api.auth import service as auth_service
        from api.notifications import fcm, service as notification_service

        with patch.dict(os.environ, {"REVELA_QA_MODE": "1"}, clear=False):
            with (
                patch.object(auth_service.requests, "post") as auth_post,
                patch.object(notification_service.requests, "post") as mail_post,
                patch.object(notification_service.smtplib, "SMTP") as smtp,
                patch.object(fcm, "get_fcm_token") as read_token,
            ):
                self.assertFalse(auth_service.send_otp_via_philsms("09123456789", "12345"))
                self.assertFalse(auth_service.send_otp_email("qa@example.invalid", "12345"))
                self.assertFalse(
                    notification_service._send_resend_email(
                        "qa@example.invalid", "subject", "body"
                    )
                )
                self.assertFalse(
                    notification_service._send_smtp_email(
                        "qa@example.invalid", "subject", "body"
                    )
                )
                self.assertFalse(fcm.send_inspection_dispatch_push(1, 2, "Synthetic"))

        auth_post.assert_not_called()
        mail_post.assert_not_called()
        smtp.assert_not_called()
        read_token.assert_not_called()

    def test_qa_does_not_start_background_workers_but_normal_mode_does(self):
        from api.utils import qa_safety

        target = MagicMock()
        with patch.dict(os.environ, {"REVELA_QA_MODE": "1"}, clear=False):
            with patch.object(qa_safety.threading, "Thread") as thread:
                self.assertFalse(qa_safety.start_background_task(target))
                thread.assert_not_called()
                target.assert_not_called()

        with patch.dict(os.environ, {"REVELA_QA_MODE": "0"}, clear=False):
            thread_instance = MagicMock()
            with patch.object(
                qa_safety.threading, "Thread", return_value=thread_instance
            ) as thread:
                self.assertTrue(qa_safety.start_background_task(target))
        thread.assert_called_once()
        thread_instance.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
