// Copyright 2026 Floriane TUERNAL SABOTINOV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * Logging utility for frontend tracing
 * Provides consistent, structured logging for debugging and monitoring
 */

interface LogContext {
  [key: string]: unknown;
}

const LOG_PREFIX = '[Invoicator]';

// Enable/disable debug logs (can be controlled via localStorage)
const isDebugEnabled = (): boolean => {
  try {
    return localStorage.getItem('invoicator_debug') === 'true';
  } catch {
    return false;
  }
};

function formatContext(context?: LogContext): string {
  if (!context || Object.keys(context).length === 0) return '';
  return ' ' + JSON.stringify(context);
}

function getTimestamp(): string {
  return new Date().toISOString().split('T')[1].slice(0, 12);
}

/**
 * Logger for frontend tracing
 */
export const logger = {
  /**
   * Debug level - only shown when debug mode is enabled
   */
  debug(module: string, message: string, context?: LogContext): void {
    if (isDebugEnabled()) {
      console.debug(
        `%c${LOG_PREFIX} [${getTimestamp()}] [DEBUG] [${module}] ${message}${formatContext(context)}`,
        'color: #6b7280'
      );
    }
  },

  /**
   * Info level - general operational messages
   */
  info(module: string, message: string, context?: LogContext): void {
    console.info(
      `%c${LOG_PREFIX} [${getTimestamp()}] [INFO] [${module}] ${message}${formatContext(context)}`,
      'color: #2563eb'
    );
  },

  /**
   * Warn level - potential issues that don't stop operation
   */
  warn(module: string, message: string, context?: LogContext): void {
    console.warn(
      `${LOG_PREFIX} [${getTimestamp()}] [WARN] [${module}] ${message}${formatContext(context)}`
    );
  },

  /**
   * Error level - errors that affect operation
   */
  error(module: string, message: string, error?: unknown, context?: LogContext): void {
    const errorInfo = error instanceof Error
      ? { errorName: error.name, errorMessage: error.message }
      : error
        ? { error: String(error) }
        : {};

    console.error(
      `${LOG_PREFIX} [${getTimestamp()}] [ERROR] [${module}] ${message}`,
      { ...errorInfo, ...context }
    );
  },

  /**
   * Trace a function execution with timing
   */
  async trace<T>(
    module: string,
    operation: string,
    fn: () => Promise<T>,
    context?: LogContext
  ): Promise<T> {
    const startTime = performance.now();
    logger.debug(module, `Starting: ${operation}`, context);

    try {
      const result = await fn();
      const duration = Math.round(performance.now() - startTime);
      logger.debug(module, `Completed: ${operation}`, { ...context, durationMs: duration });
      return result;
    } catch (error) {
      const duration = Math.round(performance.now() - startTime);
      logger.error(module, `Failed: ${operation}`, error, { ...context, durationMs: duration });
      throw error;
    }
  },

  /**
   * Log a user action
   */
  action(module: string, action: string, context?: LogContext): void {
    console.info(
      `%c${LOG_PREFIX} [${getTimestamp()}] [ACTION] [${module}] ${action}${formatContext(context)}`,
      'color: #059669'
    );
  },

  /**
   * Log a state change
   */
  state(module: string, description: string, context?: LogContext): void {
    console.info(
      `%c${LOG_PREFIX} [${getTimestamp()}] [STATE] [${module}] ${description}${formatContext(context)}`,
      'color: #7c3aed'
    );
  },

  /**
   * Enable debug mode
   */
  enableDebug(): void {
    localStorage.setItem('invoicator_debug', 'true');
    console.info(`${LOG_PREFIX} Debug mode enabled`);
  },

  /**
   * Disable debug mode
   */
  disableDebug(): void {
    localStorage.removeItem('invoicator_debug');
    console.info(`${LOG_PREFIX} Debug mode disabled`);
  }
};

// Expose logger to window for debugging in console
if (typeof window !== 'undefined') {
  (window as any).invoicatorLogger = logger;
}

export default logger;
