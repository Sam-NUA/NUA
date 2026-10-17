import { Clipboard } from '@capacitor/clipboard';

export async function copyText(text) {
  try {
    await Clipboard.write({ string: text });
    return true;
  } catch {
    return false;
  }
}
