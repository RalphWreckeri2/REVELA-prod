# Cookie & Web Storage Policy

Last Updated: October 2026 • Compliant with RA 10173 (Data Privacy Act of 2012)

This Cookie & Web Storage Policy explains how the Municipality of Mataasnakahoy ("we," "us," or "our"), through its Business Permits and Licensing Office (BPLO), utilizes cookies, HTML5 local storage, session storage, and related device storage mechanisms in connection with the REVELA geospatial intelligence and field inspection platform. This policy covers both the REVELA administrative web dashboard ("Web Portal") and the REVELA field inspection mobile application ("Mobile App").

> Official Government Platform Notice: REVELA is an internal municipal system restricted to authorized personnel of the Municipality of Mataasnakahoy. We do not serve commercial advertisements, employ marketing tracking pixels, or monetize user data.

## 1. Understanding Cookies & Web Storage

To maintain high performance, responsive user interfaces, and robust multi-factor session security, modern web applications utilize local client-side storage technologies:

- **HTTP Cookies:** Small text files placed on your browser or device by web servers. Cookies can be "session" cookies (which expire when you close your browser) or "persistent" cookies (which remain stored until an expiration date or until manually cleared).
- **HTML5 Web Storage (Local & Session Storage):** A modern, secure web standard allowing web applications to store structured key-value data directly in the client's browser. Unlike traditional cookies, local storage data is never automatically transmitted over the network on every HTTP request, significantly reducing attack surfaces and bandwidth consumption.
- **Mobile Device Storage:** Native key-value stores (such as Android SharedPreferences and iOS UserDefaults/Keychain) used by the REVELA Mobile App to retain offline task queues, UI preferences, and local cryptographic tokens.

## 2. Our "No Commercial Tracking" Guarantee

As an official regulatory instrument of the Local Government Unit (LGU) of Mataasnakahoy:

- We **NEVER** use advertising, targeting, or commercial profiling cookies.
- We **NEVER** share, sell, or rent your session or device data to marketing data brokers.
- We **NEVER** employ third-party behavioral analytics or ad-retargeting pixels (e.g., Meta Pixel, TikTok, or commercial marketing SDKs).

## 3. Detailed Inventory of Storage & Cookies Used

The table below itemizes every local storage key and third-party technical cookie employed within the REVELA platform:

| Storage Key / Name | Technology | Classification | Purpose & Retention |
| --- | --- | --- | --- |
| `revela_token` | HTML5 LocalStorage | Strictly Necessary | Stores the cryptographic JSON Web Token (JWT) issued upon successful multi-factor authentication. Required to authorize your administrative requests across protected dashboard endpoints. Automatically wiped upon clicking "Sign Out" or when session expires. |
| `revela-theme` | HTML5 LocalStorage | Functional Preference | Remembers your active visual display preference (`light`, `dark`, or `system` synchronized). Prevents display flickering and preserves accessibility settings across page reloads. |
| Google Maps Platform | Third-Party Cookies & Cache | Essential Service | Utilized by the Google Maps JavaScript API (`@react-google-maps/api`) to render high-resolution satellite imagery, topographic maps, municipal zoning layers, and geocoding results. Governed under the Google Privacy Policy: https://policies.google.com/privacy |
| Tour & Walkthrough Flags | HTML5 LocalStorage & Mobile Prefs | Functional Preference | Records whether guided onboarding tours (Map, Dashboard, Tasks, Settings) have been viewed or dismissed by the user to avoid unnecessary repetition during daily inspections. |
| Offline Task Queue | Mobile Device Storage | Strictly Necessary | In the REVELA Mobile App, stores inspection reports, geotags, and photographic evidence locally when field inspectors operate in areas with intermittent cellular connectivity, syncing to the municipal server once connection is restored. |

## 4. Mobile Device Security & Biometric Integrity

The REVELA Mobile App supports biometric unlock (fingerprint and facial recognition) for field personnel on supported Android and iOS devices. We explicitly confirm:

- **Biometric Data Never Leaves Your Device:** All biometric verification is executed exclusively by the hardware-level Secure Enclave / Trusted Execution Environment (TEE) of your physical mobile device using native OS APIs (Android BiometricPrompt and iOS LocalAuthentication).
- **Zero Server Biometric Storage:** REVELA servers, municipal databases, and cloud backends have no access to, do not process, and never store your biometric signatures, fingerprint templates, or facial scans.

## 5. How to Control, Inspect, or Clear Your Storage

You have full control over your client-side storage at all times through your browser settings:

- **Inspecting Local Storage in Chrome / Edge / Brave:** Open Developer Tools (press `F12` or `Ctrl+Shift+I`), select the **Application** tab, expand **Local Storage** in the left pane, and select your REVELA domain.
- **Clearing Local Storage & Cookies:** You can clear storage for the REVELA site at any time via your browser's Privacy & Security settings, or by clicking "Clear Browsing Data".
- **Operational Effect of Clearing Storage:** Clearing your storage will immediately log you out (by removing `revela_token`) and reset your interface theme back to system default. No municipal records or submitted inspection reports on the server will be lost or affected.

## 6. Legal Compliance & Regulatory Alignment

This policy and our data handling practices are designed to comply with:

- **Republic Act No. 10173:** The Data Privacy Act of 2012 (DPA) of the Philippines and its Implementing Rules and Regulations (IRR).
- **Republic Act No. 10175:** The Cybercrime Prevention Act of 2012.
- **National Privacy Commission (NPC) Advisory Opinions:** Aligning with NPC guidance on transparency, automated data processing, and user consent for public sector systems.

## 7. Policy Amendments & Inquiries

The Municipality of Mataasnakahoy reserves the right to update this policy when new features, APIs, or statutory mandates are introduced. Revisions will be reflected with an updated "Last Updated" date at the top of this document.

For questions, technical clarifications, or Data Privacy inquiries regarding this policy, please contact:

- **Office:** Business Permits and Licensing Office (BPLO)
- **Address:** Municipal Hall, Poblacion, Mataasnakahoy, Batangas, Philippines
- **Email:** `mkahoy.bplo@gmail.com`

> RESTRICTED ACCESS: Authorized BPLO personnel only. Violators will be prosecuted under RA 10175.

Powered by **REVELA**

© 2026 Municipality of Mataasnakahoy — Business Permits and Licensing Office (BPLO). All rights reserved.
