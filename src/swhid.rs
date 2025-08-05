use std::fmt;
use std::str::FromStr;
use crate::error::SwhidError;

/// Software Heritage object types (Core SWHID)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ObjectType {
    Content,
    Directory,
    Revision,
    Release,
    Snapshot,
}

/// Extended Software Heritage object types (Extended SWHID)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ExtendedObjectType {
    Content,
    Directory,
    Revision,
    Release,
    Snapshot,
    Origin,
    RawExtrinsicMetadata,
}

impl ObjectType {
    pub fn as_str(&self) -> &'static str {
        match self {
            ObjectType::Content => "cnt",
            ObjectType::Directory => "dir",
            ObjectType::Revision => "rev",
            ObjectType::Release => "rel",
            ObjectType::Snapshot => "snp",
        }
    }

    pub fn from_str(s: &str) -> Result<Self, SwhidError> {
        match s {
            "cnt" => Ok(ObjectType::Content),
            "dir" => Ok(ObjectType::Directory),
            "rev" => Ok(ObjectType::Revision),
            "rel" => Ok(ObjectType::Release),
            "snp" => Ok(ObjectType::Snapshot),
            _ => Err(SwhidError::InvalidObjectType(s.to_string())),
        }
    }
}

impl ExtendedObjectType {
    pub fn as_str(&self) -> &'static str {
        match self {
            ExtendedObjectType::Content => "cnt",
            ExtendedObjectType::Directory => "dir",
            ExtendedObjectType::Revision => "rev",
            ExtendedObjectType::Release => "rel",
            ExtendedObjectType::Snapshot => "snp",
            ExtendedObjectType::Origin => "ori",
            ExtendedObjectType::RawExtrinsicMetadata => "emd",
        }
    }

    pub fn from_str(s: &str) -> Result<Self, SwhidError> {
        match s {
            "cnt" => Ok(ExtendedObjectType::Content),
            "dir" => Ok(ExtendedObjectType::Directory),
            "rev" => Ok(ExtendedObjectType::Revision),
            "rel" => Ok(ExtendedObjectType::Release),
            "snp" => Ok(ExtendedObjectType::Snapshot),
            "ori" => Ok(ExtendedObjectType::Origin),
            "emd" => Ok(ExtendedObjectType::RawExtrinsicMetadata),
            _ => Err(SwhidError::InvalidObjectType(s.to_string())),
        }
    }
}

impl From<ObjectType> for ExtendedObjectType {
    fn from(obj_type: ObjectType) -> Self {
        match obj_type {
            ObjectType::Content => ExtendedObjectType::Content,
            ObjectType::Directory => ExtendedObjectType::Directory,
            ObjectType::Revision => ExtendedObjectType::Revision,
            ObjectType::Release => ExtendedObjectType::Release,
            ObjectType::Snapshot => ExtendedObjectType::Snapshot,
        }
    }
}

impl fmt::Display for ObjectType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl fmt::Display for ExtendedObjectType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Core Software Heritage Identifier
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Swhid {
    namespace: String,
    scheme_version: u32,
    object_type: ObjectType,
    object_id: [u8; 20],
}

/// Extended Software Heritage Identifier
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ExtendedSwhid {
    namespace: String,
    scheme_version: u32,
    object_type: ExtendedObjectType,
    object_id: [u8; 20],
}

/// Qualified Software Heritage Identifier
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct QualifiedSwhid {
    namespace: String,
    scheme_version: u32,
    object_type: ObjectType,
    object_id: [u8; 20],
    origin: Option<String>,
    visit: Option<Swhid>,
    anchor: Option<Swhid>,
    path: Option<Vec<u8>>,
    lines: Option<(u32, Option<u32>)>,
}

impl Swhid {
    pub const NAMESPACE: &'static str = "swh";
    pub const SCHEME_VERSION: u32 = 1;

    pub fn new(object_type: ObjectType, object_id: [u8; 20]) -> Self {
        Self {
            namespace: Self::NAMESPACE.to_string(),
            scheme_version: Self::SCHEME_VERSION,
            object_type,
            object_id,
        }
    }

