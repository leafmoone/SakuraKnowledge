//! Shared resident lifecycle: only explicitly typed request errors allow continuation.
use crate::semantic::{Result, RetrieveOptions};
use crate::semantic_jsonl::{send_response_before, MAX_RESPONSE_BYTES};
use crate::request_deadline::{DeadlineWatchdog, RequestDeadline, REQUEST_BUDGET};
use serde_json::{json, Value};
use std::error::Error;
use std::io::{BufRead, Write};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct RequestError {
    pub code: &'static str,
    pub message: String,
}

impl RequestError {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Self { code, message: message.into() }
    }

    pub fn response(&self, case_id: Option<&str>, process_query_encodings: usize) -> Value {
        json!({"case_id":case_id,"status":"FAIL","error":self.code,
            "message":self.message,"retries":0,
            "timings_ms":{"process_query_encodings":process_query_encodings}})
    }
}

impl std::fmt::Display for RequestError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl Error for RequestError {}

#[derive(Debug)]
pub enum ErrorClass<'a> {
    Recoverable(&'a RequestError),
    Fatal,
}

/// Do not infer state safety from an internal error's text or its source chain.
pub fn classify_error<'a>(error: &'a (dyn Error + 'static)) -> ErrorClass<'a> {
    match error.downcast_ref::<RequestError>() {
        Some(request) => ErrorClass::Recoverable(request),
        None => ErrorClass::Fatal,
    }
}

#[derive(Debug)]
pub struct Request<'a> {
    pub query: &'a str,
    pub case_id: &'a str,
    pub options: RetrieveOptions,
    pub sources: Vec<String>,
}

/// Reserve room for a complete failure envelope, even for heavily escaped IDs.
/// Unrepresentable IDs are invalid protocol input; valid IDs are never trimmed.
pub fn request_case_id(value: &Value) -> Option<&str> {
    let id = value.as_object()?.get("case_id")?.as_str()?;
    if id.is_empty() {
        return None;
    }
    let mut bytes = 2usize;
    for character in id.chars() {
        bytes = bytes.checked_add(match character {
            '"' | '\\' | '\u{0008}' | '\u{000c}' | '\n' | '\r' | '\t' => 2,
            '\u{0000}'..='\u{001f}' => 6,
            _ => character.len_utf8(),
        })?;
        if bytes > MAX_RESPONSE_BYTES - 1024 {
            return None;
        }
    }
    Some(id)
}

pub fn parse_request<'a>(
    value: &'a Value,
    installed_sources: Option<&[String]>,
) -> std::result::Result<Request<'a>, RequestError> {
    let object = value.as_object().ok_or_else(|| {
        RequestError::new("invalid_request", "request must be an object")
    })?;
    let case_id = request_case_id(value).ok_or_else(|| {
        RequestError::new("invalid_case_id", "case_id must be nonempty text fitting the response wire limit")
    })?;
    for field in object.keys() {
        if !matches!(field.as_str(), "query" | "case_id" | "limit" | "kind" | "namespace" | "include_vector" | "source") {
            return Err(RequestError::new("unsupported_option", "unsupported request option"));
        }
    }
    let query = object.get("query").and_then(Value::as_str).ok_or_else(|| {
        RequestError::new("invalid_query", "query must be text")
    })?;
    if query.is_empty() || query.chars().count() > 4096 {
        return Err(RequestError::new("invalid_query", "query must contain 1..4096 characters"));
    }
    // This pure validator is safe before engine entry. Internal Error::Invalid
    // from SQLite, retrieval or asset validation is NOT classified this way.
    crate::tokens(query).map_err(|error| RequestError::new("invalid_query", error.to_string()))?;
    let mut options = RetrieveOptions::default();
    if let Some(limit) = object.get("limit") {
        let number = limit.as_u64().ok_or_else(|| {
            RequestError::new("invalid_limit", "limit must be integer")
        })?;
        if !(1..=100).contains(&number) {
            return Err(RequestError::new("invalid_limit", "limit must be 1..100"));
        }
        options.limit = number as usize;
    }
    for (field, target) in [("kind", &mut options.kind), ("namespace", &mut options.namespace)] {
        if let Some(value) = object.get(field).filter(|value| !value.is_null()) {
            let text = value.as_str().ok_or_else(|| {
                RequestError::new("invalid_filter", "filter must be text")
            })?;
            if field == "kind" && !matches!(text, "subject" | "character" | "person" | "episode" | "page" | "tag") {
                return Err(RequestError::new("invalid_kind", "invalid EntryKey kind"));
            }
            if field == "namespace" && (text.trim().is_empty() || text.chars().count() > 1024) {
                return Err(RequestError::new("invalid_namespace", "invalid namespace"));
            }
            *target = Some(text.to_owned());
        }
    }
    if let Some(value) = object.get("include_vector") {
        options.include_vector = value.as_bool().ok_or_else(|| {
            RequestError::new("invalid_option", "include_vector must be boolean")
        })?;
    }
    let mut sources = Vec::new();
    if let Some(value) = object.get("source") {
        let values: Vec<&str> = match value {
            Value::String(text) => vec![text.as_str()],
            Value::Array(items) if !items.is_empty() => items.iter().map(|item| {
                item.as_str().ok_or_else(|| RequestError::new("invalid_source", "source members must be text"))
            }).collect::<std::result::Result<_, _>>()?,
            _ => return Err(RequestError::new("invalid_source", "source must be text or a nonempty list")),
        };
        for value in values {
            for source in value.split(',') {
                if source.is_empty() || source.len() > 128 || matches!(source, "." | "..")
                    || !source.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"-_.".contains(&byte))
                {
                    return Err(RequestError::new("invalid_source", "invalid source pack ID"));
                }
                if !sources.iter().any(|existing| existing == source) {
                    sources.push(source.to_owned());
                }
            }
        }
        let installed = installed_sources.ok_or_else(|| {
            RequestError::new("unsupported_option", "source selection requires --config")
        })?;
        for source in &sources {
            if !installed.contains(source) {
                return Err(RequestError::new("source_pack_missing", format!("source pack not installed: {source}")));
            }
        }
    }
    Ok(Request { query, case_id, options, sources })
}

