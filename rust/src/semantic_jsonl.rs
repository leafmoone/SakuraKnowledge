//! Shared single-query and resident semantic wire budget (UTF-8 plus newline).
use crate::semantic::Result;
use serde_json::{json, Value};
use std::io::Write;
use std::time::Instant;
pub const MAX_RESPONSE_BYTES: usize = 1048576;
#[derive(Default)]
struct BoundedJson { bytes: Vec<u8>, total: usize }
impl Write for BoundedJson {
    fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
        self.total = self.total.checked_add(data.len()).ok_or(std::io::ErrorKind::InvalidData)?;
        let room = (MAX_RESPONSE_BYTES - 1).saturating_sub(self.bytes.len());
        self.bytes.extend_from_slice(&data[..room.min(data.len())]);
        Ok(data.len())
    }
    fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
}
/// Returns whether the complete original response exceeded the budget.
pub fn send_response(output: &mut impl Write, value: &Value, case_id: &str, retrieval_ms: f64) -> Result<bool> {
    let start = Instant::now();
    let mut buffer = BoundedJson::default();
    if let Err(error) = serde_json::to_writer(&mut buffer, value) {
        eprintln!("{}",json!({"case_id":case_id,"phase":"serialization","error":error.to_string(),"serialize_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    let total_bytes = buffer.total.checked_add(1).ok_or("response byte overflow")?;
    let oversized = total_bytes > MAX_RESPONSE_BYTES;
    if oversized {
        buffer.bytes = serde_json::to_vec(&json!({"case_id":case_id,"status":"FAIL","error":"response_too_large","retries":0,"response_bytes":total_bytes,"limit_bytes":MAX_RESPONSE_BYTES}))?;
        if buffer.bytes.len()+1 > MAX_RESPONSE_BYTES { return Err("failure envelope too large".into()); }
    }
    buffer.bytes.push(b'\n');
    let serialize_ms = start.elapsed().as_secs_f64()*1000.0;
    let start = Instant::now();
    if let Err(error) = output.write_all(&buffer.bytes).and_then(|_|output.flush()) {
        eprintln!("{}",json!({"case_id":case_id,"phase":"transmission","error":error.to_string(),"transmit_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    eprintln!("{}",json!({"case_id":case_id,"retrieval_ms":retrieval_ms,"serialize_ms":serialize_ms,"transmit_ms":start.elapsed().as_secs_f64()*1000.0,"response_bytes":total_bytes,"sent_bytes":buffer.bytes.len(),"response_too_large":oversized}));
    Ok(oversized)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn utf8_newline_boundary_and_oversize_are_complete_envelopes() {
        let mut output=Vec::new();
        let mut value=json!({"case_id":"tiny","status":"PASS","text":"日"});
        let overhead=serde_json::to_vec(&value).unwrap().len()+1;
        value["text"]=json!(format!("日{}","x".repeat(MAX_RESPONSE_BYTES-overhead)));
        assert!(!send_response(&mut output,&value,"tiny",1.0).unwrap());
        assert_eq!(output.len(),MAX_RESPONSE_BYTES);
        assert_eq!(output.last(),Some(&b'\n'));
        output.clear();value["text"]=json!("日".repeat(MAX_RESPONSE_BYTES));
        let total=serde_json::to_vec(&value).unwrap().len()+1;
        assert!(send_response(&mut output,&value,"tiny",1.0).unwrap());
        let failed:Value=serde_json::from_slice(&output).unwrap();
        assert_eq!(failed["error"],"response_too_large");
        assert_eq!(failed["response_bytes"],total);
        assert!(output.len()<MAX_RESPONSE_BYTES);
    }
}
