import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import AIMenuImportReview from '../AIMenuImportReview';
import { menuFeaturesAPI } from '../../../services/api';
import { toast } from 'sonner';

jest.mock('../../../services/api', () => ({ menuFeaturesAPI: { aiPreviewMenu: jest.fn(), aiCommitMenu: jest.fn() } }));
jest.mock('sonner', () => ({ toast: { error: jest.fn(), success: jest.fn() } }));
jest.mock('../../ui/dialog', () => {
  const Box = ({ children }) => <div>{children}</div>;
  return { Dialog: Box, DialogContent: Box, DialogHeader: Box, DialogTitle: Box, DialogDescription: Box };
});

let host, root, originalReader;
beforeEach(async () => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  jest.clearAllMocks();
  originalReader = global.FileReader;
  global.FileReader = class {
    readAsDataURL() { this.result = 'data:application/pdf;base64,JVBERi0='; this.onload(); }
  };
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => root.render(<AIMenuImportReview open onOpenChange={() => {}} />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  global.FileReader = originalReader;
});

async function upload(file) {
  const input = host.querySelector('input[type="file"]');
  Object.defineProperty(input, 'files', { configurable: true, value: [file] });
  await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })));
  return input;
}

it('rejects oversized files before reading or sending them', async () => {
  await upload({ name: 'large.pdf', type: 'application/pdf', size: 3_000_001 });
  expect(menuFeaturesAPI.aiPreviewMenu).not.toHaveBeenCalled();
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('under 3 MB'));
});

it('sends a PDF to preview and displays returned items for review', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockResolvedValueOnce({ data: { count: 1, items: [
    { tempId: 'one', name: 'Toast', category: 'Food', price: 8, cost: 2, include: true },
  ] } });
  await upload({ name: 'menu.pdf', type: '', size: 100 });
  expect(menuFeaturesAPI.aiPreviewMenu).toHaveBeenCalledWith({ fileData: 'JVBERi0=', fileType: 'pdf' });
  expect(host.querySelector('[data-testid="review-stage"]')).not.toBeNull();
  expect(host.querySelector('[data-testid="row-name-0"]').value).toBe('Toast');
});

it('shows server configuration errors and allows retrying the same file', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockRejectedValueOnce({ response: { status: 503,
    data: { detail: 'Menu reading is not configured.' } } });
  const input = await upload({ name: 'menu.pdf', type: 'application/pdf', size: 100 });
  expect(toast.error).toHaveBeenCalledWith('Menu reading is not configured.');
  expect(input.value).toBe('');
  expect(input.disabled).toBe(false);
});

it('shows an actionable error for a platform payload rejection', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockRejectedValueOnce({ response: { status: 413 } });
  await upload({ name: 'menu.pdf', type: 'application/pdf', size: 100 });
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('under 3 MB'));
});
