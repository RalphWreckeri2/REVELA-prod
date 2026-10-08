# REVELA Production Database Data Dictionary
### Schema Architecture & Column-Level Technical Documentation
**Host:** `altaria.proxy.rlwy.net` | **Database:** `railway` | **Dialect:** MySQL 9.7 (InnoDB, UTF8MB4)

This data dictionary provides a complete technical and operational breakdown of all **13 active tables** in the REVELA production database. For each table, every column's data type, constraint, default value, and architectural purpose within the compliance and enforcement lifecycle is documented.

---

## Entity Relationship Overview

The database is structured around five operational subsystems:
1. **Administrative & Spatial Baseline:** `barangays`, `wlc_config`
2. **Master Business Ground Truth:** `official_registry`
3. **Automated Detection & Cost Control:** `detection_runs`, `scan_point_log`, `places_api_usage`
4. **Geospatial Intelligence & Field Enforcement:** `geospatial_logs`, `inspection_reports`, `inspection_lifecycle_events`
5. **Identity, Security, & Communications:** `users`, `user_password_resets`, `user_app_preferences`, `revela_notifications`

---

## 1. `barangays`
* **Purpose:** Serves as the authoritative master reference table for the **16 constituent barangays** of the Municipality of Mataasnakahoy. It supports GeoJSON boundary mapping, point-in-polygon establishment assignment, and municipal-wide analytical aggregation.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `barangayID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique integer identifier for each administrative barangay (IDs 1 to 16). |
| `barangayName` | `VARCHAR(255)` | `NOT NULL` | Official legal name of the barangay (e.g., *'Barangay I'*, *'Barangay Bayorbor'*, *'Barangay Calingatan'*). |

---

## 2. `official_registry`
* **Purpose:** Represents the **authoritative municipal ground truth** containing all legally registered businesses on record with the Business Permits and Licensing Office (BPLO). It tracks permit compliance statuses, physical coordinates, and Google Maps cross-referencing metadata.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `businessID` | `VARCHAR(50)` | `PK`, `NOT NULL` | Official BPLO business permit number or municipal account tracking code (e.g., *"BPLO-2026-0042"*). |
| `barangayID` | `INT (FK)` | `FK` $\rightarrow$ `barangays.barangayID`, `NOT NULL` | The barangay jurisdiction where the commercial establishment is officially registered to operate. |
| `businessName` | `VARCHAR(255)` | `NOT NULL`, `INDEX` | Legal registered business trade name as declared on municipal permit application forms. |
| `businessType` | `VARCHAR(255)` | `NULLABLE` | Legal business ownership entity type (*'Sole Proprietorship'*, *'Partnership'*, *'Corporation'*, *'Cooperative'*). |
| `lineOfBusiness` | `VARCHAR(500)` | `NULLABLE` | Specific commercial line of activity (e.g., *'Retail Selling of General Merchandise'*, *'Water Refilling Station'*, *'Bakery'*). |
| `businessAddress` | `VARCHAR(255)` | `NULLABLE` | Registered physical street address or purok descriptor as declared in municipal documentation. |
| `latitude` | `DECIMAL(10,8)` | `NULLABLE` | Geocoded or backfilled physical latitude coordinate (up to 8 decimal places for sub-meter positioning). |
| `longitude` | `DECIMAL(11,8)` | `NULLABLE` | Geocoded or backfilled physical longitude coordinate. |
| `placeID` | `VARCHAR(255)` | `NULLABLE` | Unique Google Maps identifier linked once the registry business is resolved to a Google Places POI. |
| `placeIDKind` | `ENUM('poi', 'address')` | `NULLABLE` | Provenance indicator denoting whether the `placeID` links to an exact commercial POI or a generic street address. |
| `coordSource` | `ENUM('csv', 'places', 'geocode', 'manual')` | `NULLABLE`, `INDEX` | Provenance of the GPS coordinates: `'csv'` (imported file), `'places'` (Google Places Text Search), `'geocode'` (Geocoding API), or `'manual'` (admin pinpoint). |
| `coordFetchedAt` | `DATETIME` | `NULLABLE`, `INDEX` | Timestamp when Google-derived coordinates were retrieved; enforces Google's 30-day data caching policy. |
| `matchScore` | `DECIMAL(4,3)` | `NULLABLE` | Normalized string similarity score (0.000 to 1.000) generated during automated text cross-referencing. |
| `matchStatus` | `ENUM('auto', 'review', 'approved', 'rejected')` | `NULLABLE`, `INDEX` | Pin verification queue status: `'auto'` (high confidence auto-accepted), `'review'` (flagged for admin inspection), `'approved'`, `'rejected'`. |
| `applicationStatus` | `ENUM('Active', 'Expired', 'Revoked', 'Pending', 'Closed')` | `NOT NULL`, `DEFAULT 'Pending'`, `INDEX` | Current regulatory licensing standing with the BPLO. Directly determines the baseline flag color (Active $\rightarrow$ Green, Expired $\rightarrow$ Orange, etc.). |
| `lastRenewalDate` | `DATETIME` | `NULLABLE`, `INDEX` | The exact date when the municipal mayor's business permit was last officially renewed. |
| `businessSize` | `VARCHAR(50)` | `NULLABLE` | Asset scale classification per Philippine DTI standards (*'Micro'*, *'Small'*, *'Medium'*, *'Large'*). |
| `registrationType` | `VARCHAR(50)` | `NULLABLE` | Permitting lifecycle category (*'New'* vs. *'Renewal'*). |

---

## 3. `geospatial_logs`
* **Purpose:** The central operational table representing **every map marker/flag in the system**. It stores POIs detected via automated Google Maps scans, suspect leads logged by inspectors, and spatial linkages to formal inspection reports.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `logID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique primary key for every geospatial marker/flag record. |
| `barangayID` | `INT (FK)` | `FK` $\rightarrow$ `barangays.barangayID`, `NOT NULL`, `INDEX` | Barangay where the detected entity is geographically located (derived via GeoJSON point-in-polygon). |
| `reportID` | `INT (FK)` | `FK` $\rightarrow$ `inspection_reports.reportID`, `NULLABLE`, `INDEX` | Foreign key linking to an active inspection report if this pin is under investigation or verified. |
| `detectedName` | `VARCHAR(255)` | `NULLABLE`, `INDEX` | Name of the establishment as returned by Google Places or entered by a field inspector. |
| `latitude` | `DECIMAL(10,8)` | `NULLABLE` | Physical latitude coordinate of the detected venue. |
| `longitude` | `DECIMAL(11,8)` | `NULLABLE` | Physical longitude coordinate of the detected venue. |
| `detectedDate` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `INDEX` | Exact timestamp when the establishment was first detected or flagged. |
| `nearestLandmark` | `VARCHAR(255)` | `NULLABLE` | Vicinity address, street corridor, or physical landmark returned by mapping services or field notes. |
| `flagColor` | `VARCHAR(50)` | `NULLABLE`, `INDEX` | Operational flag status: `'Red'` (unregistered), `'Green'` (compliant), `'Yellow'` (suspicious), `'Orange'` (expired/warning), `'Black'` (revoked), `'Purple'` (closed). |
| `placeID` | `VARCHAR(255)` | `NULLABLE` | Google Places unique identifier; prevents redundant duplication across overlapping grid search circles. |
| `reportedByUserID` | `INT (FK)` | `FK` $\rightarrow$ `users.userID`, `NULLABLE`, `INDEX` | The inspector account that manually reported this pin (NULL if auto-detected by Google Places grid scan). |
| `notes` | `TEXT` | `NULLABLE` | Administrative observations, field inspector comments, or historical compliance remarks. |
| `noticeLevel` | `INT` | `DEFAULT 0` | Progressive enforcement notice counter (0 = None, 1 = 1st Notice to Comply, 2 = 2nd Notice, 3 = Closure Notice). |

