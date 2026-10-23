"""Fixed Google text-tower CUDA document encoder; no tokenizer or corpus pipeline."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from tools.model_artifacts import ArtifactBinding, verified_model
from tools.prepare_embeddinggemma2_model import REFERENCE_REVISION, TOKENIZER
from tools.source_pack import binding

if TYPE_CHECKING:
    import numpy as np
    import torch
    from numpy.typing import NDArray

TRANSFORMERS_VERSION = '5.20.2'
GOOGLE_FILES = {
    'config.json': {'size': 4455, 'sha256': 'b8f1e9931b57fbc054acdb445c41765d55b0074c58d145fa82839941ad1b5bb3'},
    'model.safetensors': {'size': 1488915288, 'sha256': '197a32965d4b1105faf060417baa899e193fb73cd401f42ec9295234d5553d79'},
}


def google_artifacts(directory: Path) -> dict[str, ArtifactBinding]:
    """Bind the fixed original checkpoint once, not once per source or batch."""
    files = {}
    for name, expected in GOOGLE_FILES.items():
        item = binding(directory / name)
        if {k: item[k] for k in ('size', 'sha256')} != expected:
            raise ValueError(f'fixed Google checkpoint binding mismatch: {name}')
        files[name] = item
    return files


def load_text_model(directory: Path, device: str) -> torch.nn.Module:
    """Use native Transformers tensor forward, including no-media PAD substitution."""
    import torch
    import transformers
    if transformers.__version__ != TRANSFORMERS_VERSION:
        raise ValueError(f'Gemma build requires transformers=={TRANSFORMERS_VERSION}; found {transformers.__version__}')
    config = transformers.AutoConfig.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False,
        vision_config=None, audio_config=None)
    model = transformers.AutoModel.from_pretrained(
        directory, config=config, local_files_only=True, trust_remote_code=False,
        dtype=torch.float32, attn_implementation='eager', use_safetensors=True)
    return model.to(device=device, dtype=torch.float32).eval().requires_grad_(False)


def mean_embeddings(model: torch.nn.Module, inputs: dict[str, NDArray[np.int64]]) -> NDArray[np.float32]:
    """Mask-aware mean includes the prompt and special tokens, then L2-normalizes."""
    import torch
    device = next(model.parameters()).device
    tensors = {name: torch.from_numpy(value).to(device) for name, value in inputs.items()}
    with torch.inference_mode(), torch.autocast(device_type=device.type, enabled=False):
        hidden = model(**tensors).last_hidden_state
        mask = tensors['attention_mask'].unsqueeze(-1).to(hidden.dtype)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
        return torch.nn.functional.normalize(pooled, p=2, dim=1).cpu().numpy()


class GemmaCudaEncoder:
    """Own one verified, lazy-loaded GPU model across serial source builds."""

    def __init__(self, prepared: Path, original: Path, device: str):
        import torch
        import transformers
        import tokenizers
        parsed = torch.device(device)
        if parsed.type != 'cuda' or parsed.index is None:
            raise ValueError('explicit CUDA device required, for example cuda:0')
        if not torch.cuda.is_available() or parsed.index >= torch.cuda.device_count():
            raise ValueError(f'CUDA device unavailable: {device}; CPU fallback is disabled')
        if transformers.__version__ != TRANSFORMERS_VERSION:
            raise ValueError(f'Gemma build requires transformers=={TRANSFORMERS_VERSION}; found {transformers.__version__}')
        self.prepared = prepared.resolve()
        self.original = original.resolve()
        self.contract = verified_model(self.prepared)
        token = self.contract['artifacts']['tokenizer']
        if (self.contract['model_id'] != 'embeddinggemma-2'
                or {k: token[k] for k in ('size', 'sha256')} != TOKENIZER):
            raise ValueError('CUDA build requires the fixed prepared Gemma model/tokenizer')
        files = google_artifacts(self.original)
        self.manifest_binding = binding(self.prepared / 'manifest.json')
        # Keep FP32 arithmetic explicit; do not inherit TF32 or autocast settings.
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision('highest')
        self.device = str(parsed)
        properties = torch.cuda.get_device_properties(parsed)
        self.provenance = {
            'backend': 'torch-cuda', 'repository': 'google/embeddinggemma-2',
            'revision': REFERENCE_REVISION, 'artifacts': files,
            'torch': torch.__version__, 'transformers': transformers.__version__,
            'tokenizers': tokenizers.__version__,
            'cuda': torch.version.cuda, 'device': self.device, 'device_name': properties.name,
            'device_memory_bytes': properties.total_memory,
            'dtype': 'float32', 'tf32': False, 'attention': 'eager',
            'pooling': 'attention_mask_mean', 'normalize': True,
        }
        self.model: torch.nn.Module | None = None
        self.rows = 0
        self.seconds = 0.0
        self.load_seconds = 0.0

    def begin_source(self) -> None:
        import torch
        self.rows = 0
        self.seconds = 0.0
        torch.cuda.reset_peak_memory_stats(self.device)

    def encode(self, inputs: dict[str, NDArray[np.int64]]) -> NDArray[np.float32]:
        if self.model is None:
            start = perf_counter()
            self.model = load_text_model(self.original, self.device)
            self.load_seconds = perf_counter() - start
        start = perf_counter()
        vectors = mean_embeddings(self.model, inputs)
        self.seconds += perf_counter() - start
        self.rows += len(vectors)
        return vectors

    def statistics(self) -> dict[str, int | float | None]:
        import torch
        return {'encoded_rows': self.rows, 'encoding_seconds': self.seconds,
                'rows_per_second': self.rows / self.seconds if self.seconds else None,
                'model_load_seconds': self.load_seconds,
                'peak_device_allocated_bytes': torch.cuda.max_memory_allocated(self.device)}

    def close(self) -> None:
        import torch
        self.model = None
        with torch.cuda.device(self.device):
            torch.cuda.empty_cache()
