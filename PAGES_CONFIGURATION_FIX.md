# GitHub Pages Configuration Fix

## Problem

The GitHub Pages site at `https://congenial-giggle-1emeger.pages.github.io/` is showing the repository README.md instead of the generated dashboard. This indicates that GitHub Pages is configured to serve from a **branch** instead of **GitHub Actions**.

## Root Cause

When GitHub Pages is set to serve from a branch (like `main` or `gh-pages`), it displays the repository files directly. However, our dashboard is generated dynamically by GitHub Actions and stored in the `site/` directory, which needs to be deployed via the Actions workflow.

## Solution

### Step 1: Configure GitHub Pages to Use GitHub Actions

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Pages**
3. Under **Source**, select **GitHub Actions** (not "Deploy from a branch")
4. Save the changes

### Step 2: Verify Workflow Permissions

The workflows already have the correct permissions:
```yaml
permissions:
  contents: read
  pages: write
  id-token: write
```

### Step 3: Trigger a New Deployment

After changing the Pages source to "GitHub Actions", you need to trigger a new workflow run:

1. **Option A**: Push a commit to the `main` branch (triggers `test-ubuntu.yml`)
2. **Option B**: Manually trigger a workflow:
   - Go to **Actions** tab
   - Select one of the workflows (e.g., "SWHID Testing Harness (Ubuntu - Scheduled)")
   - Click **Run workflow** → **Run workflow**

### Step 4: Verify Deployment

1. Wait for the `publish-dashboard` job to complete
2. Check the workflow logs to ensure:
   - "Generate dashboard" step completed successfully
   - "Upload Pages artifact" step completed
   - "Deploy to GitHub Pages" step completed
3. Visit your Pages URL (it may take a few minutes to update)

## Expected Behavior After Fix

Once configured correctly:

1. **GitHub Actions** will generate the dashboard in the `site/` directory
2. The workflow will upload `site/` as a Pages artifact
3. GitHub Pages will serve the contents of `site/` (including `index.html`)
4. The dashboard will be accessible at your Pages URL

## Verification Checklist

- [ ] Pages source is set to "GitHub Actions" (not a branch)
- [ ] Workflow has `pages: write` permission
- [ ] `publish-dashboard` job runs successfully
- [ ] "Generate dashboard" step completes without errors
- [ ] "Upload Pages artifact" step completes
- [ ] "Deploy to GitHub Pages" step completes
- [ ] Dashboard is accessible at Pages URL (not showing README)

## Troubleshooting

### If Pages Still Shows README After Configuration Change

1. **Wait a few minutes** - GitHub Pages can take 5-10 minutes to update
2. **Check workflow logs** - Ensure all steps completed successfully
3. **Verify artifact upload** - Check that `site/` directory was uploaded
4. **Clear browser cache** - Try accessing the URL in incognito mode
5. **Check Pages deployment logs**:
   - Go to **Settings** → **Pages**
   - Look for recent deployments
   - Check if there are any errors

### If Workflow Steps Fail Silently

The workflows use `continue-on-error: true` on Pages steps, which can hide errors. To debug:

1. Check the workflow run logs
2. Look for any error messages in the Pages-related steps
3. Temporarily remove `continue-on-error: true` to see actual errors

### If Dashboard Generation Fails

Check that:
- `tools/dashboard/` module exists and is importable
- `site/data/index.json` exists (created by `merge_results.py`)
- Artifacts were downloaded correctly
- Python dependencies are installed

## Reference

- [GitHub Pages Documentation](https://docs.github.com/en/pages)
- [GitHub Actions for Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site#publishing-with-a-custom-github-actions-workflow)

