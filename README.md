# OptiSCPI

A Streamlit prototype for comparing SCPI (Sociétés Civiles de Placement Immobilier) against three investor profiles. The interface is in French; code identifiers and comments are in English.

## Run locally

```bash
uv sync
export OPTISCPI_ACCESS_CODE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run streamlit run streamlit_app.py
```

Set `OPTISCPI_ACCESS_CODE` as a server environment variable (or in your hosting provider's secret manager); never commit it. Use a random value of at least 32 characters. The app uses this code to sign a 30-day token stored in a `Secure`, `SameSite=Strict` cookie. Serve the app over HTTPS in production. Changing the access code invalidates existing cookies. Rotate any access code that was previously committed or shared.

`extra-streamlit-components` does not support `HttpOnly` cookies, so the browser-side token is readable by same-origin JavaScript. Streamlit's client IP is also not suitable for enforcing login limits. For a public deployment, put the app behind an identity-aware reverse proxy that issues `HttpOnly` sessions and rate-limits authentication attempts; do not treat the shared access code alone as strong user authentication.

The app opens with clearly labeled fictional sample data. To connect a Google Sheet, set `SHEET_ID` near the top of `scpi_data.py`. The workbook must be readable without signing in (for example, shared as "Anyone with the link"). Private-sheet authentication is not included in this first draft.

## Configure the workbook

Worksheet names are mapped in `WORKSHEETS` in `scpi_data.py`. Rename the tabs there to match your workbook. Keep the column headers below in English, or adapt the corresponding mapping/fields in `scpi_data.py`.

| Worksheet | Required columns | Purpose |
| --- | --- | --- |
| `SCPI` | `scpi_id`, `name`, `manager`, `strategy`, `market`, `discount`, `main_sectors`, `main_regions` | One row per SCPI; `discount` is numeric in percent, and `description` is optional. |
| `Criteres` | `criterion_key`, `label`, `category` | One row per scoring criterion. |
| `Notes` | `scpi_id`, `criterion_key`, `score` | One row per SCPI and criterion; score from 0 to 100. |
| `Ponderations` | `profile`, `criterion_key`, `weight` | One row per profile and criterion; profile names: `Équilibre`, `Stabilité`, `Performance`. |
| `Indicateurs` | `scpi_id`, `label`, `value`, `unit`, `order` | Display indicators on each SCPI card; `order` is optional. |
| `Data` | B: name, H: debt rate, I: liquidity rate, L: discount | Rows 2–117 are joined to SCPI records by name and shown on the detail sheet. |

The five category labels expected by the interface are `Structure financière`, `Diversification`, `Sécurité locative`, `Maturité`, and `Rentabilité`. The `category` value in `Criteres` must match one of these labels. Each criterion key should be unique, and each SCPI ID should be consistent across all tabs.

The full ranking shows the place, SCPI name, profile score, discount, major sectors, and major regions. Select a SCPI name to open its detail sheet. `main_sectors` and `main_regions` are displayed as provided, so separate multiple values with a comma or middle dot.

A profile score is the weighted average of the available criterion scores:

```text
sum(score × weight) / sum(weight)
```

Weights can be entered as percentages or any other positive scale; they are normalized automatically. A category score is the unweighted average of the available criteria in that category. Numeric values can use a comma decimal separator.

## Notes

- The CSV endpoint reads a worksheet by tab name. Keep the `WORKSHEETS` keys unchanged when changing tab names; `fund_details` maps to `Data` by default.
- Data is cached for 15 minutes. Restarting the app or clearing Streamlit's cache refreshes it immediately.
- This prototype illustrates a comparison method, not investment advice. Replace sample figures with verified source data and review your scoring methodology before publishing.
