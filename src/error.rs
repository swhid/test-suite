use std::fmt;
use std::io;

#[derive(Debug)]
pub enum SwhidError {
    Io(io::Error),
    InvalidFormat(String),
    InvalidNamespace(String),
    InvalidVersion(String),
    InvalidObjectType(String),
    InvalidHash(String),
    InvalidHashLength(usize),
    InvalidPath(String),
    DuplicateEntry(String),
    UnsupportedOperation(String),
    InvalidQualifier(String),
    InvalidQualifierValue(String),
    UnknownQualifier(String),
}

impl fmt::Display for SwhidError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SwhidError::Io(err) => write!(f, "I/O error: {}", err),
            SwhidError::InvalidFormat(msg) => write!(f, "Invalid format: {}", msg),
            SwhidError::InvalidNamespace(ns) => write!(f, "Invalid namespace: {}", ns),
            SwhidError::InvalidVersion(ver) => write!(f, "Invalid version: {}", ver),
            SwhidError::InvalidObjectType(ot) => write!(f, "Invalid object type: {}", ot),
            SwhidError::InvalidHash(hash) => write!(f, "Invalid hash: {}", hash),
            SwhidError::InvalidHashLength(len) => write!(f, "Invalid hash length: {} (expected 20)", len),
            SwhidError::InvalidPath(path) => write!(f, "Invalid path: {}", path),
            SwhidError::DuplicateEntry(entry) => write!(f, "Duplicate entry: {}", entry),
            SwhidError::UnsupportedOperation(op) => write!(f, "Unsupported operation: {}", op),
            SwhidError::InvalidQualifier(qual) => write!(f, "Invalid qualifier: {}", qual),
            SwhidError::InvalidQualifierValue(val) => write!(f, "Invalid qualifier value: {}", val),
            SwhidError::UnknownQualifier(qual) => write!(f, "Unknown qualifier: {}", qual),
        }
    }
}

impl std::error::Error for SwhidError {}

impl From<io::Error> for SwhidError {
    fn from(err: io::Error) -> Self {
        SwhidError::Io(err)
    }
}

impl From<hex::FromHexError> for SwhidError {
    fn from(err: hex::FromHexError) -> Self {
        SwhidError::InvalidHash(err.to_string())
    }
} 