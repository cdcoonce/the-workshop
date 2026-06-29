# Wiki Sync Infrastructure

Setup guide for the wiki sync system. The actual script and CI stage are bundled as files — this document covers prerequisites and customization.

## How It Works

1. **On merge to default branch**, the CI stage clones the project's `.wiki.git` repo
2. **`sync_wiki.py`** clears the wiki repo, copies all markdown from the wiki source directory, and uses the hand-written `_sidebar.md` (or auto-generates one)
3. **CI commits and pushes** the changes to the wiki repo

## Prerequisites

Set these up before the sync will work:

1. **Wiki enabled** — GitLab project Settings > General > Visibility, features, permissions. Toggle wiki on.
2. **First wiki page** — GitLab doesn't create the `.wiki.git` repo until at least one page exists. Create any page via the GitLab UI first.
3. **`WIKI_PUSH_TOKEN`** — A GitLab Personal Access Token with `api` + `write_repository` scopes. Store it as a **masked** CI/CD variable in the project settings (Settings > CI/CD > Variables).

## Bundled Files

### `scripts/sync_wiki.py`

The sync script. Copy it to the project and adjust these settings:

| Setting | Line | What to change |
|---------|------|----------------|
| `PROJECT_ROOT` | `Path(__file__).resolve().parents[1]` | Adjust `.parents[N]` depth based on where you place the script |
| `WIKI_SOURCE` | `PROJECT_ROOT / "wiki"` | Match the user's chosen wiki folder name |
| `SECTION_ORDER` | `["architecture", "workflows", ...]` | Match the project's wiki sections |
| Sidebar title | `"# Project Docs"` in `build_sidebar()` | Match the project name |

### `scripts/wiki-ci-stage.yml`

A CI stage snippet. Insert its contents into the project's `.gitlab-ci.yml` and adjust:

| Setting | What to change |
|---------|----------------|
| `python scripts/sync_wiki.py` | Match the actual script path in the project |
| `$CI_COMMIT_BRANCH == "main"` | Match the project's default branch |
| `wiki/**/*` in `changes:` | Match the wiki source folder name |
| `stages:` list | Add `wiki` to the top-level stages |

## Local Testing

To test the sync without CI:

```bash
# Clone the wiki repo
git clone https://gitlab.com/<group>/<project>.wiki.git /tmp/wiki-repo

# Run the sync script
python scripts/sync_wiki.py --wiki-dir /tmp/wiki-repo

# Review and push
cd /tmp/wiki-repo
git add -A
git diff --cached  # Review changes
git commit -m "Manual sync"
git push
```
