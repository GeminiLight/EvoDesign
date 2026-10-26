/** Enter used to commit IME text must never submit a model request. */
export function shouldSubmitOnEnter(event: {
  key: string;
  shiftKey?: boolean;
  keyCode?: number;
  nativeEvent?: { isComposing?: boolean; keyCode?: number };
}): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.nativeEvent?.isComposing
    && event.keyCode !== 229 && event.nativeEvent?.keyCode !== 229;
}
