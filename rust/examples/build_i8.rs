//! Explicit create-new I8 ANN from frozen FP32 NPY rows; no encoding.
use std::fs::{File,OpenOptions};
use std::io::{Read,Seek};
use usearch::{Index,IndexOptions,MetricKind,ScalarKind};
fn options(dimensions:usize)->IndexOptions { IndexOptions { dimensions,metric:MetricKind::Cos,quantization:ScalarKind::I8,connectivity:16,expansion_add:256,expansion_search:2048,..Default::default() } }
fn main()->Result<(),Box<dyn std::error::Error>> {
 let args:Vec<String>=std::env::args().collect();
 if args.len()!=3 && args.len()!=4 {return Err("build_i8 VECTORS.npy NEW_INDEX [POSITIONS.u64le]".into());}
 let mut file=File::open(&args[1])?;let mut prefix=[0;8];file.read_exact(&mut prefix)?;
 if &prefix[..6]!=b"\x93NUMPY" {return Err("NPY magic".into());}
 let len=match prefix[6] {1=>{let mut b=[0;2];file.read_exact(&mut b)?;u16::from_le_bytes(b) as usize},2=>{let mut b=[0;4];file.read_exact(&mut b)?;u32::from_le_bytes(b) as usize},_=>return Err("NPY version".into())};
 let mut header=vec![0;len];file.read_exact(&mut header)?;let text=std::str::from_utf8(&header)?;
 if !text.contains("'<f4'") || !text.contains("False") {return Err("NPY dtype/order".into());}
 let shape=text.split("'shape':").nth(1).ok_or("NPY shape")?.split('(').nth(1).ok_or("NPY shape")?.split(')').next().ok_or("NPY shape")?;
 let dims:Vec<usize>=shape.split(',').filter(|s|!s.trim().is_empty()).map(|s|s.trim().parse()).collect::<Result<_,_>>()?;
 if dims.len()!=2||dims[0]==0||!matches!(dims[1],768|1024){return Err("NPY shape".into());}let original_rows=dims[0] as u64;let dimension=dims[1];let width=(dimension*4) as u64;
 let offset=file.stream_position()?;
 if file.metadata()?.len()!=offset+original_rows*width {return Err("NPY length".into());}
 let positions:Vec<u64>=if args.len()==4 {let bytes=std::fs::read(&args[3])?;if bytes.len()%8!=0{return Err("position bytes".into());}bytes.chunks_exact(8).map(|b|u64::from_le_bytes(b.try_into().unwrap())).collect()}else{(0..original_rows).collect()};
 if positions.is_empty()||positions.iter().any(|&p|p>=original_rows)||positions.windows(2).any(|p|p[0]>=p[1]){return Err("positions must be nonempty unique ordered original keys".into());}
 let rows=positions.len();
 OpenOptions::new().write(true).create_new(true).open(&args[2])?;
 let index=Index::new(&options(dimension))?;index.reserve(rows)?;
 let mut raw=vec![0;width as usize];let mut vector=vec![0.0f32;dimension];let start=std::time::Instant::now();
 for (position,&original_position) in positions.iter().enumerate() {
  file.seek(std::io::SeekFrom::Start(offset+original_position*width))?;
  file.read_exact(&mut raw)?;
  for (v,b) in vector.iter_mut().zip(raw.chunks_exact(4)) {*v=f32::from_le_bytes(b.try_into()?);if !v.is_finite(){return Err("nonfinite vector".into());}}
  index.add(position as u64,&vector)?;
  if position%100000==0 {eprintln!("rows={} elapsed_s={}",position,start.elapsed().as_secs_f64());}
 }
 index.save(&args[2])?;
 let metadata=Index::metadata(&args[2])?;let viewed=Index::new(&metadata.into())?;viewed.view(&args[2])?;
 if viewed.size()!=rows || viewed.scalar_kind()!=ScalarKind::I8 || viewed.dimensions()!=dimension {return Err("saved contract".into());}
 for key in 0..rows {if !viewed.contains(key as u64){return Err("saved local key missing".into());}}
 println!("{}",serde_json::json!({"rows":rows,"dimension":dimension,"scalar":"i8","metric":"cos","M":16,"expansion_add":256,"expansion_search":2048,"seconds":start.elapsed().as_secs_f64()}));Ok(())
}
