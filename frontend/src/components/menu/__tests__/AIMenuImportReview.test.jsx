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

it('sends an .xlsx file to preview with fileType xlsx', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockResolvedValueOnce({ data: { count: 1, items: [
    { tempId: 'one', name: 'Flat White', category: 'Coffee', price: 5.5, cost: 2, include: true },
  ] } });
  await upload({ name: 'menu.xlsx', type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', size: 100 });
  expect(menuFeaturesAPI.aiPreviewMenu).toHaveBeenCalledWith({ fileData: 'JVBERi0=', fileType: 'xlsx' });
  expect(host.querySelector('[data-testid="review-stage"]')).not.toBeNull();
});

it('sends a legacy .xls file to preview with fileType xls', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockResolvedValueOnce({ data: { count: 1, items: [
    { tempId: 'one', name: 'Flat White', category: 'Coffee', price: 5.5, cost: 2, include: true },
  ] } });
  await upload({ name: 'menu.xls', type: 'application/vnd.ms-excel', size: 100 });
  expect(menuFeaturesAPI.aiPreviewMenu).toHaveBeenCalledWith({ fileData: 'JVBERi0=', fileType: 'xls' });
});

function textarea() {
  return host.querySelector('[data-testid="menu-text-input"]');
}

// Setting `.value` directly on a controlled React input doesn't trigger its
// onChange — React patches the native value setter to detect a real change,
// so the write has to go through that same setter before the event fires.
async function typeInto(el, value) {
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  await act(async () => {
    setValue.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

it('disables the pasted-text submit button until there is text to send', async () => {
  const submit = host.querySelector('[data-testid="menu-text-submit"]');
  expect(submit.disabled).toBe(true);
  await typeInto(textarea(), 'Flat White - $5.50');
  expect(submit.disabled).toBe(false);
});

it('sends pasted menu text to preview with fileType text', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockResolvedValueOnce({ data: { count: 1, items: [
    { tempId: 'one', name: 'Flat White', category: 'Coffee', price: 5.5, cost: 2, include: true },
  ] } });
  await typeInto(textarea(), 'Flat White - $5.50');
  await act(async () => host.querySelector('[data-testid="menu-text-submit"]').click());
  expect(menuFeaturesAPI.aiPreviewMenu).toHaveBeenCalledWith({ fileData: 'Flat White - $5.50', fileType: 'text' });
  expect(host.querySelector('[data-testid="review-stage"]')).not.toBeNull();
});

it('shows an actionable error when pasted text is too long', async () => {
  menuFeaturesAPI.aiPreviewMenu.mockRejectedValueOnce({ response: { status: 413 } });
  await typeInto(textarea(), 'x');
  await act(async () => host.querySelector('[data-testid="menu-text-submit"]').click());
  expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('too long'));
});
