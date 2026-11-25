#!/usr/bin/env python3
"""Versioned patch for the exact deployed CommonJS DiskUploader."""
from pathlib import Path
import argparse

MARKER = 'BEONMEET_DURABLE_HANDOFF_V1'
PERMISSION_OLD = '        await fs_1.default.promises.mkdir(instance.folderPath(), { recursive: true });'
PERMISSION_NEW = """        await fs_1.default.promises.mkdir(instance.folderPath(), { recursive: true, mode: 0o2770 });
        await fs_1.default.promises.chmod(instance.folderPath(), 0o2770);"""
INIT = '        this.writeChain = Promise.resolve();'
INIT_NEW = f'        // {MARKER}\n{INIT}\n        this.handoffAccepted = false;'
FOLDER = "        return path_1.default.join(this.root, this.userId.replace(/[^a-zA-Z0-9_-]/g, '_'));"
FOLDER_NEW = "        return path_1.default.join(this.root, this.userId.replace(/[^a-zA-Z0-9_-]/g, '_'), String(this.botId).replace(/[^a-zA-Z0-9_-]/g, '_'));"
FILE = '        return path_1.default.join(this.folderPath(), `${this.tempFileId}${this.extension}`);'
FILE_NEW = "        return path_1.default.join(this.folderPath(), `${String(this.tempFileId).replace(/[^a-zA-Z0-9_-]/g, '_')}${this.extension}`);"
UPLOAD = '    async uploadRecordingToRemoteStorage(_options) {'
UPLOAD_NEW = UPLOAD + '\n        if (this.handoffAccepted) return true;'
FILENAME = "                filename: `BeOnMeet-${new Date().toISOString().replace(/[:.]/g, '-')}${this.extension}`,"
FILENAME_NEW = "                filename: `BeOnMeet-${String(this.botId).replace(/[^a-zA-Z0-9_-]/g, '_')}-${String(this.tempFileId).replace(/[^a-zA-Z0-9_-]/g, '_')}${this.extension}`,"
SEND_START = '            let response;'
SEND_END = "            try {\n                await fs_1.default.promises.unlink(filePath);"
SEND_NEW = """            let accepted = false;
            for (let attempt = 0; attempt < 4; attempt++) {
                try {
                    let response;
                    if (streamControllerUrl) {
                        const encodedMeta = Buffer.from(JSON.stringify(metadata), 'utf8').toString('base64url');
                        response = await fetch(streamControllerUrl, {
                            method: 'POST', headers: { 'content-type': 'application/octet-stream', 'content-length': String(stat.size), 'x-beonmeet-secret': secret, 'x-beonmeet-meta': encodedMeta },
                            body: fs_1.default.createReadStream(filePath), duplex: 'half', signal: AbortSignal.timeout(300000)
                        });
                    } else {
                        response = await fetch(legacyControllerUrl, {
                            method: 'POST', headers: { 'content-type': 'application/json', 'x-beonmeet-secret': secret },
                            body: JSON.stringify({ ...metadata, filePath }), signal: AbortSignal.timeout(300000)
                        });
                    }
                    if (response.ok) {
                        const receipt = await response.json();
                        if (receipt.ok && (receipt.persisted || receipt.duplicate)) {
                            accepted = true;
                            break;
                        }
                        throw new Error('Controller did not acknowledge durable handoff');
                    }
                    if (response.status >= 400 && response.status < 500 && response.status !== 429) break;
                } catch (error) {
                    this.logger.warn('Recording handoff attempt failed', { botId: this.botId, attempt });
                }
                if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 1000 * 2 ** attempt));
            }
            if (!accepted) throw new Error('Recording durable handoff failed; source retained');
            this.handoffAccepted = true;
"""


def patched_source(source: str) -> str:
    if MARKER in source:
        raise ValueError('Already patched')
    if source.count(PERMISSION_OLD) == 1:
        source = source.replace(PERMISSION_OLD, PERMISSION_NEW, 1)
    elif source.count(PERMISSION_NEW) != 1:
        raise ValueError('Unexpected uploader folder permissions')
    for old, new in ((INIT, INIT_NEW), (FOLDER, FOLDER_NEW), (FILE, FILE_NEW), (UPLOAD, UPLOAD_NEW), (FILENAME, FILENAME_NEW)):
        if source.count(old) != 1:
            raise ValueError('Unexpected uploader anchor: ' + old)
        source = source.replace(old, new, 1)
    if source.count(SEND_START) != 1 or source.count(SEND_END) != 1:
        raise ValueError('Unexpected upload callback layout')
    start = source.index(SEND_START)
    end = source.index(SEND_END, start)
    return source[:start] + SEND_NEW + source[end:]


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args=parser.parse_args()
    if args.source.resolve()==args.destination.resolve():
        raise SystemExit('Refusing in-place modification')
    args.destination.write_text(patched_source(args.source.read_text(encoding='utf-8')), encoding='utf-8')
    print('COMPILED_UPLOADER_DURABLE_HANDOFF_STAGED')
