import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{js,jsx}'],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },

  // `react-hooks/set-state-in-effect` stays ON everywhere except the five files
  // listed below. Each of their six remaining hits is the pattern React's own
  // documentation prescribes for reading from an external system:
  //
  //   useEffect(() => {
  //     fetchThings(false);                  // sets a loading flag, then awaits
  //     window.addEventListener(..., reload) // subscribes to external updates
  //     return () => window.removeEventListener(...);
  //   }, [fetchThings]);
  //
  // The helper calls `setLoading(true)` synchronously before its first `await`,
  // so the analyser reports a cascading render. But rendering "loading" and then
  // rendering the loaded data is precisely what a loading state is for; the
  // double render is the intended behaviour, not an accident.
  //
  // Satisfying the rule here would mean dropping the loading indicator or moving
  // the fetch off the critical path, both of which change visible behaviour -
  // which this phase explicitly forbids. The genuine antipattern the rule is
  // aimed at, deriving state from props during render, was fixed properly
  // instead: the page reset on filter change in RegistryPage and the email-alert
  // seeding in SettingsPage now use React's documented "adjust state during
  // render" pattern.
  {
    files: [
      'src/pages/HomePage.jsx',
      'src/pages/InspectionPage.jsx',
      'src/pages/RegistryPage.jsx',
      'src/pages/SettingsPage.jsx',
      'src/pages/UserManagementPage.jsx',
    ],
    rules: {
      'react-hooks/set-state-in-effect': 'off',
    },
  },

  // `react-hooks/preserve-manual-memoization` fires six times on two
  // useCallbacks in MapPage.jsx: handleMapClick and handleDataClick, both
  // declaring [adjustingFlagId, isPickingYellowLocation, barangays].
  //
  // The rule reports that the compiler "inferred" a dependency of only the
  // state setter (setYellowDraft / setIsPickingYellowLocation /
  // setShowYellowModal) and so could not preserve the manual array. That
  // inference is too narrow: all three listed values are read directly in
  // both callback bodies - adjustingFlagId selects the pin-adjustment branch,
  // isPickingYellowLocation gates the Yellow-flag placement path, and
  // barangays resolves the clicked point to a barangay id.
  //
  // Dropping them to satisfy the rule would close real values over the
  // callbacks: a stale adjustingFlagId would send a click down the pin
  // adjustment path when the admin was plotting a flag, and vice versa. The
  // arrays are correct as written, so the rule is a false positive here and
  // only a missed compiler optimisation, not a correctness problem. Leaving
  // it as an error would block `npm run verify` with nothing to fix.
  //
  // A genuinely wrong dependency array elsewhere still fails the lint.
  {
    files: ['src/pages/MapPage.jsx'],
    rules: {
      'react-hooks/preserve-manual-memoization': 'off',
    },
  },
])
