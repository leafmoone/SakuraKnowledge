//! Shared single-query and resident semantic wire budget (UTF-8 plus newline).
use crate::semantic::Result;
use serde_json::{json, Value};
use std::io::Write;
use std::time::Instant;
// Exact frozen Moegirl templates can exceed the historical 1 MiB budget.
// Keep complete success content and a bounded, explicit failure above 2 MiB.
pub const MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
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
    send_response_optional(output, value, Some(case_id), retrieval_ms)
}
/// Resident protocol failures have a null ID rather than an invented empty string.
pub fn send_response_optional(output: &mut impl Write, value: &Value, case_id: Option<&str>, retrieval_ms: f64) -> Result<bool> {
    let start = Instant::now();
    let mut buffer = BoundedJson::default();
    if let Err(error) = serde_json::to_writer(&mut buffer, value) {
        eprintln!("{}",json!({"case_id":case_id,"phase":"serialization","error":error.to_string(),"serialize_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    let total_bytes = buffer.total.checked_add(1).ok_or("response byte overflow")?;
    let oversized = total_bytes > MAX_RESPONSE_BYTES;
    if oversized {
        let counter = value["timings_ms"]["process_query_encodings"].as_u64()
            .and_then(|number| usize::try_from(number).ok()).unwrap_or(0);
        let mut failure = crate::resident::RequestError::new(
            "response_too_large", "response exceeds the UTF-8 plus newline wire limit",
        ).response(case_id, counter);
        failure["response_bytes"] = json!(total_bytes);
        failure["limit_bytes"] = json!(MAX_RESPONSE_BYTES);
        buffer.bytes = serde_json::to_vec(&failure)?;
        if buffer.bytes.len()+1 > MAX_RESPONSE_BYTES {
            // Defensive for callers outside the resident parser. Never emit a partial ID.
            failure = crate::resident::RequestError::new(
                "invalid_case_id", "case_id exceeds the response wire limit",
            ).response(None, counter);
            buffer.bytes = serde_json::to_vec(&failure)?;
        }
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
        assert!(failed["message"].is_string());
        assert_eq!(failed["retries"],0);
    }
    #[test]
    fn nullable_id_and_oversized_failure_are_complete_bounded_envelopes() {
        let value=json!({"case_id":null,"status":"FAIL","message":"日".repeat(MAX_RESPONSE_BYTES)});
        let mut output=Vec::new();
        assert!(send_response_optional(&mut output,&value,None,0.0).unwrap());
        let failure:Value=serde_json::from_slice(&output).unwrap();
        assert_eq!(failure["case_id"],Value::Null);
        assert_eq!(failure["error"],"response_too_large");
        assert!(failure["message"].is_string());
        assert!(output.len()<=MAX_RESPONSE_BYTES);
        output.clear();
        let id="x".repeat(MAX_RESPONSE_BYTES);
        let value=json!({"case_id":id,"status":"PASS"});
        assert!(send_response(&mut output,&value,&id,0.0).unwrap());
        let failure:Value=serde_json::from_slice(&output).unwrap();
        assert_eq!(failure["case_id"],Value::Null);
        assert_eq!(failure["error"],"invalid_case_id");
        assert_eq!(output.last(),Some(&b'\n'));
        assert!(output.len()<=MAX_RESPONSE_BYTES);
    }
    #[test]
    fn partial_write_failure_is_fatal_and_does_not_attempt_a_second_envelope() {
        struct PartialWriter { bytes:Vec<u8>,writes:usize }
        impl Write for PartialWriter {
            fn write(&mut self,bytes:&[u8])->std::io::Result<usize> {
                self.writes+=1;
                if self.writes>1 {return Err(std::io::ErrorKind::BrokenPipe.into());}
                self.bytes.extend_from_slice(&bytes[..7]);
                Ok(7)
            }
            fn flush(&mut self)->std::io::Result<()> {panic!("flush after failed write");}
        }
        let mut output=PartialWriter{bytes:vec![],writes:0};
        let error=send_response(&mut output,&json!({"status":"PASS"}),"id",0.).unwrap_err();
        assert_eq!(error.downcast_ref::<std::io::Error>().unwrap().kind(),std::io::ErrorKind::BrokenPipe);
        assert_eq!(output.writes,2);assert_eq!(output.bytes.len(),7);
    }
}
