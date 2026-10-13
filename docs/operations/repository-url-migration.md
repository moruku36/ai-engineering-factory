# Repository URL migration — 2026-10-13

The owner separately authorized renaming **AI Governance Control** from
`moruku36/ai-engineering-factory` to `moruku36/ai-governance-control`.
Repository ID **1372158490** is the stable identity. This change does not authorize
merging these documentation PRs, deploying, or changing access permissions.

## Plan and observed results

1. Checked the destination: absent before rename; no name collision.
2. Inventoried main and all 32 existing branches. There were no open PRs in this
   repository at the preflight check. Existing branches and commits were retained.
3. Checked the repository configuration: no Pages site, repository webhooks,
   deployments, or GitHub deployment environments were present. No hosted Action
   manifest or submodule/deploy configuration was found in the tracked tree.
   App-installation visibility was unavailable through the attempted repository
   API; OAuth, app selection, security settings and external deployment bindings
   have not been changed or independently confirmed.
4. Renamed through GitHub's repository API. Both the old and new API paths now
   resolve to ID **1372158490** and the new full name.
5. Measured HTTP: old repository URL **301** to the new URL; new URL **200**.
   `git ls-remote` on both URLs returned the same main SHA:
   `2e8bbf8f176438e59a3417111a0ff7e825e0d7ea`.
6. Prepared URL updates on `task/url-migration-20261013` from that main SHA.
   Changes go through a Draft PR; human review and merge remain separate.

## Reference inventory

| Location | Treatment |
| --- | --- |
| English/Japanese README and getting-started guide | New clone URL and matching clone-directory examples; package/CLI unchanged |
| Governance roadmap, research, case study and ADR 0004 | New repository links; linked commit SHA and PR numbers retained |
| `pyproject.toml` project URLs | Repository, documentation and issue URLs updated; distribution name unchanged |
| `tasks/examples/sample-task.yaml` | New repository URL for new example tasks |
| `orchestrator/adapters/github.py` | New default repository slug; matching default-publisher test fixtures updated |
| Owner profile and related owner repositories | Separate minimal URL-update branches and Draft PRs; inventory and CI tracked in the migration report |
| Historical `state/handoffs` and explicit approval/test bindings | Preserved; no state/database/approval migration or history rewriting |

The publisher checks the configured origin and canonical PR URL against
`repo_slug`; GitHub's redirect alone does not make these application comparisons
equivalent. New callers should explicitly use `repo_slug="moruku36/ai-governance-control"`
and the new origin URL. Existing signed approvals or durable journals bound to the
old slug are not rewritten, translated or accepted under a new binding. Obtain
fresh human approval for work bound to the new slug. This PR changes the default
for new publisher instances only; it does not weaken origin or approval checks.

Existing clones can update their remote:

```bash
git remote set-url origin https://github.com/moruku36/ai-governance-control.git
```

CLI `ai-factory`, distribution `ai-engineering-factory`, import package
`orchestrator`, schema IDs, environment variables, credential targets and runtime
directories remain unchanged. GitHub Support case 4850510 is a separate matter.

## Redirect constraints and external follow-up

[GitHub's official rename documentation](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository)
documents Git/Web redirects, excluding project Pages URLs and hosted Action
`uses:` references. Never reuse the old repository name: doing so removes the
redirect. Update any externally owned Action consumers or external OAuth/deploy
bindings through their owners; no new permissions or integration configuration
are included here. The current workflows use third-party pinned Actions and
do not host an Action from this repository.

## Rollback

If a verified integration cannot use the new URL, stop the affected integration
and record the error before changing bindings. The owner can rename the same
repository back to the old name after checking that name remains free; compare
ID 1372158490 again and remeasure both HTTP/Git paths. Do not create a replacement
repository under either name, and do not assume redirects survive a second
rename without measurement. If URL PRs are still drafts, leave them unmerged;
if merged later, revert their commits through new PRs. Do not force-push,
rewrite historical commits, migrate signed approvals, or change deploy/security
settings as part of rollback.