---

## 4. `detection_runs`
* **Purpose:** Maintains a persistent operational audit log of all **automated municipality-wide Google Places grid detection scans**. It powers the **D2. Trend Analysis (Detection Scan History)** dashboard and enforces the monthly scan quota.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `runID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique identification number for each detection scan cycle. |
| `triggeredByUserID` | `INT (FK)` | `FK` $\rightarrow$ `users.userID`, `NULLABLE` | Admin user who triggered the detection scan (`NULL` if scheduled or initiated via maintenance scripts). |
| `startedAt` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Timestamp recording when the automated grid sweep began. |
| `completedAt` | `DATETIME` | `NULLABLE` | Timestamp when the scan either successfully completed all grid points or paused due to quota limits. |
| `status` | `VARCHAR(50)` | `NOT NULL`, `DEFAULT 'running'` | Scan status: `'running'`, `'completed'`, `'partial'` (budget limit hit, progress saved), `'cancelled'`, or `'failed'`. |
| `newFlags` | `INT` | `DEFAULT 0` | Total number of newly discovered unregistered businesses (`Red Flags`) created during this run. |
| `totalChecked` | `INT` | `DEFAULT 0` | Total number of Google Places POIs returned and cross-referenced within municipal boundaries. |

---

## 5. `scan_point_log`
* **Purpose:** Serves as a **checkpoint logger** for multi-day and rate-limited grid scans. When a detection scan is paused by Google's daily budget ceiling, this table stores finished grid coordinates so the engine resumes seamlessly without restarting.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_0900_ai_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `pointKey` | `VARCHAR(64)` | `PK`, `NOT NULL` | Formatted grid coordinate string (e.g., `"13.96500,121.11250"`) identifying a 850m search circle node. |
| `completedAt` | `DATETIME` | `NOT NULL` | Exact timestamp when all paginated Google Places result pages for this node were successfully processed. |

---

## 6. `places_api_usage`
* **Purpose:** Implements an atomic **API Cost and Budget Guard**. It tracks daily and monthly Google Places API and Geocoding API transactions in real time, preventing unexpected municipal billing overages.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_0900_ai_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `usageDate` | `DATE` | `Composite PK`, `NOT NULL` | Calendar date of recorded API consumption. |
| `kind` | `VARCHAR(20)` | `Composite PK`, `NOT NULL` | Budget tier: `'day'`, `'month'`, `'geo_day'` (geocoding), `'imp_ts_month'` (Text Search Pro), `'imp_pd_month'` (Place Details). |
| `requestCount` | `INT` | `NOT NULL`, `DEFAULT 0` | Running counter of HTTP requests dispatched to Google; increments atomically before requests fire. |

---

## 7. `inspection_reports`
* **Purpose:** Contains all formal **on-site field audit records** submitted by municipal inspectors via the REVELA Mobile Tool. It stores ground-truth coordinates, photographic evidence, and formal compliance verdicts.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `reportID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique identifier for each formal inspection report. |
| `userID` | `INT (FK)` | `FK` $\rightarrow$ `users.userID`, `NOT NULL` | The assigned municipal inspector accountable for conducting this field audit. |
| `targetID` | `INT (FK)` | `FK (logical)` $\rightarrow$ `geospatial_logs.logID`, `NOT NULL`, `INDEX` | Foreign entity ID pointing to the audited record (specifically `logID` in `geospatial_logs`). |
| `targetType` | `VARCHAR(50)` | `NOT NULL`, `INDEX` | Entity discriminator string (*'geospatial_log'*). |
| `deadline` | `DATETIME` | `NULLABLE` | SLA due date for completing the inspection assignment. |
| `inspectionResult` | `VARCHAR(50)` | `NULLABLE` | Formal inspection outcome (*'Compliant'*, *'Non-Compliant'*, *'Unregistered'*, *'Closed'*). |
| `verificationStatus` | `VARCHAR(255)` | `NULLABLE`, `INDEX` | Administrative verification state (*'Pending'*, *'In Progress'*, *'Completed'*, *'Verified'*, *'Rejected'*). |
| `photoPath` | `TEXT` | `NULLABLE` | File storage path or Cloudinary URL containing geo-tagged photographic evidence taken on-site. |
| `remarks` | `VARCHAR(255)` | `NULLABLE` | Inspector's official field notes, violations observed, or compliance conditions noted. |
| `irTimestamp` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Timestamp recording when the inspection report was formally submitted by the inspector. |
| `resolutionTime` | `INT` | `NULLABLE` | Turnaround time in hours or minutes taken from assignment dispatch to final submission. |
| `nearestLandmark` | `VARCHAR(255)` | `NULLABLE` | Verified landmark or street address observed during on-site ground truthing. |
| `verifiedLatitude` | `DECIMAL(10,8)` | `NULLABLE` | Physical latitude coordinate captured directly by the inspector's mobile GPS receiver during audit. |
| `verifiedLongitude` | `DECIMAL(11,8)` | `NULLABLE` | Physical longitude coordinate captured directly by the inspector's mobile GPS receiver during audit. |
| `verifiedAccuracy` | `DECIMAL(8,2)` | `NULLABLE` | GPS horizontal accuracy radius (in meters) reported by the mobile device at the moment of capture. |
| `syncStatus` | `VARCHAR(20)` | `DEFAULT 'synced'` | Mobile synchronization state (*'synced'*, *'pending_sync'*, *'offline'*). |
| `clientUpdatedAt` | `DATETIME` | `NULLABLE` | Timestamp of local mobile edits, used for offline conflict resolution. |
| `clientDeviceId` | `VARCHAR(100)` | `NULLABLE` | Hardware device UUID of the inspector's mobile phone for audit trail integrity. |
| `noticeLevel` | `INT` | `DEFAULT 0` | Regulatory notice level served during this inspection visit (1 = 1st Notice, 2 = 2nd Notice, 3 = Closure). |
| `wasReassigned` | `TINYINT(1)` | `NOT NULL`, `DEFAULT 0` | Boolean indicator (1/0) denoting whether the assignment was transferred from another inspector. |
| `deadlineReminderSentAt` | `DATETIME` | `NULLABLE` | Timestamp when an automated push/email warning was sent to prevent task delinquency. |

