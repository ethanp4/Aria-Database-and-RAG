# CI/CD

Two GitHub Actions workflows live in `.github/workflows/`:

| File | Runs on | Status |
|---|---|---|
| `ci.yml` | every push and every pull request, any branch | active |
| `cd-azure.yml` | manual only (`workflow_dispatch`) | **stub, not active**: fails on purpose until Azure is set up |

## CI jobs (`ci.yml`)

The four jobs run in parallel. A newer push to the same branch or PR cancels the older run.

### lint
`ruff check .` from the repo root, using `ruff.toml`. The ruleset is deliberately small
(E4/E7/E9, F, B, DJ): real bugs and dead code, not formatting. Migrations and
`advanceddb_project/` are excluded. Findings show up as annotations on the PR diff.

### test
- Python 3.13 with a `postgres:18` service container (database `aria_ci`, user `aria`).
  The test runner creates and drops `test_aria_ci` itself.
- `python manage.py check`: Django system checks.
- `python manage.py makemigrations --check --dry-run`: fails if a model change has no
  migration. Migrations are the only way the schema changes (see CLAUDE.md), so a missing one
  is a build failure.
- `coverage run ... manage.py test --noinput` with branch coverage, measuring app code only
  (migrations, tests and `manage.py` are omitted).
- The coverage report is printed in the log and uploaded as the `coverage-report` artifact
  (HTML + `coverage.xml`, kept 14 days), even when tests fail.
- No coverage threshold is enforced yet (currently about 95%). See open decisions.

`requirements.txt` is UTF-16 with a byte-order mark. pip detects the BOM and decodes it, so CI
installs it directly with no conversion (checked with pip 26 on Python 3.13; the Dockerfile
relies on the same behaviour). Keep the BOM if you edit the file.

### security
| Check | Fails the build? | Why |
|---|---|---|
| `pip-audit -r requirements.txt --strict` | **yes** | A known CVE in a pinned runtime package has a clear fix (bump the pin). `--strict` also fails if a package can't be audited, so nothing is skipped silently. |
| `bandit` full report (`--exit-zero`) | no | Every finding, including low severity, is visible in the log. Today the only hits are two low-severity B105 "hardcoded password" false positives: the `FakeGateway` test tokens `tok_decline` / `tok_timeout_authorize` in `payments/gateway.py`. |
| `bandit -ll -ii` (medium+ severity **and** medium+ confidence) | **yes** | Medium/high findings in a payments app are worth stopping for; low ones are mostly noise and would train people to ignore red builds. |

Bandit scans `aria_project/` and skips tests and migrations. If a medium+ finding is a
genuine false positive, silence that one line with `# nosec BXXX` and a reason, not by
loosening the threshold.

pip-audit needs network access to the PyPI/OSV vulnerability databases; a rare outage there
can fail the job. Re-run it rather than disabling it.

### docker
Builds the repo-root `Dockerfile` with Buildx (layer cache in GitHub Actions cache). Nothing
is pushed. It catches a broken Dockerfile or a dependency that won't install in the image.

## Running the same checks locally

Django 6.1 needs Python >= 3.12. If your host Python is older, use the commands below in
Git Bash from the repo root; they run in the `python:3.13` image and talk to a Postgres on the
host. Adjust `DB_PORT` / `DB_NAME` / credentials to your local database (the user needs
permission to create the `test_<DB_NAME>` database).

```bash
# all CI checks in one throwaway container (repo root, Git Bash)
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/repo" -w /repo \
  -e DB_HOST=host.docker.internal -e DB_PORT=5433 -e DB_NAME=aria -e DB_USER=aria -e DB_PASSWORD=pass \
  -e COVERAGE_FILE=/tmp/.coverage \
  python:3.13 sh -c '
    pip install -q --root-user-action=ignore -r requirements.txt -r requirements-dev.txt &&
    ruff check . &&
    pip-audit -r requirements.txt --strict &&
    bandit -r aria_project -x "*/tests/*,*/migrations/*,*/tests.py" -ll -ii -q &&
    cd aria_project &&
    python manage.py check &&
    python manage.py makemigrations --check --dry-run &&
    coverage run --branch --source=. --omit="*/migrations/*,*/tests/*,*/tests.py,manage.py" manage.py test --noinput &&
    coverage report --skip-covered'
```

