"""Frontend and backend device policy must agree.

The browser gate and the API gate are separate implementations of the same rule.
If they drift, a tablet passes one and is rejected by the other, which is how
tablets were locked out in the first place. This test pins them together.

The frontend source is read from disk rather than imported, because it is an
ES module written for the browser while this runs under CPython.
"""
import os
import re
import unittest

from api.auth import routes as auth_routes

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DETECTION = os.path.join(
    BACKEND_ROOT, "..", "revela_web", "src", "components", "mobileDetection.js"
)

USER_AGENTS = {
    "iphone_safari": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "iphone_desktop_site": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "ipad_safari": (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "ipad_desktop_site": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
    "ipad_chrome": (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1"
    ),
    "ipad_firefox": (
        "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) FxiOS/120.0 Mobile/15E148 Safari/605.1.15"
    ),
    "android_phone": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    ),
    "android_tablet": (
        "Mozilla/5.0 (Linux; Android 14; SM-X200) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "desktop_chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "desktop_edge": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0"
    ),
    "surface_pro": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Touch) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
}

# Which devices the API gate must reject.
EXPECTED_PHONE = {
    "iphone_safari": True,
    "iphone_desktop_site": True,
    "android_phone": True,
    "ipad_safari": False,
    "ipad_desktop_site": False,
    "ipad_chrome": False,
    "ipad_firefox": False,
    "android_tablet": False,
    "desktop_chrome": False,
    "desktop_edge": False,
    "surface_pro": False,
}


def _frontend_patterns():
    """Extract the TABLET/PHONE regex literals from the frontend source."""
    with open(FRONTEND_DETECTION, encoding="utf-8") as handle:
        source = handle.read()

    def grab(name):
        # Anchor on the terminating `/flags;` so an escaped slash inside the
        # pattern (`Mobile\/\d`) cannot end the match early.
        match = re.search(
            name + r"\s*=\s*/(.*?)/(?=[a-z]*\s*;)", source, re.DOTALL
        )
        assert match, f"could not find {name} in the frontend policy"
        return match.group(1), re.search(r"/([a-z]*)\s*;", source[match.start(1):], re.DOTALL).group(1)

    translate = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}

    def compile_from(name):
        pattern_src, flag_src = grab(name)
        flags = 0
        for char in flag_src:
            flags |= translate[char]
        return re.compile(pattern_src, flags)

    return compile_from("TABLET_USER_AGENT"), compile_from("PHONE_USER_AGENT")


class DevicePolicyParityTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.frontend_tablet, cls.frontend_phone = _frontend_patterns()

    def _frontend_is_phone(self, user_agent):
        """Mirror of the frontend's isPhoneUserAgent()."""
        if self.frontend_tablet.search(user_agent):
            return False
        return bool(self.frontend_phone.search(user_agent))

    def test_executed_frontend_policy_agrees_with_the_api_gate(self):
        """Run the shipped browser policy and compare it to the backend.

        This is the definitive check: it executes the real module rather than
        re-deriving its intent, so the two gates cannot drift silently.
        Skipped when Node is unavailable.
        """
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available on PATH")

        web_root = os.path.abspath(
            os.path.join(BACKEND_ROOT, "..", "revela_web")
        )
        script = os.path.join(web_root, "scripts", "device-policy-matrix.mjs")
        if not os.path.exists(script):
            self.skipTest(f"missing {script}")

        completed = subprocess.run(
            [node, script],
            cwd=web_root,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            completed.returncode, 0,
            f"policy matrix failed: {completed.stderr[:500]}",
        )
        matrix = json.loads(completed.stdout)

        self.assertGreater(len(matrix), 15, "matrix should cover the devices")
        for case in matrix:
            with self.subTest(case=case["label"]):
                # 1. The UA-only verdict must match the API gate exactly.
                self.assertEqual(
                    case["frontendPhoneUA"],
                    auth_routes._is_phone_user_agent(case["userAgent"]),
                    f"frontend/backend UA verdict disagrees on {case['label']}",
                )
                # 2. The browser gate must reject whenever the API gate would.
                self.assertFalse(
                    case["apiGateRejects"] and not case["restricted"],
                    f"API gate would reject {case['label']} but the UI allows it",
                )
                # 3. A tablet may only be restricted by the usability floor,
                #    never by a user-agent "Mobile" token. An iPad in Split
                #    View (320px) is phone-sized and is restricted on purpose.
                if "ipad" in case["label"] or "tablet" in case["label"]:
                    if case["restricted"]:
                        self.assertEqual(
                            case["reason"], "viewport-too-small",
                            f"tablet restricted by the wrong rule: "
                            f"{case['label']} ({case['reason']})",
                        )
                        self.assertLess(
                            min(case["width"], case["height"]), 560,
                            f"tablet restricted at a roomy viewport: "
                            f"{case['label']}",
                        )

    def test_matrix_contains_the_required_viewports(self):
        import json
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            self.skipTest("node is not available on PATH")
        web_root = os.path.abspath(
            os.path.join(BACKEND_ROOT, "..", "revela_web")
        )
        completed = subprocess.run(
            [node, os.path.join(web_root, "scripts", "device-policy-matrix.mjs")],
            cwd=web_root, capture_output=True, text=True, timeout=120,
        )
        matrix = {
            (c["width"], c["height"]): c["restricted"]
            for c in json.loads(completed.stdout)
        }
        for width, height, expected in (
            (375, 812, True),
            (844, 390, True),
            (768, 1024, False),
            (820, 1180, False),
            (1280, 800, False),
        ):
            with self.subTest(viewport=f"{width}x{height}"):
                self.assertEqual(matrix.get((width, height)), expected)

    def test_frontend_and_backend_classify_identically(self):
        for name, user_agent in USER_AGENTS.items():
            with self.subTest(device=name):
                self.assertEqual(
                    self._frontend_is_phone(user_agent),
                    EXPECTED_PHONE[name],
                    f"frontend misclassified {name}",
                )
                self.assertEqual(
                    auth_routes._is_phone_user_agent(user_agent),
                    EXPECTED_PHONE[name],
                    f"backend misclassified {name}",
                )
                self.assertEqual(
                    self._frontend_is_phone(user_agent),
                    auth_routes._is_phone_user_agent(user_agent),
                    f"frontend/backend disagree on {name}",
                )

    def test_no_tablet_is_rejected_by_either_gate(self):
        tablets = [
            name for name in USER_AGENTS
            if "ipad" in name or "tablet" in name
        ]
        self.assertTrue(tablets, "expected tablet samples")
        for name in tablets:
            user_agent = USER_AGENTS[name]
            self.assertFalse(
                auth_routes._is_phone_user_agent(user_agent),
                f"backend rejects tablet {name}",
            )
            self.assertFalse(
                self._frontend_is_phone(user_agent),
                f"frontend rejects tablet {name}",
            )

    def test_legacy_pattern_would_have_rejected_ipads(self):
        """Documents the original defect so it cannot be reintroduced."""
        legacy = re.compile(r"iPhone|iPod|Mobile|Windows Phone", re.IGNORECASE)
        for name in ("ipad_safari", "ipad_chrome", "ipad_firefox"):
            self.assertTrue(
                legacy.search(USER_AGENTS[name]),
                f"precondition: the old rule blocked {name}",
            )
            self.assertFalse(
                auth_routes._is_phone_user_agent(USER_AGENTS[name]),
                f"the new rule must not block {name}",
            )


if __name__ == "__main__":
    unittest.main()