# Evidence cleanup safety

The Settings cleanup endpoint keeps its existing age filters and confirmation
requirement. It now locks the selected reports in a MySQL transaction and makes
verified recovery copies **before** removing any original photo. This requires
transactional (InnoDB) inspection tables and temporary free disk space roughly
equal to the selected physical photos. If that space is unavailable, cleanup
stops without deleting the originals.

- A failed deletion, metadata update, or confirmed failed commit rolls back the
  database and restores removed originals. An uncertain commit outcome retains
  recovery copies until the database can be checked. Neither is reported as a
  successful cleanup.
- Recovery copies and a journal are stored in private `.cleanup-backup-*`
  directories **inside the evidence volume**, not an ephemeral system temp
  directory. Do not remove these directories manually or expose them through
  static-file hosting.
- After a successful commit, the recovery copies are disposed of. Disposal
  failure returns `recoveryPending` and a warning rather than claiming that all
  space was freed. Statistics include retained backup storage. Settings permits
  retry even when no active reports remain eligible.
- On the next cleanup, an interrupted journal is checked against locked report
  rows. Original metadata means restore the originals; committed archive metadata
  means dispose of the backups. Mixed/missing/changed metadata blocks automatic
  cleanup and retains the recovery copies for administrator review.
- Recovery failure also retains the copies. Do not retry by deleting the journal;
  inspect the associated report IDs, current `photoPath`, and recovery copies
  locally. Preserve both copies if a newer upload conflicts with the backup.

Filesystem operations and MySQL are not one atomic transaction. These journals
provide recovery for application/process failures, not protection against losing
the evidence volume, corrupt storage, or an entire host. Keep the evidence volume
persistent across restarts/deployments and maintain independent backups. A
network failure during commit can leave its outcome uncertain; recovery must
check the database, not infer that a raised exception proves the commit failed.

The ZIP download remains a separate operation. Before confirming cleanup, open
the downloaded archive and verify its dossier, manifest, and photos. A browser
download trigger alone does not prove a backup was saved successfully.

Local checks (synthetic files/transactional DB fake; no production access):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_evidence_cleanup.py -v
```

Web regression checks run the production build with synthetic API responses:

```powershell
npm run test:settings:browser
```

The browser check requires Node with WebSocket support and local Edge (or
`EDGE_BINARY`) on Windows. It covers failed/incomplete 2FA setup and retry,
server-confirmed email preferences, local-cache/refresh failures, native keyboard
activation of Settings cards, and cleanup failure/pending-recovery UI. It does
not validate production MySQL, Google Maps, geolocation, or provider delivery.
