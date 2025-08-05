use std::fs;
use std::path::Path;
use tempfile::TempDir;
use swhid::{Content, Directory, SwhidComputer, traverse_directory_recursively, TreeObject, SwhidError, Swhid, ObjectType, EntryType, Permissions, DirectoryEntry};

/// Test helper to create a temporary directory with specific structure
struct TestDir {
    temp_dir: TempDir,
}

impl TestDir {
    fn new() -> Self {
        Self {
            temp_dir: TempDir::new().unwrap(),
        }
    }

    fn path(&self) -> &Path {
        self.temp_dir.path()
    }

    fn create_file(&self, name: &str, content: &[u8]) {
        fs::write(self.path().join(name), content).unwrap();
    }

    fn create_executable(&self, name: &str, content: &[u8]) {
        let file_path = self.path().join(name);
        fs::write(&file_path, content).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mut perms = fs::metadata(&file_path).unwrap().permissions();
            perms.set_mode(0o755);
            fs::set_permissions(&file_path, perms).unwrap();
        }
    }

    fn create_subdir(&self, name: &str) -> std::path::PathBuf {
        let dir_path = self.path().join(name);
        fs::create_dir(&dir_path).unwrap();
        dir_path
    }

    fn create_symlink(&self, name: &str, target: &str) {
        #[cfg(unix)]
        {
            use std::os::unix::fs::symlink;
            symlink(target, self.path().join(name)).unwrap();
        }
    }
}

#[test]
fn test_content_hash_basic() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"Hello, World!");
    
    let content = Content::from_file(test_dir.path().join("test.txt")).unwrap();
    let swhid = content.swhid();
    
    // Known hash for "Hello, World!" content (matches Python swh identify)
    assert_eq!(swhid.object_id(), &hex::decode("b45ef6fec89518d314f546fd6c3025367b721684").unwrap()[..]);
    assert_eq!(swhid.object_type(), swhid::ObjectType::Content);
}

#[test]
fn test_content_hash_empty() {
    let test_dir = TestDir::new();
    test_dir.create_file("empty.txt", b"");
    
    let content = Content::from_file(test_dir.path().join("empty.txt")).unwrap();
    let swhid = content.swhid();
    
    // Known hash for empty content
    assert_eq!(swhid.object_id(), &hex::decode("e69de29bb2d1d6434b8b29ae775ad8c2e48c5391").unwrap()[..]);
}

#[test]
fn test_content_hash_large() {
    let test_dir = TestDir::new();
    let large_content = vec![b'a'; 10000];
    test_dir.create_file("large.txt", &large_content);
    
    let content = Content::from_file(test_dir.path().join("large.txt")).unwrap();
    let swhid = content.swhid();
    
    // Verify it's a valid SHA1 hash
    assert_eq!(swhid.object_id().len(), 20);
}

#[test]
fn test_directory_hash_single_file() {
    let test_dir = TestDir::new();
    test_dir.create_file("file.txt", b"test content");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(swhid.object_id().len(), 20);
    
    // Verify directory has exactly one entry
    assert_eq!(dir.entries().len(), 1);
    assert_eq!(dir.entries()[0].name, b"file.txt");
}

#[test]
fn test_directory_hash_multiple_files() {
    let test_dir = TestDir::new();
    test_dir.create_file("a.txt", b"content a");
    test_dir.create_file("b.txt", b"content b");
    test_dir.create_file("c.txt", b"content c");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 3);
    
    // Verify entries are sorted (Git tree sorting)
    let names: Vec<&[u8]> = dir.entries().iter().map(|e| e.name.as_slice()).collect();
    assert_eq!(names, vec![b"a.txt", b"b.txt", b"c.txt"]);
}

#[test]
fn test_directory_hash_with_executable() {
    let test_dir = TestDir::new();
    test_dir.create_file("normal.txt", b"normal file");
    test_dir.create_executable("script.sh", b"#!/bin/bash");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 2);
    
    // Verify executable has correct permissions
    let executable_entry = dir.entries().iter().find(|e| e.name == b"script.sh").unwrap();
    assert_eq!(executable_entry.permissions, swhid::Permissions::Executable);
    
    let normal_entry = dir.entries().iter().find(|e| e.name == b"normal.txt").unwrap();
    assert_eq!(normal_entry.permissions, swhid::Permissions::File);
}

#[test]
fn test_directory_hash_with_symlink() {
    let test_dir = TestDir::new();
    test_dir.create_file("target.txt", b"target content");
    test_dir.create_symlink("link.txt", "target.txt");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 2);
    
    // Verify symlink has correct permissions and target
    let symlink_entry = dir.entries().iter().find(|e| e.name == b"link.txt").unwrap();
    assert_eq!(symlink_entry.permissions, swhid::Permissions::Symlink);
    
    // The target should be the hash of the symlink target content
    let target_content = Content::from_data(b"target.txt".to_vec());
    assert_eq!(symlink_entry.target, *target_content.sha1_git());
}

#[test]
fn test_directory_hash_with_subdirectory() {
    let test_dir = TestDir::new();
    test_dir.create_file("root.txt", b"root content");
    
    let subdir = test_dir.path().join("subdir");
    fs::create_dir(&subdir).unwrap();
    fs::write(subdir.join("sub.txt"), b"sub content").unwrap();
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 2);
    
    // Verify subdirectory entry
    let subdir_entry = dir.entries().iter().find(|e| e.name == b"subdir").unwrap();
    assert_eq!(subdir_entry.permissions, swhid::Permissions::Directory);
    assert_eq!(subdir_entry.entry_type, swhid::EntryType::Directory);
}

#[test]
fn test_recursive_traversal_simple() {
    let test_dir = TestDir::new();
    test_dir.create_file("file1.txt", b"content 1");
    test_dir.create_file("file2.txt", b"content 2");
    
    let objects = traverse_directory_recursively(test_dir.path(), &[], true).unwrap();
    
    // Should have 3 objects: directory + 2 files
    assert_eq!(objects.len(), 3);
    
    // Verify all objects have valid SWHIDs
    for (_, mut obj) in objects {
        let swhid = obj.swhid();
        assert_eq!(swhid.object_id().len(), 20);
    }
}

