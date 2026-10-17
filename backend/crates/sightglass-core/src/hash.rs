//! Streaming sha256 over any reader, without buffering whole files.

use std::io::{self, ErrorKind, Read};

use sha2::{Digest, Sha256};

const BUFFER_SIZE: usize = 64 * 1024;

/// A file's sha256 and its size in bytes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Hashed {
    /// Lowercase hex digest, 64 characters.
    pub sha256: String,
    /// Number of bytes read.
    pub size: u64,
}

/// Hash everything a reader yields, 64 KiB at a time.
///
/// # Errors
///
/// Returns the reader's error, except `Interrupted`, which is retried.
pub fn sha256_reader<R: Read>(mut reader: R) -> io::Result<Hashed> {
    let mut hasher = Sha256::new();
    let mut buffer = vec![0u8; BUFFER_SIZE];
    let mut size: u64 = 0;
    loop {
        let n = match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        };
        hasher.update(&buffer[..n]);
        size += n as u64;
    }
    Ok(Hashed {
        sha256: to_hex(&hasher.finalize()),
        size,
    })
}

fn to_hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(char::from(DIGITS[usize::from(b >> 4)]));
        out.push(char::from(DIGITS[usize::from(b & 0x0f)]));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Yields at most `chunk` bytes per read, and fails or interrupts on request.
    struct Trickle<'a> {
        data: &'a [u8],
        chunk: usize,
        interrupt_first: bool,
        fail_after: Option<usize>,
        read: usize,
    }

    impl Read for Trickle<'_> {
        fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
            if self.interrupt_first {
                self.interrupt_first = false;
                return Err(io::Error::from(ErrorKind::Interrupted));
            }
            if self.fail_after.is_some_and(|limit| self.read >= limit) {
                return Err(io::Error::other("disk on fire"));
            }
            let n = self.chunk.min(buf.len()).min(self.data.len());
            buf[..n].copy_from_slice(&self.data[..n]);
            self.data = &self.data[n..];
            self.read += n;
            Ok(n)
        }
    }

    #[test]
    fn known_vectors() {
        let empty = sha256_reader(&b""[..]).unwrap();
        assert_eq!(
            empty.sha256,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(empty.size, 0);
        let abc = sha256_reader(&b"abc"[..]).unwrap();
        assert_eq!(
            abc.sha256,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(abc.size, 3);
    }

    #[test]
    fn input_larger_than_buffer_matches_one_shot_digest() {
        let data: Vec<u8> = (0..BUFFER_SIZE * 3 + 17)
            .map(|i| u8::try_from(i % 251).unwrap())
            .collect();
        let streamed = sha256_reader(&data[..]).unwrap();
        assert_eq!(streamed.sha256, to_hex(&Sha256::digest(&data)));
        assert_eq!(streamed.size, data.len() as u64);
    }

    #[test]
    fn short_reads_and_interruptions_are_handled() {
        let data = b"the quick brown fox jumps over the lazy dog".repeat(100);
        let reader = Trickle {
            data: &data,
            chunk: 7,
            interrupt_first: true,
            fail_after: None,
            read: 0,
        };
        assert_eq!(
            sha256_reader(reader).unwrap(),
            sha256_reader(&data[..]).unwrap()
        );
    }

    #[test]
    fn reader_errors_propagate() {
        let reader = Trickle {
            data: b"abcdef",
            chunk: 2,
            interrupt_first: false,
            fail_after: Some(2),
            read: 0,
        };
        let err = sha256_reader(reader).unwrap_err();
        assert_eq!(err.kind(), ErrorKind::Other);
    }
}
