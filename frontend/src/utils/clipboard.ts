import { toast } from 'react-hot-toast';

export async function copyToClipboard(text: string, promptMessage: string = 'Copy to clipboard:', successMessage?: string): Promise<boolean> {
  // Try Clipboard API first
  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      if (successMessage) toast.success(successMessage);
      return true;
    } catch (err) {
      console.warn('Clipboard API failed, trying fallback', err);
    }
  }

  // Fallback for non-secure contexts or if Clipboard API fails
  try {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    
    // Ensure it's not visible but part of the DOM
    textArea.style.position = 'fixed';
    textArea.style.left = '-9999px';
    textArea.style.top = '0';
    document.body.appendChild(textArea);
    
    textArea.focus();
    textArea.select();
    
    const successful = document.execCommand('copy');
    document.body.removeChild(textArea);
    if (successful) {
      if (successMessage) toast.success(successMessage);
      return true;
    }
  } catch (err) {
    console.error('Fallback copy failed', err);
  }

  // If all else fails, prompt the user
  window.prompt(promptMessage, text);
  return false;
}