    pub fn namespace(&self) -> &str {
        &self.namespace
    }

    pub fn scheme_version(&self) -> u32 {
        self.scheme_version
    }

    pub fn object_type(&self) -> ObjectType {
        self.object_type
    }

    pub fn object_id(&self) -> &[u8; 20] {
        &self.object_id
    }

    /// Convert to Extended SWHID
    pub fn to_extended(&self) -> ExtendedSwhid {
        ExtendedSwhid {
            namespace: self.namespace.clone(),
            scheme_version: self.scheme_version,
            object_type: self.object_type.into(),
            object_id: self.object_id,
        }
    }

    /// Convert to Qualified SWHID
    pub fn to_qualified(&self) -> QualifiedSwhid {
        QualifiedSwhid {
            namespace: self.namespace.clone(),
            scheme_version: self.scheme_version,
            object_type: self.object_type,
            object_id: self.object_id,
            origin: None,
            visit: None,
            anchor: None,
            path: None,
            lines: None,
        }
    }

    /// Parse SWHID from string
    pub fn from_string(s: &str) -> Result<Self, SwhidError> {
        let parts: Vec<&str> = s.split(':').collect();
        
        if parts.len() != 4 {
            return Err(SwhidError::InvalidFormat(format!(
                "SWHID must have 4 parts, got {}: {}", 
                parts.len(), s
            )));
        }

        let namespace = parts[0];
        if namespace != Self::NAMESPACE {
            return Err(SwhidError::InvalidNamespace(namespace.to_string()));
        }

        let scheme_version = parts[1].parse::<u32>()
            .map_err(|_| SwhidError::InvalidVersion(parts[1].to_string()))?;
        
        if scheme_version != Self::SCHEME_VERSION {
            return Err(SwhidError::InvalidVersion(parts[1].to_string()));
        }

        let object_type = ObjectType::from_str(parts[2])?;
        
        let object_id = hex::decode(parts[3])
            .map_err(|_| SwhidError::InvalidHash(parts[3].to_string()))?;
        
        if object_id.len() != 20 {
            return Err(SwhidError::InvalidHashLength(object_id.len()));
        }

        let mut object_id_array = [0u8; 20];
        object_id_array.copy_from_slice(&object_id);

        Ok(Self {
            namespace: namespace.to_string(),
            scheme_version,
            object_type,
            object_id: object_id_array,
        })
    }
}

impl ExtendedSwhid {
    pub const NAMESPACE: &'static str = "swh";
    pub const SCHEME_VERSION: u32 = 1;

    pub fn new(object_type: ExtendedObjectType, object_id: [u8; 20]) -> Self {
        Self {
            namespace: Self::NAMESPACE.to_string(),
            scheme_version: Self::SCHEME_VERSION,
            object_type,
            object_id,
        }
    }

    pub fn namespace(&self) -> &str {
        &self.namespace
    }

    pub fn scheme_version(&self) -> u32 {
        self.scheme_version
    }

    pub fn object_type(&self) -> ExtendedObjectType {
        self.object_type
    }

    pub fn object_id(&self) -> &[u8; 20] {
        &self.object_id
    }

    /// Parse Extended SWHID from string
    pub fn from_string(s: &str) -> Result<Self, SwhidError> {
        let parts: Vec<&str> = s.split(':').collect();
        
        if parts.len() != 4 {
            return Err(SwhidError::InvalidFormat(format!(
                "Extended SWHID must have 4 parts, got {}: {}", 
                parts.len(), s
            )));
        }

        let namespace = parts[0];
        if namespace != Self::NAMESPACE {
            return Err(SwhidError::InvalidNamespace(namespace.to_string()));
        }

        let scheme_version = parts[1].parse::<u32>()
            .map_err(|_| SwhidError::InvalidVersion(parts[1].to_string()))?;
        
        if scheme_version != Self::SCHEME_VERSION {
            return Err(SwhidError::InvalidVersion(parts[1].to_string()));
        }

        let object_type = ExtendedObjectType::from_str(parts[2])?;
        
        let object_id = hex::decode(parts[3])
            .map_err(|_| SwhidError::InvalidHash(parts[3].to_string()))?;
        
        if object_id.len() != 20 {
            return Err(SwhidError::InvalidHashLength(object_id.len()));
        }

        let mut object_id_array = [0u8; 20];
        object_id_array.copy_from_slice(&object_id);

        Ok(Self {
            namespace: namespace.to_string(),
            scheme_version,
            object_type,
            object_id: object_id_array,
        })
    }
}