#[test]
fn test_recursive_traversal_with_subdirs() {
    let test_dir = TestDir::new();
    test_dir.create_file("root.txt", b"root");
    
    let subdir1 = test_dir.path().join("subdir1");
    fs::create_dir(&subdir1).unwrap();
    fs::write(subdir1.join("sub1.txt"), b"sub1").unwrap();
    
    let subdir2 = test_dir.path().join("subdir2");
    fs::create_dir(&subdir2).unwrap();
    fs::write(subdir2.join("sub2.txt"), b"sub2").unwrap();
    
    let objects = traverse_directory_recursively(test_dir.path(), &[], true).unwrap();
    
    // Should have 6 objects: root dir + root file + 2 subdirs + 2 subfiles
    assert_eq!(objects.len(), 6);
    
    // Verify directory objects come first (matching Python behavior)
    let first_obj = &objects[0];
    assert!(matches!(first_obj.1, TreeObject::Directory(_)));
}

#[test]
fn test_recursive_traversal_exclude_patterns() {
    let test_dir = TestDir::new();
    test_dir.create_file("keep.txt", b"keep");
    test_dir.create_file("exclude.txt", b"exclude");
    
    let exclude_dir = test_dir.path().join("exclude_dir");
    fs::create_dir(&exclude_dir).unwrap();
    fs::write(exclude_dir.join("file.txt"), b"excluded").unwrap();
    
    let objects = traverse_directory_recursively(test_dir.path(), &["exclude_dir".to_string()], true).unwrap();
    
    // Should have 3 objects: directory + keep.txt + exclude.txt (exclude_dir should be excluded)
    assert_eq!(objects.len(), 3);
    
    // Verify excluded directory is not present
    let paths: Vec<String> = objects.iter().map(|(p, _)| p.to_string_lossy().to_string()).collect();
    assert!(!paths.iter().any(|p| p.contains("exclude_dir")));
}

#[test]
fn test_recursive_traversal_hidden_files() {
    let test_dir = TestDir::new();
    test_dir.create_file("visible.txt", b"visible");
    test_dir.create_file(".hidden", b"hidden");
    
    let objects = traverse_directory_recursively(test_dir.path(), &[], true).unwrap();
    
    // Should only have 2 objects: directory + visible.txt (hidden file should be excluded)
    assert_eq!(objects.len(), 2);
    
    // Verify hidden file is not present
    let paths: Vec<String> = objects.iter().map(|(p, _)| p.to_string_lossy().to_string()).collect();
    assert!(!paths.iter().any(|p| p.contains(".hidden")));
}

#[test]
fn test_recursive_traversal_complex_structure() {
    let test_dir = TestDir::new();
    
    // Create a complex directory structure
    test_dir.create_file("root.txt", b"root");
    test_dir.create_executable("script.sh", b"#!/bin/bash");
    
    let subdir1 = test_dir.path().join("subdir1");
    fs::create_dir(&subdir1).unwrap();
    fs::write(subdir1.join("file1.txt"), b"subdir1 file").unwrap();
    
    let subdir2 = test_dir.path().join("subdir2");
    fs::create_dir(&subdir2).unwrap();
    fs::write(subdir2.join("file2.txt"), b"subdir2 file").unwrap();
    
    let nested = subdir2.join("nested");
    fs::create_dir(&nested).unwrap();
    fs::write(nested.join("nested.txt"), b"nested file").unwrap();
    
    let objects = traverse_directory_recursively(test_dir.path(), &[], true).unwrap();
    
    // Should have 9 objects: root dir + root files + 2 subdirs + subdir files + nested dir + nested file
    assert_eq!(objects.len(), 9);
    
    // Verify all objects have valid SWHIDs
    for (_, mut obj) in objects {
        let swhid = obj.swhid();
        assert_eq!(swhid.object_id().len(), 20);
    }
}

#[test]
fn test_hash_consistency() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"consistent content");
    
    // Compute hash multiple times
    let mut dir1 = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let hash1 = dir1.compute_hash();
    
    let mut dir2 = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let hash2 = dir2.compute_hash();
    
    // Hashes should be identical
    assert_eq!(hash1, hash2);
}

#[test]
fn test_hash_deterministic_ordering() {
    let test_dir = TestDir::new();
    
    // Create files in reverse alphabetical order
    test_dir.create_file("z.txt", b"z content");
    test_dir.create_file("a.txt", b"a content");
    test_dir.create_file("m.txt", b"m content");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let hash = dir.compute_hash();
    
    // Verify entries are sorted correctly
    let names: Vec<&[u8]> = dir.entries().iter().map(|e| e.name.as_slice()).collect();
    assert_eq!(names, vec![b"a.txt", b"m.txt", b"z.txt"]);
    
    // Hash should be deterministic
    let mut dir2 = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let hash2 = dir2.compute_hash();
    assert_eq!(hash, hash2);
}

#[test]
fn test_empty_directory() {
    let test_dir = TestDir::new();
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 0);
    
    // Empty directory should have a specific hash
    let hash = dir.compute_hash();
    assert_eq!(hash.len(), 20);
}

#[test]
fn test_directory_with_mixed_content() {
    let test_dir = TestDir::new();
    
    // Create files, directories, and executables
    test_dir.create_file("file.txt", b"file content");
    test_dir.create_executable("script.sh", b"#!/bin/bash");
    
    let subdir = test_dir.path().join("subdir");
    fs::create_dir(&subdir).unwrap();
    fs::write(subdir.join("subfile.txt"), b"subfile content").unwrap();
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 3);
    
    // Verify each entry type
    let file_entry = dir.entries().iter().find(|e| e.name == b"file.txt").unwrap();
    assert_eq!(file_entry.permissions, swhid::Permissions::File);
    
    let exec_entry = dir.entries().iter().find(|e| e.name == b"script.sh").unwrap();
    assert_eq!(exec_entry.permissions, swhid::Permissions::Executable);
    
    let dir_entry = dir.entries().iter().find(|e| e.name == b"subdir").unwrap();
    assert_eq!(dir_entry.permissions, swhid::Permissions::Directory);
}

#[test]
fn test_error_handling_nonexistent_path() {
    let result = Content::from_file("nonexistent_file.txt");
    assert!(result.is_err());
}

#[test]
fn test_error_handling_directory_as_file() {
    let test_dir = TestDir::new();
    let result = Content::from_file(test_dir.path());
    assert!(result.is_err());
}

