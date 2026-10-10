//! Repository-independent optional source pack discovery and typed-key federation.
#[cfg(feature="semantic")]
#[path="semantic_federation.rs"]
mod semantic_federation;
use crate::{Runtime,TagOptions};
use serde_json::{json,Value};
use std::path::{Path,PathBuf};
use std::collections::{BTreeMap,BTreeSet};
pub type Result<T> = std::result::Result<T,Box<dyn std::error::Error>>;
fn diagnostic_trace(enabled:bool,phase:&str,pack:Option<&str>,start:std::time::Instant) {
 if enabled {eprintln!("{}",json!({"event":"retrieval_stage","phase":phase,"source_pack":pack,"elapsed_ms":start.elapsed().as_secs_f64()*1000.0}));}
}
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
 pub fn selected(&self,sources:&[String])->Result<Vec<&SourcePack>> {
  if sources.is_empty(){return Ok(self.packs.iter().collect());}
  let mut wanted=BTreeSet::new();
  for value in sources {for id in value.split(',') {
   if id.is_empty()||id.len()>128||matches!(id,"."|"..")||!id.bytes().all(|b|b.is_ascii_alphanumeric()||b"-_.".contains(&b)) {return Err(crate::modular_cli::UsageError("invalid source pack ID".into()).into());}
   wanted.insert(id);
  }}
  for s in &wanted {if !self.packs.iter().any(|p|p.id==*s){return Err(format!("source_pack_missing: {s}").into());}}
  Ok(self.packs.iter().filter(|p|wanted.contains(p.id.as_str())).collect())
 }
 pub fn list(&self)->Value {let installed:Vec<_>=self.packs.iter().map(|p|json!({"pack_id":p.id,"version":p.manifest["version"],"capabilities":p.manifest["capabilities"],"requires_model":p.manifest["requires_model"],"lexical_mode":p.manifest.get("lexical_mode").cloned().unwrap_or(json!("trusted_documents_and_identity")),"trusted_fts_documents":p.manifest["trusted_fts_documents"],"model_present":self.model_directory.join("bge-m3/manifest.json").is_file(),"status":if p.manifest["version"].is_string() && p.root.join("knowledge.sqlite").is_file(){"installed"}else{"invalid"}})).collect();let missing:Vec<String>=Vec::new();json!({"installed_packs":installed,"not_installed":missing,"model":{"id":"bge-m3","installed":self.model_directory.join("bge-m3/manifest.json").is_file()}})}
 pub fn structured(&self,command:&str,query:&str,args:&[String],sources:&[String])->Result<Value>{
  let mut forwarded=Vec::new();
  if command!="inspect" {forwarded.push(query.to_owned());}
  forwarded.extend_from_slice(args);
  for source in sources {forwarded.extend(["--source".to_owned(),source.clone()]);}
  self.structured_parsed(&crate::modular_cli::parse(command,&forwarded)?)
 }
 pub fn structured_parsed(&self,options:&crate::modular_cli::ParsedCommand)->Result<Value>{
  let command=options.command.as_str();let query=options.positionals.first().map(String::as_str).unwrap_or("");
  let selected=self.selected(&options.sources)?;let start=std::time::Instant::now();let mut parts=Vec::new();
  let kind=options.kind.as_deref();let ns=options.namespace.as_deref();let limit=options.limit;
  for pack in selected {if start.elapsed().as_secs_f64()>5.0{return Err("operation deadline exceeded".into());}let mut runtime=Runtime::open(pack.root.join("knowledge.sqlite"))?;runtime.set_deadline(start+std::time::Duration::from_secs(5));let value=match command {
   "lookup"=>if options.key{runtime.lookup_key(kind.ok_or("--kind required")?,ns.ok_or("--namespace required")?,query)?}else{runtime.lookup(query,kind,ns)?},
   "search"=>runtime.search(query,100,kind,ns)?,"ask"=>runtime.ask(query,kind,ns,options.target_namespace.as_deref())?,
   "related"=>{
    let (src_kind,src_ns,value,filter)=if options.positionals.len()==3{(options.positionals[0].as_str(),options.positionals[1].as_str(),options.positionals[2].as_str(),kind.or(options.filter.as_deref()))}else{(kind.ok_or("--kind required")?,ns.ok_or("--namespace required")?,query,options.filter.as_deref())};
    if options.direction=="in"{runtime.related_in(src_kind,src_ns,value,options.relation.as_deref(),filter,limit)?}else{runtime.related(src_kind,src_ns,value,options.relation.as_deref(),filter,limit)?}
   },
   "resolve-tag"=>runtime.resolve_tag(query,TagOptions{kind,namespace:ns,target_namespace:options.target_namespace.as_deref(),category:options.category,key:options.key,limit})?,
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
 pub fn query_encodings(&self)->usize {self.encoder.as_ref().map_or(0,|encoder|encoder.borrow().query_encodings)}
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
  let diagnostic=std::env::var_os("SKNOW_DIAGNOSTICS").is_some();
  diagnostic_trace(diagnostic,"encoding_begin",None,start);
  let vector=if selected.iter().any(|p|p.manifest["requires_model"]=="bge-m3"){Some(self.encoder.as_ref().ok_or("semantic_model_missing: bge-m3")?.borrow_mut().encode(query)?)}else{None};
  diagnostic_trace(diagnostic,"encoding_end",None,start);
  let multi=selected.iter().filter(|p|p.manifest["requires_model"]=="bge-m3").count()>1;
  for pack in selected {diagnostic_trace(diagnostic,"pack_begin",Some(&pack.id),start);let response=if pack.manifest["requires_model"]=="bge-m3"{let h=self.handles.get_mut(&pack.id).ok_or("semantic pack not opened")?;if multi {h.retrieve_branches_encoded(query,&branch_options,vector.as_ref().unwrap())?}else{h.retrieve_deferred_encoded(query,&branch_options,vector.as_ref().unwrap())?}}else{crate::semantic::lexical_retrieve_deferred(&pack.root.join("knowledge.sqlite"),query,&branch_options,start+std::time::Duration::from_secs(5))?};diagnostic_trace(diagnostic,"pack_end",Some(&pack.id),start);parts.push((pack.id.clone(),response));}
  let semantic:Vec<_>=parts.iter().filter(|(id,_)|self.handles.contains_key(id)).map(|p|p.0.clone()).collect();
  let mut value=if multi {
   let mut candidates=semantic_federation::fuse(&parts,100)?;
   candidates.retain(|c|options.kind.as_ref().is_none_or(|k|c["entry"]["kind"]==*k)&&options.namespace.as_ref().is_none_or(|n|c["entry"]["namespace"]==*n));candidates.truncate(options.limit);
   let mut proofs=Vec::new();
   for (id,part) in &parts {if let Some(h)=self.handles.get_mut(id) {
    let local:Vec<_>=candidates.iter().filter(|c|c["source_packs"].as_array().unwrap().contains(&json!(id))).map(|c|{let mut c=c.clone();for f in ["provenance","trusted_pins"] {c[f]=json!(c[f].as_array().unwrap().iter().filter(|p|p["source_pack"]==*id).cloned().collect::<Vec<_>>());}c}).collect();
    diagnostic_trace(diagnostic,"materialize_begin",Some(id),start);
    proofs.push((id.clone(),h.materialize_candidates(query,options,&local,part["trusted_pins"].as_array().ok_or("invalid pins")?,start+std::time::Duration::from_secs(5))?));
    diagnostic_trace(diagnostic,"materialize_end",Some(id),start);
   }}
   let mut v=json!({"candidates":candidates,"documents":[],"sources":[],"evidence":[],"citations":[],"trusted_pins":[],"dense_hits":[],"lexical_hits":[],"warnings":[],"contract_version":"2","response_version":"sakura-global-distance-v1","query":query,"installed_packs":self.runtime.packs.iter().map(|p|p.id.clone()).collect::<Vec<_>>(),"participating_packs":parts.iter().map(|p|p.0.clone()).collect::<Vec<_>>(),"fusion_policy":"global_cosine_dense_once_plus_source_lexical_rrf60"});
   for (id,p) in &parts {if !self.handles.contains_key(id) {proofs.push((id.clone(),p.clone()));}}
   for f in ["documents","sources","evidence","citations"] {for (id,p) in &proofs {for r in p[f].as_array().unwrap(){let r=crate::semantic::qualify_public_record(r,id);if !v[f].as_array().unwrap().contains(&r){v[f].as_array_mut().unwrap().push(r);}}}}
   for (id,p) in &parts {for pin in p["trusted_pins"].as_array().into_iter().flatten(){let pin=crate::semantic::qualify_public_record(pin,id);v["trusted_pins"].as_array_mut().unwrap().push(pin);}}
   let pinned:BTreeSet<_>=v["trusted_pins"].as_array().unwrap().iter().filter_map(key).collect();if pinned.len()>1 {v["warnings"]=json!(["multiple_trusted_identities_preserved_not_resolved"]);}
   v
  }else{merge("retrieve",query,parts.clone(),self.runtime.packs.iter().map(|p|p.id.clone()).collect(),100)};
  diagnostic_trace(diagnostic,"merge_end",None,start);
  let pins:BTreeSet<_>=parts.iter().flat_map(|p|p.1["trusted_pins"].as_array().into_iter().flatten()).filter_map(key).collect();
  if let Some(candidates)=value["candidates"].as_array_mut(){candidates.sort_by_key(|c|usize::from(!key(c).is_some_and(|k|pins.contains(&k))));candidates.truncate(options.limit);for (i,c) in candidates.iter_mut().enumerate(){c["hybrid_rank"]=json!(i+1);c["source_pack"]=c["source_packs"].clone();}}
  crate::semantic::close_public_evidence(&mut value);
  let deadline=start+std::time::Duration::from_secs(5);
  for (id,_) in &parts {
   if let Some(handle)=self.handles.get(id) {
    if !multi {handle.hydrate_documents(&mut value,id,deadline)?;}
   } else {
    let pack=self.runtime.packs.iter().find(|p|p.id==*id).ok_or("source pack missing during hydration")?;
    crate::semantic::hydrate_lexical_documents(&pack.root.join("knowledge.sqlite"),&mut value,id,deadline)?;
   }
  }
  value["hybrid"]=value["candidates"].clone();
  value["actual_tokens"]=json!(0);
  value["status"]=json!("PASS");value["identity_status"]=json!("not_asserted");value["promoted_identities"]=json!([]);value["canonical"]=Value::Null;value["entity_tag"]=Value::Null;
  value["semantic_capable_packs"]=json!(semantic);value["pack_timings_ms"]=json!(parts.iter().map(|p|json!({"source_pack":p.0,"timings_ms":p.1["timings_ms"]})).collect::<Vec<_>>());value["timings_ms"]=json!({"total":start.elapsed().as_secs_f64()*1000.,"query_encodings":self.encoder.as_ref().map_or(0,|e|e.borrow().query_encodings)-before,"embedding_cache_hit":vector.is_some() && self.encoder.as_ref().is_some_and(|e|e.borrow().query_encodings==before),"process_embedding_cache_hits":self.encoder.as_ref().map_or(0,|e|e.borrow().cache_hits),"process_query_encodings":self.encoder.as_ref().map_or(0,|e|e.borrow().query_encodings)});if start.elapsed().as_secs_f64()>5.0{return Err("query_budget_exceeded".into());}Ok(value)
 }
}

pub fn merge(command:&str,_query:&str,parts:Vec<(String,Value)>,installed:Vec<String>,limit:usize)->Value{
 let participating:Vec<_>=parts.iter().map(|p|p.0.clone()).collect();let mut result=parts.first().map(|p|p.1.clone()).unwrap_or_else(||json!({"status":"unknown","candidates":[],"relations":[]}));
 result["installed_packs"]=json!(installed);result["participating_packs"]=json!(participating);
 for field in ["candidates","relations","descriptions","evidence_chain","citations","documents","sources","evidence","trusted_pins","dense_hits","lexical_hits","hybrid"] {
  let mut rows:BTreeMap<String,(Value,f64)>=BTreeMap::new();
  for (id,value) in &parts {if let Some(items)=value[field].as_array(){for (rank,item) in items.iter().enumerate(){let mut qualified=item.clone();if command=="retrieve"&&["candidates","trusted_pins","documents","sources","evidence","citations"].contains(&field){#[cfg(feature="semantic")] {qualified=crate::semantic::qualify_public_record(item,id);}}let item=&qualified;let identity=if ["candidates","hybrid"].contains(&field)||(field=="trusted_pins"&&command!="retrieve"){key(item).unwrap_or_else(||item.to_string())}else if command=="retrieve"&&field=="documents"{format!("{id}\0{}",item["document_id"])}else if command=="retrieve"&&["trusted_pins","sources","evidence","citations"].contains(&field){format!("{id}\0{item}")}else{item.to_string()};let record=rows.entry(identity).or_insert_with(||{let mut v=item.clone();v["source_packs"]=json!([]);(v,0.)});record.1+=1./(60.+(rank+1) as f64);if field=="candidates" {let nested_fields:&[&str]=if command=="retrieve"{&["citations","descriptions","evidence_ids","source_ids","matched_documents","identity_evidence","aliases","source_fields_evidence","trusted_pins"]}else{&["citations","descriptions","evidence_ids","source_ids","matched_documents"]};for &nested in nested_fields {if let Some(other)=item[nested].as_array(){if record.0[nested].is_null(){record.0[nested]=json!([]);}if let Some(target)=record.0[nested].as_array_mut(){for value in other {if !target.contains(value){target.push(value.clone());}}}}}}let ids=record.0["source_packs"].as_array_mut().unwrap();if !ids.contains(&json!(id)){ids.push(json!(id));}}}}
  let mut rows:Vec<_>=rows.into_iter().collect();rows.sort_by(|a,b|{let priority=|v:&Value|if v["matched_by"]=="exact"{0}else if v["matched_by"]=="alias"{1}else{2};if field=="candidates"&&command=="search"{priority(&a.1.0).cmp(&priority(&b.1.0)).then_with(||b.1.1.total_cmp(&a.1.1)).then_with(||a.0.cmp(&b.0))}else{b.1.1.total_cmp(&a.1.1).then_with(||a.0.cmp(&b.0))}});
  let values:Vec<_>=rows.into_iter().take(if field=="candidates"&&["search","retrieve"].contains(&command){limit}else if command=="retrieve"&&["trusted_pins","documents","sources","evidence","citations"].contains(&field){usize::MAX}else{100}).map(|(_,r)|r.0).collect();if !values.is_empty()||result.get(field).is_some(){result[field]=json!(values);}
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
 #[cfg(feature="semantic")]
 if command=="retrieve" {crate::semantic::close_public_evidence(&mut result);}
 result
}
