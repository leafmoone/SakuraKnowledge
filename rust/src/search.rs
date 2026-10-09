//! FTS rank stream with bounded lightweight tie-group selection.
use crate::{Error, Result};
use rusqlite::{params, Connection};
use std::collections::{BTreeMap, HashSet};
use std::time::Instant;

pub const SQL: &str = "SELECT e.id,e.kind,e.namespace,e.value,e.locator,
search_fts.rank AS score,d.id AS document_id,search_fts.rowid AS fts_rowid
FROM search_fts JOIN documents d ON d.id=search_fts.document_id
JOIN entries e ON e.id=search_fts.entry_id WHERE search_fts MATCH ?1
AND e.conflicted=0 AND d.status IN ('generated_from_evidence','source_backed')
AND EXISTS (SELECT 1 FROM entry_evidence v WHERE v.entry_id=e.id AND v.status='source_backed')
AND (?2 IS NULL OR e.kind=?2) AND (?3 IS NULL OR e.namespace=?3)
ORDER BY search_fts.rank LIMIT 10001";

type Key = (String, String, String);
#[derive(Debug)]
pub struct Hit {
    pub id: i64,
    pub key: Key,
    pub locator: Option<String>,
    pub score: f64,
    pub document_id: i64,
    pub fts_rowid: i64,
}

pub struct Selected {
    pub hits: Vec<Hit>,
    pub scanned: usize,
    pub truncated: bool,
}

