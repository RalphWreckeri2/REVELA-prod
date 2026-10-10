# REVELA — Production Deployment Guide
### A Geospatial Business Intelligence System for Compliance Monitoring and Non-Registered Business Detection
**Municipality of Mataasnakahoy, Batangas — BPLO Deployment**

This repository contains the production code for the REVELA system. Based on modern cloud architecture, the production deployment is split into two managed cloud platforms for ease of maintenance, SSL management, and high availability:
- **Backend API & Database** are hosted on **Railway** (Flask REST API run in Docker + MySQL 8.x).
- **Web Frontend** is hosted on **Vercel** (React.js Admin Dashboard).
- **Domain Routing & DNS** is managed via **Namecheap** (`revelasys.site`).
- **Mobile Client (Flutter)** is compiled as a release APK and sideloaded manually. It is not bundled into the web deployment.

---

## Production Architecture

```
                                  [ Namecheap DNS: revelasys.site ]
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        ▼                                                 ▼
             [ Vercel (Web Frontend) ]                        [ Railway (Backend API) ]
          URL: https://revelasys.site                      URL: https://api.revelasys.site
                     │                                                 │
          Hosts: React Admin Dashboard                                 │ (REST API & Analytics)
          Hosts: (APK is no longer hosted here)                       ▼
                                                              [ Railway MySQL DB ]
                                                               (Internal Network)
                                                                       ▲
             [ Sideloaded Flutter APK ]                                │
              (Field Inspector Mobile)                                 │
              Connects via HTTPS API ──────────────────────────────────┘
```

---

## Part 1: Database Setup on Railway

1. **Create MySQL Service**:
   - Go to your Railway dashboard, click **New Project** -> **Provision MySQL**.
2. **Access Connection Details**:
   - In the newly created MySQL service, navigate to the **Variables** tab to get the credentials:
     - `MYSQLHOST` (Maps to `DB_HOST`)
     - `MYSQLPORT` (Maps to `DB_PORT`)
     - `MYSQLDATABASE` (Maps to `DB_NAME`)
     - `MYSQLUSER` (Maps to `DB_USER`)
     - `MYSQLPASSWORD` (Maps to `DB_PASSWORD`)
3. **Import Database Schema**:
   - Connect to the Railway MySQL instance using a local MySQL client (like MySQL Workbench, DBeaver, or VS Code MySQL extension) using the **Public Connection URL** from Railway.
   - Execute the SQL statements in [revela_db.sql](./revela_db.sql) to set up all tables and seed default barangays and administrators.

---

## Part 2: Backend Deployment on Railway

1. **Deploy Backend Service**:
   - In your Railway project, click **New** -> **GitHub Repo** -> Choose `REVELA-prod`.
   - Set the **Root Directory** in the service settings to `revela_backend`.
   - Railway will auto-detect the `Dockerfile` we added in `revela_backend/` and build the container.
2. **Configure Environment Variables**:
   - In the backend service, go to the **Variables** tab and add:
     - `FLASK_ENV` = `production`
     - `FLASK_DEBUG` = `0`
     - `JWT_SECRET_KEY` = `[Generate a secure 64-character random string]`
     - `CORS_ORIGINS` = `https://revelasys.site,https://www.revelasys.site` (Allows Vercel to reach the backend)
     - `GOOGLE_MAPS_API_KEY` = `[Your Google Maps API Key]`
     - `RESEND_API_KEY` = `[Your Resend API Key]`
     - `RESEND_FROM` = `alerts@revelasys.site`
     - `PHILSMS_API_TOKEN` = `[Your PhilSMS API Token]`
     - `PHILSMS_SENDER_ID` = `PhilSMS` (Default sender ID, or your custom approved sender ID)
     - **Database Credentials** (Link these directly from your Railway MySQL service):
       - `DB_HOST` = `${{MySQL.MYSQLHOST}}`
       - `DB_PORT` = `${{MySQL.MYSQLPORT}}`
       - `DB_NAME` = `${{MySQL.MYSQLDATABASE}}`
       - `DB_USER` = `${{MySQL.MYSQLUSER}}`
       - `DB_PASSWORD` = `${{MySQL.MYSQLPASSWORD}}`
3. **Add Custom Subdomain**:
   - Go to the backend service -> **Settings** -> **Domains** -> **Custom Domain**.
   - Input `api.revelasys.site` and copy the CNAME target value provided by Railway (e.g. `revela-backend.up.railway.app`).

---

## Part 3: Web Frontend Deployment on Vercel

1. **Create Vercel Project**:
   - Go to the Vercel dashboard, click **Add New** -> **Project**.
   - Import your `REVELA-prod` GitHub repository.
2. **Configure Build Settings**:
   - **Root Directory**: Select `revela_web`.
   - **Framework Preset**: `Vite` (automatically detected).
   - **Build Command**: `npm run build`
   - **Output Directory**: `dist`
3. **Configure Environment Variables**:
   - Add the following variables:
     - `VITE_API_ORIGIN` = `https://api.revelasys.site`
     - `VITE_API_URL` = `https://api.revelasys.site/api`