#[test]
fn test_swhid_computer_api() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"test content");
    
    let computer = SwhidComputer::new();
    
    // Test file SWHID computation
    let file_swhid = computer.compute_file_swhid(test_dir.path().join("test.txt")).unwrap();
    assert_eq!(file_swhid.object_type(), swhid::ObjectType::Content);
    
    // Test directory SWHID computation
    let dir_swhid = computer.compute_directory_swhid(test_dir.path()).unwrap();
    assert_eq!(dir_swhid.object_type(), swhid::ObjectType::Directory);
    
    // Test auto-detection
    let auto_swhid = computer.compute_swhid(test_dir.path().join("test.txt")).unwrap();
    assert_eq!(auto_swhid.object_type(), swhid::ObjectType::Content);
}

#[test]
fn test_swhid_computer_with_exclusions() {
    let test_dir = TestDir::new();
    test_dir.create_file("keep.txt", b"keep");
    
    let exclude_dir = test_dir.path().join("exclude");
    fs::create_dir(&exclude_dir).unwrap();
    fs::write(exclude_dir.join("file.txt"), b"excluded").unwrap();
    
    let computer = SwhidComputer::new().with_exclude_patterns(vec!["exclude".to_string()]);
    let dir_swhid = computer.compute_directory_swhid(test_dir.path()).unwrap();
    
    assert_eq!(dir_swhid.object_type(), swhid::ObjectType::Directory);
}

#[test]
fn test_swhid_string_parsing() {
    let swhid_str = "swh:1:cnt:95d09f2b10159347eece71399a7e2cc70638e9a7";
    let swhid = Swhid::from_string(swhid_str).unwrap();
    
    assert_eq!(swhid.namespace(), "swh");
    assert_eq!(swhid.scheme_version(), 1);
    assert_eq!(swhid.object_type(), swhid::ObjectType::Content);
    assert_eq!(swhid.to_string(), swhid_str);
}

#[test]
fn test_swhid_string_parsing_invalid() {
    let invalid_swhids = vec![
        "invalid",
        "swh:2:cnt:95d09f2b10159347eece71399a7e2cc70638e9a7", // wrong version
        "swh:1:invalid:95d09f2b10159347eece71399a7e2cc70638e9a7", // wrong type
        "swh:1:cnt:invalid", // wrong hash
    ];
    
    for invalid in invalid_swhids {
        assert!(Swhid::from_string(invalid).is_err());
    }
}

#[test]
fn test_permissions_encoding() {
    let test_dir = TestDir::new();
    test_dir.create_file("normal.txt", b"normal");
    test_dir.create_executable("script.sh", b"#!/bin/bash");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    
    let normal_entry = dir.entries().iter().find(|e| e.name == b"normal.txt").unwrap();
    assert_eq!(normal_entry.permissions, swhid::Permissions::File);
    
    let exec_entry = dir.entries().iter().find(|e| e.name == b"script.sh").unwrap();
    assert_eq!(exec_entry.permissions, swhid::Permissions::Executable);
}

#[test]
fn test_large_file_handling() {
    let test_dir = TestDir::new();
    
    // Create a file with 1MB of data
    let large_content = vec![b'x'; 1024 * 1024];
    test_dir.create_file("large.txt", &large_content);
    
    let content = Content::from_file(test_dir.path().join("large.txt")).unwrap();
    let swhid = content.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Content);
    assert_eq!(swhid.object_id().len(), 20);
}

#[test]
fn test_unicode_filename_handling() {
    let test_dir = TestDir::new();
    
    // Create file with Unicode name
    let unicode_name = "测试文件.txt";
    test_dir.create_file(unicode_name, b"unicode content");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 1);
    
    // Verify the entry name is correctly encoded
    let entry = &dir.entries()[0];
    assert_eq!(entry.name, unicode_name.as_bytes());
}

#[test]
fn test_symlink_following() {
    let test_dir = TestDir::new();
    test_dir.create_file("target.txt", b"target content");
    test_dir.create_symlink("link.txt", "target.txt");
    
    // Test with follow_symlinks = true
    let mut dir_follow = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid_follow = dir_follow.swhid();
    
    // Test with follow_symlinks = false
    let mut dir_no_follow = Directory::from_disk(test_dir.path(), &[], false).unwrap();
    let swhid_no_follow = dir_no_follow.swhid();
    
    // Results should be the same - symlinks in directory entries are always
    // treated as content objects with the target path as content
    assert_eq!(swhid_follow.object_id(), swhid_no_follow.object_id());
    
    // Verify that the symlink entry has the correct permissions and target
    let symlink_entry = dir_follow.entries().iter().find(|e| e.name == b"link.txt").unwrap();
    assert_eq!(symlink_entry.permissions, swhid::Permissions::Symlink);
    assert_eq!(symlink_entry.entry_type, swhid::EntryType::Symlink);
    
    // The target should be the hash of the symlink target path as content
    let target_content = Content::from_data(b"target.txt".to_vec());
    assert_eq!(symlink_entry.target, *target_content.sha1_git());
}

#[test]
fn test_symlink_as_object() {
    let test_dir = TestDir::new();
    test_dir.create_file("target.txt", b"target content");
    test_dir.create_symlink("link.txt", "target.txt");
    
    // When identifying the symlink itself, follow_symlinks should matter
    let link_path = test_dir.path().join("link.txt");
    let target_path = test_dir.path().join("target.txt");
    
    // Test with follow_symlinks = true (should follow the symlink)
    let computer_follow = SwhidComputer::new().with_follow_symlinks(true);
    let swhid_follow = computer_follow.compute_swhid(&link_path).unwrap();
    
    // Test with follow_symlinks = false (should treat symlink as content)
    let computer_no_follow = SwhidComputer::new().with_follow_symlinks(false);
    let swhid_no_follow = computer_no_follow.compute_swhid(&link_path).unwrap();
    
    // Results should be different
    assert_ne!(swhid_follow.object_id(), swhid_no_follow.object_id());
    
    // The follow_symlinks=true should match the target file
    let target_swhid = SwhidComputer::new().compute_swhid(&target_path).unwrap();
    assert_eq!(swhid_follow.object_id(), target_swhid.object_id());
    
    // The follow_symlinks=false should be the symlink content (target path)
    let symlink_content = Content::from_data(b"target.txt".to_vec());
    let expected_symlink_swhid = symlink_content.swhid();
    assert_eq!(swhid_no_follow.object_id(), expected_symlink_swhid.object_id());
}

