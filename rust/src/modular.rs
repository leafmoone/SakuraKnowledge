//! Repository-independent optional source pack discovery and typed-key federation.
#[cfg(feature="semantic")]
#[path="semantic_federation.rs"]
mod semantic_federation;
use crate::{Runtime,TagOptions};
use serde_json::{json,Value};
use std::path::{Path,PathBuf};
use std::collections::{BTreeMap,BTreeSet};
pub type Result<T> = std::result::Result<T,Box<dyn std::error::Error>>;
pub struct SourcePack { pub id:String,pub manifest:Value,pub root:PathBuf }
pub struct PackRuntime { pub root:PathBuf,pub packs:Vec<SourcePack>,pub model_directory:PathBuf,pub bin_directory:PathBuf }
fn key(v:&Value)->Option<String> { let v=v.get("entry_key").or_else(||v.get("entry")).or_else(||v.get("tag_key")).unwrap_or(v); Some(format!("{}\0{}\0{}",v["kind"].as_str()?,v["namespace"].as_str()?,v["value"].as_str()?)) }
impl PackRuntime {
 pub fn discover(config:&Path)->Result<Self> {
  let root=config.parent().ok_or("config parent")?.to_path_buf();let cfg:Value=serde_json::from_slice(&std::fs::read(config)?)?;
  let relative=|name:&str|->Result<PathBuf>{let p=Path::new(cfg[name].as_str().ok_or("config directory required")?);if p.is_absolute()||p.components().any(|c|!matches!(c,std::path::Component::Normal(_))) {return Err("config directories must be relative".into());}Ok(root.join(p))};
  let packdir=relative("packs_directory")?;let model_directory=relative("model_directory")?;let bin_directory=relative("bin_directory")?;let mut packs=Vec::new();
  if packdir.exists(){for entry in std::fs::read_dir(&packdir)? {let path=entry?.path();let file=path.join("manifest.json");if !file.exists(){continue;}let manifest:Value=serde_json::from_slice(&std::fs::read(file)?)?;if manifest["schema"]!="sakura-source-pack-v1"{return Err("unsupported source manifest".into());}let id=manifest["pack_id"].as_str().ok_or("pack_id required")?.to_owned();if id.is_empty()||id.len()>128||id=="."||id==".."||!id.bytes().all(|b|b.is_ascii_alphanumeric()||b"-_.".contains(&b)){return Err("unsafe source pack_id".into());}let capabilities=manifest["capabilities"].as_array().ok_or("capabilities required")?;if !capabilities.iter().any(|v|v=="structured")||!capabilities.iter().any(|v|v=="lexical"){return Err("unsupported source capabilities".into());}let unique:BTreeSet<_>=capabilities.iter().filter_map(Value::as_str).collect();if unique.len()!=capabilities.len(){return Err("duplicate source capabilities".into());}let sem=capabilities.iter().any(|v|v=="semantic");let artifacts=manifest["artifacts"].as_object().ok_or("source artifacts required")?;let expected:BTreeSet<&str>=if sem{["snapshot","lexical_membership","mapping","index"].into_iter().collect()}else{["snapshot","lexical_membership"].into_iter().collect()};if artifacts.keys().map(String::as_str).collect::<BTreeSet<_>>()!=expected||(!sem&&!manifest["semantic"].is_null()){return Err("artifact capability contradiction".into());}let mut artifact_paths=BTreeSet::new();for item in artifacts.values(){if !artifact_paths.insert(item["path"].as_str().ok_or("artifact path required")?){return Err("duplicate artifact path".into());}}if capabilities.iter().any(|v|!matches!(v.as_str(),Some("structured"|"lexical"|"semantic"))){return Err("unsupported source capability".into());}if sem {if manifest["requires_model"]!="bge-m3"{return Err("unsupported_model_contract".into());}}else if !manifest["requires_model"].is_null(){return Err("lexical source must not require semantic model".into());}for field in ["source_ids","namespaces"]{let values=manifest[field].as_array().ok_or("source_ids/namespaces required")?;let mut seen=BTreeSet::new();if values.is_empty(){return Err("empty source_ids/namespaces".into());}for value in values{let s=value.as_str().ok_or("invalid source namespace/id")?;if s.is_empty()||s.len()>256||s.chars().any(char::is_control)||!seen.insert(s){return Err("unsafe/duplicate source namespace/id".into());}}}for item in manifest["artifacts"].as_object().ok_or("source artifacts required")?.values(){let artifact=Path::new(item["path"].as_str().ok_or("artifact path required")?);if artifact.is_absolute()||artifact.components().count()!=1||artifact.components().any(|c|!matches!(c,std::path::Component::Normal(_))){return Err("unsafe source artifact path".into());}if !path.join(artifact).is_file(){return Err("source_asset_missing".into());}}if packs.iter().any(|p:&SourcePack|p.id==id){return Err("duplicate pack_id".into());}packs.push(SourcePack{id,manifest,root:path});}}
  packs.sort_by(|a,b|a.id.cmp(&b.id));Ok(Self{root,packs,model_directory,bin_directory})
 }
 pub fn selected(&self,sources:&[String])->Result<Vec<&SourcePack>> {if sources.is_empty(){return Ok(self.packs.iter().collect());}let wanted:BTreeSet<_>=sources.iter().flat_map(|s|s.split(',')).filter(|s|!s.is_empty()).collect();for s in &wanted {if !self.packs.iter().any(|p|p.id==*s){return Err(format!("source_pack_missing: {s}").into());}}Ok(self.packs.iter().filter(|p|wanted.contains(p.id.as_str())).collect())}
 pub fn list(&self)->Value {let installed:Vec<_>=self.packs.iter().map(|p|json!({"pack_id":p.id,"version":p.manifest["version"],"capabilities":p.manifest["capabilities"],"requires_model":p.manifest["requires_model"],"lexical_mode":p.manifest.get("lexical_mode").cloned().unwrap_or(json!("trusted_documents_and_identity")),"trusted_fts_documents":p.manifest["trusted_fts_documents"],"model_present":self.model_directory.join("bge-m3/manifest.json").is_file(),"status":if p.manifest["version"].is_string() && p.root.join("knowledge.sqlite").is_file(){"installed"}else{"invalid"}})).collect();let missing:Vec<String>=Vec::new();json!({"installed_packs":installed,"not_installed":missing,"model":{"id":"bge-m3","installed":self.model_directory.join("bge-m3/manifest.json").is_file()}})}
 pub fn structured(&self,command:&str,query:&str,args:&[String],sources:&[String])->Result<Value>{
  let selected=self.selected(sources)?;let start=std::time::Instant::now();let mut parts=Vec::new();
  let option=|name:&str|args.windows(2).find(|p|p[0]==name).map(|p|p[1].as_str());let kind=option("--kind");let ns=option("--namespace");let limit=option("--limit").or_else(||option("--topk")).map(str::parse::<u32>).transpose()?.unwrap_or(10);
  if ["search","related","resolve-tag"].contains(&command)&&!(1..=100).contains(&limit){return Err(crate::Error::Invalid(if command=="search"{"topk must be 1..100".into()}else{"limit must be 1..100".into()}).into());}
  for pack in selected {if start.elapsed().as_secs_f64()>5.0{return Err("operation deadline exceeded".into());}let mut runtime=Runtime::open(pack.root.join("knowledge.sqlite"))?;runtime.set_deadline(start+std::time::Duration::from_secs(5));let value=match command {
   "lookup"=>if args.iter().any(|a|a=="--key"){runtime.lookup_key(kind.ok_or(crate::Error::Invalid("exact key requires --kind and --namespace".into()))?,ns.ok_or(crate::Error::Invalid("exact key requires --kind and --namespace".into()))?,query)?}else{runtime.lookup(query,kind,ns)?},
   "search"=>runtime.search(query,100,kind,ns)?,"ask"=>runtime.ask(query,kind,ns,option("--target-namespace").or_else(||option("--target-tag-namespace")))?,
   "related"=>if args.len()>=2&&!args[0].starts_with("--"){runtime.related(query,&args[0],&args[1],option("--relation"),kind,limit)?}else{runtime.related(kind.ok_or("--kind required")?,ns.ok_or("--namespace required")?,query,option("--relation"),option("--filter"),limit)?},
   "resolve-tag"=>runtime.resolve_tag(query,TagOptions{kind,namespace:ns,target_namespace:option("--target-namespace"),category:option("--category").map(str::parse).transpose()?,key:args.iter().any(|a|a=="--key"),limit})?,
   "inspect"=>runtime.inspect()?,_=>return Err("unsupported modular command".into())};parts.push((pack.id.clone(),value));}
  Ok(crate::response::bound_response(merge(command,query,parts,self.packs.iter().map(|p|p.id.clone()).collect(),limit as usize),start+std::time::Duration::from_secs(5))?)
 }
}
#[cfg(feature="semantic")]
pub struct ModularSemantic {
    pub runtime:PackRuntime,
    encoder:Option<std::rc::Rc<std::cell::RefCell<crate::semantic::SharedEncoder>>>,
    handles:BTreeMap<String,crate::semantic::SemanticEngine>,
    pub open_timings_ms:Value,
}
#[cfg(feature="semantic")]
impl ModularSemantic {
 pub fn open(config:&Path,sources:&[String])->Result<Self>{
  let start=std::time::Instant::now();let runtime=PackRuntime::discover(config)?;
  let ids:Vec<_>=runtime.selected(sources)?.iter().map(|p|p.id.clone()).collect();let semantic:Vec<_>=runtime.packs.iter().filter(|p|ids.contains(&p.id)&&p.manifest["requires_model"]=="bge-m3").collect();
  let model=runtime.model_directory.join("bge-m3/manifest.json");let encoder=if semantic.is_empty(){None}else{if !model.is_file(){return Err("semantic_model_missing: bge-m3".into());}Some(std::rc::Rc::new(std::cell::RefCell::new(crate::semantic::SharedEncoder::open_model(&model,&runtime.bin_directory)?)))};
  let mut handles=BTreeMap::new();for pack in semantic {handles.insert(pack.id.clone(),crate::semantic::SemanticEngine::open_source(pack.root.join("knowledge.sqlite"),pack.root.join("manifest.json"),&model,encoder.as_ref().unwrap().clone())?);}
  semantic_federation::compatible(&handles.values().map(|h|h.federation_contract()).collect::<Vec<_>>())?;
  let sessions=usize::from(encoder.is_some());
  Ok(Self{runtime,encoder,handles,open_timings_ms:json!({"total":start.elapsed().as_secs_f64()*1000.,"model_sessions":sessions})})
 }
 pub fn retrieve(&mut self,query:&str,options:&crate::semantic::RetrieveOptions,sources:&[String])->Result<Value>{
  let start=std::time::Instant::now();options.validate()?;let selected=self.runtime.selected(sources)?;let mut parts=Vec::new();let mut branch_options=options.clone();branch_options.limit=100;
  let before=self.encoder.as_ref().map_or(0,|e|e.borrow().query_encodings);
  let vector=if selected.iter().any(|p|p.manifest["requires_model"]=="bge-m3"){Some(self.encoder.as_ref().ok_or("semantic_model_missing: bge-m3")?.borrow_mut().encode(query)?)}else{None};
  let multi=selected.iter().filter(|p|p.manifest["requires_model"]=="bge-m3").count()>1;
  for pack in selected {let response=if pack.manifest["requires_model"]=="bge-m3"{let h=self.handles.get_mut(&pack.id).ok_or("semantic pack not opened")?;if multi {h.retrieve_branches_encoded(query,&branch_options,vector.as_ref().unwrap())?}else{h.retrieve_encoded(query,&branch_options,vector.as_ref().unwrap())?}}else{crate::semantic::lexical_retrieve(pack.root.join("knowledge.sqlite"),query,&branch_options)?};parts.push((pack.id.clone(),response));}
  let semantic:Vec<_>=parts.iter().filter(|(id,_)|self.handles.contains_key(id)).map(|p|p.0.clone()).collect();
  let mut value=if multi {
   let mut candidates=semantic_federation::fuse(&parts,100)?;
   candidates.retain(|c|options.kind.as_ref().is_none_or(|k|c["entry"]["kind"]==*k)&&options.namespace.as_ref().is_none_or(|n|c["entry"]["namespace"]==*n));candidates.truncate(options.limit);
   let mut proofs=Vec::new();
   for (id,_) in &parts {if let Some(h)=self.handles.get_mut(id) {
    let local:Vec<_>=candidates.iter().filter(|c|c["source_packs"].as_array().unwrap().contains(&json!(id))).map(|c|{let mut c=c.clone();for f in ["provenance","trusted_pins"] {c[f]=json!(c[f].as_array().unwrap().iter().filter(|p|p["source_pack"]==*id).cloned().collect::<Vec<_>>());}c}).collect();
    proofs.push((id.clone(),h.materialize_candidates(query,options,&local,start+std::time::Duration::from_secs(5))?));
   }}
   let mut v=json!({"candidates":candidates,"documents":[],"sources":[],"evidence":[],"citations":[],"trusted_pins":[],"dense_hits":[],"lexical_hits":[],"warnings":[],"contract_version":"2","response_version":"sakura-global-distance-v1","query":query,"installed_packs":self.runtime.packs.iter().map(|p|p.id.clone()).collect::<Vec<_>>(),"participating_packs":parts.iter().map(|p|p.0.clone()).collect::<Vec<_>>(),"fusion_policy":"global_cosine_dense_once_plus_source_lexical_rrf60"});
   for (id,p) in &parts {if !self.handles.contains_key(id) {proofs.push((id.clone(),p.clone()));}}
   for f in ["documents","sources","evidence","citations"] {for (id,p) in &proofs {for r in p[f].as_array().unwrap(){let mut r=r.clone();r["source_packs"]=json!([id]);if !v[f].as_array().unwrap().contains(&r){v[f].as_array_mut().unwrap().push(r);}}}}
   for (id,p) in &parts {for pin in p["trusted_pins"].as_array().into_iter().flatten(){let mut pin=pin.clone();pin["source_packs"]=json!([id]);v["trusted_pins"].as_array_mut().unwrap().push(pin);}}
   let pinned:BTreeSet<_>=v["trusted_pins"].as_array().unwrap().iter().filter_map(key).collect();if pinned.len()>1 {v["warnings"]=json!(["multiple_trusted_identities_preserved_not_resolved"]);}
   v
  }else{merge("retrieve",query,parts.clone(),self.runtime.packs.iter().map(|p|p.id.clone()).collect(),100)};
  let pins:BTreeSet<_>=parts.iter().flat_map(|p|p.1["trusted_pins"].as_array().into_iter().flatten()).filter_map(key).collect();
  if let Some(candidates)=value["candidates"].as_array_mut(){candidates.sort_by_key(|c|usize::from(!key(c).is_some_and(|k|pins.contains(&k))));candidates.truncate(options.limit);for (i,c) in candidates.iter_mut().enumerate(){c["hybrid_rank"]=json!(i+1);c["source_pack"]=c["source_packs"].clone();}}
  value["hybrid"]=value["candidates"].clone();
  value["actual_tokens"]=json!(0);
  value["status"]=json!("PASS");value["identity_status"]=json!("not_asserted");value["promoted_identities"]=json!([]);value["canonical"]=Value::Null;value["entity_tag"]=Value::Null;
  value["semantic_capable_packs"]=json!(semantic);value["pack_timings_ms"]=json!(parts.iter().map(|p|json!({"source_pack":p.0,"timings_ms":p.1["timings_ms"]})).collect::<Vec<_>>());value["timings_ms"]=json!({"total":start.elapsed().as_secs_f64()*1000.,"query_encodings":self.encoder.as_ref().map_or(0,|e|e.borrow().query_encodings)-before,"process_query_encodings":self.encoder.as_ref().map_or(0,|e|e.borrow().query_encodings)});if start.elapsed().as_secs_f64()>5.0{return Err("query_budget_exceeded".into());}Ok(value)
 }
}