pub trait ResidentEngine {
    fn open_timings_ms(&self) -> &Value;
    fn installed_sources(&self) -> Option<Vec<String>>;
    fn query_encodings(&self) -> usize;
    fn retrieve_request(&mut self, request: &Request<'_>) -> Result<Value>;
}

impl ResidentEngine for crate::semantic::SemanticEngine {
    fn open_timings_ms(&self) -> &Value { &self.open_timings_ms }
    fn installed_sources(&self) -> Option<Vec<String>> { None }
    fn query_encodings(&self) -> usize { self.query_encodings() }
    fn retrieve_request(&mut self, request: &Request<'_>) -> Result<Value> {
        self.retrieve(request.query, &request.options)
    }
}

impl ResidentEngine for crate::modular::ModularSemantic {
    fn open_timings_ms(&self) -> &Value { &self.open_timings_ms }
    fn installed_sources(&self) -> Option<Vec<String>> {
        Some(self.runtime.packs.iter().map(|pack| pack.id.clone()).collect())
    }
    fn query_encodings(&self) -> usize { self.query_encodings() }
    fn retrieve_request(&mut self, request: &Request<'_>) -> Result<Value> {
        self.retrieve(request.query, &request.options, &request.sources)
    }
}

/// Generic embedding/test loop: absolute checks, without killing its host.
/// An arbitrary blocking Write needs the native watchdog for a hard stop.
pub fn run_resident(
    engine: &mut (impl ResidentEngine + ?Sized),
    input: impl BufRead,
    output: &mut impl Write,
) -> Result<()> {
    run_resident_with_budget(engine, input, output, REQUEST_BUDGET, None)
}

/// Native process boundary: one watchdog, shared by every completed input line.
pub fn run_native_resident(
    engine: &mut (impl ResidentEngine + ?Sized),
    input: impl BufRead,
    output: &mut impl Write,
) -> Result<()> {
    let watchdog = DeadlineWatchdog::start()?;
    run_resident_with_budget(engine, input, output, REQUEST_BUDGET, Some(&watchdog))
}

fn run_resident_with_budget(
    engine: &mut (impl ResidentEngine + ?Sized),
    input: impl BufRead,
    output: &mut impl Write,
    budget: Duration,
    watchdog: Option<&DeadlineWatchdog>,
) -> Result<()> {
    let installed = engine.installed_sources();
    let mut opened = serde_json::to_vec(&json!({"event":"opened",
        "open_timings_ms":engine.open_timings_ms(),"retries":0}))?;
    if opened.len() >= MAX_RESPONSE_BYTES {
        return Err("opened event exceeds response wire limit".into());
    }
    opened.push(b'\n');
    output.write_all(&opened)?;
    output.flush()?;
    for line in input.lines() {
        let line = line?;
        // Input waiting and cold opening are excluded. Everything after this
        // completed line, including decode/validation and output, shares one end.
        let deadline = RequestDeadline::from_start(Instant::now(), budget);
        let guard = match watchdog {
            Some(watchdog) => watchdog.arm(deadline)?,
            None => deadline.guard(),
        };
        let decoded = serde_json::from_str::<Value>(&line);
        deadline.check()?;
        let case_id = decoded.as_ref().ok().and_then(request_case_id);
        let result: Result<Value> = (|| {
            let value = decoded.as_ref().map_err(|error| {
                RequestError::new("invalid_json", error.to_string())
            })?;
            let parsed = parse_request(value, installed.as_deref());
            deadline.check()?;
            let request = parsed?;
            let retrieved = engine.retrieve_request(&request);
            deadline.check()?;
            let mut response = retrieved?;
            if !response.is_object() {
                return Err("engine response must be an object".into());
            }
            response["case_id"] = json!(request.case_id);
            Ok(response)
        })();
        deadline.check()?;
        let elapsed_ms = deadline.elapsed().as_secs_f64() * 1000.0;
        match result {
            Ok(response) => {
                send_response_before(output, &response, case_id, elapsed_ms, deadline)?;
                guard.finish()?;
            }
            Err(error) => {
                let (response, fatal) = match classify_error(error.as_ref()) {
                    ErrorClass::Recoverable(request) => (
                        request.response(case_id, engine.query_encodings()), false,
                    ),
                    ErrorClass::Fatal => (
                        RequestError::new("runtime_error", error.to_string())
                            .response(case_id, engine.query_encodings()), true,
                    ),
                };
                // A transmission failure takes precedence: no delivered FAIL is claimed.
                send_response_before(output, &response, case_id, elapsed_ms, deadline)?;
                guard.finish()?;
                if fatal {
                    return Err(error);
                }
            }
        }
    }
    Ok(())
}