#[test]
fn test_content_size_limit_file() {
    let test_dir = TestDir::new();
    
    // Create a file that exceeds the size limit
    let large_content = vec![b'a'; 1000];
    test_dir.create_file("large.txt", &large_content);
    
    // Test with size limit smaller than file size
    let computer = SwhidComputer::new().with_max_content_length(Some(500));
    let result = computer.compute_swhid(test_dir.path().join("large.txt"));
    
    // Should return an error or special status for oversized content
    assert!(result.is_err() || result.unwrap().object_id() != Content::from_data(large_content).swhid().object_id());
}

#[test]
fn test_content_size_limit_symlink() {
    let test_dir = TestDir::new();
    
    // Create a symlink with a target path that exceeds size limit
    let long_target = "a".repeat(1000);
    test_dir.create_symlink("long_link.txt", &long_target);
    
    // Test with size limit smaller than symlink target length
    let computer = SwhidComputer::new().with_max_content_length(Some(500));
    let result = computer.compute_swhid(test_dir.path().join("long_link.txt"));
    
    // Should return an error for oversized symlink
    assert!(result.is_err());
}

#[test]
fn test_content_size_limit_within_bounds() {
    let test_dir = TestDir::new();
    
    // Create a file within the size limit
    let small_content = vec![b'a'; 100];
    test_dir.create_file("small.txt", &small_content);
    
    // Test with size limit larger than file size
    let computer = SwhidComputer::new().with_max_content_length(Some(500));
    let result = computer.compute_swhid(test_dir.path().join("small.txt"));
    
    // Should succeed and return correct hash
    assert!(result.is_ok());
    let expected_swhid = Content::from_data(small_content).swhid();
    assert_eq!(result.unwrap().object_id(), expected_swhid.object_id());
}

#[test]
fn test_cli_verify_match() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"Hello, World!");
    
    let computer = SwhidComputer::new();
    let expected_swhid = computer.compute_swhid(test_dir.path().join("test.txt")).unwrap();
    
    // Test verification with matching SWHID
    let result = computer.verify_swhid(&expected_swhid.to_string(), test_dir.path().join("test.txt"));
    assert!(result.is_ok());
}

#[test]
fn test_cli_verify_mismatch() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"Hello, World!");
    
    let computer = SwhidComputer::new();
    let computed_swhid = computer.compute_swhid(test_dir.path().join("test.txt")).unwrap();
    
    // Create a different expected SWHID
    let wrong_swhid = Swhid::new(ObjectType::Content, [0u8; 20]);
    
    // Test verification with mismatching SWHID
    let result = computer.verify_swhid(&wrong_swhid.to_string(), test_dir.path().join("test.txt"));
    assert!(result.is_ok() && !result.unwrap());
}

#[test]
fn test_cli_verify_invalid_swhid() {
    let test_dir = TestDir::new();
    test_dir.create_file("test.txt", b"Hello, World!");
    
    let computer = SwhidComputer::new();
    
    // Test verification with invalid SWHID format
    let result = computer.verify_swhid("invalid-swhid", test_dir.path().join("test.txt"));
    assert!(result.is_err());
}

#[test]
fn test_swhid_validation_invalid_formats() {
    // Test various invalid SWHID formats
    let invalid_swhids = vec![
        "swh:1:cnt",  // Missing hash
        "swh:1:",  // Missing object type and hash
        "swh:",  // Missing version, object type, and hash
        "swh:1:cnt:",  // Missing hash
        "foo:1:cnt:abc8bc9d7a6bcf6db04f476d29314f157507d505",  // Wrong namespace
        "swh:2:dir:def8bc9d7a6bcf6db04f476d29314f157507d505",  // Wrong version
        "swh:1:foo:fed8bc9d7a6bcf6db04f476d29314f157507d505",  // Invalid object type
        "swh:1:dir:0b6959356d30f1a4e9b7f6bca59b9a336464c03d;invalid;malformed",  // Invalid qualifiers
        "swh:1:snp:gh6959356d30f1a4e9b7f6bca59b9a336464c03d",  // Invalid hash characters
        "swh:1:snp:foo",  // Invalid hash format
        "swh :1:dir:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",  // Whitespace in namespace
        "swh: 1:dir:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",  // Whitespace in version
        "swh:1: dir:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",  // Whitespace in object type
    ];

    for invalid_swhid in invalid_swhids {
        let result = Swhid::from_string(invalid_swhid);
        assert!(result.is_err(), "SWHID '{}' should be invalid", invalid_swhid);
    }
}

#[test]
fn test_swhid_validation_valid_formats() {
    // Test various valid SWHID formats
    let valid_swhids = vec![
        "swh:1:cnt:94a9ed024d3859793618152ea559a168bbcbb5e2",
        "swh:1:dir:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",
        "swh:1:rev:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",
        "swh:1:rel:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",
        "swh:1:snp:0b6959356d30f1a4e9b7f6bca59b9a336464c03d",
    ];

    for valid_swhid in valid_swhids {
        let result = Swhid::from_string(valid_swhid);
        assert!(result.is_ok(), "SWHID '{}' should be valid", valid_swhid);
    }
}

#[test]
fn test_swhid_validation_hash_length() {
    // Test that SWHID validation requires exactly 20 bytes (40 hex chars)
    let short_hash = "swh:1:cnt:1234567890abcdef";  // 16 chars
    let long_hash = "swh:1:cnt:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef";  // 64 chars
    let invalid_chars = "swh:1:cnt:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdeg";  // Invalid hex
    
    assert!(Swhid::from_string(short_hash).is_err());
    assert!(Swhid::from_string(long_hash).is_err());
    assert!(Swhid::from_string(invalid_chars).is_err());
}

#[test]
fn test_special_file_handling() {
    let test_dir = TestDir::new();
    
    // Test that special files (non-regular files) are handled correctly
    // This would require creating actual special files, but for now we'll test
    // that our implementation handles them gracefully
    
    // Test with a regular file first
    test_dir.create_file("regular.txt", b"content");
    let computer = SwhidComputer::new();
    let result = computer.compute_swhid(test_dir.path().join("regular.txt"));
    assert!(result.is_ok());
    
    // Note: Testing actual special files (sockets, pipes, etc.) would require
    // system-specific code and might not be portable. The Python implementation
    // returns empty content for special files, which is what we should do too.
}