---

## 8. `inspection_lifecycle_events`
* **Purpose:** Provides an **immutable, append-only audit trail** tracking the entire lifecycle of an inspection from initial dispatch to administrative verification or cancellation.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `eventID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Sequence ID for each immutable lifecycle audit event. |
| `reportID` | `INT (FK)` | `FK (logical)` $\rightarrow$ `inspection_reports.reportID`, `NOT NULL`, `INDEX` | The associated inspection report ID. |
| `targetLogID` | `INT (FK)` | `FK (logical)` $\rightarrow$ `geospatial_logs.logID`, `NOT NULL`, `INDEX` | The targeted `geospatial_logs.logID` undergoing audit. |
| `cycleID` | `INT` | `NULLABLE`, `INDEX` | Compliance cycle identifier for longitudinal enforcement tracking. |
| `eventType` | `ENUM(...)` | `NOT NULL`, `INDEX` | State transition: `'dispatched'`, `'reassigned'`, `'submitted'`, `'verified'`, or `'cancelled'`. |
| `actorUserID` | `INT (FK)` | `FK (logical)` $\rightarrow$ `users.userID`, `NULLABLE` | The system user who triggered the event (e.g. BPLO Admin dispatching, Inspector submitting). |
| `assignedToUserID` | `INT (FK)` | `FK (logical)` $\rightarrow$ `users.userID`, `NULLABLE` | The field inspector assigned to execute the inspection at the time of this event. |
| `flagColorAtEvent` | `VARCHAR(50)` | `NULLABLE` | Snapshot of the establishment's flag color at the exact moment this event occurred. |
| `inspectionResult` | `VARCHAR(50)` | `NULLABLE` | Snapshot of the inspection finding recorded during this event. |
| `remarks` | `VARCHAR(255)` | `NULLABLE` | Audit justification or administrative explanation entered for this state change. |
| `eventTimestamp` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP`, `INDEX` | Exact timestamp when the lifecycle event transpired. |

