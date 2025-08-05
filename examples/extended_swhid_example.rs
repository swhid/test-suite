use swhid::{Swhid, ExtendedSwhid, ExtendedObjectType, QualifiedSwhid, ObjectType};

fn main() {
    println!("=== Extended SWHID Example ===\n");

    // Create a core SWHID
    let object_id = [0x8f, 0xf4, 0x4f, 0x08, 0x1d, 0x43, 0x17, 0x64, 0x74, 0xb2, 
                     0x67, 0xde, 0x54, 0x51, 0xf2, 0xc2, 0xe8, 0x80, 0x89, 0xd0];
    let core_swhid = Swhid::new(ObjectType::Content, object_id);
    println!("Core SWHID: {}", core_swhid);

    // Convert to Extended SWHID
    let extended_swhid = core_swhid.to_extended();
    println!("Extended SWHID: {}", extended_swhid);

    // Create Extended SWHID with Origin type
    let origin_swhid = ExtendedSwhid::new(ExtendedObjectType::Origin, object_id);
    println!("Origin SWHID: {}", origin_swhid);

    // Create Extended SWHID with Raw Extrinsic Metadata type
    let emd_swhid = ExtendedSwhid::new(ExtendedObjectType::RawExtrinsicMetadata, object_id);
    println!("Raw Extrinsic Metadata SWHID: {}", emd_swhid);

    // Parse Extended SWHID from string
    let parsed_extended = ExtendedSwhid::from_string("swh:1:ori:8ff44f081d43176474b267de5451f2c2e88089d0").unwrap();
    println!("Parsed Extended SWHID: {}", parsed_extended);

    println!("\n=== Qualified SWHID Example ===\n");

    // Create a Qualified SWHID with qualifiers
    let qualified_swhid = QualifiedSwhid::new(ObjectType::Content, object_id)
        .with_origin("https://github.com/user/repo".to_string())
        .with_path(b"/src/main.rs".to_vec())
        .with_lines(10, Some(20));
    
    println!("Qualified SWHID: {}", qualified_swhid);

    // Parse Qualified SWHID from string
    let qualified_str = "swh:1:cnt:8ff44f081d43176474b267de5451f2c2e88089d0;origin=https://github.com/user/repo;path=/src/main.rs;lines=10-20";
    let parsed_qualified = QualifiedSwhid::from_string(qualified_str).unwrap();
    println!("Parsed Qualified SWHID: {}", parsed_qualified);

    // Access qualifiers
    println!("Origin: {:?}", parsed_qualified.origin());
    println!("Path: {:?}", parsed_qualified.path().map(|p| String::from_utf8_lossy(p)));
    println!("Lines: {:?}", parsed_qualified.lines());

    println!("\n=== Error Handling Example ===\n");

    // Test invalid Extended SWHID
    match ExtendedSwhid::from_string("invalid") {
        Ok(_) => println!("Unexpected success"),
        Err(e) => println!("Expected error: {}", e),
    }

    // Test invalid Qualified SWHID
    match QualifiedSwhid::from_string("swh:1:cnt:invalid;unknown=value") {
        Ok(_) => println!("Unexpected success"),
        Err(e) => println!("Expected error: {}", e),
    }
} 