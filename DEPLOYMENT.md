# Publish on Streamlit Community Cloud

The app is prepared for Streamlit Community Cloud with `streamlit_app.py`,
`requirements.txt`, and `.streamlit/config.toml` at repository level. The
reviewed SEC and backtest CSV snapshots must be committed because a Cloud app's
local filesystem is ephemeral.

## 1. Build and verify the publishable snapshots locally

```powershell
.venv\Scripts\Activate.ps1
$env:THIRTEENF_SEC_USER_AGENT = "Your Name your-email@example.com"
thirteenf --source sec --start-year 2014
python scripts/build_security_master.py --output data/security_master.candidate.csv
# Review candidate changes before replacing data/security_master.csv.
python scripts/build_backtests.py --start 2014-01-01
pytest -q
streamlit run streamlit_app.py
```

Do not commit `.streamlit/secrets.toml`, `data/raw/`, or `data/prices/`.

## 2. Put the project in a GitHub repository

Create an empty repository in your GitHub account, then from this project
directory run the commands GitHub displays. For a new local repository they
normally resemble:

```powershell
git init
git add .
git commit -m "Publish 13F research dashboard"
git branch -M main
git remote add origin https://github.com/YOUR-USER/YOUR-REPOSITORY.git
git push -u origin main
```

Before committing, check that the CSV snapshots are included and secrets/raw
price downloads are not:

```powershell
git status --short
git check-ignore -v .streamlit/secrets.toml data/prices/adjusted_close.csv
```

## 3. Deploy

1. Sign in at https://share.streamlit.io and connect the GitHub account.
2. Select **Create app** and choose the repository and `main` branch.
3. Set the entrypoint to `streamlit_app.py`.
4. In Advanced settings, choose Python 3.12.
5. Leave SEC refresh disabled for a public deployment. Optional Secrets:

   ```toml
   THIRTEENF_SEC_USER_AGENT = "Your Name your-email@example.com"
   THIRTEENF_ENABLE_SEC_REFRESH = "false"
   ```

6. Deploy, open the assigned `*.streamlit.app` URL, and share that URL.

## Updating published data

Run ingestion and backtests locally, review the changed processed CSVs, commit,
and push. Community Cloud redeploys the updated repository automatically. This
is safer and more reproducible than allowing every public visitor to trigger a
large SEC refresh.
