# REVELA Web

## Public entry routes

- `/` is the public, responsive REVELA landing page. It does not require a session.
- Both **Log In** links use React Router to open the unchanged login form at `/login`.
- Unauthenticated protected-route visits go to `/login`; successful login still goes to `/home`.
- Logout still returns to `/`. Visiting the public page does not clear an active session.
- The portal's existing phone-size restriction still applies to `/login` and the dashboard, not the landing or public legal pages.
- `vercel.json` already rewrites both public entry URLs to the SPA shell for direct navigation and refresh.

Run `npm run verify` for the existing lint, unit, context, and production-build checks.
Run `npm run test:public-entry:browser` on Windows with Edge installed to check the
production router, login/session flow, 2FA, recovery, role gates, and responsive layouts.
Authentication responses in this check are **synthetic**; it never contacts a backend.
Screenshots and results are written to `%LOCALAPPDATA%\Temp\opencode\revela-public-entry-review`.

The landing page uses the original `src/assets/mkahoybg.png` map as a proportional,
full-page background. A horizontal off-white CSS gradient protects text readability
without filtering or uniformly fading the map. The original system logo and municipal
seal retain their proportions and colors. Home returns to the top; About opens a native,
keyboard-accessible dialog with a concise system overview and the public legal links.

## React + Vite

This template provides a minimal setup to get React working in Vite with HMR and some ESLint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the ESLint configuration

If you are developing a production application, we recommend using TypeScript with type-aware lint rules enabled. Check out the [TS template](https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts) for information on how to integrate TypeScript and [`typescript-eslint`](https://typescript-eslint.io) in your project.