Just the tests, in the app image (as in CLAUDE.md):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W)/aria_project:/app" -e DB_HOST=host.docker.internal django python manage.py test
```

With Python >= 3.12 installed locally (`pip install -r requirements.txt -r requirements-dev.txt`):
run `ruff check .`, `pip-audit -r requirements.txt` and the bandit command from the repo root,
and the `manage.py` / `coverage` commands from `aria_project/`.

Docker build check: `docker build -t aria:ci .` from the repo root.

Workflow files themselves: `docker run --rm -v "$(pwd -W):/repo" -w /repo rhysd/actionlint:latest`
(prefix with `MSYS_NO_PATHCONV=1` in Git Bash).

## Dev dependencies (`requirements-dev.txt`)

Never installed in the production image; the Dockerfile only installs `requirements.txt`.
All are pinned so CI results don't change under us.

| Package | Why |
|---|---|
| `ruff` | Linter (the `lint` job). One fast tool instead of flake8 + plugins; config in `ruff.toml`. |
| `coverage` | Measures which code the Django test suite exercises; produces the CI coverage artifact. Works with Django's own test runner, so no pytest needed. |
| `pip-audit` | Checks pinned runtime dependencies against known vulnerability databases (PyPA/OSV). |
| `bandit` | Static security scan of our own Python code (hardcoded secrets, unsafe calls, etc.). |

## Environment variables production must set

Read in `aria_project/aria/settings.py` via django-environ. Variables set in the environment
override the `.env` file; production should use real environment variables (App Service
application settings / Key Vault references), not a `.env` file in the image.

| Variable | Production value | Default if unset (dev only) |
|---|---|---|
| `DJANGO_SECRET_KEY` | long random secret, stored as a secret | an insecure hard-coded dev key |
| `DJANGO_DEBUG` | `False` | `True` |
| `DJANGO_ALLOWED_HOSTS` | comma-separated host names of the site | empty list |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` | production Postgres | none (required) |
| `DB_PORT` | usually `5432` | `5433` |
| `ARIA_PAYMENT_GATEWAY` | a real gateway once one exists | `payments.gateway.FakeGateway` (TEMPORARY, see `docs/follow-ups.md`) |

Development-only variables that production should leave unset: `SAMPLE_ACCOUNT_PASSWORD`,
`DEFAULT_ADMIN_*`, `DEFAULT_STAFF_*` (used by `create_sample_data` / `create_default_accounts`).

## CD (Azure): not active

`cd-azure.yml` is a manual-only stub. Its first step fails with "Azure CD is not set up yet"
until all of the following exist in the GitHub `production` environment:

- Secrets: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (an Entra app
  registration with a federated credential for this repo, so GitHub logs in with OIDC and no
  client secret is stored).
- Variables: `AZURE_ACR_NAME` (container registry name) and `AZURE_WEBAPP_NAME` (App Service,
  Web App for Containers). No real names are chosen yet; these are placeholders.

When configured, it checks out the chosen ref, builds the image, pushes it to ACR tagged with
the commit SHA, and points the Web App at that image.

Things to do before turning it on:
1. The image runs `python manage.py runserver`, which is not a production server. Add a WSGI
   server (e.g. gunicorn, a new runtime dependency) and a production `CMD`.
2. Static files: no `STATIC_ROOT` / `collectstatic` step yet; production needs one (e.g.
   WhiteNoise or a storage account).
3. Migrations: add a release step that runs `python manage.py migrate --noinput` against the
   production database before the new image takes traffic (marked TODO in the workflow).
4. Set the production environment variables above as App Service settings.
5. Add a required reviewer on the `production` environment so a human approves each deploy,
   and only deploy refs that passed CI.