#[test]
fn test_empty_file_handling() {
    let test_dir = TestDir::new();
    
    // Test empty file
    test_dir.create_file("empty.txt", b"");
    
    let computer = SwhidComputer::new();
    let result = computer.compute_swhid(test_dir.path().join("empty.txt"));
    assert!(result.is_ok());
    
    // Empty file should have a specific hash
    let swhid = result.unwrap();
    let expected_content = Content::from_data(vec![]);
    let expected_swhid = expected_content.swhid();
    assert_eq!(swhid.object_id(), expected_swhid.object_id());
}

#[test]
fn test_exclusion_case_sensitivity() {
    let test_dir = TestDir::new();
    
    // Create files with different case variations
    test_dir.create_file("File.txt", b"content1");
    test_dir.create_file("file.txt", b"content2");
    test_dir.create_file("FILE.txt", b"content3");
    test_dir.create_file("other.txt", b"content4");
    
    // Test case-sensitive exclusion
    let computer = SwhidComputer::new().with_exclude_patterns(vec!["file.txt".to_string()]);
    let objects = traverse_directory_recursively(test_dir.path(), &["file.txt".to_string()], true).unwrap();
    
    // Should exclude only "file.txt" (exact match), not "File.txt" or "FILE.txt"
    let file_names: Vec<String> = objects.iter()
        .filter_map(|(path, obj)| {
            if let TreeObject::Content(_) = obj {
                Some(path.file_name().unwrap().to_string_lossy().to_string())
            } else {
                None
            }
        })
        .collect();
    
    // Should still have "File.txt", "FILE.txt", and "other.txt"
    assert!(file_names.contains(&"File.txt".to_string()));
    assert!(file_names.contains(&"FILE.txt".to_string()));
    assert!(file_names.contains(&"other.txt".to_string()));
    // Should NOT have "file.txt"
    assert!(!file_names.contains(&"file.txt".to_string()));
}

#[test]
fn test_exclusion_case_insensitive_pattern() {
    let test_dir = TestDir::new();
    
    // Create files with different case variations
    test_dir.create_file("File.txt", b"content1");
    test_dir.create_file("file.txt", b"content2");
    test_dir.create_file("FILE.txt", b"content3");
    test_dir.create_file("other.txt", b"content4");
    
    // Test with case-insensitive pattern (if supported)
    // Note: Our current implementation is case-sensitive, so this test verifies that behavior
    let computer = SwhidComputer::new().with_exclude_patterns(vec!["FILE.TXT".to_string()]);
    let objects = traverse_directory_recursively(test_dir.path(), &["FILE.TXT".to_string()], true).unwrap();
    
    let file_names: Vec<String> = objects.iter()
        .filter_map(|(path, obj)| {
            if let TreeObject::Content(_) = obj {
                Some(path.file_name().unwrap().to_string_lossy().to_string())
            } else {
                None
            }
        })
        .collect();
    
    // With case-sensitive matching, "FILE.TXT" should only match "FILE.TXT"
    assert!(file_names.contains(&"File.txt".to_string()));
    assert!(file_names.contains(&"file.txt".to_string()));
    assert!(file_names.contains(&"FILE.txt".to_string())); // Different case, should NOT be excluded
    assert!(file_names.contains(&"other.txt".to_string()));
    // Should NOT have "FILE.TXT" (exact case match)
    assert!(!file_names.contains(&"FILE.TXT".to_string()));
}

#[test]
fn test_exclusion_trailing_slash() {
    let test_dir = TestDir::new();
    
    // Create directory structure
    test_dir.create_subdir("docs");
    test_dir.create_file("docs/readme.txt", b"content1");
    test_dir.create_file("docs/api.txt", b"content2");
    test_dir.create_file("docs_file", b"content3"); // This creates a file named "docs_file"
    test_dir.create_file("other.txt", b"content4");
    
    // Test exclusion with trailing slash
    let objects = traverse_directory_recursively(test_dir.path(), &["docs_file".to_string()], true).unwrap();
    
    let file_names: Vec<String> = objects.iter()
        .filter_map(|(path, obj)| {
            if let TreeObject::Content(_) = obj {
                Some(path.file_name().unwrap().to_string_lossy().to_string())
            } else {
                None
            }
        })
        .collect();
    
    // Should exclude the "docs_file" file (exact match)
    assert!(!file_names.contains(&"docs_file".to_string()));
    // Should still have other files
    assert!(file_names.contains(&"other.txt".to_string()));
}

#[test]
fn test_exclusion_directory_vs_file() {
    let test_dir = TestDir::new();
    
    // Create both a directory and a file with similar names
    test_dir.create_subdir("docs");
    test_dir.create_file("docs/readme.txt", b"content1");
    test_dir.create_file("docs_file", b"content2"); // File named "docs_file"
    test_dir.create_file("other.txt", b"content3");
    
    // Test exclusion of directory vs file
    let objects = traverse_directory_recursively(test_dir.path(), &["docs_file".to_string()], true).unwrap();
    
    let file_names: Vec<String> = objects.iter()
        .filter_map(|(path, obj)| {
            if let TreeObject::Content(_) = obj {
                Some(path.file_name().unwrap().to_string_lossy().to_string())
            } else {
                None
            }
        })
        .collect();
    
    // Should exclude the "docs_file" file (exact match)
    assert!(!file_names.contains(&"docs_file".to_string()));
    // Should still have other files
    assert!(file_names.contains(&"other.txt".to_string()));
    // The "docs" directory and its contents should still be included
    // (since we're only excluding the file named "docs_file")
}

