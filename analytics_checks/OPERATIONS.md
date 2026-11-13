# Audited dkhando load and recovery runbook

Preparation only. No seed, bootstrap, recovery, or restore has been executed.
The database owner must explicitly approve the load after reviewing the backup,
maintenance window and recovery evidence. Restore rehearsal and recovery are
separate write operations requiring approval for their respective targets.

## Single-use loader

`python -m analytics_checks.load_seed` is read-only. It checks the exact target,
14 InnoDB tables, routine/trigger inventory, the hash-pinned seed manifest and
an exact baseline: three protected accounts, their three role rows, and no
other rows. This is stricter than merely checking seed IDs. Any added records
or partially loaded seed block execution and require another audit.

Before approved execution, pause Flask and every other database writer. The
precheck is not a concurrency lock: keeping writers paused is mandatory through
backup, load, validation and any recovery. Recheck live SHOW CREATE definitions
against the audited canonical schema; the loader checks names, not definition
identity. Do not reinstall the schema. Restrict the seed file and manifest from
concurrent modification. Do not initialize sample passwords before validation.

Execution requires all of:

* `--execute --approval LOAD-DKHANDO-ONCE` (operator acknowledgement, not a
  substitute for the user's approval).
* A verified-backup receipt, described below.
* A new absolute journal path, outside the repository, on durable local storage.
  The loader creates it exclusively, owner-only, and fsyncs each statement's
  attempt/completion record. It contains statement numbers, not SQL or secrets.

The loader runs statements sequentially on one connection, stops on the first
exception and rolls back only the current transaction. It never retries. It
consumes CALL result sets before the next statement. Failed journals must be
retained; do not circumvent them by picking a new filename. The exact baseline
check also rejects any previously committed partial load.

## Transaction boundaries and partial state

The pinned seed has 23 explicit COMMIT statements: one after all reference data
and shipments, and 22 after shipment scan blocks (shipment 14 has no scans).
There are 22 CALLs to book_shipment; each procedure owns and commits its own
transaction. The wrapper uses autocommit=False from app.db.

* Before the first COMMIT: a statement failure rolls back all pending reference
  rows. The loader stops; a raw CLI running with autocommit would differ.
* After the first COMMIT: all 11 hubs, 5 lanes, 8 accounts, 7 vehicles and their
  subtypes, 10 departures and 23 shipments persist.
* During booking: previously successful bookings persist independently.
* During scans: earlier shipment scan blocks and their trigger-updated status
  persist; the current failed block rolls back as a unit.
* A lost connection or lost acknowledgement makes the final attempted statement
  uncertain. Resolve its state by SELECT; never infer rollback from a missing
  journal completion record. Allocated AUTO_INCREMENT values may leave gaps.

The seed is not atomic or idempotent. Never retry it, ignore duplicate errors,
use mysql --force, disable constraints/triggers, or wrap it in a supposed global
rollback transaction. Do not run the raw seed CLI against dkhando.

## Backup prerequisites and commands

Observed during preparation: no mariadb-dump, mysqldump, mariadb or mysql in
PATH. Docker CLI is installed but its daemon is unreachable. Schema privileges
include SELECT, SHOW VIEW, TRIGGER, EVENT and routine privileges; routine and
trigger bodies are visible in information_schema. Global privilege is USAGE;
SELECT on mysql.proc fails with error 1142. A MariaDB 10.5 --routines dump may
therefore require administrator assistance. Do not claim a complete backup
based only on information_schema visibility.

Preferred path: have the class DBA make a MariaDB-compatible logical backup
with routine-export privileges, or provide an approved client and the necessary
metadata access. An installed MariaDB 10.5 client (or an approved container with
network access) is a utility alternative, not a privilege workaround. Do not
install a server into dkhando. A backup without routines is incomplete unless
an authorized operator separately captures and verifies their exact CREATE
statements and restore order. Do not hand-roll a password/data exporter.

The following command is a template for the authorized backup operator after
client availability and routine permissions have been resolved. Set DB_USER
and DB_PORT locally without displaying them; never source .env as shell code.
Use an encrypted local volume, outside Git/cloud sync, for BACKUP_DIR. No
password appears in arguments, environment, shell history or printed output.

    umask 077
    export BACKUP_DIR=/absolute/encrypted/private/csc540-backup
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    mariadb-dump --host=classdb2.csc.ncsu.edu --port="$DB_PORT" \
      --user="$DB_USER" --password --single-transaction --quick \
      --skip-lock-tables --routines --triggers --events --hex-blob \
      --no-tablespaces --skip-add-drop-table --skip-add-locks \
      --result-file="$BACKUP_DIR/dkhando-before.sql" dkhando
    chmod 600 "$BACKUP_DIR/dkhando-before.sql"
    shasum -a 256 "$BACKUP_DIR/dkhando-before.sql"

Check the dump command exit status immediately; a nonempty partial file is not
success. Do not pipe or print the dump, grep account INSERTs, attach it to chat,
or commit it: it necessarily contains existing password hashes. The checksum
is safe to record. Do not use --databases or --all-databases, which could embed
USE/CREATE DATABASE statements targeting dkhando. Keep writers/DDL paused for
the complete operation. Retain backup and journal until integration is accepted.

## Verify restorability without overwriting dkhando

After separate approval, restore on a disposable local MariaDB 10.5.22 instance
or an administrator-provided isolated server, never classdb2/dkhando. Use a
client account that cannot access live dkhando. Provision an empty schema such
as analytics_restore_check. Inspect the dump privately for target-selection
and destructive directives before restoring. Dump DEFINER clauses may require
the DBA to supply equivalent local definers/privileges; do not silently remove
SQL SECURITY behavior or change canonical objects on the live database.

Example restore command ONLY on the disposable local server, after approval:

    mariadb --host=127.0.0.1 --port="$RESTORE_PORT" --user="$RESTORE_USER" \
      --password analytics_restore_check < "$BACKUP_DIR/dkhando-before.sql"

Verify all 14 CREATE TABLE definitions/constraints, 14 row counts, exactly one
book_shipment procedure and the two scan triggers with their full bodies and
SQL modes/security characteristics. Verify the three account IDs, roles and
subtypes. The protected account hashes must compare equal privately between
source snapshot and restored data; emit only a boolean result, never hashes.
Run the six read-only reports on the restored database and compare to the
pre-load baseline. Test procedure/trigger behavior only in the approved
isolated rehearsal. A successful import alone is insufficient.

Create an owner-only JSON receipt outside Git only AFTER those checks:

    {
      "schema": "dkhando",
      "backup_path": "/absolute/encrypted/private/csc540-backup/dkhando-before.sql",
      "sha256": "actual SHA-256 of the verified backup",
      "restore_test_schema": "analytics_restore_check",
      "restore_verified": true,
      "writers_paused": true,
      "schema_definitions_verified": true
    }

This is an operator attestation, not cryptographic proof of rehearsal. The
loader additionally verifies the backup file, owner-only permissions and digest.
Do not manufacture a receipt to bypass missing backup/restore evidence.

## Narrow recovery procedure (not automatically executed)

Recovery requires explicit approval of the observed partial-state inventory and
a concrete deletion plan. Keep writers paused. Do not restore the full dump over
dkhando, reset tables, or change schema objects. The backup is for isolated
recovery/reconstruction and DBA assistance if preservation cannot be proved.

1. Verify seed_manifest.json's digest against the exact seed used, baseline
   receipt and original journal. Its exact keys cover all 14 seed-owned tables;
   protected accounts 540001–540003 are explicitly excluded. A key range alone
   is not proof of ownership. Snapshot current state with SELECT and intersect
   existing keys with the manifest. Missing seed rows are expected after a
   partial load and are not recreated by recovery.
2. Compare every existing candidate row's non-password values with its seed
   values. Account passwords must still be BOOTSTRAP_REQUIRED, checked as a
   server-side boolean without retrieving their contents. Derive each shipment's
   current_status/delivery_outcome from its committed scan prefix. Check scan
   sequences/timestamps/statuses/hubs and bookings exactly. If sample passwords
   have been initialized or rows changed after loading, stop for manual review.
3. Inspect ALL incoming foreign keys and rows before deleting any parent. Abort
   if any unrelated account subtype, vehicle, shipment, departure, booking or
   scan references a candidate parent. In particular, extra scan or booking rows
   for seed shipments are blockers; they must not be silently cascade-deleted.
   Compare the entire non-seed inventory with the baseline, including protected
   roles/memberships. Resolve uncertain ownership with the DBA, not guesses.
4. Produce an exact per-table key list and expected delete counts for approval.
   In a single explicit transaction, lock the candidate rows and recheck all
   predicates/foreign references. Issue parameterized single-row deletes only
   for approved exact manifest keys AND their verified current values. Never use
   broad BETWEEN predicates, DELETE-all, cascading parent cleanup as a shortcut,
   or foreign_key_checks=0. An executable implementation must check affected-row
   counts after every delete and roll back on any discrepancy.
5. Delete in this order: scan_event; booking; shipment; departure; box_truck,
   refrigerated_van, rail_car; vehicle; lane; hub; shipper, carrier, viewer;
   account. Account deletes must additionally require account_id IN (1..8),
   account_id NOT IN (540001,540002,540003), the expected role and the sentinel
   password. Role deletes use only manifest account IDs 1..8. Stop if any new
   references appear. Never reset AUTO_INCREMENT counters.
6. Before committing, verify all seed keys are absent, all unrelated rows remain
   unchanged, and protected accounts/roles/subtypes match the baseline. Verify
   protected password equality through the approved private backup mechanism,
   returning only a boolean. Commit only if every preservation check passes;
   otherwise roll back and escalate to the DBA. Retain the recovery audit.

No executable DELETE script is supplied because the approved key list and value
predicates must be generated from the actual partial state. This runbook cannot
authorize deletion of unknown or subsequently edited records.
