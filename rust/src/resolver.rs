//! P3-only offline resolver. P2 lookup/ask policy stays unchanged.
use crate::{Error, Result, Runtime, ID_STATUSES};
use rusqlite::{params, OptionalExtension};
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub struct TagOptions<'a> {
    pub target_namespace: Option<&'a str>,
    pub category: Option<i64>,
    pub kind: Option<&'a str>,
    pub namespace: Option<&'a str>,
    pub key: bool,
    pub limit: u32,
}

impl Default for TagOptions<'_> {
    fn default() -> Self {
        Self {
            target_namespace: None,
            category: None,
            kind: None,
            namespace: None,
            key: false,
            limit: 20,
        }
    }
}

struct Assessment {
    name: String,
    target: Option<i64>,
    value: Option<String>,
    matched: String,
    canonical: String,
    payload: Value,
}

fn tag_key(value: &str) -> Value {
    json!({"kind":"tag","namespace":"danbooru.tag","value":value})
}

impl Runtime {
    /// Explicit incoming direction over the original native/verified edge.
    pub fn related_in(
        &mut self,
        kind: &str,
        namespace: &str,
        value: &str,
        relation: Option<&str>,
        kind_filter: Option<&str>,
        limit: u32,
    ) -> Result<Value> {
        self.operation(|runtime| {
            if !(1..=100).contains(&limit) { return Err(Error::Invalid("limit must be 1..100".into())); }
            let columns:Vec<String> = runtime.conn.prepare("SELECT name FROM pragma_index_info('link_dst') ORDER BY seqno")?
                .query_map([],|r|r.get(0))?.collect::<std::result::Result<_,_>>()?;
            if columns != ["dst","relation","verification_status"] {
                return Err(Error::Invalid("p3_inverse_capability_absent".into()));
            }
            let mut result=runtime.lookup_key(kind,namespace,value)?;
            result["direction"]=json!("in");
            if result["status"]!=json!("found") { return Ok(result); }
            let sql=format!("SELECT s.kind,s.namespace,s.value,l.relation,l.method,l.verification_status,l.source_id,l.evidence_id,l.payload \
                FROM links l JOIN entries d ON d.id=l.dst JOIN entries s ON s.id=l.src \
                WHERE d.kind=?1 AND d.namespace=?2 AND d.value=?3 \
                AND l.verification_status IN ('native','verified') AND s.conflicted=0 \
                AND EXISTS(SELECT 1 FROM entry_evidence p WHERE p.entry_id=s.id AND p.status IN ({ID_STATUSES})) \
                AND (?4 IS NULL OR l.relation=?4) AND (?5 IS NULL OR s.kind=?5) \
                ORDER BY l.relation,s.kind,s.namespace,s.value,l.id LIMIT ?6");
            let mut stmt=runtime.conn.prepare(&sql)?;
            let rows=stmt.query_map(params![kind,namespace,value,relation,kind_filter,limit],|r|Ok(json!({
                "src":{"kind":r.get::<_,String>(0)?,"namespace":r.get::<_,String>(1)?,"value":r.get::<_,String>(2)?},
                "dst":{"kind":kind,"namespace":namespace,"value":value},"relation":r.get::<_,String>(3)?,
                "method":r.get::<_,String>(4)?,"verification_status":r.get::<_,String>(5)?,
                "source_id":r.get::<_,String>(6)?,"evidence_id":r.get::<_,String>(7)?,"payload":r.get::<_,String>(8)?
            })))?;
            let mut relations=Vec::new();
            for row in rows { runtime.check_deadline()?; relations.push(row?); }
            result["relations"]=json!(relations);
            Ok(result)
        })
    }

    pub fn resolve_tag(&mut self, query: &str, options: TagOptions<'_>) -> Result<Value> {
        self.operation(|runtime| runtime.resolve_tag_inner(query, &options))
    }

    fn assessments(&self, name: &str, category: Option<i64>) -> Result<Vec<Assessment>> {
        self.assessments_filtered(name, category, false)
    }

    fn native_assessments(&self, name: &str, category: Option<i64>) -> Result<Vec<Assessment>> {
        self.assessments_filtered(name, category, true)
    }

