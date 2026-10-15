# Publishing the static demo

GitHub Pages serves a saved RiskReplay investigation. It supports the ledger,
filters, incident timelines, policy comparison, model evidence and report
downloads. Training, new replays and imports still run in Python locally.

## Build locally

```bash
make check
make pages
```

`make pages` generates the default seeded 1,800-transaction demonstration, then
exports its verified report to `_site/`. The entry point is `_site/index.html`.
Links are relative, so the same directory works at a project URL such as
`https://ah682.github.io/riskreplay/` without a separate base-path setting.

The exporter validates the report and file checksums before copying a fixed set
of HTML, JSON and CSV files. It accepts only owned synthetic runs. It excludes
input archives, fitted model files and the simulation oracle. A manifest records
the run identity, dataset hash, semantic hash and exported file hashes.

Generated output is ignored by Git. Rebuilding replaces only a directory marked
as a previous RiskReplay static build; an unrelated nonempty directory is refused.

## GitHub configuration

In the repository's **Settings → Pages**, choose **GitHub Actions** as the build
source. The [Publish demo workflow](../.github/workflows/pages.yml) runs on pushes
to `main` and can also be started from the Actions tab.

The workflow installs the pinned Python environment, runs lint, compilation and
tests, generates the demo and uploads `_site/` as a Pages artifact. Deployment
starts only after that build succeeds. The deployment job has the Pages and
identity-token permissions required by GitHub; the build job has read-only
repository access.

After a deployment, check the published ledger and its JSON, CSV and HTML links.
`site-manifest.json` provides the identities and checksums needed to compare a
deployment with its source build. A failed build leaves the previous deployment
in place.

GitHub documents the hosting model in [About GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
and the deployment steps in [Using custom workflows with GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
