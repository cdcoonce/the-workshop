# Root README structure

The template and writing rules for the front-door `README.md`. It is a landing page:
what this is, how to run it, where to look next. Depth lives in `docs/` and the README
links to it instead of repeating it. Near 150 lines; the checker reports past the bar.

---

## Section template

```markdown
# Project Name

![Language](https://img.shields.io/badge/...) ![Framework](https://img.shields.io/badge/...) ![Tool](https://img.shields.io/badge/...)

One paragraph: what this is and the problem it solves. Bold the key technology or
product type.

---

## How it fits together

One short paragraph or one small Mermaid diagram of the major components, then a
link: "The full picture is in [architecture](docs/reference/architecture.md)."

---

## Getting started

### Prerequisites

### Install

### Run

### Test

The minimal, copy-pasteable path to a first successful run. Anything conditional,
optional, or environment-specific is a how-to guide; link to it.

---

## Documentation

- **Reference**: [architecture](docs/reference/architecture.md), [module map](docs/reference/module-map.md), [data flow](docs/reference/data-flow.md), [conventions](docs/reference/conventions.md)
- **How-to guides**: [run and deploy](docs/how-to/run-and-deploy.md), [recover a failed partition](docs/how-to/recover-a-failed-partition.md)
- **Explanation**: [about the partition scheme](docs/explanation/partition-scheme.md)

Link only what exists. Once the hub (`docs/README.md`) exists, link it first.

---

## Contact

- **Name**: email@company.com

---

## License

**Internal Use Only – Company Name**
Proprietary software. © [Year] [Company]. All rights reserved.

<!-- repo-docs: mode=landing baseline=<commit-sha> covers=pyproject.toml,.env.example,.gitlab-ci.yml,src/main.py -->
```

Sections that used to live here and now have a mode:

| Old README section    | Mode      | Home                                                              |
| --------------------- | --------- | ----------------------------------------------------------------- |
| Environment variables | reference | `docs/reference/conventions.md` or a dedicated `configuration.md` |
| Usage examples        | how-to    | one `docs/how-to/<goal>.md` per goal                              |
| API reference         | reference | `docs/reference/api.md`                                           |
| Troubleshooting table | how-to    | `docs/how-to/troubleshoot-<area>.md`                              |
| Folder structure      | reference | `docs/reference/module-map.md`                                    |
| Architecture diagrams | reference | `docs/reference/architecture.md`, one small overview may stay     |

A table of contents is optional and only earns its place past about 80 lines.

---

## Writing rules

- **Be specific over generic.** "Run `uv run dagster dev`" beats "Start the
  development server." Use actual commands, paths, and variable names.
- **Write for the new team member.** General engineering skill, zero project context.
- **Bold key terms and product names** on first mention so the page scans.
- **Code examples must be runnable.** Copy them from the codebase.
- **Always include a Contact section.** Ask who maintains the project.
- Badges: 3-6, directly under the title; see [badge-reference.md](badge-reference.md).
- One diagram at most on the landing page; the rest belong in reference docs, per
  [mermaid-guidelines.md](mermaid-guidelines.md).
- No section carries a full procedure, a full option table, or a design discussion.
  Each of those is one link.

---

## Front-door anchors

A README goes stale on a small set of files: dependency manifests, env templates, CI
configs, and entry points. Those are what its `covers` list records, not every source
file the deep docs cover.

## Hand-written READMEs

A README without a provenance footer is someone's work. Show what would change and
confirm before overwriting; the owner may want parts kept. A README carrying the
legacy `readme-generator` or `repo-reference-docs` footer is stamped: update it in
place and re-stamp with `mode=landing`.
