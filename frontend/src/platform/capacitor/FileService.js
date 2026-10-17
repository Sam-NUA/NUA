import { Filesystem, Directory } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';

/** Writes to the app's cache directory, then hands it to the native Share
 * sheet (save to Files, send via email/chat, etc.) — there is no
 * Android/iOS equivalent of a browser's automatic downloads folder. */
export async function downloadFile(blob, filename) {
  const base64 = await blobToBase64(blob);
  const result = await Filesystem.writeFile({
    path: filename,
    data: base64,
    directory: Directory.Cache,
  });
  await Share.share({ title: filename, url: result.uri, dialogTitle: `Save ${filename}` });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(String(reader.result).split(',')[1] || '');
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}