pub fn select(
    conn: &Connection,
    compiled: &str,
    kind: Option<&str>,
    namespace: Option<&str>,
    seen: HashSet<Key>,
    limit: usize,
    deadline: Instant,
) -> Result<Selected> {
    let original_seen=seen.clone();
    let streamed=select_query(conn,compiled,kind,namespace,seen,limit,deadline,true)?;
    // The historical filtered SQL sorts ties before the10000-row scan cap.
    // On cap exhaustion fall back exactly, rather than changing truncation semantics.
    if streamed.truncated && (kind.is_some() || namespace.is_some()) {
        select_query(conn,compiled,kind,namespace,original_seen,limit,deadline,false)
    } else {Ok(streamed)}
}
#[allow(clippy::too_many_arguments)]
fn select_query(conn:&Connection,compiled:&str,kind:Option<&str>,namespace:Option<&str>,mut seen:HashSet<Key>,limit:usize,deadline:Instant,stream_filtered:bool)->Result<Selected> {
    let mut filtered;
    let sql = if kind.is_some() || namespace.is_some() {
        filtered = SQL
            .replace("search_fts.rank AS score", "bm25(search_fts) AS score")
            .replace(
                "ORDER BY search_fts.rank",
                "ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid",
            ).replace(
                "FROM search_fts JOIN documents d ON d.id=search_fts.document_id\nJOIN entries e ON e.id=search_fts.entry_id",
                "FROM search_fts CROSS JOIN entries e ON e.id=search_fts.entry_id\nCROSS JOIN documents d ON d.id=search_fts.document_id");
        if stream_filtered {
            filtered=filtered.replace("bm25(search_fts) AS score","search_fts.rank AS score")
                .replace("WHERE search_fts MATCH ?1","WHERE search_fts MATCH ?1 AND rank MATCH 'bm25()'")
                .replace("ORDER BY score,e.kind,e.namespace,e.value,search_fts.rowid","ORDER BY search_fts.rank");
        }
        filtered.as_str()
    } else {
        SQL
    };
    let mut stmt = conn.prepare(sql)?;
    let mut rows = stmt.query(params![compiled, kind, namespace])?;
    let mut chosen = Vec::new();
    let mut group: BTreeMap<Key, Hit> = BTreeMap::new();
    let mut score: Option<f64> = None;
    let mut scanned = 0;
    let mut truncated = false;
    while let Some(row) = rows.next()? {
        if Instant::now() > deadline {
            return Err(Error::Budget);
        }
        scanned += 1;
        if scanned > 10000 {
            truncated = true;
            break;
        }
        let hit = Hit {
            id: row.get(0)?,
            key: (row.get(1)?, row.get(2)?, row.get(3)?),
            locator: row.get(4)?,
            score: row.get(5)?,
            document_id: row.get(6)?,
            fts_rowid: row.get(7)?,
        };
        if score.is_some_and(|s| s != hit.score) {
            for (key, value) in std::mem::take(&mut group) {
                seen.insert(key);
                chosen.push(value);
            }
            if chosen.len() >= limit {
                break;
            }
        }
        score = Some(hit.score);
        if seen.contains(&hit.key) {
            continue;
        }
        if !group.contains_key(&hit.key) || hit.fts_rowid < group[&hit.key].fts_rowid {
            group.insert(hit.key.clone(), hit);
        }
        if group.len() > limit - chosen.len() {
            group.pop_last();
        }
    }
    if chosen.len() < limit {
        chosen.extend(group.into_values());
    }
    chosen.truncate(limit);
    Ok(Selected {
        hits: chosen,
        scanned,
        truncated,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn filtered_rank_stream_matches_original_and_preserves_scan_cap() {
        let c=Connection::open_in_memory().unwrap();
        c.execute_batch("CREATE TABLE entries(id INTEGER PRIMARY KEY,kind TEXT,namespace TEXT,value TEXT,locator TEXT,conflicted INTEGER); CREATE TABLE documents(id INTEGER PRIMARY KEY,status TEXT); CREATE TABLE entry_evidence(entry_id INTEGER,status TEXT); CREATE VIRTUAL TABLE search_fts USING fts5(text,document_id UNINDEXED,entry_id UNINDEXED); INSERT INTO entries VALUES(1,'character','test','z',NULL,0),(2,'character','test','a',NULL,0),(3,'character','other','exclude',NULL,0); INSERT INTO entry_evidence VALUES(1,'source_backed'),(2,'source_backed'),(3,'source_backed');").unwrap();
        for id in 1..=300 {
            c.execute("INSERT INTO documents VALUES(?,'source_backed')",[id]).unwrap();
            c.execute("INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,'alpha',?,?)",params![id*3,id,if id%2==0 {1}else{2}]).unwrap();
        }
        let compare=|left:Selected,right:Selected| {
            let tuples=|s:&Selected|s.hits.iter().map(|h|(h.id,h.key.clone(),h.score,h.document_id,h.fts_rowid)).collect::<Vec<_>>();
            assert_eq!(tuples(&left),tuples(&right));assert_eq!(left.truncated,right.truncated);
        };
        let deadline=Instant::now()+std::time::Duration::from_secs(5);
        compare(select(&c,"\"alpha\"",Some("character"),Some("test"),HashSet::new(),10,deadline).unwrap(),select_query(&c,"\"alpha\"",Some("character"),Some("test"),HashSet::new(),10,deadline,false).unwrap());
        // SQL type-ties sort 'a' before 'z' but rowid stream does not. At10000
        // repeated-document cap, the exact original query must govern candidates.
        for id in 301..=10400 {
            c.execute("INSERT INTO documents VALUES(?,'source_backed')",[id]).unwrap();
            c.execute("INSERT INTO search_fts(rowid,text,document_id,entry_id) VALUES(?,'alpha',?,2)",params![id*3,id]).unwrap();
        }
        let deadline=Instant::now()+std::time::Duration::from_secs(5);
        let original=select_query(&c,"\"alpha\"",Some("character"),Some("test"),HashSet::new(),10,deadline,false).unwrap();
        assert!(original.truncated);assert_eq!(original.hits.len(),1);
        let naive=select_query(&c,"\"alpha\"",Some("character"),Some("test"),HashSet::new(),10,deadline,true).unwrap();
        assert!(naive.truncated);assert_eq!(naive.hits.len(),2);
        compare(select(&c,"\"alpha\"",Some("character"),Some("test"),HashSet::new(),10,deadline).unwrap(),original);
    }
}
