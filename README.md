# ncaab-ingame-logger (public, code only)

This is the logger for a pre-registered study of Polymarket US in-game prices in NCAA men's basketball (holdout B, 2026-27). The repo is public so the commit history time-stamps the logging rules **before** the season. It holds **code only**:
- No prices, books, plays or schedules are committed here.
- There are no artifacts, and logs carry counts and slugs only.
- Raw data goes over an SSH deploy key to a separate **private** repository.

Raw data is never redistributed (Polymarket US terms: personal, non-commercial use). There is no Kalshi data anywhere (CI guard).

## Sampling frame (`config/frame.json`)
- At 08:40 ET the planner lists today's D1 games (ESPN, groups=50) that have a PM US `aec-cbb-*` game-winner market.
- **One link per day (max_links = 1).** The start time *s* is picked from the grid hh:05/:20/:35/:50, 09–22 h ET. The rule takes the *s* that maximises the number of games whose window [tip − 10, tip + 150] fits entirely inside [s, s + 350 min]. Ties go to the earliest *s*.
- Within the link, every listed game is logged from tip − 10 to settle or tip + 170.
- Games with TBD times are excluded.
- With max_links > 1, links are contiguous 350-min jobs with a 10-min overlap, starting at the latest grid slot at or before the first tip − 10. Each link dispatches the next one (chained, never parallel).

## Cadence
- Book polls: every max(3 s, n_active/15) s, with all PM US calls sharing a 15 req/s token bucket (the PM US limit is 20/s).
- ESPN play-by-play: every max(10 s, n/3) s.
- Changed books are written in full, and unchanged polls are written as `hb` records carrying `transactTime`.

## Setup
- Variables: `DATA_REPO` (owner/name of the private data repo), `INGAME_DRY_RUN` (`true` during Oct 28 – Nov 1), `INGAME_SLOT` (written by the planner).
- Secrets: `DATA_DEPLOY_KEY` (SSH write key for the data repo only), `VARS_TOKEN` (fine-grained PAT, Variables read/write).
- Settings: require approval for all outside-collaborator workflow runs. No `pull_request_target` is used anywhere.
- The weekly heartbeat commit (`status/heartbeat.txt`, date and counts only) keeps schedules from auto-disabling after 60 days.
