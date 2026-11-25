import { Logger } from 'winston';
import fs from 'fs';
import path from 'path';

export interface IUploader {
  uploadRecordingToRemoteStorage(options?: { forceUpload?: boolean }): Promise<boolean>;
  saveDataToTempFile(data: Buffer): Promise<boolean>;
  setRecordingDuration(durationSeconds: number): void;
}

class DiskUploader implements IUploader {
  private readonly userId: string;
  private readonly botId: string;
  private readonly tempFileId: string;
  private readonly logger: Logger;
  private readonly meetingLink?: string;
  private readonly extension: string;
  private readonly root: string;
  private recordingDuration?: number;
  private writeChain: Promise<void> = Promise.resolve();
  private captureNotified = false;
  private readonly filename: string;

  private constructor(
    _token: string,
    _teamId: string,
    _timezone: string,
    userId: string,
    botId: string,
    _namePrefix: string,
    tempFileId: string,
    logger: Logger,
    meetingLink?: string,
  ) {
    this.userId = String(userId);
    this.botId = botId;
    this.tempFileId = tempFileId;
    this.logger = logger;
    this.meetingLink = meetingLink;
    this.extension = process.env.UPLOADER_FILE_EXTENSION || '.webm';
    this.root = process.env.RECORDING_TMP_DIR || '/recordings';
    this.filename = `BeOnMeet-${this.botId.replace(/[^a-zA-Z0-9_-]/g, '_')}-${this.tempFileId.replace(/[^a-zA-Z0-9_-]/g, '_')}${this.extension}`;
  }

  public static async initialize(
    token: string,
    teamId: string,
    timezone: string,
    userId: string,
    botId: string,
    namePrefix: string,
    tempFileId: string,
    logger: Logger,
    meetingLink?: string,
  ) {
    const instance = new DiskUploader(
      token,
      teamId,
      timezone,
      userId,
      botId,
      namePrefix,
      tempFileId,
      logger,
      meetingLink,
    );
    // The controller (UID 999, shared GID 987) creates MP3, MP4 and
    // transcript outputs next to the worker's WebM file. The default 0755
    // mkdir permissions silently break these deliverables and free recordings.
    // Explicit chmod also repairs preexisting 2755 per-user directories.
    await fs.promises.mkdir(instance.folderPath(), { recursive: true, mode: 0o2770 });
    await fs.promises.chmod(instance.folderPath(), 0o2770);
    return instance;
  }

  private folderPath(): string {
    return path.join(this.root, this.userId.replace(/[^a-zA-Z0-9_-]/g, '_'), this.botId.replace(/[^a-zA-Z0-9_-]/g, '_'));
  }

  private filePath(): string {
    return path.join(this.folderPath(), `${this.tempFileId}${this.extension}`);
  }

  public async saveDataToTempFile(data: Buffer): Promise<boolean> {
    const filePath = this.filePath();
    this.writeChain = this.writeChain.then(async () => {
      await fs.promises.appendFile(filePath, data);
    });
    try {
      await this.writeChain;
      if (data.length && !this.captureNotified) {
        this.captureNotified = true;
        const url = process.env.CONTROLLER_RECORDING_STARTED_URL;
        const secret = process.env.INTERNAL_SECRET;
        if (url && secret) {
          // The first nonempty persisted chunk is stronger evidence than
          // calling MediaRecorder.start(). Never let notification stall capture.
          void fetch(url, {
            method: 'POST', headers: { 'content-type': 'application/json', 'x-beonmeet-secret': secret },
            signal: AbortSignal.timeout(10000),
            body: JSON.stringify({ userId: this.userId, botId: this.botId, eventId: this.botId,
              meetingLink: this.meetingLink, captureBytes: data.length }),
          }).then(response => { if (!response.ok) this.captureNotified = false; })
            .catch(() => { this.captureNotified = false; });
        }
      }
      return true;
    } catch (error) {
      this.logger.error('Unable to write recording chunk', { error, filePath });
      return false;
    }
  }

  public setRecordingDuration(durationSeconds: number): void {
    if (Number.isFinite(durationSeconds) && durationSeconds > 0) {
      this.recordingDuration = Math.round(durationSeconds);
    }
  }

  public async uploadRecordingToRemoteStorage(_options?: { forceUpload?: boolean }): Promise<boolean> {
    const filePath = this.filePath();
    try {
      await this.writeChain;
      const stat = await fs.promises.stat(filePath);
      if (!stat.size) throw new Error('Recording is empty');

      const streamControllerUrl = process.env.CONTROLLER_STREAM_UPLOAD_URL;
      const legacyControllerUrl = process.env.CONTROLLER_UPLOAD_URL;
      const secret = process.env.INTERNAL_SECRET;
      if ((!streamControllerUrl && !legacyControllerUrl) || !secret) {
        throw new Error('Controller upload configuration is missing');
      }

      const metadata = {
        userId: this.userId,
        botId: this.botId,
        meetingLink: this.meetingLink,
        duration: this.recordingDuration,
        filename: this.filename,
        size: stat.size,
      };

      // Retry the same identity and source; controller acknowledgement means
      // durable handoff, not that transcription has finished.
      let response: Response | undefined;
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
      if (streamControllerUrl) {
        const encodedMeta = Buffer.from(JSON.stringify(metadata), 'utf8').toString('base64url');
        response = await fetch(streamControllerUrl, {
          method: 'POST',
          headers: {
            'content-type': 'application/octet-stream',
            'content-length': String(stat.size),
            'x-beonmeet-secret': secret,
            'x-beonmeet-meta': encodedMeta,
          },
          body: fs.createReadStream(filePath) as any,
          signal: AbortSignal.timeout(300000),
          duplex: 'half',
        } as any);
      } else {
        response = await fetch(legacyControllerUrl!, {
          method: 'POST',
          headers: {
            'content-type': 'application/json',
            'x-beonmeet-secret': secret,
          },
          body: JSON.stringify({
            ...metadata,
            filePath,
          }),
          signal: AbortSignal.timeout(300000),
        });
      }
          if (response.ok) break;
          if (response.status >= 400 && response.status < 500 && response.status !== 429) break;
        } catch (error) {
          this.logger.warn('Recording handoff attempt failed', { botId: this.botId, attempt });
        }
        if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 1000 * 2 ** attempt));
      }
      if (!response?.ok) throw new Error(`Controller recording handoff failed: ${response?.status || 'network'}`);

      try {
        await fs.promises.unlink(filePath);
      } catch {}

      this.logger.info('Recording delivered to BeOnMeet controller', {
        userId: this.userId,
        botId: this.botId,
        size: stat.size,
      });
      return true;
    } catch (error) {
      this.logger.error('BeOnMeet delivery failed', { error, filePath });
      return false;
    }
  }
}

export default DiskUploader;
