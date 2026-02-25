# Verifying v2 Directory SWHIDs Against Real Git

This guide explains how to verify expected v2 directory SWHIDs against a real Git implementation.

## Source of Expected Values

The v2 expected values in `config.yaml` (`expected_swhid_sha256`) come from **real Git**:

- **Content**: Uses `tools/generate_sha256_expected.py`, which creates a SHA256 Git repo, adds the file, and reads the blob hash from `git ls-files --stage`.
- **Directory**: The correct reference is a Git SHA256 repo with the **payload directory contents at the repo root** (not wrapped in a subdirectory). See "Manual verification" below.

## Manual Verification with Git

To verify a directory SWHID against real Git:

```bash
# 1. Create a temporary SHA256 Git repository
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"
git init --object-format=sha256

# 2. Configure Git for SWHID consistency (match test harness)
git config core.autocrlf false
git config core.filemode true
git config core.precomposeunicode false
git config core.quotepath false

# 3. Copy the payload directory CONTENTS to the repo root (not as a subdirectory!)
# For payloads/directory/empty/ (which contains .gitkeep):
cp /path/to/swhid-rs-tools/payloads/directory/empty/.gitkeep .

# For payloads/directory/simple/ (which has file1.txt, file2.txt):
cp /path/to/swhid-rs-tools/payloads/directory/simple/* .

# For nested directories, copy the full structure to repo root:
cp -r /path/to/swhid-rs-tools/payloads/directory/nested/* .

# 4. Add and get tree hash
git add .
git write-tree
# Output is the SHA256 tree hash - format as swh:2:dir:<hash>
```

**Critical**: The payload directory contents must be at the **repo root**. The `generate_sha256_expected.py` script previously copied the payload as a subdirectory (`temp_dir/dirname/`), which produces a different (incorrect) tree hash. The `git-cmd` implementation does it correctly by moving contents to root (see `implementations/git-cmd/implementation.py` lines 239–246).

## Using generate_sha256_expected.py

The script `tools/generate_sha256_expected.py` uses real Git. For directories, it should copy contents to the repo root. If you see discrepancies:

1. Run with `--dry-run` to see what Git produces:
   ```bash
   python tools/generate_sha256_expected.py config.yaml --dry-run
   ```

2. Compare with the `git-cmd` implementation logic (which puts contents at root).

3. Regenerate expected values after fixing the script:
   ```bash
   python tools/generate_sha256_expected.py config.yaml
   ```

## Cross-Check: Software Heritage Archive

The Software Heritage archive API can verify content SWHIDs (v1, SHA1). For v2/SHA256, the archive may not yet expose directory identifiers. Check:

- `https://archive.softwareheritage.org/api/1/content/sha256:<hash>/` for content
- Directory v2 support may be limited

## Known Issues

None. Both `generate_sha256_expected.py` and `swhid-rs` correctly place payload contents at the repo root and use the configured hash (SHA256) for all child object IDs when computing v2 directory SWHIDs.
