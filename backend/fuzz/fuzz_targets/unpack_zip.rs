#![no_main]

use libfuzzer_sys::fuzz_target;
use sightglass_core::unpack::Format;

fuzz_target!(|data: &[u8]| sightglass_fuzz::check(data, Format::Zip));
