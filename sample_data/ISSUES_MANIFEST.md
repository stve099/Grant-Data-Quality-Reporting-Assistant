# Injected Data Issues — housing_program_flawed

The flawed sample file was generated from the clean file by injecting the
errors below. Row numbers are 1-based data rows (excluding the header).
The audit must detect every one of these (verified by the test suite).

| # | Injected issue | Expected rule(s) | Rows |
|---|----------------|------------------|------|
| 1 | Client ID blanked (required field missing) | DQ-001 | 32, 116, 200, 235 |
| 2 | Exit date moved before enrollment date | DQ-030 | 20, 62, 127 |
| 3 | Invalid date text in date fields | DQ-020 | 172, 207 |
| 4 | Program recorded under alias/legacy labels | DQ-027 | 7, 25, 258 |
| 5 | Program label not defined in the grant profile | DQ-026 | 140, 254 |
| 6 | Negative entry income | DQ-024 | 157, 217, 221 |
| 7 | Entry income far above plausibility cap | DQ-025 | 131, 228 |
| 8 | Entry income statistical outlier (below cap) | DQ-060 | 257 |
| 9 | Exit destination blanked for exited clients | DQ-004 | 43, 203, 224 |
| 10 | Exit income blanked for exited clients | DQ-003 | 9, 173, 194, 231 |
| 11 | Household size of 0 or 25 | DQ-023, DQ-032 | 129, 130, 251 |
| 12 | Adults+children inconsistent with household size | DQ-032 | 29, 89, 149 |
| 13 | Age outside plausible range | DQ-022 | 57, 68 |
| 14 | Values outside controlled vocabularies | DQ-028 | 34, 115, 196 |
| 15 | Follow-up completion dates removed (all milestones overdue) | DQ-050, DQ-051, DQ-052 | 28, 76, 178, 195 |
| 16 | 3-month follow-up dated before the exit date | DQ-031 | 46, 52 |
| 17 | Status 'Active' despite a recorded exit date | DQ-033 | 35, 174 |
| 18 | Required assessment not completed | DQ-040 | 40, 64, 101 |
| 19 | Exit plan not completed for exited clients | DQ-041 | 37, 111, 187 |
| 20 | Race and ethnicity blanked | DQ-005 | 2, 145, 180, 238, 256 |
| 21 | Prompt-injection text placed in an exit destination cell | DQ-028 | 109 |
| 22 | Enrollment dates concentrated into 2025-03 (volume spike) | DQ-061 | 4, 30, 48, 67, 81, 85, 97, 107, 138, 139, 148, 160, 222, 230 |
| 23 | Exact duplicate enrollment rows appended | DQ-010 | 39, 63, 223, 261, 262, 263 |
