use std::path::{Path, PathBuf};
use std::fs;

pub mod swhid;
pub mod hash;
pub mod git_objects;
pub mod directory;
pub mod content;
pub mod error;
pub mod person;
pub mod timestamp;
pub mod revision;
pub mod release;
pub mod snapshot;

pub use swhid::{Swhid, ObjectType, ExtendedSwhid, ExtendedObjectType, QualifiedSwhid};
pub use error::SwhidError;
pub use person::Person;
pub use timestamp::{Timestamp, TimestampWithTimezone};
pub use directory::{TreeObject, traverse_directory_recursively, Directory, EntryType, Permissions, DirectoryEntry};
pub use content::Content;
pub use revision::{Revision, RevisionType};
pub use release::{Release, ReleaseTargetType};
pub use snapshot::{Snapshot, SnapshotBranch, SnapshotTargetType};

#[derive(Clone)]
pub struct SwhidComputer {
    pub follow_symlinks: bool,
    pub exclude_patterns: Vec<String>,
    pub max_content_length: Option<usize>,
    pub filename: bool,
    pub recursive: bool,
}

impl Default for SwhidComputer {
    fn default() -> Self {
        Self {
            follow_symlinks: true,
            exclude_patterns: Vec::new(),
            max_content_length: None,
            filename: true,
            recursive: false,
        }
    }
}

