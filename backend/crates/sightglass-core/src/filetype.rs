//! File type classification from a file name and its first bytes.
//!
//! Only the leading bytes are inspected, so classification never needs a whole file in memory.

/// How many leading bytes [`classify`] looks at; callers can pass more or fewer.
pub const HEAD_SIZE: usize = 8192;

/// Broad kind of file, used to decide how a file is diffed and which rules apply.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Category {
    /// Python source code.
    Python,
    /// Other text.
    Text,
    /// A compiled binary: ELF, Mach-O or PE.
    Compiled,
    /// A compressed or archive container.
    Archive,
    /// Anything else, including binary data with no known signature.
    Other,
}

impl Category {
    /// Lowercase name as stored in the database.
    #[must_use]
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Python => "python",
            Self::Text => "text",
            Self::Compiled => "compiled",
            Self::Archive => "archive",
            Self::Other => "other",
        }
    }
}

/// The result of classifying a file.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileType {
    /// Broad kind.
    pub category: Category,
    /// Specific format, such as `elf`, `zip`, `utf-8` text or `python`.
    pub format: &'static str,
    /// Text encoding for text and Python files: `utf-8`, `utf-8-sig`, `utf-16le` or `utf-16be`.
    pub encoding: Option<&'static str>,
}

impl FileType {
    const fn binary(category: Category, format: &'static str) -> Self {
        Self {
            category,
            format,
            encoding: None,
        }
    }
}

const PYTHON_EXTENSIONS: [&str; 3] = [".py", ".pyi", ".pyw"];

/// Classify a file from its name (any path; only the extension is used) and its leading bytes.
#[must_use]
pub fn classify(name: &str, head: &[u8]) -> FileType {
    if let Some(binary) = binary_signature(head) {
        return binary;
    }
    let Some(encoding) = text_encoding(head) else {
        return FileType::binary(Category::Other, "binary");
    };
    let lower = name.to_ascii_lowercase();
    let python = PYTHON_EXTENSIONS.iter().any(|ext| lower.ends_with(ext)) || python_shebang(head);
    if python {
        FileType {
            category: Category::Python,
            format: "python",
            encoding: Some(encoding),
        }
    } else {
        FileType {
            category: Category::Text,
            format: "text",
            encoding: Some(encoding),
        }
    }
}

fn binary_signature(head: &[u8]) -> Option<FileType> {
    use Category::{Archive, Compiled};
    let found = match head {
        [0x7f, b'E', b'L', b'F', ..] => FileType::binary(Compiled, "elf"),
        [0xfe, 0xed, 0xfa, 0xce | 0xcf, ..] | [0xce | 0xcf, 0xfa, 0xed, 0xfe, ..] => {
            FileType::binary(Compiled, "macho")
        }
        // Universal Mach-O and Java class files share 0xcafebabe; a fat header's next word is a small arch count,
        // while a class file's is its version (major 45 or later).
        [0xca, 0xfe, 0xba, 0xbe, a, b, c, d, ..] if u32::from_be_bytes([*a, *b, *c, *d]) < 45 => {
            FileType::binary(Compiled, "macho")
        }
        [b'M', b'Z', ..] => FileType::binary(Compiled, "pe"),
        [b'P', b'K', 0x03, 0x04, ..] | [b'P', b'K', 0x05, 0x06, ..] => {
            FileType::binary(Archive, "zip")
        }
        [0x1f, 0x8b, ..] => FileType::binary(Archive, "gzip"),
        [b'B', b'Z', b'h', ..] => FileType::binary(Archive, "bzip2"),
        [0xfd, b'7', b'z', b'X', b'Z', 0x00, ..] => FileType::binary(Archive, "xz"),
        [0x28, 0xb5, 0x2f, 0xfd, ..] => FileType::binary(Archive, "zstd"),
        _ if head.get(257..262) == Some(b"ustar") => FileType::binary(Archive, "tar"),
        _ => return None,
    };
    Some(found)
}

fn text_encoding(head: &[u8]) -> Option<&'static str> {
    match head {
        [0xef, 0xbb, 0xbf, rest @ ..] => valid_utf8_prefix(rest).then_some("utf-8-sig"),
        [0xff, 0xfe, ..] => Some("utf-16le"),
        [0xfe, 0xff, ..] => Some("utf-16be"),
        _ if head.contains(&0) => None,
        _ => valid_utf8_prefix(head).then_some("utf-8"),
    }
}

