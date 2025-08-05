use std::path::Path;
use std::fs;

pub mod swhid;
pub mod hash;
pub mod git_objects;
pub mod directory;
pub mod content;
pub mod error;
pub mod person;
pub mod timestamp;

pub use swhid::{Swhid, ObjectType, ExtendedSwhid, ExtendedObjectType, QualifiedSwhid};
pub use error::SwhidError;
pub use person::Person;
pub use timestamp::{Timestamp, TimestampWithTimezone};
pub use directory::{TreeObject, traverse_directory_recursively, Directory, EntryType, Permissions, DirectoryEntry};
pub use content::Content;

/// Main entry point for computing SWHIDs
pub struct SwhidComputer {
    // Configuration options
    exclude_patterns: Vec<String>,
    follow_symlinks: bool,
    max_content_length: Option<usize>,
}

impl Default for SwhidComputer {
    fn default() -> Self {
        Self {
            exclude_patterns: vec![],
            follow_symlinks: true,
            max_content_length: None,
        }
    }
}

impl SwhidComputer {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with_exclude_patterns(mut self, patterns: Vec<String>) -> Self {
        self.exclude_patterns = patterns;
        self
    }

    pub fn with_follow_symlinks(mut self, follow: bool) -> Self {
        self.follow_symlinks = follow;
        self
    }

    pub fn with_max_content_length(mut self, max_length: Option<usize>) -> Self {
        self.max_content_length = max_length;
        self
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
        
        // Check if it's a symlink first
        if path.is_symlink() {
            if self.follow_symlinks {
                // Follow the symlink - get the target and compute its SWHID
                let target = fs::read_link(path)?;
                // Resolve relative target path relative to symlink's parent directory
                let resolved_target = if target.is_relative() {
                    path.parent().unwrap().join(&target)
                } else {
                    target
                };
                if resolved_target.is_file() {
                    self.compute_file_swhid(&resolved_target)
                } else if resolved_target.is_dir() {
                    self.compute_directory_swhid(&resolved_target)
                } else {
                    Err(SwhidError::InvalidPath("Symlink target is neither file nor directory".to_string()))
                }
            } else {
                // Treat symlink as content - the content is the target path
                let target = fs::read_link(path)?;
                let target_bytes = target.to_string_lossy().as_bytes().to_vec();
                
                // Check size limit for symlink target
                if let Some(max_len) = self.max_content_length {
                    if target_bytes.len() > max_len {
                        return Err(SwhidError::UnsupportedOperation(
                            format!("Symlink too large ({} bytes)", target_bytes.len())
                        ));
                    }
                }
                
                let content = content::Content::from_data(target_bytes);
                Ok(content.swhid())
            }
        } else if path.is_file() {
            self.compute_file_swhid(path)
        } else if path.is_dir() {
            self.compute_directory_swhid(path)
        } else {
            Err(SwhidError::InvalidPath("Path is neither file nor directory".to_string()))
        }
    }

    /// Verify that a SWHID matches the computed SWHID for a path
    pub fn verify_swhid<P: AsRef<Path>>(&self, expected_swhid: &str, path: P) -> Result<bool, SwhidError> {
        // Parse the expected SWHID
        let expected = Swhid::from_string(expected_swhid)?;
        
        // Compute the actual SWHID
        let actual = self.compute_swhid(path)?;
        
        // Compare the SWHIDs
        Ok(expected == actual)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
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
} 