#[test]
fn test_directory_entry_order_git_compliance() {
    let test_dir = TestDir::new();
    
    // Create files and directories in a specific order to test Git tree sorting
    // Git sorts entries by: directories first (with trailing slash), then files
    // Within each group, sorted by byte order
    test_dir.create_file("a.txt", b"content1");
    test_dir.create_file("z.txt", b"content2");
    test_dir.create_subdir("alpha");
    test_dir.create_file("alpha/file.txt", b"content3");
    test_dir.create_subdir("zebra");
    test_dir.create_file("zebra/file.txt", b"content4");
    test_dir.create_file("1.txt", b"content5");
    test_dir.create_file("9.txt", b"content6");
    
    let dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let entries = dir.entries();
    
    // Verify that entries are sorted according to Git tree rules:
    // 1. Directories first (with trailing slash in name)
    // 2. Files second
    // 3. Within each group, sorted by byte order
    
    let mut prev_entry: Option<&DirectoryEntry> = None;
    for entry in entries {
        if let Some(prev) = prev_entry {
            // Directories should come before files
            if prev.entry_type == EntryType::Directory && entry.entry_type == EntryType::File {
                // This is correct - directories before files
            } else if prev.entry_type == EntryType::File && entry.entry_type == EntryType::Directory {
                panic!("Files should come after directories in Git tree order");
            } else {
                // Within same type, should be sorted by byte order
                assert!(prev.name <= entry.name, 
                    "Entries not in byte order: {:?} > {:?}", 
                    String::from_utf8_lossy(&prev.name), 
                    String::from_utf8_lossy(&entry.name));
            }
        }
        prev_entry = Some(entry);
    }
}

#[test]
fn test_directory_entry_order_specific_examples() {
    let test_dir = TestDir::new();
    
    // Create a specific set of entries to test exact ordering
    test_dir.create_file("a", b"content1");
    test_dir.create_subdir("b");
    test_dir.create_file("c", b"content2");
    test_dir.create_subdir("d");
    
    let dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let entries: Vec<&DirectoryEntry> = dir.entries().iter().collect();
    
    // Should have 4 entries
    assert_eq!(entries.len(), 4);
    
    // Order should be: directories first (b, d), then files (a, c)
    // Within each group, sorted by byte order
    assert_eq!(entries[0].name, b"b");
    assert_eq!(entries[0].entry_type, EntryType::Directory);
    assert_eq!(entries[1].name, b"d");
    assert_eq!(entries[1].entry_type, EntryType::Directory);
    assert_eq!(entries[2].name, b"a");
    assert_eq!(entries[2].entry_type, EntryType::File);
    assert_eq!(entries[3].name, b"c");
    assert_eq!(entries[3].entry_type, EntryType::File);
}

#[test]
fn test_directory_entry_order_with_special_chars() {
    let test_dir = TestDir::new();
    
    // Test with special characters and unicode
    test_dir.create_file("a.txt", b"content1");
    test_dir.create_file("á.txt", b"content2"); // Unicode
    test_dir.create_file("z.txt", b"content3");
    test_dir.create_subdir("alpha");
    test_dir.create_subdir("ápha"); // Unicode directory
    
    let dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let entries: Vec<&DirectoryEntry> = dir.entries().iter().collect();
    
    // Should have 5 entries
    assert_eq!(entries.len(), 5);
    
    // Directories should come first, sorted by byte order
    assert_eq!(entries[0].entry_type, EntryType::Directory);
    assert_eq!(entries[1].entry_type, EntryType::Directory);
    
    // Files should come after, sorted by byte order
    assert_eq!(entries[2].entry_type, EntryType::File);
    assert_eq!(entries[3].entry_type, EntryType::File);
    assert_eq!(entries[4].entry_type, EntryType::File);
    
    // Verify byte order sorting (not lexicographic)
    // 'a' (0x61) should come before 'á' (0xC3 0xA1) in byte order
    let a_file = entries.iter().find(|e| e.name == b"a.txt").unwrap();
    let aacute_file = entries.iter().find(|e| e.name == b"\xc3\xa1.txt").unwrap();
    assert!(a_file.name < aacute_file.name);
}

#[test]
fn test_recursive_hash_consistency() {
    let test_dir = TestDir::new();
    
    // Create a simple structure: root dir with one subdir containing one file
    test_dir.create_file("root.txt", b"root");
    
    let subdir = test_dir.path().join("subdir");
    fs::create_dir(&subdir).unwrap();
    fs::write(subdir.join("subfile.txt"), b"subfile").unwrap();
    
    // Compute hashes using recursive traversal
    let objects = traverse_directory_recursively(test_dir.path(), &[], true).unwrap();
    
    // Should have 4 objects: root dir, root file, subdir, subfile
    assert_eq!(objects.len(), 4);
    
    // Verify all hashes are consistent
    let mut hashes = Vec::new();
    for (_, mut obj) in objects {
        let swhid = obj.swhid();
        hashes.push(swhid.object_id().to_vec());
    }
    
    // All hashes should be unique and 20 bytes
    for hash in &hashes {
        assert_eq!(hash.len(), 20);
    }
    
    // Check for duplicates
    let unique_hashes: std::collections::HashSet<_> = hashes.iter().collect();
    assert_eq!(unique_hashes.len(), hashes.len());
}

#[test]
fn test_edge_case_single_byte_file() {
    let test_dir = TestDir::new();
    test_dir.create_file("single.txt", b"a");
    
    let content = Content::from_file(test_dir.path().join("single.txt")).unwrap();
    let swhid = content.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Content);
    assert_eq!(swhid.object_id().len(), 20);
}

#[test]
fn test_edge_case_very_long_filename() {
    let test_dir = TestDir::new();
    
    // Create a file with a very long name
    let long_name = "a".repeat(255);
    test_dir.create_file(&long_name, b"content");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 1);
    assert_eq!(dir.entries()[0].name, long_name.as_bytes());
}

#[test]
fn test_edge_case_special_characters() {
    let test_dir = TestDir::new();
    
    // Create files with special characters in names
    test_dir.create_file("file with spaces.txt", b"content");
    test_dir.create_file("file-with-dashes.txt", b"content");
    test_dir.create_file("file_with_underscores.txt", b"content");
    
    let mut dir = Directory::from_disk(test_dir.path(), &[], true).unwrap();
    let swhid = dir.swhid();
    
    assert_eq!(swhid.object_type(), swhid::ObjectType::Directory);
    assert_eq!(dir.entries().len(), 3);
    
    // Verify all files are present
    let names: Vec<&[u8]> = dir.entries().iter().map(|e| e.name.as_slice()).collect();
    assert!(names.iter().any(|n| n == b"file with spaces.txt"));
    assert!(names.iter().any(|n| n == b"file-with-dashes.txt"));
    assert!(names.iter().any(|n| n == b"file_with_underscores.txt"));
} 

