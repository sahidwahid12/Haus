# Changelog

All notable changes to **Haus** (Android app + backend).

## [1.5]

### Fixed
- **On-screen CTRL / ALT modifiers now work.** They are sticky and applied to the next
  keystroke — including letters typed on the soft keyboard — so `CTRL`+`C`, `CTRL`+`D`
  and `ALT`+`F` send the real control sequence to the shell.
- **Terminal white screen after login / register.** The WebView now paints the Haus dark
  background up front, loads the local xterm assets on stricter WebViews (API 30+), and
  surfaces a notice if the terminal page fails to load.

### Changed
- **Container memory limit raised to 2 GB** (was 512 MB — real workloads like
  `npm install` were being OOM-killed). The in-container welcome banner reports the new limit.
- **Inter-container network isolation hardened.** Every user container now runs on a
  dedicated bridge network with ICC (inter-container communication) disabled, so one account
  cannot reach another's sandbox over TCP/ICMP. The backend host and outbound internet
  still work.
- **Root SSH bridge key is restricted.** Only accounts listed in `WS_ROOT_SSH_USERS`
  (default `broyaseele4`) may fetch the runtime root key via `GET /api/root-ssh`;
  every other account gets `403`.

### Added
- Detailed `README.md`: architecture diagram, REST/WS API reference, backend internals,
  Android app walkthrough, 9Router gateway guide, build steps and a Download section
  pointing at GitHub Releases.
- `.gitignore` that keeps local SDK paths, build artifacts, caches and secrets out of git.
