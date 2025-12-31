# Analysis: swhid-rs Permission Handling on Windows

## Current Situation

### Test Results
- **Rust on Windows**: 93.8% pass (75/80 pass, 4 fail, 1 skip)
- **Rust on Ubuntu/macOS**: 98.8% pass (79/80 pass, 1 skip)
- **Remaining failures on Windows**:
  1. `permissions_dir` - SWHID mismatch
  2. `comprehensive_permissions` - SWHID mismatch  
  3. `mixed_types` - SWHID mismatch
  4. `synthetic_repo` - SWHID mismatch

### Working Implementations
- `git` and `git-cmd` both **PASS** all permission tests on Windows
- They use the same Git repository approach we're trying to use

## Code Analysis

### How swhid-rs Handles Permissions

#### 1. Permission Source Creation (`directory.rs:195-211`)
```rust
let permission_source: Box<dyn PermissionsSource> = match opts.permissions_source {
    PermissionsSourceKind::Auto => {
        Box::new(AutoPermissionsSource::new(root)?)
    }
    PermissionsSourceKind::GitIndex => {
        let repo = git2::Repository::open(root)?;
        Box::new(GitIndexPermissionsSource::new(repo, root.to_path_buf()))
    }
    // ...
}
```

**Key Point**: When using `Auto`, it discovers the Git repo by walking up from `root`. When using `GitIndex`, it opens the repo at `root` directly.

#### 2. Auto Source Discovery (`permissions.rs:435-465`)
```rust
pub fn new(_root: &Path) -> Result<Self, SwhidError> {
    let mut current = Some(_root);
    while let Some(path) = current {
        let git_dir = path.join(".git");
        if git_dir.exists() {
            match git2::Repository::open(path) {
                Ok(repo) => {
                    return Ok(Self {
                        inner: Box::new(GitIndexPermissionsSource::new(
                            repo,
                            path.to_path_buf(),  // <-- Uses discovered path as root
                        )),
                    });
                }
                // ...
            }
        }
        current = path.parent();
    }
    // Fall back to filesystem
}
```

**Key Point**: The `root` passed to `GitIndexPermissionsSource` is the **discovered repository root**, not the processing root.

#### 3. Git Index Permission Lookup (`permissions.rs:188-215`)
```rust
fn executable_of(&self, path: &Path) -> Result<EntryExec, SwhidError> {
    // Get relative path from repo root
    let rel_path = path
        .strip_prefix(&self.root)  // <-- Strips repo root from file path
        .map_err(|_| SwhidError::InvalidFormat(format!(
            "Path {} is not under repository root {}",
            path.display(),
            self.root.display()
        )))?;

    // Convert to forward slashes for Git
    let git_path = rel_path.to_string_lossy().replace('\\', "/");

    let index = self.repo.index()?;
    
    // Find entry in index
    if let Some(entry) = index.get_path(Path::new(&git_path), 0) {
        let mode = entry.mode;
        let executable = (mode & 0o111) != 0 || mode == 0o100755;
        Ok(EntryExec::Known(executable))
    } else {
        Ok(EntryExec::Unknown)  // <-- Returns Unknown if not in index!
    }
}
```

**Key Point**: If the file path doesn't match what's in the Git index, it returns `Unknown`, which then gets resolved based on `PermissionPolicy`.

#### 4. File Processing (`directory.rs:321-342`)
```rust
} else if ft.is_file() {
    let bytes = fs::read(entry.path())?;
    let id = hash_content(&bytes)?;

    // Use permission source to determine executable bit
    let exec = permission_source.executable_of(&entry.path())?;  // <-- Full filesystem path
    let perms = resolve_file_permissions(
        exec,
        opts.permissions_policy,
        &entry.path(),
    )?;
    let mode = perms.to_swh_mode_u32();
    // ...
}
```

**Key Point**: `entry.path()` is the **full filesystem path** (e.g., `/tmp/xyz/repo/file.txt`).

## The Problem

### Path Resolution Issue

When we:
1. Create Git repo at `/tmp/xyz/repo`
2. Copy files to `/tmp/xyz/repo/file.txt` (directly in repo root)
3. Run `git add .` → Git index has `file.txt`
4. Run `git update-index --chmod=+x file.txt` → Git index has `file.txt` with mode `100755`
5. Pass `/tmp/xyz/repo` to `swhid dir` with `--permissions-source auto`

