use std::io::{self, Read};
use std::path::Path;
use clap::{Parser, ValueEnum};
use swhid::{SwhidComputer, SwhidError, traverse_directory_recursively, TreeObject};

#[derive(Parser)]
#[command(
    name = "swhid-cli",
    about = "Compute Software Heritage persistent identifiers (SWHID)",
    long_about = "Compute the Software Heritage persistent identifier (SWHID) for the given source code object(s).

For more details about SWHIDs see:
https://docs.softwareheritage.org/devel/swh-model/persistent-identifiers.html

Tip: you can pass \"-\" to identify the content of standard input.

Examples:
  $ swhid-cli fork.c kmod.c sched/deadline.c
  swh:1:cnt:2e391c754ae730bd2d8520c2ab497c403220c6e3    fork.c
  swh:1:cnt:0277d1216f80ae1adeed84a686ed34c9b2931fc2    kmod.c
  swh:1:cnt:57b939c81bce5d06fa587df8915f05affbe22b82    sched/deadline.c

  $ swhid-cli --no-filename /usr/src/linux/kernel/
  swh:1:dir:f9f858a48d663b3809c9e2f336412717496202ab

  $ echo \"Hello, World!\" | swhid-cli -
  swh:1:cnt:8ab686eafeb1f44702738c8b0f24f2567c36da6d"
)]
struct Cli {
    /// Type of object to identify
    #[arg(short, long, value_enum, default_value_t = ObjectType::Auto)]
    object_type: ObjectType,

    /// Follow symlinks for objects passed as arguments
    #[arg(long, default_value_t = true)]
    dereference: bool,

    /// Do not follow symlinks for objects passed as arguments
    #[arg(long, conflicts_with = "dereference")]
    no_dereference: bool,

    /// Show/hide file name
    #[arg(long, default_value_t = true)]
    filename: bool,

    /// Hide file name (same as --no-filename)
    #[arg(long)]
    no_filename: bool,

    /// Exclude directories using glob patterns (e.g., "*.git" to exclude all .git directories)
    #[arg(short, long, value_name = "PATTERN")]
    exclude: Vec<String>,

    /// Reference identifier to be compared with computed one
    #[arg(short, long, value_name = "SWHID")]
    verify: Option<String>,

    /// Compute SWHID recursively (only for directories)
    #[arg(short, long)]
    recursive: bool,

    /// Objects to identify (files, directories, or "-" for stdin)
    #[arg(required = true)]
    objects: Vec<String>,
}

#[derive(ValueEnum, Clone, Debug, PartialEq)]
enum ObjectType {
    Auto,
    Content,
    Directory,
    Origin,
    Snapshot,
}

impl ObjectType {
    fn as_str(&self) -> &'static str {
        match self {
            ObjectType::Auto => "auto",
            ObjectType::Content => "content",
            ObjectType::Directory => "directory",
            ObjectType::Origin => "origin",
            ObjectType::Snapshot => "snapshot",
        }
    }
}

fn detect_object_type(obj: &str) -> Result<ObjectType, SwhidError> {
    if obj == "-" {
        return Ok(ObjectType::Content);
    }

    let path = Path::new(obj);
    if path.is_file() {
        Ok(ObjectType::Content)
    } else if path.is_dir() {
        Ok(ObjectType::Directory)
    } else {
        // Try to parse as URL
        if obj.contains("://") {
            Ok(ObjectType::Origin)
        } else {
            Err(SwhidError::InvalidPath(format!(
                "Cannot detect object type for {}",
                obj
            )))
        }
    }
}

fn identify_object(
    obj_type: &ObjectType,
    follow_symlinks: bool,
    exclude_patterns: &[String],
    obj: &str,
) -> Result<String, SwhidError> {
    let actual_type = match obj_type {
        ObjectType::Auto => detect_object_type(obj)?,
        _ => obj_type.clone(),
    };

    let computer = SwhidComputer::new()
        .with_follow_symlinks(follow_symlinks)
        .with_exclude_patterns(exclude_patterns.to_vec());

    match actual_type {
        ObjectType::Content => {
            if obj == "-" {
                // Read from stdin
                let mut data = Vec::new();
                io::stdin().read_to_end(&mut data)?;
                let content = swhid::content::Content::from_data(data);
                Ok(content.swhid().to_string())
            } else {
                let swhid = computer.compute_swhid(obj)?;
                Ok(swhid.to_string())
            }
        }
        ObjectType::Directory => {
            let swhid = computer.compute_directory_swhid(obj)?;
            Ok(swhid.to_string())
        }
        ObjectType::Origin => {
            // For now, we'll implement a basic origin SWHID
            // In the full implementation, this would use the Origin model
            Err(SwhidError::UnsupportedOperation(
                "Origin SWHID computation not yet implemented".to_string(),
            ))
        }
        ObjectType::Snapshot => {
            // For now, we'll implement a basic snapshot SWHID
            // In the full implementation, this would use the Snapshot model
            Err(SwhidError::UnsupportedOperation(
                "Snapshot SWHID computation not yet implemented".to_string(),
            ))
        }
        ObjectType::Auto => unreachable!(), // Already handled above
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();

    // Handle --no-dereference flag
    let follow_symlinks = !cli.no_dereference;

    // Validate arguments
    if let Some(ref verify_swhid) = cli.verify {
        if cli.objects.len() != 1 {
            eprintln!("Error: verification requires a single object");
            std::process::exit(1);
        }
    }

    if cli.recursive {
        if cli.objects.len() != 1 {
            eprintln!("Error: recursive option requires a single object");
            std::process::exit(1);
        }

        let obj = &cli.objects[0];
        if !Path::new(obj).is_dir() {
            eprintln!("Warning: recursive option disabled, input is not a directory object");
        } else if cli.object_type != ObjectType::Auto && cli.object_type != ObjectType::Directory {
            eprintln!("Error: recursive identification is supported only for directories");
            std::process::exit(1);
        } else if cli.verify.is_some() {
            eprintln!("Error: verification of recursive object identification is not supported");
            std::process::exit(1);
        } else {
            // Implement recursive directory traversal
            let objects = traverse_directory_recursively(
                obj,
                &cli.exclude,
                follow_symlinks,
            )?;

            for (path, mut tree_obj) in objects {
                let swhid = tree_obj.swhid();
                let path_str = path.to_string_lossy();
                
                if cli.filename && !cli.no_filename {
                    println!("{}\t{}", swhid, path_str);
                } else {
                    println!("{}", swhid);
                }
            }
            return Ok(());
        }
    }

    // Process objects
    if let Some(ref verify_swhid) = cli.verify {
        let obj = &cli.objects[0];
        let computed_swhid = identify_object(
            &cli.object_type,
            follow_symlinks,
            &cli.exclude,
            obj,
        )?;

        if verify_swhid == &computed_swhid {
            println!("SWHID match: {}", computed_swhid);
            std::process::exit(0);
        } else {
            println!("SWHID mismatch: {} != {}", verify_swhid, computed_swhid);
            std::process::exit(1);
        }
    } else {
        for obj in &cli.objects {
            match identify_object(&cli.object_type, follow_symlinks, &cli.exclude, obj) {
                Ok(swhid) => {
                                    let show_filename = cli.filename && !cli.no_filename;
                if show_filename {
                    println!("{}\t{}", swhid, obj);
                } else {
                    println!("{}", swhid);
                }
                }
                Err(e) => {
                    eprintln!("Error processing {}: {}", obj, e);
                    std::process::exit(1);
                }
            }
        }
    }

    Ok(())
} 