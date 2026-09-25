import { Logger } from 'winston';
import { KnownError } from '../error';
import { getErrorType } from '../util/logger';

const sleep = (ms: number): Promise<void> =>
  new Promise((r) => setTimeout(r, ms));

export class JobStore {
  private runningJobs: number = 0;
  private shutdownRequested: boolean = false;
  private readonly maxConcurrentJobs: number;

  constructor() {
    const configured = Number(process.env.MAX_CONCURRENT_MEETINGS || '8');
    this.maxConcurrentJobs = Number.isFinite(configured) && configured > 0
      ? Math.floor(configured)
      : 8;
    console.log(`Meeting concurrency limit: ${this.maxConcurrentJobs}`);
  }

  async addJob<T>(
    task: () => Promise<T>,
    logger: Logger,
    retryCount: number = 0,
    onPermanentFailure?: (error: unknown) => Promise<void> | void,
    onCompleted?: () => Promise<void> | void
  ): Promise<{ accepted: boolean }> {
    if (this.runningJobs >= this.maxConcurrentJobs || this.shutdownRequested) {
      logger.warn('Meeting concurrency limit reached', {
        runningJobs: this.runningJobs,
        maxConcurrentJobs: this.maxConcurrentJobs,
      });
      return { accepted: false };
    }

    this.runningJobs += 1;

    this.executeTaskWithRetry(task, logger, retryCount).then(async () => {
      logger.info('Meeting job finished successfully.', {
        runningJobs: this.runningJobs,
        maxConcurrentJobs: this.maxConcurrentJobs,
      });
      if (onCompleted) {
        try {
          await onCompleted();
        } catch (completionCallbackError) {
          logger.warn('Meeting completion callback failed', completionCallbackError as any);
        }
      }
    }).catch(async (error) => {
      const errorType = getErrorType(error);
      if (error instanceof KnownError) {
        logger.error('KnownError JobStore is permanently exiting:', { error });
      } else {
        logger.error('Error executing task after multiple retries:', { error });
      }
      logger.error(`Meeting job permanently failed. [errorType: ${errorType}]`);
      if (onPermanentFailure) {
        try {
          await onPermanentFailure(error);
        } catch (failureNotificationError) {
          logger.warn('Meeting failure notification failed', failureNotificationError as any);
        }
      }
    }).finally(() => {
      this.runningJobs = Math.max(0, this.runningJobs - 1);
      logger.info('Meeting slot released', {
        runningJobs: this.runningJobs,
        maxConcurrentJobs: this.maxConcurrentJobs,
      });
    });

    logger.info('Meeting job accepted', {
      runningJobs: this.runningJobs,
      maxConcurrentJobs: this.maxConcurrentJobs,
    });
    return { accepted: true };
  }

  private async executeTaskWithRetry<T>(
    task: () => Promise<T>,
    logger: Logger,
    retryCount: number
  ): Promise<void> {
    try {
      await task();
    } catch (error) {
      if (error instanceof KnownError && !error.retryable) {
        logger.error('KnownError is not retryable:', error.name, error.message);
        throw error;
      }

      if (error instanceof KnownError && error.retryable && (retryCount + 1) >= error.maxRetries) {
        logger.error(`KnownError: ${error.maxRetries} tries consumed:`, error.name, error.message);
        throw error;
      }

      retryCount += 1;
      await sleep(retryCount * 30000);
      if (retryCount < 3) {
        logger.warn(`Retry count: ${retryCount}`);
        await this.executeTaskWithRetry(task, logger, retryCount);
      } else {
        throw error;
      }
    }
  }

  isBusy(): boolean {
    return this.runningJobs >= this.maxConcurrentJobs;
  }

  getStats(): { runningJobs: number; maxConcurrentJobs: number; availableSlots: number } {
    return {
      runningJobs: this.runningJobs,
      maxConcurrentJobs: this.maxConcurrentJobs,
      availableSlots: Math.max(0, this.maxConcurrentJobs - this.runningJobs),
    };
  }

  isShutdownRequested(): boolean {
    return this.shutdownRequested;
  }

  requestShutdown(): void {
    this.shutdownRequested = true;
  }

  async waitForCompletion(): Promise<void> {
    if (this.runningJobs === 0) return;

    console.log(`Waiting for ${this.runningJobs} active meeting job(s) to finish...`);
    return new Promise<void>((resolve) => {
      const checkCompletion = () => {
        if (this.runningJobs === 0) {
          console.log('All meeting jobs completed');
          resolve();
        } else {
          setTimeout(checkCompletion, 1000);
        }
      };
      checkCompletion();
    });
  }
}
