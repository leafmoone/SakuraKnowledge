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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{self, BufReader, Cursor, Read};

    struct MockEngine {
        timings: Value,
        installed: Option<Vec<String>>,
        encodings: usize,
        calls: Vec<String>,
        failure: Option<Box<dyn Error>>,
        delay: Duration,
    }

    impl MockEngine {
        fn new(modular: bool) -> Self {
            Self {
                timings: json!({"model_sessions":1}),
                installed: modular.then(|| vec!["one".into(), "two".into()]),
                encodings: 0,
                calls: Vec::new(),
                failure: None,
                delay: Duration::ZERO,
            }
        }
    }

    impl ResidentEngine for MockEngine {
        fn open_timings_ms(&self) -> &Value { &self.timings }
        fn installed_sources(&self) -> Option<Vec<String>> { self.installed.clone() }
        fn query_encodings(&self) -> usize { self.encodings }
        fn retrieve_request(&mut self, request: &Request<'_>) -> Result<Value> {
            if !self.delay.is_zero() { std::thread::sleep(self.delay); }
            self.calls.push(request.query.to_owned());
            self.encodings += 1;
            if let Some(error) = self.failure.take() {
                return Err(error);
            }
            let mut response = json!({"status":"PASS","timings_ms":{
                "total":1,"query_encodings":1,"process_query_encodings":self.encodings}});
            if request.query == "oversize" {
                response["text"] = json!("日".repeat(MAX_RESPONSE_BYTES));
            }
            Ok(response)
        }
    }

    fn lines(bytes: &[u8]) -> Vec<Value> {
        assert!(bytes.is_empty() || bytes.ends_with(b"\n"));
        bytes.split_inclusive(|byte| *byte == b'\n').map(|line| {
            assert!(line.len() <= MAX_RESPONSE_BYTES);
            serde_json::from_slice(line).unwrap()
        }).collect()
    }

    fn input(requests: &[Value]) -> String {
        requests.iter().map(|request| format!("{request}\n")).collect()
    }

    fn valid() -> Value { json!({"case_id":"id","query":"q"}) }

    #[test]
    fn expired_engine_pass_is_fatal_and_never_reaches_the_wire() {
        use crate::request_deadline::DeadlineExceeded;
        for modular in [false, true] {
            let mut engine = MockEngine::new(modular);
            engine.delay = Duration::from_millis(40);
            let mut output = Vec::new();
            let error = run_resident_with_budget(
                &mut engine, Cursor::new(input(&[valid(), valid()])),
                &mut output, Duration::from_millis(20), None,
            ).unwrap_err();
            assert!(error.downcast_ref::<DeadlineExceeded>().is_some());
            assert!(matches!(classify_error(error.as_ref()), ErrorClass::Fatal));
            assert_eq!(lines(&output).len(), 1);
            assert_eq!(lines(&output)[0]["event"], "opened");
            assert_eq!(engine.calls.len(), 1);
            assert_eq!(engine.encodings, 1);
        }
    }

    #[test]
    fn q1_pass_q2_fail_q3_pass_same_engine_both_modes_eof_success() {
        for modular in [false, true] {
            let mut engine = MockEngine::new(modular);
            let input = input(&[
                json!({"case_id":"q1","query":"blue hair","limit":5}),
                json!({"case_id":"q2","query":"blue hair","limit":"bad"}),
                json!({"case_id":"q3","query":"Hatsune Miku","limit":5}),
            ]);
            let mut output = Vec::new();
            run_resident(&mut engine, Cursor::new(input), &mut output).unwrap();
            let records = lines(&output);
            assert_eq!(records.len(), 4);
            assert_eq!(records[0]["event"], "opened");
            assert_eq!(records[0]["open_timings_ms"]["model_sessions"], 1);
            assert_eq!(records[1]["status"], "PASS");
            assert_eq!(records[2]["status"], "FAIL");
            assert_eq!(records[2]["case_id"], "q2");
            assert_eq!(records[2]["error"], "invalid_limit");
            assert_eq!(records[2]["message"], "limit must be integer");
            assert_eq!(records[2]["retries"], 0);
            assert_eq!(records[2]["timings_ms"]["process_query_encodings"], 1);
            assert_eq!(records[3]["case_id"], "q3");
            assert_eq!(records[3]["status"], "PASS");
            assert_eq!(records[3]["timings_ms"]["query_encodings"], 1);
            assert_eq!(records[3]["timings_ms"]["process_query_encodings"], 2);
            assert_eq!(engine.calls, ["blue hair", "Hatsune Miku"]);
        }
    }

    #[test]
    fn protocol_failures_use_null_ids_and_continue_without_regex_extraction() {
        let input = concat!(
            "{\"case_id\":\"not-json\",\"query\":\n",
            "[]\n{}\n{\"case_id\":7,\"query\":\"q\"}\n",
            "{\"case_id\":\"\",\"query\":\"q\"}\n",
            "{\"case_id\":\"valid-id\",\"query\":false}\n",
            "{\"case_id\":\" 結尾-验证😀 \",\"query\":\"初音ミク\"}"
        );
        let mut engine = MockEngine::new(false);
        let mut output = Vec::new();
        run_resident(&mut engine, Cursor::new(input), &mut output).unwrap();
        let records = lines(&output);
        assert_eq!(records.len(), 8);
        for record in &records[1..6] {
            assert_eq!(record["case_id"], Value::Null);
            assert_eq!(record["status"], "FAIL");
            assert_eq!(record["retries"], 0);
            assert!(record["message"].is_string());
        }
        assert_eq!(records[6]["case_id"], "valid-id");
        assert_eq!(records[7]["case_id"], " 結尾-验证😀 ");
        assert_eq!(engine.encodings, 1);
    }

    #[test]
    fn every_validation_failure_is_typed_and_precedes_engine_entry() {
        let mut requests = vec![json!({"case_id":"missing-query"})];
        for (field, values) in [
            ("query", vec![Value::Null, json!(1), json!(""), json!("日".repeat(4097)), json!("a ".repeat(257))]),
            ("limit", vec![Value::Null, json!(true), json!(-1), json!(1.5), json!("1"), json!(0), json!(101), json!(u64::MAX)]),
            ("kind", vec![json!(1), json!(""), json!("unknown")]),
            ("namespace", vec![json!(false), json!(""), json!(" "), json!("日".repeat(1025))]),
            ("source", vec![Value::Null, json!(true), json!([]), json!(["one", ""]), json!([1]), json!(""), json!("one,"), json!(".."), json!("../one"), json!("missing")]),
            ("include_vector", vec![Value::Null, json!(1)]),
            ("limti", vec![json!(5)]),
        ] {
            for value in values {
                let mut request = valid();
                request[field] = value;
                requests.push(request);
            }
        }
        for modular in [false, true] {
            let mut engine = MockEngine::new(modular);
            let mut output = Vec::new();
            run_resident(&mut engine, Cursor::new(input(&requests)), &mut output).unwrap();
            let records = lines(&output);
            assert_eq!(records.len(), requests.len() + 1);
            assert!(records[1..].iter().all(|record| record["status"] == "FAIL"));
            assert_eq!(engine.encodings, 0);
            assert!(engine.calls.is_empty());
        }
    }

    #[test]
    fn valid_boundaries_and_source_pack_missing_are_parser_owned() {
        let installed = vec!["one".into(), "two".into()];
        let request = json!({"case_id":" ","query":"😀".repeat(4096),"limit":100,
            "kind":"character","namespace":" future:custom/namespace ",
            "source":["one,two","one"],"include_vector":true});
        let parsed = parse_request(&request, Some(&installed)).unwrap();
        assert_eq!(parsed.case_id, " ");
        assert_eq!(parsed.sources, ["one", "two"]);
        assert_eq!(parsed.options.namespace.as_deref(), Some(" future:custom/namespace "));
        assert!(parsed.options.include_vector);
        for limit in [1, 100] {
            let mut request = valid();
            request["limit"] = json!(limit);
            request["kind"] = Value::Null;
            request["namespace"] = Value::Null;
            assert!(parse_request(&request, None).is_ok());
        }
        let mut request = valid();
        request["source"] = json!("missing");
        assert_eq!(parse_request(&request, Some(&installed)).unwrap_err().code, "source_pack_missing");
        assert_eq!(parse_request(&request, None).unwrap_err().code, "unsupported_option");
        request["case_id"] = json!("\n".repeat(MAX_RESPONSE_BYTES));
        assert!(request_case_id(&request).is_none());
        assert_eq!(parse_request(&request, None).unwrap_err().code, "invalid_case_id");
    }

    #[test]
    fn case_id_wire_bound_counts_actual_json_escape_width() {
        let limit=MAX_RESPONSE_BYTES-1024;
        for character in ['x','日','"','\\','\n','\t','\u{0008}','\u{000c}','\u{0000}'] {
            let width=serde_json::to_vec(&character.to_string()).unwrap().len()-2;
            let id=character.to_string().repeat((limit-2)/width);
            let request=json!({"case_id":id});
            assert!(serde_json::to_vec(&request["case_id"]).unwrap().len()<=limit);
            assert_eq!(request_case_id(&request),request["case_id"].as_str());
            let request=json!({"case_id":format!("{}{}",id,character)});
            assert!(serde_json::to_vec(&request["case_id"]).unwrap().len()>limit);
            assert!(request_case_id(&request).is_none());
        }
    }

    #[test]
    fn oversize_failure_is_complete_and_next_request_is_not_reencoded_or_retried() {
        let mut engine = MockEngine::new(false);
        let mut output = Vec::new();
        let requests = [json!({"case_id":"large","query":"oversize"}), valid()];
        run_resident(&mut engine, Cursor::new(input(&requests)), &mut output).unwrap();
        let records = lines(&output);
        assert_eq!(records.len(), 3);
        assert_eq!(records[1]["case_id"], "large");
        assert_eq!(records[1]["error"], "response_too_large");
        assert_eq!(records[1]["retries"], 0);
        assert!(records[1]["message"].is_string());
        assert_eq!(records[1]["timings_ms"]["process_query_encodings"], 1);
        assert_eq!(records[2]["status"], "PASS");
        assert_eq!(engine.encodings, 2);
    }

    #[test]
    fn only_actual_request_errors_are_recoverable_not_error_messages_or_sources() {
        #[derive(Debug)]
        struct Wrapped(RequestError);
        impl std::fmt::Display for Wrapped {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "{}", self.0)
            }
        }
        impl Error for Wrapped {
            fn source(&self) -> Option<&(dyn Error + 'static)> { Some(&self.0) }
        }
        let safe = RequestError::new("invalid_query", "known safe pre-engine validation");
        assert!(matches!(classify_error(&safe), ErrorClass::Recoverable(_)));
        let errors: Vec<Box<dyn Error>> = vec![
            Box::new(crate::Error::Invalid("invalid_limit".into())),
            Box::new(crate::Error::Budget),
            Box::new(rusqlite::Error::InvalidQuery),
            Box::new(io::Error::other("ORT invalid_query")),
            "USearch source_pack_missing".into(),
            "query_budget_exceeded".into(),
            Box::new(Wrapped(safe)),
        ];
        for error in errors {
            assert!(matches!(classify_error(error.as_ref()), ErrorClass::Fatal));
            let mut engine = MockEngine::new(false);
            engine.failure = Some(error);
            let mut output = Vec::new();
            assert!(run_resident(&mut engine, Cursor::new(input(&[valid(), valid()])), &mut output).is_err());
            let records = lines(&output);
            assert_eq!(records.len(), 2);
            assert_eq!(records[1]["status"], "FAIL");
            assert_eq!(records[1]["error"], "runtime_error");
            assert_eq!(engine.calls.len(), 1);
        }
    }

    #[test]
    fn typed_engine_request_error_can_continue_but_empty_eof_is_success() {
        let mut engine = MockEngine::new(false);
        engine.failure = Some(Box::new(RequestError::new("invalid_query", "explicitly safe")));
        let mut output = Vec::new();
        run_resident(&mut engine, Cursor::new(input(&[valid(), valid()])), &mut output).unwrap();
        assert_eq!(lines(&output)[2]["status"], "PASS");
        let mut engine = MockEngine::new(false);
        output.clear();
        run_resident(&mut engine, Cursor::new(""), &mut output).unwrap();
        assert_eq!(lines(&output).len(), 1);
        assert!(engine.calls.is_empty());
    }

    #[test]
    fn stdin_io_failure_is_fatal_not_a_request_error() {
        struct BrokenInput;
        impl Read for BrokenInput {
            fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
                Err(io::Error::other("injected stdin failure"))
            }
        }
        let mut engine = MockEngine::new(false);
        let mut output = Vec::new();
        let error = run_resident(&mut engine, BufReader::new(BrokenInput), &mut output).unwrap_err();
        assert!(error.downcast_ref::<io::Error>().is_some());
        assert_eq!(lines(&output).len(), 1);
        assert!(engine.calls.is_empty());
    }

    struct BrokenOutput {
        bytes: Vec<u8>,
        writes: usize,
        flushes: usize,
        fail_write: Option<usize>,
        fail_flush: Option<usize>,
    }

    impl Write for BrokenOutput {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            self.writes += 1;
            if self.fail_write == Some(self.writes) {
                return Err(io::Error::new(io::ErrorKind::BrokenPipe, "injected write failure"));
            }
            self.bytes.extend_from_slice(bytes);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            self.flushes += 1;
            if self.fail_flush == Some(self.flushes) {
                return Err(io::Error::new(io::ErrorKind::BrokenPipe, "injected flush failure"));
            }
            Ok(())
        }
    }

    #[test]
    fn stdout_write_or_flush_failure_wins_over_engine_failure_and_stops() {
        for fatal_engine in [false, true] {
            for (fail_write, fail_flush) in [(Some(1), None), (None, Some(1)), (Some(2), None), (None, Some(2))] {
                let mut engine = MockEngine::new(false);
                if fatal_engine {
                    engine.failure = Some("injected corrupt engine".into());
                }
                let mut output = BrokenOutput { bytes: Vec::new(), writes: 0, flushes: 0, fail_write, fail_flush };
                let error = run_resident(&mut engine, Cursor::new(input(&[valid(), valid()])), &mut output).unwrap_err();
                assert_eq!(error.downcast_ref::<io::Error>().unwrap().kind(), io::ErrorKind::BrokenPipe);
                assert_eq!(engine.calls.len(), usize::from(fail_write != Some(1) && fail_flush != Some(1)));
                if fail_write == Some(2) {
                    assert_eq!(lines(&output.bytes).len(), 1);
                }
            }
        }
    }
}
