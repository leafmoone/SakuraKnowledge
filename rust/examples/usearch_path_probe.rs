//! Isolated read-only native path probe; not FULLSemanticRuntime E2E.
#[cfg(feature = "semantic")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::fs::File;
    use std::io::{Read, Seek, SeekFrom};
    use usearch::{Index, MetricKind, ScalarKind};
    let args: Vec<String> = std::env::args().collect();
    if args.len() == 6 && args[1] == "--saved-120-ef" {
        return saved_120_ef(&args[2], &args[3], &args[4], &args[5]);
    }
    if args.len() == 4 && args[1] == "--saved-five-query" {
        return saved_five_query(&args[2], &args[3]);
    }
    if args.len() != 4 {
        return Err("usage: usearch_path_probe index sample vectors.npy".into());
    }
    let metadata = Index::metadata(&args[1])?;
    if metadata.dimensions != 1024 || metadata.metric != MetricKind::Cos {
        return Err("metadata contract mismatch".into());
    }
    let index = Index::new(&metadata.into())?;
    index.view(&args[1])?;
    if index.size() != 1366520
        || index.dimensions() != 1024
        || index.metric_kind() != MetricKind::Cos
        || index.scalar_kind() != ScalarKind::F32
        || index.connectivity() != 16
    {
        return Err("native index contract mismatch".into());
    }
    // Size plus exactly one count for every expected key establishes no missing,
    // duplicate or out-of-range keys without introducing an API/fallback change.
    for key in 0..1366520 {
        if index.count(key) != 1 {
            return Err(format!("key audit failed: {key}").into());
        }
    }
    let sample: serde_json::Value = serde_json::from_reader(File::open(&args[2])?)?;
    let positions = sample["positions"].as_array().ok_or("sample positions")?;
    if positions.len() != 1200 {
        return Err("sample size".into());
    }
    let mut file = File::open(&args[3])?;
    let mut prefix = [0u8; 12];
    file.read_exact(&mut prefix[..8])?;
    if &prefix[..6] != b"\x93NUMPY" {
        return Err("NPY magic".into());
    }
    let header_bytes = if prefix[6] == 1 {
        file.read_exact(&mut prefix[8..10])?;
        u16::from_le_bytes([prefix[8], prefix[9]]) as usize
    } else if prefix[6] == 2 {
        file.read_exact(&mut prefix[8..12])?;
        u32::from_le_bytes(prefix[8..12].try_into()?) as usize
    } else {
        return Err("NPY version".into());
    };
    let mut header = vec![0; header_bytes];
    file.read_exact(&mut header)?;
    let header = std::str::from_utf8(&header)?;
    if !header.contains("'<f4'") || !header.contains("False") || !header.contains("1366520, 1024") {
        return Err("NPY shape/dtype/order".into());
    }
    let data_offset = file.stream_position()?;
    let mut actual = vec![0f32; 1024];
    let mut raw = vec![0u8; 4096];
    for position in positions {
        let key = position.as_u64().ok_or("sample key")?;
        if index.get(key, &mut actual)? != 1 {
            return Err("vector count".into());
        }
        file.seek(SeekFrom::Start(data_offset + key * 4096))?;
        file.read_exact(&mut raw)?;
        for (i, chunk) in raw.as_chunks::<4>().0.iter().enumerate() {
            if actual[i].to_bits() != u32::from_le_bytes(*chunk) {
                return Err(format!("FP32 mapping mismatch key={key} component={i}").into());
            }
        }
    }
    drop(index);
    println!(
        "{}",
        serde_json::json!({"METADATA":"PASS","PATH_VIEW":"PASS", "FULL_KEY_AUDIT":"PASS", "count":1366520,"missing":0,"duplicates":0,"out_of_range":0,"FIXED_SAMPLE_VECTOR_MAPPING":"PASS","sample_count":1200,"comparison":"EXACT_FP32_BITS","FULL_RUNTIME_QUALIFICATION":"NOT_RUN","FULL_QUALITY_ACCEPTANCE":"NOT_RUN"})
    );
    Ok(())
}

