use clap::Parser;
use std::io::Read;
use std::path::Path;
use swhid::{
    directory::traverse_directory_recursively, SwhidComputer,
};

#[derive(Parser)]
#[command(name = "swhid-cli")]
#[command(about = "Compute Software Heritage persistent identifiers")]
struct Cli {
    /// Type of object to identify
    #[arg(short, long, default_value = "auto")]
    obj_type: String,

    /// Follow symlinks (default: follow)
    #[arg(long, default_value = "true")]
    dereference: bool,

    /// Don't follow symlinks
    #[arg(long, conflicts_with = "dereference")]
    no_dereference: bool,

    /// Show filename in output
    #[arg(long, default_value = "true")]
    filename: bool,

    /// Exclude directories using glob patterns
    #[arg(short, long)]
    exclude: Vec<String>,

    /// Reference identifier to be compared with computed one
    #[arg(short, long)]
    verify: Option<String>,

    /// Compute SWHID recursively
    #[arg(short, long)]
    recursive: bool,

    /// Treat file as archive and compute directory SWHID for its contents
    #[arg(long)]
    archive: bool,

    /// Objects to identify
    objects: Vec<String>,
}

fn identify_object(
    obj_type: &str,
    follow_symlinks: bool,
    exclude_patterns: &[String],
    obj: &str,
    recursive: bool,
    is_archive: bool,
) -> Result<String, Box<dyn std::error::Error>> {
    let mut computer = SwhidComputer::new()
        .with_follow_symlinks(follow_symlinks)
        .with_exclude_patterns(exclude_patterns);
    
    if recursive {
        computer = computer.with_recursive(true);
    }

    let obj_type = if obj_type == "auto" {
        if obj == "-" {
            "content"
        } else if Path::new(obj).is_file() {
            if is_archive {
                "directory" // Treat as directory when --archive flag is used
            } else {
                "content"
            }
        } else if Path::new(obj).is_dir() {
            // Check if it's a Git repository first
            let git_path = Path::new(obj).join(".git");
            if git_path.exists() && git_path.is_dir() {
                "snapshot"
            } else {
                "directory"
            }
        } else {
            return Err("cannot detect object type".into());
        }
    } else {
        obj_type
    };

    match obj_type {
        "content" => {
            if obj == "-" {
                let mut content = Vec::new();
                std::io::stdin().read_to_end(&mut content)?;
                let swhid = computer.compute_content_swhid(&content)?;
                Ok(swhid.to_string())
            } else {
                let swhid = computer.compute_file_swhid(obj)?;
                Ok(swhid.to_string())
            }
        }
        "directory" => {
            if is_archive {
                // Process as archive when --archive flag is used
                let swhid = computer.compute_archive_directory_swhid(obj)?;
                Ok(swhid.to_string())
            } else {
                if recursive {
                    let objects = traverse_directory_recursively(obj, exclude_patterns, follow_symlinks)?;
                    let mut results = Vec::new();
                    for (path, mut obj) in objects {
                        // The TreeObject already has its SWHID computed
                        let swhid = obj.swhid();
                        let display_path = if computer.filename {
                            path.to_string_lossy().to_string()
                        } else {
                            "".to_string()
                        };
                        results.push(format!("{}\t{}", swhid, display_path));
                    }
                    Ok(results.join("\n"))
                } else {
                    let swhid = computer.compute_directory_swhid(obj)?;
                    Ok(swhid.to_string())
                }
            }
        }
        "snapshot" => {
            let swhid = computer.compute_git_snapshot_swhid(obj)?;
            Ok(swhid.to_string())
        }
        _ => Err("invalid object type".into()),
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();

    let follow_symlinks = !cli.no_dereference;

    for obj in &cli.objects {
        let result = identify_object(&cli.obj_type, follow_symlinks, &cli.exclude, obj, cli.recursive, cli.archive)?;

        if let Some(verify_swhid) = &cli.verify {
            let computer = SwhidComputer::new();
            let is_valid = computer.verify_swhid(obj, verify_swhid)?;
            if is_valid {
                println!("✓ SWHID verification successful");
            } else {
                println!("✗ SWHID verification failed");
                std::process::exit(1);
            }
        } else {
            let display_path = if cli.filename && obj != "-" {
                format!("\t{}", obj)
            } else {
                "".to_string()
            };
            println!("{}{}", result, display_path);
        }
    }

    Ok(())
} 