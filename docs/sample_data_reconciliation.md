# Official sample-data reconciliation — 2026-11-13

Authority: professor's seven-page **Sample Data for Demo and Testing.docx.pdf** supplied by the user. All seven rendered pages were visually inspected; table values were independently extracted from the PDF and compared with the parsed SQL fixture. Wrapped vehicle subtype cells were transcribed independently and checked visually. The PDF is reference data, not authorization to execute its insertion instructions.

PDF SHA-256: `3e523cb6834f8ddc10699fc40d3f9325ac2fc76c3c36105922ddb54ece7c848a`

Reviewed source SHA-256:
- `sql/01_schema.sql`: `d8348ecfb22d69411b7a5e2c8a644356bbf497c17798e904c10a64b35010d163`
- `sql/02_sample_data.sql`: `f4ece8ff04a80936dbb41f14f674a312016f7da31b2b9d2bd78c54d45d6b169d`

## Result and discrepancies

**All represented operational values match. The schema is not a lossless representation of every descriptive PDF field.** No SQL change was made during this reconciliation.

- Page 1: all 11 hub regions and code-to-ID mappings match. Full hub names have no database column and are absent from seed values. See the complete name mapping below.
- Pages 1–2: all three carrier, four shipper and one viewer roles and subtype memberships match. All eight organization names match the source SQL comments but are not persisted in database columns.
- Page 2: all seven vehicle IDs, owners, home hubs and subtype memberships match, including all four box-truck volumes/ratings, both refrigerated temperature ranges/payloads and rail-car axle count/gauge.
- Page 3: all ten departure vehicles, carriers (via vehicle ownership), directed routes, timestamps and capacities match individually.
- Page 4: all 23 shipment owners, origins, destinations, weights and promised dates match individually. All 22 shipment/departure pairs match; S14 has no booking row.
- Pages 5–7: all 69 scan tuples match individually: shipment ID, sequence, status, hub and timestamp. No missing, extra or altered scan remains. The full normalized comparison evidence is in `sample_data_pdf_evidence.json`.

Representation differences (not operational mismatches):
- C1–C3 map to account IDs 1–3; SH1–SH4 to 4–7; VW1 to 8. Vehicle/departure/shipment prefixes are removed (V101→101, D1→1, S1→1).
- Hub identifiers map as listed below. The five directed lanes are derived from the departure routes rather than separate PDF lane IDs.
- Lowercase PDF roles/statuses use the canonical uppercase database literals. Minute-resolution timestamps have zero seconds appended; no timezone conversion is performed. Numeric scale and embedded unit notation follow the schema (e.g. gauge stored as text).
- Vehicle type is represented by subtype-table membership. Departure carrier is derived through its vehicle. An unbooked shipment is represented by the absence of a booking row, not a nullable departure on shipment.
- Password initialization markers are application setup data absent from the PDF. They must NEVER be replayed over initialized university accounts.

The descriptive-name omissions are existing schema limitations, not errors introduced by the 69-scan correction. The PDF permits schema mapping, but that does not establish that omitted names meet grading expectations. Preserve the mapping appendix for review; adding name columns would require a separately approved schema change and is outside this migration.

## Hub and account mapping

- RDU → 1: Raleigh Hub — Southeast.
- ATL → 2: Atlanta Hub — Southeast.
- MIA → 3: Miami Hub — Southeast.
- JFK → 4: New York Hub — Northeast.
- BOS → 5: Boston Hub — Northeast.
- ORD → 6: Chicago Hub — Midwest.
- STL → 7: St. Louis Hub — Midwest.
- DFW → 8: Dallas Hub — Southwest.
- PHX → 9: Phoenix Hub — Southwest.
- LAX → 10: Los Angeles Hub — West.
- SEA → 11: Seattle Hub — West.

- C1 → 1: Piedmont Freight Lines — Carrier.
- C2 → 2: Atlantic Coast Haulers — Carrier.
- C3 → 3: Plains Rail Co — Carrier.
- SH1 → 4: Triangle Textiles — Shipper.
- SH2 → 5: Oak City Electronics — Shipper.
- SH3 → 6: Carolina Produce Co — Shipper.
- SH4 → 7: Coastal Furniture — Shipper.
- VW1 → 8: Fedex — Viewer.

## Actual verification

Fresh disposable LOCAL schema `csc540_scan69_311697320f9b`, MariaDB 10.5.29, host 127.0.0.1:3307. Neither existing dkhando database was selected or changed. The isolated schema is retained; temporary trigger-scenario rows were rolled back.

- Corrected canonical schema and seed installed successfully. Every non-password seed value and all 14 table counts matched, not just aggregate counts.
- 29 real trigger scenarios passed, including four-stage and five-stage histories, on-time/late delivery, allowed intermediate cycling, invalid starts, sequence errors, backward timestamps, regressions and terminal delivery.
- All six analytics integration checks passed before and after the trigger scenarios.
- `.venv/bin/python -m pytest web_tests/ -q`: **513 passed**.
- `.venv/bin/python -m unittest analytics_checks.test_offline -q`: **17 passed**.

Corrected counts: account 8; carrier 3; shipper 4; viewer 1; hub 11; lane 5; vehicle 7; box_truck 4; refrigerated_van 2; rail_car 1; departure 10; shipment 23; booking 22; scan_event 69.

Scan totals: RECEIVED 22, IN_TRANSIT 19, OUT_FOR_DELIVERY 14, DELIVERED 14, ARRIVED_AT_HUB 0. Shipment states: DELIVERED 14, IN_TRANSIT 5, RECEIVED 3, NULL 1. Outcomes: ON_TIME 9, LATE 5, NULL 9.

Analytics expectations:
- Q1: carrier 1 has 2 box trucks / 1 van / 0 rail cars; carrier 2 has 2 / 1 / 0; carrier 3 has 0 / 0 / 1.
- Q2: 10 departures; departure 1 utilization 75%. Compare tied rows by departure ID, not incidental output order.
- Q3 shipment 1: statuses RECEIVED, IN_TRANSIT, OUT_FOR_DELIVERY, DELIVERED; intervals NULL, 65, 865, 90 minutes.
- Q4: 14 delivered rows; final cumulative carrier totals 18,000 / 9,500 / 3,500 kg for carriers 1 / 2 / 3.
- Q5: departures 1, 2 and 3, each with two distinct shippers.
- Q6: shipment 14 only.

These are real isolated MariaDB results. The 513/17 tests are offline tests. University 10.5.22 was not retested or migrated in this pass; the previous 83-scan baseline remains user-reported pending execution-time preflight. No browser verification was performed in this task.
