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
    await fs.promises.mkdir(instance.folderPath(), { recursive: true });
    return instance;
  }

  private folderPath(): string {
    return path.join(this.root, this.userId.replace(/[^a-zA-Z0-9_-]/g, '_'));
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

      const controllerUrl = process.env.CONTROLLER_UPLOAD_URL;
      const secret = process.env.INTERNAL_SECRET;
      if (!controllerUrl || !secret) {
        throw new Error('Controller upload configuration is missing');
      }

      const response = await fetch(controllerUrl, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-beonmeet-secret': secret,
        },
        body: JSON.stringify({
          userId: this.userId,
          botId: this.botId,
          meetingLink: this.meetingLink,
          duration: this.recordingDuration,
          filePath,
          filename: `BeOnMeet-${new Date().toISOString().replace(/[:.]/g, '-')}${this.extension}`,
          size: stat.size,
        }),
      });

      if (!response.ok) {
        const body = await response.text();
        throw new Error(`Controller returned ${response.status}: ${body}`);
      }

      try {
        await fs.promises.unlink(filePath);
      } catch {}

      this.logger.info('Recording delivered to BeOnMeet controller', {
        userId: this.userId,
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