---

## 9. `users`
* **Purpose:** Stores user credentials, role-based authorization levels, security policies, and two-factor authentication secrets for all BPLO staff and inspectors.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `userID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique integer identifier for each system account. |
| `fullName` | `VARCHAR(255)` | `NOT NULL` | Full legal name of the municipal employee or administrator. |
| `email` | `VARCHAR(255)` | `UNIQUE`, `NOT NULL` | Official municipal email address used as the primary login identifier. |
| `phone` | `VARCHAR(20)` | `NULLABLE` | Contact phone number used for SMS alerts and urgent operational notices. |
| `userRole` | `VARCHAR(255)` | `NOT NULL` | Role-based permission tier (*'SUPER_ADMIN'*, *'ADMIN'*, *'INSPECTOR'*). |
| `userPassword` | `VARCHAR(255)` | `NOT NULL` | Secure salted cryptographic password hash generated using bcrypt (cost factor 12). |
| `createdAt` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Account creation timestamp. |
| `updatedAt` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP ON UPDATE` | Last profile modification timestamp. |
| `lastLoginAt` | `DATETIME` | `NULLABLE` | Timestamp of the user's most recent successful authentication session. |
| `mustChangePassword` | `TINYINT(1)` | `NOT NULL`, `DEFAULT 0` | Security policy flag enforcing a mandatory password update upon next login. |
| `is_2fa_enabled` | `TINYINT(1)` | `DEFAULT 0` | Boolean indicating if Time-based One-Time Password (TOTP) 2FA is activated. |
| `two_factor_secret` | `VARCHAR(32)` | `NULLABLE` | Base32-encoded cryptographic secret key used by authenticator apps (e.g. Google Authenticator). |
| `isActive` | `TINYINT(1)` | `DEFAULT 1` | Account status flag (1 = Active, 0 = Deactivated/Terminated). |
| `resetRequested` | `TINYINT(1)` | `DEFAULT 0` | Security flag indicating that a password recovery process is actively pending. |
| `fcm_token` | `TEXT` | `NULLABLE` | Firebase Cloud Messaging device registration token used to push notifications to mobile devices. |

