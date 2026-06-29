"""
Sync wiki source directory to a GitLab wiki repository.

Usage (CI):
    python scripts/sync_wiki.py --wiki-dir /tmp/wiki-repo

Usage (local):
    git clone https://gitlab.com/<group>/<project>.wiki.git /tmp/wiki-repo
    python scripts/sync_wiki.py --wiki-dir /tmp/wiki-repo
    cd /tmp/wiki-repo && git add -A && git commit -m "Sync docs" && git push

Customize WIKI_SOURCE and SECTION_ORDER for your project.
"""

import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # Adjust depth for script location
WIKI_SOURCE = PROJECT_ROOT / "wiki"  # Change to match chosen folder name

# Display order for top-level sections (customize per project)
SECTION_ORDER = ["architecture", "workflows", "infrastructure", "instructions"]


def clean_wiki(wiki_dir: Path):
    """Remove all files in wiki_dir except .git/"""
    for item in wiki_dir.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def copy_docs(wiki_dir: Path):
    """Copy wiki source content into wiki_dir, preserving directory structure."""
    for md_file in WIKI_SOURCE.rglob("*.md"):
        rel = md_file.relative_to(WIKI_SOURCE)
        dest = wiki_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md_file, dest)


def build_sidebar(wiki_dir: Path) -> str:
    """Generate _sidebar.md from the wiki directory structure."""
    lines = ["# Project Docs", ""]  # Customize title
    lines.append("[**Home**](home)")
    lines.append("")

    dirs = sorted(
        [d for d in wiki_dir.iterdir() if d.is_dir() and d.name != ".git"],
        key=lambda d: SECTION_ORDER.index(d.name) if d.name in SECTION_ORDER else 999,
    )

    for section_dir in dirs:
        lines.append(f"## {section_dir.name.title()}")
        lines.append("")
        _build_tree(section_dir, wiki_dir, lines, depth=0)
        lines.append("")

    return "\n".join(lines)


def _build_tree(directory: Path, wiki_root: Path, lines: list, depth: int):
    """Recursively build sidebar entries for a directory."""
    indent = "  " * depth
    children = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))

    for child in children:
        if child.name.startswith(".") or child.name == "_sidebar.md":
            continue
        if child.is_dir():
            dir_link = _find_index(child, wiki_root)
            dir_name = _format_name(child.name)
            if dir_link:
                lines.append(f"{indent}- **[{dir_name}]({dir_link})**")
            else:
                lines.append(f"{indent}- **{dir_name}**")
            _build_tree(child, wiki_root, lines, depth + 1)
        elif child.suffix == ".md":
            if child.stem.lower() in ("overview", "readme"):
                continue
            title = _title_from_file(child)
            rel = child.relative_to(wiki_root).with_suffix("")
            link = str(rel).replace("\\", "/")
            lines.append(f"{indent}- [{title}]({link})")


def _find_index(directory: Path, wiki_root: Path) -> str | None:
    """Find an overview.md or readme.md in a directory and return its wiki link."""
    for name in ("overview.md", "readme.md"):
        candidate = directory / name
        if candidate.exists():
            rel = candidate.relative_to(wiki_root).with_suffix("")
            return str(rel).replace("\\", "/")
    return None


def _title_from_file(path: Path) -> str:
    """Derive a display title from a markdown file (first H1 or formatted filename)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    return line[2:].strip()
    except Exception:
        pass
    return _format_name(path.stem)


def _format_name(name: str) -> str:
    """Convert a filename/dirname into a readable title."""
    if name.isupper():
        return name
    return name.replace("-", " ").replace("_", " ").title()


def main():
    parser = argparse.ArgumentParser(description="Sync wiki to GitLab wiki repo")
    parser.add_argument("--wiki-dir", required=True, help="Path to cloned wiki repo")
    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    if not (wiki_dir / ".git").exists():
        raise SystemExit(f"{wiki_dir} is not a git repo. Clone the wiki repo first.")

    print(f"Cleaning wiki directory: {wiki_dir}")
    clean_wiki(wiki_dir)

    print(f"Copying docs from: {WIKI_SOURCE}")
    copy_docs(wiki_dir)

    static_sidebar = WIKI_SOURCE / "_sidebar.md"
    if static_sidebar.exists():
        print(f"Using hand-written _sidebar.md from {static_sidebar}")
        shutil.copy2(static_sidebar, wiki_dir / "_sidebar.md")
    else:
        print("Generating _sidebar.md from directory structure")
        sidebar = build_sidebar(wiki_dir)
        (wiki_dir / "_sidebar.md").write_text(sidebar, encoding="utf-8")

    print("Done. Review changes in the wiki repo, then commit and push.")


if __name__ == "__main__":
    main()
