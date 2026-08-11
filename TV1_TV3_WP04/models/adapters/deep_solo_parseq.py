"""External DeepSolo + PARSeq OCR adapter contract.

The source-only repository does not vendor third-party repositories or model
weights. Configure ``ocr.deep_solo_parseq_command`` with placeholders:
``{image}``, ``{output}``, and ``{checkpoint}``. The command must write a JSON
list containing ``text``, normalized ``bbox`` and optional ``confidence``.

The runtime bridge is implemented in :mod:`aic2026.ocr`.
"""

from aic2026.ocr import DeepSoloParseqAdapter

__all__ = ["DeepSoloParseqAdapter"]
