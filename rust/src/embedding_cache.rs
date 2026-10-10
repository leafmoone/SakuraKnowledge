//! Session-owned exact-query LRU. Only validated vectors enter this cache.
use std::collections::VecDeque;
const MAX_ENTRIES: usize = 64;
const MAX_BYTES: usize = 512 * 1024;
struct Entry { query: Box<str>, vector: Box<[f32]>, tokens: usize }
pub(super) struct EmbeddingCache { entries: VecDeque<Entry>, bytes: usize }
impl EmbeddingCache {
    pub(super) fn new() -> Self {
        let entries = VecDeque::with_capacity(MAX_ENTRIES);
        let bytes = entries.capacity() * std::mem::size_of::<Entry>() + std::mem::size_of::<Self>();
        Self { entries, bytes }
    }
    pub(super) fn get(&mut self, query: &str) -> Option<(Vec<f32>,usize)> {
        let position = self.entries.iter().position(|entry| entry.query.as_ref() == query)?;
        let entry = self.entries.remove(position)?;
        let result = (entry.vector.to_vec(), entry.tokens);
        self.entries.push_back(entry);
        Some(result)
    }
    pub(super) fn insert(&mut self, query: &str, vector: &[f32], tokens: usize) {
        let size = query.len() + std::mem::size_of_val(vector);
        let fixed = self.entries.capacity() * std::mem::size_of::<Entry>() + std::mem::size_of::<Self>();
        if size > MAX_BYTES - fixed { return; }
        if let Some(position) = self.entries.iter().position(|entry| entry.query.as_ref() == query) {
            let old = self.entries.remove(position).unwrap();
            self.bytes -= old.query.len() + std::mem::size_of_val(old.vector.as_ref());
        }
        while self.entries.len() >= MAX_ENTRIES || self.bytes + size > MAX_BYTES {
            let old = self.entries.pop_front().unwrap();
            self.bytes -= old.query.len() + std::mem::size_of_val(old.vector.as_ref());
        }
        self.entries.push_back(Entry { query: query.into(), vector: vector.into(), tokens });
        self.bytes += size;
    }
}
