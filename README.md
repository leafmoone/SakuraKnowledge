# SakuraKnowledge

独立离线知识核心，提供 Python 3.11+ API／CLI 与只读 Rust 运行时。基础结构化和词法查询不需要模型、GPU、服务、ORM 或 SakuraPool。可选语义检索使用显式准备的本地 CPU 模型与来源包；查询不会自动下载、编译或构建索引。

## 仓库内容

- `src/sakura_knowledge/`：Python 数据构建、查询、来源与身份逻辑。
- `rust/`：Rust CLI、模块化来源发现、语义与 resident 运行时。
- `scripts/sknow.ps1`：Windows 原生启动器。
- `configs/`：正式配置示例与运行时兼容合同。
- `tools/`：产品所需的来源包构建、文本投影与组件组装工具。
- `docs/`：正式数据、运行时和来源包文档及第三方许可证。
- `skills/sakura-knowledge/`：离线查询 Skill。
- `vendor/usearch-2.26.2/`：原生运行时所需的 vendored USearch 源码和许可证。

构建产物、知识库、模型、索引、开发测试、报告、日志和任务上下文不纳入 Git。规则见 `AGENTS.md`。

## Python 安装与使用

```text
python -m pip install .
sknow inspect data/manifest.json
sknow build data/manifest.json data/new-snapshot
sknow verify data/new-snapshot/knowledge.sqlite
sknow lookup data/knowledge.sqlite 初音未来 --kind character --namespace moegirl.character
sknow search data/knowledge.sqlite 中文 --limit 20
sknow related data/knowledge.sqlite 1 --kind character --namespace bangumi.character --relation character_of --limit 20
sknow ask data/knowledge.sqlite "孤独摇滚 的 Danbooru tag 是什么"
```

查询只读、离线。`sources check` 是明确选择的网络元数据操作，不等于下载或刷新知识库。Windows 重定向非 ASCII JSON 时使用 UTF-8 环境，例如设置 `PYTHONIOENCODING=utf-8`。

## Rust 原生运行时

使用本机已有 Rust 和原生 C/C++ 工具链，不假定工具链安装在哪个盘符或用户目录：

```text
cargo build --release --manifest-path rust/Cargo.toml
cargo build --release --manifest-path rust/Cargo.toml --features semantic --bin sknow-rs --bin semantic_pilot
```

从源码构建的程序在 `rust/target/release/`，可通过 Cargo 配置相对 target 目录。部署时把程序及所需运行时共享库放入 `bin/`。语义功能支持 Windows 和 Linux CPU，另需匹配的本地 BGE-M3／ONNX Runtime 1.24.1、mapping 和 ANN 资产，Git 不包含这些二进制文件。程序与资产必须一起按配置部署，不能依赖编译机器目录。

