# Handoff: Claude co-author removal (history rewrite)

Last updated: 2026-11-18

## What was done (2026-10-23)

- Removed the `Co-Authored-By: Claude ... <noreply@anthropic.com>` trailer from all
  38 commits that carried it, using `git filter-branch --msg-filter`.
- Rewritten and force-pushed (with `--force-with-lease`) to `origin`:

  | Branch                     | New tip   |
  |----------------------------|-----------|
  | `master`                   | `48fa501` |
  | `feature/phase2-db`        | `accb062` |
  | `feature/checkout`         | `2b9e5f4` |
  | `feature/foundations`      | `3520cfe` |
  | `docker-and-setup-changes` | `97927ea` |

- Not touched: `brayden` (it never had the trailer).
- Only commit messages changed. Every rewritten commit has the same file tree,
  author, and date as the original (verified for every commit on every branch before
  pushing). Commits that came before the first trailer kept their original hashes.
- Future attribution is off: `.claude/settings.local.json` sets
  `attribution.commit`, `attribution.pr` to `""` and `sessionUrl` to `false`.
  That file stays local: it's listed in `.git/info/exclude`, not in `.gitignore`.

## Current state (checked 2026-11-18)

- No `Co-Authored-By: Claude` trailers on any remote branch.
- Local branches match `origin`, and the working tree is clean.
- Ethan's new `origin/rag` branch (`8dbbf06`, 2026-11-17) is based on the rewritten
  `master`, so his clone is synced and the old history hasn't come back.

## Rules going forward

- Don't add Claude attribution lines to commits or PR descriptions in this repo.
- Anyone with an old clone must **not** `git pull` on top of it, because that merges the old
  commits (with the trailers) back in. Re-clone instead, or run
  `git fetch && git reset --hard origin/<branch>` on each branch (save any
  unpushed work first).

## Leftovers / to-do

- **Backup tags** `backup/pre-coauthor-rewrite/<branch>` still exist locally (never
  pushed). They're the only remaining copy of the pre-rewrite history. The backup
  bundle in the temp scratchpad has since been deleted. Once you're sure nothing
  needs the old history, delete the tags:
  `git tag -l 'backup/*' | xargs git tag -d`
- **Merged PR pages on GitHub** (e.g. #4, #5) still reference the original commits and
  show Claude as co-author. You can't fix that from the repo side.
- **Separate item spotted:** `origin/rag` uses Ollama as the LLM backend, but
  `CLAUDE.md` says "Claude for generation". Either update `CLAUDE.md` or the branch
  so the two agree.
