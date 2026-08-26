# forge profile

<!-- forge:begin meta -->
<!-- forge:wrote a52487fec768c595 -->
<!-- forge:version 0.1.0 -->

forge wrote this file when it surveyed the repository. Regions between
`forge:begin` and `forge:end` markers belong to forge and are rewritten in place by setup
and by update. Everything outside them is yours, and forge never touches it. Each one records
a digest of what forge left there, so an update can tell its own words from someone else's
and stops to ask rather than overwrite them.
<!-- forge:end meta -->

<!-- forge:begin mechanics -->
<!-- forge:wrote 30c039b6d68edba9 -->
## Mechanics

Every command below marked verified was executed in this repository
and observed to succeed. Nothing here was read out of a manifest and assumed. Update leaves
this section exactly as it found it: it records what forge watched happen, and update watches
nothing. Re-run `/forge:setup` to observe it again.

| Mechanic | Command | Status | Found in |
| --- | --- | --- | --- |
| build | `uv build` | verified — exited 0 | supplied to forge setup |
| test | `uv run --extra dev pytest -m 'not integration'` | verified — exited 0 | supplied to forge setup |
| lint | `uv run --extra dev ruff check src tests` | verified — exited 0 | supplied to forge setup |
<!-- forge:end mechanics -->

<!-- forge:begin permissions -->
<!-- forge:wrote 9ee01b6461e09281 -->
## Permissions

forge's authority in this repository. The rules live in `.claude/settings.json`, which is
committed, so everyone working here gets the same ones. Setup only ever adds: no rule that
was already there has been removed.

A Bash rule matches a command by its prefix, so what is denied below is a set of spellings
rather than an operation. Two gaps follow from that and are deliberate. A bare `git push`
cannot be expressed at all, because what it pushes depends on the branch you are on and the
upstream it is tracking, neither of which is in the command. And force-push spellings are
left out: auto mode's classifier already blocks those, and it is the first layer here —
it reasons about destructiveness, where this list reasons about deployment.

Permission mode: **auto** — set by `~/.claude/settings.json`.

Auto mode cannot be set from a repository's own settings, so forge does not write it and
this is the floor a session starts from rather than the mode it is in now. Turning auto
mode on is the user's, in their user settings or in the session itself.

The rules below do not depend on it either way. A session outside auto mode is running
without the classifier this list assumes underneath it, and forge's answer to that is to
say so at startup — never to widen a rule to make up for it. These rules are committed and
shared; the mode is one person's session, and one is no reason to change the other.

Derived from this repository's own CI triggers: `.github/workflows/release.yml`.

### Denied — what can reach a deployed environment

| Operation | Rule | Why |
| --- | --- | --- |
| push a tag | `Bash(git push --tags:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment |
| push a tag | `Bash(git push origin --tags:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment |
| push a tag | `Bash(git push --follow-tags:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment |
| push a tag | `Bash(git push origin --follow-tags:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment |
| push a tag | `Bash(git push origin v[0-9]+.[0-9]+.[0-9]+:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment |
| create a release | `Bash(gh release create:*)` | .github/workflows/release.yml runs on a push of v[0-9]+.[0-9]+.[0-9]+ — job "publish" deploys to the "pypi" environment, and creating a release pushes the tag |
| start release.yml by hand | `Bash(gh workflow run release.yml:*)` | .github/workflows/release.yml can be started by hand — job "publish" deploys to the "pypi" environment |
| start release.yml by hand | `Bash(gh workflow run release:*)` | .github/workflows/release.yml can be started by hand — job "publish" deploys to the "pypi" environment |
| merge a pull request automatically | `Bash(gh pr merge --auto:*)` | auto-merge lands a change with nobody watching it land |

### Asked — what needs the user to say yes

| Operation | Rule | Why |
| --- | --- | --- |
| merge a pull request | `Bash(gh pr merge:*)` | the last irreversible step of a task belongs to the user |

### Allowed — what setup watched work

| Operation | Rule | Why |
| --- | --- | --- |
| run the build command | `Bash(uv build:*)` | setup verified it by running it here |
| run the test command | `Bash(uv run --extra dev pytest -m 'not integration':*)` | setup verified it by running it here |
| run the lint command | `Bash(uv run --extra dev ruff check src tests:*)` | setup verified it by running it here |
<!-- forge:end permissions -->
