//! Standalone dependency spike; no inference, search, export, or index writes.
//! Usage: semantic-dependency-probe TOKENIZER_JSON MODEL_ONNX USEARCH_INDEX ORT_DLL [REFERENCE_JSON]
//! Reference schema: {"add_special_tokens":true,"cases":[{"text":"...",
//! "input_ids":[1,2],"attention_mask":[1,1]}, ... exactly 120 cases]}.
//! Text is passed verbatim, one encode at a time, using tokenizer.json's padding
//! and truncation configuration. Include any model-specific prefix in `text`.

use std::{error::Error, path::Path};

use ort::{ep, session::Session};
use serde_json::Value;
use tokenizers::Tokenizer;
use usearch::{Index, MetricKind};

type Result<T> = std::result::Result<T, Box<dyn Error>>;

// ort exposes API access but not GetVersionString. Query the already-loaded,
// explicitly selected DLL, without introducing another loader dependency.
#[cfg(windows)]
fn runtime_version(dll: &Path) -> Result<String> {
    use std::{
        ffi::{c_void, CStr},
        os::windows::ffi::OsStrExt,
    };
    #[link(name = "kernel32")]
    extern "system" {
        fn GetModuleHandleW(name: *const u16) -> *mut c_void;
        fn GetProcAddress(module: *mut c_void, name: *const u8) -> *mut c_void;
    }
    let name: Vec<u16> = dll.as_os_str().encode_wide().chain(Some(0)).collect();
    // The module remains owned by ort's global loader for the process lifetime.
    unsafe {
        let module = GetModuleHandleW(name.as_ptr());
        if module.is_null() {
            return Err(std::io::Error::last_os_error().into());
        }
        let symbol = GetProcAddress(module, c"OrtGetApiBase".as_ptr().cast());
        if symbol.is_null() {
            return Err(std::io::Error::last_os_error().into());
        }
        let get_api_base: unsafe extern "system" fn() -> *const ort::sys::OrtApiBase =
            std::mem::transmute(symbol);
        let base = get_api_base()
            .as_ref()
            .ok_or("OrtGetApiBase returned null")?;
        let version = (base.GetVersionString)();
        if version.is_null() {
            return Err("GetVersionString returned null".into());
        }
        Ok(CStr::from_ptr(version).to_str()?.to_owned())
    }
}

#[cfg(not(windows))]
fn runtime_version(_dll: &Path) -> Result<String> {
    Err("This DLL dependency spike requires Windows".into())
}

fn check_runtime_version(version: &str) -> Result<()> {
    let mut parts = version.split('.');
    if parts.next() != Some("1") || parts.next() != Some("24") {
        return Err(format!("Expected ONNX Runtime 1.24.x, got {version}").into());
    }
    Ok(())
}

fn reference_options(reference: &Value) -> Result<(bool, &Vec<Value>)> {
    let special = if reference["schema"] == "p4-rust-tokenizer-reference-v1"
        && reference["status"] == "PASS"
        && reference["embedding_executed"] == false
    {
        true
    } else {
        reference["add_special_tokens"]
            .as_bool()
            .ok_or("Reference requires boolean add_special_tokens")?
    };
    let cases = reference["cases"]
        .as_array()
        .ok_or("Reference requires cases array")?;
    if cases.len() != 120 {
        return Err(format!("Expected 120 reference cases, got {}", cases.len()).into());
    }
    Ok((special, cases))
}