impl SwhidComputer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_follow_symlinks(mut self, follow_symlinks: bool) -> Self {
        self.follow_symlinks = follow_symlinks;
        self
    }

    pub fn with_exclude_patterns(mut self, exclude_patterns: &[String]) -> Self {
        self.exclude_patterns = exclude_patterns.to_vec();
        self
    }

    pub fn with_max_content_length(mut self, max_content_length: Option<usize>) -> Self {
        self.max_content_length = max_content_length;
        self
    }

    pub fn with_filename(mut self, filename: bool) -> Self {
        self.filename = filename;
        self
    }

    pub fn with_recursive(mut self, recursive: bool) -> Self {
        self.recursive = recursive;
        self
    }

    /// Compute SWHID for content bytes
    pub fn compute_content_swhid(&self, content: &[u8]) -> Result<Swhid, SwhidError> {
        let content_obj = content::Content::from_data(content.to_vec());
        Ok(content_obj.swhid())
    }

    /// Compute SWHID for a file
    pub fn compute_file_swhid<P: AsRef<Path>>(&self, path: P) -> Result<Swhid, SwhidError> {
        let content = content::Content::from_file_with_limit(path, self.max_content_length)?;
        Ok(content.swhid())
    }

    /// Compute SWHID for a directory
    pub fn compute_directory_swhid<P: AsRef<Path>>(&self, path: P) -> Result<Swhid, SwhidError> {
        let mut dir = directory::Directory::from_disk(path, &self.exclude_patterns, self.follow_symlinks)?;
        Ok(dir.swhid())
    }

    /// Auto-detect object type and compute SWHID
    pub fn compute_swhid<P: AsRef<Path>>(&self, path: P) -> Result<Swhid, SwhidError> {
        let path = path.as_ref();
        
        if path.is_symlink() {
            if self.follow_symlinks {
                // Follow the symlink and compute SWHID of the target
                let target = std::fs::read_link(path)?;
                let resolved_target = if target.is_relative() {
                    path.parent().unwrap().join(&target)
                } else {
                    target
                };
                self.compute_swhid(resolved_target)
            } else {
                // Hash the symlink target as content
                let target = std::fs::read_link(path)?;
                let target_bytes = target.to_string_lossy().as_bytes().to_vec();
                let content = content::Content::from_data(target_bytes);
                Ok(content.swhid())
            }
        } else if path.is_file() {
            self.compute_file_swhid(path)
        } else if path.is_dir() {
            self.compute_directory_swhid(path)
        } else {
            Err(SwhidError::InvalidInput("Path is neither file nor directory".to_string()))
        }
    }

    /// Verify that a SWHID matches the computed SWHID for a path
    pub fn verify_swhid<P: AsRef<Path>>(&self, path: P, expected_swhid: &str) -> Result<bool, SwhidError> {
        // Parse the expected SWHID
        let expected = Swhid::from_string(expected_swhid)?;
        
        // Compute the actual SWHID
        let actual = self.compute_swhid(path)?;
        
        Ok(expected == actual)
    }

    /// Compute a snapshot SWHID for a Git repository
    pub fn compute_git_snapshot_swhid(&self, repo_path: &str) -> Result<Swhid, SwhidError> {
        use git2::Repository;
        use std::collections::HashMap;
        use crate::snapshot::{Snapshot, SnapshotBranch, SnapshotTargetType};

        let repo = Repository::open(repo_path)?;
        let mut branches: HashMap<Vec<u8>, Option<SnapshotBranch>> = HashMap::new();

        // Process all references (branches, tags, etc.)
        for reference in repo.references()? {
            let reference = reference?;
            let name = reference.name().unwrap_or("").as_bytes().to_vec();
            
            if let Some(target) = reference.target() {
                let target_id = target.as_bytes();
                
                // Convert Vec<u8> to [u8; 20] for SnapshotBranch
                if target_id.len() == 20 {
                    let mut target_array = [0u8; 20];
                    target_array.copy_from_slice(&target_id);
                    
                    // Get the object type
                    if let Ok(obj) = repo.find_object(target, None) {
                        let target_type = match obj.kind() {
                            Some(git2::ObjectType::Blob) => SnapshotTargetType::Content,
                            Some(git2::ObjectType::Tree) => SnapshotTargetType::Directory,
                            Some(git2::ObjectType::Commit) => SnapshotTargetType::Revision,
                            Some(git2::ObjectType::Tag) => SnapshotTargetType::Release,
                            _ => SnapshotTargetType::Revision, // Default fallback
                        };

                        let branch = SnapshotBranch::new(target_array, target_type);
                        branches.insert(name, Some(branch));
                    }
                }
            }
        }

        // Process symbolic references (like HEAD -> refs/heads/main)
        for reference in repo.references()? {
            let reference = reference?;
            let name = reference.name().unwrap_or("").as_bytes().to_vec();
            
            if let Some(symbolic_target) = reference.symbolic_target() {
                // For symbolic references, we need to resolve the target
                if let Ok(target_ref) = repo.find_reference(symbolic_target) {
                    if let Some(target) = target_ref.target() {
                        let target_id = target.as_bytes();
                        if target_id.len() == 20 {
                            let mut target_array = [0u8; 20];
                            target_array.copy_from_slice(&target_id);
                            let branch = SnapshotBranch::new(target_array, SnapshotTargetType::Alias);
                            branches.insert(name, Some(branch));
                        }
                    }
                }
            }
        }

        let snapshot = Snapshot::new(branches);
        Ok(snapshot.swhid())
    }

    /// Compute a directory SWHID for the contents of an archive (tar, tgz, zip)
    pub fn compute_archive_directory_swhid(&self, archive_path: &str) -> Result<Swhid, SwhidError> {
        use tempfile::TempDir;

        let archive_path = PathBuf::from(archive_path);
        let temp_dir = TempDir::new()?;
        let extract_path = temp_dir.path();

        // Extract the archive based on its extension
        let file_name = archive_path.file_name().unwrap_or_default().to_string_lossy();
        
        // Check for archive extensions
        let archive_type = if file_name.ends_with(".tar.gz") || file_name.ends_with(".tgz") {
            "tar.gz"
        } else if file_name.ends_with(".tar.bz2") {
            "tar.bz2"
        } else if file_name.ends_with(".zip") {
            "zip"
        } else if let Some(extension) = archive_path.extension() {
            let ext = extension.to_str().unwrap_or("").to_lowercase();
            match ext.as_str() {
                "tar" => "tar",
                _ => {
                    return Err(SwhidError::InvalidInput(format!(
                        "Unsupported archive format: {:?}",
                        extension
                    )));
                }
            }
        } else {
            return Err(SwhidError::InvalidInput("Archive file has no extension".to_string()));
        };
        
        match archive_type {
            "tar" | "tar.gz" | "tar.bz2" => {
                self.extract_tar(&archive_path, extract_path)?;
            }
            "zip" => {
                self.extract_zip(&archive_path, extract_path)?;
            }
            _ => {
                return Err(SwhidError::InvalidInput(format!(
                    "Unsupported archive format: {}",
                    archive_type
                )));
            }
        }

        // Find the root directory (usually the first directory or the archive name without extension)
        let root_dir = self.find_archive_root_dir(extract_path, &archive_path)?;
        
        // Compute directory SWHID for the extracted contents
        self.compute_directory_swhid(root_dir.to_str().unwrap())
    }

    fn extract_tar(&self, archive_path: &PathBuf, extract_path: &std::path::Path) -> Result<(), SwhidError> {
        use std::fs::File;
        use flate2::read::GzDecoder;
        use bzip2::read::BzDecoder;
        use std::io::BufReader;

        let file = File::open(archive_path)?;
        let reader: Box<dyn std::io::Read> = match archive_path.extension().and_then(|s| s.to_str()) {
            Some("gz") | Some("tgz") => Box::new(GzDecoder::new(file)),
            Some("bz2") => Box::new(BzDecoder::new(file)),
            _ => Box::new(file),
        };

        let mut archive = tar::Archive::new(BufReader::new(reader));
        archive.unpack(extract_path).map_err(|e| SwhidError::Archive(e.to_string()))?;
        Ok(())
    }

    fn extract_zip(&self, archive_path: &PathBuf, extract_path: &std::path::Path) -> Result<(), SwhidError> {
        use std::fs::File;
        use std::io::BufReader;

        let file = File::open(archive_path)?;
        let mut archive = zip::ZipArchive::new(BufReader::new(file))?;
        archive.extract(extract_path)?;
        Ok(())
    }

    fn find_archive_root_dir(&self, extract_path: &std::path::Path, archive_path: &PathBuf) -> Result<PathBuf, SwhidError> {
        // First, check if there's only one directory at the root
        let entries: Vec<_> = extract_path.read_dir()?.collect();
        
        if entries.len() == 1 {
            if let Ok(entry) = &entries[0] {
                if entry.path().is_dir() {
                    return Ok(entry.path());
                }
            }
        }

        // If no single root directory, use the archive name without extension
        let archive_name = archive_path.file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("extracted");
        
        let root_dir = extract_path.join(archive_name);
        if root_dir.exists() && root_dir.is_dir() {
            return Ok(root_dir);
        }

        // Fallback: use the extract path itself
        Ok(extract_path.to_path_buf())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::fs::File;
    use tempfile::TempDir;

    #[test]
    fn test_content_swhid() {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join("test.txt");
        fs::write(&file_path, b"Hello, World!").unwrap();

        let computer = SwhidComputer::new();
        let swhid = computer.compute_file_swhid(&file_path).unwrap();
        
        assert_eq!(swhid.object_type(), ObjectType::Content);
        // Note: The exact hash value would need to be computed and verified
        // against the Python implementation
    }

    #[test]
    fn test_directory_swhid() {
        let temp_dir = TempDir::new().unwrap();
        let sub_dir = temp_dir.path().join("subdir");
        fs::create_dir(&sub_dir).unwrap();
        fs::write(sub_dir.join("file.txt"), b"test").unwrap();

        let computer = SwhidComputer::new();
        let swhid = computer.compute_directory_swhid(temp_dir.path()).unwrap();
        
        assert_eq!(swhid.object_type(), ObjectType::Directory);
    }

    #[test]
    fn test_archive_directory_swhid() {
        let temp_dir = TempDir::new().unwrap();
        let archive_dir = temp_dir.path().join("archive_contents");
        fs::create_dir(&archive_dir).unwrap();
        fs::write(archive_dir.join("file.txt"), b"test content").unwrap();
        
        // Create a simple tar archive
        let archive_path = temp_dir.path().join("test.tar");
        {
            let file = fs::File::create(&archive_path).unwrap();
            let mut builder = tar::Builder::new(file);
            builder.append_dir_all("", archive_dir).unwrap();
            builder.finish().unwrap();
        }

        let computer = SwhidComputer::new();
        let swhid = computer.compute_archive_directory_swhid(archive_path.to_str().unwrap()).unwrap();
        
        assert_eq!(swhid.object_type(), ObjectType::Directory);
    }
} 