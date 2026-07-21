# GitLab MR creation guard

1. Add a Workbench-only GitLab merge-request skill that binds the MR title to
   the `HEAD` conventional-commit subject and requires a Markdown file for the
   description.
2. Add a wrapper that rejects manual title/description flags, uses the file
   content with `glab mr create`, and reads the created MR through `glab api`.
3. Add a build test, regenerate docs and plugin outputs, then run the full gate.
