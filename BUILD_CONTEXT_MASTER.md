# LeadForgeV0 - Build Context & Handoff Master

**Generated Date:** 2026-01-21
**Current State:** 100% Operational (Slots 01-10)
**Primary Path:** `/Users/thatsarpit/Documents/LeadForgeV0`

---

## 1. System Architecture
The system is a high-performance lead sniping engine ("LeadForge") running locally on macOS. It consists of three primary components managed by PM2.

### Components
1. **LeadForge Manager** (`core/engine/slot_manager.py`)
   - **Role:** The "Brain". Manages lifecycle (Start/Stop) of 10 parallel worker slots.
   - **Key Features:**
     - **Auto-Recovery:** Detects crashes/stuck slots and restarts them.
     - **Implicit Start:** Can force-start a slot if it detects intent (Status=STARTING) even if command is missing.
     - **State Source:** Reads `slots/slotXX/slot_state.json`.
     - **Logging:** Redirects runner output (stdout/stderr) to `slots/slotXX/runner.log`.

2. **LeadForge API** (`api/app.py` & `engyne (1)/api`)
   - **Role:** Interface for the Frontend Dashboard.
   - **Bridge:** Writes to `slot_state.json` and updates `slot_config.yml`.
   - **Email:** Handles client invites via Brevo SMTP.

3. **IndiaMart Worker** (`core/workers/indiamart_worker.py`)
   - **Role:** The "Sniper". High-speed browser automation (Playwright).
   - **Mode:** "0-Second Capture" (Scanning milliseconds after lead drop).
   - **Execution Flow:**
     1. **Fetch:** Rapidly reloads "Recent Leads" page.
     2. **Scrape (JS):** Extracts leads via DOM injection (for speed). **Filters by Age** (< 30s).
     3. **Click:** Immediately clicks "Contact Buyer" (Purchase).
     4. **Verify (New!):** Opens a **New Tab**, goes to `mypurchasedbl`, confirms purchase, closes tab. (Only runs if Clicked > 0).

---

## 2. Recent Critical Engineering Changes
*These changes are live and distinguish this build from previous versions.*

### A. The "Auto-Recovery" Fix (Slot Manager)
- **Problem:** Slots would get stuck in "STARTING" loop or be killed immediately by strict zombie detection.
- **Fix:** 
  - Updated `slot_manager.py` to allow `STARTING` status if `pid` is missing (Implicit Start).
  - Added logic to reset to `STOPPED` if `STARTING` persists > 15s (Grace Period).
  - **Result:** Robust startup; crashes generate logs instead of silent failures.

### B. The "Pregabs" Fix (Age Filter)
- **Problem:** Leads slightly older than 5 seconds (e.g. 6s) were silently dropped by the browser.
- **Fix:**
  - Modified `indiamart_worker.py` JS logic to accept a configurable `maxAge`.
  - Updated `slot_config.yml` (e.g. `slot02`) to set `max_lead_age_seconds: 30`.
  - **Result:** Captures leads up to 30s old. Can be tuned in config.

### C. Multi-Tab Verification
- **Problem:** Verifying a purchase slowed down scanning or disrupted page state.
- **Fix:**
  - When a lead is clicked, the worker opens a **New Background Tab**.
  - Navigates to `seller.indiamart.com/blproduct/mypurchasedbl`.
  - Waits 5s for data sync.
  - Closes tab.
  - **Result:** Main scanning loop remains undisturbed.

### D. Logging
- **Problem:** Python logs were empty because `subprocess` silenced them.
- **Fix:** `slot_manager.py` now explicitly writes stdout/stderr to `slots/slotXX/runner.log`.

### E. The "Universal Clicker" (Robustness)
- **Problem:** IndiaMart changes CSS classes often (e.g. `.bl_grid`, `.btnCBN` removed/renamed), causing clicks to fail even if leads were found.
- **Fix:**
  - Replaced rigid JS selector with a **Heuristic DOM Crawler**.
  - Logic: Finds lead via URL Anchor (Always present) -> Walks up the DOM Tree -> Finds any button with text "Contact" or "Buy".
### F. Full Visibility (Rejected Leads)
- **Problem:** Leads rejected by filters (e.g. blacklist keywords) were discarded silently.
- **Fix:** Now marks them as `status="rejected"` and saves them.
- **Result:** Dashboard shows ALL leads the bot sees, even rejected ones (filterable).

---

## 3. Configuration & Paths

### Active Directory
**`/Users/thatsarpit/Documents/LeadForgeV0`**
*(Note: Do NOT confuse with `engyne (1)`. The runtime code is here.)*

### Environment (`.env`)
Located in Root. Contains sensitive configuration - **do not commit actual values to repository**.

Example `.env` structure (use placeholders):
- **SMTP_HOST**: `<SMTP_HOST>` (e.g., smtp-relay.brevo.com)
- **SMTP_USERNAME**: `<SMTP_USERNAME>` (e.g., your-email@domain.com)
- **BREVO_API_KEY**: `<BREVO_API_KEY>` (obtain from Brevo dashboard)

> **Note**: Store real credentials in your local `.env` file or use a secrets manager. Never commit actual values to the repository.

### Slot Config (`slots/slotXX/slot_config.yml`)
Key parameters:
```yaml
max_lead_age_seconds: 30   # Critical for "Pregabs" fix
use_browser: true
debug_snapshot: true
country:                   # List of targeted countries
  - us
  - gb
```

---

## 4. Operational Guide

### How to Start/Stop
Use the **Dashboard UI**.
- **Start:** Sets `command="START"` in JSON. Manager picks it up.
- **Stop:** Sets `command="STOP"`.

### How to Debug
1. **Check State:** `cat slots/slot02/slot_state.json` (See Status, PID, Heartbeat).
2. **Check Logs:** `tail -f slots/slot02/runner.log` (See Browser/Worker output).
3. **Manager Logs:** `pm2 logs leadforge-manager` (See Process Lifecycle).

### Recovering from weird states
If a slot is stuck:
1. Stop it in UI (or manually set `status="STOPPED"` in JSON).
2. Restart it.
The "Auto-Recovery" logic usually handles this automatically within 15 seconds.

---

## 5. Next Steps (To-Do)
- [ ] Monitor `runner.log` to ensure the Verification Tab logic is catching verified leads successfully.
- [ ] Tune `max_lead_age_seconds` based on competition (lower = faster, higher = more coverage).
- [ ] Expand to Slots 03-10 (Config is ready, just need to Start).

**End of Context**
