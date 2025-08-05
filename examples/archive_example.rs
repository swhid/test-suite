use swhid::SwhidComputer;
use std::fs;
use std::fs::File;
use tempfile::TempDir;
use tar::Builder;

fn main() {
    println!("=== Archive Directory SWHID Example ===\n");

    // Create a temporary directory with some content
    let temp_dir = TempDir::new().unwrap();
    let archive_contents = temp_dir.path().join("archive_contents");
    fs::create_dir(&archive_contents).unwrap();
    
    // Create some files in the archive
    fs::write(archive_contents.join("file1.txt"), b"Hello, World!").unwrap();
    fs::write(archive_contents.join("file2.txt"), b"Another file").unwrap();
    
    // Create a subdirectory
    let subdir = archive_contents.join("subdir");
    fs::create_dir(&subdir).unwrap();
    fs::write(subdir.join("subfile.txt"), b"File in subdirectory").unwrap();

    // Create a tar archive
    let archive_path = temp_dir.path().join("example.tar");
    {
        let file = File::create(&archive_path).unwrap();
        let mut builder = Builder::new(file);
        builder.append_dir_all("", &archive_contents).unwrap();
        builder.finish().unwrap();
    }

    println!("Created archive at: {}", archive_path.display());
    println!("Archive contents:");
    println!("  - file1.txt");
    println!("  - file2.txt");
    println!("  - subdir/subfile.txt");

    // Compute directory SWHID for the archive contents
    let computer = SwhidComputer::new();
    match computer.compute_archive_directory_swhid(archive_path.to_str().unwrap()) {
        Ok(swhid) => {
            println!("\nArchive Directory SWHID: {}", swhid);
            println!("Object Type: {:?}", swhid.object_type());
        }
        Err(e) => {
            println!("Error computing archive SWHID: {}", e);
        }
    }

    // Also compute SWHID for the original directory for comparison
    match computer.compute_directory_swhid(&archive_contents) {
        Ok(swhid) => {
            println!("\nOriginal Directory SWHID: {}", swhid);
            println!("Object Type: {:?}", swhid.object_type());
        }
        Err(e) => {
            println!("Error computing directory SWHID: {}", e);
        }
    }

    println!("\n=== Usage Notes ===");
    println!("To compute directory SWHID for an archive from command line:");
    println!("  swhid-cli --archive archive.tar");
    println!("  swhid-cli --archive archive.zip");
    println!("  swhid-cli --archive archive.tar.gz");
    println!("  swhid-cli --archive archive.tar.bz2");
    println!("\nThe --archive flag explicitly tells the tool to treat the file as an archive");
    println!("and compute the directory SWHID for its contents.");
} 