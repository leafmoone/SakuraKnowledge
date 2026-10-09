//! Shared single-query and resident semantic wire budget (UTF-8 plus newline).
use crate::semantic::Result;
use crate::request_deadline::RequestDeadline;
use serde_json::{json, Value};
use std::io::Write;
use std::time::Instant;
// Exact frozen Moegirl templates can exceed the historical 1 MiB budget.
// Keep complete success content and a bounded, explicit failure above 2 MiB.
pub const MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
#[derive(Default)]
struct BoundedJson { bytes: Vec<u8>, total: usize, deadline: Option<RequestDeadline> }
impl Write for BoundedJson {
    fn write(&mut self, data: &[u8]) -> std::io::Result<usize> {
        check_io(self.deadline)?;
        self.total = self.total.checked_add(data.len()).ok_or(std::io::ErrorKind::InvalidData)?;
        let room = (MAX_RESPONSE_BYTES - 1).saturating_sub(self.bytes.len());
        self.bytes.extend_from_slice(&data[..room.min(data.len())]);
        Ok(data.len())
    }
    fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
}
fn check_deadline(deadline: Option<RequestDeadline>) -> Result<()> {
    if let Some(deadline) = deadline { deadline.check()?; }
    Ok(())
}
fn check_io(deadline: Option<RequestDeadline>) -> std::io::Result<()> {
    if let Some(deadline) = deadline {
        deadline.check().map_err(|error| std::io::Error::new(std::io::ErrorKind::TimedOut, error))?;
    }
    Ok(())
}
struct DeadlineWriter<'a, W: Write> { output: &'a mut W, deadline: RequestDeadline }
impl<W: Write> Write for DeadlineWriter<'_, W> {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        check_io(Some(self.deadline))?;
        let result = self.output.write(bytes);
        check_io(Some(self.deadline))?;
        result
    }
    fn flush(&mut self) -> std::io::Result<()> {
        check_io(Some(self.deadline))?;
        let result = self.output.flush();
        check_io(Some(self.deadline))?;
        result
    }
}
/// Returns whether the complete original response exceeded the budget.
pub fn send_response(output: &mut impl Write, value: &Value, case_id: &str, retrieval_ms: f64) -> Result<bool> {
    send_response_optional(output, value, Some(case_id), retrieval_ms)
}
/// Resident protocol failures have a null ID rather than an invented empty string.
pub fn send_response_optional(output: &mut impl Write, value: &Value, case_id: Option<&str>, retrieval_ms: f64) -> Result<bool> {
    send_response_impl(output, value, case_id, retrieval_ms, None)
}
/// One absolute deadline covers serialization, each write, flush and profiling.
/// Generic writers are checked on return; native callers must also arm the
/// process watchdog to interrupt a synchronous blocked write/flush. The legacy
/// wrapper does not accidentally include single-query cold asset opening.
pub fn send_response_before(output: &mut impl Write, value: &Value, case_id: Option<&str>, retrieval_ms: f64, deadline: RequestDeadline) -> Result<bool> {
    send_response_impl(output, value, case_id, retrieval_ms, Some(deadline))
}
fn send_response_impl(output: &mut impl Write, value: &Value, case_id: Option<&str>, retrieval_ms: f64, deadline: Option<RequestDeadline>) -> Result<bool> {
    check_deadline(deadline)?;
    let start = Instant::now();
    let mut buffer = BoundedJson { deadline, ..BoundedJson::default() };
    let serialized = serde_json::to_writer(&mut buffer, value);
    // Preserve an explicit fatal deadline type, not serde's wrapped I/O error.
    check_deadline(deadline)?;
    if let Err(error) = serialized {
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
    check_deadline(deadline)?;
    buffer.bytes.push(b'\n');
    let serialize_ms = start.elapsed().as_secs_f64()*1000.0;
    let start = Instant::now();
    check_deadline(deadline)?;
    let transmitted = match deadline {
        Some(deadline) => {
            let mut checked = DeadlineWriter { output, deadline };
            checked.write_all(&buffer.bytes).and_then(|_| checked.flush())
        }
        None => output.write_all(&buffer.bytes).and_then(|_| output.flush()),
    };
    check_deadline(deadline)?;
    if let Err(error) = transmitted {
        eprintln!("{}",json!({"case_id":case_id,"phase":"transmission","error":error.to_string(),"transmit_ms":start.elapsed().as_secs_f64()*1000.0}));
        return Err(error.into());
    }
    eprintln!("{}",json!({"case_id":case_id,"retrieval_ms":retrieval_ms,"serialize_ms":serialize_ms,"transmit_ms":start.elapsed().as_secs_f64()*1000.0,"response_bytes":total_bytes,"sent_bytes":buffer.bytes.len(),"response_too_large":oversized}));
    check_deadline(deadline)?;
    Ok(oversized)
}
