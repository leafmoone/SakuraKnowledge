//! Pure bounded branch fusion; cosine distance is comparable only after contract checks.
use serde_json::{json,Value};
use std::collections::{BTreeMap,BTreeSet};
use super::Result;
fn key(v:&Value)->Result<(String,String,String)> {
 let e=v.get("entry").or_else(||v.get("entry_key")).unwrap_or(v);
 Ok((e["kind"].as_str().ok_or("missing kind")?.into(),e["namespace"].as_str().ok_or("missing namespace")?.into(),e["value"].as_str().ok_or("missing value")?.into()))
}
pub fn compatible(contracts:&[Value])->Result<()> {
 if let Some(first)=contracts.first() {
  for c in contracts {
   for n in ["revision","dimension","pooling","normalize","query_prefix","dtype","output"] {if c[n].is_null()||c[n]!=first[n] {return Err("incompatible semantic encoder contract".into());}}
   if c["dimension"]!=1024||c["ann"]["metric"]!="cos"||c["ann"]["dtype"]!="i8" {return Err("incompatible semantic distance contract".into());}
  }
 }
 Ok(())
}
pub fn fuse(parts:&[(String,Value)],limit:usize)->Result<Vec<Value>> {
 let mut dense=Vec::new();
 for (pack,p) in parts {for hit in p["dense_hits"].as_array().into_iter().flatten() {let d=hit["distance"].as_f64().filter(|d|d.is_finite()).ok_or("nonfinite/missing ANN distance")?;dense.push((d,key(hit)?,hit["document_id"].to_string(),hit["chunk_id"].to_string(),pack.clone(),hit.clone()));}}
 dense.sort_by(|a,b|a.0.total_cmp(&b.0).then(a.1.cmp(&b.1)).then(a.2.cmp(&b.2)).then(a.3.cmp(&b.3)));
 let mut candidates:BTreeMap<_,Value>=BTreeMap::new();let mut dense_keys=BTreeSet::new();let mut dense_rank=0usize;
 for (d,k,_,_,pack,hit) in dense {
  let first=dense_keys.insert(k.clone());if first {dense_rank+=1;}
  if first && dense_rank>100 {continue;}
  if !first && !candidates.contains_key(&k) {continue;}
  let c=candidates.entry(k).or_insert_with(||json!({"entry":hit["entry"],"rrf_score":0.,"provenance":[],"trusted_pins":[],"source_packs":[],"backend_ranks":[]}));
  if first {c["rrf_score"]=json!(1./(60.+dense_rank as f64));c["global_semantic_rank"]=json!(dense_rank);c["best_distance"]=json!(d);c["backend_ranks"].as_array_mut().unwrap().push(json!(["dense",dense_rank]));}
  add_hit(c,&pack,"dense",hit);
 }
 for (pack,p) in parts {
  let mut seen=BTreeSet::new();let mut rank=0;
  for hit in p["lexical_hits"].as_array().into_iter().flatten() {
   let k=key(hit)?;let first=seen.insert(k.clone());if first {rank=hit["rank"].as_u64().ok_or("missing lexical raw rank")? as usize;}
   let c=candidates.entry(k).or_insert_with(||json!({"entry":hit["entry"],"rrf_score":0.,"provenance":[],"trusted_pins":[],"source_packs":[],"backend_ranks":[]}));
   if first {c["rrf_score"]=json!(c["rrf_score"].as_f64().unwrap()+1./(60.+rank as f64));c["backend_ranks"].as_array_mut().unwrap().push(json!([format!("bm25:{pack}"),rank]));}
   add_hit(c,pack,"bm25",hit.clone());
  }
  for pin in p["trusted_pins"].as_array().into_iter().flatten() {
   let c=candidates.entry(key(pin)?).or_insert_with(||json!({"entry":pin["entry"],"rrf_score":0.,"provenance":[],"trusted_pins":[],"source_packs":[],"backend_ranks":[]}));
   let mut pin=pin.clone();pin["source_pack"]=json!(pack);let a=c["trusted_pins"].as_array_mut().unwrap();if !a.contains(&pin){a.push(pin);}
   add_pack(c,pack);
  }
  for item in p["candidates"].as_array().into_iter().flatten() {
   if item["provenance"].is_null() { let c=candidates.entry(key(item)?).or_insert_with(||{let mut c=item.clone();c["entry"]=item.get("entry").or_else(||item.get("entry_key")).cloned().unwrap_or(Value::Null);c["rrf_score"]=json!(0.);c["provenance"]=json!([]);c["trusted_pins"]=json!([]);c["source_packs"]=json!([]);c["backend_ranks"]=json!([]);c});add_pack(c,pack); }
  }
 }
 let mut rows:Vec<_>=candidates.into_iter().collect();rows.sort_by(|a,b|{
  let pin=|v:&Value|!v["trusted_pins"].as_array().unwrap().is_empty();pin(&b.1).cmp(&pin(&a.1)).then(b.1["rrf_score"].as_f64().unwrap().total_cmp(&a.1["rrf_score"].as_f64().unwrap())).then(a.0.cmp(&b.0))
 });
 Ok(rows.into_iter().take(limit).enumerate().map(|(i,(_,mut c))|{c["hybrid_rank"]=json!(i+1);let mut citations=c.get("citations").and_then(Value::as_array).cloned().unwrap_or_default();for p in c["provenance"].as_array().unwrap(){let h=&p["hit"];let r=json!({"document_id":h["document_id"],"source_id":h["source_id"],"evidence_id":h["evidence_id"]});if !citations.contains(&r){citations.push(r);}}for p in c["trusted_pins"].as_array().unwrap(){let r=json!({"source_id":p["source_id"],"evidence_id":p["evidence_id"]});if !citations.contains(&r){citations.push(r);}}c["citations"]=json!(citations);c}).collect())
}
fn add_pack(c:&mut Value,pack:&str) {let ids=c["source_packs"].as_array_mut().unwrap();if !ids.contains(&json!(pack)){ids.push(json!(pack));ids.sort_by_key(Value::to_string);}}
fn add_hit(c:&mut Value,pack:&str,backend:&str,hit:Value){add_pack(c,pack);let p=json!({"backend":backend,"source_pack":pack,"hit":hit});let a=c["provenance"].as_array_mut().unwrap();if !a.contains(&p){a.push(p);a.sort_by_key(Value::to_string);}}
#[cfg(test)]
mod tests {
 use super::*;
 fn h(value:&str,d:f64)->Value {json!({"entry":{"kind":"subject","namespace":"test","value":value},"distance":d,"rank":1,"score":1.-d,"document_id":value,"chunk_id":value,"source_id":value,"evidence_id":value})}
 fn p(hits:Vec<Value>)->Value {json!({"dense_hits":hits,"lexical_hits":[],"trusted_pins":[],"candidates":[]})}
 #[test] fn distance_beats_local_rank_one(){let r=fuse(&[("a".into(),p(vec![h("a",0.8)])),("b".into(),p(vec![h("b",0.1)]))],10).unwrap();assert_eq!(r[0]["entry"]["value"],"b");}
 #[test] fn worse_local_rank_beats_other_pack_first(){let r=fuse(&[("a".into(),p(vec![h("a",0.8)])),("b".into(),p(vec![h("b",0.1),h("c",0.2)]))],10).unwrap();assert_eq!(r[1]["entry"]["value"],"c");}
 #[test] fn tie_is_pack_order_independent(){let a=("a".into(),p(vec![h("a",0.1)]));let b=("b".into(),p(vec![h("b",0.1)]));assert_eq!(fuse(&[a.clone(),b.clone()],10).unwrap(),fuse(&[b,a],10).unwrap());}
 #[test] fn same_typed_key_counts_once_and_keeps_all_proofs(){let mut second=h("a",0.2);second["document_id"]=json!("other");let r=fuse(&[("a".into(),p(vec![h("a",0.1)])),("b".into(),p(vec![second]))],10).unwrap();assert_eq!(r.len(),1);assert_eq!(r[0]["best_distance"],0.1);assert_eq!(r[0]["provenance"].as_array().unwrap().len(),2);assert_eq!(r[0]["rrf_score"],1./61.);}
 #[test] fn bm25_scale_does_not_affect_order(){let mut x=p(vec![]);x["lexical_hits"]=json!([h("a",0.1),h("b",0.2)]);x["lexical_hits"][1]["rank"]=json!(2);let a=fuse(&[("a".into(),x.clone())],10).unwrap();x["lexical_hits"][0]["score"]=json!(-1e99);x["lexical_hits"][1]["score"]=json!(1e99);let b=fuse(&[("a".into(),x)],10).unwrap();assert_eq!(a.iter().map(|r|&r["entry"]).collect::<Vec<_>>(),b.iter().map(|r|&r["entry"]).collect::<Vec<_>>());}
 #[test] fn trusted_pin_first(){let mut x=p(vec![h("a",0.1)]);x["trusted_pins"]=json!([h("z",0.9)]);assert_eq!(fuse(&[("a".into(),x)],10).unwrap()[0]["entry"]["value"],"z");}
 #[test] fn lexical_only_has_no_dense_rank(){let mut x=p(vec![]);x["lexical_hits"]=json!([h("a",0.1)]);assert!(fuse(&[("a".into(),x)],10).unwrap()[0]["global_semantic_rank"].is_null());}
 #[test] fn semantic_entry_depth_is_100(){let hits=(0..150).map(|i|h(&format!("{i:03}"),i as f64/200.)).collect();assert_eq!(fuse(&[("a".into(),p(hits))],200).unwrap().len(),100);}
 #[test] fn distance_missing_or_nonfinite_rejected(){let mut hit=h("a",0.1);hit["distance"]=Value::Null;assert!(fuse(&[("a".into(),p(vec![hit]))],10).is_err());}
 #[test] fn wrong_compatible_contract_rejected(){let a=json!({"revision":"r","dimension":1024,"pooling":"cls","normalize":true,"query_prefix":"","dtype":"float32","output":"embeddings","ann":{"metric":"cos","dtype":"i8"}});let mut b=a.clone();b["revision"]=json!("other");assert!(compatible(&[a,b]).is_err());}
}
