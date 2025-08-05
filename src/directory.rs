use std::fs;
use std::os::unix::fs::MetadataExt;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use crate::swhid::{Swhid, ObjectType};
use crate::content::Content;
use crate::hash::hash_git_object;
use crate::error::SwhidError;

/// Directory entry types
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntryType {
    File,
    Directory,
    Symlink,
}

impl EntryType {
    pub fn as_str(&self) -> &'static str {
        match self {
            EntryType::File => "file",
            EntryType::Directory => "dir",
            EntryType::Symlink => "symlink",
        }
    }
}

/// Directory entry permissions (Git-style)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Permissions {
    File = 0o100644,
    Executable = 0o100755,
    Symlink = 0o120000,
    Directory = 0o040000,
}

impl Permissions {
    pub fn from_mode(mode: u32) -> Self {
        match mode & 0o170000 {
            0o040000 => Permissions::Directory,
            0o120000 => Permissions::Symlink,
            _ => {
                if mode & 0o111 != 0 {
                    Permissions::Executable
                } else {
                    Permissions::File
                }
            }
        }
    }

    pub fn as_octal(&self) -> u32 {
        *self as u32
    }
}

/// Directory entry
#[derive(Debug, Clone)]
pub struct DirectoryEntry {
    pub name: Vec<u8>,
    pub entry_type: EntryType,
    pub permissions: Permissions,
    pub target: [u8; 20], // SHA1 hash of the target object
}

impl DirectoryEntry {
    pub fn new(name: Vec<u8>, entry_type: EntryType, permissions: Permissions, target: [u8; 20]) -> Self {
        Self {
            name,
            entry_type,
            permissions,
            target,
        }
    }
}

/// Directory object
#[derive(Debug, Clone)]
pub struct Directory {
    entries: Vec<DirectoryEntry>,
    hash: Option<[u8; 20]>,
    path: Option<PathBuf>,
}

impl Directory {
    /// Create directory from disk path
    pub fn from_disk<P: AsRef<Path>>(
        path: P,
        exclude_patterns: &[String],
        follow_symlinks: bool,
    ) -> Result<Self, SwhidError> {
        let path = path.as_ref();
        let mut dir = Self::from_disk_with_hash_fn(path, exclude_patterns, follow_symlinks, |_| Ok([0u8; 20]))?;
        dir.path = Some(path.to_path_buf());
        Ok(dir)
    }

    pub fn from_disk_with_hash_fn<P: AsRef<Path>, F>(
        path: P,
        exclude_patterns: &[String],
        follow_symlinks: bool,
        mut hash_fn: F,
    ) -> Result<Self, SwhidError>
    where
        F: FnMut(&Path) -> Result<[u8; 20], SwhidError>,
    {
        let path = path.as_ref();
        let mut entries = Vec::new();
        let mut raw_entries = Vec::new();

        // First, collect all directory entries
        for entry in fs::read_dir(path)? {
            raw_entries.push(entry?);
        }

        // Sort raw entries by name to ensure consistent order
        raw_entries.sort_by(|a, b| {
            let name_a = a.file_name();
            let name_b = b.file_name();
            name_a.cmp(&name_b)
        });

        for entry in raw_entries {
            let name = entry.file_name();
            let name_bytes = name.to_string_lossy().as_bytes().to_vec();

            // Skip hidden files
            if name_bytes.starts_with(b".") {
                continue;
            }

            let metadata = if follow_symlinks {
                entry.metadata()?
            } else {
                entry.metadata()? // Note: symlink_metadata() is not available on DirEntry
            };

            // Skip excluded directories (but not files)
            if metadata.is_dir() && Self::should_exclude(&name_bytes, exclude_patterns) {
                continue;
            }

            let entry_type = if metadata.is_dir() {
                EntryType::Directory
            } else if metadata.is_symlink() {
                EntryType::Symlink
            } else {
                EntryType::File
            };

            let permissions = Permissions::from_mode(metadata.mode());

            // Compute the target hash using the provided hash function
            let target = if entry_type == EntryType::File {
                // Compute content hash
                let content = Content::from_file(entry.path())?;
                *content.sha1_git()
            } else if entry_type == EntryType::Symlink {
                // Handle symlinks - read the symlink target as content
                if let Ok(target_path) = fs::read_link(entry.path()) {
                    let target_bytes = target_path.to_string_lossy().as_bytes().to_vec();
                    let content = Content::from_data(target_bytes);
                    *content.sha1_git()
                } else {
                    // Skip broken symlinks
                    continue;
                }
            } else {
                // Use the provided hash function for directories
                hash_fn(&entry.path())?
            };

            entries.push(DirectoryEntry::new(name_bytes, entry_type, permissions, target));
        }

        // Sort entries according to Git's tree sorting rules
        entries.sort_by(|a, b| Self::entry_sort_key(a).cmp(&Self::entry_sort_key(b)));

        Ok(Self {
            entries,
            hash: None,
            path: None,
        })
    }

