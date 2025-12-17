import type { AxiosError } from 'axios';

export type ApiErrorData = {
  message?: unknown;
  error?: unknown;
  [key: string]: unknown;
};

export type HttpErrorInfo = {
  status?: number;
  message: string;
  data?: unknown;
};

const asString = (v: unknown): string | null => (typeof v === 'string' ? v : null);

export const getHttpErrorInfo = (err: unknown): HttpErrorInfo => {
  const axiosErr = err as AxiosError<ApiErrorData>;
  const status = axiosErr?.response?.status;
  const data = axiosErr?.response?.data;

  const messageFromData =
    data && typeof data === 'object'
      ? asString((data as ApiErrorData).message) ?? asString((data as ApiErrorData).error)
      : null;

  return {
    status,
    data,
    message: messageFromData ?? asString((axiosErr as unknown as { message?: unknown })?.message) ?? 'Request failed',
  };
};