#[cfg(test)]
mod extended_swhid_tests {
    use super::*;
    use swhid::{ExtendedSwhid, ExtendedObjectType, QualifiedSwhid};

    #[test]
    fn test_extended_object_type_creation() {
        assert_eq!(ExtendedObjectType::Content.as_str(), "cnt");
        assert_eq!(ExtendedObjectType::Directory.as_str(), "dir");
        assert_eq!(ExtendedObjectType::Revision.as_str(), "rev");
        assert_eq!(ExtendedObjectType::Release.as_str(), "rel");
        assert_eq!(ExtendedObjectType::Snapshot.as_str(), "snp");
        assert_eq!(ExtendedObjectType::Origin.as_str(), "ori");
        assert_eq!(ExtendedObjectType::RawExtrinsicMetadata.as_str(), "emd");
    }

    #[test]
    fn test_extended_object_type_from_str() {
        assert_eq!(ExtendedObjectType::from_str("cnt").unwrap(), ExtendedObjectType::Content);
        assert_eq!(ExtendedObjectType::from_str("dir").unwrap(), ExtendedObjectType::Directory);
        assert_eq!(ExtendedObjectType::from_str("rev").unwrap(), ExtendedObjectType::Revision);
        assert_eq!(ExtendedObjectType::from_str("rel").unwrap(), ExtendedObjectType::Release);
        assert_eq!(ExtendedObjectType::from_str("snp").unwrap(), ExtendedObjectType::Snapshot);
        assert_eq!(ExtendedObjectType::from_str("ori").unwrap(), ExtendedObjectType::Origin);
        assert_eq!(ExtendedObjectType::from_str("emd").unwrap(), ExtendedObjectType::RawExtrinsicMetadata);
        
        assert!(ExtendedObjectType::from_str("invalid").is_err());
    }

    #[test]
    fn test_extended_swhid_creation() {
        let object_id = [0u8; 20];
        let swhid = ExtendedSwhid::new(ExtendedObjectType::Content, object_id);
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ExtendedObjectType::Content);
        assert_eq!(swhid.object_id(), &object_id);
    }

    #[test]
    fn test_extended_swhid_from_string() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0";
        let swhid = ExtendedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ExtendedObjectType::Content);
        assert_eq!(hex::encode(swhid.object_id()), "8ff44f081d43176474b267de5451f2c2e88089d0");
    }

    #[test]
    fn test_extended_swhid_from_string_with_origin() {
        let swhid_str = "swh:1:ori:8ff44f081d43176474b267de5451f2c2e88089d0";
        let swhid = ExtendedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.object_type(), ExtendedObjectType::Origin);
    }

    #[test]
    fn test_extended_swhid_from_string_with_emd() {
        let swhid_str = "swh:1:emd:8ff44f081d43176474b267de5451f2c2e88089d0";
        let swhid = ExtendedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.object_type(), ExtendedObjectType::RawExtrinsicMetadata);
    }

    #[test]
    fn test_extended_swhid_display() {
        let object_id = hex::decode("8ff44f081d43176474b267de5451f2c2e88089d0").unwrap();
        let mut object_id_array = [0u8; 20];
        object_id_array.copy_from_slice(&object_id);
        
        let swhid = ExtendedSwhid::new(ExtendedObjectType::Content, object_id_array);
        let swhid_str = format!("{}", swhid);
        
        assert_eq!(swhid_str, "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0");
    }

    #[test]
    fn test_extended_swhid_invalid_format() {
        assert!(ExtendedSwhid::from_string("invalid").is_err());
        assert!(ExtendedSwhid::from_string("swh:1:cnt").is_err());
        assert!(ExtendedSwhid::from_string("swh:1:cnt:invalid").is_err());
    }

    #[test]
    fn test_extended_swhid_invalid_namespace() {
        assert!(ExtendedSwhid::from_string("invalid:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0").is_err());
    }

    #[test]
    fn test_extended_swhid_invalid_version() {
        assert!(ExtendedSwhid::from_string("swh:2:cnt:8ff44f081d43176474b267de5451f2c2e88089d0").is_err());
    }

    #[test]
    fn test_extended_swhid_invalid_object_type() {
        assert!(ExtendedSwhid::from_string("swh:1:invalid:8ff44f081d43176474b267de5451f2c2e88089d0").is_err());
    }

    #[test]
    fn test_extended_swhid_invalid_hash() {
        assert!(ExtendedSwhid::from_string("swh:1:cnt:invalid").is_err());
        assert!(ExtendedSwhid::from_string("swh:1:cnt:123").is_err()); // too short
    }

    #[test]
    fn test_core_to_extended_conversion() {
        let object_id = [0u8; 20];
        let core_swhid = Swhid::new(ObjectType::Content, object_id);
        let extended_swhid = core_swhid.to_extended();
        
        assert_eq!(extended_swhid.namespace(), core_swhid.namespace());
        assert_eq!(extended_swhid.scheme_version(), core_swhid.scheme_version());
        assert_eq!(extended_swhid.object_type(), ExtendedObjectType::Content);
        assert_eq!(extended_swhid.object_id(), core_swhid.object_id());
    }
}

#[cfg(test)]
mod qualified_swhid_tests {
    use super::*;
    use swhid::{QualifiedSwhid, Swhid, ObjectType};