    /// Get directory entries
    pub fn entries(&self) -> &[DirectoryEntry] {
        &self.entries
    }

    /// Compute the directory hash
    pub fn compute_hash(&mut self) -> [u8; 20] {
        if let Some(hash) = self.hash {
            return hash;
        }

        let mut components = Vec::new();

        for entry in &self.entries {
            // Format: perms + space + name + null + target
            // Use exact string format as per SWHID specification
            let perms_str = match entry.permissions {
                Permissions::File => "100644",
                Permissions::Executable => "100755", 
                Permissions::Symlink => "120000",
                Permissions::Directory => "40000",
            };
            components.extend_from_slice(perms_str.as_bytes());
            components.push(b' ');
            components.extend_from_slice(&entry.name);
            components.push(0);
            components.extend_from_slice(&entry.target);
        }



        let hash = hash_git_object("tree", &components);
        self.hash = Some(hash);
        hash
    }

    /// Compute SWHID for this directory
    pub fn swhid(&mut self) -> Swhid {
        let hash = self.compute_hash();
        Swhid::new(ObjectType::Directory, hash)
    }



    /// Get the path associated with this directory (for recursive traversal)
    pub fn path(&self) -> Option<&Path> {
        self.path.as_deref()
    }

    /// Entry sorting key (Git's tree sorting rules)
    fn entry_sort_key(entry: &DirectoryEntry) -> Vec<u8> {
        let mut key = entry.name.clone();
        if entry.entry_type == EntryType::Directory {
            key.push(b'/');
        }
        key
    }

    /// Check if entry should be excluded based on patterns
    fn should_exclude(name: &[u8], patterns: &[String]) -> bool {
        let name_str = String::from_utf8_lossy(name);
        should_exclude_str(&name_str, patterns)
    }
}

/// Check if entry should be excluded based on patterns (string version)
/// Uses shell pattern matching like Python's fnmatch
fn should_exclude_str(name: &str, patterns: &[String]) -> bool {
    for pattern in patterns {
        // Simple shell pattern matching - for now just exact match
        // TODO: Implement full shell pattern matching like Python's fnmatch
        if name == pattern {
            return true;
        }
    }
    false
}

/// Recursively traverse a directory and yield all objects (matching Python iter_tree behavior)
pub fn traverse_directory_recursively<P: AsRef<Path>>(
    root_path: P,
    exclude_patterns: &[String],
    follow_symlinks: bool,
) -> Result<Vec<(PathBuf, TreeObject)>, SwhidError> {
    let root_path = root_path.as_ref();
    
    // Step 1: Build the entire directory tree structure without computing hashes
    let mut dir_tree = build_directory_tree(root_path, exclude_patterns, follow_symlinks)?;
    
    // Step 2: Compute hashes bottom-up (leaves first, then parents)
    compute_hashes_bottom_up(&mut dir_tree, exclude_patterns, follow_symlinks)?;
    
    // Step 3: Collect all objects in the correct order (matching Python iter_tree)
    let mut all_objects = Vec::new();
    collect_tree_objects_from_tree(&dir_tree, root_path, exclude_patterns, follow_symlinks, &mut all_objects)?;
    
    Ok(all_objects)
}

/// Directory tree node for building the structure
struct DirectoryTreeNode {
    path: PathBuf,
    entries: Vec<DirectoryEntry>,
    children: Vec<DirectoryTreeNode>,
    hash: Option<[u8; 20]>,
}