impl QualifiedSwhid {
    pub const NAMESPACE: &'static str = "swh";
    pub const SCHEME_VERSION: u32 = 1;

    pub fn new(object_type: ObjectType, object_id: [u8; 20]) -> Self {
        Self {
            namespace: Self::NAMESPACE.to_string(),
            scheme_version: Self::SCHEME_VERSION,
            object_type,
            object_id,
            origin: None,
            visit: None,
            anchor: None,
            path: None,
            lines: None,
        }
    }

    pub fn with_origin(mut self, origin: String) -> Self {
        self.origin = Some(origin);
        self
    }

    pub fn with_visit(mut self, visit: Swhid) -> Self {
        self.visit = Some(visit);
        self
    }

    pub fn with_anchor(mut self, anchor: Swhid) -> Self {
        self.anchor = Some(anchor);
        self
    }

    pub fn with_path(mut self, path: Vec<u8>) -> Self {
        self.path = Some(path);
        self
    }

    pub fn with_lines(mut self, start: u32, end: Option<u32>) -> Self {
        self.lines = Some((start, end));
        self
    }

    pub fn namespace(&self) -> &str {
        &self.namespace
    }

    pub fn scheme_version(&self) -> u32 {
        self.scheme_version
    }

    pub fn object_type(&self) -> ObjectType {
        self.object_type
    }

    pub fn object_id(&self) -> &[u8; 20] {
        &self.object_id
    }

    pub fn origin(&self) -> Option<&str> {
        self.origin.as_deref()
    }

    pub fn visit(&self) -> Option<&Swhid> {
        self.visit.as_ref()
    }

    pub fn anchor(&self) -> Option<&Swhid> {
        self.anchor.as_ref()
    }

    pub fn path(&self) -> Option<&[u8]> {
        self.path.as_deref()
    }

    pub fn lines(&self) -> Option<(u32, Option<u32>)> {
        self.lines
    }

    /// Parse Qualified SWHID from string
    pub fn from_string(s: &str) -> Result<Self, SwhidError> {
        // Split by semicolon to separate core SWHID from qualifiers
        let parts: Vec<&str> = s.split(';').collect();
        if parts.is_empty() {
            return Err(SwhidError::InvalidFormat("Empty SWHID string".to_string()));
        }

        // Parse the core SWHID part
        let core_swhid = Swhid::from_string(parts[0])?;
        
        let mut qualified = Self {
            namespace: core_swhid.namespace().to_string(),
            scheme_version: core_swhid.scheme_version(),
            object_type: core_swhid.object_type(),
            object_id: *core_swhid.object_id(),
            origin: None,
            visit: None,
            anchor: None,
            path: None,
            lines: None,
        };

        // Parse qualifiers
        for qualifier in &parts[1..] {
            let qualifier_parts: Vec<&str> = qualifier.split('=').collect();
            if qualifier_parts.len() != 2 {
                return Err(SwhidError::InvalidFormat(format!(
                    "Invalid qualifier format: {}", qualifier
                )));
            }

            let key = qualifier_parts[0];
            let value = qualifier_parts[1];

            match key {
                "origin" => {
                    qualified.origin = Some(value.to_string());
                }
                "visit" => {
                    let visit_swhid = Swhid::from_string(value)?;
                    qualified.visit = Some(visit_swhid);
                }
                "anchor" => {
                    let anchor_swhid = Swhid::from_string(value)?;
                    qualified.anchor = Some(anchor_swhid);
                }
                "path" => {
                    qualified.path = Some(value.as_bytes().to_vec());
                }
                "lines" => {
                    let lines_parts: Vec<&str> = value.split('-').collect();
                    if lines_parts.len() > 2 {
                        return Err(SwhidError::InvalidFormat(format!(
                            "Invalid lines format: {}", value
                        )));
                    }
                    
                    let start = lines_parts[0].parse::<u32>()
                        .map_err(|_| SwhidError::InvalidFormat(format!(
                            "Invalid start line: {}", lines_parts[0]
                        )))?;
                    
                    let end = if lines_parts.len() == 2 {
                        Some(lines_parts[1].parse::<u32>()
                            .map_err(|_| SwhidError::InvalidFormat(format!(
                                "Invalid end line: {}", lines_parts[1]
                            )))?)
                    } else {
                        None
                    };
                    
                    qualified.lines = Some((start, end));
                }
                _ => {
                    return Err(SwhidError::InvalidFormat(format!(
                        "Unknown qualifier: {}", key
                    )));
                }
            }
        }

        Ok(qualified)
    }
}