Then:
- `AutoPermissionsSource::new("/tmp/xyz/repo")` discovers repo at `/tmp/xyz/repo`
- Creates `GitIndexPermissionsSource` with `root = "/tmp/xyz/repo"`
- When processing `file.txt`, `entry.path()` = `/tmp/xyz/repo/file.txt`
- `executable_of("/tmp/xyz/repo/file.txt")` strips prefix → `file.txt`
- Looks up `file.txt` in Git index → **Should find it!**

### Potential Issues

1. **Path Normalization**: Windows paths use backslashes, but Git uses forward slashes. The code does `replace('\\', "/")`, but there might be edge cases.

2. **Index Not Refreshed**: After `git update-index --chmod=+x`, the index might not be immediately readable by `git2`. We might need to refresh or reload the index.

3. **Relative Path Mismatch**: The paths in our `source_permissions` dict are relative to the source directory, but when we copy to repo root, the Git index paths might not match.

4. **Timing Issue**: The Git index might not be written to disk immediately after `git update-index`, and `git2::Repository::index()` might read a stale index.

## Proposed Solutions

### Solution 1: Verify Index State (Recommended First Step)

Add verification that permissions are actually set in the Git index before calling swhid-rs:

```python
# After setting permissions, verify they're in the index
for rel_path, is_executable in source_permissions.items():
    if is_executable:
        result = subprocess.run(
            ["git", "ls-files", "--stage", rel_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if parts and parts[0] != '100755':
                logger.warning(f"Permission not set correctly for {rel_path}: {parts[0]}")
```

### Solution 2: Use Explicit GitIndex Source

Instead of `--permissions-source auto`, use `--permissions-source git-index` explicitly. This avoids the discovery step and ensures we're using the Git index directly.

**However**: This requires `Repository::open(root)` to work, which means `root` must be the repo root. We're already doing this, so this should work.

### Solution 3: Refresh Git Index

After setting permissions, explicitly refresh the Git index to ensure it's written to disk:

```python
# After all git update-index calls
subprocess.run(
    ["git", "update-index", "--refresh"],
    cwd=repo_path,
    check=True,
    capture_output=True,
    encoding='utf-8',
    errors='replace'
)
```

### Solution 4: Use git2 Library Directly (Most Robust)

Instead of using `git` commands, use the `git2` Python library (pygit2) to directly manipulate the Git index. This ensures the index is in memory and immediately available:

```python
import pygit2

repo = pygit2.Repository(repo_path)
index = repo.index

# Add files
index.add_all()
index.write()

# Set permissions
for rel_path, is_executable in source_permissions.items():
    if is_executable:
        try:
            entry = index[rel_path]
            entry.mode = 0o100755  # Executable
            index.add(entry)
        except KeyError:
            logger.warning(f"File {rel_path} not in index")

index.write()  # Write to disk
```

**Note**: This requires `pygit2` as a dependency, which might not be available.

### Solution 5: Debug Path Resolution

Add logging to see what paths are being looked up:

```python
# Before calling swhid-rs, log what's in the Git index
result = subprocess.run(
    ["git", "ls-files", "--stage"],
    cwd=repo_path,
    capture_output=True,
    text=True,
    encoding='utf-8',
    errors='replace'
)
logger.info(f"Git index contents:\n{result.stdout}")
```

Then compare with what swhid-rs is trying to look up.

## Recommended Approach

1. **Immediate**: Add Solution 1 (verification) and Solution 3 (refresh) to ensure permissions are set correctly
2. **Debug**: Add Solution 5 (logging) to see what's actually in the Git index vs what swhid-rs is looking for
3. **If still failing**: Consider Solution 4 (pygit2) for more direct control, or investigate if there's a bug in swhid-rs's path resolution

## Testing Strategy

1. Create a minimal test case with one executable file
2. Set up Git repo and permissions as we do now
3. Verify Git index has correct permissions (`git ls-files --stage`)
4. Call `swhid dir` with `--permissions-source git-index` (explicit, not auto)
5. Check if permissions are read correctly
6. If not, add debug logging to see what paths are being looked up