impl DirectoryTreeNode {
    fn new(path: PathBuf) -> Self {
        Self {
            path,
            entries: Vec::new(),
            children: Vec::new(),
            hash: None,
        }
    }
    
    fn to_directory(&self) -> Directory {
        Directory {
            entries: self.entries.clone(),
            hash: self.hash,
            path: Some(self.path.clone()),
        }
    }
}

/// Build the directory tree structure without computing hashes
fn build_directory_tree(
    path: &Path,
    exclude_patterns: &[String],
    follow_symlinks: bool,
) -> Result<DirectoryTreeNode, SwhidError> {
    let mut node = DirectoryTreeNode::new(path.to_path_buf());
    let mut raw_entries = Vec::new();

    // Collect all directory entries
    for entry in fs::read_dir(path)? {
        raw_entries.push(entry?);
    }

    // Sort raw entries by name to ensure consistent order
    raw_entries.sort_by(|a, b| {
        let name_a = a.file_name();
        let name_b = b.file_name();
        name_a.cmp(&name_b)
    });

    for entry in raw_entries {
        let name = entry.file_name();
        let name_bytes = name.to_string_lossy().as_bytes().to_vec();

        // Skip hidden files
        if name_bytes.starts_with(b".") {
            continue;
        }

        let metadata = if follow_symlinks {
            entry.metadata()?
        } else {
            entry.metadata()?
        };

        // Skip excluded directories (but not files)
        if metadata.is_dir() && should_exclude_str(&String::from_utf8_lossy(&name_bytes), exclude_patterns) {
            continue;
        }

        let entry_type = if metadata.is_dir() {
            EntryType::Directory
        } else if metadata.is_symlink() {
            EntryType::Symlink
        } else {
            EntryType::File
        };

        let permissions = Permissions::from_mode(metadata.mode());

        // For now, use dummy hashes - we'll compute real ones later
        let target = if entry_type == EntryType::File {
            // Compute content hash immediately
            let content = Content::from_file(entry.path())?;
            *content.sha1_git()
        } else if entry_type == EntryType::Symlink {
            // Handle symlinks - read the symlink target as content
            if let Ok(target_path) = fs::read_link(entry.path()) {
                let target_bytes = target_path.to_string_lossy().as_bytes().to_vec();
                let content = Content::from_data(target_bytes);
                *content.sha1_git()
            } else {
                // Skip broken symlinks
                continue;
            }
        } else {
            // Directory - use dummy hash for now
            [0u8; 20]
        };

        let dir_entry = DirectoryEntry::new(name_bytes, entry_type, permissions, target);
        node.entries.push(dir_entry);

        // Recursively build child directories
        if entry_type == EntryType::Directory {
            let child_node = build_directory_tree(&entry.path(), exclude_patterns, follow_symlinks)?;
            node.children.push(child_node);
        }
    }

    // Sort entries according to Git's tree sorting rules
    node.entries.sort_by(|a, b| Directory::entry_sort_key(a).cmp(&Directory::entry_sort_key(b)));

    Ok(node)
}

/// Compute hashes bottom-up (leaves first, then parents)
fn compute_hashes_bottom_up(
    node: &mut DirectoryTreeNode,
    exclude_patterns: &[String],
    follow_symlinks: bool,
) -> Result<(), SwhidError> {

    
    // First, compute hashes for all children (bottom-up)
    for child in &mut node.children {
        compute_hashes_bottom_up(child, exclude_patterns, follow_symlinks)?;
    }

    // Now update the directory entries with correct child hashes
    for entry in &mut node.entries {
        if entry.entry_type == EntryType::Directory {
            // Find the corresponding child node
            let child_name = String::from_utf8_lossy(&entry.name);
            if let Some(child) = node.children.iter().find(|c| {
                c.path.file_name().map(|n| n.to_string_lossy()) == Some(child_name.clone())
            }) {
                // Use the child's computed hash
                if let Some(child_hash) = child.hash {
                    entry.target = child_hash;
                }
            }
        }
    }

    // Now compute this node's hash
    let mut temp_dir = Directory {
        entries: node.entries.clone(),
        hash: None,
        path: Some(node.path.clone()),
    };
    node.hash = Some(temp_dir.compute_hash());

    Ok(())
}

