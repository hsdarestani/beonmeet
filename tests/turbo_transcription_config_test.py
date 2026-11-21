#!/usr/bin/env python3
"""Regression for CPU-friendly multilingual STT settings; no recordings are read."""
import ast
from pathlib import Path
source=(Path(__file__).resolve().parents[1]/"app/main.py").read_text()
tree=ast.parse(source)
functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
assert "transcribe_audio_local" in functions
fn=ast.get_source_segment(source,functions["transcribe_audio_local"])
assert 'os.environ.get("WHISPER_MODEL", "large-v3-turbo")' in fn
assert 'os.environ.get("WHISPER_CPU_THREADS", "1")' in fn
assert 'os.environ.get("TRANSCRIPTION_CHUNK_SECONDS", "360")' in fn
assert "beam_size=4" in fn
assert "best_of=2" in fn
assert "condition_on_previous_text=False" in fn
assert "multilingual=True" in fn
assert "language=None" in fn
assert 'compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8")' in fn
assert "num_workers=1" in fn
assert "from faster_whisper import WhisperModel" in fn
assert "return \"\\n\".join(lines).strip(), language_label" in fn
assert "transcribe_audio_recovery_fast" in functions
assert 'os.environ.get("RECOVERY_WHISPER_MODEL", "small")' in ast.get_source_segment(source,functions["transcribe_audio_recovery_fast"])
print("TURBO_MULTILINGUAL_TRANSCRIPTION_CONFIG_TEST_PASS")