fn check_reference(tokenizer: &Tokenizer, reference: &Value) -> Result<()> {
    let (special, cases) = reference_options(reference)?;
    for (number, case) in cases.iter().enumerate() {
        let text = case["query"]
            .as_str()
            .or_else(|| case["text"].as_str())
            .ok_or_else(|| format!("Case {number}: missing text"))?;
        let encoding = tokenizer
            .encode(text, special)
            .map_err(|err| err.to_string())?;
        for (field, actual) in [
            ("input_ids", encoding.get_ids()),
            ("attention_mask", encoding.get_attention_mask()),
        ] {
            let expected: Vec<u32> = serde_json::from_value(case[field].clone())
                .map_err(|err| format!("Case {number} {field}: {err}"))?;
            if actual != expected {
                let first = actual
                    .iter()
                    .zip(&expected)
                    .position(|(a, b)| a != b)
                    .unwrap_or(actual.len().min(expected.len()));
                return Err(format!(
                    "Case {number} {field} mismatch at {first}: actual length {}, expected length {}",
                    actual.len(), expected.len()
                ).into());
            }
        }
    }
    println!("tokenizer: exact input_ids and attention_mask match for 120 cases");
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if !(4..=5).contains(&args.len()) {
        return Err("Usage: semantic-dependency-probe TOKENIZER_JSON MODEL_ONNX USEARCH_INDEX ORT_DLL [REFERENCE_JSON]".into());
    }
    let tokenizer = Tokenizer::from_file(Path::new(&args[0])).map_err(|err| err.to_string())?;
    if let Some(reference) = args.get(4) {
        check_reference(
            &tokenizer,
            &serde_json::from_slice(&std::fs::read(reference)?)?,
        )?;
    } else {
        println!("tokenizer loaded; reference comparison skipped (no reference supplied)");
    }

    let dll = std::fs::canonicalize(&args[3])?;
    let environment = ort::init_from(&dll)?;
    let version = runtime_version(&dll)?;
    check_runtime_version(&version)?;
    if !environment
        .with_execution_providers([ep::CPU::default().build()])
        .commit()
    {
        return Err("ORT environment was already initialized".into());
    }
    // File-based loading lets ORT resolve external tensor data relative to model.onnx.
    // Only CPU is registered; sequential execution uses eight intra-op threads.
    let _session = Session::builder()?
        .with_execution_providers([ep::CPU::default().build().error_on_failure()])?
        .with_intra_threads(8)?
        .with_inter_threads(1)?
        .with_parallel_execution(false)?
        .commit_from_file(Path::new(&args[1]))?;
    println!("ORT {version}: model loaded, CPU only, intra_threads=8, inter_threads=1, sequential");
    println!("{}", ort::info());

    let index_path = args[2].to_str().ok_or("USearch index path must be UTF-8")?;
    let metadata = Index::metadata(index_path)?;
    if metadata.dimensions != 1024 || metadata.metric != MetricKind::Cos {
        return Err(format!("Unexpected index header: {metadata:?}").into());
    }
    let index = Index::new(&metadata.into())?;
    index.view(index_path)?;
    if index.size() != 52664 || index.dimensions() != 1024 || index.metric_kind() != MetricKind::Cos
    {
        return Err(format!(
            "Unexpected index: len={}, ndim={}, metric={:?}",
            index.size(),
            index.dimensions(),
            index.metric_kind()
        )
        .into());
    }
    index.change_expansion_search(128);
    if index.expansion_search() != 128 {
        return Err("USearch did not retain ef_search=128".into());
    }
    println!("USearch: read-only view, len=52664, ndim=1024, metric=cos, ef_search=128");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requires_runtime_1_24() {
        assert!(check_runtime_version("1.24.4").is_ok());
        for version in ["1.23.0", "1.25.0", "2.24.0", "1.240.0"] {
            assert!(check_runtime_version(version).is_err());
        }
    }

    #[test]
    fn requires_exact_reference_count_and_explicit_special_tokens() {
        let mut reference =
            serde_json::json!({"add_special_tokens":true,"cases":vec![Value::Null;120]});
        assert!(reference_options(&reference).is_ok());
        reference["cases"].as_array_mut().unwrap().pop();
        assert!(reference_options(&reference).is_err());
        reference["cases"].as_array_mut().unwrap().push(Value::Null);
        reference["add_special_tokens"] = Value::Null;
        assert!(reference_options(&reference).is_err());
    }
}