/// Collect all objects from the tree in the correct order
fn collect_tree_objects_from_tree(
    node: &DirectoryTreeNode,
    dir_path: &Path,
    exclude_patterns: &[String],
    follow_symlinks: bool,
    objects: &mut Vec<(PathBuf, TreeObject)>,
) -> Result<(), SwhidError> {
    // First, add this directory itself (matching Python behavior)
    let dir = node.to_directory();
    objects.push((dir_path.to_path_buf(), TreeObject::Directory(dir)));
    
    // Then recursively add all children
    for entry in &node.entries {
        let child_path = dir_path.join(std::ffi::OsStr::from_bytes(&entry.name));
        
        match entry.entry_type {
            EntryType::File => {
                // Content objects are already computed during tree building
                let content = Content::from_file(&child_path)?;
                objects.push((child_path, TreeObject::Content(content)));
            }
            EntryType::Directory => {
                // Find the corresponding child node and recurse
                let child_name = String::from_utf8_lossy(&entry.name);
                if let Some(child) = node.children.iter().find(|c| {
                    c.path.file_name().map(|n| n.to_string_lossy()) == Some(child_name.clone())
                }) {
                    collect_tree_objects_from_tree(child, &child_path, exclude_patterns, follow_symlinks, objects)?;
                }
            }
            EntryType::Symlink => {
                // Handle symlinks as content (link target)
                if let Ok(target_path) = fs::read_link(&child_path) {
                    let target_bytes = target_path.to_string_lossy().as_bytes().to_vec();
                    let content = Content::from_data(target_bytes);
                    objects.push((child_path, TreeObject::Content(content)));
                }
            }
        }
    }
    
    Ok(())
}

/// Collect all objects from the tree in the correct order (matching Python iter_tree)
fn collect_tree_objects(
    dir: &mut Directory,
    dir_path: &Path,
    exclude_patterns: &[String],
    follow_symlinks: bool,
    objects: &mut Vec<(PathBuf, TreeObject)>,
) -> Result<(), SwhidError> {
    // First, add this directory itself (matching Python behavior)
    objects.push((dir_path.to_path_buf(), TreeObject::Directory(dir.clone())));
    
    // Then recursively add all children
    for entry in &dir.entries {
        let child_path = dir_path.join(std::ffi::OsStr::from_bytes(&entry.name));
        
        match entry.entry_type {
            EntryType::File => {
                // Content objects are already computed during directory creation
                let content = Content::from_file(&child_path)?;
                objects.push((child_path, TreeObject::Content(content)));
            }
            EntryType::Directory => {
                // The subdirectory hash is already computed in the target field
                // We don't need to recreate the directory, just add it to the objects
                // The target hash should be the correct subdirectory hash
                let mut subdir = Directory::from_disk(&child_path, exclude_patterns, follow_symlinks)?;
                collect_tree_objects(&mut subdir, &child_path, exclude_patterns, follow_symlinks, objects)?;
            }
            EntryType::Symlink => {
                // Handle symlinks as content (link target)
                if let Ok(target_path) = fs::read_link(&child_path) {
                    let target_bytes = target_path.to_string_lossy().as_bytes().to_vec();
                    let content = Content::from_data(target_bytes);
                    objects.push((child_path, TreeObject::Content(content)));
                }
            }
        }
    }
    
    Ok(())
}

/// Collect all content objects recursively
fn collect_content_objects(
    current_path: &Path,
    exclude_patterns: &[String],
    follow_symlinks: bool,
    objects: &mut Vec<(PathBuf, TreeObject)>,
) -> Result<(), SwhidError> {
    let metadata = if follow_symlinks {
        fs::metadata(current_path)?
    } else {
        fs::symlink_metadata(current_path)?
    };

    if metadata.is_file() {
        // Add content object
        let content = Content::from_file(current_path)?;
        objects.push((current_path.to_path_buf(), TreeObject::Content(content)));
    } else if metadata.is_dir() {
        // Process all subdirectories and files recursively
        for entry in fs::read_dir(current_path)? {
            let entry = entry?;
            let entry_path = entry.path();
            
            // Skip hidden files and excluded patterns
            if let Some(name) = entry_path.file_name() {
                let name_str = name.to_string_lossy();
                if name_str.starts_with('.') || should_exclude_str(&name_str, exclude_patterns) {
                    continue;
                }
            }
            
            collect_content_objects(&entry_path, exclude_patterns, follow_symlinks, objects)?;
        }
    }
    
    Ok(())
}

