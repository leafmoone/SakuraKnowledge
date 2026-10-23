use usearch::{Index,IndexOptions,MetricKind,ScalarKind};
fn main()->Result<(),Box<dyn std::error::Error>>{
 let a:Vec<_>=std::env::args().collect();if a.len()!=3 && a.len()!=4{return Err("inspect_i8 INDEX ROWS [DIMENSION]".into());}let rows:usize=a[2].parse()?;
 let dimension:usize=if a.len()==4{a[3].parse()?}else{1024};if !matches!(dimension,768|1024){return Err("unsupported index dimension".into());}
 let index=Index::new(&IndexOptions{dimensions:dimension,metric:MetricKind::Cos,quantization:ScalarKind::I8,connectivity:16,expansion_add:256,expansion_search:2048,multi:false})?;
 index.view(&a[1])?;if index.size()!=rows||index.dimensions()!=dimension||index.metric_kind()!=MetricKind::Cos||index.scalar_kind()!=ScalarKind::I8||index.connectivity()!=16{return Err("native index contract".into());}for key in 0..rows{if !index.contains(key as u64){return Err("native index local key coverage".into());}}
 println!("{{\"rows\":{},\"dimension\":{},\"metric\":\"cos\",\"dtype\":\"i8\",\"validation\":\"PASS\"}}",rows,dimension);Ok(())
}