---

## 10. `user_password_resets`
* **Purpose:** Manages **secure self-service password recovery** transactions by issuing short-lived, single-use verification tokens.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `uprID` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique identifier for the password reset transaction. |
| `userID` | `INT (FK)` | `FK` $\rightarrow$ `users.userID`, `NOT NULL`, `INDEX` | Account requesting password recovery. |
| `pwToken` | `CHAR(5)` | `NOT NULL` | High-entropy 5-character alphanumeric One-Time PIN (OTP) transmitted to user. |
| `createdAt` | `DATETIME` | `NOT NULL`, `DEFAULT CURRENT_TIMESTAMP` | Timestamp when the recovery token was generated. |
| `expiresAt` | `DATETIME` | `NOT NULL` | Expiration deadline (configured to 15 minutes after generation). |
| `isUsed` | `TINYINT(1)` | `NOT NULL`, `DEFAULT 0` | Security flag (1 = Consumed, 0 = Active) preventing token replay attacks. |

---

## 11. `user_app_preferences`
* **Purpose:** Stores personalized **notification delivery preferences** on a per-user basis.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_0900_ai_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `userID` | `INT (PK, FK)` | `PK`, `FK (logical)` $\rightarrow$ `users.userID`, `NOT NULL` | The target user ID linked 1-to-1 with `users.userID`. |
| `email_inspection_alerts` | `TINYINT(1)` | `NOT NULL`, `DEFAULT 1` | User preference toggle (1 = Enabled, 0 = Disabled) for receiving dispatch notifications via email. |
| `updatedAt` | `DATETIME` | `DEFAULT CURRENT_TIMESTAMP ON UPDATE` | Timestamp when user preferences were last saved. |

---

## 12. `revela_notifications`
* **Purpose:** Powers the **internal notification center** in both the Web Dashboard and the Mobile Inspection Tool, delivering real-time operational alerts to municipal personnel.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_0900_ai_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `id` | `INT` | `PK`, `AUTO_INCREMENT`, `NOT NULL` | Unique sequence ID for the notification entry. |
| `recipientUserId` | `INT (FK)` | `FK (logical)` $\rightarrow$ `users.userID`, `NOT NULL`, `INDEX` | Target recipient account (`users.userID`). |
| `type` | `VARCHAR(64)` | `NOT NULL`, `INDEX` | Notification category code (*'inspection_assigned'*, *'deadline_warning'*, *'new_year_rollover'*). |
| `title` | `VARCHAR(255)` | `NOT NULL` | High-level summary text displayed in notification dropdowns. |
| `body` | `TEXT` | `NULLABLE` | Detailed message narrative and operational instructions. |
| `link` | `VARCHAR(512)` | `NULLABLE` | Interactive web route URL or mobile deep-link navigated to when clicked (e.g., `"/inspections"`). |
| `readAt` | `DATETIME` | `NULLABLE`, `INDEX` | Timestamp when the user opened or read the notification (`NULL` = Unread). |
| `createdAt` | `DATETIME` | `DEFAULT CURRENT_TIMESTAMP`, `INDEX` | Timestamp when the notification was created. |

