"""Regression coverage for the sync-gitlab-dev skill's core promises.

The old .github/workflows/mirror.yml bot auto-mirrored GitHub dev to GitLab on
every push, bypassing review by design (it opened the MR itself). This skill
replaces that with a manual, branch-and-MR path — these assertions pin the
parts of that replacement most likely to regress silently: no direct push to
GitLab dev/main, no duplicate MRs, and delegation to gitlab-mr-create rather
than a second glab-mr-create implementation.
"""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SYNC_SKILL = REPOSITORY_ROOT / "plugins/workshop-maintainer/skills/sync-gitlab-dev/SKILL.md"
GITLAB_MR_CREATE = REPOSITORY_ROOT / "plugins/workbench/skills/gitlab-mr-create/SKILL.md"
SYNC_SKILL_DIR = REPOSITORY_ROOT / "plugins/workshop-maintainer/skills/sync-gitlab-dev"


def _normalized(path: Path) -> str:
    return " ".join(path.read_text().split())


def test_sync_gitlab_dev_is_registered_in_workshop_maintainer() -> None:
    """Registration is directory membership under the flat plugin tree: a
    plugin ships exactly what lives in its own skills/ dir, so the skill is
    registered iff it exists there with a SKILL.md."""
    assert SYNC_SKILL_DIR.is_dir()
    assert (SYNC_SKILL_DIR / "SKILL.md").is_file()


def test_sync_gitlab_dev_never_pushes_dev_directly() -> None:
    """A direct push to GitLab dev bypasses the approval rule entirely — that
    happened once by mistake and is exactly what this skill exists to prevent."""
    skill = _normalized(SYNC_SKILL)

    assert "Never push directly to GitLab `dev` or `main`" in skill
    assert "sync/from-github" in skill
    assert "force" in skill.lower()


def test_sync_gitlab_dev_avoids_duplicate_merge_requests() -> None:
    """Re-running the skill after a force-push must reuse the open MR, not open
    a second one on the same branch."""
    skill = _normalized(SYNC_SKILL)

    assert "state=opened" in skill
    assert "report its URL and stop" in skill


def test_sync_gitlab_dev_delegates_mr_creation() -> None:
    """MR creation is gitlab-mr-create's exclusive job (see
    test_gitlab_skill_boundaries.py) — this skill must not reimplement it."""
    skill = _normalized(SYNC_SKILL)

    assert "Never call `glab mr create` directly" in skill
    assert "scripts/create-mr" in skill


def test_gitlab_mr_create_permits_the_workshop_dev_via_sync_skill() -> None:
    """The scope note used to blanket-forbid the-workshop; it must now carve
    out dev via sync-gitlab-dev while still forbidding direct use elsewhere."""
    skill = _normalized(GITLAB_MR_CREATE)

    assert "sync-gitlab-dev" in skill
    assert "Do NOT use this directly on the-workshop for anything else" in skill