/// UTF-8, allowing a multi-byte character cut off by the end of the sample.
fn valid_utf8_prefix(bytes: &[u8]) -> bool {
    match std::str::from_utf8(bytes) {
        Ok(_) => true,
        Err(e) => e.error_len().is_none() && bytes.len() - e.valid_up_to() < 4,
    }
}

fn python_shebang(head: &[u8]) -> bool {
    let first_line = head.split(|&b| b == b'\n').next().unwrap_or_default();
    first_line.starts_with(b"#!") && first_line.windows(6).any(|w| w == b"python")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tar_head() -> Vec<u8> {
        let mut head = vec![0u8; 512];
        head[257..262].copy_from_slice(b"ustar");
        head
    }

    #[test]
    fn compiled_binaries() {
        let cases: [(&[u8], &str); 6] = [
            (b"\x7fELF\x02\x01\x01", "elf"),
            (b"\xcf\xfa\xed\xfe\x07\x00", "macho"),
            (b"\xfe\xed\xfa\xce", "macho"),
            (b"\xca\xfe\xba\xbe\x00\x00\x00\x02", "macho"),
            (b"MZ\x90\x00", "pe"),
            (b"\xce\xfa\xed\xfe", "macho"),
        ];
        for (head, format) in cases {
            let t = classify("lib/_speedups.so", head);
            assert_eq!(
                (t.category, t.format, t.encoding),
                (Category::Compiled, format, None)
            );
        }
    }

    #[test]
    fn java_class_is_not_macho() {
        let t = classify("Main.class", b"\xca\xfe\xba\xbe\x00\x00\x00\x34\x00");
        assert_eq!(t.category, Category::Other);
    }

    #[test]
    fn archives() {
        let tar = tar_head();
        let cases: [(&[u8], &str); 7] = [
            (b"PK\x03\x04", "zip"),
            (b"PK\x05\x06", "zip"),
            (b"\x1f\x8b\x08", "gzip"),
            (b"BZh91AY", "bzip2"),
            (b"\xfd7zXZ\x00\x00", "xz"),
            (b"\x28\xb5\x2f\xfd", "zstd"),
            (&tar, "tar"),
        ];
        for (head, format) in cases {
            let t = classify("vendor/blob", head);
            assert_eq!((t.category, t.format), (Category::Archive, format));
        }
    }

    #[test]
    fn python_by_extension_or_shebang() {
        let by_ext = classify("orbit/__init__.py", b"import os\n");
        assert_eq!(
            (by_ext.category, by_ext.encoding),
            (Category::Python, Some("utf-8"))
        );
        assert_eq!(
            classify("ORBIT/TYPES.PYI", b"x: int\n").category,
            Category::Python
        );
        assert_eq!(
            classify("bin/orbit", b"#!/usr/bin/env python3\nimport sys\n").category,
            Category::Python
        );
        assert_eq!(
            classify("bin/run", b"#!/bin/sh\necho python\n").category,
            Category::Text
        );
    }

    #[test]
    fn text_encodings() {
        assert_eq!(classify("README", b"hello\n").encoding, Some("utf-8"));
        assert_eq!(
            classify("README", b"\xef\xbb\xbfhello").encoding,
            Some("utf-8-sig")
        );
        assert_eq!(
            classify("README", b"\xff\xfeh\x00i\x00").encoding,
            Some("utf-16le")
        );
        assert_eq!(
            classify("README", b"\xfe\xff\x00h\x00i").encoding,
            Some("utf-16be")
        );
        assert_eq!(classify("empty.txt", b"").category, Category::Text);
    }

    #[test]
    fn utf8_cut_at_sample_end_is_still_text() {
        let mut head = "caf\u{e9} ".repeat(10).into_bytes();
        head.extend_from_slice(&"\u{20ac}".as_bytes()[..2]);
        assert_eq!(classify("notes.md", &head).encoding, Some("utf-8"));
    }

    #[test]
    fn binary_data_is_other() {
        assert_eq!(
            classify("data.bin", b"\x00\x01\x02\x03"),
            FileType::binary(Category::Other, "binary")
        );
        assert_eq!(
            classify("latin1.txt", b"caf\xe9 au lait").category,
            Category::Other
        );
        assert_eq!(
            classify("bad.txt", b"\xef\xbb\xbf\xc3\x28").category,
            Category::Other
        );
    }

    #[test]
    fn category_names() {
        let names: Vec<_> = [
            Category::Python,
            Category::Text,
            Category::Compiled,
            Category::Archive,
            Category::Other,
        ]
        .iter()
        .map(|c| c.as_str())
        .collect();
        assert_eq!(names, ["python", "text", "compiled", "archive", "other"]);
    }
}