---

## 13. `wlc_config`
* **Purpose:** Stores the criteria weights and geographic origin coordinates for the **Prescriptive Analytics Weighted Linear Combination (WLC) Model**, used to calculate the Operational Priority Score ($OPS$) for inspector dispatch.
* **Storage Engine:** InnoDB | **Collation:** `utf8mb4_unicode_ci`

| Column Name | Data Type | Constraints | Description & Operational Purpose |
| :--- | :--- | :--- | :--- |
| `id` | `INT` | `PK`, `NOT NULL`, `DEFAULT 1` | Singleton primary key enforcing a single active configuration row. |
| `w1_risk` | `DECIMAL(5,2)` | `DEFAULT 40.00` | Weight percentage assigned to the normalized Risk Score ($V_i$, based on Red/Yellow/Black flag density). |
| `w2_sector` | `DECIMAL(5,2)` | `DEFAULT 40.00` | Weight percentage assigned to the commercial Sector Severity Score ($C_i$). |
| `w3_distance` | `DECIMAL(5,2)` | `DEFAULT 20.00` | Weight percentage assigned to the Inverted Travel Distance Score ($(100 - D_i)$). |
| `bplo_lat` | `DECIMAL(10,8)` | `DEFAULT 13.96670000` | Latitude of the Municipal BPLO / Town Hall used as the geographic origin for Haversine dispatch calculations. |
| `bplo_lng` | `DECIMAL(11,8)` | `DEFAULT 121.11670000` | Longitude of the Municipal BPLO / Town Hall used as the geographic origin for Haversine dispatch calculations. |
| `sector_scores` | `JSON` | `NULLABLE` | JSON dictionary defining customized hazard multipliers per commercial line of business or barangay. |
| `updated_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP ON UPDATE` | Audit timestamp recording when weights were last recalibrated by the BPLO Administrator. |

---

## Technical Summary Matrix

| Table Name | Primary Key | Foreign Keys | Key Operational Indexes |
| :--- | :--- | :--- | :--- |
| `barangays` | `barangayID` | None | None |
| `official_registry` | `businessID` | `barangayID` $\rightarrow$ `barangays` | `idx_reg_status`, `idx_reg_renewal`, `idx_reg_barangay_stat`, `idx_reg_barangay_name`, `idx_reg_coord_expiry`, `idx_reg_match_status` |
| `geospatial_logs` | `logID` | `barangayID` $\rightarrow$ `barangays`<br>`reportID` $\rightarrow$ `inspection_reports`<br>`reportedByUserID` $\rightarrow$ `users` | `idx_geo_flagcolor`, `idx_geo_brgy_flag`, `idx_geo_detecteddate`, `idx_geo_reporter`, `idx_geo_barangay_name` |
| `detection_runs` | `runID` | `triggeredByUserID` $\rightarrow$ `users` | `fk_detection_user` |
| `scan_point_log` | `pointKey` | None | None |
| `places_api_usage` | `(usageDate, kind)` | None | Composite Primary Key |
| `inspection_reports` | `reportID` | `userID` $\rightarrow$ `users`<br>`targetID` (logical) $\rightarrow$ `geospatial_logs` | `idx_ir_target_type`, `idx_ir_status`, `idx_ir_target_report` |
| `inspection_lifecycle_events` | `eventID` | `reportID` (logical) $\rightarrow$ `inspection_reports`<br>`targetLogID` (logical) $\rightarrow$ `geospatial_logs`<br>`actorUserID` (logical) $\rightarrow$ `users`<br>`assignedToUserID` (logical) $\rightarrow$ `users` | `idx_report`, `idx_target`, `idx_cycle`, `idx_type_timestamp` |
| `users` | `userID` | None | Unique Index on `email` |
| `user_password_resets` | `uprID` | `userID` $\rightarrow$ `users` | `fk_upr_user` |
| `user_app_preferences` | `userID` | `userID` (logical) $\rightarrow$ `users` | Primary Key |
| `revela_notifications` | `id` | `recipientUserId` (logical) $\rightarrow$ `users` | `idx_recipient`, `idx_created`, `idx_notif_recipient_type` |
| `wlc_config` | `id` | None | Singleton Primary Key |