    fn assessments_filtered(
        &self,
        name: &str,
        category: Option<i64>,
        native_only: bool,
    ) -> Result<Vec<Assessment>> {
        let mut stmt = self.conn.prepare(&format!(
            "SELECT r.target,e.value,r.matched_by,r.canonical_status,r.payload \
             FROM tag_resolutions r LEFT JOIN entries e ON e.id=r.target \
             WHERE r.name=?1 AND (?2 IS NULL OR r.category=?2) AND (?3=0 OR r.matched_by IN ('native_exact','official_alias')) \
             AND (r.target IS NULL OR (e.kind='tag' AND e.namespace='danbooru.tag' \
             AND e.conflicted=0 AND EXISTS(SELECT 1 FROM entry_evidence p \
             WHERE p.entry_id=e.id AND p.status IN ({ID_STATUSES})))) \
             ORDER BY CASE r.matched_by WHEN 'native_exact' THEN 0 WHEN 'official_alias' THEN 1 ELSE 2 END,e.value,r.id"
        ))?;
        let rows = stmt.query_map(params![name, category, native_only as i32], |r| {
            Ok((
                r.get::<_, Option<i64>>(0)?,
                r.get::<_, Option<String>>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
            ))
        })?;
        let mut out = Vec::new();
        for row in rows {
            self.check_deadline()?;
            let (target, value, matched, canonical, text) = row?;
            let payload: Value = serde_json::from_str(&text)
                .map_err(|_| Error::Invalid("invalid P3 projection JSON".into()))?;
            if !payload.get("evidence_chain").is_some_and(Value::is_array) {
                return Err(Error::Invalid("invalid P3 proof chain".into()));
            }
            out.push(Assessment {
                name: name.to_string(),
                target,
                value,
                matched,
                canonical,
                payload,
            });
        }
        Ok(out)
    }

    fn apply_assessments(
        &self,
        out: &mut Value,
        assessments: Vec<Assessment>,
        limit: usize,
    ) -> Result<()> {
        if assessments.is_empty() {
            return Ok(());
        }
        // Unknown evidence never disappears merely because another spelling proof
        // happens to resolve. It prevents claiming unique canonical identity.
        if assessments
            .iter()
            .any(|a| a.canonical != "canonical" || a.target.is_none())
        {
            out["status"] = json!("canonical_unknown");
            out["warnings"] = json!(["canonical_evidence_incomplete"]);
            let mut chain = Vec::new();
            for a in &assessments {
                if let Some(refs) = a.payload["evidence_chain"].as_array() {
                    chain.extend(refs.clone());
                }
            }
            out["evidence_chain"] = json!(chain);
            out["unresolved_reasons"] = json!(assessments.iter()
                .filter(|a|a.canonical!="canonical" || a.target.is_none())
                .map(|a|json!({"name":a.name,"matched_by":a.matched,"reason":a.payload.get("reason").and_then(Value::as_str).unwrap_or("canonical_evidence_incomplete")})).collect::<Vec<_>>());
            return Ok(());
        }
        let mut unique = BTreeMap::<String, Assessment>::new();
        for assessment in assessments {
            self.check_deadline()?;
            let value = assessment
                .value
                .clone()
                .ok_or_else(|| Error::Invalid("missing native identity".into()))?;
            if let Some(existing) = unique.get_mut(&value) {
                for reference in assessment.payload["evidence_chain"].as_array().unwrap() {
                    if !existing.payload["evidence_chain"]
                        .as_array()
                        .unwrap()
                        .contains(reference)
                    {
                        existing.payload["evidence_chain"]
                            .as_array_mut()
                            .unwrap()
                            .push(reference.clone());
                    }
                }
            } else {
                unique.insert(value, assessment);
            }
        }
        if unique.len() > 1 {
            out["status"] = json!("tag_ambiguous");
            out["candidates_truncated"] = json!(unique.len() > limit);
            out["candidates"] = json!(unique
                .keys()
                .take(limit)
                .map(|name| json!({"tag_key":tag_key(name)}))
                .collect::<Vec<_>>());
            return Ok(());
        }
        let (name, a) = unique.into_iter().next().unwrap();
        out["status"] = json!("resolved");
        out["tag_key"] = tag_key(&name);
        out["matched_by"] = json!(a.matched);
        out["canonical_status"] = json!("canonical");
        out["evidence_chain"] = a.payload["evidence_chain"].clone();
        // Description uses the actual indexed native Wiki edge, never a wiki_key
        // or a fresh spelling resolution. Both cuts must have bound compatibility.
        let mut stmt=self.conn.prepare("SELECT w.id,w.value,l.source_id,l.evidence_id,l.payload FROM links l JOIN entries w ON w.id=l.src WHERE l.dst=?1 AND l.relation='wiki_tag' AND l.verification_status IN ('native','verified') AND w.kind='page' AND w.namespace='danbooru.wiki' AND w.conflicted=0 ORDER BY w.value,l.id")?;
        let rows = stmt.query_map([a.target], |r| {
            Ok((
                r.get::<_, i64>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
            ))
        })?;
        for row in rows {
            self.check_deadline()?;
            let (wiki_id, wiki_value, sid, eid, text) = row?;
            let link: Value = serde_json::from_str(&text)
                .map_err(|_| Error::Invalid("invalid Wiki association proof".into()))?;
            let Some(refs) = link["evidence_refs"].as_array() else {
                continue;
            };
            let wk = json!({"kind":"page","namespace":"danbooru.wiki","value":wiki_value});
            let native = tag_key(&name);
            if !refs.iter().any(|p| {
                p["role"] == "wiki_tag_link" && p["wiki_key"] == wk && p["tag_key"] == native
            }) || !refs.iter().any(|p| {
                p["role"] == "wiki_cut_compatibility"
                    && p["wiki_key"] == wk
                    && p["tag_key"] == native
                    && p["old_updated_at"].as_str().is_some_and(|v| !v.is_empty())
                    && p["old_updated_at"] == p["live_updated_at"]
                    && [
                        "old_source_id",
                        "old_input_sha256",
                        "raw_sha256",
                        "source_id",
                        "evidence_id",
                        "body_sha256",
                        "old_other_names_sha256",
                    ]
                    .iter()
                    .all(|k| p[*k].as_str().is_some_and(|v| !v.is_empty()))
                    && p["old_line"].as_i64().is_some_and(|v| v > 0)
                    && p["body_sha256"] == p["old_body_sha256"]
                    && p["body_sha256"] == p["live_body_sha256"]
                    && p["old_other_names_sha256"] == p["live_other_names_sha256"]
            }) {
                continue;
            }
            let docs = self.fetch_docs(wiki_id)?;
            if docs.is_empty() {
                continue;
            }
            let chain = out["evidence_chain"].as_array_mut().unwrap();
            for reference in refs {
                if !chain.contains(reference) {
                    chain.push(reference.clone());
                }
            }
            chain.push(json!({"role":"wiki_association_edge","source_id":sid,"evidence_id":eid,"src":wk,"dst":native}));
            for doc in &docs {
                chain.push(json!({"role":"description","source_id":doc["source_id"],"evidence_id":doc["evidence_id"],"wiki_key":wk,"tag_key":native}));
            }
            out["descriptions"] = json!(docs);
            break;
        }
        Ok(())
    }

