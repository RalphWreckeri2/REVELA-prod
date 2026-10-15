"""Regression tests: role assignment cannot escalate to SUPER_ADMIN.

create_user and update_user wrote users.userRole straight from the request
body, so any Admin could mint a SUPER_ADMIN - the exact role that
super_admin_required() gates. Roles are now allow-listed, and only an existing
SUPER_ADMIN may create or promote one.

There is no seed script for the first SUPER_ADMIN in this repository, so the
first one may still be created by any admin; that is the bootstrap escape
hatch and it closes as soon as a SUPER_ADMIN row exists.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask

from api.users import routes as users_routes
from api.users import routes as _routes

ADMIN = {"userID": 2, "userRole": "Admin"}
SUPER = {"userID": 1, "userRole": "SUPER_ADMIN"}
SYSD = {"userID": 3, "userRole": "System Administrator"}


class RoleValidationTests(unittest.TestCase):
    """Unit level on the allow-list itself."""

    def test_all_four_roles_are_accepted(self):
        for role in ("Inspector", "Admin", "SUPER_ADMIN", "System Administrator"):
            ok, value = users_routes._validate_role(role)
            self.assertTrue(ok, role)
            self.assertEqual(value, role)

    def test_invalid_roles_are_rejected(self):
        for role in ("superadmin", "SUPER-ADMIN", "Root", "", "Admin!",
                      "  ", 5, ["Admin"], None):
            ok, error = users_routes._validate_role(role)
            self.assertFalse(ok, repr(role))
            self.assertIn("must be one of", error)

    def test_casing_and_surrounding_whitespace_are_tolerated(self):
        for raw, expected in (("  super_admin  ", "SUPER_ADMIN"),
                              ("admin\n", "Admin"),
                              ("Inspector ", "Inspector"),
                              ("system administrator", "System Administrator")):
            ok, value = users_routes._validate_role(raw)
            self.assertTrue(ok, raw)
            self.assertEqual(value, expected)

    def test_role_is_normalised_for_casing_and_whitespace(self):
        ok, value = users_routes._validate_role("  super_admin  ")
        self.assertTrue(ok)
        self.assertEqual(value, "SUPER_ADMIN")

    def test_system_administrator_is_not_a_super_admin(self):
        # super_admin_required() matches the exact string; the guard must agree.
        with patch.object(users_routes, "get_jwt_identity", return_value=3), \
             patch.object(users_routes, "find_user_by_id", return_value=SYSD):
            self.assertFalse(users_routes._caller_is_super_admin())


class _RouteHarness(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.created = []
        # admin_required() wraps both views; step past it so these tests
        # exercise role authorisation rather than the JWT/session guard.
        self.create_view = users_routes.create_user_route.__wrapped__
        self.update_view = users_routes.update_user_route.__wrapped__

    def _create(self, payload, actor=ADMIN, super_admins=(SUPER,)):
        self.created.clear()
        with (
            patch.object(users_routes, "get_jwt_identity",
                         return_value=actor["userID"]),
            patch.object(users_routes, "find_user_by_id", return_value=actor),
            patch.object(users_routes, "get_users_by_role",
                         side_effect=lambda r: list(super_admins)
                         if r == "SUPER_ADMIN" else []),
            patch.object(users_routes, "find_user_by_email", return_value=None),
            patch.object(users_routes, "create_user",
                         side_effect=lambda **kw: self.created.append(kw)
                         or 99),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            with self.app.test_request_context("/users/", method="POST",
                                               json=payload):
                body, status = self.create_view()
        return body, status

    def _update(self, target, payload, actor=ADMIN, super_admins=(SUPER,)):
        updated = []

        def fetch(user_id):
            # The same lookup serves both the target row and the caller's own
            # role check, so it must answer per id.
            return actor if int(user_id) == actor["userID"] else target

        with (
            patch.object(users_routes, "get_jwt_identity",
                         return_value=actor["userID"]),
            patch.object(users_routes, "find_user_by_id", side_effect=fetch),
            patch.object(users_routes, "get_users_by_role",
                         side_effect=lambda r: list(super_admins)
                         if r == "SUPER_ADMIN" else []),
            patch.object(users_routes, "find_user_by_email", return_value=None),
            patch.object(users_routes, "update_user",
                         side_effect=lambda **kw: updated.append(kw)),
            patch("api.notifications.hub.publish_to_admins"),
        ):
            with self.app.test_request_context("/users/7", method="PATCH",
                                               json=payload):
                body, status = self.update_view(7)
        return body, status, updated


class CreateUserRoleTests(_RouteHarness):

    BASE = {"fullName": "Ana Reyes", "email": "ana@example.gov.ph",
            "role": "Inspector"}

    def test_admin_cannot_create_a_super_admin(self):
        body, status = self._create({**self.BASE, "role": "SUPER_ADMIN"})
        self.assertEqual(status, 403)
        self.assertEqual(self.created, [])

    def test_system_administrator_cannot_create_a_super_admin(self):
        body, status = self._create({**self.BASE, "role": "SUPER_ADMIN"},
                                    actor=SYSD)
        self.assertEqual(status, 403)
        self.assertEqual(self.created, [])

    def test_super_admin_can_create_a_super_admin(self):
        body, status = self._create({**self.BASE, "role": "SUPER_ADMIN"},
                                    actor=SUPER)
        self.assertEqual(status, 201)
        self.assertEqual(self.created[0]["role"], "SUPER_ADMIN")

    def test_bootstrap_first_super_admin_is_allowed(self):
        # No SUPER_ADMIN rows exist yet, so any admin may create the first.
        body, status = self._create({**self.BASE, "role": "SUPER_ADMIN"},
                                    super_admins=())
        self.assertEqual(status, 201)
        self.assertEqual(self.created[0]["role"], "SUPER_ADMIN")

    def test_invalid_role_is_400(self):
        body, status = self._create({**self.BASE, "role": "Root"})
        self.assertEqual(status, 400)
        self.assertIn("must be one of", body.get_json()["error"])
        self.assertEqual(self.created, [])

    def test_existing_role_flows_still_work(self):
        for role in ("Inspector", "Admin", "System Administrator"):
            with self.subTest(role=role):
                self.created.clear()
                body, status = self._create({**self.BASE, "role": role})
                self.assertEqual(status, 201)
                self.assertEqual(self.created[0]["role"], role)


class UpdateUserRoleTests(_RouteHarness):

    TARGET = {"userID": 7, "fullName": "Ben", "email": "ben@example.gov.ph",
              "userRole": "Inspector", "phone": None}

    def test_admin_cannot_promote_to_super_admin(self):
        body, status, updated = self._update(
            dict(self.TARGET), {"role": "SUPER_ADMIN"})
        self.assertEqual(status, 403)
        self.assertEqual(updated, [], "nothing may be written")

    def test_system_administrator_cannot_promote_to_super_admin(self):
        body, status, updated = self._update(
            dict(self.TARGET), {"role": "SUPER_ADMIN"}, actor=SYSD)
        self.assertEqual(status, 403)
        self.assertEqual(updated, [])

    def test_super_admin_can_promote_to_super_admin(self):
        body, status, updated = self._update(
            dict(self.TARGET), {"role": "SUPER_ADMIN"}, actor=SUPER)
        self.assertEqual(status, 200)
        self.assertEqual(updated[0]["role"], "SUPER_ADMIN")

    def test_invalid_role_on_update_is_400(self):
        body, status, updated = self._update(
            dict(self.TARGET), {"role": "Wizard"})
        self.assertEqual(status, 400)
        self.assertEqual(updated, [])

    def test_demoting_an_existing_super_admin_is_still_ignored(self):
        # Pre-existing behaviour: a SUPER_ADMIN row's role cannot be changed
        # through this route, by anyone. Must not be loosened here.
        target = {**self.TARGET, "userRole": "SUPER_ADMIN"}
        for actor in (ADMIN, SUPER):
            with self.subTest(actor=actor["userRole"]):
                body, status, updated = self._update(
                    dict(target), {"role": "Inspector"}, actor=actor)
                self.assertEqual(status, 200)
                self.assertEqual(updated[0]["role"], "SUPER_ADMIN",
                                 "role should be ignored, not demoted")

    def test_non_role_updates_still_work(self):
        body, status, updated = self._update(
            dict(self.TARGET), {"fullName": "Ben Santos"})
        self.assertEqual(status, 200)
        self.assertEqual(updated[0]["full_name"], "Ben Santos")
        self.assertEqual(updated[0]["role"], "Inspector")

    def test_promotion_to_other_roles_still_allowed_for_admins(self):
        for role in ("Inspector", "Admin", "System Administrator"):
            with self.subTest(role=role):
                body, status, updated = self._update(
                    dict(self.TARGET), {"role": role})
                self.assertEqual(status, 200)
                self.assertEqual(updated[0]["role"], role)


if __name__ == "__main__":
    unittest.main()