#[cfg(feature = "semantic")]
fn query_vector(value: &serde_json::Value) -> Result<Vec<f32>, Box<dyn std::error::Error>> {
    let vector: Vec<f32> = value["vector"].as_array().ok_or("saved vector missing")?
        .iter().map(|v| v.as_f64().map(|n| n as f32).ok_or("invalid component")).collect::<Result<_, _>>()?;
    let norm = vector.iter().map(|&v| f64::from(v).powi(2)).sum::<f64>().sqrt();
    if vector.len() != 1024 || vector.iter().any(|v| !v.is_finite()) || (norm - 1.0).abs() > 1e-4 {
        return Err("invalid saved normalized f32 query".into());
    }
    Ok(vector)
}

#[cfg(feature = "semantic")]
fn saved_five_query(index_path: &str, responses: &str) -> Result<(), Box<dyn std::error::Error>> {
    use std::fs::File;
    use std::time::Instant;
    use usearch::{Index, MetricKind, ScalarKind};
    let start = Instant::now();
    let metadata = Index::metadata(index_path)?;
    let index = Index::new(&metadata.into())?;
    index.view(index_path)?;
    index.change_expansion_search(128);
    if index.size() != 1366520 || index.dimensions() != 1024 || index.metric_kind() != MetricKind::Cos
        || index.scalar_kind() != ScalarKind::F32 || index.connectivity() != 16 || index.expansion_search() != 128 {
        return Err("original ANN contract mismatch".into());
    }
    let open_ms = start.elapsed().as_secs_f64() * 1000.0;
    let mut cases = Vec::new();
    for name in ["P4-033", "P4-035", "P4-039", "P4-042", "P4-064"] {
        let value: serde_json::Value = serde_json::from_reader(File::open(std::path::Path::new(responses).join(format!("formal-{name}.json")))?)?;
        if value["case_id"] != name { return Err("case mismatch".into()); }
        let vector = query_vector(&value)?;
        let start = Instant::now();
        let found = index.search(&vector, 512)?;
        if found.keys.len() != 512 || found.distances.len() != 512
            || found.distances.iter().any(|v| !v.is_finite())
            || found.distances.windows(2).any(|w| w[0] > w[1]) { return Err("invalid ANN result".into()); }
        cases.push(serde_json::json!({"case_id":name,"positions":found.keys,"distances":found.distances,
            "search_ms":start.elapsed().as_secs_f64()*1000.0}));
    }
    println!("{}",serde_json::json!({"new_measurement_not_historical":true,"open_ms":open_ms,"ef_search":128,"depth":512,"cases":cases}));
    Ok(())
}

#[cfg(feature = "semantic")]
fn compare_bits(actual: &[f32], raw: &[u8]) -> Result<(), String> {
    if raw.len() != actual.len() * 4 { return Err("FP32 row length mismatch".into()); }
    for (component, (&value, bytes)) in actual.iter().zip(raw.chunks_exact(4)).enumerate() {
        let expected = u32::from_le_bytes(bytes.try_into().unwrap());
        if value.to_bits() != expected {
            return Err(format!("component={component} index_bits={} npy_bits={expected}", value.to_bits()));
        }
    }
    Ok(())
}

