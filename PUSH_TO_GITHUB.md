# How to put this on GitHub (5 minutes)

This folder is ready to become your public repo. Do this once.

## 1. Create an empty repo on GitHub
- Go to https://github.com/new
- Repository name: `aditya-solar-flare-forecasting` (or any name you like)
- Keep it **Public** (so judges can see it)
- Do **not** add a README/License/gitignore — this folder already has them
- Click **Create repository**

## 2. Push this folder
Open Terminal, then run these commands (replace `YOUR-USERNAME` and the repo name if you changed it):

```bash
cd "/Users/aarryanparakh/antariksh hackathon/PS15_github_repo"

git init
git add .
git commit -m "Aditya-L1 solar flare forecasting — code, results, and docs"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/aditya-solar-flare-forecasting.git
git push -u origin main
```

If it asks you to log in, use your GitHub username and a **personal access token** as the password
(GitHub → Settings → Developer settings → Personal access tokens → generate one with `repo` scope).

## 3. Put the link in your deck
Once it's live, your repo URL is:

```
https://github.com/YOUR-USERNAME/aditya-solar-flare-forecasting
```

The deck already has a placeholder line — replace `[ your-username ]` on the real-data slide with your
actual username.

## Notes
- The `.gitignore` keeps the large raw data files (`.fits`, `.gz`, PRADAN folders) out of the repo on
  purpose. Only your code, docs, and result plots go up. That's what you want.
- Before pushing, open `LICENSE` and replace `[ Your Team Name ]`.
- Optional: after pushing, add a short repo description and a couple of topics
  (`solar-physics`, `space-weather`, `aditya-l1`) on the GitHub page.