pub fn merge(command:&str,_query:&str,parts:Vec<(String,Value)>,installed:Vec<String>,limit:usize)->Value{
 let participating:Vec<_>=parts.iter().map(|p|p.0.clone()).collect();let mut result=parts.first().map(|p|p.1.clone()).unwrap_or_else(||json!({"status":"unknown","candidates":[],"relations":[]}));
 result["installed_packs"]=json!(installed);result["participating_packs"]=json!(participating);
 for field in ["candidates","relations","descriptions","evidence_chain","citations","documents","sources","evidence","trusted_pins","dense_hits","lexical_hits","hybrid"] {
  let mut rows:BTreeMap<String,(Value,f64)>=BTreeMap::new();
  for (id,value) in &parts {if let Some(items)=value[field].as_array(){for (rank,item) in items.iter().enumerate(){let identity=if ["candidates","trusted_pins","hybrid"].contains(&field){key(item).unwrap_or_else(||item.to_string())}else{item.to_string()};let record=rows.entry(identity).or_insert_with(||{let mut v=item.clone();v["source_packs"]=json!([]);(v,0.)});record.1+=1./(60.+(rank+1) as f64);if field=="candidates" {for nested in ["citations","descriptions","evidence_ids","source_ids","matched_documents"] {if let Some(other)=item[nested].as_array(){if record.0[nested].is_null(){record.0[nested]=json!([]);}if let Some(target)=record.0[nested].as_array_mut(){for value in other {if !target.contains(value){target.push(value.clone());}}}}}}let ids=record.0["source_packs"].as_array_mut().unwrap();if !ids.contains(&json!(id)){ids.push(json!(id));}}}}
  let mut rows:Vec<_>=rows.into_iter().collect();rows.sort_by(|a,b|{let priority=|v:&Value|if v["matched_by"]=="exact"{0}else if v["matched_by"]=="alias"{1}else{2};if field=="candidates"&&command=="search"{priority(&a.1.0).cmp(&priority(&b.1.0)).then_with(||b.1.1.total_cmp(&a.1.1)).then_with(||a.0.cmp(&b.0))}else{b.1.1.total_cmp(&a.1.1).then_with(||a.0.cmp(&b.0))}});
  let values:Vec<_>=rows.into_iter().take(if field=="candidates"&&["search","retrieve"].contains(&command){limit}else{100}).map(|(_,r)|r.0).collect();if !values.is_empty()||result.get(field).is_some(){result[field]=json!(values);}
 }
 if command=="search" {
  let exact_parts:Vec<_>=parts.iter().filter(|p|key(&p.1["entry_key"]).is_some()||p.1["status"]=="ambiguous").map(|p|p.0.clone()).collect();
  if let Some(items)=result["candidates"].as_array_mut(){items.sort_by_key(|item|if item["matched_by"]=="exact"{0}else if item["matched_by"]=="alias"{1}else{2});}
  if let Some((_,chosen))=parts.iter().find(|p|exact_parts.contains(&p.0)){for field in ["status","entry_key","canonical","citations","descriptions","matched_by","matched_documents","source_id","evidence_id","source_fields","source_fields_evidence","source_fields_truncated","warnings"]{if let Some(v)=chosen.get(field){result[field]=v.clone();}}}else if result["candidates"].as_array().is_some_and(|v|!v.is_empty()){result["status"]=json!("found");}
  let exact_keys:BTreeSet<_>=parts.iter().flat_map(|p|p.1["candidates"].as_array().into_iter().flatten()).filter(|c|c["matched_by"]=="exact"||c["matched_by"]=="alias").filter_map(key).collect();if exact_keys.len()>1{result["status"]=json!("ambiguous");result["canonical"]=Value::Null;result["entry_key"]=Value::Null;result["citations"]=json!([]);result["descriptions"]=json!([]);for f in ["evidence_id","source_id","matched_by","matched_documents","source_fields","source_fields_evidence","source_fields_truncated"]{result.as_object_mut().unwrap().remove(f);}}
 }
 if command=="lookup"{let count=result["candidates"].as_array().map_or(0,Vec::len);result["status"]=json!(if count==0{"not_found"}else if count==1{"found"}else{"ambiguous"});}
 if ["lookup","ask","related"].contains(&command){let identities:BTreeSet<_>=parts.iter().filter_map(|p|key(&p.1["entry_key"])).chain(result["candidates"].as_array().into_iter().flatten().filter_map(key)).collect();if identities.len()==1 {if let Some((_,v))=parts.iter().find(|p|key(&p.1["entry_key"]).is_some()){for f in ["entry_key","canonical","matched_documents","source_fields","source_fields_evidence","source_fields_truncated","matched_by","source_id","evidence_id","tag_key"]{result[f]=v[f].clone();}if command!="lookup" {for f in ["status","answer","mapping_status","query","input_query","query_template","parsed_subject","target_namespace","warnings"]{if let Some(value)=v.get(f){result[f]=value.clone();}}}}}else if identities.len()>1 {for f in ["evidence_id","source_id","matched_by","matched_documents","source_fields","source_fields_evidence","source_fields_truncated"]{result.as_object_mut().unwrap().remove(f);}if command=="ask"{result["mapping_status"]=json!(if parts.iter().any(|p|p.1["mapping_status"]=="not_requested"){ "not_requested" }else{"entity_ambiguous"});result["answer"]=json!("Multiple source entity matches; specify a source key.");}result["status"]=json!(if command=="ask"{"entity_ambiguous"}else{"ambiguous"});result["entry_key"]=Value::Null;result["canonical"]=Value::Null;result["citations"]=json!([]);result["descriptions"]=json!([]);}}
 if command=="resolve-tag"{let targets:BTreeSet<_>=parts.iter().filter(|p|p.1["status"]=="resolved").filter_map(|p|key(&p.1["tag_key"])).collect();if targets.len()>1{result["status"]=json!("ambiguous");result["tag_key"]=Value::Null;}else if targets.len()==1{if let Some((_,v))=parts.iter().find(|p|p.1["status"]=="resolved"){result["status"]=json!("resolved");result["tag_key"]=v["tag_key"].clone();}}}
 result
}
#[cfg(test)]mod tests {use super::*;
#[test]fn source_filter_comma_deduplicates_and_rejects_missing(){let r=PackRuntime{root:PathBuf::new(),packs:vec![SourcePack{id:"danbooru".into(),manifest:json!({}),root:PathBuf::new()},SourcePack{id:"bangumi".into(),manifest:json!({}),root:PathBuf::new()}],model_directory:PathBuf::new(),bin_directory:PathBuf::new()};assert_eq!(r.selected(&["danbooru,bangumi".into(),"danbooru".into()]).unwrap().len(),2);assert!(r.selected(&["absent".into()]).is_err());}
#[test]fn source_rank_never_compares_bm25_and_exact_before_limit(){let p=vec![("a".into(),json!({"candidates":[{"entry_key":{"kind":"page","namespace":"a","value":"first"},"score":-10000,"matched_by":"fts"}]})),("b".into(),json!({"candidates":[{"entry_key":{"kind":"page","namespace":"b","value":"second"},"score":-1,"matched_by":"fts"},{"entry_key":{"kind":"page","namespace":"b","value":"exact"},"matched_by":"exact"}]}))];let out=merge("search","q",p,vec![],1);assert_eq!(out["candidates"][0]["entry_key"]["value"],"exact");}
#[test]fn merged_same_key_keeps_both_citations(){let k=json!({"kind":"character","namespace":"x","value":"a"});let p=vec![("a".into(),json!({"candidates":[{"entry_key":k,"citations":[{"source_id":"one","evidence_id":"1"}]}]})),("b".into(),json!({"candidates":[{"entry_key":k,"citations":[{"source_id":"two","evidence_id":"2"}]}]}))];let v=merge("lookup","a",p,vec![],10);assert_eq!(v["status"],"found");assert_eq!(v["candidates"][0]["citations"].as_array().unwrap().len(),2);}
#[test]fn identical_typed_keys_are_not_ambiguity(){let row=json!({"entry_key":{"kind":"character","namespace":"x","value":"a"}});let out=merge("lookup","a",vec![("one".into(),json!({"candidates":[row.clone()]})),("two".into(),json!({"candidates":[row]}))],vec![],10);assert_eq!(out["candidates"].as_array().unwrap().len(),1);assert_eq!(out["status"],"found");}#[test]fn different_keys_keep_ambiguity(){let rows=vec![("one".into(),json!({"candidates":[{"entry_key":{"kind":"character","namespace":"x","value":"a"}}]})),("two".into(),json!({"candidates":[{"entry_key":{"kind":"character","namespace":"y","value":"a"}}]}))];assert_eq!(merge("lookup","a",rows,vec![],10)["status"],"ambiguous");}}