#[cfg(feature = "semantic")]
fn saved_120_ef(index_path: &str, responses: &str, vectors: &str, reference: &str) -> Result<(), Box<dyn std::error::Error>> {
    use std::fs::File;
    use std::io::{Read, Seek, SeekFrom};
    use std::time::Instant;
    use usearch::{Index, MetricKind, ScalarKind};
    let metadata = Index::metadata(index_path)?;
    let index = Index::new(&metadata.into())?;
    index.view(index_path)?;
    if index.size() != 1366520 || index.dimensions() != 1024 || index.metric_kind() != MetricKind::Cos
        || index.scalar_kind() != ScalarKind::F32 || index.connectivity() != 16 { return Err("ANN contract mismatch".into()); }
    let reference: serde_json::Value = serde_json::from_reader(File::open(reference)?)?;
    let mut file = File::open(vectors)?;
    let mut prefix = [0u8;8]; file.read_exact(&mut prefix)?;
    if &prefix[..6] != b"\x93NUMPY" { return Err("NPY magic".into()); }
    let header_bytes = match prefix[6] {
        1 => { let mut b=[0;2];file.read_exact(&mut b)?;u16::from_le_bytes(b) as usize },
        2 => { let mut b=[0;4];file.read_exact(&mut b)?;u32::from_le_bytes(b) as usize },
        _ => return Err("NPY version".into()) };
    let mut header=vec![0;header_bytes];file.read_exact(&mut header)?;
    let header=std::str::from_utf8(&header)?;
    if !header.contains("'<f4'") || !header.contains("False") || !header.contains("1366520, 1024") { return Err("NPY dtype/shape/order".into()); }
    let offset=file.stream_position()?;
    let mut bit_rows=Vec::new(); let mut recall_targets=std::collections::BTreeMap::new();
    for case in reference["cases"].as_array().ok_or("reference cases")? {
        let name=case["case_id"].as_str().ok_or("reference name")?;
        let mut targets=Vec::new();
        for target in case["targets_all_entity_chunks"].as_array().ok_or("reference targets")? {
            let position=target["position"].as_u64().ok_or("position")?;
            let mut actual=vec![0.0;1024];
            if index.get(position,&mut actual)? != 1 { return Err(format!("target row count position={position}").into()); }
            file.seek(SeekFrom::Start(offset+position*4096))?;
            let mut raw=vec![0;4096];file.read_exact(&mut raw)?;
            compare_bits(&actual,&raw).map_err(|e|format!("target bits mismatch position={position} {e}"))?;
            bit_rows.push(serde_json::json!({"case_id":name,"position":position,"components":1024,"exact_fp32_bits":"PASS"}));
            targets.push(position);
        }
        recall_targets.insert(name.to_owned(),targets);
    }
    // Preload and validate every saved query before any search. No encoding or FTS.
    let mut queries=Vec::new();
    for n in 1..=120 {
        let name=format!("P4-{n:03}");
        let value:serde_json::Value=serde_json::from_reader(File::open(std::path::Path::new(responses).join(format!("formal-{name}.json")))?)?;
        if value["case_id"] != name { return Err("saved query case mismatch".into()); }
        queries.push((name,query_vector(&value)?));
    }
    let mut tiers=Vec::new();
    for ef in [1024,2048] {
        index.change_expansion_search(ef);
        if index.expansion_search()!=ef { return Err("effective configured ef mismatch".into()); }
        let mut cases=Vec::new(); let mut missing=false;
        for (name,vector) in &queries {
            let start=Instant::now();let found=index.search(vector,512)?;
            if found.keys.len()!=512 || found.distances.iter().any(|v|!v.is_finite())
                || found.distances.windows(2).any(|w|w[0]>w[1]) { return Err("invalid ANN results".into()); }
            if ["P4-035","P4-039","P4-064"].contains(&name.as_str()) && recall_targets[name].iter().all(|p|!found.keys.contains(p)) { missing=true; }
            cases.push(serde_json::json!({"case_id":name,"positions":found.keys,"distances":found.distances,"search_ms":start.elapsed().as_secs_f64()*1000.0}));
        }
        tiers.push(serde_json::json!({"ef_search":ef,"effective_width":ef.max(512),"wanted":512,"cases":cases,"known_exact_top2_target_still_missing":missing}));
        if !missing { break; }
    }
    println!("{}",serde_json::json!({"target_bits":bit_rows,"saved_queries":queries.len(),"same_index_instance":true,"tiers":tiers}));
    Ok(())
}

#[cfg(all(test, feature = "semantic"))]
mod saved_query_tests {
    #[test]
    fn target_bit_comparison_reports_component() {
        assert!(super::compare_bits(&[1.0],&1.0f32.to_le_bytes()).is_ok());
        assert!(super::compare_bits(&[1.0],&2.0f32.to_le_bytes()).unwrap_err().contains("component=0"));
        assert!(super::compare_bits(&[1.0],&[]).is_err());
    }
    #[test]
    fn validates_saved_f32_vector_without_encoding() {
        let mut v = vec![0.0;1024]; v[0] = 1.0;
        assert!(super::query_vector(&serde_json::json!({"vector":v})).is_ok());
        assert!(super::query_vector(&serde_json::json!({"vector":[1.0]})).is_err());
        assert!(super::query_vector(&serde_json::json!({"vector":vec![0.0;1024]})).is_err());
    }
}

#[cfg(not(feature = "semantic"))]
fn main() {
    panic!("semantic feature required");
}
