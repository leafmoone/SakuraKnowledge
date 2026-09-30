//! Unicode 16 normalization and full default casefold, matching the frozen
//! Python reference. Newer UCD assignments must not change search-text v2.
use unicode_normalization::UnicodeNormalization;

mod data {
    include!("unicode16_data.rs");
}
pub const VERSION: &str = data::VERSION;

fn in_ranges(c: char, ranges: &[(u32, u32)]) -> bool {
    let cp = c as u32;
    let idx = ranges.partition_point(|&(start, _)| start <= cp);
    idx > 0 && cp <= ranges[idx - 1].1
}

pub fn is_alnum(c: char) -> bool {
    in_ranges(c, data::ALNUM)
}

pub fn normalize_fold(text: &str) -> String {
    // Unicode normalization stability applies to previously assigned scalars.
    // UCD16 unassigned scalars have CCC=0 and no mapping: preserve them as
    // boundaries, preventing a newer normalization table assigning semantics.
    let mut normalized = String::new();
    let mut segment = String::new();
    for c in text.chars() {
        if in_ranges(c, data::ASSIGNED) {
            segment.push(c);
        } else {
            normalized.extend(segment.nfkc());
            segment.clear();
            normalized.push(c);
        }
    }
    normalized.extend(segment.nfkc());
    let mut folded = String::new();
    for c in normalized.chars() {
        if let Ok(idx) = data::FOLD.binary_search_by_key(&(c as u32), |&(cp, _)| cp) {
            folded.push_str(data::FOLD[idx].1);
        } else {
            folded.push(c);
        }
    }
    folded
}