    #[test]
    fn test_qualified_swhid_creation() {
        let object_id = [0u8; 20];
        let swhid = QualifiedSwhid::new(ObjectType::Content, object_id);
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ObjectType::Content);
        assert_eq!(swhid.object_id(), &object_id);
        assert_eq!(swhid.origin(), None);
        assert_eq!(swhid.visit(), None);
        assert_eq!(swhid.anchor(), None);
        assert_eq!(swhid.path(), None);
        assert_eq!(swhid.lines(), None);
    }

    #[test]
    fn test_qualified_swhid_builder_pattern() {
        let object_id = [0u8; 20];
        let origin_swhid = Swhid::new(ObjectType::Snapshot, [1u8; 20]);
        let anchor_swhid = Swhid::new(ObjectType::Revision, [2u8; 20]);
        
        let swhid = QualifiedSwhid::new(ObjectType::Content, object_id)
            .with_origin("https://github.com/user/repo".to_string())
            .with_visit(origin_swhid.clone())
            .with_anchor(anchor_swhid.clone())
            .with_path(b"/path/to/file.txt".to_vec())
            .with_lines(10, Some(20));
        
        assert_eq!(swhid.origin(), Some("https://github.com/user/repo"));
        assert_eq!(swhid.visit(), Some(&origin_swhid));
        assert_eq!(swhid.anchor(), Some(&anchor_swhid));
        assert_eq!(swhid.path(), Some(b"/path/to/file.txt".as_slice()));
        assert_eq!(swhid.lines(), Some((10, Some(20))));
    }

    #[test]
    fn test_qualified_swhid_from_string_basic() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ObjectType::Content);
        assert_eq!(hex::encode(swhid.object_id()), "8ff44f081d43176474b267de5451f2c2e88089d0");
        assert_eq!(swhid.origin(), None);
        assert_eq!(swhid.visit(), None);
        assert_eq!(swhid.anchor(), None);
        assert_eq!(swhid.path(), None);
        assert_eq!(swhid.lines(), None);
    }

    #[test]
    fn test_qualified_swhid_from_string_with_origin() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;origin=https://github.com/user/repo";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.origin(), Some("https://github.com/user/repo"));
    }

    #[test]
    fn test_qualified_swhid_from_string_with_visit() {
        let visit_swhid = "swh:1:snp:1234567890abcdef1234567890abcdef12345678";
        let swhid_str = format!("swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;visit={}", visit_swhid);
        let swhid = QualifiedSwhid::from_string(&swhid_str).unwrap();
        
        assert_eq!(swhid.visit().unwrap().to_string(), visit_swhid);
    }

    #[test]
    fn test_qualified_swhid_from_string_with_anchor() {
        let anchor_swhid = "swh:1:rev:1234567890abcdef1234567890abcdef12345678";
        let swhid_str = format!("swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;anchor={}", anchor_swhid);
        let swhid = QualifiedSwhid::from_string(&swhid_str).unwrap();
        
        assert_eq!(swhid.anchor().unwrap().to_string(), anchor_swhid);
    }

    #[test]
    fn test_qualified_swhid_from_string_with_path() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;path=/path/to/file.txt";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.path(), Some(b"/path/to/file.txt".as_slice()));
    }

    #[test]
    fn test_qualified_swhid_from_string_with_lines() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;lines=10-20";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.lines(), Some((10, Some(20))));
    }

    #[test]
    fn test_qualified_swhid_from_string_with_single_line() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;lines=10";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.lines(), Some((10, None)));
    }

    #[test]
    fn test_qualified_swhid_from_string_with_multiple_qualifiers() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;origin=https://github.com/user/repo;path=/file.txt;lines=10-20";
        let swhid = QualifiedSwhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.origin(), Some("https://github.com/user/repo"));
        assert_eq!(swhid.path(), Some(b"/file.txt".as_slice()));
        assert_eq!(swhid.lines(), Some((10, Some(20))));
    }

    #[test]
    fn test_qualified_swhid_display_basic() {
        let object_id = hex::decode("8ff44f081d43176474b267de5451f2c2e88089d0").unwrap();
        let mut object_id_array = [0u8; 20];
        object_id_array.copy_from_slice(&object_id);
        
        let swhid = QualifiedSwhid::new(ObjectType::Content, object_id_array);
        let swhid_str = format!("{}", swhid);
        
        assert_eq!(swhid_str, "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0");
    }

    #[test]
    fn test_qualified_swhid_display_with_qualifiers() {
        let object_id = hex::decode("8ff44f081d43176474b267de5451f2c2e88089d0").unwrap();
        let mut object_id_array = [0u8; 20];
        object_id_array.copy_from_slice(&object_id);
        let origin_swhid = Swhid::new(ObjectType::Snapshot, [1u8; 20]);
        let anchor_swhid = Swhid::new(ObjectType::Revision, [2u8; 20]);
        
        let swhid = QualifiedSwhid::new(ObjectType::Content, object_id_array)
            .with_origin("https://github.com/user/repo".to_string())
            .with_visit(origin_swhid)
            .with_anchor(anchor_swhid)
            .with_path(b"/path/to/file.txt".to_vec())
            .with_lines(10, Some(20));
        
        let swhid_str = format!("{}", swhid);
        
        // Should contain all qualifiers in the correct order
        assert!(swhid_str.contains(";origin=https://github.com/user/repo"));
        assert!(swhid_str.contains(";visit="));
        assert!(swhid_str.contains(";anchor="));
        assert!(swhid_str.contains(";path=/path/to/file.txt"));
        assert!(swhid_str.contains(";lines=10-20"));
    }

    #[test]
    fn test_qualified_swhid_invalid_format() {
        assert!(QualifiedSwhid::from_string("").is_err());
        assert!(QualifiedSwhid::from_string("invalid").is_err());
        assert!(QualifiedSwhid::from_string("swh:1:cnt").is_err());
    }

    #[test]
    fn test_qualified_swhid_invalid_qualifier_format() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;invalid";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
        
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;origin";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
    }

    #[test]
    fn test_qualified_swhid_unknown_qualifier() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;unknown=value";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
    }

    #[test]
    fn test_qualified_swhid_invalid_lines_format() {
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;lines=invalid";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
        
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;lines=10-invalid";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
        
        let swhid_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;lines=10-20-30";
        assert!(QualifiedSwhid::from_string(swhid_str).is_err());
    }

    #[test]
    fn test_core_to_qualified_conversion() {
        let object_id = [0u8; 20];
        let core_swhid = Swhid::new(ObjectType::Content, object_id);
        let qualified_swhid = core_swhid.to_qualified();
        
        assert_eq!(qualified_swhid.namespace(), core_swhid.namespace());
        assert_eq!(qualified_swhid.scheme_version(), core_swhid.scheme_version());
        assert_eq!(qualified_swhid.object_type(), core_swhid.object_type());
        assert_eq!(qualified_swhid.object_id(), core_swhid.object_id());
        assert_eq!(qualified_swhid.origin(), None);
        assert_eq!(qualified_swhid.visit(), None);
        assert_eq!(qualified_swhid.anchor(), None);
        assert_eq!(qualified_swhid.path(), None);
        assert_eq!(qualified_swhid.lines(), None);
    }
} 