    fn resolve_tag_inner(&mut self, query: &str, opt: &TagOptions<'_>) -> Result<Value> {
        crate::tokens(query)?; // exactly P2 validated Unicode/query bounds
        let namespace = opt.target_namespace.unwrap_or("danbooru.tag");
        if namespace != "danbooru.tag" {
            return Err(Error::Invalid("unsupported target namespace".into()));
        }
        if !(1..=100).contains(&opt.limit) {
            return Err(Error::Invalid("limit must be 1..100".into()));
        }
        if opt.category.is_some_and(|c| ![0, 1, 3, 4, 5].contains(&c)) {
            return Err(Error::Invalid("invalid native category".into()));
        }
        if opt.key && (opt.kind.is_none() || opt.namespace.is_none()) {
            return Err(Error::Invalid(
                "source key requires kind and namespace".into(),
            ));
        }
        if opt.key {
            crate::validate_key(opt.kind.unwrap(), opt.namespace.unwrap(), query)?;
        }
        let sources: Vec<String> = self
            .conn
            .prepare("SELECT source_id FROM sources ORDER BY source_id")?
            .query_map([], |r| r.get(0))?
            .collect::<std::result::Result<_, _>>()?;
        let mut out = json!({"contract_version":"2","response_version":"3","resolver_contract_version":"1",
            "snapshot":self.snapshot,"query":query,"requested_namespace":namespace,"requested_category":opt.category,
            "source_key":null,"status":"not_found","tag_key":null,"matched_by":null,"canonical_status":"unknown",
            "evidence_chain":[],"descriptions":[],"citations":[],"candidates":[],"candidates_truncated":false,
            "source_scope":sources,"warnings":[],"relations":[],"unresolved_reasons":[]});
        let capability: Option<String> = self
            .conn
            .query_row(
                "SELECT value FROM build_meta WHERE key='p3_resolver_version'",
                [],
                |r| r.get(0),
            )
            .optional()?;
        if capability.as_deref() != Some("1") {
            out["status"] = json!("unsupported");
            out["warnings"] = json!(["p3_resolver_capability_absent"]);
            return Ok(out);
        }
        let constrained = opt.key || opt.kind.is_some() || opt.namespace.is_some();
        if !constrained {
            // Priority is determined before category filtering. A category cannot
            // cause a native spelling to be reinterpreted as somebody's Wiki name.
            let native = self.native_assessments(query, None)?;
            let direct = if native.is_empty() {
                self.assessments(query, opt.category)?
            } else {
                self.native_assessments(query, opt.category)?
            };
            if !direct.is_empty() {
                self.apply_assessments(&mut out, direct, opt.limit as usize)?;
                return Ok(out);
            }
            if opt.category.is_some() && !self.assessments(query, None)?.is_empty() {
                return Ok(out); // native/alias/Wiki category constraint cannot fall back
            }
        }
        // Classification is independent of display LIMIT: all source identities
        // are collected under the same deadline, with stable typed-key ordering.
        let mut stmt = self.conn.prepare(&format!(
            "SELECT DISTINCT e.id,e.kind,e.namespace,e.value FROM entries e \
             LEFT JOIN aliases a ON a.entry_id=e.id AND a.status IN ({ID_STATUSES}) \
             WHERE (e.value=?1 OR (?2=0 AND a.text=?1)) AND (?3 IS NULL OR e.kind=?3) \
             AND (?4 IS NULL OR e.namespace=?4) AND e.conflicted=0 \
             AND EXISTS(SELECT 1 FROM entry_evidence p WHERE p.entry_id=e.id AND p.status IN ({ID_STATUSES})) \
             ORDER BY e.kind,e.namespace,e.value"
        ))?;
        let rows = stmt.query_map(
            params![query, opt.key as i32, opt.kind, opt.namespace],
            |r| {
                Ok((
                    r.get::<_, i64>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                ))
            },
        )?;
        let mut entities = Vec::new();
        for row in rows {
            self.check_deadline()?;
            entities.push(row?);
        }
        if entities.is_empty() {
            return Ok(out);
        }
        if entities.len() > 1 {
            out["status"] = json!("entity_ambiguous");
            out["candidates_truncated"] = json!(entities.len() > opt.limit as usize);
            out["candidates"] = json!(entities
                .iter()
                .take(opt.limit as usize)
                .map(|(_, k, n, v)| json!({"entry_key":{"kind":k,"namespace":n,"value":v}}))
                .collect::<Vec<_>>());
            return Ok(out);
        }
        let (id, kind, ns, value) = &entities[0];
        out["source_key"] = json!({"kind":kind,"namespace":ns,"value":value});
        out["status"] = json!("entity_found_tag_unmapped");
        if kind == "tag" && ns == "danbooru.tag" {
            if opt.category.is_some() && self.native_assessments(value, opt.category)?.is_empty() {
                out["status"] = json!("not_found");
                return Ok(out);
            }
            self.apply_assessments(
                &mut out,
                self.native_assessments(value, opt.category)?,
                opt.limit as usize,
            )?;
            return Ok(out);
        }
        let mut stmt = self.conn.prepare(
            "SELECT e.value,l.source_id,l.evidence_id,l.payload FROM links l JOIN entries e ON e.id=l.dst \
             WHERE l.src=?1 AND l.relation='entity_tag' AND l.verification_status='verified' \
             AND e.kind='tag' AND e.namespace='danbooru.tag' AND e.conflicted=0 ORDER BY e.value,l.id"
        )?;
        let rows = stmt.query_map([id], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
            ))
        })?;
        let mut targets = Vec::new();
        for row in rows {
            self.check_deadline()?;
            let (name, sid, eid, payload) = row?;
            for mut a in self.native_assessments(&name, opt.category)? {
                let link: Value = serde_json::from_str(&payload)
                    .map_err(|_| Error::Invalid("invalid mapping proof JSON".into()))?;
                a.payload["evidence_chain"].as_array_mut().unwrap().push(
                    json!({"role":"entity_tag","source_id":sid,"evidence_id":eid,"link":link}),
                );
                a.matched = "entity_tag".into();
                targets.push(a);
            }
        }
        self.apply_assessments(&mut out, targets, opt.limit as usize)?;
        Ok(out)
    }
}
