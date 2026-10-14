-- DRAFT ONLY — REVELA Phase 3, Steps 50.7–50.8.
-- Do not execute or deploy without a separately approved migration runner,
-- preflight, and review. This file is a reviewable additive schema proposal.
-- Requires MySQL 8.0.16+ for enforced CHECK constraints.
--
-- These tables provide persistence structures only. This DDL does NOT by
-- itself implement atomic request reservation, coordinate Google quota
-- reservations with pilot-budget reservations, or provide distributed lease
-- ownership/fencing. Those guarantees require application transaction logic
-- and separate multi-worker concurrency tests.
--
-- A partial run is paused/recoverable, not active. At most one row may have
-- pending, running, or cancel_requested status. MySQL enforces this through
-- a generated active slot whose NULL values do not collide in a unique index.

CREATE TABLE `nearby_barangay_pilot_runs` (
    `runID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    `barangayID` INT UNSIGNED NOT NULL,
    `authorizationSnapshot` JSON NOT NULL,
    `scopeFingerprint` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `status` ENUM(
        'pending',
        'running',
        'cancel_requested',
        'partial',
        'completed',
        'cancelled',
        'failed'
    ) NOT NULL DEFAULT 'pending',
    `requestBudget` TINYINT UNSIGNED NOT NULL,
    `attemptsReserved` TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `cancelRequestedAt` DATETIME(6) DEFAULT NULL,
    `leaseOwner` VARCHAR(128) DEFAULT NULL,
    `fencingToken` BIGINT UNSIGNED NOT NULL DEFAULT 0,
    `leaseExpiresAt` DATETIME(6) DEFAULT NULL,
    `createdAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `startedAt` DATETIME(6) DEFAULT NULL,
    `updatedAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    `completedAt` DATETIME(6) DEFAULT NULL,
    `activeRunSlot` TINYINT GENERATED ALWAYS AS (
        CASE
            WHEN `status` IN ('pending', 'running', 'cancel_requested')
                THEN 1
            ELSE NULL
        END
    ) STORED,
    PRIMARY KEY (`runID`),
    UNIQUE KEY `uq_nearby_pilot_active_slot` (`activeRunSlot`),
    KEY `idx_nearby_pilot_barangay_created` (`barangayID`, `createdAt`),
    KEY `idx_nearby_pilot_status_lease` (`status`, `leaseExpiresAt`),
    CONSTRAINT `chk_nearby_pilot_budget`
        CHECK (`requestBudget` BETWEEN 1 AND 5),
    CONSTRAINT `chk_nearby_pilot_attempts`
        CHECK (`attemptsReserved` <= `requestBudget`),
    CONSTRAINT `chk_nearby_pilot_authorization_object`
        CHECK (JSON_TYPE(`authorizationSnapshot`) = 'OBJECT')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `nearby_barangay_pilot_cells` (
    `runID` BIGINT UNSIGNED NOT NULL,
    `scopeFingerprint` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `cellKey` VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `latitude` DECIMAL(10, 7) NOT NULL,
    `longitude` DECIMAL(10, 7) NOT NULL,
    `status` ENUM('pending', 'in_progress', 'completed', 'failed')
        NOT NULL DEFAULT 'pending',
    `createdAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `startedAt` DATETIME(6) DEFAULT NULL,
    `completedAt` DATETIME(6) DEFAULT NULL,
    `updatedAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`runID`, `scopeFingerprint`, `cellKey`),
    KEY `idx_nearby_pilot_cells_status` (`runID`, `status`, `updatedAt`),
    CONSTRAINT `chk_nearby_pilot_cell_latitude`
        CHECK (`latitude` BETWEEN -90 AND 90),
    CONSTRAINT `chk_nearby_pilot_cell_longitude`
        CHECK (`longitude` BETWEEN -180 AND 180),
    CONSTRAINT `fk_nearby_pilot_cell_run`
        FOREIGN KEY (`runID`)
        REFERENCES `nearby_barangay_pilot_runs` (`runID`)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `nearby_barangay_pilot_places` (
    `runID` BIGINT UNSIGNED NOT NULL,
    `placeID` VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `barangayID` INT UNSIGNED NOT NULL,
    `processingDecision` ENUM(
        'pending',
        'permitted',
        'rejected_out_of_scope',
        'rejected_registry_conflict',
        'rejected_flag_conflict',
        'rejected_invalid',
        'processed'
    ) NOT NULL DEFAULT 'pending',
    `createdAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `decisionAt` DATETIME(6) DEFAULT NULL,
    `processedAt` DATETIME(6) DEFAULT NULL,
    `updatedAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`runID`, `placeID`),
    KEY `idx_nearby_pilot_places_decision`
        (`runID`, `processingDecision`, `updatedAt`),
    KEY `idx_nearby_pilot_places_barangay` (`barangayID`, `createdAt`),
    CONSTRAINT `fk_nearby_pilot_place_run`
        FOREIGN KEY (`runID`)
        REFERENCES `nearby_barangay_pilot_runs` (`runID`)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- The ledger is the authoritative cleanup ownership record: cleanup must
-- verify runID + flagLogID + barangayID, never Place ID alone. A future
-- nullable geospatial_logs.pilotRunID BIGINT UNSIGNED (with an index and
-- appropriate foreign key) may provide a direct ownership marker, but that
-- existing table is intentionally not altered in this draft. Before adding
-- any flag-log FK or the future column, confirm the production logID type.
CREATE TABLE `nearby_barangay_pilot_created_flags` (
    `runID` BIGINT UNSIGNED NOT NULL,
    `flagLogID` BIGINT NOT NULL,
    `barangayID` INT UNSIGNED NOT NULL,
    `createdAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`runID`, `flagLogID`),
    UNIQUE KEY `uq_nearby_pilot_flag_single_owner` (`flagLogID`),
    KEY `idx_nearby_pilot_flags_barangay` (`barangayID`, `createdAt`),
    CONSTRAINT `fk_nearby_pilot_created_flag_run`
        FOREIGN KEY (`runID`)
        REFERENCES `nearby_barangay_pilot_runs` (`runID`)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE `nearby_barangay_pilot_attempts` (
    `runID` BIGINT UNSIGNED NOT NULL,
    `attemptNumber` TINYINT UNSIGNED NOT NULL,
    `idempotencyKey` CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    `attemptType` ENUM('initial', 'retry', 'adaptive') NOT NULL,
    `reservedAt` DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    `outcome` ENUM(
        'reserved',
        'succeeded',
        'failed',
        'timed_out',
        'response_discarded'
    ) NOT NULL DEFAULT 'reserved',
    `completedAt` DATETIME(6) DEFAULT NULL,
    PRIMARY KEY (`runID`, `attemptNumber`),
    UNIQUE KEY `uq_nearby_pilot_attempt_idempotency` (`idempotencyKey`),
    KEY `idx_nearby_pilot_attempt_outcome` (`runID`, `outcome`, `reservedAt`),
    CONSTRAINT `chk_nearby_pilot_attempt_number`
        CHECK (`attemptNumber` BETWEEN 1 AND 5),
    CONSTRAINT `fk_nearby_pilot_attempt_run`
        FOREIGN KEY (`runID`)
        REFERENCES `nearby_barangay_pilot_runs` (`runID`)
        ON DELETE RESTRICT
        ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
