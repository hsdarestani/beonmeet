#!/usr/bin/env python3
"""Minimal fail-closed overlay to align current deployed STT with tested Turbo defaults.

Only modifies the primary Whisper function; never touches recording, billing,
Chrome, uploader, Telegram, or the recovery code.
"""
from __future__ import annotations
import ast
from pathlib import Path
import argparse

OLD = {
    'os.environ.get("WHISPER_MODEL", "large-v3")': 'os.environ.get("WHISPER_MODEL", "large-v3-turbo")',
    'cpu_threads=max(1, min(int(os.environ.get("WHISPER_CPU_THREADS", "2")), os.cpu_count() or 2))':
      'cpu_threads=max(1, min(int(os.environ.get("WHISPER_CPU_THREADS", "1")), os.cpu_count() or 1))',
    'os.environ.get("TRANSCRIPTION_CHUNK_SECONDS", "120")':
      'os.environ.get("TRANSCRIPTION_CHUNK_SECONDS", "360")',
    'beam_size=7,\n                best_of=5,\n                patience=1.2,':
      'beam_size=4,\n                best_of=2,\n                patience=1.0,',
    'condition_on_previous_text=True,\n                multilingual=True,':
      'condition_on_previous_text=False,\n                multilingual=True,'
}


def patched_source(source: str) -> str:
    tree=ast.parse(source)
    nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='transcribe_audio_local']
    if len(nodes)!=1: raise ValueError('Unknown transcription function')
    node=nodes[0]
    lines=source.splitlines(keepends=True)
    section=''.join(lines[node.lineno-1:node.end_lineno])
    for old,new in OLD.items():
        if section.count(old)!=1:
            raise ValueError(f'Unsupported/already-upgraded STT source: {old[:50]!r} count={section.count(old)}')
        section=section.replace(old,new,1)
    output=''.join(lines[:node.lineno-1])+section+''.join(lines[node.end_lineno:])
    ast.parse(output)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    if args.source.resolve()==args.destination.resolve(): raise SystemExit('No in-place patching')
    args.destination.write_text(patched_source(args.source.read_text()))
    print('STT_TURBO_OVERLAY_STAGED')