/// Compute directory hashes recursively, using cached content hashes
fn compute_directory_hashes(
    current_path: &Path,
    exclude_patterns: &[String],
    follow_symlinks: bool,
    hash_cache: &mut std::collections::HashMap<PathBuf, [u8; 20]>,
    objects: &mut Vec<(PathBuf, TreeObject)>,
) -> Result<(), SwhidError> {
    let metadata = if follow_symlinks {
        fs::metadata(current_path)?
    } else {
        fs::symlink_metadata(current_path)?
    };

    if metadata.is_dir() {
        // Check if we've already processed this directory
        if hash_cache.contains_key(current_path) {
            return Ok(());
        }
        
        // First, compute hashes for all subdirectories
        for entry in fs::read_dir(current_path)? {
            let entry = entry?;
            let entry_path = entry.path();
            
            // Skip hidden files and excluded patterns
            if let Some(name) = entry_path.file_name() {
                let name_str = name.to_string_lossy();
                if name_str.starts_with('.') || should_exclude_str(&name_str, exclude_patterns) {
                    continue;
                }
            }
            
            let entry_metadata = if follow_symlinks {
                fs::metadata(&entry_path)?
            } else {
                fs::symlink_metadata(&entry_path)?
            };

            if entry_metadata.is_dir() {
                compute_directory_hashes(&entry_path, exclude_patterns, follow_symlinks, hash_cache, objects)?;
            }
        }
        
        // Then compute the hash for this directory
        let hash_fn = |path: &Path| {
            if let Some(hash) = hash_cache.get(path) {
                Ok(*hash)
            } else {
                // For content objects, compute the hash
                let content = Content::from_file(path)?;
                Ok(*content.sha1_git())
            }
        };
        
        let mut dir = Directory::from_disk_with_hash_fn(current_path, exclude_patterns, follow_symlinks, hash_fn)?;
        let hash = dir.compute_hash();
        hash_cache.insert(current_path.to_path_buf(), hash);
        
        objects.push((current_path.to_path_buf(), TreeObject::Directory(dir)));
    }
    
    Ok(())
}

/// Represents an object in the directory tree (either content or directory)
#[derive(Debug)]
pub enum TreeObject {
    Content(Content),
    Directory(Directory),
}

impl TreeObject {
    /// Get the SWHID for this object
    pub fn swhid(&mut self) -> Swhid {
        match self {
            TreeObject::Content(content) => content.swhid(),
            TreeObject::Directory(dir) => dir.swhid(),
        }
    }
}



#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_directory_creation() {
        let temp_dir = TempDir::new().unwrap();
        let sub_dir = temp_dir.path().join("subdir");
        fs::create_dir(&sub_dir).unwrap();
        fs::write(sub_dir.join("file.txt"), b"test").unwrap();

        let dir = Directory::from_disk(temp_dir.path(), &[], true).unwrap();
        
        assert!(!dir.entries().is_empty());
    }

    #[test]
    fn test_directory_hash() {
        let temp_dir = TempDir::new().unwrap();
        fs::write(temp_dir.path().join("test.txt"), b"test").unwrap();

        let mut dir = Directory::from_disk(temp_dir.path(), &[], true).unwrap();
        let hash = dir.compute_hash();
        
        assert_eq!(hash.len(), 20);
    }

    #[test]
    fn test_directory_swhid() {
        let temp_dir = TempDir::new().unwrap();
        fs::write(temp_dir.path().join("test.txt"), b"test").unwrap();

        let mut dir = Directory::from_disk(temp_dir.path(), &[], true).unwrap();
        let swhid = dir.swhid();
        
        assert_eq!(swhid.object_type(), ObjectType::Directory);
    }
} 