Linux 直接运行 `bin/sknow-rs --config sknow-config.json retrieve 'blue hair' --source danbooru --limit 5`；常驻入口为 `bin/semantic_pilot --config sknow-config.json`。共享模型 manifest 的 `ort_libraries` 按平台绑定包内运行时，示例见 [运行时绑定](configs/shared-model-runtime.example.json) 和 [部署合同](docs/runtime-contract.md#platform-runtime-binding)。官方 Linux x64 发行包中的实际文件 `libonnxruntime.so.1.24.1` 应复制为包内普通文件（如 `bin/libonnxruntime.so`），不要复制符号链接。已有 Windows manifest 的 `ort_dll` 仍兼容；Linux 必须提供自己的绑定，不能使用 Windows DLL 的摘要。

优先使用已有的 BGE-M3 自定义导出与对应 manifest。需要从官方固定版本 ONNX 准备模型时，可显式运行下列离线工具（仅准备阶段需要 `onnx==1.20.1`）：

```text
python -m tools.prepare_bge_model --onnx-directory assets/bge-m3/onnx --tokenizer assets/bge-m3/tokenizer.json --output model/bge-m3 --ort-library linux-x86_64=bin/libonnxruntime.so
```

输入须来自 `BAAI/bge-m3` 的固定版本 `5617a9f61b028005a4858fdac845db406aefb181`；tokenizer 使用仓库根目录版本。官方 `sentence_embedding` 已完成 CLS 与 L2 归一化，工具只选择该输出并改名为 `embeddings`，不会再次池化、归一化或重建索引。新 manifest 记录实际派生文件的摘要，不冒称它与历史自定义导出字节相同；原模型、来源包和索引保持不变。

## 模块化布局

```text
project/
  sknow-config.json
  bin/
  packs/
    source-a/manifest.json
    source-b/manifest.json
  model/bge-m3/manifest.json
```

复制 `configs/sknow-config.example.json` 到项目根目录的 `sknow-config.json`，放入预先准备好的 Core、来源包和可选共享模型。启动脚本在仓库内使用 `scripts/sknow.ps1`；在已组装可移动包内使用根目录 `sknow.ps1`。

```powershell
./scripts/sknow.ps1 packs
./scripts/sknow.ps1 lookup '初音未来' --key --kind character --namespace moegirl.character --source moegirl
./scripts/sknow.ps1 search 'blue_hair' --source tag-wiki
./scripts/sknow.ps1 related '初音未来' --kind character --namespace moegirl.character --direction in
./scripts/sknow.ps1 resolve-tag '初音未来' --target-namespace danbooru.tag
./scripts/sknow.ps1 retrieve 'blue hair' --source danbooru,bangumi --limit 5
'{"case_id":"one","query":"blue hair","limit":5}' | powershell -NoProfile -File ./scripts/sknow.ps1 serve
```

`packs/*/manifest.json` 决定安装来源；删除来源目录后重启即可卸载。`--source` 支持重复参数或逗号分隔，省略时选择全部已安装来源，空成员及未知来源报错。`related` 支持 `in/out`，`resolve-tag` 支持 `--target-namespace`／`--target-tag-namespace`，冲突值与不适用参数均拒绝。基础查询不打开模型；缺少语义资产时明确失败，不自动下载或替代。

单体配置使用 `bin`、`database`、`manifest` 三个包内相对路径；未配置时启动器默认读取 `bin/`、`data/knowledge.sqlite` 和 `data/manifest.json`。旧 full-pack 合同保留历史相对路径身份以兼容 manifest，但不使用编译时机器位置；旧包若引用外部机器 DLL，须重新配置为项目内相对资源。已生成的外部发行目录不会被源码更新自动重打包。

## 响应与身份边界

- `(kind, namespace, value)` 是完整身份；相同拼写、标题、分数或候选映射不证明身份。
- 身份信任来自 `source_backed`。生成文本只能支持已有可信身份下的文本检索，不能创建身份或 verified 映射。
- 本地聚合标签不是原生 `danbooru.tag`。证据不足时返回 `unknown`、`ambiguous` 或 `target_unmapped`，不猜测标签、人物关联或 `character_of`。
- 公开文本与来源／证据／引用闭包只保留最终 Top-K 及独立 trusted-pin 所需证明。同一身份可保留多文档，数字文档 ID 以 pack 为界；内部候选池、RRF 与最终排序不因输出裁剪改变。
- JSONL 响应上限为 **2 MiB UTF-8，包含 newline**。超限返回明确 FAIL，不截断 PASS。
- Resident 每次加载一个模型 session，完成一行输入后执行同一五秒 absolute deadline，覆盖解析、检索、序列化、write、flush 和 profiling。冷启动、opened event 与等待／传输输入行不计入请求预算。
- 显式可恢复请求错误返回一条完整 FAIL 后继续，合法 `case_id` 原样回传，不可靠 ID 为 `null`，不自动 retry 或重载。内部不安全状态和 I/O 失败 fatal；运行期 fatal 退出1，deadline／阻塞输出退出124，无无保护的二次打印或 stdio 清理。
- OS 调度不是硬实时保证。fatal 不保证完整响应交付；完整 frame 后发生 fatal 也不能当作完成交付。

检索相关性不等于身份验证。现有已准备资产的 **QUALITY_FAIL** 和再分发权利 **NOT_CLEARED** 不因代码整理改变。母库是历史快照，不会自动同步独立包更新；真实 Pi／SakuraTool／Pool 集成与完整人工事实审查未执行时不得宣称完成。

## 来源包工具与正式文档

新增来源使用显式 `SourceAdapter`，不要求修改 Core 或母库。通用工具：`tools.normalized_source`、`tools.generic_semantic`、`tools.source_pack`、`tools.modular_components`。准备工作与查询分离，输出使用新目录。

`tools.generic_semantic`（可选 `--batch-size 4`）按文档投影、按批编码，通过磁盘向量流生成 NPY；编码阶段除模型外的额外内存由最大单文档投影和批大小决定，不再保留整个语料的 chunks／向量；后续 ANN 构建仍需索引所需内存。默认批大小为 1，保持逐条编码；较大的批适合同长度工作负载，长度差异过大时补齐开销可能使编码更慢。该值写入 workspace 输入绑定，`--resume-workspace` 须使用相同值。BGE-M3 的 1024 维、CLS+L2、512 token 上限不变，批内使用 tokenizer 的 `<pad>=1` 右侧补齐及真实 attention mask。新输出在目标同卷暂存目录完成完整验证后，以原子、禁止覆盖方式发布；已有索引不会自动重建。

向量直接流式写入标准 NPY，编码结束后原位补全行数，不再生成或复制 `vectors.f32`。完整 NPY 与 mapping 的绑定写入原子 `encoded` 检查点后，ANN 构建失败可通过 `--resume-workspace` 重试，无需重新编码。恢复仍校验来源、模型、批大小及产物摘要；未完成编码或损坏的工作区不能恢复，旧 `ready` 工作区继续兼容。该检查点不提供编码中途续跑或断电持久性保证。

- [数据合同](docs/data-contract.md)
- [运行时合同](docs/runtime-contract.md)
- [来源包合同](docs/source-pack-contract.md)
- [新增来源](docs/adding-a-source.md)
- [来源适配边界](docs/source-adapters.md)
- [tag-wiki 文本来源证明](docs/tag-wiki-provenance.md)
- [架构](docs/architecture.md)

只做与当前变更直接相关的轻量检查，不机械重跑完整矩阵或重复哈希大型资产。开发过程测试与日志放在被忽略的本地工作目录，不提交到产品仓库。
