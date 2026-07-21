# Dev-first integration guard

1. Require workflow skills to resolve the repository integration branch from
   project instructions and CI configuration rather than defaulting to `main`.
2. Record Workshop's GitHub `dev` → mirror → GitLab MR promotion path.
3. Add regression coverage, regenerate docs and distributions, and run the
   complete gate before pushing only `dev`.
