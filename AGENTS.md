# DNS Switcher AI+

- This directory is the canonical local source for `pryanus/dns-switcher-ai-plus`.
- The user requested keeping local changes and GitHub synchronized: after requested changes, run focused checks, commit and push verified work. Preserve unrelated edits.
- Rebuild the Windows executable for runtime/UI changes. Keep generated binaries in GitHub Releases, not Git history.
- Release numbering: current public version is 1.0. Use 1.01, 1.02, etc. for small updates and 1.1, 1.2, etc. for large updates. When publishing the next version, ensure the updater understands this numbering and preserves compatibility with v1.0.0. Do not restore old experimental version labels or versioned screenshot archives.
- Never publish user settings, personal hosts, backups, caches, credentials or local paths.
- Never change the real system hosts or network settings during agent tests. Use temporary files; do not probe ChatGPT live.
- Do not label homepage reachability as full functionality. Mark unsupported DNS/DPI cases honestly.
- Keep the dark interface and default favorites Spotify, ChatGPT, Gemini and Claude. Closing the window hides it in the tray; Exit stops workers and quits.
