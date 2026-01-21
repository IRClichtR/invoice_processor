/**
 * Base HTTP Client for ParseFacture API
 * Handles error handling, logging, and response typing
 */

import { ApiException } from './types';

// Base URL - empty for proxy in development, can be configured for production
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const API_PREFIX = '/api/v1';

// Enable debug logging in development
const DEBUG = import.meta.env.DEV;

function log(message: string, data?: unknown): void {
  if (DEBUG) {
    console.log(`[API] ${message}`, data !== undefined ? data : '');
  }
}

function logError(message: string, error: unknown): void {
  console.error(`[API Error] ${message}`, error);
}

/**
 * Build full URL for API endpoint
 */
export function buildUrl(endpoint: string): string {
  const path = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${API_BASE_URL}${API_PREFIX}${path}`;
}

/**
 * Parse API error response
 */
async function parseError(response: Response): Promise<ApiException> {
  let detail = `Error ${response.status}`;

  try {
    const contentType = response.headers.get('content-type');
    if (contentType?.includes('application/json')) {
      const data = await response.json();
      detail = data.detail || data.message || detail;
    } else {
      const text = await response.text();
      if (text) {
        detail = text;
      }
    }
  } catch {
    // Use default error message
  }

  // User-friendly error messages for common cases
  switch (response.status) {
    case 400:
      if (detail.includes('already exists')) {
        detail = 'A file with this name already exists';
      } else if (detail.includes('Invalid file type')) {
        detail = 'Unsupported file type. Accepted formats: PDF, JPG, PNG, TIFF, WEBP';
      } else if (detail.includes('File size')) {
        detail = 'File is too large (max 20 MB)';
      }
      break;
    case 404:
      detail = 'Resource not found';
      break;
    case 500:
      detail = 'Internal server error. Please try again.';
      break;
    case 503:
      detail = 'Service temporarily unavailable';
      break;
  }

  return new ApiException(response.status, detail);
}

/**
 * Generic fetch wrapper with error handling
 */
export async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = buildUrl(endpoint);

  log(`${options.method || 'GET'} ${url}`);

  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await parseError(response);
      logError(`Request failed: ${endpoint}`, error);
      throw error;
    }

    // Handle no-content responses
    if (response.status === 204) {
      return undefined as T;
    }

    const data = await response.json();
    log(`Response from ${endpoint}:`, data);
    return data as T;
  } catch (error) {
    if (error instanceof ApiException) {
      throw error;
    }

    // Network error or other failure
    logError('Network error', error);
    throw new ApiException(0, 'Connection error. Please check that the backend is running.');
  }
}

/**
 * GET request
 */
export async function apiGet<T>(endpoint: string): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'GET' });
}

/**
 * POST request with JSON body
 */
export async function apiPost<T>(endpoint: string, body?: unknown): Promise<T> {
  return apiFetch<T>(endpoint, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * POST request with FormData (for file uploads)
 */
export async function apiPostForm<T>(endpoint: string, formData: FormData): Promise<T> {
  const url = buildUrl(endpoint);

  log(`POST (form) ${url}`);

  try {
    const response = await fetch(url, {
      method: 'POST',
      body: formData,
      // Don't set Content-Type header - browser will set it with boundary
    });

    if (!response.ok) {
      const error = await parseError(response);
      logError(`Upload failed: ${endpoint}`, error);
      throw error;
    }

    const data = await response.json();
    log(`Response from ${endpoint}:`, data);
    return data as T;
  } catch (error) {
    if (error instanceof ApiException) {
      throw error;
    }

    logError('Upload network error', error);
    throw new ApiException(0, 'Connection error. Please check that the backend is running.');
  }
}

/**
 * PUT request with JSON body
 */
export async function apiPut<T>(endpoint: string, body?: unknown): Promise<T> {
  return apiFetch<T>(endpoint, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
}

/**
 * DELETE request
 */
export async function apiDelete<T = void>(endpoint: string): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'DELETE' });
}