#[cfg(test)]
mod generic_discovery_tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    struct Fixture { root: PathBuf }
    impl Fixture {
        fn new() -> Self {
            static NEXT: AtomicUsize = AtomicUsize::new(0);
            let root = std::env::temp_dir().join(format!("sakura-discovery-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::Relaxed)));
            std::fs::create_dir(&root).unwrap();
            std::fs::create_dir(root.join("packs")).unwrap();
            std::fs::write(root.join("config.json"), serde_json::to_vec(&json!({"packs_directory":"packs","model_directory":"models","bin_directory":"bin"})).unwrap()).unwrap();
            Self { root }
        }
        fn pack(&self, directory: &str, manifest: &Value) -> PathBuf {
            let root = self.root.join("packs").join(directory);
            std::fs::create_dir_all(&root).unwrap();
            // Discovery checks presence, not artifact contents or snapshot schema.
            for name in ["knowledge.sqlite", "lexical-membership.sqlite", "mapping.sqlite", "index.usearch"] {
                std::fs::write(root.join(name), b"placeholder").unwrap();
            }
            std::fs::write(root.join("manifest.json"), serde_json::to_vec(manifest).unwrap()).unwrap();
            root
        }
        fn discover(&self) -> Result<PackRuntime> { PackRuntime::discover(&self.root.join("config.json")) }
    }
    impl Drop for Fixture {
        fn drop(&mut self) { std::fs::remove_dir_all(&self.root).unwrap(); }
    }
    fn manifest(id: &str, semantic: bool) -> Value {
        let mut v = json!({"schema":"sakura-source-pack-v1","pack_id":id,"version":"tiny-v1","capabilities":["structured","lexical"],"requires_model":null,"source_ids":["independent-provider"],"namespaces":["future:custom/namespace"],"trusted_fts_documents":1,"artifacts":{"snapshot":{"path":"knowledge.sqlite"},"lexical_membership":{"path":"lexical-membership.sqlite"}}});
        if semantic {
            v["capabilities"] = json!(["structured","lexical","semantic"]);
            v["requires_model"] = json!("bge-m3");
            v["semantic"] = json!({"rows":1,"dimension":1024});
            v["artifacts"]["mapping"] = json!({"path":"mapping.sqlite"});
            v["artifacts"]["index"] = json!({"path":"index.usearch"});
        }
        v
    }
    fn rejected(v: Value, expected: &str) {
        let f = Fixture::new();
        f.pack("unrelated-directory", &v);
        let error = f.discover().err().expect("accepted invalid manifest").to_string();
        assert!(error.contains(expected), "expected {expected}, got {error}");
    }
    #[test]
    fn unknown_ids_and_nonwhitelisted_namespaces_use_manifest_not_directory() {
        let f = Fixture::new();
        let z = f.pack("first-directory", &manifest("z-future.pack", true));
        let a = f.pack("second-directory", &manifest("A_custom-1", false));
        let r = f.discover().unwrap();
        assert_eq!(r.packs.iter().map(|p|p.id.as_str()).collect::<Vec<_>>(), ["A_custom-1", "z-future.pack"]);
        assert_eq!(r.packs[0].root, a);
        assert_eq!(r.packs[1].root, z);
        assert_eq!(r.selected(&["z-future.pack,A_custom-1".into(), "z-future.pack".into()]).unwrap().len(), 2);
        assert_eq!(r.list()["not_installed"], json!([]));
        assert_eq!(r.list()["installed_packs"][0]["status"], "installed");
    }
    #[test]
    fn duplicate_manifest_ids_in_different_directories_are_rejected() {
        let f = Fixture::new();
        f.pack("one", &manifest("future", false));
        f.pack("two", &manifest("future", true));
        assert_eq!(f.discover().err().unwrap().to_string(), "duplicate pack_id");
    }
    #[test]
    fn unsafe_pack_ids_are_rejected() {
        for id in ["", ".", "..", "../escape", "a/b", "a\\b", "a b", "中文", &"x".repeat(129)] {
            rejected(manifest(id, false), "unsafe source pack_id");
        }
    }
    #[test]
    fn duplicate_capabilities_are_rejected() {
        let mut v = manifest("future", false);
        v["capabilities"] = json!(["structured","lexical","lexical"]);
        rejected(v, "duplicate source capabilities");
    }
    #[test]
    fn unsupported_semantic_model_is_rejected() {
        for model in [json!("future-model"), Value::Null] {
            let mut v = manifest("future", true);
            v["requires_model"] = model;
            rejected(v, "unsupported_model_contract");
        }
    }
    #[test]
    fn lexical_semantic_capability_contradictions_are_rejected() {
        let mut v = manifest("future", false);
        v["semantic"] = json!({"rows":1});
        rejected(v, "artifact capability contradiction");
        let mut v = manifest("future", false);
        v["artifacts"]["index"] = json!({"path":"index.usearch"});
        rejected(v, "artifact capability contradiction");
        let mut v = manifest("future", true);
        v["artifacts"].as_object_mut().unwrap().remove("mapping");
        rejected(v, "artifact capability contradiction");
        let mut v = manifest("future", false);
        v["requires_model"] = json!("bge-m3");
        rejected(v, "lexical source must not require semantic model");
    }
    #[test]
    fn unsafe_artifact_paths_and_duplicate_paths_are_rejected() {
        for path in ["../knowledge.sqlite", "sub/knowledge.sqlite", "/knowledge.sqlite", ".", ".."] {
            let mut v = manifest("future", false);
            v["artifacts"]["snapshot"]["path"] = json!(path);
            rejected(v, "unsafe source artifact path");
        }
        let mut v = manifest("future", false);
        v["artifacts"]["snapshot"]["path"] = json!("lexical-membership.sqlite");
        rejected(v, "duplicate artifact path");
    }
    #[test]
    fn unsafe_or_duplicate_namespace_and_source_metadata_is_rejected() {
        for field in ["namespaces", "source_ids"] {
            for values in [json!([]), json!([""]), json!(["bad\u{0000}name"]), json!(["bad\nname"]), json!(["x","x"]), json!(["x".repeat(257)])] {
                let mut v = manifest("future", false);
                let empty = values.as_array().unwrap().is_empty();
                v[field] = values;
                rejected(v, if empty { "empty source_ids/namespaces" } else { "unsafe/duplicate source namespace/id" });
            }
        }
    }
    #[test]
    fn lexical_unknown_pack_is_discovered_without_model_assets() {
        let f = Fixture::new();
        f.pack("lexical-only", &manifest("future-lexical", false));
        let r = f.discover().unwrap();
        assert!(!r.model_directory.exists());
        assert_eq!(r.list()["model"]["installed"], false);
        assert_eq!(r.list()["installed_packs"][0]["requires_model"], Value::Null);
        #[cfg(feature="semantic")]
        {
            let runtime = ModularSemantic::open(&f.root.join("config.json"), &[]).unwrap();
            assert_eq!(runtime.open_timings_ms["model_sessions"], 0);
            assert!(runtime.encoder.is_none());
            assert!(runtime.handles.is_empty());
        }
    }
    #[cfg(feature="semantic")]
    #[test]
    fn unknown_pack_federation_contracts_and_provenance() {
        let f = Fixture::new();
        f.pack("one", &manifest("future-one", true));
        f.pack("two", &manifest("future-two", true));
        let r = f.discover().unwrap();
        let contract = json!({"revision":"tiny","dimension":1024,"pooling":"cls","normalize":true,"query_prefix":"","dtype":"float32","output":"embeddings","ann":{"metric":"cos","dtype":"i8"}});
        semantic_federation::compatible(&[contract.clone(),contract.clone()]).unwrap();
        for (field, value) in [("revision", json!("different")), ("dimension", json!(768)), ("pooling", json!("mean")), ("normalize", json!(false)), ("query_prefix", json!("query: ")), ("dtype", json!("float16")), ("output", json!("other")), ("ann", json!({"metric":"l2sq","dtype":"i8"})), ("ann", json!({"metric":"cos","dtype":"f32"}))] {
            let mut other = contract.clone(); other[field] = value;
            assert!(semantic_federation::compatible(&[contract.clone(),other]).is_err(), "accepted incompatible {field}");
        }
        let entry = json!({"kind":"subject","namespace":"future:custom/namespace","value":"same"});
        let parts = r.packs.iter().enumerate().map(|(i,p)| (p.id.clone(), json!({"dense_hits":[{"entry":entry,"distance":0.1+i as f64*0.1,"document_id":i,"chunk_id":i,"source_id":"independent-provider","evidence_id":i}],"lexical_hits":[],"trusted_pins":[],"candidates":[]}))).collect::<Vec<_>>();
        let fused = semantic_federation::fuse(&parts, 10).unwrap();
        assert_eq!(fused.len(), 1);
        assert_eq!(fused[0]["source_packs"], json!(["future-one","future-two"]));
        assert_eq!(fused[0]["provenance"].as_array().unwrap().len(), 2);
        assert_eq!(fused[0]["best_distance"], 0.1);
        let mut reversed = parts.clone(); reversed.reverse();
        assert_eq!(fused, semantic_federation::fuse(&reversed, 10).unwrap());
    }
}