impl FromStr for Swhid {
    type Err = SwhidError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_string(s)
    }
}

impl FromStr for ExtendedSwhid {
    type Err = SwhidError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_string(s)
    }
}

impl FromStr for QualifiedSwhid {
    type Err = SwhidError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        Self::from_string(s)
    }
}

impl fmt::Display for Swhid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}:{}:{}", 
            self.namespace, 
            self.scheme_version, 
            self.object_type, 
            hex::encode(self.object_id)
        )
    }
}

impl fmt::Display for ExtendedSwhid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}:{}:{}:{}", 
            self.namespace, 
            self.scheme_version, 
            self.object_type, 
            hex::encode(self.object_id)
        )
    }
}

impl fmt::Display for QualifiedSwhid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Start with core SWHID
        write!(f, "{}:{}:{}:{}", 
            self.namespace, 
            self.scheme_version, 
            self.object_type, 
            hex::encode(self.object_id)
        )?;

        // Add qualifiers in the specified order: origin, visit, anchor, path, lines
        if let Some(ref origin) = self.origin {
            write!(f, ";origin={}", origin)?;
        }

        if let Some(ref visit) = self.visit {
            write!(f, ";visit={}", visit)?;
        }

        if let Some(ref anchor) = self.anchor {
            write!(f, ";anchor={}", anchor)?;
        }

        if let Some(ref path) = self.path {
            write!(f, ";path={}", String::from_utf8_lossy(path))?;
        }

        if let Some((start, end)) = self.lines {
            match end {
                Some(end) => write!(f, ";lines={}-{}", start, end)?,
                None => write!(f, ";lines={}", start)?,
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_swhid_creation() {
        let object_id = [0u8; 20];
        let swhid = Swhid::new(ObjectType::Content, object_id);
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ObjectType::Content);
        assert_eq!(swhid.object_id(), &object_id);
    }

    #[test]
    fn test_swhid_parsing() {
        let swhid_str = "swh:1:cnt:0000000000000000000000000000000000000000";
        let swhid = Swhid::from_string(swhid_str).unwrap();
        
        assert_eq!(swhid.namespace(), "swh");
        assert_eq!(swhid.scheme_version(), 1);
        assert_eq!(swhid.object_type(), ObjectType::Content);
        assert_eq!(swhid.object_id(), &[0u8; 20]);
    }

    #[test]
    fn test_swhid_display() {
        let object_id = [0u8; 20];
        let swhid = Swhid::new(ObjectType::Content, object_id);
        let expected = "swh:1:cnt:0000000000000000000000000000000000000000";
        
        assert_eq!(swhid.to_string(), expected);
    }

    #[test]
    fn test_invalid_format() {
        let result = Swhid::from_string("invalid");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_namespace() {
        let result = Swhid::from_string("invalid:1:cnt:0000000000000000000000000000000000000000");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_object_type() {
        let result = Swhid::from_string("swh:1:invalid:0000000000000000000000000000000000000000");
        assert!(result.is_err());
    }

    #[test]
    fn test_invalid_hash_length() {
        let result = Swhid::from_string("swh:1:cnt:123");
        assert!(result.is_err());
    }
} 