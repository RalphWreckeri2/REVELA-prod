-- Apply after the enforcement-state migrations. No existing business is linked
-- or recoloured by this migration. businessID is already the registry PK and
-- geospatial_logs.businessID already references it.
ALTER TABLE official_registry
    ADD COLUMN confirmedLogID INT NULL DEFAULT NULL,
    ADD UNIQUE KEY uq_registry_confirmed_pin (confirmedLogID),
    ADD CONSTRAINT fk_registry_confirmed_pin
        FOREIGN KEY (confirmedLogID) REFERENCES geospatial_logs (logID)
        ON DELETE RESTRICT ON UPDATE RESTRICT;