4. **Deploy**:
   - Click **Deploy**. Vercel will build the React app and deploy it.
5. **Assign Custom Domains**:
   - Go to Project Settings -> **Domains**.
   - Add `revelasys.site` and `www.revelasys.site`.

---

## Part 4: DNS Configuration (Namecheap)

To route your purchased domain `revelasys.site` to Vercel (Frontend) and Railway (Backend API), log in to Namecheap, go to your **Domain List** -> **Manage** -> **Advanced DNS**, and add the following records:

| Type | Host | Value | TTL | Purpose |
|------|------|-------|-----|---------|
| **A Record** | `@` | `76.76.21.21` | Automatic | Points root domain (`revelasys.site`) to Vercel |
| **CNAME Record** | `www` | `cname.vercel-dns.com.` | Automatic | Points subdomain (`www.revelasys.site`) to Vercel |
| **CNAME Record** | `api` | `[Railway Target Domain, e.g. service.up.railway.app]` | Automatic | Points API subdomain (`api.revelasys.site`) to Railway |

---

## Part 5: Email & SMS API Gateway Setup

### 1. Resend (Email Alerts)
Resend enforces a domain verification check in production. Using `onboarding@resend.dev` will restrict sending to your registered account email only (generating a 403 status code for other recipients).
- Go to the **Resend Dashboard** -> **Domains** -> **Add Domain** -> Input `revelasys.site`.
- Add the DNS records (DKIM and SPF TXT/MX records) provided by Resend to your Namecheap **Advanced DNS** table.
- Once verified (status changes to `Verified`), you can send compliance alerts to any email address using `RESEND_FROM=alerts@revelasys.site`.

### 2. PhilSMS Gateway (2FA / Passwords)
PhilSMS provides SMS delivery across Philippine mobile carriers (Globe, Smart, DITO) without requiring static IP whitelisting.
- Endpoint: `https://dashboard.philsms.com/api/v3/sms/send`
- Environment Variables required on Railway:
  - `PHILSMS_API_TOKEN`: Your API token generated from the PhilSMS Dashboard.
  - `PHILSMS_SENDER_ID`: `PhilSMS` (Default works for Globe; or your registered Sender ID).

---

## Part 6: Mobile Client (Flutter APK)

The Flutter mobile application runs on inspectors' physical Android devices and is sideloaded manually. **The APK is not part of the web deployment and is not hosted by Vercel.**

> **Why:** the APK used to be committed at `revela_web/public/revela.apk`. Vite copies everything in `public/` into `dist/` on every build, so each deployment retained an extra ~69 MB. `*.apk` is now git-ignored and the binary is never committed or bundled.

1. **Compile the APK locally**:
   Open a terminal in the development repository under `revela_mobile`:
   ```bash
   flutter build apk --release --dart-define=API_BASE=https://api.revelasys.site
   ```
   The artifact is written to `revela_mobile/build/app/outputs/flutter-apk/app-release.apk`.
   That folder is git-ignored, so the binary is never committed.

2. **Distribute it yourself.** Transfer the APK to the devices by whatever channel
   suits (USB, shared drive, messaging app). No hosting configuration is required.

3. **The old download endpoint is retired.** `https://revelasys.site/revela.apk` now
   returns a genuine HTTP 404. This is deliberate: a request that falls through to the
   SPA catch-all would return the dashboard HTML with a `200`, which looks like a
   working link but downloads a web page instead of an app.

   The behaviour comes from `revela_web/vercel.json`, which excludes the retired paths
   from the SPA catch-all with a negative lookahead:
   ```json
   { "source": "^/(?!revela\\.apk$)(?!__retired__/).*", "destination": "/index.html" }
   ```
   Every path that matches is served the SPA shell; `/revela.apk` and anything under
   `/__retired__/` match nothing, so Vercel answers them with its own 404.

   **Why not a rewrite to a non-existent path?** An earlier revision used
   `{ "source": "/revela.apk", "destination": "/__retired__/revela.apk" }` placed ahead
   of a `/(.*)` catch-all. That was verified against the live site and it does **not**
   work: Vercel resolved `/revela.apk` to the dashboard HTML with a `200` and
   `Content-Disposition: inline; filename="index.html"`. Rewrites are not "first match
   wins, then 404" -- when a rewrite destination does not resolve, evaluation continues
   and the catch-all still matches. Excluding the path is the reliable way to get a 404.

   Static assets are unaffected: `rewrites` check the filesystem first, so
   `/assets/*` and `/data/*` are served from the build output before any rewrite applies.

   If APK hosting is reintroduced, remove the lookahead from `source` and add a
   `redirects` entry for `/revela.apk` -- note that a rewrite cannot override a redirect,
   so a stale exclusion would keep shadowing it.

No `VITE_APK_DOWNLOAD_URL` variable is needed or configured. If a download button is
ever reintroduced in the UI, add the configuration then, together with the hosting
decision it depends on.
