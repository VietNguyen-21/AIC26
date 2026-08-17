"""External ChunkFormer adapter entry point.

The upstream repository and checkpoints remain outside the source-only package.
Configure ``asr.chunkformer_command`` with placeholders ``{audio}``, ``{output}``,
``{checkpoint}``, ``{device}``, ``{language}``, and ``{task}``; the command must
write a JSON list of timed segments. The concrete implementation lives in
:mod:`aic2026.asr`.
"""

from aic2026.asr import ChunkFormerAdapter

__all__ = ["ChunkFormerAdapter"]
